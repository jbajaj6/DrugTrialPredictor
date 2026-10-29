"""NIH RePORTER / ExPORTER funding features (owner: Leo).

Inputs (bulk CSVs, no account) from https://reporter.nih.gov/exporter, unzipped into data/raw/nih/:
  - ClinicalStudies file: links CORE_PROJECT_NUM -> ClinicalTrials.gov ID
  - Projects files (one per fiscal year): CORE_PROJECT_NUM, FY, TOTAL_COST, ACTIVITY,
    ADMINISTERING_IC, PROJECT_START, ...

Leakage rule: only grant-years with FY <= trial start year count.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from dtp import config

NIH_DIR = config.RAW / "nih"


def load_clinical_studies(path: Path | None = None) -> pd.DataFrame:
    path = path or next(NIH_DIR.glob("*ClinicalStudies*.csv"))
    df = pd.read_csv(path, encoding="latin-1")
    df = df.rename(columns={"ClinicalTrials.gov ID": "nct_id", "Core Project Number": "core_project_num"})
    df.columns = [c.lower() for c in df.columns]
    return df[["core_project_num", "nct_id"]].dropna().drop_duplicates()


def load_projects(paths: list[Path] | None = None) -> pd.DataFrame:
    paths = paths or sorted(NIH_DIR.glob("RePORTER_PRJ_C_FY*.csv"))
    cols = ["CORE_PROJECT_NUM", "FY", "TOTAL_COST", "ACTIVITY", "ADMINISTERING_IC"]
    frames = [pd.read_csv(p, usecols=cols, encoding="latin-1", low_memory=False) for p in paths]
    df = pd.concat(frames, ignore_index=True)
    df.columns = [c.lower() for c in df.columns]
    return df


def funding_features(trials: pd.DataFrame, links: pd.DataFrame, projects: pd.DataFrame) -> pd.DataFrame:
    """Per-trial funding features using only grant-years up to the trial's start year."""
    t = trials[["nct_id", "start_date"]].copy()
    t["start_year"] = pd.to_datetime(t["start_date"]).dt.year
    g = t.merge(links, on="nct_id").merge(projects, on="core_project_num")
    g = g[g["fy"] <= g["start_year"]]
    agg = g.groupby("nct_id").agg(
        nih_n_grants=("core_project_num", "nunique"),
        nih_total_cost=("total_cost", "sum"),
        nih_top_activity=("activity", lambda s: s.mode().iat[0] if not s.mode().empty else None),
        nih_top_ic=("administering_ic", lambda s: s.mode().iat[0] if not s.mode().empty else None),
    ).reset_index()
    out = trials[["nct_id"]].merge(agg, on="nct_id", how="left")
    out["has_nih_grant"] = out["nih_n_grants"].notna().astype(int)
    out[["nih_n_grants", "nih_total_cost"]] = out[["nih_n_grants", "nih_total_cost"]].fillna(0)
    return out
