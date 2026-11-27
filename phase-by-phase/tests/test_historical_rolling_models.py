"""Synthetic chronology and matched-cohort checks for rolling validation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import duckdb

from phase_by_phase import historical_dev_models as dev
from phase_by_phase import historical_rolling_models as rolling


def _rows() -> pd.DataFrame:
    dates = pd.to_datetime(["2015-06-01", "2015-07-01", "2016-04-01",
                            "2017-04-01", "2018-04-01", "2019-04-01"])
    return pd.DataFrame({"nct_id": [f"NCT{i:08d}" for i in range(len(dates))],
                         "first_public_date": dates,
                         "completion_label": [1, 0, 1, 0, 1, 0],
                         "completion_label_date": pd.to_datetime([
                             "2018-03-01", "2015-12-01", "2017-08-01",
                             "2018-08-01", "2020-08-01", "2021-08-01"]),
                         "significance_label": [1, np.nan, 0, np.nan, 1, np.nan],
                         "significance_label_date": pd.to_datetime([
                             "2018-04-01", None, "2017-09-01", None, "2020-09-01", None]),
                         "reversal_date": pd.to_datetime([None] * len(dates)),
                         "pure_phase": "PHASE2", "arm_row_count": 2})


def test_2015_label_posted_2018_only_enters_2019_training():
    rows = _rows()
    late = rows.nct_id.iloc[0]
    for year in (2016, 2017):
        train, valid = rolling.fold_rows(rows, year, "completion")
        assert late in set(train.nct_id)
        assert pd.isna(train.set_index("nct_id").loc[late, "fold_label"])
        assert not set(train.nct_id) & set(valid.nct_id)
    train, _ = rolling.fold_rows(rows, 2019, "completion")
    assert train.set_index("nct_id").loc[late, "fold_label"] == 1


def test_significance_date_and_reversal_are_as_of_each_fold():
    rows = _rows()
    rows.loc[0, "reversal_date"] = pd.Timestamp("2019-06-01")
    train, _ = rolling.fold_rows(rows, 2019, "reported_primary_p_lt_0_05")
    assert train.loc[train.nct_id == rows.nct_id.iloc[0], "fold_label"].iloc[0] == 1
    # A reversal in June 2019 cannot retroactively erase a January 2019
    # training label, but is observable by the fixed 2024 validation cutoff.
    label = rolling.known_as_of(rows.iloc[[0]], "completion", pd.Timestamp("2024-01-01"))
    assert pd.isna(label.iloc[0])
    rows.loc[0, "reversal_date"] = pd.Timestamp("2018-12-31")
    train, _ = rolling.fold_rows(rows, 2019, "reported_primary_p_lt_0_05")
    assert pd.isna(train.loc[train.nct_id == rows.nct_id.iloc[0], "fold_label"].iloc[0])


def test_first_event_not_replaced_by_later_event_after_cutoff():
    rows = _rows().iloc[[0]].copy()
    # The selected first event is in 2018. A later favorable event in 2015
    # would be a chronology error, not a substitute for the first event.
    assert pd.isna(rolling.known_as_of(rows, "completion", pd.Timestamp("2017-01-01")).iloc[0])
    assert rolling.known_as_of(rows, "completion", pd.Timestamp("2019-01-01")).iloc[0] == 1


def test_sql_selects_first_terminal_before_fold_filter_and_keeps_reversal_date(tmp_path):
    design = tmp_path / "design.parquet"
    results = tmp_path / "results"
    results.mkdir()
    pd.DataFrame({"nct_id": ["NCT00000001"], "first_public_nct_version": [1],
                  "first_public_date": pd.to_datetime(["2015-01-01"]),
                  "first_public_core_is_obsolete": [False],
                  "archive_left_truncated": [False],
                  "drug_intervention_count": [1], "phase_membership": ["PHASE2"]
                  }).to_parquet(design, index=False)
    core = pd.DataFrame({"nct_id": ["NCT00000001"] * 3,
                         "nct_version": [1, 2, 3],
                         "post_date": pd.to_datetime(["2015-01-01", "2018-03-01", "2019-06-01"]),
                         "is_obsolete": [False] * 3,
                         "overall_status": ["RECRUITING", "COMPLETED", "RECRUITING"],
                         "completion_date": pd.to_datetime([None, "2018-02-01", None]),
                         "completion_date_type": [None, "ACTUAL", None],
                         "completion_date_precision": [None, "day", None],
                         "results_first_post_date": pd.to_datetime([None] * 3)})
    pd.DataFrame({"nct_id": pd.Series(dtype="str"),
                  "nct_version": pd.Series(dtype="int64"),
                  "outcome_ord": pd.Series(dtype="int64"),
                  "type": pd.Series(dtype="str"),
                  "is_obsolete": pd.Series(dtype="bool"),
                  "adapter_version_public_date": pd.Series(dtype="datetime64[ns]")
                  }).to_parquet(results / "results_outcome_measures_clean.parquet", index=False)
    pd.DataFrame({"nct_id": pd.Series(dtype="str"),
                  "nct_version": pd.Series(dtype="int64"),
                  "outcome_ord": pd.Series(dtype="int64"),
                  "analysis_ord": pd.Series(dtype="int64"),
                  "p_value": pd.Series(dtype="str"),
                  "p_value_comment": pd.Series(dtype="str"),
                  "is_obsolete": pd.Series(dtype="bool"),
                  "adapter_version_public_date": pd.Series(dtype="datetime64[ns]")
                  }).to_parquet(results / "results_outcome_analyses_clean.parquet", index=False)
    con = duckdb.connect()
    con.register("dev_core", core)
    rows = dev.build_labels(con, design, results, rolling=True)
    assert len(rows) == 1
    assert pd.Timestamp(rows.completion_label_date.iloc[0]) == pd.Timestamp("2018-03-01")
    assert pd.Timestamp(rows.reversal_date.iloc[0]) == pd.Timestamp("2019-06-01")
    assert pd.isna(rolling.known_as_of(rows, "completion", pd.Timestamp("2017-01-01")).iloc[0])
    assert rolling.known_as_of(rows, "completion", pd.Timestamp("2019-01-01")).iloc[0] == 1
    assert pd.isna(rolling.known_as_of(rows, "completion", pd.Timestamp("2020-01-01")).iloc[0])


def test_score_fold_same_ncts_for_all_models(monkeypatch):
    monkeypatch.setattr(dev, "MIN_TRAIN", 10)
    monkeypatch.setattr(dev, "MIN_VALID", 5)
    monkeypatch.setattr(dev, "MIN_CLASS", 2)
    n = 30
    frame = pd.DataFrame(index=range(n))
    for name in dev.NUM:
        frame[name] = np.arange(n, dtype=float) % 7
    for name in dev.CAT:
        frame[name] = "A"
    for name in dev.FLAGS:
        frame[name] = 0
    frame["arm_row_count"] = 2
    frame["nct_id"] = [f"NCT{i:08d}" for i in range(n)]
    frame["pure_phase"] = "PHASE2"
    frame["first_public_date"] = pd.to_datetime(["2015-01-01"] * 20 + ["2016-01-01"] * 10)
    frame["fold_label"] = [i % 2 for i in range(n)]
    metrics, predictions = rolling.score_fold(frame.iloc[:20], frame.iloc[20:], 2016, "completion")
    broad = pd.concat(predictions).query("subset == 'broad' and phase == 'PHASE2'")
    assert set(broad.model) == {"prevalence", "random_forest", "hist_gradient_boosting"}
    assert all(set(group.nct_id) == set(frame.iloc[20:].nct_id)
               for _, group in broad.groupby("model"))
    assert any(m["model"] == "random_forest" and m["estimable"] for m in metrics)
