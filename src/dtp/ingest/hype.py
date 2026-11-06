"""Hype / attention features. Only for trials starting 2016 or later.

- Wikipedia: Wikimedia Pageviews REST API, monthly views of the drug's English article.
  Data starts July 2015, so a 6-month pre-start window exists for trials starting 2016+.
- GDELT 2.0: BigQuery public table `gdelt-bq.gdeltv2.gkg_partitioned`. Monthly count and mean tone
  of news articles whose URL contains the drug's name (single-word names only). GKG has no article
  text, and URL slugs carry the headline words, so this is a headline-level match.
  Needs a Google Cloud project (the free BigQuery sandbox is enough) and `gcloud auth application-default login`.

    python -m dtp.ingest.hype                                   # Wikipedia monthly pageviews (resumable)
    python -m dtp.ingest.hype gdelt --project MY_PROJECT        # dry run: prints bytes the query would scan
    python -m dtp.ingest.hype gdelt --project MY_PROJECT --run  # runs it, saves data/raw/gdelt/monthly.parquet

Leakage rule: every metric uses only the WINDOW_MONTHS full months before the start month.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

from dtp import config

WINDOW_MONTHS = 6
WIKI_URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
            "en.wikipedia/all-access/user/{article}/monthly/2015070100/2019123100")
HEADERS = {"User-Agent": "DrugTrialPredictor (https://github.com/jbajaj6/DrugTrialPredictor)"}
WIKI_CACHE = config.RAW / "wiki"
HYPE_MIN_YEAR = 2016
REQUEST_INTERVAL = 1.0  # seconds between requests; Wikimedia rate-limits bursts with HTTP 429
# Names worth looking up: one or two plain words, not arm descriptions or code names like ABC-123
_PLAUSIBLE_TITLE = re.compile(r"[a-z][a-z\-]{3,}(?: [a-z][a-z\-]{3,})?")
_NOT_A_DRUG = re.compile(r"group|dose|saline|standard|control|therapy|treatment|arm\b|water|usual|care")


class RateLimited(RuntimeError):
    pass

_CODE_NAME = re.compile(r"^[A-Z]{1,5}-?\d{2,6}[A-Z]?$")


def normalize_drug_name(name: str | None) -> str | None:
    """Lower-case, strip dosage/route/formulation noise. Code names like ABC-123 kept upper."""
    if not isinstance(name, str) or not name.strip():
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


def wiki_title(drug: str | None) -> str | None:
    """Normalized drug name -> English Wikipedia article title ('pembrolizumab' -> 'Pembrolizumab').

    None for names unlikely to have an article (code names, arm descriptions)."""
    if not isinstance(drug, str) or not _PLAUSIBLE_TITLE.fullmatch(drug) or _NOT_A_DRUG.search(drug):
        return None
    return drug[0].upper() + drug[1:].replace(" ", "_")


def _fetch_monthly(title: str) -> dict[str, int] | None:
    """{'2016-01': views, ...}; None if the article doesn't exist."""
    for attempt in range(4):
        time.sleep(REQUEST_INTERVAL)
        r = requests.get(WIKI_URL.format(article=quote(title, safe="")), headers=HEADERS, timeout=30)
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            time.sleep(30 * (attempt + 1))
            continue
        r.raise_for_status()
        return {i["timestamp"][:4] + "-" + i["timestamp"][4:6]: i["views"] for i in r.json()["items"]}
    raise RateLimited(f"still rate-limited on {title!r}; wait a while and rerun to resume")


def fetch_wiki(titles: list[str], cache: Path = WIKI_CACHE, batch: int = 50,
               max_seconds: float | None = None) -> bool:
    """Monthly pageviews per title, one request at a time, cached as one JSON file per batch.

    A batch is written only if every request in it succeeded, so a rate-limit stop never caches
    a false 'no article'. Returns True when every batch is cached."""
    cache.mkdir(parents=True, exist_ok=True)
    t0, titles = time.time(), sorted(set(t for t in titles if t))
    for i in range(0, len(titles), batch):
        f = cache / f"batch_{i // batch:04d}.json"
        if f.exists():
            continue
        if max_seconds and time.time() - t0 > max_seconds:
            return False
        chunk = titles[i:i + batch]
        f.write_text(json.dumps({t: _fetch_monthly(t) for t in chunk}))
    return True


def load_wiki(cache: Path = WIKI_CACHE) -> dict[str, dict[str, int] | None]:
    out = {}
    for f in sorted(cache.glob("batch_*.json")):
        out.update(json.loads(f.read_text()))
    return out


def wiki_features(trials: pd.DataFrame, wiki: dict, months: int = WINDOW_MONTHS,
                  known: set[str] | None = None) -> pd.DataFrame:
    """Per-trial Wikipedia attention for the drug over the `months` full months before start.

    known: lower-case names of real drugs (dtp.ingest.science.known_drug_names). Names outside it
    ("local", "standard", "intervention") are treated as having no drug article.

    wiki_has_article: the drug has an English Wikipedia article (NaN before 2016: no data)
    wiki_views:       total views in the window (log1p)
    wiki_trend:       log ratio of views in the last half of the window vs. the first half
    """
    t = trials[["nct_id", "start_date", "first_drug_name"]].copy()
    start = pd.to_datetime(t["start_date"])
    t["title"] = t["first_drug_name"].map(normalize_drug_name).map(wiki_title)
    if known is not None:
        t["title"] = t["title"].where(t["title"].fillna("").str.replace("_", " ").str.lower().isin(known))
    has, views, trend = [], [], []
    for title, s in zip(t["title"], start):
        if s.year < HYPE_MIN_YEAR:
            has.append(np.nan); views.append(np.nan); trend.append(np.nan)
            continue
        title = title if isinstance(title, str) else None  # filtered-out names come back as NaN
        if title and title not in wiki:  # not fetched yet: unknown, not "no article"
            has.append(np.nan); views.append(np.nan); trend.append(np.nan)
            continue
        series = wiki.get(title) if title else None
        if not series:
            has.append(0); views.append(0.0); trend.append(0.0)
            continue
        window = [(s - pd.DateOffset(months=k)).strftime("%Y-%m") for k in range(months, 0, -1)]
        v = np.array([series.get(m, 0) for m in window], dtype=float)
        half = months // 2
        has.append(1); views.append(np.log1p(v.sum()))
        trend.append(np.log1p(v[half:].sum()) - np.log1p(v[:half].sum()))
    return pd.DataFrame({"nct_id": t["nct_id"].to_numpy(), "wiki_has_article": has,
                         "wiki_views": views, "wiki_trend": trend})


GDELT_PATH = config.RAW / "gdelt" / "monthly.parquet"
GDELT_SQL = """
SELECT tok AS drug,
       FORMAT('%d-%02d', DIV(DATE, 10000000000), MOD(DIV(DATE, 100000000), 100)) AS month,
       COUNT(*) AS n_articles,
       AVG(SAFE_CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64)) AS mean_tone
FROM `gdelt-bq.gdeltv2.gkg_partitioned`,
     UNNEST(ARRAY(SELECT DISTINCT t FROM UNNEST(REGEXP_EXTRACT_ALL(LOWER(DocumentIdentifier), r'[a-z]{4,}')) AS t)) AS tok
WHERE _PARTITIONTIME BETWEEN TIMESTAMP('2015-07-01') AND TIMESTAMP('2019-12-31')
  AND tok IN UNNEST(@names)
GROUP BY drug, month
"""


def gdelt_names(trials: pd.DataFrame) -> list[str]:
    """Single-word drug names (lower case) of trials starting 2016+, the ones GDELT can cover."""
    t = trials[pd.to_datetime(trials["start_date"]).dt.year >= HYPE_MIN_YEAR]
    names = t["first_drug_name"].map(normalize_drug_name).map(wiki_title).dropna().str.lower()
    return sorted({n for n in names if "_" not in n and re.fullmatch(r"[a-z]{4,}", n)})


def fetch_gdelt(names: list[str], project: str, run: bool = False) -> int:
    """Dry run by default (returns bytes scanned); with run=True saves monthly counts per drug."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    cfg = dict(query_parameters=[bigquery.ArrayQueryParameter("names", "STRING", names)])
    dry = client.query(GDELT_SQL, job_config=bigquery.QueryJobConfig(dry_run=True, **cfg))
    if not run:
        return dry.total_bytes_processed
    df = client.query(GDELT_SQL, job_config=bigquery.QueryJobConfig(**cfg)).to_dataframe()
    GDELT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(GDELT_PATH, index=False)
    return dry.total_bytes_processed


def gdelt_features(trials: pd.DataFrame, monthly: pd.DataFrame | None = None,
                   months: int = WINDOW_MONTHS, known: set[str] | None = None) -> pd.DataFrame:
    """Per-trial news coverage of the drug over the `months` full months before start (2016+ only).

    gdelt_has_news: any article in the window; gdelt_articles: log1p article count;
    gdelt_tone: mean GDELT tone of those articles (NaN without news). Code and multi-word names: NaN.
    known: lower-case names of real drugs; common words that match news URLs ("local", "impact") get NaN."""
    m = pd.read_parquet(GDELT_PATH) if monthly is None else monthly
    counts = {(d, mo): (n, tone) for d, mo, n, tone in m[["drug", "month", "n_articles", "mean_tone"]].itertuples(index=False)}
    names = set(gdelt_names(trials))
    if known is not None:
        names &= known
    t = trials[["nct_id", "start_date", "first_drug_name"]].copy()
    t["drug"] = t["first_drug_name"].map(normalize_drug_name).map(wiki_title).str.lower()
    has, arts, tone = [], [], []
    for drug, s in zip(t["drug"], pd.to_datetime(t["start_date"])):
        if s.year < HYPE_MIN_YEAR or drug not in names:
            has.append(np.nan); arts.append(np.nan); tone.append(np.nan)
            continue
        window = [(s - pd.DateOffset(months=k)).strftime("%Y-%m") for k in range(months, 0, -1)]
        hits = [counts[(drug, w)] for w in window if (drug, w) in counts]
        n = sum(h[0] for h in hits)
        has.append(float(n > 0)); arts.append(np.log1p(n))
        tone.append(sum(h[0] * h[1] for h in hits) / n if n else np.nan)
    return pd.DataFrame({"nct_id": t["nct_id"].to_numpy(), "gdelt_has_news": has,
                         "gdelt_articles": arts, "gdelt_tone": tone})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?", default="wiki", choices=["wiki", "gdelt"])
    ap.add_argument("--max-seconds", type=float, help="wiki: stop after this long; rerun to resume")
    ap.add_argument("--project", help="gdelt: Google Cloud project to bill the BigQuery query to")
    ap.add_argument("--run", action="store_true", help="gdelt: run the query (default is a dry run)")
    args = ap.parse_args()
    t = pd.read_parquet(config.INTERIM / "trials_raw.parquet", columns=["start_date", "first_drug_name"])
    if args.source == "gdelt":
        if not args.project:
            ap.error("gdelt needs --project")
        names = gdelt_names(t)
        gb = fetch_gdelt(names, args.project, run=args.run) / 1e9
        if args.run:
            print(f"{len(names):,} drug names, scanned {gb:,.0f} GB -> {GDELT_PATH}")
        else:
            print(f"dry run: {len(names):,} drug names, the query would scan {gb:,.0f} GB "
                  f"(BigQuery's free tier covers 1,000 GB/month). Add --run to run it.")
        return
    t = t[pd.to_datetime(t["start_date"]).dt.year >= HYPE_MIN_YEAR]
    titles = t["first_drug_name"].map(normalize_drug_name).map(wiki_title).dropna().unique().tolist()
    done = fetch_wiki(titles, max_seconds=args.max_seconds)
    found = sum(v is not None for v in load_wiki().values())
    print(f"{len(titles):,} drug titles; {found:,} with a Wikipedia article so far; done={done}")


if __name__ == "__main__":
    main()
