"""Project-wide paths and constants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
SQL_DIR = ROOT / "sql"

# Study window (see README: 2019 cutoff avoids survivorship bias)
START_MIN = "2005-01-01"
START_MAX = "2019-12-31"

# Time-based split: train on early start years, test on later ones
TRAIN_MAX_YEAR = 2015  # train: 2005-2015, test: 2016-2019

FINAL_STATUSES = ("COMPLETED", "TERMINATED", "WITHDRAWN")

# AACT tables the pipeline reads
AACT_TABLES = [
    "studies", "designs", "sponsors", "facilities", "countries",
    "browse_conditions", "interventions", "eligibilities",
    "outcomes", "outcome_analyses",
]

# Phase -> ordinal (AACT v2 uses PHASE1/PHASE2/...; older dumps use "Phase 1")
PHASE_ORDER = {
    "EARLY_PHASE1": 0.5, "PHASE1": 1, "PHASE1/PHASE2": 1.5,
    "PHASE2": 2, "PHASE2/PHASE3": 2.5, "PHASE3": 3, "PHASE4": 4,
}

for p in (RAW, INTERIM, PROCESSED):
    p.mkdir(parents=True, exist_ok=True)
