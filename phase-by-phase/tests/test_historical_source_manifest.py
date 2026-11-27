"""Metadata-only source provenance checks."""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from phase_by_phase.historical_source_manifest import inventory


COMMIT = "a" * 40


def test_inventory_hashes_parts_without_exposing_core_column_names(tmp_path):
    core = tmp_path / "core"
    child = tmp_path / "interventions"
    core.mkdir()
    child.mkdir()
    pq.write_table(pa.table({"nct_id": ["NCT1"], "sealed_outcome": ["secret"]}), core / "p.parquet")
    pq.write_table(pa.table({"nct_id": ["NCT1"], "intervention_name": ["Drug A"]}), child / "p.parquet")
    report = inventory(tmp_path, COMMIT)
    assert report["totals"]["tables"] == 2
    assert report["totals"]["files"] == 2
    assert report["totals"]["footer_rows_including_repeated_versions_and_child_rows"] == 2
    assert report["tables"]["core"]["columns"] is None
    assert "sealed_outcome" not in str(report)
    assert len(report["tables"]["interventions"]["files"][0]["sha256"]) == 64


def test_inventory_rejects_unpinned_source(tmp_path):
    with pytest.raises(ValueError, match="pinned"):
        inventory(tmp_path, "main")


def test_inventory_rejects_schema_drift(tmp_path):
    table = tmp_path / "interventions"
    table.mkdir()
    pq.write_table(pa.table({"a": [1]}), table / "p0.parquet")
    pq.write_table(pa.table({"b": [1]}), table / "p1.parquet")
    with pytest.raises(ValueError, match="Schema drift"):
        inventory(tmp_path, COMMIT)
