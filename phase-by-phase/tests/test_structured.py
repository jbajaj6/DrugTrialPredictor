"""Synthetic, non-holdout tests for structured registry extraction."""
from __future__ import annotations

import pandas as pd
import pytest

from phase_by_phase.structured import _p_value, build_structured_tables, build_trial_snapshots


def study(nct: str, posted: str | None = "2018-02-01", p: str | None = "<0.01") -> dict:
    status = {}
    if posted is not None:
        status["resultsFirstPostDateStruct"] = {"date": posted}
    return {
        "protocolSection": {"identificationModule": {"nctId": nct}, "statusModule": status},
        "resultsSection": {
            "participantFlowModule": {"groups": [{"id": "FG1", "title": "Drug A"}], "periods": [{"title": "Overall", "milestones": [{"type": "STARTED", "achievements": [{"groupId": "FG1", "numSubjects": "12"}]}]}]},
            "outcomeMeasuresModule": {"outcomeMeasures": [{"type": "PRIMARY", "title": "Response", "reportingStatus": "POSTED", "unitOfMeasure": "Participants", "groups": [{"id": "OG1", "title": "Drug A"}], "denoms": [{"units": "Participants", "counts": [{"groupId": "OG1", "value": "12"}]}], "classes": [{"categories": [{"measurements": [{"groupId": "OG1", "value": "7"}]}]}], "analyses": [{"groupIds": ["OG1", "OG2"], "pValue": p}]}]},
            "adverseEventsModule": {"eventGroups": [{"id": "EG1", "title": "Drug A", "seriousNumAffected": 3, "seriousNumAtRisk": 12}], "seriousEvents": [{"term": "Headache", "organSystem": "Nervous system", "stats": [{"groupId": "EG1", "numAffected": "3", "numAtRisk": "12", "numEvents": "5"}]}]},
        },
    }


def trial(nct: str, phase: str, start: str, first_post: str, result_post: str | None, status: str = "COMPLETED", completion: str | None = "2020-01-01", last_update: str = "2020-01-01") -> dict:
    return {"nct_id": nct, "phase": phase, "start_date": start, "start_date_type": "ACTUAL", "first_post_date": first_post, "results_first_post_date": result_post, "last_update_post_date": last_update, "completion_date": completion, "completion_date_type": "ACTUAL", "status": status, "identity_status": "candidate_exact_label", "sponsor_class": "INDUSTRY", "allocation": "RANDOMIZED", "masking": "DOUBLE", "arm_count": 2}


def test_child_tables_preserve_measurement_provenance():
    data = build_structured_tables([study("NCT00000001")])
    assert set(data) == {"result_arms", "participant_flow", "outcomes", "analyses", "adverse_events"}
    assert data["participant_flow"].iloc[0].num_subjects_raw == "12"
    assert data["outcomes"].iloc[0].denominator_raw == "12"
    assert data["outcomes"].iloc[0].unit == "Participants"
    analysis = data["analyses"].iloc[0]
    assert (analysis.p_value_raw, analysis.p_operator, analysis.p_value_numeric) == ("<0.01", "<", 0.01)
    assert analysis.p_significant_005 == True
    event = data["adverse_events"].loc[data["adverse_events"].event_kind.eq("serious")].iloc[0]
    assert (event.subjects_affected_raw, event.events_raw) == ("3", "5")
    assert event.group_id == "EG1"
    assert event.results_first_post_date == "2018-02-01"
    total = data["adverse_events"].loc[data["adverse_events"].event_kind.eq("serious_total")].iloc[0]
    assert (total.subjects_affected_raw, total.subjects_at_risk_raw) == (3, 12)


@pytest.mark.parametrize("raw,decision", [("<0.05", True), ("0.05", False), ("<0.1", None), (">0.01", None), ("N/A", None), (None, None)])
def test_p_bounds_are_not_overinterpreted(raw, decision):
    assert _p_value(raw)[2] is decision


def test_empty_modules_have_stable_schema():
    data = build_structured_tables([{"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}}])
    assert all(frame.empty for frame in data.values())
    assert "p_value_raw" in data["analyses"].columns


def test_dated_rows_exclude_self_future_and_undated_evidence():
    ids = [f"NCT{i:08d}" for i in range(1, 6)]
    trials = pd.DataFrame([
        trial(ids[0], "PHASE1", "2017-01-01", "2017-01-02", "2018-02-01", last_update="2018-02-01"),
        trial(ids[1], "PHASE1", "2017-01-03", "2017-01-04", None),
        trial(ids[2], "PHASE2", "2019-01-01", "2019-01-03", "2020-01-01", last_update="2020-01-01"),
        trial(ids[3], "PHASE3", "2019-01-02", "2019-01-04", "2021-01-01"),
        trial(ids[4], "PHASE1", "2017-01-05", "2017-01-06", "2025-01-01"),
    ])
    bridge = pd.DataFrame({"nct_id": ids, "program_id": ["p"] * 5})
    structured = build_structured_tables([study(ids[0]), study(ids[1], None), study(ids[2], "2020-01-01", ">=0.05"), study(ids[3], "2021-01-01"), study(ids[4], "2025-01-01")])
    rows = build_trial_snapshots({"trials": trials, "program_trials": bridge}, structured, "2022-01-01")
    phase2 = rows.loc[rows.nct_id.eq(ids[2])].iloc[0]
    assert phase2.prediction_date == "2019-01-03"
    assert phase2.prior_result_count == 1
    assert phase2.prior_primary_significant_count == 1
    assert phase2.max_evidence_date == "2018-02-01"
    assert phase2.prior_flow_retention_mean is None  # STARTED alone is not retention.
    assert phase2.prior_sae_max_rate_mean == 0.25
    assert phase2.prior_primary_analysis_count == 1
    assert phase2.result_content_version_verified == True
    phase3 = rows.loc[rows.nct_id.eq(ids[3])].iloc[0]
    assert phase3.prior_result_count == 1  # Phase 2 results posted after launch.
    assert phase3.significance_label == True  # Label, never feature.
    assert rows.loc[rows.nct_id.eq(ids[1]), "significance_label"].isna().all()
    assert rows.loc[rows.nct_id.eq(ids[4]), "significance_label"].isna().all()
    # Reference the former frame-filter algorithm on this mixed-date fixture.
    # The optimized per-program index must produce identical evidence gates.
    source = trials.copy()
    for field in ("start_date", "first_post_date", "results_first_post_date", "last_update_post_date"):
        source[field + "_ts"] = pd.to_datetime(source[field], errors="coerce")
    rank = {"PHASE1": 1, "PHASE2": 2, "PHASE3": 3}
    for target in rows.itertuples(index=False):
        prediction = pd.Timestamp(target.prediction_date)
        old = source.loc[(source.nct_id != target.nct_id) & source.start_date_ts.notna() & source.first_post_date_ts.notna() & source.results_first_post_date_ts.notna()]
        old = old.loc[(old.start_date_ts < prediction) & (old.first_post_date_ts <= prediction) & (old.results_first_post_date_ts <= prediction) & (old.results_first_post_date_ts >= old.start_date_ts) & (old.results_first_post_date_ts >= old.first_post_date_ts) & old.phase.map(rank).lt(rank[target.phase])]
        assert target.prior_result_count_firstpost_gated == len(old)
        old = old.loc[old.last_update_post_date_ts.notna() & (old.last_update_post_date_ts <= prediction)]
        assert target.prior_result_count == len(old)


def test_revised_current_record_cannot_supply_historical_result_content():
    early = "NCT00000001"
    later = "NCT00000002"
    trials = pd.DataFrame([
        trial(early, "PHASE1", "2017-01-01", "2017-01-02", "2018-02-01", last_update="2021-01-01"),
        trial(later, "PHASE2", "2019-01-01", "2019-01-03", None),
    ])
    bridge = pd.DataFrame({"nct_id": [early, later], "program_id": ["p", "p"]})
    structured = build_structured_tables([study(early), study(later, None)])
    row = build_trial_snapshots({"trials": trials, "program_trials": bridge}, structured, "2022-01-01").loc[lambda x: x.nct_id.eq(later)].iloc[0]
    assert row.prior_result_count_firstpost_gated == 1
    assert row.prior_result_count == 0
    assert row.result_content_version_verified == False
    assert pd.isna(row.prior_sae_max_rate_mean)


def test_completion_requires_actual_observed_date_and_terminal_status():
    ids = ["NCT00000001", "NCT00000002", "NCT00000003"]
    trials = pd.DataFrame([
        trial(ids[0], "PHASE1", "2017-01-01", "2017-01-02", None, "COMPLETED", "2025-01-01"),
        trial(ids[1], "PHASE1", "2017-01-01", "2017-01-02", None, "TERMINATED", "2018-01-01"),
        trial(ids[2], "PHASE1", "2017-01-01", "2017-01-02", None, "RECRUITING", None),
    ])
    bridge = pd.DataFrame({"nct_id": ids, "program_id": ids})
    structured = build_structured_tables([study(nct, None) for nct in ids])
    rows = build_trial_snapshots({"trials": trials, "program_trials": bridge}, structured, "2022-01-01")
    assert pd.isna(rows.loc[0, "completion_label"])
    assert rows.loc[1, "completion_label"] == False
    assert pd.isna(rows.loc[2, "completion_label"])


def test_many_programs_without_results_are_processed_without_quadratic_filters():
    ids = [f"NCT{i:08d}" for i in range(1, 3001)]
    trials = pd.DataFrame([trial(nct, "PHASE1", "2017-01-01", "2017-01-02", None) for nct in ids])
    bridge = pd.DataFrame({"nct_id": ids, "program_id": ids})
    structured = build_structured_tables([])
    rows = build_trial_snapshots({"trials": trials, "program_trials": bridge}, structured, "2023-12-31")
    assert len(rows) == 3000
    assert rows.prior_result_count.sum() == 0


@pytest.mark.parametrize("completion,retained", [
    ("2018-12-31", False), ("2019-01-03", False), ("2019-01-04", True)])
def test_completed_trial_must_be_prospective_at_checkpoint(completion, retained):
    nct = "NCT00000001"
    trials = pd.DataFrame([trial(nct, "PHASE2", "2019-01-01", "2019-01-03",
                                 None, completion=completion, last_update="2020-01-01")])
    bridge = pd.DataFrame({"nct_id": [nct], "program_id": ["p"]})
    structured = build_structured_tables([])
    rows = build_trial_snapshots({"trials": trials, "program_trials": bridge}, structured, "2022-01-01")
    assert (len(rows) == 1) is retained


def test_same_day_public_target_result_is_not_prospective():
    nct = "NCT00000001"
    trials = pd.DataFrame([trial(nct, "PHASE2", "2019-01-01", "2019-01-03",
                                 "2019-01-03", completion="2020-01-01",
                                 last_update="2019-01-03")])
    bridge = pd.DataFrame({"nct_id": [nct], "program_id": ["p"]})
    structured = build_structured_tables([study(nct, "2019-01-03")])
    rows = build_trial_snapshots({"trials": trials, "program_trials": bridge}, structured, "2022-01-01")
    assert rows.empty


def test_public_target_result_excluded_even_when_significance_unknown():
    nct = "NCT00000001"
    trials = pd.DataFrame([trial(nct, "PHASE2", "2019-01-01", "2019-01-03",
                                 "2019-01-03", completion="2020-01-01",
                                 last_update="2020-01-01")])
    bridge = pd.DataFrame({"nct_id": [nct], "program_id": ["p"]})
    rows = build_trial_snapshots({"trials": trials, "program_trials": bridge},
                                 build_structured_tables([study(nct, "2019-01-03", None)]),
                                 "2022-01-01")
    assert rows.empty


@pytest.mark.parametrize("completion,retained", [
    ("2018-12", False), ("2019-01", False), ("2019-02", True)])
def test_month_only_actual_completion_interval_is_conservative(completion, retained):
    nct = "NCT00000001"
    trials = pd.DataFrame([trial(nct, "PHASE2", "2019-01-01", "2019-01-03",
                                 None, completion=completion, last_update="2020-01-01")])
    bridge = pd.DataFrame({"nct_id": [nct], "program_id": ["p"]})
    rows = build_trial_snapshots({"trials": trials, "program_trials": bridge},
                                 build_structured_tables([]), "2022-01-01")
    assert (len(rows) == 1) is retained
    if retained:
        assert pd.isna(rows.iloc[0].completion_label)
