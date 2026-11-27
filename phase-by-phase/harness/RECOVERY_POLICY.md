# State-aware incremental recovery

**Execute → observe → detect meaningful deviation → understand current state → revise the affected route → continue.**

This is the recovery policy for the existing harness, not a replacement for
[execution rules](EXECUTION_RULES.md), independent evaluation or scientific
safeguards. Initially reason backward from the objective. After execution
begins, reason forward from the latest verified state; do not restart the
project plan at every failure.

## Persistent state and authority

Read [CURRENT_STATE.md](CURRENT_STATE.md) at task start and update it after a
meaningful accepted result, failed strategy, invalidation, dependency change
or handoff. Do not generate an expensive narrative after each operation.
Keep the objective, remaining route, verified work, table grains/relationships,
execution position, failed approaches, new findings and unresolved dependencies
concise and evidence-linked. Detailed commands and failures belong in the
[task ledger](TASK_LEDGER.md) and task-specific evaluations.

The state file is a navigation index, **not acceptance authority**. Accepted
work needs code/input/output versions or hashes, executed checks and an
independent verdict in its evidence. The supervisor database is authoritative
for supervised task execution status. A missing or conflicting checkpoint
requires a read-only reconciliation of relevant evidence, not a blanket rebuild
or automatic promotion of an agent's claim. Do not overwrite frozen historical
criteria or earlier artifacts when updating state.

## Local recovery procedure

1. Identify the last verified checkpoint and exact failing operation; record
   command, exit code, error and artifact. Separate exploratory command errors
   from product/scientific failures.
2. State which assumption failed, which outputs remain valid and which
   downstream tasks depend on that assumption. Consult only relevant evidence.
3. Classify the deviation using the table below. Select the smallest feasible
   repair or remaining route that preserves the objective and safeguards.
4. Record the affected plan delta and its justification before executing it.
   Builders may solve engineering details inside assigned scope; coordinator
   approval is needed for scope/criteria changes, not every local fix.
5. Rerun checks affected by the repair and independent evaluation required by
   the task. Reuse unaffected accepted outputs after verifying their relevant
   lineage; do not repeat research, downloads or full data cleans without cause.
6. On acceptance, update the checkpoint and continue to the next unblocked
   task. On failure, preserve evidence and apply the bounded repair rule.

| Deviation | Response from current state |
| --- | --- |
| Engineering defect: dtype, SQL syntax, bounded-memory failure | Repair locally; keep scientific definitions fixed; verify equivalence and affected invariants. |
| Source access/schema/coverage gap | Preserve good cached inputs; authenticate or acquire only missing eligible inputs within authorization; retain unknowns and explicit coverage. |
| Insufficient classes, dates or defensible labels | Report non-estimable; do not invent labels, relax timing or treat missing as failure. Work on justified unmet dependencies. |
| Scientific redesign: label, cohort, identity, timing, features or validation | Coordinator records a prospective amendment/new experiment and its evidence exposure before evaluating it; preserve prior results and compare fairly. |
| Accepted upstream artifact is wrong | Mark the affected result invalid or requiring re-evaluation, trace dependent outputs, and quarantine them from new claims; preserve originals for audit. |

Scientific redesign must disclose which development outcomes were already
seen. A declaration after seeing results is not preregistration. Keep matched
cohorts for feature comparisons and address repeated adaptive comparisons;
do not repeatedly select favorable experiments on the same validation data.
The sealed final holdout stays sealed until the existing freeze/readiness gates
permit its evaluation. A poor final score never licenses retuning on that set.

## Dependency invalidation and repair bounds

Maintain dependency pointers in state and task evidence. Invalidation is
targeted, but transitive: a wrong drug identity can invalidate its aggregates,
features and scores even if downstream unit tests passed. An unrelated
renderer defect does not invalidate authenticated raw data. Record the reason,
affected versions and required checks; archive outputs rather than overwrite.

Retain **at most three targeted repairs per bounded task** (initial attempt
plus three repairs). New strategy names, sessions or task IDs do not reset
this budget for the same unresolved approach. A genuinely different scientific
or architectural route needs a recorded rationale, scope and acceptance gates,
linked to the failed task and its complete repair history. After exhaustion,
stop that task with an exact blocker; continue independent authorized work
only where it does not depend on the failed result.

## When broader replanning is warranted

Invoke the coordinator/global planner only when a major assumption fails, an
essential dependency cannot be met, architecture must materially change, the
remaining route cannot reach the objective, or bounded local recovery is
exhausted. Provide a compact packet: checkpoint, specific failure/evidence,
valid work, attempted repairs, affected dependencies and remaining objective.
Even then, start from verified work rather than restating the entire history.

## Project examples

- **Boolean preprocessing failure:** repair dtype handling and test an actual
  fit; retain the validated cleaned tables and unchanged split/label rules.
- **B31 registry identifier in reviewer prose:** repair only reviewer masking;
  preserve raw audit wording and the rejected v1; accept v2 only after checks
  and independent replay. Do not rebuild B29/B30 or infer clinical labels.
- **Too few traceable Phase 3 labels:** retain accepted linkage/label audits;
  prepare the planned human-review protocol and verify identities. Widening
  the efficacy definition merely to create more training rows is not a code fix.

These instructions guide agents. The current supervisor remains a bounded
launcher and does **not** automatically reason about scientific dependencies,
adjudicate endpoints or implement an unattended replanning dispatcher.
