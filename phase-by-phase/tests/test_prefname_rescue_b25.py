"""Synthetic B25 protocol checks; these are not a real-data acceptance verdict."""
import json
from pathlib import Path
import ssl
import urllib.parse

import pytest

from phase_by_phase import prefname_rescue_b25 as b


def payload(name, offset=0, total=1, **changes):
    mols = [{'molecule_chembl_id': f'CHEMBL{i+1}', 'pref_name': name.upper(),
             'max_phase': 4, 'drug_indications': ['must not enter semantics']}
            for i in range(offset, min(offset + 100, total))]
    nxt = b.page_url(name, offset + 100) if offset + 100 < total and offset < 200 else (
        b.page_url(name, 200).replace('offset=200', 'offset=300') if offset + 100 < total else None)
    meta = {'offset': offset, 'limit': 100, 'total_count': total, 'next': nxt,
            'previous': b.page_url(name, offset - 100) if offset else None}
    meta.update(changes)
    return json.dumps({'molecules': mols, 'page_meta': meta}).encode()


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """Use real freeze/hash machinery against fully synthetic 229-name B23 inputs."""
    root = tmp_path / 'inputs'
    root.mkdir()
    names = [f'a{i:03}' for i in range(229)]
    trials = [{'nct_id': f'NCT{i:08}', 'nct_version': 0, 'pure_phase': 'PHASE3',
               'checkpoint_date': '2010-01-01'} for i in range(100)]
    occ = [{'nct_id': f'NCT{i % 100:08}', 'nct_version': 0, 'intervention_ord': 0,
            'normalized_name': n, 'raw_name': n.upper(), 'origin': 'interventions'}
           for i, n in enumerate(names)]
    graph = {}
    for label, table in [('trials.jsonl', trials), ('name_occurrences.jsonl', occ)]:
        (root / label).write_text(''.join(json.dumps(r) + '\n' for r in table))
        graph[label] = b.sha(root / label)
    records = {}
    for i, name in enumerate(names):
        if i < 60:
            records[name] = {'status': 'page_cap', 'pages': []}
        else:
            raw = json.dumps({'molecules': [], 'page_meta': {'total_count': 0, 'offset': 0, 'next': None}}).encode()
            body = f'{name}.response'
            (root / body).write_bytes(raw)
            records[name] = {'status': 'complete', 'pages': [{'offset': 0, 'attempts': [
                {'status': 200, 'error_class': None, 'byte_truncated': False,
                 'body_file': body, 'sha256': b.sha(root / body)}]}]}
    objects = {
        'index': {'names': names, 'records': records, 'attempts_total': 169},
        'pre': {'ordered_names': names, 'graph_sha256': graph},
        'report': {'name_status_counts': {'page_cap': 60, 'no_exact_candidate': 169},
                   'trial_status_counts': {'unknown': 60, 'no_exact_candidate_evidence': 40},
                   'candidate_evidence_trial_bounds': [0, .6]}}
    pins = {}
    for label, obj in objects.items():
        path = root / (label + '.json')
        path.write_bytes(b.encoded(obj))
        pins[label] = (str(path.relative_to(tmp_path)), b.sha(path))
    monkeypatch.setattr(b, 'ROOT', tmp_path)
    monkeypatch.setattr(b, 'INPUTS', pins)
    pre = tmp_path / 'pre'
    b.prepare(pre)
    return pre


def response(url, total=0):
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    name, offset = query['pref_name__iexact'][0], int(query['offset'][0])
    return 200, payload(name, offset, total), None, False


def run(frozen, cache, *, fetch=response, stage='pilot', pilot=None):
    # A deterministic monotonic fake clock measures the requested sleep as time.
    tick = [0.0]
    return b.acquire(frozen, cache, stage, pilot=pilot, fetch=fetch,
                     clock=lambda: tick[0], sleeper=lambda seconds: tick.__setitem__(0, tick[0] + seconds))


def test_url_encoding_and_strict_links():
    name = "1.75% a/b + crohn's ® & = ? #"
    url = b.page_url(name, 100)
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query) == {
        'pref_name__iexact': [name], 'limit': ['100'], 'offset': ['100']}
    assert '%25' in url and '%2F' in url and '%26' in url
    b.validate_link(url.removeprefix('https://www.ebi.ac.uk'), name, 100)
    for wrong in [url.replace('https:', 'http:'), url.replace('www.ebi.ac.uk', 'evil.example'),
                  url + '&extra=1', url.replace('iexact', 'icontains')]:
        with pytest.raises(ValueError):
            b.validate_link(wrong, name, 100)
    with pytest.raises(ValueError):
        b.page_url(name, 300)


@pytest.mark.parametrize('changes', [
    {'total_count': True}, {'total_count': -1}, {'total_count': '1'}, {'offset': '0'},
    {'offset': 1}, {'limit': 20}, {'next': '/evil'}, {'previous': '/evil'},
])
def test_malformed_metadata(changes):
    with pytest.raises((ValueError, TypeError)):
        b.parse_page(payload('aspirin', **changes), 'aspirin', 0)


def test_exact_name_check_and_wrong_names():
    assert b.parse_page(payload('aspirin'), 'aspirin', 0)[0][0]['pref_name'] == 'ASPIRIN'
    for name in ['aspirin 75 mg', ' aspirin', 'other', None]:
        obj = json.loads(payload('aspirin'))
        obj['molecules'][0]['pref_name'] = name
        with pytest.raises(ValueError):
            b.parse_page(json.dumps(obj).encode(), 'aspirin', 0)
    for field in ['limit', 'offset', 'total_count', 'next', 'previous']:
        obj = json.loads(payload('aspirin'))
        del obj['page_meta'][field]
        with pytest.raises(KeyError):
            b.parse_page(json.dumps(obj).encode(), 'aspirin', 0)


def test_complete_pagination_positive_only_and_no_future_fields(frozen, tmp_path):
    cache = tmp_path / 'cache'
    index = run(frozen, cache, fetch=lambda url: response(url, 201))
    assert index['attempts_total'] == 30
    assert all(r['status'] == b.POSITIVE and len(r['pages']) == 3 for r in index['records'].values())
    status, hits = b._state('a000', index['records']['a000'], cache)
    assert status == b.POSITIVE and len(hits) == 201
    assert all('max_phase' not in h and 'drug_indications' not in h and h['response_sha256'] for h in hits)
    report = b.summarize(frozen, cache, tmp_path / 'output', 'pilot')
    assert report['newly_candidate_present_sample_trials'] == 10
    assert report['original_b23_trial_status_counts'] == {'unknown': 60, 'no_exact_candidate_evidence': 40}
    assert report['positive_only_augmented_sample_bounds'] == [.1, .6]


def test_zero_stays_unknown_and_full_requires_good_pilot(frozen, tmp_path):
    pilot = tmp_path / 'pilot'
    run(frozen, pilot)
    calls = []
    full = run(frozen, tmp_path / 'full', stage='full', pilot=pilot,
               fetch=lambda url: (calls.append(url) or response(url)))
    assert len(calls) == 50 and full['attempts_total'] == 60
    assert all(r['status'] == b.UNKNOWN_ZERO for r in full['records'].values())
    report = b.summarize(frozen, tmp_path / 'full', tmp_path / 'out', 'full')
    assert report['accounted_names'] == 60 and report['candidate_rows'] == 0
    assert report['positive_only_augmented_trial_status_counts'] == report['original_b23_trial_status_counts']
    with pytest.raises(ValueError, match='requires'):
        run(frozen, tmp_path / 'missing', stage='full')


def test_page_cap_discards_all_partial_positives(frozen, tmp_path):
    cache = tmp_path / 'cap'
    index = run(frozen, cache, fetch=lambda url: response(url, 301))
    assert index['attempts_total'] == 30
    assert all(r['status'] == 'page_cap' for r in index['records'].values())
    assert b._state('a000', index['records']['a000'], cache) == ('page_cap', [])
    with pytest.raises(ValueError, match='Pilot protocol gate failed'):
        run(frozen, tmp_path / 'full', stage='full', pilot=cache)


def test_429_circuit_and_transport_failure_and_retry(frozen, tmp_path):
    index = run(frozen, tmp_path / 'rate', fetch=lambda _: (429, b'raw rate error', 'HTTPError', False))
    assert index['attempts_total'] == 1
    assert index['records']['a000']['status'] == 'rate_limited'
    assert all(r['status'] == 'rate_limit_circuit' for n, r in index['records'].items() if n != 'a000')
    def fail(_):
        raise TimeoutError('do not retain this exception text')
    failure = run(frozen, tmp_path / 'fail', fetch=fail)
    assert failure['attempts_total'] == 20
    assert all(r['status'] == 'http_or_transport_failure' for r in failure['records'].values())
    assert 'do not retain' not in (tmp_path / 'fail' / 'index.json').read_text()
    calls = [0]
    def retry(url):
        calls[0] += 1
        return (503, b'HTTP error bytes', 'HTTPError', False) if calls[0] % 2 else response(url, 1)
    retried = run(frozen, tmp_path / 'retry', fetch=retry)
    assert retried['attempts_total'] == 20
    assert all(r['status'] == b.POSITIVE for r in retried['records'].values())
    assert any(p.read_bytes() == b'HTTP error bytes' for p in (tmp_path / 'retry').glob('*.response'))


@pytest.mark.parametrize('kind', ['malformed', 'wrong_name', 'inconsistent_total', 'duplicate_id', 'oversize'])
def test_invalid_response_never_adds_positive(frozen, tmp_path, kind):
    def fetch(url):
        status, raw, error, trunc = response(url, 101)
        obj = json.loads(raw)
        if kind == 'malformed':
            raw = b'not json'
        elif kind == 'wrong_name':
            obj['molecules'][0]['pref_name'] = 'wrong'
        elif kind == 'inconsistent_total' and obj['page_meta']['offset']:
            return response(url, 102)
        elif kind == 'duplicate_id' and obj['page_meta']['offset']:
            obj['molecules'][0]['molecule_chembl_id'] = 'CHEMBL1'
        elif kind == 'oversize':
            return 200, b'x' * (b.SETTINGS['max_response_bytes'] + 1), None, False
        if kind != 'malformed':
            raw = json.dumps(obj).encode()
        return status, raw, error, trunc
    index = run(frozen, tmp_path / 'cache', fetch=fetch)
    assert all(r['status'] in ('invalid_or_missing_page', 'http_or_transport_failure') for r in index['records'].values())


def test_hash_tampering_no_requests_and_no_overwrite(frozen, tmp_path, monkeypatch):
    def forbidden(_):
        raise AssertionError('network must not be reached')
    cache = tmp_path / 'cache'
    run(frozen, cache)
    before = {p.name: p.read_bytes() for p in cache.iterdir()}
    with pytest.raises(FileExistsError):
        run(frozen, cache, fetch=forbidden)
    assert before == {p.name: p.read_bytes() for p in cache.iterdir()}
    with pytest.raises(FileExistsError):
        b.prepare(frozen)
    out = tmp_path / 'out'
    b.summarize(frozen, cache, out, 'pilot')
    with pytest.raises(FileExistsError):
        b.summarize(frozen, cache, out, 'pilot')
    original_sha = b.sha
    monkeypatch.setattr(b, 'sha', lambda p: 'bad' if Path(p) == Path(b.__file__) else original_sha(p))
    with pytest.raises(ValueError, match='Frozen manifest'):
        run(frozen, tmp_path / 'code-tamper', fetch=forbidden)
    monkeypatch.setattr(b, 'sha', original_sha)
    p = b.ROOT / b.INPUTS['report'][0]
    p.write_bytes(p.read_bytes() + b' ')
    with pytest.raises(ValueError, match='Pinned B23 input hash'):
        run(frozen, tmp_path / 'input-tamper', fetch=forbidden)
    assert not (tmp_path / 'input-tamper').exists()


def test_cache_and_manifest_tampering(frozen, tmp_path):
    cache = tmp_path / 'cache'
    run(frozen, cache)
    index = b.read(cache / 'index.json')
    body = cache / index['records']['a000']['pages'][0]['attempts'][0]['body_file']
    original = body.read_bytes()
    body.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='digest'):
        b.replay_index(frozen, cache, 'pilot')
    body.write_bytes(original)
    index['records']['a000']['status'] = b.POSITIVE
    (cache / 'index.json').write_bytes(b.encoded(index))
    with pytest.raises(ValueError, match='Cached status'):
        b.replay_index(frozen, cache, 'pilot')
    manifest = b.read(frozen / 'pre_acquisition_manifest.json')
    manifest['urls']['a000'][0] += '&bad=1'
    (frozen / 'pre_acquisition_manifest.json').write_bytes(b.encoded(manifest))
    with pytest.raises(ValueError, match='Frozen manifest'):
        b.load_pre(frozen)


def test_offline_replay_deterministic_and_output_tampering(frozen, tmp_path, monkeypatch):
    pilot, cache = tmp_path / 'pilot', tmp_path / 'cache'
    run(frozen, pilot)
    run(frozen, cache, stage='full', pilot=pilot, fetch=lambda url: response(url, 1))
    first, second = tmp_path / 'one', tmp_path / 'two'
    b.summarize(frozen, cache, first, 'full')
    monkeypatch.setattr(b, 'transport', lambda _: pytest.fail('Offline attempted network'))
    b.summarize(frozen, cache, second, 'full')
    assert b.verify_output(first) == b.verify_output(second)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {p.name: p.read_bytes() for p in second.iterdir()}
    (second / 'report.json').write_text('tamper')
    with pytest.raises(ValueError, match='Output bytes'):
        b.verify_output(second)


def test_global_cap_includes_pilot_and_refuses_400_plus(frozen, tmp_path):
    # At most 60*3*2 = 360 attempts are possible; 400 is an outer safety guard.
    pilot = tmp_path / 'pilot'
    run(frozen, pilot)
    def retry(url):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        name, off = q['pref_name__iexact'][0], int(q['offset'][0])
        key = (name, off)
        calls[key] += 1
        return response(url, 301) if calls[key] % 2 == 0 else (None, b'', 'TimeoutError', False)
    from collections import Counter
    calls = Counter()
    index = run(frozen, tmp_path / 'full', stage='full', pilot=pilot, fetch=retry)
    assert index['attempts_total'] == 10 + 50 * 3 * 2 == 310 <= 400
    index['attempts_total'] = 401
    (tmp_path / 'full' / 'index.json').write_bytes(b.encoded(index))
    with pytest.raises(ValueError, match='accounting'):
        b.replay_index(frozen, tmp_path / 'full', 'full')


def test_transport_tls_and_redirect_refusal(monkeypatch):
    contexts = []
    original = ssl.create_default_context
    def context(**kwargs):
        result = original(**kwargs)
        contexts.append(result)
        return result
    monkeypatch.setattr(b.ssl, 'create_default_context', context)
    class Response:
        code = 200
        def read(self, _):
            return b''
        def close(self):
            pass
    class Opener:
        def open(self, request, timeout):
            assert timeout == 10 and request.full_url == b.page_url('aspirin', 0)
            return Response()
    def opener(*handlers):
        assert any(isinstance(h, b._NoRedirect) for h in handlers)
        return Opener()
    monkeypatch.setattr(b.urllib.request, 'build_opener', opener)
    assert b.transport(b.page_url('aspirin', 0)) == (200, b'', None, False)
    assert contexts[0].check_hostname and contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert b._NoRedirect().redirect_request(None, None, None, None, None, None) is None
    with pytest.raises(ValueError):
        b.transport(b.page_url('aspirin', 0).replace('https:', 'http:'))
