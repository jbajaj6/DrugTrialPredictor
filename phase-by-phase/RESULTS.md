# Executed findings — 2026-11-19

## Conclusion

The acquisition, cleaning, longitudinal-table, evaluation and reporting pipeline
has been implemented and executed. **The current strict linked dataset does not
support a credible evaluation of the proposed dynamic Phase 3 predictor.**
It supports a data-quality and longitudinal feasibility analysis. This is a
limitation of this identity/chronology/cohort construction, not evidence that
drug progression is inherently unpredictable.

No real-data model was fitted, no test AUC was manufactured, and no individual
probability or significance p-value is claimed. The model implementation is
verified using synthetic tests, clearly separate from empirical findings.

## Data and cleaning

| Measure | Final count |
| --- | ---: |
| Complete query records | 151,081 |
| Retained trials with strict experimental-arm links | 67,109 |
| Candidate exact-label regimen–indication programs | 71,485 |
| Arm-level trial–program links | 112,292 |
| Candidate programs containing multiple trials | 5,333 |
| Candidate programs spanning multiple phase labels | 2,522 |
| Candidates with both pure Phase 1 and pure Phase 3 records, irrespective of order | 421 |
| Candidates with precise actual Phase 1 start before precise actual Phase 3 start | 119 |

One trial can contain multiple experimental regimens, so the number of
candidate programs can exceed the number of retained trials. Program identities
are not independently validated molecular development programs.

The source query covers interventional drug/biologic trials, Early Phase 1
through Phase 3, starting from 2005 through 2026-11-19, including ongoing and
combined-phase trials. It does not cover all registered research or all
first-ever development. All 152 saved pages passed checksum and count checks.

Important data constraints:

- 43,857 trials list multiple conditions and are excluded from strict linkage.
- 58,373 start dates have month-only precision; the primary analysis does not
  invent exact days for them.
- 110,285 source trials have no public results-posting date (73.0%).
- 251,344 source-supplied alias rows are retained for review, not silently merged.
- Only 44.4% of downloaded trials meet the strict linkage rules.

Exclusion counts can overlap. Exact-name matching can both fragment true programs
and conflate studies with different purposes/formulations. The bounded
[source review](SOURCE_REVIEW.md) documents concrete examples and fixes.

## Five-year Phase 3 risk sets

The event is a matching, separately registered pure Phase 3 ACTUAL trial start
within the strict included cohort. **No match observed is not the same as drug
failure.** Excluded later trials and aliases can create apparent non-events.

| Checkpoint | Snapshots | Full follow-up / determinate | Observed events | No matched event |
| --- | ---: | ---: | ---: | ---: |
| Registry-entry baseline | 13,701 | 7,689 | 53 | 7,636 |
| First public Phase 1 results | 1,878 | 870 | 2 | 868 |
| First public Phase 2 results | 80 | 27 | 0 | 27 |

These are selected risk sets, not general drug-success rates. The post-phase
groups require public results and therefore have publication/selection bias.
The baseline is registry entry, not necessarily before Phase 1 started.

## Why the predictive analyses were not fitted

The model code requires chronological holdouts, full-horizon label availability,
and separation of shared drug components/NCT IDs. After those rules:

| Checkpoint | Train: rows / events | Validation: rows / events | Test: rows / events |
| --- | ---: | ---: | ---: |
| Registry entry | 293 / 0 | 184 / 2 | 1,097 / 4 |
| Post–Phase 1 | 11 / 0 | 12 / 0 | 60 / 0 |
| Post–Phase 2 | No adequate calendar span | No adequate calendar span | No adequate calendar span |

Training sets with no positive examples cannot estimate a useful advancement
classifier. Two or four held-out events would also not support a reliable
model comparison. The pipeline correctly returned **not_estimable** at every
checkpoint rather than reporting an impressive but misleading accuracy.

The implemented analyses are:

1. EDA, missingness, exclusion and linkage diagnostics — executed.
2. Observed phase histories and time between phases — executed.
3. Historical-rate and logistic probability models — implemented; data gate failed.
4. Post-phase random-forest comparison — implemented; data gate failed.
5. Same-landmark incremental Brier comparison, calibration, and paired
   group-bootstrap intervals — implemented; no supported real-data fit to evaluate.

The update features currently count dated trial starts and results postings.
They do not yet extract the biological safety or efficacy content of results.
FDA approval prediction is also not implemented without indication-specific
regulatory labels.

## What is needed to evaluate the original idea

- Review drug identities/aliases and indication equivalence, with a labeled
  sample to measure linkage precision and missed matches.
- Distinguish original development from repurposing, background treatment,
  formulation comparisons and later pharmacokinetic studies.
- Address healthy-volunteer Phase 1 studies that cannot be assigned a disease
  indication without later information; this requires an explicit unit-of-analysis
  decision rather than retroactively inventing an indication.
- Evaluate interval-based handling of partial dates and appropriate follow-up
  methods as prespecified sensitivity analyses.
- Obtain historical protocol/result-availability evidence before claiming true
  prospective baseline prediction.
- Extract interpretable safety/efficacy endpoints before claiming a biological
  evidence update, rather than merely a registry-history update.

## Verification and reproducibility

**118 tests passed**. Syntax and Git whitespace checks passed. Offline CLI tests
verify input immutability, report generation, corruption rejection and model
gates. Performance refactoring produced exactly identical snapshots, timelines,
splits and JSON results on the initial full run before the final source fixes.

Final local outputs:

- [Full report](../data/processed/phase_by_phase_final_2026-11-19/REPORT.md)
- [Quality audit](../data/processed/phase_by_phase_final_2026-11-19/quality_audit.json)
- [Analysis metrics and feasibility](../data/processed/phase_by_phase_final_2026-11-19/analysis_report.json)
- [Execution manifest](../data/processed/phase_by_phase_final_2026-11-19/run_manifest.json)
- [Cohort figure](../data/processed/phase_by_phase_final_2026-11-19/cohort.png)

These data/output links work in the local checkout; generated data are deliberately
Git-ignored and are not included on GitHub. The source files and this summary
are repository documents. Follow the [README commands](README.md#run-it) to
reproduce the outputs. Use a fresh output directory; retain previous runs.
