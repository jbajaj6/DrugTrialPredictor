# B25 exact preferred-name candidate rescue: builder handoff

**BLOCKED/PARTIAL acquisition; PASS_SYNTHETIC engineering.** Independent evaluation has reproduced the synthetic checks and the failed-pilot cache replay. The real-data acceptance gate is **not satisfied**: the environment cannot resolve `www.ebi.ac.uk`. Ten pilot names exhausted their two attempts with `URLError`, no HTTP status, and no response bytes. The full command correctly refused the failed pilot before creating a full cache/output or making any further request. A complete 60-name acquisition and full offline replay remain unexecuted. No preferred-name candidate evidence was obtained, and no real-data pass is claimed.

## Scope and frozen inputs

Read before implementation: `AGENTS.md`, `skills/structured-trials/SKILL.md`, `harness/EXECUTION_RULES.md`, frozen B25 ledger section/prompt, and the B23/B24 builder and independent-evaluation handoffs. Only the new B25 module, its focused test, this handoff, and new ignored B25 data artifacts were written. B18/B23/B24 implementations, the ledger, README, source snapshots and previous reports/caches were not edited. No result or final-holdout source was opened. No model or linkage policy was changed.

The module authenticates all three ledger-pinned files **before reading their names or preparing request URLs**:

| B23 input | SHA-256 |
| --- | --- |
| `data/raw/b23_chembl_cache_100_2026-11-27_v1/index.json` | `269c2f8b72d083a869858b1a2312d7c3413eb9d114fdcfcdd7be5714f4c385d2` |
| `data/processed/b23_pre_100_2026-11-27_v1/pre_acquisition_manifest.json` | `6ee1379dd8498f623a35eda9a559f58de3f56acd8ee20f08db4b7f643bacdfcf` |
| `data/processed/b23_pilot_100_2026-11-27_v1/report.json` | `0fa4d6814a40b1dd6510b2684798eb5c75c7a7402971e715df9b49050c1904ec` |

The ledger explicitly pins B23's **v1** pre-manifest, whereas B23's live cache used its later v2 freeze. B25 does not replace that pin or misrepresent v1 as the live-run manifest. It verifies v1's shared 229 names and the digests of its source-only `trials.jsonl` and `name_occurrences.jsonl`. It authenticates all **393 original B23 attempt bodies** against the pinned index and reconstructs original complete-name statuses from those archived pages, including B23's treatment of ambiguous candidates. Reconstructed name and trial counts must equal the pinned report. This reproduced 100 pre-2020 Phase 3 trials, 260 name occurrences, and the original trial statuses **47 candidate-present / 20 no-exact-candidate / 33 unknown**. Source tables and original cache/report remain unchanged; no ChEMBL outcome, approval, phase, or indication field enters B25 semantic evidence.

## Pre-acquisition freeze and protocol

New manifest: `data/processed/b25_pre_2026-11-27_v1/pre_acquisition_manifest.json`.

- Manifest SHA-256: `eb752de11455edc8f583ef5c462ec9cbfd4bde2bb7f104f15e842a073ff26b46`.
- Module SHA-256: `ffd82fa5abaf5ab2c092fbe9a54173d7d186a173b40e22c54bf6814f44403509`.
- Exactly **60 sorted names** selected only by original cache status `page_cap`, all members of B23's frozen 229 names.
- Exactly **180 planned URLs**, offsets 0/100/200, `limit=100`, only `https://www.ebi.ac.uk/chembl/api/data/molecule.json?pref_name__iexact=<encoded name>`.
- Two attempts/page, 10-second timeout, at least 0.3 seconds between request starts, three pages/name, 8 MiB captured-response limit, and 400 total attempts including reused pilot records. Oversize captures are marked truncated and cannot yield evidence.
- TLS certificate and hostname verification are enabled using the configured CA or `certifi`; HTTP redirects are refused. There was **no successful TLS/HTTP exchange in this run**, so configuration is verified synthetically rather than claimed as observed endpoint success.

The manifest was persisted and inspected before the first request. Its mtime precedes every recorded request start. Each online/offline call rebuilds the whole frozen plan from authenticated B23 inputs and the current code hash, refusing input/code/settings/URL tampering. Every attempt is checkpointed with original query/name, page offset, HTTP status, safe error class, UTC request/retrieval times, monotonic request start, body filename, byte SHA-256, truncation flag and stage. Original network error messages are not stored. Failed attempts have empty capture files because no HTTP bytes were received.

The deterministic first ten names are:

1. `1.0% al-8309b ophthalmic solution`
2. `1.75% al-8309b ophthalmic solution`
3. `17 ohpc`
4. `5-aminosalicyclic acid`
5. `5-asa`
6. `5-fluoruracil`
7. `abt-493 also known as glecaprevir`
8. `abt-493/abt-530`
9. `abt-530 also known as pibrentasvir`
10. `al blister-packs with instruction leaflets`

A full run requires all ten pilot names to have complete validated pagination, allowing either a positive preferred-name candidate or a zero preferred-name hit. It copies and authenticates the immutable pilot index and bodies, reuses those ten records, then acquires the remaining fifty under the same manifest and total attempt cap. This is implemented and tested synthetically but blocked in this real run. A 429 stops retries immediately and opens the global circuit. Caps, failures, invalid metadata, wrong preferred names and incomplete pagination cannot add positive evidence.

Every response must have valid integer `page_meta` totals/limit/offset, exact result count, correct next/previous query links, consistent totals across pages, and distinct molecule IDs. Every returned preferred name must pass Python case-insensitive exact `casefold()` equality with the unchanged normalized query string. No dose/salt/punctuation removal or synonym query is performed. A hit is emitted only after complete pagination; partial hits are discarded. Candidate rows retain the original query string, URL/offset, response digest/body, retrieval date, molecule ID and matched preferred name. Zero hits receive exactly `no_preferred_name_hit_molecular_unknown` and never establish synonym absence or clinical identity.

## Exact commands, exits and observed artifacts

All commands below run from `phase-by-phase/`. Logs and reproducible inspection script are in `data/processed/b25_execution_2026-11-27_v1/`; they are coordinator handoff evidence rather than ledger edits. Redirections below preserve stdout/stderr verbatim.

```sh
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_prefname_rescue_b25.py > data/processed/b25_execution_2026-11-27_v1/focused_initial.log 2>&1
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.prefname_rescue_b25 prepare --out data/processed/b25_pre_2026-11-27_v1 > data/processed/b25_execution_2026-11-27_v1/prepare.log 2>&1
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.prefname_rescue_b25 pilot --pre data/processed/b25_pre_2026-11-27_v1 --cache data/raw/b25_prefname_pilot_cache_2026-11-27_v1 --out data/processed/b25_prefname_pilot_2026-11-27_v1 > data/processed/b25_execution_2026-11-27_v1/pilot.log 2>&1
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.prefname_rescue_b25 full --pre data/processed/b25_pre_2026-11-27_v1 --pilot-cache data/raw/b25_prefname_pilot_cache_2026-11-27_v1 --cache data/raw/b25_prefname_full_cache_2026-11-27_v1 --out data/processed/b25_prefname_full_2026-11-27_v1 > data/processed/b25_execution_2026-11-27_v1/full_blocked.log 2>&1
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests > data/processed/b25_execution_2026-11-27_v1/full_tests.log 2>&1
../.venv/bin/python harness/check.py > data/processed/b25_execution_2026-11-27_v1/harness.log 2>&1
PYTHONPATH=src ../.venv/bin/python data/processed/b25_execution_2026-11-27_v1/inspect_artifacts.py > data/processed/b25_execution_2026-11-27_v1/inspection.log 2>&1
```

| Command | Exit | Observed result |
| --- | ---: | --- |
| Focused tests | 0 | **24 passed** in 4.76 seconds. No failing focused run. |
| Prepare | 0 | 60 names; manifest/code digests above; before network. |
| Pilot | 0 | 10/10 pilot records; 20 attempts; **pilot protocol pass false**. CLI success means a conservatively recorded attempt/replay, not successful acquisition. |
| Full | **1** | Failed pilot gate, exact traceback preserved in `full_blocked.log`; full cache/output directories do not exist. No additional requests. |
| Full test suite | 0 | **430 passed**, six environment warnings: five existing DuckDB deprecations and joblib physical-core detection. 50.35 seconds. |
| Harness | 0 | **PASS**. |
| Artifact inspection | 0 | Every pilot/pre/cache/output artifact inspected; all 393 original B23 body digests and three pins rechecked; both replays match all six output files. |

The exact final full-command failure is:

```text
ValueError: Pilot protocol gate failed; no full acquisition authorized
```

The separate diagnostic command was:

```sh
../.venv/bin/python - <<'PY' > data/processed/b25_execution_2026-11-27_v1/network_diagnostic.log 2>&1
import socket
try:
 print('DNS',socket.getaddrinfo('www.ebi.ac.uk',443))
except OSError as e:
 print('DNS_ERROR',type(e).__name__,e.errno,str(e))
PY
```

It exited 0 while recording the caught failure exactly: `DNS_ERROR gaierror 8 [Errno 8] nodename nor servname provided, or not known`. No diagnostic endpoint request was made. Permissions specify restricted network and approval policy `never`; no escalation, alternate acquisition route or additional pilot was attempted.

Builder offline **pilot** replay, exit 0, with transport explicitly forbidden:

```sh
PYTHONPATH=src ../.venv/bin/python - <<'PY' > data/processed/b25_execution_2026-11-27_v1/pilot_offline_replay.log 2>&1
from pathlib import Path
from phase_by_phase import prefname_rescue_b25 as b
pre=Path('data/processed/b25_pre_2026-11-27_v1')
cache=Path('data/raw/b25_prefname_pilot_cache_2026-11-27_v1')
original=Path('data/processed/b25_prefname_pilot_2026-11-27_v1')
out=Path('data/processed/b25_prefname_pilot_replay_2026-11-27_v1')
b.transport=lambda _: (_ for _ in ()).throw(AssertionError('offline must not access network'))
report=b.summarize(pre,cache,out,'pilot')
assert b.verify_output(original)==b.verify_output(out)
assert {p.name:p.read_bytes() for p in original.iterdir()}=={p.name:p.read_bytes() for p in out.iterdir()}
print({'all_files_byte_identical':len(list(out.iterdir())),'report':report})
PY
```

This checks the same frozen manifest, cache body digests and **10/10 pilot** accounting. It is not a 60/60 full acquisition replay. The implemented full offline CLI requires `--compare` to verify original output bytes; running it without a successful full cache is inappropriate here.

No targeted code repair rounds were needed or used. No code changed after the pre-acquisition freeze. Operational failures were retained rather than repaired away: all 20 DNS-blocked attempts; the full-gate refusal above; an initial evaluator spawn failed with `invalid thread-store request: no rollout found for thread id 01a21bcc-ca83-7250-b9c9-90029b7e121e`, then a separate-context evaluator launched successfully. An initial read-only repository discovery command `rg -n 'B25|B23|B24' harness/TASK_LEDGER.md && cat pyproject.toml .gitignore` exited 1 with `cat: pyproject.toml: No such file or directory`; no project file was changed in response. These are not passing real-data checks.

Synthetic tests cover URL encoding/filter/host safety, page limits, complete multipage evidence, malformed/missing metadata, inconsistent totals, duplicate IDs, exact and wrong preferred names, zero-hit unknowns, 429 circuit, transport exceptions, retry/error bytes, oversize capture, spacing, pilot-before-full reuse, total-attempt accounting, input/code/manifest/cache/output tampering, overwrite refusal, verified TLS/redirect refusal, and deterministic complete offline replay. The 400-attempt outer guard exceeds the structural maximum of 360 attempts for 60 names × 3 pages × 2 attempts; tests also verify pilot attempts are counted in full totals.

## Artifact accounting and scientific limits

Pilot cache: `data/raw/b25_prefname_pilot_cache_2026-11-27_v1`; index SHA-256 `6b5d12be7ab6b760b9e9675bc4711135430dba32b0985c9a39576ac438e84f42`. It contains `index.json` and 20 distinct empty response-capture files with matching digests. All 20 attempts have status null and safe error class `URLError`. Minimum monotonic request-start spacing was **0.302503208 seconds**. No bytes were truncated and no 429 was observed; no HTTP response of any kind was observed.

Pilot output: `data/processed/b25_prefname_pilot_2026-11-27_v1`. Builder replay: `data/processed/b25_prefname_pilot_replay_2026-11-27_v1`. Independent replay: `data/processed/b25_eval_pilot_replay_2026-11-27_v1`. All six files match byte-for-byte in both replays: `name_status.jsonl` (10 rows), `preferred_name_candidates.jsonl` (0), `name_occurrences.jsonl` (10), `trial_coverage.jsonl` (100), `report.json`, and `manifest.json`. The manifest hashes all five content files and pins pre/cache/code digests. Pilot trial rows retain original B23 status separately from the positive-only augmented status.

`data/processed/b25_execution_2026-11-27_v1/blocked_60_name_accounting.jsonl` accounts for all **60 frozen names** without fabricating a full acquisition: **10 attempted failures / 50 unattempted because the pilot gate failed**, all molecular-unknown. `inspection.json` records that distinction, output counts, hashes and scientific report. This is plan accounting, **not 60/60 acquired-name accounting** or a full B25 evidence report.

There are **zero observed positive additions**, rather than evidence that preferred-name matches are absent. Original B23 trial states remain **47/20/33** and the positive-only augmented sample bounds remain **47%–80%**, lower-bound increase **0 percentage points**. These are partial-identification bounds within B23's 100 sampled trials, not population bounds for the 19,576-trial frame. Population sampling uncertainty and clinical identity precision remain unquantified. A preferred-name endpoint cannot establish synonym absence, equivalence of clinical regimens, active ingredients or historical availability; even a future positive-only addition would be retrospective candidate evidence, not linkage validation or model performance.

## Independent evaluation and remaining gate

The independent evaluator inspected the implementation/tests, reran focused/full/harness checks and audited the pilot cache/pre/output. Its exact commands and logs are under `data/processed/b25_eval_2026-11-27_v1/`:

- `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_prefname_rescue_b25.py`: exit 0, **24 passed** (4.16 s).
- `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests`: exit 0, **430 passed**, six existing environment warnings (48.93 s).
- `../.venv/bin/python harness/check.py`: exit 0, **PASS**.
- `PYTHONPATH=src ../.venv/bin/python data/processed/b25_eval_2026-11-27_v1/audit_pilot.py`: exit 0, pinned hashes, 10 pilot names/20 attempts, conservative status, five output digests and six-file replay identity verified. Minimum UTC request-start gap 0.302508 s. Its fresh offline replay used the same `summarize(..., 'pilot')` path with a network-forbidden transport.
- `PYTHONPATH=src ../.venv/bin/python data/processed/b25_eval_2026-11-27_v1/replay_pilot.py data/processed/b25_eval_pilot_replay_2026-11-27_v2`: exit 0, a second fresh independent offline pilot replay, all six files byte-identical with transport forbidden. The script and replay log are preserved in the evaluator evidence directory.

Independent verdict: **PASS_SYNTHETIC engineering; BLOCKED/PARTIAL acquisition**. There is no independent real-data acceptance. Resuming acquisition requires a permitted environment with working DNS/HTTPS, a fresh immutable pilot cache/output under the unchanged code/input manifest, then a passing pilot, all 60 accounted name searches, full offline byte replay, artifact inspection and mandatory independent acceptance. The failed artifacts must remain intact. The 400-trial scale, clinical linkage and model changes remain unauthorized.
