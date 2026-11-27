"""Preserve versioned Anamnesis results as separate, reviewable child tables.

Only publicly posted versions before 2024 enter these development cleaning
outputs. Later outcome values are not inspected or emitted. This module does
not decide trial success, parse p-values, or build model features.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import duckdb
import pyarrow.parquet as pq


COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
KEY = {"nct_id", "nct_version"}
REQUIRED = {
    "results_outcome_measures": {"outcome_ord", "type", "title", "description"},
    "results_outcome_analyses": {"outcome_ord", "analysis_ord", "p_value", "p_value_comment"},
    "results_outcome_groups": {"outcome_ord", "group_id", "title"},
    "results_outcome_measurements": {"outcome_ord", "measurement_ord", "group_id", "value"},
    "results_outcome_analysis_groups": {"outcome_ord", "analysis_ord", "group_id"},
    "results_pflow": {"pre_assignment_details", "recruitment_details"},
    "results_pflow_groups": {"group_id", "title"},
    "results_pflow_periods": {"period_ord", "title"},
    "results_adverse_event_groups": {"group_id", "title"},
    "results_adverse_serious_events": {"event_ord", "term"},
    "results_adverse_other_events": {"event_ord", "term"},
    "results_adverse_serious_event_stats": {"event_ord", "stat_ord", "group_id", "num_affected", "num_events"},
    "results_adverse_other_event_stats": {"event_ord", "stat_ord", "group_id", "num_affected", "num_events"},
}
CORE_REQUIRED = KEY | {"last_update_post_date", "is_obsolete"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(source: Path) -> dict[str, dict]:
    """Validate only schemas and Parquet footer counts, not result values."""
    tables = ["core"] + sorted(p.name for p in source.glob("results_*") if p.is_dir())
    if len(tables) == 1:
        raise FileNotFoundError("No results_* directories in source")
    missing_tables = sorted(set(REQUIRED) - set(tables))
    if missing_tables:
        raise ValueError(f"Missing required results tables: {missing_tables}")
    report = {}
    for table in tables:
        parts = sorted((source / table).glob("*.parquet"))
        if not parts:
            raise FileNotFoundError(f"No Parquet parts for {table}")
        schemas = [pq.read_schema(part) for part in parts]
        if any(not schema.equals(schemas[0]) for schema in schemas[1:]):
            raise ValueError(f"Inconsistent Parquet part schema in {table}")
        names = set(schemas[0].names)
        needed = CORE_REQUIRED if table == "core" else KEY | REQUIRED.get(table, set())
        missing = sorted(needed - names)
        if missing:
            raise ValueError(f"Incompatible {table} schema; missing {missing}")
        if any(name.startswith("adapter_") for name in names):
            raise ValueError(f"Reserved adapter_ column in {table}")
        report[table] = {"parts": [str(p.relative_to(source)) for p in parts],
                         "source_rows": sum(pq.ParquetFile(p).metadata.num_rows for p in parts),
                         # Do not inventory sealed core outcome/status fields.
                         "columns": schemas[0].names if table != "core" else sorted(CORE_REQUIRED)}
    return report


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parquet_expr(source: Path, parts: list[str]) -> str:
    paths = ", ".join(_literal(str(source / p)) for p in parts)
    return f"read_parquet([{paths}], filename=true)"


def _count(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0])


def normalize(source: Path, out: Path, commit: str, nct_ids: list[str] | None = None) -> dict:
    """Stream pre-2024 public result versions to one Parquet file per source table.

    All source columns survive unchanged. An inner version join excludes
    unposted, unlinked and 2024+ versions from this development output; the
    immutable full raw download retains them for later, separately gated use.
    """
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError("Source commit must be an immutable 40-character hex hash")
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite: {out}")
    if nct_ids is not None and (not nct_ids or len(nct_ids) != len(set(nct_ids))):
        raise ValueError("NCT selection must be a nonempty unique list")
    source = source.resolve()
    report = inventory(source)
    con = duckdb.connect()
    core = _parquet_expr(source, report["core"]["parts"])
    # Project only keys and posting dates from core. Outcome/status payloads
    # never enter this audit, including for sealed 2024+ versions.
    con.execute("CREATE TEMP TABLE core_dates AS SELECT nct_id, nct_version, "
                "CAST(last_update_post_date AS DATE) AS post_date, "
                "is_obsolete FROM " + core)
    if _count(con, "SELECT count(*) FROM (SELECT nct_id, nct_version FROM core_dates "
               "GROUP BY 1,2 HAVING count(*) > 1)"):
        raise ValueError("Duplicate core version keys")
    con.execute("CREATE TEMP TABLE public_versions AS SELECT nct_id, nct_version, "
                "post_date AS adapter_version_public_date, "
                "is_obsolete AS adapter_core_is_obsolete FROM core_dates "
                "WHERE post_date IS NOT NULL AND post_date < DATE '2024-01-01'")
    if nct_ids is not None:
        con.execute("CREATE TEMP TABLE selected_ncts(nct_id VARCHAR)")
        con.executemany("INSERT INTO selected_ncts VALUES (?)", [(n,) for n in nct_ids])
        con.execute("DELETE FROM public_versions WHERE nct_id NOT IN (SELECT nct_id FROM selected_ncts)")
    out.mkdir(parents=True)
    counts = {}
    output_hashes = {}
    guide = []
    for table, item in report.items():
        if table == "core":
            continue
        # The version join is exact. filename is added by DuckDB and is not a
        # replacement for a source ordinal; source ordinals remain untouched.
        scan = _parquet_expr(source, item["parts"])
        output = out / f"{table}_clean.parquet"
        query = ("SELECT r.* EXCLUDE(filename), r.filename AS adapter_source_file, "
                 "v.adapter_version_public_date, v.adapter_core_is_obsolete, "
                 f"{_literal(commit)} AS adapter_source_commit, "
                 f"{_literal(table)} AS adapter_source_table "
                 f"FROM {scan} AS r INNER JOIN public_versions AS v "
                 "ON r.nct_id=v.nct_id AND r.nct_version=v.nct_version")
        con.execute(f"COPY ({query}) TO {_literal(str(output))} (FORMAT PARQUET, COMPRESSION ZSTD)")
        con.execute(f"CREATE VIEW {_literal(table)} AS SELECT * FROM read_parquet({_literal(str(output))})")
        rows = _count(con, f"SELECT count(*) FROM {_literal(table)}")
        # Compare with an independent scan of source keys only.  This audit
        # never materializes sealed result payloads in Python or the output.
        expected = _count(con, f"SELECT count(*) FROM (SELECT r.nct_id, r.nct_version "
                          f"FROM {scan} r INNER JOIN public_versions v "
                          "ON r.nct_id=v.nct_id AND r.nct_version=v.nct_version)")
        if rows != expected:
            raise AssertionError(f"Source-row loss in {table}: {rows} != {expected}")
        # This query projects only child keys. It cannot expose p-values,
        # event counts, comments or any other sealed result payload.
        selected_where = (" WHERE nct_id IN (SELECT nct_id FROM selected_ncts)"
                          if nct_ids is not None else "")
        audit = con.execute(
            "SELECT count(*) FILTER (WHERE c.nct_id IS NULL), "
            "count(*) FILTER (WHERE c.nct_id IS NOT NULL AND c.post_date IS NULL), "
            "count(*) FILTER (WHERE c.post_date >= DATE '2024-01-01'), "
            "count(*) FILTER (WHERE c.post_date < DATE '2024-01-01') "
            f"FROM (SELECT nct_id,nct_version FROM {scan}{selected_where}) r LEFT JOIN core_dates c "
            "ON r.nct_id=c.nct_id AND r.nct_version=c.nct_version"
        ).fetchone()
        missing_core, unposted, sealed, eligible = map(int, audit)
        selected_rows = missing_core + unposted + sealed + eligible
        if selected_rows > item["source_rows"] or eligible != rows or (nct_ids is None and selected_rows != item["source_rows"]):
            raise AssertionError(f"Source-row partition mismatch in {table}")
        counts[table] = {"eligible_public_rows": rows, "source_rows_all_dates": item["source_rows"],
                         "selected_source_rows": selected_rows,
                         "unselected_nct_rows": item["source_rows"] - selected_rows,
                         "missing_core_version_rows": missing_core,
                         "unposted_core_version_rows": unposted,
                         "posted_2024_or_later_rows": sealed,
                         "excluded_from_development_rows": missing_core + unposted + sealed,
                         "public_version_keys": _count(con, f"SELECT count(*) FROM "
                            f"(SELECT nct_id,nct_version FROM {_literal(table)} GROUP BY 1,2)")}
        natural = [c for c in item["columns"] if c in ("nct_id", "nct_version", "group_id")
                   or c.endswith("_ord")]
        if len(natural) > 2:
            group_by = ",".join('"' + c + '"' for c in natural)
            counts[table]["duplicate_natural_key_groups"] = _count(
                con, f"SELECT count(*) FROM (SELECT {group_by} FROM {_literal(table)} "
                     f"GROUP BY {group_by} HAVING count(*) > 1)")
        output_hashes[output.name] = sha256(output)
        for column in pq.read_schema(output).names:
            guide.append({"table": table, "column": column,
                          "origin": "adapter" if column.startswith("adapter_") else "source",
                          "description": _description(column)})
    # Referential integrity is reported, not used to drop or fabricate rows.
    references = [
        ("results_outcome_analyses", "results_outcome_measures", ["outcome_ord"]),
        ("results_outcome_groups", "results_outcome_measures", ["outcome_ord"]),
        ("results_outcome_measurements", "results_outcome_groups", ["outcome_ord", "group_id"]),
        ("results_outcome_analysis_groups", "results_outcome_analyses", ["outcome_ord", "analysis_ord"]),
        ("results_outcome_analysis_groups", "results_outcome_groups", ["outcome_ord", "group_id"]),
        ("results_pflow_milestones", "results_pflow_periods", ["period_ord"]),
        ("results_pflow_milestone_achievements", "results_pflow_milestones", ["period_ord", "milestone_ord"]),
        ("results_pflow_milestone_achievements", "results_pflow_groups", ["group_id"]),
        ("results_pflow_drop_withdraw_reasons", "results_pflow_drop_withdraws", ["period_ord", "dw_ord"]),
        ("results_pflow_drop_withdraw_reasons", "results_pflow_groups", ["group_id"]),
        ("results_adverse_serious_event_stats", "results_adverse_serious_events", ["event_ord"]),
        ("results_adverse_serious_event_stats", "results_adverse_event_groups", ["group_id"]),
        ("results_adverse_other_event_stats", "results_adverse_other_events", ["event_ord"]),
        ("results_adverse_other_event_stats", "results_adverse_event_groups", ["group_id"]),
    ]
    for child, parent, columns in references:
        if child not in counts or parent not in counts:
            continue
        terms = " AND ".join(f"p.{column}=c.{column}" for column in ["nct_id", "nct_version"] + columns)
        unresolved = _count(con, f"SELECT count(*) FROM {_literal(child)} c WHERE NOT EXISTS "
                            f"(SELECT 1 FROM {_literal(parent)} p WHERE {terms})")
        counts[child].setdefault("unresolved_references", {})[parent] = unresolved
    # CSV is deliberately metadata only. No raw patient or sealed outcome text
    # is duplicated in a human-readable sidecar.
    guide_path = out / "column_guide.csv"
    with guide_path.open("w") as stream:
        stream.write("table,column,origin,description\n")
        for row in guide:
            stream.write(",".join(_csv(row[k]) for k in ("table", "column", "origin", "description")) + "\n")
    output_hashes[guide_path.name] = sha256(guide_path)
    manifest = {"status": "cleaning_only_no_labels_or_models",
                "scope": "publicly posted versions before 2024 only; later and unposted source remains immutable raw",
                "source_root": str(source), "source_commit": commit,
                "selected_nct_count": len(nct_ids) if nct_ids is not None else None,
                "source_files_sha256": {part: sha256(source / part)
                                        for item in report.values() for part in item["parts"]},
                "code_sha256": sha256(Path(__file__)), "inventory": report,
                "counts": counts, "output_files_sha256": output_hashes,
                "interpretation": "Raw p text is not a success label. Event counts, people affected, and people at risk are distinct. Unresolved references are retained."}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    con.close()
    return manifest


def _csv(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _description(column: str) -> str:
    return {
        "nct_id": "Trial identifier; never join without nct_version.",
        "nct_version": "Historical source version; join all child tables on both keys.",
        "outcome_ord": "Outcome position within this trial version.",
        "analysis_ord": "Analysis position within this outcome and version.",
        "group_id": "Result group identifier; meaning is table- and version-specific.",
        "p_value": "Raw reported p-value text; not parsed or labeled by this cleaner.",
        "num_events": "Number of events; not necessarily number of affected participants.",
        "num_affected": "Number of affected participants as reported.",
        "num_at_risk": "Reported denominator or at-risk count; preserve separately.",
        "adapter_source_file": "Source Parquet part path supplied by DuckDB filename metadata.",
        "adapter_source_commit": "Pinned Anamnesis repository commit.",
        "adapter_source_table": "Original results_* table name.",
        "adapter_version_public_date": "Public posting date of the exact core version; no event-day inference.",
        "adapter_core_is_obsolete": "Core obsolete flag on the exact source version.",
    }.get(column, "Unmodified source field; consult pinned dataset card/schema.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--nct-ids", type=Path, help="Optional newline-delimited development pilot IDs")
    args = parser.parse_args()
    ids = [s.strip() for s in args.nct_ids.read_text().splitlines() if s.strip()] if args.nct_ids else None
    report = normalize(args.source, args.out, args.commit, ids)
    print(json.dumps({"out": str(args.out), "tables": len(report["counts"]),
                      "eligible_rows": sum(x["eligible_public_rows"] for x in report["counts"].values())}))


if __name__ == "__main__":
    main()
