# B28 independent evaluation — PASS_REAL_DATA_CHECKS

2026-11-27. Supervised builder attempt 1 exited 0 (coordinator-confirmed). This is an independent engineering/data-lineage acceptance of the descriptive arm-link audit, **not** an identity, treatment, efficacy, model, or feature-promotion finding.

## Frozen inputs and source boundary

I read `../AGENTS.md`, `../skills/structured-trials/SKILL.md`, `EXECUTION_RULES.md`, the frozen B28 section of `TASK_LEDGER.md`, `B28_BUILDER_PROMPT.md`, and the accepted B24/B26/B27R evaluations before examining B28. The module is `../src/phase_by_phase/arm_feasibility_b28.py`; its SHA-256 is `aceec3e122b4dd0aea2ab09cb7cf649f759739bb11df80ba53707c32292fb3e4`. The full output manifest SHA-256 is `5f8c689548973883fd3e02e80e14487608f4760a79f2c6518f6aeedbf34b3d53`.

The independently checked predecessor manifest digests are B27R clean `cfb0c06e1f90da5adce0351d95674ce0720b1d70758ef89e9b2530b20e80d68b`, B26 full-v2 `981a3820c29c0af99ee70437ab256c89e0898dc18c1c421773dd1f485956ff97`, and B24 full-v2 `f193bf4d65424b415552ac644be20b8591495537ae85923ca2248aaab66318c0`. Source inspection shows `verify_inputs()` authenticates all three manifests and all seven used child Parquets before DuckDB connection or row query. It projects B27R measurement *presence* and first-public target/prior metadata, not result values; B26 child versions are requested by exact NCT/version; B24 arms/edges/assertions use the same exact version. Output source assertions and conditions are lossless candidate-version subsets (both-direction `EXCEPT ALL` zero missing/extra). No target label-version arm join, target P3 result value, holdout, ChEMBL, NLP, or model access appears in the module. The proxy class is isolated from tier construction and used only for final descriptive grouping; B26 trial/name OR flags are not used to establish an ordinal arm link.

The code enforces `memory_limit='2GiB'`, `threads=2`, and `temp_directory=''` (no spill), with no fallback raising these limits. Same-key reciprocal validity requires both directional assertions, both validity flags, `audit_uncertain IS FALSE`, one relevant experimental arm, and a single-candidate-DRUG regimen. Missing/obsolete/ambiguous intervention or regimen paths are not strict. Controls, combinations, fanout, missing links, one-sided edges, and absent conditions remain sensitivity/uncertainty states, not proof of exposure. The condition strings have no independent publication date; this limitation is explicit in the report.

## Independent execution and counts

All commands below ran from `phase-by-phase/`; exit codes are observed, not builder assertions.

| Check | Command | Exit/result |
| --- | --- | --- |
| Focused | `PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_arm_feasibility_b28.py` | 0; 37 passed |
| Full | `PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m pytest -q -p no:cacheprovider` | 0; 552 passed, 5 existing deprecation warnings |
| Harness | `PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python harness/check.py` | 0; PASS |
| Fresh offline replay | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.arm_feasibility_b28 --out data/processed/b28_eval_full_replay_2026-11-27_v1` | 0; 91 targets, 2,448 original name/prior pairs |
| Byte comparison | `diff -rq data/processed/b28_full_2026-11-27_v1 data/processed/b28_eval_full_replay_2026-11-27_v1` | 0; 13/13 files identical |
| Source reconstruction diagnostic | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python data/processed/b28_execution_2026-11-27_v1/b28_source_check.py data/processed/b28_full_2026-11-27_v1 data/processed/b28_eval_full_replay_2026-11-27_v1` | 0; 1,572 ordinal booleans, 2,448 pair flags and source-key multisets agree |

The last diagnostic is builder-authored auxiliary code, which I inspected; it is supporting cross-check evidence, not the basis for calling this an independent verdict. My direct read-only DuckDB check over `pair_review.parquet` and `ordinal_review.parquet` returned `(2448 pairs, 12 strict pairs, 7 strict targets, 0 tier-1/non-strict, 0 strict/non-tier-1)` and `(1572 ordinal rows, 103 strict ordinals)`, respectively. B27R selected metadata and B28 pair-review have zero missing or extra rows in either-direction `EXCEPT ALL`, so arm-path fanout does not change the 2,448-pair denominator. The output report has 2,235 distinct target/prior pairs, 1,014 prior trials, 97 names, 2,692 ordinal pairs, and 2,399 fully linked arm pairs. Pair tiers total 12 strict, 2,376 explicit control/combination, 10 reciprocal ambiguous, 0 one-sided, and 50 unlinked/unknown. Exclusive target tiers are 7/75/5/0/4. Phase/class denominator strata are P1 negative 63, P1 positive 165, P2 negative 747, P2 positive 1,473; strict strata are 2/0/8/2 in that order. These are descriptive counts, not effect estimates.

I inspected source-keyed examples: strict prasugrel `NCT01560780` ordinal 0 ↔ `NCT00642174` ordinal 0 has reciprocal assertion IDs on both exact-version experimental arms; another prasugrel prior `NCT01107899` is reciprocal but non-strict. Cisplatin `NCT01004978` ↔ `NCT00191815` demonstrates a target experimental/control-arm collision with a missing prior arm; it is not strict. Unlinked denosumab `NCT01077154` ↔ `NCT00293813` retains the missing prior path. These examples support the distinction between exact ordinal evidence and trial/name OR summaries; they do not verify clinical identity.

## Failures and limits

No substantive B28 failure found. Two evaluator command setup errors were corrected without changing source or full/replay artifacts: an initial `sha256sum` used nonexistent `b27r_full_2026-11-27_v1` instead of the pinned `b27r_clean_2026-11-27_v1` (exit 1), and the auxiliary diagnostic initially lacked `PYTHONPATH=src` (exit 1, import error). The builder reported an earlier auxiliary `inspect.py` stdlib-shadowing error and subsequent rename; this was not a module or output repair. The Git status command in my sandbox was unavailable due local Xcode/gitconfig permissions (exit 128), so I did not rely on Git status for this verdict. The diagnostic writes its own ignored `inspection_results.json`; it did not alter code, full output, or source data.

**Verdict: PASS_REAL_DATA_CHECKS** for the frozen B28 descriptive feasibility audit. Strict arm linkage is 12/2,448 name/prior pairs involving 7/91 targets under these exact-version rules. It is not evidence that a normalized name denotes the same molecule/regimen or that prior result presence predicts target outcomes. Any modeling or policy use requires a separately frozen task and evaluation.
