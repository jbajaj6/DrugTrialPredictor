"""Scientific counterexamples and source-accounting tests for organization."""
import copy
import json

import pandas as pd
import pytest

from phase_by_phase.organize import SCHEMAS, build_tables, control_kind, label_key


def study(nct="NCT00000001", drugs=None, conditions=None, arms=None):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct},
            "statusModule": {
                "overallStatus": "COMPLETED",
                "startDateStruct": {"date": "2010-02-03", "type": "ACTUAL"},
                "studyFirstPostDateStruct": {"date": "2009-12-30", "type": "ACTUAL"},
            },
            "designModule": {
                "studyType": "INTERVENTIONAL", "phases": ["PHASE1"],
                "designInfo": {"allocation": "RANDOMIZED", "maskingInfo": {"masking": "DOUBLE"}},
                "enrollmentInfo": {"count": 36, "type": "ACTUAL"},
            },
            "conditionsModule": {"conditions": conditions if conditions is not None else ["Disease X"]},
            "armsInterventionsModule": {
                "armGroups": arms if arms is not None else [{"label": "Treatment", "type": "EXPERIMENTAL"}],
                "interventions": drugs if drugs is not None else [
                    {"name": "Drug A", "type": "DRUG", "armGroupLabels": ["Treatment"]}
                ],
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"class": "INDUSTRY", "name": "Sponsor A"}},
        },
        "hasResults": True,
    }


def components(tables):
    return [json.loads(value) for value in tables["program_trials"]["component_keys_json"]]


def exclusion_reasons(tables):
    return set(tables["exclusions"]["reason"])


def test_experimental_drug_is_not_combined_with_active_comparator():
    source = study(
        arms=[{"label": "Treatment", "type": "EXPERIMENTAL"}, {"label": "Control", "type": "ACTIVE_COMPARATOR"}],
        drugs=[{"name": "Drug A", "type": "DRUG", "armGroupLabels": ["Treatment"]},
               {"name": "Drug B", "type": "DRUG", "armGroupLabels": ["Control"]}],
    )
    tables = build_tables([source])
    assert components(tables) == [["drug a"]]
    assert len(tables["interventions"]) == 2
    assert tables["exclusions"].empty


def test_two_experimental_arms_are_separate_regimens_not_one_combination():
    source = study(
        arms=[{"label": "A", "type": "EXPERIMENTAL"}, {"label": "B", "type": "EXPERIMENTAL"}],
        drugs=[{"name": "Drug A", "type": "DRUG", "armGroupLabels": ["A"]},
               {"name": "Drug B", "type": "DRUG", "armGroupLabels": ["B"]}],
    )
    tables = build_tables([source])
    assert sorted(components(tables)) == [["drug a"], ["drug b"]]
    assert len(tables["programs"]) == 2


def test_actual_combination_in_one_arm_includes_biologic_but_not_placebo():
    source = study(drugs=[
        {"name": "Biologic B", "type": "BIOLOGICAL", "armGroupLabels": ["Treatment"]},
        {"name": "Drug A", "type": "DRUG", "armGroupLabels": ["Treatment"]},
        {"name": "Placebo matched to Drug C", "type": "DRUG", "armGroupLabels": ["Treatment"]},
    ])
    assert components(build_tables([source])) == [["biologic b", "drug a"]]


@pytest.mark.parametrize("label", ["Drug A + placebo", "Drug A or placebo", "Placebo plus Drug A", "Drug A placebo"])
def test_mixed_active_and_control_names_are_flagged_not_erased(label):
    source = study(drugs=[{"name": label, "type": "DRUG", "armGroupLabels": ["Treatment"]}])
    tables = build_tables([source])
    assert tables["program_trials"].empty
    assert "ambiguous_active_control_label" in exclusion_reasons(tables)
    assert tables["interventions"].iloc[0]["name"] == label


def test_two_conditions_do_not_generate_speculative_program_cross_product():
    tables = build_tables([study(conditions=["Breast Cancer", "Lung Cancer"])])
    assert tables["program_trials"].empty
    assert exclusion_reasons(tables) == {"multiple_conditions"}
    assert len(tables["conditions"]) == 2
    assert len(tables["trials"]) == 1


def test_healthy_volunteer_label_is_not_treated_as_disease_indication():
    tables = build_tables([study(conditions=["Healthy Volunteers"])])
    assert tables["program_trials"].empty
    assert "healthy_volunteer_condition_not_indication" in exclusion_reasons(tables)


@pytest.mark.parametrize("name", ["Study Drug", "chemotherapy", "Investigational Product"])
def test_generic_labels_cannot_link_unrelated_molecules(name):
    source = study(drugs=[{"name": name, "type": "DRUG", "armGroupLabels": ["Treatment"]}])
    result = build_tables([source])
    assert result["program_trials"].empty
    assert "generic_intervention_name_requires_review" in exclusion_reasons(result)


def test_exact_duplicate_conditions_deduplicate_but_mesh_does_not_broaden_disease():
    source = study(conditions=["NSCLC", " nsclc "])
    source["derivedSection"] = {"conditionBrowseModule": {"meshes": [{"term": "Lung Neoplasms"}]}}
    tables = build_tables([source])
    assert tables["program_trials"].iloc[0]["indication_id"] == "nsclc"
    assert tables["conditions"].iloc[0]["mesh_terms_json"] == '["Lung Neoplasms"]'
    assert tables["trials"].iloc[0]["condition_count"] == 1


def test_greek_letters_and_punctuation_do_not_collide():
    sources = [study(nct=f"NCT{i:08d}", drugs=[{"name": name, "type": "DRUG", "armGroupLabels": ["Treatment"]}])
               for i, name in enumerate(["Interferon α", "Interferon β", "Drug-A", "Drug A"], start=1)]
    tables = build_tables(sources)
    assert tables["programs"]["program_id"].nunique() == 4
    assert label_key(" Interferon α  ") == "interferon α"
    assert label_key("Café") == label_key("Cafe\u0301")


@pytest.mark.parametrize("name", ["Drug A + Drug B", "Drug A/Drug B", "Drug A or Drug B"])
def test_embedded_combination_names_are_not_guessed_into_molecule_groups(name):
    source = study(drugs=[{"name": name, "type": "DRUG", "armGroupLabels": ["Treatment"]}])
    tables = build_tables([source])
    assert tables["program_trials"].empty
    assert "compound_intervention_name_requires_review" in exclusion_reasons(tables)
    assert tables["interventions"].iloc[0]["name"] == name


def test_other_names_export_candidates_without_automatic_alias_merge():
    first = study()
    first["protocolSection"]["armsInterventionsModule"]["interventions"][0]["otherNames"] = ["Brand A"]
    second = study(nct="NCT00000002", drugs=[{"name": "Brand A", "type": "DRUG", "armGroupLabels": ["Treatment"]}])
    tables = build_tables([first, second])
    assert len(tables["programs"]) == 2
    assert tables["alias_candidates"].iloc[0]["review_status"] == "not_applied_requires_review"
    assert tables["alias_candidates"].iloc[0]["alias_key"] == "brand a"


def test_unassigned_drug_in_multi_arm_trial_does_not_get_assigned_to_every_arm():
    source = study(
        arms=[{"label": "A", "type": "EXPERIMENTAL"}, {"label": "B", "type": "ACTIVE_COMPARATOR"}],
        drugs=[{"name": "Drug A", "type": "DRUG"}],
    )
    tables = build_tables([source])
    assert tables["program_trials"].empty
    assert "unassigned_intervention_multiarms" in exclusion_reasons(tables)


def test_reverse_arm_intervention_names_are_usable():
    source = study(
        arms=[{"label": "A", "type": "EXPERIMENTAL", "interventionNames": ["DRUG: Drug A"]},
              {"label": "B", "type": "ACTIVE_COMPARATOR", "interventionNames": ["DRUG: Drug B"]}],
        drugs=[{"name": "Drug A", "type": "DRUG"}, {"name": "Drug B", "type": "DRUG"}],
    )
    tables = build_tables([source])
    assert components(tables) == [["drug a"]]
    assert tables["program_trials"].iloc[0]["mapping_basis"] == "arm_intervention_names"


def test_conflicting_assignment_directions_fail_closed():
    source = study(
        arms=[{"label": "A", "type": "EXPERIMENTAL"},
              {"label": "B", "type": "ACTIVE_COMPARATOR", "interventionNames": ["DRUG: Drug A"]}],
        drugs=[{"name": "Drug A", "type": "DRUG", "armGroupLabels": ["A"]}],
    )
    tables = build_tables([source])
    assert tables["program_trials"].empty
    assert "inconsistent_arm_assignment" in exclusion_reasons(tables)


def test_unknown_arm_reference_is_not_ignored():
    source = study(drugs=[{"name": "Drug A", "type": "DRUG", "armGroupLabels": ["Typo"]}])
    assert "unknown_arm_assignment" in exclusion_reasons(build_tables([source]))


def test_one_explicit_arm_allows_missing_intervention_arm_labels():
    source = study(drugs=[{"name": "Drug A", "type": "DRUG"}])
    tables = build_tables([source])
    assert components(tables) == [["drug a"]]
    assert tables["program_trials"].iloc[0]["mapping_basis"] == "single_arm_fallback"


def test_no_arms_requires_explicit_single_group_design_for_fallback():
    source = study(arms=[], drugs=[{"name": "Drug A", "type": "DRUG"}])
    assert "missing_arm_groups" in exclusion_reasons(build_tables([source]))
    source["protocolSection"]["designModule"]["designInfo"]["interventionModel"] = "SINGLE_GROUP"
    tables = build_tables([source])
    assert components(tables) == [["drug a"]]
    assert tables["program_trials"].iloc[0]["mapping_basis"] == "single_group_design"


def test_non_drug_cointervention_is_explicitly_excluded():
    source = study(drugs=[
        {"name": "Drug A", "type": "DRUG", "armGroupLabels": ["Treatment"]},
        {"name": "Radiation", "type": "RADIATION", "armGroupLabels": ["Treatment"]},
    ])
    tables = build_tables([source])
    assert tables["program_trials"].empty
    assert "non_drug_cointervention" in exclusion_reasons(tables)


def test_partial_dates_remain_partial_not_guessed_first_day():
    source = study()
    status = source["protocolSection"]["statusModule"]
    status["completionDateStruct"] = {"date": "2012-02", "type": "ACTUAL"}
    status["resultsFirstPostDateStruct"] = {"date": "2013", "type": "ACTUAL"}
    status["lastUpdatePostDateStruct"] = {"date": "2020-02-31"}
    row = build_tables([source])["trials"].iloc[0]
    assert row["start_date"] == "2010-02-03" and row["start_date_type"] == "ACTUAL"
    assert row["start_date_precision"] == "day"
    assert row["completion_date"] == "2012-02" and row["completion_date_precision"] == "month"
    assert row["results_first_post_date"] == "2013" and row["results_first_post_date_precision"] == "year"
    assert row["last_update_post_date_precision"] == "invalid"
    assert row["primary_completion_date_precision"] == "missing"


@pytest.mark.parametrize("phases,expected", [(["EARLY_PHASE1"], "EARLY_PHASE1"),
    (["PHASE1", "PHASE2"], "PHASE1/PHASE2"), (["PHASE3", "PHASE2"], "PHASE2/PHASE3")])
def test_api_phase_arrays_and_early_phase1(phases, expected):
    source = study()
    source["protocolSection"]["designModule"]["phases"] = phases
    assert build_tables([source])["trials"].iloc[0]["phase"] == expected


def test_observational_record_is_preserved_but_excluded_from_bridge():
    source = study()
    source["protocolSection"]["designModule"]["studyType"] = "OBSERVATIONAL"
    tables = build_tables([source])
    assert len(tables["trials"]) == 1
    assert tables["program_trials"].empty
    assert "not_interventional" in exclusion_reasons(tables)


@pytest.mark.parametrize("nct", [None, "", "NCT1", "garbage"])
def test_invalid_source_identifier_fails_explicitly(nct):
    with pytest.raises(ValueError, match="missing or malformed nctId"):
        build_tables([study(nct=nct)])


def test_duplicate_source_trial_fails_explicitly():
    with pytest.raises(ValueError, match="Duplicate nctId"):
        build_tables([study(), study()])


def test_every_unmapped_trial_gets_reason_and_all_inputs_survive():
    sources = [study(), study("NCT00000002", drugs=[]), study("NCT00000003", conditions=[])]
    tables = build_tables(sources)
    downloaded = set(tables["trials"]["nct_id"])
    mapped = set(tables["program_trials"]["nct_id"])
    excluded = set(tables["exclusions"]["nct_id"])
    assert len(downloaded) == 3
    assert downloaded == mapped | excluded
    assert len(excluded) == 2


def test_output_schemas_survive_empty_cohort():
    tables = build_tables([])
    assert set(tables) == set(SCHEMAS)
    for name, columns in SCHEMAS.items():
        assert list(tables[name].columns) == columns
        assert tables[name].empty


def test_shared_component_regimens_have_one_transitive_drug_group():
    sources = []
    for i, names in enumerate([["Drug A"], ["Drug A", "Drug B"], ["Drug B"], ["Drug C"]], start=1):
        sources.append(study(nct=f"NCT{i:08d}", drugs=[{"name": name, "type": "DRUG", "armGroupLabels": ["Treatment"]} for name in names]))
    tables = build_tables(sources)
    bridge = tables["program_trials"].set_index("nct_id")
    assert bridge.loc["NCT00000001", "drug_group"] == bridge.loc["NCT00000003", "drug_group"]
    assert bridge.loc["NCT00000001", "drug_group"] != bridge.loc["NCT00000004", "drug_group"]


def test_source_and_intervention_order_do_not_change_programs():
    first = study(drugs=[{"name": name, "type": "DRUG", "armGroupLabels": ["Treatment"]} for name in ["Drug B", "Drug A", "Drug A"]])
    second = study(nct="NCT00000002")
    sources = [first, second]
    shuffled = copy.deepcopy(list(reversed(sources)))
    shuffled[1]["protocolSection"]["armsInterventionsModule"]["interventions"].reverse()
    original = build_tables(sources)
    reordered = build_tables(shuffled)
    pd.testing.assert_frame_equal(original["program_trials"], reordered["program_trials"])
    pd.testing.assert_frame_equal(original["programs"], reordered["programs"])


def test_placebo_only_arm_does_not_create_empty_program():
    tables = build_tables([study(drugs=[{"name": "placebo", "type": "DRUG", "armGroupLabels": ["Treatment"]}])])
    assert tables["programs"].empty
    assert "no_active_drug_in_experimental_arm" in exclusion_reasons(tables)
    assert control_kind("sham procedure") == "control"


def test_reviewed_nct05572515_alternative_regimens_are_not_pooled():
    alternate = "Pomalidomide, Bortezomib and Dexamethasone (PVd) or Carfilzomib and Dexamethasone (Kd)"
    source = study(
        nct="NCT05572515",
        arms=[{"label": "Teclistamab", "type": "EXPERIMENTAL"},
              {"label": alternate, "type": "EXPERIMENTAL",
               "description": "Participants will receive either PVd or Kd based on principal investigator's choice."}],
        drugs=[{"name": "Teclistamab", "type": "DRUG", "armGroupLabels": ["Teclistamab"]}]
        + [{"name": name, "type": "DRUG", "armGroupLabels": [alternate]}
           for name in ["Pomalidomide", "Bortezomib", "Dexamethasone", "Carfilzomib"]],
    )
    tables = build_tables([source])
    assert components(tables) == [["teclistamab"]]
    assert "alternative_regimens_in_arm_label" in exclusion_reasons(tables)
    assert "alternative_regimens_in_arm_description" in exclusion_reasons(tables)
    assert set(tables["exclusions"]["arm_label"]) == {alternate}
    assert len(tables["interventions"]) == 5


@pytest.mark.parametrize("label", ["Drug A versus Drug B", "Drug A vs. Drug B", "Drug A with/without Drug B"])
def test_explicit_alternative_arm_labels_require_review(label):
    source = study(arms=[{"label": label, "type": "EXPERIMENTAL"}],
                   drugs=[{"name": name, "type": "DRUG", "armGroupLabels": [label]} for name in ["Drug A", "Drug B"]])
    tables = build_tables([source])
    assert tables["program_trials"].empty
    assert "alternative_regimens_in_arm_label" in exclusion_reasons(tables)


def test_nct07336732_with_without_arm_is_not_false_monotherapy():
    label = "Andamertinib with or without platinum-based chemothsrapy versus platinum-based chemotherapy"
    source = study(nct="NCT07336732", arms=[{"label": label, "type": "EXPERIMENTAL"}],
                   drugs=[{"name": "PLB1004", "type": "DRUG", "description": label, "armGroupLabels": [label]}])
    tables = build_tables([source])
    assert tables["program_trials"].empty
    assert "alternative_regimens_in_arm_label" in exclusion_reasons(tables)
    assert tables["interventions"].iloc[0]["intervention_description"] == label


def test_description_regimen_alternatives_excluded_but_generic_narrative_or_allowed():
    source = study()
    arm = source["protocolSection"]["armsInterventionsModule"]["armGroups"][0]
    arm["description"] = "Drug A will be given until progression or unacceptable toxicity."
    assert components(build_tables([source])) == [["drug a"]]
    arm["description"] = "Drug A is given with or without chemotherapy."
    tables = build_tables([source])
    assert tables["program_trials"].empty
    assert "alternative_regimens_in_arm_description" in exclusion_reasons(tables)
    details = json.loads(tables["interventions"].iloc[0]["assigned_arm_details_json"])
    assert details[0]["description"] == arm["description"]


def test_reviewed_nct06281964_text_contradiction_excluded_with_evidence_not_permanent_blacklist():
    source = study(nct="NCT06281964",
                   arms=[{"label": "PLB1004", "type": "EXPERIMENTAL", "description": "PLB1004 given alone as monotherapy"}],
                   drugs=[{"name": "PLB1004", "type": "DRUG", "armGroupLabels": ["PLB1004"],
                           "description": "Participants receive PLB1004, pemetrexed and either carboplatin or cisplatin."}])
    tables = build_tables([source])
    assert tables["program_trials"].empty
    assert "reviewed_source_regimen_contradiction" in exclusion_reasons(tables)
    detail = tables["exclusions"].loc[tables["exclusions"].reason.eq("reviewed_source_regimen_contradiction"), "detail"].iloc[0]
    evidence = json.loads(detail)
    assert evidence["source_url"] == "https://clinicaltrials.gov/study/NCT06281964"
    assert evidence["reviewed_snapshot"] == "2026-11-19"
    # The same NCT is accepted if its source contradiction has actually been corrected.
    source["protocolSection"]["armsInterventionsModule"]["interventions"][0]["description"] = "PLB1004 monotherapy."
    corrected = build_tables([source])
    assert components(corrected) == [["plb1004"]]
    assert "reviewed_source_regimen_contradiction" not in exclusion_reasons(corrected)
