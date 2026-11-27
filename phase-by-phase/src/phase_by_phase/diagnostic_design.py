"""Retrospective AACT design and dated-sponsor ablation on B6 rows.

Current AACT protocol, phase and sponsor values lack registration-era versions.
Scores from this module are diagnostics, not at-launch predictive claims.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .acquire import sha256
from .replay_aact import EXPECTED_ARCHIVE_SHA256, HOLDOUT, PURE_PHASES, TRAIN_ORIGIN, _date, _hash_stream


SOURCE_TABLES = ("studies", "sponsors", "designs", "eligibilities", "conditions",
                 "design_outcomes", "browse_conditions", "design_groups", "interventions")
CATEGORICAL = ("phase_stratum", "sponsor_class", "allocation", "intervention_model",
               "masking", "primary_purpose", "elig_gender", "disease_area")
NUMERIC = ("start_year", "number_of_arms", "has_dmc", "n_conditions",
           "n_primary_outcomes", "n_secondary_outcomes", "n_mesh_terms",
           "has_placebo_arm", "has_active_comparator", "n_drug_interventions",
           "elig_min_age_years", "elig_max_age_years", "elig_healthy_volunteers")
SPONSOR = ("sponsor_prior_finished", "sponsor_prior_stop_rate", "sponsor_no_prior_finished")
DESIGN_FEATURES = CATEGORICAL + NUMERIC
DESIGN_SPONSOR_FEATURES = DESIGN_FEATURES + SPONSOR
FORBIDDEN = {"overall_status", "completion_label", "completion_date", "last_update_post_date",
             "results_first_post_date", "post_enrollment_final", "enrollment", "n_sites",
             "why_stopped", "reg_lag_days", "public_post_lag_days"}
DISEASE_MESH = (("oncology", "Neoplasms"), ("cardiovascular", "Cardiovascular Diseases"),
                ("neuro", "Nervous System Diseases"), ("mental", "Mental Disorders"),
                ("infection", "Infections"), ("respiratory", "Respiratory Tract Diseases"),
                ("digestive", "Digestive System Diseases"),
                ("metabolic", "Nutritional and Metabolic Diseases"),
                ("endocrine", "Endocrine System Diseases"),
                ("immune", "Immune System Diseases"),
                ("skin", "Skin and Connective Tissue Diseases"),
                ("musculoskeletal", "Musculoskeletal Diseases"),
                ("urogenital", "Urogenital Diseases"),
                ("blood", "Hemic and Lymphatic Diseases"), ("eye", "Eye Diseases"))


def verify_source(tables: Path) -> dict:
    archive = tables.parent / "20261029_aact_flat.zip"
    if not archive.is_file():
        raise FileNotFoundError(archive)
    archive_hash = sha256(archive)
    if archive_hash != EXPECTED_ARCHIVE_SHA256:
        raise ValueError("AACT archive hash mismatch")
    consumed = {}
    with zipfile.ZipFile(archive) as zipped:
        for name in SOURCE_TABLES:
            path = tables / f"{name}.txt"
            if not path.is_file():
                raise FileNotFoundError(path)
            info = zipped.getinfo(f"{name}.txt")
            file_hash = sha256(path)
            with zipped.open(info) as stream:
                zip_hash = _hash_stream(stream)
            if path.stat().st_size != info.file_size or file_hash != zip_hash:
                raise ValueError(f"Extracted AACT table differs from archive: {name}")
            consumed[name] = {"sha256": file_hash, "bytes": info.file_size}
    return {"archive_sha256": archive_hash, "archive_bytes": archive.stat().st_size,
            "tables_verified_against_archive": consumed}


def _view(con: duckdb.DuckDBPyConnection, name: str, tables: Path) -> None:
    if name not in SOURCE_TABLES:
        raise ValueError("Unexpected AACT table")
    path = str((tables / f"{name}.txt").resolve()).replace("'", "''")
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv('{path}', "
                "delim='|', header=true, quote='\"', escape='\"', sample_size=-1)")


def assert_whitelist(columns: tuple[str, ...]) -> None:
    if not columns or len(columns) != len(set(columns)) or set(columns) & FORBIDDEN:
        raise ValueError("Invalid or leaky feature whitelist")
    if not set(columns).issubset(set(DESIGN_SPONSOR_FEATURES)):
        raise ValueError("Unapproved feature in model input")


def _one_nct(frame: pd.DataFrame, name: str) -> None:
    if frame.nct_id.isna().any() or frame.nct_id.duplicated().any():
        raise ValueError(f"{name} is not one NCT per row")


def _age_years(values: pd.Series) -> pd.Series:
    text = values.fillna("").astype(str).str.lower()
    parsed = text.str.extract(r"(\d+(?:\.\d+)?)\s*(year|month|week|day)")
    scale = parsed[1].map({"year": 1.0, "month": 1 / 12, "week": 7 / 365, "day": 1 / 365})
    return pd.to_numeric(parsed[0], errors="coerce") * scale


def build_sponsor_history(rows: pd.DataFrame, leads: pd.DataFrame) -> pd.DataFrame:
    """Other-trial terminal outcomes posted strictly before target checkpoint."""
    _one_nct(rows, "B6 rows")
    _one_nct(leads, "lead sponsors")
    joined = rows[["nct_id", "prediction_date", "start_date", "first_post_date",
                   "completion_date", "completion_date_type", "last_update_post_date",
                   "completion_label", "completion_label_available_date"]].merge(
        leads[["nct_id", "lead_sponsor_name"]], on="nct_id", how="left", validate="one_to_one")
    joined["checkpoint"] = _date(joined.prediction_date)
    joined["available"] = _date(joined.completion_label_available_date)
    joined["start"] = _date(joined.start_date)
    joined["first_post"] = _date(joined.first_post_date)
    joined["completion"] = _date(joined.completion_date)
    joined["last_update"] = _date(joined.last_update_post_date)
    if joined.checkpoint.ge(HOLDOUT).any():
        raise ValueError("Sealed checkpoint in sponsor source")
    known = joined.completion_label.notna()
    invalid = known & (joined.available.isna() | joined.start.isna() |
                       joined.first_post.isna() | joined.completion.isna() |
                       joined.completion_date_type.ne("ACTUAL") |
                       joined.completion.le(joined.checkpoint) |
                       joined.last_update.lt(joined.completion) |
                       joined.available.lt(joined.completion) |
                       joined.available.lt(joined.last_update) |
                       joined.available.le(joined.checkpoint) |
                       joined.available.ge(HOLDOUT))
    if invalid.any():
        raise ValueError("Sponsor source has nonprospective or unavailable label")
    records = []
    for sponsor, group in joined.groupby("lead_sponsor_name", dropna=False):
        if pd.isna(sponsor):
            for row in group.itertuples(index=False):
                records.append((row.nct_id, 0, np.nan, 1, None))
            continue
        prior = group.loc[group.completion_label.notna() & group.available.notna()]
        prior = prior.sort_values("available")
        dates = prior.available.to_numpy(dtype="datetime64[ns]")
        labels = prior.completion_label.astype(int).to_numpy()
        stopped = np.concatenate([[0], np.cumsum(labels == 0)])
        prior_ids = prior.nct_id.to_numpy()
        id_index = {nct: index for index, nct in enumerate(prior_ids)}
        for row in group.itertuples(index=False):
            limit = int(np.searchsorted(dates, np.datetime64(row.checkpoint), side="left"))
            own_index = id_index.get(row.nct_id)
            own_prior = own_index is not None and own_index < limit
            count = limit - int(own_prior)
            n_stop = int(stopped[limit] - int(own_prior and labels[own_index] == 0))
            latest_index = limit - 1
            if own_prior and latest_index == own_index:
                latest_index -= 1
            latest = prior.available.iloc[latest_index] if count else None
            records.append((row.nct_id, count, (n_stop + 2.5) / (count + 5) if count else np.nan,
                            int(count == 0), latest))
    result = pd.DataFrame(records, columns=["nct_id", *SPONSOR, "sponsor_latest_prior_available"])
    _one_nct(result, "sponsor history")
    checked = result.merge(joined[["nct_id", "checkpoint"]], on="nct_id", validate="one_to_one")
    if (_date(checked.sponsor_latest_prior_available) >= checked.checkpoint).any():
        raise AssertionError("Future sponsor outcome entered history")
    return result


def load_design(tables: Path, target_ids: pd.Series, history_ids: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect()
    for name in SOURCE_TABLES:
        _view(con, name, tables)
    con.register("target_ids", target_ids.to_frame(name="nct_id"))
    con.register("history_ids", history_ids.to_frame(name="nct_id"))
    leads = con.execute("""SELECT s.nct_id, MAX(s.name) AS lead_sponsor_name,
        MAX(UPPER(s.agency_class)) AS sponsor_class
        FROM sponsors s JOIN history_ids h ON s.nct_id=h.nct_id
        WHERE LOWER(s.lead_or_collaborator)='lead' GROUP BY s.nct_id""").df()
    _one_nct(leads, "AACT lead sponsor aggregate")
    design = con.execute("""SELECT t.nct_id, s.number_of_arms, s.has_dmc,
        d.allocation, d.intervention_model, d.masking, d.primary_purpose,
        e.gender AS elig_gender, e.healthy_volunteers AS elig_healthy_volunteers,
        e.minimum_age, e.maximum_age,
        c.n_conditions, o.n_primary_outcomes, o.n_secondary_outcomes,
        m.n_mesh_terms, m.mesh_terms,
        g.has_placebo_arm, g.has_active_comparator, i.n_drug_interventions
        FROM target_ids t
        LEFT JOIN studies s ON s.nct_id=t.nct_id
        LEFT JOIN designs d ON d.nct_id=t.nct_id
        LEFT JOIN eligibilities e ON e.nct_id=t.nct_id
        LEFT JOIN (SELECT c.nct_id, COUNT(*) AS n_conditions FROM conditions c
                   JOIN target_ids t ON c.nct_id=t.nct_id GROUP BY c.nct_id) c ON c.nct_id=t.nct_id
        LEFT JOIN (SELECT o.nct_id,
                   SUM(CASE WHEN LOWER(o.outcome_type)='primary' THEN 1 ELSE 0 END) AS n_primary_outcomes,
                   SUM(CASE WHEN LOWER(o.outcome_type)='secondary' THEN 1 ELSE 0 END) AS n_secondary_outcomes
                   FROM design_outcomes o JOIN target_ids t ON o.nct_id=t.nct_id
                   GROUP BY o.nct_id) o ON o.nct_id=t.nct_id
        LEFT JOIN (SELECT m.nct_id, COUNT(DISTINCT m.mesh_term) AS n_mesh_terms,
                   STRING_AGG(DISTINCT m.mesh_term, '|') AS mesh_terms
                   FROM browse_conditions m JOIN target_ids t ON m.nct_id=t.nct_id
                   WHERE LOWER(m.mesh_type) IN ('mesh-list', 'mesh-ancestor')
                   GROUP BY m.nct_id) m ON m.nct_id=t.nct_id
        LEFT JOIN (SELECT g.nct_id,
                   MAX(CASE WHEN UPPER(g.group_type)='PLACEBO_COMPARATOR' THEN 1 ELSE 0 END) AS has_placebo_arm,
                   MAX(CASE WHEN UPPER(g.group_type)='ACTIVE_COMPARATOR' THEN 1 ELSE 0 END) AS has_active_comparator
                   FROM design_groups g JOIN target_ids t ON g.nct_id=t.nct_id
                   GROUP BY g.nct_id) g ON g.nct_id=t.nct_id
        LEFT JOIN (SELECT i.nct_id, COUNT(DISTINCT LOWER(i.name)) AS n_drug_interventions
                   FROM interventions i JOIN target_ids t ON i.nct_id=t.nct_id
                   WHERE UPPER(i.intervention_type)='DRUG' GROUP BY i.nct_id) i ON i.nct_id=t.nct_id""").df()
    _one_nct(design, "AACT design join")
    return design, leads


def prepare_features(targets: pd.DataFrame, design: pd.DataFrame,
                     sponsor_hist: pd.DataFrame, leads: pd.DataFrame) -> pd.DataFrame:
    _one_nct(targets, "target rows")
    _one_nct(design, "design fields")
    result = targets[["nct_id", "phase_stratum", "prediction_date", "start_date"]].merge(
        design, on="nct_id", how="left", validate="one_to_one")
    result = result.merge(leads[["nct_id", "sponsor_class"]], on="nct_id",
                          how="left", validate="one_to_one")
    result = result.merge(sponsor_hist[["nct_id", *SPONSOR]], on="nct_id",
                          how="left", validate="one_to_one")
    _one_nct(result, "model features")
    result["start_year"] = _date(result.start_date).dt.year
    result["elig_min_age_years"] = _age_years(result.minimum_age)
    result["elig_max_age_years"] = _age_years(result.maximum_age)
    for col in ("has_dmc", "elig_healthy_volunteers"):
        known = result[col].notna()
        result[col] = result[col].astype(str).str.lower().isin(("t", "true", "yes", "1")).astype(float)
        result.loc[~known, col] = np.nan
    mesh_sets = result.mesh_terms.fillna("").map(lambda value: set(str(value).split("|")))
    result["disease_area"] = "none"
    for area, term in reversed(DISEASE_MESH):
        result.loc[mesh_sets.map(lambda terms, t=term: t in terms), "disease_area"] = area
    for col in CATEGORICAL:
        result[col] = result[col].fillna("MISSING").astype(str)
    for col in NUMERIC + SPONSOR:
        result[col] = pd.to_numeric(result[col], errors="coerce")
    return result[["nct_id", "prediction_date", *DESIGN_SPONSOR_FEATURES]]


def _model(kind: str, categorical: tuple[str, ...], numeric: tuple[str, ...]) -> Pipeline:
    preprocessing = ColumnTransformer([
        ("numeric", Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler())]), list(numeric)),
        ("categorical", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]), list(categorical))
    ])
    if kind == "logistic":
        fitted = LogisticRegression(max_iter=500, solver="lbfgs")
    elif kind == "random_forest":
        fitted = RandomForestClassifier(n_estimators=100, max_depth=8, min_samples_leaf=20,
                                        random_state=545, n_jobs=1)
    elif kind == "gradient_boosting":
        fitted = HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15,
                                                 learning_rate=0.05, l2_regularization=1,
                                                 random_state=545)
    else:
        raise ValueError("Unknown prespecified model")
    return Pipeline([("preprocess", preprocessing), ("model", fitted)])


def evaluate(rows: pd.DataFrame, features: pd.DataFrame) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    _one_nct(rows, "B6 target subset")
    _one_nct(features, "feature subset")
    if set(rows.nct_id) != set(features.nct_id):
        raise ValueError("Target and feature NCT sets differ")
    if (_date(rows.prediction_date) >= HOLDOUT).any():
        raise ValueError("Sealed checkpoint in evaluation input")
    targets = rows[["nct_id", "prediction_date", "start_date",
                    "completion_label", "completion_label_available_date"]].merge(
        features, on=["nct_id", "prediction_date"], validate="one_to_one")
    start = _date(targets.start_date)
    checkpoint = _date(targets.prediction_date)
    availability = _date(targets.completion_label_available_date)
    if (checkpoint >= HOLDOUT).any() or (availability.notna() & availability.le(checkpoint)).any():
        raise ValueError("Sealed or nonprospective target labels")
    training = start.lt(TRAIN_ORIGIN) & checkpoint.lt(TRAIN_ORIGIN) & availability.lt(TRAIN_ORIGIN)
    validation = (start.ge(TRAIN_ORIGIN) & start.lt(pd.Timestamp("2020-01-01")) &
                  checkpoint.lt(HOLDOUT) & availability.lt(HOLDOUT))
    # Explicitly separate labels and predictions in every output artifact.
    labels = targets.loc[validation & targets.completion_label.notna(),
                         ["nct_id", "phase_stratum", "prediction_date", "completion_label"]].copy()
    results = {}
    prediction_records = []
    for cohort in ("pooled", *PURE_PHASES):
        phase_mask = pd.Series(True, index=targets.index) if cohort == "pooled" else targets.phase_stratum.eq(cohort)
        train = targets.loc[training & phase_mask & targets.completion_label.notna()]
        val = targets.loc[validation & phase_mask & targets.completion_label.notna()]
        y_train = train.completion_label.astype(int)
        y_val = val.completion_label.astype(int)
        counts = {"train_labeled": len(train), "train_positive": int(y_train.sum()),
                  "train_negative": len(train) - int(y_train.sum()),
                  "validation_labeled": len(val), "validation_positive": int(y_val.sum()),
                  "validation_negative": len(val) - int(y_val.sum())}
        results[cohort] = {"support": counts}
        for ablation, columns in (("design", DESIGN_FEATURES),
                                  ("design_plus_sponsor", DESIGN_SPONSOR_FEATURES)):
            assert_whitelist(columns)
            ablation_report = {}
            results[cohort][ablation] = ablation_report
            for model_name in ("prevalence", "logistic", "random_forest", "gradient_boosting"):
                if (len(train) < 100 or len(val) < 30 or y_train.nunique() < 2 or y_val.nunique() < 2):
                    ablation_report[model_name] = {"status": "not_estimable", **counts}
                    continue
                if model_name == "prevalence":
                    scores = np.full(len(val), float(y_train.mean()))
                else:
                    categorical = tuple(col for col in columns if col in CATEGORICAL)
                    numeric = tuple(col for col in columns if col not in CATEGORICAL)
                    model = _model(model_name, categorical, numeric)
                    model.fit(train[list(columns)], y_train)
                    scores = model.predict_proba(val[list(columns)])[:, 1]
                ablation_report[model_name] = {
                    "status": "retrospective_diagnostic_only", **counts,
                    "roc_auc": float(roc_auc_score(y_val, scores)),
                    "average_precision": float(average_precision_score(y_val, scores)),
                    "brier": float(brier_score_loss(y_val, scores)),
                    "calibration_gap": float(y_val.mean() - np.mean(scores))}
                prediction_records.extend((row.nct_id, row.phase_stratum, row.prediction_date,
                                           cohort, ablation, model_name, float(score))
                                          for row, score in zip(val.itertuples(index=False), scores))
    predictions = pd.DataFrame(prediction_records, columns=[
        "nct_id", "phase_stratum", "prediction_date", "cohort", "ablation", "model", "score"])
    if predictions.duplicated(["nct_id", "phase_stratum", "prediction_date", "cohort",
                               "ablation", "model"]).any():
        raise AssertionError("Duplicate validation prediction key")
    return results, predictions, labels


def _pilot_rows(rows: pd.DataFrame, per_cell: int) -> pd.DataFrame:
    if per_cell <= 0:
        raise ValueError("pilot-per-cell must be positive")
    start = _date(rows.start_date)
    frames = []
    for phase in PURE_PHASES:
        for period in (start.lt(TRAIN_ORIGIN), start.ge(TRAIN_ORIGIN)):
            eligible = rows.loc[rows.phase_stratum.eq(phase) & period & rows.completion_label.notna()]
            for label in (0, 1):
                frames.append(eligible.loc[eligible.completion_label.eq(label)].sort_values("nct_id").head(per_cell // 2))
    return pd.concat(frames, ignore_index=True).drop_duplicates("nct_id")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b6-rows", required=True, type=Path)
    parser.add_argument("--tables", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pilot-per-cell", type=int, default=None)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Refusing to overwrite existing diagnostic output")
    provenance = verify_source(args.tables)
    b6_hash = sha256(args.b6_rows)
    all_rows = pd.read_parquet(args.b6_rows)
    _one_nct(all_rows, "B6 source")
    if (_date(all_rows.prediction_date) >= HOLDOUT).any():
        raise ValueError("B6 source contains sealed checkpoint")
    rows = _pilot_rows(all_rows, args.pilot_per_cell) if args.pilot_per_cell else all_rows
    design, leads = load_design(args.tables, rows.nct_id, all_rows.nct_id)
    sponsor_history = build_sponsor_history(all_rows, leads)
    features = prepare_features(rows, design, sponsor_history, leads)
    metrics, predictions, labels = evaluate(rows, features)
    args.out.mkdir(parents=True)
    prediction_path = args.out / "validation_predictions.parquet"
    label_path = args.out / "validation_labels.parquet"
    predictions.to_parquet(prediction_path, index=False)
    labels.to_parquet(label_path, index=False)
    report = {"status": "retrospective_diagnostic_not_at_launch_validated",
              "input_b6_sha256": b6_hash, "source_provenance": provenance,
              "pilot_per_phase_period": args.pilot_per_cell,
              "target_rows": len(rows), "target_unique_nct": rows.nct_id.nunique(),
              "source_b6_rows": len(all_rows),
              "sponsor_history_coverage": {
                  "eligible_prior_finished_targets": int((sponsor_history.sponsor_prior_finished > 0).sum()),
                  "no_eligible_prior_finished_targets": int(sponsor_history.sponsor_no_prior_finished.sum()),
                  "pool": "B6 prospective one-NCT cohort only; not all interventional AACT studies"},
              "feature_whitelist": {"design": list(DESIGN_FEATURES),
                                    "design_plus_sponsor": list(DESIGN_SPONSOR_FEATURES)},
              "model_settings": {"logistic": {"max_iter": 500, "solver": "lbfgs"},
                                 "random_forest": {"n_estimators": 100, "max_depth": 8,
                                                   "min_samples_leaf": 20, "random_state": 545},
                                 "gradient_boosting": {"max_iter": 100, "max_leaf_nodes": 15,
                                                       "learning_rate": 0.05, "l2_regularization": 1,
                                                       "random_state": 545}},
              "metrics": metrics,
              "prediction_sha256": sha256(prediction_path),
              "label_sha256": sha256(label_path),
              "scientific_warning": "Current AACT design, phase, MeSH and sponsor fields lack registration-era versions. Scores are retrospective diagnostics only; no at-launch or Jai .681 parity claim.",
              "sponsor_warning": "Prior outcomes use other B6 trials only (not Jai's all-interventional sponsor pool), with a conservative last-update public-availability proxy strictly before target checkpoint. Zero eligible prior finished records is not a new sponsor or zero stop performance. Current lead-sponsor identity is not historically verified.",
              "holdout": "2024+ first-public checkpoints excluded before model fitting or label evaluation; no final test score. DuckDB flat-CSV ingestion may physically parse unselected later records/columns during schema inference, so this is a logical outcome seal, not a byte-level access guarantee."}
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"target_rows": len(rows), "validation_predictions": len(predictions),
                      "validation_labels": len(labels)}))


if __name__ == "__main__":
    main()
