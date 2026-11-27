# B26 source-only cross-phase candidate-name bridge

**Independent verdict: PASS_REAL_DATA_CHECKS for the bounded source-name audit.** This is a descriptive source-name audit. An earlier same-name registration does not establish clinical exposure, earlier results, molecule/regimen/indication identity or a sponsor program. Every coverage count is retrospective descriptive output, not an authorized prediction feature. No B26 model was fitted, no API was called, and no outcome/result or holdout source was opened. Optional B23/B25 chemical annotations were omitted.

## Scope and frozen provenance

Read before editing: local `AGENTS.md`, `skills/structured-trials/SKILL.md`, execution rules, frozen B26 ledger/prompt, and B24/B25 builder and accepted independent handoffs. Changes are limited to the new B26 module, focused test, this handoff and new ignored `data/processed/b26_*` artifacts. Prior code, README, ledger, source snapshots and previous outputs were not edited. The pre-existing untracked `harness/task_ledger.sqlite` was not a B26 deliverable. These command records are supplied for coordinator ledger entry; builder ownership excludes ledger edits.

Authentication precedes all source row queries:

| Frozen input | SHA-256 |
| --- | --- |
| B24 full-v2 manifest | `f193bf4d65424b415552ac644be20b8591495537ae85923ca2248aaab66318c0` |
| B11a exact-version aliases | `3b22aeca92560c8f21ff30d87e656cc16f429f17d1c8037fa749a958eed4e583` |
| Raw-source inventory manifest | `a1b318aafc861a6948a53d74fbffabd3694e82aa986d8227ddc14187edea2219` |

The run also verifies every one of B24's twelve manifest-listed child/report digests, all twenty inventoried condition-part digests, and the unchanged B18 normalizer module digest. The output manifest records **35 input file hashes**, B26 and B18 code hashes, fixed resource settings and all seventeen semantic output hashes; its own digest is excluded from its contents. Final B26 code SHA-256 is `62582769f75682907f3f4a42df94989005f24da8d29ddbcb7044c2844395422b`. Final output manifest SHA-256 is `981a3820c29c0af99ee70437ab256c89e0898dc18c1c421773dd1f485956ff97`.

Only the five first-public B24 graph tables are queried. The remaining B24 files are hash-verified lineage inputs, not feature sources. Raw conditions are semijoined/joined to exact first-public `(nct_id,nct_version)` **before their values are materialized**. Counts of nonmatching revisions use keys only: 6,144,578 alias rows and 2,514,839 condition rows from other versions of selected NCTs are excluded. The 20 condition parts have 9,618,118 all-version footer rows; 108,097 exact-version rows are selected. No unversioned MeSH or other source table is used.

Raw condition columns contain no independent public-date field. Output conditions carry source file, zero-based file row, source commit and exact-version checkpoint with `exact_version_only_no_independent_public_date`; no separate public-availability date is invented. Arm/intervention canonical provenance fails closed if a known checkpoint lacks an equal, nonmissing child source-public date. Unknown checkpoint trials remain inspectable and cannot link. Aliases keep their parent/date diagnostics separately and never enlarge links. Actual arms, interventions and aliases have zero missing/mismatched source-public dates; aliases have zero orphan parents or parent-written-name mismatches.

## Grains and bounded method

Natural keys are validated before analysis: one first-public row per NCT and exact trial/version, arm/intervention `(NCT,version,ord)`, original assertion ID, edge `(NCT,version,arm ordinal,intervention ordinal)`, alias `(NCT,version,intervention ordinal,other-name ordinal)` and condition `(NCT,version,ord)`. Duplicate/missing keys, version bleed, orphan edges, non-development checkpoints and prohibited result/model/chemical schema fields fail explicitly.

| Output | Grain and purpose |
| --- | --- |
| `trials`, `arms`, `interventions`, `assertions`, `edges` | Five byte-exact B24 copies; original keys, roles, names, raw prose, directional flags, assertion pointers and nested provenance preserved. |
| `aliases`, `conditions` | Separate exact-version raw children; no arm × alias × condition flattening. |
| `alias_summary` | One row per original alias, parent name/key, casefold/trim-only alias collision and date/orphan flags. No alias unification. |
| `intervention_names` | One row per original intervention, unchanged raw data plus B18 canonical DRUG key, exclusions, role/direction/combination flags. Includes unlinked interventions. |
| `name_trials` | One row per canonical name/trial, with original version and contributing intervention ordinals. |
| `name_dates` | One row per name/phase/date with distinct-trial count, cumulative count and earliest source example pointer. |
| `name_summary` | One row per name; phase/trial/raw-name multiplicity, ambiguity and high-fanout summaries. Retrospective audit only. |
| `name_coverage` | One row per later trial/name/prior phase, strict-earlier counts, ties/future/missing-date diagnostics and an inspectable earlier NCT/date pointer. |
| `later_trial_coverage` | One row per later P2/P3 trial, including trials with zero candidate names or coverage; P1/P2 name coverage kept separate. |
| `trial_child_coverage` | Independent per-trial child counts and source absence, without child multiplication. |

B18's existing `normalize_drug_name` is imported unchanged and applied only to canonical DRUG intervention names. It retains whole combination strings and salt/dose text under its existing punctuation normalization. Distinct raw spellings remain visible; its normalization does not verify identity. Alias strings use only separate casefold/trim collision diagnostics. Conditions do not constrain or expand name overlap. Neither control-role annotations nor combination flags silently remove canonical rows from this exploratory denominator.

The resource guard is **2 GiB, two threads, insertion-order preservation disabled, zero temporary spill**. Name/trial and name/phase/date aggregates feed three strict ASOF comparisons, rather than a global intervention-pair expansion. First-public NCT uniqueness plus disjoint phases ensures earlier/later NCTs differ; dates must be strictly earlier. Missing/tied dates cannot link. The five wide graph files are copied without re-sorting, avoiding wide assertion materialization during export. Output row orders are explicit and deterministic. Wall-clock timings are recorded outside the semantic manifest so fresh replay can be byte-identical.

Combination flags are descriptive raw `+`, `/`, `&`, `and`, `plus`, `combination` markers or multiple raw DRUG ordinals in a union arm; they do not parse or adjudicate a regimen. A multi-DRUG flag may reflect directional conflict. Known control roles and unknown/other roles are separate. An intervention may have reciprocal and one-sided edges on different arms, so these flag counts overlap. Source absence and null values remain unknown clinical evidence.

## Observed full-data audit

All frozen source and preflight name counts reproduced without changing inputs or criteria.

| Phase | Trials | Canonical candidate intervention rows | Unlinked candidates | Candidates with one-sided edge | Candidates with reciprocal edge |
| --- | ---: | ---: | ---: | ---: | ---: |
| P1 | 19,343 | 34,168 | 4,254 | 4,070 | 27,180 |
| P2 | 29,704 | 50,105 | 10,785 | 3,174 | 37,326 |
| P3 | 19,576 | 32,765 | 6,492 | 1,980 | 25,141 |
| **Total** | **68,623** | **117,038** | **21,531** | **9,224** | **89,647** |

There are 121,039 arms, 159,113 interventions, 354,917 assertions, 184,256 exact edges, **77,458 aliases** and **108,097 conditions**. Edges retain B24's 170,661 reciprocal / 7,322 intervention-only / 6,273 arm-group-only split. Of all interventions, 17,587 have B18 control/empty-name exclusions and 24,488 are non-DRUG; no raw null/empty canonical names occur in this frozen source, though synthetic fixtures cover them. The 21,531 unlinked canonical candidates remain in the denominator.

The 117,038 candidate source rows aggregate to **111,060 name/trial rows**, **107,129 name/phase/date rows** and **42,844 name keys**. Of those keys, **5,702** appear in at least two phases and **1,599** in all three; **3,624** have multiple raw written-name variants. There are **94 high-fanout names**, using a predeclared descriptive threshold of at least 100 distinct trials. Examples include cyclophosphamide (1,059 trials), cisplatin (957), carboplatin (932), paclitaxel (892) and docetaxel (743). These broad strings are not program identifiers.

| Possible prior-name coverage | Distinct covered later trials | Later-trial denominator |
| --- | ---: | ---: |
| P1 → P2 | **14,631** | 29,704 |
| P1 → P3 | **7,443** | 19,576 |
| P2 → P3 | **9,566** | 19,576 |
| P1 or P2 → P3 union | **10,300** | 19,576 |

Coverage uses existence at later-NCT grain, not multiplied intervention/arm/alias/condition counts. `later_trial_coverage` includes all **49,280 later trials**. `name_coverage` has 111,290 later-name/prior-phase rows. Tied name/trial comparisons excluded from earlier coverage are P1→P2 **798**, P1→P3 **239**, P2→P3 **1,743**; corresponding future comparisons are **690,248**, **249,975**, **626,019**. These are aggregate name/trial comparisons, not distinct later trials. No checkpoint dates are missing in the pinned cohort; missing dates remain tested synthetically.

There are 35,921 alias rows whose casefold/trim string points to more than one canonical name. This diagnostic does not select a preferred parent or merge candidates. Canonical candidate rows include 9,641 possible combination-string rows, 45,268 possible multi-DRUG/direction-conflict rows, 25,198 with a known control role and 7,440 shared between experimental/control roles. Flags overlap and do not measure clinical combination prevalence. There are 44,143 trials without alias children, 23 without condition children, and 14,373 without arm edges; these are source-coverage counts, not negative clinical findings.

## Artifacts, examples and inspection

Final full output: `data/processed/b26_full_2026-11-27_v2`. Fresh builder offline replay: `data/processed/b26_replay_2026-11-27_v2`. Both have fifteen Parquet tables, `examples.json`, `report.json`, and `manifest.json`: **18/18 files byte-identical**. The v1 full/replay outputs are preserved as superseded pre-provenance-guard artifacts. Execution records and inspection scripts/results are in `data/processed/b26_execution_2026-11-27_v1`.

The builder inspection independently recomputed every input/output/code hash, compared the five original graph files byte-for-byte, checked complete alias/condition source multisets with `EXCEPT ALL` in both directions, revalidated keys/dates, reconstructed three coverage totals using phase/name minimum dates, and directly checked distinct prior counts for 30 examples. All passed. Richer curated rows are in execution `inspected_examples.json`; raw text and provenance are also in the complete output tables.

Inspected examples illustrate the boundaries:

- P1→P2: `ketoconazole`, later `NCT00019695` v0 (2007-03-05), has four strictly earlier P1 same-name registrations, including `NCT00238225` (2005-10-13). Its unlinked intervention remains represented.
- P1→P3: `cisplatin`, later `NCT00117572` v0 (2005-07-07), has `NCT00116896` (2005-07-01) as an earlier same-name registration.
- P2→P3: `rituximab`, later `NCT00118209` v0 (2005-07-11), has `NCT00117156` (2005-07-04) as an earlier same-name registration. None of these examples establishes earlier result availability.
- `NCT00506246` preserves separate Propofol ordinals 0/1 and opposing arm assertions. `NCT01170637` / `NCT01176097` preserve genuinely one-sided assignments under B24's written-name audit. This bridge does not adjudicate them.
- `Lucentis`, `Remicade` and `Daytrana` appear in alias collision review with their distinct source parents; they do not enlarge name coverage. The raw `0.9% sodium chloride` family also survives B18 normalization where its written string is not one of B18's explicit control exclusions; role and high-fanout review are not chemical adjudication.

## Commands, failures and repair budget

All commands ran from `phase-by-phase/`, with `PYTHONPATH=src` for Python module/test commands. The ignored `run.py` recorder saves exact argv, environment, exit status, runtime and full combined output in `commands.jsonl` and the named log. Exact failed output is preserved, not summarized away.

| Command | Exit and observed result | Log |
| --- | --- | --- |
| `../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_cross_phase_bridge_b26.py` | Initial exit 1: **11 failed / 17 passed**, one shared DuckDB binder error: `Ambiguous reference to column name "nct_id" (use: "e.nct_id" or "a.nct_id")`. | `focused_initial.log` |
| Same focused command after repair 1 | Exit 0: **28 passed**. Repair uses explicit arm-multiplicity join keys. | `focused_repair1.log` |
| `../.venv/bin/python -m phase_by_phase.cross_phase_bridge_b26 --out data/processed/b26_full_2026-11-27_v1` | Exit 0, 4.237s; superseded after independent temporal probe. | `full_v1.log` |
| `../.venv/bin/python -m phase_by_phase.cross_phase_bridge_b26 --out data/processed/b26_replay_2026-11-27_v1` | Exit 0, 4.003s; pre-repair replay preserved. | `replay_v1.log` |
| `../.venv/bin/python -m pytest -q -p no:cacheprovider tests` before repair 2 | Exit 0: **458 passed**, six existing environment/deprecation warnings. | `project_tests_v1.log` |
| Independent synthetic future-public-date probe | Exit 0 demonstrated semantic failure: P1 checkpoint 2008/source date 2012 contributed to P2 checkpoint 2009. This is **repair 2**, despite the probe command itself succeeding. The canonical/arm provenance guard now fails closed for missing or mismatched source-public dates at known checkpoints; six new cases test both child types. | Independent `b26_eval_2026-11-27_v1/date_probe.log` and `date_probe_repair2.log` |
| Focused command after repair 2 | Exit 0: **34 passed**. | `focused_repair2.log` |
| `../.venv/bin/python -m phase_by_phase.cross_phase_bridge_b26 --out data/processed/b26_full_2026-11-27_v2` | Exit 0, **3.633s**, final full source-only run. | `full_v2.log` |
| `../.venv/bin/python -m phase_by_phase.cross_phase_bridge_b26 --out data/processed/b26_replay_2026-11-27_v2` | Exit 0, **4.426s**, fresh final-code offline replay. | `replay_v2.log` |
| `../.venv/bin/python data/processed/b26_execution_2026-11-27_v1/inspect_artifacts.py` | Exit 0, **18/18 files identical**, source multisets/hashes/keys/dates/counts pass. | `inspection_final.log`, `inspection.json` |
| `../.venv/bin/python -m pytest -q -p no:cacheprovider tests` on final code | Exit 0: **464 passed**, six existing environment/deprecation warnings. | `project_tests_final.log` |
| `../.venv/bin/python harness/check.py` initial and final | Exit 0 / **PASS** both runs. | `harness_v1.log`, `harness_final.log` |

**Two targeted repair rounds used; one remains available.** Independent acceptance is recorded below; no implementation or documentation failure remains. No new linkage policy, clinical identity verification, result evidence, prediction model or API expansion is authorized by these checks.

## Independent acceptance

The independent evaluator issued **PASS_REAL_DATA_CHECKS** after reviewing actual new-file diffs and this handoff, rerunning **34 focused / 464 project tests** and harness **PASS** (all exit 0), independently verifying all 35 input hashes and 17 content-output hashes, and checking complete alias/condition source multisets in both directions. A separate Python/B18 reconstruction matched every candidate source row and name/trial ordinal list. Independent sorted-date/bisect checks matched **all 111,290** coverage rows, including earlier/tied/future counts and distinct-NCT earlier exemplars. The evaluator also checked named phase-pair examples, top-five fanout counts and twelve execution-log references against the actual artifacts; exit 0.

The evaluator's fresh full offline replay replaced socket transports and DNS with functions that raise on use. It exited 0 and reproduced **18/18 files byte-for-byte** at `data/processed/b26_eval_full_offline_replay_2026-11-27_v1`. Independent evidence, exact commands/exits, the initial temporal defect and its successful six-case repair probe are recorded in `data/processed/b26_eval_2026-11-27_v1/INDEPENDENT_EVALUATION.md`, with `inspection_v2.log`, `handoff_review.log`, `replay_comparison.json` and complete test/replay logs alongside it. The independent v1 inspection exited 1 because repair2 had changed the current code hash; that stale-artifact refusal is retained separately and was not a final-v2 failure. The final verdict reports no unresolved implementation or documentation issue and accepts only this source-name audit.
