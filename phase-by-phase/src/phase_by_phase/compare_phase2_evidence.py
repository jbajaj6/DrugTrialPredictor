"""B9: dated Phase 1 evidence for Phase 2 significance, development only.

The 200-day arm models an *assumed* sponsor information set. Current registry
result content is not a historical version, even when its first-post date is
known; neither arm is a verified prospective reconstruction.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from .acquire import sha256


HOLDOUT = pd.Timestamp("2024-01-01")
TRAIN_END = pd.Timestamp("2016-01-01")
VALIDATION_END = pd.Timestamp("2020-01-01")
LAG_DAYS = 200
SOURCE_COLUMNS = ["nct_id", "phase", "primary_completion_date",
                  "primary_completion_date_precision", "primary_completion_date_type",
                  "results_first_post_date", "results_first_post_date_precision",
                  "last_update_post_date"]
TARGET_COLUMNS = ["nct_id", "phase_stratum", "first_post_date", "start_date",
                  "qualifier_aware_significance_label",
                  "qualifier_aware_significance_available_date", "prospective_at_checkpoint"]
FEATURES = ["launch_year", "prior_result_count", "prior_primary_tested_count",
            "prior_primary_significant_count"]


def _exact_day(values: pd.Series) -> pd.Series:
    text = values.astype("string")
    valid = text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").fillna(False)
    return pd.to_datetime(text.where(valid), errors="coerce")


def _date_bounds(raw: object, precision: object) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return possible interval, never an imputed clinical event date."""
    if not isinstance(raw, str):
        return pd.NaT, pd.NaT
    if str(precision).lower() == "day":
        parsed = _exact_day(pd.Series([raw])).iloc[0]
        return parsed, parsed
    if str(precision).lower() == "month":
        if not pd.Series([raw]).astype("string").str.fullmatch(r"\d{4}-\d{2}").iloc[0]:
            return pd.NaT, pd.NaT
        try:
            month = pd.Period(raw, freq="M")
        except ValueError:
            return pd.NaT, pd.NaT
        return month.start_time.normalize(), month.end_time.normalize()
    return pd.NaT, pd.NaT


def _require(frame: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"{name} missing columns: {missing}")


def build_rows(targets: pd.DataFrame, trials: pd.DataFrame, links: pd.DataFrame,
               analyses: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return one row per pre-2024 Phase 2 NCT; candidate links are audit only.

    Duplicate NCT/program links or conflicting NCT-level provenance fail closed.
    The result content has no historical version; counts describe sensitivity
    arms, not verified as-of sponsor knowledge.
    """
    _require(targets, TARGET_COLUMNS, "targets")
    _require(trials, SOURCE_COLUMNS, "trials")
    _require(links, ["nct_id", "program_id", "drug_group"], "links")
    _require(analyses, ["nct_id", "outcome_type", "p_significant_005"], "analyses")
    if targets.nct_id.duplicated().any() or trials.nct_id.duplicated().any():
        raise ValueError("Duplicate NCT source rows")
    if links.groupby(["nct_id", "program_id"]).drug_group.nunique().gt(1).any():
        raise ValueError("Conflicting candidate NCT/program link")
    if links.groupby("program_id").drug_group.nunique().gt(1).any():
        raise ValueError("Program maps to conflicting drug groups")
    duplicate_links_collapsed = int(links.duplicated(["nct_id", "program_id"]).sum())
    links = links.drop_duplicates(["nct_id", "program_id"])
    target = targets.loc[targets.phase_stratum.eq("PHASE2")].copy()
    first = _exact_day(target.first_post_date)
    # Remove the sealed holdout before reading target labels or their dates.
    target = target.loc[first.lt(HOLDOUT)].copy()
    target["checkpoint"] = pd.concat([_exact_day(target.first_post_date),
                                       _exact_day(target.start_date)], axis=1).max(axis=1)
    target = target.loc[target.checkpoint.notna() & target.checkpoint.lt(HOLDOUT) &
                        target.prospective_at_checkpoint.eq(True)].copy()
    target["label"] = target.qualifier_aware_significance_label
    target["label_available"] = _exact_day(target.qualifier_aware_significance_available_date)
    if (target.label_available.notna() & target.label_available.le(target.checkpoint)).any():
        raise ValueError("Target label available on/before prediction checkpoint")
    # A target may have multiple candidate programs, but its label contributes
    # exactly once to evaluation. Ambiguous links are retained as audit rows.
    phase1 = trials.loc[trials.phase.eq("PHASE1"), SOURCE_COLUMNS].copy()
    phase1_bounds = [_date_bounds(raw, precision) for raw, precision in zip(
        phase1.primary_completion_date, phase1.primary_completion_date_precision)]
    phase1["primary_earliest"] = pd.to_datetime(
        pd.Series([x[0] for x in phase1_bounds], index=phase1.index), errors="coerce")
    phase1["primary_latest"] = pd.to_datetime(
        pd.Series([x[1] for x in phase1_bounds], index=phase1.index), errors="coerce")
    phase1["post_day"] = _exact_day(phase1.results_first_post_date)
    phase1["update_day"] = _exact_day(phase1.last_update_post_date)
    phase1["date_ok"] = (phase1.primary_completion_date_type.astype("string").str.upper().eq("ACTUAL") &
                         phase1.results_first_post_date_precision.astype("string").str.lower().eq("day") &
                         phase1.primary_latest.notna() & phase1.post_day.notna() & phase1.update_day.notna() &
                         phase1.primary_latest.le(phase1.post_day))
    primary = analyses.loc[analyses.outcome_type.eq("PRIMARY")]
    def decide(group: pd.DataFrame) -> bool | None:
        values = [bool(v) for v in group.p_significant_005 if pd.notna(v)]
        if any(values):
            return True
        if len(values) == len(group) and values:
            return False
        return None
    decisions = {nct: decide(group) for nct, group in primary.groupby("nct_id", sort=False)}
    phase1["prior_decision"] = phase1.nct_id.map(decisions)
    target_source = trials.set_index("nct_id")
    link_map = links.groupby("program_id").nct_id.apply(lambda x: tuple(sorted(set(x)))).to_dict()
    target_links = links.groupby("nct_id").program_id.apply(lambda x: tuple(sorted(set(x)))).to_dict()
    histories = phase1.set_index("nct_id").to_dict("index")
    records = []
    audit = {"phase2_targets": len(target), "duplicate_identical_candidate_links_collapsed": duplicate_links_collapsed,
             "linked_targets": 0,
             "ambiguous_target_links": 0, "phase1_candidates": 0,
             "excluded_missing_or_inexact_source_date": 0,
             "excluded_current_result_revision_after_window": 0,
             "eligible_phase1_month_completion_candidates": 0,
             "target_timing_verified_exact_day": 0,
             "target_timing_verified_safe_month": 0}
    for row in target.itertuples(index=False):
        programs = target_links.get(row.nct_id, ())
        own = target_source.loc[row.nct_id] if row.nct_id in target_source.index else None
        own_primary_earliest, own_primary_latest = (
            _date_bounds(own.primary_completion_date, own.primary_completion_date_precision)
            if own is not None else (pd.NaT, pd.NaT))
        own_result = (_exact_day(pd.Series([own.results_first_post_date])).iloc[0]
                      if own is not None else pd.NaT)
        target_timing_verified = bool(
            own is not None and str(own.primary_completion_date_type).upper() == "ACTUAL" and
            pd.notna(own_primary_earliest) and own_primary_earliest > row.checkpoint and
            (pd.isna(own_result) or own_result > row.checkpoint))
        if target_timing_verified:
            if str(own.primary_completion_date_precision).lower() == "day":
                audit["target_timing_verified_exact_day"] += 1
            else:
                audit["target_timing_verified_safe_month"] += 1
        if programs:
            audit["linked_targets"] += 1
        if len(programs) > 1:
            audit["ambiguous_target_links"] += 1
        public_ids: set[str] = set()
        proxy_ids: set[str] = set()
        candidate_ids = set().union(*(link_map.get(p, ()) for p in programs)) if programs else set()
        for prior_id in candidate_ids - {row.nct_id}:
            item = histories.get(prior_id)
            if item is None:
                continue
            audit["phase1_candidates"] += 1
            if not item["date_ok"]:
                audit["excluded_missing_or_inexact_source_date"] += 1
                continue
            if item["primary_latest"] > row.checkpoint:
                continue
            if str(item["primary_completion_date_precision"]).lower() == "month":
                audit["eligible_phase1_month_completion_candidates"] += 1
            if item["post_day"] <= row.checkpoint and item["update_day"] <= row.checkpoint:
                public_ids.add(prior_id)
            elif (row.checkpoint < item["post_day"] <= row.checkpoint + pd.Timedelta(days=LAG_DAYS)
                  and item["update_day"] <= row.checkpoint + pd.Timedelta(days=LAG_DAYS)):
                proxy_ids.add(prior_id)
            elif item["post_day"] <= row.checkpoint + pd.Timedelta(days=LAG_DAYS):
                audit["excluded_current_result_revision_after_window"] += 1
        def counts(ids: set[str]) -> tuple[int, int, int]:
            values = [histories[nct]["prior_decision"] for nct in ids]
            return len(ids), sum(v is not None for v in values), sum(v is True for v in values)
        pub = counts(public_ids)
        prox = counts(public_ids | proxy_ids)
        records.append({"nct_id": row.nct_id, "checkpoint": row.checkpoint.strftime("%Y-%m-%d"),
                        "label": row.label, "label_available": (row.label_available.strftime("%Y-%m-%d")
                                                                  if pd.notna(row.label_available) else None),
                        "candidate_program_ids_json": json.dumps(programs),
                        "candidate_link_count": len(programs),
                        "target_timing_verified": target_timing_verified,
                        "public_prior_nct_ids_json": json.dumps(sorted(public_ids)),
                        "proxy_only_prior_nct_ids_json": json.dumps(sorted(proxy_ids)),
                        "public_prior_result_count": pub[0], "public_prior_primary_tested_count": pub[1],
                        "public_prior_primary_significant_count": pub[2],
                        "proxy_prior_result_count": prox[0], "proxy_prior_primary_tested_count": prox[1],
                        "proxy_prior_primary_significant_count": prox[2],
                        "historical_result_content_verified": False})
    result = pd.DataFrame.from_records(records)
    if not result.empty and result.nct_id.duplicated().any():
        raise AssertionError("Target duplication after candidate linking")
    audit["public_with_prior"] = int(result.public_prior_result_count.gt(0).sum()) if len(result) else 0
    audit["proxy_with_additional_prior"] = int((result.proxy_prior_result_count >
                                                 result.public_prior_result_count).sum()) if len(result) else 0
    audit["labeled_targets"] = int(result.label.notna().sum()) if len(result) else 0
    audit["target_timing_verified"] = int(result.target_timing_verified.sum()) if len(result) else 0
    audit["labeled_target_timing_verified"] = int((result.label.notna() &
                                                     result.target_timing_verified).sum()) if len(result) else 0
    audit["historical_warning"] = ("Result content is a current registry version, not verified content at first posting; "
                                   "posting dates and the 200-day sponsor proxy do not prove sponsor knowledge.")
    return result, audit


def evaluate(rows: pd.DataFrame, links: pd.DataFrame) -> dict:
    """Paired, fixed-model development assessment; never read sealed labels."""
    if rows.empty:
        return {"status": "not_estimable", "reason": "no Phase 2 targets"}
    frame = rows.copy()
    checkpoint = _exact_day(frame.checkpoint)
    if checkpoint.ge(HOLDOUT).any():
        raise ValueError("Sealed holdout target entered development rows")
    frame["label_available"] = _exact_day(frame.label_available)
    frame = frame.loc[frame.label.notna() & frame.label_available.notna() &
                      frame.target_timing_verified.eq(True)].copy()
    checkpoint = _exact_day(frame.checkpoint)
    frame = frame.loc[checkpoint.lt(VALIDATION_END) &
                      frame.label_available.lt(TRAIN_END).where(checkpoint.lt(TRAIN_END),
                                                               frame.label_available.lt(HOLDOUT))].copy()
    # Same target NCTs and same split in both arms. Drop ambiguous drug-group
    # identities rather than leak group membership across partitions.
    group = links.groupby("nct_id").drug_group.agg(lambda s: tuple(sorted(set(s))))
    frame["groups"] = frame.nct_id.map(group)
    frame = frame.loc[frame.groups.map(lambda g: isinstance(g, tuple) and len(g) == 1)].copy()
    frame["drug_group"] = frame.groups.map(lambda g: g[0])
    frame["launch_year"] = _exact_day(frame.checkpoint).dt.year.astype(float)
    train = frame.loc[_exact_day(frame.checkpoint).lt(TRAIN_END)].copy()
    val = frame.loc[_exact_day(frame.checkpoint).ge(TRAIN_END) &
                    _exact_day(frame.checkpoint).lt(VALIDATION_END)].copy()
    val = val.loc[~val.drug_group.isin(set(train.drug_group))].copy()
    counts = {"train": len(train), "train_positive": int(train.label.eq(1).sum()),
              "validation": len(val), "validation_positive": int(val.label.eq(1).sum()),
              "public_with_prior_validation": int(val.public_prior_result_count.gt(0).sum()),
              "proxy_extra_validation": int((val.proxy_prior_result_count > val.public_prior_result_count).sum())}
    if (len(train) < 100 or len(val) < 30 or train.label.nunique() < 2 or val.label.nunique() < 2):
        return {"status": "not_estimable", "counts": counts,
                "reason": "development row/class support gate (100 train, 30 validation, two classes) failed"}
    if counts["proxy_extra_validation"] == 0:
        return {"status": "not_estimable", "counts": counts,
                "reason": "no validation target gains Phase 1 evidence under the 200-day proxy; paired evidence effect cannot be estimated"}
    y_train, y_val = train.label.astype(int), val.label.astype(int)
    baseline = np.full(len(val), float(y_train.mean()))
    def metrics(p: np.ndarray) -> dict:
        return {"roc_auc": float(roc_auc_score(y_val, p)),
                "average_precision": float(average_precision_score(y_val, p)),
                "brier": float(brier_score_loss(y_val, p))}
    result = {"status": "retrospective_development_only", "counts": counts,
              "baseline": metrics(baseline), "arms": {}}
    for arm in ("public", "proxy"):
        cols = ["launch_year"] + [f"{arm}_{name}" for name in FEATURES[1:]]
        model = RandomForestClassifier(n_estimators=200, min_samples_leaf=5,
                                       random_state=545, n_jobs=1)
        model.fit(train[cols], y_train)
        result["arms"][arm] = metrics(model.predict_proba(val[cols])[:, 1])
    return result


def load_development_sources(inputs: dict[str, Path]) -> dict[str, pd.DataFrame]:
    """Column- and predicate-prune outcome inputs before their materialization."""
    # Predicate- and column-prune at the Parquet boundary. Never materialize
    # 2024+ target labels or result-bearing Phase 1 rows in Python. Both
    # start and first-public dates must predate the sealed holdout.
    frames = {}
    frames["b5"] = pd.read_parquet(
        inputs["b5"], columns=TARGET_COLUMNS,
        filters=[("phase_stratum", "=", "PHASE2"),
                 ("start_date", "<", HOLDOUT), ("first_post_date", "<", HOLDOUT)])
    cutoff = "2024-01-01"
    phase1 = pd.read_parquet(
        inputs["trials"], columns=SOURCE_COLUMNS,
        filters=[("phase", "=", "PHASE1"), ("first_post_date", "<", cutoff),
                 ("results_first_post_date", "<", cutoff),
                 ("last_update_post_date", "<", cutoff)])
    # Only target trials whose own primary-completion and result dates are
    # pre-holdout are eligible for strict timing verification. Others remain
    # in the descriptive B5 target base with timing unverified.
    phase2 = pd.read_parquet(
        inputs["trials"], columns=SOURCE_COLUMNS,
        filters=[("phase", "=", "PHASE2"), ("start_date", "<", cutoff),
                 ("first_post_date", "<", cutoff),
                 ("primary_completion_date", "<", cutoff),
                 ("results_first_post_date", "<", cutoff)])
    frames["trials"] = pd.concat([phase1, phase2], ignore_index=True)
    frames["links"] = pd.read_parquet(inputs["links"], columns=["nct_id", "program_id", "drug_group"])
    candidate_ids = sorted(set(phase1.nct_id) & set(frames["links"].nct_id))
    if candidate_ids:
        frames["analyses"] = pd.read_parquet(
            inputs["analyses"], columns=["nct_id", "outcome_type", "p_significant_005"],
            filters=[("nct_id", "in", candidate_ids), ("outcome_type", "=", "PRIMARY")])
    else:
        frames["analyses"] = pd.DataFrame(columns=["nct_id", "outcome_type", "p_significant_005"])
    return frames


def run(b5: Path, structured: Path, out: Path) -> dict:
    if out.exists():
        raise ValueError("Refusing to overwrite an output directory")
    inputs = {"b5": b5 / "aact_development_rows.parquet", "trials": structured / "trials.parquet",
              "links": structured / "program_trials.parquet", "analyses": structured / "analyses.parquet"}
    for path in inputs.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    frames = load_development_sources(inputs)
    rows, audit = build_rows(frames["b5"], frames["trials"], frames["links"], frames["analyses"])
    evaluation = evaluate(rows, frames["links"])
    out.mkdir(parents=True)
    rows.to_parquet(out / "phase2_target_rows.parquet", index=False)
    report = {"status": "development_only", "source_inputs_sha256": {k: sha256(p) for k, p in inputs.items()},
              "audit": audit, "evaluation": evaluation,
              "feature_whitelist": {"baseline": ["launch_year"],
                                    "public": ["launch_year"] + [f"public_{n}" for n in FEATURES[1:]],
                                    "proxy": ["launch_year"] + [f"proxy_{n}" for n in FEATURES[1:]]},
              "label": "B5 qualifier-aware reported primary p<0.05; missing remains unknown",
              "split": "checkpoint <2016 train with label by 2016; 2016-2019 validation with label by 2024; 2024+ sealed",
              "sponsor_assumption": "Only ACTUAL Phase1 primary completion by checkpoint; result first posted within inclusive 200 days; not verified internal access"}
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (out / "manifest.json").write_text(json.dumps({"inputs_sha256": report["source_inputs_sha256"],
                                                     "outputs_sha256": {name: sha256(out / name) for name in
                                                                         ("phase2_target_rows.parquet", "report.json")},
                                                     "code_sha256": sha256(Path(__file__))}, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b5", type=Path, required=True)
    parser.add_argument("--structured", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.b5, args.structured, args.out)
    print(json.dumps({"audit": report["audit"], "evaluation": report["evaluation"]}, indent=2))


if __name__ == "__main__":
    main()
