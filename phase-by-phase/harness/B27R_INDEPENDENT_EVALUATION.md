# B27R independent evaluation — clean-process replay

**Verdict: PASS_REAL_DATA_CHECKS for the separately preregistered B27R clean replay.** This is not a retroactive acceptance of B27 attempt 1: that attempt remains rejected for its documented whole-table result read before authentication and candidate restriction. B27R only re-executed the frozen final-v3 code in a new worker process, produced a new ignored output, and compared bytes. Its result is still a feasibility count, not clinical linkage, efficacy, model readiness or a feature authorization.

## Process and access boundary

I read local AGENTS, the structured-trials skill, execution rules, the frozen B27R ledger section and prompt, the rejected B27 independent evaluation, the B27R worker handoff, final frozen module and execution records. I did not edit code, tests, README, ledger, source/holdout files, the B27 rejected output or the B27R output. This document is my only edit.

The worker's preserved record 'data/processed/b27r_execution_2026-11-27_v1/replay.json' identifies parent PID **75819**, separate child PID **75822**, exact child command, UTC start/finish, exit, runtime, empty stderr, source hash before/after and all artifact digests. The reported first shell command was a byte-only SHA-256 of the module. The child began at **2026-11-27T08:10:39.357977Z**, ended at **08:10:42.752981Z**, exited **0**, and ran **3.394528625 seconds**. Its command was:

    PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.proxy_link_feasibility_b27 --out data/processed/b27r_clean_2026-11-27_v1

The recorded before/after module SHA-256 both equal the frozen 'eef732527ade9b3d527b31cadfd58b127a414e3148e25bc6784ec6f0b0883928', which I rehashed independently. The logged sequence then runs focused tests, full suite, harness and comparison **after** the child finishes. I inspected those records, raw stdout/stderr, comparison script and handoff. No recorded exploratory query, schema probe, PyArrow whole-result read, target-result sample, 2024+ holdout operation, network call or model command appears in the B27R worker record. The only permitted real result-child access is inside the unchanged frozen module, whose 'verify_inputs()' authenticates pins/used children before row queries and whose known-label prior-NCT restriction precedes result metadata/value-presence reduction. This is process-log evidence, not an operating-system syscall trace; no claim is made about unobserved actions. The supervisor/coordinator retains final task disposition authority.

## Independent hashes and counts

I independently streamed SHA-256 over **22/22** manifest-listed pinned inputs, including B22, B26, B11b and raw-source manifests, B18 restricted comparator, queried children and nine raw core parts; all matched the new output manifest. I separately recomputed the frozen module digest, **11/11** listed output digests, and every byte hash in the new and rejected-v3 comparator directories: **12/12 files match byte-for-byte**, including the manifest. The B27R manifest SHA-256 is 'cfb0c06e1f90da5adce0351d95674ce0720b1d70758ef89e9b2530b20e80d68b'. This comparison uses the old B27 final-v3 output only as a byte comparator, not as an accepted source or input to the replay.

Decoding only the permitted new 'report.json' and 'manifest.json' reproduces **19,576** target rows (170 proxy-positive, 127 proxy-negative, 19,279 unknown), **189** known-label targets with strict-earlier same-name P1/P2 registration, **21,669** name/prior pairs, **19,587** target/prior pairs, **7,086** prior NCTs and 233 names. The as-of nonempty-primary-measurement gate is **91** targets, 2,448 name/prior pairs, 2,235 target/prior pairs, 1,014 prior NCTs and 97 names. The report/manifest are byte-identical to the prior final-v3 comparator and retain the independent B27 artifact-level chronology/source checks; B27R does not claim a fresh target-value re-audit or convert the rejected B27 process into a pass. No model, feature promotion, identity or effect interpretation follows from these counts.

## Commands and exits

All independent commands below ran from 'phase-by-phase/'. My inspection read only worker JSON/logs, new/comparator report/manifest and byte streams for hashes; it did not decode result-child rows or target values.

| Command/check | Independent result |
| --- | --- |
| Byte-only Python SHA-256 over frozen module, 22 pinned input files, 11 listed new outputs, all 12 new/comparator files; decode new report/manifest | Exit 0; all hashes/counts above matched. |
| Inspect 'replay.json', 'focused.json', 'full.json', 'harness.json', 'comparison.json', raw streams and 'compare.py' | Exit 0; separate child process, source hash before/after, sequential commands, all recorded exits 0 and no logged exploratory data read. |
| 'PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_proxy_link_feasibility_b27.py' | Exit 0; **51 passed**. |
| 'PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests' | Exit 0; **515 passed**, five existing DuckDB deprecation warnings. |
| 'PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python harness/check.py' | Exit 0; **PASS**. |

The worker's own test/comparison logs additionally record 51 focused/515 full/harness PASS and 12/12 byte equality, with no retry or repair. My re-execution corroborated the test/harness results. Passing B27R means only that the frozen B27 final-v3 artifact was reproduced in this separately supervised, apparently clean process under the pinned access path. The original B27 failure remains recorded and rejected. The fixed early training split still has no known labels public before 2016, and no prediction run or final holdout is authorized.
