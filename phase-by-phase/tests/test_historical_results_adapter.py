"""Synthetic, cleaning-only contracts for versioned results."""
from __future__ import annotations

import pandas as pd
import pytest

from phase_by_phase.historical_results_adapter import REQUIRED, normalize


COMMIT = "8bba65094c7d11a0a66924fab556ba971d456cef"


def source_fixture(root):
    core = pd.DataFrame([
        {"nct_id": "NCT1", "nct_version": 1, "last_update_post_date": "2018-02-01", "is_obsolete": False,
         "overall_status": "UNKNOWN", "secret_outcome": "not a cleaner input"},
        {"nct_id": "NCT1", "nct_version": 2, "last_update_post_date": "2019-03-01", "is_obsolete": False,
         "overall_status": "UNKNOWN", "secret_outcome": "not a cleaner input"},
        {"nct_id": "NCT1", "nct_version": 3, "last_update_post_date": "2024-02-01", "is_obsolete": False,
         "overall_status": "COMPLETED", "secret_outcome": "sealed"},
        {"nct_id": "NCT2", "nct_version": 1, "last_update_post_date": None, "is_obsolete": False,
         "overall_status": "COMPLETED", "secret_outcome": "unposted"},
    ])
    frames = {"core": core}
    for table, required in REQUIRED.items():
        columns = ["nct_id", "nct_version"] + sorted(required)
        base = {column: None for column in columns}
        base.update({"nct_id": "NCT1", "nct_version": 1})
        for key in ("outcome_ord", "analysis_ord", "measurement_ord", "period_ord", "milestone_ord", "event_ord", "stat_ord"):
            if key in base:
                base[key] = 0
        if "group_id" in base:
            base["group_id"] = "GROUP_A"
        if "title" in base:
            base["title"] = "Raw outcome wording"
        if "description" in base:
            base["description"] = "Keep this long-form result text unchanged."
        if "p_value" in base:
            base["p_value"] = "<0.05"
        if "p_value_comment" in base:
            base["p_value_comment"] = "prespecified comparison"
        frames[table] = pd.DataFrame([base])
    frames["results_outcome_measures"] = pd.concat([
        frames["results_outcome_measures"],
        frames["results_outcome_measures"].assign(nct_version=2, title="Revised wording"),
        frames["results_outcome_measures"].assign(nct_version=3, title="Sealed wording"),
        frames["results_outcome_measures"].assign(nct_id="NCT2", title="Unposted wording"),
    ], ignore_index=True)
    frames["results_outcome_analyses"] = pd.concat([
        frames["results_outcome_analyses"],
        frames["results_outcome_analyses"].assign(nct_version=2, outcome_ord=99, p_value="0.8"),
        frames["results_outcome_analyses"].assign(nct_version=3, p_value="0.001"),
        frames["results_outcome_analyses"].assign(nct_id="NCT_ORPHAN", p_value="orphan secret"),
    ], ignore_index=True)
    frames["results_outcome_groups"] = pd.concat([
        frames["results_outcome_groups"],
        frames["results_outcome_groups"].assign(nct_version=2),
    ], ignore_index=True)
    for name, frame in frames.items():
        directory = root / name
        directory.mkdir(parents=True)
        frame.to_parquet(directory / "part-00000.parquet", index=False)
    return frames


def test_preserves_raw_text_keys_and_reports_unresolved_without_sealed_values(tmp_path):
    source = tmp_path / "source"
    source_fixture(source)
    out = tmp_path / "out"
    report = normalize(source, out, COMMIT)
    measures = pd.read_parquet(out / "results_outcome_measures_clean.parquet")
    analyses = pd.read_parquet(out / "results_outcome_analyses_clean.parquet")
    assert len(measures) == 2
    assert measures.title.tolist() == ["Raw outcome wording", "Revised wording"]
    assert measures.description.tolist() == ["Keep this long-form result text unchanged."] * 2
    assert set(measures.adapter_version_public_date.astype(str)) == {"2018-02-01", "2019-03-01"}
    assert set(measures.adapter_source_commit) == {COMMIT}
    assert len(analyses) == 2
    assert analyses.p_value.tolist() == ["<0.05", "0.8"]
    assert report["counts"]["results_outcome_analyses"]["unresolved_references"]["results_outcome_measures"] == 1
    assert report["counts"]["results_outcome_analyses"]["missing_core_version_rows"] == 1
    assert report["counts"]["results_outcome_analyses"]["posted_2024_or_later_rows"] == 1
    assert report["counts"]["results_outcome_analyses"]["unposted_core_version_rows"] == 0
    assert "0.001" not in analyses.p_value.tolist()
    assert "orphan secret" not in analyses.p_value.tolist()
    assert "secret_outcome" not in measures.columns
    assert report["counts"]["results_outcome_measures"]["excluded_from_development_rows"] == 2
    assert report["counts"]["results_outcome_measures"]["unposted_core_version_rows"] == 1
    assert report["counts"]["results_outcome_measures"]["posted_2024_or_later_rows"] == 1


def test_missing_required_result_column_fails_before_output(tmp_path):
    source = tmp_path / "source"
    source_fixture(source)
    path = source / "results_outcome_analyses" / "part-00000.parquet"
    pd.read_parquet(path).drop(columns="p_value_comment").to_parquet(path, index=False)
    with pytest.raises(ValueError, match="p_value_comment"):
        normalize(source, tmp_path / "out", COMMIT)
    assert not (tmp_path / "out").exists()


def test_duplicate_public_core_version_fails_before_output(tmp_path):
    source = tmp_path / "source"
    source_fixture(source)
    path = source / "core" / "part-00000.parquet"
    core = pd.read_parquet(path)
    pd.concat([core, core.iloc[[0]]], ignore_index=True).to_parquet(path, index=False)
    with pytest.raises(ValueError, match="Duplicate core"):
        normalize(source, tmp_path / "out", COMMIT)
    assert not (tmp_path / "out").exists()


def test_selected_nct_retains_all_eligible_versions(tmp_path):
    source = tmp_path / "source"
    source_fixture(source)
    report = normalize(source, tmp_path / "out", COMMIT, ["NCT1"])
    assert report["selected_nct_count"] == 1
    frame = pd.read_parquet(tmp_path / "out" / "results_outcome_measures_clean.parquet")
    assert set(frame.nct_version) == {1, 2}
