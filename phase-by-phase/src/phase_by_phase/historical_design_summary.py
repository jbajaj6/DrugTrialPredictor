"""Build a reversible first-public design summary, without outcomes or models.

This is a descriptive staging table, not a ready-to-train feature matrix. In
particular, start date and sponsor identity need further checkpoint-specific
review before any model uses them. Only a strict core-column allowlist is read.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


CORE_COLUMNS = (
    "nct_id", "nct_version", "last_update_post_date", "is_obsolete",
    "study_type", "allocation", "intervention_model", "primary_purpose",
    "masking", "enrollment_count", "enrollment_type", "lead_sponsor_name",
    "lead_sponsor_class", "start_date", "start_date_type", "start_date_precision",
    "study_first_post_date",
)
CHILDREN = {
    "phase_membership": ("nct_id", "nct_version", "phase", "adapter_version_public_date"),
    "arms_clean": ("nct_id", "nct_version", "arm_type", "adapter_version_public_date"),
    "interventions_clean": ("nct_id", "nct_version", "intervention_type", "adapter_version_public_date"),
    "arm_intervention_links": ("nct_id", "nct_version", "adapter_link_status", "adapter_version_public_date"),
    "intervention_aliases_clean": ("nct_id", "nct_version", "adapter_link_status", "adapter_version_public_date"),
}


def _quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_columns(paths: list[Path], columns: tuple[str, ...], table: str) -> None:
    if not paths:
        raise FileNotFoundError(f"Missing {table} Parquet files")
    for path in paths:
        missing = set(columns) - set(pq.read_schema(path).names)
        if missing:
            raise ValueError(f"Missing {table} columns in {path.name}: {sorted(missing)}")


def _core_scan(paths: list[Path]) -> str:
    names = ", ".join("CAST(last_update_post_date AS DATE) AS last_update_post_date"
                      if name == "last_update_post_date" else name for name in CORE_COLUMNS)
    locations = ", ".join(_quote(path.resolve()) for path in paths)
    return f"SELECT {names}, filename AS adapter_core_source_file FROM read_parquet([{locations}], filename=true)"


def _child_scan(path: Path, columns: tuple[str, ...]) -> str:
    names = ", ".join("CAST(adapter_version_public_date AS DATE) AS adapter_version_public_date"
                      if name == "adapter_version_public_date" else name for name in columns)
    return f"SELECT {names} FROM read_parquet({_quote(path.resolve())})"


def _ids(path: Path | None) -> list[str] | None:
    if path is None:
        return None
    values = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if not values or len(values) != len(set(values)):
        raise ValueError("Pilot IDs must be nonempty and unique")
    return values


def build(source: Path, protocol: Path, out: Path, ids_path: Path | None = None) -> dict:
    """Select exact public versions and aggregate five child tables independently."""
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {out}")
    core_paths = sorted((source / "core").glob("*.parquet"))
    _require_columns(core_paths, CORE_COLUMNS, "core")
    for name, columns in CHILDREN.items():
        _require_columns([protocol / f"{name}.parquet"], columns, name)
    ids = _ids(ids_path)
    protocol_manifest_path = protocol / "manifest.json"
    source_manifest = json.loads(protocol_manifest_path.read_text())
    if source_manifest.get("source_root") != str(source.resolve()):
        raise ValueError("Protocol manifest refers to a different source root")
    if not source_manifest.get("source_commit"):
        raise ValueError("Protocol manifest has no pinned source commit")
    expected_source_hashes = source_manifest.get("source_files_sha256", {})
    expected_output_hashes = source_manifest.get("output_files_sha256", {})
    verified_input_hashes = {}
    for path in core_paths:
        key = f"core/{path.name}"
        actual = _digest(path)
        if expected_source_hashes.get(key) != actual:
            raise ValueError(f"Missing or mismatched source hash: {key}")
        verified_input_hashes[key] = actual
    for name in CHILDREN:
        path = protocol / f"{name}.parquet"
        actual = _digest(path)
        if expected_output_hashes.get(path.name) != actual:
            raise ValueError(f"Missing or mismatched protocol hash: {path.name}")
        verified_input_hashes[path.name] = actual
    if ids is not None and source_manifest.get("selected_nct_count") is not None:
        if source_manifest["selected_nct_count"] != len(ids):
            raise ValueError("Pilot ID count disagrees with protocol manifest")
    if ids is None and source_manifest.get("selected_nct_count") is not None:
        raise ValueError("Full summary requires full, not pilot, protocol tables")

    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=2")
    con.execute(f"CREATE VIEW core_projection AS {_core_scan(core_paths)}")
    if ids is not None:
        con.execute("CREATE TEMP TABLE pilot_ids(nct_id VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO pilot_ids VALUES (?)", [(value,) for value in ids])
        scope = "WHERE nct_id IN (SELECT nct_id FROM pilot_ids)"
    else:
        scope = ""
    con.execute(f"CREATE VIEW scoped_core AS SELECT * FROM core_projection {scope}")
    funnel = dict(zip(("source_core_versions", "null_public_date", "posted_2024_plus", "posted_before_2024"),
                      map(int, con.execute("""SELECT COUNT(*),
                          COUNT(*) FILTER (WHERE last_update_post_date IS NULL),
                          COUNT(*) FILTER (WHERE last_update_post_date >= DATE '2024-01-01'),
                          COUNT(*) FILTER (WHERE last_update_post_date < DATE '2024-01-01')
                          FROM scoped_core""").fetchone())))
    con.execute("""CREATE VIEW eligible_core AS SELECT * FROM scoped_core
                   WHERE last_update_post_date < DATE '2024-01-01'""")
    duplicate = con.execute("""SELECT nct_id, nct_version FROM eligible_core
                              GROUP BY 1,2 HAVING COUNT(*) > 1 LIMIT 1""").fetchone()
    if duplicate:
        raise ValueError(f"Duplicate eligible core version key: {duplicate}")
    con.execute("""CREATE VIEW first_public AS SELECT * EXCLUDE (selection_rank) FROM (
                   SELECT *, ROW_NUMBER() OVER
                     (PARTITION BY nct_id ORDER BY last_update_post_date, nct_version) AS selection_rank
                   FROM eligible_core) WHERE selection_rank=1""")
    funnel["selected_ncts"] = int(con.execute("SELECT COUNT(*) FROM first_public").fetchone()[0])
    funnel["requested_ids_without_public_pre2024_version"] = (
        len(ids) - funnel["selected_ncts"] if ids is not None else None)

    # Each child is aggregated independently before its one-to-one key join;
    # joining the children first would multiply arm x intervention x alias rows.
    for name, columns in CHILDREN.items():
        con.execute(f"CREATE VIEW source_{name} AS {_child_scan(protocol / f'{name}.parquet', columns)}")
        # Date consistency is checked only on selected versions, so later
        # versions retained in the lossless child files do not enter features.
        mismatch = con.execute(f"""SELECT COUNT(*) FROM source_{name} c
            JOIN first_public v USING (nct_id, nct_version)
            WHERE c.adapter_version_public_date IS DISTINCT FROM v.last_update_post_date""").fetchone()[0]
        if mismatch:
            raise ValueError(f"{name}: {mismatch} selected child dates disagree with core")

    con.execute("""CREATE VIEW phase_counts AS SELECT nct_id,nct_version,
        COUNT(*) AS phase_row_count,
        STRING_AGG(DISTINCT phase, '|' ORDER BY phase) AS phase_membership,
        COUNT(*) FILTER (WHERE phase IS NULL) AS phase_missing_value_count
        FROM source_phase_membership GROUP BY 1,2""")
    con.execute("""CREATE VIEW arm_counts AS SELECT nct_id,nct_version,
        COUNT(*) AS arm_row_count,
        COUNT(*) FILTER (WHERE upper(arm_type)='EXPERIMENTAL') AS experimental_arm_count,
        COUNT(*) FILTER (WHERE upper(arm_type)='PLACEBO_COMPARATOR') AS placebo_arm_count,
        COUNT(*) FILTER (WHERE arm_type IS NULL) AS arm_missing_type_count
        FROM source_arms_clean GROUP BY 1,2""")
    con.execute("""CREATE VIEW intervention_counts AS SELECT nct_id,nct_version,
        COUNT(*) AS intervention_row_count,
        COUNT(*) FILTER (WHERE upper(intervention_type)='DRUG') AS drug_intervention_count,
        COUNT(*) FILTER (WHERE intervention_type IS NULL) AS intervention_missing_type_count
        FROM source_interventions_clean GROUP BY 1,2""")
    con.execute("""CREATE VIEW link_counts AS SELECT nct_id,nct_version,
        COUNT(*) AS arm_intervention_link_row_count,
        COUNT(*) FILTER (WHERE adapter_link_status='resolved') AS resolved_link_count,
        COUNT(*) FILTER (WHERE adapter_link_status IS DISTINCT FROM 'resolved') AS unresolved_link_count
        FROM source_arm_intervention_links GROUP BY 1,2""")
    con.execute("""CREATE VIEW alias_counts AS SELECT nct_id,nct_version,
        COUNT(*) AS intervention_alias_row_count,
        COUNT(*) FILTER (WHERE adapter_link_status IS DISTINCT FROM 'resolved') AS unresolved_alias_count
        FROM source_intervention_aliases_clean GROUP BY 1,2""")

    out.mkdir(parents=True)
    spill = out / "duckdb_spill"
    spill.mkdir()
    con.execute(f"SET temp_directory={_quote(spill)}")
    output = out / "first_public_design_summary.parquet"
    query = """SELECT v.nct_id, v.nct_version AS first_public_nct_version,
        v.last_update_post_date AS first_public_date,
        v.adapter_core_source_file, v.is_obsolete AS first_public_core_is_obsolete,
        v.study_first_post_date,
        CAST(v.study_first_post_date AS DATE) < v.last_update_post_date AS archive_left_truncated,
        v.study_type, v.allocation, v.intervention_model, v.primary_purpose,
        v.masking, v.lead_sponsor_name, v.lead_sponsor_class,
        v.start_date, v.start_date_type, v.start_date_precision,
        CASE WHEN upper(v.enrollment_type)='ESTIMATED' THEN v.enrollment_count ELSE NULL END
          AS estimated_enrollment_count,
        v.enrollment_type IS NULL OR upper(v.enrollment_type) <> 'ESTIMATED'
          OR v.enrollment_count IS NULL AS estimated_enrollment_missing,
        COALESCE(p.phase_row_count,0) AS phase_row_count, p.phase_membership,
        COALESCE(p.phase_missing_value_count,0) AS phase_missing_value_count,
        COALESCE(a.arm_row_count,0) AS arm_row_count,
        COALESCE(a.experimental_arm_count,0) AS experimental_arm_count,
        COALESCE(a.placebo_arm_count,0) AS placebo_arm_count,
        COALESCE(a.arm_missing_type_count,0) AS arm_missing_type_count,
        COALESCE(i.intervention_row_count,0) AS intervention_row_count,
        COALESCE(i.drug_intervention_count,0) AS drug_intervention_count,
        COALESCE(i.intervention_missing_type_count,0) AS intervention_missing_type_count,
        COALESCE(l.arm_intervention_link_row_count,0) AS arm_intervention_link_row_count,
        COALESCE(l.resolved_link_count,0) AS resolved_link_count,
        COALESCE(l.unresolved_link_count,0) AS unresolved_link_count,
        COALESCE(x.intervention_alias_row_count,0) AS intervention_alias_row_count,
        COALESCE(x.unresolved_alias_count,0) AS unresolved_alias_count,
        p.nct_id IS NULL AS phase_rows_missing,
        a.nct_id IS NULL AS arm_rows_missing,
        i.nct_id IS NULL AS intervention_rows_missing,
        l.nct_id IS NULL AS link_rows_missing,
        x.nct_id IS NULL AS alias_rows_missing
        FROM first_public v
        LEFT JOIN phase_counts p USING (nct_id,nct_version)
        LEFT JOIN arm_counts a USING (nct_id,nct_version)
        LEFT JOIN intervention_counts i USING (nct_id,nct_version)
        LEFT JOIN link_counts l USING (nct_id,nct_version)
        LEFT JOIN alias_counts x USING (nct_id,nct_version)"""
    con.execute(f"COPY ({query}) TO {_quote(output)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    rows, unique_ncts, actual_enrollment = con.execute(f"""SELECT COUNT(*), COUNT(DISTINCT nct_id),
        COUNT(*) FILTER (WHERE estimated_enrollment_count IS NOT NULL AND estimated_enrollment_missing)
        FROM read_parquet({_quote(output)})""").fetchone()
    if rows != funnel["selected_ncts"] or unique_ncts != rows or actual_enrollment:
        raise AssertionError("One-NCT or estimated-enrollment output invariant failed")
    funnel["output_rows"] = rows
    guide = out / "column_guide.csv"
    schema = pq.read_schema(output)
    with guide.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("column", "dtype", "meaning"))
        for field in schema:
            meaning = "Descriptive first-public design only; not automatically a model feature"
            if field.name == "estimated_enrollment_count":
                meaning = "Planned enrollment only when source enrollment_type is ESTIMATED; not observed enrollment"
            elif field.name.endswith("_count"):
                meaning = "Count of exact-version child rows (or named subset); not a count of trials"
            elif field.name.endswith("_missing"):
                meaning = "Explicit missingness at this version; do not treat as a negative outcome"
            writer.writerow((field.name, str(field.type), meaning))
    (out / "funnel.json").write_text(json.dumps(funnel, indent=2, sort_keys=True) + "\n")
    report = {
        "status": "earliest_available_archived_public_version_descriptive_only_no_labels_or_models",
        "source_commit": source_manifest["source_commit"],
        "source_root": str(source.resolve()),
        "protocol_root": str(protocol.resolve()),
        "protocol_manifest_sha256": _digest(protocol_manifest_path),
        "code_sha256": _digest(Path(__file__)),
        "verified_input_sha256": verified_input_hashes,
        "pilot_ids_sha256": _digest(ids_path) if ids_path else None,
        "funnel": funnel,
        "output_sha256": {name: _digest(out / name) for name in
                          ("first_public_design_summary.parquet", "column_guide.csv", "funnel.json")},
    }
    (out / "manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    con.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ids", type=Path, help="Fixed pilot NCT-ID list; omit for full archive")
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.protocol, args.out, args.ids), indent=2))


if __name__ == "__main__":
    main()
