"""Labels, cohort filter, and registration-time features from the raw AACT pull.

    python -m dtp.features    # data/interim/*.parquet -> data/processed/trials.parquet
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from dtp import config

# ---- Disease areas: top-level MeSH disease categories (AACT lists them as ancestor terms) ----
DISEASE_AREAS = {
    "oncology": ["Neoplasms"],
    "cardiovascular": ["Cardiovascular Diseases"],
    "neuro": ["Nervous System Diseases"],
    "mental": ["Mental Disorders"],
    "infection": ["Infections"],
    "respiratory": ["Respiratory Tract Diseases"],
    "digestive": ["Digestive System Diseases"],
    "metabolic": ["Nutritional and Metabolic Diseases"],
    "endocrine": ["Endocrine System Diseases"],
    "immune": ["Immune System Diseases"],
    "skin": ["Skin and Connective Tissue Diseases"],
    "musculoskeletal": ["Musculoskeletal Diseases"],
    "urogenital": ["Urogenital Diseases", "Female Urogenital Diseases and Pregnancy Complications"],
    "blood": ["Hemic and Lymphatic Diseases"],
    "eye": ["Eye Diseases"],
}
AREA_COLS = [f"area_{a}" for a in DISEASE_AREAS]

# ---- Feature groups (used by the ablation in dtp.models) ---------------------------------
CATEGORICAL = [
    "phase", "sponsor_class", "allocation", "intervention_model", "masking",
    "primary_purpose", "disease_area", "elig_gender",
]
DESIGN_NUMERIC = [
    "phase_ord", "number_of_arms", "has_dmc", "n_collaborators", "start_year", "reg_lag_days",
    "n_mesh_terms", "n_conditions", "n_drug_interventions", "n_disease_areas",
    "n_primary_outcomes", "n_secondary_outcomes",
    "has_placebo_arm", "has_active_comparator", "has_no_intervention_arm",
    "elig_healthy_volunteers", "elig_min_age_yrs", "elig_max_age_yrs", "elig_pediatric",
    "elig_len", "elig_n_inclusion", "elig_n_exclusion", "elig_biomarker",
] + AREA_COLS
SPONSOR_HISTORY = [
    "sponsor_prior_trials", "sponsor_prior_finished", "sponsor_prior_stop_rate", "sponsor_first_trial",
]
# Can change after a trial starts (withdrawn trials often have no sites listed). Leakage check only.
POST_START_RISKY = ["n_sites", "n_countries", "has_us_site"]

FEATURE_GROUPS = {
    "design": DESIGN_NUMERIC + CATEGORICAL,
    "sponsor_history": SPONSOR_HISTORY,
    "sites": POST_START_RISKY,
    # filled in as the other joins land:
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
# "not due to safety concerns", "no safety or efficacy issues", ... must not count as safety/efficacy
_NEGATED = re.compile(r"\b(?:not|no|unrelated to|without|nor)\b[^.;]{0,60}(?:safety|efficacy|concerns?)")
_AGE = re.compile(r"(\d+(?:\.\d+)?)\s*(year|month|week|day|hour|minute)", re.IGNORECASE)
_AGE_UNIT_YEARS = {"year": 1, "month": 1 / 12, "week": 7 / 365, "day": 1 / 365,
                   "hour": 1 / 8760, "minute": 1 / 525600}

# why_stopped -> reason category (EDA only; known after the trial ends). First match wins.
WHY_STOPPED = [
    ("safety", r"safety|toxicit|adverse|side effect|death|serious"),
    ("efficacy", r"efficac|futil|lack of (?:benefit|effect|response)|interim analysis|ineffective|no benefit"
                 r"|clinical activity|insufficient (?:activity|response)"),
    ("enrollment", r"enrol|accru|recruit|participant|patients? (?:were|was) not|subjects?|inclusion"
                   r"|sample size|patient availability|eligible patients"),
    ("business", r"sponsor|business|fund|financ|commercial|strateg|company|portfolio|priorit|budget|drug supply"
                 r"|manufactur|program|other indication|resource"),
    ("pi_or_site", r"\bpi\b|investigator|site|staff|left the institution|relocat"),
    ("regulatory", r"fda|regulat|irb|ethic|approval"),
]


def _to_bool(s: pd.Series) -> pd.Series:
    return s.map(lambda v: np.nan if pd.isna(v) else float(str(v).strip().lower() in _TRUTHY))


def _split_criteria(text: str | float) -> tuple[int, int]:
    if not isinstance(text, str):
        return 0, 0
    inc, _, exc = text.lower().partition("exclusion criteria")
    bullets = lambda t: len(re.findall(r"^\s*(?:[-*•]|\d+[.)])\s+", t, flags=re.M))
    return bullets(inc), bullets(exc)


def parse_age_years(s: str | float) -> float:
    """'18 Years' -> 18.0, '6 Months' -> 0.5, 'N/A' / missing -> NaN."""
    if not isinstance(s, str):
        return np.nan
    m = _AGE.search(s)
    return float(m.group(1)) * _AGE_UNIT_YEARS[m.group(2).lower()] if m else np.nan


def why_stopped_category(text: str | float) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    low = _NEGATED.sub(" ", text.lower())
    for cat, pat in WHY_STOPPED:
        if re.search(pat, low):
            return cat
    return "other"


def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["completed"] = (df["overall_status"] == "COMPLETED").astype(int)
    df["withdrawn"] = (df["overall_status"] == "WITHDRAWN").astype(int)
    # Target B: completed trials that report a primary-outcome p-value.
    has_p = df["label_min_primary_p"].notna() & (df["completed"] == 1)
    df["met_primary"] = np.where(has_p, (df["label_min_primary_p"] < 0.05).astype(float), np.nan)
    stopped = df["completed"] == 0
    df["post_stop_reason"] = np.where(stopped, df["post_why_stopped"].map(why_stopped_category), None)
    df.loc[stopped & df["post_stop_reason"].isna(), "post_stop_reason"] = "not_given"
    return df


def add_design_features(df: pd.DataFrame) -> pd.DataFrame:
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
    for c in ["number_of_arms", "n_primary_outcomes", "n_secondary_outcomes",
              "has_placebo_arm", "has_active_comparator", "has_no_intervention_arm"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Disease areas (multi-label) + one primary area for grouping/EDA
    terms = df["mesh_terms"].fillna("").str.split("|").map(set)
    for area, names in DISEASE_AREAS.items():
        df[f"area_{area}"] = terms.map(lambda t, n=names: int(any(x in t for x in n)))
    df["n_disease_areas"] = df[AREA_COLS].sum(axis=1)
    df["disease_area"] = "none"
    for area in reversed(DISEASE_AREAS):  # earlier entries in DISEASE_AREAS take priority
        df.loc[df[f"area_{area}"] == 1, "disease_area"] = area

    df["elig_min_age_yrs"] = df["elig_min_age"].map(parse_age_years)
    df["elig_max_age_yrs"] = df["elig_max_age"].map(parse_age_years)
    df["elig_pediatric"] = (df["elig_min_age_yrs"] < 18).astype(int)

    crit = df["elig_criteria"]
    df["elig_len"] = crit.fillna("").str.len()
    counts = crit.map(_split_criteria)
    df["elig_n_inclusion"] = counts.str[0]
    df["elig_n_exclusion"] = counts.str[1]
    df["elig_biomarker"] = crit.fillna("").str.contains(_BIOMARKER).astype(int)

    for c in ["allocation", "intervention_model", "masking", "primary_purpose", "elig_gender"]:
        df[c] = df[c].fillna("NA").astype(str).str.upper()
    return df


def add_sponsor_history(df: pd.DataFrame, hist: pd.DataFrame, smoothing: float = 5.0) -> pd.DataFrame:
    """Lead sponsor's track record using only trials that started / ended before this trial started.

    sponsor_prior_trials:     trials by the same lead sponsor that started earlier
    sponsor_prior_finished:   ...that had also ended (any final status) before this start
    sponsor_prior_stop_rate:  share of those that were terminated/withdrawn, shrunk toward the
                              overall rate with `smoothing` pseudo-trials so small sponsors aren't 0/1
    """
    df = df.copy()
    h = hist.dropna(subset=["lead_sponsor_name", "start_date"]).copy()
    codes = {name: i for i, name in enumerate(h["lead_sponsor_name"].unique())}
    day = lambda s: (pd.to_datetime(s) - pd.Timestamp("1900-01-01")).dt.days.to_numpy()
    BIG = 100_000  # > number of days in the date range, so (sponsor, day) packs into one sortable int

    h_code = h["lead_sponsor_name"].map(codes).to_numpy()
    starts = np.sort(h_code * BIG + day(h["start_date"]))

    fin = h[h["overall_status"].isin(config.FINAL_STATUSES) & h["end_date"].notna()]
    fin = fin.assign(key=fin["lead_sponsor_name"].map(codes).to_numpy() * BIG + day(fin["end_date"]),
                     stopped=(fin["overall_status"] != "COMPLETED").astype(int)).sort_values("key")
    end_keys = fin["key"].to_numpy()
    stop_cum = np.concatenate([[0], np.cumsum(fin["stopped"].to_numpy())])
    prior_rate = fin.loc[pd.to_datetime(fin["end_date"]).dt.year <= config.TRAIN_MAX_YEAR, "stopped"].mean()

    t_code = df["lead_sponsor_name"].map(codes)
    known = t_code.notna().to_numpy()
    code = t_code.fillna(-1).astype(int).to_numpy()
    key = code * BIG + day(df["start_date"])
    lo = code * BIG

    n_started = np.searchsorted(starts, key, "left") - np.searchsorted(starts, lo, "left")
    i_end, i_lo = np.searchsorted(end_keys, key, "left"), np.searchsorted(end_keys, lo, "left")
    n_ended = i_end - i_lo
    n_stopped = stop_cum[i_end] - stop_cum[i_lo]

    df["sponsor_prior_trials"] = np.where(known, n_started, 0)
    df["sponsor_prior_finished"] = np.where(known, n_ended, 0)
    df["sponsor_prior_stop_rate"] = (np.where(known, n_stopped, 0) + smoothing * prior_rate) / (
        df["sponsor_prior_finished"] + smoothing)
    df["sponsor_first_trial"] = (df["sponsor_prior_trials"] == 0).astype(int)
    return df


def apply_cohort(df: pd.DataFrame, max_lag: int = config.MAX_REG_LAG_DAYS) -> pd.DataFrame:
    """Keep trials registered by `max_lag` days after start, i.e. predictable at registration."""
    return df[df["reg_lag_days"] <= max_lag].reset_index(drop=True)


def build(raw: pd.DataFrame, hist: pd.DataFrame | None = None, cohort: bool = True) -> pd.DataFrame:
    df = add_design_features(add_labels(raw))
    if hist is not None:
        df = add_sponsor_history(df, hist)
    if cohort:
        df = apply_cohort(df)
    return df.drop(columns=["elig_criteria"])


def main() -> None:
    raw = pd.read_parquet(config.INTERIM / "trials_raw.parquet")
    hist_path = config.INTERIM / "sponsor_history.parquet"
    hist = pd.read_parquet(hist_path) if hist_path.exists() else None
    df = build(raw, hist)
    out = config.PROCESSED / "trials.parquet"
    df.to_parquet(out, index=False)
    print(f"cohort: {len(df):,} of {len(raw):,} trials registered <= {config.MAX_REG_LAG_DAYS} days after start")
    print(f"wrote {len(df):,} rows x {df.shape[1]} cols -> {out}")
    print(df["overall_status"].value_counts().to_string())
    print(f"completion rate: {df['completed'].mean():.3f}; Target B rows: {df['met_primary'].notna().sum():,}")


if __name__ == "__main__":
    main()
