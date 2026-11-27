# B20 repair 1: independent verified-CA evaluation (2026-11-27)

**Verdict: PASS_REAL_DATA_CHECKS for the transport repair and offline replay.** The repaired transport obtained one verified HTTPS response without `SSL_CERT_FILE`. The fresh offline replay reproduces every semantic artifact from the immutable v2 online acquisition. This does not upgrade retrospective exact-name candidates to verified clinical identities or historical at-checkpoint features.

## Scope and diff

I inspected the final working tree against the previously audited v2 implementation. The bounded repair adds `certifi>=2024.2.2` to `requirements.txt`; imports `os`, `ssl`, and `certifi` in `src/phase_by_phase/bridge_b20.py`; and changes only the transport's `urlopen` call to use `ssl.create_default_context(cafile=os.environ.get('SSL_CERT_FILE') or certifi.where())`. The HTTPS URL, 10-second timeout, 8 MiB body bound, retry/circuit settings, cache schema, matching, sampling, and source joins are unchanged. `tests/test_bridge_b20.py` adds two no-network tests inspecting the actual context passed to `urlopen`: both the certifi default and an explicitly configured distinct CA file require `ssl.CERT_REQUIRED` and hostname checking. The B20 builder handoff documents the repair. The B20 source and test files are currently untracked, so the comparison used the original v2 code reviewed during the prior evaluation, the current source, and the two manifests' pinned code hashes; `git diff` alone cannot show changes within untracked files.

The default certificate bundle is the installed certifi 2024.8.30 file, SHA-256 `94edeb66e91774fcae93a05650914e29096259a5c7e871a1f65d461ab5201b47`. A missing or invalid configured CA file fails closed as a transport error; the code never uses an unverified context or turns off hostname checking. The cache records only the safe exception class, not exception text or credentials.

## Commands and results

All commands ran from `phase-by-phase/`:

| Command | Exit | Observed result |
| --- | ---: | --- |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_bridge_b20.py` | 0 | 40 passed |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 0 | 349 passed, five existing DuckDB deprecation warnings |
| `../.venv/bin/python harness/check.py` | 0 | PASS |
| Read-only comparison script below | 0 | 16 semantic hashes and report byte-identical; 33 pinned source hashes and 223 cached body digests valid |
| Bounded live transport smoke below | 0 | HTTP 200, 27,512 response bytes, no error/truncation; no cache or trial output written |

The builder's fresh replay command was:

```sh
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.bridge_b20 \
  --out data/processed/b20_offline_verified_ca_replay_2026-11-27_v1 \
  --cache data/raw/b20_chembl_cache_network_2026-11-27_v2 --mode offline
```

My read-only comparison ran:

```sh
PYTHONPATH=src ../.venv/bin/python - <<'PY'
import hashlib, json, ssl
from pathlib import Path
import certifi
from phase_by_phase import bridge_b20 as b

root = Path.cwd()
original = root / 'data/processed/b20_pilot_network_2026-11-27_v2'
replay = root / 'data/processed/b20_offline_verified_ca_replay_2026-11-27_v1'
j = lambda p: json.loads(p.read_text())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
a, z = j(original / 'manifest.json'), j(replay / 'manifest.json')
assert sha(Path(b.__file__)) == z['code_sha256']
assert a['code_sha256'] != z['code_sha256']
assert (a['mode'], z['mode']) == ('online', 'offline')
assert a['ordered_names'] == z['ordered_names']
assert a['selected_trials'] == z['selected_trials']
assert a['source_sha256'] == z['source_sha256'] and len(a['source_sha256']) == 33
assert a['cache_index_sha256'] == z['cache_index_sha256']
assert a['semantic_sha256'] == z['semantic_sha256']
assert a['report_sha256'] == z['report_sha256']
for name, digest in a['semantic_sha256'].items():
    assert sha(original / name) == sha(replay / name) == digest, name
assert sha(original / 'report.json') == sha(replay / 'report.json') == a['report_sha256']
for path, digest in a['source_sha256'].items():
    assert sha(root / path) == digest, path
cache = root / a['cache']
assert sha(cache / 'index.json') == a['cache_index_sha256']
index = j(cache / 'index.json')
body_count = 0
for record in index['records'].values():
    for attempt in record['attempts']:
        body_count += 1
        assert sha(cache / attempt['body_file']) == attempt['sha256']
assert body_count == 223
context = ssl.create_default_context(cafile=certifi.where())
assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
print('PASS', z['code_sha256'], len(a['semantic_sha256']),
      len(a['source_sha256']), body_count, a['report_sha256'])
PY
```

The original online v2 manifest pins code SHA-256 `d2ca6d33782bc92f220ec2738ff9ee86c34d125a8d5c97c96bef3cd60a6664c6`; the repaired replay manifest and current source pin `dcff9e8369731d0fae40c30f47a55b4457014649e209a45c1f7eb7da942542b4`. Both have the same 16 semantic file digests and report SHA-256 `70311ff375f32b5264c0c40300213815bb347fad2e118d46a87af4acfeeb173c`. Mode/code metadata intentionally make the manifest hashes differ.

The coordinator-requested single public-service smoke used the repaired transport **without** the environment override:

```sh
env -u SSL_CERT_FILE PYTHONPATH=src ../.venv/bin/python -c 'import ssl; from phase_by_phase import bridge_b20 as b; status, body, error, truncated=b.transport(b.search_url("aspirin")); print({"status":status,"bytes":len(body),"error_class":error,"truncated":truncated,"verify_mode":ssl.CERT_REQUIRED}); assert status==200 and error is None and not truncated and len(body)>0'
```

It exited 0 with `status=200`, `bytes=27512`, `error_class=None`, and `truncated=False`. The request used the fixed public HTTPS ChEMBL search endpoint, a 10-second timeout, certificate verification, and hostname checking. The body was neither saved nor treated as evidence for any project trial.

## Remaining scientific limits

The online v2 cache remains a bounded, incomplete retrospective annotation: 200 alphabetically first names of 369 were queried; 72 names had one exact candidate, 6 ambiguous exact candidates, 44 complete no-exact searches, 67 truncated searches, 11 failed searches, and 169 names over budget. Truncations and failures are unresolved, not negatives. The alphabetical subset is nonrepresentative. The 140 candidate-occurrence rows have exact text evidence only; human adjudication is blank, clinical identity and historical ChEMBL availability are unknown, and no precision, efficacy, cross-phase validity, or model score is established. No 2024+ holdout outcome was opened for this evaluation.
