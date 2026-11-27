# B24 bidirectional arm–intervention audit: builder handoff

**Builder implementation and development replay complete; independent evaluation pending.** This is a source-assertion audit. Equal written names do not establish the same molecule, dose, formulation, regimen or clinical identity. Union edges can represent directional conflict. B18, its linkage policy, source snapshots, previous outputs, ChEMBL, README and the task ledger were not changed. No model was fitted, and no outcome/result table or 2024+ holdout was opened.

The builder read `AGENTS.md`, the structured-trials skill, execution rules, frozen B24 ledger section/prompt, the B18 README/ledger handoff and manifest, and both B23 handoffs before implementation. The three assigned deliverables are `src/phase_by_phase/arm_link_audit_b24.py`, `tests/test_arm_link_audit_b24.py` and this handoff. All new execution/data artifacts are beneath the already Git-ignored `data/` directory. These command records are provided for the coordinator's ledger; the builder's ownership excludes editing that ledger.

## Inputs and method

Before DuckDB source queries, the module streams and verifies all four SHA-256 values against both the frozen constants and B18's pinned `report.json` metadata. That JSON is a manifest input only; its outcome paths are never opened. The CLI accepts an output directory and optional pilot limit, with no arbitrary source/glob or result-table input.

B15 is projected to **only** `nct_id`, `first_public_nct_version`, `first_public_date`, and `pure_phase`. The frame includes pure `PHASE1/2/3` first-public keys strictly before 2020. Duplicate/missing exact frame keys fail. The pilot takes the first 300 keys ordered by SHA-256 of `20261127|nct_id|version`, with exact-key tie breaks. All protocol reads join the selected exact NCT/version keys. DuckDB is fixed to **2 GiB, two threads, insertion-order preservation disabled and an empty temporary directory (no spill)**. No global all-version join is materialized. A resource failure stops the run; it does not increase the budget or enable disk spill.

`assertions.parquet` retains every original link column and source row multiplicity, plus the complete matched arm/intervention records as nested structs, phase/checkpoint, generated assertion ID, arm role, resolved intervention category/name and explicit missing-ordinal, unresolved, orphan, obsolete/unknown, public-date violation/unknown and unresolved-version flags. Separate arm/intervention tables also retain unlinked children. The assertion ID is a deterministic within-run pointer to original file/row, direction, parent/item ordinal and raw text; it is not a registry identity.

Nonmissing exact `(NCT, version, arm ordinal, intervention ordinal)` keys form distinct edges. Presence of either assertion direction determines reciprocal, intervention-only or arm_group-only classification, without deleting uncertain assertions. Missing-key assertions remain in the assertion/review tables. Every edge retains its contributing assertion IDs. A duplicate arm/intervention ordinal key fails before it can multiply source assertions.

Written-name agreement uses the intervention child's original name at the exact ordinal. The exact-name and Python `casefold().strip()` comparisons are separate outputs. The latter does not remove punctuation, collapse internal whitespace, split a regimen, remove salts/doses or adjudicate identity. Opposite-name agreement on unilateral edges requires the same exact arm and a **different intervention ordinal**. Duplicate ordinals, raw descriptions and both source directions remain reviewable.

Policy comparison first uses resolved, nonobsolete assertions with present exact children and known matching public dates/version flags. Flagged assertions remain in the audit but do not enter policy eligibility. All these flags happen to be zero in this replay; the distinction is exercised synthetically. Policies use intervention-direction, union or reciprocal exact edges. Raw DRUG rows count distinct arm/intervention ordinal edges. B18-normalized candidate rows retain each edge with a nonnull existing B18 name key, excluding that normalizer's placebo/control labels. B18-style primary rows require one distinct normalized candidate in an experimental arm, not shared with a nonexperimental arm. Two raw ordinals with one normalized name can satisfy that descriptive B18 rule; this does not verify one drug. Unlinked B18 fallback exposures are outside these edge-policy counts.

## Full observed counts

All frozen preflight aggregates reproduced without changing sources or criteria.

| Phase | Trials | Reciprocal edges | Intervention-only | Arm_group-only |
| --- | ---: | ---: | ---: | ---: |
| PHASE1 | 19,343 | 57,242 | 3,517 | 2,946 |
| PHASE2 | 29,704 | 69,280 | 2,426 | 2,156 |
| PHASE3 | 19,576 | 44,139 | 1,379 | 1,171 |
| **Total** | **68,623** | **170,661** | **7,322** | **6,273** |

There are **354,917 assertions**, **184,256 exact edges**, **54,250 linked versions**, and **14,373 versions without links**. The complete child tables contain 121,039 arms and 159,113 interventions. All assertion orphan/unresolved/missing/date/obsolete/version flags and corresponding child flags are zero. Unknown flags are retained explicitly; missing values are not converted into negative outcomes.

Of 13,595 unilateral edges, **13,569** have an opposite-direction exact written-name assertion at another ordinal, **16** more agree only after casefold/trim, and **10** have neither. At arm-plus-exact-name grain there are 176,939 groups, including **23 one-sided groups**. Casefold/trim yields 176,925 groups and **ten one-sided arm_group groups**: eight Phase 1, two Phase 2, zero Phase 3. There are 6,957 exact-name arm groups with multiple intervention ordinals. These are descriptive name/ordinal counts, not verified identity or registry-error counts.

| Policy | Raw DRUG rows | Candidate rows | Candidate trials | Primary rows | Primary trials |
| --- | ---: | ---: | ---: | ---: | ---: |
| Intervention | 159,311 | 136,373 | 53,672 | 55,714 | 35,209 |
| Union | 165,420 | 141,852 | 53,672 | 58,973 | 35,208 |
| Reciprocal | 152,218 | 129,992 | 53,672 | 52,555 | 35,557 |

Each policy has 54,250 trials with raw DRUG edges. The 55,714 intervention-policy primary rows and 9,499 Phase 3 primary trials reproduce B18's corresponding counts. The candidate-edge denominator excludes B18's 21,531 no-resolved-link fallback rows: 136,373 + 21,531 = B18's 157,904 candidate exposures. The report additionally breaks down phase, DRUG/non-DRUG, arm role, control sharing and possible multi-DRUG/conflicting-arm rows.

Reciprocal-only eligibility is **non-monotone**: relative to intervention-direction eligibility, **378 trials gain** primary eligibility (P1 152, P2 93, P3 133), while **30 lose** it (17, 9, 4). Net gain is 348 trials. The reciprocal-only Phase 3 count is 9,628. Deleting a competing candidate or control-sharing edge changes the B18 rule. Union loses one Phase 1 primary trial and has the same Phase 2/3 primary trial totals as intervention-direction links. Row counts and trial eligibility therefore answer different questions; none establishes a better clinical linkage policy.

## Artifacts and inspected examples

Final pilot: `data/processed/b24_pilot_2026-11-27_v2` (300 trials: P1 78, P2 123, P3 99; 1,508 assertions, 767 edges). Final full: `data/processed/b24_full_2026-11-27_v2`. Fresh builder replay: `data/processed/b24_full_replay_2026-11-27_v1`. Execution logs, source-multiset inspection script/results and richer curated examples: `data/processed/b24_execution_2026-11-27_v1`.

Each successful output contains ten deterministic Parquet tables: `trials`, `arms`, `interventions`, `assertions`, `edges`, `names_exact`, `names_folded`, `policy_rows`, `trial_policy` and `review`; plus `review_examples.json`, `report.json`, and `manifest.json`. The full review sheet has **14,993 assertion rows** with original keys/provenance, complete child text, blank human adjudication and unknown clinical identity. The first 100 ordered review assertions are also readable as JSON. The manifest pins all four source paths/digests, B18 metadata digest, audit/normalizer code digests and all twelve output-file digests. It excludes its own digest to avoid self-reference.

The additional inspected source assertions are stored in execution `inspected_examples.json`:

- `NCT00506246` v0 arm 1: distinct Propofol ordinals 0/1 illustrate same-written-name opposite-direction assertions. Raw dose/regimen descriptions remain separate.
- `NCT00594503` v0 and `NCT00702923` v0 illustrate casefold/trim-only agreement; no chemical merging is performed.
- `NCT01170637` v0 has genuinely one-sided Ibuprofen/Pseudoephedrine-HCl arm assignments under this written-name rule. `NCT01176097` includes both AZD5658 and Placebo one-sided assertions. “One-sided” describes source assertions, not which one is correct.
- B23's `NCT01223352` v0 arm 0 links distinct ordinals 0 and 1 both written `bosentan`. Union has two raw DRUG ordinals, while B18 normalization has one candidate name. It is a direction/ordinal conflict with unknown clinical interpretation, not proof of a combination.

The builder inspection recomputed all source/output hashes, compared the **complete source multisets in both `EXCEPT ALL` directions** for links/arms/interventions, checked exact cohort/phase totals, edge-key uniqueness, assertion-to-trial membership, preflight aggregates, flags and review identity fields. All passed. The fresh full replay produced **all ten Parquet tables, review examples, report and manifest byte-for-byte identical**. This is builder reproducibility evidence; the independent evaluator must still inspect the diff, rerun checks and a fresh replay, and issue the verdict.

## Commands, failures and repair budget

Commands below run from `phase-by-phase/`. Log names are relative to the execution directory above. Exact command arrays/exits are also recorded in `commands.jsonl`.

| Command | Exit | Evidence |
| --- | ---: | --- |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_arm_link_audit_b24.py` | 1, then 0 | Initial fixture keyword error: 11 passed/1 failed; repair 1: 12 passed. Logs `focused_initial.log`, `focused_repair1.log`. |
| `PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.arm_link_audit_b24 --out data/processed/b24_pilot_2026-11-27_v1 --limit 300` | 0 | Initial pilot; preserved, superseded by final-code v2. `pilot.log`. |
| `PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.arm_link_audit_b24 --out data/processed/b24_full_2026-11-27_v1` | 1 | 2 GiB allocation failure while exporting/sorting assertions; partial directory retained without successful manifest. `full.log`. |
| Focused command above after memory repair | 0 | 12 passed. `focused_repair2.log`. |
| Focused command above with new end-to-end writer/replay test | 1 | New test caught a query of `review` after its table was freed: 12 passed/1 failed. `focused_repair2_writer.log`. |
| Focused command above after repair 3 | 0 | **13 passed**, including complete writer/hash/replay coverage. `focused_repair3.log`. |
| `PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.arm_link_audit_b24 --out data/processed/b24_pilot_2026-11-27_v2 --limit 300` | 0 | Final-code pilot before final full replay. `pilot_v2.log`. |
| `PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.arm_link_audit_b24 --out data/processed/b24_full_2026-11-27_v2` | 0 | Final full outputs. `full_v2.log`. |
| `PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.arm_link_audit_b24 --out data/processed/b24_full_replay_2026-11-27_v1` | 0 | Fresh full replay. `full_replay.log`. |
| `PYTHONPATH=src ../.venv/bin/python data/processed/b24_execution_2026-11-27_v1/inspect_artifacts.py` | 0 | Full source multisets/hashes/preflight/flags/examples. `inspection.log`. |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 0 | Preliminary 405 passed; final **406 passed**, six existing-environment warnings (five DuckDB deprecations, one joblib core detection). `full_tests.log`, `full_tests_final.log`. |
| `../.venv/bin/python harness/check.py` | 0 | Initial and final **PASS**. `harness.log`, `harness_final.log`. |
| Byte comparison of both full manifests and every listed file | 0 | `replay_comparison.json`; all listed bytes identical. |

**Three repair rounds used; no unresolved implementation blocker.** Repair 1 corrected a synthetic helper passing `adapter_link_status` twice and ensured review retains original assertion IDs/raw keys even without an edge. Repair 2 addressed the actual no-spill memory failure by releasing redundant materialized intermediates, using narrow key sorts, freeing each exported table and disabling insertion-order preservation, while retaining 2 GiB/two-thread limits. Repair 3 made the small JSON review export read the newly written review Parquet after its in-memory table was freed; the added complete writer/replay test then passed. Failed/superseded artifacts remain intact. No additional repairs are authorized under this bounded task.

The synthetic cases cover duplicate-name ordinals, casefold distinctions, genuine unilateral labels, non-DRUG links, repeated assertion multisets, multi-DRUG competition, controls/placebo, normalized-name collisions, non-monotone primary eligibility, orphan/missing/unresolved/obsolete/date flags, duplicate child keys, source hash tampering, metadata projection, exact-version/holdout exclusion, resource settings, overwrite refusal and deterministic complete exports.

Passing B24 would authorize only an audited choice set for a future separately registered linkage policy. Independent acceptance is pending; clinical identity, efficacy, historical ChEMBL availability and model performance remain outside this task.
