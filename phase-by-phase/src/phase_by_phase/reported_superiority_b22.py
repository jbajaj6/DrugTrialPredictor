"""B22: development-only audit of reported primary superiority p<0.05.

This proxy is about a reported statistical test, not clinical benefit, drug
efficacy, completion, or regulatory approval. No model is fitted here.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from .audit_b19 import guard_dates, parse_p


ROOT = Path(__file__).resolve().parents[2]
B15 = ROOT / "data/processed/anamnesis_rolling_b15_full_v1_2026-11-25"
B19 = ROOT / "data/processed/b19_full_2026-11-27_v1"
B17 = ROOT / "data/processed/anamnesis_grade_b17_full_v3_2026-11-25"
B15_MANIFEST = "11aa4e90dc5c4a0abc4cf469078c82078cf1c3b69520b6371061f5ff40fe1ca2"
B19_MANIFEST = "44303770c8b9db387bb008d215f44bd1a70ef1025d611fe5a5ae01cbf5a37107"
B17_MANIFEST = "778d4a5f97d4afa868747d8d44269ff3bde203faeb08b5b0442d84d872a0cdd2"
CUTOFF = pd.Timestamp("2024-01-01")
KEY = ["nct_id", "nct_version", "outcome_ord", "analysis_ord"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def p_threshold(raw: str | None) -> tuple[int | None, str, str | None, float | None]:
    """Compare the entire reported p interval to the strict threshold."""
    parsed = parse_p(raw)
    status, op, value = parsed["status"], parsed["qualifier"], parsed["value"]
    if status != "parsed" or value is None or not math.isfinite(value):
        return None, "p_" + status, op, value
    if op == "=":
        return int(value < .05), "p_determinate", op, value
    if op == "<" and value <= .05 or op == "<=" and value < .05:
        return 1, "p_determinate", op, value
    if op in (">", ">=") and value >= .05:
        return 0, "p_determinate", op, value
    return None, "p_interval_crosses_threshold", op, value


def decide(trial: dict | None, primary: list[dict], checkpoint_date) -> dict:
    """Assign one target label, or an explicit unknown reason, in fixed order."""
    result = {"proxy_label": None, "reason_code": "no_posted_primary_result",
              "nct_version": None, "outcome_ord": None, "analysis_ord": None,
              "result_date": None, "p_value_raw": None, "p_qualifier": None,
              "p_numeric": None, "analysis_group_ids": None,
              "arm_mapping_state": None, "comparator_role_state": None,
              "analysis_type_enum": None, "tested_flag_state": None,
              "overlapping_uncertainty_states": []}
    if trial is None:
        return result
    result["nct_version"] = trial["nct_version"]
    result["result_date"] = pd.Timestamp(trial["result_date"])
    if pd.isna(result["result_date"]) or result["result_date"] >= CUTOFF or result["result_date"] <= pd.Timestamp(checkpoint_date):
        result["reason_code"] = "invalid_result_chronology"
        return result
    if trial["primary_outcome_count"] != 1 or trial["primary_source_row_count"] != 1 or trial["primary_count_state"] != "single" or len(primary) != 1:
        result["reason_code"] = "primary_missing_or_multiple"
        return result
    item = primary[0]
    result["outcome_ord"] = item["outcome_ord"]
    result["arm_mapping_state"] = item["arm_mapping_state"]
    result["comparator_role_state"] = item["comparator_role_state"]
    if item["endpoint_key_state"] != "unique" or item["missing_primary_key_rows"] != 0:
        result["reason_code"] = "ambiguous_primary_key"
        return result
    if item["analysis_count"] != 1 or len(item["analysis_evidence"]) != 1:
        result["reason_code"] = "analysis_missing_or_multiple"
        return result
    analysis = item["analysis_evidence"][0]
    result["analysis_ord"] = analysis["analysis_ord"]
    result["analysis_group_ids"] = list(analysis["group_ids"])
    result["p_value_raw"] = analysis["p_value_raw"]
    kind = analysis["analysis_type"]
    result["analysis_type_enum"] = kind["enum_state"]
    result["tested_flag_state"] = kind["tested_flag_state"]
    uncertainties = []
    if kind["enum_state"] != "superiority":
        uncertainties.append("not_explicit_superiority")
    if kind["tested_flag_state"] in ("true", "invalid") or kind["field_consistency"].startswith(("conflict", "review")):
        uncertainties.append("noninferiority_equivalence_or_flag_conflict")
    if item["arm_mapping_state"] != "exact_label_candidate_bijection":
        uncertainties.append("arm_mapping_unverified")
    if item["comparator_role_state"] != "explicit_two_group_roles":
        uncertainties.append("comparator_role_unverified")
    if analysis["contrast_state"] != "explicit_two_group_role_contrast" or len(analysis["group_ids"]) != 2 or len(set(analysis["group_ids"])) != 2:
        uncertainties.append("analysis_contrast_unverified")
    label, p_reason, qualifier, number = p_threshold(analysis["p_value_raw"])
    result.update(p_qualifier=qualifier,p_numeric=number)
    if p_reason != "p_determinate":
        uncertainties.append(p_reason)
    result["overlapping_uncertainty_states"] = uncertainties
    result["reason_code"] = uncertainties[0] if uncertainties else "determinate_reported_superiority_p"
    result["proxy_label"] = label if not uncertainties else None
    return result


def _check_manifest(directory: Path, expected: str) -> dict:
    if digest(directory / "manifest.json") != expected:
        raise ValueError(f"Pinned manifest mismatch: {directory}")
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, sha in manifest["output_sha256"].items():
        if digest(directory / name) != sha:
            raise ValueError(f"Pinned output mismatch: {directory / name}")
    return manifest


def validate_selected_keys(trial_keys: pd.DataFrame, primary_keys: pd.DataFrame,
                           target_ids: set[str]) -> None:
    if trial_keys.nct_id.duplicated().any() or trial_keys[["nct_id","nct_version"]].isna().any().any():
        raise ValueError("Duplicate/missing B19 result version key")
    if primary_keys[KEY[:-1]].isna().any().any() or primary_keys.duplicated(KEY[:-1]).any():
        raise ValueError("Duplicate/missing B19 primary key")
    if not set(trial_keys.nct_id).issubset(target_ids) or not set(primary_keys.nct_id).issubset(set(trial_keys.nct_id)):
        raise ValueError("Orphan B19 target key")
    joined=primary_keys.merge(trial_keys,on=["nct_id","nct_version"],suffixes=("_primary","_trial"),validate="many_to_one")
    if len(joined)!=len(primary_keys) or joined.result_date_primary.ne(joined.result_date_trial).any():
        raise ValueError("B19 primary/selected-version date mismatch")
    if (trial_keys.result_date.isna().any() or trial_keys.result_date.ge(CUTOFF).any()
            or primary_keys.result_date.isna().any() or primary_keys.result_date.ge(CUTOFF).any()):
        raise ValueError("Holdout result date detected")


def review_sample(labels: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Fixed per-reason sample independent of input row order."""
    ordered=labels.assign(_h=labels.nct_id.map(lambda x: hashlib.sha256(f"{seed}|{x}".encode()).hexdigest()))
    review=pd.concat([block.sort_values(["_h","nct_id"]).head(3) for _,block in ordered.groupby("reason_code",sort=True)],ignore_index=True)
    return review.drop(columns="_h").sort_values(["reason_code","nct_id"]).reset_index(drop=True)


def materialize_labels(records: list[dict]) -> pd.DataFrame:
    """Retain exact nullable integer keys; float inference can corrupt ordinals."""
    result=pd.DataFrame.from_records(records)
    for column in ("nct_version","outcome_ord","analysis_ord"):
        result[column]=pd.array([row[column] for row in records],dtype="Int64")
    return result


def materialize_pair_evidence(records: list[dict]) -> pd.DataFrame:
    """Keep selected analysis and candidate-arm ordinals exact in evidence."""
    columns=KEY+["group_id","group_title","group_source_file",
        "analysis_group_source_file","arm_ord","arm_label","arm_type","arm_source_file"]
    result=pd.DataFrame.from_records(records,columns=columns)
    for column in ("nct_version","outcome_ord","analysis_ord","arm_ord"):
        result[column]=pd.array([row[column] for row in records],dtype="Int64")
    return result


def _read_inputs() -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame,dict]:
    b15 = _check_manifest(B15,B15_MANIFEST)
    b19 = _check_manifest(B19,B19_MANIFEST)
    b17 = _check_manifest(B17,B17_MANIFEST)
    if b19["provenance"]["b17_manifest_sha256"] != B17_MANIFEST:
        raise ValueError("B19/B17 provenance mismatch")
    if b19["provenance"]["upstream_manifest_provenance"][str(B15 / "manifest.json")]["sha256"] != B15_MANIFEST:
        raise ValueError("B19/B15 provenance mismatch")
    # Revalidate every preserved child table's public date against the
    # selected exact version before opening result values.
    guard_dates(B17)
    target_path = B15 / "development_rows.parquet"
    targets = pd.read_parquet(target_path, columns=["nct_id","pure_phase","first_public_date","first_public_nct_version"])
    targets = targets[targets.pure_phase.eq("PHASE3")].copy()
    if len(targets) != 19576 or targets.nct_id.isna().any() or targets.nct_id.duplicated().any():
        raise ValueError("B15 Phase 3 denominator mismatch")
    targets["first_public_date"] = pd.to_datetime(targets.first_public_date)
    if targets.first_public_date.isna().any() or targets.first_public_date.ge(pd.Timestamp("2020-01-01")).any():
        raise ValueError("Invalid B15 target checkpoint")
    # Inspect projected keys/dates before opening any result-value columns.
    trial_keys = pd.read_parquet(B19 / "trial_evidence.parquet",columns=["nct_id","nct_version","result_date"])
    primary_keys = pd.read_parquet(B19 / "primary_evidence.parquet",columns=["nct_id","nct_version","outcome_ord","result_date"])
    validate_selected_keys(trial_keys,primary_keys,set(targets.nct_id))
    # Exact child analysis keys are checked against B19 nested evidence.
    analyses_keys = pd.read_parquet(B17 / "results_outcome_analyses_clean.parquet",columns=KEY+["adapter_version_public_date"])
    if analyses_keys[KEY].isna().any().any() or analyses_keys.duplicated(KEY).any() or analyses_keys.adapter_version_public_date.ge(CUTOFF).any():
        raise ValueError("Duplicate/missing/holdout exact analysis key")
    trials = pd.read_parquet(B19 / "trial_evidence.parquet")
    primaries = pd.read_parquet(B19 / "primary_evidence.parquet")
    analysis_key_set = set(analyses_keys[KEY].itertuples(index=False,name=None))
    for row in primaries.itertuples(index=False):
        for analysis in row.analysis_evidence:
            if (row.nct_id,row.nct_version,row.outcome_ord,analysis["analysis_ord"]) not in analysis_key_set:
                raise ValueError("Orphan nested analysis key")
    return targets,trials,primaries,analyses_keys,{"b15_manifest":B15_MANIFEST,"b19_manifest":B19_MANIFEST,"b17_manifest":B17_MANIFEST,
                                                "b15_rows":digest(target_path),"b19_trial":digest(B19/"trial_evidence.parquet"),
                                                "b19_primary":digest(B19/"primary_evidence.parquet"),
                                                "b17_analysis":digest(B17/"results_outcome_analyses_clean.parquet")}


def run(out: Path, limit_targets: int | None = None, seed: int = 20261127) -> dict:
    if out.exists():
        raise FileExistsError(f"Refusing overwrite: {out}")
    if limit_targets is not None and limit_targets < 1:
        raise ValueError("limit_targets must be positive")
    targets,trials,primaries,analysis_keys,input_hashes = _read_inputs()
    if limit_targets:
        targets = targets.sort_values("nct_id").head(limit_targets)
    trial_by_id = {row["nct_id"]:row for row in trials.to_dict("records")}
    primary_by_id = {key:block.to_dict("records") for key,block in primaries.groupby("nct_id")}
    records=[]
    for row in targets.sort_values("nct_id").itertuples(index=False):
        decision=decide(trial_by_id.get(row.nct_id),primary_by_id.get(row.nct_id,[]),row.first_public_date)
        records.append({"nct_id":row.nct_id,"target_checkpoint":row.first_public_date,
                        "target_first_public_version":row.first_public_nct_version,**decision})
    labels=materialize_labels(records)
    if labels.nct_id.duplicated().any() or len(labels)!=len(targets):
        raise ValueError("Target rows multiplied or lost")
    # Attach raw analysis provenance only for exact selected keys, never a
    # many-to-many join and never as a predictor feature.
    raw = pd.read_parquet(B17 / "results_outcome_analyses_clean.parquet")
    raw = raw.merge(labels[["nct_id","nct_version","outcome_ord","analysis_ord"]].dropna(),on=KEY,how="inner",validate="one_to_one")
    if len(raw)!=int(labels.analysis_ord.notna().sum()):
        raise ValueError("Exact source analysis row is missing or multiplied")
    keys_to_check=labels.loc[labels.proxy_label.notna(),KEY]
    if not set(keys_to_check.itertuples(index=False,name=None)).issubset(set(raw[KEY].itertuples(index=False,name=None))):
        raise ValueError("Determinate proxy has no raw analysis provenance")
    # Public dates are source dates, not parsed submission/anticipated dates.
    if raw.adapter_version_public_date.isna().any() or raw.adapter_version_public_date.ge(CUTOFF).any():
        raise ValueError("Invalid raw analysis public date")
    raw = raw.merge(labels[KEY[:2]+["result_date","p_value_raw"]].dropna(subset=KEY[:2]).drop_duplicates(KEY[:2]),
                    on=KEY[:2],how="left",validate="many_to_one",suffixes=("","_selected"))
    if raw.adapter_version_public_date.ne(raw.result_date).any() or raw.p_value.fillna("").ne(raw.p_value_raw.fillna("")).any():
        raise ValueError("Raw analysis public date/p differs from selected B19 evidence")
    comment_keys = set(raw.loc[raw.non_inferiority_comment.fillna("").astype(str).str.strip().ne(""),KEY]
                       .itertuples(index=False,name=None))
    if comment_keys:
        affected = labels[KEY].apply(tuple,axis=1).isin(comment_keys)
        labels.loc[affected,"proxy_label"] = None
        labels.loc[affected,"reason_code"] = "noninferiority_comment_requires_review"
    source_columns = raw[KEY+["adapter_source_file","adapter_source_commit","adapter_source_table","adapter_version_public_date"]]
    labels = labels.merge(source_columns,on=KEY,how="left",validate="one_to_one")
    analysis_group_path = B17 / "results_outcome_analysis_groups_clean.parquet"
    raw_groups = pd.read_parquet(analysis_group_path,columns=KEY+["group_id","adapter_source_file"])
    if raw_groups[KEY+["group_id"]].isna().any().any() or raw_groups.duplicated(KEY+["group_id"]).any():
        raise ValueError("Invalid exact analysis-group keys")
    group_by_key = {key:sorted(block.group_id.tolist()) for key,block in raw_groups.groupby(KEY)}
    for row in labels.loc[labels.analysis_ord.notna(),KEY+["analysis_group_ids"]].itertuples(index=False):
        key = tuple(row[:4])
        if sorted(row.analysis_group_ids) != group_by_key.get(key,[]):
            raise ValueError("B19 contrast group IDs differ from preserved B17 exact keys")
    # Two rows per determinate analysis: exact result-group and candidate arm
    # ordinals with original source file provenance. These are label evidence,
    # not drug/clinical identity claims or predictor columns.
    known=labels[labels.proxy_label.notna()]
    group_source=pd.read_parquet(B17/"results_outcome_groups_clean.parquet")
    arm_source=pd.read_parquet(B17/"arms_at_result_version.parquet")
    group_lookup={key:block for key,block in group_source.groupby(KEY[:3])}
    arm_lookup={key:block for key,block in arm_source.groupby(KEY[:2])}
    link_lookup={key:block for key,block in raw_groups.groupby(KEY)}
    pair_records=[]
    for label in known.to_dict("records"):
        key=tuple(label[c] for c in KEY)
        outcome_groups=group_lookup.get(key[:3])
        arms=arm_lookup.get(key[:2])
        links=link_lookup.get(key)
        if outcome_groups is None or arms is None or links is None or len(links)!=2:
            raise ValueError("Determinate proxy missing exact arm/group/link provenance")
        if len(arms)!=2 or len(outcome_groups)!=2:
            raise ValueError("Determinate proxy lacks unique two-arm/group mapping")
        by_label={str(a.arm_label).strip().casefold():a for a in arms.itertuples(index=False)}
        if len(by_label)!=2:
            raise ValueError("Duplicate candidate arm labels")
        for link in links.itertuples(index=False):
            group=outcome_groups.loc[outcome_groups.group_id.eq(link.group_id)]
            if len(group)!=1:
                raise ValueError("Ambiguous exact result group")
            g=group.iloc[0]
            arm=by_label.get(str(g.title).strip().casefold())
            if arm is None:
                raise ValueError("Candidate group/arm bijection failed")
            pair_records.append({**{c:label[c] for c in KEY},"group_id":link.group_id,
                                 "group_title":g.title,"group_source_file":g.adapter_source_file,
                                 "analysis_group_source_file":link.adapter_source_file,
                                 "arm_ord":arm.ord,"arm_label":arm.arm_label,"arm_type":arm.arm_type,
                                 "arm_source_file":arm.adapter_source_file})
    pair_evidence=materialize_pair_evidence(pair_records)
    if len(pair_evidence)!=2*len(known) or pair_evidence.duplicated(KEY+["group_id"]).any():
        raise ValueError("Determinate group/arm evidence multiplied or lost")
    review=review_sample(labels,seed)
    out.mkdir(parents=True)
    labels.to_parquet(out/"all_target_labels.parquet",index=False)
    raw.to_parquet(out/"exact_analysis_evidence.parquet",index=False)
    pair_evidence.to_parquet(out/"determinate_group_arm_evidence.parquet",index=False)
    review.to_csv(out/"review_sheet.csv",index=False)
    rolling={}
    for year in range(2016,2020):
        boundary=pd.Timestamp(f"{year}-01-01")
        next_boundary=pd.Timestamp(f"{year+1}-01-01")
        train=labels.loc[labels.proxy_label.notna() & labels.target_checkpoint.lt(boundary)
                         & labels.result_date.lt(boundary)]
        validation=labels.loc[labels.target_checkpoint.ge(boundary)
                              & labels.target_checkpoint.lt(next_boundary)
                              & labels.proxy_label.notna()]
        rolling[str(year)]={"training_known":len(train),"training_positive":int(train.proxy_label.eq(1).sum()),
                            "training_negative":int(train.proxy_label.eq(0).sum()),
                            "validation_known_by_2024":len(validation),
                            "validation_positive":int(validation.proxy_label.eq(1).sum()),
                            "validation_negative":int(validation.proxy_label.eq(0).sum())}
    report={"scope":"development-only reported primary superiority p<0.05 proxy; not clinical efficacy",
            "targets":len(labels),"known":int(labels.proxy_label.notna().sum()),
            "positive":int(labels.proxy_label.eq(1).sum()),"negative":int(labels.proxy_label.eq(0).sum()),
            "known_public_before_2016":int((labels.proxy_label.notna() & labels.result_date.lt(pd.Timestamp("2016-01-01"))).sum()),
            "known_public_2016_through_2023":int((labels.proxy_label.notna() & labels.result_date.ge(pd.Timestamp("2016-01-01"))).sum()),
            "rolling_cutoff_support_descriptive_only":rolling,
            "reason_counts":dict(Counter(labels.reason_code)),
            "overlapping_uncertainty_counts":dict(Counter(x for states in labels.overlapping_uncertainty_states for x in states)),
            "review_rows":len(review),"model":"not trained", "holdout":"2024+ result values not opened"}
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    manifest={"input_sha256":input_hashes,"code_sha256":digest(Path(__file__)),
              "settings":{"limit_targets":limit_targets,"seed":seed},
              "output_sha256":{p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()}}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    return report


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--limit-targets",type=int)
    parser.add_argument("--seed",type=int,default=20261127)
    args=parser.parse_args()
    print(json.dumps(run(args.out,args.limit_targets,args.seed),indent=2))


if __name__=="__main__":
    main()
