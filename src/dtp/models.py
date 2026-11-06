"""Baselines, models, the feature-group ablation, and diagnostics.

    python -m dtp.models --target completed
    python -m dtp.models --target met_primary
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from scipy.stats import loguniform, randint, uniform
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.model_selection import PredefinedSplit, RandomizedSearchCV
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from dtp import config
from dtp.features import ALL_CATEGORICAL, FEATURE_GROUPS

# Headline comparison: each outside signal added to the design features.
ABLATIONS = {
    "design": ["design"],
    "design+sponsor_history": ["design", "sponsor_history"],
    "design+sponsor_history+funding": ["design", "sponsor_history", "funding"],
    "design+sponsor_history+science": ["design", "sponsor_history", "science"],
    "design+sponsor_history+text": ["design", "sponsor_history", "text"],
    "all (no hype)": ["design", "sponsor_history", "funding", "science", "text"],
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


class Winsorizer(BaseEstimator, TransformerMixin):
    """Clip each numeric column to its [lower, upper] quantiles, learned on the training rows only.

    Count features have long right tails (a few trials list 100+ secondary outcomes or conditions);
    clipping keeps those rows but stops them from dominating the scaled inputs of linear models.
    Missing values pass through untouched (the imputer handles them next)."""

    def __init__(self, lower: float = 0.01, upper: float = 0.99):
        self.lower, self.upper = lower, upper

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        self.lo_ = np.nanquantile(X, self.lower, axis=0)
        self.hi_ = np.nanquantile(X, self.upper, axis=0)
        return self

    def transform(self, X):
        return np.clip(np.asarray(X, dtype=float), self.lo_, self.hi_)

    def get_feature_names_out(self, input_features=None):
        return np.asarray(input_features, dtype=object)


def preprocessor(cols: list[str]) -> ColumnTransformer:
    """Numeric: clip outliers -> median-impute (+ missing flags) -> standardize. Categorical: one-hot.
    Everything is fit inside the model pipeline, i.e. on training rows only."""
    cat = [c for c in cols if c in ALL_CATEGORICAL]
    num = [c for c in cols if c not in ALL_CATEGORICAL]
    return ColumnTransformer([
        ("num", make_pipeline(Winsorizer(), SimpleImputer(strategy="median", add_indicator=True),
                              StandardScaler()), num),
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


# ---- Hyperparameter tuning (validation split inside the training years) --------------------------

PARAM_SPACE = {
    "logistic": {"model__C": loguniform(1e-3, 1e1)},
    "random_forest": {"model__n_estimators": randint(150, 400), "model__max_depth": [8, 12, 16, 24, None],
                      "model__min_samples_leaf": randint(2, 40), "model__max_features": ["sqrt", 0.3, 0.5]},
    "grad_boost": {"model__learning_rate": loguniform(0.02, 0.2), "model__max_iter": randint(150, 600),
                   "model__max_leaf_nodes": randint(15, 63), "model__min_samples_leaf": randint(20, 200),
                   "model__l2_regularization": uniform(0, 2)},
}


def validation_split(train: pd.DataFrame) -> PredefinedSplit:
    """-1 = always in the fitting fold (start <= 2012), 0 = validation fold (2013-2015)."""
    return PredefinedSplit(np.where(train["start_year"] >= config.VAL_MIN_YEAR, 0, -1))


def tune(df: pd.DataFrame, target: str, groups: list[str], model: str, n_iter: int = 12,
         seed: int = 0, **split) -> RandomizedSearchCV:
    """Randomized search scored by validation ROC-AUC (fit 2005-2012, validate 2013-2015).

    The best setting is then refit on all training years; the test years are never touched.
    `return_train_score` keeps training AUC so over- and underfitting are visible."""
    train, _ = time_split(df, target, **split)
    cols = feature_list(df, groups)
    pipe = Pipeline([("prep", preprocessor(cols)), ("model", make_models(seed)[model])])
    search = RandomizedSearchCV(pipe, PARAM_SPACE[model], n_iter=n_iter, scoring="roc_auc",
                                cv=validation_split(train), refit=True, random_state=seed,
                                return_train_score=True, n_jobs=1)
    search.fit(train[cols], train[target].astype(int))
    search.feature_cols_ = cols
    return search


def search_table(search: RandomizedSearchCV) -> pd.DataFrame:
    """One row per tried setting: parameters, training AUC, validation AUC, and the overfitting gap."""
    r = pd.DataFrame(search.cv_results_)
    params = r["params"].apply(pd.Series).rename(columns=lambda c: c.replace("model__", ""))
    out = params.assign(train_auc=r["mean_train_score"], val_auc=r["mean_test_score"])
    out["gap"] = out["train_auc"] - out["val_auc"]
    return out.sort_values("val_auc", ascending=False).reset_index(drop=True)


# ---- Class imbalance: weighting vs. resampling ---------------------------------------------------

def imbalance_comparison(df: pd.DataFrame, target: str, groups: list[str],
                         model: str = "grad_boost", seed: int = 0) -> pd.DataFrame:
    """Compare no adjustment, class weights, random under- and oversampling, and SMOTE on the
    validation years. Resampling sits inside the pipeline, so only training rows are resampled."""
    from imblearn.over_sampling import RandomOverSampler, SMOTE
    from imblearn.pipeline import Pipeline as ImbPipeline
    from imblearn.under_sampling import RandomUnderSampler

    train, _ = time_split(df, target)
    fit_rows, val_rows = train[train["start_year"] < config.VAL_MIN_YEAR], train[train["start_year"] >= config.VAL_MIN_YEAR]
    cols = feature_list(df, groups)
    strategies = {
        "none": None, "class weights": "weights",
        "random undersampling": RandomUnderSampler(random_state=seed),
        "random oversampling": RandomOverSampler(random_state=seed),
        "SMOTE (after encoding)": SMOTE(random_state=seed),
    }
    rows = []
    for name, sampler in strategies.items():
        est = make_models(seed)[model]
        if sampler != "weights":
            est.set_params(class_weight=None)
        steps = [("prep", preprocessor(cols))] + ([("sample", sampler)] if sampler not in (None, "weights") else [])
        pipe = ImbPipeline(steps + [("model", est)])
        pipe.fit(fit_rows[cols], fit_rows[target].astype(int))
        p = pipe.predict_proba(val_rows[cols])[:, 1]
        rows.append({"strategy": name, **scores(val_rows[target].astype(int), p)})
    return pd.DataFrame(rows)


# ---- Uncertainty: bootstrap confidence intervals -------------------------------------------------

def bootstrap_auc(y, p, n_boot: int = 1000, seed: int = 0) -> dict:
    """ROC-AUC with a 95% percentile bootstrap interval (resampling test trials with replacement)."""
    y, p = np.asarray(y), np.asarray(p)
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n_boot):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() != y[i].max():
            stats.append(roc_auc_score(y[i], p[i]))
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return {"roc_auc": roc_auc_score(y, p), "ci_low": lo, "ci_high": hi}


def paired_bootstrap_diff(y, p_a, p_b, n_boot: int = 1000, seed: int = 0) -> dict:
    """AUC(b) - AUC(a) on the same test trials, with a 95% bootstrap interval and the share of
    resamples where b does not beat a (a one-sided bootstrap p-value)."""
    y, p_a, p_b = map(np.asarray, (y, p_a, p_b))
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(n_boot):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() != y[i].max():
            d.append(roc_auc_score(y[i], p_b[i]) - roc_auc_score(y[i], p_a[i]))
    d = np.array(d)
    return {"diff": roc_auc_score(y, p_b) - roc_auc_score(y, p_a), "ci_low": np.percentile(d, 2.5),
            "ci_high": np.percentile(d, 97.5), "p_not_better": (d <= 0).mean()}


def logistic_coefficients(pipe: Pipeline) -> pd.Series:
    """Standardized coefficients of a fitted logistic pipeline, by encoded feature name.
    Positive = higher odds of the positive class (completed / met primary)."""
    names = pipe.named_steps["prep"].get_feature_names_out()
    coef = pipe.named_steps["model"].coef_.ravel()
    return pd.Series(coef, index=[n.split("__", 1)[1] for n in names]).sort_values()


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
