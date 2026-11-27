# B27 Phase 3 proxy-link feasibility — builder handoff

**Implementation and builder checks complete; independent acceptance pending.**
This is a deterministic, read-only feasibility audit. The evaluator, not this
handoff, decides `PASS_REAL_DATA_CHECKS`. An initial exploratory probe violated
the source-access contract; that incident is disclosed below and remains for
independent adjudication.

## Boundary and ownership

The only new tracked deliverables are
`src/phase_by_phase/proxy_link_feasibility_b27.py`,
`tests/test_proxy_link_feasibility_b27.py`, and this handoff. New generated files
are under ignored `data/processed/b27_*` directories. AGENTS, structured-trials
skill, execution rules, frozen B27 ledger/prompt, and accepted B22/B26 handoffs
were read first. Previous code, README, ledger, inputs and existing artifacts
were not edited. This command record is supplied for the coordinator's ledger.

No model, efficacy estimate, p-value interpretation, drug/arm/regimen/indication
identity, feature promotion or holdout evaluation is produced. Reported proxy
class is B22 label provenance only; missing labels remain unknown. Same-name
registrations, primary headers and nonempty measurements do not establish an
interpretable effect or usable p-value. Exact strings may denote control drugs,
shared arms, broad regimens or unrelated programs.

## Access-contract incident and repair record

**Before implementation, a schema/sample probe ran `pyarrow.parquet.read_table`
on both complete B11b result-child files, then sliced to one row.** This read
occurred before hash verification and before candidate semijoin, so target
Phase 3 and unrelated result payloads were materialized. The shell exited 0,
but the action violated the task's access contract. It cannot be undone or
converted into a clean-session claim by later successful tests. The probe
read B11b's pre-2024 cleaned public-version files; no raw 2024+ outcome values
were opened. No prediction run or result-based feature selection followed.
I do **not** claim that this builder session maintained the no-target-result-read
firewall. The coordinator/evaluator must decide the consequence.

A subsequent metadata-only manifest probe exited 1 with
`KeyError: 'output_sha256'`; the corrected B11b key is
`output_files_sha256`. Both exact commands and incident details are preserved in
[data/processed/b27_execution_2026-11-27_v1/PREFLIGHT_FAILURES.md](../data/processed/b27_execution_2026-11-27_v1/PREFLIGHT_FAILURES.md).

**Two targeted code repair rounds used; one remains.** Initial 42-test/full-v1
checks passed. Self-review found that tied/later primary dates were combined
rather than separated per checkpoint, explicit phase-overlap counts were absent,
and the label-date/value-access gates could be stronger. Repair 1 added these,
a materialized value-free measurement-key semijoin and six regressions. Two
final tests added measurement-only withdrawal and B18 non-gating coverage.
Repair 2 arose from final source review: a missing core version hit the generic
missing-key exception instead of remaining inspectable unknown metadata. It now
survives as an unavailable revision and duplicate revisions still fail. The
additional null-version regression passes; no real-data count changed.
No acceptance criterion changed. Full-v1/full-v2 remain preserved and superseded;
full-v3 and replay-v3 use final code.

## Pinned inputs and method

All authentication completes **before row queries in the module**. It checks
four frozen manifests, B18's standalone comparator and every queried child/core
part. The output manifest records 22 authenticated input-file digests:

| Frozen source | Manifest/file SHA-256 |
| --- | --- |
| B22 full-v4 manifest | `90dbc788896ed5340e3ba7899851ed62feeb1d6b0f27a9f95fc286cc0207235f` |
| B26 full-v2 manifest | `981a3820c29c0af99ee70437ab256c89e0898dc18c1c421773dd1f485956ff97` |
| B11b full cleaning manifest | `ac4ab7c684bea7867a3814d06dfb031e0ada7883cd18444950e4d09c594e4889` |
| Full raw-source inventory | `a1b318aafc861a6948a53d74fbffabd3694e82aa986d8227ddc14187edea2219` |
| B18 full-v2 prior contributions | `74595949abfdc9fee7862bff249de442e5d3b0984ec08f5d55ae8455ee400ba3` |

Used B22 labels, five B26 children and two B11b children are individually
hash-checked; all nine raw core parts are checked against the inventory. B26
`intervention_names` is authenticated provenance; candidate reconstruction uses
canonical `name_trials` and its original intervention ordinal lists. No aliases,
condition expansion, aggregate example NCT or B18 gate enlarges/restricts pairs.

1. Project B22 labels into explicitly named `label_*`/`audit_label_*` columns.
   Join **all 19,576** targets to B26 on NCT, first-public version and date.
   B22's later result version is never a join/predictor key. Target checkpoints
   are 2005–2019; label dates must be after checkpoint and before 2024.
2. Expand only **297 known labels** on identical canonical names to different
   pure-P1/P2 NCTs with strictly earlier first-public dates. Preserve the actual
   trial/version/name/ordinal keys and overlapping ambiguity flags. Reconcile
   every known-target name/phase count against B26 `name_coverage`.
3. Restrict raw core metadata to the resulting 7,086 prior NCTs. Project only
   exact keys, public date, obsolescence and file/row/commit provenance; no raw
   core outcome/status/enrollment payload is queried. Noninteger/negative/
   overflowing version keys are unavailable. Select the latest whole nonobsolete
   record strictly before each checkpoint and before 2024, using public date then
   integer version. When multiple nonobsolete versions share that latest day,
   retain the version tie-break for inspection but mark availability unknown.
   Any undated core revision, malformed key or unknown obsolescence also makes
   as-of availability unknown conservatively; no date order is invented.
4. Read prior header **metadata** separately, preserving exact version/outcome,
   source row/file/commit, type, dates and obsolescence. Valid primary presence
   requires exact NCT/version, nonobsolete child and core, and equal source/core
   public dates. Materialize allowed measurement row keys without values; only
   then evaluate nonempty value presence at exact NCT/version/outcome. Raw
   measurement values are not emitted. Measurement source dates must also equal
   the whole-core public date. Empty/missing values do not imply negative effects.
5. Keep `ever_posted_before_checkpoint`/`ever_measurement_before_checkpoint`
   separate from `asof_current_primary_header`/`asof_current_primary_measurement`.
   A newer whole record can remove headers or measurements. Unknown/tied dates
   and mismatched keys never establish availability. The ever flags are a dated
   sensitivity, not a substitute for the as-of gate.
6. Produce B18 restricted comparison separately. Its absence is unknown, and its
   dated result pointer is not a replacement for B27's exhaustive B26 metadata.

DuckDB is fixed to **2 GiB, two threads, empty temp directory (zero spill)**.
No network is used. The final replay additionally replaces sockets, DNS and
connection helpers with functions that raise. Logical semijoin/projection
checks do not claim that Parquet's physical row-group reads contain only selected
rows. No global arm × alias × condition or all-trial pair expansion occurs.

## Observed full-v3 feasibility

B22 denominator remains **19,576**: 170 proxy-positive, 127 proxy-negative,
19,279 unknown. Unknown-label targets retain their B26 registration coverage but
are explicitly `not_expanded_unknown_label`; prior-result booleans remain null.
Known-label targets with no pairs have false availability, not negative labels.

| Gate | Distinct targets | Positive / negative targets | Prior NCTs | Names | Target/prior pairs | Name/prior pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Strict-earlier P1/P2 same-name registration | 189 | 110 / 79 | 7,086 | 233 | 19,587 | 21,669 |
| Ever dated primary header | 93 | 52 / 41 | 1,099 | 98 | 2,433 | 2,660 |
| As-of primary header | 93 | 52 / 41 | 1,099 | 98 | 2,433 | 2,660 |
| Ever dated nonempty primary measurement | 91 | 50 / 41 | 1,014 | 97 | 2,235 | 2,448 |
| As-of nonempty primary measurement | 91 | 50 / 41 | 1,014 | 97 | 2,235 | 2,448 |

Name/prior pair grain is `(target NCT, canonical name, prior NCT)`.
Target/prior pairs collapse names; prior NCT and name counts are distinct across
the corresponding gate. Counts of targets across gates, classes, phase and
availability states can overlap and must not be summed indiscriminately.

| Phase coverage | Registration targets / pairs | As-of-header targets / pairs | As-of-measurement targets / pairs |
| --- | ---: | ---: | ---: |
| P1 | 143 / 5,276 | 51 / 230 | 50 / 228 |
| P2 | 179 / 16,393 | 89 / 2,430 | 87 / 2,220 |
| Both phases, distinct targets | 133 | 47 | 46 |
| Union, distinct targets | 189 | 93 | 91 |

Pairs in this phase table are name/prior pairs. `report.json` provides separate
target/prior/name/pair counts at every gate by phase, proxy class and target
year, plus exclusive label-publication cutoffs from 2016-01-01 to 2024-01-01.
There are **zero known labels before the 2016 cutoff**. A broader registration
or result presence count does not authorize a prediction run.

Availability at name/prior-pair grain: 2,448 primary-with-measurement, 212
primary-header-without-measurement, 18,661 no as-of primary, 344 unknown because
of missing core dates, four unknown because of ambiguous latest public day.
These correspond to 91, 45, 183, 34 and three distinct targets respectively;
the target sets overlap. No real withdrawal status occurred; header and
measurement withdrawal are both exercised synthetically. No available
malformed core key, unmatched primary version or core/child date mismatch was
found. Per-request diagnostics contain **11 tied and 32,405 later primary-header
comparisons**, 11,390 requests without any primary header, and 17,154 without an
earlier primary header. Repeated source records across target checkpoints mean
these are request/header comparisons, not unique trials. Core diagnostics
separately retain 276 tied comparisons and 509 missing-date comparisons.

B18 covers **100 targets**, with **18** dated as-of result pointers, reproducing
the restricted preflight. This is a separate lower bound, never the exhaustive
B26 numerator. Pair ambiguity flags overlap: 19,716 high-fanout, 17,032 known
control-role, 12,466 shared experimental/control roles, 10,103 unlinked, 1,158
one-sided and 17,572 possible combination/conflict pairs. They are retained
warnings about candidate interpretation, not clinical identity adjudications.

## Artifacts and builder inspection

Final artifacts: [b27_full_2026-11-27_v3](../data/processed/b27_full_2026-11-27_v3/manifest.json).
Fresh offline replay: [b27_replay_2026-11-27_v3](../data/processed/b27_replay_2026-11-27_v3/manifest.json).
All **12/12 files are byte-identical**, including nine Parquet tables, report,
examples and manifest. Manifest SHA-256:
`cfb0c06e1f90da5adce0351d95674ce0720b1d70758ef89e9b2530b20e80d68b`.
Final module SHA-256:
`eef732527ade9b3d527b31cadfd58b127a414e3148e25bc6784ec6f0b0883928`.

| Table | Rows | Purpose |
| --- | ---: | --- |
| `target_feasibility` | 19,576 | All-target labels/audit provenance and coverage |
| `candidate_pairs` | 21,669 | Bounded known-label actual candidate keys, flags and availability |
| `availability` | 19,587 | One target/prior checkpoint; whole-record selection and diagnostics |
| `core_meta` | 157,770 | Prior-only all-version key/date/obsolescence/source metadata |
| `version_evidence` | 106,857 | Nonobsolete prior versions before last relevant checkpoint; child presence |
| `prior_headers` | 61,265 | Prior-only header metadata, including secondary/future/version diagnostics |
| `primary_headers` | 3,654 | Exact eligible-version primary metadata and validity |
| `measurement_presence` | 13,601 | Exact allowed primary child keys, dates, validity and nonempty flag |
| `b18_comparison` | 382 | Restricted comparator metadata, never a gate |

The builder [inspection script](../data/processed/b27_execution_2026-11-27_v1/inspect_artifacts_v3.py)
recomputes input/output/code hashes, compares replay bytes, reconstructs every
candidate pair from B26 source rows, checks latest whole-core selection for all
19,587 requests, verifies exact integer schemas and no target NCTs in prior
child outputs, compares the raw core metadata multiset in both directions,
recomputes bounded exact-primary measurement presence from B11b, and checks every
phase/class/year gate aggregation. All assertions exited 0. This is builder
inspection, not independent evaluation.

Inspected examples (full metadata in `examples.json` and execution
`inspection_v3.json`):

- Proxy-negative target `NCT01004978` (2009-10-30), `cisplatin`, prior P2
  `NCT00191815`, first-public v0 (2005-09-19): as-of v5 (2009-08-19) has one
  primary header and five valid nonempty measurements. Target control-role and
  high-fanout flags remain true. No beneficial effect is inferred.
- Proxy-positive target `NCT01208662` (2010-09-24), `bortezomib`, prior P2
  `NCT00810576`: as-of v3 (2010-07-09) has one header/four nonempty measurements.
- `NCT01004978` / prior `NCT00475657` / `cisplatin`: exact as-of v9
  (2009-05-29) has one primary header and no valid nonempty measurement.
- `NCT02246621` / prior `NCT00532272` / `letrozole`: v3 is the deterministic
  tie-break on 2011-06-27, but same-day versions force availability unknown.
- `NCT02625623` / prior `NCT02549209` / `paclitaxel`: an undated core revision
  forces unknown despite a retained earlier dated core pointer.

## Exact validation commands and observed exits

Commands run from `phase-by-phase/`. The recorder applies `PYTHONPATH=src` and
`PYTHONDONTWRITEBYTECODE=1`; `commands.jsonl` records full argv, environment,
exit status and runtime, and each named log preserves complete output.
The commands below include that recorder so they are directly reproducible.

```sh
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py focused_initial ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_proxy_link_feasibility_b27.py
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py full_v1 ../.venv/bin/python -m phase_by_phase.proxy_link_feasibility_b27 --out data/processed/b27_full_2026-11-27_v1
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py project_tests_v1 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py harness_v1 ../.venv/bin/python harness/check.py
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py focused_repair1 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_proxy_link_feasibility_b27.py
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py full_v2 ../.venv/bin/python -m phase_by_phase.proxy_link_feasibility_b27 --out data/processed/b27_full_2026-11-27_v2
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py replay_v2 ../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/offline_replay.py --out data/processed/b27_replay_2026-11-27_v2
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py project_tests_final ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py harness_final ../.venv/bin/python harness/check.py
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py inspection_final ../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/inspect_artifacts.py
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py focused_final ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_proxy_link_feasibility_b27.py
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py project_tests_final50 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py focused_repair2 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_proxy_link_feasibility_b27.py
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py full_v3 ../.venv/bin/python -m phase_by_phase.proxy_link_feasibility_b27 --out data/processed/b27_full_2026-11-27_v3
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py harness_repair2 ../.venv/bin/python harness/check.py
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py replay_v3 ../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/offline_replay.py --out data/processed/b27_replay_2026-11-27_v3
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py project_tests_repair2 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/run.py inspection_v3 ../.venv/bin/python data/processed/b27_execution_2026-11-27_v1/inspect_artifacts_v3.py
```

Every listed command exited **0**. Focused counts: initial 42, repair1 48,
50 before repair2, final **51**. Project counts: preliminary 506, revised 512/514, final **515**
(with six pre-existing warnings: five DuckDB deprecations and one joblib
physical-core warning). All three harness runs report **PASS**. Final run timings and exact logs are
recorded in `commands.jsonl`; the full-v3/replay-v3 counts match full-v2. Synthetic checks cover source authentication,
first-public/label-version separation, exact integer keys above 2^53, strict
public dates and ties, future/missing dates, malformed keys, whole-record and
measurement withdrawal, no measurement, version/outcome mismatch, high-fanout,
duplicate keys, unknown labels, target/unrelated exclusions and B18 non-gating.

The implementation/replay and artifacts are reviewable. **Independent verdict
and adjudication of the initial source-access violation remain outstanding.**
