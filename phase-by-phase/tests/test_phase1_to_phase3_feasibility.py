"""Synthetic checks for the Phase 1 -> Phase 3 feasibility firewall."""
import pandas as pd

from phase_by_phase.phase1_to_phase3_feasibility import link_eligibility, support_gate


def _pair(**changes):
    pair = dict(phase1_nct_id="NCT1", phase3_nct_id="NCT3",
                drug_key="DRUG A", condition_key="CONDITION A",
                phase1_candidate_count=1, phase3_candidate_count=1,
                phase1_checkpoint_date="2009-01-01", phase1_result_date="2010-06-01",
                phase3_checkpoint_date="2012-01-01",
                phase3_label=1, phase3_label_date="2015-01-01")
    pair.update(changes)
    return pair


def test_public_phase1_result_must_precede_phase3_checkpoint():
    rows = link_eligibility(pd.DataFrame([_pair(), _pair(phase1_result_date="2012-02-01"),
                                         _pair(phase1_result_date="2008-12-01")]))
    assert rows.link_eligible.tolist() == [True, False, False]


def test_ambiguous_links_and_missing_label_are_not_negative():
    rows = link_eligibility(pd.DataFrame([
        _pair(phase1_candidate_count=2),
        _pair(phase3_candidate_count=2),
        _pair(phase3_label=None, phase3_label_date=None),
    ]))
    assert rows.link_eligible.tolist() == [False, False, True]
    assert rows.label_known.tolist() == [True, True, False]
    assert pd.isna(rows.loc[2, "phase3_label"])


def test_holdout_date_never_known_and_same_nct_rejected():
    rows = link_eligibility(pd.DataFrame([
        _pair(phase3_label_date="2024-01-01"),
        _pair(phase1_nct_id="NCT3"),
    ]))
    assert rows.label_known.tolist() == [False, True]
    assert rows.link_eligible.tolist() == [True, False]


def test_gate_rejects_unsupported_and_cross_split_program():
    rows = link_eligibility(pd.DataFrame([
        _pair(phase3_nct_id="NCT3A", phase3_checkpoint_date="2014-01-01"),
        _pair(phase3_nct_id="NCT3B", phase3_checkpoint_date="2017-01-01",
              phase1_result_date="2016-06-01", phase3_label_date="2018-01-01"),
    ]))
    gate = support_gate(rows)
    assert not gate["estimable"]
    assert gate["overlapping_program_groups_excluded"] == 1
    assert gate["train"] == gate["validation"] == 0


def test_partition_uses_phase1_result_date_not_phase3_design_date():
    rows = link_eligibility(pd.DataFrame([
        _pair(drug_key="DRUG B", phase1_result_date="2016-06-01",
              phase3_checkpoint_date="2017-01-01", phase3_label_date="2018-01-01"),
    ]))
    gate = support_gate(rows)
    assert gate["train"] == 0
    assert gate["validation"] == 1
