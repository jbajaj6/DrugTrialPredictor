# B30 builder handoff — exact-first-public planned-primary coverage

2026-11-27. Builder implementation and checks completed on attempt 1; **independent evaluator acceptance pending**. No repair rounds, failing commands, or source schema/timing contradictions were encountered. This handoff is not an acceptance verdict. The ledger is unchanged under the builder's explicit scope; the coordinator can record the evidence below.

## Scope and access

New standalone module: `src/phase_by_phase/planned_primary_coverage_b30.py`. New focused tests: `tests/test_planned_primary_coverage_b30.py`. No existing code, source data, previous output, README, or ledger was edited. All generated artifacts are in fresh Git-ignored `data/processed/b30_*` directories.

Before connecting to DuckDB or querying any rows, the module authenticates **19 inputs**: the pinned source inventory, the pinned B29 manifest and queue, and every one of the 16 inventory-declared `primary_outcomes` parts. It checks the exact part-name inventory, source boundary, eight-column schema digest, per-part bytes/footer rows, and 7,967,548 footer-row total. Source schema or B29 key/timing contradictions raise an error rather than change the protocol. No network access is used.

The source view explicitly projects `nct_id,nct_version,ord,measure,time_frame,description,is_obsolete,obsolete_by` and physical file/row identifiers. A key-only audit reads NCT/version keys for the selected NCTs to distinguish missing exact versions from NCTs absent from the child table; other-version planned text is not materialized. The text materialization uses an exact `(nct_id,nct_version)` semijoin against the authenticated B29 first-public keys **inside DuckDB**. Only 452 exact-version planned rows leave that source join. This is a logical projection/materialization boundary, not a claim that Parquet IO excludes every physical byte associated with other rows.

Planned rows preserve all three raw text fields without cleaning, raw ord/version and obsolete flags/pointers, source part and zero-based physical row, part/inventory digests, source commit/table/dataset/license, B29 manifest/queue digests, and B29 checkpoint. Each row states that the checkpoint is a **whole-version association only**; child public availability is not independently dated. The unversioned original-primary history table is never opened. The only source-row inputs are the B29 metadata queue and the authenticated versioned planned-primary parts. No result-child table, later-result wording/value/p field, holdout outcome or model artifact was opened by B30.

Selected-result version/date/outcome/analysis pointers remain unchanged queue metadata in `trial_summary`. They are absent from `planned_primary_rows` and never determine its source keys or ordinal states. No cross-version ordinal equality or automatic text comparison establishes semantic identity. Both tables have null `human_later_result_wording`, `human_prespecification_review`, `human_reviewer`, and `human_review_date` columns.

## Observed output and limits

Full output: `data/processed/b30_full_2026-11-27_v1/`. Fresh replay: `data/processed/b30_replay_2026-11-27_v1/`. Each contains a 343-row `trial_summary` and 452-row `planned_primary_rows`, each as Parquet and CSV, plus `report.json` and `manifest.json`.

| Structural state | Trials | Exact planned rows |
| --- | ---: | ---: |
| Exact NCT/version observed | 329 | 452 |
| NCT observed only at other source versions; exact version not observed | 13 | 0 |
| NCT not observed in this planned-child table | 1 | 0 |
| Total fixed B29 queue | 343 | 452 |

All 452 observed rows have unique, nonnull source ordinals and a nonobsolete source flag with null obsolete pointer. Zero obsolete/unknown/duplicate/null-ordinal cases were observed in this snapshot; synthetic tests exercise them without discarding rows. Of these observed rows, 73 have null time frame and 260 have null description; no measure is null. Missing text remains null. Empty strings, whitespace, Unicode, quotes, and line breaks are preserved rather than normalized.

The 14 zero-row trials have `planned_presence_state=not_observed`. The child table cannot distinguish an absent historical child association from an explicitly empty planned-primary list: **no trial is established as `no_primary_planned`**. Every summary instead has `no_primary_planned_state=unknown_not_assessed`, including observed trials. Zero missing-text counts for zero-row trials count observed source rows only and do not establish complete fields. The sole source-NCT miss is `NCT00134251`, first-public v0. An example exact-version miss is `NCT00118209`, first-public v0, with 463 key-only other-version source rows; none of their text was substituted.

`report.json` gives descriptive structural counts by B29 inclusion group, selection stratum, exclusive reason and era. These reconcile to 343 trials and 452 rows. This enriched queue supports neither population prevalence nor a confidence interval. Coverage, nonobsolete flags, and whole-version association do not prove original prespecification, independent child publication timing, clinical identity, endpoint switching, efficacy, or a recoverable clinical label. A clinical comparison requires separate preregistration and human review.

## Commands and observed exit codes

Commands ran from `phase-by-phase/`. All commands below exited **0**. No targeted repairs were used.

| Check | Exact command | Result |
| --- | --- | --- |
| Focused synthetic | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_planned_primary_coverage_b30.py` | 29 passed in 2.26s |
| Full suite | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 612 passed in 57.44s; five existing Arrow deprecation warnings and one joblib physical-core detection warning |
| Harness | `PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python harness/check.py` | PASS |
| Actual bounded output | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.planned_primary_coverage_b30 --out data/processed/b30_full_2026-11-27_v1` | 343 trials, 452 planned rows |
| Fresh replay | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.planned_primary_coverage_b30 --out data/processed/b30_replay_2026-11-27_v1` | 343 trials, 452 planned rows |
| Byte comparison | `diff -rq data/processed/b30_full_2026-11-27_v1 data/processed/b30_replay_2026-11-27_v1` | All six files byte-identical |
| Independent-query cross-check | `PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python data/processed/b30_checks_2026-11-27_v1/b30_independent_checks.py` | All 19 input and five content-output digests match; source/output multiset differences 0 in each direction; B29/summary metadata differences 0 in each direction; trial counts and blank human fields verified |
| Whitespace check | `git diff --check` | Exit 0; final new-file whitespace checked separately |

Both real runs use DuckDB memory limit 2 GiB, two threads, empty temp directory, and max temp size 0 bytes (no spill). The focused suite checks the actual settings. It also checks exact-version isolation, future-version/out-of-queue text exclusion, forbidden result-column projection, null/duplicate ordinals, obsolete/unknown/conflicting flags, source NCT/version misses, zero rows, raw text and physical provenance, exact int64 result metadata, blank human fields, descriptive reconciliation, invalid timing/key rejection, manifest/queue/first-part/last-part tampering, source schema contradiction, authentication-before-connection, and fresh ignored output refusal rules.

The independent-query script is a **builder cross-check using separately written SQL**, not a separate evaluator verdict. It does not import the B30 module. It independently authenticates inputs before its first row query, makes its own exact-key semijoin, compares all eight source columns plus file/row as multisets, and compares B29 metadata. Its JSON includes all 14 zero-row trial keys and the source-key examples below. No result text is queried for these checks.

## Source-key examples inspected

Source rows below are zero-based physical row numbers, verified by the independent-query comparison. Part names are beneath the inventory's `primary_outcomes/` directory; all are source first-public v0.

| NCT | Planned first-public source | Exact planned content/structure | Separate selected-result metadata |
| --- | --- | --- | --- |
| NCT00132873 | part-00000-of-00016, rows 243852–243853; 2005-08-22 | ord 0 `Adverse experiences`; ord 1 `Vital signs`; time frames/descriptions null | v4, 2013-11-25; outcome/analysis pointers unknown |
| NCT00355849 | part-00000-of-00016, row 489766; 2006-07-25 | one planned measure beginning `To compare in patients who at study entry have type 2 diabetes`; null time frame/description | No result-version/date/pointers |
| NCT00598806 | part-00001-of-00016, row 306970; 2008-01-23 | one planned measure beginning `To evaluate the recurrence rate at 2 years`; time frame `2 years`; description null | v9, 2017-08-15; outcome/analysis ord 0 |
| NCT00672854 | part-00001-of-00016, row 382726; 2008-05-06 | ord 0 planned measure beginning `to determine differences between soybean oil and olive oil-based lipid emulsions`; time frame `2 years` | v13, 2014-08-01; outcome ord 0, analysis unknown |
| NCT02314117 | part-00005-of-00016, row 198997; 2014-12-10 | ord 0 `Progression Free Survival (PFS)`; time frame `Randomization to Radiological Disease Progression or Death from Any Cause (Approximately 42 Months)`; description null | v36, 2018-05-02; outcome/analysis ord 0 |

Matching ordinal values in this table are only metadata coincidences across versions; no semantic comparison or clinical conclusion was performed. Full original planned strings are in the row package and independent-check JSON.

## SHA-256 evidence

The full manifest lists all 19 authenticated inputs. Headline pins remain exactly those in the frozen ledger: inventory `a1b318aafc861a6948a53d74fbffabd3694e82aa986d8227ddc14187edea2219`; B29 manifest `1030acd767d2c032b009200f78e29275673c4b45cad6d0e1f12df92856d8dd99`; B29 queue `8cc1aa8ffea76b8c5d69d97d5a33b81808d04b20fecbd8c921f99ed3d45527cf`.

| Artifact | SHA-256 |
| --- | --- |
| B30 module | `acaec07838388c5b2828ee9a70e4258eef6ae7113878fd914141684cb68cef7a` |
| B30 focused tests | `40e4a6d22e0d8bb28abe7b2da8be1eb0811b14a276bb85d9ca88a7891f7e8b92` |
| Full/replay manifest | `bc78b2f363f599988f9b37f96d75273873bee458b170b764bf9903934a7ab358` |
| trial_summary.parquet | `2cd4b1da9233365a494c3b4a7395b04a71732229feae2ae9d5139147745170e0` |
| trial_summary.csv | `8d25691943ed3695d94176915b429bb65750775aa9d656b7e7c308cb44a64673` |
| planned_primary_rows.parquet | `3eb6c7b71cd7d4c69353d7f7399e55467a36f556db0d1926a3e0adf026e30683` |
| planned_primary_rows.csv | `5ceebcae19904728c81a576e9bb7b8351f258f599dd7aa9efb4d45d5f06d4b14` |
| report.json | `231b537c4ce6bd1da413ca4939485e467fe850c2bd3d5122bd6fb5c8037a85bb` |
| Independent-query script | `83b265e1b31bf1e5e3531b6bf6df53e0432acb27013e763d1589a91207dd8718` |
| Independent-query JSON | `e751e290b44ae7587339308eb9db6d45a4ecc9e2020e75e97887414345c6a7ce` |

Cross-check artifacts are in `data/processed/b30_checks_2026-11-27_v1/`. The handoff and command record are the builder evidence for coordinator/evaluator review, not automatic acceptance or authorization to expand labels.
