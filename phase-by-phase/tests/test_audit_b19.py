"""Focused synthetic B19 structural audit checks, never efficacy assertions."""
import json

import pandas as pd
import pytest

from phase_by_phase.audit_b19 import (ANALYSIS, FILES, GROUP, KEYS, OUTCOME, TRIAL,
    analysis_type_evidence, audit_frames, coverage_report, guard_dates, parse_p, run, sample_records, sample_trials)


def fixture():
    common = dict(nct_id="NCT_SYNTHETIC", nct_version=2,
                  adapter_version_public_date=pd.Timestamp("2020-01-01"))
    selected = pd.DataFrame([{**{c: common[c] for c in TRIAL}, "result_date": pd.Timestamp("2020-01-01"), "reason_code": "synthetic_reason"}])
    def rows(values):
        return pd.DataFrame([{**common, **v} for v in values])
    frames = {
        "measures": rows([dict(outcome_ord=0, type="PRIMARY", title="RAW PRIMARY", description="full raw description", time_frame="12 weeks", param_type="Mean", unit_of_measure="percent")]),
        "groups": rows([dict(outcome_ord=0, group_id=g, title=label, description="raw group") for g, label in (("G0", "Drug"), ("G1", "Placebo"))]),
        "arms": rows([dict(ord=i, arm_label=label, arm_type=role, description="raw arm") for i, (label, role) in enumerate((("Drug", "EXPERIMENTAL"), ("Placebo", "PLACEBO_COMPARATOR")))]),
        "measurements": rows([dict(outcome_ord=0, class_ord=0, category_ord=0, measurement_ord=i, group_id=g, value=v, spread="3") for i, (g, v) in enumerate((("G0", "10"), ("G1", "20")))]),
        "analyses": rows([dict(outcome_ord=0, analysis_ord=0, p_value="<0.01", statistical_method="raw method", ci_lower_limit="-2", ci_upper_limit="-1", tested_non_inferiority=False, non_inferiority_type=None)]),
        "analysis_groups": rows([dict(outcome_ord=0, analysis_ord=0, group_id=g) for g in ("G0", "G1")]),
    }
    return selected, frames


def test_one_trial_and_endpoint_without_child_multiplication():
    selected, frames = fixture()
    extra = frames["measurements"].copy()
    extra["class_ord"] = 1
    frames["measurements"] = pd.concat([frames["measurements"], extra], ignore_index=True)
    primary, trials, quality = audit_frames(selected, frames)
    assert len(trials) == len(primary) == 1
    assert primary.iloc[0].measurement_row_count == 4
    assert primary.iloc[0].numeric_result_group_count == 2
    assert primary.iloc[0].measurement_groups_with_multiple_rows == 2
    assert quality["measurements"]["duplicate_key_rows"] == 0
    assert primary.iloc[0].direction_state == "unknown_not_assessed"
    assert "efficacy_grade" not in primary
    assert primary.iloc[0].analysis_contrast_states == ["explicit_two_group_role_contrast"]
    assert primary.iloc[0].analysis_evidence[0]["p_parse"] == {"status": "parsed", "qualifier": "<", "value": .01}


@pytest.mark.parametrize("table", list(FILES))
def test_duplicate_full_child_keys_reported_without_multiplication(table):
    selected, frames = fixture()
    frames[table] = pd.concat([frames[table], frames[table].iloc[:1]], ignore_index=True)
    primary, trials, quality = audit_frames(selected, frames)
    assert len(trials) == len(primary) == 1
    assert quality[table]["duplicate_key_rows"] == 2
    if table == "measures":
        assert primary.iloc[0].endpoint_key_state == "duplicate_ambiguous"
    if table in {"groups", "arms"}:
        assert primary.iloc[0].arm_mapping_state == "ambiguous_keys"


def test_missing_multiple_primary_and_empty_inputs():
    selected, frames = fixture()
    frames["measures"]["type"] = "SECONDARY"
    primary, trials, quality = audit_frames(selected, frames)
    assert primary.empty and trials.iloc[0].primary_count_state == "missing"
    assert coverage_report(primary, trials, sample_trials(trials))["primary_funnel"]["primary_outcomes"]["independent_count"] == 0
    selected, frames = fixture()
    extra = frames["measures"].copy()
    extra["outcome_ord"] = 1
    frames["measures"] = pd.concat([frames["measures"], extra], ignore_index=True)
    primary, trials, _ = audit_frames(selected, frames)
    assert len(primary) == 2 and trials.iloc[0].primary_outcome_count == 2
    assert primary.primary_outcome_count.eq(2).all()
    empty_frames = {k: v.iloc[:0] for k, v in frames.items()}
    primary, trials, _ = audit_frames(selected.iloc[:0], empty_frames)
    assert primary.empty and sample_trials(trials).empty
    assert coverage_report(primary, trials, sample_trials(trials))["sample_count"] == 0


@pytest.mark.parametrize("raw,status,qualifier,value", [
    (None, "missing", None, None), ("", "missing", None, None), ("NA", "malformed", None, None),
    ("< 1e-3", "parsed", "<", .001), ("<=.05", "parsed", "<=", .05),
    ("0", "parsed", "=", 0), ("1", "parsed", "=", 1), ("2", "out_of_bounds", "=", 2),
    ("-0.1", "out_of_bounds", "=", -.1), ("<0", "out_of_bounds", "<", 0),
    (">1", "out_of_bounds", ">", 1), ("0.02 (adjusted)", "malformed", None, None)])
def test_p_bounds_and_qualifiers_without_significance_or_direction(raw, status, qualifier, value):
    assert parse_p(raw) == {"status": status, "qualifier": qualifier, "value": value}


def test_mixed_roles_missing_analysis_keys_and_unknown_ni():
    selected, frames = fixture()
    frames["arms"]["arm_type"] = "EXPERIMENTAL"
    frames["analyses"]["tested_non_inferiority"] = None
    primary, _, _ = audit_frames(selected, frames)
    assert primary.iloc[0].comparator_role_state == "mixed_or_unsupported_roles"
    assert primary.iloc[0].analysis_contrast_states == ["contrast_roles_unknown"]
    assert primary.iloc[0].noninferiority_state == "unknown_no_noninferiority_claim"
    assert primary.iloc[0].tested_non_inferiority_states == ["missing"]
    frames["analysis_groups"] = frames["analysis_groups"].iloc[:0]
    primary, _, _ = audit_frames(selected, frames)
    assert primary.iloc[0].analysis_contrast_states == ["missing_analysis_group_keys"]
    frames["analysis_groups"] = fixture()[1]["analysis_groups"]
    frames["analysis_groups"].loc[0, "group_id"] = None
    primary, _, quality = audit_frames(selected, frames)
    assert quality["analysis_groups"]["missing_key_rows"] == 1
    assert primary.iloc[0].analysis_contrast_states == ["ambiguous_analysis_group_keys"]


def test_orphans_missing_columns_and_duplicate_selected():
    selected, frames = fixture()
    frames["analysis_groups"].loc[0, "analysis_ord"] = 99
    frames["measurements"].loc[0, "group_id"] = "UNRESOLVED"
    primary, _, quality = audit_frames(selected, frames)
    assert quality["analysis_groups"]["orphan_parent_rows"] == 1
    assert quality["measurements"]["orphan_parent_rows"] == 1
    assert primary.iloc[0].numeric_result_group_count == 1
    with pytest.raises(ValueError, match="target trial"):
        audit_frames(pd.concat([selected, selected]), frames)
    frames["analyses"] = frames["analyses"].drop(columns="analysis_ord")
    with pytest.raises(ValueError, match="exact key columns"):
        audit_frames(selected, frames)


def test_missing_arm_key_and_missing_primary_key_remain_unknown():
    selected, frames = fixture()
    frames["arms"].loc[0, "ord"] = float("nan")
    primary, _, quality = audit_frames(selected, frames)
    assert primary.iloc[0].arm_mapping_state == "ambiguous_keys"
    assert primary.iloc[0].comparator_role_state == "unknown"
    assert quality["arms"]["missing_key_rows"] == 1
    frames["measures"]["outcome_ord"] = float("nan")
    primary, trials, _ = audit_frames(selected, frames)
    assert primary.empty
    assert trials.iloc[0].missing_primary_key_rows == 1
    assert trials.iloc[0].primary_count_state == "missing_keys"


def write_metadata_fixture(tmp_path, selected, frames):
    selected.to_parquet(tmp_path / "graded_trials.parquet", index=False)
    for name, filename in FILES.items():
        frames[name].to_parquet(tmp_path / filename, index=False)
    frames["groups"][TRIAL + ["adapter_version_public_date"]].to_parquet(tmp_path / "results_adverse_serious_event_stats_clean.parquet", index=False)


def test_all_table_date_guard_before_values_including_nonpilot_rows(tmp_path):
    selected, frames = fixture()
    write_metadata_fixture(tmp_path, selected, frames)
    assert len(guard_dates(tmp_path, expected_count=1)[0]) == 1
    frames["analyses"]["adapter_version_public_date"] = pd.Timestamp("2024-01-01")
    write_metadata_fixture(tmp_path, selected, frames)
    with pytest.raises(ValueError, match="2024"):
        guard_dates(tmp_path, expected_count=1)
    frames["analyses"]["adapter_version_public_date"] = pd.NaT
    write_metadata_fixture(tmp_path, selected, frames)
    with pytest.raises(ValueError, match="Missing/invalid"):
        guard_dates(tmp_path, expected_count=1)
    selected["result_date"] = pd.Timestamp("2024-01-01")
    with pytest.raises(ValueError, match="2024"):
        audit_frames(selected, frames)


def test_date_mismatch_and_missing_public_column(tmp_path):
    selected, frames = fixture()
    frames["arms"]["adapter_version_public_date"] = pd.Timestamp("2019-01-01")
    write_metadata_fixture(tmp_path, selected, frames)
    with pytest.raises(ValueError, match="differs"):
        guard_dates(tmp_path, 1)
    frames["arms"] = frames["arms"].drop(columns="adapter_version_public_date")
    write_metadata_fixture(tmp_path, selected, frames)
    with pytest.raises(ValueError, match="Missing public"):
        guard_dates(tmp_path, 1)


def test_deterministic_stratified_sample_rare_reasons_and_raw_linkage():
    selected, frames = fixture()
    primary, trial, _ = audit_frames(selected, frames)
    trials = pd.concat([trial.assign(nct_id=f"NCT_{i:03}", b17_reason_code=f"reason_{i % 11}") for i in range(180)], ignore_index=True)
    first = sample_trials(trials)
    second = sample_trials(trials.sample(frac=1, random_state=1))
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == first.nct_id.nunique() == 120
    assert first.b17_reason_code.nunique() == 11
    raw = sample_records(sample_trials(trial), frames)[0]
    assert raw["children"]["measures"][0]["description"] == "full raw description"
    assert raw["children"]["measures"][0]["time_frame"] == "12 weeks"
    assert raw["children"]["analyses"][0]["statistical_method"] == "raw method"
    assert len(raw["children"]["measurements"]) == 2
    assert len(raw["children"]["analysis_groups"]) == 2
    json.dumps(raw, allow_nan=False)
    frames["analysis_groups"].loc[0, "analysis_ord"] = 99
    raw = sample_records(sample_trials(trial), frames)[0]
    assert len(raw["children"]["analysis_groups"]) == 1
    assert len(raw["unlinked_primary_children"]["analysis_groups"]) == 1


def test_unknown_and_ambiguous_numeric_no_negative_outcomes():
    selected, frames = fixture()
    frames["measurements"]["value"] = [None, "not reported"]
    frames["analyses"]["p_value"] = None
    frames["groups"]["title"] = "same"
    primary, trials, _ = audit_frames(selected, frames)
    assert primary.iloc[0].numeric_result_group_count == 0
    assert primary.iloc[0].p_parse_states == ["missing"]
    assert primary.iloc[0].arm_mapping_state == "labels_not_unique_bijection"
    assert primary.iloc[0].direction_state == "unknown_not_assessed"
    assert not trials.iloc[0].parsed_p_present


def test_pinned_source_and_no_overwrite(tmp_path):
    with pytest.raises(ValueError, match="pinned B17"):
        run(tmp_path, tmp_path / "new")
    with pytest.raises(FileExistsError, match="overwrite"):
        run(tmp_path, tmp_path)


@pytest.mark.parametrize("flag,flag_state", [(True, "true"), (False, "false"), (None, "missing")])
@pytest.mark.parametrize("raw,category", [
    ("SUPERIORITY", "superiority"), ("NON_INFERIORITY", "noninferiority"),
    ("EQUIVALENCE", "equivalence"), ("NON_INFERIORITY_OR_EQUIVALENCE", "noninferiority_or_equivalence"),
    ("SUPERIORITY_OR_OTHER", "superiority_or_other"), ("OTHER", "other"),
    ("UNRECOGNIZED", "unknown_enum"), (None, "missing")])
def test_analysis_type_enum_flag_cross_product_stays_separate(flag, flag_state, raw, category):
    evidence = analysis_type_evidence(flag, raw)
    assert evidence["tested_non_inferiority_raw"] is flag
    assert evidence["tested_flag_state"] == flag_state
    assert evidence["non_inferiority_type_raw"] == raw
    assert evidence["enum_state"] == category
    if flag is True and raw == "SUPERIORITY":
        assert evidence["field_consistency"] == "conflict_true_flag_superiority_enum"
    if flag is False and raw == "NON_INFERIORITY":
        assert evidence["field_consistency"] == "conflict_false_flag_noninferiority_enum"
    if flag is None:
        assert evidence["field_consistency"] == "unknown_missing_flag"


@pytest.mark.parametrize("raw,expected", [("NON_INFERIORITY_OR_EQUIVALENCE_LEGACY", "noninferiority_or_equivalence"),
    ("SUPERIORITY_OR_OTHER_LEGACY", "superiority_or_other")])
def test_legacy_enums_are_exact_mappings(raw, expected):
    assert analysis_type_evidence(None, raw)["enum_state"] == expected
    assert analysis_type_evidence(None, "NI_OR_EQ_LEGACY")["enum_state"] == "unknown_enum"


def test_primary_enum_aggregate_counts_and_equivalence_not_erased():
    selected, frames = fixture()
    analyses = pd.concat([frames["analyses"].assign(analysis_ord=i, tested_non_inferiority=flag, non_inferiority_type=raw)
        for i, (flag, raw) in enumerate([(False, "SUPERIORITY_OR_OTHER"), (None, "NON_INFERIORITY"),
            (None, "EQUIVALENCE"), (True, "NON_INFERIORITY_OR_EQUIVALENCE"), (None, None)])], ignore_index=True)
    frames["analyses"] = analyses
    primary, trials, _ = audit_frames(selected, frames)
    row = primary.iloc[0]
    assert row.noninferiority_state == "explicit_noninferiority_enum"
    assert row.equivalence_state == "explicit_equivalence_enum"
    assert "noninferiority_or_equivalence" in row.analysis_type_enum_states
    assert row.tested_non_inferiority_states == ["false", "missing", "true"]
    report = coverage_report(primary, trials, sample_trials(trials))
    counts = report["all_primary_analysis_type_counts"]
    assert counts["analysis_rows"] == 5
    assert counts["tested_flag_state"] == {"false": 1, "missing": 3, "true": 1}
    assert counts["raw_enum"]["<missing>"] == 1
    assert counts["enum_state"]["equivalence"] == 1
    assert counts["flag_by_enum"]["true|noninferiority_or_equivalence"] == 1
    # A broad superiority/other enum is neither a positive NI assertion nor proof of absence.
    frames["analyses"] = analyses.iloc[:1]
    primary, _, _ = audit_frames(selected, frames)
    assert primary.iloc[0].noninferiority_state == "unknown_no_noninferiority_claim"
    assert primary.iloc[0].equivalence_state == "unknown_no_equivalence_claim"
    frames["analyses"] = analyses.iloc[3:4]
    primary, _, _ = audit_frames(selected, frames)
    assert primary.iloc[0].noninferiority_state == primary.iloc[0].equivalence_state == "combined_enum_ambiguous"
