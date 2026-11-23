"""Deliberate corruption tests: reporting success must not hide broken data."""
import json

import pandas as pd
import pytest

from phase_by_phase.audit import audit_tables, review_sample
from phase_by_phase.organize import build_tables


def source(nct, phase="PHASE1", drug="Drug A", conditions=None):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct},
            "designModule": {"studyType": "INTERVENTIONAL", "phases": [phase]},
            "statusModule": {
                "startDateStruct": {"date": "2010-02-03", "type": "ACTUAL"},
                "studyFirstPostDateStruct": {"date": "2009-12-31"},
                "completionDateStruct": {"date": "2012-02", "type": "ACTUAL"},
            },
            "conditionsModule": {"conditions": conditions or ["Disease X"]},
            "armsInterventionsModule": {
                "armGroups": [{"label": "Treatment", "type": "EXPERIMENTAL"}],
                "interventions": [{"name": drug, "type": "DRUG", "armGroupLabels": ["Treatment"]}],
            },
        }
    }


@pytest.fixture
def tables():
    return build_tables([
        source("NCT00000001"), source("NCT00000002", phase="PHASE3"),
        source("NCT00000003", drug="Drug B"),
    ])


@pytest.fixture
def manifest():
    return {"complete": True, "records": 3, "total_count": 3, "cutoff": "2026-11-19"}


def status(report, name):
    return next(check["status"] for check in report["checks"] if check["name"] == name)


def test_structural_success_does_not_masquerade_as_clinical_validation(tables, manifest):
    original = {name: value.copy(deep=True) for name, value in tables.items()}
    report = audit_tables(tables, manifest)
    assert report["summary"]["structural_status"] == "PASS"
    assert report["overall"] == "WARN" and report["hard_fail"] is False
    assert status(report, "clinical_identity_validation") == "WARN"
    assert status(report, "historical_feature_availability") == "WARN"
    assert report["summary"]["programs_with_multiple_phase_labels"] == 1
    assert report["summary"]["programs_with_pure_phase1_and_phase3_records"] == 1
    json.dumps(report, allow_nan=False)
    for name in tables:
        pd.testing.assert_frame_equal(tables[name], original[name])


def test_partial_download_warns_without_failing_sound_tables(tables):
    report = audit_tables(tables, {"complete": False, "records": 3, "total_count": 100})
    assert not report["hard_fail"]
    assert status(report, "source_complete") == "WARN"
    assert report["summary"]["source"]["total_count"] == 100


def test_empty_dataset_fails():
    report = audit_tables(build_tables([]), {"complete": True, "records": 0, "total_count": 0})
    assert report["hard_fail"]
    assert status(report, "source_trials_nonempty") == "FAIL"


def test_missing_schema_reports_failure_instead_of_keyerror(tables, manifest):
    del tables["trials"]["nct_id"]
    report = audit_tables(tables, manifest)
    assert report["hard_fail"]
    assert status(report, "schema_trials") == "FAIL"


def test_null_program_key_is_hard_failure(tables, manifest):
    tables["program_trials"].loc[0, "program_id"] = None
    report = audit_tables(tables, manifest)
    assert report["hard_fail"]
    assert status(report, "nonmissing_keys_program_trials") == "FAIL"


def test_duplicate_trial_row_is_hard_failure(tables, manifest):
    tables["trials"] = pd.concat([tables["trials"], tables["trials"].iloc[[0]]], ignore_index=True)
    report = audit_tables(tables, manifest)
    assert report["hard_fail"]
    assert status(report, "unique_keys_trials") == "FAIL"


def test_duplicate_bridge_arm_is_hard_failure(tables, manifest):
    tables["program_trials"] = pd.concat([tables["program_trials"], tables["program_trials"].iloc[[0]]], ignore_index=True)
    report = audit_tables(tables, manifest)
    assert report["hard_fail"]
    assert status(report, "unique_keys_program_trials") == "FAIL"


def test_foreign_trial_in_child_table_is_hard_failure(tables, manifest):
    tables["interventions"].loc[0, "nct_id"] = "NCT99999999"
    report = audit_tables(tables, manifest)
    assert report["hard_fail"]
    assert status(report, "nct_foreign_keys_interventions") == "FAIL"


def test_unaccounted_downloaded_trial_is_hard_failure(tables, manifest):
    tables["program_trials"] = tables["program_trials"].loc[tables["program_trials"]["nct_id"].ne("NCT00000003")]
    report = audit_tables(tables, manifest)
    assert status(report, "all_downloaded_trials_accounted_for") == "FAIL"
    assert report["hard_fail"]


def test_explicit_exclusion_accounts_for_unlinked_trial():
    tables = build_tables([source("NCT00000001"), source("NCT00000002", conditions=["Disease X", "Disease Y"])])
    report = audit_tables(tables, {"complete": True, "records": 2, "total_count": 2})
    assert not report["hard_fail"]
    assert status(report, "all_downloaded_trials_accounted_for") == "PASS"
    assert report["summary"]["linkage_fraction_of_all_downloaded_trials"] == 0.5
    assert report["summary"]["unlinked_trials"] == 1


def test_changed_program_summary_identity_fails_cross_table_collision_check(tables, manifest):
    tables["programs"].loc[0, "indication_id"] = "different disease"
    report = audit_tables(tables, manifest)
    assert status(report, "program_id_single_identity") == "FAIL"
    assert report["hard_fail"]


def test_orphaned_program_id_fails_foreign_key_check(tables, manifest):
    tables["program_trials"].loc[0, "program_id"] = "unknown-program"
    report = audit_tables(tables, manifest)
    assert status(report, "program_foreign_keys") == "FAIL"


def test_null_components_fail_without_crashing(tables, manifest):
    tables["program_trials"].loc[0, "component_keys_json"] = None
    report = audit_tables(tables, manifest)
    assert report["hard_fail"]
    assert status(report, "canonical_active_component_lists") == "FAIL"


@pytest.mark.parametrize("bad_json", ['["placebo"]', '["drug b","drug a"]', '["drug a","drug a"]', '{"drug":"a"}', 'not json'])
def test_corrupted_component_lists_fail(bad_json, tables, manifest):
    tables["program_trials"].loc[0, "component_keys_json"] = bad_json
    report = audit_tables(tables, manifest)
    assert status(report, "canonical_active_component_lists") == "FAIL"


def test_shared_drug_split_across_groups_fails(tables, manifest):
    tables["program_trials"].loc[0, "drug_group"] = "different-group"
    report = audit_tables(tables, manifest)
    assert status(report, "shared_components_stay_grouped") == "FAIL"


def test_program_counts_use_unique_trials_not_exploded_rows(tables, manifest):
    tables["programs"].loc[0, "n_trials"] = 999
    report = audit_tables(tables, manifest)
    assert status(report, "program_trial_counts_match") == "FAIL"


def test_unknown_phase_and_wrong_study_type_are_detected(tables, manifest):
    tables["trials"].loc[0, "phase"] = "PHASE99"
    tables["trials"].loc[0, "study_type"] = "OBSERVATIONAL"
    report = audit_tables(tables, manifest)
    assert status(report, "canonical_phase_values") == "FAIL"
    assert status(report, "linked_trials_have_supported_phase") == "FAIL"
    assert status(report, "linked_trials_interventional") == "FAIL"


def test_partial_dates_reported_and_false_precision_detected(tables, manifest):
    report = audit_tables(tables, manifest)
    assert report["summary"]["date_precision_counts"]["completion_date"]["month"] == 3
    assert status(report, "date_precision_preserved_completion_date") == "PASS"
    tables["trials"].loc[0, "completion_date_precision"] = "day"
    report = audit_tables(tables, manifest)
    assert status(report, "date_precision_preserved_completion_date") == "FAIL"


def test_invalid_source_dates_warn_if_truthfully_preserved():
    record = source("NCT00000001")
    record["protocolSection"]["statusModule"]["startDateStruct"]["date"] = "2010-02-31"
    report = audit_tables(build_tables([record]), {"complete": True, "records": 1, "total_count": 1})
    assert not report["hard_fail"]
    assert status(report, "invalid_source_dates_start_date") == "WARN"
    assert report["summary"]["date_precision_counts"]["start_date"]["invalid"] == 1


@pytest.mark.parametrize("manifest,failed_check", [
    ({"complete": True, "records": 4, "total_count": 3}, "manifest_record_count"),
    ({"complete": True, "records": 3, "total_count": 100}, "manifest_total_count"),
    ({"complete": False, "records": 3, "total_count": 1}, "manifest_total_count"),
])
def test_manifest_count_contradictions_fail(tables, manifest, failed_check):
    report = audit_tables(tables, manifest)
    assert status(report, failed_check) == "FAIL"
    assert report["hard_fail"]


def test_missing_manifest_does_not_invent_download_completeness(tables):
    report = audit_tables(tables, {})
    assert not report["hard_fail"]
    assert status(report, "source_complete") == "WARN"
    assert status(report, "manifest_record_count") == "WARN"


def test_review_queue_deterministic_includes_urls_and_is_not_adjudication(tables):
    first = review_sample(tables, n=2)
    reordered = {name: value.iloc[::-1].reset_index(drop=True) for name, value in tables.items()}
    pd.testing.assert_frame_equal(first, review_sample(reordered, n=2))
    assert len(first) == 2
    assert set(first["review_stratum"]) == {"multiple_phase_labels", "single_phase_label"}
    assert set(first["identity_review"]) == {"NOT_REVIEWED"}
    assert all(url.startswith("https://clinicaltrials.gov/study/NCT") for item in first["source_urls_json"] for url in json.loads(item))


def test_zero_sized_review_queue_keeps_schema(tables):
    assert review_sample(tables, n=0).empty
    with pytest.raises(ValueError, match="nonnegative"):
        review_sample(tables, n=-1)
