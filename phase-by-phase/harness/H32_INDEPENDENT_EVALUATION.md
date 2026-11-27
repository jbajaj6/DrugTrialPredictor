# H32 independent evaluation — PASS_SYNTHETIC (policy/harness only)

2026-11-27. **Verdict: PASS_SYNTHETIC for the bounded state-aware recovery policy and required-file check.** This is a documentation/harness verdict, not a scientific-data replay or model acceptance.

I read `../AGENTS.md`, `../skills/structured-trials/SKILL.md`, `EXECUTION_RULES.md`, frozen H32 ledger entry, `RECOVERY_POLICY.md`, `CURRENT_STATE.md`, the H32 diff for `../README.md`, `SUPERVISOR.md` and `check.py`, and the accepted B31 independent evaluation. `git status --short` showed only the expected seven modified files (AGENTS, README, execution rules, supervisor guide, ledger, checker and skill) plus the two new policy/state files before this evaluation was added. No source data, model, holdout, or result table was opened.

The policy distinguishes local engineering repair, acquisition/coverage gaps, non-estimable science, scientific redesign, and invalid upstream artifacts; it requires prospective recorded amendments and targeted transitive dependency invalidation. It preserves unaffected accepted outputs and the three-repair limit across renamings of the same unresolved approach. It explicitly states that `CURRENT_STATE.md` is an evidence index, not acceptance authority; the supervisor execution database and independent evaluations retain their roles. The new `check.py` entries require both state/policy files, without changing scientific computation.

Observed commands from `phase-by-phase/`:

| Command | Exit/result |
| --- | --- |
| `GIT_CONFIG_GLOBAL=/dev/null git status --short` | 0; expected H32 scope before this evaluation file |
| `GIT_CONFIG_GLOBAL=/dev/null git diff -- AGENTS.md README.md harness/EXECUTION_RULES.md harness/SUPERVISOR.md harness/TASK_LEDGER.md harness/check.py skills/structured-trials/SKILL.md` | 0; bounded policy/required-list diff |
| `PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python harness/check.py` | 0; PASS, including SHA-256 entries for `RECOVERY_POLICY.md` and `CURRENT_STATE.md` |
| `GIT_CONFIG_GLOBAL=/dev/null git diff --check` | 0; no whitespace errors |
| `GIT_CONFIG_GLOBAL=/dev/null git rev-parse --short HEAD` | 0; `245d800`, matching the stated scientific-code checkpoint |

A read-only local-link existence check over README, recovery policy, current state, execution rules and supervisor guide found **162 local links, zero missing**. The B31 evaluation file, accepted v2 reviewer casebook path and local supervisor checkpoint database path exist. The state summary's B31 figures—343 cases, 452 planned rows, 396 reported headers, 38 focused/650 full tests and 15-file replay—match the accepted [B31 independent evaluation](B31_INDEPENDENT_EVALUATION.md). Its rejection of B31 v1 and warning against clinical-label/model claims also agree. I checked the supervisor database path's existence only; I did not query its contents or treat the state page as a substitute for the recorded supervisor verdict.

**Enforcement limit:** The three-repair count for one task is bounded by the existing supervisor, but whether a renamed/new task is the *same scientific approach*, whether dependencies are transitively invalidated, and whether a state claim is semantically reconciled are coordinator/agent policy judgments, **not software-enforced cross-task guarantees** in `supervisor.py` or `check.py`. H32 correctly discloses this. No automatic replanner, source replay, label change, model run or final-holdout access occurred.
