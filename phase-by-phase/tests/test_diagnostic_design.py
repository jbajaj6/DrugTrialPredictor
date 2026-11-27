"""Synthetic correctness gates for the B7 retrospective diagnostic."""
import numpy as np
import pandas as pd
import pytest

from phase_by_phase.diagnostic_design import (
    FORBIDDEN, _one_nct, assert_whitelist, build_sponsor_history,
    evaluate, prepare_features,
)


def _trial(nct, start, post, completion, update, label, sponsor="Example"):
    checkpoint = max(pd.Timestamp(start), pd.Timestamp(post))
    return {"nct_id": nct, "start_date": pd.Timestamp(start),
            "first_post_date": pd.Timestamp(post), "prediction_date": checkpoint,
            "completion_date": pd.Timestamp(completion), "completion_date_type": "ACTUAL",
            "last_update_post_date": pd.Timestamp(update), "completion_label": label,
            "completion_label_available_date": pd.Timestamp(update)}


def test_feature_whitelist_rejects_target_and_lag():
    for forbidden in FORBIDDEN:
        with pytest.raises(ValueError):
            assert_whitelist(("start_year", forbidden))
    with pytest.raises(ValueError):
        assert_whitelist(("start_year", "start_year"))


def test_sponsor_history_only_other_published_prior_outcomes():
    rows = pd.DataFrame([
        _trial("prior", "2010-01-01", "2010-01-02", "2011-01-01", "2012-01-01", 0),
        _trial("same_day", "2010-01-01", "2010-01-02", "2011-01-01", "2015-01-01", 1),
        _trial("target", "2015-01-01", "2015-01-01", "2017-01-01", "2018-01-01", 1),
        _trial("future", "2015-01-01", "2015-01-01", "2018-01-01", "2019-01-01", 0),
    ])
    leads = pd.DataFrame({"nct_id": rows.nct_id, "lead_sponsor_name": "Example"})
    history = build_sponsor_history(rows, leads).set_index("nct_id")
    assert history.loc["target", "sponsor_prior_finished"] == 1
    assert history.loc["target", "sponsor_prior_stop_rate"] == pytest.approx(3.5 / 6)
    assert history.loc["target", "sponsor_latest_prior_available"] == pd.Timestamp("2012-01-01")
    assert history.loc["prior", "sponsor_no_prior_finished"] == 1
    assert np.isnan(history.loc["prior", "sponsor_prior_stop_rate"])


def test_sponsor_history_rejects_completion_before_checkpoint_and_bad_update():
    leads = pd.DataFrame({"nct_id": ["bad"], "lead_sponsor_name": ["Example"]})
    early = pd.DataFrame([_trial("bad", "2015-01-01", "2015-01-02",
                                 "2014-12-01", "2016-01-01", 1)])
    with pytest.raises(ValueError, match="nonprospective"):
        build_sponsor_history(early, leads)
    bad_update = pd.DataFrame([_trial("bad", "2010-01-01", "2010-01-02",
                                      "2012-01-01", "2011-01-01", 1)])
    with pytest.raises(ValueError, match="unavailable"):
        build_sponsor_history(bad_update, leads)
    early_claim = pd.DataFrame([_trial("bad", "2010-01-01", "2010-01-02",
                                      "2012-01-01", "2013-01-01", 1)])
    early_claim.loc[0, "completion_label_available_date"] = pd.Timestamp("2011-01-01")
    with pytest.raises(ValueError, match="unavailable"):
        build_sponsor_history(early_claim, leads)


def test_cardinality_and_sealed_label_guard():
    with pytest.raises(ValueError, match="one NCT"):
        _one_nct(pd.DataFrame({"nct_id": ["x", "x"]}), "target")

    class SealedLabel:
        def __bool__(self):
            raise AssertionError("sealed label accessed")

    rows = pd.DataFrame({"nct_id": ["sealed"], "prediction_date": [pd.Timestamp("2024-01-01")],
                         "completion_label": [SealedLabel()]})
    features = pd.DataFrame({"nct_id": ["sealed"], "prediction_date": [pd.Timestamp("2024-01-01")]})
    with pytest.raises(ValueError, match="Sealed"):
        evaluate(rows, features)


def test_missing_protocol_flags_stay_unknown():
    target = pd.DataFrame({"nct_id": ["x"], "phase_stratum": ["PHASE2"],
                           "prediction_date": [pd.Timestamp("2012-01-01")],
                           "start_date": [pd.Timestamp("2012-01-01")]})
    design = pd.DataFrame({"nct_id": ["x"], "has_dmc": [None],
                           "elig_healthy_volunteers": [None], "mesh_terms": [None],
                           "minimum_age": [None], "maximum_age": [None]})
    for column in ("allocation", "intervention_model", "masking", "primary_purpose",
                   "elig_gender", "number_of_arms", "n_conditions", "n_primary_outcomes",
                   "n_secondary_outcomes", "n_mesh_terms", "has_placebo_arm",
                   "has_active_comparator", "n_drug_interventions"):
        design[column] = None
    lead = pd.DataFrame({"nct_id": ["x"], "sponsor_class": ["INDUSTRY"]})
    history = pd.DataFrame({"nct_id": ["x"], "sponsor_prior_finished": [0],
                            "sponsor_prior_stop_rate": [np.nan], "sponsor_no_prior_finished": [1]})
    result = prepare_features(target, design, history, lead)
    assert pd.isna(result.loc[0, "has_dmc"])
    assert pd.isna(result.loc[0, "elig_healthy_volunteers"])
