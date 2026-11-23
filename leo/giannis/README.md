# Leo / Giannis — Phase-by-Phase Extension

This folder contains the phase-by-phase extension to DrugTrialPredictor. It is
separate from the repository's original **one-trial-at-registration** completion
and primary-endpoint analyses. Here the unit is an **exact-label candidate drug
regimen plus indication**, followed through registered trials over time.

## Project question

Can information available at registry entry, and later information publicly
posted after Phase 1 or Phase 2, help predict whether a separately registered
pure Phase 3 trial starts in the following five years? A matching Phase 3 start
is **development activity**, not efficacy, regulatory approval, or proof that
the drug works. A missing match is not proof of drug failure.

## What is in this folder

| Path | Contents |
| --- | --- |
| [phase-by-phase/](phase-by-phase/) | Acquisition, arm-aware cleaning, candidate linkage, audits, longitudinal snapshots, analysis code and tests |
| [Phase-by-phase README](phase-by-phase/README.md) | Pipeline diagram, data rules, definitions, commands and validation approach |
| [Executed results](phase-by-phase/RESULTS.md) | Actual counts, model-feasibility findings and limitations from the full run |
| [Status](phase-by-phase/STATUS.md) | What is implemented versus still unresolved |
| [Source review](phase-by-phase/SOURCE_REVIEW.md) | Bounded, source-linked review of ambiguous records |
| [visualizations/](visualizations/) | Two interactive HTML explainers: [pipeline walkthrough](visualizations/drug-development-walkthrough.html) and [analysis-methods lab](visualizations/analysis-methods-lab.html) |

The longer [project learning guide](https://chatgpt.com/space/page_d8723a0d42748191ac34fc65d61aee01)
explains the SQL, table shapes, joins, modeling choices and limitations with a
knowledge-check question after each section. It is a separate ChatGPT Page,
not a file in this GitHub repository.

## Where we are

The end-to-end ClinicalTrials.gov pipeline has run on a complete saved query of
**151,081 drug/biologic trial records** as of 2026-11-19. The arm-aware rules
retained **67,109 trials**, yielding **71,485 exact-label candidate programs**
and **112,292 arm-level links**. Structural/source audits passed; the overall
quality status is **WARN** because drug/indication identity and historical
registry versions have not been clinically validated.

The five-year mature checkpoint cohorts contain **7,689** registry-entry
snapshots with **53** matching Phase 3 events, **870** post–Phase 1 snapshots
with **2** events, and **27** post–Phase 2 snapshots with **0** events. After
chronological holdouts, label-availability gaps and related-program purges,
there are too few independent positive examples to fit or evaluate a credible
real-data predictor. The pipeline reports **not estimable**; it does not claim
an individual drug probability, model AUC or p-value for this analysis. See
the [executed results](phase-by-phase/RESULTS.md) for the exact split counts.

## How the data are organized

```text
ClinicalTrials.gov saved JSON pages
  -> trials + interventions + conditions
  -> experimental-arm program_trials + programs
  -> exclusions, aliases and source-linked review queue
  -> program_timelines
  -> dated snapshots (baseline, post-Phase 1, post-Phase 2)
  -> mature outcomes and chronology/group-aware splits
  -> model only if the support gate passes
```

The `trials`, `interventions` and `conditions` tables retain raw provenance;
`program_trials` is the candidate arm-level bridge. The model would receive
selected features from one row of `snapshots` at a time, not every table
directly. Post-phase features currently count dated trial starts and public
results postings; they do **not** extract safety or efficacy findings.

## Game plan

1. **Validate identity and the target.** Review a stratified sample of candidate
   programs and excluded trials with source links. Measure false links and
   missed Phase 3 continuations; resolve drug aliases, indication equivalence,
   formulations, combinations, background treatment and repurposing explicitly.
2. **Strengthen time accuracy.** Obtain historical registry versions or a
   defensible as-of reconstruction so baseline design and sponsor fields are
   demonstrably available at each landmark. Handle month-only dates through a
   prespecified sensitivity analysis instead of inventing exact days.
3. **Rebuild the risk sets.** Recalculate candidate timelines, five-year labels
   and group-disjoint time splits after reviewed linkage. Report how many
   independent Phase 3 events survive in every partition. Revisit the unit of
   analysis or horizon only with a documented scientific rationale.
4. **Add substantive evidence updates.** Parse publicly dated Phase 1/2
   efficacy and safety results, with missingness and selection-bias checks.
   Keep any FDA approval question separate until an indication-specific
   regulatory outcome table is linked and audited.
5. **Fit and evaluate only when support is sufficient.** Compare historical
   event rate, baseline logistic regression and same-landmark updated models;
   assess Brier score, calibration, discrimination and uncertainty on held-out
   groups. Do not interpret a coefficient p-value as the probability that an
   individual prediction is true.

## Reproduce locally

Run commands from the repository root. The saved full raw and processed files
are under `data/raw/` and `data/processed/` at the repository root. They are
large and intentionally **Git-ignored**, so GitHub contains the code and
documentation, not the downloaded cohort. See the [run instructions](phase-by-phase/README.md#run-it)
for the full download and offline replay commands.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r leo/giannis/phase-by-phase/requirements.txt
.venv/bin/python -m pytest -q
```
