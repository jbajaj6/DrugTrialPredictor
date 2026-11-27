# B28 builder handoff — exact-ordinal arm feasibility

Builder execution is complete; **independent scientific acceptance is outstanding**. The frozen denominator is preserved: **91 Phase 3 targets, 2,448 candidate-name/prior rows**, 2,235 distinct target/prior trial pairs, 1,014 prior trials and 97 normalized names. There is no denominator discrepancy. The implemented strict tier covers **12 rows and 7/91 targets (7.7%)**, with 5 proxy-negative and 2 proxy-positive targets. These are descriptive exposure-feasibility counts, not verified clinical identities or useful prediction features.

Only `src/phase_by_phase/arm_feasibility_b28.py`, `tests/test_arm_feasibility_b28.py`, this handoff, and new ignored `data/processed/b28_*` artifacts were created. The ledger, README, old code, source snapshots and previous results were not edited. The frozen B28 ledger, local AGENTS, structured-trials skill, execution rules and accepted B24/B26/B27R independent evaluations were read before implementation. The coordinator retains ledger ownership; this handoff records the builder's commands and failure instead of changing the ledger.

**Construction and interpretation.** The CLI checks the three frozen manifest hashes and every used child digest **before creating a DuckDB connection or querying rows**. Ten authenticated inputs comprise three manifests and seven Parquet children: B27R `candidate_pairs`; B26 `trials`, `intervention_names`, `conditions`; B24 `arms`, `edges`, `assertions`. The output manifest lists exact relative paths and digests. The source manifests are pinned to:

| Source | Manifest SHA-256 |
| --- | --- |
| B27R clean-v1 | `cfb0c06e1f90da5adce0351d95674ce0720b1d70758ef89e9b2530b20e80d68b` |
| B26 full-v2 | `981a3820c29c0af99ee70437ab256c89e0898dc18c1c421773dd1f485956ff97` |
| B24 full-v2 | `f193bf4d65424b415552ac644be20b8591495537ae85923ca2248aaab66318c0` |

B27R rows are selected solely by `asof_current_primary_measurement IS TRUE`. Target/prior first-public versions, dates, canonical name and ordinal lists identify the requests. B27R trial/name OR summaries are not projected into exposure construction. Proxy classes are isolated in a separate table, joined only for final descriptive counts. No target label-version arm join, target Phase 3 result value, raw result child, 2024+ holdout, chemical/API source, NLP or real-data modeling was used. The requested full suite includes existing synthetic model-component tests.

Candidate trial/version semijoins precede child-value materialization. Both sides use exact `(NCT, first-public version, candidate_key, intervention ordinal)` requests and exact `(NCT, version, intervention ordinal, arm ordinal)` B24 edges. Arm roles come from the actual joined B24 arm. Regimen counts include **all union-edge intervention ordinals on that particular arm**, including other names and B18 control exclusions, rather than only the matched drug. Raw names, raw-name equality, canonical key, source public dates, arm/intervention ordinals, direction booleans, assertion IDs, source records and ambiguity flags survive in review outputs. Aliases are not read or expanded.

The explicit strict implementation requires one linked arm for the exact ordinal, that arm experimental, a reciprocal **same-key** edge with both `has_*` and both `valid_*` booleans true and `audit_uncertain=false`, exactly one raw DRUG ordinal and one normalized candidate DRUG in that arm, no uncertain/missing regimen edge, no raw combination-string flag, and nonobsolete/resolved source intervention metadata. Repeated DRUG ordinals, even with the same normalized string, remain regimen ambiguity. A control or second arm linked to that same ordinal prevents uniqueness; a different ordinal's control arm does not automatically poison this ordinal. Missing/mismatched arm/intervention source-public dates fail closed. Trial/version/date/phase discrepancies and duplicate natural keys also fail closed. Unknown or absent links remain review rows, not negative outcomes.

Tier precedence is deterministic: **strict; explicit control/combination; reciprocal ambiguous; one-sided; unlinked/unknown**. The lowest available rank wins for each original pair and then each distinct target. All overlapping flags remain separately available. High fanout never changes tier. This precedence means a pair with both a control/combination path and an absent link can have rank 2 while retaining its absent-link flag. A reciprocal path alone does not establish the correct regimen or identity.

Exact, case-sensitive condition-string overlap is computed only from nonobsolete, nonempty conditions at the same first-public versions. It is unknown if either set is absent. These raw conditions have **no independently observed public date**; their association with a checkpoint is exact-version provenance only. Neither condition overlap nor fanout <100 gates the main strict tier. Raw combination markers are inherited per intervention string from the pinned B26 audit; they are a conservative heuristic, not chemical or regimen adjudication.

**Observed counts.** The 91 targets retain B27R's 50 positive / 41 negative reported-p proxy classes. The table below distinguishes pair support from exclusive target precedence; target support across pair tiers overlaps.

| Tier | Original name/prior rows | Distinct targets supporting a pair in tier | Targets with this best tier |
| --- | ---: | ---: | ---: |
| Strict reciprocal single-DRUG experimental, both sides | 12 | 7 | 7 |
| Explicit control/combination | 2,376 | 80 | 75 |
| Reciprocal but ambiguous | 10 | 8 | 5 |
| One-sided | 0 | 0 | 0 |
| Unlinked/unknown | 50 | 14 | 4 |
| Total exclusive assignments | 2,448 | Do not sum | 91 |

No pair wins the one-sided tier, but **207 rows / 30 targets** have an overlapping one-sided flag. Similarly, **1,588 rows / 65 targets** have an unlinked path, despite only 50 rows winning rank 5. There are no missing requested canonical intervention children in this real output. Unknown arm-role review paths comprise 33 `OTHER` and 859 null-role rows; these are paths, not distinct trials.

| Prior phase | B22 proxy class | Denominator rows / targets | Strict rows / targets |
| --- | --- | ---: | ---: |
| Phase 1 | Negative (0) | 63 / 22 | 2 / 2 |
| Phase 1 | Positive (1) | 165 / 28 | 0 / 0 |
| Phase 2 | Negative (0) | 747 / 38 | 8 / 5 |
| Phase 2 | Positive (1) | 1,473 / 49 | 2 / 2 |

Targets can appear in both prior-phase groups. Full tier and sensitivity cross-tabs by prior phase and proxy class, with distinct targets, original name/prior pairs, target/prior trial pairs, names, prior trials, ordinal pairs and arm pairs, are in `report.json`. Empty strata are represented as empty arrays, not evidence of a new negative label.

| Overlapping descriptor/sensitivity | Original rows | Distinct targets |
| --- | ---: | ---: |
| Actual joined control role somewhere in the pair | 2,212 | 68 |
| Actual arm multi-DRUG or per-ordinal combination string | 2,206 | 69 |
| At least one exact raw-name match | 1,375 | 79 |
| Fanout >=100 | 2,236 | 47 |
| Exact condition-string overlap | 97 | 25 |
| Strict and fanout <100 | 7 | 5 |
| Strict and condition overlap | 1 | 1 |
| Strict, fanout <100 and condition overlap | 1 | 1 |

There are 2,351 condition-mismatch rows and zero condition-unknown rows in this input. Missing conditions remain supported as unknown by synthetic tests. The main strict result remains 12/7 regardless of those sensitivities. The preliminary 17-pair/13-target OR diagnostic was not an acceptance target, denominator, eligibility rule or source of strict flags. Its policy differs from these exact-ordinal uniqueness/regimen checks; the numerical difference alone is not an estimate of clinical linkage overstatement or understatement.

**Outputs and determinism.** Full output is `data/processed/b28_full_2026-11-27_v1/`; a fresh child-process run into a separate path is `data/processed/b28_replay_2026-11-27_v1/`. All **13/13 files match byte-for-byte**. Each export has a deterministic explicit ordering and ZSTD Parquet compression. The manifest excludes its own digest and output-directory-dependent information. DuckDB uses **2 GiB, two threads, disabled insertion-order preservation, empty temp directory / no spill**. No fallback increases those limits.

| Export | Rows / contents |
| --- | ---: |
| `target_review.parquet` | 91 |
| `pair_review.parquet` | 2,448 |
| `ordinal_review.parquet` | 1,572 relevant side-specific ordinal records |
| `ordinal_pairs.parquet` | 2,692 |
| `arm_review.parquet` | 1,892, including absent-link placeholders |
| `arm_pairs.parquet` | 5,178, including absent-link placeholders |
| `arm_regimens.parquet` | 1,055 |
| `conditions.parquet` | 1,910 |
| `source_assertions.parquet` | 4,451 |
| `proxy_classes.parquet` | 91; final descriptive strata only |
| `report.json`, `examples.json`, `manifest.json` | Counts, source-keyed examples, hashes/settings |

There are **2,399 distinct fully linked arm pairs** among the 5,178 outer-join paths. These paths must not be counted as additional targets. Counts in a pair-tier/sensitivity stratum describe all paths belonging to those original pairs; `path_tiers` separately restricts the arm paths by their own tier.

Final module SHA-256: `aceec3e122b4dd0aea2ab09cb7cf649f759739bb11df80ba53707c32292fb3e4`.

Full/replay manifest SHA-256: `5f8c689548973883fd3e02e80e14487608f4760a79f2c6518f6aeedbf34b3d53`.

**Commands, exits and preserved failure.** Commands ran from `phase-by-phase/`. The execution wrapper is `data/processed/b28_execution_2026-11-27_v1/run.py`; it records the exact argv, working directory, UTC start/end, runtime, exit code, and unabridged stdout/stderr in separate files. It sets `PYTHONPATH=src` and `PYTHONDONTWRITEBYTECODE=1` for every child. Each command below was invoked as `../.venv/bin/python data/processed/b28_execution_2026-11-27_v1/run.py RECORD COMMAND...` with the record and command shown. These are builder checks, not evaluator acceptance.

| Record | Exact child command | Exit / observation |
| --- | --- | --- |
| `focused_v1` | `../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_arm_feasibility_b28.py` | 0; 37 passed |
| `full_v1` | `../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 0; 552 passed, 6 warnings |
| `harness_v1` | `../.venv/bin/python harness/check.py` | 0; PASS |
| `real_v1` | `../.venv/bin/python -m phase_by_phase.arm_feasibility_b28 --out data/processed/b28_full_2026-11-27_v1` | 0; 91 targets / 2,448 rows; 1.619 s |
| `replay_v1` | `../.venv/bin/python -m phase_by_phase.arm_feasibility_b28 --out data/processed/b28_replay_2026-11-27_v1` | 0; same counts; 1.649 s |
| `inspection_v1` | `../.venv/bin/python data/processed/b28_execution_2026-11-27_v1/inspect.py data/processed/b28_full_2026-11-27_v1 data/processed/b28_replay_2026-11-27_v1` | **1**; helper shadowed stdlib `inspect`, causing `AttributeError: partially initialized module 'inspect' has no attribute 'getmro'`; failed before data access |
| `inspection_r1` | `../.venv/bin/python data/processed/b28_execution_2026-11-27_v1/b28_source_check.py data/processed/b28_full_2026-11-27_v1 data/processed/b28_replay_2026-11-27_v1` | 0; reconstruction/hash/multiset checks below |
| `summarize_v1` | `../.venv/bin/python data/processed/b28_execution_2026-11-27_v1/b28_summarize.py` | 0; authenticated-output counts and unilateral examples |

The full-suite warnings were five existing DuckDB `fetch_record_batch()` deprecations and one existing joblib physical-core-detection warning. Focused tests cover same-name different ordinals, different-arm directional assertions, one-sided edges, control collision, multiple DRUG ordinals, alias nonexpansion, condition mismatch/absence, raw-name inequality, public-date null/future values, first-public version bleed, duplicate rejection, missing links, class isolation, hash failure and resource settings.

One targeted auxiliary repair round was used; **no implementation or test repair was needed**. The failed helper is preserved at `data/processed/b28_execution_2026-11-27_v1/failed_round1/inspect.py`, with `inspection_v1.json/.stdout/.stderr` untouched. Repair commands, each exit 0, were:

```sh
mkdir -p data/processed/b28_execution_2026-11-27_v1/failed_round1
mv data/processed/b28_execution_2026-11-27_v1/inspect.py data/processed/b28_execution_2026-11-27_v1/failed_round1/inspect.py
cp data/processed/b28_execution_2026-11-27_v1/failed_round1/inspect.py data/processed/b28_execution_2026-11-27_v1/b28_source_check.py
```

Renaming removed the stdlib shadow; the same helper body then passed. Both full/replay outputs predate the helper repair and were left unchanged. There were no failed audit output directories or unresolved execution failures. Preflight consisted of read-only `pwd`, `rg --files`, `rg -n`, `cat`, `sed`, `ls`, and `git status --short` over the instructions, frozen ledger, accepted evaluations, predecessor source, manifest JSON and harness. All exited 0; the initial Git status was clean. No exploratory source-table query preceded authentication.

**Separate builder reconstruction and inspected examples.** The renamed helper authenticates all ten inputs before any row query and then independently reconstructs from the B27R metadata projection, B26 first-public canonical ordinals, and B24 exact edges/arms using Python dictionaries. It does not call the module's `load`, `build`, `validate`, or tier-construction functions. It agrees on **all 1,572 ordinal strict booleans**, independently reaggregates all 2,448 pair strict flags, and checks B27R-to-output pair-key multisets in both directions. It also finds zero missing/extra rows in both-direction `EXCEPT ALL` comparisons for candidate-restricted B24 assertions and B26 conditions. It verifies ten input hashes, code hash, twelve content-output hashes and all thirteen full/replay file hashes. This is a second builder verification path, not an independent evaluator or an OS syscall trace.

Evidence is in `inspection_results.json`, `inspection_r1.stdout`, `handoff_counts.json` and `summarize_v1.stdout` under the execution directory. Source-keyed examples include:

- **Strict:** target `NCT01560780` v0, checkpoint 2012-03-22, prasugrel ordinal 0 / arm 0, paired with Phase 2 `NCT00642174` v0, first-public 2008-03-24, ordinal 0 / arm 0. Both are reciprocal experimental paths; B24 assertion IDs are target `[97102,97104]`, prior `[8438,8440]`. Raw `Prasugrel` versus `prasugrel` differs; conditions do not overlap. Those descriptors do not remove it from the strict tier.
- **Same name, different prior support:** `NCT01560780` v0 paired with `NCT01107899` v0 prasugrel ordinal 1 / arm 2 has reciprocal experimental evidence but remains ambiguous rather than strict. `NCT00356135` v0 prasugrel ordinal 0 has no first-public arm edge and remains an unknown path.
- **Other-ordinal reciprocity is insufficient:** `NCT00609518` v0 dexamethasone arm 1 has ordinal 4 `arm_group_only`, assertion `[5426]`, valid flags `(false,true)`; ordinal 5 is `intervention_only`, assertion `[5434]`, flags `(true,false)`. Both have other-ordinal exact-name opposite-direction evidence, both have `strict_exposed=false`, and the actual arm contains three DRUG ordinals. `NCT00613626` v0 cisplatin ordinals 0/3 similarly have opposite one-sided evidence on actual active-comparator arm 1.
- **Condition sensitivity:** strict target `NCT03237325` v0 SGX942 paired with Phase 2 `NCT02013050` v0 is the sole strict pair with exact condition overlap; name fanout is 2. Requiring that descriptor would describe 1 target rather than the main 7, without establishing indication identity.

Scientific limits remain substantial: result **presence** is not a usable effect, exact strings are candidate identities, reciprocal source assertions do not verify molecule/dose/formulation/regimen, arm `EXPERIMENTAL` does not establish benefit, and condition equality or low fanout does not validate an indication/program. Unknowns were not made negative, and no result/holdout/model policy was changed. Independent evaluation must inspect the diff, exact source-key joins, dates, proxy support, hashes and output provenance before accepting even these descriptive findings.
