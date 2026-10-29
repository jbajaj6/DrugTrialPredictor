"""Write a tiny fake AACT flat-file dump (pipe-delimited) for smoke tests. Not real data."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def write_fake_aact(out: Path, n: int = 600, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    out.mkdir(parents=True, exist_ok=True)
    ids = [f"NCT{10_000_000 + i:08d}" for i in range(n)]
    years = rng.integers(2003, 2022, n)  # some fall outside 2005-2019 and should be filtered
    industry = rng.random(n) < 0.5
    phase = rng.choice(["PHASE1", "PHASE2", "PHASE3", "PHASE4", "PHASE1/PHASE2"], n)
    # completion depends a bit on sponsor + phase so models have signal to find
    p_complete = 0.75 + 0.1 * industry - 0.05 * (phase == "PHASE1")
    status = np.where(rng.random(n) < p_complete, "COMPLETED",
                      rng.choice(["TERMINATED", "WITHDRAWN"], n))
    status[:5] = "RECRUITING"  # non-final, should be dropped

    studies = pd.DataFrame({
        "nct_id": ids,
        "study_type": np.where(np.arange(n) % 50 == 7, "OBSERVATIONAL", "INTERVENTIONAL"),
        "overall_status": status,
        "phase": phase,
        "start_date": [f"{y}-0{rng.integers(1, 10)}-15" for y in years],
        "study_first_submitted_date": [f"{y}-01-01" for y in years],
        "number_of_arms": rng.integers(1, 5, n),
        "has_dmc": rng.choice(["t", "f", ""], n),
        "enrollment": rng.integers(0, 500, n),
        "enrollment_type": "ACTUAL",
        "why_stopped": "",
    })
    designs = pd.DataFrame({
        "nct_id": ids,
        "allocation": rng.choice(["RANDOMIZED", "NON_RANDOMIZED", "NA"], n),
        "intervention_model": rng.choice(["PARALLEL", "SINGLE_GROUP", "CROSSOVER"], n),
        "masking": rng.choice(["NONE", "DOUBLE", "QUADRUPLE"], n),
        "primary_purpose": rng.choice(["TREATMENT", "PREVENTION"], n),
    })
    sponsors = pd.concat([
        pd.DataFrame({"nct_id": ids, "agency_class": np.where(industry, "INDUSTRY", "OTHER"),
                      "lead_or_collaborator": "lead", "name": "Sponsor"}),
        pd.DataFrame({"nct_id": ids[::3], "agency_class": "NIH",
                      "lead_or_collaborator": "collaborator", "name": "NCI"}),
    ])
    facilities = pd.DataFrame({"nct_id": np.repeat(ids, 2), "id": range(2 * n)})
    countries = pd.DataFrame({"nct_id": ids, "name": rng.choice(["United States", "France"], n), "removed": "f"})
    browse = pd.DataFrame({"nct_id": ids, "mesh_term": rng.choice(["Neoplasms", "Diabetes Mellitus", "Asthma"], n),
                           "mesh_type": "mesh-list"})
    interventions = pd.DataFrame({
        "nct_id": ids,
        "intervention_type": np.where(np.arange(n) % 40 == 3, "DEVICE", "DRUG"),
        "name": rng.choice(["Pembrolizumab 200 mg", "ABC-123", "Metformin tablets"], n),
    })
    elig = pd.DataFrame({
        "nct_id": ids, "gender": "ALL", "healthy_volunteers": "f",
        "criteria": np.where(rng.random(n) < 0.3,
                             "Inclusion Criteria: - HER2 positive - age > 18 Exclusion Criteria: - pregnancy",
                             "Inclusion Criteria: - adults Exclusion Criteria: - none"),
    })
    outcomes = pd.DataFrame({"id": range(n), "nct_id": ids, "outcome_type": "PRIMARY"})
    has_res = rng.random(n) < 0.6
    oa = pd.DataFrame({"outcome_id": np.arange(n)[has_res], "nct_id": np.array(ids)[has_res],
                       "p_value": rng.uniform(0, 0.3, has_res.sum()).round(4)})

    for name, df in {
        "studies": studies, "designs": designs, "sponsors": sponsors, "facilities": facilities,
        "countries": countries, "browse_conditions": browse, "interventions": interventions,
        "eligibilities": elig, "outcomes": outcomes, "outcome_analyses": oa,
    }.items():
        df.to_csv(out / f"{name}.txt", sep="|", index=False)
    return out
