"""Broad, one-NCT development cohort with separate completion/significance labels.

This layer does not infer program identity or use current protocol design as a
launch feature. All 2024+ first-public-posting rows are sealed before outcomes
are read. Missing results and missing p-values remain unknown, never negative.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .acquire import sha256
from .audit_jai_parity import _known_before_checkpoint
from .structured import _day


HOLDOUT_FROM = pd.Timestamp("2024-01-01")
TRAIN_END = pd.Timestamp("2020-01-01")
PURE_PHASES = ("PHASE1", "PHASE2", "PHASE3")
NONCOMPLETION = {"TERMINATED", "WITHDRAWN"}
ROW_COLUMNS = ("nct_id", "phase_stratum", "prediction_date", "prediction_year",
               "completion_label", "completion_label_available_date",
               "significance_label", "significance_label_available_date")


def _primary_decisions(analyses: pd.DataFrame, eligible_ids: set[str]) -> dict[str, bool | None]:
    needed = {"nct_id", "outcome_type", "p_significant_005"}
    if needed - set(analyses):
        raise ValueError(f"Missing analyses columns: {sorted(needed - set(analyses))}")
    # Never touch outcomes belonging to a sealed or excluded target.
    allowed = analyses.loc[analyses.nct_id.isin(eligible_ids)]
    primary = allowed.loc[allowed.outcome_type.eq("PRIMARY")]
    decisions = {}
    for nct, group in primary.groupby("nct_id", sort=False):
        values = group.p_significant_005.tolist()
        if any(value is True for value in values):
            decisions[nct] = True
        elif values and all(value is False for value in values):
            decisions[nct] = False
        else:
            decisions[nct] = None
    return decisions


def broad_cohort(trials: pd.DataFrame, interventions: pd.DataFrame,
                 analyses: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Create development rows without requiring results for completion."""
    required = {"nct_id", "phase", "study_type", "first_post_date", "completion_date",
                "completion_date_type", "last_update_post_date", "results_first_post_date",
                "status"}
    if required - set(trials):
        raise ValueError(f"Missing trial columns: {sorted(required - set(trials))}")
    if not {"nct_id", "intervention_type"}.issubset(interventions):
        raise ValueError("Missing intervention columns")
    if trials.nct_id.duplicated().any() or trials.nct_id.isna().any():
        raise ValueError("Trials must be unique and identified by NCT")
    source_n = len(trials)
    first_post = trials.first_post_date.map(_day)
    eligible_time = first_post.notna() & first_post.lt(HOLDOUT_FROM)
    sealed_n = int((~eligible_time).sum())
    # Slicing before any completion/status/result-date column is accessed is
    # essential: tests supply objects that raise if a sealed outcome is used.
    dev = trials.loc[eligible_time].copy()
    dev["prediction_ts"] = first_post.loc[eligible_time]
    interventional_n = int(dev.study_type.eq("INTERVENTIONAL").sum())
    dev = dev.loc[dev.study_type.eq("INTERVENTIONAL")].copy()
    drug_ids = set(interventions.loc[interventions.intervention_type.eq("DRUG"), "nct_id"])
    dev = dev.loc[dev.nct_id.isin(drug_ids)].copy()
    drug_n = len(dev)
    prospective = []
    excluded_finished = 0
    excluded_own_results = 0
    for row in dev.itertuples(index=False):
        prediction = row.prediction_ts
        if _known_before_checkpoint(row.completion_date, row.completion_date_type, prediction):
            excluded_finished += 1
            continue
        result_post = _day(row.results_first_post_date)
        if result_post is not None and result_post <= prediction:
            excluded_own_results += 1
            continue
        prospective.append(row.nct_id)
    dev = dev.loc[dev.nct_id.isin(prospective)].copy()
    # Resolve dated eligibility before ever reading p-value decisions. A
    # result posted after the development cutoff, or for a non-completed
    # target, is sealed for this task even if its analysis is on disk.
    p_eligible = set()
    for row in dev.itertuples(index=False):
        prediction = row.prediction_ts
        boundary = TRAIN_END if prediction < TRAIN_END else HOLDOUT_FROM
        result_post = _day(row.results_first_post_date)
        update = _day(row.last_update_post_date)
        completion = _day(row.completion_date)
        if (result_post is None or update is None or completion is None or
                str(row.completion_date_type).upper() != "ACTUAL"):
            continue
        if (prediction < max(result_post, update) < boundary and
                prediction < max(completion, update) < boundary and
                row.status == "COMPLETED"):
            p_eligible.add(row.nct_id)
    decisions = _primary_decisions(analyses, p_eligible)
    counts = {"source_unique_nct": source_n, "sealed_2024_or_undated_first_post": sealed_n,
              "first_post_before_2024": int(eligible_time.sum()),
              "interventional": interventional_n, "drug_interventional": drug_n,
              "excluded_known_finished_at_checkpoint": excluded_finished,
              "excluded_own_results_public_at_checkpoint": excluded_own_results,
              "prospective_unique_nct": len(dev)}
    records = []
    coverage = {}
    for row in dev.itertuples(index=False):
        prediction = row.prediction_ts
        phase = row.phase if row.phase in PURE_PHASES else (row.phase or "MISSING_PHASE")
        completion_date = _day(row.completion_date)
        last_update = _day(row.last_update_post_date)
        result_post = _day(row.results_first_post_date)
        boundary = TRAIN_END if prediction < TRAIN_END else HOLDOUT_FROM
        completion_label = None
        completion_available = None
        if (str(row.completion_date_type).upper() == "ACTUAL" and
                completion_date is not None and last_update is not None):
            candidate_date = max(completion_date, last_update)
            if prediction < candidate_date < boundary:
                status = row.status
                if status == "COMPLETED":
                    completion_label = True
                    completion_available = candidate_date
                elif status in NONCOMPLETION:
                    completion_label = False
                    completion_available = candidate_date
        significance_label = None
        significance_available = None
        if completion_label is True and result_post is not None and last_update is not None:
            candidate_date = max(result_post, last_update)
            if prediction < candidate_date < boundary:
                decision = decisions.get(row.nct_id)
                if decision is not None:
                    significance_label = decision
                    significance_available = candidate_date
        split = "train" if prediction < TRAIN_END else "validation"
        bucket = coverage.setdefault(phase, {"train_rows": 0, "validation_rows": 0,
                                             "train_completion_labeled": 0,
                                             "validation_completion_labeled": 0,
                                             "train_completed_q2_eligible": 0,
                                             "validation_completed_q2_eligible": 0,
                                             "train_significance_labeled": 0,
                                             "validation_significance_labeled": 0,
                                             "train_completion_positive": 0,
                                             "train_completion_negative": 0,
                                             "validation_completion_positive": 0,
                                             "validation_completion_negative": 0,
                                             "train_significance_positive": 0,
                                             "train_significance_negative": 0,
                                             "validation_significance_positive": 0,
                                             "validation_significance_negative": 0,
                                             "completed_q2_eligible_but_missing_significance": 0,
                                             "missing_significance": 0})
        bucket[f"{split}_rows"] += 1
        bucket[f"{split}_completion_labeled"] += int(completion_label is not None)
        bucket[f"{split}_completed_q2_eligible"] += int(completion_label is True)
        bucket[f"{split}_significance_labeled"] += int(significance_label is not None)
        for task_name, value in (("completion", completion_label),
                                 ("significance", significance_label)):
            if value is not None:
                bucket[f"{split}_{task_name}_{'positive' if value else 'negative'}"] += 1
        bucket["completed_q2_eligible_but_missing_significance"] += int(
            completion_label is True and significance_label is None)
        bucket["missing_significance"] += int(significance_label is None)
        records.append((row.nct_id, phase, prediction.strftime("%Y-%m-%d"),
                        int(prediction.year), completion_label,
                        completion_available.strftime("%Y-%m-%d") if completion_available is not None else None,
                        significance_label,
                        significance_available.strftime("%Y-%m-%d") if significance_available is not None else None))
    frame = pd.DataFrame.from_records(records, columns=ROW_COLUMNS).sort_values("nct_id").reset_index(drop=True)
    if frame.nct_id.duplicated().any() or len(frame) != counts["prospective_unique_nct"]:
        raise AssertionError("Broad cohort lost one-NCT-per-row integrity")
    for label, available in (("completion_label", "completion_label_available_date"),
                             ("significance_label", "significance_label_available_date")):
        dated = pd.to_datetime(frame[available], errors="coerce")
        prediction = pd.to_datetime(frame.prediction_date)
        if (dated.notna() & (dated <= prediction)).any():
            raise AssertionError(f"{label} is not prospectively dated")
    support = {}
    for phase, values in coverage.items():
        support[phase] = {}
        for task_name in ("completion", "significance"):
            train_n = values[f"train_{task_name}_labeled"]
            val_n = values[f"validation_{task_name}_labeled"]
            train_pos = values[f"train_{task_name}_positive"]
            val_pos = values[f"validation_{task_name}_positive"]
            supported = (train_n >= 100 and val_n >= 30 and
                         0 < train_pos < train_n and 0 < val_pos < val_n)
            support[phase][task_name] = {
                "status": "label_support_only_no_model" if supported else "not_estimable",
                "train_labeled": train_n, "validation_labeled": val_n,
                "reason": "No historical launch design features; model not fitted" if supported
                          else "Development row/class support gate failed; model not fitted"}
    report = {"status": "development_only_broad_trial_cohort_no_model",
              "unit": "one NCT per row; no program linkage inferred",
              "source_funnel": counts,
              "phase_strata": {key: coverage[key] for key in sorted(coverage)},
              "task_support": {key: support[key] for key in sorted(support)},
              "pure_phase_primary_strata": list(PURE_PHASES),
              "nonpure_phase_policy": "Reported separately; never pooled into pure Phase 1/2/3",
              "label_policy": "Unknown stays null. Completion does not require results. Significance is a posted-primary-p-value proxy among time-valid COMPLETED trials only.",
              "feature_columns": ["prediction_year"],
              "feature_warning": "Current protocol design and target results are not launch features; historical source versions are unavailable.",
              "result_detail_coverage": {"date_and_completion_eligible_nct_for_q2": len(p_eligible),
                                         "primary_analysis_nct_in_eligible_q2": len(decisions),
                                         "interpretable_primary_analysis_nct": sum(value is not None for value in decisions.values())},
              "final_holdout_sealed": True,
              "scientific_limits": [
                  "Current registry status and result content are retrospective; last-update gating is conservative, not a substitute for archived record versions.",
                  "Posted p<0.05 on any primary analysis is not the same as prespecified primary endpoint success, multiplicity adjustment, or clinical benefit.",
                  "Current phase designation may not match the first-public-posting version; phase is retrospective stratification only, not a validated launch feature.",
                  "Only acquired date-matched detail records can supply significance; no-results trials are not negative significance labels.",
                  "Trial-level breadth is separate from candidate exact-label earlier-phase program linkage."]}
    return frame, report


def safe_analysis_nct_ids(trials: pd.DataFrame, interventions: pd.DataFrame) -> set[str]:
    """Resolve dated, completed-only Q2 candidates before reading p-value data."""
    empty_analyses = pd.DataFrame(columns=["nct_id", "outcome_type", "p_significant_005"])
    candidates, _ = broad_cohort(trials, interventions, empty_analyses)
    completed = set(candidates.loc[candidates.completion_label.eq(True), "nct_id"])
    if not completed:
        return set()
    dates = candidates.set_index("nct_id").prediction_date.to_dict()
    safe = set()
    for row in trials.loc[trials.nct_id.isin(completed),
                          ["nct_id", "results_first_post_date", "last_update_post_date"]].itertuples(index=False):
        prediction = _day(dates[row.nct_id])
        boundary = TRAIN_END if prediction < TRAIN_END else HOLDOUT_FROM
        posted = _day(row.results_first_post_date)
        update = _day(row.last_update_post_date)
        if posted is not None and update is not None and prediction < max(posted, update) < boundary:
            safe.add(row.nct_id)
    return safe


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-trials", type=int, default=None,
                        help="Deterministic sorted-NCT pilot; omit for full source")
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Do not overwrite an existing broad cohort")
    paths = {name: args.dataset / f"{name}.parquet" for name in ("trials", "interventions", "analyses")}
    # Read only checkpoint metadata first. A full-column read here would
    # materialize sealed 2024+ outcome/status columns before the date firewall.
    index = pd.read_parquet(paths["trials"], columns=["nct_id", "first_post_date"])
    if index.nct_id.duplicated().any() or index.nct_id.isna().any():
        raise ValueError("Trial parquet has missing or duplicate NCT IDs")
    if args.max_trials is not None:
        if args.max_trials < 1:
            raise ValueError("max-trials must be positive")
        index = index.sort_values("nct_id").head(args.max_trials)
    pilot_source_n = len(index)
    checkpoint = index.first_post_date.map(_day)
    allowed_nct = set(index.loc[checkpoint.notna() & checkpoint.lt(HOLDOUT_FROM), "nct_id"])
    if allowed_nct:
        trials = pd.read_parquet(paths["trials"],
                                 filters=[("nct_id", "in", sorted(allowed_nct))])
    else:
        trials = pd.read_parquet(paths["trials"],
                                 filters=[("nct_id", "in", [])])
    wanted = allowed_nct
    interventions = pd.read_parquet(paths["interventions"])
    interventions = interventions.loc[interventions.nct_id.isin(wanted)]
    safe_p_ids = safe_analysis_nct_ids(trials, interventions)
    if safe_p_ids:
        # Predicate pushdown limits returned analysis rows to independently
        # established, as-of eligible NCTs. Do not load the whole p-value file.
        analyses = pd.read_parquet(paths["analyses"],
                                   filters=[("nct_id", "in", sorted(safe_p_ids))])
    else:
        analyses = pd.DataFrame(columns=["nct_id", "outcome_type", "p_significant_005"])
    rows, report = broad_cohort(trials, interventions, analyses)
    report["source_funnel"]["source_unique_nct"] = pilot_source_n
    report["source_funnel"]["sealed_2024_or_undated_first_post"] = pilot_source_n - len(allowed_nct)
    report["input_sha256"] = {name: sha256(path) for name, path in paths.items()}
    report["pilot_max_trials"] = args.max_trials
    report["analysis_predicate_nct_count"] = len(safe_p_ids)
    args.out.mkdir(parents=True)
    target = args.out / "broad_prediction_rows.parquet"
    rows.to_parquet(target, index=False)
    report["output_sha256"] = sha256(target)
    (args.out / "coverage_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "rows": len(rows),
                      "primary_analysis_nct": report["result_detail_coverage"]["primary_analysis_nct_in_eligible_q2"]}))


if __name__ == "__main__":
    main()
