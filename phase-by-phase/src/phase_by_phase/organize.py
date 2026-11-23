"""Auditable, arm-aware organization of ClinicalTrials.gov API records.

The resulting programs are *candidate exact-label identities*, not verified
molecules. No alias, MeSH hierarchy, or fuzzy-name merges are applied. Only
single-condition, unambiguously assigned experimental drug/biologic arms enter
the strict bridge. All downloaded trials and reasons for exclusions survive.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from typing import Any

import pandas as pd

from .clean import normalize_phase


DATE_FIELDS = {
    "start_date": "startDateStruct",
    "first_post_date": "studyFirstPostDateStruct",
    "results_first_post_date": "resultsFirstPostDateStruct",
    "completion_date": "completionDateStruct",
    "primary_completion_date": "primaryCompletionDateStruct",
    "last_update_post_date": "lastUpdatePostDateStruct",
}
TRIAL_COLUMNS = [
    "nct_id", "phase", "phases_raw_json", "status", "enrollment", "enrollment_type",
    "sponsor_class", "sponsor_name", "study_type", "has_results", "condition_count",
    "arm_count", "allocation", "masking", "intervention_model", "identity_status",
] + [name for field in DATE_FIELDS for name in (field, f"{field}_precision", f"{field}_type")]
INTERVENTION_COLUMNS = [
    "nct_id", "intervention_index", "name", "intervention_type", "drug_key",
    "control_kind", "arm_group_labels_json", "other_names_json",
    "intervention_description", "assigned_arm_details_json",
]
CONDITION_COLUMNS = [
    "nct_id", "condition_index", "condition_name", "indication_id", "mesh_terms_json",
]
BRIDGE_COLUMNS = [
    "nct_id", "program_id", "regimen_id", "indication_id", "drug_group",
    "component_keys_json", "arm_label", "mapping_basis", "n_regimen_components",
    "identity_status",
]
PROGRAM_COLUMNS = [
    "program_id", "regimen_id", "indication_id", "drug_group", "component_keys_json",
    "n_regimen_components", "identity_status", "n_trials", "n_arms",
]
EXCLUSION_COLUMNS = ["nct_id", "scope", "arm_label", "reason", "detail"]
ALIAS_COLUMNS = [
    "nct_id", "intervention_index", "primary_name", "primary_key", "alias_name",
    "alias_key", "source", "review_status", "conflicting_primary_keys",
]
SCHEMAS = {
    "trials": TRIAL_COLUMNS,
    "interventions": INTERVENTION_COLUMNS,
    "conditions": CONDITION_COLUMNS,
    "program_trials": BRIDGE_COLUMNS,
    "programs": PROGRAM_COLUMNS,
    "exclusions": EXCLUSION_COLUMNS,
    "alias_candidates": ALIAS_COLUMNS,
}
_NCT = re.compile(r"NCT\d{8}\Z")
_CONTROL_TOKEN = re.compile(r"\b(?:placebo|sham)\b", re.IGNORECASE)
_MIXED_CONTROL = re.compile(r"\+|/|\b(?:and|plus|or|with|versus|vs)\b", re.IGNORECASE)
_COMPOUND_LABEL = re.compile(r"\+|/|\b(?:and|plus|versus|vs|or)\b", re.IGNORECASE)
_ALTERNATIVE_ARM_LABEL = re.compile(
    r"\b(?:or|versus|vs)\b|\bwith\s*/\s*without\b|\+\s*/\s*-", re.IGNORECASE
)
_ALTERNATIVE_DESCRIPTION = re.compile(
    r"\bwith\s+or\s+without\b|\bwith\s*/\s*without\b|\beither\b[^.;\n]{0,600}\bor\b",
    re.IGNORECASE,
)
_HEALTHY_CONDITIONS = {
    "healthy", "healthy volunteers", "healthy volunteer", "healthy participants",
    "healthy adults", "healthy subjects", "healthy subject", "normal volunteers",
}
_GENERIC_DRUG_LABELS = {
    "study drug", "investigational drug", "investigational product", "study medication",
    "chemotherapy", "standard of care", "standard therapy", "experimental drug",
    "active comparator", "control", "test drug", "drug", "medication", "treatment",
}
# Reviewed source contradictions are not molecule aliases or permanent NCT
# blacklists. Apply only while the cited contradictory text is still present.
# Evidence: cached 2026-11-19 snapshot, page_00127.json.gz; registry last update
# 2026-04-23. Arm says monotherapy, but the corresponding intervention describes
# PLB1004 plus pemetrexed and platinum chemotherapy. Do not infer which is true.
REVIEWED_SOURCE_EXCLUSIONS = {
    "NCT06281964": {
        "arm_label": "plb1004",
        "arm_description_contains": "plb1004 given alone as monotherapy",
        "intervention_name": "plb1004",
        "intervention_description_terms": ["pemetrexed", "carboplatin", "cisplatin"],
        "source_url": "https://clinicaltrials.gov/study/NCT06281964",
        "reviewed_snapshot": "2026-11-19",
        "source_last_update": "2026-04-23",
        "evidence": "PLB1004 arm states monotherapy but its assigned intervention description includes pemetrexed and carboplatin/cisplatin. Regimen identity is contradictory.",
    },
}


def label_key(value: Any) -> str | None:
    """Normalize Unicode composition, letter case, and whitespace only.

    Deliberately preserve Greek letters, accents, hyphens, slashes, doses, and
    punctuation: alpha/beta or distinct named formulations must not collapse.
    """
    if not isinstance(value, str):
        return None
    key = " ".join(unicodedata.normalize("NFC", value).lower().split())
    return key or None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _identifier(prefix: str, value: Any) -> str:
    return prefix + "_" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()[:24]


def _reviewed_source_contradiction(nct: str, arm: dict, assigned: list[dict]) -> str | None:
    evidence = REVIEWED_SOURCE_EXCLUSIONS.get(nct)
    if evidence is None or label_key(arm.get("label")) != evidence["arm_label"]:
        return None
    if evidence["arm_description_contains"] not in (label_key(arm.get("description")) or ""):
        return None
    for item in assigned:
        description = label_key(item.get("description")) or ""
        if label_key(item.get("name")) == evidence["intervention_name"] and all(
            term in description for term in evidence["intervention_description_terms"]
        ):
            return _json(evidence)
    return None


def control_kind(name: Any) -> str:
    """Separate clear controls from labels mixing active treatment and control.

    No substring-based dropping: ``Drug A + placebo`` requires review. A label
    starting with placebo/sham without joining language is a control; labels
    containing the token elsewhere are conservatively ambiguous.
    """
    key = label_key(name)
    if not key or not _CONTROL_TOKEN.search(key):
        return "not_control"
    if _MIXED_CONTROL.search(key):
        return "ambiguous_control_label"
    if re.match(r"^(?:placebo|sham)\b", key):
        return "control"
    return "ambiguous_control_label"


def _date_parts(value: Any) -> tuple[str | None, str, str | None]:
    struct = value if isinstance(value, dict) else {}
    raw = struct.get("date")
    kind = struct.get("type")
    if not raw:
        return None, "missing", kind
    raw = str(raw).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            date.fromisoformat(raw)
            precision = "day"
        elif re.fullmatch(r"\d{4}-\d{2}", raw):
            date.fromisoformat(raw + "-01")
            precision = "month"
        elif re.fullmatch(r"\d{4}", raw):
            date(int(raw), 1, 1)
            precision = "year"
        else:
            precision = "invalid"
    except ValueError:
        precision = "invalid"
    return raw, precision, kind


def _normalized_phase(phases: Any) -> str | None:
    if not isinstance(phases, list):
        return None
    # API emits EARLY_PHASE1 rather than the display label Early Phase 1.
    if phases == ["EARLY_PHASE1"]:
        return "EARLY_PHASE1"
    keys = {normalize_phase(value) for value in phases}
    if None in keys or not keys:
        return None
    if keys == {"PHASE1", "PHASE2"}:
        return "PHASE1/PHASE2"
    if keys == {"PHASE2", "PHASE3"}:
        return "PHASE2/PHASE3"
    return next(iter(keys)) if len(keys) == 1 else None


def _component_groups(bridge: pd.DataFrame) -> dict[str, str]:
    """Connect overlapping exact-label regimens for leakage-aware splitting."""
    parent: dict[str, str] = {}

    def root(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for value in bridge["component_keys_json"].unique():
        components = json.loads(value)
        for component in components:
            parent[root(component)] = root(components[0])
    groups: dict[str, list[str]] = {}
    for component in sorted(parent):
        groups.setdefault(root(component), []).append(component)
    return {
        component: _identifier("druggroup", members)
        for members in groups.values() for component in members
    }


def build_tables(studies: list[dict[str, Any]]) -> dict[str, pd.DataFrame]:
    """Return normalized source tables and a strict candidate-program bridge.

    Missing/malformed/duplicate NCT IDs fail explicitly. Clinical ambiguity
    instead produces a reasoned exclusion, retaining source records for review.
    Repeated condition *spellings* are deduplicated only after exact case/space
    normalization. Multiple distinct conditions never become a cross product.
    """
    records: dict[str, list[dict[str, Any]]] = {name: [] for name in SCHEMAS}
    seen: set[str] = set()

    def exclude(nct: str, reason: str, detail: str = "", arm: str | None = None) -> None:
        records["exclusions"].append({
            "nct_id": nct, "scope": "arm" if arm is not None else "trial",
            "arm_label": arm, "reason": reason, "detail": detail,
        })

    for position, study in enumerate(studies):
        if not isinstance(study, dict):
            raise ValueError(f"Record {position} has missing or malformed nctId: not an object")
        protocol = study.get("protocolSection", {})
        if not isinstance(protocol, dict):
            raise ValueError(f"Record {position} has missing or malformed nctId: invalid protocolSection")
        nct = protocol.get("identificationModule", {}).get("nctId")
        if not isinstance(nct, str) or not _NCT.fullmatch(nct):
            raise ValueError(f"Record {position} has missing or malformed nctId: {nct!r}")
        if nct in seen:
            raise ValueError(f"Duplicate nctId in downloaded records: {nct}")
        seen.add(nct)

        status = protocol.get("statusModule", {})
        design = protocol.get("designModule", {})
        info = design.get("designInfo", {})
        sponsor = protocol.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
        arms_module = protocol.get("armsInterventionsModule", {})
        interventions = arms_module.get("interventions", []) or []
        arms = arms_module.get("armGroups", []) or []
        conditions = protocol.get("conditionsModule", {}).get("conditions", []) or []
        indication_keys = sorted({key for value in conditions if (key := label_key(value))})
        mesh = study.get("derivedSection", {}).get("conditionBrowseModule", {}).get("meshes", [])
        mesh_terms = [m.get("term") for m in mesh if isinstance(m, dict) and m.get("term")]
        trial = {
            "nct_id": nct, "phase": _normalized_phase(design.get("phases", [])),
            "phases_raw_json": _json(design.get("phases", [])),
            "status": status.get("overallStatus"),
            "enrollment": design.get("enrollmentInfo", {}).get("count"),
            "enrollment_type": design.get("enrollmentInfo", {}).get("type"),
            "sponsor_class": sponsor.get("class"), "sponsor_name": sponsor.get("name"),
            "study_type": design.get("studyType"), "has_results": bool(study.get("hasResults", False)),
            "condition_count": len(indication_keys), "arm_count": len(arms),
            "allocation": info.get("allocation"), "masking": info.get("maskingInfo", {}).get("masking"),
            "intervention_model": info.get("interventionModel"),
            "identity_status": "exact_label_candidate_unvalidated",
        }
        for field, source in DATE_FIELDS.items():
            trial[field], trial[f"{field}_precision"], trial[f"{field}_type"] = _date_parts(status.get(source))
        records["trials"].append(trial)
        for index, condition in enumerate(conditions):
            records["conditions"].append({
                "nct_id": nct, "condition_index": index, "condition_name": condition,
                "indication_id": label_key(condition), "mesh_terms_json": _json(mesh_terms),
            })
        for index, intervention in enumerate(interventions):
            name = intervention.get("name")
            key = label_key(name)
            other_names = intervention.get("otherNames", []) or []
            assigned_labels = {label_key(value) for value in intervention.get("armGroupLabels", []) or []}
            arm_details = [{key: arm.get(key) for key in ["label", "type", "description"]}
                           for arm in arms if label_key(arm.get("label")) in assigned_labels]
            records["interventions"].append({
                "nct_id": nct, "intervention_index": index, "name": name,
                "intervention_type": intervention.get("type"), "drug_key": key,
                "control_kind": control_kind(name),
                "arm_group_labels_json": _json(intervention.get("armGroupLabels", []) or []),
                "other_names_json": _json(other_names),
                "intervention_description": intervention.get("description"),
                "assigned_arm_details_json": _json(arm_details),
            })
            if intervention.get("type") in {"DRUG", "BIOLOGICAL"} and key and control_kind(name) == "not_control":
                for alias in other_names:
                    if (alias_key := label_key(alias)) and alias_key != key:
                        records["alias_candidates"].append({
                            "nct_id": nct, "intervention_index": index, "primary_name": name,
                            "primary_key": key, "alias_name": alias, "alias_key": alias_key,
                            "source": "ClinicalTrials.gov intervention.otherNames",
                            "review_status": "not_applied_requires_review",
                        })

        reasons = []
        if trial["study_type"] != "INTERVENTIONAL":
            reasons.append("not_interventional")
        if not indication_keys:
            reasons.append("missing_condition")
        elif len(indication_keys) != 1:
            reasons.append("multiple_conditions")
        elif indication_keys[0] in _HEALTHY_CONDITIONS:
            reasons.append("healthy_volunteer_condition_not_indication")
        if len(indication_keys) == 1 and any(label_key(value) is None for value in conditions):
            reasons.append("malformed_condition")
        if trial["phase"] not in {"EARLY_PHASE1", "PHASE1", "PHASE1/PHASE2", "PHASE2", "PHASE2/PHASE3", "PHASE3"}:
            reasons.append("unsupported_or_missing_phase")
        if not interventions:
            reasons.append("missing_interventions")
        for reason in reasons:
            exclude(nct, reason)
        if reasons:
            continue

        synthetic_arm = False
        if not arms and info.get("interventionModel") == "SINGLE_GROUP":
            arms = [{"label": "__single_group__", "type": "EXPERIMENTAL"}]
            synthetic_arm = True
        if not arms:
            exclude(nct, "missing_arm_groups")
            continue
        arm_keys = [label_key(arm.get("label")) for arm in arms]
        if None in arm_keys or len(set(arm_keys)) != len(arm_keys):
            exclude(nct, "missing_or_duplicate_arm_label")
            continue
        arm_by_key = dict(zip(arm_keys, arms))
        selected = [key for key, arm in arm_by_key.items() if arm.get("type") == "EXPERIMENTAL"]
        single_arm_fallback = len(arms) == 1 and arms[0].get("type") in {None, ""}
        if single_arm_fallback:
            selected = list(arm_keys)
        if not selected:
            exclude(nct, "no_experimental_arm")
            continue

        # Recover assignments from either API direction, checking consistency.
        reverse: dict[int, set[str]] = {i: set() for i in range(len(interventions))}
        unmatched_arm_references = []
        for arm_key, arm in arm_by_key.items():
            for reference in arm.get("interventionNames", []) or []:
                matches = [i for i, item in enumerate(interventions)
                           if label_key(reference) == label_key(f"{item.get('type')}: {item.get('name')}")]
                if not matches:
                    unmatched_arm_references.append(reference)
                for i in matches:
                    reverse[i].add(arm_key)
        if unmatched_arm_references:
            exclude(nct, "unmatched_arm_intervention_reference", _json(unmatched_arm_references))
            continue

        assignments: dict[str, list[int]] = {key: [] for key in arm_by_key}
        bases: dict[str, set[str]] = {key: set() for key in arm_by_key}
        assignment_errors = []
        for i, item in enumerate(interventions):
            labels = {label_key(value) for value in (item.get("armGroupLabels", []) or [])}
            if labels - set(arm_by_key):
                assignment_errors.append("unknown_arm_assignment")
                continue
            if labels and reverse[i] and labels != reverse[i]:
                assignment_errors.append("inconsistent_arm_assignment")
                continue
            if labels:
                targets, basis = labels, "intervention_arm_labels"
            elif reverse[i]:
                targets, basis = reverse[i], "arm_intervention_names"
            elif len(arms) == 1:
                targets = set(arm_keys)
                basis = "single_group_design" if synthetic_arm else "single_arm_fallback"
            else:
                assignment_errors.append("unassigned_intervention_multiarms")
                continue
            for key in targets:
                assignments[key].append(i)
                bases[key].add(basis)
        if assignment_errors:
            for reason in sorted(set(assignment_errors)):
                exclude(nct, reason)
            continue

        for arm_key in selected:
            arm = arm_by_key[arm_key]
            arm_label = arm["label"]
            components = set()
            arm_errors = set()
            error_details = {}
            if _ALTERNATIVE_ARM_LABEL.search(arm_label):
                arm_errors.add("alternative_regimens_in_arm_label")
                error_details["alternative_regimens_in_arm_label"] = arm_label
            arm_description = arm.get("description") or ""
            if _ALTERNATIVE_DESCRIPTION.search(arm_description):
                arm_errors.add("alternative_regimens_in_arm_description")
                error_details["alternative_regimens_in_arm_description"] = arm_description
            contradiction = _reviewed_source_contradiction(
                nct, arm, [interventions[i] for i in assignments[arm_key]]
            )
            if contradiction:
                arm_errors.add("reviewed_source_regimen_contradiction")
                error_details["reviewed_source_regimen_contradiction"] = contradiction
            for i in assignments[arm_key]:
                item = interventions[i]
                kind = control_kind(item.get("name"))
                if kind == "control":
                    continue
                if kind == "ambiguous_control_label":
                    arm_errors.add("ambiguous_active_control_label")
                    continue
                if item.get("type") not in {"DRUG", "BIOLOGICAL"}:
                    arm_errors.add("non_drug_cointervention")
                    continue
                if (key := label_key(item.get("name"))) is None:
                    arm_errors.add("missing_intervention_name")
                elif key in _GENERIC_DRUG_LABELS:
                    arm_errors.add("generic_intervention_name_requires_review")
                elif _COMPOUND_LABEL.search(key):
                    # Do not guess whether a slash denotes dose, alternative,
                    # or a fixed combination; constituents require review.
                    arm_errors.add("compound_intervention_name_requires_review")
                else:
                    components.add(key)
            if not components:
                arm_errors.add("no_active_drug_in_experimental_arm")
            if arm_errors:
                for reason in sorted(arm_errors):
                    exclude(nct, reason, detail=error_details.get(reason, ""), arm=arm_label)
                continue
            components_sorted = sorted(components)
            regimen = _identifier("regimen", components_sorted)
            indication = indication_keys[0]
            records["program_trials"].append({
                "nct_id": nct, "program_id": _identifier("program", [regimen, indication]),
                "regimen_id": regimen, "indication_id": indication,
                "component_keys_json": _json(components_sorted), "arm_label": arm_label,
                "mapping_basis": "+".join(sorted(bases[arm_key])),
                "n_regimen_components": len(components_sorted),
                "identity_status": "exact_label_candidate_unvalidated",
            })

    tables = {name: pd.DataFrame.from_records(records[name], columns=columns)
              for name, columns in SCHEMAS.items()}
    bridge = tables["program_trials"]
    if not bridge.empty:
        groups = _component_groups(bridge)
        bridge["drug_group"] = bridge["component_keys_json"].map(lambda value: groups[json.loads(value)[0]])
        for program, group in bridge.groupby("program_id", sort=True):
            first = group.iloc[0]
            records["programs"].append({
                **{field: first[field] for field in PROGRAM_COLUMNS if field not in {"n_trials", "n_arms"}},
                "program_id": program, "n_trials": group["nct_id"].nunique(),
                "n_arms": len(group),
            })
        tables["programs"] = pd.DataFrame.from_records(records["programs"], columns=PROGRAM_COLUMNS)
        tables["program_trials"] = bridge.sort_values(["nct_id", "program_id", "arm_label"]).reset_index(drop=True)
    aliases = tables["alias_candidates"]
    if not aliases.empty:
        alias_counts = aliases.groupby("alias_key")["primary_key"].nunique()
        aliases["conflicting_primary_keys"] = aliases["alias_key"].map(alias_counts).gt(1)
        tables["alias_candidates"] = aliases.drop_duplicates().reset_index(drop=True)

    # Failing here is a programming/schema error, never a biological judgement.
    mapped = set(tables["program_trials"]["nct_id"])
    excluded = set(tables["exclusions"]["nct_id"])
    if seen - mapped - excluded:
        raise AssertionError(f"Unaccounted trial IDs: {sorted(seen - mapped - excluded)}")
    if tables["program_trials"].duplicated(["nct_id", "program_id", "arm_label"]).any():
        raise AssertionError("Duplicate trial/program/arm links")
    return tables
