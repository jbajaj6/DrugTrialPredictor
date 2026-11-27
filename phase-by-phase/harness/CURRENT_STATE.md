# Current verified project state

Last meaningful checkpoint: **B31 repaired v2 accepted, 2026-11-27**.
Scientific-code checkpoint: Git commit `245d800` on `leo/giannis`.
H32 adds recovery instructions only; it does not change that scientific state.
Its [independent policy/harness review](H32_INDEPENDENT_EVALUATION.md) passed;
the state/policy files are now required by the harness entry point.

## Final objective and remaining route

Determine whether design, sponsor history and already-available earlier-phase
evidence improve prediction of phase-specific completion and reported primary
statistical significance. The current difficult subquestion is earlier Phase
1/2 evidence → later Phase 3 outcome. Completion, reported p<.05, beneficial
effect and FDA approval are different targets, not interchangeable labels.

Remaining route: define and audit endpoint adjudication and drug-identity
verification → assess eligible time/group-disjoint label support → preregister
supported feature/model comparisons → evaluate on development data → freeze
and use the final holdout only under existing gates. No NLP/embedding work is
currently authorized by the local execution contract.

## Completed work and evidence

| Checkpoint | Verified result and evidence | Reuse boundary |
| --- | --- | --- |
| Historical source/cleaning | Pinned full release downloaded; versioned protocol/arm/result text retained. [Schema guide](../HISTORICAL_CLEANED_SCHEMA.md), [ledger B11a/B11b evaluations](TASK_LEDGER.md). | Preserve raw and accepted clean outputs; source versions are not unique trials. |
| B22 | 19,576 Phase 3 targets; 297 narrow reported-p proxies, 19,279 unknown. [Evaluation](B22_INDEPENDENT_EVALUATION.md). | Not clinical benefit; chronological support gates failed for a new model. |
| B26 | Source-name, exact-version cross-phase bridge. [Evaluation](B26_INDEPENDENT_EVALUATION.md). | Names are candidate links, not verified molecular/indication identity. |
| B27R/B28 | Clean outcome-link replay and exact-arm feasibility accepted. [B27R evaluation](B27R_INDEPENDENT_EVALUATION.md), [B28 evaluation](B28_INDEPENDENT_EVALUATION.md). | Broad 91 measurement-bearing candidates reduce to seven under the strict recorded sensitivity funnel; neither set is model-ready. |
| B29 | 343-case metadata review queue from 19,576 targets. [Evaluation](B29_INDEPENDENT_EVALUATION.md). | Enriched fixed-seed queue; no population prevalence claim. |
| B30 | 452 first-public planned-primary rows across 329 of the 343 cases; 14 not observed. [Evaluation](B30_INDEPENDENT_EVALUATION.md). | Exact historical keys, but no independent child-publication date or proof of prespecification. |
| B31 v2 | 343 cases, 452 planned rows, 396 later PRIMARY headers; 38 focused/650 full tests, harness PASS and 15-file independent byte replay. [Evaluation](B31_INDEPENDENT_EVALUATION.md), [handoff](B31_ENDPOINT_REVIEW_PACKAGE.md). | Human-review preparation only; no automatic endpoint match, clinical label or model score. |

The evaluations/hand-offs contain versioned inputs, code/output hashes and
executed checks. Reconcile them before reuse; this index does not itself prove
correctness. Older development-only completion models remain separately
documented in the [README](../README.md); B31 did not rerun them.

## Data structures and dependency relationships

- Historical parent grain: `(nct_id, nct_version)` plus associated public date.
  Arms/interventions/outcomes add their own ordinal keys; never join child
  ordinals across versions as if stable endpoint identities.
- B26 keeps arms, interventions, aliases, conditions and source assertions
  separately. Cross-phase name overlap remains uncertain clinical identity.
- Review dependency route: B22/B19 metadata → B29 queue → B30 planned rows;
  B30 plus authenticated B17 exact result headers → B31 package.
- Link-feasibility route: B22/B19 and B26/B24 evidence → B27R → B28.
- B31 reviewer files hold opaque IDs, independent planned/reported lists and
  blank human fields. Audit-only files retain NCT/version/date/source lineage
  and sampling strata. Later reported headers are review evidence, **not
  earlier prediction features**. Share only the reviewer directory for the
  limited blinded review.

## Execution position and next dependencies

No scientific task is running at this checkpoint. B31 supervisor task is
accepted in the local ignored [state database](../data/processed/b31_supervisor_2026-11-27_v1/state.sqlite).
Accepted local [reviewer casebook](../data/processed/b31_full_2026-11-27_v2/reviewer/casebook.html)
is ready; raw/local artifacts are not included in GitHub.

Next uncompleted work: prespecify a two-independent-human-reviewer endpoint
correspondence/adjudication rubric, disagreement reconciliation and provenance
requirements; then conduct review. Separately establish a defensible identity
policy and verification evidence. Neither an agent's agreement nor identical
wording establishes a clinical label. Broader training depends on both sound
links and sufficient eligible labels. Preparing a rubric is possible without
rebuilding cleaned data; completing human adjudication requires reviewers.

## Failed approaches and new information

- Original B27 was rejected for result-child access before authentication and
  candidate restriction. Only separately evaluated B27R is accepted.
- B31 v1 failed literal-registry-ID blinding and must not be distributed as a
  blinded package. One targeted masking repair produced accepted v2; raw audit
  wording and rejected v1 remain preserved. Do not reset this task's repair
  history when resuming it.
- All 269 selected-result cases have eligible headers in B31; 74 no-result
  cases stay unknown. Of those 269, 52 lack an inherited outcome pointer but
  retain their headers. Header availability is not efficacy or recoverability.
- Strict exact-arm/name rules do not solve identity uncertainty or scarce
  defensible labels. No new AUC or efficacy model can be claimed from B31.

## Safeguards and invalidation

2024+ final outcomes remain sealed. Current model-support failures are
non-estimable results, not reasons to soften labels, chronology or leakage
rules. No accepted artifact is newly invalidated by H32. On a future error,
record affected artifact versions and transitive dependencies here and in the
ledger; preserve unaffected work and originals. Apply the
[recovery policy](RECOVERY_POLICY.md) and update only the affected route.
