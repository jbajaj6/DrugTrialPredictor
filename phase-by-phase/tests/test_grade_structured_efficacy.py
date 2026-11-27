"""Synthetic safety and chronology boundaries for structured efficacy grading."""
import pandas as pd
import pytest

from phase_by_phase.grade_structured_efficacy import grade_trial, parse_p, favorable_direction, run
from phase_by_phase.historical_dev_models import digest
import json


def fixture():
    measures = pd.DataFrame([dict(outcome_ord=0,type="PRIMARY",title="Overall Survival",
                                  unit_of_measure="Months",param_type="Median",
                                  is_obsolete=False,adapter_core_is_obsolete=False)])
    groups = pd.DataFrame([dict(outcome_ord=0,group_id=gid,title=title,
                                is_obsolete=False,adapter_core_is_obsolete=False)
                           for gid,title in (("OG0","Drug"),("OG1","Placebo"))])
    measurements = pd.DataFrame([dict(outcome_ord=0,group_id=gid,value=value,
                                      is_obsolete=False,adapter_core_is_obsolete=False)
                                 for gid,value in (("OG0","15"),("OG1","10"))])
    analyses = pd.DataFrame([dict(outcome_ord=0,analysis_ord=0,p_value="0.02",
                                   group_description="Drug versus Placebo",
                                   tested_non_inferiority=False,non_inferiority_type=None,
                                   is_obsolete=False,adapter_core_is_obsolete=False)])
    arms = pd.DataFrame([dict(arm_label=label,arm_type=role,
                              is_obsolete=False,adapter_core_is_obsolete=False)
                         for label,role in (("Drug","EXPERIMENTAL"),
                                            ("Placebo","PLACEBO_COMPARATOR"))])
    analysis_groups = pd.DataFrame([dict(outcome_ord=0,analysis_ord=0,group_id=gid,
                                      is_obsolete=False,adapter_core_is_obsolete=False)
                                    for gid in ("OG0","OG1")])
    return [measures,groups,measurements,analyses,arms,analysis_groups]


def test_supported_requires_mapping_direction_and_verified_comparison():
    parts = fixture()
    assert grade_trial(*parts)["efficacy_grade"] == "supported_benefit"
    parts[5].loc[0,"group_id"] = "OTHER"
    assert grade_trial(*parts)["reason_code"] == "analysis_comparison_unverified"


def test_direction_and_p_do_not_equate_to_worked():
    parts = fixture()
    parts[2].loc[parts[2].group_id.eq("OG0"),"value"] = "5"
    assert grade_trial(*parts)["efficacy_grade"] == "benefit_not_demonstrated"
    parts = fixture()
    parts[3].loc[0,"p_value"] = "0.8"
    assert grade_trial(*parts)["efficacy_grade"] == "benefit_not_demonstrated"
    parts[3].loc[0,"p_value"] = None
    assert grade_trial(*parts)["efficacy_grade"] == "directional_only"


def test_ambiguous_structure_remains_ungradable():
    parts = fixture()
    parts[0].loc[0,"title"] = "Pain Score"
    assert grade_trial(*parts)["reason_code"] == "effect_direction_not_verified"
    parts = fixture()
    parts[0] = pd.concat([parts[0],parts[0].assign(outcome_ord=1)])
    assert grade_trial(*parts)["reason_code"] == "multiple_primary_outcomes"
    parts = fixture()
    parts[3] = pd.concat([parts[3],parts[3]],ignore_index=True)
    assert grade_trial(*parts)["reason_code"] == "multiple_analyses_multiplicity_unknown"
    parts = fixture()
    parts[3].loc[0,"tested_non_inferiority"] = True
    assert grade_trial(*parts)["reason_code"] == "noninferiority_requires_review"
    parts = fixture()
    parts[3]["tested_non_inferiority"] = parts[3].tested_non_inferiority.astype("boolean")
    parts[3].loc[0,"tested_non_inferiority"] = pd.NA
    assert grade_trial(*parts)["efficacy_grade"] == "supported_benefit"
    parts = fixture()
    parts[0].loc[0,"unit_of_measure"] = "Percent"
    assert grade_trial(*parts)["reason_code"] == "effect_unit_or_parameter_unverified"


def test_missing_comparator_or_values_are_not_failures():
    parts = fixture()
    parts[4].loc[1,"arm_label"] = "Control"
    assert grade_trial(*parts)["efficacy_grade"] == "ungradable"
    parts = fixture()
    parts[2].loc[1,"value"] = None
    assert grade_trial(*parts)["reason_code"] == "non_numeric_measurement"
    parts = fixture()
    result = grade_trial(*parts)
    assert result["safety_signal"] == "unknown"
    assert result["safety_reason_code"] == "event_comparison_not_verified"


@pytest.mark.parametrize("raw,reason",[("<0.05","p_supports_threshold"),
                                         ("<=0.05","p_ambiguous"),
                                         ("0.05","p_does_not_support_threshold"),
                                         (">0.01","p_ambiguous"),
                                         (None,"p_missing")])
def test_p_boundary(raw,reason):
    assert parse_p(raw)[1] == reason


def test_only_strict_directions_whitelisted():
    assert favorable_direction("Overall Survival") == "higher"
    assert favorable_direction("Change in Pain Score") is None


def test_run_selects_first_exact_version_and_seals_2024(tmp_path):
    """Duplicate primary rows cannot alter version choice; later revisions stay out."""
    protocol, results, prior = (tmp_path / name for name in ("protocol", "results", "prior"))
    for directory in (protocol,results,prior):
        directory.mkdir()
    prior_file = prior / "development_rows.parquet"
    pd.DataFrame([dict(nct_id="NCT00000001",pure_phase="PHASE3",
                       first_public_date=pd.Timestamp("2018-01-01"))]).to_parquet(prior_file)
    (prior / "manifest.json").write_text(json.dumps({"output_sha256":{prior_file.name:digest(prior_file)}}))
    arms = pd.DataFrame([dict(nct_id="NCT00000001",nct_version=v,arm_label=label,
                              arm_type=role,is_obsolete=False,adapter_core_is_obsolete=False)
                         for v in (2,3,4) for label,role in
                         (("Drug","EXPERIMENTAL"),("Placebo","PLACEBO_COMPARATOR"))])
    arm_file = protocol / "arms_clean.parquet"
    arms.to_parquet(arm_file)
    (protocol / "manifest.json").write_text(json.dumps({"output_files_sha256":{arm_file.name:digest(arm_file)}}))
    shared = dict(nct_id="NCT00000001",outcome_ord=0,is_obsolete=False,
                  adapter_core_is_obsolete=False)
    dates = {2:pd.Timestamp("2019-01-01"),3:pd.Timestamp("2020-01-01"),
             4:pd.Timestamp("2024-01-01")}
    measures = pd.DataFrame([dict(shared,nct_version=v,type="PRIMARY",
                                  title="Overall Survival",unit_of_measure="Months",
                                  param_type="Median",adapter_version_public_date=dates[v])
                             for v in (2,2,3,4)])
    groups = pd.DataFrame([dict(shared,nct_version=v,group_id=gid,title=title)
                           for v in (2,3,4) for gid,title in (("OG0","Drug"),("OG1","Placebo"))])
    measurements = pd.DataFrame([dict(shared,nct_version=v,group_id=gid,value=value)
                                 for v in (2,3,4) for gid,value in (("OG0","15"),("OG1","10"))])
    analyses = pd.DataFrame([dict(shared,nct_version=v,analysis_ord=0,p_value="0.02",
                                  tested_non_inferiority=False,non_inferiority_type=None,
                                  ci_lower_limit=None,ci_upper_limit=None)
                             for v in (2,3,4)])
    analysis_groups = pd.DataFrame([dict(shared,nct_version=v,analysis_ord=0,group_id=gid)
                                    for v in (2,3,4) for gid in ("OG0","OG1")])
    serious = pd.DataFrame([dict(nct_id="NCT00000001",nct_version=v,event_ord=0,
                                group_id="OG0",num_affected=1,num_at_risk=10,
                                is_obsolete=False,adapter_core_is_obsolete=False)
                           for v in (2,3,4)])
    tables = dict(results_outcome_measures_clean=measures,
                  results_outcome_groups_clean=groups,
                  results_outcome_measurements_clean=measurements,
                  results_outcome_analyses_clean=analyses,
                  results_outcome_analysis_groups_clean=analysis_groups,
                  results_adverse_serious_event_stats_clean=serious)
    hashes = {}
    for name,frame in tables.items():
        path = results / f"{name}.parquet"
        frame.to_parquet(path)
        hashes[path.name] = digest(path)
    (results / "manifest.json").write_text(json.dumps({"output_files_sha256":hashes}))
    report = run(prior_file,protocol,results,tmp_path / "out")
    assert report["selected_result_versions"] == 1
    output = pd.read_parquet(tmp_path / "out" / "graded_trials.parquet")
    assert output.nct_version.tolist() == [2]
    assert output.result_date.iloc[0] == pd.Timestamp("2019-01-01")
    assert output.serious_event_stat_row_count.tolist() == [1]
    assert pd.read_parquet(tmp_path / "out" / "results_outcome_measures_clean.parquet").nct_version.unique().tolist() == [2]
    with pytest.raises(FileExistsError):
        run(prior_file,protocol,results,tmp_path / "out")
