"""Lossless, version-keyed organization of historical protocol child tables.

This adapter does not choose prediction checkpoints, derive outcomes, or fit a
model. The 2026-11 full-release schema is required; older public samples are
reported as incompatible rather than silently joining text labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import duckdb
import pandas as pd
import pyarrow.parquet as pq


TABLES = ("core", "phases", "arm_groups", "interventions", "intervention_arm_links",
          "intervention_other_names")
REQUIRED = {
    "core": {"nct_id", "nct_version", "last_update_post_date", "is_obsolete"},
    "phases": {"nct_id", "nct_version", "ord", "phase", "is_obsolete"},
    "arm_groups": {"nct_id", "nct_version", "ord", "arm_label", "arm_type", "description", "is_obsolete"},
    "interventions": {"nct_id", "nct_version", "ord", "intervention_name", "intervention_type", "description", "is_obsolete"},
    "intervention_arm_links": {"nct_id", "nct_version", "source", "parent_ord", "item_ord", "raw_label", "intervention_ord", "arm_group_ord", "is_obsolete"},
    "intervention_other_names": {"nct_id", "nct_version", "intervention_ord", "other_name_ord", "other_name", "is_obsolete"},
}
OUTPUTS = {
    "phases": "phase_membership",
    "arm_groups": "arms_clean",
    "interventions": "interventions_clean",
    "intervention_arm_links": "arm_intervention_links",
    "intervention_other_names": "intervention_aliases_clean",
}
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(source: Path) -> tuple[dict[str, list[Path]], dict[str, dict]]:
    """Read only Parquet metadata; do not inspect outcome/label tables."""
    files = {}
    schemas = {}
    for name in TABLES:
        parts = sorted((source / name).glob("*.parquet"))
        if not parts:
            raise FileNotFoundError(f"No Parquet parts for {name}: {source / name}")
        files[name] = parts
        column_sets = [set(pq.read_schema(part).names) for part in parts]
        all_columns = set.intersection(*column_sets)
        missing = sorted(REQUIRED[name] - all_columns)
        part_drift_columns = set.union(*column_sets) - all_columns
        part_drift = sorted(part_drift_columns & REQUIRED[name]) if name == "core" else sorted(part_drift_columns)
        schemas[name] = {"missing_required": missing, "inconsistent_part_columns": part_drift,
                         # Core may contain sealed outcome columns. Do not reproduce
                         # even their names in the development manifest.
                         "common_columns": sorted(all_columns & REQUIRED[name]) if name == "core"
                         else sorted(all_columns), "parts": len(parts)}
    return files, schemas


def require_full_schema(schemas: dict[str, dict]) -> None:
    gaps = {name: {k: value for k, value in report.items()
                   if k in ("missing_required", "inconsistent_part_columns") and value}
            for name, report in schemas.items()}
    gaps = {name: value for name, value in gaps.items() if value}
    if gaps:
        raise ValueError("Incompatible historical release schema: " + json.dumps(gaps, sort_keys=True))


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _scan(parts: list[Path]) -> str:
    paths = ", ".join(_sql_literal(str(part.resolve())) for part in parts)
    return f"read_parquet([{paths}], filename=true)"


def _key_counts(con: duckdb.DuckDBPyConnection, table: str) -> tuple[int, int, int]:
    output = _sql_literal(str(table))
    rows, versions, missing = con.execute(f"""SELECT COUNT(*),
        COUNT(DISTINCT (nct_id, nct_version)),
        COALESCE(SUM(CASE WHEN NOT adapter_version_key_resolved THEN 1 ELSE 0 END), 0)
        FROM read_parquet({output})""").fetchone()
    return int(rows), int(versions), int(missing)


def _copy_query(con: duckdb.DuckDBPyConnection, query: str, destination: Path) -> None:
    con.execute(f"COPY ({query}) TO {_sql_literal(str(destination))} (FORMAT PARQUET, COMPRESSION ZSTD)")


def _nct_bounds(part: Path) -> tuple[str, str]:
    """Use footer statistics; never scan outcome columns to choose a batch."""
    parquet = pq.ParquetFile(part)
    column = parquet.schema_arrow.names.index("nct_id")
    lows, highs = [], []
    for index in range(parquet.metadata.num_row_groups):
        stats = parquet.metadata.row_group(index).column(column).statistics
        if stats is None or stats.min is None or stats.max is None:
            raise ValueError(f"Cannot safely bound NCT batch without footer statistics: {part}")
        low = stats.min.decode() if isinstance(stats.min, bytes) else str(stats.min)
        high = stats.max.decode() if isinstance(stats.max, bytes) else str(stats.max)
        lows.append(low)
        highs.append(high)
    return min(lows), max(highs)


def _stream_keyed_parts(con: duckdb.DuckDBPyConnection, query: str, name: str,
                        parts: list[Path], destination: Path) -> None:
    """Resolve one source part at a time against range-pruned exact keys."""
    writer = None
    serial = 0
    try:
        for part in parts:
            low, high = _nct_bounds(part)
            bound = f"nct_id BETWEEN {_sql_literal(low)} AND {_sql_literal(high)}"
            con.execute(f"CREATE OR REPLACE TEMP VIEW batch_core AS SELECT * FROM selected_core WHERE {bound}")
            con.execute(f"CREATE OR REPLACE TEMP VIEW batch_arms AS SELECT * FROM source_arm_groups WHERE {bound}")
            con.execute(f"CREATE OR REPLACE TEMP VIEW batch_interventions AS SELECT * FROM source_interventions WHERE {bound}")
            con.execute(f"CREATE OR REPLACE TEMP VIEW batch_child AS SELECT * FROM {_scan([part])}")
            batch_query = (query.replace(f"source_{name} c", "batch_child c")
                           .replace("selected_core v", "batch_core v")
                           .replace("FROM source_arm_groups GROUP BY", "FROM batch_arms GROUP BY")
                           .replace("FROM source_interventions GROUP BY", "FROM batch_interventions GROUP BY")
                           .replace("ROW_NUMBER() OVER () - 1 AS", f"ROW_NUMBER() OVER () - 1 + {serial} AS"))
            reader = con.execute(batch_query).fetch_record_batch(rows_per_batch=65536)
            for batch in reader:
                if writer is None:
                    writer = pq.ParquetWriter(destination, batch.schema, compression="zstd")
                writer.write_batch(batch)
                serial += batch.num_rows
        if writer is None:
            raise ValueError(f"No rows to stream for {name}; refusing schema-free output")
    finally:
        if writer is not None:
            writer.close()


def normalize(source: Path, out: Path, commit: str, nct_ids: list[str] | None = None) -> dict:
    """Stream child Parquet through bounded-memory DuckDB joins and COPY."""
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("Source commit must be an immutable 40-character hex hash")
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite: {out}")
    files, schemas = inventory(source)
    require_full_schema(schemas)
    if nct_ids is not None and (not nct_ids or len(nct_ids) != len(set(nct_ids))):
        raise ValueError("NCT selection must be a nonempty unique list")
    for name in OUTPUTS:
        if any(column.startswith("adapter_") or column == "filename"
               for column in pq.read_schema(files[name][0]).names):
            raise ValueError(f"Reserved adapter_ or filename column in source {name}")

    # Only these four core columns are projected; status/results/enrollment are
    # never read. DuckDB scans Parquet parts and spills joins under a 1 GiB cap.
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=2")
    if nct_ids is not None:
        con.register("selected_ids", pd.DataFrame({"nct_id": nct_ids}))
    for name in TABLES:
        projection = ("nct_id, nct_version, last_update_post_date, is_obsolete"
                      if name == "core" else "*")
        pilot_filter = ("WHERE nct_id IN (SELECT nct_id FROM selected_ids)"
                        if nct_ids is not None else "")
        con.execute(f"CREATE VIEW source_{name} AS SELECT {projection} FROM {_scan(files[name])} {pilot_filter}")
    selected = "WHERE EXISTS (SELECT 1 FROM selected_ids s WHERE s.nct_id=c.nct_id)" if nct_ids is not None else ""
    core_selected = ("WHERE EXISTS (SELECT 1 FROM selected_ids s WHERE s.nct_id=nct_id)"
                     if nct_ids is not None else "")
    con.execute(f"CREATE VIEW selected_core AS SELECT * FROM source_core {core_selected}")
    out.mkdir(parents=True)
    spill = out / "duckdb_spill"
    spill.mkdir()
    con.execute(f"SET temp_directory={_sql_literal(str(spill))}")
    duplicate = con.execute("""SELECT nct_id, nct_version FROM selected_core
        GROUP BY nct_id, nct_version HAVING COUNT(*) > 1 LIMIT 1""").fetchone()
    if duplicate:
        raise ValueError("Duplicate core (nct_id, nct_version) keys")
    source_prefix = _sql_literal(str(source.resolve()) + "/")
    output_hashes = {}
    counts = {}
    guide = []
    for name, output_name in OUTPUTS.items():
        output_path = out / f"{output_name}.parquet"
        link_joins = ""
        link_columns = ""
        if name == "intervention_arm_links":
            link_joins = """LEFT JOIN (SELECT nct_id, nct_version, ord, COUNT(*) AS n
                FROM source_arm_groups GROUP BY nct_id, nct_version, ord) arm
                ON c.nct_id=arm.nct_id AND c.nct_version=arm.nct_version AND c.arm_group_ord=arm.ord
                LEFT JOIN (SELECT nct_id, nct_version, ord, COUNT(*) AS n
                FROM source_interventions GROUP BY nct_id, nct_version, ord) intervention
                ON c.nct_id=intervention.nct_id AND c.nct_version=intervention.nct_version
                   AND c.intervention_ord=intervention.ord"""
            link_columns = """, COALESCE(arm.n, 0) AS adapter_arm_match_count,
                COALESCE(intervention.n, 0) AS adapter_intervention_match_count,
                CASE WHEN COALESCE(arm.n, 0)=1 AND COALESCE(intervention.n, 0)=1 THEN 'resolved'
                ELSE CONCAT_WS('+',
                  CASE WHEN COALESCE(arm.n, 0)>1 THEN 'ambiguous_arm'
                       WHEN COALESCE(arm.n, 0)=0 THEN 'unresolved_arm' END,
                  CASE WHEN COALESCE(intervention.n, 0)>1 THEN 'ambiguous_intervention'
                       WHEN COALESCE(intervention.n, 0)=0 THEN 'unresolved_intervention' END)
                END AS adapter_link_status"""
        elif name == "intervention_other_names":
            link_joins = """LEFT JOIN (SELECT nct_id, nct_version, ord, COUNT(*) AS n
                FROM source_interventions GROUP BY nct_id, nct_version, ord) intervention
                ON c.nct_id=intervention.nct_id AND c.nct_version=intervention.nct_version
                   AND c.intervention_ord=intervention.ord"""
            link_columns = """, COALESCE(intervention.n, 0) AS adapter_intervention_match_count,
                CASE WHEN COALESCE(intervention.n, 0)=1 THEN 'resolved'
                     WHEN COALESCE(intervention.n, 0)>1 THEN 'ambiguous_intervention'
                     ELSE 'unresolved_intervention' END AS adapter_link_status"""
        query = f"""SELECT c.* EXCLUDE(filename),
            replace(c.filename, {source_prefix}, '') AS adapter_source_file,
            ROW_NUMBER() OVER () - 1 AS adapter_loaded_row_index,
            {_sql_literal(commit)} AS adapter_source_commit,
            {_sql_literal(name)} AS adapter_source_table,
            v.last_update_post_date AS adapter_version_public_date,
            v.is_obsolete AS adapter_core_is_obsolete,
            v.nct_id IS NOT NULL AS adapter_version_key_resolved
            {link_columns}
            FROM source_{name} c LEFT JOIN selected_core v
              ON c.nct_id=v.nct_id AND c.nct_version=v.nct_version
            {link_joins} {selected}"""
        if nct_ids is None and name in ("intervention_arm_links", "intervention_other_names"):
            _stream_keyed_parts(con, query, name, files[name], output_path)
        else:
            _copy_query(con, query, output_path)
        rows, versions, missing = _key_counts(con, str(output_path))
        if nct_ids is None:
            expected = sum(pq.ParquetFile(part).metadata.num_rows for part in files[name])
        else:
            expected = int(con.execute(f"SELECT COUNT(*) FROM source_{name} c {selected}").fetchone()[0])
        if rows != expected:
            raise AssertionError(f"Loss or duplication of {name} rows: {rows} != {expected}")
        output_hashes[output_path.name] = sha256(output_path)
        duplicate_ord = None
        if name not in ("intervention_arm_links", "intervention_other_names"):
            duplicate_ord = int(con.execute(f"""SELECT COALESCE(SUM(n-1), 0) FROM
                (SELECT COUNT(*) AS n FROM read_parquet({_sql_literal(str(output_path))})
                 GROUP BY nct_id, nct_version, ord HAVING COUNT(*)>1)""").fetchone()[0])
        elif name == "intervention_other_names":
            duplicate_ord = int(con.execute(f"""SELECT COALESCE(SUM(n-1), 0) FROM
                (SELECT COUNT(*) AS n FROM read_parquet({_sql_literal(str(output_path))})
                 GROUP BY nct_id, nct_version, intervention_ord, other_name_ord HAVING COUNT(*)>1)""").fetchone()[0])
        counts[output_name] = {"rows": rows, "unique_version_keys": versions,
                               "missing_core_version": missing,
                               "duplicate_ordinal_keys": duplicate_ord}
        schema = pq.read_schema(output_path)
        for column in schema.names:
            guide.append({"table": output_name, "column": column, "dtype": str(schema.field(column).type),
                          "origin": "adapter" if column.startswith("adapter_") else name,
                          "description": _description(column)})
    link_path = out / "arm_intervention_links.parquet"
    link_counts = con.execute(f"""SELECT adapter_link_status, COUNT(*) FROM
        read_parquet({_sql_literal(str(link_path))}) GROUP BY adapter_link_status""").fetchall()
    counts["arm_intervention_links"]["link_status_counts"] = {str(k): int(v) for k, v in link_counts}
    alias_path = out / "intervention_aliases_clean.parquet"
    alias_counts = con.execute(f"""SELECT adapter_link_status, COUNT(*) FROM
        read_parquet({_sql_literal(str(alias_path))}) GROUP BY adapter_link_status""").fetchall()
    counts["intervention_aliases_clean"]["link_status_counts"] = {str(k): int(v) for k, v in alias_counts}
    con.close()
    guide_path = out / "column_guide.csv"
    pd.DataFrame(guide).to_csv(guide_path, index=False)
    output_hashes[guide_path.name] = sha256(guide_path)
    manifest = {"status": "organized_only_no_labels_or_models", "source_commit": commit,
                "source_root": str(source.resolve()), "selected_nct_count": len(nct_ids) if nct_ids else None,
                "source_files_sha256": {p.relative_to(source).as_posix(): sha256(p)
                                        for parts in files.values() for p in parts},
                "code_sha256": sha256(Path(__file__)), "schemas": schemas, "counts": counts,
                "output_files_sha256": output_hashes,
                "scientific_note": "Candidate arm links are registry records, not verified drug identities. Missing or ambiguous links remain rows. Dates are copied, not interpreted as exact clinical event times. The older public sample is not a full-release cohort."}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    return manifest


def _description(column: str) -> str:
    return {
        "nct_id": "Registry trial identifier; join with nct_version.",
        "nct_version": "Source version number; child rows must join on both NCT and version.",
        "ord": "Source list position; distinguishes repeated entries within one version.",
        "adapter_source_file": "Relative source Parquet part that supplied this row.",
        "adapter_loaded_row_index": "Serial number assigned during streamed output; not original source ordinal.",
        "adapter_source_commit": "Pinned source repository commit.",
        "adapter_source_table": "Original source table name.",
        "adapter_version_public_date": "Core last-update public date for this exact version; null means not shown public or unresolved core key.",
        "adapter_core_is_obsolete": "Core obsolete indicator for this exact version.",
        "adapter_version_key_resolved": "Whether this child row joins to exactly one core version.",
        "adapter_arm_match_count": "Number of arm rows matching the exact NCT/version/arm ordinal.",
        "adapter_intervention_match_count": "Number of intervention rows matching the exact NCT/version/intervention ordinal.",
        "adapter_link_status": "Resolved, missing, or ambiguous ordinal reference; unresolved rows are retained.",
    }.get(column, "Unmodified source field; consult the pinned dataset schema for semantics.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--commit", help="Pinned source commit (required when normalizing)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--schema-check", action="store_true")
    parser.add_argument("--nct-ids", type=Path, help="Optional newline-delimited pilot NCT IDs")
    args = parser.parse_args()
    files, schemas = inventory(args.source)
    if args.schema_check:
        gaps = {name: {key: report[key] for key in ("missing_required", "inconsistent_part_columns")
                       if report[key]} for name, report in schemas.items()}
        gaps = {name: details for name, details in gaps.items() if details}
        print(json.dumps({"compatible_full_release_schema": not bool(gaps), "gaps": gaps,
                          "parts": {name: len(parts) for name, parts in files.items()}}, indent=2))
        return
    if args.out is None:
        parser.error("--out is required unless --schema-check is used")
    if args.commit is None:
        parser.error("--commit is required when normalizing")
    nct_ids = [line.strip() for line in args.nct_ids.read_text().splitlines() if line.strip()] if args.nct_ids else None
    report = normalize(args.source, args.out, args.commit, nct_ids)
    print(json.dumps({"counts": report["counts"], "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
