"""Auditable retrospective landmarks, temporal holdouts, and exploratory models.

The endpoint is *observed registration of a separate Phase 3 trial starting
within a fixed horizon*. It is not clinical success, eventual progression,
approval, or proof that a program without a matching trial was discontinued.
Current registry metadata are not historical record versions; fitted models
are therefore explicitly exploratory, even when dated evidence is filtered.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


SEED = 545
PHASE1 = {"EARLY_PHASE1", "PHASE1"}
PHASE2 = {"PHASE2"}
PHASE3 = {"PHASE3"}  # Combined Phase2/3 start does not date its Phase3 component.
BASE_NUMERIC = ["n_regimen_components", "elapsed_days"]
BASE_CATEGORICAL = ["indication_id", "index_phase", "sponsor_class", "allocation", "masking"]
PHASE1_FEATURES = ["phase1_started_count", "phase1_results_count"]
PHASE2_FEATURES = PHASE1_FEATURES + ["phase2_started_count", "phase2_results_count"]
SNAPSHOT_COLUMNS = [
    "program_id", "regimen_id", "indication_id", "checkpoint", "landmark_date",
    "horizon_end", "event_date", "event_first_public_date", "outcome_available_date",
    "label", "label_status", "index_nct_id", "index_start_date", "index_phase",
    "elapsed_days", "n_regimen_components", "sponsor_class", "allocation", "masking",
    "phase1_started_count", "phase1_results_count", "phase2_started_count",
    "phase2_results_count", "max_feature_available_date", "historical_versions_available",
    "drug_group",
]


def exact_date(value: object) -> pd.Timestamp:
    """Never invent a day for a month-only/year-only registry date."""
    if value is None or pd.isna(value):
        return pd.NaT
    text = str(value)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return pd.NaT
    return pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")


def _exact_dates(values: pd.Series) -> pd.Series:
    """Vectorized equivalent of ``exact_date`` for registry-sized tables."""
    text = values.astype("string")
    return pd.to_datetime(text.where(text.str.fullmatch(r"\d{4}-\d{2}-\d{2}", na=False)),
                          format="%Y-%m-%d", errors="coerce")


def _earliest_possible_dates(values: pd.Series) -> pd.Series:
    """Vectorized exclusion-only partial-date bounds (never model features)."""
    text = values.astype("string")
    text = text.where(~text.str.fullmatch(r"\d{4}", na=False), text + "-01-01")
    text = text.where(~text.str.fullmatch(r"\d{4}-\d{2}", na=False), text + "-01")
    return _exact_dates(text)


def _earliest_possible_date(value: object) -> pd.Timestamp:
    """Lower bound used ONLY to exclude ambiguous chronology, never as a date.

    A month-only/year-only record can predate a later precise record. Ignoring
    it would falsely make that later record the beginning of the program.
    """
    if value is None or pd.isna(value):
        return pd.NaT
    text = str(value)
    if re.fullmatch(r"\d{4}", text):
        text += "-01-01"
    elif re.fullmatch(r"\d{4}-\d{2}", text):
        text += "-01"
    return exact_date(text)


def _date_text(value: object) -> str | None:
    return None if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def _text(value: object, default: str = "unknown") -> str:
    return default if value is None or pd.isna(value) else str(value)


def _components(row: pd.Series) -> list[str]:
    try:
        parsed = json.loads(row.get("component_keys_json", "[]"))
    except (ValueError, TypeError):
        parsed = []
    # No unsafe splitting of dose-bearing/combination labels here.
    return sorted(set(str(value) for value in parsed)) or [str(row["regimen_id"])]


def _wilson(positive: int, total: int) -> dict | None:
    """Descriptive binomial interval, not a correction for linkage/selection."""
    if total == 0:
        return None
    fraction, z = positive / total, 1.959963984540054
    denominator = 1 + z * z / total
    center = (fraction + z * z / (2 * total)) / denominator
    radius = z * np.sqrt(fraction * (1 - fraction) / total + z * z / (4 * total * total)) / denominator
    return {"fraction": fraction, "low": float(center - radius), "high": float(center + radius),
            "method": "descriptive Wilson 95%; assumes independent programs, does not account for related drugs, selection or linkage error"}


def leakage_groups(bridge: pd.DataFrame) -> dict[str, str]:
    """Union programs sharing an exact drug component OR any source trial.

    This cannot identify unresolved molecular aliases, which remains a stated
    limitation. Connecting by NCT also prevents different experimental arms of
    one trial from entering different partitions.
    """
    parent = {str(p): str(p) for p in bridge["program_id"].dropna().unique()}

    def root(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        a, b = root(left), root(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    owner: dict[tuple[str, str], str] = {}
    for _, row in bridge.sort_values(["program_id", "nct_id"]).iterrows():
        program = str(row["program_id"])
        keys = [("trial", str(row["nct_id"]))]
        keys += [("drug", component) for component in _components(row)]
        for key in keys:
            if key in owner:
                union(program, owner[key])
            else:
                owner[key] = program
    return {program: root(program) for program in parent}


def create_snapshots(
    tables: dict[str, pd.DataFrame], cutoff: str, horizon_years: int = 5,
) -> tuple[pd.DataFrame, dict]:
    """Build baseline/post-results landmarks with explicit exclusions/censoring."""
    end = exact_date(cutoff)
    if pd.isna(end) or horizon_years < 1:
        raise ValueError("cutoff must be YYYY-MM-DD and horizon_years must be positive")
    trials = tables["trials"].copy()
    bridge = tables["program_trials"].copy()
    if trials["nct_id"].duplicated().any():
        raise ValueError("trials must have one row per nct_id")
    absent = set(bridge["nct_id"]) - set(trials["nct_id"])
    if absent:
        raise ValueError("program_trials contains NCT IDs absent from trials")
    groups = leakage_groups(bridge)
    for column in ["start_date", "first_post_date", "results_first_post_date"]:
        trials[f"_{column}"] = _exact_dates(trials.get(column, pd.Series(index=trials.index, dtype=object)))
    trials["_actual_start"] = trials["_start_date"].where(
        trials.get("start_date_type", pd.Series("", index=trials.index)).fillna("").str.upper().eq("ACTUAL")
    )
    # Keep the trials' phase/metadata, identities exclusively from the bridge.
    identity = bridge[[c for c in ["nct_id", "program_id", "regimen_id", "indication_id", "component_keys_json"] if c in bridge]].drop_duplicates(["nct_id", "program_id"])
    joined = identity.merge(trials, on="nct_id", validate="many_to_one")
    exclusions: Counter = Counter()
    records: list[dict] = []
    # Bulk eligibility is equivalent to the former per-program checks, in the
    # same precedence order. Most programs never reach a landmark; avoid tens
    # of thousands of tiny DataFrame allocations for those rejected histories.
    known_all = joined.loc[joined["_actual_start"].notna() & (joined["_actual_start"] <= end)]
    first = known_all.sort_values(["program_id", "_actual_start", "nct_id"]).drop_duplicates("program_id").set_index("program_id", drop=False)
    no_actual = joined.program_id.nunique() - len(first)
    if no_actual:
        exclusions["program_no_full_actual_start"] = no_actual

    def exclude(ids, reason):
        nonlocal first
        selected = first.index.intersection(ids)
        if len(selected):
            exclusions[reason] = len(selected)
            first = first.drop(index=selected)

    unresolved = joined.loc[joined["_actual_start"].isna()]
    lower = _earliest_possible_dates(unresolved["start_date"])
    initial_start = unresolved.program_id.map(first["_actual_start"])
    conflict = initial_start.notna() & (lower.isna() | (lower <= initial_start))
    exclude(unresolved.loc[conflict, "program_id"].unique(), "program_unresolved_initial_chronology")
    exclude(first.loc[~first.phase.isin(PHASE1)].index, "program_first_observed_phase_not_pure_phase1")
    tied = known_all.loc[(known_all["_actual_start"] == known_all.program_id.map(first["_actual_start"])) & ~known_all.phase.isin(PHASE1)]
    exclude(tied.program_id.unique(), "program_tied_initial_phase_order")
    exclude(first.loc[first["_first_post_date"].isna() | (first["_first_post_date"] > end)].index,
            "program_missing_or_future_index_public_date")
    eligible = joined.loc[joined.program_id.isin(first.index)]
    for program_id, history in eligible.groupby("program_id", sort=True):
        known = history.loc[history["_actual_start"].notna() & (history["_actual_start"] <= end)].sort_values(["_actual_start", "nct_id"])
        index = first.loc[program_id]
        baseline_date = max(index["_actual_start"], index["_first_post_date"])
        phase3 = history.loc[history["phase"].isin(PHASE3)]
        phase3_actual = phase3.loc[phase3["_actual_start"].notna() & (phase3["_actual_start"] <= end)]
        # A recorded Phase3 study with unusable actual chronology cannot safely
        # establish a negative fixed-horizon label. Planned future starts are
        # not events; actual/unknown-date Phase3 records are indeterminate.
        types = phase3.get("start_date_type", pd.Series("", index=phase3.index)).fillna("").str.upper()
        unresolved_phase3 = phase3.loc[phase3["_actual_start"].isna() & ~types.eq("ESTIMATED")]
        landmarks = [("baseline", baseline_date)]
        for checkpoint, phases in [("post_phase1", PHASE1), ("post_phase2", PHASE2)]:
            results = known.loc[
                known["phase"].isin(phases)
                & known["_results_first_post_date"].notna()
                & known["_first_post_date"].notna()
                & (known["_results_first_post_date"] >= baseline_date)
                & (known["_results_first_post_date"] >= known["_actual_start"])
                & (known["_results_first_post_date"] >= known["_first_post_date"])
                & (known["_results_first_post_date"] <= end)
            ]
            if results.empty:
                exclusions[f"{checkpoint}_no_usable_public_results"] += 1
            else:
                landmarks.append((checkpoint, results["_results_first_post_date"].min()))
        for checkpoint, landmark in landmarks:
            if not phase3_actual.empty and (phase3_actual["_actual_start"] <= landmark).any():
                exclusions[f"{checkpoint}_phase3_already_started"] += 1
                continue
            horizon = landmark + pd.DateOffset(years=horizon_years)
            future = phase3_actual.loc[phase3_actual["_actual_start"] > landmark].sort_values(["_actual_start", "nct_id"])
            event = None if future.empty else future.iloc[0]
            event_date = pd.NaT if event is None else event["_actual_start"]
            event_public = pd.NaT if event is None else event["_first_post_date"]
            label = None
            if horizon > end:
                label_status = "insufficient_followup"
            elif not unresolved_phase3.empty:
                label_status = "indeterminate_phase3_date"
            elif event is not None and (pd.isna(event_public) or event_public > end):
                label_status = "indeterminate_phase3_public_date"
            else:
                label_status = "mature"
                label = int(event is not None and event_date <= horizon)
            # Conservative split embargo: all labels require the complete
            # horizon; late-publicly-posted events require their posting date.
            available = horizon
            if label == 1:
                available = max(horizon, event_public)
            prior = known.loc[
                known["_first_post_date"].notna()
                & (known["_first_post_date"] <= landmark)
                & (known["_actual_start"] <= landmark)
            ]
            row = {
                "program_id": program_id, "regimen_id": index["regimen_id"],
                "indication_id": index["indication_id"], "checkpoint": checkpoint,
                "landmark_date": _date_text(landmark), "horizon_end": _date_text(horizon),
                "event_date": _date_text(event_date), "event_first_public_date": _date_text(event_public),
                "outcome_available_date": _date_text(available), "label": label,
                "label_status": label_status, "index_nct_id": index["nct_id"],
                "index_start_date": _date_text(index["_actual_start"]), "index_phase": index["phase"],
                "elapsed_days": (landmark - index["_actual_start"]).days,
                "n_regimen_components": len(_components(index)),
                "historical_versions_available": False, "drug_group": groups[program_id],
                **{c: _text(index.get(c)) for c in ["sponsor_class", "allocation", "masking"]},
            }
            dated_evidence = [index["_actual_start"], index["_first_post_date"]]
            for prefix, phases in [("phase1", PHASE1), ("phase2", PHASE2)]:
                phase_prior = prior.loc[prior["phase"].isin(phases)]
                posted = phase_prior.loc[
                    phase_prior["_results_first_post_date"].notna()
                    & (phase_prior["_results_first_post_date"] >= phase_prior["_actual_start"])
                    & (phase_prior["_results_first_post_date"] >= phase_prior["_first_post_date"])
                    & (phase_prior["_results_first_post_date"] <= landmark)
                ]
                row[f"{prefix}_started_count"] = phase_prior["nct_id"].nunique()
                row[f"{prefix}_results_count"] = posted["nct_id"].nunique()
                dated_evidence.extend(phase_prior["_first_post_date"].tolist())
                dated_evidence.extend(phase_prior["_actual_start"].tolist())
                dated_evidence.extend(posted["_results_first_post_date"].tolist())
            row["max_feature_available_date"] = _date_text(max(dated_evidence))
            records.append(row)
    snapshots = pd.DataFrame(records, columns=SNAPSHOT_COLUMNS)
    counts = {}
    for checkpoint, group in snapshots.groupby("checkpoint"):
        mature = group[group.label_status.eq("mature")]
        counts[checkpoint] = {
            "snapshots": len(group), "mature": len(mature),
            "observed_phase3_within_horizon": int(mature.label.eq(1).sum()),
            "no_observed_phase3_within_horizon": int(mature.label.eq(0).sum()),
            "label_status_counts": {str(k): int(v) for k, v in group.label_status.value_counts().items()},
            "observed_fraction_interval": _wilson(int(mature.label.eq(1).sum()), len(mature)),
        }
    return snapshots, {"checkpoint_counts": counts, "exclusions": dict(exclusions), "leakage_groups": len(set(groups.values()))}


def temporal_split(frame: pd.DataFrame, horizon_years: int = 5) -> tuple[pd.DataFrame, dict]:
    """Embargo-aware calendar periods, then group and label-availability purges.

    Related programs are assigned to their earliest candidate period; rows in
    later periods are dropped, never moved backwards in time. Entire date ties
    stay together. Training labels must be available before validation starts;
    validation labels before test starts. The final fit uses training only.
    Two full-horizon gaps are reserved first; the remaining calendar span is
    allocated 60/20/20. This is a time allocation, not a row-count proportion.
    """
    data = frame.sort_values(["landmark_date", "program_id"]).copy()
    if len(data) < 5:
        data["split"] = "excluded_too_few_rows"
        return data, {"status": "insufficient_rows"}
    dates = pd.to_datetime(data.landmark_date)
    gap = pd.Timedelta(days=366 * horizon_years)
    available_span = dates.max() - dates.min() + pd.Timedelta(days=1) - 2 * gap
    if available_span <= pd.Timedelta(0):
        data["split"] = "excluded_insufficient_calendar_span"
        return data, {"status": "insufficient_calendar_span_for_two_horizon_embargoes", "counts": {"excluded_insufficient_calendar_span": len(data)}}
    val_boundary = (dates.min() + available_span * 0.6 + gap).ceil("D")
    test_boundary = (val_boundary + available_span * 0.2 + gap).ceil("D")
    data["split"] = np.where(dates < val_boundary, "train", np.where(dates < test_boundary, "validation", "test"))
    order = {"train": 0, "validation": 1, "test": 2}
    earliest = data.groupby("drug_group")["split"].agg(lambda s: min(s, key=order.get))
    overlap = data["split"] != data["drug_group"].map(earliest)
    data.loc[overlap, "split"] = "excluded_related_group"
    available = pd.to_datetime(data.outcome_available_date)
    unavailable = ((data.split.eq("train") & (available >= val_boundary)) |
                   (data.split.eq("validation") & (available >= test_boundary)))
    data.loc[unavailable, "split"] = "excluded_outcome_embargo"
    counts = {str(k): int(v) for k, v in data.split.value_counts().items()}
    return data, {"method": "60/20/20 usable calendar time after reserving two full-horizon embargo gaps; exact drug/NCT group purge",
                  "validation_start": _date_text(val_boundary), "test_start": _date_text(test_boundary), "counts": counts}


def _metrics(y: np.ndarray, p: np.ndarray) -> dict:
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
    p = np.clip(np.asarray(p, dtype=float), 1e-8, 1 - 1e-8)
    both = len(np.unique(y)) == 2
    return {
        "n": len(y), "positives": int(np.sum(y)), "event_rate": float(np.mean(y)),
        "roc_auc": float(roc_auc_score(y, p)) if both else None,
        "average_precision": float(average_precision_score(y, p)) if both else None,
        "brier_score": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "mean_predicted_probability": float(np.mean(p)),
    }


def _calibration(y: np.ndarray, p: np.ndarray) -> list[dict]:
    result = []
    for lower in np.arange(0, 1, 0.1):
        selected = (p >= lower) & (p < lower + 0.1 if lower < 0.89 else p <= 1)
        if selected.any():
            result.append({"lower": round(float(lower), 1), "upper": round(float(lower + 0.1), 1),
                           "n": int(selected.sum()), "mean_prediction": float(p[selected].mean()),
                           "observed_fraction": float(y[selected].mean())})
    return result


def _bootstrap_metrics(y: np.ndarray, predictions: dict[str, np.ndarray], groups: np.ndarray, repeats: int) -> dict:
    """Paired cluster bootstrap on held-out predictions, not training refits."""
    unique = np.unique(groups)
    if repeats < 20 or len(unique) < 10:
        return {"status": "insufficient_bootstrap_replicates_or_test_groups"}
    rng = np.random.default_rng(SEED)
    indices = {group: np.flatnonzero(groups == group) for group in unique}
    samples: dict[str, dict[str, list]] = {name: {m: [] for m in ["roc_auc", "average_precision", "brier_score", "log_loss"]} for name in predictions}
    paired: list[float] = []
    for _ in range(repeats):
        selected = np.concatenate([indices[g] for g in rng.choice(unique, len(unique), replace=True)])
        metrics = {name: _metrics(y[selected], p[selected]) for name, p in predictions.items()}
        for name in predictions:
            for metric in samples[name]:
                if metrics[name][metric] is not None:
                    samples[name][metric].append(metrics[name][metric])
        if "baseline_logistic" in metrics and "updated_logistic" in metrics:
            paired.append(metrics["baseline_logistic"]["brier_score"] - metrics["updated_logistic"]["brier_score"])
    intervals = {name: {metric: {"low": float(np.quantile(vals, 0.025)), "high": float(np.quantile(vals, 0.975)), "valid_replicates": len(vals)}
                        for metric, vals in values.items() if vals} for name, values in samples.items()}
    result = {"method": "paired test-group percentile bootstrap; fixed trained models; no training uncertainty", "repeats": repeats, "intervals_95": intervals}
    if paired:
        low, high = np.quantile(paired, [0.025, 0.975])
        result["paired_brier_improvement_baseline_minus_updated"] = {
            "estimate": float(np.mean((y - predictions["baseline_logistic"]) ** 2) - np.mean((y - predictions["updated_logistic"]) ** 2)),
            "low": float(low), "high": float(high),
            "interpretation": "positive values favor updated model; interval crossing zero is inconclusive",
        }
    return result


def _pipeline(numeric: list[str], algorithm: str):
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    preprocessor = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler())]), numeric),
        ("categorical", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=10), BASE_CATEGORICAL),
    ])
    model = (LogisticRegression(C=1.0, max_iter=2000, random_state=SEED) if algorithm == "logistic" else
             RandomForestClassifier(n_estimators=250, max_depth=6, min_samples_leaf=10, n_jobs=1, random_state=SEED))
    return Pipeline([("preprocess", preprocessor), ("model", model)])


def fit_checkpoint(frame: pd.DataFrame, checkpoint: str, bootstrap: int = 300, horizon_years: int = 5) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Fit prespecified baselines and updates only if held-out support exists."""
    mature = frame.loc[frame.label_status.eq("mature")].copy()
    split, split_report = temporal_split(mature, horizon_years)
    report = {"checkpoint": checkpoint, "split": split_report,
              "support_gate": "engineering minimum, not a formal sample-size/power calculation: train >=100, >=20 each class; validation/test >=30, >=10 each class; >=10 groups each split"}
    partitions = {name: split.loc[split.split.eq(name)] for name in ["train", "validation", "test"]}
    support = {}
    problems = []
    for name, part in partitions.items():
        positives = int(part.label.eq(1).sum())
        negatives = int(part.label.eq(0).sum())
        groups = part.drug_group.nunique()
        support[name] = {"n": len(part), "positive": positives, "negative": negatives, "groups": groups}
        if len(part) < (100 if name == "train" else 30) or min(positives, negatives) < (20 if name == "train" else 10) or groups < 10:
            problems.append(name)
    report["support"] = support
    if problems:
        report.update(status="not_estimable", reason="insufficient independent mature support after chronology/group purges: " + ", ".join(problems))
        return report, pd.DataFrame(), split
    train, validation, test = (partitions[name] for name in ["train", "validation", "test"])
    y_train = train.label.to_numpy(dtype=int)
    y_val = validation.label.to_numpy(dtype=int)
    y_test = test.label.to_numpy(dtype=int)
    prevalence = float(y_train.mean())
    models = {"baseline_logistic": _pipeline(BASE_NUMERIC, "logistic")}
    if checkpoint != "baseline":
        extra = PHASE1_FEATURES if checkpoint == "post_phase1" else PHASE2_FEATURES
        models["updated_logistic"] = _pipeline(BASE_NUMERIC + extra, "logistic")
        models["updated_random_forest"] = _pipeline(BASE_NUMERIC + extra, "forest")
    predictions = {"historical_rate": np.full(len(test), prevalence)}
    validation_scores = {"historical_rate": _metrics(y_val, np.full(len(validation), prevalence))}
    test_scores = {"historical_rate": _metrics(y_test, predictions["historical_rate"])}
    for name, model in models.items():
        model.fit(train, y_train)
        predictions[name] = model.predict_proba(test)[:, 1]
        validation_scores[name] = _metrics(y_val, model.predict_proba(validation)[:, 1])
        test_scores[name] = _metrics(y_test, predictions[name])
        test_scores[name]["calibration_bins"] = _calibration(y_test, predictions[name])
    winner = min(validation_scores, key=lambda name: validation_scores[name]["brier_score"])
    report.update(status="exploratory_fit", validation_metrics=validation_scores, test_metrics=test_scores,
                  selected_on_validation_brier=winner, training_prevalence=prevalence,
                  uncertainty=_bootstrap_metrics(y_test, predictions, test.drug_group.to_numpy(), bootstrap),
                  features={"baseline": BASE_NUMERIC + BASE_CATEGORICAL,
                            "updated_extra": [] if checkpoint == "baseline" else (PHASE1_FEATURES if checkpoint == "post_phase1" else PHASE2_FEATURES)})
    exported = test[["program_id", "regimen_id", "indication_id", "checkpoint", "landmark_date", "horizon_end", "label", "drug_group"]].copy()
    for name, values in predictions.items():
        exported[f"p_{name}"] = values
    return report, exported, split


def _progression(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    bridge = tables["program_trials"][["program_id", "nct_id"]].drop_duplicates()
    trial = tables["trials"]
    joined = bridge.merge(trial[["nct_id", "phase", "start_date", "start_date_type", "first_post_date"]], on="nct_id", validate="many_to_one")
    if joined.empty:
        return pd.DataFrame()
    joined["actual_day"] = _exact_dates(joined.start_date).where(joined.start_date_type.fillna("").str.upper().eq("ACTUAL"))
    result = joined.groupby("program_id", sort=True).nct_id.nunique().to_frame("n_trials")
    phase_dates = {}
    for name, phases in [("phase1", PHASE1), ("phase2", PHASE2), ("phase3", PHASE3)]:
        phase = joined.loc[joined.phase.isin(phases)].groupby("program_id")
        result[f"{name}_trials"] = phase.nct_id.nunique().reindex(result.index, fill_value=0)
        phase_dates[name] = phase.actual_day.min().reindex(result.index)
        result[f"first_actual_{name}_date"] = phase_dates[name].dt.strftime("%Y-%m-%d").where(phase_dates[name].notna(), None)
    combined = joined.phase.isin({"PHASE1/PHASE2", "PHASE2/PHASE3"}).groupby(joined.program_id).sum()
    result["combined_phase_trials"] = combined.reindex(result.index, fill_value=0).astype(int)
    for earlier, later in [("phase1", "phase2"), ("phase2", "phase3"), ("phase1", "phase3")]:
        days = (phase_dates[later] - phase_dates[earlier]).dt.days
        result[f"{earlier}_to_{later}_days"] = days
        result[f"{earlier}_before_{later}"] = days.gt(0)
    return result.reset_index()


def build_analysis(
    tables: dict[str, pd.DataFrame], cutoff: str, output_dir: Path,
    horizon_years: int = 5, bootstrap: int = 300, *, data_complete: bool = False,
) -> dict:
    """Write reproducible data/metrics; never turn unsupported results into claims."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots, cohort = create_snapshots(tables, cutoff, horizon_years)
    snapshots.to_parquet(output_dir / "snapshots.parquet", index=False)
    progression = _progression(tables)
    progression.to_parquet(output_dir / "program_timelines.parquet", index=False)
    report = {
        "schema_version": 1, "cutoff": cutoff, "horizon_years": horizon_years,
        "data_complete": data_complete, "random_seed": SEED,
        "endpoint": f"observed separate pure Phase3 trial ACTUAL start within the strict exact-linked cohort in (landmark, landmark + {horizon_years} years]; out-of-cohort/unlinked trials are not reliable absences",
        "landmarks": {"baseline": "registry-entry landmark: max(first observed pure Phase1 actual start, public first posting); not necessarily before Phase1",
                      "post_phase1": "first valid public results-posting date for a pure Phase1 trial",
                      "post_phase2": "first valid public results-posting date for a pure Phase2 trial"},
        "limitations": [
            "Exact surface-name regimen/indication linkage is provisional; aliases and indication granularity are unresolved.",
            "Absence of an exact-matched registered Phase3 event is not evidence of failure or discontinuation.",
            "Phase3 trials excluded by arm/indication/identity rules or outside the source cohort may be true advancements that cannot be linked; negative labels mean no event observed within the strict cohort only.",
            "First observed Phase1 is not confirmed first-ever development, especially for truncated registry coverage.",
            "Programs with any missing/partial/unknown-type start that could predate the precise index trial are excluded rather than treating a later Phase1 trial as program entry.",
            "Registry records are current versions; historical phase, design, sponsor and identity versions are unavailable. Models are exploratory, not prospective validated.",
            "Only full actual start dates are used; partial dates and ambiguous Phase3 chronology are not silently imputed.",
            "Post-results cohorts exclude programs without posted results and are selected subpopulations.",
            "Updated models add date-available trial/results-posting counts only; efficacy effect sizes, endpoint success and adverse-event content are not parsed biological features.",
            "Combined Phase1/2 cannot establish pure Phase1 entry; combined Phase2/3 start does not establish a separate Phase3 start.",
            "Group bootstrap intervals quantify test-sample uncertainty conditional on fitted models, not individual probability or training uncertainty.",
            "No FDA approval labels, individual probability intervals, coefficient p-values, or causal claims are produced.",
            "Baseline and updated models are paired at the same landmark/riskset; between-checkpoint scores do not measure causal value of new evidence.",
        ],
        "cohort": cohort, "models": {},
        "descriptive": {"programs": len(progression),
                        "programs_with_pure_phase1": int(progression.phase1_trials.gt(0).sum()) if len(progression) else 0,
                        "programs_with_pure_phase2": int(progression.phase2_trials.gt(0).sum()) if len(progression) else 0,
                        "programs_with_pure_phase3": int(progression.phase3_trials.gt(0).sum()) if len(progression) else 0,
                        "phase1_before_phase2": int(progression.phase1_before_phase2.sum()) if len(progression) else 0,
                        "phase2_before_phase3": int(progression.phase2_before_phase3.sum()) if len(progression) else 0,
                        "phase1_before_phase3": int(progression.phase1_before_phase3.sum()) if len(progression) else 0},
    }
    prediction_frames, split_frames = [], []
    for checkpoint in ["baseline", "post_phase1", "post_phase2"]:
        frame = snapshots.loc[snapshots.checkpoint.eq(checkpoint)]
        if not data_complete:
            result = {"status": "not_estimable", "reason": "source extraction is incomplete or completeness was not explicitly verified; missing later trials cannot be negatives"}
        else:
            result, predictions, split = fit_checkpoint(frame, checkpoint, bootstrap, horizon_years)
            if not predictions.empty:
                prediction_frames.append(predictions)
            if not split.empty:
                split_frames.append(split)
        report["models"][checkpoint] = result
    predictions = pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame(columns=["program_id", "checkpoint", "label"])
    splits = pd.concat(split_frames, ignore_index=True) if split_frames else pd.DataFrame(columns=["program_id", "checkpoint", "split"])
    predictions.to_parquet(output_dir / "predictions.parquet", index=False)
    splits.to_parquet(output_dir / "analysis_splits.parquet", index=False)
    (output_dir / "analysis_report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report
