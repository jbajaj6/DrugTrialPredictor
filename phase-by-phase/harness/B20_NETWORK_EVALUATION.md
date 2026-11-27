# B20 network-cache independent evaluation (2026-11-27)

**Verdict: PASS_REAL_DATA_CHECKS for the bounded retrospective molecular-candidate pilot.** This accepts source-key preservation, bounded acquisition, archived response evidence, exact-name candidate annotation, and offline replay. It does **not** accept clinical molecule identity, candidate precision, historical ChEMBL availability at a trial checkpoint, an efficacy label, or a predictive model.

I evaluated the fresh online run at `data/processed/b20_pilot_network_2026-11-27_v2/` and its cache at `data/raw/b20_chembl_cache_network_2026-11-27_v2/`. I made no remote requests and did not read final-holdout outcomes. The online run was made by the coordinator with `SSL_CERT_FILE` pointing to an installed certifi CA bundle; TLS verification remained enabled. The earlier source-only run was blocked by certificate verification and is not evidence of absent chemical matches.

## Executed checks

Run from `phase-by-phase/`:

| Command | Exit | Observed result |
| --- | ---: | --- |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_bridge_b20.py` | 0 | 38 passed |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 0 | 347 passed, five existing deprecation warnings |
| `python3 harness/check.py` | 0 | PASS |
| `PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.bridge_b20 --out data/processed/b20_eval_offline_2026-11-27_v1 --cache data/raw/b20_chembl_cache_network_2026-11-27_v2 --mode offline --seed 20261127 --name-limit 200` | 0 | Report and all 16 semantic JSONL files byte-identical to the online run |
| Independent read-only Python audit below | 0 | All assertions passed; no transport invoked |

The test and harness commands preceded the online run. At that time, the repair was an environment CA setting, not a code change: the online manifest's code SHA-256 was `d2ca6d33782bc92f220ec2738ff9ee86c34d125a8d5c97c96bef3cd60a6664c6`, the code audited by those tests and the initial read-only v2 audit. An initial sandboxed test invocation could not load the project Python framework (exit 134); the read-only runtime-access retries above passed. **A subsequent targeted code repair began after this v2 evaluation.** This verdict is tied to the pinned v2 code and cache, not the later working-tree state; post-repair acceptance requires fresh tests and replay against the repaired code.

The independent audit recomputed the sample from pinned sources, compared exact source-child multisets, verified 33 input hashes, every cache body digest, the code hash, report hash, and 16 semantic file hashes, then independently reparsed cached responses and reconstructed candidate-occurrence rows:

```sh
PYTHONPATH=src ../.venv/bin/python - <<'PY'
import collections, hashlib, json
from pathlib import Path
from datetime import datetime
from phase_by_phase import bridge_b20 as b

root = Path.cwd()
out = root / 'data/processed/b20_pilot_network_2026-11-27_v2'
replay = root / 'data/processed/b20_eval_offline_2026-11-27_v1'
old = root / 'data/processed/b20_pilot_2026-11-27_v1'
load = lambda p: [json.loads(s) for s in p.read_text().splitlines()]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
canon = lambda xs: collections.Counter(
    json.dumps(x, sort_keys=True, ensure_ascii=False, default=str) for x in xs)
m = json.loads((out / 'manifest.json').read_text())
r = json.loads((out / 'report.json').read_text())
# The manifest pins the original v2 code. A later repair may change the
# working tree, so do not substitute the current code hash for the v2 hash.
assert m['code_sha256'] == 'd2ca6d33782bc92f220ec2738ff9ee86c34d125a8d5c97c96bef3cd60a6664c6'
assert sha(out / 'report.json') == sha(replay / 'report.json') == m['report_sha256']
assert len(m['source_sha256']) == 33
for p, digest in m['source_sha256'].items():
    assert sha(root / p) == digest, p
for p, digest in m['semantic_sha256'].items():
    assert sha(out / p) == sha(replay / p) == digest, p
source, _ = b.load_sources()
selected, counts = b.select_trials(
    source['trials'], source['exposures'], source['alias_review'], m['seed'])
assert canon(selected) == canon(m['selected_trials']) == canon(load(out / 'trials.jsonl'))
assert counts == m['sample_counts'] == r['sample_counts']
tables = b.extract(source, selected)
for label, rows in tables.items():
    assert canon(rows) == canon(load(out / (label + '.jsonl'))), label
    assert sha(out / (label + '.jsonl')) == sha(old / (label + '.jsonl')), label
assert all(x['checkpoint_date'] < '2020-01-01' for x in load(out / 'trials.jsonl'))
index = json.loads((root / m['cache'] / 'index.json').read_text())
assert sha(root / m['cache'] / 'index.json') == m['cache_index_sha256']
names = sorted({x['normalized_name'] for x in b.name_occurrences(tables)
                if x['normalized_name']})
assert names == m['ordered_names'] == index['names'] == sorted(index['records'])
assert len(names) == 369 and m['name_limit'] == index['name_limit'] == 200
states, evidence = {}, []
attempt_status = collections.Counter()
for i, name in enumerate(names):
    rec = index['records'][name]
    assert rec['url'] == b.search_url(name)
    if i < 200:
        assert rec['attempts'] and len(rec['attempts']) <= 2
    else:
        assert not rec['attempts'] and rec['reason'] == 'unqueried_name_budget'
    for attempt in rec['attempts']:
        attempt_status[str(attempt['status'])] += 1
        assert sha(root / m['cache'] / attempt['body_file']) == attempt['sha256']
        assert attempt['url'] == rec['url'] and not attempt['byte_truncated']
        assert datetime.fromisoformat(attempt['retrieved_at']).utcoffset().total_seconds() == 0
    hits, state = b.match_response(name, rec, root / m['cache'])
    states[name] = state
    evidence.extend(hits)
assert collections.Counter(states.values()) == r['name_status_counts']
assert canon(evidence) == canon(load(out / 'chembl_evidence.jsonl'))
occurrences = load(out / 'name_occurrences.jsonl')
expected = []
for occurrence in occurrences:
    for hit in evidence:
        if hit['normalized_name'] == occurrence['normalized_name'] and hit['exact_match']:
            expected.append({**occurrence,
                **{k: v for k, v in hit.items() if k != 'normalized_name'},
                'candidate_only': True})
candidates = load(out / 'molecular_candidates.jsonl')
assert canon(expected) == canon(candidates)
assert all(c['exact_match'] and c['matched_evidence'] for c in candidates)
assert not any(k in x for x in evidence + candidates
               for k in ('max_phase', 'first_approval', 'indication', 'approval'))
assert all(x['clinical_identity'] == 'unknown'
           and x['historical_chembl_availability'] == 'unknown'
           and x['human_adjudication'] is None
           for x in load(out / 'review_sheet.jsonl'))
print('PASS', len(selected), len(names), len(evidence), len(candidates),
      dict(attempt_status), dict(collections.Counter(states.values())))
source['db'].close()
PY
```

## Evidence and limits

- Exact selected-key quotas were 50 primary single-drug, 25 multi-drug, 25 no-link, 20 shared-control, 15 nonexperimental-only, and 15 alias-collision: **150 distinct trial/version keys, zero shortfalls**. The source multiset comparison retained 284 arms, 366 interventions, 152 aliases, 944 bidirectional assertions, 193 exact-version conditions, 415 B18 exposure rows, 125 alias-review rows, 415 target-exposure rows, and 150 design-provenance rows. The source-only pilot has identical source tables.
- There were **369 unique normalized recorded names**. The lexicographically first **200** were attempted in 223 requests: 189 HTTP 200 responses and 34 no-status `TimeoutError` attempts. Eleven names ultimately failed. The cache records URL, UTC retrieval time, status/error class, response bytes and SHA-256; all were verified.
- Independent cache parsing reproduced 8,626 search-result evidence rows and 101 exact pref-name/synonym evidence hits. The semantic output has 140 candidate-occurrence rows; every one has exact normalized-name evidence. This is not 140 verified trial-drug identities. Seventeen exact evidence hits came from searches whose 100-result page was truncated; those searches remain unresolved despite retaining the hits.
- Name statuses were 72 one exact candidate, 6 ambiguous exact candidates, 44 no exact candidate on a complete response, **67 response-truncated**, **11 API failures**, and 169 unqueried under the name budget. The 67 truncated and 11 failed searches are **unknown, not negatives**. There are 360 unresolved name occurrences and 331 intervention-level review rows with blank human adjudication and unknown clinical identity/historical availability.
- The first-200 **alphabetical** query plan meets the preregistered upper bound but is not representative of all 369 names. Do not extrapolate hit, no-hit, or coverage rates to all names, occurrences, interventions, or trials. Original B18 flags and sample-stratum coverage remain inspectable, but overlapping flags are not mutually exclusive.
- The ChEMBL responses are contemporary annotations. No current `max_phase`, approval, or indication field enters semantic evidence/candidate tables, and no Phase 3 outcome or 2024+ holdout row was used. Exact text equality alone does not verify salt, formulation, biologic, combination regimen, indication, or public availability at the historical checkpoint.
