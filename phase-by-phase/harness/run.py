"""Offline phase-specific RF harness. No LLM calls or external downloads.

Run from this folder: python run.py audit|train|evaluate --data PATH --out NEW_DIR
Training requires --retrospective because the current table lacks historical versions.
"""
import argparse
import hashlib
import json
import platform
from pathlib import Path
from datetime import datetime, timezone

from policy import FEATURES, CATEGORICAL, NUMERIC, phase_name, completion_label, significance_label, supported, split_year, validate_features, verify_split_records, assert_fit_partition

ROOT = Path(__file__).resolve().parent

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""): digest.update(chunk)
    return digest.hexdigest()

def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False, default=str)+"\n")

def trace(out, stage, **kwargs):
    with (out / "trace.jsonl").open("a") as f:
        f.write(json.dumps({"at":datetime.now(timezone.utc).isoformat(), "stage":stage, **kwargs}, default=str)+"\n")

def load_data(path):
    import pandas as pd
    df = pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)
    required = ["nct_id", "phase", "overall_status", "label_min_primary_p", "start_date", "first_submitted_date"] + FEATURES
    missing = sorted(set(required)-set(df.columns))
    if missing: raise ValueError(f"Missing required columns; no silent dropping: {missing}")
    if df.nct_id.isna().any() or df.nct_id.duplicated().any():
        raise ValueError("Input must contain exactly one non-null NCT ID per row")
    df = df.copy()
    dates = pd.to_datetime(df.start_date, errors="coerce")
    registered = pd.to_datetime(df.first_submitted_date, errors="coerce")
    if dates.isna().any() or registered.isna().any(): raise ValueError("Missing/invalid cohort dates")
    year = pd.to_numeric(df.start_year, errors="coerce")
    if (year != dates.dt.year).any(): raise ValueError("start_year disagrees with start_date")
    df["start_year"] = year.astype(int)
    for c in NUMERIC:
        old = df[c]
        new = pd.to_numeric(old, errors="coerce")
        if (old.notna() & new.isna()).any(): raise ValueError(f"Non-numeric values in {c}")
        if new.isin([float("inf"),float("-inf")]).any(): raise ValueError(f"Infinite values in {c}")
        df[c] = new
    df["phase_bucket"] = df.phase.map(phase_name)
    df["completion"] = df.overall_status.map(completion_label)
    df["reported_significance"] = [significance_label(s,p) for s,p in zip(df.overall_status,df.label_min_primary_p)]
    df["split"] = df.start_year.map(split_year)
    df["cohort_eligible"] = (registered-dates).dt.days.le(90) & df.completion.notna()
    verify_partitions(df)
    return df

def verify_partitions(df):
    keys = ["nct_id", "start_year", "split"]
    group_key = "leakage_group_id" if "leakage_group_id" in df.columns else None
    if group_key: keys.append(group_key)
    return verify_split_records(df[keys].to_dict("records"), group_key=group_key)

def identity(args, config):
    return {"data_sha256":sha(args.data), "config_sha256":sha(ROOT/"config.json"),
            "code_sha256":{p:sha(ROOT/p) for p in ["run.py","policy.py"]},
            "mode":"retrospective_current_record",
            "python":platform.python_version(), "seed":config["seed"]}

def audit(df, config):
    eligible = df[df.cohort_eligible & df.split.ne("excluded")]
    rows = []
    for phase in config["phases"]:
        for target in config["targets"]:
            for split in ["train","validation","calibration","test"]:
                d = eligible[(eligible.phase_bucket==phase)&(eligible.split==split)]
                if split == "test":
                    rows.append({"phase":phase,"target":target,"split":split,
                                 "n_cohort":len(d),"outcomes":"WITHHELD_UNTIL_FINAL_EVALUATION"})
                    continue
                y = d[target].dropna().astype(int).tolist()
                rows.append({"phase":phase,"target":target,"split":split,"n_cohort":len(d),
                             "n_labeled":len(y),"n_positive":sum(y),"n_negative":len(y)-sum(y),
                             "coverage":len(y)/len(d) if len(d) else None,
                             "supported":supported(y, config["minimum_per_class_per_split"])})
    return {"source_rows":len(df),"eligible_rows":len(eligible),
            "excluded_combined_early_other":eligible.phase_bucket.value_counts().to_dict(),
            "missingness_development_only":eligible[eligible.split.ne("test")][FEATURES].isna().mean().to_dict(),"tasks":rows,
            "split_integrity":verify_partitions(df),
            "warnings":["Retrospective current-record study; historical feature and label availability not established.",
                        "Q2 is the existing numeric MIN-p proxy among completed reporters; p-value qualifiers/direction/multiplicity unavailable.",
                        "One row per NCT ID; no validated drug-level grouping or transition labels.",
                        "20 per class is a feasibility floor, not a power calculation."]}

def metrics(y,p):
    import numpy as np
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss, log_loss, confusion_matrix, f1_score
    y,p = np.asarray(y,dtype=int), np.clip(np.asarray(p,dtype=float),1e-7,1-1e-7)
    bins=[]
    for lo in np.arange(0,1,.1):
        keep=(p>=lo)&(p<lo+.1)
        bins.append({"lower":round(float(lo),1),"n":int(keep.sum()),
                     "mean_pred":float(p[keep].mean()) if keep.any() else None,
                     "observed":float(y[keep].mean()) if keep.any() else None})
    return {"n":len(y),"prevalence":float(y.mean()),"roc_auc":float(roc_auc_score(y,p)),
            "average_precision_positive":float(average_precision_score(y,p)),
            "average_precision_negative":float(average_precision_score(1-y,1-p)),
            "brier":float(brier_score_loss(y,p)),"log_loss":float(log_loss(y,p)),
            "f1_negative_at_0_5":float(f1_score(1-y,(p<.5).astype(int),zero_division=0)),
            "confusion_matrix_at_0_5":confusion_matrix(y,p>=.5,labels=[0,1]).tolist(),"calibration_bins":bins}

def make_pipe(config, params):
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import Pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import OneHotEncoder
    from sklearn.ensemble import RandomForestClassifier
    numeric=SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)
    categorical=Pipeline([("impute",SimpleImputer(strategy="most_frequent",keep_empty_features=True)),
                          ("encode",OneHotEncoder(handle_unknown="ignore"))])
    prep=ColumnTransformer([("num",numeric,NUMERIC),("cat",categorical,CATEGORICAL)])
    return Pipeline([("prep",prep),("rf",RandomForestClassifier(n_estimators=config["n_estimators"],
                    random_state=config["seed"],n_jobs=2,**params))])

def fit(args, df, config, out):
    import numpy as np
    import joblib
    import sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss
    if not args.retrospective:
        raise ValueError("Current-record inputs support retrospective analysis only. Use --retrospective to label this accurately.")
    if (out/"frozen.json").exists(): raise ValueError("Frozen experiment exists; use a new output directory")
    split_integrity = verify_partitions(df)
    # Discard final-test rows before constructing any development task frame.
    development = df[df.split.isin(["train", "validation", "calibration"])].copy()
    all_results=[]
    for phase in config["phases"]:
        for target in config["targets"]:
            task=f"{phase}_{target}"
            task_df=development[development.cohort_eligible & development.phase_bucket.eq(phase) & development[target].notna()]
            parts={s:task_df[task_df.split.eq(s)] for s in ["train","validation","calibration"]}
            if any(not supported(d[target].astype(int).tolist(),config["minimum_per_class_per_split"]) for d in parts.values()):
                all_results.append({"task":task,"status":"UNSUPPORTED","reason":"insufficient class counts in train/validation/calibration"})
                trace(out,"task_unsupported",task=task)
                continue
            train,val,cal=[parts[s] for s in ["train","validation","calibration"]]
            assert_fit_partition(train[["split"]].to_dict("records"), {"train"})
            assert_fit_partition(cal[["split"]].to_dict("records"), {"calibration"})
            best=None
            for params in config["candidates"]:
                model=make_pipe(config,params)
                model.fit(train[FEATURES],train[target].astype(int))
                p=model.predict_proba(val[FEATURES])[:,1]
                score=float(brier_score_loss(val[target],p))
                trace(out,"validation_candidate",task=task,params=params,brier=score)
                if best is None or score<best[0]: best=(score,model,params)
            score,model,params=best
            # Calibrate on separate rows. The selected forest is not refit on calibration or test.
            cp=np.clip(model.predict_proba(cal[FEATURES])[:,1],1e-7,1-1e-7)
            calibrator=LogisticRegression(C=1.0,random_state=config["seed"]).fit(np.log(cp/(1-cp)).reshape(-1,1),cal[target].astype(int))
            artifact={"model":model,"calibrator":calibrator,"features":FEATURES,
                      "phase":phase,"target":target,"train_prevalence":float(train[target].mean())}
            joblib.dump(artifact,out/f"{task}.joblib")
            manifest=task_df[["nct_id","phase_bucket","split"]].copy()
            manifest.to_csv(out/f"{task}_split_manifest.csv",index=False)
            all_results.append({"task":task,"status":"FROZEN","parameters":params,
                                "validation_brier_uncalibrated":score,
                                "baseline_validation_brier":float(brier_score_loss(val[target],np.full(len(val),artifact["train_prevalence"]))),
                                "artifact_sha256":sha(out/f"{task}.joblib")})
    frozen={**identity(args,config),"sklearn":sklearn.__version__,"tasks":all_results,
            "split_integrity":split_integrity,
            "claim":"Retrospective within-phase completion/significance; no progression prediction"}
    write(out/"frozen.json",frozen)
    trace(out,"freeze",tasks=all_results)

def evaluate(args,df,config,out):
    import numpy as np
    import joblib
    import sklearn
    from sklearn.metrics import roc_auc_score, brier_score_loss
    frozen=json.loads((out/"frozen.json").read_text())
    if verify_partitions(df) != frozen["split_integrity"]:
        raise ValueError("Split integrity differs from frozen experiment")
    current=identity(args,config)
    for key in ["data_sha256","config_sha256","code_sha256","python"]:
        if current[key]!=frozen[key]: raise ValueError(f"Frozen experiment changed: {key}")
    if sklearn.__version__!=frozen["sklearn"]: raise ValueError("scikit-learn version differs from frozen run")
    # A consumed final test may not be rerun or used to drive tuning, even after a partial failure.
    with (out/"TEST_CONSUMED").open("x") as f: f.write(datetime.now(timezone.utc).isoformat())
    results=[]
    for item in frozen["tasks"]:
        if item["status"]!="FROZEN": results.append(item); continue
        task=item["task"]
        if sha(out/f"{task}.joblib")!=item["artifact_sha256"]: raise ValueError("Model artifact changed")
        a=joblib.load(out/f"{task}.joblib")
        d=df[df.cohort_eligible & df.phase_bucket.eq(a["phase"]) & df.split.eq("test") & df[a["target"]].notna()]
        y=d[a["target"]].astype(int).to_numpy()
        if not supported(y.tolist(),config["minimum_per_class_per_split"]):
            results.append({"task":task,"status":"UNSUPPORTED_TEST"}); continue
        p=np.clip(a["model"].predict_proba(d[FEATURES])[:,1],1e-7,1-1e-7)
        p=a["calibrator"].predict_proba(np.log(p/(1-p)).reshape(-1,1))[:,1]
        baseline=np.full(len(y),a["train_prevalence"])
        rng=np.random.default_rng(config["seed"])
        aucs=[]; gains=[]
        for _ in range(200):
            ix=rng.integers(0,len(y),len(y))
            if len(np.unique(y[ix]))<2: continue
            aucs.append(roc_auc_score(y[ix],p[ix]))
            gains.append(brier_score_loss(y[ix],baseline[ix])-brier_score_loss(y[ix],p[ix]))
        report={"task":task,"status":"EVALUATED","model":metrics(y,p),"prevalence_baseline":metrics(y,baseline),
                "roc_auc_95_interval":np.quantile(aucs,[.025,.975]).tolist(),
                "brier_improvement_95_interval":np.quantile(gains,[.025,.975]).tolist(),
                "interval_limit":"NCT-row bootstrap; correlated drugs/sponsors may make intervals optimistic"}
        results.append(report)
        d[["nct_id"]].assign(observed=y,predicted=p).to_csv(out/f"{task}_predictions.csv",index=False)
        write(out/"test_report.json",results)
        trace(out,"test_evaluated",task=task)
    write(out/"test_report.json",results)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=["audit","train","evaluate"])
    parser.add_argument("--data",required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--retrospective",action="store_true")
    args=parser.parse_args()
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/"config.json").read_text())
    validate_features(FEATURES)
    try:
        df=load_data(args.data)
        trace(out,"start",stage_requested=args.stage,data_sha256=sha(args.data))
        if args.stage=="audit": write(out/"audit.json",audit(df,config))
        elif args.stage=="train": fit(args,df,config,out)
        else: evaluate(args,df,config,out)
    except Exception as e:
        trace(out,"FAIL",error=str(e)); raise

if __name__=="__main__": main()

