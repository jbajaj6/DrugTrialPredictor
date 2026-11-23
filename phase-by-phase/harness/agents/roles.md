# Agent task cards

## Coordinator
Goal: complete one acceptance item at a time within phase-by-phase only.
Inputs: AGENTS.md, config, tasklist, latest progress, artifact paths/hashes.
Outputs: explicit task cards and checkpoint records. Owns tasklist/progress.
Limits: 3 repair rounds, no test optimization, no data fabrication.

## Data auditor
Goal: determine what the existing dataset can support, without changing it.
Read: current processed table, main schema/label source, branch STATUS.md.
Write: phase-by-phase outputs only; audit and provenance findings.
Check: unique NCT, dates, exact phase counts, unknown labels, p qualifiers,
post-outcome fields, missingness, cohort exclusions, Q2 reporting coverage.
Return: PASS/BLOCKED/WARN with evidence paths, not an inferred success label.

## Builder
Goal: implement a scoped acceptance item using deterministic Python functions.
Read: audit, policy, code, task card. Write only assigned phase-by-phase files.
Tools: editor, compile, unit tests, training/validation runner. No final-test tool.
Return: changed files, commands/exits, artifact paths, outstanding failures.

## Independent evaluator
Goal: try to falsify the implementation and its scientific claims.
Read: code/diff, input manifest, fixtures, generated artifacts, traces.
Write: eval verdict and reports only; do not repair builder code while judging.
Tools: independent tests, invariant checks, final-test evaluation after freeze.
Return: severity, failure ID, reproduction, expected/observed, evidence path.
Never accept AUC as proof of no leakage. Never allow a nice report to hide
unsupported Phase 1 Q2 or an unobserved endpoint.

Suggested provider-neutral handoff:
```json
{
  "task_id": "RF-02", "status": "BLOCKED", "agent_role": "data_auditor",
  "inputs": ["path + sha256"], "allowed_write_paths": ["phase-by-phase/outputs"],
  "checks": [{"id": "missing-p-is-unknown", "passed": true}],
  "artifacts": [], "failures": [], "next_action": "specific bounded action"
}
```

Run these roles in the user's existing Codex or Claude Code session. This kit
does not implement an SDK provider adapter or autonomously call paid models.
Agents help build and audit the pipeline; the random forest produces all
trial predictions without LLM calls.
