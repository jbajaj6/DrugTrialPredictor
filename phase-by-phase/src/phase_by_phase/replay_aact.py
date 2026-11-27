"""Development-safe replay of Jai's dated AACT flat-file cohort.

The original SQL's terminal-status and primary-p gates are only applied after
excluding trials first publicly posted in 2024 or later. Consequently counts
are *not* advertised as literal unsealed SQL parity when late-posted IDs exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import zipfile

import duckdb
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from .acquire import sha256


HOLDOUT = pd.Timestamp("2024-01-01")
TRAIN_ORIGIN = pd.Timestamp("2016-01-01")
TERMINAL = ("COMPLETED", "TERMINATED", "WITHDRAWN")
PURE_PHASES = ("PHASE1", "PHASE2", "PHASE3")
EXPECTED_ARCHIVE_SHA256 = "aece8294f88a0934fe9efb4d398e06ed1b91e8b185159a36af372a46df26e362"
INPUT_TABLES = ("studies", "interventions", "outcomes", "outcome_analyses")


def _hash_stream(stream) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(8 * 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def verify_source(tables: Path, expected_archive_sha256: str = EXPECTED_ARCHIVE_SHA256,
                  table_names: tuple[str, ...] = INPUT_TABLES) -> dict:
    """Verify the dated ZIP and prove extracted input bytes match its members."""
    archive = tables.parent / "20261029_aact_flat.zip"
    if not archive.is_file():
        raise FileNotFoundError(f"Cannot verify AACT source without archive: {archive}")
    archive_hash = sha256(archive)
    if archive_hash != expected_archive_sha256:
        raise ValueError(f"AACT archive SHA-256 mismatch: {archive_hash}")
    table_report = {}
    with zipfile.ZipFile(archive) as zipped:
        for name in table_names:
            if name not in INPUT_TABLES:
                raise ValueError(f"Unexpected source table: {name}")
            path = tables / f"{name}.txt"
            if not path.is_file():
                raise FileNotFoundError(path)
            member = f"{name}.txt"
            info = zipped.getinfo(member)
            size = path.stat().st_size
            extracted_hash = sha256(path)
            with zipped.open(info) as source:
                member_hash = _hash_stream(source)
            if size != info.file_size or extracted_hash != member_hash:
                raise ValueError(f"Extracted AACT table differs from verified ZIP member: {name}")
            table_report[name] = {"sha256": extracted_hash, "bytes": size,
                                  "verified_against_zip_member": True}
    return {"archive_sha256": archive_hash, "archive_bytes": archive.stat().st_size,
            "archive_verified": True, "consumed_tables": table_report}


def _view(con: duckdb.DuckDBPyConnection, name: str, tables: Path) -> None:
    path = tables / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(path)
    # Match the original loader's flat-file dialect and inference settings.
    if name not in {"studies", "interventions", "outcomes", "outcome_analyses"}:
        raise ValueError("Unexpected AACT table")
    escaped = str(path.resolve()).replace("'", "''")
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv('{escaped}', "
                "delim='|', header=true, quote='\"', escape='\"', sample_size=-1)")


def _date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _strict_p_decision(value: float, modifier: str | None) -> bool | None:
    """Whether a reported primary p relation resolves p < 0.05."""
    if not math.isfinite(value) or not 0 <= value <= 1:
        return None
    mod = "" if modifier is None else str(modifier).strip().upper()
    if mod in ("", "=", "=="):
        return value < 0.05
    if mod == "<":
        return True if value <= 0.05 else None
    if mod == "<=":
        return True if value < 0.05 else None
    if mod in (">", ">="):
        return False if value >= 0.05 else None
    return None


def qualifier_aware_decisions(analyses: pd.DataFrame) -> dict[str, bool | None]:
    """Any definite positive wins; negative needs all numeric rows definite."""
    result = {}
    for nct, group in analyses.groupby("nct_id", sort=False):
        decisions = [_strict_p_decision(float(row.p_value), row.p_value_modifier)
                     if pd.notna(row.p_value) else None
                     for row in group.itertuples(index=False)]
        result[nct] = (True if any(v is True for v in decisions) else
                       False if decisions and all(v is False for v in decisions) else None)
    return result


def derive_rows(base: pd.DataFrame, p_by_nct: dict[str, float],
                strict_by_nct: dict[str, bool | None] | None = None) -> pd.DataFrame:
    """Apply original <=90-day lag, then strictly dated development labels."""
    required = {"nct_id", "overall_status", "phase", "start_date", "first_submitted_date",
                "first_post_date", "completion_date", "completion_date_type",
                "last_update_post_date", "results_first_post_date"}
    if required - set(base):
        raise ValueError(f"Missing columns: {sorted(required - set(base))}")
    if base.nct_id.duplicated().any():
        raise ValueError("Original base must have one row per NCT")
    posted = _date(base.first_post_date)
    # This guard must precede any status/result access in callers. It remains
    # a defensive direct-call check for injected sealed sentinels.
    dev = base.loc[posted.notna() & posted.lt(HOLDOUT)].copy()
    start = _date(dev.start_date)
    submitted = _date(dev.first_submitted_date)
    dev["reg_lag_days"] = (submitted - start).dt.days
    dev = dev.loc[dev.reg_lag_days.le(90)].copy()
    checkpoint = _date(dev.first_post_date)
    completion = _date(dev.completion_date)
    update = _date(dev.last_update_post_date)
    result_post = _date(dev.results_first_post_date)
    actual_completion = dev.completion_date_type.astype(str).str.upper().eq("ACTUAL")
    dev["audit_completion_on_or_before_checkpoint"] = (actual_completion & completion.notna() &
                                                         completion.le(checkpoint))
    dev["audit_result_on_or_before_checkpoint"] = result_post.notna() & result_post.le(checkpoint)
    dev["audit_submitted_after_completion"] = submitted.notna() & completion.notna() & submitted.gt(completion)
    dev["audit_start_on_or_after_completion"] = start.notna() & completion.notna() & start.ge(completion)
    dev["audit_update_before_actual_completion"] = (actual_completion & completion.notna() &
                                                      update.notna() & update.lt(completion))
    # The original SQL includes trials that had already finished before they
    # first became public. Retain their parity rows, but never label or score
    # them as prospective predictions.
    prospective = ~(dev.audit_completion_on_or_before_checkpoint |
                    dev.audit_result_on_or_before_checkpoint)
    dev["prospective_at_checkpoint"] = prospective
    boundary = pd.Series(pd.Timestamp("2020-01-01"), index=dev.index)
    boundary.loc[checkpoint.ge(pd.Timestamp("2020-01-01"))] = HOLDOUT
    available = pd.concat([completion, update], axis=1).max(axis=1)
    valid_q1 = (prospective & actual_completion & completion.notna() & update.notna() &
                update.ge(completion) & available.gt(checkpoint) &
                available.lt(boundary))
    dev["completion_label"] = pd.Series(pd.NA, index=dev.index, dtype="Int64")
    dev.loc[valid_q1, "completion_label"] = dev.loc[valid_q1, "overall_status"].eq("COMPLETED").astype(int)
    dev["completion_label_available_date"] = available.where(valid_q1)
    valid_result = (dev.completion_label.eq(1).fillna(False) & result_post.notna() &
                    update.notna() & result_post.gt(checkpoint) &
                    pd.concat([result_post, update], axis=1).max(axis=1).lt(boundary))
    dev["significance_label"] = pd.Series(pd.NA, index=dev.index, dtype="Int64")
    p = pd.to_numeric(dev.nct_id.map(p_by_nct), errors="coerce")
    known_p = valid_result & p.notna()
    dev.loc[known_p, "significance_label"] = p.loc[known_p].lt(0.05).astype(int)
    dev["significance_label_available_date"] = pd.concat([result_post, update], axis=1).max(axis=1).where(known_p)
    strict = dev.nct_id.map(strict_by_nct or {})
    strict_known = valid_result & strict.notna()
    dev["qualifier_aware_significance_label"] = pd.Series(pd.NA, index=dev.index, dtype="Int64")
    dev.loc[strict_known, "qualifier_aware_significance_label"] = strict.loc[strict_known].astype(int)
    dev["qualifier_aware_significance_available_date"] = pd.concat(
        [result_post, update], axis=1).max(axis=1).where(strict_known)
    dev["phase_stratum"] = dev.phase.fillna("MISSING_PHASE").str.upper().str.replace(" ", "", regex=False)
    return dev.sort_values("nct_id").reset_index(drop=True)


def _wilson(positive: int, total: int) -> list[float] | None:
    if total == 0:
        return None
    z = 1.959963984540054
    p = positive / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [center - half, center + half]


def phase_prevalence(rows: pd.DataFrame) -> dict:
    """Prespecified 2005-15/2016-19 start split, with as-of label cutoffs."""
    start = _date(rows.start_date)
    posted = _date(rows.first_post_date)
    report = {}
    for phase in PURE_PHASES:
        subset = rows.loc[rows.phase_stratum.eq(phase) & rows.prospective_at_checkpoint]
        phase_start = start.loc[subset.index]
        phase_posted = posted.loc[subset.index]
        report[phase] = {}
        for task, label_col, available_col in (
                ("completion", "completion_label", "completion_label_available_date"),
                ("significance_numeric", "significance_label", "significance_label_available_date"),
                ("significance_qualifier_aware", "qualifier_aware_significance_label",
                 "qualifier_aware_significance_available_date")):
            available = _date(subset[available_col])
            train = subset.loc[phase_start.lt(TRAIN_ORIGIN) & phase_posted.lt(TRAIN_ORIGIN) &
                               available.lt(TRAIN_ORIGIN) & subset[label_col].notna()]
            val = subset.loc[phase_start.ge(TRAIN_ORIGIN) & phase_start.lt(pd.Timestamp("2020-01-01")) &
                             phase_posted.lt(HOLDOUT) & available.lt(HOLDOUT) &
                             subset[label_col].notna()]
            y_train = train[label_col].astype(int)
            y_val = val[label_col].astype(int)
            n_train, n_val = len(train), len(val)
            train_pos, val_pos = int(y_train.sum()), int(y_val.sum())
            entry = {"unit": "one NCT", "train_start_years": "2005-2015",
                     "validation_start_years": "2016-2019", "train_label_cutoff": "2016-01-01",
                     "validation_label_cutoff": "2024-01-01",
                     "train_labeled": n_train, "train_positive": train_pos,
                     "train_negative": n_train - train_pos,
                     "validation_labeled": n_val, "validation_positive": val_pos,
                     "validation_negative": n_val - val_pos,
                     "validation_observed_rate_wilson95": _wilson(val_pos, n_val)}
            if n_train < 100 or n_val < 30 or not (0 < train_pos < n_train and 0 < val_pos < n_val):
                entry.update(status="not_estimable", reason="Minimum row/class support gate failed")
            else:
                prevalence = train_pos / n_train
                scores = [prevalence] * n_val
                entry.update(status="prevalence_baseline_only", train_prevalence=prevalence,
                             validation_observed_rate=val_pos / n_val,
                             roc_auc=float(roc_auc_score(y_val, scores)),
                             average_precision=float(average_precision_score(y_val, scores)),
                             brier=float(brier_score_loss(y_val, scores)),
                             calibration_gap=(val_pos / n_val) - prevalence,
                             score_ci_warning="No model-score uncertainty claimed; Wilson interval covers observed event rate only")
            report[phase][task] = entry
    return report


def replay(tables: Path) -> tuple[pd.DataFrame, dict]:
    provenance = verify_source(tables)
    con = duckdb.connect()
    for name in ("studies", "interventions"):
        _view(con, name, tables)
    # Metadata-only gate. Do not query status or results for a first-posted
    # 2024+ NCT. The original SQL has no such gate, so report divergence.
    metadata = con.execute("""SELECT nct_id, study_first_posted_date, start_date
        FROM studies WHERE CAST(start_date AS DATE) BETWEEN DATE '2005-01-01'
        AND DATE '2019-12-31'""").df()
    first_post = _date(metadata.study_first_posted_date)
    sealed_ids = set(metadata.loc[first_post.isna() | first_post.ge(HOLDOUT), "nct_id"])
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
        FROM studies s JOIN allowed_ids a ON s.nct_id = a.nct_id
        WHERE UPPER(s.study_type) = 'INTERVENTIONAL'
          AND UPPER(s.overall_status) IN ('COMPLETED', 'TERMINATED', 'WITHDRAWN')
          AND CAST(s.start_date AS DATE) BETWEEN DATE '2005-01-01' AND DATE '2019-12-31'
          AND EXISTS (SELECT 1 FROM interventions i WHERE i.nct_id=s.nct_id
                      AND UPPER(i.intervention_type)='DRUG')""").df()
    # Determine as-of eligible Q2 IDs from metadata/date fields only. Outcomes
    # are queried only after this whitelist is established.
    skeleton = derive_rows(base, {})
    q2_candidates = skeleton.loc[skeleton.completion_label.eq(1).fillna(False)]
    dates = _date(q2_candidates.results_first_post_date)
    updates = _date(q2_candidates.last_update_post_date)
    checkpoints = _date(q2_candidates.first_post_date)
    boundaries = pd.Series(pd.Timestamp("2020-01-01"), index=q2_candidates.index)
    boundaries.loc[checkpoints.ge(pd.Timestamp("2020-01-01"))] = HOLDOUT
    safe = (dates.notna() & updates.notna() & dates.gt(checkpoints) &
            pd.concat([dates, updates], axis=1).max(axis=1).lt(boundaries))
    q2_ids = q2_candidates.loc[safe, "nct_id"]
    p_values: dict[str, float] = {}
    strict_values: dict[str, bool | None] = {}
    modifier_counts: dict[str, int] = {}
    invalid_p_rows = 0
    missing_p_rows = 0
    if len(q2_ids):
        con.register("q2_ids", q2_ids.to_frame())
        for name in ("outcomes", "outcome_analyses"):
            _view(con, name, tables)
        p_rows = con.execute("""SELECT o.nct_id,
            TRY_CAST(oa.p_value AS DOUBLE PRECISION) AS p_value,
            oa.p_value_modifier
            FROM outcomes o JOIN q2_ids q ON q.nct_id=o.nct_id
            JOIN outcome_analyses oa ON oa.outcome_id=o.id
            WHERE UPPER(o.outcome_type)='PRIMARY'""").df()
        numeric_rows = p_rows.loc[p_rows.p_value.notna()]
        p_values = numeric_rows.groupby("nct_id").p_value.min().to_dict()
        strict_values = qualifier_aware_decisions(p_rows)
        modifier_counts = numeric_rows.p_value_modifier.fillna("<none>").astype(str).value_counts().to_dict()
        invalid_p_rows = int(((numeric_rows.p_value < 0) | (numeric_rows.p_value > 1)).sum())
        missing_p_rows = int(p_rows.p_value.isna().sum())
    rows = derive_rows(base, p_values, strict_values)
    report = {"status": "development_safe_aact_replay_not_literal_unsealed_sql",
              "archive_date": "2026-10-29",
              "source_provenance": provenance,
              "original_sql_raw_reference": 95726,
              "original_sql_lag_reference": 73842,
              "original_sql_q2_reference": 9030,
              "start_2005_2019_metadata_nct": len(metadata),
              "sealed_or_undated_first_post_before_status_read": len(sealed_ids),
              "development_safe_terminal_drug_base_nct": len(base),
              "lag_le_90_nct": len(rows),
              "prospective_lag_cohort_nct": int(rows.prospective_at_checkpoint.sum()),
              "nonprospective_original_rule_rows": int((~rows.prospective_at_checkpoint).sum()),
              "chronology_audit_flags_in_lag_cohort": {
                  key.removeprefix("audit_"): int(rows[key].sum()) for key in rows
                  if key.startswith("audit_")},
              "q1_dated_known": int(rows.completion_label.notna().sum()),
              "q2_completed_with_dated_p": int(rows.significance_label.notna().sum()),
              "q2_qualifier_aware_determinate": int(rows.qualifier_aware_significance_label.notna().sum()),
              "primary_p_modifier_counts": modifier_counts,
              "primary_p_out_of_range_numeric_rows": invalid_p_rows,
              "primary_analysis_rows_missing_numeric_p": missing_p_rows,
              "q2_candidate_nct_before_p_read": len(q2_ids),
              "prespecified_variants": {
                  "jai_parity": "Descriptive original-rule baseline with holdout seal; not an unsealed SQL rerun",
                  "phase_prevalence": phase_prevalence(rows),
                  "historically_verified_design": "not_estimable: AACT current design has no verified registration-era version",
                  "dated_sponsor_history": "not_estimable: target sponsor identity and prior sponsor outcomes lack verified historical versions in this AACT replay",
                  "dated_earlier_phase_evidence": "not_estimable: exact-label candidate links are not verified clinical program identity on these AACT target rows"},
              "no_forest_fitted": True,
              "scientific_limits": [
                  "Original SQL lacks the first-post holdout gate, so reference counts may differ.",
                  "Original SQL includes trials already finished by first public posting; parity rows are retained but excluded from prospective evaluation.",
                  "AACT is a current snapshot; protocol design/sponsor/phase history at registration is not certified.",
                  "Last-update-posted is a conservative availability proxy, not proof that the present status or p-value matched its earlier version.",
                  "DuckDB flat-file scans may physically parse excluded CSV rows; SQL ID predicates prevent their outcome values from entering derived rows but do not certify byte-level non-read.",
                  "Current posted p-values may differ from first-posted result version.",
                  "Jai numeric min-p Q2 ignores qualifiers; qualifier-aware Q2 preserves ambiguous inequalities as unknown.",
                  "Q2 is a p<0.05 proxy among completed trials, not clinical success."]}
    return rows, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Refusing to overwrite existing replay")
    rows, report = replay(args.tables)
    args.out.mkdir(parents=True)
    path = args.out / "aact_development_rows.parquet"
    rows.to_parquet(path, index=False)
    report["output_sha256"] = sha256(path)
    (args.out / "coverage_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("development_safe_terminal_drug_base_nct",
                                                  "lag_le_90_nct", "q1_dated_known",
                                                  "q2_completed_with_dated_p")}))


if __name__ == "__main__":
    main()
