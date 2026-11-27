# B29 metadata-only Phase 3 label review queue

Builder handoff, 2026-11-27. **Independent evaluation is pending; the builder does not decide acceptance.** No label expansion, clinical annotation, benefit inference, recoverability estimate, model or feature promotion is produced.

The new standalone implementation is `src/phase_by_phase/label_review_queue_b29.py`; focused synthetic tests are `tests/test_label_review_queue_b29.py`. These and this handoff are the only new code/test/document files. Existing code, data, README and coordinator-owned ledger are unchanged. Execution evidence is in ignored `data/processed/b29_execution_2026-11-27_v1/`; the coordinator can copy its command record into the ledger. No source snapshot or prior report was overwritten.

## Source boundary and lineage

Before editing, read `AGENTS.md`, `skills/structured-trials/SKILL.md`, `harness/EXECUTION_RULES.md`, the complete frozen B29 ledger section and builder assignment, and accepted B19/B22 evaluations. Preflight discovery, code/manifest reading, authenticated schema inspection and an explicit metadata-only reason/structural-state query all exited 0. A baseline of 119 existing code/test/document files was saved before implementation; all 119 remain byte-identical, including the ledger and README.

The CLI authenticates both pinned manifests, then both used Parquets, before opening DuckDB or querying source rows. It also checks B22's declared B19 manifest/trial digests. The only source row reads are two explicit column projections **inside DuckDB**, materialized as metadata tables. The complete B22 file is never materialized through Arrow, pandas, Python records or a wildcard source view. Schema discovery used DuckDB `DESCRIBE`, not row/value inspection.

| Used input | SHA-256 |
| --- | --- |
| B22 full-v4 `manifest.json` | `90dbc788896ed5340e3ba7899851ed62feeb1d6b0f27a9f95fc286cc0207235f` |
| B22 `all_target_labels.parquet` | `084681630d86f308347b32f4e940c710f57babc1f9bf07392f9b88326a59987d` |
| B19 full-v1 `manifest.json` | `44303770c8b9db387bb008d215f44bd1a70ef1025d611fe5a5ae01cbf5a37107` |
| B19 `trial_evidence.parquet` | `eef3d0fc1c34b53cd91605c37f3bf81bbc43cff609bf1b0f65a29b7a1529000e` |

`B22_COLUMNS` and `B19_COLUMNS` are exhaustive allowlists, also recorded in `report.json`. B22 contributes NCT, first-public version/checkpoint, selected-result version/date, existing exclusive reason and overlapping uncertainty flags, candidate mapping/type states, exact outcome/analysis pointers and adapter provenance. **B22 proxy class, p strings/numbers/qualifiers and analysis group payloads are excluded.** B19 contributes selected keys/date, primary/source-row/key/analysis counts and structural mapping/contrast/NI/EQ/type/direction states. Parameter/unit families, historical grades, parsed-p summaries, endpoint prose, nested evidence, measurement values and result-child tables are excluded. No B17, raw source, external endpoint or holdout table is opened.

First-public target pointers remain separate from later selected-result pointers. B19 structural fields and its own matched result pointers are populated only on exact `(NCT, selected result version, selected result date)` equality. Missing NCT linkage or version/date mismatches are explicit unknown states with null B19 states and null outcome/analysis pointers. Synthetic tests exercise all three cases; real data has 8,414 exact matches and 11,162 unknown/no-result-pointer rows, with zero mismatches.

An outcome pointer is inherited from authenticated B22 only with exact B19 lineage, one primary outcome, one primary source row, single-primary state and no missing primary key. An analysis pointer additionally needs one analysis and an existing B22 analysis ordinal. No alternate endpoint/analysis is selected. These are **inherited source pointers**, not new checks against child values. Ambiguous/missing pointers remain null with an explicit unknown pointer state. Nullable exact keys remain Parquet `int64`, with a synthetic `2**53+1`-and-larger round-trip check.

No human field is completed: prespecification, multiplicity, comparator/arm map, effect direction, NI/EQ, clinical relevance, reviewer and adjudication date are null in Parquet and blank in CSV. Actual clinical review requires a separately frozen protocol that examines exact source versions and originally registered endpoints. A result-version PRIMARY designation does not establish original prespecification; B17 grades are not ground truth; exact candidate labels do not verify drug identity. NI/EQ is a different estimand, and a small p does not establish benefit. Trial/endpoint/analysis counts describe different, overlapping grains and cannot be added into a clinical eligibility funnel.

## Deterministic sampling

The seed is fixed at **20261127**. Rank NCTs by hexadecimal `SHA256("20261127|" + NCT)`, breaking ties by NCT, and take the first 150 from all 19,576 targets. This is the sole probability-sample component; its uniform-draw probability is `150/19576`. Do not use the combined queue to estimate prevalence.

Remove these 150 NCTs before enrichment. For each of the eight eligible reasons, sort each era bucket (2005–09, 2010–14, 2015–19) by the same SHA/NCT order, then take one from each available bucket in chronological era order, repeating up to 25 cases. Exhausted buckets are skipped. Apply the same era round-robin to up to 25 known-report anchors. Reasons are processed lexically, then anchors; exclusive reasons guarantee cross-reason disjointness. No shortfall is filled from another reason. Enriched and anchor rows carry `probability_sample=false` and null `uniform_draw_probability`.

The metadata ledger includes `inclusion_group` (`not_selected`, `uniform`, `rare_reason`, `known_anchor`), `selection_stratum`, within-stratum `selection_order`, inclusion logic and SHA rank value. The review queue is its selected subset, unique by NCT. CSV array flags are JSON strings; Parquet retains string arrays. Both exports retain source pointers and blank human fields. There are no direct positive/negative labels in either export.

| Component / exclusive reason | Frozen population | Uniform already selected | Additional selected | Shortfall against request |
| --- | ---: | ---: | ---: | ---: |
| Uniform / all targets | 19,576 | — | 150 | 0 |
| analysis_contrast_unverified | 9 | 0 | 9 | 16 |
| analysis_missing_or_multiple | 3,550 | 27 | 25 | 0 |
| arm_mapping_unverified | 301 | 2 | 25 | 0 |
| comparator_role_unverified | 98 | 4 | 25 | 0 |
| noninferiority_comment_requires_review | 542 | 7 | 25 | 0 |
| not_explicit_superiority | 1,200 | 7 | 25 | 0 |
| p_missing | 9 | 0 | 9 | 16 |
| primary_missing_or_multiple | 2,408 | 27 | 25 | 0 |
| Known-report anchors | 297 | 2 | 25 | 0 |

The remaining exclusive reason, `no_posted_primary_result`, has 11,162 targets and is eligible only through the uniform draw (74 selected). All ten exclusive reasons sum to 19,576. Existing frozen B22 counts of 170 positive, 127 negative and 19,279 unknown are inherited context; B29 does not read or recalculate proxy classes. The final queue contains **343 distinct NCTs: 150 uniform + 168 rare-reason + 25 anchors**.

Every 25-case enriched/anchor stratum has era counts 9/8/8. The nine contrast cases have 0/6/3; the nine missing-p cases have 0/3/6. Uniform era counts are 46/56/48. No absent-era cases were invented.

## Executed commands and evidence

All commands ran from `phase-by-phase/`. The ignored recorder `data/processed/b29_execution_2026-11-27_v1/run_command.py` sets `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH=src`, saves complete stdout/stderr, command/exit/timing and child peak RSS in `commands.jsonl`. Commands below are the underlying recorded commands; each exited **0**.

```bash
../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_label_review_queue_b29.py
../.venv/bin/python -m pytest -q -p no:cacheprovider tests
../.venv/bin/python harness/check.py
../.venv/bin/python -m phase_by_phase.label_review_queue_b29 --out data/processed/b29_full_2026-11-27_v1
../.venv/bin/python -m phase_by_phase.label_review_queue_b29 --out data/processed/b29_replay_2026-11-27_v1
../.venv/bin/python data/processed/b29_execution_2026-11-27_v1/review_metadata.py
```

Focused synthetic tests: **31 passed**. Full suite: **583 passed**, five existing DuckDB deprecation warnings and one existing joblib physical-core discovery warning. Harness: **PASS**. The output-directory test was made hermetic after its initial successful run, adding an explicit unignored-output rejection assertion; final focused and full-suite reruns are separately recorded. No implementation failure, failed artifact, targeted repair or unresolved engineering blocker occurred. Targeted repair count: **0 of 3**. Acceptance remains for the independent evaluator.

The actual full run took 1.109 seconds with child peak RSS 280,018,944 bytes; replay took 1.080 seconds, peak RSS 296,386,560 bytes. DuckDB is constrained to `memory_limit=2GiB`, `threads=2`, empty temp directory and `max_temp_directory_size=0B`, so disk spill is disabled. Synthetic tests assert all four runtime settings. No intermediate cross-products are built; Python retrieves only aggregate metadata in the implementation.

The builder's separate read-only review script authenticates inputs and output digests before row queries, uses the same explicit source projection boundary, compares every preserved source field and B19 structural field at exact source keys, checks absent lineage/null pointers, unique keys, queue subset, blank human fields and prohibited columns, and reconstructs sampling independently with Python SHA ordering and era queues. It checks all 119 baseline file hashes. Results are saved in `metadata_review.json` and `metadata_review_v1.log`; all source-field mismatch counts are zero and the independent sampling reconstruction equals the saved queue. This is builder verification, not independent evaluator acceptance.

Dates: target checkpoints span **2005-06-24 through 2019-12-30**; selected results span **2008-10-31 through 2023-12-29**. No selected result is on/before its checkpoint or in 2024+. All 6,006 single-primary outcome pointers are retained; 2,456 also have exact inherited analysis pointers, while 3,550 have unknown analysis pointers. The other 13,570 targets have unknown outcome and analysis pointers. No target p/measurement/prose/child values were queried to establish these metadata facts.

Representative source-keyed queue examples (metadata only; full ten-stratum examples in `metadata_review.json`):

| NCT / component | First-public version / date | Selected result version / date | Outcome / analysis pointers |
| --- | --- | --- | --- |
| NCT00355849 / uniform | 0 / 2006-07-25 | unknown | unknown / unknown |
| NCT00132873 / primary multiplicity | 0 / 2005-08-22 | 4 / 2013-11-25 | unknown / unknown |
| NCT00672854 / analysis multiplicity | 0 / 2008-05-06 | 13 / 2014-08-01 | 0 / unknown |
| NCT02314117 / missing p reason | 0 / 2014-12-10 | 36 / 2018-05-02 | 0 / 0 |
| NCT00598806 / known-report anchor | 0 / 2008-01-23 | 9 / 2017-08-15 | 0 / 0 |

## Artifacts and replay hashes

Fresh ignored output directories:

- `data/processed/b29_full_2026-11-27_v1/`
- `data/processed/b29_replay_2026-11-27_v1/`
- `data/processed/b29_execution_2026-11-27_v1/`

The full and replay directories each contain exactly five files; **all five, including the manifest, are byte-identical**. Output hashes from the authenticated generated manifest:

| Artifact | SHA-256 |
| --- | --- |
| `metadata_ledger.parquet` | `3e70a996a7e027ab8eb28003e9ce0ed3e9f2c67436f64a1096d5a8a627e89fdb` |
| `review_queue.parquet` | `8cc1aa8ffea76b8c5d69d97d5a33b81808d04b20fecbd8c921f99ed3d45527cf` |
| `review_queue.csv` | `da31dca0fb5ba29df05b30883712b64c34a5c7d8301c9404cd8e22d9a7b03bee` |
| `report.json` | `e76443b58fb39d9b9b21319437151d1d27a5580f4c6e5f36c045aa870c8aed9a` |

Implementation SHA-256: `8da66af1b56b58d3be42653d7f57496f507e336cad2695dae7d9d75b93fe8797`. The manifest contains the exact source digests and fixed settings. A new `--out data/processed/b29_*` path is required; existing or unignored output directories are refused. No output path, timestamp or elapsed-time field enters the deterministic data/report/manifest content.
