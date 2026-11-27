"""Synthetic B30 gates; no real source or result-child rows opened here."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from phase_by_phase import planned_primary_coverage_b30 as b


@pytest.fixture
def package(tmp_path):
    db = b.connect()
    db.execute('''CREATE TABLE fixture_queue(nct_id VARCHAR,target_first_public_version BIGINT,
        target_checkpoint DATE,target_era VARCHAR,inclusion_group VARCHAR,selection_stratum VARCHAR,
        selection_order BIGINT,b22_exclusive_reason VARCHAR,selected_result_version BIGINT,
        selected_result_date DATE,outcome_ord BIGINT,analysis_ord BIGINT,
        outcome_pointer_status VARCHAR,analysis_pointer_status VARCHAR,b19_lineage_status VARCHAR)''')
    for i, key in enumerate('ABCDE'):
        db.execute("INSERT INTO fixture_queue VALUES (?,7,'2012-02-01','2010-14','uniform','all_targets',?,'p_missing',?,'2018-03-01',?,?, 'exact_b22_pointer','exact_b22_pointer','exact_nct_version_date')",
                   [key, i, 2**53+1, 2**53+3, 2**53+5])
    queue = tmp_path / 'queue.parquet'
    db.execute(f'COPY fixture_queue TO {b.sp(queue)} (FORMAT PARQUET)')
    b.load_queue(db, queue, 5)
    db.execute('''CREATE TABLE fixture_source(nct_id VARCHAR,nct_version BIGINT,ord BIGINT,
        measure VARCHAR,time_frame VARCHAR,description VARCHAR,is_obsolete BOOLEAN,obsolete_by VARCHAR,
        p_value_raw VARCHAR,measurement_value VARCHAR)''')
    values = [
        ('A',7,0,'  Exact\ntext, α "quoted"  ','Day 2','\nDescription\n',False,None),
        ('A',7,0,'duplicate different text',None,None,False,None),
        ('A',7,1,'obsolete','Day 7',None,True,'9'),
        ('A',7,None,None,None,None,None,None),
        ('D',7,3,'conflict',None,None,False,'8'),
        ('E',7,2,'preserved','Week 3','unchanged',False,None),
        ('A',9,0,'FUTURE FORBIDDEN',None,None,False,None),
        ('B',9,0,'MISMATCH FORBIDDEN',None,None,False,None),
        ('B',None,None,'NULL VERSION FORBIDDEN',None,None,None,None),
        ('OUTSIDE',7,0,'OUTSIDE QUEUE FORBIDDEN',None,None,False,None),
    ]
    db.executemany('INSERT INTO fixture_source VALUES (?,?,?,?,?,?,?,?,?,?)',
                   [(*row,'RESULT VALUE FORBIDDEN','RESULT MEASUREMENT FORBIDDEN') for row in values])
    part = tmp_path/'primary_outcomes/part-00000-of-00001.parquet'
    part.parent.mkdir()
    db.execute(f'COPY fixture_source TO {b.sp(part)} (FORMAT PARQUET)')
    source = {'source_root':str(tmp_path),'source_commit':'synthetic-commit','dataset':'synthetic',
              'license':'fixture','tables':{'primary_outcomes':{'files':[
                  {'relative_path':part.relative_to(tmp_path).as_posix(),'sha256':b.sha(part)}]}}}
    b.load_planned(db, [part], source)
    b.build(db)
    yield db, tmp_path
    db.close()


def test_exact_version_isolation_future_and_outside_queue(package):
    db,_ = package
    assert db.execute('SELECT DISTINCT nct_version FROM planned_primary_rows').fetchall()==[(7,)]
    assert b.n(db,'SELECT count(*) FROM planned_primary_rows')==6
    assert 'FORBIDDEN' not in str(db.execute('SELECT * FROM planned_primary_rows').fetchall())
    assert b.n(db,'SELECT count(*) FROM trial_summary')==5


def test_projection_forbidden_result_columns_and_sources(package):
    db,_ = package
    names = {r[0] for r in db.execute('DESCRIBE planned_source').fetchall()}
    assert names == set(b.PLANNED)|{'filename','file_row_number'}
    assert not names.intersection({'p_value_raw','measurement_value','result_date'})
    assert set(r[0] for r in db.execute('DESCRIBE queue').fetchall())==set(b.QUEUE)
    sql = db.execute("SELECT sql FROM duckdb_views() WHERE view_name='planned_source'").fetchone()[0]
    assert 'fixture_source' not in sql
    assert 'results_' not in sql and 'history_original' not in sql


def test_duplicates_null_ordinals_and_no_silent_dedup(package):
    db,_=package
    a=b.records(db,"SELECT * FROM trial_summary WHERE nct_id='A'")[0]
    assert (a['planned_source_rows'],a['distinct_nonnull_ordinals'],a['duplicate_ordinal_rows'],a['null_ordinal_rows'])==(4,2,2,1)
    assert db.execute("SELECT ordinal_state FROM planned_primary_rows WHERE ord IS NULL").fetchall()==[('unknown_null_ordinal',)]


def test_obsolete_unknown_conflict_retained(package):
    db,_=package
    assert dict(db.execute('SELECT obsolete_state,count(*) FROM planned_primary_rows GROUP BY 1').fetchall())=={
        'obsolete':1,'unknown_obsolete_flag':1,'unknown_flag_pointer_conflict':1,'nonobsolete_source_flag':3}
    assert db.execute("SELECT is_obsolete,obsolete_by FROM planned_primary_rows WHERE measure='obsolete'").fetchone()==(True,'9')


def test_source_key_miss_zero_rows_and_no_primary_unknown(package):
    db,_=package
    rows={r['nct_id']:r for r in b.records(db,'SELECT * FROM trial_summary')}
    assert rows['B']['source_key_state']=='unknown_exact_version_not_observed'
    assert rows['B']['other_version_rows']==1 and rows['B']['source_null_version_rows']==1
    assert rows['C']['source_key_state']=='unknown_source_nct_not_observed'
    for key in 'BC':
        assert rows[key]['planned_presence_state']=='not_observed'
        assert rows[key]['planned_source_rows']==0
        assert rows[key]['no_primary_planned_state']=='unknown_not_assessed'
    assert all(r['no_primary_planned_state']=='unknown_not_assessed' for r in rows.values())


def test_text_and_physical_provenance_preserved(package):
    db,tmp=package
    row=b.records(db,"SELECT * FROM planned_primary_rows WHERE source_file_row=0")[0]
    assert row['measure']=='  Exact\ntext, α "quoted"  '
    assert row['time_frame']=='Day 2' and row['description']=='\nDescription\n'
    assert row['source_commit']=='synthetic-commit'
    assert row['source_part_sha256']==b.sha(Path(row['source_file']))
    assert row['source_inventory_sha256']==b.INVENTORY_SHA
    assert row['b29_queue_sha256']==b.QUEUE_SHA and row['b29_manifest_sha256']==b.B29_SHA
    assert row['whole_version_association_date'].isoformat()=='2012-02-01'
    assert row['timing_provenance']==b.TIMING


def test_result_pointer_separation_and_exact_integer_output(package):
    db,tmp=package
    names={r[0] for r in db.execute('DESCRIBE planned_primary_rows').fetchall()}
    assert not names.intersection(set(b.QUEUE)-{'nct_id'})
    row=b.records(db,"SELECT * FROM trial_summary WHERE nct_id='A'")[0]
    assert (row['selected_result_version'],row['outcome_ord'],row['analysis_ord'])==(2**53+1,2**53+3,2**53+5)
    path=tmp/'summary.parquet'
    db.execute(f'COPY trial_summary TO {b.sp(path)} (FORMAT PARQUET)')
    assert str(pq.read_schema(path).field('outcome_ord').type)=='int64'


def test_blank_human_review_fields(package):
    db,_=package
    for table in ('trial_summary','planned_primary_rows'):
        for field in b.HUMAN:
            assert b.n(db,f'SELECT count(*) FROM {table} WHERE {field} IS NOT NULL')==0


def test_descriptive_group_counts_reconcile(package):
    db,_=package
    report=b.summarize(db)
    assert sum(r['trials'] for r in report['by_selection_era'])==5
    assert sum(r['planned_source_rows'] for r in report['by_selection_era'])==6
    assert sum(r['source_rows'] for r in report['row_states'])==6
    assert report['no_primary_planned']['trials_established']==0
    assert 'prevalence' not in set(report)


@pytest.mark.parametrize('mutation',[
    "UPDATE fixture_queue SET target_first_public_version=NULL",
    "UPDATE fixture_queue SET target_checkpoint='2024-01-01'",
    "UPDATE fixture_queue SET target_checkpoint='2004-01-01'",
    "UPDATE fixture_queue SET selected_result_date='2024-01-01'",
    "UPDATE fixture_queue SET selected_result_date=target_checkpoint",
    "UPDATE fixture_queue SET selected_result_version=NULL",
    "UPDATE fixture_queue SET target_era='2015-19'",
    "UPDATE fixture_queue SET analysis_ord=1,outcome_ord=NULL",
    "UPDATE fixture_queue SET nct_id=NULL",
    "INSERT INTO fixture_queue SELECT * FROM fixture_queue LIMIT 1",
])
def test_queue_contradiction_blocks_before_planned_access(package,mutation):
    db,tmp=package
    db.execute(mutation)
    path=tmp/'bad.parquet'
    db.execute(f'COPY fixture_queue TO {b.sp(path)} (FORMAT PARQUET)')
    with b.connect() as fresh:
        with pytest.raises(ValueError,match='contradiction'):
            b.load_queue(fresh,path,5)
        assert not b.n(fresh,"SELECT count(*) FROM duckdb_tables() WHERE table_name='keys'")


def auth_fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'ROOT',tmp_path)
    monkeypatch.setattr(b,'INVENTORY',tmp_path/'inventory.json')
    monkeypatch.setattr(b,'B29',tmp_path/'b29')
    b.B29.mkdir()
    queue=b.B29/'review_queue.parquet';queue.write_bytes(b'queue metadata')
    monkeypatch.setattr(b,'QUEUE_SHA',b.sha(queue))
    manifest=b.B29/'manifest.json'
    b.dump(manifest,{'output_sha256':{'review_queue.parquet':b.QUEUE_SHA}})
    monkeypatch.setattr(b,'B29_SHA',b.sha(manifest))
    source_root=tmp_path/'data/raw/anamnesis/fixture'
    schema=pa.schema([(c,pa.int64() if c in ('nct_version','ord') else pa.bool_() if c=='is_obsolete' else pa.string()) for c in b.PLANNED])
    files=[]
    for i in range(16):
        rel=f'primary_outcomes/part-{i:05d}-of-00016.parquet'
        p=source_root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(f'part {i}'.encode())
        files.append({'relative_path':rel,'rows':500000 if i<15 else 467548,'bytes':p.stat().st_size,'sha256':b.sha(p)})
    b.dump(b.INVENTORY,{'source_root':str(source_root),'tables':{'primary_outcomes':{
        'files':files,'rows':7967548,'columns':list(b.PLANNED),
        'schema_sha256':hashlib.sha256(schema.serialize().to_pybytes()).hexdigest()}}})
    monkeypatch.setattr(b,'INVENTORY_SHA',b.sha(b.INVENTORY))
    def footer(path):
        i=int(Path(path).name[5:10])
        return SimpleNamespace(schema_arrow=schema,metadata=SimpleNamespace(num_rows=files[i]['rows']))
    monkeypatch.setattr(b.pq,'ParquetFile',footer)
    return source_root,files


@pytest.mark.parametrize('tamper',['none','inventory','manifest','queue','first_part','last_part'])
def test_all_input_authentication(tmp_path,monkeypatch,tamper):
    root,files=auth_fixture(tmp_path,monkeypatch)
    target={'inventory':b.INVENTORY,'manifest':b.B29/'manifest.json',
            'queue':b.B29/'review_queue.parquet','first_part':root/files[0]['relative_path'],
            'last_part':root/files[-1]['relative_path']}.get(tamper)
    if target:
        target.write_bytes(b'tampered')
        with pytest.raises(ValueError,match='SHA-256 mismatch'):
            b.verify_inputs()
    else:
        authenticated,parts,_=b.verify_inputs()
        assert len(authenticated)==19 and len(parts)==16


def test_schema_contradiction_blocks(tmp_path,monkeypatch):
    auth_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(b.pq,'ParquetFile',lambda p:SimpleNamespace(schema_arrow=pa.schema([('public_date',pa.string())])))
    with pytest.raises(ValueError,match='schema/footer contradiction'):
        b.verify_inputs()


def test_authentication_before_connection(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'prepare_output',lambda out:tmp_path/'new')
    def fail():
        raise ValueError('authentication failure')
    monkeypatch.setattr(b,'verify_inputs',fail)
    monkeypatch.setattr(b,'connect',lambda:pytest.fail('connection before authentication'))
    with pytest.raises(ValueError,match='authentication failure'):
        b.run(tmp_path/'new')


def test_resource_bounds():
    with b.connect() as db:
        for name,value in [('threads',2),('memory_limit','2.0 GiB'),('temp_directory',''),('max_temp_directory_size','0 bytes')]:
            assert db.execute(f"SELECT current_setting('{name}')").fetchone()[0]==value


def test_fresh_ignored_output_boundary(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'ROOT',tmp_path)
    with pytest.raises(ValueError,match='new data/processed/b30_'):
        b.prepare_output(tmp_path/'b30_wrong')
    path=tmp_path/'data/processed/b30_new'
    monkeypatch.setattr(b.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=0))
    assert b.prepare_output(path)==path and not path.exists()
    path.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        b.prepare_output(path)
    monkeypatch.setattr(b.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=1))
    with pytest.raises(ValueError,match='Git-ignored'):
        b.prepare_output(path.with_name('b30_other'))
