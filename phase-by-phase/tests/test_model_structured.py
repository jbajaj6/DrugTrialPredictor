import numpy as np
import pandas as pd
import pytest

from phase_by_phase.model_structured import development_evaluation


def _fixture(n_train=120, n_val=40, n_holdout=10, with_evidence=False):
    n = n_train + n_val + n_holdout
    years = (["2010-01-01"] * n_train + ["2021-01-01"] * n_val +
             ["2024-01-01"] * n_holdout)
    available = (["2019-01-01"] * n_train + ["2023-01-01"] * n_val +
                 ["2025-01-01"] * n_holdout)
    rows = pd.DataFrame({
        "nct_id": [f"NCT{i:08d}" for i in range(n)],
        "program_id": [f"p{i}" for i in range(n)],
        "phase": "PHASE2", "prediction_date": years,
        "completion_label": [bool(i % 2) for i in range(n)],
        "significance_label": [bool(i % 2) for i in range(n)],
        "completion_label_available_date": available,
        "significance_label_available_date": available,
        "historical_design_verified": False,
        "arm_count": 2, "sponsor_class": "INDUSTRY",
        "allocation": "RANDOMIZED", "masking": "DOUBLE",
        "prior_result_count": int(with_evidence),
        "prior_primary_analysis_count": int(with_evidence),
        "prior_primary_tested_count": int(with_evidence),
        "prior_primary_significant_count": int(with_evidence),
        "prior_flow_retention_mean": np.nan,
        "prior_sae_max_rate_mean": np.nan,
    })
    bridge = pd.DataFrame({"program_id": rows.program_id,
                           "drug_group": [f"g{i}" for i in range(n)]})
    return rows, bridge


def test_development_only_and_sealed_holdout():
    rows, bridge = _fixture()
    report = development_evaluation(rows, bridge)
    assert report["split"]["final_holdout_sealed"] is True
    task = report["tasks"]["PHASE2:completion"]
    assert task["status"] == "development_only"
    assert task["counts"]["sealed_rows_2024_onward"] == 10
    assert task["design_forest"]["n"] == 40
    assert task["matched_evidence_comparison"]["status"] == "not_estimable"


def test_matched_comparison_uses_same_rows():
    rows, bridge = _fixture(n_train=120, n_val=40, with_evidence=True)
    report = development_evaluation(rows, bridge)
    matched = report["tasks"]["PHASE2:completion"]["matched_evidence_comparison"]
    assert matched["status"] == "development_only"
    assert matched["design"]["n"] == matched["design_plus_earlier"]["n"] == 40


def test_group_overlap_purged_and_bad_schema_rejected():
    rows, bridge = _fixture()
    bridge.loc[120:159, "drug_group"] = bridge.loc[0:39, "drug_group"].to_numpy()
    report = development_evaluation(rows, bridge)
    assert report["tasks"]["PHASE2:completion"]["counts"]["validation_rows"] == 0
    with pytest.raises(ValueError, match="Missing prediction columns"):
        development_evaluation(rows.drop(columns="arm_count"), bridge)


def test_sealed_label_dates_are_not_parsed():
    class SealedDate:
        def __str__(self):
            raise AssertionError("sealed label availability was parsed")

    rows, bridge = _fixture()
    rows.loc[160:, "completion_label_available_date"] = [SealedDate()] * 10
    rows.loc[160:, "significance_label_available_date"] = [SealedDate()] * 10
    report = development_evaluation(rows, bridge)
    assert report["tasks"]["PHASE2:completion"]["counts"]["sealed_rows_2024_onward"] == 10
