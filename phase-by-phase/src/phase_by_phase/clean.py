"""First-pass identity cleaning for the phase-by-phase dataset.

This module deliberately performs conservative *surface normalization*. It
does not claim that two different strings are the same molecule or indication
unless an upstream controlled identifier says so. Alias resolution against
RxNorm/ChEMBL/MeSH belongs in a later, auditable mapping table.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable

import pandas as pd


PHASE_ALIASES = {
    "EARLY PHASE 1": "EARLY_PHASE1",
    "EARLY PHASE1": "EARLY_PHASE1",
    "EARLY_PHASE1": "EARLY_PHASE1",
    "PHASE 1": "PHASE1",
    "PHASE1": "PHASE1",
    "PHASE 1 PHASE 2": "PHASE1/PHASE2",
    "PHASE 1/PHASE 2": "PHASE1/PHASE2",
    "PHASE1 PHASE2": "PHASE1/PHASE2",
    "PHASE1/PHASE2": "PHASE1/PHASE2",
    "PHASE 2": "PHASE2",
    "PHASE2": "PHASE2",
    "PHASE 2 PHASE 3": "PHASE2/PHASE3",
    "PHASE 2/PHASE 3": "PHASE2/PHASE3",
    "PHASE2 PHASE3": "PHASE2/PHASE3",
    "PHASE2/PHASE3": "PHASE2/PHASE3",
    "PHASE 3": "PHASE3",
    "PHASE3": "PHASE3",
    "PHASE 4": "PHASE4",
    "PHASE4": "PHASE4",
    "NA": "NA",
    "N/A": "NA",
    "NOT APPLICABLE": "NA",
}

PHASE_RANK = {
    "EARLY_PHASE1": 0.5,
    "PHASE1": 1.0,
    "PHASE1/PHASE2": 1.5,
    "PHASE2": 2.0,
    "PHASE2/PHASE3": 2.5,
    "PHASE3": 3.0,
    "PHASE4": 4.0,
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SPACE = re.compile(r"\s+")
_PLACEBO = re.compile(r"\b(?:placebo|sham)\b", re.IGNORECASE)


def _ascii(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()


def _key(value: object) -> str | None:
    text = _NON_ALNUM.sub(" ", _ascii(value).lower())
    text = _SPACE.sub(" ", text).strip()
    return text or None


def normalize_phase(value: object) -> str | None:
    """Return the canonical AACT-style phase label, or ``None`` if unknown."""
    if value is None or pd.isna(value):
        return None
    raw = _ascii(value).upper().replace("_", " ").strip()
    raw = re.sub(r"\s*/\s*", "/", raw)
    raw = _SPACE.sub(" ", raw)
    canonical = PHASE_ALIASES.get(raw)
    return None if canonical == "NA" else canonical


def normalize_drug_name(value: object) -> str | None:
    """Conservatively normalize a drug label without guessing molecular aliases."""
    key = _key(value)
    if key is None or _PLACEBO.search(key):
        return None
    return key


def normalize_indication(raw_condition: object, mesh_term: object = None) -> str | None:
    """Prefer a controlled MeSH indication; otherwise normalize the raw label."""
    return _key(mesh_term) or _key(raw_condition)


def regimen_key(drug_names: Iterable[object]) -> str | None:
    """Create a stable unordered regimen key from non-placebo components."""
    components = sorted({d for value in drug_names if (d := normalize_drug_name(value))})
    return "+".join(components) if components else None


def make_program_id(regimen: str, indication: str) -> str:
    """Create a readable, collision-resistant ID for a regimen-indication pair."""
    raw = f"{regimen}|{indication}"
    digest = hashlib.sha1(raw.encode()).hexdigest()[:10]
    regimen_slug = _NON_ALNUM.sub("-", regimen)[:40].strip("-")
    indication_slug = _NON_ALNUM.sub("-", indication)[:40].strip("-")
    return f"{regimen_slug}__{indication_slug}__{digest}"


def build_program_trials(
    rows: pd.DataFrame,
    *,
    nct_col: str = "nct_id",
    drug_col: str = "drug_name",
    condition_col: str = "condition_name",
    mesh_col: str = "mesh_term",
) -> pd.DataFrame:
    """Build the auditable NCT-to-program bridge from long-form mappings.

    ``rows`` may contain repeated NCT/drug/condition combinations. All active
    drug components within an NCT ID form one regimen. Each distinct controlled
    indication produces a bridge row. Trials with multiple indications are
    retained but flagged because their drug-to-indication assignment is
    ambiguous and should be handled in a sensitivity analysis.
    """
    required = {nct_col, drug_col, condition_col}
    missing = required - set(rows.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    data = rows.copy()
    if mesh_col not in data:
        data[mesh_col] = None
    data["drug_key"] = data[drug_col].map(normalize_drug_name)
    data["indication_key"] = [
        normalize_indication(raw, mesh)
        for raw, mesh in zip(data[condition_col], data[mesh_col])
    ]

    records: list[dict[str, object]] = []
    for nct_id, trial in data.groupby(nct_col, sort=True, dropna=False):
        regimen = regimen_key(trial["drug_key"])
        indications = sorted(set(trial["indication_key"].dropna()))
        if not nct_id or pd.isna(nct_id) or regimen is None or not indications:
            continue
        ambiguous = len(indications) > 1
        for indication in indications:
            records.append(
                {
                    "nct_id": str(nct_id),
                    "regimen_id": regimen,
                    "indication_id": indication,
                    "program_id": make_program_id(regimen, indication),
                    "n_regimen_components": len(regimen.split("+")),
                    "n_trial_indications": len(indications),
                    "ambiguous_mapping": ambiguous,
                }
            )

    columns = [
        "nct_id",
        "regimen_id",
        "indication_id",
        "program_id",
        "n_regimen_components",
        "n_trial_indications",
        "ambiguous_mapping",
    ]
    return pd.DataFrame.from_records(records, columns=columns).drop_duplicates().reset_index(drop=True)
