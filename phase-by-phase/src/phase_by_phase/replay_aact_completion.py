"""Completion-only, prospective AACT cohort without a registration-lag gate.

This is separate from Jai's terminal-status/<=90-day parity replay. Ongoing
trials remain one-NCT rows with unknown labels, never negative outcomes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from .acquire import sha256
from .replay_aact import (_date, _view, _wilson, HOLDOUT, PURE_PHASES,
                          TRAIN_ORIGIN, verify_source)


TERMINAL = {"COMPLETED", "TERMINATED", "WITHDRAWN"}


def completion_rows(base: pd.DataFrame) -> pd.DataFrame:
    required = {"nct_id", "overall_status", "phase", "start_date", "first_submitted_date",
                "first_post_date", "completion_date", "completion_date_type",
                "last_update_post_date", "results_first_post_date"}
    if required - set(base):
        raise ValueError(f"Missing columns: {sorted(required - set(base))}")
    if base.nct_id.isna().any() or base.nct_id.duplicated().any():
        raise ValueError("AACT completion source must be unique by NCT")
    first_post = _date(base.first_post_date)
    # Direct callers may inject sealed sentinels. Slice before outcome access.
    dev = base.loc[first_post.notna() & first_post.lt(HOLDOUT)].copy()
    start = _date(dev.start_date)
    checkpoint = pd.concat([start, first_post.loc[dev.index]], axis=1).max(axis=1)
    submitted = _date(dev.first_submitted_date)
    completion = _date(dev.completion_date)
    update = _date(dev.last_update_post_date)
    results = _date(dev.results_first_post_date)
    actual = dev.completion_date_type.astype(str).str.upper().eq("ACTUAL")
    dev["reg_lag_days"] = (submitted - start).dt.days
    dev["public_post_lag_days"] = (first_post.loc[dev.index] - start).dt.days
    dev["lag_bucket"] = "missing_submitted_or_start"
    dev.loc[dev.reg_lag_days.lt(0), "lag_bucket"] = "submitted_before_start"
    dev.loc[dev.reg_lag_days.between(0, 90), "lag_bucket"] = "submitted_0_to_90_days_after_start"
    dev.loc[dev.reg_lag_days.gt(90), "lag_bucket"] = "submitted_more_than_90_days_after_start"
    dev["jai_lag_le_90"] = dev.reg_lag_days.le(90)
    dev["public_post_lag_bucket"] = "missing_start_or_post"
    dev.loc[dev.public_post_lag_days.lt(0), "public_post_lag_bucket"] = "posted_before_start"
    dev.loc[dev.public_post_lag_days.between(0, 90), "public_post_lag_bucket"] = "posted_0_to_90_days_after_start"
    dev.loc[dev.public_post_lag_days.gt(90), "public_post_lag_bucket"] = "posted_more_than_90_days_after_start"
    dev["audit_actual_completion_on_or_before_checkpoint"] = actual & completion.notna() & completion.le(checkpoint)
    dev["audit_own_results_on_or_before_checkpoint"] = results.notna() & results.le(checkpoint)
    dev["audit_update_before_actual_completion"] = actual & completion.notna() & update.notna() & update.lt(completion)
    dev["prospective_at_checkpoint"] = ~(dev.audit_actual_completion_on_or_before_checkpoint |
                                         dev.audit_own_results_on_or_before_checkpoint)
    dev = dev.loc[dev.prospective_at_checkpoint].copy()
    checkpoint = checkpoint.loc[dev.index]
    completion = completion.loc[dev.index]
    update = update.loc[dev.index]
    actual = actual.loc[dev.index]
    # The split follows start-year cohorts, not whether posting preceded 2020.
    # Old training outcomes must be public before 2016; 2016-19 validation
    # outcomes may accrue until the still-sealed 2024 boundary.
    boundary = pd.Series(TRAIN_ORIGIN, index=dev.index)
    boundary.loc[start.loc[dev.index].ge(TRAIN_ORIGIN)] = HOLDOUT
    label_valid = (actual & completion.notna() & update.notna() &
                   completion.gt(checkpoint) & update.ge(completion) &
                   update.lt(boundary) & dev.overall_status.isin(TERMINAL))
    dev["completion_label"] = pd.Series(pd.NA, index=dev.index, dtype="Int64")
    dev.loc[label_valid, "completion_label"] = dev.loc[label_valid, "overall_status"].eq("COMPLETED").astype(int)
    dev["completion_label_available_date"] = update.where(label_valid)
    dev["phase_stratum"] = dev.phase.fillna("MISSING_PHASE").str.upper().str.replace(" ", "", regex=False)
    dev["prediction_date"] = checkpoint
    return dev.sort_values("nct_id").reset_index(drop=True)


def _phase_prevalence(rows: pd.DataFrame) -> dict:
    start = _date(rows.start_date)
    posted = _date(rows.first_post_date)
    available = _date(rows.completion_label_available_date)
    report = {}
    for phase in PURE_PHASES:
        in_phase = rows.phase_stratum.eq(phase)
        train = rows.loc[in_phase & start.lt(TRAIN_ORIGIN) & posted.lt(TRAIN_ORIGIN) &
                         available.lt(TRAIN_ORIGIN) & rows.completion_label.notna()]
        validation = rows.loc[in_phase & start.ge(TRAIN_ORIGIN) &
                              start.lt(pd.Timestamp("2020-01-01")) & posted.lt(HOLDOUT) &
                              available.lt(HOLDOUT) & rows.completion_label.notna()]
        y_train = train.completion_label.astype(int)
        y_val = validation.completion_label.astype(int)
        nt, nv = len(train), len(validation)
        pt, pv = int(y_train.sum()), int(y_val.sum())
        entry = {"unit": "one NCT", "train_start_years": "2005-2015",
                 "validation_start_years": "2016-2019", "train_label_cutoff": "2016-01-01",
                 "validation_label_cutoff": "2024-01-01", "train_labeled": nt,
                 "train_positive": pt, "train_negative": nt - pt,
                 "validation_labeled": nv, "validation_positive": pv,
                 "validation_negative": nv - pv,
                 "validation_observed_rate_wilson95": _wilson(pv, nv)}
        if nt < 100 or nv < 30 or not (0 < pt < nt and 0 < pv < nv):
            entry.update(status="not_estimable", reason="Minimum row/class support gate failed")
        else:
            prevalence = pt / nt
            score = [prevalence] * nv
            entry.update(status="prevalence_baseline_only", train_prevalence=prevalence,
                         validation_observed_rate=pv / nv,
                         roc_auc=float(roc_auc_score(y_val, score)),
                         average_precision=float(average_precision_score(y_val, score)),
                         brier=float(brier_score_loss(y_val, score)),
                         calibration_gap=pv / nv - prevalence)
        report[phase] = entry
    return report


def _counts(rows: pd.DataFrame) -> dict:
    lag = rows.jai_lag_le_90
    labeled = rows.completion_label.notna()
    posted_late = rows.public_post_lag_days.gt(90)
    posted_after_start = rows.public_post_lag_days.gt(0)
    return {"all_prospective_nct": len(rows),
            "jai_lag_le_90_prospective_nct": int(lag.sum()),
            "incremental_without_lag_nct": int((~lag).sum()),
            "all_dated_terminal_labels": int(labeled.sum()),
            "lag_le_90_dated_terminal_labels": int((lag & labeled).sum()),
            "incremental_dated_terminal_labels": int((~lag & labeled).sum()),
            "first_public_post_after_start_nct": int(posted_after_start.sum()),
            "first_public_post_gt_90_days_after_start_nct": int(posted_late.sum()),
            "first_public_post_gt_90_days_dated_labels": int((posted_late & labeled).sum()),
            "unknown_or_censored_labels": int((~labeled).sum())}


def replay(tables: Path) -> tuple[pd.DataFrame, dict]:
    provenance = verify_source(tables, table_names=("studies", "interventions"))
    con = duckdb.connect()
    for name in ("studies", "interventions"):
        _view(con, name, tables)
    metadata = con.execute("""SELECT nct_id, study_first_posted_date, start_date
        FROM studies WHERE CAST(start_date AS DATE) BETWEEN DATE '2005-01-01'
        AND DATE '2019-12-31'""").df()
    first_post = _date(metadata.study_first_posted_date)
    allowed_ids = metadata.loc[first_post.notna() & first_post.lt(HOLDOUT), "nct_id"]
    con.register("allowed_ids", allowed_ids.to_frame())
    base = con.execute("""SELECT s.nct_id,
        UPPER(s.overall_status) AS overall_status,
        UPPER(REPLACE(s.phase, ' ', '')) AS phase,
        CAST(s.start_date AS DATE) AS start_date,
        CAST(s.study_first_submitted_date AS DATE) AS first_submitted_date,
        CAST(s.study_first_posted_date AS DATE) AS first_post_date,
        CAST(s.completion_date AS DATE) AS completion_date,
        UPPER(s.completion_date_type) AS completion_date_type,
        CAST(s.last_update_posted_date AS DATE) AS last_update_post_date,
        CAST(s.results_first_posted_date AS DATE) AS results_first_post_date
        FROM studies s JOIN allowed_ids a ON a.nct_id=s.nct_id
        WHERE UPPER(s.study_type)='INTERVENTIONAL'
          AND CAST(s.start_date AS DATE) BETWEEN DATE '2005-01-01' AND DATE '2019-12-31'
          AND EXISTS (SELECT 1 FROM interventions i WHERE i.nct_id=s.nct_id
                      AND UPPER(i.intervention_type)='DRUG')""").df()
    rows = completion_rows(base)
    labeled = rows.completion_label.notna()
    phase_status = {}
    for phase, group in rows.groupby("phase_stratum"):
        phase_status[phase] = {"counts": _counts(group),
                               "current_status_counts": group.overall_status.value_counts(dropna=False).to_dict(),
                               "lag_buckets": group.lag_bucket.value_counts(dropna=False).to_dict(),
                               "first_public_post_buckets": group.public_post_lag_bucket.value_counts(dropna=False).to_dict(),
                               "by_current_status": {
                                   str(status): _counts(status_rows)
                                   for status, status_rows in group.groupby("overall_status", dropna=False)},
                               "dated_labels_by_current_status": group.loc[group.completion_label.notna(),
                                                                              "overall_status"].value_counts().to_dict()}
    report = {"status": "development_only_completion_cohort_no_lag_gate",
              "unit": "one NCT per row", "source_provenance": provenance,
              "source_start_year_metadata_nct": len(metadata),
              "sealed_or_undated_first_post_before_outcome_read": len(metadata) - len(allowed_ids),
              "drug_interventional_first_post_before_2024": len(base),
              "excluded_nonprospective_at_checkpoint": len(base) - len(rows),
              "overall": _counts(rows),
              "overall_lag_buckets": rows.lag_bucket.value_counts(dropna=False).to_dict(),
              "overall_first_public_post_buckets": rows.public_post_lag_bucket.value_counts(dropna=False).to_dict(),
              "missingness": {"first_submitted_date": int(rows.first_submitted_date.isna().sum()),
                              "completion_date": int(rows.completion_date.isna().sum()),
                              "last_update_post_date": int(rows.last_update_post_date.isna().sum()),
                              "current_status": int(rows.overall_status.isna().sum())},
              "phase_status_and_lag": phase_status,
              "phase_prevalence": _phase_prevalence(rows),
              "feature_columns": [], "no_predictive_model_fitted": True,
              "lag_comparator_definition": "Jai <=90 uses first submitted minus start; this differs from first public posting minus start. Neither lag is a primary B6 gate.",
              "prediction_checkpoint": "later of actual start date and first public posting date",
              "label_rule": "ACTUAL completion after max(start, first public posting); last public update on/after completion and before development cutoff; COMPLETED=1, TERMINATED/WITHDRAWN=0, all others unknown",
              "scientific_limits": [
                  "Current AACT status and phase are retrospective; historical record versions are unavailable.",
                  "Last-update-posted is a conservative label-availability proxy, not proof of earlier version content.",
                  "Last-update-posted is not the actual status-transition date; true terminal-label availability may differ.",
                  "DuckDB CSV scans can physically parse sealed source bytes, but ID predicates prevent excluded outcomes entering derived rows.",
                  "No current status, enrollment, results or stopping reason is used as a predictor."]}
    if rows.nct_id.duplicated().any() or len(rows) != report["overall"]["all_prospective_nct"]:
        raise AssertionError("One-NCT cohort integrity failed")
    if (pd.to_datetime(rows.first_post_date) >= HOLDOUT).any():
        raise AssertionError("Sealed prediction checkpoint entered cohort")
    if ((pd.to_datetime(rows.completion_date) <= pd.to_datetime(rows.prediction_date)) & labeled).any():
        raise AssertionError("Known label predates prediction checkpoint")
    return rows, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Refusing to overwrite existing completion cohort")
    rows, report = replay(args.tables)
    args.out.mkdir(parents=True)
    target = args.out / "completion_prediction_rows.parquet"
    rows.to_parquet(target, index=False)
    report["output_sha256"] = sha256(target)
    (args.out / "coverage_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["overall"]))


if __name__ == "__main__":
    main()
