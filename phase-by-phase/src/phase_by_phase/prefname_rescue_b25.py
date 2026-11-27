"""Frozen B25 positive-only preferred-name acquisition; no clinical linkage.

Only B23's pinned name cache, protocol occurrences and sample metadata are read.
No results, holdout, models, synonyms endpoint or historical feature is accessed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import certifi

ROOT = Path(__file__).resolve().parents[2]
INPUTS = {
    'index': ('data/raw/b23_chembl_cache_100_2026-11-27_v1/index.json',
              '269c2f8b72d083a869858b1a2312d7c3413eb9d114fdcfcdd7be5714f4c385d2'),
    'pre': ('data/processed/b23_pre_100_2026-11-27_v1/pre_acquisition_manifest.json',
            '6ee1379dd8498f623a35eda9a559f58de3f56acd8ee20f08db4b7f643bacdfcf'),
    'report': ('data/processed/b23_pilot_100_2026-11-27_v1/report.json',
               '0fa4d6814a40b1dd6510b2684798eb5c75c7a7402971e715df9b49050c1904ec'),
}
ENDPOINT = 'https://www.ebi.ac.uk/chembl/api/data/molecule.json'
SETTINGS = {'page_size': 100, 'max_pages_per_name': 3, 'attempts_per_page': 2,
            'timeout_seconds': 10, 'min_request_spacing_seconds': 0.3,
            'max_response_bytes': 8 * 1024 * 1024, 'global_live_attempts': 400,
            'pilot_names': 10, 'tls_certificate_and_hostname_verification': True,
            'redirects': 'refused', 'full_run': 'reuse ten pilot records; acquire remaining fifty'}
BOUNDARY = ('Contemporary retrospective preferred-name candidate evidence only. '
            'Zero preferred-name hits do not establish synonym absence or a negative '
            'molecular match. Clinical identity and historical availability remain unknown. '
            'Sample bounds are not population bounds; population sampling uncertainty '
            'is unquantified. No model, linkage policy or 400-trial scale authorization.')
UNKNOWN_ZERO = 'no_preferred_name_hit_molecular_unknown'
POSITIVE = 'preferred_name_candidate_evidence'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def encoded(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def read(path: Path):
    return json.loads(path.read_bytes())


def write_new(path: Path, content: bytes) -> None:
    with path.open('xb') as f:
        f.write(content)


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def page_url(name: str, offset: int) -> str:
    if type(offset) is not int or offset not in (0, 100, 200):
        raise ValueError('Offset outside frozen page plan')
    return ENDPOINT + '?' + urllib.parse.urlencode(
        [('pref_name__iexact', name), ('limit', 100), ('offset', offset)])


def validate_link(link, name: str, offset: int) -> None:
    if not isinstance(link, str):
        raise ValueError('Invalid pagination URL')
    actual = urllib.parse.urlsplit(urllib.parse.urljoin(ENDPOINT, link))
    expected = urllib.parse.urlsplit(page_url(name, offset))
    if ((actual.scheme, actual.netloc, actual.path, actual.fragment) !=
            (expected.scheme, expected.netloc, expected.path, '') or
            sorted(urllib.parse.parse_qsl(actual.query, keep_blank_values=True)) !=
            sorted(urllib.parse.parse_qsl(expected.query, keep_blank_values=True))):
        raise ValueError('Pagination URL outside frozen query')


def parse_page(raw: bytes, name: str, offset: int) -> tuple[list[dict], int]:
    obj = json.loads(raw)
    mols, meta = obj['molecules'], obj['page_meta']
    total = meta['total_count']
    if (not isinstance(mols, list) or type(total) is not int or total < 0 or
            type(meta['offset']) is not int or meta['offset'] != offset or
            type(meta['limit']) is not int or meta['limit'] != 100 or
            offset > total or len(mols) != min(100, total - offset)):
        raise ValueError('Invalid page metadata/count')
    # Validate the next link, but never follow a server-supplied URL.
    if offset + len(mols) < total:
        # A fourth page is outside our frozen plan: validate its query separately.
        next_offset = offset + 100
        if next_offset <= 200:
            validate_link(meta['next'], name, next_offset)
        else:
            link = meta['next']
            if not isinstance(link, str):
                raise ValueError('Missing next page')
            expected = page_url(name, 200).replace('offset=200', 'offset=300')
            a = urllib.parse.urlsplit(urllib.parse.urljoin(ENDPOINT, link))
            e = urllib.parse.urlsplit(expected)
            if ((a.scheme, a.netloc, a.path, a.fragment) != (e.scheme, e.netloc, e.path, '') or
                    sorted(urllib.parse.parse_qsl(a.query)) != sorted(urllib.parse.parse_qsl(e.query))):
                raise ValueError('Invalid capped next page')
    elif meta['next'] is not None:
        raise ValueError('Unexpected next page')
    if offset:
        validate_link(meta['previous'], name, offset - 100)
    elif meta['previous'] is not None:
        raise ValueError('Unexpected previous page')
    for m in mols:
        if (not isinstance(m, dict) or not isinstance(m.get('pref_name'), str) or
                m['pref_name'].casefold() != name.casefold() or
                not isinstance(m.get('molecule_chembl_id'), str) or
                not re.fullmatch(r'CHEMBL[0-9]+', m['molecule_chembl_id'])):
            raise ValueError('Wrong or missing exact preferred-name evidence')
    return mols, total


def _normal(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split()) if value else None


def baseline() -> dict:
    """Authenticate all three pins before reading names or making query plans."""
    for path, digest in INPUTS.values():
        if sha(ROOT / path) != digest:
            raise ValueError('Pinned B23 input hash mismatch: ' + path)
    index, pre, report = (read(ROOT / INPUTS[k][0]) for k in ('index', 'pre', 'report'))
    names = pre['ordered_names']
    selected = sorted(n for n, r in index['records'].items() if r['status'] == 'page_cap')
    if (len(names) != 229 or names != sorted(set(names)) or index['names'] != names or
            set(index['records']) != set(names) or len(selected) != 60):
        raise ValueError('B23 frozen name selection/accounting mismatch')
    graph = {}
    # These two source-only tables suffice; do not open any outcomes or other sources.
    for label in ('trials.jsonl', 'name_occurrences.jsonl'):
        path = (ROOT / INPUTS['pre'][0]).parent / label
        if sha(path) != pre['graph_sha256'][label]:
            raise ValueError('B23 protocol graph digest mismatch')
        graph[label] = rows(path)
    trials, occurrences = graph['trials.jsonl'], graph['name_occurrences.jsonl']
    keys = [(r['nct_id'], r['nct_version']) for r in trials]
    if (len(keys) != 100 or len(set(keys)) != 100 or
            any(r['pure_phase'] != 'PHASE3' or not '1900-01-01' <= r['checkpoint_date'] < '2020-01-01'
                for r in trials) or
            any((o['nct_id'], o['nct_version']) not in keys for o in occurrences)):
        raise ValueError('B23 source-only sample/key/date mismatch')
    if sorted({o['normalized_name'] for o in occurrences if o['normalized_name']}) != names:
        raise ValueError('B23 occurrence name accounting mismatch')
    cache = (ROOT / INPUTS['index'][0]).parent
    statuses, body_count, seen = {}, 0, set()
    for name in names:
        record = index['records'][name]
        for page in record['pages']:
            for a in page['attempts']:
                f = a['body_file']
                if Path(f).name != f or f in seen or sha(cache / f) != a['sha256']:
                    raise ValueError('B23 response body digest/uniqueness mismatch')
                seen.add(f)
                body_count += 1
        if record['status'] != 'complete':
            statuses[name] = record['status']
            continue
        exact_ids, expected, total = set(), 0, None
        for page in record['pages']:
            good = [a for a in page['attempts'] if a['status'] == 200 and
                    not a['error_class'] and not a['byte_truncated']]
            if len(good) != 1 or page['offset'] != expected:
                raise ValueError('B23 complete pagination mismatch')
            obj = read(cache / good[0]['body_file'])
            mols, meta = obj['molecules'], obj['page_meta']
            n = meta['total_count']
            if (type(n) is not int or n < 0 or meta['offset'] != expected or
                    (total is not None and total != n) or len(mols) > 100 or
                    bool(meta['next']) != (expected + len(mols) < n)):
                raise ValueError('B23 complete metadata mismatch')
            total = n
            expected += len(mols)
            for m in mols:
                values = [m.get('pref_name')]
                for s in m['molecule_synonyms']:
                    values.extend((s.get('molecule_synonym'), s.get('synonyms')))
                if any(_normal(v) == name for v in values):
                    exact_ids.add(m['molecule_chembl_id'])
        if total is None or total != expected:
            raise ValueError('B23 incomplete search called complete')
        statuses[name] = ('one_exact_candidate' if len(exact_ids) == 1 else
                          'ambiguous_exact_candidates' if exact_ids else 'no_exact_candidate')
    if body_count != index['attempts_total'] or dict(Counter(statuses.values())) != report['name_status_counts']:
        raise ValueError('B23 original name statuses differ from pinned report')
    by_trial = defaultdict(list)
    for o in occurrences:
        by_trial[o['nct_id'], o['nct_version']].append(statuses.get(o['normalized_name'], 'missing_recorded_name'))
    baseline_trials = []
    for t in sorted(trials, key=lambda r: (r['nct_id'], r['nct_version'])):
        states = by_trial[t['nct_id'], t['nct_version']]
        state = ('unknown_no_drug_name' if not states else
                 'candidate_evidence_present' if 'one_exact_candidate' in states else
                 'unknown' if any(s != 'no_exact_candidate' for s in states) else
                 'no_exact_candidate_evidence')
        baseline_trials.append({**t, 'original_b23_status': state})
    if dict(Counter(t['original_b23_status'] for t in baseline_trials)) != report['trial_status_counts']:
        raise ValueError('B23 original trial statuses differ from pinned report')
    return {'ordered_names': selected, 'original_name_statuses': statuses,
            'trials': baseline_trials, 'occurrences': occurrences,
            'b23_report': report, 'verified_b23_body_count': body_count}


def frozen_plan() -> dict:
    data = baseline()
    return {'schema': 'B25-v1', 'inputs': INPUTS, 'code_sha256': sha(Path(__file__)),
            'settings': SETTINGS, 'boundary': BOUNDARY, **data,
            'urls': {n: [page_url(n, o) for o in (0, 100, 200)] for n in data['ordered_names']}}


def prepare(out: Path) -> dict:
    if out.exists():
        raise FileExistsError(out)
    manifest = frozen_plan()
    out.mkdir(parents=True)
    write_new(out / 'pre_acquisition_manifest.json', encoded(manifest))
    return {'names': 60, 'sha256': sha(out / 'pre_acquisition_manifest.json')}


def load_pre(pre: Path) -> dict:
    manifest = read(pre / 'pre_acquisition_manifest.json')
    # Rebuild the entire plan from authenticated B23 inputs and current code.
    if manifest != json.loads(encoded(frozen_plan())):
        raise ValueError('Frozen manifest/code/settings/input mismatch')
    return manifest


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def transport(url: str) -> tuple[int | None, bytes, str | None, bool]:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query)
    name, offset = query['pref_name__iexact'][0], int(query['offset'][0])
    if url != page_url(name, offset):
        raise ValueError('Transport URL outside frozen endpoint')
    context = ssl.create_default_context(cafile=os.environ.get('SSL_CERT_FILE') or certifi.where())
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=context))
    raw, status, error, truncated = bytearray(), None, None, False
    response = None
    try:
        request = urllib.request.Request(url, headers={'Accept': 'application/json',
                                                       'User-Agent': 'B25-preferred-name-audit/1.0'})
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
            error = 'HTTPError'
        status = response.code
        while len(raw) <= SETTINGS['max_response_bytes']:
            chunk = response.read(min(65536, SETTINGS['max_response_bytes'] + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        truncated = len(raw) > SETTINGS['max_response_bytes']
    except Exception as exc:
        # Preserve bytes already read; never persist exception messages/credentials.
        error = type(exc).__name__
    finally:
        if response is not None:
            response.close()
    return status, bytes(raw[:SETTINGS['max_response_bytes']]), error, truncated


def _success(a: dict) -> bool:
    return a['status'] == 200 and a['error_class'] is None and not a['byte_truncated']


def _state(name: str, record: dict, cache: Path) -> tuple[str, list[dict]]:
    """Derive status from raw attempts, including incomplete pages; never trust labels."""
    hits, total, ids = [], None, set()
    for i, page in enumerate(record['pages']):
        offset = i * 100
        if page['offset'] != offset or page['url'] != page_url(name, offset):
            raise ValueError('Noncontiguous or wrong cached page')
        good = [a for a in page['attempts'] if _success(a)]
        if not good:
            return ('rate_limited' if page['attempts'][-1]['status'] == 429 else
                    'global_attempt_cap' if len(page['attempts']) < 2 else
                    'http_or_transport_failure'), []
        try:
            mols, count = parse_page((cache / good[0]['body_file']).read_bytes(), name, offset)
            if total is not None and total != count:
                raise ValueError('Inconsistent total_count')
            total = count
            for m in mols:
                mid = m['molecule_chembl_id']
                if mid in ids:
                    raise ValueError('Duplicate molecule across pages')
                ids.add(mid)
                hits.append({'normalized_name': name, 'matched_pref_name': m['pref_name'],
                    'molecule_chembl_id': mid, 'query_url': page['url'], 'offset': offset,
                    'response_sha256': good[0]['sha256'], 'body_file': good[0]['body_file'],
                    'retrieved_at': good[0]['retrieved_at'], 'clinical_identity': 'unknown'})
        except (ValueError, KeyError, TypeError):
            return 'invalid_or_missing_page', []
        if offset + len(mols) == total:
            if i != len(record['pages']) - 1:
                raise ValueError('Unexpected pages after complete search')
            return (POSITIVE if hits else UNKNOWN_ZERO), hits
    return ('page_cap' if len(record['pages']) == 3 else 'global_attempt_cap'), []


def save_index(cache: Path, index: dict) -> None:
    # This new run's mutable progress index is atomically checkpointed per attempt.
    tmp = cache / 'index.pending'
    write_new(tmp, encoded(index))
    tmp.replace(cache / 'index.json')


def acquire(pre: Path, cache: Path, stage: str, *, pilot: Path | None = None,
            fetch=None, sleeper=time.sleep, clock=time.monotonic) -> dict:
    if cache.exists():
        raise FileExistsError(cache)
    plan = load_pre(pre)
    if stage not in ('pilot', 'full'):
        raise ValueError('Unknown acquisition stage')
    names = plan['ordered_names'][:10] if stage == 'pilot' else plan['ordered_names']
    seed = None
    if stage == 'full':
        if pilot is None:
            raise ValueError('Full acquisition requires validated first-ten pilot')
        seed = replay_index(pre, pilot, 'pilot')
        if not all(r['status'] in (POSITIVE, UNKNOWN_ZERO) for r in seed['records'].values()):
            raise ValueError('Pilot protocol gate failed; no full acquisition authorized')
    cache.mkdir(parents=True)
    index = {'stage': stage, 'names': names, 'settings': SETTINGS,
             'pre_acquisition_sha256': sha(pre / 'pre_acquisition_manifest.json'),
             'records': {}, 'attempts_total': 0, 'pilot_index_sha256': None}
    if seed:
        write_new(cache / 'pilot_index.json', (pilot / 'index.json').read_bytes())
        index['pilot_index_sha256'] = sha(cache / 'pilot_index.json')
        index['records'] = json.loads(json.dumps(seed['records']))
        index['attempts_total'] = seed['attempts_total']
        for r in seed['records'].values():
            for page in r['pages']:
                for a in page['attempts']:
                    write_new(cache / a['body_file'], (pilot / a['body_file']).read_bytes())
    save_index(cache, index)
    fetch = fetch or transport
    last_request, rate_limited = None, False
    for name in names:
        if name in index['records']:
            continue
        record = {'pages': [], 'status': 'in_progress'}
        index['records'][name] = record
        if rate_limited or index['attempts_total'] >= 400:
            record['status'] = 'rate_limit_circuit' if rate_limited else 'global_attempt_cap'
            save_index(cache, index)
            continue
        for offset in (0, 100, 200):
            if index['attempts_total'] >= 400:
                break
            page = {'url': plan['urls'][name][offset // 100], 'offset': offset, 'attempts': []}
            record['pages'].append(page)
            for retry in range(2):
                if index['attempts_total'] >= 400:
                    break
                if last_request is not None:
                    sleeper(max(0, .3 - (clock() - last_request)))
                last_request = clock()
                started = datetime.now(timezone.utc).isoformat()
                try:
                    status, raw, error, truncated = fetch(page['url'])
                except Exception as exc:
                    status, raw, error, truncated = None, b'', type(exc).__name__, False
                if len(raw) > SETTINGS['max_response_bytes']:
                    raw, truncated = raw[:SETTINGS['max_response_bytes']], True
                body = f"{hashlib.sha256(name.encode()).hexdigest()}.{offset}.{retry}.response"
                write_new(cache / body, raw)
                a = {'url': page['url'], 'offset': offset, 'status': status,
                     'error_class': error, 'byte_truncated': truncated, 'body_file': body,
                     'sha256': sha(cache / body), 'request_started_at': started,
                     'request_monotonic': last_request, 'stage': stage,
                     'retrieved_at': datetime.now(timezone.utc).isoformat()}
                page['attempts'].append(a)
                index['attempts_total'] += 1
                save_index(cache, index)
                if _success(a) or status == 429:
                    break
            state, _ = _state(name, record, cache)
            if state != 'global_attempt_cap' or index['attempts_total'] >= 400:
                break
        record['status'], _ = _state(name, record, cache)
        rate_limited = record['status'] == 'rate_limited'
        save_index(cache, index)
    return replay_index(pre, cache, stage)


def replay_index(pre: Path, cache: Path, stage: str) -> dict:
    plan = load_pre(pre)
    index = read(cache / 'index.json')
    names = plan['ordered_names'][:10] if stage == 'pilot' else plan['ordered_names']
    if (stage not in ('pilot', 'full') or index['stage'] != stage or index['names'] != names or
            index['settings'] != SETTINGS or
            index['pre_acquisition_sha256'] != sha(pre / 'pre_acquisition_manifest.json') or
            set(index['records']) != set(names)):
        raise ValueError('Cache selection/manifest/settings/accounting mismatch')
    seed = None
    if stage == 'full':
        if sha(cache / 'pilot_index.json') != index['pilot_index_sha256']:
            raise ValueError('Pilot index digest mismatch')
        seed = read(cache / 'pilot_index.json')
        if (seed['stage'] != 'pilot' or seed['names'] != names[:10] or
                seed['pre_acquisition_sha256'] != index['pre_acquisition_sha256'] or
                seed['settings'] != SETTINGS or set(seed['records']) != set(names[:10]) or
                seed['attempts_total'] != sum(len(p['attempts']) for r in seed['records'].values() for p in r['pages'])):
            raise ValueError('Invalid pilot provenance')
        for n in names[:10]:
            if seed['records'][n] != index['records'][n] or seed['records'][n]['status'] not in (POSITIVE, UNKNOWN_ZERO):
                raise ValueError('Pilot gate or reused record mismatch')
    elif index['pilot_index_sha256'] is not None:
        raise ValueError('Unexpected pilot provenance')
    seen, attempts, circuit, last_times = set(), 0, False, {}
    for name in names:
        r = index['records'][name]
        if len(r['pages']) > 3:
            raise ValueError('Page cap exceeded')
        for page in r['pages']:
            aa = page['attempts']
            if circuit or not 1 <= len(aa) <= 2 or attempts >= 400:
                raise ValueError('Attempt cap/circuit violation')
            for i, a in enumerate(aa):
                expected_stage = 'pilot' if stage == 'pilot' or name in names[:10] else 'full'
                expected_body = f"{hashlib.sha256(name.encode()).hexdigest()}.{page['offset']}.{i}.response"
                if (a['stage'] != expected_stage or a['body_file'] != expected_body or
                        a['url'] != page['url'] or a['offset'] != page['offset'] or
                        a['body_file'] in seen or sha(cache / a['body_file']) != a['sha256'] or
                        (cache / a['body_file']).stat().st_size > SETTINGS['max_response_bytes'] or
                        type(a['byte_truncated']) is not bool or
                        (a['status'] is not None and type(a['status']) is not int)):
                    raise ValueError('Attempt metadata/body digest mismatch')
                start, end = (datetime.fromisoformat(a[k]) for k in ('request_started_at', 'retrieved_at'))
                if start.utcoffset() != timezone.utc.utcoffset(start) or end.utcoffset() != timezone.utc.utcoffset(end) or end < start:
                    raise ValueError('Invalid UTC attempt timestamps')
                if not isinstance(a['request_monotonic'], (float, int)):
                    raise ValueError('Invalid request clock')
                previous = last_times.get(expected_stage)
                if previous is not None and a['request_monotonic'] - previous < .3 - 1e-8:
                    raise ValueError('Request spacing violation')
                last_times[expected_stage] = a['request_monotonic']
                seen.add(a['body_file'])
                attempts += 1
                if attempts > 400 or (i < len(aa) - 1 and (_success(a) or a['status'] == 429)):
                    raise ValueError('Retry/cap violation')
                if a['status'] == 429:
                    circuit = True
        if circuit and not r['pages']:
            expected = 'rate_limit_circuit'
        elif not r['pages']:
            if attempts != 400:
                raise ValueError('Unattempted name without cap/circuit')
            expected = 'global_attempt_cap'
        else:
            expected, _ = _state(name, r, cache)
            # Failures/invalid pages must terminate retrieval for that name.
            for i in range(1, len(r['pages'])):
                prior, _ = _state(name, {'pages': r['pages'][:i]}, cache)
                if prior != 'global_attempt_cap':
                    raise ValueError('Pages continued after terminal response')
        if r['status'] != expected:
            raise ValueError('Cached status differs from raw response state')
    if attempts != index['attempts_total']:
        raise ValueError('Attempt accounting mismatch')
    expected_files = seen | {'index.json'} | ({'pilot_index.json'} if seed else set())
    if {p.name for p in cache.iterdir()} != expected_files:
        raise ValueError('Unaccounted cache artifact')
    return index


def summarize(pre: Path, cache: Path, out: Path, stage: str) -> dict:
    if out.exists():
        raise FileExistsError(out)
    plan, index = load_pre(pre), replay_index(pre, cache, stage)
    statuses, evidence = {}, []
    for n in index['names']:
        status, hits = _state(n, index['records'][n], cache) if index['records'][n]['pages'] else (index['records'][n]['status'], [])
        statuses[n] = status
        evidence.extend(hits)
    positive = {n for n, s in statuses.items() if s == POSITIVE}
    occurrences = [{**o, 'original_b23_name_status': plan['original_name_statuses'].get(o['normalized_name']),
                    'b25_status': statuses[o['normalized_name']],
                    'b25_positive_addition': o['normalized_name'] in positive}
                   for o in plan['occurrences'] if o['normalized_name'] in statuses]
    added = {(o['nct_id'], o['nct_version']) for o in occurrences if o['b25_positive_addition']}
    trials = [{**t, 'b25_positive_addition': (t['nct_id'], t['nct_version']) in added,
               'positive_only_augmented_status': 'candidate_evidence_present'
               if (t['nct_id'], t['nct_version']) in added else t['original_b23_status']}
              for t in plan['trials']]
    original = dict(Counter(t['original_b23_status'] for t in trials))
    augmented = dict(Counter(t['positive_only_augmented_status'] for t in trials))
    yes = augmented.get('candidate_evidence_present', 0)
    unknown = sum(v for k, v in augmented.items() if k.startswith('unknown'))
    report = {'stage': stage, 'planned_names': len(index['names']), 'accounted_names': len(statuses),
              'name_status_counts': dict(Counter(statuses.values())), 'candidate_rows': len(evidence),
              'positive_names': len(positive), 'attempts_total_including_pilot': index['attempts_total'],
              'pilot_protocol_pass': all(s in (POSITIVE, UNKNOWN_ZERO) for n, s in statuses.items()
                                         if n in plan['ordered_names'][:10]),
              'queried_name_occurrences': len(occurrences),
              'positive_name_occurrences': sum(o['b25_positive_addition'] for o in occurrences),
              'sample_trials_with_positive_additions': len(added),
              'newly_candidate_present_sample_trials': sum(t['original_b23_status'] != 'candidate_evidence_present'
                                                         and t['b25_positive_addition'] for t in trials),
              'sample_trials': 100, 'original_b23_trial_status_counts': original,
              'positive_only_augmented_trial_status_counts': augmented,
              'original_b23_sample_bounds': plan['b23_report']['candidate_evidence_trial_bounds'],
              'positive_only_augmented_sample_bounds': [yes / 100, (yes + unknown) / 100],
              'sample_lower_bound_increase': (yes - original.get('candidate_evidence_present', 0)) / 100,
              'population_sampling_uncertainty': 'unquantified', 'clinical_identity': 'unknown',
              'boundary': BOUNDARY}
    name_rows = [{'normalized_name': n, 'original_b23_status': plan['original_name_statuses'][n],
                  'b25_status': statuses[n], 'query_url': plan['urls'][n][0],
                  'candidate_count': sum(e['normalized_name'] == n for e in evidence)} for n in index['names']]
    out.mkdir(parents=True)
    for label, table in [('name_status', name_rows), ('preferred_name_candidates', evidence),
                         ('name_occurrences', occurrences), ('trial_coverage', trials)]:
        write_new(out / (label + '.jsonl'), ''.join(json.dumps(r, sort_keys=True, ensure_ascii=False) + '\n' for r in table).encode())
    write_new(out / 'report.json', encoded(report))
    manifest = {'pre_acquisition_sha256': sha(pre / 'pre_acquisition_manifest.json'),
                'cache_index_sha256': sha(cache / 'index.json'), 'code_sha256': sha(Path(__file__)),
                'output_sha256': {p.name: sha(p) for p in sorted(out.iterdir())}}
    write_new(out / 'manifest.json', encoded(manifest))
    return report


def verify_output(out: Path) -> dict:
    manifest = read(out / 'manifest.json')
    if set(p.name for p in out.iterdir()) != set(manifest['output_sha256']) | {'manifest.json'}:
        raise ValueError('Output artifact accounting mismatch')
    for f, digest in manifest['output_sha256'].items():
        if Path(f).name != f or sha(out / f) != digest:
            raise ValueError('Output bytes/digest mismatch')
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('prepare', 'pilot', 'full', 'offline'))
    p.add_argument('--pre', type=Path)
    p.add_argument('--cache', type=Path)
    p.add_argument('--pilot-cache', type=Path)
    p.add_argument('--compare', type=Path)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    # All new artifacts must be B25-named ignored data directories inside this workspace.
    for dest in (args.out, args.cache):
        if dest is not None and (not dest.resolve().is_relative_to(ROOT / 'data') or
                                 not dest.name.startswith('b25_')):
            p.error('B25 outputs/caches must be new data/**/b25_* directories')
    if args.out.exists():
        raise FileExistsError(args.out)
    if args.mode == 'prepare':
        print(json.dumps(prepare(args.out), sort_keys=True))
        return
    if args.pre is None or args.cache is None:
        p.error('--pre and --cache required')
    stage = 'pilot' if args.mode == 'pilot' else 'full'
    if args.mode != 'offline':
        acquire(args.pre, args.cache, stage, pilot=args.pilot_cache)
    elif args.compare is None:
        p.error('Offline replay requires --compare to verify original output bytes')
    report = summarize(args.pre, args.cache, args.out, stage)
    if args.mode == 'offline':
        before, after = verify_output(args.compare), verify_output(args.out)
        if before != after or any((args.compare / f).read_bytes() != (args.out / f).read_bytes()
                                  for f in before['output_sha256']):
            raise ValueError('Offline replay output bytes differ')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
