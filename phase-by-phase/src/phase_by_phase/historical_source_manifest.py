"""Inventory an immutable local Anamnesis archive without reading row values."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import pyarrow.parquet as pq


COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(source: Path, commit: str) -> dict:
    if not COMMIT.fullmatch(commit):
        raise ValueError("Expected a pinned 40-character source commit")
    source = source.resolve()
    tables = {}
    total_files = total_rows = total_bytes = 0
    for directory in sorted(source.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        parts = sorted(directory.glob("*.parquet"))
        if not parts:
            continue
        files = []
        first_schema = None
        for part in parts:
            parquet = pq.ParquetFile(part)
            schema = parquet.schema_arrow
            if first_schema is None:
                first_schema = schema
            elif not first_schema.equals(schema):
                raise ValueError(f"Schema drift among parts of {directory.name}")
            item = {"relative_path": part.relative_to(source).as_posix(),
                    "rows": parquet.metadata.num_rows, "bytes": part.stat().st_size,
                    "sha256": _hash(part)}
            files.append(item)
            total_files += 1
            total_rows += item["rows"]
            total_bytes += item["bytes"]
        # Core contains sealed target-status fields. Hash its schema, but do
        # not copy those column names into a development-side manifest.
        schema_bytes = first_schema.serialize().to_pybytes()
        tables[directory.name] = {"files": files,
                                  "rows": sum(item["rows"] for item in files),
                                  "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
                                  "columns": first_schema.names if directory.name != "core" else None}
    if not tables:
        raise FileNotFoundError(f"No Parquet tables in {source}")
    return {"source_root": str(source), "source_commit": commit,
            "inspection": "Parquet footer/schema/bytes only; no row values or sealed outcomes read",
            "dataset": "anamnesis-data/clinical_trials_history",
            "license": "CC BY-NC 4.0; attribute Anamnesis Data and ClinicalTrials.gov",
            "totals": {"tables": len(tables), "files": total_files,
                       "footer_rows_including_repeated_versions_and_child_rows": total_rows,
                       "parquet_bytes": total_bytes}, "tables": tables}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"Refusing to overwrite: {args.out}")
    report = inventory(args.source, args.commit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["totals"]))


if __name__ == "__main__":
    main()
