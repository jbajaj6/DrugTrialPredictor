# B22 independent evaluation — 2026-11-27

**Verdict: PASS_REAL_DATA_CHECKS for the development-only reported-superiority-p proxy audit. No model is estimable or authorized by this verdict.** A positive proxy is a reported primary superiority analysis with a p interval wholly below 0.05; it is not a favorable treatment effect, clinical efficacy, completion, or FDA approval.

## Scope and repair record

I independently read the fixed [B22 ledger criteria](./TASK_LEDGER.md), [builder assignment](./B22_BUILDER_PROMPT.md), [execution rules](./EXECUTION_RULES.md), [structured-trials skill](../skills/structured-trials/SKILL.md), implementation, focused tests, handoff, and generated pilot/full outputs. I did not edit the builder's code, tests, criteria, or prior artifacts.

My initial full-v1 review **rejected** the artifact: `all_target_labels.parquet` and `determinate_group_arm_evidence.parquet` serialized nullable `nct_version`, `outcome_ord`, and `analysis_ord` as Arrow `double`. That violates exact integer-key preservation even if the observed ordinals are small. The builder's targeted repair creates nullable pandas `Int64` columns directly from original record integers before writing. The corrected focused tests include a `2**53 + 1` key/arm-ordinal Parquet round trip. I verified that the full-v4 and independent-replay Arrow schemas now encode those keys as `int64` (and the pair evidence encodes `arm_ord` as `int64`). The v1 failure remains a recorded failed candidate, not a passing run.

## Commands and observed exits

Commands ran from `phase-by-phase/` in the project virtual environment:

| Command | Exit and evidence |
| --- | --- |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_reported_superiority_b22.py` | 0; **34 passed** |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 0; **393 passed**, five pre-existing DuckDB deprecation warnings |
| `../.venv/bin/python harness/check.py` | 0; **PASS** |
| `PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.reported_superiority_b22 --out data/processed/b22_e22_independent_replay_2026-11-27_v1` | 0; fresh ignored full development replay |

Evaluator-only ad hoc inspection commands initially had two shell/SQL errors: a source-hash probe treated manifest labels as file paths (exit 1), and one joined unknown analysis rows to determinate pair rows, giving a misleading combined count (exit 0 but discarded). Corrected explicit-path hashing and separate-key joins exited 0. These were evaluator probe mistakes, not builder-code failures.

## Independent artifact checks

- Builder [full-v4 report](../data/processed/b22_full_2026-11-27_v4/report.json) and [independent replay](../data/processed/b22_e22_independent_replay_2026-11-27_v1/report.json) are byte-identical. Their code hash, seven pinned input hashes, and **all five output hashes** match; each manifest's output hashes match the files on disk. The corrected [pilot-v4 report](../data/processed/b22_pilot_2026-11-27_v4/report.json) has 1,000 unique targets and three determinate labels, with integer exact-key schemas.
- [All-target labels](../data/processed/b22_full_2026-11-27_v4/all_target_labels.parquet): **19,576 rows and 19,576 unique NCTs**, 170 positive, 127 negative, 19,279 unknown. No checkpoint falls outside 2005–2019; no nonnull selected result date is on/before its checkpoint or in 2024+. All nullable exact source-key columns are Arrow `int64`.
- [Exact analysis evidence](../data/processed/b22_full_2026-11-27_v4/exact_analysis_evidence.parquet): 2,456 unique referenced rows, each joining to an exact target NCT/version/outcome/analysis key; zero raw-vs-selected posting-date or p-string mismatches. [Determinate group/arm evidence](../data/processed/b22_full_2026-11-27_v4/determinate_group_arm_evidence.parquet): 594 rows, exactly two distinct group rows for each of 297 determinate analyses, with one experimental and one explicit active/placebo comparator role per analysis. No orphan determinate group rows.
- Independent SQL checked every known label against its raw qualifier and numeric bound: **zero** positive/negative interval violations, superiority/arm-role gate violations, or accepted noninferiority-comment conflicts. The exact B15, B19, and B17 manifest/data hashes match the pinned files. The module uses B15 checkpoints and pinned B19/B17 pre-2024 result evidence to create **labels only**; it fits no predictor or model and does not place target results in earlier-phase features. B17 child-date guarding and independent output checks found no 2024+ result values. This is a logical data-access check, not a claim about physical Parquet row-group bytes.

Representative real rows inspected: NCT00145470 version 15, posted 2019-09-16, `=0.0257` → proxy 1; NCT00118209 version 513, posted 2020-04-17, `=0.6519` → proxy 0; NCT00116805 version 19, posted 2010-05-19, `<0.001` → **unknown** because noninferiority/equivalence evidence and a comment require review. These illustrate the statistical-test proxy, not whether the treatment helped.

## Class support and scientific limits

Known labels by **result-public year** (positive/negative) are: 2017 8/11; 2018 21/25; 2019 32/25; 2020 38/18; 2021 27/13; 2022 24/20; 2023 20/15. There are **zero known labels public before 2016**. The descriptive rolling-cutoff report gives 2018 training 19 (8/11) and 2019 training 65 (29/36); these are not verified linked-program cohorts and fall below the preregistered 100-training support gate. The 2019 validation set has only 25 known labels (20/5), below the 50-validation and ten-per-class gates. Thus **no random-forest or gradient-boosting result, AUC, calibration, or Phase 1/2-to-Phase 3 inference is supported** by B22.

Most trials remain unknown because results, one unambiguous primary analysis, explicit superiority, or candidate arm mapping are missing. Exact arm-label matches are candidate mappings, not verified drug/indication identity. The proxy does not read effect direction, size, safety or approval, and a significant p-value can reflect an unfavorable effect. A later task must establish trustworthy program linkage and enough chronologically available labels before modeling.
