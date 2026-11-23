"""Loss-conscious ClinicalTrials.gov results extraction and dated trial rows.

Registry records are current versions, not historical snapshots. Dates here gate
public availability of results; they do not prove that every field had its
current value at that date. Program IDs are candidate exact-label identities.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from typing import Any

import pandas as pd


SCHEMAS = {
    "result_arms": ["nct_id", "module", "group_id", "title", "description", "results_first_post_date"],
    "participant_flow": ["nct_id", "period_index", "period_title", "kind", "item_index", "item_type", "group_id", "num_subjects_raw", "results_first_post_date"],
    "outcomes": ["nct_id", "outcome_index", "outcome_type", "title", "reporting_status", "unit", "param_type", "time_frame", "group_id", "class_index", "class_title", "category_index", "category_title", "value_raw", "lower_limit_raw", "upper_limit_raw", "denominator_raw", "denominator_unit", "results_first_post_date"],
    "analyses": ["nct_id", "outcome_index", "outcome_type", "analysis_index", "group_ids_json", "group_description", "p_value_raw", "p_operator", "p_value_numeric", "p_significant_005", "statistical_method", "param_type", "param_value_raw", "ci_lower_raw", "ci_upper_raw", "results_first_post_date"],
    "adverse_events": ["nct_id", "event_kind", "event_index", "term", "organ_system", "group_id", "subjects_affected_raw", "subjects_at_risk_raw", "events_raw", "assessment_type", "results_first_post_date"],
}

PHASES = {"PHASE1", "PHASE2", "PHASE3"}
TERMINAL_NONCOMPLETION = {"TERMINATED", "WITHDRAWN"}
_P = re.compile(r"^\s*(<=|>=|<|>|=)?\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*$")


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _day(value: Any) -> pd.Timestamp | None:
    """Only exact dates are usable for temporal attribution."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return pd.Timestamp(value)


def _date_text(value: Any) -> str | None:
    return value if _day(value) is not None else None


def _p_value(value: Any) -> tuple[str | None, float | None, bool | None]:
    """Return qualifier, numeric bound, and defensible threshold decision.

    For example '<0.05' is significant but '<0.1' is indeterminate. A
    comparison of a p-value with 0.05 is not a probability of success.
    """
    match = _P.fullmatch(str(value)) if value is not None else None
    if match is None:
        return None, None, None
    op, raw = match.groups()
    op = op or "="
    number = float(raw)
    if op in {"=", "<", "<="} and number < 0.05:
        return op, number, True
    if op == "<" and number <= 0.05:
        return op, number, True
    if op in {"=", ">", ">="} and number >= 0.05:
        return op, number, False
    if op == ">" and number >= 0.05:
        return op, number, False
    return op, number, None


def build_structured_tables(studies: list[dict[str, Any]]) -> dict[str, pd.DataFrame]:
    """Extract child tables without collapsing arms, outcomes, or event terms.

    The raw registry's first results-posting date is repeated on child rows as
    a conservative public-availability gate; later revisions are not dated by
    this first-post date and remain a documented historical-version caveat.
    """
    rows: dict[str, list[dict[str, Any]]] = {key: [] for key in SCHEMAS}
    seen: set[str] = set()
    for study in studies:
        protocol = _as_dict(_as_dict(study).get("protocolSection"))
        nct = _as_dict(protocol.get("identificationModule")).get("nctId")
        if not isinstance(nct, str) or not re.fullmatch(r"NCT\d{8}", nct):
            raise ValueError(f"invalid nctId: {nct!r}")
        if nct in seen:
            raise ValueError(f"duplicate nctId: {nct}")
        seen.add(nct)
        status = _as_dict(protocol.get("statusModule"))
        posted = _as_dict(status.get("resultsFirstPostDateStruct")).get("date")
        posted = _date_text(posted)
        result = _as_dict(_as_dict(study).get("resultsSection"))

        for module_key, module_name in (("participantFlowModule", "participant_flow"), ("outcomeMeasuresModule", "outcome"), ("adverseEventsModule", "adverse_events")):
            module = _as_dict(result.get(module_key))
            group_field = "eventGroups" if module_key == "adverseEventsModule" else "groups"
            for group in _as_list(module.get(group_field)):
                rows["result_arms"].append({"nct_id": nct, "module": module_name, "group_id": group.get("id"), "title": group.get("title"), "description": group.get("description"), "results_first_post_date": posted})
                if module_key == "adverseEventsModule":
                    for kind in ("serious", "other"):
                        rows["adverse_events"].append({"nct_id": nct, "event_kind": f"{kind}_total", "event_index": None, "term": None, "organ_system": None, "group_id": group.get("id"), "subjects_affected_raw": group.get(f"{kind}NumAffected"), "subjects_at_risk_raw": group.get(f"{kind}NumAtRisk"), "events_raw": None, "assessment_type": None, "results_first_post_date": posted})

        flow = _as_dict(result.get("participantFlowModule"))
        for period_index, period in enumerate(_as_list(flow.get("periods"))):
            for kind, section, members in (("milestone", "milestones", "achievements"), ("drop_withdraw", "dropWithdraws", "reasons")):
                for item_index, item in enumerate(_as_list(period.get(section))):
                    for value in _as_list(item.get(members)):
                        rows["participant_flow"].append({"nct_id": nct, "period_index": period_index, "period_title": period.get("title"), "kind": kind, "item_index": item_index, "item_type": item.get("type"), "group_id": value.get("groupId"), "num_subjects_raw": value.get("numSubjects"), "results_first_post_date": posted})

        outcomes = _as_dict(result.get("outcomeMeasuresModule"))
        for outcome_index, outcome in enumerate(_as_list(outcomes.get("outcomeMeasures"))):
            base = {"nct_id": nct, "outcome_index": outcome_index, "outcome_type": outcome.get("type"), "results_first_post_date": posted}
            for group in _as_list(outcome.get("groups")):
                rows["result_arms"].append({"nct_id": nct, "module": f"outcome:{outcome_index}", "group_id": group.get("id"), "title": group.get("title"), "description": group.get("description"), "results_first_post_date": posted})
            denoms = {}
            for denom in _as_list(outcome.get("denoms")):
                for count in _as_list(denom.get("counts")):
                    denoms[count.get("groupId")] = (count.get("value"), denom.get("units"))
            for class_index, cls in enumerate(_as_list(outcome.get("classes"))):
                class_denoms = denoms.copy()
                for denom in _as_list(cls.get("denoms")):
                    for count in _as_list(denom.get("counts")):
                        class_denoms[count.get("groupId")] = (count.get("value"), denom.get("units"))
                for category_index, category in enumerate(_as_list(cls.get("categories"))):
                    for measurement in _as_list(category.get("measurements")):
                        gid = measurement.get("groupId")
                        denominator, denominator_unit = class_denoms.get(gid, (None, None))
                        rows["outcomes"].append({**base, "title": outcome.get("title"), "reporting_status": outcome.get("reportingStatus"), "unit": outcome.get("unitOfMeasure"), "param_type": outcome.get("paramType"), "time_frame": outcome.get("timeFrame"), "group_id": gid, "class_index": class_index, "class_title": cls.get("title"), "category_index": category_index, "category_title": category.get("title"), "value_raw": measurement.get("value"), "lower_limit_raw": measurement.get("lowerLimit"), "upper_limit_raw": measurement.get("upperLimit"), "denominator_raw": denominator, "denominator_unit": denominator_unit})
            for analysis_index, analysis in enumerate(_as_list(outcome.get("analyses"))):
                op, number, significant = _p_value(analysis.get("pValue"))
                rows["analyses"].append({**base, "analysis_index": analysis_index, "group_ids_json": json.dumps(_as_list(analysis.get("groupIds")), separators=(",", ":")), "group_description": analysis.get("groupDescription"), "p_value_raw": analysis.get("pValue"), "p_operator": op, "p_value_numeric": number, "p_significant_005": significant, "statistical_method": analysis.get("statisticalMethod"), "param_type": analysis.get("paramType"), "param_value_raw": analysis.get("paramValue"), "ci_lower_raw": analysis.get("ciLowerLimit"), "ci_upper_raw": analysis.get("ciUpperLimit")})

        adverse = _as_dict(result.get("adverseEventsModule"))
        for kind, field in (("serious", "seriousEvents"), ("other", "otherEvents")):
            for event_index, event in enumerate(_as_list(adverse.get(field))):
                for stat in _as_list(event.get("stats")):
                    rows["adverse_events"].append({"nct_id": nct, "event_kind": kind, "event_index": event_index, "term": event.get("term"), "organ_system": event.get("organSystem"), "group_id": stat.get("groupId"), "subjects_affected_raw": stat.get("numAffected"), "subjects_at_risk_raw": stat.get("numAtRisk"), "events_raw": stat.get("numEvents"), "assessment_type": event.get("assessmentType"), "results_first_post_date": posted})
    return {name: pd.DataFrame.from_records(rows[name], columns=columns) for name, columns in SCHEMAS.items()}


def _significance_label(analyses: pd.DataFrame, nct: str, posted: pd.Timestamp | None, cutoff: pd.Timestamp) -> bool | None:
    if posted is None or pd.isna(posted) or posted > cutoff:
        return None
    primary = analyses.loc[(analyses.nct_id == nct) & (analyses.outcome_type == "PRIMARY")]
    if primary.empty:
        return None
    decisions = primary.p_significant_005.tolist()
    if any(value is True for value in decisions):
        return True
    if all(value is False for value in decisions):
        return False
    return None


def _flow_retention(frame: pd.DataFrame) -> float | None:
    """Whole-trial completed/started ratio from a single flow period only."""
    frame = frame.loc[frame.kind == "milestone"]
    if frame.empty or frame.period_index.nunique() != 1:
        return None
    frame = frame.loc[frame.item_type.isin(["STARTED", "COMPLETED"])].copy()
    if frame.duplicated(["item_type", "group_id"]).any():
        return None
    frame["subjects"] = pd.to_numeric(frame.num_subjects_raw, errors="coerce")
    if frame.subjects.isna().any():
        return None
    counts = frame.pivot(index="group_id", columns="item_type", values="subjects")
    if not {"STARTED", "COMPLETED"}.issubset(counts.columns) or counts.isna().any().any():
        return None
    if (counts.COMPLETED > counts.STARTED).any() or counts.STARTED.sum() <= 0:
        return None
    return float(counts.COMPLETED.sum() / counts.STARTED.sum())


def _sae_max_rate(frame: pd.DataFrame) -> float | None:
    """Max reported per-group serious-event *people* rate, not summed terms."""
    frame = frame.loc[frame.event_kind == "serious_total"].copy()
    if frame.empty or frame.duplicated("group_id").any():
        return None
    affected = pd.to_numeric(frame.subjects_affected_raw, errors="coerce")
    at_risk = pd.to_numeric(frame.subjects_at_risk_raw, errors="coerce")
    valid = affected.notna() & at_risk.notna() & at_risk.gt(0) & affected.ge(0) & affected.le(at_risk)
    if not valid.all():
        return None
    return float((affected / at_risk).max())


def build_trial_snapshots(tables: dict[str, pd.DataFrame], structured_tables: dict[str, pd.DataFrame], cutoff: str | pd.Timestamp) -> pd.DataFrame:
    """One launch-dated row per eligible pure-phase trial and candidate program.

    A target's own results/status are labels only, never features. Earlier-trial
    result features require exact first-public date and earlier actual start.
    Undated results are excluded. No target after the cutoff is emitted.
    """
    end = _day(str(cutoff)[:10])
    if end is None:
        raise ValueError("cutoff must be an exact ISO day")
    trial = tables["trials"].copy()
    bridge = tables["program_trials"]["nct_id program_id".split()].drop_duplicates()
    columns = ["nct_id", "program_id", "phase", "prediction_date", "completion_label", "significance_label", "completion_label_available_date", "significance_label_available_date", "label_available_date", "prior_result_count", "prior_result_count_firstpost_gated", "prior_primary_significant_count", "prior_primary_tested_count", "prior_primary_analysis_count", "prior_flow_retention_mean", "prior_sae_max_rate_mean", "max_evidence_date", "result_content_version_verified", "historical_design_verified", "sponsor_class", "allocation", "masking", "arm_count", "identity_status"]
    if bridge.empty:
        return pd.DataFrame(columns=columns)
    trial = trial.merge(bridge, on="nct_id", how="inner", validate="one_to_many")
    trial = trial.loc[trial.phase.isin(PHASES)].copy()
    trial["start_ts"] = trial.start_date.map(_day)
    trial["first_post_ts"] = trial.first_post_date.map(_day)
    trial["result_post_ts"] = trial.results_first_post_date.map(_day)
    trial["completion_ts"] = trial.completion_date.map(_day)
    trial["last_update_ts"] = trial.last_update_post_date.map(_day) if "last_update_post_date" in trial else pd.NaT
    analyses = structured_tables["analyses"]
    flow = structured_tables["participant_flow"]
    events = structured_tables["adverse_events"]
    # Preindex only trials that could possibly be prior result evidence. Most
    # target programs have no such rows, so they need no per-target frame work.
    history_by_program: dict[str, list] = defaultdict(list)
    trial_rows = list(trial.itertuples(index=False))
    rank = {"PHASE1": 1, "PHASE2": 2, "PHASE3": 3}
    for candidate in trial_rows:
        if (pd.notna(candidate.start_ts) and pd.notna(candidate.first_post_ts)
                and pd.notna(candidate.result_post_ts)
                and candidate.result_post_ts >= candidate.start_ts
                and candidate.result_post_ts >= candidate.first_post_ts):
            history_by_program[candidate.program_id].append(candidate)
    primary = analyses.loc[analyses.outcome_type.eq("PRIMARY")]
    analysis_counts = primary.groupby("nct_id").size().to_dict()
    posted_by_nct = dict(trial[["nct_id", "result_post_ts"]].drop_duplicates().itertuples(index=False, name=None))
    significance = {
        nct: _significance_label(group, nct, posted_by_nct.get(nct), end)
        for nct, group in primary.groupby("nct_id", sort=False)
    }
    flow_retention = {nct: _flow_retention(group) for nct, group in flow.groupby("nct_id", sort=False)}
    sae_rate = {nct: _sae_max_rate(group) for nct, group in events.groupby("nct_id", sort=False)}
    records = []
    for row in trial_rows:
        if str(row.start_date_type).upper() != "ACTUAL" or pd.isna(row.start_ts) or pd.isna(row.first_post_ts):
            continue
        prediction = max(row.start_ts, row.first_post_ts)
        if prediction > end:
            continue
        prior_candidates = []
        seen_prior: set[str] = set()
        for item in history_by_program.get(row.program_id, ()):
            if (item.nct_id != row.nct_id and item.nct_id not in seen_prior
                    and item.start_ts < prediction and item.first_post_ts <= prediction
                    and item.result_post_ts <= prediction and rank[item.phase] < rank[row.phase]):
                prior_candidates.append(item)
                seen_prior.add(item.nct_id)
        exploratory_count = len(prior_candidates)
        # A current record revised after the prediction date cannot establish
        # that its current numeric results were available at first posting.
        prior = [item for item in prior_candidates if pd.notna(item.last_update_ts) and item.last_update_ts <= prediction]
        prior_decisions = [significance.get(item.nct_id) for item in prior]
        prior_flow = [flow_retention.get(item.nct_id) for item in prior]
        prior_sae = [sae_rate.get(item.nct_id) for item in prior]
        prior_flow = [value for value in prior_flow if value is not None]
        prior_sae = [value for value in prior_sae if value is not None]
        completion = None
        completion_available = None
        if pd.notna(row.completion_ts) and pd.notna(row.last_update_ts) and str(row.completion_date_type).upper() == "ACTUAL":
            completion_available = max(row.completion_ts, row.last_update_ts)
        if completion_available is not None and completion_available <= end:
            if row.status == "COMPLETED":
                completion = True
            elif row.status in TERMINAL_NONCOMPLETION:
                completion = False
        significance_available = max(row.result_post_ts, row.last_update_ts) if pd.notna(row.result_post_ts) and pd.notna(row.last_update_ts) else None
        sig_label = significance.get(row.nct_id) if significance_available is not None and significance_available <= end else None
        available = [value for value in (completion_available if completion is not None else None, significance_available if sig_label is not None else None) if value is not None]
        records.append({"nct_id": row.nct_id, "program_id": row.program_id, "phase": row.phase, "prediction_date": prediction.strftime("%Y-%m-%d"), "completion_label": completion, "significance_label": sig_label, "completion_label_available_date": completion_available.strftime("%Y-%m-%d") if completion is not None else None, "significance_label_available_date": significance_available.strftime("%Y-%m-%d") if sig_label is not None else None, "label_available_date": max(available).strftime("%Y-%m-%d") if available else None, "prior_result_count": len(prior), "prior_result_count_firstpost_gated": exploratory_count, "prior_primary_significant_count": sum(value is True for value in prior_decisions), "prior_primary_tested_count": sum(value is not None for value in prior_decisions), "prior_primary_analysis_count": sum(analysis_counts.get(item.nct_id, 0) for item in prior), "prior_flow_retention_mean": sum(prior_flow) / len(prior_flow) if prior_flow else None, "prior_sae_max_rate_mean": sum(prior_sae) / len(prior_sae) if prior_sae else None, "max_evidence_date": max(item.last_update_ts for item in prior).strftime("%Y-%m-%d") if prior else None, "result_content_version_verified": bool(exploratory_count and len(prior) == exploratory_count), "historical_design_verified": bool(pd.notna(row.last_update_ts) and row.last_update_ts <= prediction), "sponsor_class": getattr(row, "sponsor_class", None), "allocation": getattr(row, "allocation", None), "masking": getattr(row, "masking", None), "arm_count": getattr(row, "arm_count", None), "identity_status": getattr(row, "identity_status", None)})
    return pd.DataFrame.from_records(records, columns=columns)
