# B30 independent evaluation — PASS_REAL_DATA_CHECKS

2026-11-27. Supervised builder attempt 1 exited 0 (coordinator-confirmed). **Verdict: PASS_REAL_DATA_CHECKS for exact-first-public planned-primary coverage only.** This does not establish original prespecification, child-field publication timing, endpoint switching, clinical labels, benefit, or model readiness. No substantive B30 failure or repair round was found.

I read `../AGENTS.md`, `../skills/structured-trials/SKILL.md`, `EXECUTION_RULES.md`, the frozen B30 ledger section, `B30_BUILDER_PROMPT.md`, B29's accepted independent evaluation, the entire B30 module, focused tests, builder handoff, and actual artifacts. I did not edit builder code, tests, previous outputs, source or ledger.

## Access, authentication and scientific boundary

The module `../src/phase_by_phase/planned_primary_coverage_b30.py` calls `verify_inputs()` before DuckDB connection or any row query. It authenticates **19 inputs**: the frozen full source inventory, B29 manifest and queue, and all **16** inventory-declared `primary_outcomes` parts. It checks part names, bytes, Arrow schema digest, footer row counts and 7,967,548-row footer total. The frozen headline SHA-256 values are inventory `a1b318aafc861a6948a53d74fbffabd3694e82aa986d8227ddc14187edea2219`, B29 manifest `1030acd767d2c032b009200f78e29275673c4b45cad6d0e1f12df92856d8dd99`, and B29 queue `8cc1aa8ffea76b8c5d69d97d5a33b81808d04b20fecbd8c921f99ed3d45527cf`. Current B30 module SHA-256 is `acaec07838388c5b2828ee9a70e4258eef6ae7113878fd914141684cb68cef7a`.

Source inspection found only the allowed eight versioned planned-primary columns plus physical filename/row number projected inside DuckDB. A key-only NCT/version audit distinguishes missing exact versions; the text-bearing table is created only through an exact B29 `(nct_id,target_first_public_version)` semijoin inside DuckDB. B29 result pointers remain metadata in the trial summary and are neither source join keys nor planned-row fields. No `history_original_primary_outcomes` timing source, target result-child/prose/p/measurement, 2024+ holdout, chemical source, NLP or model path appears. The source child has no independent public date: the B29 checkpoint is marked as a **whole-version association**, not proof that a particular field was independently public then. The implementation uses 2 GiB, two threads and zero spill.

## Evaluator commands and independent source checks

All commands ran from `phase-by-phase/`; exits below are evaluator observations.

| Check | Command | Result |
| --- | --- | --- |
| Focused | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_planned_primary_coverage_b30.py` | Exit 0; 29 passed |
| Full | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | Exit 0; 612 passed, five existing deprecation warnings |
| Harness | `PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python harness/check.py` | Exit 0; PASS |
| Fresh offline replay | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.planned_primary_coverage_b30 --out data/processed/b30_eval_replay_2026-11-27_v1` | Exit 0; 343 trials, 452 planned rows |
| Byte comparison | `diff -rq data/processed/b30_full_2026-11-27_v1 data/processed/b30_eval_replay_2026-11-27_v1` | Exit 0; all six files identical |

My separate read-only DuckDB check, after `verify_inputs()` completed, semijoined all 16 source parts to the B29 exact NCT/version keys and compared the eight raw fields **plus physical source file/row** against `planned_primary_rows.parquet` in both directions. It found **452 source rows, 0 missing, 0 extra, 0 wrong-version rows**. A separate `EXCEPT ALL` comparison of every B29 queue metadata field to `trial_summary.parquet` found **0 missing and 0 extra**. The summary has 343 rows/343 unique NCTs, its planned-row counts sum to 452, and 14 trials have zero exact-version rows. Those 14 remain `not_observed`/`unknown_not_assessed`: 13 have the NCT only at other source versions; one NCT is absent from the planned-child table. No row is called `no_primary_planned`. All 452 observed rows are unique nonnull source ordinals with `nonobsolete_source_flag`; this is an observed snapshot property, not an assumption about absent/obsolete/duplicate rows. All four human-review fields are null in both tables.

Source-key examples checked directly from the output: `NCT00132873` first-public v0 has planned ordinals 0/1 at physical rows 243852/243853 (`Adverse experiences`, `Vital signs`) while its later result is v4; `NCT00355849` v0 has one planned row at physical row 489766 and no result pointer; `NCT00598806` v0 row 306970 has a two-year time frame while its later result is v9; `NCT02314117` v0 row 198997 has `Progression Free Survival (PFS)` while its later result is v36. Ordinal equality across first-public and result versions is not semantic identity. I did not inspect target result content.

The full output manifest SHA-256 is `bc78b2f363f599988f9b37f96d75273873bee458b170b764bf9903934a7ab358`. It lists all 19 authenticated inputs; my direct rehash matched all five content artifacts: `trial_summary.parquet` `2cd4b1da9233365a494c3b4a7395b04a71732229feae2ae9d5139147745170e0`, `trial_summary.csv` `8d25691943ed3695d94176915b429bb65750775aa9d656b7e7c308cb44a64673`, `planned_primary_rows.parquet` `3eb6c7b71cd7d4c69353d7f7399e55467a36f556db0d1926a3e0adf026e30683`, `planned_primary_rows.csv` `5ceebcae19904728c81a576e9bb7b8351f258f599dd7aa9efb4d45d5f06d4b14`, and `report.json` `231b537c4ce6bd1da413ca4939485e467fe850c2bd3d5122bd6fb5c8037a85bb`.

No evaluator command failed in this B30 audit. The builder's separate cross-check is supporting evidence only; this verdict rests on independently rerun checks and the direct source-key/multiset reconstruction above. The enriched 343-case queue cannot support population prevalence or a confidence interval. Acceptance authorizes only this inspectable planned-text package; any planned-versus-reported or clinical interpretation requires a separately frozen human-review protocol.
