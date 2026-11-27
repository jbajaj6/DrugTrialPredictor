"""Focused B24 source-graph, temporal, policy and preservation fixtures."""
from datetime import date
from pathlib import Path

import pytest

from phase_by_phase import arm_link_audit_b24 as audit

COMMON = '''nct_id VARCHAR,nct_version BIGINT,is_obsolete BOOLEAN,
 adapter_source_file VARCHAR,adapter_loaded_row_index BIGINT,adapter_source_commit VARCHAR,
 adapter_version_public_date DATE,adapter_version_key_resolved BOOLEAN,adapter_core_is_obsolete BOOLEAN'''


@pytest.fixture
def db():
    c = audit.connect()
    c.execute('CREATE TABLE trials(nct_id VARCHAR,nct_version BIGINT,checkpoint_date DATE,pure_phase VARCHAR)')
    c.execute("INSERT INTO trials VALUES ('N',0,'2010-01-01','PHASE3')")
    c.execute(f'CREATE TABLE arms({COMMON},ord BIGINT,arm_type VARCHAR,arm_label VARCHAR,description VARCHAR)')
    c.execute(f'CREATE TABLE interventions({COMMON},ord BIGINT,intervention_name VARCHAR,intervention_type VARCHAR,description VARCHAR)')
    c.execute(f'''CREATE TABLE links({COMMON},source VARCHAR,parent_ord BIGINT,item_ord BIGINT,
      intervention_ord BIGINT,arm_group_ord BIGINT,intervention_name VARCHAR,intervention_type VARCHAR,
      arm_label VARCHAR,raw_label VARCHAR,adapter_link_status VARCHAR)''')
    yield c
    c.close()


def put(db, table, **kwargs):
    defaults = dict(nct_id='N', nct_version=0, is_obsolete=False, adapter_source_file=table+'.parquet',
                    adapter_loaded_row_index=kwargs.get('ord', kwargs.get('item_ord', 0)),
                    adapter_source_commit='frozen', adapter_version_public_date=date(2010, 1, 1),
                    adapter_version_key_resolved=True, adapter_core_is_obsolete=False)
    defaults.update(kwargs)
    db.execute(f"INSERT INTO {table} ({','.join(defaults)}) VALUES ({','.join('?' for _ in defaults)})", list(defaults.values()))


def arm(db, ordinal=0, role='EXPERIMENTAL', **kw):
    put(db, 'arms', ord=ordinal, arm_type=role, arm_label=f'arm {ordinal}', description='raw arm prose', **kw)


def drug(db, ordinal=0, name='Drug X', category='DRUG', **kw):
    put(db, 'interventions', ord=ordinal, intervention_name=name, intervention_type=category,
        description=f'raw dose/regimen {ordinal}', **kw)


def link(db, source, intervention=0, arm=0, item=0, **kw):
    put(db, 'links', source=source, parent_ord=intervention if source=='intervention' else arm,
        item_ord=item, intervention_ord=intervention, arm_group_ord=arm,
        raw_label='raw written link', **dict({'adapter_link_status':'resolved'}, **kw))


def test_duplicate_names_are_reciprocal_only_at_name_grain(db):
    arm(db); drug(db,0); drug(db,1)
    link(db,'intervention',0); link(db,'arm_group',1)
    r=audit.analyze(db)
    assert r['tables']['assertions']==2 and r['tables']['edges']==2
    assert db.execute('select distinct edge_class from edges order by 1').fetchall()==[('arm_group_only',),('intervention_only',)]
    assert db.execute('select bool_and(opposite_exact_name_other_ordinal) from edges').fetchone()==(True,)
    assert db.execute('select intervention_ordinals,has_intervention,has_arm_group from names_exact').fetchone()==(2,True,True)
    review=audit.rows(db,'select * from review order by intervention_ord')
    assert [r['intervention_record']['description'] for r in review]==['raw dose/regimen 0','raw dose/regimen 1']
    assert all(r['human_adjudication'] is None and r['clinical_identity']=='unknown' for r in review)
    assert all(r['adapter_source_file']=='links.parquet' for r in review)


def test_casefold_trim_is_separate_and_does_not_strip_dose_or_punctuation(db):
    arm(db)
    for n,name in enumerate(('Straße X',' STRASSE X ','Strasse-X','Strasse X 20 mg')):
        drug(db,n,name)
        link(db,'intervention' if n==0 else 'arm_group',n,item=n)
    audit.analyze(db)
    assert db.execute('select count(*) from names_exact').fetchone()[0]==4
    assert db.execute('select count(*) from names_folded').fetchone()[0]==3
    assert db.execute('select opposite_exact_name_other_ordinal,opposite_folded_name_other_ordinal from edges where intervention_ord=0').fetchone()==(False,True)


def test_genuinely_unilateral_and_nondrug(db):
    arm(db); drug(db,0,'Device X','DEVICE'); link(db,'arm_group')
    audit.analyze(db)
    assert db.execute('select edge_class,opposite_folded_name_other_ordinal from edges').fetchone()==('arm_group_only',False)
    assert db.execute('select count(*) from policy_rows').fetchone()[0]==0


def test_primary_eligibility_is_nonmonotone_with_competing_drug(db):
    arm(db); drug(db,0,'Drug X');drug(db,1,'Drug Y')
    link(db,'intervention',0);link(db,'arm_group',0)
    link(db,'intervention',1,item=1)
    audit.analyze(db)
    assert dict(db.execute('select policy,primary_rows from trial_policy').fetchall())=={'intervention':0,'union':0,'reciprocal':1}
    assert db.execute("select raw_drugs_in_arm from policy_rows where policy='union' limit 1").fetchone()[0]==2


def test_control_sharing_and_placebo_exclusion(db):
    arm(db);arm(db,1,'ACTIVE_COMPARATOR');drug(db);drug(db,1,'Placebo')
    for d in ('intervention','arm_group'):
        link(db,d,0,0);link(db,d,0,1,item=1);link(db,d,1,0,item=2)
    audit.analyze(db)
    assert db.execute('select count(*) from policy_rows where primary_candidate').fetchone()[0]==0
    assert db.execute("select distinct candidate_drugs_in_arm,raw_drugs_in_arm from policy_rows where arm_group_ord=0").fetchall()==[(1,2)]
    assert db.execute("select distinct candidate_key from policy_rows where intervention_ord=1").fetchone()==(None,)


def test_same_normalized_name_stays_two_raw_drug_ordinals(db):
    arm(db);drug(db,0,'Drug-X');drug(db,1,'Drug X')
    for d in ('intervention','arm_group'):
        link(db,d,0);link(db,d,1,item=1)
    audit.analyze(db)
    assert db.execute('select distinct candidate_drugs_in_arm,raw_drugs_in_arm,primary_candidate from policy_rows').fetchall()==[(1,2,True)]


def test_orphan_unresolved_missing_date_obsolete_are_retained(db):
    arm(db);drug(db,0,is_obsolete=True);drug(db,1,adapter_version_public_date=None)
    drug(db,2,adapter_version_public_date=date(2024,1,1))
    for n in (0,1,2,99):link(db,'intervention',n,item=n)
    link(db,'arm_group',None,arm=99,item=5,adapter_link_status='unresolved')
    r=audit.analyze(db)
    assert r['tables']['assertions']==5 and r['tables']['edges']==4
    assert db.execute('select count(*) from policy_rows').fetchone()[0]==0
    flags=db.execute('select sum(obsolete::int),sum(date_unknown::int),sum(date_violation::int),sum(orphan_intervention::int),sum(orphan_arm::int),sum(unresolved::int) from assertions').fetchone()
    assert flags==(1,3,1,2,1,1)
    assert db.execute('select count(*) from review where missing_ordinal and nct_id=\'N\' and assertion_id is not null').fetchone()[0]==1


def test_duplicate_child_keys_fail_without_multiplying_assertions(db):
    arm(db);arm(db);drug(db);link(db,'intervention')
    with pytest.raises(ValueError,match='Duplicate arms'):
        audit.analyze(db)


def test_repeated_source_assertions_preserve_multiset(db):
    arm(db);drug(db)
    link(db,'intervention');link(db,'intervention');link(db,'arm_group')
    audit.analyze(db)
    assert db.execute('select assertion_rows,length(assertion_ids),edge_class from edges').fetchone()==(3,3,'reciprocal')


def test_hash_mismatch_precedes_queries_and_sources_are_allowlisted(tmp_path):
    inputs={k:tmp_path/k for k in audit.PINNED}
    for p in inputs.values():p.write_bytes(b'fixture')
    with pytest.raises(ValueError,match='SHA-256 mismatch'):
        audit.verify_sources(inputs,audit.PINNED)
    expected={k:audit.sha(v) for k,v in inputs.items()}
    assert audit.verify_sources(inputs,expected)==expected
    with pytest.raises(ValueError,match='Exactly four'):
        audit.verify_sources(dict(inputs,outcomes=tmp_path/'sealed'),expected)


def test_metadata_projection_exact_version_and_holdout_firewall(db,tmp_path):
    # Poison label values exist but are never projected; no result file is supplied.
    for t in ('trials','arms','interventions','links'): db.execute(f'drop table {t}')
    cohort=tmp_path/'development_rows.parquet'
    db.execute(f"""COPY (SELECT 'N' AS nct_id,0 AS first_public_nct_version,
      DATE '2010-01-01' AS first_public_date,'PHASE1' AS pure_phase,'sealed' AS outcome
      UNION ALL SELECT 'H',0,DATE '2024-01-01','PHASE3','sealed'
      UNION ALL SELECT 'M',0,DATE '2010-01-01','PHASE1_PHASE2','sealed') TO '{cohort}' (FORMAT PARQUET)""")
    files={'cohort':cohort}
    for t in ('arms','interventions','links'):
        p=tmp_path/(t+'.parquet')
        db.execute(f"COPY (SELECT 'N' AS nct_id,0 AS nct_version UNION ALL SELECT 'N',1 UNION ALL SELECT 'H',0) TO '{p}' (FORMAT PARQUET)")
        files[t]=p
    audit.load(db,files,1)
    assert [c[0] for c in db.execute('describe frame').fetchall()]==['nct_id','nct_version','checkpoint_date','pure_phase']
    assert db.execute('select nct_id,nct_version from trials').fetchall()==[('N',0)]
    for t in ('arms','interventions','links'):
        assert db.execute(f'select * from {t}').fetchall()==[('N',0)]
    assert db.execute("select current_setting('threads'),current_setting('temp_directory')").fetchone()==(2,'')


def test_no_overwrite(tmp_path):
    with pytest.raises(FileExistsError):audit.build(tmp_path)


def test_complete_synthetic_build_manifest_and_deterministic_replay(db,tmp_path,monkeypatch):
    import json
    from phase_by_phase import arm_link_audit_b24 as audit
    arm(db);drug(db);link(db,'intervention');link(db,'arm_group')
    inputs={}
    for table in ('arms','interventions','links'):
        p=tmp_path/(table+'.parquet')
        db.execute(f"COPY {table} TO '{p}' (FORMAT PARQUET)")
        inputs[table]=p
    p=tmp_path/'cohort.parquet'
    # The fixture's source trial table is normally populated by load().
    db.execute(f"COPY (SELECT 'N' AS nct_id,0 AS first_public_nct_version,DATE '2010-01-01' AS first_public_date,'PHASE1' AS pure_phase) TO '{p}' (FORMAT PARQUET)")
    inputs['cohort']=p
    hashes={k:audit.sha(v) for k,v in inputs.items()}
    manifest=tmp_path/'b18.json';manifest.write_text(json.dumps({'input_sha256':hashes}))
    monkeypatch.setattr(audit,'INPUTS',inputs);monkeypatch.setattr(audit,'PINNED',hashes)
    monkeypatch.setattr(audit,'B18_MANIFEST',manifest)
    # Manifest paths must be relative to the test source root.
    monkeypatch.setattr(audit,'ROOT',tmp_path)
    (tmp_path/'src/phase_by_phase').mkdir(parents=True)
    (tmp_path/'src/phase_by_phase/drug_level_candidates.py').write_text('normalizer fixture')
    audit.build(tmp_path/'first',1);audit.build(tmp_path/'second',1)
    first=json.loads((tmp_path/'first/manifest.json').read_text())
    second=json.loads((tmp_path/'second/manifest.json').read_text())
    assert first['output_sha256']==second['output_sha256']
    assert len(first['output_sha256'])==12
    for name,digest in first['output_sha256'].items():assert audit.sha(tmp_path/'first'/name)==digest
