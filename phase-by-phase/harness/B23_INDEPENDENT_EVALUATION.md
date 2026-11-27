# B23 independent 100-trial evaluation (2026-11-27)

**Verdict: PASS_REAL_DATA_CHECKS for the frozen 100-trial acquisition and reproducibility gates; scientific coverage is only partially identified.** This accepts the probability draw, exact-version source graph, bounded cached paging, conservative unknown classification, and byte-identical offline replay. It does not accept molecule identity, historical ChEMBL availability, efficacy, a population coverage point estimate, or automatic 400-trial scale-up.

I read `AGENTS.md`, `skills/structured-trials/SKILL.md`, `harness/EXECUTION_RULES.md`, the frozen B23 ledger section and builder prompt before evaluating. The builder's files, cache, and source snapshots were not edited. I did not use the network or inspect final-holdout outcomes.

## Exact commands and results

From `phase-by-phase/`:

| Command | Exit | Result |
| --- | ---: | --- |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_coverage_b23.py` | 0 | 10 passed |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 0 | 393 passed; five existing DuckDB deprecation warnings |
| `../.venv/bin/python harness/check.py` | 0 | PASS |
| `PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.coverage_b23 offline --pre data/processed/b23_pre_100_2026-11-27_v2 --cache data/raw/b23_chembl_cache_100_2026-11-27_v1 --out data/processed/b23_eval_replay_100_2026-11-27_v1` | 0 | Fresh evaluator replay; report and all **14** semantic JSONL files byte-identical to the online output |
| Independent read-only audit below | 0 | Source, cache, pagination, exact-name evidence, occurrence accounting, and bounds passed |

One initial in-memory audit exited **1** because I asserted the builder's preliminary statement of **15** semantic files. The manifest actually contains **14** semantic JSONL files plus `report.json`; no required grain is missing (the occurrence grain is `name_occurrences.jsonl` with `candidate_status`). The count was corrected in the builder handoff and my audit; the corrected audit exited **0**. This was a reporting/assertion mismatch, not a corrupted file or failed replay.

The following read-only check is a compact reproducible version of my source/cache/artifact audit:

```sh
PYTHONPATH=src ../.venv/bin/python - <<'PY'
import collections, hashlib, json
from datetime import datetime
from pathlib import Path
from phase_by_phase import bridge_b20 as b20, coverage_b23 as b23

root = Path.cwd()
pre = root / 'data/processed/b23_pre_100_2026-11-27_v2'
out = root / 'data/processed/b23_pilot_100_2026-11-27_v1'
rep = root / 'data/processed/b23_eval_replay_100_2026-11-27_v1'
cache = root / 'data/raw/b23_chembl_cache_100_2026-11-27_v1'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
j = lambda p: json.loads(p.read_text())
rows = lambda p: [json.loads(s) for s in p.read_text().splitlines()]
canon = lambda xs: collections.Counter(
    json.dumps(x, sort_keys=True, ensure_ascii=False, default=str) for x in xs)
pm, om, report, index = (j(pre/'pre_acquisition_manifest.json'),
                         j(out/'manifest.json'), j(out/'report.json'),
                         j(cache/'index.json'))
assert sha(pre/'pre_acquisition_manifest.json') == (
    om['pre_acquisition_sha256']) == index['pre_acquisition_sha256'] == (
    '790c2aac45db80fe64fb710773aeae7d11f1c7b0aae947dcf7dd676a1a459e95')
assert sha(Path(b23.__file__)) == pm['code_sha256']
assert sha(cache/'index.json') == om['cache_index_sha256']
assert sha(out/'report.json') == sha(rep/'report.json') == om['report_sha256']
assert len(om['semantic_sha256']) == 14
for name, digest in om['semantic_sha256'].items():
    assert sha(out/name) == sha(rep/name) == digest, name
for name, digest in pm['source_sha256'].items():
    assert sha(root/name) == digest, name
for name, digest in pm['graph_sha256'].items():
    assert sha(pre/name) == digest, name
    if name != 'name_occurrences.jsonl':  # output adds candidate_status
        assert sha(out/name) == sha(rep/name) == digest, name
assert pm['ordered_names'] == index['names'] == sorted(index['records'])
assert len(index['names']) == 229
source, _ = b20.load_sources()
frame = {(r['nct_id'], r['nct_version']): r for r in source['trials']}
selected = [frame[x['nct_id'], x['nct_version']] for x in pm['selected_keys']]
extracted = b20.extract(source, selected)
for name in ('trials','arms','interventions','aliases','links',
             'conditions','design_provenance'):
    assert canon(extracted[name]) == canon(rows(pre/(name+'.jsonl'))), name
assert canon(b20.name_occurrences(extracted)) == canon(rows(pre/'name_occurrences.jsonl'))
source['db'].close()
attempts = 0
states = collections.Counter()
hits = []
saved_states = {r['normalized_name']:r['status'] for r in rows(out/'name_status.jsonl')}
for name in index['names']:
    record = index['records'][name]
    states[record['status']] += 1
    assert len(record['pages']) <= 3
    for page in record['pages']:
        assert len(page['attempts']) <= 2
        assert page['url'] == b23.page_url(name, page['offset'])
        for a in page['attempts']:
            attempts += 1
            raw = (cache/a['body_file']).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == a['sha256']
            assert len(raw) <= b23.MAX_BYTES + 1
            assert (a['url'], a['offset']) == (page['url'], page['offset'])
            assert datetime.fromisoformat(a['retrieved_at']).utcoffset().total_seconds() == 0
    if record['status'] == 'complete':
        offset, total = 0, None
        for page in record['pages']:
            assert page['offset'] == offset
            good = [a for a in page['attempts'] if a['status'] == 200
                    and not a['error_class'] and not a['byte_truncated']]
            assert len(good) == 1
            chunk, count = b23.parse_page((cache/good[0]['body_file']).read_bytes(),
                                          name, offset)
            assert total is None or total == count
            total, offset = count, offset + len(chunk)
        assert offset == total
    if record['status'] == 'page_cap':
        assert len(record['pages']) == 3
    status, found = b23.classify(name, record, cache)
    assert status == saved_states[name]
    hits.extend(found)
assert attempts == index['attempts_total'] == 393 <= 1500
assert states == {'complete':156, 'page_cap':60, 'http_or_transport_failure':13}
assert canon(hits) == canon(rows(out/'chembl_exact_candidates.jsonl'))
assert all(h['matched_evidence'] and
           all(b20.normalize(v['value']) == h['normalized_name']
               for v in h['matched_evidence']) for h in hits)
occ = rows(out/'name_occurrences.jsonl')
assert len(occ) == 260
assert all(o['candidate_status'] == saved_states[o['normalized_name']] for o in occ)
trials = rows(out/'trial_coverage.jsonl')
assert collections.Counter(t['status'] for t in trials) == {
    'candidate_evidence_present':47, 'no_exact_candidate_evidence':20, 'unknown':33}
assert report['candidate_evidence_trial_bounds'] == [0.47, 0.8]
assert len(rows(out/'arm_coverage.jsonl')) == 164
assert len(rows(out/'intervention_coverage.jsonl')) == 200
assert all(r['human_adjudication'] is None and r['clinical_identity'] == 'unknown'
           for r in rows(out/'review_sheet.jsonl'))
print('PASS', len(selected), len(index['names']), attempts, dict(states),
      len(hits), len(om['semantic_sha256']))
PY
```

The frozen pre-acquisition manifest SHA-256 is `790c2aac45db80fe64fb710773aeae7d11f1c7b0aae947dcf7dd676a1a459e95`; the B15 frame hash is `7f72e55e525f3841defb872dfa2e33c31a655975d35550357348d33296b01b43`. A separate metadata-only B15 query independently recomputed the same 19,576-record frame and first 100 SHA-256-selected keys, without using B18 flags or results. All **33** pinned source hashes and eight pre-acquisition graph hashes matched. Direct exact-key source multisets matched all 100 trials/design rows, 164 arms, 223 interventions, 66 aliases, 468 preserved bidirectional link rows and 129 conditions. The sampled graph contains 200 `DRUG` interventions and 260 nonblank recorded-name occurrences; all 260 map to the 229 cached name statuses and all 200 DRUG intervention keys are represented.

The cache contains **229/229** planned names, **379** pages and **393** attempts (365 pages with one attempt, 14 with two), below the 1,500-attempt ceiling and the three-page/two-attempt per-page caps. HTTP outcomes were 366 status 200, 25 no-status `TimeoutError` attempts, and two HTTP 400 errors; a recovered timeout is among the 25. The minimum gap between recorded UTC completion times was 0.362 seconds; source code applies at least 0.3 seconds between request starts. All 393 body digests, URLs, offsets and UTC timestamps matched the index; largest body was 268,036 bytes. All 156 `complete` names were checked page-by-page for contiguous offsets, consistent totals and completed pagination. Sixty names hit the three-page cap and 13 had terminal transport/HTTP failure; all 73 remain unknown, not no-match. The complete names classify as 83 one exact candidate, four ambiguous exact candidates and 69 no exact candidate.

There are **91 exact candidate rows**. Every candidate's normalized text matches a preferred name or synonym and each `(normalized_name, molecule_chembl_id)` pair traced uniquely to one archived successful page in a separate audit (zero ambiguous page links). Candidate rows do not carry a direct response SHA/page-offset field, but the normalized-name index plus molecule ID gives an unambiguous cache-page trace in this run; future schemas would be easier to audit with explicit pointers. Returned, original, parent and active IDs remain separate. No maximum-phase, approval, indication, result or holdout field entered candidate semantics; the 200-row review sheet retains blank human adjudication and unknown clinical identity.

Of 164 arms, 73 are experimental, 56 active comparators, 31 placebo comparators, three no-intervention and one sham comparator. Twenty-four selected trials have no resolved DRUG arm assignment. The frozen ledger's **25** multi-DRUG-arm preflight used intervention-direction assertions; the conservative union of both preserved directions flags **26**. The extra is `NCT01223352` version 0 arm ordinal 0: the `arm_group` assertion names DRUG ordinal 0 while the `intervention` assertion names DRUG ordinal 1. Neither assertion was deleted or silently treated as a verified combination. The builder handoff now discloses both definitions.

## Scientific interpretation and scale gate

The 100 sampled trial statuses are **47 candidate-evidence-present, 20 no-exact-candidate-evidence, and 33 unknown**. Assigning all unknowns uncovered/covered gives **47%–80% partial-identification bounds within these 100 sampled trials**, not guaranteed bounds for all 19,576 frame trials. Sampling uncertainty for population extrapolation is unquantified; no point estimate or Wilson interval is warranted. The builder corrected its handoff to say this explicitly. Controls, aliases and combination regimens remain separate; an exact contemporary name is not clinical or historical identity evidence.

**This 100-pilot engineering pass does not authorize a 400-trial run.** The 60 page-capped names and 13 failures leave material unknowns (33/100 trial statuses). The frozen ledger requires a new preregistered acquisition/uncertainty plan rather than claiming population coverage or automatically scaling the current run.
