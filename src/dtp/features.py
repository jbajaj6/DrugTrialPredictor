"""Labels and trial-design features from the raw AACT pull.

    python -m dtp.features          # data/interim/trials_raw.parquet -> data/processed/trials.parquet
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from dtp import config

# ---- Feature groups (used by the ablation in dtp.models) ---------------------------------
CATEGORICAL = [
    "phase", "sponsor_class", "allocation", "intervention_model", "masking",
    "primary_purpose", "disease_area", "elig_gender",
]
DESIGN_NUMERIC = [
    "phase_ord", "number_of_arms", "has_dmc", "n_collaborators", "start_year",
    "reg_lag_days", "n_mesh_terms", "n_drug_interventions", "elig_healthy_volunteers",
    "elig_len", "elig_n_inclusion", "elig_n_exclusion", "elig_biomarker",
]
# Can change after start; test models with and without (README "Leakage rules").
POST_START_RISKY = ["n_sites", "n_countries", "has_us_site"]

FEATURE_GROUPS = {
    "design": DESIGN_NUMERIC + CATEGORICAL,
    "sites": POST_START_RISKY,
    # filled in as other owners land their joins:
    "funding": ["has_nih_grant", "nih_n_grants", "nih_total_cost"],
    "hype": ["has_news", "news_count", "news_tone", "wiki_views"],
}

LABEL_COLS = ["completed", "withdrawn", "met_primary"]

_BIOMARKER = re.compile(
    r"\b(?:her2|egfr|alk|braf|kras|brca[12]?|pd-?l1|mutation|biomarker|genotyp\w*|"
    r"express(?:ion|ing)|positive for|amplification|fusion|msi-h|dmmr)\b",
    re.IGNORECASE,
)
_TRUTHY = {"t", "true", "yes", "1", "y"}


def _to_bool(s: pd.Series) -> pd.Series:
    return s.map(lambda v: np.nan if pd.isna(v) else float(str(v).strip().lower() in _TRUTHY))


def _split_criteria(text: str | float) -> tuple[int, int]:
    if not isinstance(text, str):
        return 0, 0
    low = text.lower()
    inc, _, exc = low.partition("exclusion criteria")
    bullets = lambda t: len(re.findall(r"^\s*(?:[-*•]|\d+[.)])\s+", t, flags=re.M))
    return bullets(inc), bullets(exc)


def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["completed"] = (df["overall_status"] == "COMPLETED").astype(int)
    df["withdrawn"] = (df["overall_status"] == "WITHDRAWN").astype(int)
    # Target B: completed trials that report a primary-outcome p-value.
    has_p = df["label_min_primary_p"].notna() & (df["completed"] == 1)
    df["met_primary"] = np.where(has_p, (df["label_min_primary_p"] < 0.05).astype(float), np.nan)
    return df


def add_design_features(df: pd.DataFrame, top_k_disease: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["phase"] = df["phase"].fillna("NA")
    df["phase_ord"] = df["phase"].map(config.PHASE_ORDER)

    sc = df["lead_agency_class"].fillna("OTHER").str.upper()
    df["sponsor_class"] = np.select(
        [sc.eq("INDUSTRY"), sc.isin(["NIH", "U.S. FED", "FED", "OTHER_GOV"])],
        ["INDUSTRY", "GOV"], default="ACADEMIC_OTHER",
    )

    start = pd.to_datetime(df["start_date"])
    df["start_year"] = start.dt.year
    df["reg_lag_days"] = (pd.to_datetime(df["first_submitted_date"]) - start).dt.days

    df["has_dmc"] = _to_bool(df["has_dmc"])
    df["elig_healthy_volunteers"] = _to_bool(df["elig_healthy_volunteers"])
    df["number_of_arms"] = pd.to_numeric(df["number_of_arms"], errors="coerce")

    top = df["mesh_term_first"].value_counts().head(top_k_disease).index
    df["disease_area"] = df["mesh_term_first"].where(df["mesh_term_first"].isin(top), "OTHER").fillna("NONE")

    crit = df["elig_criteria"]
    df["elig_len"] = crit.fillna("").str.len()
    counts = crit.map(_split_criteria)
    df["elig_n_inclusion"] = counts.str[0]
    df["elig_n_exclusion"] = counts.str[1]
    df["elig_biomarker"] = crit.fillna("").str.contains(_BIOMARKER).astype(int)

    for c in ["allocation", "intervention_model", "masking", "primary_purpose", "elig_gender"]:
        df[c] = df[c].fillna("NA").astype(str).str.upper()
    return df


def build(raw: pd.DataFrame) -> pd.DataFrame:
    df = add_design_features(add_labels(raw))
    return df.drop(columns=["elig_criteria"])


def main() -> None:
    raw = pd.read_parquet(config.INTERIM / "trials_raw.parquet")
    df = build(raw)
    out = config.PROCESSED / "trials.parquet"
    df.to_parquet(out, index=False)
    print(f"wrote {len(df):,} rows x {df.shape[1]} cols -> {out}")
    print(f"completion rate: {df['completed'].mean():.3f}; Target B rows: {df['met_primary'].notna().sum():,}")


if __name__ == "__main__":
    main()
