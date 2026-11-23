"""Dependency-free contracts for Leo's within-phase experiment."""
import re

CATEGORICAL = ["sponsor_class", "allocation", "intervention_model", "masking",
               "primary_purpose", "disease_area", "elig_gender"]
NUMERIC = ["number_of_arms", "has_dmc", "n_collaborators", "start_year",
           "n_mesh_terms", "n_conditions", "n_drug_interventions", "n_disease_areas",
           "n_primary_outcomes", "n_secondary_outcomes", "has_placebo_arm",
           "has_active_comparator", "has_no_intervention_arm", "elig_healthy_volunteers",
           "elig_min_age_yrs", "elig_max_age_yrs", "elig_pediatric",
           "sponsor_prior_finished", "sponsor_first_trial"]
FEATURES = CATEGORICAL + NUMERIC
STATUSES = {"COMPLETED", "TERMINATED", "WITHDRAWN"}

def phase_name(value):
    text = re.sub(r"[\s_]", "", str(value).upper())
    return {"PHASE1": "PHASE1", "PHASE2": "PHASE2", "PHASE3": "PHASE3",
            "PHASE1/PHASE2": "PHASE1/PHASE2", "PHASE2/PHASE3": "PHASE2/PHASE3",
            "EARLYPHASE1": "EARLY_PHASE1"}.get(text, "OTHER")

def completion_label(status):
    return int(status == "COMPLETED") if status in STATUSES else None

def significance_label(status, p):
    """Existing numeric MIN-p proxy; qualifiers cannot be recovered from this table."""
    if status != "COMPLETED" or p is None:
        return None
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    if not 0 <= p <= 1:
        return None
    return int(p < .05)

def validate_features(columns):
    unknown = set(columns) - set(FEATURES)
    if unknown:
        raise ValueError(f"Unapproved model features: {sorted(unknown)}")
    if len(columns) != len(set(columns)):
        raise ValueError("Duplicate model feature")

def split_year(year):
    if 2005 <= year <= 2012:
        return "train"
    if 2013 <= year <= 2014:
        return "validation"
    if year == 2015:
        return "calibration"
    if 2016 <= year <= 2019:
        return "test"
    return "excluded"

def supported(labels, minimum=20):
    return sum(v == 0 for v in labels) >= minimum and sum(v == 1 for v in labels) >= minimum

def verify_split_records(records, group_key=None):
    """Fail on repeated trial IDs, bad year routing or cross-split related groups.

    Optional groups must be validated upstream; this does not infer drug aliases.
    """
    seen = set()
    groups = {}
    counts = {s: 0 for s in ["train", "validation", "calibration", "test", "excluded"]}
    for row in records:
        trial = row.get("nct_id")
        if not isinstance(trial, str) or not trial.strip():
            raise ValueError("Missing/invalid trial ID in split manifest")
        if trial in seen:
            raise ValueError(f"Trial repeated in split manifest: {trial}")
        seen.add(trial)
        year = row.get("start_year")
        try:
            numeric_year = float(year)
            if not numeric_year.is_integer(): raise ValueError("Non-integer year")
            expected = split_year(int(numeric_year))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Missing/invalid split year") from exc
        split = row.get("split")
        if split != expected:
            raise ValueError(f"Wrong split for {trial}: {split}, expected {expected}")
        counts[split] += 1
        if group_key and split != "excluded":
            group = row.get(group_key)
            if not isinstance(group, str) or not group.strip():
                raise ValueError("Missing validated leakage group")
            if group in groups and groups[group] != split:
                raise ValueError(f"Related group crosses partitions: {group}")
            groups[group] = split
    return {"unique_trials": len(seen), "partition_counts": counts,
            "trial_id_overlap": 0, "group_check": group_key or "unavailable"}

def assert_fit_partition(records, allowed_splits):
    """Guard every estimator fit, including the probability calibrator."""
    allowed = set(allowed_splits)
    if not allowed or not allowed <= {"train", "calibration"}:
        raise ValueError("Only train or calibration may fit their assigned estimator")
    for row in records:
        if row.get("split") not in allowed:
            raise ValueError(f"Forbidden fitting partition: {row.get('split')}")

