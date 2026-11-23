"""Development-only phase/task models; final holdout labels stay sealed.

This is retrospective because the source is a current registry version, not a
historical protocol archive. No score from this command is a final-test score.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


TRAIN_END = "2020-01-01"
VALIDATION_END = "2024-01-01"
NUMERIC_DESIGN = ["arm_count"]
CATEGORICAL_DESIGN = ["sponsor_class", "allocation", "masking"]
EVIDENCE = ["prior_result_count", "prior_primary_analysis_count", "prior_primary_tested_count",
            "prior_primary_significant_count", "prior_flow_retention_mean", "prior_sae_max_rate_mean"]
TASKS = {"completion": ("completion_label", "completion_label_available_date"),
         "significance": ("significance_label", "significance_label_available_date")}


def _metrics(y: np.ndarray, p: np.ndarray) -> dict:
    bins = np.minimum((np.asarray(p) * 5).astype(int), 4)
    calibration = [{"lower": i / 5, "upper": (i + 1) / 5,
                    "n": int((bins == i).sum()),
                    "mean_prediction": float(np.asarray(p)[bins == i].mean()) if (bins == i).any() else None,
                    "observed_rate": float(y[bins == i].mean()) if (bins == i).any() else None}
                   for i in range(5)]
    return {"n": int(len(y)), "positive": int(y.sum()),
            "roc_auc": float(roc_auc_score(y, p)),
            "average_precision": float(average_precision_score(y, p)),
            "brier": float(brier_score_loss(y, p)),
            "log_loss": float(log_loss(y, p, labels=[0, 1])),
            "calibration_bins": calibration,
            "threshold": 0.5,
            "confusion": {"tn": int(((y == 0) & (p < 0.5)).sum()),
                          "fp": int(((y == 0) & (p >= 0.5)).sum()),
                          "fn": int(((y == 1) & (p < 0.5)).sum()),
                          "tp": int(((y == 1) & (p >= 0.5)).sum())}}


def _paired_group_interval(y: np.ndarray, design: np.ndarray, updated: np.ndarray,
                           groups: np.ndarray, replicates: int = 300) -> dict:
    """Resample validation drug groups with fixed fitted models and split."""
    unique = np.unique(groups)
    if len(unique) < 10:
        return {"status": "not_estimable", "reason": "fewer than 10 validation groups"}
    indices = {group: np.flatnonzero(groups == group) for group in unique}
    rng = np.random.default_rng(545)
    delta = []
    for _ in range(replicates):
        drawn = rng.choice(unique, size=len(unique), replace=True)
        positions = np.concatenate([indices[group] for group in drawn])
        delta.append(np.mean((y[positions] - design[positions]) ** 2 -
                             (y[positions] - updated[positions]) ** 2))
    return {"status": "fixed_model_fixed_split_group_bootstrap",
            "replicates": replicates, "groups": len(unique),
            "low": float(np.quantile(delta, 0.025)),
            "high": float(np.quantile(delta, 0.975))}


def _forest(numeric: list[str], categorical: list[str]) -> Pipeline:
    prep = ColumnTransformer([
        ("num", SimpleImputer(strategy="median", keep_empty_features=True), numeric),
        ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
                          ("encode", OneHotEncoder(handle_unknown="ignore"))]), categorical),
    ])
    return Pipeline([("prep", prep), ("forest", RandomForestClassifier(
        n_estimators=200, min_samples_leaf=5, max_features="sqrt", random_state=545, n_jobs=1))])


def development_evaluation(rows: pd.DataFrame, bridge: pd.DataFrame) -> dict:
    """Evaluate on validation only; never access test labels or select on test.

    Fixed chronological partitions: train <2020, validation 2020–2023, and
    2024+ sealed. Label-version date must precede the next partition. Exact
    drug groups appearing in training are purged from validation.
    """
    required = {"nct_id", "program_id", "phase", "prediction_date", "historical_design_verified",
                *NUMERIC_DESIGN, *CATEGORICAL_DESIGN, *EVIDENCE,
                *(item for pair in TASKS.values() for item in pair)}
    missing = required - set(rows)
    if missing:
        raise ValueError(f"Missing prediction columns: {sorted(missing)}")
    group_map = bridge[["program_id", "drug_group"]].drop_duplicates()
    if group_map.duplicated("program_id").any():
        raise ValueError("Program has multiple exact-drug groups")
    frame = rows.merge(group_map, on="program_id", validate="many_to_one")
    if frame.duplicated(["nct_id", "program_id"]).any():
        raise ValueError("Duplicate trial/program rows")
    dates = pd.to_datetime(frame.prediction_date, errors="coerce")
    if dates.isna().any():
        raise ValueError("Malformed prediction date")
    # Current protocol fields are not treated as historical launch values unless
    # the source's last update predates that launch. A year feature is computed
    # from the prediction date itself and is always available.
    for col in NUMERIC_DESIGN + CATEGORICAL_DESIGN:
        frame.loc[~frame.historical_design_verified.eq(True), col] = np.nan
    frame["launch_year"] = dates.dt.year.astype(float)
    phase_report = {}
    for phase in ("PHASE1", "PHASE2", "PHASE3"):
        for task, (label, available) in TASKS.items():
            key = f"{phase}:{task}"
            phase_rows = frame.loc[frame.phase.eq(phase)]
            phase_dates = pd.to_datetime(phase_rows.prediction_date)
            sealed_count = int((phase_dates >= VALIDATION_END).sum())
            # Drop sealed rows before accessing availability or label values.
            subset = phase_rows.loc[phase_dates < VALIDATION_END].copy()
            pdate = pd.to_datetime(subset.prediction_date)
            adate = pd.to_datetime(subset[available], errors="coerce")
            train = subset.loc[(pdate < TRAIN_END) & (adate < TRAIN_END) & subset[label].notna()].copy()
            val = subset.loc[(pdate >= TRAIN_END) & (pdate < VALIDATION_END) &
                             (adate < VALIDATION_END) & subset[label].notna()].copy()
            val = val.loc[~val.drug_group.isin(set(train.drug_group))]
            counts = {"train_rows": len(train), "train_positive": int(train[label].eq(True).sum()),
                      "validation_rows": len(val), "validation_positive": int(val[label].eq(True).sum()),
                      "sealed_rows_2024_onward": sealed_count}
            # No outcome inspection or score computation on 2024+ rows.
            if len(train) < 100 or len(val) < 30 or train[label].nunique() < 2 or val[label].nunique() < 2:
                phase_report[key] = {"status": "not_estimable", "counts": counts,
                                     "reason": "development class/row support gate failed"}
                continue
            y_train = train[label].astype(int).to_numpy()
            y_val = val[label].astype(int).to_numpy()
            rate = float(y_train.mean())
            result = {"status": "development_only", "counts": counts,
                      "prevalence": _metrics(y_val, np.full(len(val), rate))}
            for features in ("design", "design_plus_earlier"):
                if features == "design_plus_earlier":
                    matched_train = train.loc[train.prior_result_count.gt(0)].copy()
                    matched_val = val.loc[val.prior_result_count.gt(0)].copy()
                    # Compare both feature sets on this same restricted cohort,
                    # separately below; do not claim improvement otherwise.
                    continue
                numeric = ["launch_year"] + NUMERIC_DESIGN
                categorical = CATEGORICAL_DESIGN
                model = _forest(numeric, categorical)
                model.fit(train[numeric + categorical], y_train)
                result["design_forest"] = _metrics(y_val, model.predict_proba(val[numeric + categorical])[:, 1])
            matched = {"train_rows": len(matched_train), "validation_rows": len(matched_val),
                       "train_positive": int(matched_train[label].eq(True).sum()),
                       "validation_positive": int(matched_val[label].eq(True).sum())}
            if (len(matched_train) < 100 or len(matched_val) < 30 or
                    matched_train[label].nunique() < 2 or matched_val[label].nunique() < 2):
                result["matched_evidence_comparison"] = {"status": "not_estimable", "counts": matched}
            else:
                matched_result = {"status": "development_only", "counts": matched}
                predictions = {}
                for name, evidence in (("design", []), ("design_plus_earlier", EVIDENCE)):
                    numeric = ["launch_year"] + NUMERIC_DESIGN + evidence
                    categorical = CATEGORICAL_DESIGN
                    model = _forest(numeric, categorical)
                    model.fit(matched_train[numeric + categorical], matched_train[label].astype(int))
                    probs = model.predict_proba(matched_val[numeric + categorical])[:, 1]
                    predictions[name] = probs
                    matched_result[name] = _metrics(matched_val[label].astype(int).to_numpy(), probs)
                matched_result["brier_improvement"] = matched_result["design"]["brier"] - matched_result["design_plus_earlier"]["brier"]
                matched_result["brier_improvement_interval"] = _paired_group_interval(
                    matched_val[label].astype(int).to_numpy(), predictions["design"],
                    predictions["design_plus_earlier"], matched_val.drug_group.to_numpy())
                result["matched_evidence_comparison"] = matched_result
            phase_report[key] = result
    return {"status": "development_only_no_final_holdout_evaluation", "split": {
        "train_prediction_before": TRAIN_END, "train_label_available_before": TRAIN_END,
        "validation_prediction_start": TRAIN_END, "validation_prediction_before": VALIDATION_END,
        "validation_label_available_before": VALIDATION_END,
        "final_holdout_prediction_from": VALIDATION_END, "final_holdout_sealed": True},
        "historical_version_warning": "Current records do not prove at-launch feature content; only source last-update-gated design is used.",
        "tasks": phase_report}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Do not overwrite a previous development evaluation")
    result = development_evaluation(pd.read_parquet(args.dataset / "prediction_rows.parquet"),
                                    pd.read_parquet(args.dataset / "program_trials.parquet"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value["status"] for key, value in result["tasks"].items()}, indent=2))


if __name__ == "__main__":
    main()
