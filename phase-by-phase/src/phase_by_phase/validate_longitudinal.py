"""Prespecified rolling-origin checks on development data only.

The 2024+ holdout is partitioned before any outcome or availability column is
read. These folds diagnose stability; they are not independent final tests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .model_structured import (CATEGORICAL_DESIGN, EVIDENCE, NUMERIC_DESIGN,
                               TASKS, VALIDATION_END, _design_feature_support,
                               _forest, _metrics)


WINDOWS = (("2016-01-01", "2018-01-01"),
           ("2018-01-01", "2020-01-01"),
           ("2020-01-01", "2022-01-01"),
           ("2022-01-01", "2024-01-01"))
MIN_TRAIN = 100
MIN_VALIDATION = 30


def _dates(values: pd.Series, name: str) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce", format="%Y-%m-%d")
    if values.notna().any() and dates[values.notna()].isna().any():
        raise ValueError(f"Malformed {name}")
    return dates


def longitudinal_evaluation(rows: pd.DataFrame, bridge: pd.DataFrame) -> dict:
    """Evaluate fixed two-year windows without reading sealed outcomes.

    Each training label must have been public before the window starts; each
    validation label before its end. Validation identities seen in training are
    purged. The feature schema and model settings never change across folds.
    """
    required = {"nct_id", "program_id", "phase", "prediction_date",
                "historical_design_verified", "prior_result_count", "max_evidence_date",
                *NUMERIC_DESIGN, *CATEGORICAL_DESIGN, *EVIDENCE,
                *(column for pair in TASKS.values() for column in pair)}
    missing = required - set(rows)
    if missing:
        raise ValueError(f"Missing prediction columns: {sorted(missing)}")
    if not {"program_id", "drug_group"}.issubset(bridge):
        raise ValueError("Bridge lacks program_id or drug_group")
    if rows.duplicated(["nct_id", "program_id"]).any():
        raise ValueError("Duplicate trial/program rows")
    dates = _dates(rows.prediction_date, "prediction_date")
    if dates.isna().any():
        raise ValueError("Missing prediction_date")
    sealed_count = int((dates >= VALIDATION_END).sum())
    # This slice must happen before parsing or testing labels, available dates,
    # or earlier-result dates. In particular, callers may supply sealed sentinels.
    dev = rows.loc[dates < VALIDATION_END].copy()
    dev["_prediction_ts"] = dates.loc[dates < VALIDATION_END]
    drug_groups = bridge[["program_id", "drug_group"]].drop_duplicates()
    if drug_groups.duplicated("program_id").any():
        raise ValueError("Program has multiple exact-drug groups")
    dev = dev.merge(drug_groups, on="program_id", validate="many_to_one")
    if dev.drug_group.isna().any():
        raise ValueError("Development program lacks exact-drug group")
    evidence_date = _dates(dev.max_evidence_date, "max_evidence_date")
    evidence_count = pd.to_numeric(dev.prior_result_count, errors="coerce")
    if (evidence_count.isna() | (evidence_count < 0) |
            (evidence_count % 1 != 0)).any():
        raise ValueError("Invalid earlier-result count")
    if ((evidence_count.gt(0) & evidence_date.isna()) |
            (evidence_count.eq(0) & evidence_date.notna()) |
            (evidence_date > dev._prediction_ts)).any():
        raise ValueError("Earlier-trial evidence is undated or after prediction")
    # Do not train on present-day protocol fields unless the whole source record
    # is certified unchanged since prediction. The flag itself is never a feature.
    verified = dev.historical_design_verified.eq(True)
    for column in NUMERIC_DESIGN + CATEGORICAL_DESIGN:
        dev.loc[~verified, column] = np.nan
    dev["launch_year"] = dev._prediction_ts.dt.year.astype(float)
    feature_names = ["launch_year", *NUMERIC_DESIGN, *CATEGORICAL_DESIGN]
    reports = []
    for start, end in WINDOWS:
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        for phase in ("PHASE1", "PHASE2", "PHASE3"):
            phase_rows = dev.loc[dev.phase.eq(phase)]
            for task, (label, available) in TASKS.items():
                available_ts = _dates(phase_rows[available], available)
                if (available_ts.notna() & (available_ts <= phase_rows._prediction_ts)).any():
                    raise ValueError(f"{available} is not after prediction_date")
                eligible = phase_rows.loc[phase_rows[label].notna()].copy()
                if not eligible[label].isin([True, False, 0, 1]).all():
                    raise ValueError(f"Invalid {label}")
                eligible["_available_ts"] = available_ts.loc[eligible.index]
                if eligible._available_ts.isna().any():
                    raise ValueError(f"Labeled row lacks {available}")
                train = eligible.loc[(eligible._prediction_ts < start_ts) &
                                     (eligible._available_ts < start_ts)]
                candidate_val = eligible.loc[(eligible._prediction_ts >= start_ts) &
                                             (eligible._prediction_ts < end_ts) &
                                             (eligible._available_ts < end_ts)]
                val = candidate_val.loc[~candidate_val.drug_group.isin(set(train.drug_group))]
                if not set(train.drug_group).isdisjoint(val.drug_group):
                    raise AssertionError("Train/validation drug identities overlap")
                counts = {"train": int(len(train)), "train_unique_nct": int(train.nct_id.nunique()),
                          "train_positive": int(train[label].eq(True).sum()),
                          "validation_candidates": int(len(candidate_val)),
                          "validation_candidate_unique_nct": int(candidate_val.nct_id.nunique()),
                          "validation_purged_identity": int(len(candidate_val) - len(val)),
                          "validation": int(len(val)), "validation_unique_nct": int(val.nct_id.nunique()),
                          "validation_positive": int(val[label].eq(True).sum())}
                item = {"window_start": start, "window_end": end, "phase": phase,
                        "task": task, "counts": counts,
                        "identity_overlap_after_purge": 0,
                        "feature_support": _design_feature_support(train, val)}
                if (len(train) < MIN_TRAIN or len(val) < MIN_VALIDATION or
                        train[label].nunique() < 2 or val[label].nunique() < 2):
                    item.update(status="not_estimable", model_input_status="not_fitted",
                                reason="development class/row support gate failed")
                else:
                    y_train = train[label].astype(int).to_numpy()
                    y_val = val[label].astype(int).to_numpy()
                    rate = float(y_train.mean())
                    model = _forest(["launch_year", *NUMERIC_DESIGN], CATEGORICAL_DESIGN)
                    model.fit(train[feature_names], y_train)
                    item.update(status="development_only",
                                model_input_status=item["feature_support"]["model_input_status"],
                                prevalence=_metrics(y_val, np.full(len(val), rate)),
                                design_forest=_metrics(y_val, model.predict_proba(val[feature_names])[:, 1]))
                reports.append(item)
    return {"status": "development_only_no_final_holdout_evaluation",
            "sealed_rows_2024_onward": sealed_count,
            "unit": "NCT x candidate program; rows are not independent trials",
            "windows": [{"start": start, "end": end} for start, end in WINDOWS],
            "feature_schema": feature_names,
            "feature_policy": "Current design fields masked unless source last update is no later than prediction; earlier evidence must be dated no later than prediction.",
            "caveat": "Current registry records and exact-label identities are not verified historical protocol versions or clinical program links. Identity purge is within each phase/task fold, not a globally unseen-drug guarantee.",
            "folds": reports}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Do not overwrite a previous longitudinal evaluation")
    report = longitudinal_evaluation(pd.read_parquet(args.dataset / "prediction_rows.parquet"),
                                     pd.read_parquet(args.dataset / "program_trials.parquet"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "folds": len(report["folds"]),
                      "estimable": sum(item["status"] == "development_only" for item in report["folds"]) }))


if __name__ == "__main__":
    main()
