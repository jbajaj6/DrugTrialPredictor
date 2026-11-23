"""Resumable, checksummed ClinicalTrials.gov extraction and offline replay."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ",".join([
    "IdentificationModule", "StatusModule", "SponsorCollaboratorsModule",
    "DesignModule", "ArmsInterventionsModule", "ConditionsModule", "HasResults",
])


def study_query(cutoff: str) -> str:
    end = date.fromisoformat(cutoff).strftime("%m/%d/%Y")
    return (
        "AREA[StudyType]INTERVENTIONAL AND "
        "(AREA[InterventionType]DRUG OR AREA[InterventionType]BIOLOGICAL) AND "
        "(AREA[Phase]EARLY_PHASE1 OR AREA[Phase]PHASE1 OR "
        "AREA[Phase]PHASE2 OR AREA[Phase]PHASE3) AND "
        f"AREA[StartDate]RANGE[01/01/2005,{end}]"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_snapshot(directory: Path) -> tuple[list[dict], dict]:
    """Verify bytes, pagination counts and unique IDs before returning a snapshot."""
    manifest = json.loads((directory / "manifest.json").read_text())
    studies = []
    for page in manifest["pages"]:
        path = directory / page["file"]
        if path.parent.resolve() != directory.resolve():
            raise ValueError("Manifest page escapes snapshot directory")
        if sha256(path) != page["sha256"]:
            raise ValueError(f"Checksum mismatch: {path.name}")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            batch = json.load(handle)["studies"]
        if len(batch) != page["records"]:
            raise ValueError("Page count mismatch")
        studies.extend(batch)
    ids = [s.get("protocolSection", {}).get("identificationModule", {}).get("nctId") for s in studies]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Missing or duplicate source NCT IDs; snapshot is not complete")
    if len(studies) != manifest["records"]:
        raise ValueError("Manifest record count mismatch")
    if manifest["complete"] and len(studies) != manifest["total_count"]:
        raise ValueError("Complete snapshot count disagrees with API total")
    return studies, manifest


def download_snapshot(directory: Path, cutoff: str, max_studies: int | None = None) -> dict:
    """Persist each page and resume interruptions. None downloads the entire query."""
    if max_studies is not None and max_studies < 1:
        raise ValueError("max_studies must be positive or None")
    params = {"query.term": study_query(cutoff), "format": "json", "pageSize": 1000,
              "countTotal": "true", "sort": "StudyFirstPostDate:asc", "fields": FIELDS}
    directory.mkdir(parents=True, exist_ok=True)
    mpath = directory / "manifest.json"
    if mpath.exists():
        _, manifest = load_snapshot(directory)
        if manifest["params"] != params or manifest["cutoff"] != cutoff:
            raise ValueError("Existing snapshot has different query; choose a new directory")
        if manifest["complete"]:
            return manifest
    else:
        if list(directory.iterdir()):
            raise ValueError("Nonempty snapshot directory without manifest")
        manifest = {"schema_version": 1, "api": API, "params": params, "cutoff": cutoff,
                    "retrieval_started_utc": datetime.now(timezone.utc).isoformat(),
                    "pages": [], "records": 0, "total_count": None, "next_page_token": None,
                    "complete": False, "sampling": "complete query requested; not a random sample"}
        _save(mpath, manifest)
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"], respect_retry_after_header=True)
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        while not manifest["complete"]:
            remaining = None if max_studies is None else max_studies - manifest["records"]
            if remaining is not None and remaining <= 0:
                break
            query = dict(params)
            if remaining is not None:
                query["pageSize"] = min(1000, remaining)
            if manifest["next_page_token"]:
                query["pageToken"] = manifest["next_page_token"]
            response = session.get(API, params=query, timeout=(15, 120))
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload.get("studies"), list):
                raise ValueError("API response missing study list")
            total = payload.get("totalCount")
            if total is not None:
                if manifest["total_count"] not in (None, total):
                    raise ValueError("Registry total changed mid-download; use a new snapshot")
                manifest["total_count"] = total
            if not payload["studies"] and payload.get("nextPageToken"):
                raise ValueError("Empty page with continuation token")
            next_token = payload.get("nextPageToken")
            if next_token and next_token == manifest["next_page_token"]:
                raise ValueError("Repeated pagination token")
            name = f"page_{len(manifest['pages']):05d}.json.gz"
            path = directory / name
            if path.exists():
                raise ValueError(f"Unmanifested page exists: {path}; preserve it and use a new snapshot")
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            manifest["pages"].append({"file": name, "records": len(payload["studies"]),
                                      "sha256": sha256(path), "retrieved_utc": datetime.now(timezone.utc).isoformat()})
            manifest["records"] += len(payload["studies"])
            manifest["next_page_token"] = next_token
            manifest["complete"] = next_token is None and manifest["records"] == manifest["total_count"]
            manifest["retrieval_updated_utc"] = datetime.now(timezone.utc).isoformat()
            _save(mpath, manifest)
            print(f"Downloaded {manifest['records']:,}/{manifest['total_count']:,} records", flush=True)
            if next_token is None:
                if not manifest["complete"]:
                    raise ValueError("Pagination ended before API total was reached")
                break
            time.sleep(0.1)
    load_snapshot(directory)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--max-studies", type=int, default=None)
    args = parser.parse_args()
    result = download_snapshot(args.out, args.cutoff, args.max_studies)
    print(json.dumps({k: v for k, v in result.items() if k not in {"pages", "next_page_token"}}, indent=2))


if __name__ == "__main__":
    main()
