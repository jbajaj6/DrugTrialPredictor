"""Small, fail-closed supervisor for bounded, human-specified Codex tasks.

No session is launched by importing this module or by ``status``/``handoff``.
The database is the authority; Codex prose is never accepted as evaluation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


WEEK_MINUTES = 10_080
MAX_ATTEMPTS = 4  # initial attempt and at most three targeted repairs
APP_SERVER_DOC = "https://learn.chatgpt.com/docs/app-server"
CLI_DOC = "https://learn.chatgpt.com/docs/non-interactive-mode"
CLI_REFERENCE = "https://learn.chatgpt.com/docs/cli/reference"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GateError(RuntimeError):
    pass


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, prompt TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', model TEXT NOT NULL,
            reasoning_effort TEXT, max_seconds INTEGER NOT NULL, projected_percent REAL NOT NULL,
            accepted_at REAL
        );
        CREATE TABLE IF NOT EXISTS dependencies (
            task_id TEXT NOT NULL REFERENCES tasks(id),
            depends_on TEXT NOT NULL REFERENCES tasks(id),
            PRIMARY KEY(task_id, depends_on), CHECK(task_id != depends_on)
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
            number INTEGER NOT NULL, strategy TEXT NOT NULL, status TEXT NOT NULL,
            started_at REAL NOT NULL, ended_at REAL, exit_code INTEGER,
            process_group_id INTEGER,
            output_path TEXT NOT NULL, failure TEXT,
            UNIQUE(task_id, number), UNIQUE(task_id, strategy)
        );
        CREATE TABLE IF NOT EXISTS evaluations (
            task_id TEXT NOT NULL REFERENCES tasks(id), attempt_id INTEGER NOT NULL REFERENCES attempts(id),
            evaluator TEXT NOT NULL, verdict TEXT NOT NULL, evidence_path TEXT NOT NULL,
            created_at REAL NOT NULL, PRIMARY KEY(task_id, attempt_id)
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, at REAL NOT NULL, task_id TEXT,
            event TEXT NOT NULL, detail TEXT NOT NULL
        );
    """)
    return db


def event(db: sqlite3.Connection, task: str | None, name: str, detail: str = "") -> None:
    db.execute("INSERT INTO events(at,task_id,event,detail) VALUES(?,?,?,?)",
               (time.time(), task, name, detail))


def add_task(db: sqlite3.Connection, *, task_id: str, kind: str, prompt: str,
             model: str, max_seconds: int, projected_percent: float,
             dependencies: list[str] | None = None,
             reasoning_effort: str | None = None) -> None:
    if not task_id or not prompt or not model or kind not in {"structured", "text", "memo"}:
        raise GateError("task id, kind, prompt, and model are required")
    if not 1 <= max_seconds <= 3600 or not 0 < projected_percent <= 100:
        raise GateError("bounded duration and positive projected usage are required")
    if reasoning_effort is not None and reasoning_effort not in {"low", "medium", "high", "xhigh", "max", "ultra"}:
        raise GateError("invalid reasoning effort")
    dependencies = dependencies or []
    with db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
            raise GateError("duplicate task")
        for dep in dependencies:
            if not db.execute("SELECT 1 FROM tasks WHERE id=?", (dep,)).fetchone():
                raise GateError(f"unknown dependency: {dep}")
        db.execute("INSERT INTO tasks(id,kind,prompt,model,reasoning_effort,max_seconds,projected_percent) "
                   "VALUES(?,?,?,?,?,?,?)", (task_id, kind, prompt, model, reasoning_effort, max_seconds, projected_percent))
        db.executemany("INSERT INTO dependencies(task_id,depends_on) VALUES(?,?)",
                       [(task_id, dep) for dep in dependencies])
        event(db, task_id, "added")


def _read_response(proc: subprocess.Popen, request: dict, expected_id: int, deadline: float) -> dict:
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    # The app server is a local process; bound each line read with select.
    import selectors
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        while time.monotonic() < deadline:
            if not selector.select(max(0, deadline - time.monotonic())):
                break
            line = proc.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            if message.get("id") == expected_id:
                if "error" in message or "result" not in message:
                    raise GateError("App Server rate-limit request failed")
                return message["result"]
    finally:
        selector.close()
    raise GateError("App Server rate-limit response timed out")


def read_weekly_usage(codex: str = "codex", *, now: float | None = None) -> dict:
    """Read only documented App Server JSON-RPC; return sanitized weekly fields."""
    now = time.time() if now is None else now
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY"):
        env.pop(key, None)
    proc = subprocess.Popen([codex, "app-server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, bufsize=1, env=env, cwd=PROJECT_ROOT)
    try:
        deadline = time.monotonic() + 10
        _read_response(proc, {"method": "initialize", "id": 1,
                              "params": {"clientInfo": {"name": "phase_supervisor",
                                                        "title": "Phase Supervisor", "version": "0.1.0"}}}, 1, deadline)
        assert proc.stdin
        proc.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
        proc.stdin.flush()
        response = _read_response(proc, {"method": "account/rateLimits/read", "id": 2}, 2, deadline)
        return parse_weekly_usage(response, now=now)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise GateError("weekly usage unavailable") from exc
    finally:
        proc.kill()
        proc.wait(timeout=5)


def parse_weekly_usage(result: dict, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    buckets = []
    single = result.get("rateLimits")
    if isinstance(single, dict) and single.get("limitId") == "codex":
        buckets.append(single)
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, dict) and "codex" in by_id:
        buckets.append(by_id["codex"])
    if not buckets:
        raise GateError("codex weekly bucket missing")
    weekly = []
    for bucket in buckets:
        if bucket.get("limitId") != "codex" or bucket.get("rateLimitReachedType"):
            raise GateError("codex limit state contradictory or reached")
        for name in ("primary", "secondary"):
            window = bucket.get(name)
            if isinstance(window, dict) and window.get("windowDurationMins") == WEEK_MINUTES:
                used, reset = window.get("usedPercent"), window.get("resetsAt")
                if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or not 0 <= used <= 100:
                    raise GateError("invalid weekly used percent")
                if isinstance(reset, bool) or not isinstance(reset, (int, float)) or not now < reset <= now + WEEK_MINUTES * 60 + 300:
                    raise GateError("stale weekly window")
                weekly.append((float(used), float(reset)))
    if not weekly or any(abs(a[0] - weekly[0][0]) > 0.01 or abs(a[1] - weekly[0][1]) > 60 for a in weekly):
        raise GateError("weekly bucket missing or contradictory")
    return {"used_percent": weekly[0][0], "resets_at": weekly[0][1],
            "window_minutes": WEEK_MINUTES, "checked_at": now}


def check_reserve(usage: dict, *, reserve_percent: float = 7,
                  projected_percent: float, margin_percent: float = 1) -> None:
    if not 0 < reserve_percent < 100 or margin_percent < 0 or projected_percent <= 0:
        raise GateError("invalid reserve configuration")
    if time.time() >= usage["resets_at"] or time.time() - usage["checked_at"] > 60:
        raise GateError("weekly usage is stale")
    if 100 - usage["used_percent"] - projected_percent - margin_percent < reserve_percent:
        raise GateError("projected work could cross weekly reserve")


def check_cli_preflight(codex: str, model: str, reasoning_effort: str | None = None) -> None:
    """Require ChatGPT-plan auth and an exact model in the refreshed CLI catalog."""
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY"):
        env.pop(key, None)
    try:
        auth = subprocess.run([codex, "login", "status"], capture_output=True,
                              text=True, timeout=10, env=env, check=False, cwd=PROJECT_ROOT)
        if auth.returncode or "logged in using chatgpt" not in (auth.stdout + auth.stderr).lower():
            raise GateError("ChatGPT-plan CLI authentication not verified")
        catalog = subprocess.run([codex, "debug", "models"], capture_output=True,
                                 text=True, timeout=15, env=env, check=False, cwd=PROJECT_ROOT)
        if catalog.returncode:
            raise GateError("live model catalog unavailable")
        data = json.loads(catalog.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise GateError("CLI authentication or model catalog unavailable") from exc
    def find_model(value: object) -> dict | None:
        if isinstance(value, dict):
            if value.get("slug") == model:
                return value
            return next((found for item in value.values() if isinstance(item, (dict, list))
                         if (found := find_model(item)) is not None), None)
        if isinstance(value, list):
            return next((found for item in value if (found := find_model(item)) is not None), None)
        return None
    selected = find_model(data)
    if selected is None:
        raise GateError("requested model absent from live CLI catalog")
    if reasoning_effort is not None:
        levels = selected.get("supported_reasoning_levels")
        if not isinstance(levels, list) or reasoning_effort not in {
            level.get("effort") for level in levels if isinstance(level, dict)
        }:
            raise GateError("requested reasoning effort unsupported by live model")


def _ready(db: sqlite3.Connection, task: sqlite3.Row) -> None:
    missing = db.execute("SELECT depends_on FROM dependencies d JOIN tasks t ON t.id=d.depends_on "
                         "WHERE d.task_id=? AND t.status!='accepted'", (task["id"],)).fetchall()
    if missing:
        raise GateError("dependencies not accepted: " + ", ".join(row[0] for row in missing))
    if task["kind"] != "structured":
        gate = db.execute("SELECT 1 FROM tasks WHERE id='STRUCTURED_READY' AND status='accepted'").fetchone()
        if not gate:
            raise GateError("structured readiness gate not accepted")
    if task["status"] in {"accepted", "running", "awaiting_evaluation", "interrupted_unreviewed"}:
        raise GateError("task is not launchable")


def prepare_attempt(db: sqlite3.Connection, task_id: str, strategy: str,
                    output_path: Path) -> tuple[sqlite3.Row, int]:
    if not strategy.strip():
        raise GateError("distinct nonempty strategy required")
    if output_path.exists():
        raise GateError("attempt output already exists")
    with db:
        db.execute("BEGIN IMMEDIATE")
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise GateError("unknown task")
        _ready(db, task)
        previous = db.execute("SELECT * FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1", (task_id,)).fetchone()
        number = 1 if previous is None else previous["number"] + 1
        if number > MAX_ATTEMPTS:
            raise GateError("repair limit reached")
        if previous is not None and previous["status"] not in {"failed", "rejected", "interrupted"}:
            raise GateError("previous attempt needs evaluator disposition")
        if db.execute("SELECT 1 FROM attempts WHERE task_id=? AND strategy=?", (task_id, strategy)).fetchone():
            raise GateError("unchanged failed strategy")
        cur = db.execute("INSERT INTO attempts(task_id,number,strategy,status,started_at,output_path) "
                         "VALUES(?,?,?,?,?,?)", (task_id, number, strategy, "running", time.time(), str(output_path)))
        db.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
        event(db, task_id, "attempt_started", f"attempt={number}")
        return task, cur.lastrowid


def finish_attempt(db: sqlite3.Connection, attempt_id: int, exit_code: int,
                   failure: str = "", *, interruption: bool = False) -> None:
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM attempts WHERE id=? AND status='running'", (attempt_id,)).fetchone()
        if row is None:
            raise GateError("attempt is not running")
        status = "interrupted" if interruption else ("awaiting_evaluation" if exit_code == 0 else "failed")
        task_status = "interrupted_unreviewed" if interruption else status
        db.execute("UPDATE attempts SET status=?,ended_at=?,exit_code=?,failure=? WHERE id=?",
                   (status, time.time(), exit_code, failure[:500], attempt_id))
        db.execute("UPDATE tasks SET status=? WHERE id=?", (task_status, row["task_id"]))
        event(db, row["task_id"], "attempt_finished", f"attempt={row['number']};exit={exit_code}")


def completed_turn(path: Path) -> bool:
    """An exit-zero CLI without a successful turn event is not a success."""
    completed = False
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line)
                if item.get("type") in {"turn.failed", "error"}:
                    return False
                if item.get("type") == "turn.completed":
                    completed = True
    except (OSError, ValueError):
        return False
    return completed


def recover(db: sqlite3.Connection) -> int:
    """After process death, never silently relaunch an in-flight attempt."""
    with db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT id,task_id FROM attempts WHERE status='running'").fetchall()
        for row in rows:
            db.execute("UPDATE attempts SET status='interrupted',ended_at=?,failure='supervisor restart; inspect output' WHERE id=?",
                       (time.time(), row["id"]))
            db.execute("UPDATE tasks SET status='interrupted_unreviewed' WHERE id=?", (row["task_id"],))
            event(db, row["task_id"], "recovered_interruption")
    return len(rows)


def acknowledge_interruption(db: sqlite3.Connection, task_id: str, evidence_path: Path) -> None:
    """Operator records process inspection; recovery never assumes child exited."""
    if not evidence_path.is_file() or not evidence_path.read_text(encoding="utf-8").strip():
        raise GateError("nonempty orphan-process inspection evidence required")
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None or row["status"] != "interrupted_unreviewed":
            raise GateError("task is not awaiting interruption review")
        db.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
        event(db, task_id, "interruption_reviewed", str(evidence_path))


def evaluate(db: sqlite3.Connection, task_id: str, attempt_id: int, evaluator: str,
             verdict: str, evidence_path: Path) -> None:
    if evaluator.strip().lower() in {"", "builder"} or verdict not in {"accept", "reject"}:
        raise GateError("distinct evaluator and accept/reject verdict required")
    if not evidence_path.is_file() or not evidence_path.read_text(encoding="utf-8").strip():
        raise GateError("nonempty evaluator evidence file required")
    if task_id == "STRUCTURED_READY" and verdict == "accept":
        try:
            readiness = json.loads(evidence_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise GateError("structured readiness requires JSON scientific evidence") from exc
        if not isinstance(readiness, dict) or readiness.get("scientific_readiness") is not True or not readiness.get("evidence"):
            raise GateError("explicit scientific readiness evidence required")
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM attempts WHERE id=? AND task_id=? AND status='awaiting_evaluation'",
                         (attempt_id, task_id)).fetchone()
        if row is None:
            raise GateError("successful attempt awaiting evaluation required")
        db.execute("INSERT INTO evaluations VALUES(?,?,?,?,?,?)",
                   (task_id, attempt_id, evaluator, verdict, str(evidence_path), time.time()))
        new_status = "accepted" if verdict == "accept" else "rejected"
        db.execute("UPDATE attempts SET status=? WHERE id=?", (new_status, attempt_id))
        db.execute("UPDATE tasks SET status=?,accepted_at=? WHERE id=?",
                   (new_status, time.time() if verdict == "accept" else None, task_id))
        event(db, task_id, "evaluated", verdict)


def run_task(db: sqlite3.Connection, task_id: str, strategy: str, output_path: Path,
             *, reserve_percent: float = 7, margin_percent: float = 1,
             codex: str = "codex", dry_run: bool = False,
             usage_reader=read_weekly_usage) -> dict:
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if task is None:
        raise GateError("unknown task")
    _ready(db, task)
    if dry_run:
        if output_path.exists() or db.execute("SELECT 1 FROM attempts WHERE task_id=? AND strategy=?", (task_id, strategy)).fetchone():
            raise GateError("output or strategy already exists")
        return {"dry_run": True, "task": task_id, "model": task["model"],
                "max_seconds": task["max_seconds"], "projected_percent": task["projected_percent"],
                "reserve_percent": reserve_percent}
    usage = usage_reader(codex)
    check_reserve(usage, reserve_percent=reserve_percent,
                  projected_percent=task["projected_percent"], margin_percent=margin_percent)
    check_cli_preflight(codex, task["model"], task["reasoning_effort"])
    task, attempt_id = prepare_attempt(db, task_id, strategy, output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # No approval override, full-access sandbox, API key, or automatic reset.
    command = [codex, "exec", "--model", task["model"], "--sandbox", "workspace-write",
               "--json", "--ephemeral"]
    if task["reasoning_effort"]:
        command.extend(["--config", f'model_reasoning_effort="{task["reasoning_effort"]}"'])
    command.append(task["prompt"])
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY"):
        env.pop(key, None)
    failure = ""
    exit_code = 1
    proc = None
    interruption = False

    def stop_child() -> None:
        if proc is None:
            return
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # interruption review remains mandatory

    try:
        with output_path.open("x", encoding="utf-8") as output:
            proc = subprocess.Popen(command, stdout=output, stderr=subprocess.DEVNULL, env=env,
                                    start_new_session=True, cwd=PROJECT_ROOT)
            with db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE attempts SET process_group_id=? WHERE id=? AND status='running'",
                           (proc.pid, attempt_id))
            deadline = time.monotonic() + task["max_seconds"]
            while proc.poll() is None:
                if time.monotonic() >= deadline:
                    failure = "session time bound reached"
                    break
                time.sleep(min(30, max(0.1, deadline - time.monotonic())))
                if proc.poll() is not None:
                    break
                try:
                    fresh = usage_reader(codex)
                    check_reserve(fresh, reserve_percent=reserve_percent,
                                  projected_percent=0.001, margin_percent=margin_percent)
                except GateError:
                    failure = "weekly usage unavailable or reserve reached during session"
                    break
            if failure:
                interruption = True
                stop_child()
            else:
                exit_code = proc.returncode
                if exit_code:
                    failure = "Codex CLI failed"
                elif not completed_turn(output_path):
                    exit_code = 1
                    failure = "Codex CLI exited without a completed turn"
    except BaseException as exc:
        interruption = proc is not None or isinstance(exc, (KeyboardInterrupt, SystemExit))
        failure = f"supervisor interrupted or launcher error: {type(exc).__name__}"
        try:
            stop_child()
        except OSError:
            pass  # fail closed: operator must inspect possible orphan
        if not isinstance(exc, (OSError, subprocess.SubprocessError, sqlite3.Error)):
            raise
    finally:
        finish_attempt(db, attempt_id, exit_code, failure, interruption=interruption)
    return {"task": task_id, "attempt_id": attempt_id, "exit_code": exit_code,
            "output": str(output_path), "failure": failure}


def handoff(db: sqlite3.Connection) -> dict:
    return {"tasks": [dict(row) for row in db.execute(
        "SELECT id,kind,status,model,reasoning_effort,max_seconds,projected_percent,accepted_at FROM tasks ORDER BY id")],
            "attempts": [dict(row) for row in db.execute(
                "SELECT id,task_id,number,strategy,status,started_at,ended_at,exit_code,process_group_id,output_path,failure FROM attempts ORDER BY id")],
            "evaluations": [dict(row) for row in db.execute("SELECT * FROM evaluations ORDER BY created_at")],
            "events": [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id")]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add")
    add.add_argument("id")
    add.add_argument("--kind", choices=["structured", "text", "memo"], required=True)
    add.add_argument("--prompt-file", type=Path, required=True)
    add.add_argument("--model", required=True)
    add.add_argument("--reasoning-effort", choices=["low", "medium", "high", "xhigh", "max", "ultra"])
    add.add_argument("--max-seconds", type=int, required=True)
    add.add_argument("--projected-percent", type=float, required=True)
    add.add_argument("--depends-on", action="append", default=[])
    run = sub.add_parser("run")
    run.add_argument("id")
    run.add_argument("--strategy", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--reserve-percent", type=float, default=7)
    run.add_argument("--margin-percent", type=float, default=1)
    run.add_argument("--codex", default="codex")
    run.add_argument("--dry-run", action="store_true")
    ev = sub.add_parser("evaluate")
    ev.add_argument("id")
    ev.add_argument("attempt_id", type=int)
    ev.add_argument("--evaluator", required=True)
    ev.add_argument("--verdict", choices=["accept", "reject"], required=True)
    ev.add_argument("--evidence", type=Path, required=True)
    sub.add_parser("recover")
    sub.add_parser("handoff")
    sub.add_parser("status")
    ack = sub.add_parser("acknowledge-interruption")
    ack.add_argument("id")
    ack.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        db = connect(args.db)
        if args.action == "add":
            add_task(db, task_id=args.id, kind=args.kind,
                     prompt=args.prompt_file.read_text(encoding="utf-8"), model=args.model,
                     max_seconds=args.max_seconds, projected_percent=args.projected_percent,
                     dependencies=args.depends_on, reasoning_effort=args.reasoning_effort)
            result = {"added": args.id}
        elif args.action == "run":
            result = run_task(db, args.id, args.strategy, args.output,
                              reserve_percent=args.reserve_percent, margin_percent=args.margin_percent,
                              codex=args.codex, dry_run=args.dry_run)
        elif args.action == "evaluate":
            evaluate(db, args.id, args.attempt_id, args.evaluator, args.verdict, args.evidence)
            result = {"evaluated": args.id, "verdict": args.verdict}
        elif args.action == "recover":
            result = {"interrupted_attempts": recover(db)}
        elif args.action == "acknowledge-interruption":
            acknowledge_interruption(db, args.id, args.evidence)
            result = {"interruption_reviewed": args.id}
        elif args.action == "status":
            data = handoff(db)
            for row in data["tasks"]:
                print(f"{row['id']}: {row['status']} ({row['kind']})")
            print(f"{len(data['attempts'])} attempts; {len(data['evaluations'])} evaluations")
            return 0
        else:
            result = handoff(db)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (GateError, OSError, sqlite3.Error) as exc:
        print(f"supervisor blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
