"""Resume checksummed full-record retrieval for source NCT IDs with posted results.

The slim source snapshot omits resultsSection. This enrichment never changes it.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from .acquire import sha256


API = "https://clinicaltrials.gov/api/v2/studies"
NCT = re.compile(r"NCT\d{8}\Z")


def eligible_ids(trials_path: Path) -> list[str]:
    trials = pd.read_parquet(trials_path, columns=["nct_id", "has_results"])
    ids = trials.loc[trials.has_results.eq(True), "nct_id"].astype(str).tolist()
    if any(not NCT.fullmatch(x) for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Invalid or duplicate eligible NCT IDs")
    return sorted(ids)


def development_sample_ids(trials_path: Path, per_phase_year: int,
                           before_year: int = 2024) -> list[str]:
    """Deterministic phase/year coverage without reading any outcome label."""
    if per_phase_year < 1:
        raise ValueError("per_phase_year must be positive")
    trials = pd.read_parquet(trials_path, columns=["nct_id", "has_results", "phase", "start_date"])
    trials = trials.loc[trials.has_results.eq(True) &
                        trials.phase.isin(["PHASE1", "PHASE2", "PHASE3"])].copy()
    trials["start_year"] = pd.to_numeric(trials.start_date.astype("string").str.slice(0, 4), errors="coerce")
    trials = trials.loc[trials.start_year.lt(before_year)]
    selected = (trials.sort_values("nct_id").groupby(["phase", "start_year"], sort=True)
                .head(per_phase_year))
    ids = selected.nct_id.astype(str).tolist()
    if any(not NCT.fullmatch(x) for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("Invalid or duplicate development sample IDs")
    return sorted(ids)


def _write_json(path: Path, obj: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def retrieve(ids: list[str], output: Path, *, session: requests.Session | None = None) -> dict:
    """Get exactly the supplied NCT IDs; existing records are hash-verified.

    A failed request leaves its ID pending. The manifest is updated after every
    successful record so interruption is safe. Selection must be done upstream.
    """
    if not ids or any(not NCT.fullmatch(x) for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Supply unique, canonical NCT IDs")
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    requested = sorted(ids)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["requested_ids"] != requested:
            raise ValueError("Existing detail snapshot has a different ID set")
    else:
        if any(output.iterdir()):
            raise ValueError("Nonempty detail directory without manifest")
        manifest = {"schema_version": 1, "api": API, "requested_ids": requested,
                    "retrieval_started_utc": datetime.now(timezone.utc).isoformat(),
                    "records": {}, "complete": False}
        _write_json(manifest_path, manifest)
    for nct_id, entry in manifest["records"].items():
        path = output / entry["file"]
        if path.parent.resolve() != output.resolve() or sha256(path) != entry["sha256"]:
            raise ValueError(f"Detail hash or path mismatch for {nct_id}")
    own_session = session is None
    session = session or requests.Session()
    try:
        for nct_id in requested:
            if nct_id in manifest["records"]:
                continue
            response = session.get(f"{API}/{nct_id}", params={"format": "json"}, timeout=(15, 90))
            response.raise_for_status()
            study = response.json()
            actual_id = study.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
            if actual_id != nct_id:
                raise ValueError(f"Unexpected NCT ID: {actual_id} instead of {nct_id}")
            filename = f"{nct_id}.json.gz"
            path = output / filename
            if path.exists():
                raise ValueError(f"Unmanifested existing file: {path}")
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                json.dump(study, handle, ensure_ascii=False)
            manifest["records"][nct_id] = {"file": filename, "sha256": sha256(path),
                                           "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                                           "has_results_section": "resultsSection" in study}
            manifest["complete"] = len(manifest["records"]) == len(requested)
            _write_json(manifest_path, manifest)
    finally:
        if own_session:
            session.close()
    return manifest


def load_details(directory: Path) -> tuple[list[dict], dict]:
    manifest = json.loads((directory / "manifest.json").read_text())
    if set(manifest["records"]) - set(manifest["requested_ids"]):
        raise ValueError("Manifest contains unrequested records")
    studies = []
    for nct_id in sorted(manifest["records"]):
        entry = manifest["records"][nct_id]
        path = directory / entry["file"]
        if path.parent.resolve() != directory.resolve() or sha256(path) != entry["sha256"]:
            raise ValueError(f"Detail hash or path mismatch for {nct_id}")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            study = json.load(handle)
        if study.get("protocolSection", {}).get("identificationModule", {}).get("nctId") != nct_id:
            raise ValueError(f"Detail NCT mismatch for {nct_id}")
        studies.append(study)
    if manifest["complete"] != (len(studies) == len(manifest["requested_ids"])):
        raise ValueError("Detail completeness mismatch")
    return studies, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", nargs="*", default=None,
                        help="optional explicit NCT IDs for a linked-trial pilot")
    parser.add_argument("--per-phase-year", type=int, default=None,
                        help="deterministic result-bearing sample per pure phase and start year")
    parser.add_argument("--before-year", type=int, default=2024,
                        help="exclude later start years from a development sample")
    args = parser.parse_args()
    ids = eligible_ids(args.trials)
    if args.per_phase_year is not None:
        ids = development_sample_ids(args.trials, args.per_phase_year, args.before_year)
    if args.ids:
        unknown = set(args.ids) - set(ids)
        if unknown:
            parser.error(f"IDs are not result-bearing source trials: {sorted(unknown)}")
        ids = sorted(set(args.ids))
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        ids = ids[:args.limit]
    result = retrieve(ids, args.out)
    print(json.dumps({"requested": len(ids), "retrieved": len(result["records"]),
                      "complete": result["complete"]}, indent=2))


if __name__ == "__main__":
    main()
