import pandas as pd

from phase_by_phase.build_broad_cohort import broad_cohort, safe_analysis_nct_ids


class Bomb:
    def __str__(self):
        raise AssertionError("sealed or excluded outcome read")

    def __eq__(self, other):
        raise AssertionError("sealed or excluded outcome compared")

    def __bool__(self):
        raise AssertionError("sealed or excluded outcome used")


def _inputs():
    ids = [f"NCT{i:08d}" for i in range(1, 6)]
    trials = pd.DataFrame({
        "nct_id": ids, "phase": ["PHASE1", "PHASE2", "PHASE3", "PHASE1/PHASE2", "PHASE2"],
        "study_type": ["INTERVENTIONAL"] * 5,
        "first_post_date": ["2019-01-02", "2019-01-02", "2019-01-02", "2019-01-02", "2024-01-01"],
        "completion_date": ["2019-08-01", "2019-08-01", "2019-08-01", "2019-01", Bomb()],
        "completion_date_type": ["ACTUAL"] * 5,
        "last_update_post_date": ["2019-09-01"] * 4 + [Bomb()],
        "results_first_post_date": [None, "2019-08-15", "2019-08-15", None, Bomb()],
        "status": ["COMPLETED", "COMPLETED", "TERMINATED", "COMPLETED", Bomb()]})
    interventions = pd.DataFrame({"nct_id": ids,
                                  "intervention_type": ["DRUG"] * 5})
    analyses = pd.DataFrame({"nct_id": [ids[1], ids[2], ids[4]],
                             "outcome_type": ["PRIMARY"] * 3,
                             "p_significant_005": [True, True, Bomb()]})
    return trials, interventions, analyses


def test_completion_does_not_require_results_and_q2_is_completed_only():
    trials, interventions, analyses = _inputs()
    rows, report = broad_cohort(trials, interventions, analyses)
    assert list(rows.nct_id) == ["NCT00000001", "NCT00000002", "NCT00000003"]
    no_result = rows.loc[rows.nct_id.eq("NCT00000001")].iloc[0]
    assert bool(no_result.completion_label) is True
    assert pd.isna(no_result.significance_label)
    completed_p = rows.loc[rows.nct_id.eq("NCT00000002")].iloc[0]
    assert bool(completed_p.significance_label) is True
    terminated_p = rows.loc[rows.nct_id.eq("NCT00000003")].iloc[0]
    assert bool(terminated_p.completion_label) is False
    assert pd.isna(terminated_p.significance_label)
    assert report["phase_strata"]["PHASE2"]["train_completed_q2_eligible"] == 1
    assert report["phase_strata"]["PHASE3"]["train_significance_labeled"] == 0
    assert report["feature_columns"] == ["prediction_year"]
    assert not set(("p_value_raw", "p_significant_005", "results_first_post_date")) & set(rows)


def test_sealed_and_already_public_own_outcome_never_accessed():
    trials, interventions, analyses = _inputs()
    trials.loc[3, "results_first_post_date"] = "2019-01-02"
    trials.loc[3, "completion_date"] = "2019-08-01"
    analyses.loc[len(analyses)] = ["NCT00000004", "PRIMARY", Bomb()]
    rows, report = broad_cohort(trials, interventions, analyses)
    assert "NCT00000004" not in set(rows.nct_id)
    assert "NCT00000005" not in set(rows.nct_id)
    assert report["source_funnel"]["sealed_2024_or_undated_first_post"] == 1
    assert report["source_funnel"]["excluded_own_results_public_at_checkpoint"] == 1


def test_after_cutoff_and_noncompleted_p_values_never_read():
    trials, interventions, analyses = _inputs()
    trials.loc[1, "results_first_post_date"] = "2024-01-01"
    trials.loc[1, "last_update_post_date"] = "2024-01-02"
    analyses.loc[0, "p_significant_005"] = Bomb()
    analyses.loc[1, "p_significant_005"] = Bomb()  # terminated target, not Q2 eligible
    rows, report = broad_cohort(trials, interventions, analyses)
    assert rows.significance_label.notna().sum() == 0
    assert report["result_detail_coverage"]["primary_analysis_nct_in_eligible_q2"] == 0


def test_parquet_read_allowlist_precedes_analysis_access():
    trials, interventions, _ = _inputs()
    assert safe_analysis_nct_ids(trials, interventions) == {"NCT00000002"}
    trials.loc[1, "results_first_post_date"] = "2024-01-01"
    trials.loc[1, "last_update_post_date"] = "2024-01-02"
    assert safe_analysis_nct_ids(trials, interventions) == set()


def test_direct_analysis_filter_never_reads_sealed_outcome_type_or_p():
    trials, interventions, analyses = _inputs()
    analyses.loc[len(analyses)] = ["NCT99999999", Bomb(), Bomb()]
    rows, report = broad_cohort(trials, interventions, analyses)
    assert len(rows) == 3
    assert report["result_detail_coverage"]["primary_analysis_nct_in_eligible_q2"] == 1


def test_unknown_p_value_stays_unknown_and_mixed_phase_is_separate():
    trials, interventions, analyses = _inputs()
    trials.loc[3, "completion_date"] = "2019-08-01"
    analyses.loc[len(analyses)] = ["NCT00000004", "PRIMARY", None]
    rows, report = broad_cohort(trials, interventions, analyses)
    mixed = rows.loc[rows.nct_id.eq("NCT00000004")].iloc[0]
    assert mixed.phase_stratum == "PHASE1/PHASE2"
    assert pd.isna(mixed.significance_label)
    assert report["phase_strata"]["PHASE1/PHASE2"]["missing_significance"] == 1
