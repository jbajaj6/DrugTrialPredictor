"""Hype / attention features (owner: Giannis). 2015+ only.

- Wikipedia: Wikimedia Pageviews REST API (daily views per article).
- GDELT 2.0: easiest via BigQuery public table `gdelt-bq.gdeltv2.gkg` — count articles whose
  themes/organizations mention the drug or sponsor and average V2Tone in the pre-start window.

Leakage rule: every metric is computed over [start_date - WINDOW_DAYS, start_date).
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd
import requests

WINDOW_DAYS = 180
WIKI_URL = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "en.wikipedia/all-access/user/{article}/daily/{start}/{end}"
)
HEADERS = {"User-Agent": "DrugTrialPredictor (https://github.com/jbajaj6/DrugTrialPredictor)"}

_CODE_NAME = re.compile(r"^[A-Z]{1,5}-?\d{2,6}[A-Z]?$")


def normalize_drug_name(name: str | None) -> str | None:
    """Lower-case, strip dosage/route/formulation noise. Code names like ABC-123 kept upper."""
    if not name:
        return None
    s = name.strip()
    if _CODE_NAME.match(s.upper().replace(" ", "")):
        return s.upper().replace(" ", "")
    s = s.lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|µg|g|ml|iu|units?|%)\b", " ", s)
    s = re.sub(r"\b(tablets?|capsules?|injection|oral|iv|intravenous|subcutaneous|"
               r"solution|cream|gel|placebo|extended[- ]release|er|xr)\b", " ", s)
    s = re.sub(r"[^a-z0-9\- ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def wiki_pageviews(article: str, start: date, days: int = WINDOW_DAYS) -> int | None:
    """Total views of an English Wikipedia article in the `days` before `start`. None if no page."""
    end = start - timedelta(days=1)
    begin = start - timedelta(days=days)
    url = WIKI_URL.format(
        article=article.replace(" ", "_").capitalize(),
        start=begin.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"),
    )
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return int(sum(item["views"] for item in r.json().get("items", [])))


def gdelt_features(trials: pd.DataFrame) -> pd.DataFrame:
    """TODO(Giannis): BigQuery pull of article count + mean tone per drug in the pre-start window."""
    raise NotImplementedError
