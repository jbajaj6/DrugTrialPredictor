"""Drugs@FDA: was the trial's drug already FDA-approved when the trial started, and was it approved later?

Source: Drugs@FDA bulk data files (https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files),
one zip, no account. Drugs are matched on active ingredient name (lower-cased, salts stripped).

    python -m dtp.ingest.fda        # download + unzip into data/raw/fda/

Features vs. labels:
  - fda_approved_before: an original approval (any application type, incl. generics) dated before the
    trial's start date. Known at registration, so it's a feature (repurposing vs. new drug).
  - fda_new_approval: for drugs NOT approved before the start, whether an original NDA/BLA approval came
    later. Known only after the fact, so it's the stretch-goal label, never a feature.
"""
from __future__ import annotations

import io
import re
import zipfile

import numpy as np
import pandas as pd
import requests

from dtp import config
from dtp.ingest.hype import HEADERS, normalize_drug_name

FDA_DIR = config.RAW / "fda"
FDA_URL = "https://www.fda.gov/media/89850/download"
_SALT = re.compile(r"\b(hydrochloride|hcl|sodium|potassium|calcium|magnesium|sulfate|acetate|citrate|"
                   r"maleate|mesylate|tartrate|phosphate|succinate|fumarate|bromide|chloride|besylate|"
                   r"hydrobromide|monohydrate|dihydrate|anhydrous|disodium|tosylate|lactate|nitrate)\b")


def download(dest=FDA_DIR) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    r = requests.get(FDA_URL, headers=HEADERS, timeout=300)
    r.raise_for_status()
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(dest)


def ingredient_key(name) -> str | None:
    s = normalize_drug_name(name)
    if not s:
        return None
    s = re.sub(r"\s+", " ", _SALT.sub(" ", s.lower())).strip()
    return s or None


def approvals(src=FDA_DIR) -> pd.DataFrame:
    """One row per single-ingredient key: first original approval (any type) and first NDA/BLA approval."""
    read = lambda f: pd.read_csv(src / f, sep="\t", dtype=str, encoding="latin-1", on_bad_lines="skip")
    prod, sub, app = read("Products.txt"), read("Submissions.txt"), read("Applications.txt")
    orig = sub[(sub["SubmissionType"] == "ORIG") & (sub["SubmissionStatus"] == "AP")]
    orig = orig.assign(date=pd.to_datetime(orig["SubmissionStatusDate"], errors="coerce"))
    orig = orig.groupby("ApplNo")["date"].min().reset_index()
    p = prod[["ApplNo", "ActiveIngredient"]].drop_duplicates()
    p = p[~p["ActiveIngredient"].fillna("").str.contains(";")]  # combination products: skip
    p = p.assign(key=p["ActiveIngredient"].map(ingredient_key)).dropna(subset=["key"])
    d = p.merge(orig, on="ApplNo").merge(app[["ApplNo", "ApplType"]], on="ApplNo", how="left")
    first_any = d.groupby("key")["date"].min()
    first_new = d[d["ApplType"].isin(["NDA", "BLA"])].groupby("key")["date"].min()
    return pd.DataFrame({"fda_first_approval": first_any, "fda_first_nda_bla": first_new}).reset_index()


def fda_features(trials: pd.DataFrame, appr: pd.DataFrame | None = None) -> pd.DataFrame:
    appr = approvals() if appr is None else appr
    t = trials[["nct_id", "start_date", "first_drug_name"]].copy()
    t["key"] = t["first_drug_name"].map(ingredient_key)
    t = t.merge(appr, on="key", how="left")
    start = pd.to_datetime(t["start_date"])
    before = (t["fda_first_approval"] < start).astype(int)
    later = t["fda_first_nda_bla"] >= start
    # code names (ABC-123) are renamed before approval, so a non-match says nothing about approval
    code_name = t["first_drug_name"].map(normalize_drug_name).fillna("").str.isupper()
    return pd.DataFrame({
        "nct_id": t["nct_id"].to_numpy(),
        "fda_approved_before": before.to_numpy(),
        # label: only for named drugs that weren't on the market yet
        "fda_new_approval": np.where((before == 1) | code_name, np.nan, later.astype(float)),
    })


def main() -> None:
    download()
    a = approvals()
    print(f"{len(a):,} single-ingredient keys with an FDA approval")


if __name__ == "__main__":
    main()
