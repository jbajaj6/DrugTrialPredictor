"""Permutation tests for H1-H3 (proposal section 5)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def permutation_test(outcome, group, n_perm: int = 10_000, seed: int = 0) -> dict:
    """Two-sided permutation test on the difference in means (rates) between group==1 and group==0."""
    y = np.asarray(outcome, dtype=float)
    g = np.asarray(group).astype(bool)
    rng = np.random.default_rng(seed)
    observed = y[g].mean() - y[~g].mean()
    n1 = g.sum()
    null = np.empty(n_perm)
    for i in range(n_perm):
        idx = rng.permutation(len(y))
        null[i] = y[idx[:n1]].mean() - y[idx[n1:]].mean()
    p = (np.sum(np.abs(null) >= abs(observed)) + 1) / (n_perm + 1)
    return {"diff": observed, "p_value": p, "n_group1": int(n1), "n_group0": int((~g).sum())}


def h1_sponsor(df: pd.DataFrame, **kw) -> dict:
    """H1: completion rate, industry vs. academic sponsors."""
    d = df[df["sponsor_class"].isin(["INDUSTRY", "ACADEMIC_OTHER"])]
    return permutation_test(d["completed"], d["sponsor_class"] == "INDUSTRY", **kw)


def h2_hype(df: pd.DataFrame, **kw) -> dict:
    """H2: completion rate, top vs. bottom quartile of pre-start Wikipedia views of the drug
    (industry trials starting 2016+ whose drug has an article)."""
    d = df[(df["sponsor_class"] == "INDUSTRY") & (df["wiki_has_article"] == 1)]
    lo, hi = d["wiki_views"].quantile([0.25, 0.75])
    d = d[(d["wiki_views"] <= lo) | (d["wiki_views"] >= hi)]
    return permutation_test(d["completed"], d["wiki_views"] >= hi, **kw)


def h3_funding(df: pd.DataFrame, **kw) -> dict:
    """H3: among academic trials, completion rate with vs. without a linked NIH grant."""
    d = df[df["sponsor_class"] == "ACADEMIC_OTHER"]
    return permutation_test(d["completed"], d["has_nih_grant"] == 1, **kw)
