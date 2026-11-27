# B29 independent evaluation — PASS_REAL_DATA_CHECKS

2026-11-27. Supervised builder attempt 1 exited 0 (coordinator-confirmed). **Verdict: PASS_REAL_DATA_CHECKS for a metadata-only human review queue**, not for expanded labels, clinical review, benefit, recoverability, modeling, or holdout use. No substantive B29 implementation failure was found.

I read `../AGENTS.md`, `../skills/structured-trials/SKILL.md`, `EXECUTION_RULES.md`, the frozen B29 section of `TASK_LEDGER.md`, `B29_BUILDER_PROMPT.md`, accepted B19/B22 evaluations, the entire B29 module/tests/handoff, and the actual full artifacts. I did not edit builder code, tests, source or previous outputs.

## Access and source provenance

The module `../src/phase_by_phase/label_review_queue_b29.py` authenticates the B22 and B19 manifests and their two used Parquets **before** connecting to DuckDB or querying source rows, and verifies B22's declared B19 manifest/trial lineage. Direct SHA-256 checks returned B22 manifest `90dbc788896ed5340e3ba7899851ed62feeb1d6b0f27a9f95fc286cc0207235f`, B22 `all_target_labels.parquet` `084681630d86f308347b32f4e940c710f57babc1f9bf07392f9b88326a59987d`, B19 manifest `44303770c8b9db387bb008d215f44bd1a70ef1025d611fe5a5ae01cbf5a37107`, and B19 `trial_evidence.parquet` `eef3d0fc1c34b53cd91605c37f3bf81bbc43cff609bf1b0f65a29b7a1529000e`. Module SHA-256 is `8da66af1b56b58d3be42653d7f57496f507e336cad2695dae7d9d75b93fe8797`; full output manifest SHA-256 is `1030acd767d2c032b009200f78e29275673c4b45cad6d0e1f12df92856d8dd99`.

The only source-row reads are explicit `SELECT` allowlists projected *inside DuckDB* from those two authenticated Parquets. The module does not materialize the complete B22 file via Arrow/pandas/Python, use `SELECT *` on a source file, or read p raw/numeric/qualifier, measurement value, nested analysis evidence, endpoint prose, target result-child, 2024+ holdout or model inputs. The B19 projection contains only trial-level structural counts/states, not nested evidence or values. The B22 proxy class is not read or exported; the exclusive *reason* is preserved. Output Parquet schema contains none of `p_value_raw`, `p_value`, `p_numeric`, `analysis_evidence`, `measurement_value` or `label_proxy_class`. The implementation sets 2 GiB, two threads, empty temp directory and zero spill.

First-public target NCT/version/date and later selected-result version/date are separate. B19 fields and inherited B22 outcome/analysis pointers are exposed only for exact NCT + selected result version + result date; missing/mismatched lineage remains unknown/null. My authenticated projected-source comparison gave B22 metadata `EXCEPT ALL` **0 missing/0 extra** over all allowed fields, B19 exact-lineage structural-state mismatch **0**, exact-lineage classification mismatch **0**, and unexpected nonnull B19/pointer fields on unknown lineage **0**. The actual ledger has 8,414 exact matches and 11,162 no-result-pointer unknowns; no mismatch happened in this snapshot. The absence of observed mismatches does not weaken the synthetic mismatch test. The B19 historical `PRIMARY` designation and inherited pointers do not prove original prespecification; no alternative endpoint or smallest p was chosen.

## Independently executed checks

All commands ran from `phase-by-phase/`; these are evaluator runs, not builder self-reports.

| Check | Command | Observed result |
| --- | --- | --- |
| Focused | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_label_review_queue_b29.py` | Exit 0; 31 passed |
| Full | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | Exit 0; 583 passed, five existing deprecation warnings |
| Harness | `PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python harness/check.py` | Exit 0; PASS |
| Fresh replay | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.label_review_queue_b29 --out data/processed/b29_eval_replay_2026-11-27_v1` | Exit 0; 19,576 targets, 343 queue rows |
| Byte comparison | `diff -rq data/processed/b29_full_2026-11-27_v1 data/processed/b29_eval_replay_2026-11-27_v1` | Exit 0; all five files byte-identical |

Direct rehash of all four full content artifacts matched the generated manifest: ledger `3e70a996a7e027ab8eb28003e9ce0ed3e9f2c67436f64a1096d5a8a627e89fdb`, queue Parquet `8cc1aa8ffea76b8c5d69d97d5a33b81808d04b20fecbd8c921f99ed3d45527cf`, queue CSV `da31dca0fb5ba29df05b30883712b64c34a5c7d8301c9404cd8e22d9a7b03bee`, and report `e76443b58fb39d9b9b21319437151d1d27a5580f4c6e5f36c045aa870c8aed9a`.

The metadata ledger has **19,576 rows/unique NCTs**. Its exclusive reasons independently count 11,162 no posted primary; 2,408 primary missing/multiple; 3,550 analysis missing/multiple; 1,200 not explicit superiority; 542 NI-comment review; 301 arm mapping; 98 comparator role; nine contrast unverified; nine p missing; and 297 determinate-report anchors. These sum to 19,576 without assigning new labels. The queue has **343 unique NCTs**: 150 uniform SHA-ranked, 168 disjoint rare-reason cases (25 each for six larger strata, nine each for the two nine-case strata), and 25 known anchors. My separate Python SHA256 and era-round-robin reconstruction from the output metadata exactly reproduced all 150 uniform and 193 enriched/anchor NCTs in order. Queue human-adjudication fields are all null; no direct positive/negative label is present.

Source-keyed metadata examples checked in `review_queue.parquet`: `NCT00355849` uniform has first-public v0/date 2006-07-25 and no result pointer; `NCT00132873` primary-multiplicity has first-public v0 and result v4/date 2013-11-25 but unknown endpoint/analysis pointers; `NCT00672854` analysis-multiplicity retains outcome ordinal 0 but unknown analysis; `NCT02314117` p-missing and `NCT00598806` anchor retain exact inherited outcome/analysis ordinal 0. These are pointers for future human review, not examination of result values.

## Exact failures and interpretation limit

Two evaluator probe setup errors were corrected without changing source, code or outputs: macOS `shasum` failed under sandboxed Perl/dyld (exit 134), and an initial ad hoc DuckDB `CREATE VIEW ... read_parquet(?)` was not preparable (exit 1). A first lineage diagnostic showed 11,162 apparent mismatches because it compared SQL `NULL` to `FALSE`; correcting to `coalesce(...,false)` yielded **0**. These are evaluator-command failures, not builder failures.

The frozen protocol calls the fixed-seed SHA-ranked 150 a probability-sample component and records nominal `150/19576` inclusion probability. The actual selection is deterministic conditional on seed `20261127`; a design-based prevalence standard error or confidence interval would require a justified randomized seed/design assumption not established here. The combined 343-case queue is deliberately enriched and must never be used as a prevalence sample. No prevalence, recoverability rate or CI is produced here. This qualification does not change the frozen selection algorithm or the queue acceptance.

Passing B29 authorizes only this preparatory metadata queue. Clinical adjudication must be separately preregistered and inspect exact source versions and originally registered endpoints with human reviewers. Missing/ambiguous results remain unknown; B17 grading, p<.05, NI/EQ flags and exact candidate names are not efficacy or clinical-identity ground truth.
