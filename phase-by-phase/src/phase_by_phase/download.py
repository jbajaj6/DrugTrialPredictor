"""Download a reproducible sample from the public ClinicalTrials.gov API v2."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import pandas as pd
import requests


API_URL = "https://clinicaltrials.gov/api/v2/studies"
DEFAULT_QUERY = (
    "AREA[StudyType]INTERVENTIONAL AND "
    "AREA[InterventionType]DRUG AND "
    "(AREA[Phase]PHASE1 OR AREA[Phase]PHASE2 OR AREA[Phase]PHASE3) AND "
    "AREA[StartDate]RANGE[01/01/2005, 12/31/2019]"
)


def _get(mapping: dict, *keys, default=None):
    value = mapping
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def download_studies(max_studies: int = 1000, query: str = DEFAULT_QUERY) -> list[dict]:
    """Download up to ``max_studies`` studies with API pagination."""
    studies: list[dict] = []
    token = None
    session = requests.Session()
    while len(studies) < max_studies:
        params = {
            "query.term": query,
            "format": "json",
            "pageSize": min(100, max_studies - len(studies)),
        }
        if token:
            params["pageToken"] = token
        response = session.get(API_URL, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        page = payload.get("studies", [])
        if not page:
            break
        studies.extend(page)
        token = payload.get("nextPageToken")
        if not token:
            break
    return studies[:max_studies]


def flatten_studies(studies: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return trial metadata and long-form trial/drug/condition mappings."""
    trials: list[dict] = []
    mappings: list[dict] = []
    for study in studies:
        protocol = study.get("protocolSection", {})
        ident = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        design = protocol.get("designModule", {})
        conditions = protocol.get("conditionsModule", {}).get("conditions", [])
        interventions = protocol.get("armsInterventionsModule", {}).get("interventions", [])
        nct_id = ident.get("nctId")
        phases = design.get("phases", [])
        trials.append(
            {
                "nct_id": nct_id,
                "overall_status": status.get("overallStatus"),
                "start_date": _get(status, "startDateStruct", "date"),
                "completion_date": _get(status, "completionDateStruct", "date"),
                "first_submitted_date": status.get("studyFirstSubmitDate"),
                "phase": "/".join(phases) if phases else None,
                "enrollment": _get(design, "enrollmentInfo", "count"),
                "enrollment_type": _get(design, "enrollmentInfo", "type"),
            }
        )
        drugs = [i.get("name") for i in interventions if i.get("type") == "DRUG"]
        for drug in drugs:
            for condition in conditions:
                mappings.append(
                    {
                        "nct_id": nct_id,
                        "drug_name": drug,
                        "condition_name": condition,
                        # API MeSH terms are study-level and cannot be safely paired
                        # one-to-one with raw conditions; controlled mapping comes later.
                        "mesh_term": None,
                    }
                )
    return pd.DataFrame(trials), pd.DataFrame(mappings)


def save_download(studies: list[dict], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "studies.json.gz"
    with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
        json.dump(studies, handle)
    trials, mappings = flatten_studies(studies)
    trials_path = out_dir / "trials.parquet"
    mappings_path = out_dir / "trial_program_inputs.parquet"
    trials.to_parquet(trials_path, index=False)
    mappings.to_parquet(mappings_path, index=False)
    return trials_path, mappings_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-studies", type=int, default=1000)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--out", type=Path, default=Path("data/raw/phase_by_phase"))
    args = parser.parse_args()
    studies = download_studies(args.max_studies, args.query)
    trials_path, mappings_path = save_download(studies, args.out)
    print(f"downloaded {len(studies):,} studies")
    print(f"trial metadata: {trials_path}")
    print(f"drug-condition mappings: {mappings_path}")


if __name__ == "__main__":
    main()
