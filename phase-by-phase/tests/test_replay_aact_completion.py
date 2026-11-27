"""B6 synthetic checks for no-lag, all-status prospective completion rows."""
import pandas as pd

from phase_by_phase.replay_aact_completion import completion_rows


def _trial(nct, **change):
    row = {"nct_id": nct, "overall_status": "COMPLETED", "phase": "PHASE3",
           "start_date": "2017-01-01", "first_submitted_date": "2017-02-01",
           "first_post_date": "2017-02-10", "completion_date": "2021-01-01",
           "completion_date_type": "ACTUAL", "last_update_post_date": "2021-02-01",
           "results_first_post_date": None}
    row.update(change)
    return row


def test_late_registration_is_retained_and_lag_flagged():
    rows = completion_rows(pd.DataFrame([
        _trial("LATE", first_submitted_date="2017-06-01"),
        _trial("EARLY", first_submitted_date="2016-12-01")]))
    assert rows.nct_id.tolist() == ["EARLY", "LATE"]
    values = rows.set_index("nct_id")
    assert values.loc["LATE", "lag_bucket"] == "submitted_more_than_90_days_after_start"
    assert not values.loc["LATE", "jai_lag_le_90"]
    assert values.loc["EARLY", "jai_lag_le_90"]
    assert values.loc["LATE", "public_post_lag_bucket"] == "posted_0_to_90_days_after_start"
    assert values.completion_label.tolist() == [1, 1]


def test_ongoing_is_unlabeled_not_failure():
    rows = completion_rows(pd.DataFrame([
        _trial("ONGOING", overall_status="RECRUITING", completion_date=None,
               completion_date_type="ESTIMATED", last_update_post_date="2023-01-01")]))
    assert len(rows) == 1
    assert pd.isna(rows.loc[0, "completion_label"])


def test_sealed_status_and_completion_not_accessed():
    class Bomb:
        def __str__(self):
            raise AssertionError("sealed outcome accessed")

    rows = completion_rows(pd.DataFrame([_trial("SAFE"),
        _trial("SEALED", first_post_date="2024-01-01", overall_status=Bomb(),
               completion_date=Bomb())]))
    assert rows.nct_id.tolist() == ["SAFE"]


def test_nonprospective_and_update_before_completion_excluded_or_unknown():
    rows = completion_rows(pd.DataFrame([
        _trial("ALREADY_DONE", completion_date="2017-02-10"),
        _trial("OWN_RESULT", results_first_post_date="2017-02-10"),
        _trial("EARLY_UPDATE", last_update_post_date="2020-12-01")]))
    assert rows.nct_id.tolist() == ["EARLY_UPDATE"]
    assert rows.completion_label.isna().all()


def test_split_uses_2016_training_origin_and_2024_validation_cutoff():
    rows = completion_rows(pd.DataFrame([
        _trial("VALIDATION"),
        _trial("OLD_TRAIN", start_date="2015-01-01",
               first_submitted_date="2015-02-01", first_post_date="2015-02-10",
               completion_date="2017-01-01", last_update_post_date="2017-02-01")]))
    values = rows.set_index("nct_id")
    assert values.loc["VALIDATION", "completion_label"] == 1
    assert pd.isna(values.loc["OLD_TRAIN", "completion_label"])


def test_pre_start_posting_uses_start_as_checkpoint():
    rows = completion_rows(pd.DataFrame([
        _trial("VALID_PRESTART", first_post_date="2016-12-01"),
        _trial("DONE_BEFORE_START", first_post_date="2016-12-01",
               completion_date="2016-12-15", last_update_post_date="2017-02-01"),
        _trial("OWN_RESULT_BEFORE_START", first_post_date="2016-12-01",
               results_first_post_date="2016-12-15")]))
    assert rows.nct_id.tolist() == ["VALID_PRESTART"]
    assert rows.loc[0, "prediction_date"] == pd.Timestamp("2017-01-01")
    assert rows.loc[0, "public_post_lag_bucket"] == "posted_before_start"
    assert rows.loc[0, "completion_label"] == 1
