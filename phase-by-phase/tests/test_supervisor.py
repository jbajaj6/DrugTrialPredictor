"""Failure injection for the persistent supervisor; no Codex model call."""

import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "supervisor", Path(__file__).parents[1] / "harness" / "supervisor.py"
)
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)


def usage(used=80, now=1_800_000_000):
    return {"rateLimitsByLimitId": {"codex": {
        "limitId": "codex", "primary": {"usedPercent": 4, "windowDurationMins": 300,
                                         "resetsAt": now + 100},
        "secondary": {"usedPercent": used, "windowDurationMins": 10080,
                      "resetsAt": now + 1000}}}}


def task(db, name="A", *, kind="structured", deps=None):
    supervisor.add_task(db, task_id=name, kind=kind, prompt="Do one bounded thing",
                        model="gpt-6.1-sol", max_seconds=60,
                        projected_percent=2, dependencies=deps)


def test_usage_window_and_reserves(monkeypatch):
    now = 1_800_000_000
    parsed = supervisor.parse_weekly_usage(usage(now=now), now=now)
    assert parsed["used_percent"] == 80
    monkeypatch.setattr(supervisor.time, "time", lambda: now)
    supervisor.check_reserve(parsed, reserve_percent=7, projected_percent=2)
    supervisor.check_reserve(parsed, reserve_percent=5, projected_percent=2)
    with pytest.raises(supervisor.GateError, match="reserve"):
        supervisor.check_reserve(supervisor.parse_weekly_usage(usage(used=94, now=now), now=now),
                                 reserve_percent=5, projected_percent=2)
    supervisor.check_reserve(supervisor.parse_weekly_usage(usage(used=87, now=now), now=now),
                             reserve_percent=10, projected_percent=2)
    with pytest.raises(supervisor.GateError, match="reserve"):
        supervisor.check_reserve(supervisor.parse_weekly_usage(usage(used=89, now=now), now=now),
                                 reserve_percent=10, projected_percent=2)
    with pytest.raises(supervisor.GateError, match="stale"):
        supervisor.check_reserve({**parsed, "checked_at": now - 61},
                                 reserve_percent=5, projected_percent=2)
    with pytest.raises(supervisor.GateError):
        supervisor.parse_weekly_usage({"rateLimits": {"limitId": "codex",
                                       "primary": {"windowDurationMins": 300}}}, now=now)
    contradictory = usage(now=now)
    contradictory["rateLimits"] = {"limitId": "codex", "secondary": {
        "usedPercent": 50, "windowDurationMins": 10080, "resetsAt": now + 1000}}
    with pytest.raises(supervisor.GateError, match="contradictory"):
        supervisor.parse_weekly_usage(contradictory, now=now)


def test_duplicate_dependency_science_gate_and_dry_run(tmp_path):
    db = supervisor.connect(tmp_path / "state.sqlite")
    task(db)
    with pytest.raises(supervisor.GateError, match="duplicate"):
        task(db)
    task(db, "B", kind="text", deps=["A"])
    with pytest.raises(supervisor.GateError, match="dependencies"):
        supervisor.run_task(db, "B", "initial", tmp_path / "b.jsonl", dry_run=True)
    assert supervisor.run_task(db, "A", "initial", tmp_path / "a.jsonl", dry_run=True)["dry_run"]
    assert not (tmp_path / "a.jsonl").exists()
    assert not db.execute("SELECT 1 FROM attempts").fetchone()


def test_restart_failed_command_evaluator_and_repair_history(tmp_path):
    path = tmp_path / "state.sqlite"
    db = supervisor.connect(path)
    task(db)
    _, first = supervisor.prepare_attempt(db, "A", "first", tmp_path / "first.jsonl")
    db.close()
    db = supervisor.connect(path)
    assert supervisor.recover(db) == 1
    assert supervisor.recover(db) == 0
    with pytest.raises(supervisor.GateError, match="not launchable"):
        supervisor.prepare_attempt(db, "A", "new strategy", tmp_path / "blocked.jsonl")
    inspection = tmp_path / "process-inspection.txt"
    inspection.write_text("No orphaned Codex child remains; workspace reviewed.")
    supervisor.acknowledge_interruption(db, "A", inspection)
    with pytest.raises(supervisor.GateError, match="unchanged"):
        supervisor.prepare_attempt(db, "A", "first", tmp_path / "other.jsonl")
    _, second = supervisor.prepare_attempt(db, "A", "targeted fix", tmp_path / "second.jsonl")
    supervisor.finish_attempt(db, second, 1, "failed command")
    assert db.execute("SELECT status FROM attempts WHERE id=?", (second,)).fetchone()[0] == "failed"
    _, third = supervisor.prepare_attempt(db, "A", "second fix", tmp_path / "third.jsonl")
    supervisor.finish_attempt(db, third, 0)
    evidence = tmp_path / "eval.txt"
    evidence.write_text("Independent evaluator: rejected because gate failed.")
    with pytest.raises(supervisor.GateError):
        supervisor.evaluate(db, "A", third, "builder", "accept", evidence)
    supervisor.evaluate(db, "A", third, "evaluator", "reject", evidence)
    _, fourth = supervisor.prepare_attempt(db, "A", "third fix", tmp_path / "fourth.jsonl")
    supervisor.finish_attempt(db, fourth, 0)
    with pytest.raises(supervisor.GateError, match="not launchable"):
        supervisor.prepare_attempt(db, "A", "fifth", tmp_path / "fifth.jsonl")
    evidence.write_text("Independent evaluator: all required checks passed.")
    supervisor.evaluate(db, "A", fourth, "evaluator", "accept", evidence)
    report = supervisor.handoff(db)
    assert report["tasks"][0]["status"] == "accepted"
    assert [a["status"] for a in report["attempts"]] == [
        "interrupted", "failed", "rejected", "accepted"]
    assert first != second


def test_failed_launch_is_durable_and_no_secret_in_handoff(tmp_path, monkeypatch):
    db = supervisor.connect(tmp_path / "state.sqlite")
    task(db)
    monkeypatch.setattr(supervisor, "check_cli_preflight", lambda *_: None)
    def known_usage(_codex):
        return {"used_percent": 60, "resets_at": supervisor.time.time() + 1000,
                "window_minutes": 10080, "checked_at": supervisor.time.time()}
    result = supervisor.run_task(db, "A", "missing executable", tmp_path / "out.jsonl",
                                 codex=str(tmp_path / "nonexistent-codex"), usage_reader=known_usage)
    assert result["exit_code"] != 0
    assert db.execute("SELECT status FROM tasks WHERE id='A'").fetchone()[0] == "failed"
    assert "OPENAI_API_KEY" not in json.dumps(supervisor.handoff(db))


def test_turn_completion_marker(tmp_path):
    output = tmp_path / "events.jsonl"
    output.write_text('{"type":"turn.completed"}\n')
    assert supervisor.completed_turn(output)
    output.write_text('{"type":"turn.completed"}\n{"type":"turn.failed"}\n')
    assert not supervisor.completed_turn(output)
    output.write_text('{"type":"turn.completed"}\nnot json\n')
    assert not supervisor.completed_turn(output)


def test_live_catalog_preflight(monkeypatch):
    class Result:
        def __init__(self, code, out):
            self.returncode, self.stdout, self.stderr = code, out, ""
    def fake_run(command, **_kwargs):
        if command[1:3] == ["login", "status"]:
            return Result(0, "Logged in using ChatGPT")
        return Result(0, json.dumps({"models": [{"slug": "gpt-6.1-sol", "supported_reasoning_levels": [{"effort": "high"}]}]}))
    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)
    supervisor.check_cli_preflight("codex", "gpt-6.1-sol")
    supervisor.check_cli_preflight("codex", "gpt-6.1-sol", "high")
    with pytest.raises(supervisor.GateError, match="unsupported"):
        supervisor.check_cli_preflight("codex", "gpt-6.1-sol", "ultra")
    with pytest.raises(supervisor.GateError, match="absent"):
        supervisor.check_cli_preflight("codex", "gpt-6.2-sol")
    monkeypatch.setattr(supervisor.subprocess, "run", lambda *_args, **_kwargs: Result(0, "Logged in using API key"))
    with pytest.raises(supervisor.GateError, match="ChatGPT-plan"):
        supervisor.check_cli_preflight("codex", "gpt-6.1-sol")


def test_scientific_readiness_requires_explicit_evidence(tmp_path):
    db = supervisor.connect(tmp_path / "state.sqlite")
    task(db, "STRUCTURED_READY")
    _, attempt = supervisor.prepare_attempt(db, "STRUCTURED_READY", "readiness audit", tmp_path / "audit.jsonl")
    supervisor.finish_attempt(db, attempt, 0)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"engineering_pass": True}))
    with pytest.raises(supervisor.GateError, match="scientific readiness"):
        supervisor.evaluate(db, "STRUCTURED_READY", attempt, "evaluator", "accept", evidence)
    evidence.write_text(json.dumps({"scientific_readiness": True, "evidence": "independent dated-data audit"}))
    supervisor.evaluate(db, "STRUCTURED_READY", attempt, "evaluator", "accept", evidence)
    task(db, "TEXT", kind="text", deps=["STRUCTURED_READY"])
    assert supervisor.run_task(db, "TEXT", "first", tmp_path / "text.jsonl", dry_run=True)["dry_run"]


def test_ctrl_c_kills_child_and_requires_orphan_review(tmp_path, monkeypatch):
    db = supervisor.connect(tmp_path / "state.sqlite")
    task(db)
    monkeypatch.setattr(supervisor, "check_cli_preflight", lambda *_: None)
    launched = {}
    class InterruptedChild:
        pid = 12345
        def __init__(self, _command, **kwargs):
            launched.update(kwargs)
        def poll(self):
            raise KeyboardInterrupt
        def wait(self, **_kwargs):
            return -9
    monkeypatch.setattr(supervisor.subprocess, "Popen", InterruptedChild)
    killed = []
    monkeypatch.setattr(supervisor.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    def known_usage(_codex):
        return {"used_percent": 60, "resets_at": supervisor.time.time() + 1000,
                "window_minutes": 10080, "checked_at": supervisor.time.time()}
    with pytest.raises(KeyboardInterrupt):
        supervisor.run_task(db, "A", "initial", tmp_path / "out.jsonl", usage_reader=known_usage)
    assert launched["cwd"] == supervisor.PROJECT_ROOT
    assert launched["start_new_session"] is True
    assert killed and killed[0][0] == 12345
    assert db.execute("SELECT process_group_id FROM attempts WHERE task_id='A'").fetchone()[0] == 12345
    assert db.execute("SELECT status FROM tasks WHERE id='A'").fetchone()[0] == "interrupted_unreviewed"
    with pytest.raises(supervisor.GateError, match="not launchable"):
        supervisor.prepare_attempt(db, "A", "new strategy", tmp_path / "next.jsonl")
