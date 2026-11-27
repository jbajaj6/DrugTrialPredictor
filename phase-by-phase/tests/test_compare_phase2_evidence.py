import json

import pandas as pd
import pytest

from phase_by_phase.compare_phase2_evidence import build_rows, evaluate, load_development_sources


def _fixtures():
    targets = pd.DataFrame({
        "nct_id": ["NCT00000002", "NCT00000003", "NCT00000004"],
        "phase_stratum": ["PHASE2"] * 3,
        "first_post_date": ["2020-01-01", "2020-01-01", "2024-01-01"],
        "start_date": ["2020-01-01", "2020-01-01", "2024-01-01"],
        "qualifier_aware_significance_label": [1, 0, 1],
        "qualifier_aware_significance_available_date": ["2022-01-01", "2022-01-01", "2025-01-01"],
        "prospective_at_checkpoint": [True] * 3,
    })
    trials = pd.DataFrame({
        "nct_id": ["NCT00000001", "NCT00000005", "NCT00000006", "NCT00000007", "NCT00000008", "NCT00000002", "NCT00000003"],
        "phase": ["PHASE1"] * 5 + ["PHASE2"] * 2,
        "primary_completion_date": ["2019-12-01"] * 5 + ["2021-01-01"] * 2,
        "primary_completion_date_precision": ["day"] * 7,
        "primary_completion_date_type": ["ACTUAL"] * 7,
        "results_first_post_date": ["2020-07-18", "2020-07-19", "2020-07-20", "2020-07-19", None, "2022-01-01", "2022-01-01"],
        "results_first_post_date_precision": ["day"] * 4 + ["invalid"] + ["day"] * 2,
        "last_update_post_date": ["2020-07-18", "2020-07-19", "2020-07-20", "2021-01-01", None, "2022-01-01", "2022-01-01"],
    })
    links = pd.DataFrame({
        "nct_id": ["NCT00000002", *trials.nct_id.iloc[:5]],
        "program_id": ["p1"] * 6,
        "drug_group": ["g1"] * 6,
    })
    analyses = pd.DataFrame({"nct_id": trials.nct_id.iloc[:5],
                             "outcome_type": ["PRIMARY"] * 5,
                             "p_significant_005": [True, False, True, True, None]})
    return targets, trials, links, analyses


def test_proxy_boundary_and_future_result_exclusion():
    targets, trials, links, analyses = _fixtures()
    rows, audit = build_rows(targets, trials, links, analyses)
    assert len(rows) == 2  # 2024+ target is sealed before labels are touched.
    row = rows.set_index("nct_id").loc["NCT00000002"]
    assert row.public_prior_result_count == 0
    assert row.target_timing_verified
    assert row.proxy_prior_result_count == 2
    assert row.proxy_prior_primary_tested_count == 2
    assert row.proxy_prior_primary_significant_count == 1
    assert set(json.loads(row.proxy_only_prior_nct_ids_json)) == {"NCT00000001", "NCT00000005"}
    assert audit["excluded_current_result_revision_after_window"] == 1
    assert audit["excluded_missing_or_inexact_source_date"] == 1
    assert audit["historical_warning"]
    assert evaluate(rows, links)["status"] == "not_estimable"


def test_public_and_actual_completion_gate():
    targets, trials, links, analyses = _fixtures()
    trials.loc[0, ["results_first_post_date", "last_update_post_date"]] = "2019-12-20"
    trials.loc[1, "primary_completion_date"] = "2020-01-02"
    rows, _ = build_rows(targets, trials, links, analyses)
    row = rows.iloc[0]
    assert row.public_prior_result_count == 1
    assert row.proxy_prior_result_count == 1
    assert json.loads(row.public_prior_nct_ids_json) == ["NCT00000001"]
    trials.loc[0, "primary_completion_date_type"] = "ESTIMATED"
    rows, _ = build_rows(targets, trials, links, analyses)
    assert rows.iloc[0].public_prior_result_count == 0


def test_unknown_result_not_negative_and_duplicate_link_rejected():
    targets, trials, links, analyses = _fixtures()
    analyses.loc[0, "p_significant_005"] = None
    rows, _ = build_rows(targets, trials, links, analyses)
    assert rows.iloc[0].proxy_prior_result_count == 2
    assert rows.iloc[0].proxy_prior_primary_tested_count == 1
    repeated, audit = build_rows(targets, trials, pd.concat([links, links.iloc[[0]]]), analyses)
    assert len(repeated) == 2
    assert audit["duplicate_identical_candidate_links_collapsed"] == 1
    conflicting = pd.concat([links, links.iloc[[0]].assign(drug_group="g2")])
    with pytest.raises(ValueError, match="Conflicting candidate"):
        build_rows(targets, trials, conflicting, analyses)


def test_label_and_holdout_firewall():
    targets, trials, links, analyses = _fixtures()
    targets.loc[0, "qualifier_aware_significance_available_date"] = "2020-01-01"
    with pytest.raises(ValueError, match="on/before"):
        build_rows(targets, trials, links, analyses)
    targets.loc[0, "qualifier_aware_significance_available_date"] = "2022-01-01"
    class Sealed:
        def __str__(self):
            raise AssertionError("Sealed label inspected")
    targets["qualifier_aware_significance_label"] = targets.qualifier_aware_significance_label.astype(object)
    targets.at[2, "qualifier_aware_significance_label"] = Sealed()
    targets.at[2, "qualifier_aware_significance_available_date"] = Sealed()
    rows, _ = build_rows(targets, trials, links, analyses)
    assert len(rows) == 2
    rows.loc[0, "checkpoint"] = "2024-01-01"
    with pytest.raises(ValueError, match="Sealed holdout"):
        evaluate(rows, links)


def test_target_own_primary_completion_must_follow_checkpoint():
    targets, trials, links, analyses = _fixtures()
    trials.loc[trials.nct_id.eq("NCT00000002"), "primary_completion_date"] = "2019-12-31"
    rows, audit = build_rows(targets, trials, links, analyses)
    assert not rows.loc[rows.nct_id.eq("NCT00000002"), "target_timing_verified"].iloc[0]
    assert audit["labeled_target_timing_verified"] == 1


def test_month_only_completion_uses_interval_not_imputed_day():
    targets, trials, links, analyses = _fixtures()
    trials.loc[trials.nct_id.eq("NCT00000002"), "primary_completion_date"] = "2020-02"
    trials.loc[trials.nct_id.eq("NCT00000002"), "primary_completion_date_precision"] = "month"
    trials.loc[trials.nct_id.eq("NCT00000001"), "primary_completion_date"] = "2019-12"
    trials.loc[trials.nct_id.eq("NCT00000001"), "primary_completion_date_precision"] = "month"
    rows, audit = build_rows(targets, trials, links, analyses)
    assert rows.iloc[0].target_timing_verified
    assert rows.iloc[0].proxy_prior_result_count == 2
    assert audit["target_timing_verified_safe_month"] == 1
    assert audit["eligible_phase1_month_completion_candidates"] >= 1
    # Same-month outcome and checkpoint overlap: order cannot be certified.
    trials.loc[trials.nct_id.eq("NCT00000002"), "primary_completion_date"] = "2020-01"
    trials.loc[trials.nct_id.eq("NCT00000001"), "primary_completion_date"] = "2020-01"
    rows, _ = build_rows(targets, trials, links, analyses)
    assert not rows.iloc[0].target_timing_verified
    assert "NCT00000001" not in json.loads(rows.iloc[0].proxy_only_prior_nct_ids_json)


def test_paired_development_uses_identical_target_cohort():
    train_n, val_n = 120, 40
    n = train_n + val_n
    rows = pd.DataFrame({
        "nct_id": [f"NCT{i:08d}" for i in range(n)],
        "checkpoint": ["2010-01-01"] * train_n + ["2017-01-01"] * val_n,
        "label": [i % 2 for i in range(n)],
        "label_available": ["2015-01-01"] * train_n + ["2023-01-01"] * val_n,
        "target_timing_verified": [True] * n,
        "public_prior_result_count": [0] * n,
        "public_prior_primary_tested_count": [0] * n,
        "public_prior_primary_significant_count": [0] * n,
        "proxy_prior_result_count": [i % 2 for i in range(n)],
        "proxy_prior_primary_tested_count": [i % 2 for i in range(n)],
        "proxy_prior_primary_significant_count": [i % 2 for i in range(n)],
    })
    links = pd.DataFrame({"nct_id": rows.nct_id,
                          "drug_group": [f"g{i}" for i in range(n)]})
    report = evaluate(rows, links)
    assert report["status"] == "retrospective_development_only"
    assert report["counts"]["train"] == train_n
    assert report["counts"]["validation"] == val_n
    assert set(report["arms"]) == {"public", "proxy"}
    assert all("brier" in report["arms"][arm] for arm in ("public", "proxy"))


def test_loader_never_requests_unfiltered_holdout_outcomes(monkeypatch, tmp_path):
    targets, trials, links, analyses = _fixtures()
    paths = {name: tmp_path / f"{name}.parquet" for name in ("b5", "trials", "links", "analyses")}
    calls = []
    def guarded_read(path, *, columns, filters=None):
        name = path.stem
        calls.append((name, columns, filters))
        if name == "b5":
            assert {"phase_stratum", "start_date", "first_post_date"} <= {f[0] for f in filters}
            assert all(f[1] in ("=", "<") for f in filters)
            return targets.loc[targets.first_post_date.lt("2024-01-01")].copy()
        if name == "trials":
            assert {"phase", "first_post_date", "results_first_post_date"} <= {f[0] for f in filters}
            phase = next(f[2] for f in filters if f[0] == "phase")
            if phase == "PHASE1":
                assert "last_update_post_date" in {f[0] for f in filters}
                return trials.loc[trials.phase.eq("PHASE1")].copy()
            assert "primary_completion_date" in {f[0] for f in filters}
            return trials.loc[trials.phase.eq("PHASE2")].copy()
        if name == "links":
            assert columns == ["nct_id", "program_id", "drug_group"]
            return links.copy()
        assert name == "analyses"
        assert {"nct_id", "outcome_type"} <= {f[0] for f in filters}
        return analyses.copy()
    monkeypatch.setattr(pd, "read_parquet", guarded_read)
    frames = load_development_sources(paths)
    assert frames["b5"].nct_id.tolist() == ["NCT00000002", "NCT00000003"]
    assert len(calls) == 5
