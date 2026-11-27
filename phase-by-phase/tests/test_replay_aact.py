"""Synthetic date and label-firewall checks for the AACT replay."""
import hashlib
import zipfile

import pandas as pd
import pytest

from phase_by_phase.replay_aact import (derive_rows, phase_prevalence,
                                       qualifier_aware_decisions, verify_source)


def _trial(nct, **change):
    row = {"nct_id": nct, "overall_status": "COMPLETED", "phase": "PHASE3",
           "start_date": "2015-01-01", "first_submitted_date": "2015-02-01",
           "first_post_date": "2015-02-10", "completion_date": "2017-01-01",
           "completion_date_type": "ACTUAL", "last_update_post_date": "2017-02-01",
           "results_first_post_date": "2017-01-15"}
    row.update(change)
    return row


def test_lag_has_no_lower_bound_and_missing_p_stays_unknown():
    rows = pd.DataFrame([_trial("EARLY", first_submitted_date="2014-01-01"),
                         _trial("LATE", first_submitted_date="2015-05-01")])
    result = derive_rows(rows, {})
    assert result.nct_id.tolist() == ["EARLY"]
    assert result.completion_label.tolist() == [1]
    assert result.significance_label.isna().all()


def test_q2_is_completed_only_and_results_posted_after_checkpoint():
    rows = pd.DataFrame([_trial("YES"), _trial("STOP", overall_status="TERMINATED"),
                         _trial("OWN", results_first_post_date="2015-02-10")])
    result = derive_rows(rows, {"YES": 0.04, "STOP": 0.01, "OWN": 0.01})
    values = result.set_index("nct_id")
    assert values.loc["YES", "significance_label"] == 1
    assert pd.isna(values.loc["STOP", "significance_label"])
    assert pd.isna(values.loc["OWN", "significance_label"])


def test_sealed_row_outcome_objects_not_accessed():
    class Bomb:
        def __str__(self):
            raise AssertionError("sealed status accessed")

    rows = pd.DataFrame([_trial("SAFE"),
                         _trial("SEALED", first_post_date="2024-01-01",
                                overall_status=Bomb(), completion_date=Bomb())])
    result = derive_rows(rows, {})
    assert result.nct_id.tolist() == ["SAFE"]


def test_same_day_completion_not_labeled():
    rows = pd.DataFrame([_trial("SAME", completion_date="2015-02-10",
                                last_update_post_date="2017-02-01")])
    result = derive_rows(rows, {"SAME": 0.01})
    assert result.completion_label.isna().all()
    assert result.significance_label.isna().all()
    assert result.prospective_at_checkpoint.tolist() == [False]


def test_prevalence_train_requires_label_before_2016():
    rows = pd.DataFrame([_trial("EARLY", completion_date="2015-06-01",
                                last_update_post_date="2015-07-01"),
                         _trial("LATE", completion_date="2017-01-01",
                                last_update_post_date="2017-02-01")])
    result = derive_rows(rows, {})
    report = phase_prevalence(result)["PHASE3"]["completion"]
    assert report["train_labeled"] == 1
    assert report["validation_labeled"] == 0
    assert report["status"] == "not_estimable"


def test_qualifier_aware_p_preserves_ambiguous_and_missing():
    analyses = pd.DataFrame([
        {"nct_id": "LOW", "p_value": 0.05, "p_value_modifier": "<"},
        {"nct_id": "AMBIG", "p_value": 0.04, "p_value_modifier": ">"},
        {"nct_id": "INVALID", "p_value": 1.2, "p_value_modifier": None},
        {"nct_id": "MISSING", "p_value": 0.3, "p_value_modifier": None},
        {"nct_id": "MISSING", "p_value": None, "p_value_modifier": None},
        {"nct_id": "NEG", "p_value": 0.3, "p_value_modifier": "="},
    ])
    result = qualifier_aware_decisions(analyses)
    assert result == {"LOW": True, "AMBIG": None, "INVALID": None,
                      "MISSING": None, "NEG": False}


def test_update_before_completion_cannot_date_terminal_label():
    rows = pd.DataFrame([_trial("EARLY_UPDATE", completion_date="2017-01-01",
                                last_update_post_date="2016-12-01")])
    result = derive_rows(rows, {"EARLY_UPDATE": 0.01})
    assert result.audit_update_before_actual_completion.tolist() == [True]
    assert result.completion_label.isna().all()
    assert result.significance_label.isna().all()


def test_provenance_detects_changed_extracted_input(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()
    archive = tmp_path / "20261029_aact_flat.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("studies.txt", "nct_id|status\nNCT1|COMPLETED\n")
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    extracted = tables / "studies.txt"
    extracted.write_bytes(b"nct_id|status\nNCT1|COMPLETED\n")
    report = verify_source(tables, expected, ("studies",))
    assert report["consumed_tables"]["studies"]["verified_against_zip_member"] is True
    extracted.write_bytes(b"nct_id|status\nNCT1|TERMINATED\n")
    with pytest.raises(ValueError, match="differs from verified ZIP"):
        verify_source(tables, expected, ("studies",))
