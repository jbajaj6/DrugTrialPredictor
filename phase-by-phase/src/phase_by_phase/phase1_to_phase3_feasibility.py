"""Development-only feasibility of Phase 1 results predicting Phase 3 p<.05.

An exact drug/condition string match is only a candidate program link. This
audit deliberately rejects one-to-many links and never treats missing p as 0.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from .historical_dev_models import digest, literal


CUTOFF = pd.Timestamp("2024-01-01")
MIN_TRAIN, MIN_VALID, MIN_CLASS = 100, 50, 10


def link_eligibility(rows: pd.DataFrame) -> pd.DataFrame:
    """Fail closed on candidate, source-version, chronology and label ambiguity."""
    result = rows.copy()
    p1_checkpoint = pd.to_datetime(result.phase1_checkpoint_date)
    p1_date = pd.to_datetime(result.phase1_result_date)
    p3_date = pd.to_datetime(result.phase3_checkpoint_date)
    label_date = pd.to_datetime(result.phase3_label_date)
    result["phase1_result_available"] = (p1_date.notna() & (p1_date > p1_checkpoint)
                                         & (p1_date < p3_date)
                                         & (p1_date < CUTOFF))
    result["unique_candidate_pair"] = ((result.phase1_candidate_count == 1)
                                        & (result.phase3_candidate_count == 1))
    result["link_eligible"] = (result.unique_candidate_pair
                               & result.phase1_result_available
                               & (result.phase1_nct_id != result.phase3_nct_id)
                               & result.drug_key.notna() & result.condition_key.notna()
                               & (result.drug_key != "PLACEBO"))
    result["label_known"] = (result.phase3_label.notna() & label_date.notna()
                              & (label_date > p3_date) & (label_date < CUTOFF))
    return result


def support_gate(rows: pd.DataFrame) -> dict:
    """Development split and independent program grouping precede any fit."""
    eligible = rows[rows.link_eligible].copy()
    eligible["phase1_result_date"] = pd.to_datetime(eligible.phase1_result_date)
    eligible["phase3_label_date"] = pd.to_datetime(eligible.phase3_label_date)
    train = eligible[(eligible.phase1_result_date >= "2005-01-01")
                     & (eligible.phase1_result_date < "2016-01-01")
                     & eligible.label_known & (eligible.phase3_label_date < "2016-01-01")]
    validation = eligible[(eligible.phase1_result_date >= "2016-01-01")
                          & (eligible.phase1_result_date < "2020-01-01")
                          & eligible.label_known]
    # A program may have multiple NCTs; no matched drug/condition group may
    # appear in both partitions. Exclude overlap, never move a row across time.
    train_groups = set(zip(train.drug_key, train.condition_key))
    val_groups = set(zip(validation.drug_key, validation.condition_key))
    overlap = train_groups & val_groups
    train = train.loc[[pair not in overlap for pair in zip(train.drug_key, train.condition_key)]]
    validation = validation.loc[[pair not in overlap for pair in zip(validation.drug_key, validation.condition_key)]]
    counts = {"train": len(train), "validation": len(validation),
              "train_0": int((train.phase3_label == 0).sum()),
              "train_1": int((train.phase3_label == 1).sum()),
              "validation_0": int((validation.phase3_label == 0).sum()),
              "validation_1": int((validation.phase3_label == 1).sum()),
              "overlapping_program_groups_excluded": len(overlap)}
    counts["estimable"] = (counts["train"] >= MIN_TRAIN
                           and counts["validation"] >= MIN_VALID
                           and all(counts[key] >= MIN_CLASS for key in
                                   ("train_0", "train_1", "validation_0", "validation_1")))
    return counts


def run(source: Path, design: Path, protocol: Path, results: Path,
        prior_rows: Path, out: Path, limit_targets: int | None = None) -> dict:
    if out.exists():
        raise FileExistsError(f"Refusing overwrite: {out}")
    if limit_targets is not None and limit_targets < 1:
        raise ValueError("limit_targets must be positive")
    source, design, protocol, results, prior_rows = (
        p.resolve() for p in (source, design, protocol, results, prior_rows))
    design_manifest = json.loads((design.parent / "manifest.json").read_text())
    protocol_manifest = json.loads((protocol / "manifest.json").read_text())
    results_manifest = json.loads((results / "manifest.json").read_text())
    prior_manifest = json.loads((prior_rows.parent / "manifest.json").read_text())
    if any(m.get("source_root") != str(source) for m in
           (design_manifest, protocol_manifest, results_manifest, prior_manifest)):
        raise ValueError("Pinned source root mismatch")
    for path, expected in ((design, design_manifest["output_sha256"].get(design.name)),
                           (prior_rows, prior_manifest["output_sha256"].get(prior_rows.name)),
                           (protocol / "interventions_clean.parquet",
                            protocol_manifest["output_files_sha256"].get("interventions_clean.parquet")),
                           (results / "results_outcome_measures_clean.parquet",
                            results_manifest["output_files_sha256"].get("results_outcome_measures_clean.parquet")),
                           (results / "results_outcome_measurements_clean.parquet",
                            results_manifest["output_files_sha256"].get("results_outcome_measurements_clean.parquet"))):
        if expected != digest(path):
            raise ValueError(f"Pinned input hash mismatch: {path.name}")
    conditions = sorted((source / "conditions").glob("*.parquet"))
    if not conditions:
        raise FileNotFoundError("Missing pinned conditions source")
    # B11a does not inventory conditions. Capture every source-part digest in
    # this run's manifest; no upstream digest is falsely claimed verified.
    out.mkdir(parents=True)
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'")
    con.execute("SET threads=2")
    (out / "duckdb_spill").mkdir()
    con.execute(f"SET temp_directory={literal(out / 'duckdb_spill')}")
    try:
        con.execute(f"CREATE VIEW design AS SELECT nct_id, first_public_nct_version AS nct_version, "
                    f"CAST(first_public_date AS DATE) checkpoint_date, phase_membership "
                    f"FROM read_parquet({literal(design)}) "
                    "WHERE first_public_date < DATE '2024-01-01' AND "
                    "phase_membership IN ('PHASE1','PHASE3') AND drug_intervention_count=1 "
                    "AND archive_left_truncated IS FALSE")
        con.execute(f"CREATE VIEW eligible_prior AS SELECT nct_id,pure_phase FROM "
                    f"read_parquet({literal(prior_rows)}) "
                    "WHERE pure_phase IN ('PHASE1','PHASE3')")
        con.execute("CREATE TEMP TABLE phases AS SELECT d.* FROM design d "
                    "JOIN eligible_prior e ON e.nct_id=d.nct_id "
                    "AND e.pure_phase=d.phase_membership")
        con.execute("CREATE TEMP TABLE targets AS SELECT * FROM phases "
                    "WHERE phase_membership='PHASE3' "
                    "AND checkpoint_date >= DATE '2005-01-01' AND checkpoint_date < DATE '2020-01-01' "
                    "ORDER BY nct_id " + (f"LIMIT {limit_targets}" if limit_targets else ""))
        con.execute(f"CREATE VIEW interventions AS SELECT nct_id,nct_version,intervention_name "
                    f"FROM read_parquet({literal(protocol / 'interventions_clean.parquet')}) "
                    "WHERE upper(intervention_type)='DRUG' AND is_obsolete IS DISTINCT FROM TRUE")
        con.execute(f"CREATE VIEW conditions AS SELECT nct_id,nct_version,condition "
                    f"FROM read_parquet([{','.join(literal(p) for p in conditions)}]) "
                    "WHERE is_obsolete IS DISTINCT FROM TRUE")
        con.execute("""CREATE TEMP TABLE keys AS
            WITH drug AS (SELECT p.nct_id, upper(trim(i.intervention_name)) drug_key,
                                 COUNT(*) drug_rows
                 FROM phases p JOIN interventions i USING(nct_id,nct_version)
                 GROUP BY 1,2),
                 cond AS (SELECT p.nct_id, upper(trim(c.condition)) condition_key,
                                  COUNT(*) condition_rows
                 FROM phases p JOIN conditions c USING(nct_id,nct_version)
                 GROUP BY 1,2),
                 single_drug AS (SELECT nct_id,MIN(drug_key) drug_key FROM drug
                    GROUP BY 1 HAVING SUM(drug_rows)=1 AND COUNT(*)=1),
                 single_condition AS (SELECT nct_id,MIN(condition_key) condition_key FROM cond
                    GROUP BY 1 HAVING SUM(condition_rows)=1 AND COUNT(*)=1)
            SELECT p.nct_id,p.nct_version,p.checkpoint_date,p.phase_membership,
                   d.drug_key,c.condition_key
            FROM phases p JOIN single_drug d USING(nct_id)
                          JOIN single_condition c USING(nct_id)
            WHERE d.drug_key IS NOT NULL AND d.drug_key NOT IN ('','PLACEBO')
                  AND c.condition_key IS NOT NULL AND c.condition_key!=''""")
        # P1 results are the earliest exact historical version containing a
        # reported outcome. Never reuse a later P1 revision at an earlier date.
        measure = results / "results_outcome_measures_clean.parquet"
        measurement = results / "results_outcome_measurements_clean.parquet"
        con.execute(f"""CREATE TEMP TABLE phase1_result_versions AS
            SELECT k.nct_id,k.nct_version AS checkpoint_version,
                   m.nct_version result_version,
                   CAST(m.adapter_version_public_date AS DATE) result_date,
                   COUNT(DISTINCT m.outcome_ord) outcome_count,
                   COUNT(DISTINCT m.outcome_ord) FILTER (WHERE upper(m.type)='PRIMARY') primary_outcome_count,
                   COUNT(*) FILTER (WHERE coalesce(trim(m.description),'')!='') outcome_description_count
            FROM keys k JOIN read_parquet({literal(measure)}) m ON k.nct_id=m.nct_id
            WHERE k.phase_membership='PHASE1'
                  AND m.adapter_version_public_date < DATE '2024-01-01'
                  AND m.adapter_version_public_date > k.checkpoint_date
                  AND m.adapter_core_is_obsolete IS DISTINCT FROM TRUE
                  AND m.is_obsolete IS DISTINCT FROM TRUE
            GROUP BY 1,2,3,4""")
        con.execute("""CREATE TEMP TABLE phase1_first_result AS SELECT * EXCLUDE(rn) FROM (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY nct_id ORDER BY result_date,result_version) rn
            FROM phase1_result_versions) WHERE rn=1""")
        con.execute(f"""CREATE TEMP TABLE phase1_measurements AS SELECT r.nct_id,
            COUNT(*) AS measurement_count,
            COUNT(*) FILTER (WHERE TRY_CAST(m.value AS DOUBLE) IS NOT NULL) AS numeric_measurement_count,
            COUNT(*) FILTER (WHERE m.value IS NOT NULL) AS nonempty_measurement_count
            FROM phase1_first_result r JOIN read_parquet({literal(measurement)}) m
            ON m.nct_id=r.nct_id AND m.nct_version=r.result_version
            WHERE m.is_obsolete IS DISTINCT FROM TRUE
            GROUP BY r.nct_id""")
        con.execute(f"""CREATE VIEW labels AS SELECT nct_id, CAST(significance_label AS INTEGER) phase3_label,
            CAST(significance_label_date AS DATE) phase3_label_date
            FROM read_parquet({literal(prior_rows)}) WHERE pure_phase='PHASE3'""")
        con.execute("""CREATE TEMP TABLE pairs AS WITH candidate AS (
            SELECT p1.nct_id phase1_nct_id,p1.nct_version phase1_checkpoint_version,
                p1.checkpoint_date phase1_checkpoint_date,
                p3.nct_id phase3_nct_id,p3.nct_version phase3_checkpoint_version,
                p3.checkpoint_date phase3_checkpoint_date,
                p1.drug_key,p1.condition_key,
                r.result_version phase1_result_version,r.result_date phase1_result_date,
                r.outcome_count,r.primary_outcome_count,r.outcome_description_count,
                z.measurement_count,z.numeric_measurement_count,z.nonempty_measurement_count,
                l.phase3_label,l.phase3_label_date
            FROM keys p1 JOIN keys p3 ON p1.drug_key=p3.drug_key
                AND p1.condition_key=p3.condition_key AND p1.nct_id!=p3.nct_id
            LEFT JOIN phase1_first_result r ON r.nct_id=p1.nct_id
            LEFT JOIN phase1_measurements z ON z.nct_id=p1.nct_id
            LEFT JOIN labels l ON l.nct_id=p3.nct_id
            WHERE p1.phase_membership='PHASE1' AND p3.phase_membership='PHASE3'
                AND p3.nct_id IN (SELECT nct_id FROM targets)
                AND p1.checkpoint_date < p3.checkpoint_date
            ), counted AS (SELECT *,
              COUNT(*) OVER(PARTITION BY phase3_nct_id) phase1_candidate_count,
              COUNT(*) OVER(PARTITION BY phase1_nct_id) phase3_candidate_count
              FROM candidate) SELECT * FROM counted""")
        rows = con.execute("SELECT * FROM pairs").df()
        funnel = {name: int(con.execute(query).fetchone()[0]) for name,query in {
            "phase1_first_designs": "SELECT count(*) FROM phases WHERE phase_membership='PHASE1'",
            "phase3_target_first_designs": "SELECT count(*) FROM targets",
            "single_drug_condition_trial_keys": "SELECT count(*) FROM keys",
            "candidate_pairs": "SELECT count(*) FROM pairs",
            "phase1_result_versions": "SELECT count(*) FROM phase1_first_result",
        }.items()}
    finally:
        con.close()
    if not rows.empty:
        rows = link_eligibility(rows)
    else:
        rows = pd.DataFrame(columns=["phase1_nct_id", "phase3_nct_id", "link_eligible",
                                     "label_known", "phase3_checkpoint_date", "phase3_label_date",
                                     "phase3_label", "drug_key", "condition_key"])
    funnel.update({"unique_candidate_pairs": int(rows.unique_candidate_pair.sum()) if not rows.empty else 0,
                   "linked_with_public_phase1_result_before_phase3": int(rows.link_eligible.sum()),
                   "linked_labeled_phase3": int((rows.link_eligible & rows.label_known).sum()),
                   "linked_unknown_phase3_label": int((rows.link_eligible & ~rows.label_known).sum()),
                   "linked_numeric_phase1_measurements": int((rows.link_eligible &
                       (rows.numeric_measurement_count.fillna(0) > 0)).sum()) if not rows.empty else 0})
    support = support_gate(rows) if not rows.empty else {"estimable": False,
        "train": 0, "validation": 0, "train_0": 0, "train_1": 0,
        "validation_0": 0, "validation_1": 0, "overlapping_program_groups_excluded": 0}
    rows.to_parquet(out / "candidate_pairs.parquet", index=False)
    report = {"status": "feasibility_gate_only_no_model_trained",
              "scope": "development pre-2024 outcomes; exact-string links provisional",
              "pilot_target_limit": limit_targets, "funnel": funnel, "support": support,
              "phase1_availability_fields_not_model_features": ["outcome_count",
                  "primary_outcome_count", "outcome_description_count", "measurement_count",
                  "numeric_measurement_count", "nonempty_measurement_count"],
              "input_sha256": {str(path): digest(path) for path in
                  (design, protocol / 'interventions_clean.parquet',
                   results / 'results_outcome_measures_clean.parquet',
                   results / 'results_outcome_measurements_clean.parquet', prior_rows,
                   *conditions)},
              "code_sha256": digest(Path(__file__))}
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    report["output_sha256"] = {p.name: digest(p) for p in out.iterdir() if p.is_file()}
    (out / "manifest.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "design", "protocol", "results", "prior_rows", "out"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--limit-targets", type=int)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.design, args.protocol, args.results,
                         args.prior_rows, args.out, args.limit_targets), indent=2))


if __name__ == "__main__":
    main()
