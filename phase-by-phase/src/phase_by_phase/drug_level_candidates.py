"""Development-only, unverified drug-name candidate linkage at Phase 3 landmarks.

No efficacy model is fitted here. Exact label equality is a candidate, not chemical
identity; aliases are review flags. Historical inputs are strictly before the
Phase 3 first-public checkpoint, while B17 grades remain labels only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import duckdb


def normalize_drug_name(value: str | None) -> str | None:
    if not value:
        return None
    name = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    name = re.sub(r"\s+", " ", name)
    if not name or name in {"placebo", "control", "standard of care", "usual care"}:
        return None
    if re.search(r"\b(placebo|vehicle|sham|saline|control)\b", name):
        return None
    return name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _query_int(db: duckdb.DuckDBPyConnection, query: str) -> int:
    return int(db.execute(query).fetchone()[0])


def _sql_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def build(
    *, cohort: Path, design: Path, protocol: Path, results: Path,
    grades: Path, core: Path, out: Path, limit: int | None = None,
) -> dict:
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite prior output: {out}")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    inputs = {
        "cohort": cohort, "design": design, "grades": grades, "core": core,
        "interventions": protocol / "interventions_clean.parquet",
        "arms": protocol / "arms_clean.parquet",
        "links": protocol / "arm_intervention_links.parquet",
        "aliases": protocol / "intervention_aliases_clean.parquet",
        "outcomes": results / "results_outcome_measures_clean.parquet",
        "serious": results / "results_adverse_serious_event_stats_clean.parquet",
    }
    for key, path in inputs.items():
        if key == "core":
            if not path.is_dir() or not list(path.glob("*.parquet")):
                raise FileNotFoundError(f"{key}: {path}")
        elif not path.is_file():
            raise FileNotFoundError(f"{key}: {path}")
    out.mkdir(parents=True)
    db = duckdb.connect()
    db.execute("PRAGMA memory_limit='4GB'")
    db.create_function("drug_key", normalize_drug_name, ["VARCHAR"], "VARCHAR", null_handling="special")
    for key, path in inputs.items():
        source = path / "*.parquet" if key == "core" else path
        db.execute(f"CREATE VIEW {key} AS SELECT * FROM read_parquet({_sql_path(source)})")
    observed = {row[0] for row in db.execute("SELECT DISTINCT pure_phase FROM cohort").fetchall()}
    if not {'PHASE1', 'PHASE2', 'PHASE3'}.issubset(observed):
        raise ValueError(f"Unexpected or missing cohort phases: {observed}")
    suffix = f"LIMIT {limit}" if limit is not None else ""
    db.execute(f"""
        CREATE TEMP TABLE target AS
        SELECT nct_id, first_public_nct_version AS nct_version,
               CAST(first_public_date AS DATE) AS checkpoint_date,
               CASE WHEN first_public_date < DATE '2016-01-01' THEN 'train_2005_15'
                    ELSE 'validation_2016_19' END AS split
        FROM cohort WHERE pure_phase='PHASE3'
          AND first_public_date < DATE '2020-01-01'
        ORDER BY hash(nct_id),nct_id {suffix}
    """)
    if not _query_int(db, "SELECT count(*) FROM target"):
        raise ValueError("No Phase 3 targets; refusing empty report")
    db.execute("""
        CREATE TEMP TABLE relevant AS
        SELECT c.nct_id, c.first_public_nct_version AS nct_version,
               CAST(c.first_public_date AS DATE) AS source_date, c.pure_phase
        FROM cohort c WHERE c.pure_phase IN ('PHASE1','PHASE2','PHASE3')
          AND c.first_public_date < DATE '2020-01-01'
          AND (c.pure_phase <> 'PHASE3' OR c.nct_id IN (SELECT nct_id FROM target))
    """)
    # B12 verifies the first-public version used by B15; reject drift.
    drift = _query_int(db, """
        SELECT count(*) FROM relevant r LEFT JOIN design d
        ON r.nct_id=d.nct_id AND r.nct_version=d.first_public_nct_version
        WHERE d.nct_id IS NULL OR r.source_date <> d.first_public_date
    """)
    if drift:
        raise ValueError(f"B15/B12 first-public key/date mismatch: {drift}")
    db.execute("""
        CREATE TEMP TABLE exposure AS
        WITH linked AS (
          SELECT DISTINCT r.nct_id, r.nct_version, r.source_date, r.pure_phase,
            i.ord AS intervention_ord, i.intervention_name, i.description AS intervention_description,
            i.adapter_source_file AS intervention_source_file,
            a.ord AS arm_group_ord, a.arm_label, a.arm_type,
            a.description AS arm_description,
            l.adapter_source_file AS link_source_file,
            drug_key(i.intervention_name) AS candidate_drug_key
          FROM relevant r
          JOIN interventions i ON i.nct_id=r.nct_id AND i.nct_version=r.nct_version
          LEFT JOIN links l ON l.nct_id=i.nct_id AND l.nct_version=i.nct_version
            AND l.intervention_ord=i.ord AND l.source='intervention'
            AND l.adapter_link_status='resolved' AND l.arm_group_ord IS NOT NULL
          LEFT JOIN arms a ON a.nct_id=l.nct_id AND a.nct_version=l.nct_version
            AND a.ord=l.arm_group_ord
          WHERE upper(i.intervention_type)='DRUG'
            AND coalesce(i.is_obsolete,false)=false
            AND coalesce(a.is_obsolete,false)=false
            AND coalesce(l.is_obsolete,false)=false
            AND drug_key(i.intervention_name) IS NOT NULL
        ), flagged AS (
          SELECT *, count(DISTINCT candidate_drug_key) OVER
            (PARTITION BY nct_id,nct_version,arm_group_ord) AS drugs_in_arm,
            max(CASE WHEN arm_type IS NOT NULL AND arm_type <> 'EXPERIMENTAL'
                     THEN 1 ELSE 0 END) OVER
            (PARTITION BY nct_id,nct_version,candidate_drug_key) AS shared_with_nonexperimental
          FROM linked
        )
        SELECT *, CASE WHEN arm_type='EXPERIMENTAL' AND drugs_in_arm=1
                           AND shared_with_nonexperimental=0 THEN true ELSE false END
                           AS primary_candidate,
               CASE WHEN arm_group_ord IS NULL OR arm_type IS NULL THEN 'no_resolved_arm_link'
                    WHEN arm_type<>'EXPERIMENTAL' THEN 'non_experimental_arm'
                    WHEN drugs_in_arm>1 THEN 'multi_drug_arm'
                    WHEN shared_with_nonexperimental=1 THEN 'shared_with_control'
                    ELSE 'single_experimental_drug' END AS identity_flag,
               'exact_normalized_name_unverified' AS match_type
        FROM flagged
    """)
    # Alias claims are retained for review, but not silently merged into a
    # primary clinical drug identity. Count collisions across canonical names.
    db.execute("""
        CREATE TEMP TABLE alias_review AS
        WITH a AS (
          SELECT DISTINCT e.nct_id,e.nct_version,e.intervention_ord,
            e.candidate_drug_key AS canonical_key, e.primary_candidate,
            drug_key(x.other_name) AS alias_key, x.other_name AS alias_raw,
            x.adapter_source_file AS alias_source_file
          FROM exposure e JOIN aliases x ON x.nct_id=e.nct_id
            AND x.nct_version=e.nct_version AND x.intervention_ord=e.intervention_ord
          WHERE x.adapter_link_status='resolved'
            AND coalesce(x.is_obsolete,false)=false
        ), collisions AS (
          SELECT alias_key,count(DISTINCT canonical_key) AS canonical_count
          FROM a WHERE alias_key IS NOT NULL GROUP BY 1
        )
        SELECT a.*, c.canonical_count,
          CASE WHEN c.canonical_count=1 AND a.alias_key<>a.canonical_key
               THEN 'single_canonical_alias_candidate_unverified'
               ELSE 'collision_or_self_alias' END AS alias_status
        FROM a JOIN collisions c USING(alias_key)
    """)
    db.execute("""
        CREATE TEMP TABLE target_exposure AS
        SELECT DISTINCT e.nct_id AS target_nct_id, e.nct_version AS target_version,
          e.source_date AS checkpoint_date, t.split, e.candidate_drug_key,
          e.primary_candidate, e.identity_flag, e.match_type,
          e.intervention_ord,e.arm_group_ord,e.intervention_name,e.arm_label,
          e.intervention_description,e.arm_description
        FROM exposure e JOIN target t ON e.nct_id=t.nct_id AND e.nct_version=t.nct_version
    """)
    # Latest *whole record* version before each landmark, then inspect only
    # the results at that exact version. This avoids carrying a retracted
    # primary result forward from a stale earlier result-bearing version.
    db.execute("""
        CREATE TEMP TABLE contribution AS
        WITH candidate AS (
          SELECT DISTINCT t.target_nct_id,t.target_version,t.checkpoint_date,t.split,
            t.candidate_drug_key,t.primary_candidate AS target_primary,
            e.nct_id AS prior_nct_id,e.nct_version AS prior_design_version,
            e.source_date AS prior_design_date,e.pure_phase AS prior_phase,
            e.intervention_ord,e.arm_group_ord,e.intervention_name,
            e.intervention_description,e.arm_label,e.arm_type,e.arm_description,
            e.intervention_source_file,e.link_source_file,
            e.primary_candidate AS prior_primary,e.identity_flag,e.match_type
          FROM target_exposure t JOIN exposure e
            ON e.candidate_drug_key=t.candidate_drug_key
            AND e.pure_phase IN ('PHASE1','PHASE2') AND e.nct_id<>t.target_nct_id
            AND e.source_date<t.checkpoint_date
          WHERE t.primary_candidate AND e.primary_candidate
        ), dated_records AS (
          SELECT c.target_nct_id,c.candidate_drug_key,c.prior_nct_id,
            k.nct_version AS prior_asof_record_version,
            coalesce(k.last_update_post_date,k.study_first_post_date) AS prior_asof_record_date,
            row_number() OVER (PARTITION BY c.target_nct_id,c.candidate_drug_key,c.prior_nct_id
              ORDER BY coalesce(k.last_update_post_date,k.study_first_post_date) DESC,
                k.nct_version DESC) AS rn
          FROM (SELECT DISTINCT target_nct_id,candidate_drug_key,prior_nct_id,checkpoint_date FROM candidate) c
          JOIN core k ON k.nct_id=c.prior_nct_id
            AND coalesce(k.last_update_post_date,k.study_first_post_date)<c.checkpoint_date
            AND coalesce(k.last_update_post_date,k.study_first_post_date)<DATE '2024-01-01'
            AND coalesce(k.is_obsolete,false)=false
        ), asof_record AS (SELECT * FROM dated_records WHERE rn=1)
        SELECT c.*,r.prior_asof_record_version,r.prior_asof_record_date,
          CASE WHEN EXISTS (SELECT 1 FROM outcomes o WHERE o.nct_id=c.prior_nct_id
            AND o.nct_version=r.prior_asof_record_version
            AND o.adapter_version_public_date<c.checkpoint_date
            AND upper(o.type)='PRIMARY' AND coalesce(o.is_obsolete,false)=false)
            THEN r.prior_asof_record_version ELSE NULL END AS prior_result_version,
          CASE WHEN EXISTS (SELECT 1 FROM outcomes o WHERE o.nct_id=c.prior_nct_id
            AND o.nct_version=r.prior_asof_record_version
            AND o.adapter_version_public_date<c.checkpoint_date
            AND upper(o.type)='PRIMARY' AND coalesce(o.is_obsolete,false)=false)
            THEN r.prior_asof_record_date ELSE NULL END AS prior_result_date,
          EXISTS(SELECT 1 FROM serious s WHERE s.nct_id=c.prior_nct_id
            AND s.nct_version=r.prior_asof_record_version
            AND s.adapter_version_public_date<c.checkpoint_date
            AND s.num_at_risk>0 AND s.num_affected IS NOT NULL
            AND s.num_affected>=0 AND s.num_affected<=s.num_at_risk
            AND coalesce(s.is_obsolete,false)=false) AS has_appropriate_denominator_safety
        FROM candidate c LEFT JOIN asof_record r
          ON r.target_nct_id=c.target_nct_id AND r.candidate_drug_key=c.candidate_drug_key
          AND r.prior_nct_id=c.prior_nct_id
    """)
    db.execute("""
        CREATE TEMP TABLE landmark AS
        WITH prior AS (
          SELECT target_nct_id,candidate_drug_key,
            count(DISTINCT prior_nct_id) FILTER(WHERE prior_phase='PHASE1') AS prior_p1_trials,
            count(DISTINCT prior_nct_id) FILTER(WHERE prior_phase='PHASE2') AS prior_p2_trials,
            count(DISTINCT (prior_nct_id,arm_group_ord)) FILTER(WHERE prior_phase='PHASE1') AS prior_p1_arms,
            count(DISTINCT (prior_nct_id,arm_group_ord)) FILTER(WHERE prior_phase='PHASE2') AS prior_p2_arms,
            count(DISTINCT prior_nct_id) FILTER(WHERE prior_phase='PHASE1' AND prior_result_date IS NOT NULL) AS prior_p1_result_trials,
            count(DISTINCT prior_nct_id) FILTER(WHERE prior_phase='PHASE2' AND prior_result_date IS NOT NULL) AS prior_p2_result_trials,
            count(DISTINCT prior_nct_id) FILTER(WHERE has_appropriate_denominator_safety) AS prior_safety_coverage_trials
          FROM contribution GROUP BY 1,2
        ), targets AS (
          SELECT target_nct_id,target_version,checkpoint_date,split,candidate_drug_key,
            count(DISTINCT intervention_ord) AS target_interventions,
            count(DISTINCT arm_group_ord) AS target_arms
          FROM target_exposure WHERE primary_candidate GROUP BY 1,2,3,4,5
        ), target_key_counts AS (
          SELECT target_nct_id,count(DISTINCT candidate_drug_key) AS active_candidate_drug_count
          FROM target_exposure WHERE primary_candidate GROUP BY 1
        )
        SELECT t.*,coalesce(p.prior_p1_trials,0) AS prior_p1_trials,
          coalesce(p.prior_p2_trials,0) AS prior_p2_trials,
          coalesce(p.prior_p1_arms,0) AS prior_p1_arms,
          coalesce(p.prior_p2_arms,0) AS prior_p2_arms,
          coalesce(p.prior_p1_result_trials,0) AS prior_p1_result_trials,
          coalesce(p.prior_p2_result_trials,0) AS prior_p2_result_trials,
          coalesce(p.prior_safety_coverage_trials,0) AS prior_safety_coverage_trials,
          g.efficacy_grade AS phase3_efficacy_label_only,
          g.reason_code AS phase3_reason_label_only,
          g.result_date AS phase3_result_date_label_only,
          g.safety_signal AS phase3_safety_label_only,
          CASE WHEN g.nct_id IS NULL OR g.efficacy_grade='ungradable' THEN 1 ELSE 0 END
            AS phase3_grade_unknown_denominator,
          k.active_candidate_drug_count,
          k.active_candidate_drug_count>1 AS multi_active_phase3_ambiguous
        FROM targets t LEFT JOIN prior p USING(target_nct_id,candidate_drug_key)
        JOIN target_key_counts k USING(target_nct_id)
        LEFT JOIN grades g ON g.nct_id=t.target_nct_id
          AND g.result_date<DATE '2024-01-01'
    """)
    db.execute("""
        CREATE TEMP TABLE drug_rollup AS
        WITH first_landmark AS (
          SELECT * EXCLUDE (rank_no) FROM (
            SELECT l.*,row_number() OVER
              (PARTITION BY candidate_drug_key ORDER BY checkpoint_date,target_nct_id)
              AS rank_no FROM landmark l
          ) WHERE rank_no=1
        ), phase3_trials AS (
          SELECT candidate_drug_key,count(DISTINCT target_nct_id) AS phase3_trial_count,
            count(DISTINCT target_nct_id) FILTER(WHERE NOT multi_active_phase3_ambiguous)
              AS phase3_attributable_count,
            count(DISTINCT target_nct_id) FILTER(WHERE NOT multi_active_phase3_ambiguous
              AND phase3_efficacy_label_only IS NOT NULL
              AND phase3_efficacy_label_only<>'ungradable') AS phase3_graded_count,
            count(DISTINCT target_nct_id) FILTER(WHERE NOT multi_active_phase3_ambiguous
              AND phase3_efficacy_label_only='supported_benefit')
              AS phase3_supported_count,
            count(DISTINCT target_nct_id) FILTER(WHERE NOT multi_active_phase3_ambiguous
              AND phase3_efficacy_label_only='directional_only')
              AS phase3_directional_count,
            count(DISTINCT target_nct_id) FILTER(WHERE NOT multi_active_phase3_ambiguous
              AND phase3_efficacy_label_only='benefit_not_demonstrated')
              AS phase3_not_demonstrated_count
          FROM landmark GROUP BY 1
        )
        SELECT f.candidate_drug_key, f.target_nct_id AS first_phase3_nct_id,
          f.checkpoint_date AS first_phase3_checkpoint, f.split,
          f.prior_p1_trials,f.prior_p2_trials,f.prior_p1_arms,f.prior_p2_arms,
          f.prior_p1_result_trials,f.prior_p2_result_trials,
          f.prior_safety_coverage_trials,p.phase3_trial_count,p.phase3_attributable_count,
          p.phase3_graded_count,
          p.phase3_supported_count,p.phase3_directional_count,p.phase3_not_demonstrated_count,
          p.phase3_trial_count-p.phase3_graded_count AS phase3_unknown_or_ambiguous_denominator,
          'candidate_name_identity_unverified' AS identity_status
        FROM first_landmark f JOIN phase3_trials p USING(candidate_drug_key)
    """)
    duplicate_count = _query_int(db, """SELECT count(*) FROM
      (SELECT target_nct_id,candidate_drug_key,count(*) n FROM landmark GROUP BY 1,2 HAVING n>1)""")
    if duplicate_count:
        raise AssertionError(f"Duplicate drug/landmark rows: {duplicate_count}")
    duplicate_drug = _query_int(db, """SELECT count(*) FROM
      (SELECT candidate_drug_key,count(*) n FROM drug_rollup GROUP BY 1 HAVING n>1)""")
    if duplicate_drug:
        raise AssertionError(f"Duplicate drug rollup keys: {duplicate_drug}")
    leakage = _query_int(db, """SELECT count(*) FROM contribution WHERE
      prior_design_date>=checkpoint_date OR prior_result_date>=checkpoint_date
      OR prior_asof_record_date>=checkpoint_date""")
    if leakage:
        raise AssertionError(f"Post-checkpoint earlier evidence: {leakage}")
    grade_leak = _query_int(db, "SELECT count(*) FROM landmark WHERE phase3_result_date_label_only>=DATE '2024-01-01'")
    if grade_leak:
        raise AssertionError(f"2024+ target labels: {grade_leak}")
    # Name-key overlap across temporal splits invalidates naïve row-level
    # model validation. Mark it explicitly; no model is trained.
    overlap = _query_int(db, """SELECT count(*) FROM
      (SELECT candidate_drug_key FROM landmark GROUP BY 1 HAVING count(DISTINCT split)>1)""")
    alias_only_targets = _query_int(db, """
      SELECT count(DISTINCT t.target_nct_id) FROM target_exposure t
      JOIN alias_review a ON a.alias_key=t.candidate_drug_key
        AND a.canonical_key<>a.alias_key AND a.canonical_count=1
        AND a.primary_candidate AND a.nct_id<>t.target_nct_id
      JOIN relevant r ON r.nct_id=a.nct_id AND r.nct_version=a.nct_version
        AND r.pure_phase IN ('PHASE1','PHASE2') AND r.source_date<t.checkpoint_date
      WHERE t.primary_candidate AND NOT EXISTS (
        SELECT 1 FROM exposure e WHERE e.nct_id=a.nct_id
          AND e.candidate_drug_key=t.candidate_drug_key AND e.primary_candidate)
    """)
    for name, table in [
        ("candidate_exposures", "exposure"), ("alias_review", "alias_review"),
        ("target_exposures", "target_exposure"), ("prior_contributions", "contribution"),
        ("drug_landmarks", "landmark"), ("drug_rollup", "drug_rollup"),
    ]:
        db.execute(f"COPY (SELECT * FROM {table}) TO {_sql_path(out / f'{name}.parquet')} (FORMAT PARQUET)")
    by_split = db.execute("""SELECT split,count(*) landmarks,
      count(DISTINCT target_nct_id) target_trials,
      count(*) FILTER(WHERE prior_p1_trials>0) with_p1,
      count(*) FILTER(WHERE prior_p2_trials>0) with_p2,
      count(*) FILTER(WHERE prior_p1_result_trials>0) with_p1_result,
      count(*) FILTER(WHERE prior_p2_result_trials>0) with_p2_result,
      count(*) FILTER(WHERE phase3_efficacy_label_only='supported_benefit') supported,
      count(*) FILTER(WHERE phase3_grade_unknown_denominator=1) unknown_or_ungradable,
      count(*) FILTER(WHERE phase3_efficacy_label_only<>'ungradable'
        AND phase3_result_date_label_only < CASE WHEN split='train_2005_15'
          THEN DATE '2016-01-01' ELSE DATE '2024-01-01' END) AS grade_public_by_split_cutoff
      FROM landmark GROUP BY 1 ORDER BY 1""").fetchall()
    report = {
        "mode": "pilot" if limit else "full", "phase3_target_ncts": _query_int(db, "SELECT count(*) FROM target"),
        "b17_result_trials": _query_int(db, "SELECT count(*) FROM target t JOIN grades g USING(nct_id) WHERE g.result_date<DATE '2024-01-01'"),
        "target_candidate_ncts": _query_int(db, "SELECT count(DISTINCT target_nct_id) FROM target_exposure"),
        "target_primary_candidate_ncts": _query_int(db, "SELECT count(DISTINCT target_nct_id) FROM target_exposure WHERE primary_candidate"),
        "flagged_target_exposures": _query_int(db, "SELECT count(*) FROM target_exposure WHERE NOT primary_candidate"),
        "alias_only_prior_candidate_target_ncts_review_only": alias_only_targets,
        "alias_review_rows": _query_int(db, "SELECT count(*) FROM alias_review"),
        "alias_collision_rows": _query_int(db, "SELECT count(*) FROM alias_review WHERE canonical_count>1"),
        "landmark_rows": _query_int(db, "SELECT count(*) FROM landmark"),
        "drug_rollup_rows": _query_int(db, "SELECT count(*) FROM drug_rollup"),
        "contribution_rows": _query_int(db, "SELECT count(*) FROM contribution"),
        "train_validation_drug_keys_overlap": overlap,
        "by_split": [dict(zip(["split","landmarks","target_trials","with_p1","with_p2","with_p1_result","with_p2_result","supported","unknown_or_ungradable","grade_public_by_split_cutoff"], row)) for row in by_split],
        "model_status": "NOT_ESTIMABLE: unverified active-ingredient/indication identity, zero supported-benefit class; no fit or validation",
        "input_paths": {k: str(v) for k,v in inputs.items()},
        "input_sha256": {k: ({p.name: _sha256(p) for p in sorted(v.glob('*.parquet'))}
                              if k == 'core' else _sha256(v)) for k,v in inputs.items()},
        "output_sha256": {p.name: _sha256(p) for p in out.glob("*.parquet")},
        "notes": [
            "Exact normalized names are candidate identities, not verified ingredients.",
            "Alias rows are review-only, never silently merged into primary candidates.",
            "Prior outcomes are checked only in the latest whole-record version strictly before checkpoint; retracted results are not carried forward.",
            "Safety coverage requires num_at_risk and num_affected; no rates or event sums calculated.",
            "Phase 3 grades are label-only and excluded from prior_contributions.",
            "Train/validation name-key overlap is reported; no row-level model is fit.",
        ],
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    db.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cohort", "design", "protocol", "results", "grades", "core", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(build(**vars(args)), indent=2, default=str))


if __name__ == "__main__":
    main()
