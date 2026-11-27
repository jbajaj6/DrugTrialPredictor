"""B23 probability-panel coverage of *candidate evidence*, never drug identity.

Prepare freezes source-only provenance before acquisition. Online and offline
consume that exact manifest; no target outcomes or holdout are accessed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.parse

from . import bridge_b20 as b20

SEED = '20261127'
MAX_PAGES = 3
MAX_ATTEMPTS = 1500
MAX_BYTES = 8 * 1024 * 1024
SETTINGS = {'max_pages_per_name': MAX_PAGES, 'page_size': 100,
            'attempts_per_page': 2, 'timeout_seconds': 10,
            'min_request_spacing_seconds': .3, 'max_response_bytes': MAX_BYTES,
            'global_live_attempts': MAX_ATTEMPTS}
SOURCE_TABLES = ('trials', 'design_provenance', 'arms', 'interventions',
                 'aliases', 'links', 'conditions', 'name_occurrences')


def select(trials: list[dict], n: int = 100) -> tuple[list[dict], str]:
    b20.validate_keys(trials, b20.KEY, 'B15 frame')
    if len(trials) != 19576 or any(r['pure_phase'] != 'PHASE3' for r in trials):
        raise ValueError('Unexpected B15 PHASE3 probability frame')
    b20.guard_dates(trials, [])
    ordered = sorted(trials, key=lambda r: (hashlib.sha256(
        f"{SEED}|{r['nct_id']}|{r['nct_version']}".encode()).hexdigest(),
        r['nct_id'], r['nct_version']))
    frame = hashlib.sha256(''.join(json.dumps(r, sort_keys=True, default=str)+'\n'
                      for r in sorted(trials, key=lambda r:(r['nct_id'],r['nct_version']))).encode()).hexdigest()
    return ordered[:n], frame


def prepare(out: Path) -> dict:
    if out.exists():
        raise FileExistsError(out)
    source, hashes = b20.load_sources()
    try:
        selected, frame_hash = select(source['trials'])
        # Extraction uses B20's exact-version graph checks; B18 flags are not
        # part of the draw or the B23 released source-only graph.
        extracted = b20.extract(source, selected)
        tables = {k: extracted[k] for k in SOURCE_TABLES if k != 'name_occurrences'}
        tables['name_occurrences'] = b20.name_occurrences(tables)
        names = sorted({r['normalized_name'] for r in tables['name_occurrences'] if r['normalized_name']})
        out.mkdir(parents=True)
        table_hashes = b20.write_tables(out, tables)
        manifest = {'frame_sha256': frame_hash, 'frame_size': len(source['trials']),
            'selection': 'ascending SHA256(20261127|nct_id|version), key tie-break; first 100',
            'selected_keys': [{k:r[k] for k in ('nct_id','nct_version','checkpoint_date')}
                              for r in selected], 'source_sha256': hashes,
            'graph_sha256': table_hashes, 'ordered_names': names,
            'settings': SETTINGS, 'code_sha256': b20.sha(Path(__file__)),
            'boundary': 'Contemporary exact-name candidate evidence only; not verified drug identity.'}
        b20.dump(out/'pre_acquisition_manifest.json', manifest)
        return {'rows': {k:len(v) for k,v in tables.items()}, 'names':len(names),
                'frame_size': len(source['trials']), 'manifest_sha256':b20.sha(out/'pre_acquisition_manifest.json')}
    finally:
        source['db'].close()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(s) for s in path.read_text().splitlines()]


def load_prepared(path: Path) -> tuple[dict, dict]:
    manifest = json.loads((path/'pre_acquisition_manifest.json').read_text())
    if manifest['code_sha256'] != b20.sha(Path(__file__)) or manifest['settings'] != SETTINGS:
        raise ValueError('Frozen code/settings mismatch')
    tables = {}
    for label, digest in manifest['graph_sha256'].items():
        p = path/label
        if b20.sha(p) != digest:
            raise ValueError('Frozen graph digest mismatch')
        tables[label.removesuffix('.jsonl')] = read_jsonl(p)
    names = sorted({r['normalized_name'] for r in tables['name_occurrences'] if r['normalized_name']})
    if names != manifest['ordered_names']:
        raise ValueError('Frozen name multiset mismatch')
    return manifest, tables


def page_url(name: str, offset: int) -> str:
    base = b20.search_url(name)
    return base.replace('offset=0', f'offset={offset}')


def parse_page(raw: bytes, name: str, offset: int) -> tuple[list[dict], int]:
    obj = json.loads(raw)
    molecules, meta = obj['molecules'], obj['page_meta']
    total = meta['total_count']
    if not isinstance(molecules, list) or not isinstance(total, int) or total < 0:
        raise ValueError('Invalid page payload')
    if int(meta.get('offset', offset)) != offset or len(molecules) > 100:
        raise ValueError('Page offset/size mismatch')
    if offset + len(molecules) < total and not meta.get('next'):
        raise ValueError('Missing next page')
    if offset + len(molecules) >= total and meta.get('next'):
        raise ValueError('Unexpected next page')
    if offset < total and not molecules:
        raise ValueError('Empty nonterminal page')
    for molecule in molecules:
        if not molecule.get('molecule_chembl_id') or not isinstance(molecule.get('molecule_synonyms'), list):
            raise ValueError('Incomplete molecule evidence')
    return molecules, total


def acquire(names: list[str], cache: Path, pre_hash: str, *, fetch=b20.transport,
            sleeper=time.sleep, clock=None, attempt_limit: int = MAX_ATTEMPTS) -> dict:
    if cache.exists():
        raise FileExistsError(cache)
    if names != sorted(set(names)):
        raise ValueError('Names must be complete sorted unique list')
    cache.mkdir(parents=True)
    index = {'pre_acquisition_sha256':pre_hash, 'names': names, 'settings': SETTINGS,
             'records':{}, 'attempts_total':0}
    last_request = None
    clock = clock or time.monotonic
    rate_limited=False
    for name in names:
        record = {'pages': [], 'status':'unknown'}
        if rate_limited:
            record['status']='rate_limit_circuit'
            index['records'][name]=record
            b20.dump(cache/'index.json',index)
            continue
        offset = 0
        for page_number in range(MAX_PAGES):
            if index['attempts_total'] >= attempt_limit:
                record['status']='global_attempt_cap'; break
            page = {'offset':offset, 'url':page_url(name,offset), 'attempts':[]}
            response = None
            for retry in range(2):
                if index['attempts_total'] >= attempt_limit:
                    break
                now = clock()
                if last_request is not None:
                    sleeper(max(0,.3-(now-last_request)))
                last_request = clock()
                status, raw, error, truncated = fetch(page['url'])
                index['attempts_total'] += 1
                if len(raw)>MAX_BYTES:
                    truncated=True
                body = f"{hashlib.sha256(name.encode()).hexdigest()}.{offset}.{retry}.response"
                (cache/body).write_bytes(raw)
                attempt = {'url':page['url'], 'offset':offset, 'status':status,
                    'error_class':error, 'byte_truncated':truncated,
                    'retrieved_at':datetime.now(timezone.utc).isoformat(),
                    'body_file':body, 'sha256':hashlib.sha256(raw).hexdigest()}
                page['attempts'].append(attempt)
                if status==200 and not error and not truncated:
                    response=raw; break
                if status==429:
                    # Never evade a rate limit with more rapid requests.
                    break
            record['pages'].append(page)
            if response is None:
                record['status']='http_or_transport_failure'
                if page['attempts'] and page['attempts'][-1]['status']==429:
                    record['status']='rate_limited'
                    rate_limited=True
                break
            try:
                molecules,total=parse_page(response,name,offset)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                record['status']='invalid_or_missing_page'; break
            if offset+len(molecules)>=total:
                record['status']='complete'; break
            if page_number==MAX_PAGES-1:
                record['status']='page_cap'; break
            offset += len(molecules)
        index['records'][name]=record
        # Persist after each name, so rate limits or interrupts leave evidence.
        b20.dump(cache/'index.json',index)
    return index


def replay_index(cache: Path, names: list[str], pre_hash: str) -> dict:
    index = json.loads((cache/'index.json').read_text())
    if index['names']!=names or index['settings']!=SETTINGS or index['pre_acquisition_sha256']!=pre_hash:
        raise ValueError('Cache selection/settings/provenance mismatch')
    seen=set()
    for name, record in index['records'].items():
        offsets=[]
        for page in record['pages']:
            offsets.append(page['offset'])
            if page['url']!=page_url(name,page['offset']):
                raise ValueError('Cached query mismatch')
            for a in page['attempts']:
                if a['body_file'] in seen or b20.sha(cache/a['body_file'])!=a['sha256']:
                    raise ValueError('Duplicate page body or cache digest mismatch')
                seen.add(a['body_file'])
        if offsets!=sorted(set(offsets)):
            raise ValueError('Duplicate/nonmonotone page')
    if set(index['records'])!=set(names):
        raise ValueError('Missing name record')
    return index


def classify(name: str, record: dict, cache: Path) -> tuple[str,list[dict]]:
    if record['status']!='complete':
        return record['status'],[]
    molecules=[]; total=None; expected=0
    try:
        for page in record['pages']:
            if page['offset']!=expected or not page['attempts']:
                raise ValueError('Missing/duplicate page')
            good=[a for a in page['attempts'] if a['status']==200 and not a['error_class'] and not a['byte_truncated']]
            if len(good)!=1:
                raise ValueError('No unique successful page')
            chunk,n=parse_page((cache/good[0]['body_file']).read_bytes(),name,expected)
            if total is not None and n!=total:
                raise ValueError('Inconsistent total')
            total=n; molecules.extend(chunk); expected+=len(chunk)
        if total is None or expected!=total:
            raise ValueError('Incomplete search')
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return 'invalid_or_missing_page',[]
    hits=[]
    for m in molecules:
        matched=[]
        if b20.normalize(m.get('pref_name'))==name:
            matched.append({'field':'pref_name','value':m['pref_name']})
        for s in m['molecule_synonyms']:
            for f in ('molecule_synonym','synonyms'):
                if b20.normalize(s.get(f))==name:
                    matched.append({'field':f,'value':s[f],'syn_type':s.get('syn_type')})
        if matched:
            h=m.get('molecule_hierarchy') or {}
            hits.append({'normalized_name':name,'molecule_chembl_id':m['molecule_chembl_id'],
                'original_chembl_id':h.get('molecule_chembl_id'),
                'parent_chembl_id':h.get('parent_chembl_id'),
                'active_chembl_id':h.get('active_chembl_id'),
                'matched_evidence':matched})
    ids={h['molecule_chembl_id'] for h in hits}
    return ('ambiguous_exact_candidates' if len(ids)>1 else
            'one_exact_candidate' if ids else 'no_exact_candidate'),hits


def summarize(pre: Path, cache: Path, out: Path) -> dict:
    if out.exists(): raise FileExistsError(out)
    manifest,tables=load_prepared(pre)
    index=replay_index(cache,manifest['ordered_names'],b20.sha(pre/'pre_acquisition_manifest.json'))
    statuses={}; evidence=[]
    for name in manifest['ordered_names']:
        statuses[name],hits=classify(name,index['records'][name],cache)
        evidence.extend(hits)
    trial_names=defaultdict(list); intervention_names=defaultdict(list)
    for o in tables['name_occurrences']:
        k=(o['nct_id'],o['nct_version']); status=statuses.get(o['normalized_name'],'missing_recorded_name')
        o['candidate_status']=status
        trial_names[k].append(status)
        intervention_names[k+(o['intervention_ord'],)].append(status)
    unknown=lambda s:s not in ('one_exact_candidate','no_exact_candidate')
    trial_rows=[]
    for trial in tables['trials']:
        k=(trial['nct_id'],trial['nct_version']); states=trial_names[k]
        if not states: state='unknown_no_drug_name'
        elif any(s=='one_exact_candidate' for s in states): state='candidate_evidence_present'
        elif any(unknown(s) for s in states): state='unknown'
        else: state='no_exact_candidate_evidence'
        trial_rows.append({'nct_id':k[0],'nct_version':k[1],'status':state,
            'name_occurrences':len(states)})
    intervention_rows=[]
    for r in tables['interventions']:
        if (r['intervention_type'] or '').upper()!='DRUG': continue
        k=(r['nct_id'],r['nct_version'],r['ord']); states=intervention_names[k]
        intervention_rows.append({'nct_id':k[0],'nct_version':k[1],
            'intervention_ord':k[2], 'candidate_statuses':sorted(states),
            'unresolved':not states or any(unknown(s) for s in states)})
    arm_drugs=defaultdict(set)
    for link in tables['links']:
        if link.get('adapter_link_status')=='resolved' and link.get('intervention_ord') is not None:
            arm_drugs[(link['nct_id'],link['nct_version'],link['arm_group_ord'])].add(link['intervention_ord'])
    drug_keys={(r['nct_id'],r['nct_version'],r['ord']) for r in tables['interventions'] if (r['intervention_type'] or '').upper()=='DRUG'}
    arm_rows=[]
    for a in tables['arms']:
        k=(a['nct_id'],a['nct_version'],a['ord'])
        drugs=sorted(i for i in arm_drugs[k] if k[:2]+(i,) in drug_keys)
        arm_rows.append({'nct_id':k[0],'nct_version':k[1],'arm_ord':k[2],
            'arm_type':a.get('arm_type'),'drug_intervention_ords':drugs,
            'multi_drug':len(drugs)>1,'missing_drug_link':not drugs})
    tables.update({'chembl_exact_candidates':evidence,
        'name_status':[{'normalized_name':n,'status':statuses[n]} for n in manifest['ordered_names']],
        'intervention_coverage':intervention_rows,'arm_coverage':arm_rows,
        'trial_coverage':trial_rows,
        'review_sheet':[{'nct_id':r['nct_id'],'nct_version':r['nct_version'],
            'intervention_ord':r['intervention_ord'],'candidate_statuses':r['candidate_statuses'],
            'human_adjudication':None,'clinical_identity':'unknown'} for r in intervention_rows]})
    out.mkdir(parents=True)
    table_hashes=b20.write_tables(out,tables)
    counts=Counter(r['status'] for r in trial_rows)
    yes=counts['candidate_evidence_present']; unresolved=sum(v for k,v in counts.items() if k.startswith('unknown'))
    report={'frame_size':manifest['frame_size'],'sample_trials':len(trial_rows),
        'source_counts':{k:len(tables[k]) for k in SOURCE_TABLES},
        'source_drug_interventions':len(intervention_rows),'experimental_arms':sum((a['arm_type'] or '').upper()=='EXPERIMENTAL' for a in tables['arms']),
        'name_status_counts':dict(Counter(statuses.values())), 'trial_status_counts':dict(counts),
        'candidate_evidence_trial_bounds':[yes/len(trial_rows),(yes+unresolved)/len(trial_rows)],
        'molecular_validity':'unverified', 'precision':'not_estimated',
        'boundary':'Current ChEMBL candidate evidence, not historical identity or efficacy.'}
    b20.dump(out/'report.json',report)
    b20.dump(out/'manifest.json',{'pre_acquisition_sha256':b20.sha(pre/'pre_acquisition_manifest.json'),
        'cache_index_sha256':b20.sha(cache/'index.json'),'semantic_sha256':table_hashes,
        'report_sha256':b20.sha(out/'report.json')})
    return report


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=('prepare','online','offline'))
    p.add_argument('--pre',type=Path)
    p.add_argument('--cache',type=Path)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.mode=='prepare': print(json.dumps(prepare(args.out),sort_keys=True)); return
    if not args.pre or not args.cache: p.error('--pre and --cache required')
    manifest,_=load_prepared(args.pre)
    if args.mode=='online':
        acquire(manifest['ordered_names'],args.cache,b20.sha(args.pre/'pre_acquisition_manifest.json'))
    print(json.dumps(summarize(args.pre,args.cache,args.out),sort_keys=True))


if __name__=='__main__': main()
