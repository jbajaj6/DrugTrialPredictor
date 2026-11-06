from dtp.ingest.fda import ingredient_key
from dtp.ingest.science import drug_key


def test_drug_key_matches_wikipedia_filter():
    assert drug_key("Pembrolizumab 200 mg IV") == "pembrolizumab"
    assert drug_key("ABC-123") is None      # code names have no PubMed/ChEMBL name match
    assert drug_key("Placebo") is None


def test_fda_ingredient_key_strips_salts():
    assert ingredient_key("Metformin Hydrochloride") == "metformin"
    assert ingredient_key("ATORVASTATIN CALCIUM") == "atorvastatin"
