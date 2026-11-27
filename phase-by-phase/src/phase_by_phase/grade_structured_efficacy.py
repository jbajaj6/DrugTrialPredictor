"""Conservative, development-only grading of first posted Phase 3 results.

These grades describe *reported evidence*, not FDA approval or clinical efficacy.
Every positive grade requires a unique arm-to-result-group mapping and an endpoint
whose favorable numerical direction is specified by a deliberately tiny whitelist.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import duckdb
import pandas as pd

from .historical_dev_models import digest, literal


CUTOFF = pd.Timestamp("2024-01-01")
REQUIRED = ("results_outcome_measures_clean", "results_outcome_groups_clean",
            "results_outcome_measurements_clean", "results_outcome_analyses_clean",
            "results_outcome_analysis_groups_clean",
            "results_adverse_serious_event_stats_clean")


def favorable_direction(title: str | None) -> str | None:
    """Only unambiguous endpoint families; all others require human review."""
    name = str(title or "").casefold().strip()
    if re.fullmatch(r"(?:overall survival|progression.free survival|event.free survival|disease.free survival)(?:\s*\(.*\))?", name):
        return "higher"
    if re.fullmatch(r"(?:time to death|time to progression|time to relapse)(?:\s*\(.*\))?", name):
        return "higher"
    return None


def parse_p(value: str | None) -> tuple[float | None, str]:
    if value is None or not str(value).strip():
        return None, "p_missing"
    match = re.fullmatch(r"\s*([<>]=?|=)?\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*", str(value))
    if not match:
        return None, "p_ambiguous"
    op, number = match.group(1) or "=", float(match.group(2))
    if op == "<" and number <= .05:
        return number, "p_supports_threshold"
    if op == "=" and number < .05:
        return number, "p_supports_threshold"
    if op in ("=", ">", ">=") and number >= .05:
        return number, "p_does_not_support_threshold"
    return None, "p_ambiguous"


def _live(records: pd.DataFrame) -> pd.DataFrame:
    if records.empty:
        return records
    return records[records.is_obsolete.ne(True) & records.adapter_core_is_obsolete.ne(True)]


def grade_trial(measures: pd.DataFrame, groups: pd.DataFrame,
                measurements: pd.DataFrame, analyses: pd.DataFrame,
                arms: pd.DataFrame, analysis_groups: pd.DataFrame | None = None) -> dict:
    """Grade one exact NCT/version. Fail closed on all structural ambiguity."""
    result = {"efficacy_grade": "ungradable", "reason_code": "no_primary_result",
              "safety_signal": "unknown", "safety_reason_code": "event_comparison_not_verified",
              "outcome_ord": None, "treatment_group_id": None,
              "comparator_group_id": None, "treatment_value": None,
              "comparator_value": None, "effect_difference": None,
              "p_value_raw": None, "p_parse_reason": None,
              "favorable_direction": None}
    primary = _live(measures)
    primary = primary[primary.type.fillna("").str.upper().eq("PRIMARY")]
    if len(primary) != 1 or primary.outcome_ord.isna().any():
        result["reason_code"] = "multiple_primary_outcomes" if len(primary) > 1 else "no_primary_result"
        return result
    outcome = primary.iloc[0]
    result["outcome_ord"] = int(outcome.outcome_ord)
    direction = favorable_direction(outcome.title)
    result["favorable_direction"] = direction
    if direction is None:
        result["reason_code"] = "effect_direction_not_verified"
        return result
    if str(outcome.get("unit_of_measure", "")).strip().casefold() not in {
            "days", "weeks", "months", "years"} or str(outcome.get("param_type", "")).strip().casefold() not in {
            "median", "mean"}:
        result["reason_code"] = "effect_unit_or_parameter_unverified"
        return result
    group = _live(groups)
    group = group[group.outcome_ord.eq(outcome.outcome_ord)]
    arm = _live(arms)
    if len(group) != 2 or group.group_id.nunique() != 2 or len(arm) != 2:
        result["reason_code"] = "ambiguous_groups_or_arms"
        return result
    # Registry group titles are not globally unique; accept only exact,
    # one-to-one, same-version arm labels and explicit arm roles.
    arm_titles = arm.arm_label.fillna("").str.strip().str.casefold()
    group_titles = group.title.fillna("").str.strip().str.casefold()
    if (arm_titles.eq("").any() or group_titles.eq("").any()
            or arm_titles.nunique() != 2 or group_titles.nunique() != 2
            or set(arm_titles) != set(group_titles)):
        result["reason_code"] = "arm_group_mapping_unverified"
        return result
    role = dict(zip(arm_titles, arm.arm_type.fillna("")))
    if sorted(role.values()) not in (["EXPERIMENTAL", "PLACEBO_COMPARATOR"],
                                     ["ACTIVE_COMPARATOR", "EXPERIMENTAL"]):
        result["reason_code"] = "treatment_comparator_unverified"
        return result
    gid = dict(zip(group_titles, group.group_id))
    treatment = gid[next(k for k,v in role.items() if v == "EXPERIMENTAL")]
    comparator = gid[next(k for k,v in role.items() if v != "EXPERIMENTAL")]
    result["treatment_group_id"] = treatment
    result["comparator_group_id"] = comparator
    values = _live(measurements)
    values = values[values.outcome_ord.eq(outcome.outcome_ord)]
    if (len(values) != 2 or values.group_id.nunique() != 2
            or set(values.group_id) != {treatment, comparator}):
        result["reason_code"] = "multiple_or_missing_measurements"
        return result
    numeric = pd.to_numeric(values.value, errors="coerce")
    if numeric.isna().any():
        result["reason_code"] = "non_numeric_measurement"
        return result
    by_group = dict(zip(values.group_id, numeric))
    treatment_value, comparator_value = float(by_group[treatment]), float(by_group[comparator])
    delta = treatment_value - comparator_value
    result.update(treatment_value=treatment_value, comparator_value=comparator_value,
                  effect_difference=delta)
    analysis = _live(analyses)
    analysis = analysis[analysis.outcome_ord.eq(outcome.outcome_ord)]
    if len(analysis) > 1:
        result["reason_code"] = "multiple_analyses_multiplicity_unknown"
        return result
    if len(analysis) == 1:
        row = analysis.iloc[0]
        result["p_value_raw"] = row.p_value
        if (pd.notna(row.tested_non_inferiority) and bool(row.tested_non_inferiority)) or pd.notna(row.non_inferiority_type):
            result["reason_code"] = "noninferiority_requires_review"
            return result
        # Explicit structured analysis-group IDs, not prose substring matching,
        # are required to attribute this p-value to the measured contrast.
        if analysis_groups is None:
            result["reason_code"] = "analysis_comparison_unverified"
            return result
        linked = _live(analysis_groups)
        linked = linked[(linked.outcome_ord.eq(outcome.outcome_ord))
                        & (linked.analysis_ord.eq(row.analysis_ord))]
        if (len(linked) != 2 or linked.group_id.nunique() != 2
                or set(linked.group_id) != {treatment, comparator}):
            result["reason_code"] = "analysis_comparison_unverified"
            return result
        p, p_reason = parse_p(row.p_value)
        result["p_parse_reason"] = p_reason
    else:
        p, p_reason = None, "p_missing"
        result["p_parse_reason"] = p_reason
    favorable = delta > 0 if direction == "higher" else delta < 0
    if favorable and p_reason == "p_supports_threshold":
        result.update(efficacy_grade="supported_benefit", reason_code="favorable_controlled_primary_p")
    elif favorable and p_reason in ("p_missing", "p_ambiguous"):
        result.update(efficacy_grade="directional_only", reason_code="favorable_difference_inference_missing")
    elif not favorable or p_reason == "p_does_not_support_threshold":
        result.update(efficacy_grade="benefit_not_demonstrated", reason_code="no_supported_favorable_comparison")
    return result


def run(prior_rows: Path, protocol: Path, results: Path, out: Path,
        limit_targets: int | None = None) -> dict:
    """Choose earliest exact public version with posted primary evidence."""
    if out.exists():
        raise FileExistsError(f"Refusing overwrite: {out}")
    if limit_targets is not None and limit_targets < 1:
        raise ValueError("limit_targets must be positive")
    prior_rows, protocol, results = (p.resolve() for p in (prior_rows, protocol, results))
    manifests = [json.loads((prior_rows.parent / "manifest.json").read_text()),
                 json.loads((protocol / "manifest.json").read_text()),
                 json.loads((results / "manifest.json").read_text())]
    inputs = {prior_rows: manifests[0]["output_sha256"].get(prior_rows.name)}
    for name in ("arms_clean.parquet",):
        inputs[protocol / name] = manifests[1]["output_files_sha256"].get(name)
    for name in REQUIRED:
        inputs[results / f"{name}.parquet"] = manifests[2]["output_files_sha256"].get(f"{name}.parquet")
    for path, expected in inputs.items():
        if digest(path) != expected:
            raise ValueError(f"Pinned input hash mismatch: {path}")
    out.mkdir(parents=True)
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'")
    con.execute("SET threads=2")
    (out / "duckdb_spill").mkdir()
    con.execute(f"SET temp_directory={literal(out / 'duckdb_spill')}")
    try:
        con.execute(f"""CREATE TEMP TABLE targets AS SELECT nct_id,
            CAST(first_public_date AS DATE) checkpoint_date
            FROM read_parquet({literal(prior_rows)})
            WHERE pure_phase='PHASE3' AND first_public_date < DATE '2020-01-01'
              AND first_public_date >= DATE '2005-01-01'
            ORDER BY nct_id {f'LIMIT {limit_targets}' if limit_targets else ''}""")
        m = results / "results_outcome_measures_clean.parquet"
        v = results / "results_outcome_measurements_clean.parquet"
        a = results / "results_outcome_analyses_clean.parquet"
        con.execute(f"""CREATE TEMP TABLE selected AS WITH eligible_versions AS (
            SELECT DISTINCT m.nct_id,m.nct_version,
              CAST(m.adapter_version_public_date AS DATE) result_date
            FROM read_parquet({literal(m)}) m JOIN targets t USING(nct_id)
            WHERE upper(m.type)='PRIMARY' AND m.is_obsolete IS DISTINCT FROM TRUE
              AND m.adapter_core_is_obsolete IS DISTINCT FROM TRUE
              AND m.adapter_version_public_date > t.checkpoint_date
              AND m.adapter_version_public_date < DATE '2024-01-01'
              AND (EXISTS (SELECT 1 FROM read_parquet({literal(v)}) x
                    WHERE x.nct_id=m.nct_id AND x.nct_version=m.nct_version
                      AND x.outcome_ord=m.outcome_ord AND x.is_obsolete IS DISTINCT FROM TRUE)
                OR EXISTS (SELECT 1 FROM read_parquet({literal(a)}) x
                    WHERE x.nct_id=m.nct_id AND x.nct_version=m.nct_version
                      AND x.outcome_ord=m.outcome_ord AND x.is_obsolete IS DISTINCT FROM TRUE))
            ), ranked AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY nct_id
                ORDER BY result_date,nct_version) rn FROM eligible_versions)
            SELECT nct_id,nct_version,result_date FROM ranked WHERE rn=1""")
        targets = con.execute("SELECT * FROM targets").df()
        selected = con.execute("SELECT * FROM selected").df()
        tables = {}
        for name in REQUIRED:
            path = results / f"{name}.parquet"
            tables[name] = con.execute(f"SELECT x.* FROM read_parquet({literal(path)}) x JOIN selected s USING(nct_id,nct_version) WHERE x.is_obsolete IS DISTINCT FROM TRUE AND x.adapter_core_is_obsolete IS DISTINCT FROM TRUE").df()
        arms = con.execute(f"SELECT x.* FROM read_parquet({literal(protocol / 'arms_clean.parquet')}) x JOIN selected s USING(nct_id,nct_version) WHERE x.is_obsolete IS DISTINCT FROM TRUE AND x.adapter_core_is_obsolete IS DISTINCT FROM TRUE").df()
    finally:
        con.close()
    for name, table in tables.items():
        table.to_parquet(out / f"{name}.parquet", index=False)
    arms.to_parquet(out / "arms_at_result_version.parquet", index=False)
    groups = {name: {key: block for key,block in table.groupby(["nct_id","nct_version"])}
              for name,table in tables.items()}
    arm_groups = {key: block for key,block in arms.groupby(["nct_id","nct_version"])}
    empty = {name: table.iloc[0:0] for name,table in tables.items()}
    records = []
    for row in selected.itertuples(index=False):
        key = (row.nct_id,row.nct_version)
        primary_rows = groups[REQUIRED[0]].get(key,empty[REQUIRED[0]])
        measurement_rows = groups[REQUIRED[2]].get(key,empty[REQUIRED[2]])
        analysis_rows = groups[REQUIRED[3]].get(key,empty[REQUIRED[3]])
        serious_rows = groups[REQUIRED[5]].get(key,empty[REQUIRED[5]])
        numeric = pd.to_numeric(measurement_rows.value,errors="coerce")
        primary_ords = set(primary_rows.loc[primary_rows.type.fillna("").str.upper().eq("PRIMARY"),"outcome_ord"])
        primary_numeric = measurement_rows[measurement_rows.outcome_ord.isin(primary_ords)].loc[numeric.notna()]
        primary_analyses = analysis_rows[analysis_rows.outcome_ord.isin(primary_ords)]
        grade = grade_trial(groups[REQUIRED[0]].get(key,empty[REQUIRED[0]]),
                            groups[REQUIRED[1]].get(key,empty[REQUIRED[1]]),
                            groups[REQUIRED[2]].get(key,empty[REQUIRED[2]]),
                            groups[REQUIRED[3]].get(key,empty[REQUIRED[3]]),
                            arm_groups.get(key,arms.iloc[0:0]),
                            groups[REQUIRED[4]].get(key,empty[REQUIRED[4]]))
        records.append(dict(nct_id=row.nct_id,nct_version=row.nct_version,
                            result_date=row.result_date,
                            primary_outcome_count=len(primary_ords),
                            primary_numeric_result_group_count=int(primary_numeric.group_id.nunique()),
                            primary_analysis_count=len(primary_analyses),
                            primary_p_present=bool(primary_analyses.p_value.notna().any()),
                            primary_ci_present=bool(primary_analyses.ci_lower_limit.notna().any()
                                                    & primary_analyses.ci_upper_limit.notna().any()),
                            serious_event_stat_row_count=len(serious_rows),
                            **grade))
    grades = pd.DataFrame.from_records(records)
    grades.to_parquet(out / "graded_trials.parquet", index=False)
    counts = grades.efficacy_grade.value_counts().to_dict() if not grades.empty else {}
    report = {"status":"development_grading_only_no_model_trained",
              "version_policy":"earliest pre-2024 posted version after checkpoint containing a primary outcome with measurements or analysis; exact NCT/version joins",
              "scope":"B15 pure Phase 3 development, no 2024+ result values",
              "targets":len(targets),"selected_result_versions":len(selected),
              "without_posted_primary_result":len(targets)-len(selected),
              "grade_counts":counts,"reason_counts":grades.reason_code.value_counts().to_dict() if not grades.empty else {},
              "evidence_availability":{"at_least_two_numeric_primary_groups":int((grades.primary_numeric_result_group_count >= 2).sum()) if not grades.empty else 0,
                                       "primary_analysis_present":int((grades.primary_analysis_count > 0).sum()) if not grades.empty else 0,
                                       "primary_p_present":int(grades.primary_p_present.sum()) if not grades.empty else 0,
                                       "primary_ci_present":int(grades.primary_ci_present.sum()) if not grades.empty else 0,
                                       "serious_event_stats_present":int((grades.serious_event_stat_row_count > 0).sum()) if not grades.empty else 0},
              "safety_note":"Serious event rows preserved but no safety signal inferred without defensible person-level comparator rates",
              "model_support_gate":{"supported_benefit_count":int(counts.get("supported_benefit",0)),
                                    "minimum_positive_per_split":10,
                                    "verified_drug_indication_links":"not_established_by_this_grader",
                                    "estimable":False,
                                    "reason":"zero supported-benefit labels or no verified independent-program linkage; do not fit"},
              "model_status":"not_estimable_no_model_trained"}
    (out / "report.json").write_text(json.dumps(report,indent=2,default=str)+"\n")
    manifest = {"input_sha256":{str(p):digest(p) for p in inputs},
                "output_sha256":{p.name:digest(p) for p in out.glob("*.parquet")},
                "report_sha256":digest(out / "report.json")}
    (out / "manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-rows",type=Path,required=True)
    parser.add_argument("--protocol",type=Path,required=True)
    parser.add_argument("--results",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--limit-targets",type=int)
    args = parser.parse_args()
    print(json.dumps(run(args.prior_rows,args.protocol,args.results,args.out,args.limit_targets),indent=2))


if __name__ == "__main__":
    main()
