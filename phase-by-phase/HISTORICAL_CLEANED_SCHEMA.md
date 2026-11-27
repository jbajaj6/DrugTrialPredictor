# Historical cleaned-data structure

**Status (2026-11-25):** the pinned full release is downloaded and all 79 raw
tables are preserved locally. The 37 `results_*` tables have been cleaned for
publicly posted, pre-2024 versions (78,479,244 versioned child rows), with a
full row-count and relationship audit. Full streaming normalization of phase,
arm, intervention, arm-link, and alias tables passed independent full-source
evaluation. The remaining non-results tables are preserved as raw Parquet, not
yet claimed as normalized outputs. The older public 20-trial sample has a
different schema. A separate first-public descriptive design summary now
contains 477,191 NCT rows; it does not replace these detailed tables. No
prediction table, target label, or model is produced in this pass.

## Descriptive first-public summary

The [B12 summary](data/processed/anamnesis_first_public_design_full_b12_guidefix_2026-11-25/first_public_design_summary.parquet)
has one row per NCT's earliest archived public pre-2024 version, with its
exact version key, public date, source provenance, safe design fields,
estimated-only enrollment, and phase/arm/intervention/link/alias counts and
missingness. The [column guide](data/processed/anamnesis_first_public_design_full_b12_guidefix_2026-11-25/column_guide.csv)
lists every output column. The child rows and original text remain in the
separate detailed tables below. The summary deliberately has no status,
reported results, actual enrollment, target or NLP features. It is a staging
view, not an eligible model cohort or a per-arm outcome table.

## Keys and relationships

```text
trial (nct_id)
  └─ public record version (nct_id, nct_version, last_update_post_date)
       ├─ phase_membership (one row per listed phase)
       ├─ arms_clean (one row per arm)
       ├─ interventions_clean (one row per intervention)
       ├─ intervention_aliases_clean (one row per source alias)
       ├─ arm_intervention_links (one row per registry association)
       ├─ planned primary / secondary / other outcomes (separate source tables)
       └─ results_* (outcomes, groups, analyses, participant flow,
                     baseline characteristics, adverse events)
```

The public posting date belongs to the **whole version**. `nct_id` alone is
not a safe join: it would mix a 2016 arm with a 2022 result. Every child row
keeps its source columns, original text, NCT/version key, and source-file/commit
provenance. Relationship checks report unresolved references, while the arm
link table also carries row-level resolution flags. The raw
Parquet is immutable and retained separately. A source ordinal or group ID
is an *intra-version* identifier, not a stable drug ID across trials.

## Categories retained

| Category | Row grain | Important fields and text retained | Why separate? |
| --- | --- | --- | --- |
| Trial/version (`core`, raw) | NCT × version | Public post date; titles; summary; detailed description; eligibility criteria; study design, sponsor, dates and date precision; status and results metadata | A later version may revise every one of these. Status/results are not launch inputs. |
| Phase membership | NCT × version × phase entry | Raw phase label and source ordinal where supplied | A trial may say `PHASE1/PHASE2`; it is not automatically two independent trials. |
| Arms | NCT × version × arm ordinal | Arm label, type (`EXPERIMENTAL`, `PLACEBO_COMPARATOR`, etc.), full description | One trial has multiple treatment/control groups. |
| Interventions | NCT × version × intervention ordinal | Name, type (`DRUG`, `BIOLOGICAL`, device, procedure, etc.), full description | One arm may receive multiple interventions, and one intervention may appear in several arms. |
| Intervention aliases | NCT × version × intervention ordinal × alias ordinal | Additional intervention names in the original source | Candidate names for future chemical/entity linkage, not verified molecular identities. |
| Arm–intervention links | NCT × version × source association | Original link labels/ordinals, resolved references when unique, or explicit missing/ambiguous status | A name match is not sufficient proof of regimen assignment. |
| Planned outcomes | NCT × version × outcome ordinal | Primary/secondary/other measure wording, description, time frame | Protocol outcomes are distinct from later measured results. |
| Reported outcome measures | NCT × version × outcome ordinal | Primary/secondary type, title, description, population, time frame, units, denominator and reporting status | A trial may report many outcomes; this is not a single trial-level p-value. |
| Outcome analyses | NCT × version × outcome ordinal × analysis ordinal | Statistical method, raw p-value and comment, confidence interval, estimate, noninferiority and other analysis text | Multiple analyses can refer to one outcome; raw p-value text is preserved, not silently coerced. |
| Outcome groups/measurements | NCT × version × outcome/group/class/category/measurement IDs | Group title/description, numeric values, spread, limits and comments | Connects a measured value to the reported group; not necessarily the protocol arm. |
| Participant flow | NCT × version × period/group/milestone/reason IDs | Recruitment and pre-assignment text; counts entering, completing, dropping/withdrawing; reasons/comments | Flow counts and reasons must not be mistaken for treatment effects. |
| Baseline characteristics | NCT × version × measure/group/class/category IDs | Baseline demographic/clinical measure text, units, denominators and values | These describe recruited participants, often posted after the trial began. |
| Adverse events | NCT × version × event/group IDs | Serious/other event terms, organ systems, notes, assessed groups, people affected/at risk, event counts | Event counts and people affected differ; safety results are post-trial information. |
| Results context | NCT × version | Limitations/caveats and other posted-results descriptions | Keeps interpretation text for later analysis without using it as an early feature. |
| Other registry text and links | NCT × version × source row | Conditions, keywords, aliases, references/citations, document metadata, IPD information, locations and contacts | Retained in the raw 79-table archive for later dated text work; document metadata is not the document body. |

In the downloaded public sample, `core` has 741 versions of 20 NCTs;
`arm_groups` has 2,348 rows, `interventions` 2,593,
`intervention_arm_links` 4,159, `results_outcome_measures` 1,660, and
`results_outcome_analyses` 1,275. **These are sample counts only**, not
cohort counts or evidence of full-release cleaning.

**Full-release verified counts:** `core` has 4,496,043 versions of 613,411
NCTs. The result cleaner retains 78,479,244 pre-2024 public-version rows
across 37 `results_*` tables; it excludes 13,001,670 unposted rows and
32,078,655 2024+ posted rows from development-clean outputs while keeping
all of them in raw. The 15-NCT pilot retains 185 phase rows, 208 arms, 405
interventions, 566 arm–intervention links, and 9,261 result rows. These are
versioned child rows, not independent trials. Even pre-2024 result content
could post **after** an individual future prediction checkpoint, so later
analysis must apply another as-of gate.

The full phase/arm/intervention/alias adapter reports 3,808,945 phase rows,
8,217,346 arms, 9,732,541 interventions, 26,033,535 arm–intervention links,
and 12,992,016 aliases. It reports zero missing core-version references or
duplicate ordinal keys, and resolves all arm links and aliases by the source's
exact versioned ordinals. **Resolution of a registry ordinal is not clinical
verification of a chemical identity.** These five outputs retain all source
dates, including 2024+ protocol versions; their later use as model inputs
will require an explicit pre-checkpoint filter. Independent full checks passed:
all 60,784,383 protocol child rows match source counts and order-independent
full-row hashes; exact-version/date joins, 133 source hashes and six output
hashes match. The code passed 203 tests and the project harness.

## Drug and cross-phase identity

The regimen is **arm → intervention(s)** in a particular trial version. A
separate candidate-drug identity layer is needed to connect that regimen to
another trial/phase. Normalized intervention names and aliases can suggest a
candidate; they do not prove the same chemical, dose, indication, or sponsor
program. A combination arm can link to several candidates. Ambiguous or
missing candidate links remain unresolved. No verified cross-phase drug
graph is claimed in the current cleaned outputs.

The full 79-table schema has **no structured chemical identifier, SMILES,
InChI, dose, route, or regimen field**. Intervention names, alternate names,
descriptions, arm descriptions, and MeSH intervention terms are retained as
source text for later candidate linkage. A molecular descriptor would require
a separate, dated external chemical source and identity audit.

## Text retained for later NLP

Keep original title, brief/detailed summary, eligibility, arm and intervention
descriptions, planned outcome wording, results outcome/group/analysis comments,
participant-flow explanations, adverse-event notes, limitations/caveats, and
reference/document metadata **with the version and public date**. Do not
tokenize, embed, replace, or pre-summarize those fields now. The registry
archive does not imply full journal articles or the bodies of uploaded
documents are included; only actual source fields are retained.

## Cleaning checks before claiming completion

1. Pin and hash the full gated source; inventory all tables and compare each
   schema with the adapter requirements.
2. Preserve source row counts within the declared public, pre-2024 scope;
   report every orphan, duplicate ordinal and ambiguous arm link.
3. Compare source and cleaned text on sampled NCT/version/ordinal rows.
4. Audit public posting dates, obsolete markers, date precision and changed
   fields across versions. Do not infer that a null public date was available.
5. Independently rerun tests and a full-source replay. A synthetic fixture or
   20-trial sample cannot establish full-data completion.

See the [source decision](HISTORICAL_DATA_DECISIONS.md) and
[task ledger](harness/TASK_LEDGER.md) for executed versus pending work.
