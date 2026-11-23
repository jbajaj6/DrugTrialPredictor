"""Offline pipeline integration: replay, persisted evidence, and model gates."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from phase_by_phase import analysis, run_analysis
from phase_by_phase.acquire import sha256


def _study(nct, phase, year, drug):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct},
            "statusModule": {
                "overallStatus": "COMPLETED",
                "startDateStruct": {"date": f"{year}-03-01", "type": "ACTUAL"},
                "studyFirstPostDateStruct": {"date": f"{year}-02-01", "type": "ACTUAL"},
                "completionDateStruct": {"date": f"{year + 1}-03-01", "type": "ACTUAL"},
                "resultsFirstPostDateStruct": {"date": f"{year + 1}-07-01", "type": "ACTUAL"},
                "lastUpdatePostDateStruct": {"date": "2026-01-01", "type": "ACTUAL"},
            },
            "designModule": {
                "studyType": "INTERVENTIONAL", "phases": [phase],
                "enrollmentInfo": {"count": 100, "type": "ACTUAL"},
                "designInfo": {"allocation": "RANDOMIZED", "interventionModel": "SINGLE_GROUP",
                               "maskingInfo": {"masking": "NONE"}},
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Example Sponsor", "class": "INDUSTRY"}},
            "conditionsModule": {"conditions": ["Example Disease"]},
            "armsInterventionsModule": {
                "armGroups": [{"label": "Treatment", "type": "EXPERIMENTAL"}],
                "interventions": [{"name": drug, "type": "DRUG", "armGroupLabels": ["Treatment"]}],
            },
        },
        "hasResults": True,
    }


@pytest.fixture
def cached_snapshot(tmp_path):
    """A real checksummed on-disk snapshot format; no downloader or network."""
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    records = [
        _study("NCT00000001", "PHASE1", 2008, "Drug A"),
        _study("NCT00000002", "PHASE2", 2010, "Drug A"),
        _study("NCT00000003", "PHASE3", 2013, "Drug A"),
        _study("NCT00000004", "PHASE1", 2009, "Drug B"),
    ]
    page = snapshot / "page_00000.json.gz"
    with gzip.open(page, "wt", encoding="utf-8") as handle:
        json.dump({"studies": records, "totalCount": len(records)}, handle)
    manifest = {
        "schema_version": 1, "cutoff": "2026-11-19", "complete": True,
        "records": len(records), "total_count": len(records),
        "pages": [{"file": page.name, "records": len(records), "sha256": sha256(page)}],
        "retrieval_started_utc": "2026-11-19T12:00:00+00:00",
        "params": {"query.term": "offline integration fixture"},
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return snapshot


def _raw_hashes(snapshot):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in snapshot.iterdir()}


def test_offline_cli_creates_reports_plot_and_provenance_without_mutating_raw(cached_snapshot, tmp_path):
    before = _raw_hashes(cached_snapshot)
    output = tmp_path / "output"
    environment = os.environ.copy()
    package_source = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = package_source + os.pathsep + environment.get("PYTHONPATH", "")
    environment["MPLCONFIGDIR"] = str(tmp_path / "matplotlib-cache")
    result = subprocess.run(
        [sys.executable, "-m", "phase_by_phase.run_analysis", "--snapshot", str(cached_snapshot),
         "--out", str(output), "--bootstrap", "0"],
        env=environment, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _raw_hashes(cached_snapshot) == before
    audit = json.loads((output / "quality_audit.json").read_text())
    provenance = json.loads((output / "run_manifest.json").read_text())
    report = json.loads((output / "analysis_report.json").read_text())
    assert audit["hard_fail"] is False
    assert audit["summary"]["input_trials"] == 4
    assert provenance["records"] == 4 and provenance["query_complete"] is True
    assert provenance["source_manifest_sha256"] == before["manifest.json"]
    assert "organize.py" in provenance["source_code_sha256"]
    assert report["data_complete"] is True
    assert set(report["models"]) == {"baseline", "post_phase1", "post_phase2"}
    assert all(model["status"] == "not_estimable" for model in report["models"].values())
    assert pd.read_parquet(output / "trials.parquet").shape[0] == 4
    assert not pd.read_parquet(output / "snapshots.parquet").empty
    assert (output / "REPORT.md").stat().st_size > 0
    assert (output / "cohort.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_incomplete_snapshot_never_invokes_model_fitting(cached_snapshot, tmp_path, monkeypatch):
    manifest_path = cached_snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(complete=False, total_count=100)
    manifest_path.write_text(json.dumps(manifest))

    def forbidden_fit(*args, **kwargs):
        raise AssertionError("Incomplete extraction must not fit any checkpoint model")

    monkeypatch.setattr(analysis, "fit_checkpoint", forbidden_fit)
    result = run_analysis.run(cached_snapshot, tmp_path / "incomplete", bootstrap=0)
    assert not result["audit"]["hard_fail"]
    assert result["analysis"]["data_complete"] is False
    for model in result["analysis"]["models"].values():
        assert model["status"] == "not_estimable"
        assert "incomplete" in model["reason"]
    assert pd.read_parquet(tmp_path / "incomplete" / "predictions.parquet").empty


def test_failed_audit_persists_evidence_and_blocks_analysis(cached_snapshot, tmp_path, monkeypatch):
    output = tmp_path / "failed-audit"
    monkeypatch.setattr(run_analysis, "audit_tables", lambda *args: {
        "summary": {}, "checks": [{"name": "injected_corruption", "status": "FAIL"}],
        "overall": "FAIL", "hard_fail": True,
    })

    def forbidden_analysis(*args, **kwargs):
        raise AssertionError("Analysis must not execute after a hard data failure")

    monkeypatch.setattr(run_analysis, "build_analysis", forbidden_analysis)
    with pytest.raises(ValueError, match="Data audit failed"):
        run_analysis.run(cached_snapshot, output, bootstrap=0)
    assert json.loads((output / "quality_audit.json").read_text())["hard_fail"] is True
    assert (output / "run_manifest.json").exists()
    assert not (output / "analysis_report.json").exists()
    assert not (output / "predictions.parquet").exists()


def test_nonempty_output_is_rejected_without_overwriting_results(cached_snapshot, tmp_path):
    output = tmp_path / "existing-output"
    output.mkdir()
    marker = output / "previous-result.txt"
    marker.write_text("keep this earlier result")
    with pytest.raises(ValueError, match="not empty"):
        run_analysis.run(cached_snapshot, output, bootstrap=0)
    assert marker.read_text() == "keep this earlier result"
    assert sorted(path.name for path in output.iterdir()) == ["previous-result.txt"]


def test_tampered_snapshot_is_rejected_before_outputs_are_written(cached_snapshot, tmp_path):
    page = cached_snapshot / "page_00000.json.gz"
    page.write_bytes(page.read_bytes() + b"changed")
    output = tmp_path / "tampered-output"
    with pytest.raises(ValueError, match="Checksum mismatch"):
        run_analysis.run(cached_snapshot, output, bootstrap=0)
    assert not output.exists()
