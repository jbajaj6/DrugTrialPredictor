"""End-to-end smoke test on a fake AACT dump: ingest SQL -> features -> models -> stats."""
import pandas as pd
import pytest

from dtp import stats
from dtp.features import build
from dtp.ingest.aact import from_flatfiles
from dtp.ingest.hype import normalize_drug_name
from dtp.models import run

from fake_aact import write_fake_aact


@pytest.fixture(scope="module")
def trials(tmp_path_factory):
    d = write_fake_aact(tmp_path_factory.mktemp("aact"))
    return build(from_flatfiles(d))


def test_sql_filters(trials):
    assert trials["nct_id"].is_unique
    assert set(trials["overall_status"]) <= {"COMPLETED", "TERMINATED", "WITHDRAWN"}
    assert trials["start_year"].between(2005, 2019).all()
    assert 300 < len(trials) < 600


def test_labels(trials):
    assert trials["completed"].isin([0, 1]).all()
    tb = trials[trials["met_primary"].notna()]
    assert (tb["completed"] == 1).all()
    assert len(tb) > 0


def test_no_leaky_columns_in_features(trials):
    from dtp.features import FEATURE_GROUPS
    feats = {c for cols in FEATURE_GROUPS.values() for c in cols}
    assert not any(c.startswith(("post_", "label_")) for c in feats)
    assert not {"completed", "met_primary", "overall_status"} & feats


def test_models_run(trials):
    res = run(trials, "completed")
    assert {"majority", "rate_lookup", "logistic", "random_forest", "grad_boost"} <= set(res["model"])
    assert res["roc_auc"].between(0, 1).all()


def test_permutation(trials):
    out = stats.h1_sponsor(trials, n_perm=500)
    assert 0 < out["p_value"] <= 1


def test_normalize_drug_name():
    assert normalize_drug_name("Pembrolizumab 200 mg IV") == "pembrolizumab"
    assert normalize_drug_name("abc-123") == "ABC-123"
    assert normalize_drug_name("Metformin (Glucophage) tablets") == "metformin"
