"""Synthetic modern-release contracts; no historical outcome data are opened."""
from __future__ import annotations

import json
import sys

import pandas as pd
import pytest

from phase_by_phase.historical_adapter import inventory, main, normalize, require_full_schema


COMMIT = "8bba65094c7d11a0a66924fab556ba971d456cef"


def _make_source(root):
    frames = {
        "core": pd.DataFrame([
            {"nct_id": "NCT1", "nct_version": 0, "last_update_post_date": "2010-01-01", "is_obsolete": False,
             "overall_status": "COMPLETED", "secret_outcome": "do not read"},
            {"nct_id": "NCT1", "nct_version": 1, "last_update_post_date": "2011-01-01", "is_obsolete": False,
             "overall_status": "TERMINATED", "secret_outcome": "do not read"},
            {"nct_id": "NCT2", "nct_version": 0, "last_update_post_date": None, "is_obsolete": False,
             "overall_status": "UNKNOWN", "secret_outcome": "do not read"},
        ]),
        "phases": pd.DataFrame([
            {"nct_id": "NCT1", "nct_version": 0, "ord": 0, "phase": "PHASE1", "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 0, "ord": 1, "phase": "PHASE2", "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 1, "ord": 0, "phase": "PHASE2", "is_obsolete": False},
        ]),
        "arm_groups": pd.DataFrame([
            {"nct_id": "NCT1", "nct_version": 0, "ord": 0, "arm_label": "Combo", "arm_type": "EXPERIMENTAL", "description": "A + B", "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 0, "ord": 1, "arm_label": "Control", "arm_type": "PLACEBO_COMPARATOR", "description": "Placebo", "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 1, "ord": 0, "arm_label": "Revised", "arm_type": "EXPERIMENTAL", "description": "A only", "is_obsolete": False},
        ]),
        "interventions": pd.DataFrame([
            {"nct_id": "NCT1", "nct_version": 0, "ord": 0, "intervention_name": "A", "intervention_type": "DRUG", "description": "raw A", "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 0, "ord": 1, "intervention_name": "B", "intervention_type": "DRUG", "description": "raw B", "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 1, "ord": 0, "intervention_name": "A", "intervention_type": "DRUG", "description": "revised A", "is_obsolete": False},
        ]),
        "intervention_arm_links": pd.DataFrame([
            {"nct_id": "NCT1", "nct_version": 0, "source": "arm", "parent_ord": 0, "item_ord": 0, "raw_label": "A", "intervention_ord": 0, "arm_group_ord": 0, "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 0, "source": "arm", "parent_ord": 0, "item_ord": 1, "raw_label": "B", "intervention_ord": 1, "arm_group_ord": 0, "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 0, "source": "intervention", "parent_ord": 1, "item_ord": 0, "raw_label": "unknown", "intervention_ord": None, "arm_group_ord": 1, "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 1, "source": "arm", "parent_ord": 0, "item_ord": 0, "raw_label": "B", "intervention_ord": 1, "arm_group_ord": 0, "is_obsolete": False},
        ]),
        "intervention_other_names": pd.DataFrame([
            {"nct_id": "NCT1", "nct_version": 0, "intervention_ord": 0,
             "other_name_ord": 0, "other_name": "Compound A (raw alias)", "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 0, "intervention_ord": 1,
             "other_name_ord": 0, "other_name": "B / second name", "is_obsolete": False},
            {"nct_id": "NCT1", "nct_version": 1, "intervention_ord": 1,
             "other_name_ord": 0, "other_name": "B now missing", "is_obsolete": False},
        ]),
    }
    for name, frame in frames.items():
        directory = root / name
        directory.mkdir(parents=True)
        frame.to_parquet(directory / "part-00000.parquet", index=False)
    return frames


def test_versioned_lossless_mixed_phase_combination_and_unresolved(tmp_path):
    source = tmp_path / "source"
    inputs = _make_source(source)
    out = tmp_path / "out"
    report = normalize(source, out, COMMIT)
    assert report["status"] == "organized_only_no_labels_or_models"
    for source_name, output_name in (("phases", "phase_membership"),
                                     ("arm_groups", "arms_clean"),
                                     ("interventions", "interventions_clean"),
                                     ("intervention_arm_links", "arm_intervention_links"),
                                     ("intervention_other_names", "intervention_aliases_clean")):
        result = pd.read_parquet(out / f"{output_name}.parquet")
        assert len(result) == len(inputs[source_name])
        assert set(inputs[source_name].columns).issubset(result.columns)
        assert result[list(inputs[source_name].columns)].reset_index(drop=True).equals(
            inputs[source_name].reset_index(drop=True))
        assert result.adapter_version_key_resolved.all()
    phases = pd.read_parquet(out / "phase_membership.parquet")
    assert phases.loc[phases.nct_version.eq(0), "phase"].tolist() == ["PHASE1", "PHASE2"]
    links = pd.read_parquet(out / "arm_intervention_links.parquet")
    assert links.adapter_link_status.tolist() == ["resolved", "resolved", "unresolved_intervention", "unresolved_intervention"]
    assert links.raw_label.tolist() == ["A", "B", "unknown", "B"]
    aliases = pd.read_parquet(out / "intervention_aliases_clean.parquet")
    assert aliases.other_name.tolist() == ["Compound A (raw alias)", "B / second name", "B now missing"]
    assert aliases.adapter_link_status.tolist() == ["resolved", "resolved", "unresolved_intervention"]
    assert "secret_outcome" not in str(report) and "overall_status" not in str(report)
    assert "secret_outcome" not in links and "overall_status" not in links
    assert json.loads((out / "manifest.json").read_text())["source_commit"] == COMMIT


def test_schema_drift_missing_ord_fails_before_output(tmp_path):
    source = tmp_path / "source"
    _make_source(source)
    path = source / "interventions" / "part-00000.parquet"
    pd.read_parquet(path).drop(columns="ord").to_parquet(path, index=False)
    _, schemas = inventory(source)
    assert schemas["interventions"]["missing_required"] == ["ord"]
    with pytest.raises(ValueError, match="Incompatible historical release schema"):
        require_full_schema(schemas)
    with pytest.raises(ValueError, match="Incompatible historical release schema"):
        normalize(source, tmp_path / "out", COMMIT)
    assert not (tmp_path / "out").exists()


def test_pilot_selects_ncts_but_keeps_all_selected_versions(tmp_path):
    source = tmp_path / "source"
    _make_source(source)
    out = tmp_path / "out"
    normalize(source, out, COMMIT, ["NCT1"])
    phases = pd.read_parquet(out / "phase_membership.parquet")
    assert set(phases.nct_version) == {0, 1}
    assert set(phases.nct_id) == {"NCT1"}


def test_duplicate_core_version_is_rejected(tmp_path):
    source = tmp_path / "source"
    _make_source(source)
    path = source / "core" / "part-00000.parquet"
    core = pd.read_parquet(path)
    pd.concat([core, core.iloc[[0]]], ignore_index=True).to_parquet(path, index=False)
    with pytest.raises(ValueError, match="Duplicate core"):
        normalize(source, tmp_path / "out", COMMIT)


def test_invalid_commit_and_existing_output_rejected(tmp_path):
    source = tmp_path / "source"
    _make_source(source)
    with pytest.raises(ValueError, match="immutable"):
        normalize(source, tmp_path / "out", "main")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        normalize(source, out, COMMIT)


def test_schema_check_needs_no_commit_and_flags_part_drift(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    _make_source(source)
    part = source / "phases" / "part-00000.parquet"
    second = source / "phases" / "part-00001.parquet"
    pd.read_parquet(part).assign(extra_field="x").to_parquet(second, index=False)
    monkeypatch.setattr(sys, "argv", ["historical_adapter", "--source", str(source), "--schema-check"])
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["compatible_full_release_schema"] is False
    assert result["gaps"]["phases"]["inconsistent_part_columns"] == ["extra_field"]
    with pytest.raises(ValueError, match="Incompatible historical release schema"):
        require_full_schema(inventory(source)[1])


def test_normalization_cli_still_requires_commit(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _make_source(source)
    monkeypatch.setattr(sys, "argv", ["historical_adapter", "--source", str(source),
                                        "--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert not (tmp_path / "out").exists()


def test_full_mode_streams_multiple_parts_with_exact_key_ambiguity(tmp_path):
    source = tmp_path / "source"
    _make_source(source)
    arm_path = source / "arm_groups" / "part-00000.parquet"
    arms = pd.read_parquet(arm_path)
    pd.concat([arms, arms.iloc[[0]]], ignore_index=True).to_parquet(arm_path, index=False)
    link_path = source / "intervention_arm_links" / "part-00000.parquet"
    links = pd.read_parquet(link_path)
    links.iloc[:2].to_parquet(link_path, index=False)
    links.iloc[2:].to_parquet(source / "intervention_arm_links" / "part-00001.parquet", index=False)
    out = tmp_path / "out"
    report = normalize(source, out, COMMIT)
    result = pd.read_parquet(out / "arm_intervention_links.parquet")
    assert len(result) == len(links)
    by_key = result.set_index(["nct_version", "parent_ord", "item_ord"])
    assert by_key.loc[(0, 0, 0), "adapter_link_status"] == "ambiguous_arm"
    assert by_key.loc[(0, 0, 1), "adapter_link_status"] == "ambiguous_arm"
    assert by_key.loc[(1, 0, 0), "adapter_link_status"] == "unresolved_intervention"
    assert report["counts"]["arms_clean"]["duplicate_ordinal_keys"] == 1
