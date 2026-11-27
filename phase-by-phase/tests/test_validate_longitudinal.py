import numpy as np
import pandas as pd
import pytest

from phase_by_phase.validate_longitudinal import longitudinal_evaluation


def _fixture(n_train=120, n_val=40, n_sealed=5):
    n = n_train + n_val + n_sealed
    rows = pd.DataFrame({
        "nct_id": [f"NCT{i:08d}" for i in range(n)],
        "program_id": [f"program-{i}" for i in range(n)],
        "phase": "PHASE2",
        "prediction_date": (["2010-01-01"] * n_train + ["2021-01-01"] * n_val +
                            ["2024-01-01"] * n_sealed),
        "completion_label": [bool(i % 2) for i in range(n)],
        "completion_label_available_date": (["2019-01-01"] * n_train +
                                            ["2021-12-01"] * n_val + ["2025-01-01"] * n_sealed),
        "significance_label": [None] * n,
        "significance_label_available_date": [None] * n,
        "historical_design_verified": False,
        "arm_count": 2,
        "sponsor_class": "INDUSTRY",
        "allocation": "RANDOMIZED",
        "masking": "DOUBLE",
        "prior_result_count": 0,
        "prior_primary_analysis_count": 0,
        "prior_primary_tested_count": 0,
        "prior_primary_significant_count": 0,
        "prior_flow_retention_mean": np.nan,
        "prior_sae_max_rate_mean": np.nan,
        "max_evidence_date": None,
    })
    bridge = pd.DataFrame({"program_id": rows.program_id,
                           "drug_group": [f"drug-{i}" for i in range(n)]})
    return rows, bridge


def test_rolling_origin_maturity_and_support():
    rows, bridge = _fixture()
    report = longitudinal_evaluation(rows, bridge)
    assert report["sealed_rows_2024_onward"] == 5
    assert len(report["folds"]) == 4 * 3 * 2
    fold = next(item for item in report["folds"] if item["phase"] == "PHASE2" and
                item["task"] == "completion" and item["window_start"] == "2020-01-01")
    assert fold["status"] == "development_only"
    assert fold["counts"]["train"] == 120
    assert fold["counts"]["validation"] == 40
    assert fold["identity_overlap_after_purge"] == 0
    assert fold["feature_support"]["train"]["rows_with_any_observed_design"] == 0
    assert fold["feature_support"]["validation"]["rows_with_any_observed_design"] == 0
    assert fold["model_input_status"] == "calendar_only_no_observed_design_in_training"
    # 2018 origin cannot use labels that only became public in 2019.
    early = next(item for item in report["folds"] if item["phase"] == "PHASE2" and
                 item["task"] == "completion" and item["window_start"] == "2018-01-01")
    assert early["counts"]["train"] == 0
    assert early["status"] == "not_estimable"


def test_identity_purge_and_future_evidence_fail_closed():
    rows, bridge = _fixture()
    bridge.loc[120:159, "drug_group"] = bridge.loc[0:39, "drug_group"].to_numpy()
    report = longitudinal_evaluation(rows, bridge)
    fold = next(item for item in report["folds"] if item["phase"] == "PHASE2" and
                item["task"] == "completion" and item["window_start"] == "2020-01-01")
    assert fold["counts"]["validation_purged_identity"] == 40
    assert fold["counts"]["validation"] == 0
    rows.loc[0, "prior_result_count"] = 1
    rows.loc[0, "max_evidence_date"] = "2011-01-01"
    with pytest.raises(ValueError, match="Earlier-trial evidence"):
        longitudinal_evaluation(rows, bridge)


def test_sealed_outcome_columns_never_accessed():
    class Sealed:
        def __str__(self):
            raise AssertionError("sealed outcome accessed")

        def __eq__(self, other):
            raise AssertionError("sealed outcome compared")

    rows, bridge = _fixture()
    for column in ("completion_label", "completion_label_available_date",
                   "significance_label", "significance_label_available_date",
                   "max_evidence_date"):
        rows[column] = rows[column].astype(object)
        rows.loc[160:, column] = [Sealed()] * 5
    report = longitudinal_evaluation(rows, bridge)
    assert report["sealed_rows_2024_onward"] == 5


@pytest.mark.parametrize("available", ["2020-01-01", "2021-01-01"])
def test_label_not_after_prediction_is_rejected(available):
    rows, bridge = _fixture()
    rows.loc[120, "completion_label_available_date"] = available
    with pytest.raises(ValueError, match="not after prediction"):
        longitudinal_evaluation(rows, bridge)


def test_rolling_report_separates_verified_and_observed_design():
    rows, bridge = _fixture()
    rows.loc[:119, "historical_design_verified"] = True
    rows.loc[:119, ["arm_count", "sponsor_class", "allocation", "masking"]] = np.nan
    report = longitudinal_evaluation(rows, bridge)
    fold = next(item for item in report["folds"] if item["phase"] == "PHASE2" and
                item["task"] == "completion" and item["window_start"] == "2020-01-01")
    assert fold["feature_support"]["train"]["historical_design_verified_rows"] == 120
    assert fold["feature_support"]["train"]["rows_with_any_observed_design"] == 0
    assert fold["model_input_status"] == "calendar_only_no_observed_design_in_training"
