import pandas as pd

from phase_by_phase.clean import (
    PHASE_RANK,
    build_program_trials,
    normalize_drug_name,
    normalize_indication,
    normalize_phase,
    regimen_key,
)


def test_phase_normalization_and_ordering():
    assert normalize_phase("EARLY_PHASE1") == "EARLY_PHASE1"
    assert normalize_phase("Phase 1") == "PHASE1"
    assert normalize_phase("PHASE1/PHASE2") == "PHASE1/PHASE2"
    assert normalize_phase("Phase 2 / Phase 3") == "PHASE2/PHASE3"
    assert normalize_phase("Not Applicable") is None
    assert PHASE_RANK[normalize_phase("Phase 3")] == 3.0


def test_regimen_is_order_independent_and_drops_placebo():
    assert regimen_key(["Drug B", "Placebo", "drug-a", "Drug B"]) == "drug a+drug b"
    assert normalize_drug_name("PLACEBO matched to Drug A") is None


def test_indication_prefers_mesh_term():
    assert normalize_indication("NSCLC", "Lung Neoplasms") == "lung neoplasms"
    assert normalize_indication("Non-small cell lung cancer") == "non small cell lung cancer"


def test_program_bridge_flags_multi_indication_trials():
    rows = pd.DataFrame(
        {
            "nct_id": ["NCT1", "NCT1", "NCT1", "NCT2"],
            "drug_name": ["Drug A", "Drug B", "Placebo", "Drug C"],
            "condition_name": ["Condition X", "Condition X", "Condition Y", "Condition Z"],
            "mesh_term": ["Disease X", "Disease X", "Disease Y", None],
        }
    )
    bridge = build_program_trials(rows)

    nct1 = bridge[bridge["nct_id"] == "NCT1"]
    assert len(nct1) == 2
    assert set(nct1["regimen_id"]) == {"drug a+drug b"}
    assert nct1["ambiguous_mapping"].all()
    assert nct1["program_id"].nunique() == 2

    nct2 = bridge[bridge["nct_id"] == "NCT2"].iloc[0]
    assert nct2["indication_id"] == "condition z"
    assert not nct2["ambiguous_mapping"]


def test_program_ids_are_deterministic():
    rows = pd.DataFrame(
        {
            "nct_id": ["NCT9", "NCT9"],
            "drug_name": ["Drug A", "Drug B"],
            "condition_name": ["Condition X", "Condition X"],
        }
    )
    first = build_program_trials(rows)
    second = build_program_trials(rows.sample(frac=1, random_state=7))
    assert first.loc[0, "program_id"] == second.loc[0, "program_id"]
