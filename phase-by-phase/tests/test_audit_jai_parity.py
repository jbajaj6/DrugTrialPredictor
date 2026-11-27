import pandas as pd

from phase_by_phase.audit_jai_parity import jai_parity_audit


def _study(nct, submitted, posted, *, start="2019-01-01", intervention="DRUG",
           status="COMPLETED", has_results=False):
    return {"hasResults": has_results,
            "protocolSection": {
                "identificationModule": {"nctId": nct},
                "designModule": {"studyType": "INTERVENTIONAL"},
                "armsInterventionsModule": {"interventions": [{"type": intervention, "name": "Drug A"}]},
                "statusModule": {"overallStatus": status,
                                 "startDateStruct": {"date": start},
                                 "studyFirstSubmitDate": submitted,
                                 "studyFirstPostDateStruct": {"date": posted}}}}


def _cleaned(ids):
    return pd.DataFrame({
        "nct_id": ids, "phase": ["PHASE2"] * len(ids),
        "condition_count": [1] * len(ids), "start_date_type": ["ACTUAL"] * len(ids),
        "completion_date": ["2019-08-01"] * len(ids),
        "completion_date_type": ["ACTUAL"] * len(ids),
        "last_update_post_date": ["2019-09-01"] * len(ids),
        "results_first_post_date": [None] * len(ids)})


def test_submitted_lag_not_posted_lag_and_no_result_completion_retained():
    good = _study("NCT00000001", "2019-03-01", "2019-05-01")
    late_submission = _study("NCT00000002", "2019-05-01", "2019-05-02")
    studies = [good, late_submission]
    cleaned = _cleaned(["NCT00000001", "NCT00000002"])
    bridge = pd.DataFrame({"nct_id": cleaned.nct_id, "program_id": ["p1", "p2"]})
    report = jai_parity_audit(studies, cleaned, bridge)
    assert report["source_records"] == 2
    assert report["jai_like_cohort"] == 1
    assert report["jai_like_without_posted_results"] == 1
    assert report["known_completion_labels_without_posted_results"] == 1
    assert report["completion_label_maturity"]["train"]["known_by_origin"] == 1
    assert report["phase_by_phase_extra_funnel_on_jai_like_cohort"][-2]["nct_count"] == 1
    assert report["phase_by_phase_extra_funnel_on_jai_like_cohort"][-1]["nct_count"] == 1


def test_early_submission_allowed_and_same_day_completion_not_prospective():
    early = _study("NCT00000003", "2018-12-01", "2019-02-01")
    cleaned = _cleaned(["NCT00000003"])
    cleaned.loc[0, "completion_date"] = "2019-02-01"
    bridge = pd.DataFrame({"nct_id": ["NCT00000003"], "program_id": ["p3"]})
    report = jai_parity_audit([early], cleaned, bridge)
    assert report["jai_like_cohort"] == 1
    assert report["early_submission_negative_lag"] == 1
    assert report["phase_by_phase_extra_funnel_on_jai_like_cohort"][-2]["nct_count"] == 0
    assert report["completion_label_maturity"]["train"]["known_by_origin"] == 1


def test_sealed_outcome_not_accessed():
    class BombStatus(dict):
        def get(self, key, default=None):
            if key != "studyFirstPostDateStruct":
                raise AssertionError("sealed source outcome or metadata read")
            return super().get(key, default)

    sealed = _study("NCT00000004", "2019-01-02", "2024-01-01")
    sealed["protocolSection"]["statusModule"] = BombStatus(
        {"studyFirstPostDateStruct": {"date": "2024-01-01"}})
    cleaned = _cleaned(["NCT00000004"])
    bridge = pd.DataFrame({"nct_id": ["NCT00000004"], "program_id": ["p4"]})
    report = jai_parity_audit([sealed], cleaned, bridge)
    assert report["jai_like_cohort"] == 0
    assert report["sealed_first_post_2024_onward_or_undated"] == 1


def test_biological_only_is_excluded_by_jai_drug_rule():
    biological = _study("NCT00000005", "2019-01-02", "2019-01-03", intervention="BIOLOGICAL")
    cleaned = _cleaned(["NCT00000005"])
    bridge = pd.DataFrame({"nct_id": ["NCT00000005"], "program_id": ["p5"]})
    report = jai_parity_audit([biological], cleaned, bridge)
    assert report["jai_like_cohort"] == 0
    assert report["jai_like_funnel"][1]["nct_count"] == 1
    assert report["jai_like_funnel"][2]["nct_count"] == 0


def test_month_only_start_is_bounded_not_imputed_and_outside_year_separate():
    month_certain = _study("NCT00000006", "2019-04-01", "2019-04-02", start="2019-01")
    month_uncertain = _study("NCT00000007", "2019-04-20", "2019-04-21", start="2019-01")
    outside_year = _study("NCT00000008", "2004-04-01", "2004-04-02", start="2004-01")
    ids = ["NCT00000006", "NCT00000007", "NCT00000008"]
    cleaned = _cleaned(ids)
    bridge = pd.DataFrame({"nct_id": ids, "program_id": ids})
    report = jai_parity_audit([month_certain, month_uncertain, outside_year], cleaned, bridge)
    precision = report["start_precision_after_final_status"]
    assert precision["month_only_in_range"] == 2
    assert precision["outside_2005_2019"] == 1
    bounds = report["month_only_start_submitted_lag_bounds"]
    assert bounds["definitely_lag_le_90"] == 1
    assert bounds["possibly_lag_le_90"] == 2
    assert bounds["uncertain_at_month_precision"] == 1
    assert report["jai_like_cohort"] == 0
