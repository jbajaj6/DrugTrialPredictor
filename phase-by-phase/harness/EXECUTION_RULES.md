# Execution rules

1. Coordinator records a bounded task and immutable acceptance criteria in `TASK_LEDGER.md` before assigning it. Builder changes only assigned files. Auditor and evaluator do not change acceptance criteria.
2. The data auditor verifies source manifests, hashes, columns, date precision, label definitions, coverage, and leakage risk. Source data are read-only.
3. The independent evaluator reads the actual diff and output artifacts, runs tests and real-data checks, and gives one of `PASS_SYNTHETIC`, `PASS_REAL_DATA_CHECKS`, `FAIL`, or `BLOCKED/PARTIAL` with exact command and exit code.
4. On `FAIL`, the coordinator assigns a specific repair. At most three repair rounds per task. Rerun the checks and independent evaluation after each repair. If unresolved, stop that task with a precise blocker; do not soften the criteria.
5. The real-data pilot is acquisition/replay, cleaning, structured results, dated target rows, audit, train, and evaluate. Scale only after the pilot passes. Store new outputs in a new directory; never overwrite a previous run.
6. During development, use synthetic fixtures and development partitions only. Never open final-test outcomes for debugging. Freeze source manifest hash, split manifest, feature list, settings, and code hashes before a single final evaluation. A poor final score does not trigger tuning on that test.
7. Separate engineering correctness, data-quality evidence, and predictive performance. An unsupported label or single-class partition yields an explicit not-estimable report, not an invented score. Record every command, exit code, artifact path, and checksum.
