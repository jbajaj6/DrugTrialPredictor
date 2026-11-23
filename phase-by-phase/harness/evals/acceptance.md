# Evaluations and stop conditions

## Deterministic correctness
Must pass: labels, missing p unknown, p=.05 boundary, invalid p handling,
combined/early-phase isolation, no-NLP allowlist, date-to-year consistency,
unique NCT IDs, required column checks, no nonfinite numerical features.
The dependency-free regression suite covers policy functions. Real-data audit
and runner integration checks are separate; never claim all are covered by it.

## Required runner integration cases (not yet executed)
1. Generate a separate seeded synthetic fixture with both classes in each
phase/target/split, minimum 20/class. Mark all outputs SYNTHETIC.
2. Audit, train, evaluate; verify six distinct artifacts and finite metrics.
3. Second final evaluation must fail; input/config/code/model mutations after
freeze must fail. Check hash manifests and atomic test marker.
4. Missing required column, duplicated NCT, invalid numeric, inconsistent
start_year, single-class stratum: fail or explicit UNSUPPORTED, never silent pass.
5. Extreme values/category present only in test must not change train-fitted
imputation or category vocabulary. Known labels must not appear in model inputs.
6. Include unknown/missing p, stopped trial with p, combined phases, and bad
dates. Check exact exclusion funnel and Q2 denominator.
7. End-to-end rerun with identical seed/input/environment must yield equal
validation predictions within documented numerical tolerance.
8. A test-score-dependent proposed fix must stop; no test-fishing repair loop.

## Model evaluation
For each phase and target report N/class counts and reporting coverage,
ROC-AUC, average precision for each class, Brier score, log loss, calibration
bins, confusion matrix and negative-class F1 at a fixed .5 threshold.
The runner compares RF to a phase-specific training-prevalence baseline.
Bootstrap ROC-AUC and paired Brier improvement; current runner uses 200
NCT-row resamples. Report correlation limitation. Drug/sponsor grouped
sensitivity, 3-seed robustness, disease-rate comparator, permutation importance,
and uncertainty for other metrics are useful follow-ups, NOT implemented here.

Do not require an invented minimum AUC. If RF fails to beat baseline or its
interval overlaps no gain, report no demonstrated improvement. This is a valid
research result. A small cohort that passes the feasibility floor can still
have inadequate precision or statistical power.

## Acceptance items from the existing project's lessons

Read LESSONS_FROM_EXISTING_WORK.md. Require phase × year/disease/sponsor base
rates and reporting coverage before real training. Keep outcome summaries out
of feature inputs. PENDING evaluations: matched-row design-only vs safe-history
ablations, train/validation overfit diagnostics, withdrawn-vs-terminated
sensitivity, and year-stratified calibration. Mark these pending until actually
run. Pooled null findings are not proof of null effects in each phase; earlier
subgroup AUCs are not separately trained model results. No NLP or external data
is introduced by applying these lessons.

## Agent evaluation
Score the agent on whether it preserved the scope and label contract,
read the relevant artifacts, used the permitted tools, reproduced defects,
respected one-writer ownership, stopped at bounded retries, and reported the
actual artifact state. Tests grade correctness; independent agent review grades
interpretation and omitted limitations. No LLM-as-judge replaces data labels.

## Enforced data separation

The forest fits only 2005–2012 rows; model selection uses 2013–2014; a separate
calibrator fits only 2015; final evaluation uses 2016–2019. Preprocessing is
training-fitted. Test rows are removed before constructing development task
frames; test labels/rates are withheld from development audit output. Every
run verifies unique NCT IDs, year-to-partition assignment and split integrity.
If a validated leakage_group_id is supplied, cross-partition related groups
also fail. Provisional program links are not accepted as verified groups.
Absent a verified group, only NCT-level separation is established. The frozen
input/code/config/model hashes and one-use test marker still apply.

25 dependency-free policy tests now pass, including duplicate NCT, wrong-year
routing, optional related-group overlap and estimator-fit partition guards.
ML pipeline integration remains unexecuted in this workspace.
