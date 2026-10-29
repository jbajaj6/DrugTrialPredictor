"""NIH funding features: grants linked to each trial, measured before the trial started.

Sources (both public, no account):
  - ExPORTER Clinical Studies file: links NIH core project numbers to ClinicalTrials.gov IDs
    (https://reporter.nih.gov/exporter/clinicalstudies)
  - RePORTER API v2 (https://api.reporter.nih.gov): one row per grant per fiscal year, with
    award amount, activity code (R01, U10, ...) and funding institute (NCI, NHLBI, ...)

    python -m dtp.ingest.nih            # download links + grant-years (resumable; cached per batch)

Leakage rule: only grant-years with fiscal_year <= the trial's start year count. The link itself is
reported by grantees in progress reports, so `has_nih_link` alone may be weakly outcome-dependent.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from dtp import config

NIH_DIR = config.RAW / "nih"
LINKS_CSV = NIH_DIR / "ClinicalStudies.csv"
LINKS_URL = "https://reporter.nih.gov/services/exporter/DownloadFromDocService?DocType=EXPCS&KeyId=1"
API_URL = "https://api.reporter.nih.gov/v2/projects/search"
API_FIELDS = ["CoreProjectNum", "FiscalYear", "AwardAmount", "ActivityCode", "AgencyIcAdmin"]
COOPERATIVE = ("U10", "UG1", "U01", "U24", "UM1")  # cooperative-agreement / network grants


def download_links(path: Path = LINKS_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(LINKS_URL, timeout=300)
    r.raise_for_status()
    path.write_bytes(r.content)
    return path


def load_links(path: Path = LINKS_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="latin-1")
    df = df.rename(columns={"Core Project Number": "core_project_num", "ClinicalTrials.gov ID": "nct_id"})
    return df[["core_project_num", "nct_id"]].dropna().drop_duplicates()


def _fetch_batch(core_nums: list[str]) -> list[dict]:
    rows, offset = [], 0
    while True:
        body = {"criteria": {"project_nums": core_nums}, "include_fields": API_FIELDS,
                "offset": offset, "limit": 500}
        r = requests.post(API_URL, json=body, timeout=120)
        r.raise_for_status()
        res = r.json()
        rows += res["results"]
        offset += 500
        time.sleep(1)  # RePORTER asks for at most one request per second
        if offset >= res["meta"]["total"] or offset >= 14_500:  # API caps offset at 14,999
            return rows


def fetch_grant_years(core_nums: list[str], cache: Path = NIH_DIR / "api", batch: int = 25,
                      max_seconds: float | None = None) -> bool:
    """Download grant-years for `core_nums` into one JSON file per batch. Returns True when done."""
    cache.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    nums = sorted(set(core_nums))
    for i in range(0, len(nums), batch):
        f = cache / f"batch_{i // batch:04d}.json"
        if f.exists():
            continue
        if max_seconds and time.time() - t0 > max_seconds:
            return False
        f.write_text(json.dumps(_fetch_batch(nums[i:i + batch])))
    return True


def load_grant_years(cache: Path = NIH_DIR / "api") -> pd.DataFrame:
    rows = [r for f in sorted(cache.glob("batch_*.json")) for r in json.loads(f.read_text())]
    df = pd.json_normalize(rows)
    df = df.rename(columns={"agency_ic_admin.abbreviation": "ic"})
    return df[["core_project_num", "fiscal_year", "award_amount", "activity_code", "ic"]]


def funding_features(trials: pd.DataFrame, links: pd.DataFrame, grants: pd.DataFrame) -> pd.DataFrame:
    """Per-trial NIH features from grant-years up to the trial's start year."""
    t = trials[["nct_id", "start_date"]].assign(start_year=lambda d: pd.to_datetime(d["start_date"]).dt.year)
    g = t.merge(links, on="nct_id").merge(grants, on="core_project_num")
    g = g[g["fiscal_year"] <= g["start_year"]]
    agg = g.groupby("nct_id").agg(
        nih_n_grants=("core_project_num", "nunique"),
        nih_total_award=("award_amount", "sum"),
        nih_grant_years=("fiscal_year", "nunique"),
        nih_has_r01=("activity_code", lambda s: int((s == "R01").any())),
        nih_has_cooperative=("activity_code", lambda s: int(s.isin(COOPERATIVE).any())),
        nih_top_ic=("ic", lambda s: s.mode().iat[0] if s.notna().any() else None),
    ).reset_index()
    out = trials[["nct_id"]].merge(agg, on="nct_id", how="left")
    out["has_nih_link"] = trials["nct_id"].isin(links["nct_id"]).astype(int).to_numpy()
    out["has_nih_grant"] = out["nih_n_grants"].notna().astype(int)
    for c in ["nih_n_grants", "nih_total_award", "nih_grant_years", "nih_has_r01", "nih_has_cooperative"]:
        out[c] = out[c].fillna(0)
    out["nih_log_award"] = np.log1p(out["nih_total_award"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-seconds", type=float, help="stop after this long; rerun to resume")
    args = ap.parse_args()
    if not LINKS_CSV.exists():
        download_links()
    links = load_links()
    trials = pd.read_parquet(config.INTERIM / "trials_raw.parquet", columns=["nct_id"])
    cores = links.loc[links["nct_id"].isin(trials["nct_id"]), "core_project_num"]
    done = fetch_grant_years(cores.tolist(), max_seconds=args.max_seconds)
    n = len(list((NIH_DIR / "api").glob("batch_*.json")))
    print(f"{cores.nunique():,} core projects linked to pulled trials; {n} batches cached; done={done}")


if __name__ == "__main__":
    main()
