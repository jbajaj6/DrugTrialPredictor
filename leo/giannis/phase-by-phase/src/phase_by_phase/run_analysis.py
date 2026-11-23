"""Download/replay -> organize -> audit -> longitudinal analysis -> report."""
from __future__ import annotations

import argparse
import gc
import importlib.metadata
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from .acquire import download_snapshot, load_snapshot, sha256
from .analysis import build_analysis
from .audit import audit_tables, review_sample
from .organize import build_tables
from .report import write_report


def run(snapshot: Path, output: Path, horizon_years: int = 5, bootstrap: int = 300) -> dict:
    studies, manifest = load_snapshot(snapshot)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is not empty; choose a new directory to preserve previous results")
    output.mkdir(parents=True, exist_ok=True)
    print(f"Organizing {len(studies):,} studies", flush=True)
    tables = build_tables(studies)
    # Raw JSON is large; release it before the DataFrame audits and models.
    del studies
    gc.collect()
    for name, frame in tables.items():
        frame.to_parquet(output / f"{name}.parquet", index=False)
        print(f"  {name}: {len(frame):,} rows", flush=True)
    audit = audit_tables(tables, manifest)
    (output / "quality_audit.json").write_text(json.dumps(audit, indent=2, allow_nan=False) + "\n")
    review_sample(tables).to_parquet(output / "linkage_review_queue.parquet", index=False)
    source_dir = Path(__file__).parent
    provenance = {"run_utc": datetime.now(timezone.utc).isoformat(),
                  "source_manifest": str(snapshot / "manifest.json"),
                  "source_manifest_sha256": sha256(snapshot / "manifest.json"),
                  "cutoff": manifest["cutoff"], "records": manifest["records"],
                  "query_complete": manifest["complete"], "python": platform.python_version(),
                  "horizon_years": horizon_years, "bootstrap_replicates": bootstrap,
                  "packages": {p: importlib.metadata.version(p) for p in ["pandas", "numpy", "scikit-learn", "requests", "pyarrow"]},
                  "source_code_sha256": {p.name: sha256(p) for p in sorted(source_dir.glob("*.py"))}}
    (output / "run_manifest.json").write_text(json.dumps(provenance, indent=2) + "\n")
    if audit["hard_fail"]:
        raise ValueError("Data audit failed; inspect quality_audit.json. Modeling was not run.")
    print("Building dated snapshots and assessing model support", flush=True)
    analysis = build_analysis(tables, manifest["cutoff"], output, horizon_years, bootstrap,
                              data_complete=manifest["complete"])
    write_report(output, tables, manifest, audit, analysis)
    print(f"Report: {output / 'REPORT.md'}", flush=True)
    return {"audit": audit, "analysis": analysis}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--cutoff", default="2026-11-19")
    parser.add_argument("--max-studies", type=int, default=None,
                        help="optional pilot cap; incomplete datasets never train models")
    parser.add_argument("--horizon-years", type=int, default=5)
    parser.add_argument("--bootstrap", type=int, default=300)
    args = parser.parse_args()
    if args.download:
        download_snapshot(args.snapshot, args.cutoff, args.max_studies)
    run(args.snapshot, args.out, args.horizon_years, args.bootstrap)


if __name__ == "__main__":
    main()
