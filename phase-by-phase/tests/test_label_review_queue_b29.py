"""Synthetic B29 boundary, lineage and sampling checks; no real outcome reads."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest

from phase_by_phase import label_review_queue_b29 as b


@pytest.fixture
def db():
    with b.connect() as con:
        # Only synthetic fixture sources contain these deliberately forbidden
        # sentinel columns; the loader must project them away inside DuckDB.
        con.execute('''CREATE TABLE source_targets (
            nct_id VARCHAR, target_checkpoint TIMESTAMP_NS,target_first_public_version BIGINT,
            reason_code VARCHAR,nct_version BIGINT,result_date TIMESTAMP_NS,
            outcome_ord BIGINT,analysis_ord BIGINT,arm_mapping_state VARCHAR,
            comparator_role_state VARCHAR,analysis_type_enum VARCHAR,tested_flag_state VARCHAR,
            overlapping_uncertainty_states VARCHAR[],adapter_source_file VARCHAR,
            adapter_source_commit VARCHAR,adapter_source_table VARCHAR,
            adapter_version_public_date TIMESTAMP,p_value_raw VARCHAR,proxy_label DOUBLE,
            analysis_evidence STRUCT(secret VARCHAR)[],outcome_title VARCHAR)''')
        offset = 0
        for reason, count in b.REASONS.items():
            con.execute('''INSERT INTO source_targets SELECT
                'NCT' || lpad(i::VARCHAR,8,'0'),
                make_date(2005+(i%15)::INTEGER,1,1),7,?,
                CASE WHEN ? THEN NULL ELSE 9007199254740993 END,
                CASE WHEN ? THEN NULL ELSE TIMESTAMP '2023-01-01' END,
                CASE WHEN ? THEN NULL ELSE 9007199254740995 END,
                CASE WHEN ? THEN NULL ELSE 9007199254740997 END,
                'candidate','unknown','superiority','missing',['inherited_unknown'],
                'synthetic_source','synthetic_commit','synthetic_table',TIMESTAMP '2005-01-01',
                'FORBIDDEN_P',1,[{'secret':'FORBIDDEN_NESTED'}],'FORBIDDEN_PROSE'
                FROM range(?,?) t(i)''',
                [reason,reason=='no_posted_primary_result',reason=='no_posted_primary_result',
                 reason in ('no_posted_primary_result','primary_missing_or_multiple'),
                 reason in ('no_posted_primary_result','primary_missing_or_multiple','analysis_missing_or_multiple'),
                 offset,offset+count])
            offset += count
        definitions = ','.join(f'{c} ' + ('BIGINT' if c in (
            'primary_outcome_count','primary_source_row_count','missing_primary_key_rows','analysis_count')
            else 'VARCHAR') for c in b.B19_STATES)
        con.execute('CREATE TABLE source_b19(nct_id VARCHAR,nct_version BIGINT,result_date TIMESTAMP_NS,'+definitions+')')
        values = []
        for col in b.B19_STATES:
            values.append({'primary_outcome_count':'1','primary_source_row_count':'1',
                'missing_primary_key_rows':'0','primary_count_state':"'single'",'analysis_count':'1',
                'direction_state':"'unknown_not_assessed'"}.get(col,"'structural_unknown'"))
        con.execute('INSERT INTO source_b19 SELECT nct_id,nct_version,result_date,'+','.join(values)+
                    ' FROM source_targets WHERE nct_version IS NOT NULL')
        con.execute("UPDATE source_b19 SET primary_count_state='multiple',primary_outcome_count=2 "
                    "WHERE nct_id IN (SELECT nct_id FROM source_targets WHERE reason_code='primary_missing_or_multiple')")
        con.execute("UPDATE source_b19 SET analysis_count=2 WHERE nct_id IN "
                    "(SELECT nct_id FROM source_targets WHERE reason_code='analysis_missing_or_multiple')")
        yield con


def load_synthetic(db):
    db.execute('CREATE TABLE targets AS SELECT '+','.join(b.B22_COLUMNS)+' FROM source_targets')
    db.execute('CREATE TABLE b19 AS SELECT '+','.join(b.B19_COLUMNS)+' FROM source_b19')


def build(db):
    load_synthetic(db)
    b.validate(db,b.REASONS)
    b.build_ledger(db)
    b.sample(db)


def test_projection_inside_duckdb(db,tmp_path):
    for table in ('targets','b19'):
        db.execute(f"COPY source_{table} TO '{tmp_path / (table+'.parquet')}' (FORMAT PARQUET)")
    b.load(db,tmp_path/'targets.parquet',tmp_path/'b19.parquet')
    assert tuple(r[0] for r in db.execute('DESCRIBE targets').fetchall()) == b.B22_COLUMNS
    assert tuple(r[0] for r in db.execute('DESCRIBE b19').fetchall()) == b.B19_COLUMNS
    assert 'p_value_raw' not in b.B22_COLUMNS
    assert 'analysis_evidence' not in b.B19_COLUMNS
    b.validate(db,b.REASONS)


def test_frozen_denominator_and_exclusive_reasons(db):
    build(db)
    assert b.n(db,'SELECT count(*) FROM metadata_ledger') == 19576
    assert dict(db.execute('SELECT b22_exclusive_reason,count(*) FROM metadata_ledger GROUP BY 1').fetchall()) == b.REASONS
    assert b.n(db,"SELECT count(*) FROM metadata_ledger WHERE b19_lineage_status='exact_nct_version_date'") == 8414
    assert b.n(db,'SELECT count(DISTINCT nct_id) FROM metadata_ledger') == 19576


@pytest.mark.parametrize('mutation,error',[
    ("UPDATE targets SET nct_id=NULL WHERE nct_id=(SELECT min(nct_id) FROM targets)",'Missing NCT'),
    ("INSERT INTO targets SELECT * FROM targets LIMIT 1",'Duplicate NCT'),
    ("INSERT INTO b19 SELECT * FROM b19 LIMIT 1",'Duplicate NCT'),
    ("UPDATE targets SET reason_code='invented'",'exclusive reason'),
    ("UPDATE targets SET reason_code=NULL",'exclusive reason'),
    ("DELETE FROM targets WHERE nct_id=(SELECT min(nct_id) FROM targets)",'denominator mismatch'),
    ("UPDATE targets SET target_checkpoint=DATE '2020-01-01'",'target/result'),
    ("UPDATE targets SET target_checkpoint=DATE '2004-12-31'",'target/result'),
    ("UPDATE targets SET target_first_public_version=NULL",'target/result'),
    ("UPDATE targets SET result_date=DATE '2024-01-01' WHERE nct_version IS NOT NULL",'target/result'),
    ("UPDATE targets SET result_date=target_checkpoint WHERE nct_version IS NOT NULL",'target/result'),
    ("UPDATE targets SET nct_version=NULL WHERE result_date IS NOT NULL",'target/result'),
    ("UPDATE targets SET outcome_ord=NULL WHERE analysis_ord IS NOT NULL",'target/result'),
    ("UPDATE b19 SET result_date=DATE '2024-01-01'",'holdout B19'),
    ("UPDATE b19 SET nct_version=NULL",'holdout B19'),
])
def test_reject_invalid_metadata(db,mutation,error):
    load_synthetic(db)
    db.execute(mutation)
    with pytest.raises(ValueError,match=error):
        b.validate(db,b.REASONS)


@pytest.mark.parametrize('mutation,state',[
    ('DELETE FROM b19 WHERE nct_id=?','unknown_missing_b19'),
    ('UPDATE b19 SET nct_version=nct_version+1 WHERE nct_id=?','unknown_b19_version_or_date_mismatch'),
    ("UPDATE b19 SET result_date=DATE '2023-01-02' WHERE nct_id=?",'unknown_b19_version_or_date_mismatch'),
])
def test_lineage_unknown_never_borrowed(db,mutation,state):
    load_synthetic(db)
    key = db.execute('SELECT min(nct_id) FROM targets WHERE analysis_ord IS NOT NULL').fetchone()[0]
    db.execute(mutation,[key])
    b.validate(db,b.REASONS)
    b.build_ledger(db)
    row = b.records(db,f"SELECT * FROM ledger WHERE nct_id='{key}'")[0]
    assert row['b19_lineage_status'] == state
    assert all(row[c] is None for c in ('outcome_ord','analysis_ord','b19_selected_result_version',
                                      'b19_selected_result_date',*[f'b19_{c}' for c in b.B19_STATES]))
    assert row['target_first_public_version'] == 7
    assert row['selected_result_version'] == 2**53+1


def test_missing_and_ambiguous_pointers(db):
    build(db)
    assert b.n(db,"SELECT count(*) FROM ledger WHERE b22_exclusive_reason='primary_missing_or_multiple' AND outcome_ord IS NOT NULL") == 0
    assert b.n(db,"SELECT count(*) FROM ledger WHERE b22_exclusive_reason='analysis_missing_or_multiple' AND analysis_ord IS NOT NULL") == 0
    assert b.n(db,"SELECT count(*) FROM ledger WHERE b22_exclusive_reason='analysis_missing_or_multiple' AND outcome_ord IS NOT NULL") == 3550
    assert b.n(db,"SELECT count(*) FROM ledger WHERE b22_exclusive_reason='no_posted_primary_result' AND b19_primary_count_state IS NOT NULL") == 0


def reference_sample(rows):
    ordered = sorted(rows,key=lambda r:(hashlib.sha256(f'{b.SEED}|{r[0]}'.encode()).hexdigest(),r[0]))
    selected = {row[0]:('uniform','all_targets') for row in ordered[:150]}
    for reason in (*b.RARE,b.KNOWN):
        pools = [[row for row in ordered if row[0] not in selected and row[1]==reason and row[2]==era]
                 for era in ('2005-09','2010-14','2015-19')]
        chosen = []
        while any(pools) and len(chosen)<25:
            for pool in pools:
                if pool and len(chosen)<25:
                    chosen.append(pool.pop(0))
        for row in chosen:
            selected[row[0]]=('known_anchor' if reason==b.KNOWN else 'rare_reason',reason)
    return selected


def test_sha_sampling_disjoint_and_independent_reference(db):
    build(db)
    rows = db.execute('SELECT nct_id,b22_exclusive_reason,target_era FROM ledger').fetchall()
    actual = {r[0]:(r[1],r[2]) for r in db.execute('SELECT nct_id,inclusion_group,selection_stratum FROM selections').fetchall()}
    assert actual == reference_sample(rows)
    assert len(actual) == b.n(db,'SELECT count(*) FROM selections')
    assert b.n(db,"SELECT count(*) FROM selections WHERE inclusion_group='uniform'") == 150
    assert b.n(db,"SELECT count(*) FROM selections WHERE probability_sample IS TRUE AND inclusion_group!='uniform'") == 0
    assert b.n(db,"SELECT count(*) FROM selections WHERE inclusion_group!='uniform' AND uniform_draw_probability IS NOT NULL") == 0
    assert db.execute("SELECT DISTINCT uniform_draw_probability FROM selections WHERE inclusion_group='uniform'").fetchall() == [(150/19576,)]
    report=b.summarize(db)
    for item in report['sampling']:
        assert item['selected'] == min(item['requested'],item['available_after_uniform'])
        assert item['shortfall'] == item['requested']-item['selected']
    assert len(report['sampling'])==10
    assert {r['selection_stratum'] for r in report['sampling'] if r['shortfall']} == {'p_missing','analysis_contrast_unverified'}
    assert b.n(db,"SELECT count(*) FROM selections WHERE selection_stratum='no_posted_primary_result'") == 0


def test_reordered_inputs_same_output(db):
    build(db)
    before=db.execute('SELECT * FROM metadata_ledger ORDER BY nct_id').fetchall()
    db.execute('CREATE OR REPLACE TABLE targets AS SELECT * FROM targets ORDER BY nct_id DESC')
    db.execute('CREATE OR REPLACE TABLE b19 AS SELECT * FROM b19 ORDER BY nct_id DESC')
    for table in ('ledger','selections','metadata_ledger','review_queue'):
        db.execute(f'DROP TABLE {table}')
    b.build_ledger(db)
    b.sample(db)
    assert db.execute('SELECT * FROM metadata_ledger ORDER BY nct_id').fetchall()==before


def test_blank_human_fields_no_direct_values_and_exact_integer_export(db,tmp_path):
    build(db)
    names={row[0] for row in db.execute('DESCRIBE review_queue').fetchall()}
    assert not names.intersection({'proxy_label','p_value_raw','p_numeric','p_qualifier',
        'analysis_group_ids','analysis_evidence','outcome_title','measurement_value','b17_reason_code'})
    for field in b.ADJUDICATION:
        assert b.n(db,f'SELECT count(*) FROM review_queue WHERE {field} IS NOT NULL')==0
    path=tmp_path/'queue.parquet'
    db.execute(f"COPY review_queue TO '{path}' (FORMAT PARQUET)")
    schema=pq.read_schema(path)
    for col in ('target_first_public_version','selected_result_version','b19_selected_result_version','outcome_ord','analysis_ord'):
        assert str(schema.field(col).type)=='int64'
    assert db.execute(f"SELECT DISTINCT analysis_ord FROM read_parquet('{path}') WHERE analysis_ord IS NOT NULL").fetchall()==[(2**53+5,)]


def test_round_robin_skips_empty_eras_and_no_topup(db):
    load_synthetic(db)
    db.execute("UPDATE targets SET target_checkpoint=DATE '2018-01-01' WHERE reason_code='p_missing'")
    b.build_ledger(db)
    b.sample(db)
    assert b.n(db,"SELECT count(*) FROM review_queue WHERE selection_stratum='p_missing'")<=9
    assert db.execute("SELECT DISTINCT target_era FROM review_queue WHERE selection_stratum='p_missing'").fetchall()==[('2015-19',)]


def test_authentication_before_connection(monkeypatch,tmp_path):
    monkeypatch.setattr(b,'prepare_output',lambda out:tmp_path/'new')
    def fail():
        raise ValueError('test authentication fails')
    monkeypatch.setattr(b,'verify_inputs',fail)
    monkeypatch.setattr(b,'connect',lambda:pytest.fail('Connection attempted before authentication'))
    with pytest.raises(ValueError,match='authentication fails'):
        b.run(tmp_path/'new')


@pytest.mark.parametrize('tamper', ['manifest','child','none'])
def test_hash_authentication(tmp_path,tamper):
    child=tmp_path/'metadata.parquet'
    child.write_bytes(b'synthetic bytes; never queried')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'output_sha256':{child.name:b.sha(child)}}))
    pins={tmp_path:b.sha(manifest)}
    if tamper=='manifest':
        manifest.write_text('tampered')
    elif tamper=='child':
        child.write_bytes(b'tampered')
    if tamper=='none':
        assert len(b.verify_inputs(pins,{tmp_path:child.name}))==2
    else:
        with pytest.raises(ValueError,match='SHA-256 mismatch'):
            b.verify_inputs(pins,{tmp_path:child.name})


def test_resource_bounds():
    with b.connect() as db:
        assert db.execute("SELECT current_setting('threads')").fetchone()[0]==2
        assert db.execute("SELECT current_setting('temp_directory')").fetchone()[0]==''
        assert db.execute("SELECT current_setting('max_temp_directory_size')").fetchone()[0]=='0 bytes'
        assert db.execute("SELECT current_setting('memory_limit')").fetchone()[0]=='2.0 GiB'


def test_output_boundary_and_existing_refusal(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'ROOT',tmp_path)
    with pytest.raises(ValueError,match='new data/processed/b29_'):
        b.prepare_output(tmp_path/'b29_wrong_location')
    existing=tmp_path/'data/processed/b29_existing'
    existing.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        b.prepare_output(existing)
    path=tmp_path/'data/processed/b29_synthetic_uncreated_output'
    monkeypatch.setattr(b.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=0))
    assert b.prepare_output(path)==path
    assert not path.exists()
    monkeypatch.setattr(b.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=1))
    with pytest.raises(ValueError,match='Git-ignored'):
        b.prepare_output(path)
