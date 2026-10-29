from dtp.ingest.hype import normalize_drug_name


def test_normalize_drug_name():
    assert normalize_drug_name("Pembrolizumab 200 mg IV") == "pembrolizumab"
    assert normalize_drug_name("abc-123") == "ABC-123"
    assert normalize_drug_name("Metformin (Glucophage) tablets") == "metformin"
