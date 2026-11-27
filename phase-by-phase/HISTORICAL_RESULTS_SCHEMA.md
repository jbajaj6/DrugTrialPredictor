# Historical results-cleaning schema

Status (2026-11-25): **cleaning only**. The full gated Anamnesis archive was
downloaded and the 37 results tables were cleaned and independently audited:
78,479,244 public pre-2024 versioned result child rows. The older,
nonrepresentative 20-trial public sample was used only for early join checks;
full-release counts are in the [README](README.md) and
[task ledger](harness/TASK_LEDGER.md). The cleaner neither derives a success
label nor fits a prediction model. See
[`historical_results_adapter.py`](src/phase_by_phase/historical_results_adapter.py)
and its synthetic [tests](tests/test_historical_results_adapter.py).

## The shape of the data

One `core` row represents one historical **version** of one trial, not one
drug, arm, or independent trial. Every cleaned results table preserves all
source columns and has `(nct_id, nct_version)` plus:

| Column | Meaning |
| --- | --- |
| `adapter_version_public_date` | `core.last_update_post_date` for **that same version**, not an inferred day of clinical observation or first result posting. |
| `adapter_core_is_obsolete` | Whether the source's core record marks this version obsolete. Versions are flagged, not silently removed. |
| `adapter_source_file` | Exact input Parquet part. |
| `adapter_source_commit`, `adapter_source_table` | Immutable source revision and original source table. |

The output has **one Parquet table per `results_*` source table**. It does
not flatten multiple arms, outcome measures, analyses, or repeated versions
into a single row. Source ordinals and IDs remain intact. Join child rows on
`(nct_id, nct_version)` **plus the relevant ordinals**; never on a drug label
or NCT alone. The cleaner retains the original free text verbatim in each
table; NLP preprocessing is out of scope.

The current development cleaning output contains only versions whose core
record has a non-null public posting date **before 2024-01-01**. Later and
unposted source rows are left in the immutable raw archive, not read into
the development output. The output manifest reports source footer row counts
and eligible row counts so exclusions are visible. Exclusions are split into
missing matching core version, matching core with null/unposted date, and
matching core posted in 2024 or later; a pilot selection separately reports
unselected NCT rows. This key/date-only audit does not inspect later result
payloads. This is a development
boundary, not a statement that 2024+ data do not exist.

## Result categories retained

| Category | Tables and grain | Key content retained |
| --- | --- | --- |
| Outcome definitions | `results_outcome_measures`: NCT/version/outcome ordinal; `results_outcome_classes`, `results_outcome_categories` | Primary/secondary designation, title, full description, population, reporting status, time frame, units, measurement/dispersion type. |
| Outcome groups | `results_outcome_groups`: NCT/version/outcome ordinal/group ID | Original result-group label and description. This is a **reported-results group**, not automatically the same entity as a protocol arm. |
| Outcome values | `results_outcome_measurements`, `results_outcome_denoms`, `results_outcome_denom_counts`, `results_outcome_class_denoms`, `results_outcome_class_denom_counts` | Per-group values, spread, bounds, comments, denominators and unit text; class/category/measurement ordinals stay separate. |
| Statistical analyses | `results_outcome_analyses`, `results_outcome_analysis_groups` | One analysis ordinal per outcome, raw p-value string and comment/qualifier, comparison groups, statistical method/comment, confidence intervals, effect estimate, and noninferiority text. **No p-value is interpreted as a label during cleaning.** |
| Participant flow | `results_pflow`, `results_pflow_periods`, `results_pflow_groups`, `results_pflow_milestones`, `results_pflow_milestone_achievements`, `results_pflow_drop_withdraws`, `results_pflow_drop_withdraw_reasons` | Preassignment and recruitment prose; periods, flow-group labels, milestone and withdrawal categories, counts and comments. |
| Adverse events | `results_adverse_events`, `results_adverse_event_groups`, `results_adverse_serious_events`, `results_adverse_serious_event_stats`, `results_adverse_other_events`, `results_adverse_other_event_stats` | Event terms, organ systems, notes, time frames, safety-group labels, `num_events`, `num_affected`, and `num_at_risk` as **distinct** fields. They must not be summed as though they mean the same thing. |
| Baseline characteristics | `results_baseline`, `results_baseline_groups`, `results_baseline_measures`, `results_baseline_measurements` and their class/category/denominator/count child tables | Population description, baseline group text, measure labels, units, values and denominators. These are reported results, not original trial-design inputs. |
| Results caveats | `results_more_info` | Source limitations/caveats and other available result-disclosure text. |

All 37 `results_*` tables present in the public sample are emitted, including
the nested denominator and class tables not individually spelled out above.
The generated `column_guide.csv` lists every actual source/adapter column
for each table, and `manifest.json` has counts, source hashes, output hashes,
duplicate natural-key groups, and unresolved parent-reference counts. Full
release schema/coverage still require their own audit; the public sample's
older schema cannot certify the full source.

## How results relate to arms and phases

The protocol side has separate versioned phase, arm, intervention and
arm-intervention link tables. The results side has **outcome**, participant-flow,
baseline and adverse-event **group IDs**. A result group may correspond to
one protocol arm, combine arms, or use a modified analysis population. There
is no honest universal join based on title text. Future arm-to-result-group
mapping must preserve zero, one or multiple candidates and an ambiguity
reason; this cleaner does **not** assert that mapping.

Likewise, a Phase 1 trial and a Phase 2 trial do not share a registry key.
Cross-phase drug/indication linkage is a separate candidate-identity layer,
not created by these results tables. The cleaned result rows remain available
to attach to that layer later without losing the original observations.

## Executed sample check

The pinned public sample (`8f7ea755c8e5af34c5ac948a71064b0a35b7951b`)
produced **37 separate cleaned result tables and 33,464 eligible pre-2024
result rows**. For illustration: 717 outcome-measure rows, 549 statistical
analysis rows, 1,478 outcome-group rows, 2,919 outcome-measurement rows,
47 participant-flow overview rows, and 5,181 serious-event statistic rows.
Across all 37 tables, the sample has 114,930 source rows: 33,464 eligible
public pre-2024 rows, 81,466 rows posted in 2024 or later, zero unposted
core-version rows, and zero missing-core rows. These counts reflect repeated
historical versions, not independent patients or trials.
Those are repeated **versioned records across 20 sample NCTs**, not counts of
independent trials. The sample cannot establish project-wide sample size,
label support, or model performance.

Run the cleaning-only command after the full archive is authenticated and
downloaded, substituting an unused output path and its pinned full commit:

```sh
PYTHONPATH=phase-by-phase/src .venv/bin/python -m phase_by_phase.historical_results_adapter \
  --source phase-by-phase/data/raw/anamnesis/full_8bba6509_2026-11-25 \
  --commit 8bba65094c7d11a0a66924fab556ba971d456cef \
  --out phase-by-phase/data/processed/anamnesis_results_full_NEW_RUN
```

The command refuses to overwrite an existing output directory. All raw and
generated Parquet stays Git-ignored. Cite Anamnesis Data's
[dataset card](https://huggingface.co/datasets/anamnesis-data/clinical_trials_history)
and attribute the underlying records to ClinicalTrials.gov; the dataset is
CC BY-NC 4.0 and commercial use requires separate permission.
