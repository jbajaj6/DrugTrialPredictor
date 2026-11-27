"""Synthetic B31 header-only boundaries; no real source rows are opened."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_by_phase import endpoint_review_package_b31 as b


@pytest.fixture
def fixture(tmp_path):
    db = b.connect()
    db.execute('''CREATE TABLE fixture_cases(nct_id VARCHAR,target_first_public_version BIGINT,
        target_checkpoint TIMESTAMP,target_era VARCHAR,inclusion_group VARCHAR,
        selection_stratum VARCHAR,selection_order BIGINT,b22_exclusive_reason VARCHAR,
        selected_result_version BIGINT,selected_result_date TIMESTAMP,outcome_ord BIGINT,
        outcome_pointer_status VARCHAR,planned_presence_state VARCHAR,source_key_state VARCHAR,
        planned_source_rows BIGINT,timing_provenance VARCHAR,label_proxy_class VARCHAR)''')
    # The exact frozen no-result and result-without-pointer denominators are exercised.
    for i in range(343):
        db.execute("""INSERT INTO fixture_cases VALUES (?,0,'2012-01-01','2010-14',
            'uniform','secret stratum',?,'SECRET REASON',?,?,?,'inherited',?,?,?,
            'whole-version only','SECRET PROXY')""",
            [f'SYN{i:03}', i, 7 if i < 269 else None,
             '2018-01-01' if i < 269 else None, 0 if i < 217 else None,
             'observed' if i < 2 else 'not_observed', 'exact' if i < 2 else 'unknown',
             1 if i < 2 else 0])
    cases = tmp_path/'cases.parquet'
    db.execute(f'COPY fixture_cases TO {b.sp(cases)} (FORMAT PARQUET)')
    b.load_cases(db, cases)
    db.execute('''CREATE TABLE fixture_headers(nct_id VARCHAR,nct_version BIGINT,outcome_ord BIGINT,
        type VARCHAR,title VARCHAR,description VARCHAR,time_frame VARCHAR,is_obsolete BOOLEAN,
        obsolete_by VARCHAR,adapter_source_file VARCHAR,adapter_version_public_date TIMESTAMP,
        adapter_core_is_obsolete BOOLEAN,adapter_source_commit VARCHAR,adapter_source_table VARCHAR,
        p_value_raw VARCHAR,measurement_value VARCHAR,label_proxy_class VARCHAR)''')
    rows = [
        ('SYN000',7,0,'PRIMARY','different wording',False,None,False,'2018-01-01'),
        ('SYN000',7,0,'PRIMARY','duplicate row',False,None,False,'2018-01-01'),
        ('SYN000',7,None,'PRIMARY',None,False,None,False,'2018-01-01'),
        ('SYN000',7,4,'PRIMARY','obsolete',True,'8',False,'2018-01-01'),
        ('SYN000',7,5,'PRIMARY','unknown flag',None,None,False,'2018-01-01'),
        ('SYN000',7,6,'PRIMARY','conflict',False,'8',False,'2018-01-01'),
        ('SYN000',7,7,'PRIMARY','core obsolete',False,None,True,'2018-01-01'),
        ('SYN000',7,8,'PRIMARY','core unknown',False,None,None,'2018-01-01'),
        ('SYN001',7,9,'PRIMARY','  same wording\nα "quote"  ',False,None,False,'2018-01-01'),
        ('SYN217',7,0,'PRIMARY','no inherited outcome pointer',False,None,False,'2018-01-01'),
        ('SYN002',7,0,'SECONDARY','SECONDARY FORBIDDEN',False,None,False,'2018-01-01'),
        ('SYN002',7,1,None,'NULL TYPE FORBIDDEN',False,None,False,'2018-01-01'),
        ('SYN003',8,0,'PRIMARY','WRONG VERSION FORBIDDEN',False,None,False,'2025-01-01'),
        ('SYN000',8,0,'PRIMARY','FUTURE FORBIDDEN',False,None,False,'2025-01-01'),
        ('OUTSIDE',7,0,'PRIMARY','OUTSIDE FORBIDDEN',False,None,False,'2018-01-01'),
        ('SYN300',7,0,'PRIMARY','NO RESULT FORBIDDEN',False,None,False,'2018-01-01'),
    ]
    for key,version,ord_,type_,title,obsolete,pointer,core,date in rows:
        db.execute('INSERT INTO fixture_headers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   [key,version,ord_,type_,title,'\nDescription NCT01234567  ','2 years',obsolete,pointer,
                    'raw/headers.parquet',date,core,'commit','results_outcome_measures',
                    'P FORBIDDEN','VALUE FORBIDDEN','PROXY FORBIDDEN'])
    header = tmp_path/'headers.parquet'
    db.execute(f'COPY fixture_headers TO {b.sp(header)} (FORMAT PARQUET)')
    b.load_headers(db,header)
    db.execute('''CREATE TABLE fixture_planned(nct_id VARCHAR,nct_version BIGINT,ord BIGINT,
        measure VARCHAR,time_frame VARCHAR,description VARCHAR,is_obsolete BOOLEAN,
        obsolete_by VARCHAR,source_file VARCHAR,source_file_row BIGINT,source_part_sha256 VARCHAR,
        source_inventory_sha256 VARCHAR,source_commit VARCHAR,source_table VARCHAR,
        source_dataset VARCHAR,source_license VARCHAR,b29_manifest_sha256 VARCHAR,
        b29_queue_sha256 VARCHAR,ordinal_source_row_count BIGINT,
        whole_version_association_date TIMESTAMP,timing_provenance VARCHAR,
        ordinal_state VARCHAR,obsolete_state VARCHAR,p_value_raw VARCHAR)''')
    for i in range(2):
        db.execute("""INSERT INTO fixture_planned VALUES (?,0,0,?,'2 years',NULL,FALSE,NULL,
            'raw/planned.parquet',?,'part sha','inventory sha','commit','primary_outcomes',
            'dataset','license','manifest','queue',1,'2012-01-01','whole-version only',
            'unique_source_ordinal','nonobsolete_source_flag','P FORBIDDEN')""",
            [f'SYN{i:03}', 'planned wording' if i==0 else '  same wording\nα "quote"  ', i])
    planned=tmp_path/'planned.parquet'
    db.execute(f'COPY fixture_planned TO {b.sp(planned)} (FORMAT PARQUET)')
    b.build(db,planned,2)
    yield db,tmp_path,header,planned,cases
    db.close()


def test_frozen_denominators_and_no_pointer_preservation(fixture):
    db,*_=fixture
    report=b.summarize(db)
    assert report['case_count']==343 and report['result_without_outcome_pointer_cases']==52
    assert b.n(db,"SELECT count(*) FROM audit_cases WHERE reported_availability='unknown_no_selected_result'")==74
    assert b.n(db,"SELECT count(*) FROM audit_reported WHERE nct_id='SYN217'")==1
    assert report['reported_primary_row_count']==10 and report['reviewer_reported_row_count']==5


def test_semijoin_isolates_version_and_queue_before_text(fixture):
    db,*_=fixture
    text=str(db.execute('SELECT * FROM exact_primary_headers').fetchall())
    assert 'FORBIDDEN' not in text
    assert db.execute('SELECT DISTINCT nct_version FROM exact_primary_headers').fetchall()==[(7,)]
    assert set(r[0] for r in db.execute('DESCRIBE exact_primary_headers').fetchall())==set(b.HEADERS)|{
        'source_file_row','source_file','source_file_sha256','b17_manifest_sha256'}


def test_no_automatic_match_by_ordinal_or_wording(fixture):
    db,*_=fixture
    assert db.execute("SELECT ord,measure FROM audit_planned WHERE nct_id='SYN000'").fetchone()==(0,'planned wording')
    assert b.n(db,"SELECT count(*) FROM audit_reported WHERE nct_id='SYN000' AND outcome_ord=0")==2
    assert db.execute("SELECT outcome_ord,title FROM audit_reported WHERE nct_id='SYN001'").fetchone()==(9,'  same wording\nα "quote"  ')
    # All independent physical headers survive, with no match or label columns.
    assert b.n(db,'SELECT count(*) FROM review_planned')==2
    for kind,schema in b.REVIEW_SCHEMA.items():
        assert tuple(r[0] for r in db.execute(f'DESCRIBE review_{kind}').fetchall())==schema


def test_obsolete_unknown_null_duplicate_rows_marked(fixture):
    db,*_=fixture
    assert dict(db.execute('SELECT obsolete_state,count(*) FROM audit_reported GROUP BY 1').fetchall())=={
        'nonobsolete_source_flag':5,'obsolete':2,'unknown_obsolete_flag':2,'unknown_flag_pointer_conflict':1}
    assert b.n(db,"SELECT count(*) FROM audit_reported WHERE ordinal_state='ambiguous_duplicate_ordinal'")==2
    assert b.n(db,"SELECT count(*) FROM audit_reported WHERE ordinal_state='unknown_null_ordinal'")==1
    assert b.n(db,"SELECT count(*) FROM review_reported WHERE title IN ('obsolete','core obsolete','unknown flag','core unknown','conflict')")==0


def test_missing_header_and_primary_unknown(fixture):
    db,*_=fixture
    states=dict(db.execute("SELECT nct_id,reported_availability FROM audit_cases WHERE nct_id IN ('SYN002','SYN003','SYN300')").fetchall())
    assert states=={'SYN002':'unknown_missing_primary_header','SYN003':'unknown_missing_exact_header','SYN300':'unknown_no_selected_result'}
    assert b.n(db,"SELECT count(*) FROM review_cases WHERE planned_availability='unknown_not_observed'")==341
    assert db.execute("SELECT selected_header_rows,unknown_type_rows FROM audit_cases WHERE nct_id='SYN002'").fetchone()==(2,1)


def test_source_provenance_and_raw_text(fixture):
    db,tmp,header,*_=fixture
    r=b.records(db,"SELECT * FROM audit_reported WHERE nct_id='SYN001'")[0]
    assert r['title']=='  same wording\nα "quote"  ' and r['description']=='\nDescription NCT01234567  '
    assert r['adapter_source_file']=='raw/headers.parquet' and r['adapter_source_commit']=='commit'
    assert r['source_file']==str(header) and r['source_file_row']==8
    assert r['source_file_sha256']==b.HEADER_SHA and r['b17_manifest_sha256']==b.B17_SHA
    assert b.n(db,'SELECT count(DISTINCT review_row_id) FROM audit_reported')==10


def test_blank_fields_and_casebook_blinding(fixture):
    db,*_=fixture
    for kind in b.REVIEW_SCHEMA:
        for field in b.HUMAN:
            assert b.n(db,f'SELECT count(*) FROM review_{kind} WHERE {field} IS NOT NULL')==0
    rendered=b.casebook(db)
    for forbidden in ('SYN000','SECRET REASON','SECRET PROXY','secret stratum','P FORBIDDEN','raw/headers','2018-01-01'):
        assert forbidden not in rendered
    assert 'Study prose may reidentify' in rendered
    assert 'NCT01234567' not in rendered and '[registry identifier masked]' in rendered
    assert 'textarea' in rendered and 'does not save' in rendered
    assert 'α &quot;quote&quot;' in rendered


def test_id_order_independent_of_selection_metadata(fixture):
    db,tmp,*_=fixture
    before=db.execute('SELECT nct_id,case_id,reviewer_order_hash FROM case_keys ORDER BY 1').fetchall()
    db.execute("UPDATE fixture_cases SET b22_exclusive_reason='changed',inclusion_group='known_anchor',selection_stratum='anchor',selection_order=999,label_proxy_class='changed'")
    path=tmp/'changed.parquet'
    db.execute(f'COPY fixture_cases TO {b.sp(path)} (FORMAT PARQUET)')
    with b.connect() as fresh:
        b.load_cases(fresh,path)
        assert fresh.execute('SELECT nct_id,case_id,reviewer_order_hash FROM case_keys ORDER BY 1').fetchall()==before


@pytest.mark.parametrize('mutation',[
    "UPDATE fixture_cases SET target_checkpoint='2024-01-01' WHERE nct_id='SYN000'",
    "UPDATE fixture_cases SET selected_result_date='2024-01-01' WHERE nct_id='SYN000'",
    "UPDATE fixture_cases SET selected_result_date=target_checkpoint WHERE nct_id='SYN000'",
    "UPDATE fixture_cases SET selected_result_date=NULL WHERE nct_id='SYN000'",
    "UPDATE fixture_cases SET nct_id=NULL WHERE nct_id='SYN000'",
    "UPDATE fixture_cases SET target_first_public_version=NULL WHERE nct_id='SYN000'",
    "UPDATE fixture_cases SET selected_result_version=-1 WHERE nct_id='SYN000'",
    "INSERT INTO fixture_cases SELECT * FROM fixture_cases LIMIT 1",
])
def test_case_contradiction_blocks_before_headers(fixture,mutation):
    db,tmp,*_=fixture
    db.execute(mutation)
    path=tmp/'bad.parquet'
    db.execute(f'COPY fixture_cases TO {b.sp(path)} (FORMAT PARQUET)')
    with b.connect() as fresh:
        with pytest.raises(ValueError,match='contradiction'):
            b.load_cases(fresh,path)
        assert not b.n(fresh,"SELECT count(*) FROM duckdb_tables() WHERE table_name='result_keys'")


@pytest.mark.parametrize('date',[None,'2018-01-02','2024-01-01','2012-01-01'])
def test_header_date_mismatch_blocks_before_text(fixture,date):
    db,tmp,_,_,cases=fixture
    db.execute('UPDATE fixture_headers SET adapter_version_public_date=? WHERE nct_id=\'SYN000\' AND nct_version=7',[date])
    path=tmp/'bad_headers.parquet'
    db.execute(f'COPY fixture_headers TO {b.sp(path)} (FORMAT PARQUET)')
    with b.connect() as fresh:
        b.load_cases(fresh,cases)
        with pytest.raises(ValueError,match='exact-public-date contradiction'):
            b.load_headers(fresh,path)
        assert not b.n(fresh,"SELECT count(*) FROM duckdb_tables() WHERE table_name='exact_primary_headers'")


def test_no_eligible_primary_is_unknown(fixture):
    db,tmp,_,planned,cases=fixture
    db.execute("UPDATE fixture_headers SET is_obsolete=TRUE WHERE nct_id='SYN001'")
    path=tmp/'obsolete.parquet'
    db.execute(f'COPY fixture_headers TO {b.sp(path)} (FORMAT PARQUET)')
    with b.connect() as fresh:
        b.load_cases(fresh,cases);b.load_headers(fresh,path);b.build(fresh,planned,2)
        assert fresh.execute("SELECT reported_availability FROM audit_cases WHERE nct_id='SYN001'").fetchone()==('unknown_no_eligible_primary_header',)


@pytest.mark.parametrize('mutation',[
    "UPDATE fixture_planned SET nct_version=1",
    "UPDATE fixture_planned SET whole_version_association_date='2012-01-02'",
    "UPDATE fixture_planned SET nct_id='OUTSIDE'",
    "DELETE FROM fixture_planned",
])
def test_planned_key_count_guard(fixture,mutation):
    db,tmp,header,_,cases=fixture
    db.execute(mutation)
    path=tmp/'bad_planned.parquet'
    db.execute(f'COPY fixture_planned TO {b.sp(path)} (FORMAT PARQUET)')
    with b.connect() as fresh:
        b.load_cases(fresh,cases);b.load_headers(fresh,header)
        with pytest.raises(ValueError,match='Planned exact-key/count contradiction'):
            b.build(fresh,path,2)


def auth_fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'ROOT',tmp_path)
    for name in ('B30','B17','B29'):
        path=tmp_path/name;path.mkdir();monkeypatch.setattr(b,name,path)
    for path,name in ((b.B30/'trial_summary.parquet','SUMMARY_SHA'),
                      (b.B30/'planned_primary_rows.parquet','PLANNED_SHA'),
                      (b.B17/b.HEADER,'HEADER_SHA'),(b.B29/'review_queue.parquet','QUEUE_SHA')):
        path.write_bytes(str(path).encode());monkeypatch.setattr(b,name,b.sha(path))
    b.dump(b.B29/'manifest.json',{'output_sha256':{'review_queue.parquet':b.QUEUE_SHA}})
    monkeypatch.setattr(b,'B29_SHA',b.sha(b.B29/'manifest.json'))
    b.dump(b.B17/'manifest.json',{'output_sha256':{b.HEADER:b.HEADER_SHA}})
    monkeypatch.setattr(b,'B17_SHA',b.sha(b.B17/'manifest.json'))
    b.dump(b.B30/'manifest.json',{'output_sha256':{'trial_summary.parquet':b.SUMMARY_SHA,
        'planned_primary_rows.parquet':b.PLANNED_SHA},'input_sha256':{
            str((b.B29/'manifest.json').relative_to(b.ROOT)):b.B29_SHA,
            str((b.B29/'review_queue.parquet').relative_to(b.ROOT)):b.QUEUE_SHA}})
    monkeypatch.setattr(b,'B30_SHA',b.sha(b.B30/'manifest.json'))
    footers={'trial_summary.parquet':(b.CASE,343),'planned_primary_rows.parquet':(b.PLANNED,452),b.HEADER:(b.HEADERS,90204)}
    def footer(path):
        cols,rows=footers[Path(path).name]
        return SimpleNamespace(schema_arrow=SimpleNamespace(names=cols),metadata=SimpleNamespace(num_rows=rows))
    monkeypatch.setattr(b.pq,'ParquetFile',footer)


@pytest.mark.parametrize('target',['none','B30_manifest','B17_manifest','B29_manifest','summary','planned','header','queue'])
def test_authentication_every_input(tmp_path,monkeypatch,target):
    auth_fixture(tmp_path,monkeypatch)
    paths={'B30_manifest':b.B30/'manifest.json','B17_manifest':b.B17/'manifest.json',
           'B29_manifest':b.B29/'manifest.json','summary':b.B30/'trial_summary.parquet',
           'planned':b.B30/'planned_primary_rows.parquet','header':b.B17/b.HEADER,
           'queue':b.B29/'review_queue.parquet'}
    if target=='none':
        assert len(b.verify_inputs())==7
    else:
        paths[target].write_bytes(b'tampered')
        with pytest.raises(ValueError,match='SHA-256 mismatch'):
            b.verify_inputs()


def test_schema_and_lineage_contradictions(tmp_path,monkeypatch):
    auth_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(b.pq,'ParquetFile',lambda p:SimpleNamespace(schema_arrow=SimpleNamespace(names=[])))
    with pytest.raises(ValueError,match='Schema/footer contradiction'):
        b.verify_inputs()
    manifest=json.loads((b.B30/'manifest.json').read_text())
    manifest['output_sha256']['trial_summary.parquet']='wrong'
    b.dump(b.B30/'manifest.json',manifest)
    monkeypatch.setattr(b,'B30_SHA',b.sha(b.B30/'manifest.json'))
    with pytest.raises(ValueError,match='Manifest lineage contradiction'):
        b.verify_inputs()


def test_auth_before_connection(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'prepare_output',lambda out:tmp_path/'new')
    def fail():
        raise ValueError('auth failure')
    monkeypatch.setattr(b,'verify_inputs',fail)
    monkeypatch.setattr(b,'connect',lambda:pytest.fail('must not connect'))
    with pytest.raises(ValueError,match='auth failure'):
        b.run(tmp_path/'new')


def test_resource_settings(fixture):
    db,*_=fixture
    values=dict(db.execute("SELECT name,value FROM duckdb_settings() WHERE name IN ('memory_limit','threads','temp_directory','max_temp_directory_size')").fetchall())
    assert values['threads']=='2' and values['temp_directory']==''
    assert values['memory_limit']=='2.0 GiB' and values['max_temp_directory_size']=='0 bytes'


def test_output_refuses_existing_wrong_and_unignored(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'ROOT',tmp_path)
    parent=tmp_path/'data/processed';parent.mkdir(parents=True)
    existing=parent/'b31_existing';existing.mkdir()
    with pytest.raises(FileExistsError):b.prepare_output(existing)
    with pytest.raises(ValueError,match='fresh'):b.prepare_output(parent/'b30_wrong')
    monkeypatch.setattr(b.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1))
    with pytest.raises(ValueError,match='Git-ignored'):b.prepare_output(parent/'b31_new')
    monkeypatch.setattr(b.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    assert b.prepare_output(parent/'b31_new')==parent/'b31_new'


def test_registry_identifier_masking_preserves_raw_audit(fixture):
    db,*_=fixture
    assert db.execute("SELECT description FROM audit_reported LIMIT 1").fetchone()==('\nDescription NCT01234567  ',)
    assert db.execute("SELECT description FROM review_reported LIMIT 1").fetchone()==('\nDescription [registry identifier masked]  ',)
    assert db.execute("SELECT "+b.reviewer_text(('value',))+" FROM (VALUES ('nct-12345678 NCT 87654321 NCT00000000')) t(value)").fetchone()==('[registry identifier masked] [registry identifier masked] [registry identifier masked]',)
