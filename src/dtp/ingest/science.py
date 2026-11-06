"""Science features: what was known about the drug and how the trial describes itself.

Sources (all free and public, no account):
  - ClinicalTrials.gov API v2: each trial's brief title and brief summary
  - PubMed E-utilities: number of papers mentioning the drug published before the trial's start year
  - ChEMBL API: drug mechanisms of action (action type, target) and molecule type / first approval

    python -m dtp.ingest.science text      # trial summaries (~3 min)
    python -m dtp.ingest.science chembl    # mechanisms + molecules (~5 min)
    python -m dtp.ingest.science pubmed    # prior-paper counts per (drug, start year) (~2 h at 3 requests/s; resumable)
    python -m dtp.ingest.science embed     # sentence embeddings of the summaries (~1 h on 2 CPUs)

Leakage rules:
  - PubMed counts only papers dated before the trial's start year.
  - ChEMBL: only attributes that don't depend on how the trial ended (action type, molecule type,
    whether the target already had an approved drug before the start year). Current max_phase is
    excluded. Whether a drug has a curated mechanism at all is partly retrospective (ChEMBL curates
    drugs that reached the clinic or market), so `chembl_has_mechanism` is flagged in the notebook.
  - Summaries come from the current record; sponsors can edit them after the trial starts, and
    ClinicalTrials.gov record history isn't public (HTTP 403), so the first-posted text isn't available.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from dtp import config
from dtp.ingest.hype import HEADERS, normalize_drug_name, wiki_title

SCI_DIR = config.RAW / "science"
TEXT_CACHE = SCI_DIR / "ctgov"
PUBMED_CACHE = SCI_DIR / "pubmed"
CHEMBL_CACHE = SCI_DIR / "chembl"
EMBED_PATH = config.INTERIM / "summary_embeddings.npy"
EMBED_IDS = config.INTERIM / "summary_embedding_ids.parquet"

CTGOV_URL = "https://clinicaltrials.gov/api/v2/studies"
EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
CHEMBL_URL = "https://www.ebi.ac.uk/chembl/api/data"
EMBED_MODEL = "pritamdeka/S-PubMedBert-MS-MARCO"  # PubMedBERT fine-tuned for sentence embeddings
N_EMBED_PCS = 20

# Coarse classes of ChEMBL action types
ACTION_CLASS = {
    "INHIBITOR": "inhibitor", "NEGATIVE ALLOSTERIC MODULATOR": "inhibitor", "BLOCKER": "inhibitor",
    "ANTAGONIST": "antagonist", "INVERSE AGONIST": "antagonist",
    "AGONIST": "agonist", "PARTIAL AGONIST": "agonist", "POSITIVE ALLOSTERIC MODULATOR": "agonist",
    "ACTIVATOR": "agonist", "OPENER": "agonist",
    "BINDING AGENT": "binder", "CROSS-LINKING AGENT": "binder",
}


def _get(url: str, params: dict, tries: int = 4, **kw) -> requests.Response:
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=120, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url} kept failing; rerun to resume")


# ---- ClinicalTrials.gov text ------------------------------------------------------------------

def fetch_text(nct_ids: list[str], cache: Path = TEXT_CACHE, batch: int = 500) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    ids = sorted(set(nct_ids))
    for i in range(0, len(ids), batch):
        f = cache / f"batch_{i // batch:04d}.json"
        if f.exists():
            continue
        chunk = ids[i:i + batch]
        r = _get(CTGOV_URL, {"filter.ids": ",".join(chunk), "pageSize": 1000,
                             "fields": "NCTId,BriefTitle,BriefSummary"})
        out = {}
        for s in r.json()["studies"]:
            p = s["protocolSection"]
            out[p["identificationModule"]["nctId"]] = {
                "title": p["identificationModule"].get("briefTitle"),
                "summary": p.get("descriptionModule", {}).get("briefSummary")}
        f.write_text(json.dumps(out))


def load_text(cache: Path = TEXT_CACHE) -> pd.DataFrame:
    rows = {}
    for f in sorted(cache.glob("batch_*.json")):
        rows.update(json.loads(f.read_text()))
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("nct_id").reset_index()


# ---- PubMed prior literature ------------------------------------------------------------------

def _pubmed_count(name: str, before_year: int) -> int:
    term = f'"{name}"[tiab] AND 1800:{before_year - 1}[dp]'
    r = _get(EUTILS_URL, {"db": "pubmed", "term": term, "rettype": "count", "retmode": "json"})
    return int(r.json()["esearchresult"]["count"])


def fetch_pubmed(pairs: list[tuple[str, int]], cache: Path = PUBMED_CACHE, batch: int = 300,
                 workers: int = 3) -> None:
    """Papers mentioning the drug in title/abstract published before each start year.

    NCBI allows 3 requests/second without an API key: `workers` threads, each at most one
    request per second. One JSON file per batch, written only when every request in it succeeded."""
    from concurrent.futures import ThreadPoolExecutor

    def paced(pair):
        t0 = time.time()
        n = _pubmed_count(*pair)
        time.sleep(max(0.0, 1.05 - (time.time() - t0)))
        return [pair[0], int(pair[1]), n]

    cache.mkdir(parents=True, exist_ok=True)
    pairs = sorted(set(pairs))
    with ThreadPoolExecutor(workers) as pool:
        for i in range(0, len(pairs), batch):
            f = cache / f"batch_{i // batch:04d}.json"
            if not f.exists():
                f.write_text(json.dumps(list(pool.map(paced, pairs[i:i + batch]))))


def load_pubmed(cache: Path = PUBMED_CACHE) -> pd.DataFrame:
    rows = [r for f in sorted(cache.glob("batch_*.json")) for r in json.loads(f.read_text())]
    return pd.DataFrame(rows, columns=["drug", "start_year", "pubmed_prior_papers"])


def drug_key(name) -> str | None:
    """Normalized drug name usable as a PubMed / ChEMBL lookup key (same filter as Wikipedia)."""
    t = wiki_title(normalize_drug_name(name))
    return t.replace("_", " ").lower() if t else None


# ---- ChEMBL mechanisms ------------------------------------------------------------------------

def _paged(endpoint: str, key: str, params: dict) -> list[dict]:
    rows, offset = [], 0
    while True:
        r = _get(f"{CHEMBL_URL}/{endpoint}.json", {**params, "limit": 1000, "offset": offset})
        d = r.json()
        rows += d[key]
        offset += 1000
        if not d["page_meta"]["next"]:
            return rows


def fetch_chembl(cache: Path = CHEMBL_CACHE) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    mech_f, mol_f = cache / "mechanisms.json", cache / "molecules.json"
    if not mech_f.exists():
        mech = _paged("mechanism", "mechanisms", {})
        mech_f.write_text(json.dumps([{k: m.get(k) for k in (
            "molecule_chembl_id", "parent_molecule_chembl_id", "action_type",
            "target_chembl_id", "mechanism_of_action")} for m in mech]))
    if not mol_f.exists():
        mech = json.loads(mech_f.read_text())
        ids = sorted({m["parent_molecule_chembl_id"] or m["molecule_chembl_id"] for m in mech}
                     | {m["molecule_chembl_id"] for m in mech})
        mols = []
        for i in range(0, len(ids), 200):
            r = _get(f"{CHEMBL_URL}/molecule.json",
                     {"molecule_chembl_id__in": ",".join(ids[i:i + 200]), "limit": 1000})
            for m in r.json()["molecules"]:
                mols.append({"molecule_chembl_id": m["molecule_chembl_id"],
                             "pref_name": m.get("pref_name"),
                             "molecule_type": m.get("molecule_type"),
                             "first_approval": m.get("first_approval"),
                             "synonyms": sorted({s["molecule_synonym"] for s in m.get("molecule_synonyms") or []})})
        mol_f.write_text(json.dumps(mols))


def chembl_table(cache: Path = CHEMBL_CACHE) -> pd.DataFrame:
    """One row per lower-cased drug name (pref_name or synonym): molecule type, main action class,
    first approval year and the earliest approval year of any drug sharing one of its targets."""
    mech = pd.DataFrame(json.loads((cache / "mechanisms.json").read_text()))
    mols = pd.DataFrame(json.loads((cache / "molecules.json").read_text()))
    mech["mol"] = mech["parent_molecule_chembl_id"].fillna(mech["molecule_chembl_id"])
    mech = mech.merge(mols[["molecule_chembl_id", "first_approval"]], left_on="mol",
                      right_on="molecule_chembl_id", how="left", suffixes=("", "_m"))
    # earliest approval among all drugs hitting each target
    tgt_first = mech.dropna(subset=["target_chembl_id"]).groupby("target_chembl_id")["first_approval"].min()
    mech["target_first_approval"] = mech["target_chembl_id"].map(tgt_first)
    per_mol = mech.groupby("mol").agg(
        action=("action_type", lambda s: s.map(ACTION_CLASS).fillna("other").mode().iat[0]),
        n_targets=("target_chembl_id", "nunique"),
        target_first_approval=("target_first_approval", "min"))
    names = []
    for m in mols.itertuples():
        for n in {m.pref_name, *m.synonyms} - {None}:
            names.append((n.lower(), m.molecule_chembl_id, m.molecule_type, m.first_approval))
    names = pd.DataFrame(names, columns=["drug", "mol", "molecule_type", "first_approval"])
    names = names.merge(per_mol, left_on="mol", right_index=True, how="inner")
    return names.drop_duplicates("drug").reset_index(drop=True)


def known_drug_names() -> set[str]:
    """Lower-case names of real drugs: ChEMBL names/synonyms plus Drugs@FDA ingredients.

    Used to drop arm descriptions and common words ("local", "standard") before matching drug
    names against Wikipedia and news URLs."""
    from dtp.ingest import fda

    names = set(chembl_table()["drug"]) if (CHEMBL_CACHE / "molecules.json").exists() else set()
    if (fda.FDA_DIR / "Products.txt").exists():
        names |= set(fda.approvals()["key"])
    return names


# ---- Embeddings --------------------------------------------------------------------------------

def trial_text(text: pd.DataFrame) -> pd.Series:
    return (text["title"].fillna("") + ". " + text["summary"].fillna("")).str.slice(0, 2000)


def embed(text: pd.DataFrame, model_name: str = EMBED_MODEL, batch_size: int = 64) -> None:
    """Sentence embeddings of title + brief summary (first 128 tokens), saved in chunks."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device="cpu")
    model.max_seq_length = 128
    docs = trial_text(text).tolist()
    parts_dir = config.INTERIM / "embed_parts"
    parts_dir.mkdir(exist_ok=True)
    step = 5000
    for i in range(0, len(docs), step):
        f = parts_dir / f"part_{i // step:03d}.npy"
        if not f.exists():
            np.save(f, model.encode(docs[i:i + step], batch_size=batch_size,
                                    normalize_embeddings=True).astype(np.float32))
    np.save(EMBED_PATH, np.vstack([np.load(f) for f in sorted(parts_dir.glob("part_*.npy"))]))
    text[["nct_id"]].to_parquet(EMBED_IDS, index=False)


def embedding_pcs(train_ids: pd.Series, n: int = N_EMBED_PCS) -> pd.DataFrame:
    """PCA of the embeddings, fit on training-period trials only, as emb_pc1..emb_pcN."""
    from sklearn.decomposition import PCA

    X = np.load(EMBED_PATH)
    ids = pd.read_parquet(EMBED_IDS)["nct_id"]
    pca = PCA(n_components=n, random_state=0).fit(X[ids.isin(set(train_ids)).to_numpy()])
    Z = pca.transform(X)
    out = pd.DataFrame(Z, columns=[f"emb_pc{i + 1}" for i in range(n)])
    out.insert(0, "nct_id", ids.to_numpy())
    return out


# ---- Per-trial features ------------------------------------------------------------------------

def science_features(trials: pd.DataFrame) -> pd.DataFrame:
    """Per-trial prior-literature and mechanism features (no embeddings; see embedding_pcs)."""
    t = trials[["nct_id", "start_date", "first_drug_name"]].copy()
    t["start_year"] = pd.to_datetime(t["start_date"]).dt.year
    t["drug"] = t["first_drug_name"].map(drug_key)
    out = t[["nct_id"]].copy()
    if any(PUBMED_CACHE.glob("batch_*.json")):
        pm = t.merge(load_pubmed(), on=["drug", "start_year"], how="left")
        out["pubmed_log_prior_papers"] = np.log1p(pm["pubmed_prior_papers"]).to_numpy()
        out["pubmed_has_prior"] = (pm["pubmed_prior_papers"] > 0).astype(float).where(
            pm["pubmed_prior_papers"].notna()).to_numpy()
    if (CHEMBL_CACHE / "molecules.json").exists():
        ch = t.merge(chembl_table(), on="drug", how="left")
        y = ch["start_year"]
        out["chembl_has_mechanism"] = ch["mol"].notna().astype(int).to_numpy()
        out["chembl_action"] = ch["action"].fillna("unknown").to_numpy()
        out["chembl_molecule_type"] = ch["molecule_type"].fillna("unknown").str.upper().to_numpy()
        out["chembl_n_targets"] = ch["n_targets"].to_numpy()
        out["chembl_approved_before"] = (ch["first_approval"] < y).astype(float).where(ch["mol"].notna()).to_numpy()
        out["chembl_known_target"] = (ch["target_first_approval"] < y).astype(float).where(
            ch["mol"].notna()).to_numpy()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["text", "chembl", "pubmed", "embed"])
    args = ap.parse_args()
    trials = pd.read_parquet(config.PROCESSED / "trials.parquet",
                             columns=["nct_id", "start_date", "first_drug_name"])
    if args.step == "text":
        fetch_text(trials["nct_id"].tolist())
        print(f"{len(load_text()):,} trial summaries")
    elif args.step == "chembl":
        fetch_chembl()
        print(f"{len(chembl_table()):,} ChEMBL drug names with a mechanism")
    elif args.step == "pubmed":
        y = pd.to_datetime(trials["start_date"]).dt.year
        pairs = [(d, int(yr)) for d, yr in zip(trials["first_drug_name"].map(drug_key), y) if isinstance(d, str)]
        fetch_pubmed(pairs)
        print(f"{len(load_pubmed()):,} (drug, year) PubMed counts")
    else:
        embed(load_text())
        print(f"embeddings: {np.load(EMBED_PATH).shape}")


if __name__ == "__main__":
    main()
