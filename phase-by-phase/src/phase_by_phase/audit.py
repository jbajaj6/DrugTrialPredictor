"""Fail-closed structural audit, with clinical uncertainty reported separately.

This audit does not certify biological identity, historical feature availability,
or model validity. A structurally sound exact-label cohort therefore still has
an overall WARN until those scientific limitations are addressed.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from functools import lru_cache
from typing import Any

import pandas as pd

from .organize import DATE_FIELDS, SCHEMAS, control_kind, label_key


CANONICAL_PHASES = {"EARLY_PHASE1", "PHASE1", "PHASE1/PHASE2", "PHASE2", "PHASE2/PHASE3", "PHASE3", "PHASE4"}
STRICT_PHASES = CANONICAL_PHASES - {"PHASE4"}
REVIEW_COLUMNS = [
    "program_id", "regimen_id", "indication_id", "component_keys_json", "n_trials",
    "phase_labels", "review_stratum", "nct_ids_json", "source_urls_json",
    "identity_review", "regimen_review", "indication_review", "notes",
]


def _safe(value: Any) -> Any:
    """Convert numpy/pandas scalars and missing values to strict JSON values."""
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    if value is None or value is pd.NA:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _blank(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype("string").str.strip().eq("").fillna(False)


def _nonblank_set(series: pd.Series) -> set:
    return set(series[~_blank(series)])


@lru_cache(maxsize=100_000)
def _observed_precision(raw: str | None) -> str:
    if raw is None or not raw.strip():
        return "missing"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            date.fromisoformat(raw)
            return "day"
        if re.fullmatch(r"\d{4}-\d{2}", raw):
            date.fromisoformat(raw + "-01")
            return "month"
        if re.fullmatch(r"\d{4}", raw):
            date(int(raw), 1, 1)
            return "year"
    except ValueError:
        pass
    return "invalid"


def _components(value: Any) -> list[str] | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, list) or not parsed or any(not isinstance(item, str) for item in parsed):
        return None
    if parsed != sorted(set(parsed)):
        return None
    if any(label_key(item) != item or not item or control_kind(item) != "not_control" for item in parsed):
        return None
    if any(re.search(r"\+|/|\b(?:and|plus|versus|vs|or)\b", item) for item in parsed):
        return None
    return parsed


def audit_tables(tables: dict[str, pd.DataFrame], manifest: dict[str, Any]) -> dict[str, Any]:
    """Audit organized tables without modifying them or writing any files.

    ``manifest`` may contain ``complete``, ``records``, ``total_count`` and
    retrieval/cutoff metadata. Incompleteness is WARN, contradictory counts are
    FAIL, and absent metadata are reported rather than inferred.
    """
    checks: list[dict[str, Any]] = []

    def check(name: str, status: str, value: Any, message: str) -> None:
        checks.append({"name": name, "status": status, "value": _safe(value), "message": message})

    summary: dict[str, Any] = {
        "table_rows": {name: len(frame) for name, frame in tables.items() if isinstance(frame, pd.DataFrame)},
        "source": {key: manifest.get(key) for key in [
            "complete", "records", "total_count", "query", "cutoff", "retrieved_at_utc",
            "retrieved_at", "retrieval_started_at", "retrieval_completed_at", "data_timestamp",
            "source", "api_url", "sort", "snapshot_date",
        ] if key in manifest},
    }

    def finish() -> dict[str, Any]:
        hard_fail = any(item["status"] == "FAIL" for item in checks)
        summary["structural_status"] = "FAIL" if hard_fail else "PASS"
        summary["clinical_identity_validated"] = False
        result = {
            "summary": summary, "checks": checks,
            "overall": "FAIL" if hard_fail else ("WARN" if any(item["status"] == "WARN" for item in checks) else "PASS"),
            "hard_fail": hard_fail,
        }
        return _safe(result)

    bad_schema = False
    for name, columns in SCHEMAS.items():
        frame = tables.get(name)
        missing = columns if not isinstance(frame, pd.DataFrame) else sorted(set(columns) - set(frame.columns))
        check(f"schema_{name}", "FAIL" if missing else "PASS", missing, "All documented columns must exist, including in empty tables.")
        bad_schema |= bool(missing)
    if bad_schema:
        return finish()

    trials, bridge, programs = tables["trials"], tables["program_trials"], tables["programs"]
    exclusions, aliases = tables["exclusions"], tables["alias_candidates"]
    check("source_trials_nonempty", "PASS" if len(trials) else "FAIL", len(trials), "An empty download is not a usable data run.")
    check("strict_bridge_nonempty", "PASS" if len(bridge) else "FAIL", len(bridge), "A run with no eligible program links cannot support the planned analysis.")

    key_columns = {
        "trials": ["nct_id"], "interventions": ["nct_id", "intervention_index"],
        "conditions": ["nct_id", "condition_index"],
        "program_trials": ["nct_id", "program_id", "regimen_id", "indication_id", "drug_group", "arm_label", "component_keys_json", "mapping_basis"],
        "programs": ["program_id", "regimen_id", "indication_id", "drug_group", "component_keys_json"],
        "exclusions": ["nct_id", "scope", "reason"],
        "alias_candidates": ["nct_id", "intervention_index", "primary_key", "alias_key", "review_status"],
    }
    for name, columns in key_columns.items():
        frame = tables[name]
        null_rows = pd.Series(False, index=frame.index)
        for column in columns:
            null_rows |= _blank(frame[column])
        count = int(null_rows.sum())
        check(f"nonmissing_keys_{name}", "FAIL" if count else "PASS", count, "Required identifiers and structural keys cannot be null or blank.")

    uniqueness = {
        "trials": ["nct_id"], "interventions": ["nct_id", "intervention_index"],
        "conditions": ["nct_id", "condition_index"], "programs": ["program_id"],
        "program_trials": ["nct_id", "program_id", "arm_label"],
    }
    for name, columns in uniqueness.items():
        count = int(tables[name].duplicated(columns).sum())
        check(f"unique_keys_{name}", "FAIL" if count else "PASS", count, f"Unique row key: {', '.join(columns)}.")
    bad_ncts = int((~trials["nct_id"].astype("string").str.fullmatch(r"NCT\d{8}").fillna(False)).sum())
    check("valid_nct_ids", "FAIL" if bad_ncts else "PASS", bad_ncts, "Trial identifiers must follow the registry NCT######## format.")
    input_ids = _nonblank_set(trials["nct_id"])
    for name in ["interventions", "conditions", "program_trials", "exclusions", "alias_candidates"]:
        foreign = sorted(_nonblank_set(tables[name]["nct_id"]) - input_ids, key=str)
        check(f"nct_foreign_keys_{name}", "FAIL" if foreign else "PASS", {"count": len(foreign), "examples": foreign[:10]}, "Every child NCT must occur in the complete trial table.")
    linked = _nonblank_set(bridge["nct_id"])
    excluded = _nonblank_set(exclusions["nct_id"])
    missing_account = sorted(input_ids - linked - excluded, key=str)
    check("all_downloaded_trials_accounted_for", "FAIL" if missing_account else "PASS", {"count": len(missing_account), "examples": missing_account[:10]}, "Each input trial must have a strict link, an explicit exclusion, or both for partial arm exclusions.")
    program_ids = _nonblank_set(programs["program_id"])
    linked_programs = _nonblank_set(bridge["program_id"])
    missing_programs = sorted(linked_programs - program_ids, key=str)
    orphan_programs = sorted(program_ids - linked_programs, key=str)
    check("program_foreign_keys", "FAIL" if missing_programs else "PASS", {"count": len(missing_programs), "examples": missing_programs[:10]}, "Every bridge program must have a program summary row.")
    check("programs_have_trial_links", "FAIL" if orphan_programs else "PASS", {"count": len(orphan_programs), "examples": orphan_programs[:10]}, "Program summary rows must not be orphaned.")

    identities = pd.concat([bridge[["program_id", "regimen_id", "indication_id", "component_keys_json", "drug_group"]], programs[["program_id", "regimen_id", "indication_id", "component_keys_json", "drug_group"]]], ignore_index=True)
    pairs = identities[["program_id", "regimen_id", "indication_id"]].drop_duplicates()
    collisions = int(pairs.groupby("program_id", dropna=False).size().gt(1).sum())
    check("program_id_single_identity", "FAIL" if collisions else "PASS", collisions, "One program ID must map to exactly one regimen and exact indication across both tables.")
    regimen_collisions = int(identities[["regimen_id", "component_keys_json"]].drop_duplicates().groupby("regimen_id", dropna=False).size().gt(1).sum())
    check("regimen_id_single_components", "FAIL" if regimen_collisions else "PASS", regimen_collisions, "One regimen ID cannot denote different component lists.")
    group_collisions = int(identities[["program_id", "drug_group"]].drop_duplicates().groupby("program_id", dropna=False).size().gt(1).sum())
    check("program_id_single_split_group", "FAIL" if group_collisions else "PASS", group_collisions, "Each candidate program has one consistent splitting group.")

    parsed_components = {value: _components(value) for value in identities["component_keys_json"].dropna().unique() if isinstance(value, str)}
    bad_components = identities["component_keys_json"].map(lambda value: not isinstance(value, str) or parsed_components.get(value) is None)
    check("canonical_active_component_lists", "FAIL" if bad_components.any() else "PASS", int(bad_components.sum()), "Components must be nonempty, sorted, unique canonical labels without unresolved controls or compound strings.")
    component_groups: dict[str, set[str]] = {}
    for value, group in identities[["component_keys_json", "drug_group"]].drop_duplicates().itertuples(index=False, name=None):
        for component in parsed_components.get(value, []) or []:
            component_groups.setdefault(component, set()).add(group)
    divided = sorted(component for component, groups in component_groups.items() if len(groups) > 1)
    check("shared_components_stay_grouped", "FAIL" if divided else "PASS", {"count": len(divided), "examples": divided[:10]}, "Overlapping exact-name drug regimens must share a splitting group.")
    expected_counts = bridge.groupby("program_id")["nct_id"].nunique()
    expected_arms = bridge.groupby("program_id").size()
    count_mismatch = programs["program_id"].map(expected_counts).ne(pd.to_numeric(programs["n_trials"], errors="coerce"))
    arm_mismatch = programs["program_id"].map(expected_arms).ne(pd.to_numeric(programs["n_arms"], errors="coerce"))
    check("program_trial_counts_match", "FAIL" if count_mismatch.any() else "PASS", int(count_mismatch.sum()), "n_trials counts distinct NCT IDs, not arms or exploded mappings.")
    check("program_arm_counts_match", "FAIL" if arm_mismatch.any() else "PASS", int(arm_mismatch.sum()), "n_arms counts the retained trial/program/arm bridge rows.")

    unknown = trials["phase"].notna() & ~trials["phase"].isin(CANONICAL_PHASES)
    missing_phases = int(trials["phase"].isna().sum())
    check("canonical_phase_values", "FAIL" if unknown.any() else "PASS", int(unknown.sum()), "Nonmissing normalized phase labels must use the documented vocabulary.")
    check("missing_source_phases_reported", "WARN" if missing_phases else "PASS", missing_phases, "Missing or unsupported original phases remain visible and must be excluded from strict program linkage.")
    linked_trials = trials.loc[trials["nct_id"].isin(linked)]
    bad_linked_phases = int((~linked_trials["phase"].isin(STRICT_PHASES)).sum())
    check("linked_trials_have_supported_phase", "FAIL" if bad_linked_phases else "PASS", bad_linked_phases, "Strict linked trials require an eligible development phase.")
    bad_type = int(linked_trials["study_type"].ne("INTERVENTIONAL").sum())
    check("linked_trials_interventional", "FAIL" if bad_type else "PASS", bad_type, "Observational records cannot enter the strict bridge.")
    multiple = int(pd.to_numeric(linked_trials["condition_count"], errors="coerce").ne(1).sum())
    check("linked_trials_single_condition", "FAIL" if multiple else "PASS", multiple, "Unreviewed multi-condition cross products are excluded.")

    dates = {}
    for field in DATE_FIELDS:
        actual = trials[field].map(lambda value: _observed_precision(None if pd.isna(value) else str(value)))
        mismatch = int(actual.ne(trials[f"{field}_precision"]).sum())
        dates[field] = {precision: int(actual.eq(precision).sum()) for precision in ["day", "month", "year", "missing", "invalid"]}
        check(f"date_precision_preserved_{field}", "FAIL" if mismatch else "PASS", mismatch, "Stored precision must agree with the un-imputed source date string.")
        check(f"invalid_source_dates_{field}", "WARN" if dates[field]["invalid"] else "PASS", dates[field]["invalid"], "Invalid source dates are counted, not silently repaired or turned into exact dates.")
    summary["date_precision_counts"] = dates

    actual_records = len(trials)
    record_count = manifest.get("records")
    total_count = manifest.get("total_count")
    count_is_int = lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if record_count is None:
        check("manifest_record_count", "WARN", None, "No download record count was supplied for reconciliation.")
    else:
        match = count_is_int(record_count) and record_count == actual_records
        check("manifest_record_count", "PASS" if match else "FAIL", {"manifest": record_count, "organized": actual_records}, "Downloaded records and source trial rows must agree exactly.")
    if manifest.get("complete") is True:
        check("source_complete", "PASS", True, "The downloader reports pagination exhausted; this does not establish historical completeness of the registry.")
        if total_count is None:
            check("manifest_total_count", "WARN", None, "API totalCount is absent; pagination completeness cannot be cross-checked against it.")
        else:
            match = count_is_int(total_count) and total_count == actual_records
            check("manifest_total_count", "PASS" if match else "FAIL", {"api_total": total_count, "organized": actual_records}, "A complete download must reconcile to its reported API total.")
    else:
        check("source_complete", "WARN", manifest.get("complete"), "This is a partial or unverified acquisition; report sample findings, not full-cohort conclusions.")
        if total_count is not None:
            valid = count_is_int(total_count) and total_count >= actual_records
            check("manifest_total_count", "PASS" if valid else "FAIL", {"api_total": total_count, "organized": actual_records}, "A partial download cannot contain more rows than its reported source total.")

    phase_links = bridge[["program_id", "nct_id"]].drop_duplicates().merge(trials[["nct_id", "phase"]], on="nct_id", how="left")
    distinct_phases = phase_links.groupby("program_id")["phase"].nunique()
    pure_phase1 = set(phase_links.loc[phase_links["phase"].eq("PHASE1"), "program_id"])
    pure_phase3 = set(phase_links.loc[phase_links["phase"].eq("PHASE3"), "program_id"])
    summary.update({
        "input_trials": actual_records, "linked_trials": len(linked),
        "unlinked_trials": len(input_ids - linked), "trials_with_any_exclusion": len(excluded),
        "partially_linked_trials_with_exclusions": len(linked & excluded),
        "linkage_fraction_of_all_downloaded_trials": len(linked & input_ids) / len(input_ids) if input_ids else 0.0,
        "candidate_programs": len(programs),
        "programs_with_multiple_trials": int(expected_counts.gt(1).sum()),
        "programs_with_multiple_phase_labels": int(distinct_phases.gt(1).sum()),
        "programs_with_pure_phase1_and_phase3_records": len(pure_phase1 & pure_phase3),
        "phase_distribution": trials["phase"].fillna("MISSING").value_counts().to_dict(),
        "exclusion_reason_counts": exclusions.groupby("reason")["nct_id"].nunique().to_dict(),
        "trial_missingness": {field: {"count": int(_blank(trials[field]).sum()), "fraction": float(_blank(trials[field]).mean()) if len(trials) else None} for field in ["phase", "status", "enrollment", "sponsor_class", "sponsor_name", "allocation", "masking", *DATE_FIELDS]},
        "unreviewed_alias_candidates": len(aliases),
    })
    conflicts = int(aliases["conflicting_primary_keys"].fillna(False).astype(bool).sum())
    check("alias_candidates_not_applied", "WARN" if len(aliases) else "INFO", {"candidates": len(aliases), "conflicting_candidate_rows": conflicts}, "Alias suggestions are not validated merges; exact-label identities can fragment a true drug program.")
    check("clinical_identity_validation", "WARN", False, "Structural tests do not verify molecule equivalence, disease granularity, dose/formulation equivalence, or true development-program continuity. Manual review is required.")
    check("historical_feature_availability", "WARN", False, "Current registry fields are not historical as-of snapshots. These tables alone do not establish leakage-free predictive features.")
    return finish()


def review_sample(tables: dict[str, pd.DataFrame], n: int = 50, seed: int = 545) -> pd.DataFrame:
    """Stable review queue, prioritizing a mix of multi-phase and other programs.

    Hash-ranked stratified selection is reproducible under source-row reordering.
    The queue is a review template, never fabricated human adjudication.
    """
    if n < 0:
        raise ValueError("n must be nonnegative")
    programs = tables["programs"]
    if not n or programs.empty:
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    links = tables["program_trials"][["program_id", "nct_id"]].drop_duplicates().merge(tables["trials"][["nct_id", "phase"]], on="nct_id", how="left")
    lookup = {}
    for program, group in links.groupby("program_id", sort=True):
        phases = sorted(set(group["phase"].dropna()))
        ncts = sorted(set(group["nct_id"].dropna()))
        lookup[program] = {
            "phase_labels": "; ".join(phases),
            "review_stratum": "multiple_phase_labels" if len(phases) > 1 else "single_phase_label",
            "nct_ids_json": json.dumps(ncts),
            "source_urls_json": json.dumps([f"https://clinicaltrials.gov/study/{nct}" for nct in ncts]),
        }
    candidates = []
    for _, row in programs.iterrows():
        program = row["program_id"]
        if program not in lookup:
            continue
        candidates.append({
            **{field: row[field] for field in ["program_id", "regimen_id", "indication_id", "component_keys_json", "n_trials"]},
            **lookup[program], "identity_review": "NOT_REVIEWED", "regimen_review": "NOT_REVIEWED",
            "indication_review": "NOT_REVIEWED", "notes": "",
            "_rank": hashlib.sha256(f"{seed}:{program}".encode()).hexdigest(),
        })
    ranked = sorted(candidates, key=lambda row: (row["_rank"], row["program_id"]))
    quota = (min(n, len(ranked)) + 1) // 2
    selected = [row for row in ranked if row["review_stratum"] == "multiple_phase_labels"][:quota]
    selected += [row for row in ranked if row["review_stratum"] == "single_phase_label"][: min(n, len(ranked)) - quota]
    selected_ids = {row["program_id"] for row in selected}
    selected += [row for row in ranked if row["program_id"] not in selected_ids][: max(0, n - len(selected))]
    return pd.DataFrame.from_records(selected, columns=REVIEW_COLUMNS)
