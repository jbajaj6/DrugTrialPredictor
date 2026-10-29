from dtp.features import parse_age_years, why_stopped_category


def test_parse_age_years():
    assert parse_age_years("18 Years") == 18
    assert parse_age_years("6 Months") == 0.5
    assert parse_age_years("N/A") != parse_age_years("N/A")  # NaN


def test_why_stopped_ignores_negated_safety():
    assert why_stopped_category("Business reasons not related to safety") == "business"
    assert why_stopped_category("Recruitment difficulties; no safety concerns") == "enrollment"
    assert why_stopped_category("Safety concerns in the treatment arm") == "safety"
    assert why_stopped_category("Insufficient clinical activity") == "efficacy"
    assert why_stopped_category("") is None
