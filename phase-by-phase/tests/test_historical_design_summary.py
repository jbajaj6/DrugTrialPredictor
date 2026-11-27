"""Synthetic B12 checks; no sealed outcomes are loaded."""
import json
import hashlib

import pandas as pd
import pytest

from phase_by_phase.historical_design_summary import build


def fixture_inputs(tmp_path):
    source = tmp_path / "raw"
    (source / "core").mkdir(parents=True)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    core = pd.DataFrame([
        dict(nct_id="NCT1", nct_version=1, last_update_post_date="2012-03-01",
             is_obsolete=False, study_type="INTERVENTIONAL", allocation="RANDOMIZED",
             intervention_model="PARALLEL", primary_purpose="TREATMENT", masking="DOUBLE",
             enrollment_count=50, enrollment_type="ACTUAL", lead_sponsor_name="Maker",
             lead_sponsor_class="INDUSTRY", start_date="2012-01-01", start_date_type="ACTUAL",
             start_date_precision="DAY", study_first_post_date="2010-02-01",
             overall_status="COMPLETED", secret_label="future"),
        dict(nct_id="NCT1", nct_version=0, last_update_post_date="2010-02-01",
             is_obsolete=False, study_type="INTERVENTIONAL", allocation="RANDOMIZED",
             intervention_model="PARALLEL", primary_purpose="TREATMENT", masking="NONE",
             enrollment_count=100, enrollment_type="ESTIMATED", lead_sponsor_name="Maker",
             lead_sponsor_class="INDUSTRY", start_date="2010-01-01", start_date_type="ESTIMATED",
             start_date_precision="MONTH", study_first_post_date="2010-02-01",
             overall_status="RECRUITING", secret_label="not-yet"),
        dict(nct_id="NCT2", nct_version=0, last_update_post_date=None,
             is_obsolete=False, study_type="INTERVENTIONAL", allocation=None,
             intervention_model=None, primary_purpose=None, masking=None,
             enrollment_count=None, enrollment_type=None, lead_sponsor_name=None,
             lead_sponsor_class=None, start_date=None, start_date_type=None,
             start_date_precision=None, study_first_post_date=None,
             overall_status="UNKNOWN", secret_label="unknown"),
        dict(nct_id="NCT3", nct_version=0, last_update_post_date="2024-01-01",
             is_obsolete=False, study_type="INTERVENTIONAL", allocation=None,
             intervention_model=None, primary_purpose=None, masking=None,
             enrollment_count=None, enrollment_type=None, lead_sponsor_name=None,
             lead_sponsor_class=None, start_date=None, start_date_type=None,
             start_date_precision=None, study_first_post_date="2024-01-01",
             overall_status="COMPLETED", secret_label="sealed"),
    ])
    core.to_parquet(source / "core" / "part.parquet", index=False)
    tables = {
        "phase_membership": pd.DataFrame([
            dict(nct_id="NCT1", nct_version=0, phase="PHASE1", adapter_version_public_date="2010-02-01"),
            dict(nct_id="NCT1", nct_version=0, phase="PHASE2", adapter_version_public_date="2010-02-01"),
            dict(nct_id="NCT1", nct_version=1, phase="PHASE3", adapter_version_public_date="2012-03-01")]),
        "arms_clean": pd.DataFrame([
            dict(nct_id="NCT1", nct_version=0, arm_type="EXPERIMENTAL", adapter_version_public_date="2010-02-01"),
            dict(nct_id="NCT1", nct_version=0, arm_type="PLACEBO_COMPARATOR", adapter_version_public_date="2010-02-01"),
            dict(nct_id="NCT1", nct_version=1, arm_type="EXPERIMENTAL", adapter_version_public_date="2012-03-01")]),
        "interventions_clean": pd.DataFrame([
            dict(nct_id="NCT1", nct_version=0, intervention_type="DRUG", adapter_version_public_date="2010-02-01"),
            dict(nct_id="NCT1", nct_version=0, intervention_type="DRUG", adapter_version_public_date="2010-02-01")]),
        "arm_intervention_links": pd.DataFrame([
            dict(nct_id="NCT1", nct_version=0, adapter_link_status="resolved", adapter_version_public_date="2010-02-01"),
            dict(nct_id="NCT1", nct_version=0, adapter_link_status="unresolved_arm", adapter_version_public_date="2010-02-01")]),
        "intervention_aliases_clean": pd.DataFrame([
            dict(nct_id="NCT1", nct_version=0, adapter_link_status="resolved", adapter_version_public_date="2010-02-01")]),
    }
    for name, frame in tables.items():
        frame.to_parquet(protocol / f"{name}.parquet", index=False)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    (protocol / "manifest.json").write_text(json.dumps({
        "source_root": str(source.resolve()), "source_commit": "a" * 40,
        "selected_nct_count": None,
        "source_files_sha256": {"core/part.parquet": digest(source / "core" / "part.parquet")},
        "output_files_sha256": {f"{name}.parquet": digest(protocol / f"{name}.parquet")
                                for name in tables}}))
    ids = tmp_path / "pilot_ids.txt"
    ids.write_text("NCT1\nNCT2\nNCT3\n")
    return source, protocol, ids


def test_first_public_exact_version_counts_no_future_or_actual_enrollment(tmp_path):
    source, protocol, ids = fixture_inputs(tmp_path)
    report = build(source, protocol, tmp_path / "out", ids)
    row = pd.read_parquet(tmp_path / "out" / "first_public_design_summary.parquet").iloc[0]
    assert report["funnel"]["selected_ncts"] == 1
    assert report["funnel"]["requested_ids_without_public_pre2024_version"] == 2
    assert row.nct_id == "NCT1" and row.first_public_nct_version == 0
    assert row.phase_membership == "PHASE1|PHASE2"
    assert row.arm_row_count == 2 and row.intervention_row_count == 2
    assert row.arm_intervention_link_row_count == 2 and row.unresolved_link_count == 1
    assert row.estimated_enrollment_count == 100 and not row.estimated_enrollment_missing
    guide = pd.read_csv(tmp_path / "out" / "column_guide.csv").set_index("column")
    assert "Planned enrollment" in guide.loc["estimated_enrollment_count", "meaning"]
    assert "overall_status" not in row.index and "secret_label" not in row.index
    assert "ACTUAL" not in str(row.to_dict())


def test_duplicate_key_missing_schema_and_overwrite_fail_closed(tmp_path):
    source, protocol, _ = fixture_inputs(tmp_path)
    core_path = source / "core" / "part.parquet"
    core = pd.read_parquet(core_path)
    pd.concat([core, core.iloc[[1]]], ignore_index=True).to_parquet(core_path, index=False)
    manifest_path = protocol / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source_files_sha256"]["core/part.parquet"] = __import__("hashlib").sha256(core_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Duplicate eligible core version"):
        build(source, protocol, tmp_path / "dup")
    core.to_parquet(core_path, index=False)
    manifest["source_files_sha256"]["core/part.parquet"] = __import__("hashlib").sha256(core_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    arm_path = protocol / "arms_clean.parquet"
    arms = pd.read_parquet(arm_path)
    arms.drop(columns="arm_type").to_parquet(arm_path, index=False)
    manifest["output_files_sha256"]["arms_clean.parquet"] = __import__("hashlib").sha256(arm_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Missing arms_clean columns"):
        build(source, protocol, tmp_path / "bad_schema")
    arms.to_parquet(arm_path, index=False)
    manifest["output_files_sha256"]["arms_clean.parquet"] = __import__("hashlib").sha256(arm_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        build(source, protocol, existing)


def test_child_date_mismatch_rejected(tmp_path):
    source, protocol, _ = fixture_inputs(tmp_path)
    path = protocol / "arms_clean.parquet"
    arms = pd.read_parquet(path)
    arms.loc[0, "adapter_version_public_date"] = "2011-01-01"
    arms.to_parquet(path, index=False)
    manifest_path = protocol / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output_files_sha256"]["arms_clean.parquet"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="dates disagree"):
        build(source, protocol, tmp_path / "mismatch")


def test_same_public_date_tie_breaks_by_version_and_actual_enrollment_stays_out(tmp_path):
    source, protocol, _ = fixture_inputs(tmp_path)
    path = source / "core" / "part.parquet"
    core = pd.read_parquet(path)
    core.loc[0, "last_update_post_date"] = "2010-02-01"  # v1 ties v0
    core.loc[1, "enrollment_type"] = "ACTUAL"
    core.to_parquet(path, index=False)
    manifest_path = protocol / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source_files_sha256"]["core/part.parquet"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    build(source, protocol, tmp_path / "tie")
    row = pd.read_parquet(tmp_path / "tie" / "first_public_design_summary.parquet").iloc[0]
    assert row.first_public_nct_version == 0
    assert pd.isna(row.estimated_enrollment_count)
    assert row.estimated_enrollment_missing


def test_hash_mismatch_rejected_before_any_output(tmp_path):
    source, protocol, _ = fixture_inputs(tmp_path)
    path = protocol / "arms_clean.parquet"
    changed = pd.read_parquet(path)
    changed.loc[0, "arm_type"] = "CHANGED"
    changed.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="Mismatched protocol hash|mismatched protocol hash"):
        build(source, protocol, tmp_path / "tampered")
    assert not (tmp_path / "tampered").exists()
