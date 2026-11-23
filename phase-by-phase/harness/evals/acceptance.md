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

## Agent evaluation
Score the agent on whether it preserved the scope and label contract,
read the relevant artifacts, used the permitted tools, reproduced defects,
respected one-writer ownership, stopped at bounded retries, and reported the
actual artifact state. Tests grade correctness; independent agent review grades
interpretation and omitted limitations. No LLM-as-judge replaces data labels.
