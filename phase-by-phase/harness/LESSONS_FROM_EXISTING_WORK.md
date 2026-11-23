# Lessons from the existing jbajaj6 project for Leo's phase-by-phase design

Reviewed November 23, 2026. These are the team's documented repository findings,
not a claim that Jai personally performed every analysis. They guide this
extension's experiments; they are not newly measured phase-specific results.

Sources: [team report](https://github.com/jbajaj6/DrugTrialPredictor/blob/main/docs/report.md)
(sections 2–6 and 8–9) and [README](https://github.com/jbajaj6/DrugTrialPredictor/blob/main/README.md).
Reviewed report blob: 2cc429eea23995e9170d375aa5797b278cb9a9c0.
Reviewed README blob: 72799324fcda54006f2977a52252f9bef95c1592.
The current issue listing contains the two draft PRs, not an independent
catalog of reported model bugs.

## Findings mapped to this design

| Existing finding or issue | What it means for Leo's work | Decision and state |
|---|---|---|
| Tuned RF pooled ROC-AUC was .681 for completion and .725 for the reported-significance target; boosting tied RF for completion. | RF is a reasonable starting model, but these numbers establish neither its superiority in every phase nor six new performance results. | IMPLEMENTED: start with RF and phase-specific prevalence comparators. Never use old AUCs as pass thresholds. |
| Existing model's completion AUC was about .74 in Phase 1 and .61–.64 in Phases 2–3. | Pooled performance hides differences between phases. These are subgroup results for the existing model, not separately retrained forests. | IMPLEMENTED: phase-specific models/reports. REQUIRED EVAL: report support, coverage, ranking and calibration in each phase. Do not promise splitting improves results. |
| Sponsor history was the only clear incremental completion gain (+.025 AUC), with no clear significance gain. | Operational experience may help completion more than significance. It needs to be re-tested within each phase. | IMPLEMENTED: permitted sponsor counts/first-trial flag. PENDING: matched-row design-only vs +safe-history ablations and paired uncertainty. Exclude the existing leaked smoothed stop-rate until safely rebuilt. |
| Recorded stopping reasons were mostly enrollment (~34%) or business (~18%), rather than efficacy (~6%) or safety (~4%). | Completion and reported significance answer different questions. The percentages come from retrospective text bucketing, not new no-NLP labels. | IMPLEMENTED: keep two targets; exclude post_why_stopped as a feature. PENDING: exploratory withdrawn-vs-terminated sensitivity, without parsing text in v1. |
| Phase 2/combined phases and oncology had higher stop rates; industry and academic sponsorship differed. | Splitting by phase does not remove disease/sponsor case-mix differences. | IMPLEMENTED: structured disease and sponsor features and separate combined-phase handling. PENDING: audit phase × disease/sponsor/year base rates and Q2 coverage; subgroup model metrics need support counts. No causal interpretation. |
| About 79% completed. Balanced weights substantially improved stopped-class F1 in original validation. | Accuracy alone can hide failure to flag stops; imbalance can differ in every phase and target. | IMPLEMENTED: weighted/unweighted RF candidates, average precision for both outcomes and stopped-class F1. No default SMOTE or resampling. Original F1 gain is not promised under this harness's Brier-based selection. |
| More tuning usually changed AUC by less than .005; deeper forests overfit the training years. | Large agent-driven searches can spend time exploiting validation noise. | IMPLEMENTED: four prespecified candidates and bounded repair loops. PENDING: train-versus-validation overfit diagnostics before any justified search expansion. Never tune against final test. |
| Funding, hype and structured science did not show clear pooled incremental prediction gains; Q2 text gains were uncertain. | More sources need not help, and a pooled null finding does not prove zero benefit in every phase. | IMPLEMENTED: current structured data only; no NLP/external joins. Future additions require within-phase matched-cohort ablations. Do not convert missing coverage into universal zero. |
| Sites/countries inflated AUC by ~.04; final enrollment overwrites planned enrollment; registration lag can encode later cancellation. | Useful-looking predictors may reveal the outcome. | IMPLEMENTED: exclude sites, final enrollment and registration lag from inputs; keep the <=90-day registration cohort rule only. Historical planned values require actual provenance before inclusion. |
| Latest records can revise planned outcomes and eligibility; historical retrieval failed in the project. | Even structured fields may have post-start revisions. Start-year splitting does not recreate past knowledge. | IMPLEMENTED: describe the study as retrospective current-record evaluation. PENDING: historical feature and label-availability audit before claiming a registration-time backtest. |
| Q2 has 9,030 completed p-reporting trials versus 73,842 Q1 trials; the MIN-p label misses non-inferiority/multiplicity issues. | The two tasks describe different populations. Missing Q2 is unknown, and Phase 1 may not have suitable statistical efficacy outcomes. | IMPLEMENTED: unknowns remain unknown, phase/split coverage and sparse-task stop conditions. PENDING: reporting coverage by year/sponsor/disease and qualifier/direction/endpoint-design audit. Label stays reported significance, not beneficial efficacy. |
| Test-year stop rates rose roughly 20% to 26%; unfinished long trials are missing from the final-status cohort. | Cohort selection and case mix can shift both probability quality and ranking. | IMPLEMENTED: separate calibration year. PENDING: year-stratified base rates, reporting and model calibration sensitivity. Never recalibrate using final-test outcomes. Do not inherit the report's broad assertion that censoring cannot affect ROC-AUC: selection can change class-conditional populations too. |
| Drug-name matching initially linked ordinary words to irrelevant news; the phase extension still pools comparator drugs. | Relevant to later highest-phase linking, not a blocker for one-row-per-NCT completion/significance tasks. | IMPLEMENTED: NCT identity, no provisional program IDs as predictors. LATER: arm-aware regimen/indication links and controlled aliases before progression labels. |
| Completion/significance were associated with drug-level FDA approval. | Association does not make either score an advancement or approval probability; drug-level approval is not automatically indication-specific. | IMPLEMENTED: no multiplying Q1/Q2 probabilities into highest-phase predictions. LATER: explicit linked transition outcomes, mature follow-up and indication-specific evidence. |

## New harness-review finding, separate from prior empirical lessons

The existing sponsor_prior_stop_rate smooths rows with a global outcome prior
through 2015. This harness fits through 2012, validates on 2013–2014 and
calibrates on 2015. The smoothed feature would leak held-out outcomes into
earlier rows. It stays excluded despite the original report's history gain.
Restoration requires a permitted-data-only prior and dated provenance checks.

## Required agent use

Before a proposed change, state the source finding and original cohort,
whether it applies now or only to longitudinal linkage, the exact change
inside phase-by-phase, and its implementation/evaluation state.

Data auditor: inspect base rates and Q2 reporting coverage by phase, year,
disease and sponsor. Keep these descriptive outcome summaries out of model
inputs. Do not silently change the cohort to reproduce the earlier findings.

Builder: keep the small RF search, no-NLP allowlist and separate targets. Safe
history ablations must use the same eligible rows and splits. Do not add new
sources or rebuild the broader pipeline.

Evaluator: distinguish inherited background, newly measured within-phase
results and pending follow-ups. A previous pooled finding is not a successful
replication. A confidence interval overlapping no gain stays uncertain.

## Scope and current status

All changes remain under phase-by-phase/harness. This update records lessons,
adds explicit evaluation requirements and assigns follow-up work. It does not
claim that pending ablations, subgroup audits or real-data experiments have run.

## Proposed extension: predict reported operational stopping reasons

See [STOPPING_REASON_DESIGN.md](STOPPING_REASON_DESIGN.md). Enrollment and business
reasons can become audited outcomes for an auxiliary phase-specific forest,
with unknown/ambiguous reasons retained. This design is pending implementation;
existing completion/significance models remain unchanged. Regimen complexity
is a hypothesis to test, not a hard-coded enrollment penalty.
