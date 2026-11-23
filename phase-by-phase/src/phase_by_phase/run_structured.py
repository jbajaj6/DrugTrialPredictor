"""Replay a saved slim cohort and separate full-result records into auditable tables."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .acquire import load_snapshot, sha256
from .audit import audit_tables
from .fetch_details import load_details
from .organize import SCHEMAS, build_tables
from .structured import build_structured_tables, build_trial_snapshots


def run(source: Path, details: Path, out: Path, *, selected_only: bool = False,
        cleaned: Path | None = None, prediction_cutoff: str = "2023-12-31") -> dict:
    """Write a new derived dataset; never mutate source or previous outputs."""
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory is not empty; preserve prior runs")
    studies, source_manifest = load_snapshot(source)
    result_studies, detail_manifest = load_details(details)
    detail_ids = {x["protocolSection"]["identificationModule"]["nctId"] for x in result_studies}
    source_ids = {x["protocolSection"]["identificationModule"]["nctId"] for x in studies}
    if not detail_ids <= source_ids:
        raise ValueError("Detail NCT IDs must belong to immutable source cohort")
    if cleaned is not None:
        if selected_only:
            raise ValueError("Existing cleaned tables require a full-cohort run")
        tables = {name: pd.read_parquet(cleaned / f"{name}.parquet") for name in SCHEMAS}
        if set(tables["trials"].nct_id) != source_ids:
            raise ValueError("Cleaned trial IDs do not match verified source snapshot")
        # The cleaned input is an already-audited immutable output. Re-audit it
        # below rather than silently trusting the prior run's report.
    else:
        if selected_only:
            studies = [x for x in studies if x["protocolSection"]["identificationModule"]["nctId"] in detail_ids]
        tables = build_tables(studies)
    del studies
    slim_dates = tables["trials"].set_index("nct_id")[["results_first_post_date", "last_update_post_date"]]
    matched_details = []
    detail_date_mismatches = []
    for study in result_studies:
        nct = study["protocolSection"]["identificationModule"]["nctId"]
        status = study.get("protocolSection", {}).get("statusModule", {})
        current = (status.get("resultsFirstPostDateStruct", {}).get("date"),
                   status.get("lastUpdatePostDateStruct", {}).get("date"))
        saved = tuple(slim_dates.loc[nct])
        saved = tuple(None if pd.isna(value) else value for value in saved)
        if current == saved:
            matched_details.append(study)
        else:
            detail_date_mismatches.append(nct)
    # The local pilot is a selected subset, not a complete-query cohort. Keep
    # that distinction explicit in its audit and prohibit final-model claims.
    audit_manifest = dict(source_manifest)
    audit_manifest["records"] = len(tables["trials"])
    audit_manifest["total_count"] = len(tables["trials"])
    audit_manifest["complete"] = not selected_only and source_manifest["complete"]
    audit = audit_tables(tables, audit_manifest)
    # Current full records can change after the slim source snapshot. Do not
    # silently join revised content to an older first-post/last-update date.
    structured = build_structured_tables(matched_details)
    if prediction_cutoff >= "2024-01-01" or prediction_cutoff > source_manifest["cutoff"]:
        raise ValueError("Development runner cannot emit sealed 2024+ prediction rows")
    snapshots = build_trial_snapshots(tables, structured, prediction_cutoff)
    if snapshots.duplicated(["nct_id", "program_id"]).any():
        raise ValueError("Duplicate trial/program prediction rows")
    if "max_evidence_date" in snapshots and "prediction_date" in snapshots:
        invalid = snapshots.max_evidence_date.notna() & (snapshots.max_evidence_date > snapshots.prediction_date)
        if invalid.any():
            raise ValueError("Earlier evidence postdates prediction")
    if audit["hard_fail"]:
        raise ValueError("Source/cleaning audit failed; no output written")
    out.mkdir(parents=True, exist_ok=True)
    artifact_paths = {}
    for name, frame in {**tables, **structured, "prediction_rows": snapshots}.items():
        frame.to_parquet(out / f"{name}.parquet", index=False)
        artifact_paths[f"{name}.parquet"] = out / f"{name}.parquet"
    (out / "quality_audit.json").write_text(json.dumps(audit, indent=2, allow_nan=False) + "\n")
    coverage = {
        "source_trials_replayed": len(source_ids),
        "trials_in_cleaned_output": len(tables["trials"]),
        "cleaned_tables_reused_from": str(cleaned) if cleaned is not None else None,
        "source_query_complete": source_manifest["complete"],
        "selected_only_pilot": selected_only,
        "development_prediction_cutoff": prediction_cutoff,
        "final_holdout_2024_onward_omitted_from_prediction_rows": prediction_cutoff < "2024-01-01",
        "detail_records": len(result_studies),
        "detail_records_with_results_section": sum("resultsSection" in x for x in result_studies),
        "detail_records_date_matched_to_source": len(matched_details),
        "detail_records_date_mismatched_excluded": len(detail_date_mismatches),
        "detail_date_mismatch_nct_ids": detail_date_mismatches[:25],
        "detail_snapshot_complete": detail_manifest["complete"],
        "child_rows": {name: len(frame) for name, frame in structured.items()},
        "prediction_rows": len(snapshots),
        "prediction_phase_counts": dict(Counter(snapshots.phase)) if "phase" in snapshots else {},
        "label_coverage": {col: int(snapshots[col].notna().sum()) for col in ("completion_label", "significance_label") if col in snapshots},
        "historical_version_warning": "Current registry detail content is not an archived first-posted version; retrospective/exploratory only.",
    }
    (out / "feature_coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    artifact_paths["quality_audit.json"] = out / "quality_audit.json"
    artifact_paths["feature_coverage.json"] = out / "feature_coverage.json"
    manifest = {"run_utc": datetime.now(timezone.utc).isoformat(),
                "source_manifest": str(source / "manifest.json"),
                "source_manifest_sha256": sha256(source / "manifest.json"),
                "detail_manifest": str(details / "manifest.json"),
                "detail_manifest_sha256": sha256(details / "manifest.json"),
                "selected_only_pilot": selected_only,
                "development_prediction_cutoff": prediction_cutoff,
                "cleaned_tables_reused_from": str(cleaned) if cleaned is not None else None,
                "source_code_sha256": {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                "output_sha256": {name: sha256(path) for name, path in sorted(artifact_paths.items())}}
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return coverage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--selected-only", action="store_true")
    parser.add_argument("--cleaned", type=Path, default=None,
                        help="reuse and re-audit existing full-cohort clean tables")
    parser.add_argument("--prediction-cutoff", default="2023-12-31",
                        help="development prediction rows end before sealed 2024+ holdout")
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.details, args.out,
                         selected_only=args.selected_only, cleaned=args.cleaned,
                         prediction_cutoff=args.prediction_cutoff), indent=2))


if __name__ == "__main__":
    main()
