"""Data-quality evaluations for the identity-cleaning stage."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def evaluate_identity(raw: pd.DataFrame, bridge: pd.DataFrame) -> dict:
    input_trials = raw["nct_id"].nunique() if "nct_id" in raw else 0
    mapped_trials = bridge["nct_id"].nunique() if not bridge.empty else 0
    coverage = mapped_trials / input_trials if input_trials else 0.0
    collisions = (
        bridge.groupby("program_id")[["regimen_id", "indication_id"]]
        .apply(lambda x: len(x.drop_duplicates()))
        .gt(1)
        .sum()
        if not bridge.empty
        else 0
    )
    duplicate_rows = int(bridge.duplicated(["nct_id", "program_id"]).sum()) if not bridge.empty else 0
    null_keys = int(
        bridge[["nct_id", "regimen_id", "indication_id", "program_id"]].isna().any(axis=1).sum()
    ) if not bridge.empty else 0
    placebo_rows = int(bridge["regimen_id"].str.contains(r"\b(?:placebo|sham)\b", case=False).sum()) if not bridge.empty else 0
    ambiguous_trials = int(bridge.loc[bridge["ambiguous_mapping"], "nct_id"].nunique()) if not bridge.empty else 0

    checks = [
        {"name": "bridge_not_empty", "status": "PASS" if mapped_trials else "FAIL", "value": mapped_trials},
        {"name": "no_null_keys", "status": "PASS" if null_keys == 0 else "FAIL", "value": null_keys},
        {"name": "no_duplicate_bridge_rows", "status": "PASS" if duplicate_rows == 0 else "FAIL", "value": duplicate_rows},
        {"name": "program_ids_are_unique_mappings", "status": "PASS" if collisions == 0 else "FAIL", "value": int(collisions)},
        {"name": "placebos_removed", "status": "PASS" if placebo_rows == 0 else "FAIL", "value": placebo_rows},
        {"name": "mapping_coverage", "status": "PASS" if coverage >= 0.80 else "WARN", "value": round(coverage, 4)},
        {"name": "ambiguous_trials_reported", "status": "INFO", "value": ambiguous_trials},
    ]
    return {
        "summary": {
            "input_rows": len(raw),
            "input_trials": input_trials,
            "mapped_trials": mapped_trials,
            "unique_programs": int(bridge["program_id"].nunique()) if not bridge.empty else 0,
            "mapping_coverage": coverage,
            "ambiguous_trials": ambiguous_trials,
        },
        "checks": checks,
        "overall": "FAIL" if any(c["status"] == "FAIL" for c in checks) else "PASS",
    }


def markdown_report(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Identity-cleaning evaluation",
        "",
        f"**Overall: {report['overall']}**",
        "",
        "## Cohort summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {key.replace('_', ' ')} | {value} |" for key, value in summary.items())
    lines.extend(["", "## Checks", "", "| Check | Status | Value |", "| --- | --- | ---: |"])
    lines.extend(f"| {c['name']} | {c['status']} | {c['value']} |" for c in report["checks"])
    return "\n".join(lines) + "\n"


def save_report(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "identity_eval.json").write_text(json.dumps(report, indent=2) + "\n")
    (out_dir / "identity_eval.md").write_text(markdown_report(report))
