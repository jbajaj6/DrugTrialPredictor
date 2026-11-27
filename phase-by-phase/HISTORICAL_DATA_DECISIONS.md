# Historical-data decisions and audit contract

Status: **full protocol/results cleaning independently checked; descriptive
first-public design staging complete; prediction labels and models not yet
implemented** (2026-11-25). The
approved source is [Anamnesis Clinical Trials Version History](https://huggingface.co/datasets/anamnesis-data/clinical_trials_history),
compiled from ClinicalTrials.gov under CC BY-NC 4.0. Cite Anamnesis Data and
attribute the underlying records to ClinicalTrials.gov. The full release is
pinned to `8bba65094c7d11a0a66924fab556ba971d456cef`; all 1,135 Parquet
parts have a local SHA-256 source manifest. The older AACT snapshot stays
unchanged as a comparison, not a fallback for unavailable historical fields.

## What a row means

The source `core` table is **one NCT version**, keyed `(nct_id, nct_version)`;
its 4.5 million rows are not 4.5 million independent trials. Versioned child
tables such as `phases`, `interventions`, `conditions`, `arm_groups`, primary
outcome measures, and result analyses join on **both** keys. A source entry's
`ord` or outcome/analysis ordinal is also retained within child tables; a
drug name alone is not a row key. Per-NCT tables are identified from their
actual full-release schema before any join. The public 20-trial sample has an
older schema and cannot certify the newer full release's columns.

The cleaning deliverable is the version index and normalized child
tables for phases, arms, interventions, their links, and reported outcomes.
It preserves raw text and provenance. A separate [first-public design summary](data/processed/anamnesis_first_public_design_full_b12_guidefix_2026-11-25/)
contains 477,191 descriptive NCT rows from exact public versions. It does
**not** create prediction rows, target labels, an eligible model matrix, or a
score. The remaining table below describes a later analysis design, not an
output claimed from this cleaning pass.

Possible later derived tables have separate purposes:

| Table | Grain | Contains | Must not contain |
| --- | --- | --- | --- |
| `version_index` | NCT × public version | Posting date, source version, precision, file/commit provenance | Unposted review failures as public history |
| `protocol_asof` | target NCT × checkpoint | Design and regimen information from exactly one selected public version | Later edits, final enrollment, own results |
| `result_events` | NCT × version × outcome × analysis | First public version containing each reported analysis, raw p text/qualifier, outcome and arm identifiers | An inferred result date from current content alone |
| `target_labels` | target NCT × task | Later completion or reported-primary-p proxy, first known/public date, unknown reason | Input features |
| `prediction_rows` | target NCT × checkpoint × task | As-of features, provenance, split, separate label reference | Post-checkpoint target data in feature columns |
| `audit_funnel` | phase × task × split × exclusion reason | Counts, missingness, changed fields, eligible class counts | A score for an unsupported cell |

Arm/intervention cleaning is **lossless at the row level**, not a single
`drug_name` column. The normalized `phase_membership` table retains every
phase listed for `(nct_id, nct_version)`; `arms_clean` retains every arm and
its source order/type/label/description; `interventions_clean` retains every
intervention and its source order/type/name/description; and
`arm_intervention_links` retains every raw association plus resolved arm and
intervention ordinals, or an explicit unresolved reason. Each table retains
`(nct_id, nct_version)` and source row provenance. A phase is attached to the
trial **version** rather than arbitrarily to one arm; mixed-phase versions
remain mixed-phase until a documented analysis stratum is chosen. These child
tables may have many rows per trial version and must never be joined naively
into the one-row prediction table, where they would multiply observations.
Instead, an audited derived summary supplies arm/regimen features while the
full child tables remain available for inspection and later NLP.

Cross-trial linkage is a separate layer: `drug_candidates` stores normalized
names and retained raw names/aliases without claiming verified chemical
identity; `intervention_drug_links` maps each intervention instance to zero,
one or several candidate drugs with an ambiguity reason; and
`candidate_program_links` connects trial versions across phases by candidate
drug **and indication**, with source NCTs, version dates, linkage rule and
confidence/status. This is how a Phase 1 arm can be related to a Phase 2 arm
without collapsing either arm, drug, intervention, or trial into one field.
One drug may appear in multiple interventions and arms; one combination arm
may contain multiple drugs. Unresolved links remain unresolved, never forced.

The stored row must carry `source_commit`, `feature_nct_version`,
`feature_post_date`, `checkpoint_date`, `label_version`, `label_available_date`,
and explicit missingness/precision flags. A reviewable CSV can flatten the
prediction rows, but raw and versioned Parquet remain unchanged and Git-ignored.

## Time and leakage rules

1. For a **registration** checkpoint, use the earliest publicly posted version
   of the target trial. The checkpoint is no earlier than its recorded start and
   that posting date. For a later checkpoint, choose the latest public target
   version whose `last_update_post_date <= checkpoint_date`; tie-break by
   `nct_version`. A null posting date means review failure, not public data.
2. Do not keep a target whose own terminal outcome or results were already
   public by that checkpoint. Exclude obsolete IDs and report their count.
3. Use the selected target version's protocol: phase, allocation, masking,
   intervention model, planned/then-reported enrollment **type**, arms,
   interventions, planned outcomes, conditions and eligibility. Never use its
   later final status, why-stopped field, final enrollment, own p-value, or
   post-checkpoint site footprint as a launch feature.
4. Preserve month/year precision. A normalized first-of-month date is an
   encoding, not proof an event happened on that day. For ordering, use interval
   bounds; ambiguous same-month comparisons remain unknown.
5. Earlier-phase evidence comes only from **other NCTs** linked by an auditable
   candidate drug/indication rule. A public arm requires the result-containing
   version to have posted by the target checkpoint. The separate 200-day arm
   is an **unverified sponsor-knowledge sensitivity scenario**, never a
   leakage-free public prediction.
6. Sponsor history uses other NCTs. A prior terminal outcome counts only if a
   terminal version was public strictly before the target checkpoint. Exact
   sponsor names are candidate identities, not corporate lineage proof.
7. Pre-2024 development target rows are read separately from sealed 2024+
   outcomes. Training (2005–15) labels must be available before 2016;
   validation (2016–19) labels before 2024. The **final evaluation window is
   provisional**: many 2024+ starts will not have enough follow-up by the
   archive cutoff. Before fitting, audit outcome maturity using keys/dates and
   choose a fixed later eligible test cohort without looking at scores. No
   sealed outcome is used for feature decisions, tuning, or debugging.

## Questions and labels

**Completion** is a broad one-NCT-per-phase question. A label is known only
when a later public version supports a terminal state and the existing
conservative ACTUAL completion/date-consistency rule. `COMPLETED` is positive;
supported `TERMINATED`/`WITHDRAWN` is negative. Ongoing trials, unclear date
order, or reversed status histories remain unknown/censored. A reported
p-value is **not** required for this task. The pilot must report how many
terminal trials the conservative date rule excludes; it must not silently
convert them to failures or change the rule after seeing scores.

**Reported primary statistical significance** is separate and only defined
for completed trials with an interpretable primary analysis. Join
`results_outcome_measures` to `results_outcome_analyses` on
`(nct_id, nct_version, outcome_ord)`, retain each `analysis_ord`, raw `p_value`,
qualifier and comment, and identify the **first public version that actually
contains** the determinate analysis. The minimum interpretable primary p<.05
is a proxy, not proof of endpoint success, favorable effect, multiplicity
control, or clinical benefit. Missing/ambiguous p remains unknown, not zero.

For each pure Phase 1, 2, and 3 target, compare fixed feature blocks on the
**same eligible target rows**: prevalence; versioned design; + regimen/design
complexity; + dated sponsor history; + public earlier-phase structured
evidence. Phase 1 has no earlier phase; Phase 2 may use Phase 1; Phase 3 may
use Phase 1/2. NIH funding, pre-start public attention, and science/drug
context are candidates only if separate source timestamps and coverage pass
audit. NLP of report wording is a later, separately authorized scope; it is
excluded by the current project execution contract.

The **complete 79-table source download** must retain text-bearing fields,
including titles, summaries, eligibility criteria, intervention and arm
descriptions, planned outcome wording, result comments, and document/reference
metadata where present. Preserve original captured text and its
`(nct_id, nct_version, last_update_post_date)` provenance in the ignored raw
source; do not overwrite it with cleaned tokens or embeddings. A later NLP
pipeline must select text by the same as-of version rule and separately audit
whether a field is registry text, a posted results description, or merely a
link/metadata for an external paper. No NLP features are fitted in B11.

## Regimen and other feature decisions

The versioned intervention-to-arm link, not a count of intervention names,
should establish whether a drug is experimental or comparator and whether an
arm has one or several active agents. Derive arm count, active/comparator arm
count, single-versus-combination indicator, drug/biologic type, and count of
planned primary outcomes only when links are unambiguous. Preserve unknown
for unresolved arm mapping. Dose, schedule, and eligibility restrictiveness
may be prose-only; do not pretend they are structured fields. Earlier-trial
effect sizes, denominators, participant flow, and adverse events are future
candidate features only after their version/date and treatment-to-comparator
mapping pass audit. Event counts must not be confused with affected people.

## Checks before any score

- Full-release commit, exact file inventory, downloaded bytes and SHA-256;
  full schema must be inspected rather than inferred from the older sample.
- Stratified 2005–19 pilot across phases, years, registration lag and
  result/no-result states; count first-public-version coverage and field
  changes versus latest versions. The 20-trial public sample is only a schema
  smoke test and cannot establish these rates.
- Unique `(nct_id, checkpoint, task)` rows; child joins cannot multiply target
  rows; source version/date for every input; no future/self-result features;
  no sealed target outcomes loaded into development.
- Separate completion and significance funnels by phase and period, including
  unknown/censored reasons and positive/negative counts. No score if a cell is
  single-class or below the predeclared support gate.
- Fit all imputers, encoders, clipping and model tuning on training data only.
  Compare ROC-AUC, average precision and Brier on identical validation rows;
  use grouped uncertainty for linked drug programs. A higher AUC is not an
  individual success probability or evidence of causation.

The full pinned release is downloaded and byte-inventoried: 79 tables,
1,135 Parquet files, 4,496,043 `core` versions of 613,411 NCTs. The
cleaning-only result adapter has produced 37 versioned public pre-2024 result
tables (78,479,244 child rows). The full phase/arm/intervention/link/alias
cleaner has produced five versioned tables: 3,808,945 phase entries, 8,217,346
arms, 9,732,541 interventions, 26,033,535 links, and 12,992,016 aliases.
Independent evaluation of those five full outputs passed: 203 tests, matching
source/output hashes and row counts, and zero exact-key or text-preservation
mismatches across 60,784,383 protocol child rows. Other
non-results tables remain available in the immutable raw
archive, not yet normalized. No historical prediction table, label, model, or
score is claimed. Executed commands and outcomes belong in the
[task ledger](harness/TASK_LEDGER.md) and README.
