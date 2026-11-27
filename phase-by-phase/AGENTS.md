# Phase-by-phase execution contract

Scope: make code, tests, and documentation changes only in this directory. The repository's existing top-level pipeline and raw/processed data are read-only inputs. Do not edit or overwrite an existing raw snapshot or report.

Read `harness/EXECUTION_RULES.md`, `harness/TASK_LEDGER.md`, and `skills/structured-trials/SKILL.md` before implementation. The coordinator owns scope and the ledger; a builder owns bounded code changes; a data auditor inspects source/label provenance; an independent evaluator inspects diffs, runs checks, and reports exact failures. The builder cannot change acceptance criteria.

Read `harness/CURRENT_STATE.md` and `harness/RECOVERY_POLICY.md` before planning or recovery. Resume from verified evidence, preserve unaffected accepted artifacts, and revise only the affected route. Update the compact state at meaningful checkpoints. Engineering fixes may be local; scientific changes require a prospective recorded protocol change, and upstream errors require targeted transitive dependency invalidation. New task IDs do not reset the same approach's three-repair budget.

No NLP, embeddings, LLM extraction, or GPU work. Keep the final holdout sealed during development. A synthetic pass is not a real-data pass; a real-data audit is not a successful model. Never use a trial's final status, results, enrollment, or stopping reason as its own at-launch features. Earlier-trial results require a trustworthy public availability date no later than the later trial's prediction date.

Use at most three repair rounds per bounded task, and record commands, exit codes, artifacts, and blockers in the ledger. Preserve missing values as unknown; do not convert missing p-values or results to negative outcomes. Do not claim clinical identity verification from exact drug-label matches.
