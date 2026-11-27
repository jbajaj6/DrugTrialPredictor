"""Independent synthetic expectations for the bounded B27 feasibility audit."""
import json
from pathlib import Path

import pytest

from phase_by_phase import proxy_link_feasibility_b27 as b


@pytest.fixture
def db():
    con = b.connect()
    yield con
    con.close()


def candidate_fixture(db, unknown=False):
    db.execute('''CREATE TABLE labels(target_nct_id VARCHAR,target_checkpoint DATE,
        target_first_public_version BIGINT,label_proxy_class INTEGER,label_reason_code VARCHAR,
        audit_label_result_version BIGINT,label_result_public_date DATE)''')
    db.execute("INSERT INTO labels VALUES ('T','2015-01-01',0,1,'known',999,'2020-01-01')")
    if unknown:
        db.execute("INSERT INTO labels VALUES ('U','2015-01-01',0,NULL,'unknown',998,'2020-01-01')")
    db.execute('''CREATE TABLE trials(nct_id VARCHAR,nct_version BIGINT,checkpoint_date DATE,pure_phase VARCHAR)''')
    db.execute("INSERT INTO trials VALUES ('T',0,'2015-01-01','PHASE3'),('P',4,'2010-01-01','PHASE1'),('Q',2,'2011-01-01','PHASE2'),('U',0,'2015-01-01','PHASE3')")
    db.execute('''CREATE TABLE name_trials(candidate_key VARCHAR,nct_id VARCHAR,nct_version BIGINT,
        pure_phase VARCHAR,checkpoint_date DATE,intervention_ordinals BIGINT[],has_control_role BOOLEAN,
        has_unlinked BOOLEAN,has_one_sided BOOLEAN,shared_experimental_control BOOLEAN,
        possible_combination_or_conflict BOOLEAN)''')
    for name, trial, ver, phase, date in [('x','T',0,'PHASE3','2015-01-01'),
        ('x','P',4,'PHASE1','2010-01-01'),('x','Q',2,'PHASE2','2011-01-01'),
        ('x','U',0,'PHASE3','2015-01-01')]:
        db.execute('INSERT INTO name_trials VALUES (?,?,?,?,?,[0],false,false,false,false,false)',[name,trial,ver,phase,date])
    db.execute('''CREATE TABLE later_trial_coverage AS SELECT nct_id,nct_version,checkpoint_date,
        1 AS candidate_names,1 AS names_with_prior_p1,1 AS names_with_prior_p2,1 AS names_with_any_prior
        FROM trials WHERE pure_phase='PHASE3' ''')
    db.execute('''CREATE TABLE name_coverage AS SELECT nct_id,nct_version,checkpoint_date,candidate_key,
        'PHASE1' AS prior_phase,1 AS earlier_name_trials FROM name_trials WHERE pure_phase='PHASE3'
        UNION ALL SELECT nct_id,nct_version,checkpoint_date,candidate_key,'PHASE2',1 FROM name_trials WHERE pure_phase='PHASE3' ''')


def result_fixture(db, checkpoint='2015-01-01'):
    db.execute('CREATE TABLE requests(target_nct_id VARCHAR,prior_nct_id VARCHAR,target_checkpoint DATE)')
    db.execute('INSERT INTO requests VALUES (?,?,?)',['T','P',checkpoint])
    db.execute('CREATE TABLE prior_limits AS SELECT prior_nct_id AS nct_id,max(target_checkpoint) AS max_checkpoint FROM requests GROUP BY 1')
    db.execute('''CREATE TABLE candidate_keys AS SELECT *, 'x' AS candidate_key FROM requests''')
    db.execute('''CREATE TABLE core_source(nct_id VARCHAR,nct_version VARCHAR,public_date DATE,
        is_obsolete BOOLEAN,source_file VARCHAR DEFAULT 'core',source_row BIGINT DEFAULT 0,
        source_commit VARCHAR DEFAULT 'commit')''')
    db.execute('''CREATE TABLE header_source(nct_id VARCHAR,nct_version BIGINT,outcome_ord BIGINT,
        type VARCHAR,is_obsolete BOOLEAN DEFAULT false,adapter_version_public_date DATE,
        adapter_core_is_obsolete BOOLEAN DEFAULT false,adapter_source_file VARCHAR DEFAULT 'header',
        source_row BIGINT DEFAULT 0,adapter_source_commit VARCHAR DEFAULT 'commit')''')
    db.execute('''CREATE TABLE measurement_source(nct_id VARCHAR,nct_version BIGINT,outcome_ord BIGINT,
        class_ord BIGINT DEFAULT 0,category_ord BIGINT DEFAULT 0,measurement_ord BIGINT DEFAULT 0,
        group_id VARCHAR DEFAULT 'g',adapter_version_public_date DATE,
        is_obsolete BOOLEAN DEFAULT false,adapter_core_is_obsolete BOOLEAN DEFAULT false,
        adapter_source_file VARCHAR DEFAULT 'measure',source_row BIGINT DEFAULT 0,
        adapter_source_commit VARCHAR DEFAULT 'commit',value VARCHAR)''')


def core(db, v='1', date='2010-01-01', nct='P', obsolete=False):
    db.execute('INSERT INTO core_source(nct_id,nct_version,public_date,is_obsolete) VALUES (?,?,?,?)',[nct,v,date,obsolete])


def header(db, v=1, date='2010-01-01', nct='P', outcome=0, kind='PRIMARY', obsolete=False):
    db.execute('''INSERT INTO header_source(nct_id,nct_version,outcome_ord,type,is_obsolete,adapter_version_public_date)
        VALUES (?,?,?,?,?,?)''',[nct,v,outcome,kind,obsolete,date])


def measurement(db, v=1, date='2010-01-01', nct='P', outcome=0, value='12', obsolete=False):
    db.execute('''INSERT INTO measurement_source(nct_id,nct_version,outcome_ord,adapter_version_public_date,value,is_obsolete)
        VALUES (?,?,?,?,?,?)''',[nct,v,outcome,date,value,obsolete])


def availability(db):
    b.result_audit(db)
    return b.records(db,'SELECT * FROM availability')[0]


def test_first_public_join_never_label_result_version(db):
    candidate_fixture(db,unknown=True)
    b.build_candidates(db)
    assert b.n(db,'SELECT count(*) FROM targets_base') == 2
    assert b.n(db,'SELECT count(*) FROM candidate_keys') == 2
    assert b.n(db,"SELECT count(*) FROM candidate_keys WHERE target_nct_id='U'") == 0
    assert b.n(db,'SELECT count(DISTINCT prior_nct_id) FROM candidate_keys') == 2
    assert b.n(db,'SELECT max(target_first_public_version) FROM candidate_keys') == 0
    assert b.n(db,'SELECT audit_label_result_version FROM targets_base WHERE target_nct_id=\'T\'') == 999


def test_wrong_first_public_version_rejected(db):
    candidate_fixture(db)
    db.execute('UPDATE labels SET target_first_public_version=999')
    with pytest.raises(ValueError,match='first-public'):
        b.build_candidates(db)


def test_duplicate_name_pair_rejected(db):
    candidate_fixture(db)
    db.execute("INSERT INTO name_trials SELECT * FROM name_trials WHERE nct_id='P'")
    with pytest.raises(ValueError,match='Duplicate key'):
        b.build_candidates(db)


def test_high_fanout_flag_no_exclusion_or_alias_expansion(db):
    candidate_fixture(db)
    db.execute("INSERT INTO name_trials SELECT 'x','Z'||i,0,'PHASE1',DATE '2018-01-01',[0],false,false,false,false,false FROM range(110) r(i)")
    b.build_candidates(db)
    assert b.n(db,'SELECT count(*) FROM candidate_keys WHERE high_fanout') == 2


@pytest.mark.parametrize('date', ['2015-01-01','2016-01-01',None])
def test_registration_tied_future_missing_unavailable(db,date):
    candidate_fixture(db)
    db.execute("UPDATE name_trials SET checkpoint_date=? WHERE nct_id='P'",[date])
    db.execute("UPDATE name_coverage SET earlier_name_trials=0 WHERE prior_phase='PHASE1'")
    b.build_candidates(db)
    assert b.n(db,"SELECT count(*) FROM candidate_keys WHERE prior_nct_id='P'") == 0


def test_withdrawal_whole_record_does_not_carry_results_forward(db):
    result_fixture(db)
    core(db);header(db);measurement(db)
    core(db,'2','2014-01-01')
    row=availability(db)
    assert row['ever_posted_before_checkpoint'] is True
    assert row['ever_measurement_before_checkpoint'] is True
    assert row['asof_core_version'] == 2
    assert row['asof_current_primary_header'] is False
    assert row['availability_status'] == 'asof_withdrawn_primary'


def test_nonobsolete_whole_core_gate(db):
    result_fixture(db)
    core(db);header(db);measurement(db)
    core(db,'2','2014-01-01',obsolete=True)
    row=availability(db)
    assert row['asof_core_version'] == 1
    assert row['asof_current_primary_measurement']


@pytest.mark.parametrize('date',['2015-01-01','2016-01-01','2024-01-01',None])
def test_core_strict_dates_and_pre2024(db,date):
    result_fixture(db)
    core(db,date=date);header(db,date=date);measurement(db,date=date)
    row=availability(db)
    assert not row['asof_current_primary_measurement']
    assert not row['ever_posted_before_checkpoint']
    assert b.n(db,'SELECT count(*) FROM measurement_presence') == 0


@pytest.mark.parametrize('date',['2015-01-01','2016-01-01',None])
def test_header_source_public_date_must_equal_core(db,date):
    result_fixture(db)
    core(db);header(db,date=date);measurement(db)
    row=availability(db)
    assert not row['asof_current_primary_header']
    assert b.n(db,'SELECT count(*) FROM measurement_presence') == 0


@pytest.mark.parametrize('date',['2015-01-01','2016-01-01',None])
def test_measurement_source_date_must_equal_exact_version(db,date):
    result_fixture(db)
    core(db);header(db);measurement(db,date=date)
    row=availability(db)
    assert row['asof_current_primary_header']
    assert not row['asof_current_primary_measurement']


@pytest.mark.parametrize('value',[None,'','  '])
def test_header_without_nonempty_measurement(db,value):
    result_fixture(db)
    core(db);header(db);measurement(db,value=value)
    row=availability(db)
    assert row['availability_status'] == 'primary_header_without_measurement'


@pytest.mark.parametrize('which',['header_version','measurement_version','measurement_outcome','secondary','obsolete_header','obsolete_measurement'])
def test_exact_child_key_and_primary_nonobsolete_gates(db,which):
    result_fixture(db)
    core(db)
    header(db,v=2 if which=='header_version' else 1,
           kind='SECONDARY' if which=='secondary' else 'PRIMARY',obsolete=which=='obsolete_header')
    measurement(db,v=2 if which=='measurement_version' else 1,
                outcome=1 if which=='measurement_outcome' else 0,obsolete=which=='obsolete_measurement')
    row=availability(db)
    assert not row['asof_current_primary_measurement']


@pytest.mark.parametrize('v',['x','1.2','-1','','9223372036854775808',None])
def test_malformed_core_version_unknown(db,v):
    result_fixture(db)
    core(db);header(db);measurement(db)
    core(db,v,'2014-01-01')
    row=availability(db)
    assert row['availability_status'] == 'unknown_malformed_version'
    assert not row['asof_current_primary_measurement']


def test_ambiguous_latest_public_day_unavailable_with_version_tiebreak(db):
    result_fixture(db)
    core(db);header(db);measurement(db)
    core(db,'2');header(db,2);measurement(db,2)
    row=availability(db)
    assert row['asof_core_version']==2
    assert row['availability_status']=='unknown_ambiguous_asof_public_day'
    assert not row['ever_posted_before_checkpoint']
    assert not row['asof_current_primary_measurement']


def test_missing_date_prevents_assuming_latest_known_version(db):
    result_fixture(db)
    core(db);header(db);measurement(db)
    core(db,'2',None)
    assert availability(db)['availability_status']=='unknown_missing_core_date'


def test_target_and_non_candidate_results_never_materialized(db):
    result_fixture(db)
    core(db);header(db);measurement(db)
    for nct in ['T','HOLDOUT','UNRELATED']:
        core(db,nct=nct);header(db,nct=nct);measurement(db,nct=nct,value='must not enter audit')
    row=availability(db)
    assert row['asof_current_primary_measurement']
    for table in ['core_meta','prior_headers','primary_headers','measurement_presence']:
        assert b.n(db,f"SELECT count(*) FROM {table} WHERE nct_id<>'P'")==0
    assert 'value' not in [r[0] for r in db.execute('DESCRIBE measurement_presence').fetchall()]


def test_per_checkpoint_no_latest_result_leakage(db):
    result_fixture(db,'2011-01-01')
    db.execute("INSERT INTO requests VALUES ('T2','P','2015-01-01')")
    db.execute("UPDATE prior_limits SET max_checkpoint='2015-01-01'")
    db.execute("INSERT INTO candidate_keys SELECT *, 'x' FROM requests WHERE target_nct_id='T2'")
    core(db);core(db,'2','2013-01-01');header(db,2,'2013-01-01');measurement(db,2,'2013-01-01')
    b.result_audit(db)
    rows=b.records(db,'SELECT * FROM availability ORDER BY target_nct_id')
    assert not rows[0]['asof_current_primary_measurement']
    assert rows[0]['asof_core_version']==1
    assert rows[1]['asof_current_primary_measurement']


def test_exact_large_integer_roundtrip(db,tmp_path):
    result_fixture(db)
    v=2**53+1
    core(db,str(v));header(db,v);measurement(db,v)
    row=availability(db)
    assert row['asof_core_version']==v
    path=tmp_path/'version.parquet'
    db.execute(f"COPY availability TO '{path}' (FORMAT PARQUET)")
    assert db.execute(f"SELECT asof_core_version FROM read_parquet('{path}')").fetchone()[0]==v


def test_settings_and_overwrite_refusal(db,tmp_path):
    assert db.execute("SELECT current_setting('threads'),current_setting('temp_directory')").fetchone()==(2,'')
    assert b.SETTINGS['memory_limit']=='2GiB'
    with pytest.raises(FileExistsError):
        b.run(tmp_path)


def test_hash_verification_precedes_connect(monkeypatch,tmp_path):
    path=tmp_path/'manifest.json';path.write_text('{}')
    monkeypatch.setattr(b,'PINS',{path:'incorrect'})
    monkeypatch.setattr(b,'connect',lambda: pytest.fail('row-query connection before authentication'))
    with pytest.raises(ValueError,match='Pinned SHA-256 mismatch'):
        b.run(tmp_path/'fresh')


def test_used_child_hash_tamper(monkeypatch,tmp_path):
    for label in ['B22','B26','B11']:
        directory=tmp_path/label;directory.mkdir()
        monkeypatch.setattr(b,label,directory)
        (directory/'manifest.json').write_text(json.dumps({'output_sha256':{'all_target_labels.parquet':'bad'}}))
    monkeypatch.setattr(b,'PINS',{})
    (b.B22/'all_target_labels.parquet').write_text('changed')
    with pytest.raises(ValueError,match='Used child SHA-256 mismatch'):
        b.verify_inputs()


def test_duplicate_core_key_fails_closed(db):
    result_fixture(db);core(db);core(db)
    with pytest.raises(ValueError,match='Duplicate key'):
        availability(db)


@pytest.mark.parametrize('date',['2024-01-01','2015-01-01',None])
def test_label_date_boundary_cannot_enter_first_public_audit(db,date):
    candidate_fixture(db)
    db.execute('UPDATE labels SET label_result_public_date=?',[date])
    with pytest.raises(ValueError,match='boundary'):
        b.build_candidates(db)


def test_header_date_diagnostics_keep_tied_later_and_wrong_versions(db):
    result_fixture(db)
    core(db)
    header(db,v=9,date='2015-01-01')
    header(db,v=10,date='2016-01-01')
    header(db,v=11,date=None)
    row=availability(db)
    assert row['tied_primary_dates']==1
    assert row['later_primary_dates']==1
    assert row['missing_primary_dates']==1
    assert row['unmatched_primary_versions']==3
    assert not row['asof_current_primary_header']


def test_no_header_is_reporting_absence_not_negative_proxy(db):
    result_fixture(db);core(db)
    row=availability(db)
    assert row['all_primary_header_rows']==0
    assert row['availability_status']=='no_asof_primary'
    assert 'proxy_label' not in row


def test_prior_versions_after_last_checkpoint_never_read_measurements(db):
    result_fixture(db);core(db);header(db);measurement(db)
    core(db,'2','2017-01-01');header(db,2,'2017-01-01');measurement(db,2,'2017-01-01',value='future')
    row=availability(db)
    assert row['asof_core_version']==1
    assert b.n(db,'SELECT count(*) FROM allowed_measurement_rows WHERE nct_version=2')==0
    assert b.n(db,'SELECT count(*) FROM measurement_presence WHERE nct_version=2')==0


def test_withdrawn_measurements_do_not_persist_under_current_header(db):
    result_fixture(db);core(db);header(db);measurement(db)
    core(db,'2','2014-01-01');header(db,2,'2014-01-01')
    row=availability(db)
    assert row['ever_measurement_before_checkpoint']
    assert row['asof_current_primary_header']
    assert not row['asof_current_primary_measurement']
    assert row['availability_status']=='primary_header_without_measurement'


def test_b18_empty_comparator_never_gates_b26_candidates(db):
    candidate_fixture(db,unknown=True);b.build_candidates(db)
    # Use request-level flags to isolate comparison behavior from result fixture.
    db.execute('''CREATE TABLE candidate_pairs AS SELECT *,false AS ever_posted_before_checkpoint,
        false AS ever_measurement_before_checkpoint,false AS asof_current_primary_header,
        false AS asof_current_primary_measurement FROM candidate_keys''')
    db.execute('''CREATE TABLE b18_source(target_nct_id VARCHAR,target_version BIGINT,checkpoint_date DATE,
        candidate_drug_key VARCHAR,prior_nct_id VARCHAR,prior_phase VARCHAR,prior_design_date DATE,
        prior_asof_record_version BIGINT,prior_asof_record_date DATE,prior_result_version BIGINT,prior_result_date DATE)''')
    b.comparison(db)
    assert b.n(db,'SELECT count(*) FROM candidate_pairs')==2
    assert b.n(db,'SELECT count(*) FROM b18_comparison')==0
    row=b.records(db,"SELECT * FROM target_feasibility WHERE target_nct_id='U'")[0]
    assert row['has_asof_measurement'] is None
    assert row['label_proxy_class'] is None
    assert row['b18_restricted_covered'] is None
