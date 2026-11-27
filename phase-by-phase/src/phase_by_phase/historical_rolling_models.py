"""Year-by-year development validation of first-public drug-trial designs.

The final 2024+ outcome archive is never loaded. A trial's first later event
is chosen once; each fold then asks whether that event was known at its cutoff.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from . import historical_dev_models as dev


YEARS = (2016, 2017, 2018, 2019)
VALIDATION_CUTOFF = pd.Timestamp("2024-01-01")


def known_as_of(rows: pd.DataFrame, task: str, cutoff: pd.Timestamp) -> pd.Series:
    """The first event must predate cutoff; a known reversal makes it unknown."""
    label_col, date_col = (("completion_label", "completion_label_date") if task == "completion"
                           else ("significance_label", "significance_label_date"))
    event_date = pd.to_datetime(rows[date_col])
    reversal = pd.to_datetime(rows["reversal_date"])
    good = (rows[label_col].notna() & (event_date > pd.to_datetime(rows.first_public_date))
            & (event_date < cutoff) & (reversal.isna() | (reversal >= cutoff)))
    if task != "completion":
        completion_date = pd.to_datetime(rows.completion_label_date)
        good &= (rows.completion_label == 1) & (completion_date < cutoff)
    return rows[label_col].where(good)


def fold_rows(rows: pd.DataFrame, year: int, task: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if year not in YEARS:
        raise ValueError(f"Unsupported development year: {year}")
    cutoff = pd.Timestamp(f"{year}-01-01")
    checkpoint = pd.to_datetime(rows.first_public_date)
    train = rows[(checkpoint >= pd.Timestamp("2005-01-01")) & (checkpoint < cutoff)].copy()
    valid = rows[(checkpoint >= cutoff) & (checkpoint < pd.Timestamp(f"{year + 1}-01-01"))].copy()
    train["fold_label"] = known_as_of(train, task, cutoff)
    valid["fold_label"] = known_as_of(valid, task, VALIDATION_CUTOFF)
    if set(train.nct_id) & set(valid.nct_id):
        raise ValueError("Fold train/validation NCT overlap")
    return train, valid


def score_fold(train: pd.DataFrame, valid: pd.DataFrame, year: int,
               task: str) -> tuple[list[dict], list[pd.DataFrame]]:
    metrics: list[dict] = []
    predictions: list[pd.DataFrame] = []
    for p in dev.PHASES:
        t = train[(train.pure_phase == p) & train.fold_label.notna()]
        v = valid[(valid.pure_phase == p) & valid.fold_label.notna()]
        for subset in ("broad", "arm_rich"):
            tr = t if subset == "broad" else t[t.arm_row_count > 0]
            va = v if subset == "broad" else v[v.arm_row_count > 0]
            counts = {f"{part}_{klass}": int((frame.fold_label == klass).sum())
                      for part, frame in (("train", tr), ("validation", va))
                      for klass in (0, 1)}
            support = (len(tr) >= dev.MIN_TRAIN and len(va) >= dev.MIN_VALID
                       and all(count >= dev.MIN_CLASS for count in counts.values()))
            base = {"year": year, "task": task, "phase": p, "subset": subset,
                    "train_rows": len(tr), "validation_rows": len(va), **counts,
                    "estimable": bool(support),
                    "reason": None if support else
                    "minimum_100_train_50_validation_10_per_class_not_met"}
            feature_sets = (("all_design", dev.FEATURES),) if subset == "broad" else (
                ("all_design", dev.FEATURES), ("without_arm_features", dev.NO_ARM_FEATURES))
            if not support:
                metrics.extend({**base, "feature_set": label, "model": None}
                               for label, _ in feature_sets)
                continue
            y_train, y_valid = tr.fold_label.astype(int), va.fold_label.astype(int)
            for feature_set, columns in feature_sets:
                for name in ("prevalence", "random_forest", "hist_gradient_boosting"):
                    if name == "prevalence":
                        prob = np.repeat(y_train.mean(), len(va))
                    else:
                        predictor = dev.model(name, columns)
                        if name == "random_forest":
                            predictor.set_params(model__n_estimators=1000)
                        predictor.fit(tr[list(columns)], y_train)
                        prob = predictor.predict_proba(va[list(columns)])[:, 1]
                    metrics.append({**base, "feature_set": feature_set, "model": name,
                                    "roc_auc": float(roc_auc_score(y_valid, prob)),
                                    "average_precision": float(average_precision_score(y_valid, prob)),
                                    "brier": float(brier_score_loss(y_valid, prob))})
                    predictions.append(pd.DataFrame({
                        "nct_id": va.nct_id.to_numpy(), "validation_year": year,
                        "checkpoint_date": va.first_public_date.to_numpy(),
                        "task": task, "phase": p, "subset": subset,
                        "feature_set": feature_set, "model": name,
                        "label": y_valid.to_numpy(), "probability": prob}))
    return metrics, predictions


def run(source: Path, design: Path, results: Path, out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"Refusing overwrite: {out}")
    design_manifest = json.loads((design.parent / "manifest.json").read_text())
    results_manifest = json.loads((results / "manifest.json").read_text())
    if (design_manifest["source_root"] != str(source.resolve())
            or results_manifest["source_root"] != str(source.resolve())):
        raise ValueError("Pinned source root mismatch")
    if dev.digest(design) != design_manifest["output_sha256"][design.name]:
        raise ValueError("Pinned design hash mismatch")
    for name in ("results_outcome_measures_clean.parquet", "results_outcome_analyses_clean.parquet"):
        if dev.digest(results / name) != results_manifest["output_files_sha256"].get(name):
            raise ValueError(f"Pinned result hash mismatch: {name}")
    dev.verify_core_parts(sorted((source / "core").glob("*.parquet")),
                          design_manifest["verified_input_sha256"])
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'")
    con.execute("SET threads=2")
    out.mkdir(parents=True)
    (out / "duckdb_spill").mkdir()
    con.execute(f"SET temp_directory={dev.literal(out / 'duckdb_spill')}")
    try:
        dev._source_view(con, source)
        rows = dev.build_labels(con, design, results, rolling=True)
    finally:
        con.close()
    if rows.nct_id.duplicated().any():
        raise ValueError("Duplicate one-NCT modeling rows")
    if rows[list(dev.FLAGS)].isna().any().any():
        raise ValueError("Missing Boolean flag")
    rows[list(dev.FLAGS)] = rows[list(dev.FLAGS)].astype("int8")
    metrics: list[dict] = []
    predictions: list[pd.DataFrame] = []
    funnel: list[dict] = []
    for year in YEARS:
        for task in ("completion", "reported_primary_p_lt_0_05"):
            train, valid = fold_rows(rows, year, task)
            observation_days = (VALIDATION_CUTOFF - pd.to_datetime(valid.first_public_date)).dt.days
            funnel.append({"year": year, "task": task,
                           "train_checkpoint_rows": len(train),
                           "train_known_labels": int(train.fold_label.notna().sum()),
                           "validation_checkpoint_rows": len(valid),
                           "validation_known_labels": int(valid.fold_label.notna().sum()),
                           "validation_unknown_labels": int(valid.fold_label.isna().sum()),
                           "validation_known_fraction": float(valid.fold_label.notna().mean()) if len(valid) else None,
                           "validation_observation_days_min": int(observation_days.min()) if len(valid) else None,
                           "validation_observation_days_median": float(observation_days.median()) if len(valid) else None,
                           "validation_observation_days_max": int(observation_days.max()) if len(valid) else None})
            fold_metrics, fold_predictions = score_fold(train, valid, year, task)
            metrics.extend(fold_metrics)
            predictions.extend(fold_predictions)
    if predictions:
        pd.concat(predictions, ignore_index=True).to_parquet(
            out / "validation_predictions.parquet", index=False)
    # Store dated rows for independent eligibility and missingness review.
    rows[["nct_id", "first_public_nct_version", "first_public_date", "pure_phase",
          "completion_label", "completion_label_date", "significance_label",
          "significance_label_date", "reversal_date", *dev.FEATURES]].to_parquet(
              out / "development_rows.parquet", index=False)
    report = {"status": "rolling_development_only_no_final_holdout_scored",
              "source_commit": design_manifest["source_commit"],
              "source_root": str(source.resolve()), "design_root": str(design.parent.resolve()),
              "results_root": str(results.resolve()), "years": YEARS,
              "training_rule": "2005 through prior year; first label public strictly before fold Jan 1",
              "validation_rule": "first-public in fold year; label after checkpoint and before 2024-01-01",
              "reversal_rule": "known reversal strictly before as-of cutoff makes label unknown",
              "features": dev.FEATURES, "cohort_rule": "first-public recorded DRUG intervention",
              "random_forest_trees": 1000,
              "minimum_support": {"train": dev.MIN_TRAIN, "validation": dev.MIN_VALID,
                                  "each_class_per_partition": dev.MIN_CLASS},
              "funnel": funnel, "metrics": metrics,
              "input_sha256": {"design": dev.digest(design),
                               "design_manifest": dev.digest(design.parent / "manifest.json"),
                               "results_manifest": dev.digest(results / "manifest.json")},
              "code_sha256": {"rolling": dev.digest(Path(__file__)),
                              "baseline": dev.digest(Path(dev.__file__))}}
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    report["output_sha256"] = {p.name: dev.digest(p) for p in out.iterdir() if p.is_file()}
    (out / "manifest.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "design", "results", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = run(args.source, args.design, args.results, args.out)
    print(json.dumps({"status": report["status"], "funnel": report["funnel"],
                      "metrics": report["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
