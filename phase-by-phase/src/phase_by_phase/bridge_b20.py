"""Bounded retrospective molecular candidates; no clinical links or dated features.

All source graphs remain separate. A current exact name hit is an annotation only.
The CLI reads development metadata and protocol children, never outcomes or MeSH.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import ssl
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import duckdb
import certifi

ROOT = Path(__file__).resolve().parents[2]
B18 = ROOT / 'data/processed/anamnesis_drug_candidates_b18_full_v2_2026-11-25'
RAW_MANIFEST = ROOT / 'data/processed/anamnesis_full_source_manifest_2026-11-25.json'
DESIGN_MANIFEST = ROOT / 'data/processed/anamnesis_first_public_design_full_b12_hash_verified_2026-11-25/manifest.json'
QUOTAS = (('primary_single_drug', 50), ('multi_drug', 25), ('no_link', 25),
          ('shared_control', 20), ('nonexperimental_only', 15), ('alias_collision', 15))
FLAGS = {'primary_single_drug': 'single_experimental_drug', 'multi_drug': 'multi_drug_arm',
         'no_link': 'no_resolved_arm_link', 'shared_control': 'shared_with_control'}
KEY = ('nct_id', 'nct_version')
LIMIT_BYTES = 8 * 1024 * 1024
BOUNDARY = ('Retrospective molecular identity candidates only; clinical identity, indication, '
            'cross-phase linkage and historical ChEMBL availability remain unverified.')


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, default=str) + '\n')


def normalize(value: str | None) -> str | None:
    """Case/Unicode/whitespace only; never split combinations or strip salts/doses."""
    if value is None:
        return None
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split()) or None


def key(row: dict) -> tuple:
    return tuple(row[k] for k in KEY)


def validate_keys(rows: list[dict], columns: tuple[str, ...], table: str) -> None:
    seen = set()
    for row in rows:
        values = tuple(row.get(k) for k in columns)
        if any(v is None or v == '' for v in values) or values in seen:
            raise ValueError(f'{table}: missing/duplicate exact key {values}')
        seen.add(values)


def guard_dates(trials: list[dict], children: list[dict]) -> None:
    dates = {key(r): str(r['checkpoint_date'])[:10] for r in trials}
    for d in dates.values():
        if not ('1900-01-01' <= d < '2020-01-01'):
            raise ValueError('Missing/invalid/pre-2020 checkpoint guard')
        date.fromisoformat(d)
    for r in children:
        if key(r) not in dates:
            raise ValueError('Orphan trial/version child')
        if 'adapter_version_public_date' in r:
            if r['adapter_version_public_date'] is None or str(r['adapter_version_public_date'])[:10] != dates[key(r)]:
                raise ValueError('Child public date differs from exact checkpoint')


def select_trials(trials: list[dict], exposures: list[dict], aliases: list[dict], seed: int):
    validate_keys(trials, KEY, 'trial universe')
    guard_dates(trials, [])
    flags = defaultdict(set)
    for r in exposures:
        flags[key(r)].add(r['identity_flag'])
    collisions = {key(r) for r in aliases if r['canonical_count'] > 1}
    selected, used, counts = [], set(), {}
    for stratum, quota in QUOTAS:
        def eligible(r):
            f = flags[key(r)]
            if stratum == 'alias_collision':
                return key(r) in collisions
            if stratum == 'nonexperimental_only':
                return f == {'non_experimental_arm'}
            return FLAGS[stratum] in f
        pool = [r for r in trials if key(r) not in used and eligible(r)]
        pool.sort(key=lambda r: (hashlib.sha256(f'{seed}|{r["nct_id"]}|{r["nct_version"]}'.encode()).hexdigest(), key(r)))
        chosen = pool[:quota]
        counts[stratum] = dict(requested=quota, available_remaining=len(pool), selected=len(chosen), shortfall=quota-len(chosen))
        for r in chosen:
            selected.append(dict(r, sample_stratum=stratum))
            used.add(key(r))
    return sorted(selected, key=key), counts


def search_url(name: str) -> str:
    return 'https://www.ebi.ac.uk/chembl/api/data/molecule/search.json?' + urllib.parse.urlencode({
        'q': name, 'limit': 100, 'offset': 0,
        'only': 'molecule_chembl_id,pref_name,molecule_synonyms,molecule_hierarchy,molecule_type'})


def transport(url: str) -> tuple[int | None, bytes, str | None, bool]:
    """No credentials, headers, environment or exception text are logged."""
    try:
        request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'B20-research-pilot/1.0'})
        # Python.org macOS builds may lack their default OpenSSL CA file.
        # Honor an explicitly configured verified bundle; otherwise use
        # certifi's maintained roots. Never disable certificate checks.
        ca_file = os.environ.get('SSL_CERT_FILE') or certifi.where()
        context = ssl.create_default_context(cafile=ca_file)
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
            raw = response.read(LIMIT_BYTES + 1)
            return response.status, raw, None, len(raw) > LIMIT_BYTES
    except urllib.error.HTTPError as e:
        raw = e.read(LIMIT_BYTES + 1)
        return e.code, raw, 'HTTPError', len(raw) > LIMIT_BYTES
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, b'', type(e).__name__, False


def acquire(names: list[str], cache: Path, mode: str, limit: int = 200,
            fetch=transport, sleep=time.sleep, now=None) -> dict:
    if names != sorted(set(names)) or not 0 <= limit <= 200:
        raise ValueError('Names must be sorted/unique; name limit must be 0..200')
    if mode == 'offline':
        index = json.loads((cache / 'index.json').read_text())
        if index['names'] != names or index['name_limit'] != limit:
            raise ValueError('Offline cache selection/settings mismatch')
        for record in index['records'].values():
            for attempt in record['attempts']:
                if sha(cache / attempt['body_file']) != attempt['sha256']:
                    raise ValueError('Cache byte digest mismatch')
        return index
    cache.mkdir(parents=True, exist_ok=False)
    index = {'names': names, 'name_limit': limit, 'records': {}, 'settings': {
        'timeout_seconds': 10, 'attempts_per_name': 2, 'minimum_request_interval_seconds': .3,
        'page_limit': 100, 'max_response_bytes': LIMIT_BYTES, 'consecutive_failure_circuit': 3}}
    consecutive_failures = 0
    for ordinal, name in enumerate(names):
        reason = ('unqueried_name_budget' if ordinal >= limit else
                  'unqueried_source_only' if mode == 'source-only' else
                  'unqueried_network_circuit' if consecutive_failures >= 3 else None)
        record = {'url': search_url(name), 'attempts': [], 'reason': reason}
        if reason is None:
            for attempt_no in range(2):
                sleep(.3 if attempt_no == 0 else 1.)
                status, raw, error, truncated = fetch(record['url'])
                stem = hashlib.sha256(name.encode()).hexdigest() + f'.{attempt_no}'
                body_file = stem + '.response'
                (cache / body_file).write_bytes(raw)
                attempt = {'status': status, 'error_class': error, 'byte_truncated': truncated,
                           'sha256': hashlib.sha256(raw).hexdigest(), 'body_file': body_file,
                           'url': record['url'], 'retrieved_at': now or datetime.now(timezone.utc).isoformat()}
                record['attempts'].append(attempt)
                if status == 200 and not error:
                    break
            record['reason'] = 'response' if status == 200 and not error else 'api_failure'
            consecutive_failures = consecutive_failures + 1 if record['reason'] == 'api_failure' else 0
        index['records'][name] = record
    dump(cache / 'index.json', index)
    return index


def match_response(name: str, record: dict, cache: Path) -> tuple[list[dict], str]:
    if record['reason'] != 'response':
        return [], record['reason']
    attempt = record['attempts'][-1]
    if attempt['byte_truncated']:
        return [], 'response_truncated'
    try:
        data = json.loads((cache / attempt['body_file']).read_bytes())
        molecules, meta = data['molecules'], data['page_meta']
        if not isinstance(molecules, list) or not isinstance(meta['total_count'], int):
            raise ValueError()
        truncated = bool(meta.get('next')) or meta['total_count'] > len(molecules) or meta.get('offset', 0) != 0
        evidence = []
        for rank, molecule in enumerate(molecules):
            mid = molecule['molecule_chembl_id']
            hierarchy = molecule.get('molecule_hierarchy') or {}
            synonyms = molecule.get('molecule_synonyms')
            # Missing synonym payload cannot establish a complete negative search.
            if not isinstance(synonyms, list) or not mid:
                raise ValueError()
            matched = []
            if normalize(molecule.get('pref_name')) == name:
                matched.append({'field': 'pref_name', 'value': molecule['pref_name']})
            for s in synonyms:
                for field in ('molecule_synonym', 'synonyms'):
                    if normalize(s.get(field)) == name:
                        matched.append({'field': field, 'value': s[field], 'syn_type': s.get('syn_type')})
            evidence.append({'normalized_name': name, 'result_rank': rank, 'molecule_chembl_id': mid,
                             'pref_name': molecule.get('pref_name'), 'molecule_type': molecule.get('molecule_type'),
                             'original_chembl_id': hierarchy.get('molecule_chembl_id'),
                             'parent_chembl_id': hierarchy.get('parent_chembl_id'),
                             'active_chembl_id': hierarchy.get('active_chembl_id'),
                             'synonyms': synonyms, 'matched_evidence': matched,
                             'exact_match': bool(matched), 'search_truncated': truncated,
                             'response_sha256': attempt['sha256'], 'url': record['url']})
        exact = [e for e in evidence if e['exact_match']]
        ids = {e['molecule_chembl_id'] for e in exact}
        parents = {e['parent_chembl_id'] for e in exact if e['parent_chembl_id']}
        status = ('response_truncated' if truncated else 'ambiguous_exact_candidates' if len(ids) > 1 or len(parents) > 1
                  else 'one_exact_candidate' if ids else 'no_exact_candidate')
        return evidence, status
    except (ValueError, KeyError, TypeError, UnicodeError):
        return [], 'invalid_response'


def sqlpath(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def rows(db, sql: str) -> list[dict]:
    result = db.execute(sql)
    cols = [d[0] for d in result.description]
    return [dict(zip(cols, r)) for r in result.fetchall()]


def load_sources() -> tuple[dict, dict]:
    """Verify pinned manifests/bytes, then project metadata before row access."""
    report_path = B18 / 'report.json'
    report = json.loads(report_path.read_text())
    dm = json.loads(DESIGN_MANIFEST.read_text())
    raw_manifest = json.loads(RAW_MANIFEST.read_text())
    def local(p):
        return ROOT / p.removeprefix('phase-by-phase/')
    paths = {k: local(report['input_paths'][k]) for k in ('cohort', 'design', 'arms', 'interventions', 'aliases', 'links')}
    protocol_manifest = paths['arms'].parent / 'manifest.json'
    pm = json.loads(protocol_manifest.read_text())
    hashes = {}
    def verify(p, expected):
        actual = sha(p)
        if actual != expected:
            raise ValueError(f'Source digest mismatch: {p.name}')
        hashes[str(p.relative_to(ROOT))] = actual
    verify(protocol_manifest, dm['protocol_manifest_sha256'])
    for label, p in paths.items():
        verify(p, report['input_sha256'][label])
        if label not in ('cohort', 'design'):
            verify(p, pm['output_files_sha256'][p.name])
    verify(paths['design'], dm['output_sha256'][paths['design'].name])
    for label in ('candidate_exposures', 'target_exposures', 'alias_review'):
        paths[label] = B18 / f'{label}.parquet'
        verify(paths[label], report['output_sha256'][paths[label].name])
    raw = Path(raw_manifest['source_root'])
    if not raw.exists():
        raw = ROOT / 'data/raw/anamnesis/full_8bba6509_2026-11-25'
    conditions = []
    for record in raw_manifest['tables']['conditions']['files']:
        p = raw / record['relative_path']
        verify(p, record['sha256'])
        conditions.append(p)
    for p in (report_path, DESIGN_MANIFEST, RAW_MANIFEST):
        hashes[str(p.relative_to(ROOT))] = sha(p)
    db = duckdb.connect()
    db.execute("SET threads=2; SET memory_limit='2GB'")
    for label, p in paths.items():
        db.execute(f'CREATE VIEW {label} AS SELECT * FROM read_parquet({sqlpath(p)})')
    # The cohort contains development labels; only these four metadata columns are scanned.
    trials = rows(db, """SELECT nct_id,first_public_nct_version AS nct_version,
      CAST(first_public_date AS DATE) AS checkpoint_date,pure_phase FROM cohort
      WHERE pure_phase='PHASE3' AND first_public_date < DATE '2020-01-01'""")
    exposures = rows(db, "SELECT * FROM candidate_exposures WHERE pure_phase='PHASE3' AND source_date < DATE '2020-01-01'")
    targets = rows(db, 'SELECT * FROM target_exposures')
    aliases = rows(db, 'SELECT * FROM alias_review')
    return {'db': db, 'trials': trials, 'exposures': exposures, 'targets': targets,
            'alias_review': aliases, 'conditions': conditions}, hashes


def extract(source: dict, selected: list[dict]) -> dict:
    db = source['db']
    import pyarrow as pa
    db.register('selection', pa.Table.from_pylist([{k: r[k] for k in KEY} for r in selected]))
    tables = {'trials': selected}
    for label in ('arms', 'interventions', 'aliases', 'links'):
        tables[label] = rows(db, f'SELECT c.* FROM {label} c JOIN selection s USING(nct_id,nct_version)')
    condition_scan = ','.join(sqlpath(p) for p in source['conditions'])
    tables['conditions'] = rows(db, f"SELECT c.*,filename AS source_file FROM read_parquet([{condition_scan}],filename=true) c JOIN selection s USING(nct_id,nct_version)")
    wanted = {key(r) for r in selected}
    tables['b18_exposures'] = [r for r in source['exposures'] if key(r) in wanted]
    tables['b18_alias_review'] = [r for r in source['alias_review'] if key(r) in wanted]
    tables['b18_target_exposures'] = [dict(r, nct_id=r['target_nct_id'], nct_version=r['target_version']) for r in source['targets'] if (r['target_nct_id'], r['target_version']) in wanted]
    validate_graph(tables)
    # B12 metadata is projected explicitly; no current status/results/enrollment.
    tables['design_provenance'] = rows(db, """SELECT d.nct_id,d.first_public_nct_version AS nct_version,
       d.first_public_date,d.study_first_post_date,d.archive_left_truncated,d.adapter_core_source_file
       FROM design d JOIN selection s ON d.nct_id=s.nct_id AND d.first_public_nct_version=s.nct_version""")
    validate_keys(tables['design_provenance'], KEY, 'design provenance')
    checkpoints = {key(r): r['checkpoint_date'] for r in selected}
    if len(tables['design_provenance']) != len(selected) or any(r['first_public_date'] != checkpoints[key(r)] for r in tables['design_provenance']):
        raise ValueError('B12 checkpoint/key mismatch')
    return tables


def validate_graph(tables: dict) -> None:
    for label, columns in {'trials': KEY, 'arms': KEY+('ord',), 'interventions': KEY+('ord',),
                           'aliases': KEY+('intervention_ord','other_name_ord'),
                           'links': KEY+('source','parent_ord','item_ord'), 'conditions': KEY+('ord',)}.items():
        validate_keys(tables[label], columns, label)
        guard_dates(tables['trials'], tables[label])
    ints = {key(r)+(r['ord'],) for r in tables['interventions']}
    arms = {key(r)+(r['ord'],) for r in tables['arms']}
    for r in tables['aliases']:
        if r.get('adapter_link_status') == 'resolved' and key(r)+(r['intervention_ord'],) not in ints:
            raise ValueError('Resolved alias missing exact intervention parent')
    for r in tables['links']:
        if r.get('adapter_link_status') == 'resolved' and (key(r)+(r['intervention_ord'],) not in ints or key(r)+(r['arm_group_ord'],) not in arms):
            raise ValueError('Resolved assertion missing exact parent')


def name_occurrences(tables: dict) -> list[dict]:
    drug_keys = {key(r)+(r['ord'],) for r in tables['interventions'] if (r['intervention_type'] or '').upper() == 'DRUG'}
    result = []
    for label, field in (('interventions', 'intervention_name'), ('aliases', 'other_name')):
        for r in tables[label]:
            ordinal = r['ord'] if label == 'interventions' else r['intervention_ord']
            if key(r)+(ordinal,) not in drug_keys:
                continue
            result.append({**{k:r[k] for k in KEY}, 'intervention_ord': ordinal,
                           'origin': label, 'other_name_ord': r.get('other_name_ord'),
                           'raw_name': r[field], 'normalized_name': normalize(r[field]),
                           'source_file': r['adapter_source_file'], 'is_obsolete': r['is_obsolete'],
                           'source_link_status': r.get('adapter_link_status')})
    return result


def annotate(tables: dict, index: dict, cache: Path) -> None:
    occurrences = name_occurrences(tables)
    evidence, states, candidates = [], {}, defaultdict(list)
    for name in index['names']:
        hits, state = match_response(name, index['records'][name], cache)
        evidence.extend(hits)
        states[name] = state
        candidates[name] = [h for h in hits if h['exact_match']]
    tables['chembl_evidence'] = evidence
    tables['query_status'] = [{'normalized_name': n, 'status': states[n],
                             'request_attempts': len(index['records'][n]['attempts']),
                             'url': index['records'][n]['url']} for n in index['names']]
    for o in occurrences:
        o['status'] = states.get(o['normalized_name'], 'missing_recorded_name')
    tables['name_occurrences'] = occurrences
    tables['molecular_candidates'] = [{**o, **{k:v for k,v in h.items() if k != 'normalized_name'},
                                       'candidate_only': True} for o in occurrences for h in candidates[o['normalized_name']]]
    tables['unresolved_collisions'] = [o for o in occurrences if o['status'] != 'one_exact_candidate']
    tables['review_sheet'] = []
    source_flags = defaultdict(set)
    for e in tables['b18_exposures']:
        source_flags[key(e)+(e['intervention_ord'],)].add(e['identity_flag'])
    for intervention in tables['interventions']:
        if (intervention['intervention_type'] or '').upper() != 'DRUG':
            continue
        ik = key(intervention)+(intervention['ord'],)
        occ = [o for o in occurrences if key(o)+(o['intervention_ord'],) == ik]
        ids = sorted({h['molecule_chembl_id'] for o in occ for h in candidates[o['normalized_name']]})
        parents = sorted({h['parent_chembl_id'] for o in occ for h in candidates[o['normalized_name']] if h['parent_chembl_id']})
        tables['review_sheet'].append({**{k:intervention[k] for k in KEY}, 'intervention_ord': intervention['ord'],
            'raw_name': intervention['intervention_name'], 'source_flags': sorted(source_flags[ik]),
            'name_statuses': sorted({o['status'] for o in occ}), 'candidate_ids': ids, 'parent_ids': parents,
            'ambiguous_across_names': len(ids)>1 or len(parents)>1, 'human_adjudication': None,
            'clinical_identity': 'unknown', 'historical_chembl_availability': 'unknown', 'boundary': BOUNDARY})


def write_tables(out: Path, tables: dict) -> dict:
    hashes = {}
    for label, records in tables.items():
        encoded = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) for r in records)
        path = out / f'{label}.jsonl'
        path.write_text(''.join(r+'\n' for r in encoded))
        hashes[path.name] = sha(path)
    return hashes


def build(out: Path, cache: Path, mode: str = 'online', seed: int = 20261127, name_limit: int = 200) -> dict:
    if out.exists():
        raise FileExistsError(f'Refusing prior output: {out}')
    source, source_hashes = load_sources()
    selected, counts = select_trials(source['trials'], source['exposures'], source['alias_review'], seed)
    if not selected:
        raise ValueError('Empty fixed pilot selection')
    tables = extract(source, selected)
    occurrences = name_occurrences(tables)
    names = sorted({r['normalized_name'] for r in occurrences if r['normalized_name']})
    index = acquire(names, cache, mode, name_limit)
    annotate(tables, index, cache)
    out.mkdir(parents=True)
    table_hashes = write_tables(out, tables)
    strata = {key(r):r['sample_stratum'] for r in selected}
    report = {'boundary': BOUNDARY, 'rows': {k:len(v) for k,v in tables.items()}, 'sample_counts': counts,
              'name_status_counts': dict(Counter(r['status'] for r in tables['query_status'])),
              'occurrence_status_by_stratum': {s:dict(Counter(o['status'] for o in tables['name_occurrences'] if strata[key(o)]==s)) for s,_ in QUOTAS},
              'source_identity_flags_by_stratum': {s:dict(Counter(o['identity_flag'] for o in tables['b18_exposures'] if strata[key(o)]==s)) for s,_ in QUOTAS},
              'queried_unique_names': sum(bool(r['attempts']) for r in index['records'].values()),
              'network_blocker': any(r['reason'] in ('api_failure','unqueried_network_circuit') for r in index['records'].values()),
              'source_exact_key_integrity': 'passed', 'molecular_validity': 'unverified',
              'missing_children_by_type': {label:sum(not any(key(c)==key(t) for c in tables[label]) for t in selected) for label in ('arms','interventions','aliases','links','conditions')},
              'non_drug_interventions_preserved_not_queried': sum((r['intervention_type'] or '').upper()!='DRUG' for r in tables['interventions']),
              'source_obsolete_rows_preserved': {label:sum(bool(r.get('is_obsolete')) for r in tables[label]) for label in ('arms','interventions','aliases','links','conditions')},
              'assertion_status_counts': dict(Counter(r['adapter_link_status'] for r in tables['links'])),
              'mesh_evidence': 'excluded_no_version', 'precision': 'not_estimated_no_independent_molecule_review'}
    dump(out/'report.json', report)
    dump(out/'manifest.json', {'seed':seed, 'sampling':'quota order; SHA256(seed|NCT|version); remove selected keys before next quota',
         'selected_trials':selected, 'sample_counts':counts, 'normalization':'NFKC/casefold/whitespace only',
         'name_limit':name_limit, 'ordered_names':names, 'source_sha256':source_hashes,
         'code_sha256':sha(Path(__file__)), 'cache_index_sha256':sha(cache/'index.json'),
         'cache':str(cache), 'mode':mode, 'semantic_sha256':table_hashes, 'report_sha256':sha(out/'report.json'),
         'source_attribution':'Anamnesis Data / ClinicalTrials.gov, CC BY-NC 4.0; ChEMBL public API', 'boundary':BOUNDARY})
    source['db'].close()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--mode', choices=('online','offline','source-only'), default='online')
    p.add_argument('--seed', type=int, default=20261127)
    p.add_argument('--name-limit', type=int, default=200)
    print(json.dumps(build(**vars(p.parse_args())), indent=2))


if __name__ == '__main__':
    main()
