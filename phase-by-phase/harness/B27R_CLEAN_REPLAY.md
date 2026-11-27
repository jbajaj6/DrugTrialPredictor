# B27R clean-process replay execution record

Executed 2026-11-27 from `phase-by-phase/`. This is an execution handoff, not an acceptance verdict. **B27 attempt 1 failed its access contract and remains rejected.** Its final-v3 outputs are comparators only. The independent evaluator decides the B27R verdict.

The worker read `AGENTS.md`, `skills/structured-trials/SKILL.md`, `harness/EXECUTION_RULES.md`, the frozen B27/B27R ledger sections, `harness/B27_INDEPENDENT_EVALUATION.md`, `harness/B27R_CLEAN_REPLAY_PROMPT.md`, and the complete frozen module before replay. No source, test, README, ledger, input, or prior output was edited. No repair was attempted.

## Preflight and process boundary

The first shell command was `shasum -a 256 src/phase_by_phase/proxy_link_feasibility_b27.py` (exit 0). Its byte digest matched the required `eef732527ade9b3d527b31cadfd58b127a414e3148e25bc6784ec6f0b0883928`. The parent repeated this byte check immediately before spawning, and again after completion; all matched.

`git check-ignore data/processed/b27r_execution_2026-11-27_v1/record.json data/processed/b27r_clean_2026-11-27_v1/manifest.json` exited 0 and listed both paths. The parent asserted that both directories and this handoff did not exist, then exclusively created fresh execution logs. No data files were opened before replay by the worker. Instruction/source reads, file-name listings, ignore checks, and `git status --short` preceded it.

The system Python parent used `subprocess.Popen` with the frozen module as a separate Python child, without importing it into the parent. Exact replay command:

```sh
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.proxy_link_feasibility_b27 --out data/processed/b27r_clean_2026-11-27_v1
```

The child inherited `PYTHONDONTWRITEBYTECODE=1` to avoid bytecode writes. Parent PID 75819; child PID 75822. Start: `2026-11-27T08:10:39.357977+00:00`; finish: `2026-11-27T08:10:42.752981+00:00`; elapsed **3.394528625 seconds**; exit **0**. Stderr was empty. Complete command, cwd, timestamps, PIDs, exit, runtime, before/after code hashes, and all 12 artifact hashes are in `data/processed/b27r_execution_2026-11-27_v1/replay.json`; raw streams are `replay.stdout` and `replay.stderr` there.

Exact replay stdout:

```json
{"asof_measurement": [{"name_prior_pairs": 2448, "names": 97, "prior_ncts": 1014, "target_prior_pairs": 2235, "targets": 91}], "candidate_counts": [{"name_prior_pairs": 21669, "names": 233, "prior_ncts": 7086, "target_prior_pairs": 19587, "targets": 189}], "target_denominator": 19576}
```

## Required checks

All commands ran sequentially after successful replay. Each has a separate JSON execution record plus unabridged `.stdout` and `.stderr` in the ignored execution directory. No failures occurred, so no repair or retry occurred.

| Exact command | Exit and observed result | Wall runtime |
| --- | --- | --- |
| `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_proxy_link_feasibility_b27.py` | 0; 51 passed in 2.82s | 3.637059250s |
| `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 0; 515 passed, 6 warnings in 52.85s | 53.825461208s |
| `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python harness/check.py` | 0; harness reported `PASS` | 0.066783917s |
| `/usr/bin/python3 data/processed/b27r_execution_2026-11-27_v1/compare.py > data/processed/b27r_execution_2026-11-27_v1/comparison.stdout 2> data/processed/b27r_execution_2026-11-27_v1/comparison.stderr` | 0; 12/12 file digests equal; no differences | 0.011667417s internal comparison runtime |

Full-suite warnings were five existing DuckDB `fetch_record_batch()` deprecations and one joblib physical-core detection warning. These were warnings, not test failures. Required synthetic tests include model-component tests; no separate model fitting, scoring, or real-data model command was run.

## Byte comparison and permitted inspection

The saved `compare.py` streams bytes into SHA-256 for every file in the fresh output and `data/processed/b27_full_2026-11-27_v3/`. It does not decode Parquet or examples. File sets and all **12/12** digests match. Full paired digests and inspection results are preserved in `comparison.json` and `comparison.stdout`; comparison stderr was empty.

Only the new and comparator `report.json` and `manifest.json` were decoded for counts/hashes outside the frozen module. Their contents match. The new manifest records 22 input digests and 11 output digests; all 11 listed output hashes and its code hash match the actual byte hashes. This is a manifest inspection, not an independent re-audit of input rows.

| Artifact (same digest in both directories) | SHA-256 |
| --- | --- |
| `report.json` | `bde83471ad75d6e2c0b13e472ceb2576e5b08b0fb5a6da28dd3cb2ca852c982f` |
| `manifest.json` | `cfb0c06e1f90da5adce0351d95674ce0720b1d70758ef89e9b2530b20e80d68b` |

Report-only counts: 19,576 target rows; proxy classes 170 positive, 127 negative, 19,279 unknown. Candidate gate: 189 targets, 21,669 name/prior pairs, 19,587 target/prior pairs, 7,086 prior NCTs, 233 names. As-of nonempty-primary-measurement gate: 91 targets, 2,448 name/prior pairs, 2,235 target/prior pairs, 1,014 prior NCTs, 97 names. These are reproduced audit counts, not efficacy, clinical identity, predictive performance, or model-readiness findings.

## Access scope and review status

No exploratory query, schema probe, row sampling, PyArrow result-child read, target Phase 3 result-value inspection, or 2024+ target outcome inspection was performed. The frozen replay module was the sole code used to read real B11b result children. Its independently inspected authentication and candidate restrictions were left unchanged. Outside that process, data artifacts other than the four permitted JSON documents were accessed only as byte streams for hashes. No network request, holdout evaluation, model selection, or feature promotion was performed.

Generated data and execution evidence remain under ignored `data/processed/` paths. This new handoff is the only nonignored file created by this worker. Existing worktree changes observed at preflight were preserved. There are no observed execution failures or digest differences to report. Independent review of logs, chronology, process boundary, and artifacts remains outstanding; this document makes no self-acceptance claim.
