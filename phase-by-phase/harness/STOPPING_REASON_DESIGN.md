# Phase-specific prediction of reported stopping reasons

Status: DESIGN ADDED; label audit, implementation and real-data evaluation PENDING.
Scope: phase-by-phase/harness only. Existing six completion/significance tasks
are unchanged. This adds a proposed auxiliary model within each phase, using
current structured predictors and the existing categorized stopping labels.

## Question and interpretation

Can information about the design and sponsor predict whether a trial will
eventually stop with an enrollment-related or business-related recorded reason?

The ~34% enrollment and ~18% business figures describe recorded reasons among
stopped trials in the earlier cohort. They are NOT probabilities for every new
trial, phase-specific priors, or feature weights. Estimate every phase's own
rates from its training data.

Predicting a reported reason is different from proving a cause. For example,
a combination regimen might be associated with enrollment difficulty because
it is studied in a harder-to-recruit disease population. It could also help
recruitment in some contexts. Test the hypothesis; do not hard-code a penalty.

## Proposed output per phase

Keep completion and significance outputs. Add an auxiliary multiclass random
forest whose probabilities describe these mutually exclusive observed events:

| Class | Training label |
|---|---|
| Completed | Final status COMPLETED |
| Stopped: reported enrollment reason | TERMINATED/WITHDRAWN with audited enrollment label |
| Stopped: reported business reason | TERMINATED/WITHDRAWN with audited business label |
| Stopped: another reported reason | Other sufficiently clear reported stopping category |
| Stopped: unknown or ambiguous reason | Missing/not_given/unclear/multiple unresolved categories |

Keeping unknown/ambiguous stopping as its own class avoids treating an
undocumented enrollment failure as a confirmed negative or dropping all such
trials. The probabilities predict the recorded event, including documentation
patterns; true unreported causes remain unidentified.

For this model only, the sum of all stopped-class probabilities is its overall
stopping probability. Do not multiply a reason percentage among documented
stops by the separate Q1 forest's score and call it unconditional causal risk.
The existing binary Q1 model is a comparator, not a guaranteed probability
identity with a separately fitted auxiliary model. A UI should either use the
multiclass model's coherent completion/stopping decomposition or clearly label
the two models as different estimates.

## Existing labels need an audit first

The broader code already produces post_stop_reason from post_why_stopped with
regex rules. That is label construction, not a permitted predictor. Keep the
current no-NLP input promise: reuse categorized labels read-only; do not add
text, embeddings, an LLM judge, or stopping-reason words to model inputs.

Source: [features.py](https://github.com/jbajaj6/DrugTrialPredictor/blob/main/src/dtp/features.py),
why_stopped_category and add_labels. The existing rules are explicitly first
match wins (safety, efficacy, enrollment, business, PI/site, regulatory), so a
multi-reason statement can lose its secondary cause. Broad words such as
participant or sponsor can also yield noisy categories.

Required before training:
- Count each category and missing/unknown reasons by phase, status, split/year.
- Manually review a reproducible stratified sample of existing assignments;
  record disagreements, missing categories and multi-reason cases. Review
  confirms label accuracy, not counterfactual causation.
- Version the mapping and adjudications within phase-by-phase. Do not edit the
  broader classifier or silently alter label policy after test results.
- Preserve unknown/ambiguous cases; do not force every stop into enrollment or
  business. If multi-reason flags cannot be recovered from existing categorical
  labels, explicitly document that limitation before claiming exclusivity.
- Distinguish withdrawals (before enrollment) and terminations in the audit.
  Do not use the eventual status as an input to a registration-time model.
- Require per-class support in every partition. If enrollment/business labels
  in a phase are sparse or unreliable, mark that output unsupported.

## Hypotheses and usable information

| Hypothesis to test | Available structured information | Limit |
|---|---|---|
| More complicated design is associated with enrollment-related stopping | number_of_arms, intervention_model, allocation, masking | Proxies for design complexity, not direct measures of participant burden |
| Narrower eligible population is associated with enrollment-related stopping | Structured age limits, eligible gender, healthy-volunteer flag, disease area | Does not measure all exclusions or disease prevalence; no text parsing in v1 |
| Less experienced sponsors have greater operational stopping risk | Sponsor class, permitted prior finished counts and first-trial flag | Existing smoothed stop-rate remains excluded for leakage |
| Certain disease/design combinations have higher enrollment risk | Disease category plus structured design; RF can learn interactions | Correlation and case mix, not proof that changing one feature fixes recruitment |
| Business-related stopping correlates with sponsor/design history | Sponsor class, permitted experience counts, design and year | Cash runway, budgets, strategy changes and supply problems are not directly observed |
| A more burdensome regimen hurts recruitment | Validated active-regimen complexity would be needed | Current n_drug_interventions can count comparator drugs; do not interpret it as drugs each patient takes |

The existing allowlist contains n_drug_interventions. It may remain a generic
study-level intervention count, but explanations must not relabel it as a
validated combination regimen. Demonstrating the user's regimen hypothesis
requires arm-aware active treatments and, ideally, baseline dose/route/visit
burden. These are later feature-audit tasks, not data we currently possess.
Never substitute final enrollment or sites to fill this gap.

## Explain a prediction without inventing a mechanism

Use held-out per-class permutation importance to test whether feature groups
help each reason task. For individual explanations, add a verified tree
attribution method only as a later, tested component; contributions explain
the fitted score, not causal effects.

An output can say:
“Elevated predicted risk of enrollment-related reported stopping; associated
model inputs include the trial's design, eligible age range and disease area.”
It must not say:
“The regimen will cause recruitment failure.”
Only list features that the actual fitted explanation supports. Return an
unsupported/uncertain explanation when feature provenance or attribution fails.
No new LLM-written explanations are required for v1.

## Evaluation and agent acceptance

Reuse chronological train/validation/calibration/test partitions, label
provenance, frozen test guard and no-NLP allowlist. Do not tune using the
already exposed test set. This is a new planned experiment; it requires its
own prespecified protocol and a genuinely untouched holdout before claiming
confirmatory performance if earlier test outcomes have been inspected.

Compare to training phase-specific class prevalence; report per-class counts,
reporting coverage, one-vs-rest average precision/ROC-AUC, probability
calibration, multiclass log loss and Brier score definition, confusion matrix,
and uncertainty. Evaluate enrollment/business performance by sponsor and
disease only where support permits. Check whether results are driven by
documentation/missingness and compare withdrawn/terminated cohorts.

The current binary calibrator in run.py is not a multiclass implementation.
Do not simply append class names to config.json. Builder must implement
multiclass metrics, calibration, support checks, schema and tests separately
under this extension, after label audit passes. Keep the initial six tasks
intact while testing this addition.

Coordinator -> label auditor -> builder -> independent evaluator, with the
existing bounded repair loop. The evaluator checks unknown-reason handling,
first-match label noise, prohibited predictors, per-class calibration, regimen
provenance, and causal language. No model or performance result is claimed yet.
