"""Read-only API-snapshot comparison with Jai's original AACT cohort rules.

This is a breadth/funnel audit, not model training or exact AACT reproduction.
Only first-public-registration dates are read before 2024+ rows are discarded;
sealed rows' status, completion, and label dates are never inspected.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from .acquire import load_snapshot, sha256
from .structured import _day


FINAL = {"COMPLETED", "TERMINATED", "WITHDRAWN"}
PURE_PHASE = {"PHASE1", "PHASE2", "PHASE3"}
START_MIN = pd.Timestamp("2005-01-01")
START_MAX = pd.Timestamp("2019-12-31")
HOLDOUT_FROM = pd.Timestamp("2024-01-01")
TRAIN_END = pd.Timestamp("2020-01-01")


def _field(mapping: dict, section: str) -> dict:
    value = mapping.get(section, {})
    return value if isinstance(value, dict) else {}


def _dated_section(mapping: dict, key: str):
    return _day(_field(mapping, key).get("date"))


def _known_before_checkpoint(completion_raw, completion_type, prediction) -> bool:
    if str(completion_type).upper() != "ACTUAL":
        return False
    day = _day(completion_raw)
    if day is not None:
        return day <= prediction
    if isinstance(completion_raw, str) and re.fullmatch(r"\d{4}-\d{2}", completion_raw):
        try:
            return pd.Period(completion_raw, freq="M") <= prediction.to_period("M")
        except ValueError:
            return False
    return False


def jai_parity_audit(studies: list[dict], cleaned: pd.DataFrame,
                     bridge: pd.DataFrame) -> dict:
    """Count source and phase-by-phase gates, one NCT per source row.

    The source snapshot is broader than Jai's DRUG-only AACT query, and current
    API status is retrospective. AACT flatfiles are not present locally.
    """
    needed = {"nct_id", "phase", "condition_count", "start_date_type", "completion_date",
              "completion_date_type", "last_update_post_date", "results_first_post_date"}
    if needed - set(cleaned):
        raise ValueError(f"Missing cleaned columns: {sorted(needed - set(cleaned))}")
    if not {"nct_id", "program_id"}.issubset(bridge):
        raise ValueError("Missing program bridge columns")
    if cleaned.nct_id.duplicated().any():
        raise ValueError("Cleaned table is not one row per NCT")

    stages = {key: set() for key in (
        "first_post_before_2024", "interventional", "drug_intervention", "final_status",
        "start_period_2005_2019", "exact_start_2005_2019", "first_submitted_exact",
        "submitted_lag_le_90")}
    source_total = len(studies)
    seen: set[str] = set()
    records: dict[str, dict] = {}
    start_precision = {"exact_day_in_range": 0, "month_only_in_range": 0,
                       "outside_2005_2019": 0, "undated_or_unparseable": 0}
    month_lag_bounds = {"month_only_in_range": 0, "submitted_exact": 0,
                        "definitely_lag_le_90": 0, "possibly_lag_le_90": 0,
                        "uncertain_at_month_precision": 0}
    for study in studies:
        protocol = _field(study, "protocolSection")
        nct = _field(protocol, "identificationModule").get("nctId")
        if not isinstance(nct, str) or not nct or nct in seen:
            raise ValueError("Missing or duplicate source NCT")
        seen.add(nct)
        status = _field(protocol, "statusModule")
        # This is the only field consulted for the potentially sealed row.
        first_post = _dated_section(status, "studyFirstPostDateStruct")
        if first_post is None or first_post >= HOLDOUT_FROM:
            continue
        stages["first_post_before_2024"].add(nct)
        if str(_field(protocol, "designModule").get("studyType", "")).upper() != "INTERVENTIONAL":
            continue
        stages["interventional"].add(nct)
        interventions = _field(protocol, "armsInterventionsModule").get("interventions", []) or []
        if not any(isinstance(item, dict) and str(item.get("type", "")).upper() == "DRUG"
                   for item in interventions):
            continue
        stages["drug_intervention"].add(nct)
        current_status = str(status.get("overallStatus", "")).upper()
        if current_status not in FINAL:
            continue
        stages["final_status"].add(nct)
        start_raw = _field(status, "startDateStruct").get("date")
        start = _day(start_raw)
        month = None
        if isinstance(start_raw, str) and re.fullmatch(r"\d{4}-\d{2}", start_raw):
            try:
                month = pd.Period(start_raw, freq="M")
            except ValueError:
                pass
        if start is not None:
            in_range = START_MIN <= start <= START_MAX
        elif month is not None:
            in_range = pd.Period("2005-01", freq="M") <= month <= pd.Period("2019-12", freq="M")
        else:
            in_range = False
        if not in_range:
            start_precision["outside_2005_2019" if start is not None or month is not None
                            else "undated_or_unparseable"] += 1
            continue
        stages["start_period_2005_2019"].add(nct)
        if month is not None:
            start_precision["month_only_in_range"] += 1
            month_lag_bounds["month_only_in_range"] += 1
            submitted = _day(status.get("studyFirstSubmitDate"))
            if submitted is not None:
                month_lag_bounds["submitted_exact"] += 1
                upper = (submitted - month.start_time).days
                lower = (submitted - month.end_time.normalize()).days
                if upper <= 90:
                    month_lag_bounds["definitely_lag_le_90"] += 1
                if lower <= 90:
                    month_lag_bounds["possibly_lag_le_90"] += 1
                    if upper > 90:
                        month_lag_bounds["uncertain_at_month_precision"] += 1
            continue
        start_precision["exact_day_in_range"] += 1
        stages["exact_start_2005_2019"].add(nct)
        submitted = _day(status.get("studyFirstSubmitDate"))
        if submitted is None:
            continue
        stages["first_submitted_exact"].add(nct)
        lag = (submitted - start).days
        if lag > 90:  # Jai does not impose a lower bound on early submissions.
            continue
        stages["submitted_lag_le_90"].add(nct)
        records[nct] = {"first_post": first_post, "start": start,
                        "submitted_lag_days": lag,
                        "status": current_status,
                        "has_results": study.get("hasResults") is True}

    jai_ids = stages["submitted_lag_le_90"]
    missing_cleaned = jai_ids - set(cleaned.nct_id)
    if missing_cleaned:
        raise ValueError(f"Jai-like source trials missing from cleaned table: {len(missing_cleaned)}")
    # All these rows passed the checkpoint gate, so outcome dates are now safe
    # to read. The bridge is a candidate exact-label linkage, not verified ID.
    cohort = cleaned.loc[cleaned.nct_id.isin(jai_ids)].copy()
    mapped = set(bridge.nct_id)
    phase_stages = {key: set() for key in (
        "pure_phase", "precise_actual_start", "one_recorded_condition_proxy", "arm_aware_program_link",
        "prospective_at_first_post", "completion_label_available_by_split_end")}
    labels = {"train": {"rows": 0, "known_by_origin": 0, "completed": 0, "stopped": 0},
              "validation": {"rows": 0, "known_by_end": 0, "completed": 0, "stopped": 0}}
    no_result_known = 0
    for row in cohort.itertuples(index=False):
        nct = row.nct_id
        info = records[nct]
        prediction = info["first_post"]
        split = "train" if prediction < TRAIN_END else "validation"
        labels[split]["rows"] += 1
        completion = _day(row.completion_date)
        update = _day(row.last_update_post_date)
        label_known = False
        if (str(row.completion_date_type).upper() == "ACTUAL" and
                completion is not None and update is not None):
            available = max(completion, update)
            boundary = TRAIN_END if split == "train" else HOLDOUT_FROM
            if prediction < available < boundary:
                label_known = True
                labels[split]["known_by_origin" if split == "train" else "known_by_end"] += 1
                labels[split]["completed" if info["status"] == "COMPLETED" else "stopped"] += 1
                if not info["has_results"]:
                    no_result_known += 1
        if row.phase not in PURE_PHASE:
            continue
        phase_stages["pure_phase"].add(nct)
        if str(row.start_date_type).upper() != "ACTUAL":
            continue
        phase_stages["precise_actual_start"].add(nct)
        if row.condition_count != 1:
            continue
        phase_stages["one_recorded_condition_proxy"].add(nct)
        if nct not in mapped:
            continue
        phase_stages["arm_aware_program_link"].add(nct)
        if _known_before_checkpoint(row.completion_date, row.completion_date_type, prediction):
            continue
        result_post = _day(row.results_first_post_date)
        if result_post is not None and result_post <= prediction:
            continue
        phase_stages["prospective_at_first_post"].add(nct)
        if label_known:
            phase_stages["completion_label_available_by_split_end"].add(nct)

    ordered_source = list(stages)
    ordered_phase = list(phase_stages)
    return {"status": "api_snapshot_approximate_jai_cleaning_parity_no_model",
            "unit": "unique NCT trial",
            "source_records": source_total,
            "sealed_first_post_2024_onward_or_undated": source_total - len(stages[ordered_source[0]]),
            "jai_like_funnel": [{"gate": key, "nct_count": len(stages[key])} for key in ordered_source],
            "jai_like_cohort": len(jai_ids),
            "jai_like_cohort_basis": "strict exact-day, first-public-post-before-2024 API subset; not Jai's full AACT cohort",
            "start_precision_after_final_status": start_precision,
            "month_only_start_submitted_lag_bounds": month_lag_bounds,
            "jai_like_without_posted_results": sum(not item["has_results"] for item in records.values()),
            "early_submission_negative_lag": sum(item["submitted_lag_days"] < 0 for item in records.values()),
            "phase_by_phase_extra_funnel_on_jai_like_cohort": [
                {"gate": key, "nct_count": len(phase_stages[key])} for key in ordered_phase],
            "completion_label_maturity": labels,
            "known_completion_labels_without_posted_results": no_result_known,
            "original_start_split": {
                "2005_2015": sum(item["start"].year <= 2015 for item in records.values()),
                "2016_2019": sum(item["start"].year >= 2016 for item in records.values())},
            "caveats": [
                "Current API snapshot is not Jai's original AACT flatfile vintage, and its query includes biologics before the DRUG-only gate.",
                "API month-only start dates cannot reproduce SQL CAST(start_date AS DATE); exact-day starts are required here.",
                "Month-only start lag bounds use the first and last possible day of the month; no date is imputed into the cohort.",
                "Current final status is a retrospective cohort gate, not an at-registration feature.",
                "Sealing trials first posted in 2024 or later changes Jai's original 2005-2019-start cohort, independent of snapshot vintage.",
                "First-submitted date is used for Jai's <=90-day lag; first-posted date is used only as the public prediction checkpoint.",
                "Jai's original start-year train/test split is distinct from this report's first-public-checkpoint label-maturity partitions.",
                "One recorded condition is only a proxy for the organizer's eligible non-healthy, unambiguous indication rule.",
                "No results-section requirement is imposed for completion; no broad linked earlier-phase evidence is claimed."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cleaned", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Do not overwrite a previous parity audit")
    studies, source_manifest = load_snapshot(args.source)
    cleaned_path = args.cleaned / "trials.parquet"
    bridge_path = args.cleaned / "program_trials.parquet"
    report = jai_parity_audit(studies, pd.read_parquet(cleaned_path), pd.read_parquet(bridge_path))
    report["input_integrity"] = {
        "source_manifest_sha256": sha256(args.source / "manifest.json"),
        "source_manifest_records": source_manifest["records"],
        "cleaned_trials_sha256": sha256(cleaned_path),
        "program_trials_sha256": sha256(bridge_path)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "source_records": report["source_records"],
                      "jai_like_cohort": report["jai_like_cohort"]}))


if __name__ == "__main__":
    main()
