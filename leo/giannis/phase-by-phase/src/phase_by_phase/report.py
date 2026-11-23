"""Generate a readable, evidence-linked report from actual pipeline outputs."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd


def _cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(headers, rows):
    return ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"] + [
        "| " + " | ".join(_cell(x) for x in row) + " |" for row in rows
    ]


def write_report(output: Path, tables: dict, manifest: dict, audit: dict, analysis: dict) -> None:
    trials, links, programs = (tables[x] for x in ["trials", "program_trials", "programs"])
    counts = analysis["cohort"]["checkpoint_counts"]
    linked = links.nct_id.nunique()
    lines = [
        "# Phase-by-phase: executed analysis", "",
        f"Data cutoff: **{manifest['cutoff']}**. Follow-up horizon: **{analysis['horizon_years']} years**.", "",
        "## Bottom line", "",
        f"Downloaded **{len(trials):,} studies**. The conservative arm/condition rules retain "
        f"**{linked:,} trials** in **{len(programs):,} exact-label candidate programs**.", "",
        "These tables are structurally organized and auditable. They are not a clinically validated "
        "drug-development database: molecule aliases, indication equivalence, and historical record versions "
        "remain unresolved. The old 1,755-program pilot count is superseded and not comparable to this stricter cohort.", "",
        "Models are fitted only where the chronological, outcome-availability, and drug-group holdouts "
        "contain enough events. A not-estimable result is a data-feasibility finding, not a model failure.", "",
        "## Source and reproducibility", "",
        "Source: [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api). "
        "Interventional DRUG or BIOLOGICAL studies; Early Phase 1 through Phase 3, "
        "including combined phases and ongoing studies; start dates from 2005 through the cutoff. "
        "This is not all ClinicalTrials.gov and not a random sample.", "",
        f"- API total for this query: {manifest['total_count']:,}.",
        f"- Cached records: {manifest['records']:,}; complete query: {manifest['complete']}.",
        f"- Page files: {len(manifest['pages'])}; every page verified by SHA-256 and NCT uniqueness.",
        "- [Run manifest](run_manifest.json) records query-manifest hash, source-code hashes, package versions, and run time.",
        "- Offline replay uses the saved records; a fresh registry download is a new snapshot.", "",
        "## Cleaning and table organization", "",
    ]
    lines += _table(["Table", "Rows", "Meaning"], [
        (name, f"{len(tables[name]):,}", meaning) for name, meaning in [
            ("trials", "Every downloaded NCT, current metadata and source date precision"),
            ("interventions", "Drug/biologic/control names and arm assignments retained"),
            ("conditions", "Raw labels preserved; no broad MeSH-to-specific-condition guessing"),
            ("program_trials", "Experimental-arm links with one unambiguous condition"),
            ("programs", "Exact-label regimen + indication candidates"),
            ("exclusions", "Explicit reasons at trial or arm level; a trial may have multiple reasons"),
            ("alias_candidates", "Source-supplied names for review, not automatically merged"),
        ]])
    lines += ["", f"Audit outcome: **{audit['overall']}**; hard structural failures: **{audit['hard_fail']}**. "
              "WARN denotes unresolved scientific validation, not silently approved clinical truth. "
              "[Machine-readable audit](quality_audit.json).", ""]
    excluded = tables["exclusions"]
    if not excluded.empty:
        reason_counts = excluded.groupby("reason").nct_id.nunique().sort_values(ascending=False)
        lines += ["### Most common exclusion reasons", ""]
        lines += _table(["Reason", "Distinct trials affected"], [(k, f"{v:,}") for k,v in reason_counts.head(15).items()])
        lines += ["", "Counts overlap: one trial may have several reasons or one excluded and one retained arm.", ""]
    lines += ["### What changed from the prototype", "",
              "- A-versus-B comparator studies no longer become A-plus-B regimens.",
              "- Genuine combinations are formed only from drugs assigned to the same experimental arm.",
              "- Multiple conditions, unresolved compound labels, ambiguous assignments and non-drug cointerventions have explicit exclusions.",
              "- Names retain Unicode and meaningful punctuation; no fuzzy or unreviewed molecular alias merges.",
              "- Partial dates remain partial. Negative labels are not assigned to recent programs with insufficient follow-up.",
              "- The main audit starts from every downloaded trial, not only successfully flattened rows.", "",
              "## Observed phase histories", "",
              "Same labels across phases are candidate links. They do not prove sponsor-program continuity. "
              "Counts below require exact dated ACTUAL starts for chronological transitions; combined Phase 2/3 "
              "does not identify a separate Phase 3 start.", ""]
    lines += _table(["History metric", "Programs"], [(k.replace("_", " "), f"{v:,}") for k,v in analysis["descriptive"].items()])
    lines += ["", "## Prediction-ready risk sets", "",
              f"Endpoint: **{analysis['endpoint']}**. Only events in the strictly linked subset can be found. "
              "A zero means no matching event observed within the horizon, not biological failure, no efficacy, "
              "or proof of discontinuation. Excluded later trials and alias changes can produce false negatives.", "",
              "The baseline is a registry-entry landmark, not guaranteed before Phase 1. Post-phase landmarks "
              "are first valid public results postings, not private internal readouts or completion dates. "
              "Updated models use dated registry-history counts, not detailed safety or efficacy measurements.", ""]
    lines += _table(["Checkpoint", "Snapshots", "Mature", "Phase 3 events", "No matched event", "Not mature/indeterminate"], [
        (k, v["snapshots"], v["mature"], v["observed_phase3_within_horizon"], v["no_observed_phase3_within_horizon"], v["snapshots"]-v["mature"])
        for k,v in counts.items()])
    lines += ["", "Early positive events with insufficient full-horizon follow-up are excluded alongside "
              "short-follow-up negatives, avoiding asymmetric outcome selection.", "",
              "![Cohort and checkpoint counts](cohort.png)", "", "## Model results and conclusions", ""]
    fitted = False
    for checkpoint, model in analysis["models"].items():
        lines += [f"### {checkpoint}", "", f"Status: **{model['status']}**.", ""]
        if model.get("reason"):
            lines += [model["reason"], ""]
        if model.get("support"):
            lines += _table(["Partition", "Programs", "Positive", "Negative", "Drug/NCT groups"], [
                (k, v["n"], v["positive"], v["negative"], v["groups"]) for k,v in model["support"].items()])
            lines += [""]
        split = model.get("split", {})
        if split.get("validation_start"):
            lines += [f"Validation starts {split['validation_start']}; test starts {split['test_start']}. "
                      "Outcome-availability embargoes and related-drug purges reduce the usable samples.", ""]
        if model["status"] == "exploratory_fit":
            fitted = True
            lines += _table(["Model", "Test AUC", "Average precision", "Brier (lower better)", "Log loss"], [
                (k, f"{v['roc_auc']:.3f}", f"{v['average_precision']:.3f}", f"{v['brier_score']:.4f}", f"{v['log_loss']:.4f}")
                for k,v in model["test_metrics"].items()])
            winner = model["selected_on_validation_brier"]
            lines += ["", f"Selected on validation Brier score: **{winner}**. All shown test models are prespecified; "
                      "the test set is not used to select the winner.", ""]
            paired = model["uncertainty"].get("paired_brier_improvement_baseline_minus_updated")
            if paired:
                lines += [f"Adding dated history changes Brier score by {paired['estimate']:.4f} "
                          f"(baseline minus updated; 95% test-group bootstrap interval {paired['low']:.4f} to {paired['high']:.4f}). "
                          + ("The interval crosses zero: improvement is inconclusive." if paired['low'] <= 0 <= paired['high']
                             else "This is conditional on the fitted models and the provisional linkage rules, not causal evidence."), ""]
    if not fitted:
        lines += ["**No model met the prespecified support requirements.** We therefore do not report a "
                  "75% probability, accuracy, or a p-value as if it were validated. The implemented model "
                  "pipeline runs on supported data; this extraction's remaining support is documented above.", ""]
    lines += ["## What the conclusions do and do not establish", "",
              "1. Structural checks establish reproducible bookkeeping, not verified biological identity.",
              "2. Exact-name, single-indication linkage is conservative and incomplete; exclusions change the target population.",
              "3. Counts describe registered development activity, not drug efficacy or approval probability.",
              "4. Current registry fields are not historical versions. Any fitted scores are exploratory retrospective estimates.",
              "5. Post-results samples have publication/selection bias. Test metric intervals are not intervals for an individual drug's chance.",
              "6. FDA approval, detailed adverse-event/efficacy extraction, coefficient p-values and individual probability intervals are not produced.", "",
              "## How to inspect or rerun", "",
              "- [Analysis report JSON](analysis_report.json): all support counts, split boundaries, metrics, bootstrap intervals and limitations.",
              "- [Quality audit JSON](quality_audit.json): source reconciliation, integrity and missingness.",
              "- [Snapshots](snapshots.parquet): one program/checkpoint row with dates, features, outcome and censoring reason.",
              "- [Trial exclusions](exclusions.parquet): every rejected mapping with its reason.",
              "- [Review queue](linkage_review_queue.parquet): seeded source-linked candidates for clinical identity review.",
              "- [Predictions](predictions.parquet): held-out predictions only, when support gates pass.", "",
              "Run the documented offline command in the [project README](../../../leo/giannis/phase-by-phase/README.md). "
              "Use a new output directory to preserve previous runs.", ""]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    _plots(output, tables, analysis)


def _plots(output: Path, tables: dict, analysis: dict) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(output / ".mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), layout="constrained")
    labels = ["Downloaded trials", "Trials with strict links"]
    values = [len(tables["trials"]), tables["program_trials"].nct_id.nunique()]
    axes[0].bar(labels, values, color=["#346b9c", "#22867a"])
    axes[0].set_title("Trial-level selection")
    axes[0].set_ylabel("Distinct trials")
    for i,v in enumerate(values):
        axes[0].text(i, v, f"{v:,}", ha="center", va="bottom")
    counts = analysis["cohort"]["checkpoint_counts"]
    names = list(counts)
    mature = [counts[n]["mature"] for n in names]
    immature = [counts[n]["snapshots"] - counts[n]["mature"] for n in names]
    axes[1].bar(names, mature, label="Full follow-up", color="#22867a")
    axes[1].bar(names, immature, bottom=mature, label="Short/indeterminate", color="#deb166")
    axes[1].set_title("Candidate programs at each checkpoint")
    axes[1].set_ylabel("Program-checkpoint rows")
    axes[1].legend()
    fig.suptitle("Phase-by-phase cohort audit — exact-label, strict linked subset")
    fig.savefig(output / "cohort.png", dpi=170)
    plt.close(fig)
    for checkpoint, model in analysis["models"].items():
        if model["status"] != "exploratory_fit":
            continue
        fig, ax = plt.subplots(figsize=(6, 5), layout="constrained")
        ax.plot([0, 1], [0, 1], "--", color="gray", label="Perfect calibration")
        for name, values in model["test_metrics"].items():
            bins = values.get("calibration_bins", [])
            if bins:
                ax.plot([x["mean_prediction"] for x in bins], [x["observed_fraction"] for x in bins], "o-", label=name)
        ax.set(xlabel="Mean predicted probability", ylabel="Observed strict-cohort event fraction",
               title=f"Exploratory held-out calibration: {checkpoint}", xlim=(0, 1), ylim=(0, 1))
        ax.legend(fontsize="small")
        fig.savefig(output / f"calibration_{checkpoint}.png", dpi=170)
        plt.close(fig)
