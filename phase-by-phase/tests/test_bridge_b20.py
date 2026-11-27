"""B20 scientific boundaries and exact source graph integrity."""
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import random
import ssl

import certifi

import pytest

from phase_by_phase import bridge_b20 as b


def test_transport_uses_verified_ca_bundle_without_disabling_tls(monkeypatch):
    """No live request: inspect the TLS context sent to urllib."""
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    seen = {}
    make_context = ssl.create_default_context

    def context_factory(*, cafile):
        seen['ca_file'] = cafile
        return make_context(cafile=cafile)

    class Response(io.BytesIO):
        status = 200

    def fake_open(request, timeout, context):
        seen['request'] = request
        seen['timeout'] = timeout
        seen['context'] = context
        return Response(b'{"ok":true}')

    monkeypatch.setattr(b.urllib.request, 'urlopen', fake_open)
    monkeypatch.setattr(b.ssl, 'create_default_context', context_factory)
    assert b.transport(b.search_url('aspirin')) == (200, b'{"ok":true}', None, False)
    assert seen['timeout'] == 10
    assert seen['request'].full_url.startswith('https://')
    assert seen['context'].verify_mode == ssl.CERT_REQUIRED
    assert seen['context'].check_hostname is True
    assert seen['ca_file'] == certifi.where()


def test_transport_honors_explicit_ca_file(monkeypatch, tmp_path):
    custom_ca = tmp_path / 'verified-ca.pem'
    custom_ca.write_bytes(Path(certifi.where()).read_bytes())
    monkeypatch.setenv('SSL_CERT_FILE', str(custom_ca))
    seen = {}
    make_context = ssl.create_default_context

    def context_factory(*, cafile):
        seen['ca_file'] = cafile
        return make_context(cafile=cafile)

    class Response(io.BytesIO):
        status = 200

    def fake_open(request, timeout, context):
        seen['context'] = context
        return Response(b'{}')

    monkeypatch.setattr(b.urllib.request, 'urlopen', fake_open)
    monkeypatch.setattr(b.ssl, 'create_default_context', context_factory)
    assert b.transport(b.search_url('aspirin'))[0] == 200
    assert seen['context'].verify_mode == ssl.CERT_REQUIRED
    assert seen['context'].check_hostname is True
    assert seen['ca_file'] == str(custom_ca)


def molecule(mid='CHEMBL1', pref='Aspirin', synonym=None, parent='CHEMBL1'):
    return {'molecule_chembl_id':mid, 'pref_name':pref,
            'molecule_synonyms':[] if synonym is None else [{'molecule_synonym':synonym, 'syn_type':'OTHER'}],
            'molecule_hierarchy':{'molecule_chembl_id':mid,'parent_chembl_id':parent,'active_chembl_id':parent},
            'molecule_type':'Small molecule', 'max_phase':4, 'first_approval':2025}


def payload(molecules, total=None, next_page=None):
    return json.dumps({'molecules':molecules, 'page_meta':{'total_count':len(molecules) if total is None else total,'next':next_page,'offset':0}}).encode()


def cached(tmp_path, body, status=200):
    names=['aspirin']
    index=b.acquire(names,tmp_path/'cache','online',fetch=lambda url:(status,body,None,False),sleep=lambda t:None, now='frozen')
    return index['records']['aspirin'],tmp_path/'cache'


@pytest.mark.parametrize('raw,want', [(' ASPIRIN\t','aspirin'),('Drug A + Drug B','drug a + drug b'),
                                     ('A hydrochloride','a hydrochloride'),('Ａ','a'),('',None),(None,None)])
def test_normalization_preserves_combinations_and_salt(raw,want):
    assert b.normalize(raw)==want


@pytest.mark.parametrize('molecules,status,count', [([], 'no_exact_candidate',0),
    ([molecule(pref='other',synonym='ASPIRIN')],'one_exact_candidate',1),
    ([molecule(),molecule('CHEMBL2',parent='CHEMBL1')],'ambiguous_exact_candidates',2),
    ([molecule(pref='Aspirin delayed release')],'no_exact_candidate',0),
    ([molecule(pref='Aspirinn')],'no_exact_candidate',0)])
def test_exact_zero_one_multiple_and_fuzzy_exclusion(tmp_path,molecules,status,count):
    record,cache=cached(tmp_path,payload(molecules))
    evidence,state=b.match_response('aspirin',record,cache)
    assert state==status
    assert sum(e['exact_match'] for e in evidence)==count
    assert all('max_phase' not in e and 'first_approval' not in e for e in evidence)


def test_salt_parent_and_active_separate(tmp_path):
    record,cache=cached(tmp_path,payload([molecule('CHEMBL_SALT',parent='CHEMBL_PARENT')]))
    evidence,state=b.match_response('aspirin',record,cache)
    assert state=='one_exact_candidate'
    assert evidence[0]['molecule_chembl_id']=='CHEMBL_SALT'
    assert evidence[0]['original_chembl_id']=='CHEMBL_SALT'
    assert evidence[0]['parent_chembl_id']=='CHEMBL_PARENT'
    assert evidence[0]['active_chembl_id']=='CHEMBL_PARENT'


@pytest.mark.parametrize('total,next_page',[(101,None),(1,'next')])
def test_truncation_preserves_hits_but_unresolved(tmp_path,total,next_page):
    record,cache=cached(tmp_path,payload([molecule()],total,next_page))
    evidence,state=b.match_response('aspirin',record,cache)
    assert state=='response_truncated' and evidence[0]['exact_match']


@pytest.mark.parametrize('body',[b'bad json',b'{}',payload([{'molecule_chembl_id':'CHEMBL1'}])])
def test_invalid_response_is_unknown(tmp_path,body):
    record,cache=cached(tmp_path,body)
    assert b.match_response('aspirin',record,cache)==([], 'invalid_response')


def test_api_failure_and_byte_truncation(tmp_path):
    record,cache=cached(tmp_path,b'error',503)
    assert len(record['attempts'])==2
    assert b.match_response('aspirin',record,cache)==([], 'api_failure')
    record['reason']='response';record['attempts'][-1]['byte_truncated']=True
    assert b.match_response('aspirin',record,cache)==([], 'response_truncated')


def test_rate_retry_budget_circuit_and_offline(tmp_path):
    sleeps=[];calls=[]
    def fetch(url):
        calls.append(url)
        return None,b'', 'URLError',False
    names=[str(i) for i in range(9)]
    index=b.acquire(names,tmp_path/'cache','online',limit=8,fetch=fetch,sleep=sleeps.append,now='frozen')
    assert len(calls)==6 and all(t>=.3 for t in sleeps)
    assert index['records']['3']['reason']=='unqueried_network_circuit'
    assert index['records']['8']['reason']=='unqueried_name_budget'
    replay=b.acquire(names,tmp_path/'cache','offline',limit=8,fetch=lambda _:pytest.fail('offline network'))
    assert index==replay
    with pytest.raises(ValueError,match='settings mismatch'):
        b.acquire(names,tmp_path/'cache','offline',limit=7)
    attempt=index['records']['0']['attempts'][0]
    (tmp_path/'cache'/attempt['body_file']).write_bytes(b'tamper')
    with pytest.raises(ValueError,match='digest'):
        b.acquire(names,tmp_path/'cache','offline',limit=8)


@pytest.mark.parametrize('names,limit',[(['b','a'],200),(['a','a'],200),(['a'],201)])
def test_invalid_acquisition_plan(tmp_path,names,limit):
    with pytest.raises(ValueError):
        b.acquire(names,tmp_path/'cache','source-only',limit)


def graph():
    trial={'nct_id':'NCT1','nct_version':0,'checkpoint_date':date(2019,1,1),'sample_stratum':'multi_drug'}
    base={k:trial[k] for k in b.KEY}
    child={**base,'adapter_version_public_date':trial['checkpoint_date'],'is_obsolete':False,'adapter_source_file':'source'}
    return {'trials':[trial],
      'interventions':[{**child,'ord':i,'intervention_name':name,'intervention_type':'DRUG'} for i,name in enumerate(['Aspirin','Other'])],
      'arms':[{**child,'ord':0,'arm_type':'ACTIVE_COMPARATOR','arm_label':'control'}],
      'aliases':[], 'links':[{**child,'source':'intervention','parent_ord':i,'item_ord':0,'intervention_ord':i,
                           'arm_group_ord':0,'adapter_link_status':'resolved'} for i in (0,1)],
      'conditions':[{**base,'ord':0,'condition':'Disease'}],
      'b18_exposures':[{**base,'intervention_ord':i,'identity_flag':'non_experimental_arm'} for i in (0,1)]}


def test_control_only_multi_drug_graph_not_collapsed(tmp_path):
    tables=graph();b.validate_graph(tables)
    index=b.acquire(['aspirin','other'],tmp_path/'cache','online',fetch=lambda url:(200,payload([molecule()]),None,False),sleep=lambda _:None)
    b.annotate(tables,index,tmp_path/'cache')
    assert len(tables['interventions'])==2 and len(tables['links'])==2
    assert len(tables['review_sheet'])==2
    assert all(r['clinical_identity']=='unknown' for r in tables['review_sheet'])
    assert all(r['source_flags']==['non_experimental_arm'] for r in tables['review_sheet'])
    assert len(tables['molecular_candidates'])==1


def test_combination_cannot_match_ingredient(tmp_path):
    record,cache=cached(tmp_path,payload([molecule()]))
    evidence,state=b.match_response('aspirin + other',record,cache)
    assert state=='no_exact_candidate' and not evidence[0]['exact_match']


def test_alias_collision_not_identity(tmp_path):
    tables=graph();c=tables['interventions'][0]
    tables['aliases']=[{**{k:v for k,v in c.items() if k!='ord'},'intervention_ord':0,'other_name_ord':0,
                        'other_name':'Alias','adapter_link_status':'resolved'}]
    index=b.acquire(['alias','aspirin','other'],tmp_path/'cache','online',fetch=lambda url:(200,payload([molecule(),molecule('CHEMBL2')]),None,False),sleep=lambda _:None)
    b.annotate(tables,index,tmp_path/'cache')
    assert tables['review_sheet'][0]['ambiguous_across_names']
    assert len(tables['unresolved_collisions'])==3
    assert len(tables['molecular_candidates'])==2


@pytest.mark.parametrize('table,field', [('arms','ord'),('interventions','ord'),('aliases','other_name_ord'),('links','item_ord'),('conditions','ord')])
def test_duplicate_and_missing_child_keys(table,field):
    tables=graph()
    if table=='aliases':
        tables[table]=[{**tables['conditions'][0],'intervention_ord':0,'other_name_ord':0}]
    bad=deepcopy(tables);bad[table].append(deepcopy(bad[table][0]))
    with pytest.raises(ValueError,match='duplicate'):
        b.validate_graph(bad)
    tables[table][0][field]=None
    with pytest.raises(ValueError,match='missing'):
        b.validate_graph(tables)


@pytest.mark.parametrize('mutation', ['version','date','holdout','missing_date','parent'])
def test_exact_join_and_date_guards(mutation):
    tables=graph()
    if mutation=='version':tables['arms'][0]['nct_version']=1
    if mutation=='date':tables['arms'][0]['adapter_version_public_date']=date(2019,1,2)
    if mutation=='holdout':tables['trials'][0]['checkpoint_date']=date(2024,1,1)
    if mutation=='missing_date':tables['arms'][0]['adapter_version_public_date']=None
    if mutation=='parent':tables['links'][0]['intervention_ord']=99
    with pytest.raises(ValueError):b.validate_graph(tables)


def test_deterministic_disjoint_priority_selection_and_shortfall():
    trials=[{'nct_id':f'NCT{i:04}','nct_version':0,'checkpoint_date':date(2018,1,1)} for i in range(400)]
    exposures=[];aliases=[]
    flags=['single_experimental_drug','multi_drug_arm','no_resolved_arm_link','shared_with_control','non_experimental_arm']
    for i,r in enumerate(trials):
        exposures.append({**r,'identity_flag':flags[i%5]})
        aliases.append({**r,'canonical_count':2})
    selected,counts=b.select_trials(trials,exposures,aliases,123)
    assert len(selected)==150 and len({b.key(r) for r in selected})==150
    assert all(c['shortfall']==0 for c in counts.values())
    random.Random(11).shuffle(trials);exposures.reverse();aliases.reverse()
    assert (selected,counts)==b.select_trials(trials,exposures,aliases,123)
    assert selected!=b.select_trials(trials,exposures,aliases,124)[0]
    short,counts=b.select_trials(trials[:1],[],[],123)
    assert short==[] and sum(c['shortfall'] for c in counts.values())==150
    with pytest.raises(ValueError,match='duplicate'):
        b.select_trials(trials+trials[:1],[],[],123)


def test_semantic_tables_identical_on_offline_replay(tmp_path):
    tables=graph();names=['aspirin','other']
    index=b.acquire(names,tmp_path/'cache','online',fetch=lambda url:(200,payload([molecule()]),None,False),sleep=lambda _:None,now='frozen')
    first=deepcopy(tables);b.annotate(first,index,tmp_path/'cache')
    replay=b.acquire(names,tmp_path/'cache','offline',fetch=lambda _:pytest.fail('network'))
    second=deepcopy(tables);b.annotate(second,replay,tmp_path/'cache')
    (tmp_path/'one').mkdir();(tmp_path/'two').mkdir()
    assert b.write_tables(tmp_path/'one',first)==b.write_tables(tmp_path/'two',second)
    with pytest.raises(FileExistsError):b.acquire(names,tmp_path/'cache','online')


def test_source_only_explicit_unknown(tmp_path):
    index=b.acquire(['aspirin'],tmp_path/'cache','source-only',fetch=lambda _:pytest.fail('network'))
    assert b.match_response('aspirin',index['records']['aspirin'],tmp_path/'cache')==([], 'unqueried_source_only')
