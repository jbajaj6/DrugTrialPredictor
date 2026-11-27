"""Synthetic guardrails for the development-only historical baseline."""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest

import phase_by_phase.historical_dev_models as dev
from phase_by_phase.historical_dev_models import (
    FEATURES, FLAGS, _source_view, assert_unique, label_by_cutoff,
    make_preprocessor, p_label, phase, verify_core_parts,
)


def test_phase_is_pure_and_mixed_is_not_duplicated():
    assert phase("PHASE2") == "PHASE2"
    assert phase("PHASE 3") == "PHASE3"
    assert phase("PHASE1|PHASE2") is None
    assert phase(None) is None


def test_primary_p_threshold_bounds_and_unknowns():
    assert p_label("0.049") == 1
    assert p_label("0.05") == 0
    assert p_label("<0.001") == 1
    assert p_label("<.0001") == 1
    assert p_label("<=0.01") == 1
    assert p_label("<0.1") is None
    assert p_label("<=0.05") is None
    assert p_label(">0.05") == 0
    assert p_label(">=0.05") == 0
    assert p_label(">0.01") is None
    assert p_label(None) is None
    assert p_label("0.01", "adjusted? unclear") is None


def test_chronology_cutoffs():
    assert label_by_cutoff("2010-01-01", "2015-12-31", "train")
    assert not label_by_cutoff("2010-01-01", "2016-01-01", "train")
    assert not label_by_cutoff("2010-01-01", "2010-01-01", "train")
    assert label_by_cutoff("2018-01-01", "2023-12-31", "validation")
    assert not label_by_cutoff("2018-01-01", "2024-01-01", "validation")


def test_feature_whitelist_excludes_outcomes_and_ids():
    forbidden = {"nct_id", "first_public_date", "lead_sponsor_name", "overall_status",
                 "completion_date", "p_value", "results_first_post_date",
                 "actual_enrollment", "adapter_core_source_file"}
    assert not forbidden.intersection(FEATURES)


def test_preprocessing_only_learns_training_categories():
    frame = pd.DataFrame({name: [1, np.nan] for name in FEATURES})
    for name in ("study_type", "allocation", "intervention_model", "primary_purpose",
                 "masking", "lead_sponsor_class", "phase_membership"):
        frame[name] = ["TRAIN_ONLY", "UNSEEN_VALIDATION"]
    train = frame.iloc[:1]
    valid = frame.iloc[1:]
    prep = make_preprocessor().fit(train)
    before = prep.transform(train)
    after = prep.transform(valid)
    assert before.shape == after.shape
    assert before.shape[1] > 0


def test_sealed_core_status_not_materialized(tmp_path):
    core = tmp_path / "core"
    core.mkdir()
    pd.DataFrame({"nct_id": ["OLD", "SEALED"], "nct_version": [0, 1],
                  "last_update_post_date": pd.to_datetime(["2023-12-31", "2024-01-01"]),
                  "is_obsolete": [False, False],
                  "overall_status": ["COMPLETED", "SEALED_SENTINEL"],
                  "completion_date": pd.to_datetime(["2023-01-01", "2024-01-01"]),
                  "completion_date_type": ["ACTUAL", "ACTUAL"],
                  "completion_date_precision": ["day", "day"],
                  "results_first_post_date": pd.to_datetime(["2023-01-01", "2024-01-01"]),
                  }).to_parquet(core / "part.parquet", index=False)
    con = duckdb.connect()
    _source_view(con, tmp_path)
    assert con.execute("SELECT nct_id FROM dev_core").fetchall() == [("OLD",)]
    assert con.execute("SELECT count(*) FROM dev_core WHERE overall_status='SEALED_SENTINEL'").fetchone()[0] == 0


def _synthetic_features(n: int) -> pd.DataFrame:
    frame = pd.DataFrame(index=range(n))
    for name in dev.NUM:
        frame[name] = np.arange(n, dtype=float) % 7
    for name in dev.CAT:
        frame[name] = ["A" if i % 2 else "B" for i in range(n)]
    for name in FLAGS:
        frame[name] = pd.Series([i % 3 == 0 for i in range(n)], dtype=bool)
    frame["arm_row_count"] = [0 if i % 5 == 0 else 2 for i in range(n)]
    frame["nct_id"] = [f"NCT{i:08d}" for i in range(n)]
    frame["pure_phase"] = "PHASE2"
    frame["split"] = ["train" if i < n * 2 // 3 else "validation" for i in range(n)]
    frame["completion_label"] = [i % 2 for i in range(n)]
    frame["significance_label"] = np.nan
    return frame


def test_both_models_fit_boolean_flags_without_dropping_rows():
    frame = _synthetic_features(45)
    train, valid = frame.iloc[:30], frame.iloc[30:]
    for name in ("random_forest", "hist_gradient_boosting"):
        predictor = dev.model(name)
        predictor.fit(train[list(FEATURES)].assign(**{
            flag: train[flag].astype("int8") for flag in FLAGS
        }), train.completion_label)
        probs = predictor.predict_proba(valid[list(FEATURES)].assign(**{
            flag: valid[flag].astype("int8") for flag in FLAGS
        }))[:, 1]
        assert len(probs) == len(valid)
        assert np.isfinite(probs).all()


def test_arm_ablation_uses_same_validation_ids(monkeypatch):
    monkeypatch.setattr(dev, "MIN_TRAIN", 30)
    monkeypatch.setattr(dev, "MIN_VALID", 15)
    monkeypatch.setattr(dev, "MIN_CLASS", 5)
    rows = _synthetic_features(90)
    metrics, predictions = dev.score_cells(rows)
    arm = predictions[(predictions.subset == "arm_rich") &
                      (predictions.model == "random_forest")]
    full = set(arm[arm.feature_set == "all_design"].nct_id)
    ablated = set(arm[arm.feature_set == "without_arm_features"].nct_id)
    assert full == ablated and len(full) > 0
    assert any(m["subset"] == "broad" and m["estimable"] for m in metrics)
    assert rows["arm_rows_missing"].dtype == bool  # caller data was not mutated


def test_missing_flag_and_duplicate_model_keys_fail_closed():
    rows = _synthetic_features(6)
    rows[FLAGS[0]] = rows[FLAGS[0]].astype(object)
    rows.loc[0, FLAGS[0]] = None
    with pytest.raises(ValueError, match="Missing Boolean flag"):
        dev.score_cells(rows)
    rows = _synthetic_features(6)
    rows.loc[1, "nct_id"] = rows.loc[0, "nct_id"]
    with pytest.raises(ValueError, match="Duplicate one-NCT"):
        dev.score_cells(rows)


def test_core_part_set_and_duplicate_source_keys_fail_closed(tmp_path):
    part = tmp_path / "part.parquet"
    part.write_bytes(b"source")
    expected = {"core/part.parquet": dev.digest(part)}
    verify_core_parts([part], expected)
    with pytest.raises(ValueError, match="part-set"):
        verify_core_parts([], expected)
    extra = tmp_path / "extra.parquet"
    extra.write_bytes(b"extra")
    with pytest.raises(ValueError, match="part-set"):
        verify_core_parts([part, extra], expected)
    con = duckdb.connect()
    con.execute("CREATE TABLE design(nct_id VARCHAR, nct_version INTEGER)")
    con.execute("INSERT INTO design VALUES ('NCT1',0),('NCT1',1)")
    with pytest.raises(ValueError, match="Duplicate design"):
        assert_unique(con, "design", ("nct_id",))
