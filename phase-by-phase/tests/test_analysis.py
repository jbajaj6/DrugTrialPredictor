"""Scientific contract tests: dates, risk sets, identities, and held-out data."""
import json

import pandas as pd
import pytest

from phase_by_phase.analysis import (
    build_analysis, create_snapshots, exact_date, fit_checkpoint, leakage_groups,
    temporal_split,
)


def trial(nct, phase, start, posted=None, results=None, start_type="ACTUAL"):
    return dict(nct_id=nct, phase=phase, start_date=start, start_date_type=start_type,
                first_post_date=posted or start, results_first_post_date=results,
                sponsor_class="INDUSTRY", allocation="RANDOMIZED", masking="DOUBLE")


def tables(records, programs=None):
    if programs is None:
        programs = ["p1"] * len(records)
    bridge = pd.DataFrame([
        dict(nct_id=t["nct_id"], program_id=p, regimen_id=f"drug_{p}",
             indication_id="condition", component_keys_json=json.dumps([f"drug_{p}"]))
        for t, p in zip(records, programs)
    ])
    return {"trials": pd.DataFrame(records), "program_trials": bridge,
            "programs": bridge.drop_duplicates("program_id")}


def test_partial_dates_are_not_silently_imputed():
    assert pd.isna(exact_date("2012-06"))
    assert pd.isna(exact_date("2012"))
    assert pd.isna(exact_date("2012-02-31"))
    assert exact_date("2012-06-17") == pd.Timestamp("2012-06-17")


def test_baseline_is_public_landmark_and_uses_fixed_horizon():
    data = tables([trial("N1", "PHASE1", "2008-01-01", "2008-02-01", "2010-01-01"),
                   trial("N2", "PHASE3", "2014-01-01")])
    snapshots, _ = create_snapshots(data, "2026-01-01")
    baseline = snapshots.loc[snapshots.checkpoint.eq("baseline")].iloc[0]
    updated = snapshots.loc[snapshots.checkpoint.eq("post_phase1")].iloc[0]
    assert baseline.landmark_date == "2008-02-01"
    assert baseline.horizon_end == "2013-02-01"
    assert baseline.label == 0
    assert updated.landmark_date == "2010-01-01"
    assert updated.label == 1


def test_short_followup_excludes_early_positives_and_negatives_equally():
    data = tables([trial("N1", "PHASE1", "2022-01-01"), trial("N2", "PHASE3", "2023-01-01")])
    snapshots, _ = create_snapshots(data, "2026-01-01")
    assert snapshots.iloc[0].label_status == "insufficient_followup"
    assert pd.isna(snapshots.iloc[0].label)


def test_phase3_already_reached_is_not_a_post_phase1_prediction():
    data = tables([trial("N1", "PHASE1", "2008-01-01", results="2015-01-01"),
                   trial("N2", "PHASE3", "2014-01-01")])
    snapshots, report = create_snapshots(data, "2026-01-01")
    assert snapshots.checkpoint.tolist() == ["baseline"]
    assert report["exclusions"]["post_phase1_phase3_already_started"] == 1


def test_future_trial_or_result_never_enters_dated_features():
    data = tables([trial("N1", "PHASE1", "2008-01-01", results="2010-01-01"),
                   trial("N2", "PHASE1", "2009-01-01", posted="2011-01-01", results="2012-01-01"),
                   trial("N3", "PHASE1", "2012-01-01", results="2014-01-01")])
    snapshots, _ = create_snapshots(data, "2026-01-01")
    updated = snapshots.loc[snapshots.checkpoint.eq("post_phase1")].iloc[0]
    assert updated.phase1_started_count == 1
    assert updated.phase1_results_count == 1
    assert updated.max_feature_available_date <= updated.landmark_date
    assert not updated.historical_versions_available


def test_estimated_phase3_is_not_observed_event_and_combined_is_not_pure_phase3():
    data = tables([trial("N1", "PHASE1", "2008-01-01"),
                   trial("N2", "PHASE3", "2011-01-01", start_type="ESTIMATED"),
                   trial("N3", "PHASE2/PHASE3", "2012-01-01")])
    snapshots, _ = create_snapshots(data, "2026-01-01")
    assert snapshots.iloc[0].label == 0
    assert pd.isna(snapshots.iloc[0].event_date)


def test_undated_actual_phase3_cannot_be_a_negative():
    data = tables([trial("N1", "PHASE1", "2008-01-01"), trial("N2", "PHASE3", "2012-02")])
    snapshots, _ = create_snapshots(data, "2026-01-01")
    assert snapshots.iloc[0].label_status == "indeterminate_phase3_date"
    assert pd.isna(snapshots.iloc[0].label)


def test_first_observed_later_phase_not_relabelled_phase1_entry():
    data = tables([trial("N1", "PHASE2", "2005-01-01"), trial("N2", "PHASE1", "2008-01-01")])
    snapshots, report = create_snapshots(data, "2026-01-01")
    assert snapshots.empty
    assert report["exclusions"]["program_first_observed_phase_not_pure_phase1"] == 1


@pytest.mark.parametrize("early_start,early_type", [("2005-06", None), ("2005-06-01", None), (None, None)])
def test_earlier_partial_or_unknown_chronology_cannot_relabel_later_phase1(early_start, early_type):
    data = tables([trial("N1", "PHASE2", early_start, posted="2005-06-15", start_type=early_type),
                   trial("N2", "PHASE1", "2008-01-01")])
    snapshots, report = create_snapshots(data, "2026-01-01")
    assert snapshots.empty
    assert report["exclusions"]["program_unresolved_initial_chronology"] == 1


def test_leakage_groups_connect_shared_drugs_and_shared_nct():
    bridge = pd.DataFrame([
        dict(program_id="a", nct_id="N1", regimen_id="a", component_keys_json='["x"]'),
        dict(program_id="b", nct_id="N2", regimen_id="b", component_keys_json='["x", "y"]'),
        dict(program_id="c", nct_id="N2", regimen_id="c", component_keys_json='["z"]'),
        dict(program_id="d", nct_id="N3", regimen_id="d", component_keys_json='["q"]'),
    ])
    grouped = leakage_groups(bridge)
    assert grouped["a"] == grouped["b"] == grouped["c"]
    assert grouped["d"] != grouped["a"]


def test_split_purges_group_overlap_and_future_labels():
    dates = pd.date_range("1990-01-01", "2020-01-01", freq="MS")
    frame = pd.DataFrame({"program_id": [f"p{i}" for i in range(len(dates))],
                          "landmark_date": dates.strftime("%Y-%m-%d"),
                          "outcome_available_date": (dates + pd.DateOffset(years=5)).strftime("%Y-%m-%d"),
                          "drug_group": [f"d{i}" for i in range(len(dates))]})
    frame.loc[[0, len(frame) - 1], "drug_group"] = "same_drug"
    split, report = temporal_split(frame)
    train = split[split.split.eq("train")]
    val = split[split.split.eq("validation")]
    test = split[split.split.eq("test")]
    assert len(train) and len(val) and len(test)
    assert set(train.drug_group).isdisjoint(test.drug_group)
    assert set(val.drug_group).isdisjoint(test.drug_group)
    assert (train.outcome_available_date < report["validation_start"]).all()
    assert (val.outcome_available_date < report["test_start"]).all()
    assert split.iloc[-1]["split"] == "excluded_related_group"
    assert "excluded_outcome_embargo" in split.split.values


def test_incomplete_extraction_exports_data_but_does_not_fit(tmp_path):
    data = tables([trial("N1", "PHASE1", "2008-01-01", results="2011-01-01")])
    report = build_analysis(data, "2026-01-01", tmp_path, data_complete=False)
    assert report["models"]["baseline"]["status"] == "not_estimable"
    assert (tmp_path / "snapshots.parquet").exists()
    assert pd.read_parquet(tmp_path / "predictions.parquet").empty
    assert json.loads((tmp_path / "analysis_report.json").read_text())["data_complete"] is False


def test_tiny_complete_cohort_is_reported_not_estimable(tmp_path):
    data = tables([trial("N1", "PHASE1", "2008-01-01")])
    report = build_analysis(data, "2026-01-01", tmp_path, data_complete=True)
    assert report["models"]["baseline"]["status"] == "not_estimable"
    assert "support" in report["models"]["baseline"]


def test_duplicate_trials_rejected():
    data = tables([trial("N1", "PHASE1", "2008-01-01"), trial("N1", "PHASE1", "2008-01-01")])
    with pytest.raises(ValueError, match="one row"):
        create_snapshots(data, "2026-01-01")


def test_supported_synthetic_cohort_fits_and_scores_same_paired_holdout():
    # Synthetic data are only a software smoke test, never project findings.
    dates = pd.date_range("1980-01-01", "2020-01-01", freq="MS")
    count = len(dates)
    frame = pd.DataFrame({
        "program_id": [f"p{i}" for i in range(count)],
        "regimen_id": [f"d{i}" for i in range(count)],
        "drug_group": [f"d{i}" for i in range(count)],
        "indication_id": "condition", "checkpoint": "post_phase1",
        "landmark_date": dates.strftime("%Y-%m-%d"),
        "horizon_end": (dates + pd.DateOffset(years=5)).strftime("%Y-%m-%d"),
        "outcome_available_date": (dates + pd.DateOffset(years=5)).strftime("%Y-%m-%d"),
        "label": [i % 2 for i in range(count)], "label_status": "mature",
        "n_regimen_components": 1, "elapsed_days": 800,
        "index_phase": "PHASE1", "sponsor_class": "INDUSTRY",
        "allocation": "RANDOMIZED", "masking": "DOUBLE",
        "phase1_started_count": [1 + i % 3 for i in range(count)],
        "phase1_results_count": 1,
    })
    report, predictions, split = fit_checkpoint(frame, "post_phase1", bootstrap=20)
    assert report["status"] == "exploratory_fit"
    assert len(predictions) == split.split.eq("test").sum()
    assert set(report["test_metrics"]) == {
        "historical_rate", "baseline_logistic", "updated_logistic", "updated_random_forest",
    }
    for name in report["test_metrics"]:
        assert predictions[f"p_{name}"].between(0, 1).all()
        assert report["test_metrics"][name]["n"] == len(predictions)
    assert "paired_brier_improvement_baseline_minus_updated" in report["uncertainty"]
