"""B22 preregistered reported-superiority-p proxy boundaries (synthetic)."""
from __future__ import annotations

import pandas as pd
import pytest

from phase_by_phase.reported_superiority_b22 import decide, materialize_labels, materialize_pair_evidence, p_threshold, run, validate_selected_keys, review_sample


@pytest.mark.parametrize("raw,want",[("=.049",1),("=.05",0),("<.05",1),
                                      ("<=.05",None),("<.1",None),(">.05",0),
                                      (">.01",None),("0.1",0),(">=0.05",0),
                                      ("nan",None),("1.2",None),("-0.1",None)])
def test_p_interval_truth_table(raw,want):
    assert p_threshold(raw)[0] == want


def fixture():
    trial={"nct_version":2,"result_date":pd.Timestamp("2020-01-01"),
           "primary_outcome_count":1,"primary_source_row_count":1,"primary_count_state":"single"}
    analysis={"analysis_ord":0,"group_ids":["OG0","OG1"],"p_value_raw":"<.01",
              "contrast_state":"explicit_two_group_role_contrast",
              "analysis_type":{"enum_state":"superiority","tested_flag_state":"missing",
                               "field_consistency":"unknown_missing_flag"}}
    primary={"outcome_ord":0,"endpoint_key_state":"unique","missing_primary_key_rows":0,
             "analysis_count":1,"analysis_evidence":[analysis],
             "arm_mapping_state":"exact_label_candidate_bijection",
             "comparator_role_state":"explicit_two_group_roles"}
    return trial,[primary]


def test_determinate_and_unknown_conditions():
    trial,primary=fixture()
    assert decide(trial,primary,"2018-01-01")["proxy_label"] == 1
    primary[0]["analysis_evidence"][0]["p_value_raw"] = "=.05"
    assert decide(trial,primary,"2018-01-01")["proxy_label"] == 0
    assert decide(None,[],"2018-01-01")["reason_code"] == "no_posted_primary_result"


@pytest.mark.parametrize("change,reason",[
    (lambda t,p: t.update(primary_outcome_count=2),"primary_missing_or_multiple"),
    (lambda t,p: t.update(primary_source_row_count=2),"primary_missing_or_multiple"),
    (lambda t,p: p[0].update(analysis_count=2),"analysis_missing_or_multiple"),
    (lambda t,p: p[0].update(analysis_count=0,analysis_evidence=[]),"analysis_missing_or_multiple"),
    (lambda t,p: p[0].update(arm_mapping_state="labels_not_unique_bijection"),"arm_mapping_unverified"),
    (lambda t,p: p[0].update(comparator_role_state="mixed_or_unsupported_roles"),"comparator_role_unverified"),
    (lambda t,p: p[0]["analysis_evidence"][0].update(group_ids=["OG0","OG0"]),"analysis_contrast_unverified"),
    (lambda t,p: p[0]["analysis_evidence"][0].update(group_ids=["OG0"]),"analysis_contrast_unverified"),
    (lambda t,p: p[0]["analysis_evidence"][0]["analysis_type"].update(enum_state="superiority_or_other"),"not_explicit_superiority"),
    (lambda t,p: p[0]["analysis_evidence"][0]["analysis_type"].update(enum_state="noninferiority"),"not_explicit_superiority"),
    (lambda t,p: p[0]["analysis_evidence"][0]["analysis_type"].update(enum_state="equivalence"),"not_explicit_superiority"),
    (lambda t,p: p[0]["analysis_evidence"][0]["analysis_type"].update(enum_state="noninferiority_or_equivalence"),"not_explicit_superiority"),
    (lambda t,p: p[0]["analysis_evidence"][0]["analysis_type"].update(tested_flag_state="true"),"noninferiority_equivalence_or_flag_conflict"),
    (lambda t,p: p[0]["analysis_evidence"][0]["analysis_type"].update(field_consistency="conflict_true_flag_superiority_enum"),"noninferiority_equivalence_or_flag_conflict"),
    (lambda t,p: p[0]["analysis_evidence"][0].update(p_value_raw="<.1"),"p_interval_crosses_threshold"),
    (lambda t,p: p[0]["analysis_evidence"][0].update(p_value_raw=None),"p_missing")])
def test_fail_closed(change,reason):
    trial,primary=fixture()
    change(trial,primary)
    result=decide(trial,primary,"2018-01-01")
    assert result["proxy_label"] is None
    assert result["reason_code"] == reason


def test_date_and_no_overwrite_guards(tmp_path):
    trial,primary=fixture()
    assert decide(trial,primary,"2020-01-01")["reason_code"] == "invalid_result_chronology"
    trial["result_date"] = pd.Timestamp("2024-01-01")
    assert decide(trial,primary,"2018-01-01")["reason_code"] == "invalid_result_chronology"
    existing=tmp_path/"existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        run(existing)


def test_exact_key_and_holdout_guards():
    trial=pd.DataFrame([dict(nct_id="NCT1",nct_version=2,result_date=pd.Timestamp("2019-01-01"))])
    primary=trial.assign(outcome_ord=0)
    validate_selected_keys(trial,primary,{"NCT1"})
    with pytest.raises(ValueError,match="Duplicate"):
        validate_selected_keys(pd.concat([trial,trial]),primary,{"NCT1"})
    with pytest.raises(ValueError,match="Duplicate"):
        validate_selected_keys(trial,pd.concat([primary,primary]),{"NCT1"})
    with pytest.raises(ValueError,match="Orphan"):
        validate_selected_keys(trial,primary.assign(nct_id="NCT2"),{"NCT1"})
    with pytest.raises(ValueError,match="date mismatch"):
        validate_selected_keys(trial,primary.assign(result_date=pd.Timestamp("2020-01-01")),{"NCT1"})
    with pytest.raises(ValueError,match="Holdout"):
        holdout=trial.assign(result_date=pd.Timestamp("2024-01-01"))
        validate_selected_keys(holdout,holdout.assign(outcome_ord=0),{"NCT1"})


def test_review_selection_replays_after_row_shuffle():
    rows=pd.DataFrame([dict(nct_id=f"NCT{i:04}",reason_code="positive" if i%2 else "unknown",proxy_label=i%2)
                       for i in range(20)])
    a=review_sample(rows,20261127)
    b=review_sample(rows.sample(frac=1,random_state=7),20261127)
    pd.testing.assert_frame_equal(a,b)
    assert len(a)==6


def test_nullable_exact_keys_survive_parquet_roundtrip(tmp_path):
    # A float-backed nullable ordinal silently rounds 2**53+1 to 2**53.
    large = 2**53 + 1
    rows = [dict(nct_id="NCT1", nct_version=large, outcome_ord=large,
                 analysis_ord=large),
            dict(nct_id="NCT2", nct_version=None, outcome_ord=None,
                 analysis_ord=None)]
    labels = materialize_labels(rows)
    for column in ("nct_version", "outcome_ord", "analysis_ord"):
        assert str(labels[column].dtype) == "Int64"
        assert labels.loc[0, column] == large
        assert pd.isna(labels.loc[1, column])
    path = tmp_path / "labels.parquet"
    labels.to_parquet(path, index=False)
    replay = pd.read_parquet(path)
    for column in ("nct_version", "outcome_ord", "analysis_ord"):
        assert str(replay[column].dtype) == "Int64"
        assert replay.loc[0, column] == large
        assert pd.isna(replay.loc[1, column])


def test_pair_evidence_exact_ordinals_survive_parquet_roundtrip(tmp_path):
    large = 2**53 + 1
    row = dict(nct_id="NCT1", nct_version=large, outcome_ord=large,
               analysis_ord=large, group_id="OG1", group_title="Treatment",
               group_source_file="groups.parquet", analysis_group_source_file="links.parquet",
               arm_ord=large, arm_label="Treatment", arm_type="EXPERIMENTAL",
               arm_source_file="arms.parquet")
    evidence = materialize_pair_evidence([row])
    path = tmp_path / "pairs.parquet"
    evidence.to_parquet(path, index=False)
    replay = pd.read_parquet(path)
    for column in ("nct_version", "outcome_ord", "analysis_ord", "arm_ord"):
        assert str(replay[column].dtype) == "Int64"
        assert replay.loc[0, column] == large
