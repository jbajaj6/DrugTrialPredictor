"""Development-only historical design baseline; never reads 2024+ outcomes.

One observation is a first-public NCT checkpoint, not an arm.  Raw core status
and results are used only to construct later labels, never in model features.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


PHASES = ("PHASE1", "PHASE2", "PHASE3")
CAT = ("study_type", "allocation", "intervention_model", "primary_purpose",
       "masking", "lead_sponsor_class", "phase_membership")
NUM = ("estimated_enrollment_count", "arm_row_count", "experimental_arm_count",
       "placebo_arm_count", "intervention_row_count", "drug_intervention_count",
       "arm_intervention_link_row_count", "resolved_link_count",
       "unresolved_link_count", "intervention_alias_row_count",
       "unresolved_alias_count", "phase_row_count", "phase_missing_value_count",
       "arm_missing_type_count", "intervention_missing_type_count")
FLAGS = ("estimated_enrollment_missing", "phase_rows_missing", "arm_rows_missing",
         "intervention_rows_missing", "link_rows_missing", "alias_rows_missing")
FEATURES = CAT + NUM + FLAGS
ARM_FEATURES = ("arm_row_count", "experimental_arm_count", "placebo_arm_count",
                "arm_intervention_link_row_count", "resolved_link_count",
                "unresolved_link_count", "arm_missing_type_count",
                "arm_rows_missing", "link_rows_missing")
NO_ARM_FEATURES = tuple(name for name in FEATURES if name not in ARM_FEATURES)
TERMINAL = ("COMPLETED", "TERMINATED", "WITHDRAWN")
P_NUMBER = r"(?:0?\.\d+|0|1(?:\.0+)?)"
P_EXACT = re.compile(rf"^{P_NUMBER}$")
P_BOUND = re.compile(rf"^(<=|>=|<|>)\s*({P_NUMBER})$")
MIN_TRAIN, MIN_VALID, MIN_CLASS = 100, 50, 10


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def phase(value: object) -> str | None:
    """Pure-phase main analysis; combined phase assignments are a separate cohort."""
    if pd.isna(value):
        return None
    cleaned = str(value).upper().replace(" ", "").replace("_", "")
    return cleaned if cleaned in PHASES else None


def p_label(value: object, comment: object = None) -> int | None:
    """Interpret only p expressions that force one side of the .05 threshold."""
    if value is None or pd.isna(value) or (comment is not None and not pd.isna(comment) and str(comment).strip()):
        return None
    text = str(value).strip()
    if P_EXACT.fullmatch(text):
        number = float(text)
        return int(number < .05) if 0 < number <= 1 else None
    match = P_BOUND.fullmatch(text)
    if not match:
        return None
    operator, raw = match.groups()
    bound = float(raw)
    if not 0 <= bound <= 1:
        return None
    if operator == "<" and bound <= .05:
        return 1
    if operator == "<=" and bound < .05:
        return 1
    if operator in (">", ">=") and bound >= .05:
        return 0
    return None


def split_for(checkpoint: pd.Timestamp) -> str | None:
    if pd.Timestamp("2005-01-01") <= checkpoint < pd.Timestamp("2016-01-01"):
        return "train"
    if pd.Timestamp("2016-01-01") <= checkpoint < pd.Timestamp("2020-01-01"):
        return "validation"
    return None


def label_by_cutoff(checkpoint: object, availability: object, split: str) -> bool:
    if pd.isna(checkpoint) or pd.isna(availability):
        return False
    cutoff = pd.Timestamp("2016-01-01" if split == "train" else "2024-01-01")
    return pd.Timestamp(checkpoint) < pd.Timestamp(availability) < cutoff


def make_preprocessor(feature_columns: tuple[str, ...] = FEATURES) -> ColumnTransformer:
    # Every imputer and encoder is fitted by Pipeline.fit on training rows only.
    # Flags are complete yes/no indicators, converted to 0/1 before fitting.
    numeric = [name for name in NUM if name in feature_columns]
    flags = [name for name in FLAGS if name in feature_columns]
    categorical = [name for name in CAT if name in feature_columns]
    return ColumnTransformer([
        ("numeric", SimpleImputer(strategy="median", add_indicator=True), numeric),
        ("flags", "passthrough", flags),
        ("categorical", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), categorical),
    ], remainder="drop", sparse_threshold=0)


def model(name: str, feature_columns: tuple[str, ...] = FEATURES) -> Pipeline:
    if name == "random_forest":
        clf = RandomForestClassifier(n_estimators=300, min_samples_leaf=5,
                                     class_weight="balanced", max_features="sqrt",
                                     random_state=42, n_jobs=2)
    elif name == "hist_gradient_boosting":
        clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05,
                                            max_leaf_nodes=15, min_samples_leaf=20,
                                            l2_regularization=1.0, random_state=42)
    else:
        raise ValueError(name)
    return Pipeline([("preprocess", make_preprocessor(feature_columns)), ("model", clf)])


def assert_unique(con: duckdb.DuckDBPyConnection, table: str, keys: tuple[str, ...]) -> None:
    """Fail closed before a many-to-many source join or duplicate target score."""
    if table not in ("design", "dev_core", "targets", "eligible"):
        raise ValueError("Unsupported uniqueness table")
    if not keys or any(key not in ("nct_id", "nct_version") for key in keys):
        raise ValueError("Unsupported uniqueness key")
    cols = ",".join(keys)
    duplicate = con.execute(
        f"SELECT 1 FROM {table} GROUP BY {cols} HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate:
        raise ValueError(f"Duplicate {table} key: {cols}")


def verify_core_parts(core_paths: list[Path], expected: dict[str, str]) -> None:
    actual_keys = {f"core/{path.name}" for path in core_paths}
    expected_keys = {key for key in expected if key.startswith("core/")}
    if actual_keys != expected_keys:
        raise ValueError("Pinned core part-set mismatch")
    for path in core_paths:
        if digest(path) != expected[f"core/{path.name}"]:
            raise ValueError(f"Pinned core hash mismatch: {path.name}")


def _source_view(con: duckdb.DuckDBPyConnection, source: Path) -> None:
    files = sorted((source / "core").glob("*.parquet"))
    if not files:
        raise FileNotFoundError("Missing pinned raw core Parquet")
    paths = "[" + ",".join(literal(p.resolve()) for p in files) + "]"
    # Filter inside the read view; no 2024+ status, results or completion-date
    # values are projected into any materialized development relation.
    con.execute(f"""CREATE VIEW dev_core AS
        SELECT nct_id, nct_version, CAST(last_update_post_date AS DATE) AS post_date,
               is_obsolete, overall_status, completion_date,
               completion_date_type, completion_date_precision,
               results_first_post_date
        FROM read_parquet({paths})
        WHERE last_update_post_date < DATE '2024-01-01'""")


def build_labels(con: duckdb.DuckDBPyConnection, design: Path,
                 results: Path, ids: Path | None = None,
                 rolling: bool = False) -> pd.DataFrame:
    con.execute(f"CREATE VIEW design AS SELECT * FROM read_parquet({literal(design.resolve())})")
    assert_unique(con, "design", ("nct_id",))
    assert_unique(con, "dev_core", ("nct_id", "nct_version"))
    id_clause = ""
    if ids is not None:
        values = [v.strip() for v in ids.read_text().splitlines() if v.strip()]
        if len(values) != 15 or len(set(values)) != 15:
            raise ValueError("Pilot must be the fixed 15 unique NCT IDs")
        con.execute("CREATE TEMP TABLE pilot_ids(nct_id VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO pilot_ids VALUES (?)", [(v,) for v in values])
        id_clause = "AND d.nct_id IN (SELECT nct_id FROM pilot_ids)"
    con.execute(f"""CREATE TEMP TABLE targets AS
        SELECT d.*,
          CASE WHEN d.first_public_date >= DATE '2005-01-01'
                 AND d.first_public_date < DATE '2016-01-01' THEN 'train'
               WHEN d.first_public_date >= DATE '2016-01-01'
                 AND d.first_public_date < DATE '2020-01-01' THEN 'validation'
               ELSE NULL END AS split,
          c.overall_status AS checkpoint_status,
          c.completion_date AS checkpoint_completion_date,
          c.completion_date_type AS checkpoint_completion_type,
          c.completion_date_precision AS checkpoint_completion_precision,
          c.results_first_post_date AS checkpoint_results_first_post_date
        FROM design d JOIN dev_core c
          ON c.nct_id=d.nct_id AND c.nct_version=d.first_public_nct_version
        WHERE d.first_public_date < DATE '2020-01-01' {id_clause}""")
    assert_unique(con, "targets", ("nct_id",))
    # A terminal first version or an already-actual completion is not a
    # prospective target. Archive-left-truncated records are also excluded.
    con.execute("""CREATE TEMP TABLE eligible_all AS SELECT * FROM targets
        WHERE split IS NOT NULL AND first_public_core_is_obsolete IS DISTINCT FROM TRUE
          AND archive_left_truncated IS FALSE
          AND upper(coalesce(checkpoint_status,'')) NOT IN ('COMPLETED','TERMINATED','WITHDRAWN')
          AND NOT (upper(coalesce(checkpoint_completion_type,''))='ACTUAL'
                   AND CASE WHEN checkpoint_completion_precision='month'
                       THEN date_trunc('month',checkpoint_completion_date)
                       ELSE checkpoint_completion_date END <= first_public_date)
          AND (checkpoint_results_first_post_date IS NULL
               OR checkpoint_results_first_post_date > first_public_date)""")
    con.execute("""CREATE TEMP TABLE eligible AS SELECT * FROM eligible_all
        WHERE drug_intervention_count > 0""")
    assert_unique(con, "eligible", ("nct_id",))
    cohort_counts = con.execute("""SELECT COUNT(*), COUNT(*) FILTER
        (WHERE drug_intervention_count IS NULL OR drug_intervention_count <= 0)
        FROM eligible_all""").fetchone()
    # First later terminal version determines the answer. For a completed
    # status, require an ACTUAL date after checkpoint and not after posting;
    # stopped trials need no ACTUAL completion date. Contradictory later
    # terminal states are unknown, not silently resolved in our favor.
    terminal_cutoff = "DATE '2024-01-01'" if rolling else (
        "CASE WHEN e.split='train' THEN DATE '2016-01-01' ELSE DATE '2024-01-01' END")
    con.execute(f"""CREATE TEMP TABLE first_terminal AS SELECT * EXCLUDE (rn) FROM (
        SELECT e.nct_id, c.post_date AS completion_label_date,
               upper(c.overall_status) AS first_terminal_status,
               c.completion_date AS terminal_completion_date,
               c.completion_date_type AS terminal_completion_type,
               c.completion_date_precision AS terminal_completion_precision,
               ROW_NUMBER() OVER (PARTITION BY e.nct_id ORDER BY c.post_date,c.nct_version) rn
        FROM eligible e JOIN dev_core c USING (nct_id)
        WHERE c.post_date > e.first_public_date
          AND c.post_date < {terminal_cutoff}
          AND upper(c.overall_status) IN ('COMPLETED','TERMINATED','WITHDRAWN')
          AND c.is_obsolete IS DISTINCT FROM TRUE
      ) WHERE rn=1""")
    if rolling:
        # The first terminal event is selected once, independently of each fold.
        # A later reversal invalidates only folds that could already observe it.
        con.execute("""CREATE TEMP TABLE reversals AS SELECT t.nct_id,
            MIN(later.post_date) AS reversal_date
          FROM first_terminal t JOIN dev_core later USING (nct_id)
          WHERE later.post_date > t.completion_label_date
            AND later.is_obsolete IS DISTINCT FROM TRUE
            AND (upper(later.overall_status) IN
                   ('RECRUITING','ACTIVE_NOT_RECRUITING','NOT_YET_RECRUITING',
                    'ENROLLING_BY_INVITATION','SUSPENDED')
              OR (t.first_terminal_status='COMPLETED'
                    AND upper(later.overall_status) IN ('TERMINATED','WITHDRAWN'))
              OR (t.first_terminal_status IN ('TERMINATED','WITHDRAWN')
                    AND upper(later.overall_status)='COMPLETED'))
          GROUP BY t.nct_id""")
    con.execute(f"""CREATE TEMP TABLE completion AS SELECT t.nct_id,
        t.completion_label_date,
        {"r.reversal_date," if rolling else ""}
        CASE WHEN EXISTS (
          SELECT 1 FROM dev_core later
          WHERE later.nct_id=t.nct_id AND later.post_date > t.completion_label_date
            AND later.post_date < {"DATE '1900-01-01'" if rolling else terminal_cutoff}
            AND later.is_obsolete IS DISTINCT FROM TRUE
            AND (upper(later.overall_status) IN
                   ('RECRUITING','ACTIVE_NOT_RECRUITING','NOT_YET_RECRUITING',
                    'ENROLLING_BY_INVITATION','SUSPENDED')
              OR (t.first_terminal_status='COMPLETED'
                    AND upper(later.overall_status) IN ('TERMINATED','WITHDRAWN'))
              OR (t.first_terminal_status IN ('TERMINATED','WITHDRAWN')
                    AND upper(later.overall_status)='COMPLETED'))
          ) THEN NULL
          WHEN t.first_terminal_status='COMPLETED'
            AND upper(coalesce(t.terminal_completion_type,''))='ACTUAL'
            AND CASE WHEN t.terminal_completion_precision='month'
                     THEN date_trunc('month',t.terminal_completion_date)
                     WHEN t.terminal_completion_precision='day'
                     THEN t.terminal_completion_date ELSE NULL END > e.first_public_date
            AND CASE WHEN t.terminal_completion_precision='month'
                     THEN last_day(t.terminal_completion_date)
                     WHEN t.terminal_completion_precision='day'
                     THEN t.terminal_completion_date ELSE NULL END <= t.completion_label_date THEN 1
          WHEN t.first_terminal_status IN ('TERMINATED','WITHDRAWN') THEN 0
          ELSE NULL END AS completion_label
        FROM first_terminal t JOIN eligible e USING (nct_id)
        {"LEFT JOIN reversals r USING (nct_id)" if rolling else ""}""")
    measures = results / "results_outcome_measures_clean.parquet"
    analyses = results / "results_outcome_analyses_clean.parquet"
    if not measures.is_file() or not analyses.is_file():
        raise FileNotFoundError("Missing cleaned pre-2024 primary outcome tables")
    # One primary measure and one analysis in that version, with exact
    # unqualified numeric p. This intentionally leaves many labels unknown.
    con.execute(f"""CREATE TEMP TABLE primary_candidates AS
        WITH all_primary AS (
          SELECT nct_id,nct_version,COUNT(DISTINCT outcome_ord) AS primary_measure_count
          FROM read_parquet({literal(measures.resolve())})
          WHERE upper(type)='PRIMARY' AND is_obsolete IS DISTINCT FROM TRUE
          GROUP BY 1,2
        ), primary_rows AS (
          SELECT m.nct_id,m.nct_version,m.outcome_ord,
                 m.adapter_version_public_date AS post_date,
                 a.analysis_ord,a.p_value,a.p_value_comment
          FROM read_parquet({literal(measures.resolve())}) m
          JOIN read_parquet({literal(analyses.resolve())}) a
            USING (nct_id,nct_version,outcome_ord)
          WHERE upper(m.type)='PRIMARY'
            AND m.is_obsolete IS DISTINCT FROM TRUE
            AND a.is_obsolete IS DISTINCT FROM TRUE
            AND m.adapter_version_public_date=a.adapter_version_public_date
        ), analysis_counts AS (
          SELECT nct_id,nct_version,MIN(post_date) AS significance_label_date,
                 MIN(p_value) AS p_value,MIN(p_value_comment) AS p_value_comment,
                 COUNT(*) AS primary_analysis_count,
                 COUNT(*) FILTER (WHERE p_value IS NOT NULL) AS populated_p_count
          FROM primary_rows GROUP BY nct_id,nct_version
        ) SELECT a.*,m.primary_measure_count FROM analysis_counts a
          JOIN all_primary m USING (nct_id,nct_version)
          WHERE a.populated_p_count > 0""")
    # Keep the first qualifying result, not a cherry-picked later revision.
    rows = con.execute(f"""SELECT e.*, c.completion_label,c.completion_label_date,
             {"c.reversal_date," if rolling else ""}
             p.nct_version AS result_version,p.significance_label_date,p.p_value,
             p.p_value_comment,p.primary_measure_count,p.primary_analysis_count
        FROM eligible e LEFT JOIN completion c USING (nct_id)
        LEFT JOIN (SELECT * EXCLUDE (rn) FROM (
           SELECT e.nct_id,p.*, ROW_NUMBER() OVER
             (PARTITION BY e.nct_id ORDER BY p.significance_label_date,p.nct_version) rn
           FROM eligible e JOIN completion c USING (nct_id)
           JOIN primary_candidates p USING (nct_id)
           WHERE c.completion_label=1
             AND p.significance_label_date > e.first_public_date
             AND p.significance_label_date < {terminal_cutoff}
             AND p.significance_label_date >= c.completion_label_date
        ) WHERE rn=1) p USING (nct_id)""").df()
    rows["pure_phase"] = rows.phase_membership.map(phase)
    rows["significance_label"] = [
        p_label(v, comment) if (pd.notna(n) and pd.notna(a) and n == 1 and a == 1) else np.nan
        for v, comment, n, a in zip(rows.p_value, rows.p_value_comment,
                                    rows.primary_measure_count, rows.primary_analysis_count)
    ]
    rows.attrs["eligible_before_drug_filter"] = int(cohort_counts[0])
    rows.attrs["excluded_no_drug_intervention"] = int(cohort_counts[1])
    return rows


def score_cells(rows: pd.DataFrame) -> tuple[list[dict], pd.DataFrame]:
    metrics: list[dict] = []
    predictions: list[pd.DataFrame] = []
    if rows.nct_id.duplicated().any():
        raise ValueError("Duplicate one-NCT modeling rows")
    if rows[list(FLAGS)].isna().any().any():
        raise ValueError("Missing Boolean flag; cannot encode as 0/1")
    # sklearn's flag branch receives integers, never Boolean/object columns.
    rows = rows.copy()
    rows[list(FLAGS)] = rows[list(FLAGS)].astype("int8")
    for task, column in (("completion", "completion_label"),
                         ("reported_primary_p_lt_0_05", "significance_label")):
        for p in PHASES:
            phase_rows = rows[(rows.pure_phase == p) & rows[column].notna()]
            for subset in ("broad", "arm_rich"):
                sub = phase_rows if subset == "broad" else phase_rows[phase_rows.arm_row_count > 0]
                train = sub[sub.split == "train"].copy()
                valid = sub[sub.split == "validation"].copy()
                counts = {f"{s}_{k}": int((part[column] == k).sum()) for s, part in
                          (("train", train), ("validation", valid)) for k in (0, 1)}
                support = (len(train) >= MIN_TRAIN and len(valid) >= MIN_VALID
                           and all(v >= MIN_CLASS for v in counts.values()))
                base = {"task": task, "phase": p, "subset": subset,
                        "train_rows": len(train), "validation_rows": len(valid), **counts,
                        "estimable": bool(support),
                        "reason": None if support else "minimum_100_train_50_validation_10_per_class_not_met"}
                feature_sets = (("all_design", FEATURES),) if subset == "broad" else (
                    ("all_design", FEATURES), ("without_arm_features", NO_ARM_FEATURES))
                if not support:
                    metrics.extend({**base, "feature_set": label, "model": None}
                                   for label, _ in feature_sets)
                    continue
                y_train = train[column].astype(int)
                y_valid = valid[column].astype(int)
                for feature_set, columns in feature_sets:
                    for name in ("prevalence", "random_forest", "hist_gradient_boosting"):
                        if name == "prevalence":
                            prob = np.repeat(y_train.mean(), len(valid))
                        else:
                            pipe = model(name, columns)
                            pipe.fit(train[list(columns)], y_train)
                            prob = pipe.predict_proba(valid[list(columns)])[:, 1]
                        metrics.append({**base, "feature_set": feature_set, "model": name,
                                        "roc_auc": float(roc_auc_score(y_valid, prob)),
                                        "average_precision": float(average_precision_score(y_valid, prob)),
                                        "brier": float(brier_score_loss(y_valid, prob))})
                        predictions.append(pd.DataFrame({"nct_id": valid.nct_id.to_numpy(),
                            "task": task, "phase": p, "subset": subset,
                            "feature_set": feature_set, "model": name,
                            "label": y_valid.to_numpy(), "probability": prob}))
    return metrics, pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()


def run(source: Path, design: Path, results: Path, out: Path,
        ids: Path | None = None) -> dict:
    if out.exists():
        raise FileExistsError(f"Refusing overwrite: {out}")
    design_manifest = json.loads((design.parent / "manifest.json").read_text())
    if design_manifest["source_root"] != str(source.resolve()):
        raise ValueError("B12 source root mismatch")
    if digest(design) != design_manifest["output_sha256"][design.name]:
        raise ValueError("B12 design hash mismatch")
    results_manifest = json.loads((results / "manifest.json").read_text())
    if results_manifest["source_root"] != str(source.resolve()):
        raise ValueError("B11b source root mismatch")
    for name in ("results_outcome_measures_clean.parquet",
                 "results_outcome_analyses_clean.parquet"):
        if digest(results / name) != results_manifest["output_files_sha256"].get(name):
            raise ValueError(f"B11b result hash mismatch: {name}")
    core_paths = sorted((source / "core").glob("*.parquet"))
    expected_core = design_manifest["verified_input_sha256"]
    verify_core_parts(core_paths, expected_core)
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'")
    con.execute("SET threads=2")
    out.mkdir(parents=True)
    (out / "duckdb_spill").mkdir()
    con.execute(f"SET temp_directory={literal(out / 'duckdb_spill')}")
    _source_view(con, source)
    rows = build_labels(con, design, results, ids)
    con.close()
    metrics, predictions = score_cells(rows)
    # Omit raw outcome/status columns from the public inspection CSV.
    inspection = rows[["nct_id", "first_public_nct_version", "first_public_date",
        "split", "pure_phase", "completion_label",
        "completion_label_date", "significance_label", "significance_label_date",
        *FEATURES]].copy()
    inspection.to_parquet(out / "development_rows.parquet", index=False)
    if not predictions.empty:
        predictions.to_parquet(out / "validation_predictions.parquet", index=False)
    funnel = {"eligible_before_drug_filter": rows.attrs["eligible_before_drug_filter"],
              "excluded_no_drug_intervention": rows.attrs["excluded_no_drug_intervention"],
              "target_eligible_rows": len(rows), "pure_phase_rows": int(rows.pure_phase.notna().sum()),
              "arm_rich_rows": int((rows.arm_row_count > 0).sum()),
              "train_rows": int((rows.split == "train").sum()),
              "validation_rows": int((rows.split == "validation").sum()),
              "completion_known": int(rows.completion_label.notna().sum()),
              "significance_known": int(rows.significance_label.notna().sum())}
    missingness = rows.groupby(["split", "pure_phase"], dropna=False).agg(
        rows=("nct_id", "size"), no_arms=("arm_rows_missing", "sum"),
        no_interventions=("intervention_rows_missing", "sum"),
        no_phase=("phase_rows_missing", "sum"),
        no_estimated_enrollment=("estimated_enrollment_missing", "sum"))
    missingness.reset_index().to_csv(out / "missingness_by_era_phase.csv", index=False)
    report = {"status": "development_only_no_final_holdout_scored",
              "source_commit": design_manifest["source_commit"],
              "source_root": str(source.resolve()), "design_root": str(design.parent.resolve()),
              "results_root": str(results.resolve()), "pilot_ids_sha256": digest(ids) if ids else None,
              "feature_columns": FEATURES, "categorical": CAT, "numeric": NUM, "flags": FLAGS,
              "arm_features_removed_in_ablation": ARM_FEATURES,
              "drug_cohort_rule": "drug_intervention_count > 0 at first public version",
              "arm_rich_rule": "arm_row_count > 0 at first public version",
              "split": {"train_checkpoint": "2005-01-01 through 2015-12-31",
                        "train_label_before": "2016-01-01",
                        "validation_checkpoint": "2016-01-01 through 2019-12-31",
                        "validation_label_before": "2024-01-01"},
              "minimum_support": {"train": MIN_TRAIN, "validation": MIN_VALID,
                                  "each_class_per_partition": MIN_CLASS},
              "funnel": funnel, "metrics": metrics,
              "input_sha256": {"design": digest(design),
                  "design_manifest": digest(design.parent / "manifest.json"),
                  "results_manifest": digest(results / "manifest.json")},
              "code_sha256": digest(Path(__file__))}
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    report["output_sha256"] = {p.name: digest(p) for p in out.iterdir() if p.is_file()}
    (out / "manifest.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source", "design", "results", "out"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--ids", type=Path)
    args = parser.parse_args()
    report = run(args.source, args.design, args.results, args.out, args.ids)
    print(json.dumps({"status": report["status"], "funnel": report["funnel"],
                      "metrics": report["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
