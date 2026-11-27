"""B26 source graph, strict chronology, denominator and deterministic replay checks."""
from datetime import date
import json
from pathlib import Path

import pytest

from phase_by_phase import cross_phase_bridge_b26 as b


@pytest.fixture
def db():
    d = b.connect()
    d.execute('CREATE TABLE trials(nct_id VARCHAR,nct_version BIGINT,checkpoint_date DATE,pure_phase VARCHAR)')
    common = 'nct_id VARCHAR,nct_version BIGINT,ord BIGINT'
    d.execute(f'CREATE TABLE arms({common},arm_type VARCHAR,arm_label VARCHAR,description VARCHAR,adapter_version_public_date DATE)')
    d.execute(f'''CREATE TABLE interventions({common},intervention_name VARCHAR,intervention_type VARCHAR,
        description VARCHAR,adapter_version_public_date DATE)''')
    d.execute('''CREATE TABLE assertions(assertion_id BIGINT,nct_id VARCHAR,nct_version BIGINT,
        source VARCHAR,arm_group_ord BIGINT,intervention_ord BIGINT,raw_label VARCHAR)''')
    d.execute('''CREATE TABLE edges(nct_id VARCHAR,nct_version BIGINT,arm_group_ord BIGINT,intervention_ord BIGINT,
        pure_phase VARCHAR,edge_class VARCHAR,has_intervention BOOLEAN,has_arm_group BOOLEAN)''')
    d.execute('''CREATE TABLE aliases(nct_id VARCHAR,nct_version BIGINT,intervention_ord BIGINT,other_name_ord BIGINT,
        intervention_name VARCHAR,other_name VARCHAR,adapter_version_public_date DATE)''')
    d.execute('''CREATE TABLE conditions(nct_id VARCHAR,nct_version BIGINT,ord BIGINT,condition VARCHAR,
        is_obsolete BOOLEAN,obsolete_by VARCHAR)''')
    yield d
    d.close()


def trial(d, nct, phase='PHASE1', when='2008-01-01', names=('Drug X',), version=0):
    d.execute('INSERT INTO trials VALUES (?,?,?,?)',[nct,version,when,phase])
    for i, name in enumerate(names):
        d.execute('INSERT INTO interventions VALUES (?,?,?,?,?,?,?)',
                  [nct,version,i,name,'DRUG','raw dose and regimen untouched',when])


def edge(d, nct, ordinal=0, arm=0, role='EXPERIMENTAL', kind='reciprocal'):
    v,p,dt=d.execute('SELECT nct_version,pure_phase,checkpoint_date FROM trials WHERE nct_id=?',[nct]).fetchone()
    if not d.execute('SELECT count(*) FROM arms WHERE nct_id=? AND ord=?',[nct,arm]).fetchone()[0]:
        d.execute('INSERT INTO arms VALUES (?,?,?,?,?,?,?)',[nct,v,arm,role,'raw arm','raw prose',dt])
    a=kind in ('reciprocal','intervention_only'); c=kind in ('reciprocal','arm_group_only')
    d.execute('INSERT INTO edges VALUES (?,?,?,?,?,?,?,?)',[nct,v,arm,ordinal,p,kind,a,c])
    aid=d.execute('SELECT count(*) FROM assertions').fetchone()[0]
    for k in (['intervention'] if a else [])+(['arm_group'] if c else []):
        aid+=1
        d.execute('INSERT INTO assertions VALUES (?,?,?,?,?,?,?)',[aid,nct,v,k,arm,ordinal,'raw directional text'])


def test_unlinked_stays_denominator_and_distinct_later_trials(db):
    trial(db,'A',names=('Drug X','Drug X'));trial(db,'B','PHASE2','2009-01-01',('Drug X','Drug X'))
    edge(db,'B',0);edge(db,'B',1,arm=1,kind='intervention_only')
    r=b.analyze(db)
    assert r['coverage'][0]['covered_distinct_later_trials']==1
    assert db.execute('SELECT earlier_name_trials FROM name_coverage').fetchall()==[(1,)]
    assert db.execute('SELECT count(*) FROM name_trials').fetchone()==(2,)
    assert db.execute("SELECT intervention_rows,has_unlinked FROM name_trials WHERE nct_id='A'").fetchone()==(2,True)
    assert db.execute("SELECT has_one_sided_name,has_reciprocal_name FROM later_trial_coverage").fetchone()==(True,True)


def test_separate_p1_p2_p3_and_union(db):
    trial(db,'A'); trial(db,'B','PHASE2','2009-01-01')
    trial(db,'C','PHASE3','2010-01-01');trial(db,'D','PHASE3','2010-01-01',('Other',))
    r=b.analyze(db)
    assert [x['covered_distinct_later_trials'] for x in r['coverage']]==[1,1,1,1]
    assert len(db.execute('SELECT * FROM later_trial_coverage').fetchall())==3


def test_tied_future_and_missing_dates_never_link(db):
    trial(db,'A',when='2010-01-01'); trial(db,'B',when='2011-01-01');trial(db,'M',when=None)
    trial(db,'C','PHASE2','2010-01-01');trial(db,'D','PHASE3',None)
    b.analyze(db)
    assert db.execute("SELECT earlier_name_trials,tied_name_trials,future_name_trials,missing_prior_dates FROM name_coverage WHERE nct_id='C'").fetchone()==(0,1,1,1)
    assert db.execute("SELECT count(*) FROM name_coverage WHERE later_date_missing AND earlier_name_trials<>0").fetchone()==(0,)
    assert db.execute('SELECT count(*) FROM name_coverage WHERE earlier_example_nct=nct_id').fetchone()==(0,)


def test_strict_date_boundary_and_exemplar(db):
    trial(db,'A',when='2009-12-31');trial(db,'Z',when='2010-01-01')
    trial(db,'B','PHASE3','2010-01-01')
    b.analyze(db)
    assert db.execute("SELECT earlier_name_trials,tied_name_trials,earlier_example_nct,earlier_example_checkpoint FROM name_coverage WHERE prior_phase='PHASE1'").fetchone()==(1,1,'A',date(2009,12,31))


@pytest.mark.parametrize('table', ['arms','interventions'])
@pytest.mark.parametrize('source_date', [None,'2012-01-01','2007-01-01'])
def test_unverifiable_canonical_or_role_public_date_fails_closed(db,table,source_date):
    trial(db,'EARLY');edge(db,'EARLY')
    trial(db,'LATER','PHASE2','2009-01-01')
    db.execute(f'UPDATE {table} SET adapter_version_public_date=? WHERE nct_id=?',[source_date,'EARLY'])
    with pytest.raises(ValueError,match=f'Unverifiable first-public {table} public date'):
        b.analyze(db)


def test_controls_combinations_and_roles_are_flags_not_merges(db):
    trial(db,'A',names=('Drug X + Drug Y','Placebo','Drug X','Drug Y',None,'Control arm','Drug X 20mg','Drug X salt'))
    trial(db,'B','PHASE2','2009-01-01',('Drug X',))
    edge(db,'A',0);edge(db,'A',2);edge(db,'A',2,arm=1,role='ACTIVE_COMPARATOR',kind='arm_group_only')
    b.analyze(db)
    flags=db.execute("SELECT possible_combination_string,possible_multi_drug_arm_or_direction_conflict FROM intervention_names WHERE nct_id='A' AND ord=0").fetchone()
    assert flags==(True,True)
    assert db.execute("SELECT shared_experimental_control,has_one_sided FROM intervention_names WHERE nct_id='A' AND ord=2").fetchone()==(True,True)
    assert db.execute("SELECT count(*) FROM name_trials WHERE candidate_key IN ('drug x','drug y','drug x drug y','drug x 20mg','drug x salt')").fetchone()==(6,)
    assert db.execute("SELECT count(*) FROM intervention_names WHERE name_status='empty_or_null'").fetchone()==(1,)
    assert db.execute("SELECT count(*) FROM name_trials WHERE candidate_key LIKE '%placebo%' OR candidate_key LIKE '%control%'").fetchone()==(0,)


def test_nondrug_null_names_and_b18_normalizer_verbatim(db):
    trial(db,'A',names=(None,'','Vehicle','Drug-X','Drug X'))
    db.execute("UPDATE interventions SET intervention_type='DEVICE' WHERE ord=3")
    b.analyze(db)
    assert db.execute('SELECT candidate_key FROM name_summary').fetchall()==[('drug x',)]
    assert db.execute('SELECT count(*) FROM intervention_names').fetchone()==(5,)
    assert b.normalize_drug_name('Drug-X 20 mg')=='drug x 20 mg'


def test_alias_collision_does_not_expand_names_and_children_do_not_multiply(db):
    trial(db,'A',names=('Drug X','Other'));trial(db,'B','PHASE2','2009-01-01',('Alias only',))
    db.execute("INSERT INTO aliases VALUES ('A',0,0,0,'Drug X','Alias only','2008-01-01'),('A',0,1,0,'Other','Alias only','2008-01-01')")
    db.execute("INSERT INTO conditions VALUES ('A',0,0,'Disease X',false,NULL),('A',0,1,'Disease Y',false,NULL)")
    b.analyze(db)
    assert db.execute('SELECT bool_and(alias_collision) FROM alias_summary').fetchone()==(True,)
    assert db.execute('SELECT names_with_any_prior FROM later_trial_coverage').fetchone()==(0,)
    assert db.execute('SELECT count(*) FROM intervention_names').fetchone()==(3,)
    assert db.execute("SELECT aliases_rows,conditions_rows FROM trial_child_coverage WHERE nct_id='A'").fetchone()==(2,2)


def test_missing_alias_parent_and_public_date_remain_visible(db):
    trial(db,'A')
    db.execute("INSERT INTO aliases VALUES ('A',0,9,0,'Unknown','Alt',NULL),('A',0,0,0,'Drug X','Drug X','2012-01-01')")
    b.analyze(db)
    assert db.execute('SELECT count(*) FROM alias_summary WHERE orphan_parent AND public_date_missing').fetchone()==(1,)
    assert db.execute('SELECT count(*) FROM alias_summary WHERE self_alias_written AND public_date_mismatch').fetchone()==(1,)


def test_common_names_high_fanout_and_normalization_collisions(db):
    for i in range(100):trial(db,f'A{i:03}',names=('Drug-X' if i%2 else 'Drug X',))
    trial(db,'B','PHASE2','2009-01-01')
    b.analyze(db)
    assert db.execute('SELECT high_fanout,raw_name_variants,distinct_trials FROM name_summary').fetchone()==(True,2,101)
    assert db.execute('SELECT earlier_name_trials FROM name_coverage').fetchone()==(100,)


@pytest.mark.parametrize('table,insert',[
    ('interventions',"SELECT * FROM interventions"),
    ('trials',"SELECT * FROM trials"),
    ('arms',"SELECT * FROM arms"),
    ('edges',"SELECT * FROM edges"),
    ('assertions',"SELECT * FROM assertions"),
    ('aliases',"SELECT * FROM aliases"),
    ('conditions',"SELECT * FROM conditions"),
])
def test_duplicate_natural_keys_fail(db,table,insert):
    trial(db,'A');edge(db,'A')
    db.execute("INSERT INTO aliases VALUES ('A',0,0,0,'Drug X','Alt','2008-01-01')")
    db.execute("INSERT INTO conditions VALUES ('A',0,0,'Disease',false,NULL)")
    db.execute(f'INSERT INTO {table} {insert}')
    with pytest.raises(ValueError,match='Duplicate'):b.analyze(db)


@pytest.mark.parametrize('table', ['aliases','conditions'])
def test_direct_version_bleed_fails(db,table):
    trial(db,'A')
    if table=='aliases':db.execute("INSERT INTO aliases VALUES ('A',1,0,0,'Drug X','Alt','2008-01-01')")
    else:db.execute("INSERT INTO conditions VALUES ('A',1,0,'Future disease',false,NULL)")
    with pytest.raises(ValueError,match='version bleed'):b.analyze(db)


def test_source_child_loading_filters_exact_versions_before_values(db,tmp_path):
    trial(db,'A');trial(db,'B','PHASE2','2009-01-01')
    db.execute("INSERT INTO aliases VALUES ('A',0,0,0,'Drug X','Correct','2008-01-01'),('A',1,0,0,'Drug X','Future','2012-01-01')")
    db.execute("INSERT INTO conditions VALUES ('A',0,0,'Correct condition',false,NULL),('A',1,0,'Future condition',false,NULL),('HOLDOUT',0,0,'Sealed',false,NULL)")
    for t in ('aliases','conditions'):
        db.execute(f"COPY {t} TO {b.sp(tmp_path/(t+'.parquet'))} (FORMAT PARQUET)")
        db.execute(f'DROP TABLE {t}')
    audit=b.load_children(db,tmp_path/'aliases.parquet',[tmp_path/'conditions.parquet'],'frozen')
    assert audit['conditions']=={'selected_exact_version_rows':1,'other_versions_of_selected_ncts_key_only':1}
    assert db.execute('SELECT condition,b26_public_date_provenance FROM conditions').fetchone()==('Correct condition','exact_version_only_no_independent_public_date')
    assert db.execute('SELECT other_name FROM aliases').fetchall()==[('Correct',)]
    b.analyze(db)
    assert db.execute("SELECT aliases_rows,conditions_rows FROM trial_child_coverage WHERE nct_id='B'").fetchone()==(0,0)


@pytest.mark.parametrize('table,column',[('interventions','outcome_value'),('aliases','chembl_id'),
    ('trials','final_status'),('conditions','result_date'),('arms','enrollment'),('trials','holdout_label')])
def test_attempted_leakage_rejected(db,table,column):
    trial(db,'A')
    db.execute(f'ALTER TABLE {table} ADD COLUMN {column} VARCHAR')
    with pytest.raises(ValueError,match='Forbidden'):b.analyze(db)


def test_holdout_date_and_same_nct_across_phases_rejected(db):
    trial(db,'A',when='2024-01-01')
    with pytest.raises(ValueError,match='Non-development'):b.analyze(db)
    db.execute('DELETE FROM trials');db.execute('DELETE FROM interventions')
    trial(db,'A');trial(db,'A','PHASE2','2009-01-01',version=1)
    with pytest.raises(ValueError,match='Duplicate trials'):b.analyze(db)


def test_hash_tampering_and_existing_output_refused(tmp_path):
    p=tmp_path/'data';p.write_text('tampered')
    with pytest.raises(ValueError,match='SHA-256'):b.check_hash(p,'0'*64)
    with pytest.raises(ValueError):b.build(tmp_path/'b26_forbidden_location')


def test_writer_replay_all_files_byte_identical(db,tmp_path,monkeypatch):
    trial(db,'A');trial(db,'B','PHASE2','2009-01-01');edge(db,'B')
    result=b.analyze(db)
    graph=tmp_path/'graph';graph.mkdir()
    for table in b.GRAPH_TABLES:
        db.execute(f"COPY {table} TO {b.sp(graph/(table+'.parquet'))} (FORMAT PARQUET)")
    monkeypatch.setattr(b,'GRAPH',graph)
    a,z=tmp_path/'b26_a',tmp_path/'b26_z'
    b.write_outputs(db,a,result,{'synthetic':'fixed'})
    b.write_outputs(db,z,result,{'synthetic':'fixed'})
    assert {p.name:b.sha(p) for p in a.iterdir()}=={p.name:b.sha(p) for p in z.iterdir()}
    manifest=json.loads((a/'manifest.json').read_text())
    assert len(manifest['output_sha256'])==17
    assert all(b.sha(a/p)==h for p,h in manifest['output_sha256'].items())
    for t in b.GRAPH_TABLES:assert b.sha(a/(t+'.parquet'))==b.sha(graph/(t+'.parquet'))
    with pytest.raises(FileExistsError):b.write_outputs(db,a,result,{})
