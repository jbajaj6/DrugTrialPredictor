"""B19 development-only structural evidence audit; never grades efficacy."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[2]
PINNED = ROOT / "data/processed/anamnesis_grade_b17_full_v3_2026-11-25"
PINNED_MANIFEST = "778d4a5f97d4afa868747d8d44269ff3bde203faeb08b5b0442d84d872a0cdd2"
CUTOFF = pd.Timestamp("2024-01-01")
SEED = 20261127
TRIAL = ["nct_id", "nct_version"]
OUTCOME = TRIAL + ["outcome_ord"]
ANALYSIS = OUTCOME + ["analysis_ord"]
GROUP = OUTCOME + ["group_id"]
FILES = {
    "measures": "results_outcome_measures_clean.parquet",
    "groups": "results_outcome_groups_clean.parquet",
    "measurements": "results_outcome_measurements_clean.parquet",
    "analyses": "results_outcome_analyses_clean.parquet",
    "analysis_groups": "results_outcome_analysis_groups_clean.parquet",
    "arms": "arms_at_result_version.parquet",
}
KEYS = {"measures": OUTCOME, "groups": GROUP, "analyses": ANALYSIS,
        "analysis_groups": ANALYSIS + ["group_id"], "arms": TRIAL + ["ord"],
        "measurements": OUTCOME + ["class_ord", "category_ord", "measurement_ord", "group_id"]}
SAMPLE_AXES = ["b17_reason_code", "p_presence", "parameter_families", "unit_families", "era", "mapping_states", "contrast_states"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return _jsonable(value.item())
    return value


def parse_p(value) -> dict:
    """Parse a reported probability/bound without threshold or direction inference."""
    if value is None or pd.isna(value) or not str(value).strip():
        return {"status": "missing", "qualifier": None, "value": None}
    match = re.fullmatch(r"\s*(<=|>=|<|>|=)?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*", str(value))
    if not match:
        return {"status": "malformed", "qualifier": None, "value": None}
    qualifier, number = match.group(1) or "=", float(match.group(2))
    valid = math.isfinite(number) and 0 <= number <= 1 and not (qualifier == "<" and number == 0) and not (qualifier == ">" and number == 1)
    return {"status": "parsed" if valid else "out_of_bounds", "qualifier": qualifier, "value": number if math.isfinite(number) else None}


def analysis_type_evidence(tested_flag, raw_type) -> dict:
    """Keep legacy flag and exact enum distinct; never infer a clinical null."""
    flag = "missing" if tested_flag is None or pd.isna(tested_flag) else "true" if tested_flag is True or tested_flag == True else "false" if tested_flag is False or tested_flag == False else "invalid"
    normalized = _norm(raw_type).upper()
    categories = {"NON_INFERIORITY": "noninferiority", "EQUIVALENCE": "equivalence",
        "NON_INFERIORITY_OR_EQUIVALENCE": "noninferiority_or_equivalence", "NON_INFERIORITY_OR_EQUIVALENCE_LEGACY": "noninferiority_or_equivalence",
        "SUPERIORITY": "superiority", "SUPERIORITY_OR_OTHER": "superiority_or_other",
        "SUPERIORITY_OR_OTHER_LEGACY": "superiority_or_other", "OTHER": "other"}
    category = categories.get(normalized, "missing" if not normalized else "unknown_enum")
    if flag == "missing":
        consistency = "unknown_missing_flag"
    elif flag == "invalid":
        consistency = "unknown_invalid_flag"
    elif category in {"missing", "unknown_enum"}:
        consistency = "unknown_enum"
    elif flag == "true" and category == "superiority":
        consistency = "conflict_true_flag_superiority_enum"
    elif flag == "false" and category == "noninferiority":
        consistency = "conflict_false_flag_noninferiority_enum"
    elif flag == "true" and category in {"equivalence", "superiority_or_other", "other"}:
        consistency = "review_true_flag_" + category + "_enum"
    elif flag == "false" and category == "noninferiority_or_equivalence":
        consistency = "review_false_flag_combined_enum"
    else:
        consistency = "no_direct_conflict_observed"
    return {"tested_non_inferiority_raw": tested_flag, "tested_flag_state": flag,
        "non_inferiority_type_raw": raw_type, "enum_state": category, "field_consistency": consistency}


def verify_provenance(source: Path) -> dict:
    """Only pinned B17 output values are used. Upstream manifests are metadata."""
    if source.resolve() != PINNED.resolve():
        raise ValueError("Only the preregistered pinned B17 directory is permitted")
    manifest_path = source / "manifest.json"
    if digest(manifest_path) != PINNED_MANIFEST:
        raise ValueError("Pinned B17 manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text())
    checks = {}
    expected_names = set(FILES.values()) | {"graded_trials.parquet", "results_adverse_serious_event_stats_clean.parquet"}
    if set(manifest["output_sha256"]) != expected_names:
        raise ValueError("Unexpected B17 output inventory")
    for name, expected in manifest["output_sha256"].items():
        actual = digest(source / name)
        if actual != expected:
            raise ValueError(f"B17 output hash mismatch: {name}")
        checks[name] = actual
    if digest(source / "report.json") != manifest["report_sha256"]:
        raise ValueError("B17 report hash mismatch")
    upstream = {}
    for filename, expected in manifest["input_sha256"].items():
        path = Path(filename)
        parent_manifest = path.parent / "manifest.json"
        metadata = json.loads(parent_manifest.read_text())
        declared = metadata.get("output_sha256", metadata.get("output_files_sha256", {})).get(path.name)
        if declared != expected:
            raise ValueError(f"Upstream manifest declaration mismatch: {path.name}")
        upstream[str(parent_manifest)] = {"sha256": digest(parent_manifest), "source_commit": metadata.get("source_commit")}
    report = json.loads((source / "report.json").read_text())
    if report.get("selected_result_versions") != 8414:
        raise ValueError("B17 report universe mismatch")
    return {"b17_manifest_sha256": PINNED_MANIFEST, "b17_output_sha256": checks,
            "b17_report_sha256": manifest["report_sha256"], "upstream_manifest_provenance": upstream,
            "upstream_verification": "B17 input hash declarations matched upstream manifests; upstream value files not reopened"}


def guard_dates(source: Path, expected_count: int = 8414) -> tuple[pd.DataFrame, dict]:
    """Project keys and public dates for ALL pinned tables before reading values."""
    selected = pd.read_parquet(source / "graded_trials.parquet", columns=TRIAL + ["result_date"])
    if len(selected) != expected_count or selected[TRIAL].isna().any().any() or selected.duplicated(TRIAL).any() or selected.nct_id.duplicated().any():
        raise ValueError("Selected exact-version universe is missing, duplicated, or wrong size")
    selected["result_date"] = pd.to_datetime(selected.result_date, errors="coerce")
    if selected.result_date.isna().any() or selected.result_date.ge(CUTOFF).any():
        raise ValueError("Selected public dates are missing/invalid or include 2024+")
    by_key = {tuple(row[:2]): row[2] for row in selected.itertuples(index=False, name=None)}
    summary = {}
    for name in list(FILES.values()) + ["results_adverse_serious_event_stats_clean.parquet"]:
        path = source / name
        if "adapter_version_public_date" not in pq.read_schema(path).names:
            raise ValueError(f"Missing public availability date: {name}")
        frame = pd.read_parquet(path, columns=TRIAL + ["adapter_version_public_date"])
        dates = pd.to_datetime(frame.adapter_version_public_date, errors="coerce")
        if dates.isna().any() or dates.ge(CUTOFF).any():
            raise ValueError(f"Missing/invalid or 2024+ public date: {name}")
        expected = pd.Series([by_key.get(tuple(k), pd.NaT) for k in frame[TRIAL].itertuples(index=False, name=None)], index=frame.index)
        if expected.isna().any() or not dates.eq(expected).all():
            raise ValueError(f"Child public date/key differs from selected exact version: {name}")
        summary[name] = {"rows_checked": len(frame), "min_public_date": str(dates.min()), "max_public_date": str(dates.max())}
    return selected, summary


def _keys(frame: pd.DataFrame, columns: list[str]) -> set:
    return set(frame.dropna(subset=columns)[columns].itertuples(index=False, name=None))


def _subset(frame: pd.DataFrame, columns: list[str], keys: set) -> pd.DataFrame:
    return frame.loc[[tuple(k) in keys for k in frame[columns].itertuples(index=False, name=None)]]


def _live(frame: pd.DataFrame) -> pd.DataFrame:
    keep = pd.Series(True, index=frame.index)
    for c in ("is_obsolete", "adapter_core_is_obsolete"):
        if c in frame:
            keep &= ~frame[c].fillna(False).astype(bool)
    return frame.loc[keep]


def _norm(value) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip().casefold()


def _family(value, unit=False) -> str:
    value = _norm(value)
    if not value:
        return "missing"
    if not unit:
        return value
    families = {"percent": {"percent", "%", "percentage"}, "time": {"days", "weeks", "months", "years", "hours", "minutes", "seconds"},
                "count": {"participants", "subjects", "patients", "events", "number", "count"}, "score": {"score", "scores", "points"}}
    return next((k for k, values in families.items() if value in values), "other_structured_unit")


def key_quality(selected: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> dict:
    trial_keys = _keys(selected, TRIAL)
    parents = {"groups": ("measures", OUTCOME), "measurements": ("groups", GROUP),
               "analyses": ("measures", OUTCOME), "analysis_groups": ("analyses", ANALYSIS)}
    result = {}
    for name, frame in frames.items():
        key = KEYS[name]
        if any(c not in frame for c in key):
            raise ValueError(f"Missing required exact key columns: {name}")
        duplicate = frame.duplicated(key, keep=False)
        orphan_trial = ~frame[TRIAL].apply(tuple, axis=1).isin(trial_keys)
        item = {"rows": len(frame), "missing_key_rows": int(frame[key].isna().any(axis=1).sum()),
                "duplicate_key_rows": int(duplicate.sum()), "duplicate_keys": len(_keys(frame.loc[duplicate], key)),
                "orphan_trial_rows": int(orphan_trial.sum())}
        if name in parents:
            parent, join_key = parents[name]
            parent_keys = _keys(frames[parent], join_key)
            item["orphan_parent_rows"] = sum(tuple(k) not in parent_keys for k in frame[join_key].itertuples(index=False, name=None))
        if name == "analysis_groups":
            groups = _keys(frames["groups"], GROUP)
            item["orphan_result_group_rows"] = sum(tuple(k) not in groups for k in frame[GROUP].itertuples(index=False, name=None))
        result[name] = item
    return result


def _mapping(groups: pd.DataFrame, arms: pd.DataFrame) -> tuple[str, str, dict]:
    if groups.empty or arms.empty:
        return "missing_groups_or_arms", "unknown", {}
    if groups[GROUP].isna().any().any() or arms[KEYS["arms"]].isna().any().any() or groups.duplicated("group_id").any() or arms.duplicated("ord").any():
        return "ambiguous_keys", "unknown", {}
    group_labels = groups.title.map(_norm)
    arm_labels = arms.arm_label.map(_norm)
    if group_labels.eq("").any() or arm_labels.eq("").any() or group_labels.duplicated().any() or arm_labels.duplicated().any() or set(group_labels) != set(arm_labels):
        return "labels_not_unique_bijection", "unknown", {}
    roles = dict(zip(arm_labels, arms.arm_type))
    mapped = dict(zip(groups.group_id, [roles[x] for x in group_labels]))
    values = sorted(_norm(v).upper() for v in mapped.values())
    comparator = "explicit_two_group_roles" if values in (["EXPERIMENTAL", "PLACEBO_COMPARATOR"], ["ACTIVE_COMPARATOR", "EXPERIMENTAL"]) else "mixed_or_unsupported_roles"
    return "exact_label_candidate_bijection", comparator, mapped


def audit_frames(selected: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Pure synthetic-testable audit. Raw rows are never joined multiplicatively."""
    if selected.duplicated(TRIAL).any() or selected[TRIAL].isna().any().any() or selected.nct_id.duplicated().any():
        raise ValueError("Duplicate/missing target trial key")
    dates = pd.to_datetime(selected.result_date, errors="coerce")
    if dates.isna().any() or dates.ge(CUTOFF).any():
        raise ValueError("Missing/invalid or 2024+ selected dates")
    frames = {k: _live(v) for k, v in frames.items()}
    quality = key_quality(selected, frames)
    grouped = {name: {key: block for key, block in frame.groupby(TRIAL, dropna=False)} for name, frame in frames.items()}
    records, trials = [], []
    for trial in selected.sort_values(TRIAL).to_dict("records"):
        key = tuple(trial[c] for c in TRIAL)
        local = {name: grouped[name].get(key, frame.iloc[:0]) for name, frame in frames.items()}
        primary = local["measures"].loc[local["measures"].type.map(_norm).eq("primary")]
        ords = sorted(primary.outcome_ord.dropna().unique())
        endpoint_records = []
        for outcome in ords:
            parts = {name: frame.loc[frame.outcome_ord.eq(outcome)] for name, frame in local.items() if "outcome_ord" in frame}
            measure = primary.loc[primary.outcome_ord.eq(outcome)]
            row = measure.iloc[0] if len(measure) == 1 else pd.Series(dtype=object)
            groups, analyses, links, values = (parts[n] for n in ("groups", "analyses", "analysis_groups", "measurements"))
            mapping, roles, mapped = _mapping(groups, local["arms"])
            valid_group_keys = _keys(groups.loc[~groups.duplicated(GROUP, keep=False)], GROUP)
            valid_values = values.loc[~values.duplicated(KEYS["measurements"], keep=False) & ~values[KEYS["measurements"]].isna().any(axis=1)]
            valid_values = _subset(valid_values, GROUP, valid_group_keys)
            numeric = pd.to_numeric(valid_values.value, errors="coerce")
            numeric = numeric.where(numeric.map(lambda x: pd.notna(x) and math.isfinite(x)))
            p = [parse_p(x) for x in analyses.p_value]
            contrast_states, analysis_evidence = [], []
            for analysis in analyses.to_dict("records"):
                linked = links.loc[links.analysis_ord.eq(analysis["analysis_ord"])]
                ids = linked.group_id.dropna().tolist()
                if pd.isna(analysis["analysis_ord"]) or analyses.analysis_ord.eq(analysis["analysis_ord"]).sum() != 1:
                    state = "ambiguous_analysis_key"
                elif linked.empty:
                    state = "missing_analysis_group_keys"
                elif linked.group_id.isna().any() or linked.duplicated(KEYS["analysis_groups"]).any():
                    state = "ambiguous_analysis_group_keys"
                elif len(ids) != 2 or len(set(ids)) != 2:
                    state = "not_explicit_two_group_contrast"
                elif not set(ids).issubset(set(groups.group_id.dropna())) or groups.duplicated(GROUP).any():
                    state = "unresolved_result_group_keys"
                elif mapping != "exact_label_candidate_bijection" or roles != "explicit_two_group_roles" or set(ids) != set(mapped):
                    state = "contrast_roles_unknown"
                else:
                    state = "explicit_two_group_role_contrast"
                contrast_states.append(state)
                analysis_evidence.append({"analysis_ord": analysis["analysis_ord"], "p_value_raw": analysis.get("p_value"),
                    "p_parse": parse_p(analysis.get("p_value")), "group_ids": ids, "contrast_state": state,
                    "analysis_type": analysis_type_evidence(analysis.get("tested_non_inferiority"), analysis.get("non_inferiority_type"))})
            types = [x["analysis_type"] for x in analysis_evidence]
            enum_states = sorted({x["enum_state"] for x in types}) or ["no_analysis"]
            flag_states = sorted({x["tested_flag_state"] for x in types}) or ["no_analysis"]
            consistency_states = sorted({x["field_consistency"] for x in types}) or ["no_analysis"]
            ni_state = "explicit_noninferiority_enum" if "noninferiority" in enum_states else "combined_enum_ambiguous" if "noninferiority_or_equivalence" in enum_states else "true_flag_without_noninferiority_enum" if "true" in flag_states else "unknown_no_noninferiority_claim" if types else "no_analysis"
            eq_state = "explicit_equivalence_enum" if "equivalence" in enum_states else "combined_enum_ambiguous" if "noninferiority_or_equivalence" in enum_states else "unknown_no_equivalence_claim" if types else "no_analysis"
            evidence = {**{c: trial[c] for c in TRIAL}, "outcome_ord": outcome, "result_date": trial["result_date"],
                "b17_reason_code": trial.get("reason_code", "unknown"), "primary_outcome_count": len(ords), "primary_source_row_count": len(primary),
                "missing_primary_key_rows": int(primary.outcome_ord.isna().sum()), "endpoint_key_state": "unique" if len(measure) == 1 else "duplicate_ambiguous",
                "param_type": row.get("param_type"), "unit_of_measure": row.get("unit_of_measure"),
                "parameter_family": _family(row.get("param_type")), "unit_family": _family(row.get("unit_of_measure"), True),
                "result_group_count": groups.group_id.nunique(), "measurement_row_count": len(values), "valid_measurement_row_count": len(valid_values),
                "numeric_result_group_count": valid_values.loc[numeric.notna(), "group_id"].nunique(), "nonnumeric_or_missing_measurement_rows": int(numeric.isna().sum()),
                "measurement_groups_with_multiple_rows": int((valid_values.groupby("group_id").size() > 1).sum()),
                "analysis_count": len(analyses), "p_present": any(x["status"] != "missing" for x in p),
                "p_parse_states": sorted(set(x["status"] for x in p)) or ["no_analysis"],
                "p_parsed_count": sum(x["status"] == "parsed" for x in p),
                "analysis_evidence": analysis_evidence,
                "analysis_contrast_states": sorted(set(contrast_states)) or ["no_analysis"],
                "arm_mapping_state": mapping, "comparator_role_state": roles,
                "tested_non_inferiority_states": flag_states, "analysis_type_enum_states": enum_states,
                "analysis_type_consistency_states": consistency_states, "noninferiority_state": ni_state,
                "equivalence_state": eq_state, "direction_state": "unknown_not_assessed",
                "multiplicity_state": "multiple_primary_outcomes" if len(ords) > 1 else "multiple_analyses" if len(analyses) > 1 else "adjustment_not_verified"}
            records.append(evidence)
            endpoint_records.append(evidence)
        union = lambda c, default="missing": "|".join(sorted({str(r[c]) for r in endpoint_records})) or default
        flatten = lambda c: "|".join(sorted({x for r in endpoint_records for x in r[c]})) or "no_primary"
        date = pd.Timestamp(trial["result_date"])
        trials.append({**{c: trial[c] for c in TRIAL}, "result_date": date,
            "b17_reason_code": trial.get("reason_code", "unknown"), "primary_outcome_count": len(ords), "primary_source_row_count": len(primary),
            "missing_primary_key_rows": int(primary.outcome_ord.isna().sum()), "primary_count_state": "missing" if primary.empty else "missing_keys" if primary.outcome_ord.isna().any() else "multiple" if len(ords) > 1 else "single",
            "p_presence": "present" if any(r["p_present"] for r in endpoint_records) else "absent_or_unknown",
            "parameter_families": union("parameter_family"), "unit_families": union("unit_family"),
            "era": "2008-2011" if date.year <= 2011 else "2012-2015" if date.year <= 2015 else "2016-2019" if date.year <= 2019 else "2020-2023",
            "mapping_states": union("arm_mapping_state"), "contrast_states": flatten("analysis_contrast_states"),
            "comparator_role_states": union("comparator_role_state"), "noninferiority_states": union("noninferiority_state"),
            "equivalence_states": union("equivalence_state"), "tested_non_inferiority_states": flatten("tested_non_inferiority_states"),
            "analysis_type_enum_states": flatten("analysis_type_enum_states"), "analysis_type_consistency_states": flatten("analysis_type_consistency_states"),
            "p_parse_states": flatten("p_parse_states"), "analysis_count": sum(r["analysis_count"] for r in endpoint_records),
            "numeric_result_group_count_sum_across_endpoints": sum(r["numeric_result_group_count"] for r in endpoint_records),
            "direction_state": "unknown_not_assessed",
            "numeric_primary_present": any(r["numeric_result_group_count"] >= 2 for r in endpoint_records),
            "parsed_p_present": any(r["p_parsed_count"] > 0 for r in endpoint_records)})
    primary_columns = list(records[0]) if records else TRIAL + ["outcome_ord", "result_date", "endpoint_key_state", "param_type", "unit_of_measure", "numeric_result_group_count", "p_parsed_count", "analysis_contrast_states", "arm_mapping_state", "comparator_role_state", "noninferiority_state", "equivalence_state", "parameter_family", "unit_family", "multiplicity_state", "p_parse_states", "analysis_evidence", "tested_non_inferiority_states", "analysis_type_enum_states", "analysis_type_consistency_states"]
    trial_columns = list(trials[0]) if trials else TRIAL + ["result_date", "primary_outcome_count", "numeric_primary_present", "p_presence", "parsed_p_present", "primary_count_state"] + SAMPLE_AXES
    return pd.DataFrame(records, columns=primary_columns), pd.DataFrame(trials, columns=list(dict.fromkeys(trial_columns))), quality


def sample_trials(trials: pd.DataFrame, size=120, seed=SEED) -> pd.DataFrame:
    """Reason/p/era coverage, rare marginals, then seeded stratum round-robin."""
    if size < 0:
        raise ValueError("sample size must be nonnegative")
    if trials.empty:
        return trials.assign(sampling_stratum=pd.Series(dtype=str))
    work = trials.copy().reset_index(drop=True)
    composite = work[SAMPLE_AXES].astype(str).agg(";".join, axis=1)
    work["sampling_stratum"] = composite.map(lambda s: "b19_" + hashlib.sha256(s.encode()).hexdigest()[:16])
    rank = {i: hashlib.sha256(f"{seed}|{row.nct_id}|{row.nct_version}".encode()).hexdigest() for i, row in work.iterrows()}
    chosen = []
    n = min(size, len(work))
    priority = [(c, str(v)) for c in ("b17_reason_code", "p_presence", "era") for v in sorted(work[c].unique())]
    rare = [(c, str(v)) for _, c, v in sorted((int(work[c].eq(v).sum()), c, str(v)) for c in SAMPLE_AXES for v in work[c].unique())]
    for column, value in priority + rare:
        if len(chosen) >= n:
            break
        candidates = work.index[work[column].astype(str).eq(value)].tolist()
        if not set(candidates).intersection(chosen):
            chosen.append(min(candidates, key=rank.get))
    strata = {k: sorted(block.index, key=rank.get) for k, block in work.groupby("sampling_stratum")}
    while len(chosen) < n:
        for stratum in sorted(strata, key=lambda s: hashlib.sha256(f"{seed}|{s}".encode()).hexdigest()):
            remaining = [i for i in strata[stratum] if i not in chosen]
            if remaining:
                chosen.append(remaining[0])
            if len(chosen) == n:
                break
    return work.loc[chosen].sort_values(TRIAL).reset_index(drop=True)


def sample_records(sample: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> list[dict]:
    """Raw exact-key children; unresolved children retained separately for review."""
    grouped = {name: {key: block for key, block in frame.groupby(TRIAL, dropna=False)} for name, frame in frames.items()}
    result = []
    for trial in sample.to_dict("records"):
        key = tuple(trial[c] for c in TRIAL)
        local = {name: grouped[name].get(key, frame.iloc[:0]) for name, frame in frames.items()}
        primary = local["measures"].loc[local["measures"].type.map(_norm).eq("primary")]
        outcome_keys = _keys(primary, OUTCOME)
        children = {"measures": primary, "arms": local["arms"]}
        for name in ("groups", "analyses"):
            children[name] = _subset(local[name], OUTCOME, outcome_keys)
        children["measurements"] = _subset(local["measurements"], GROUP, _keys(children["groups"], GROUP))
        links = _subset(local["analysis_groups"], ANALYSIS, _keys(children["analyses"], ANALYSIS))
        children["analysis_groups"] = _subset(links, GROUP, _keys(children["groups"], GROUP))
        unlinked = {}
        for name in ("groups", "measurements", "analyses", "analysis_groups"):
            primary_scoped = _subset(local[name], OUTCOME, outcome_keys)
            unlinked[name] = primary_scoped.loc[~primary_scoped.index.isin(children[name].index)].to_dict("records")
        result.append(_jsonable({"trial": trial, "children": {name: frame.to_dict("records") for name, frame in children.items()}, "unlinked_primary_children": unlinked}))
    return result


def _counts(frame: pd.DataFrame, column: str) -> dict:
    return {str(k): int(v) for k, v in frame[column].value_counts(dropna=False).items()} if column in frame else {}


def coverage_report(primary: pd.DataFrame, trials: pd.DataFrame, sample: pd.DataFrame) -> dict:
    trial_masks = {"selected_trials": pd.Series(True, index=trials.index),
        "has_primary_key": trials.primary_outcome_count.gt(0), "single_primary_key": trials.primary_outcome_count.eq(1),
        "two_numeric_primary_groups": trials.numeric_primary_present, "p_present": trials.p_presence.eq("present"), "parsed_p_present": trials.parsed_p_present}
    primary_masks = {"primary_outcomes": pd.Series(True, index=primary.index), "unique_endpoint_key": primary.endpoint_key_state.eq("unique"),
        "parameter_and_unit_present": primary.param_type.map(_norm).ne("") & primary.unit_of_measure.map(_norm).ne(""),
        "two_numeric_groups": primary.numeric_result_group_count.ge(2), "p_parsed": primary.p_parsed_count.gt(0),
        "explicit_role_contrast": primary.analysis_contrast_states.map(lambda v: "explicit_two_group_role_contrast" in v),
        "candidate_arm_bijection": primary.arm_mapping_state.eq("exact_label_candidate_bijection"),
        "explicit_comparator_roles": primary.comparator_role_state.eq("explicit_two_group_roles"),
        "tested_ni_flag_explicit_false_all_analyses": primary.tested_non_inferiority_states.map(lambda v: v == ["false"])}
    def funnel(masks):
        running = pd.Series(True, index=next(iter(masks.values())).index)
        result = {}
        for name, mask in masks.items():
            running &= mask
            result[name] = {"independent_count": int(mask.sum()), "cumulative_in_listed_order": int(running.sum())}
        return result
    analysis_types = [analysis["analysis_type"] for analyses in primary.analysis_evidence for analysis in analyses]
    return {"trial_funnel": funnel(trial_masks), "primary_funnel": funnel(primary_masks),
        "trial_distributions": {c: _counts(trials, c) for c in SAMPLE_AXES + ["primary_count_state"]},
        "primary_distributions": {c: _counts(primary, c) for c in ("parameter_family", "unit_family", "arm_mapping_state", "comparator_role_state", "noninferiority_state", "equivalence_state", "multiplicity_state", "endpoint_key_state")},
        "all_primary_analysis_type_counts": {"analysis_rows": len(analysis_types),
            "raw_enum": dict(Counter("<missing>" if not _norm(x["non_inferiority_type_raw"]) else str(x["non_inferiority_type_raw"]) for x in analysis_types)),
            "enum_state": dict(Counter(x["enum_state"] for x in analysis_types)),
            "tested_flag_state": dict(Counter(x["tested_flag_state"] for x in analysis_types)),
            "field_consistency": dict(Counter(x["field_consistency"] for x in analysis_types)),
            "flag_by_enum": dict(Counter(x["tested_flag_state"] + "|" + x["enum_state"] for x in analysis_types))},
        "primary_p_parse_counts": dict(Counter(x for states in primary.p_parse_states for x in states)),
        "primary_contrast_counts": dict(Counter(x for states in primary.analysis_contrast_states for x in states)),
        "sample_count": len(sample), "sample_coverage": {c: {"universe": _counts(trials, c), "sample": _counts(sample, c)} for c in SAMPLE_AXES},
        "interpretation": "Availability funnel only; no new efficacy labels, no direction assessment, no model. Exact arm-label candidates do not verify clinical identity. No new estimable target established."}


def run(source: Path, out: Path, limit_trials: int | None = None, sample_size=120, seed=SEED) -> dict:
    if out.exists():
        raise FileExistsError(f"Refusing overwrite: {out}")
    if limit_trials is not None and limit_trials < 1:
        raise ValueError("limit_trials must be positive")
    if sample_size < 0:
        raise ValueError("sample_size must be nonnegative")
    provenance = verify_provenance(source)
    selected, dates = guard_dates(source)
    # Values are opened only after every source table passes metadata-only guards.
    reasons = pd.read_parquet(source / "graded_trials.parquet", columns=TRIAL + ["reason_code"])
    selected = selected.merge(reasons, on=TRIAL, validate="one_to_one").sort_values(TRIAL)
    if limit_trials is not None:
        selected = selected.head(limit_trials)
    keys = _keys(selected, TRIAL)
    frames = {name: _subset(pd.read_parquet(source / filename), TRIAL, keys) for name, filename in FILES.items()}
    primary, trials, quality = audit_frames(selected, frames)
    sample = sample_trials(trials, sample_size, seed)
    report = {"status": "development_structural_audit_only", "pinned_universe": 8414, "audited_trials": len(trials), "audited_primary_outcomes": len(primary),
              "pilot": limit_trials is not None, "seed": seed, "sample_requested": sample_size, "date_guard": dates, "key_quality": quality,
              **coverage_report(primary, trials, sample)}
    raw_sample = sample_records(sample, frames)
    out.mkdir(parents=True)
    primary.to_parquet(out / "primary_evidence.parquet", index=False)
    trials.to_parquet(out / "trial_evidence.parquet", index=False)
    sample.to_parquet(out / "sample_trials.parquet", index=False)
    with (out / "sample_raw.jsonl").open("w") as handle:
        for record in raw_sample:
            handle.write(json.dumps(record, allow_nan=False) + "\n")
    (out / "report.json").write_text(json.dumps(_jsonable(report), indent=2, allow_nan=False) + "\n")
    manifest = {"provenance": provenance, "settings": {"limit_trials": limit_trials, "sample_size": sample_size, "seed": seed},
        "code_sha256": digest(Path(__file__)), "output_sha256": {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()},
        "sample_algorithm": "Cover reason codes, p presence, eras in axis/value order first; then rare marginals by frequency/axis/value; SHA256(seed|NCT|version) ties; fill round-robin over SHA256(seed|stratum)-ordered strata. Stratum=b19_ plus first16 SHA256 hex digits of semicolon-joined SAMPLE_AXES values. Unique exact trials, sorted output."}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PINNED)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit-trials", type=int)
    parser.add_argument("--sample-size", type=int, default=120)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.out, args.limit_trials, args.sample_size, args.seed), indent=2))


if __name__ == "__main__":
    main()
