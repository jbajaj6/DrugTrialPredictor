"""Baselines, models, the feature-group ablation, and diagnostics.

    python -m dtp.models --target completed
    python -m dtp.models --target met_primary
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from dtp import config
from dtp.features import CATEGORICAL, FEATURE_GROUPS

# Headline comparison: each outside signal added to the design features.
ABLATIONS = {
    "design": ["design"],
    "design+sponsor_history": ["design", "sponsor_history"],
    "design+sponsor_history+funding": ["design", "sponsor_history", "funding"],
}
# Hype data only exists for trials starting 2016+, so its comparison uses its own split.
HYPE_SPLIT = {"years": (2016, 2019), "train_max_year": 2017}
HYPE_ABLATIONS = {
    "design+sponsor_history": ["design", "sponsor_history"],
    "design+sponsor_history+hype": ["design", "sponsor_history", "hype"],
}
# Not a candidate model: shows how much site counts (which change after start) would inflate results.
LEAKAGE_CHECK = {"design+sponsor_history+sites (leaky)": ["design", "sponsor_history", "sites"]}


def time_split(df: pd.DataFrame, target: str, train_max_year: int = config.TRAIN_MAX_YEAR,
               years: tuple[int, int] | None = None):
    """Train on start years <= train_max_year, test on later ones (optionally within `years`)."""
    d = df[df[target].notna()]
    if years:
        d = d[d["start_year"].between(*years)]
    return d[d["start_year"] <= train_max_year], d[d["start_year"] > train_max_year]


def feature_list(df: pd.DataFrame, groups: list[str]) -> list[str]:
    cols = [c for g in groups for c in FEATURE_GROUPS[g]]
    return [c for c in dict.fromkeys(cols) if c in df.columns]  # skip groups not joined yet


def preprocessor(cols: list[str]) -> ColumnTransformer:
    cat = [c for c in cols if c in CATEGORICAL]
    num = [c for c in cols if c not in CATEGORICAL]
    return ColumnTransformer([
        ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), num),
        ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=20), cat),
    ])


def make_models(seed: int = 0) -> dict:
    return {
        "logistic": LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000),
        "random_forest": RandomForestClassifier(
            n_estimators=300, min_samples_leaf=5, class_weight="balanced", n_jobs=-1, random_state=seed),
        "grad_boost": HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=400, class_weight="balanced", random_state=seed),
    }


def scores(y, p, threshold: float = 0.5) -> dict:
    y = np.asarray(y)
    return {
        "roc_auc": roc_auc_score(y, p),
        "pr_auc": average_precision_score(y, p),
        # minority class = stopped (Q1) / not met (Q2), the outcome we want to flag
        "pr_auc_minority": average_precision_score(1 - y, 1 - np.asarray(p)),
        "f1_minority": f1_score(1 - y, (np.asarray(p) < threshold).astype(int)),
        "n_test": len(y),
    }


def phase_disease_baseline(train: pd.DataFrame, test: pd.DataFrame, target: str) -> np.ndarray:
    """Predict the training-set rate for the trial's (phase, disease_area) cell, with fallbacks."""
    overall = train[target].mean()
    by_phase = train.groupby("phase")[target].mean()
    by_cell = train.groupby(["phase", "disease_area"])[target].agg(["mean", "size"])
    by_cell = by_cell[by_cell["size"] >= 30]["mean"]
    keys = list(zip(test["phase"], test["disease_area"]))
    return np.array([by_cell.get(k, by_phase.get(k[0], overall)) for k in keys])


def fit(df: pd.DataFrame, target: str, groups: list[str], model: str = "grad_boost", **split):
    """Fit one model on the time split. Returns (pipeline, feature columns, test frame with `pred`)."""
    train, test = time_split(df, target, **split)
    cols = feature_list(df, groups)
    pipe = Pipeline([("prep", preprocessor(cols)), ("model", make_models()[model])])
    pipe.fit(train[cols], train[target].astype(int))
    test = test.assign(pred=pipe.predict_proba(test[cols])[:, 1])
    return pipe, cols, test


def run(df: pd.DataFrame, target: str, ablations: dict | None = None,
        models: list[str] | None = None, **split) -> pd.DataFrame:
    """Baselines + every model x feature set. `split` goes to time_split (train_max_year, years)."""
    ablations = ablations or {**ABLATIONS, **LEAKAGE_CHECK}
    train, test = time_split(df, target, **split)
    y_tr, y_te = train[target].astype(int), test[target].astype(int)
    rows = [
        {"features": "-", "model": "majority", **scores(y_te, np.full(len(y_te), y_tr.mean()))},
        {"features": "phase+disease", "model": "rate_lookup",
         **scores(y_te, phase_disease_baseline(train, test, target))},
    ]
    seen = set()
    for name, groups in ablations.items():
        cols = feature_list(df, groups)
        if tuple(cols) in seen:  # a group that isn't joined yet makes this identical to an earlier run
            continue
        seen.add(tuple(cols))
        for mname in models or make_models():
            _, _, t = fit(df, target, groups, mname, **split)
            rows.append({"features": name, "model": mname, **scores(t[target], t["pred"])})
    return pd.DataFrame(rows)


def importance(pipe, test: pd.DataFrame, cols: list[str], target: str,
               n_rows: int = 8000, seed: int = 0) -> pd.Series:
    """Permutation importance (drop in ROC-AUC when a column is shuffled) on a test-set sample."""
    s = test.sample(min(n_rows, len(test)), random_state=seed)
    r = permutation_importance(pipe, s[cols], s[target].astype(int), scoring="roc_auc",
                               n_repeats=3, random_state=seed, n_jobs=-1)
    return pd.Series(r.importances_mean, index=cols).sort_values(ascending=False)


def auc_by_group(test: pd.DataFrame, target: str, group: str, min_n: int = 200) -> pd.DataFrame:
    rows = []
    for g, d in test.groupby(group):
        if len(d) >= min_n and d[target].nunique() == 2:
            rows.append({group: g, "n": len(d), "rate": d[target].mean(),
                         "roc_auc": roc_auc_score(d[target].astype(int), d["pred"])})
    return pd.DataFrame(rows).sort_values("n", ascending=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="completed", choices=["completed", "met_primary"])
    args = ap.parse_args()
    df = pd.read_parquet(config.PROCESSED / "trials.parquet")
    res = run(df, args.target)
    print(res.round(3).to_string(index=False))
    res.to_csv(config.PROCESSED / f"results_{args.target}.csv", index=False)


if __name__ == "__main__":
    main()
