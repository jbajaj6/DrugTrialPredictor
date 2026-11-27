"""B23 bounds, provenance, pagination and transport failure fixtures."""
import hashlib
import json

import pytest

from phase_by_phase import coverage_b23 as b


def payload(molecules, total, offset=0, next_page=None):
    return json.dumps({'molecules': molecules, 'page_meta': {'total_count': total,
        'offset': offset, 'next': next_page}}).encode()


def molecule(mid, name='Aspirin'):
    return {'molecule_chembl_id':mid, 'pref_name':name, 'molecule_synonyms':[],
            'molecule_hierarchy':{'parent_chembl_id':mid}}


def test_selection_independent_of_flags(monkeypatch):
    monkeypatch.setattr(b.b20, 'guard_dates', lambda *_: None)
    frame=[{'nct_id':f'NCT{i:08}', 'nct_version':0,'pure_phase':'PHASE3',
            'checkpoint_date':'2010-01-01'} for i in range(19576)]
    a,hash_a=b.select(frame)
    reverse=list(reversed(frame))
    c,hash_c=b.select(reverse)
    assert [(x['nct_id'],x['nct_version']) for x in a]==[(x['nct_id'],x['nct_version']) for x in c]
    assert hash_a==hash_c and len(a)==100
    with pytest.raises(ValueError,match='frame'):
        b.select(frame[:-1])


def test_complete_two_pages_and_exact_candidates(tmp_path):
    pages=[payload([molecule('CHEMBL1')],2,0,'next'),
           payload([molecule('CHEMBL2','Other')],2,1,None)]
    calls=[]
    def fetch(url):
        calls.append(url)
        return 200,pages[len(calls)-1],None,False
    index=b.acquire(['aspirin'],tmp_path/'cache','fixed',fetch=fetch,sleeper=lambda _:None,
                    clock=lambda:0)
    assert len(calls)==2 and index['records']['aspirin']['status']=='complete'
    replay=b.replay_index(tmp_path/'cache',['aspirin'],'fixed')
    status,hits=b.classify('aspirin',replay['records']['aspirin'],tmp_path/'cache')
    assert status=='one_exact_candidate' and len(hits)==1
    assert hits[0]['original_chembl_id'] is None
    assert (tmp_path/'cache'/'index.json').exists()


def test_zero_and_multiple_exact(tmp_path):
    for label,mols,expected in [('zero',[molecule('X','Other')],'no_exact_candidate'),
                                ('multi',[molecule('X'),molecule('Y')],'ambiguous_exact_candidates')]:
        raw=payload(mols,len(mols))
        c=tmp_path/label
        index=b.acquire(['aspirin'],c,'fixed',fetch=lambda _: (200,raw,None,False),
                        sleeper=lambda _:None,clock=lambda:0)
        assert b.classify('aspirin',index['records']['aspirin'],c)[0]==expected


@pytest.mark.parametrize('raw',[
    payload([molecule('X')],2,0,None),  # missing next
    payload([molecule('X')],1,5,None),  # incorrect offset
])
def test_invalid_page_unknown(tmp_path,raw):
    index=b.acquire(['aspirin'],tmp_path/'c','fixed',fetch=lambda _: (200,raw,None,False),
                    sleeper=lambda _:None,clock=lambda:0)
    assert index['records']['aspirin']['status']=='invalid_or_missing_page'
    assert b.classify('aspirin',index['records']['aspirin'],tmp_path/'c')[0]!='no_exact_candidate'


def test_page_cap_and_global_budget_unknown(tmp_path):
    # Every page claims more results; the three-page limit cannot prove a negative.
    raws=[payload([molecule(str(i),'Other')],4,i,'next') for i in range(3)]
    seen=[]
    def fetch(_):
        raw=raws[len(seen)]
        seen.append(1)
        return 200,raw,None,False
    index=b.acquire(['aspirin'],tmp_path/'cap','fixed',
        fetch=fetch,
        sleeper=lambda _:None,clock=lambda:0)
    assert index['records']['aspirin']['status']=='page_cap'
    limited=b.acquire(['aspirin','other'],tmp_path/'budget','fixed',attempt_limit=0)
    assert all(r['status']=='global_attempt_cap' for r in limited['records'].values())


def test_429_timeout_oversize_and_digest_tamper(tmp_path):
    c=tmp_path/'rate'
    index=b.acquire(['aspirin','other'],c,'fixed',fetch=lambda _: (429,b'no', 'HTTPError',False),
                    sleeper=lambda _:None,clock=lambda:0)
    assert index['records']['aspirin']['status']=='rate_limited'
    assert index['records']['other']['status']=='rate_limit_circuit'
    for label,response in [('timeout',(None,b'','TimeoutError',False)),
                           ('large',(200,b'x'*(b.MAX_BYTES+1),None,True))]:
        cache=tmp_path/label
        i=b.acquire(['aspirin'],cache,'fixed',fetch=lambda _:response,sleeper=lambda _:None,clock=lambda:0)
        assert i['records']['aspirin']['status']=='http_or_transport_failure'
    good=tmp_path/'good'
    b.acquire(['aspirin'],good,'fixed',fetch=lambda _:(200,payload([],0),None,False),
              sleeper=lambda _:None,clock=lambda:0)
    record=json.loads((good/'index.json').read_text())['records']['aspirin']
    (good/record['pages'][0]['attempts'][0]['body_file']).write_bytes(b'tamper')
    with pytest.raises(ValueError,match='digest'):
        b.replay_index(good,['aspirin'],'fixed')


def test_cache_duplicate_page_rejected(tmp_path):
    c=tmp_path/'c'
    b.acquire(['aspirin'],c,'fixed',fetch=lambda _:(200,payload([],0),None,False),
              sleeper=lambda _:None,clock=lambda:0)
    index=json.loads((c/'index.json').read_text())
    index['records']['aspirin']['pages'].append(index['records']['aspirin']['pages'][0])
    (c/'index.json').write_text(json.dumps(index))
    with pytest.raises(ValueError,match='Duplicate'):
        b.replay_index(c,['aspirin'],'fixed')


def test_offline_replay_does_not_call_network(tmp_path, monkeypatch):
    c=tmp_path/'cache'
    b.acquire(['aspirin'],c,'frozen',fetch=lambda _:(200,payload([],0),None,False),
              sleeper=lambda _:None,clock=lambda:0)
    monkeypatch.setattr(b.b20,'transport',lambda _: (_ for _ in ()).throw(AssertionError('network')))
    index=b.replay_index(c,['aspirin'],'frozen')
    assert b.classify('aspirin',index['records']['aspirin'],c)==('no_exact_candidate',[])


def test_pre_2020_only_and_orphan_graph_rejected(monkeypatch):
    frame=[{'nct_id':f'NCT{i:08}', 'nct_version':0,'pure_phase':'PHASE3',
            'checkpoint_date':'2010-01-01'} for i in range(19576)]
    frame[0]['checkpoint_date']='2024-01-01'
    with pytest.raises(ValueError,match='checkpoint'):
        b.select(frame)
    with pytest.raises(ValueError,match='Orphan'):
        b.b20.guard_dates([{'nct_id':'NCT00000001','nct_version':0,
                            'checkpoint_date':'2010-01-01'}],
                          [{'nct_id':'NCT00000002','nct_version':0}])
