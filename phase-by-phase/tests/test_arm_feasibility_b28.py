"""Synthetic exact-key safety and denominator tests; no real result access."""
import json
from pathlib import Path

import pytest

from phase_by_phase import arm_feasibility_b28 as b


@pytest.fixture
def db():
    d = b.connect()
    d.execute('''CREATE TABLE selected AS SELECT 'T' AS target_nct_id,0 AS target_first_public_version,
        DATE '2019-01-01' AS target_checkpoint,'P' AS prior_nct_id,0 AS prior_first_public_version,
        DATE '2010-01-01' AS prior_first_public_date,'PHASE2' AS prior_phase,'drug' AS candidate_key,
        [0] AS target_intervention_ordinals,[0] AS prior_intervention_ordinals,
        150 AS name_trial_fanout,true AS asof_current_primary_measurement''')
    d.execute("CREATE TABLE proxy_classes AS SELECT 'T' AS target_nct_id,1 AS label_proxy_class")
    b.prepare_requests(d)
    d.execute('CREATE TABLE trials AS SELECT * FROM requests')
    d.execute('''CREATE TABLE interventions(nct_id VARCHAR,nct_version INTEGER,ord INTEGER,
        candidate_key VARCHAR,intervention_name VARCHAR,intervention_type VARCHAR,
        possible_combination_string BOOLEAN,adapter_version_public_date DATE,is_obsolete BOOLEAN,
        adapter_core_is_obsolete BOOLEAN,adapter_version_key_resolved BOOLEAN)''')
    d.execute('''CREATE TABLE arms(nct_id VARCHAR,nct_version INTEGER,ord INTEGER,
        arm_type VARCHAR,adapter_version_public_date DATE)''')
    d.execute('''CREATE TABLE edges(nct_id VARCHAR,nct_version INTEGER,intervention_ord INTEGER,
        arm_group_ord INTEGER,checkpoint_date DATE,edge_class VARCHAR,has_intervention BOOLEAN,
        has_arm_group BOOLEAN,valid_intervention BOOLEAN,valid_arm_group BOOLEAN,audit_uncertain BOOLEAN)''')
    d.execute('''CREATE TABLE conditions(nct_id VARCHAR,nct_version INTEGER,ord INTEGER,
        condition VARCHAR,is_obsolete BOOLEAN)''')
    d.execute('CREATE TABLE source_assertions(assertion_id BIGINT)')
    for trial in ('T','P'):
        add_intervention(d, trial)
        add_arm(d, trial)
        add_edge(d, trial)
    yield d
    d.close()


def date(trial):
    return '2019-01-01' if trial=='T' else '2010-01-01'


def add_intervention(d, trial, ordinal=0, key='drug', raw='Drug', category='DRUG', version=0):
    d.execute('INSERT INTO interventions VALUES (?,?,?,?,?,?,false,?,false,false,true)',
              [trial,version,ordinal,key,raw,category,date(trial)])


def add_arm(d, trial, arm=0, role='EXPERIMENTAL', version=0):
    d.execute('INSERT INTO arms VALUES (?,?,?,?,?)',[trial,version,arm,role,date(trial)])


def add_edge(d, trial, ordinal=0, arm=0, kind='reciprocal', version=0):
    hi, ha = kind!='arm_group_only', kind!='intervention_only'
    d.execute('INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?,false)',
              [trial,version,ordinal,arm,date(trial),kind,hi,ha,hi,ha])


def result(d):
    b.build(d)
    return b.records(d,'SELECT * FROM pair_review')[0]


def test_strict_ignores_fanout_and_condition_mismatch(db):
    db.execute("INSERT INTO conditions VALUES ('T',0,0,'A',false),('P',0,0,'B',false)")
    row = result(db)
    assert row['tier_rank']==1 and row['strict_both']
    assert row['high_fanout'] and row['exact_condition_overlap'] is False
    assert b.grain_counts(db)[0]['targets']==1
    assert b.report(db)['sensitivities']['strict_low_fanout']==[]


@pytest.mark.parametrize('column,value', [('valid_intervention','false'),('valid_arm_group','false'),
    ('audit_uncertain','true'),('audit_uncertain','NULL'),('valid_arm_group','NULL')])
def test_same_edge_validity_required(db,column,value):
    db.execute(f"UPDATE edges SET {column}={value} WHERE nct_id='T'")
    row=result(db)
    assert row['tier_rank']==3 and not row['strict_both']


def test_other_ordinal_reciprocity_cannot_rescue(db):
    db.execute("UPDATE edges SET edge_class='intervention_only',has_arm_group=false,valid_arm_group=false WHERE nct_id='T'")
    add_intervention(db,'T',1)
    add_edge(db,'T',1,kind='arm_group_only')
    row=result(db)
    assert not row['strict_both'] and row['one_sided']
    assert row['tier_rank']==2  # two raw DRUG ordinals on this same arm


def test_opposite_directions_on_different_arms_are_not_reciprocal(db):
    db.execute("UPDATE edges SET edge_class='intervention_only',has_arm_group=false,valid_arm_group=false WHERE nct_id='T'")
    add_arm(db,'T',1)
    add_edge(db,'T',arm=1,kind='arm_group_only')
    row=result(db)
    assert row['tier_rank']==4 and not row['strict_both']


def test_other_ordinal_control_role_does_not_poison_actual_join(db):
    add_intervention(db,'T',1)
    add_arm(db,'T',1,'ACTIVE_COMPARATOR')
    add_edge(db,'T',1,1)
    row=result(db)
    assert row['tier_rank']==1 and not row['control']
    assert b.n(db,'SELECT count(*) FROM ordinal_review')==2


def test_same_ordinal_control_collision_blocks_strict(db):
    add_arm(db,'T',1,'ACTIVE_COMPARATOR')
    add_edge(db,'T',arm=1)
    row=result(db)
    assert row['tier_rank']==2 and row['control'] and not row['strict_both']


@pytest.mark.parametrize('raw,key', [('Other','other'),('Drug','drug'),('Placebo',None)])
def test_arm_regimen_uses_all_actual_drug_ordinals(db,raw,key):
    add_intervention(db,'T',1,key,raw)
    add_edge(db,'T',1)
    row=result(db)
    assert row['tier_rank']==2 and row['combination'] and not row['strict_both']


def test_non_drug_cannot_supply_candidate(db):
    db.execute("UPDATE interventions SET intervention_type='DEVICE' WHERE nct_id='T'")
    row=result(db)
    assert not row['strict_both'] and row['missing_intervention']


def test_multiple_experimental_arms_not_unique_and_no_target_inflation(db):
    add_arm(db,'T',1)
    add_edge(db,'T',arm=1)
    row=result(db)
    assert row['tier_rank']==3 and row['arm_paths']==2
    assert b.grain_counts(db)[0]['targets']==1
    assert b.grain_counts(db)[0]['name_prior_pairs']==1
    assert b.grain_counts(db)[0]['arm_pairs']==2


def test_unlinked_and_unknown_preserved(db):
    db.execute("DELETE FROM edges WHERE nct_id='T'")
    row=result(db)
    assert row['tier_rank']==5 and row['unlinked_unknown'] and row['arm_paths']==1
    assert row['exact_condition_overlap'] is None
    assert b.n(db,'SELECT count(*) FROM target_review')==1


@pytest.mark.parametrize('role',[None,'OTHER','ACTIVE_COMPARATOR','PLACEBO_COMPARATOR'])
def test_role_is_actual_arm_and_unknown_is_not_exposed(db,role):
    db.execute("UPDATE arms SET arm_type=? WHERE nct_id='T'",[role])
    row=result(db)
    assert not row['strict_both']
    assert row['tier_rank']==(2 if role in ('ACTIVE_COMPARATOR','PLACEBO_COMPARATOR') else 3)


def test_alias_collision_does_not_expand_canonical_ordinals(db):
    db.execute("CREATE TABLE aliases AS SELECT 'T' AS nct_id,9 AS intervention_ord,'Drug' AS alias")
    add_intervention(db,'T',9,'other','Other')
    add_arm(db,'T',9,'ACTIVE_COMPARATOR')
    add_edge(db,'T',9,9)
    assert result(db)['tier_rank']==1
    assert b.n(db,'SELECT count(*) FROM ordinal_review')==2


def test_different_versions_never_supply_missing_ordinal(db):
    db.execute("UPDATE interventions SET nct_version=9 WHERE nct_id='T'")
    row=result(db)
    assert row['missing_intervention'] and not row['strict_both']


@pytest.mark.parametrize('table',['arms','interventions'])
@pytest.mark.parametrize('value',[None,'2023-01-01'])
def test_null_or_future_child_public_date_fails_closed(db,table,value):
    db.execute(f"UPDATE {table} SET adapter_version_public_date=? WHERE nct_id='T'",[value])
    with pytest.raises(ValueError,match='child date'):
        b.build(db)


def test_first_public_frame_version_bleed_fails_closed(db):
    db.execute("UPDATE trials SET nct_version=7 WHERE nct_id='T'")
    with pytest.raises(ValueError,match='frame date/version'):
        b.build(db)


@pytest.mark.parametrize('table',['arms','interventions','edges'])
def test_duplicate_natural_keys_rejected(db,table):
    db.execute(f'INSERT INTO {table} SELECT * FROM {table} LIMIT 1')
    with pytest.raises(ValueError,match='Duplicate'):
        b.build(db)


def test_raw_equality_separate_from_normalized_equality(db):
    db.execute("UPDATE interventions SET intervention_name='DRUG' WHERE nct_id='P'")
    row=result(db)
    assert row['strict_both'] and row['any_exact_raw_name_equal'] is False


def test_proxy_class_cannot_change_exposure(db):
    db.execute('UPDATE proxy_classes SET label_proxy_class=0')
    assert result(db)['tier_rank']==1


def test_empty_ordinal_list_keeps_pair_unknown(db):
    db.execute("DELETE FROM ordinal_requests WHERE nct_id='T'")
    row=result(db)
    assert row['tier_rank']==5 and row['unlinked_unknown']
    assert b.grain_counts(db)[0]['name_prior_pairs']==1


def test_manifest_authentication_before_connection(tmp_path,monkeypatch):
    p=tmp_path/'manifest.json'
    p.write_text('{}')
    monkeypatch.setattr(b,'PINS',{tmp_path:'0'*64})
    monkeypatch.setattr(b,'connect',lambda: pytest.fail('Connection before authentication'))
    with pytest.raises(ValueError,match='manifest SHA-256'):
        b.verify_inputs()


def test_child_hash_tamper_rejected(tmp_path,monkeypatch):
    child=tmp_path/'candidate_pairs.parquet'
    child.write_bytes(b'tampered')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'output_sha256':{child.name:'0'*64}}))
    monkeypatch.setattr(b,'ROOT',tmp_path)
    monkeypatch.setattr(b,'PINS',{tmp_path:b.sha(manifest)})
    monkeypatch.setattr(b,'USED',{tmp_path:('candidate_pairs',)})
    with pytest.raises(ValueError,match='child SHA-256'):
        b.verify_inputs()


def test_no_result_or_remote_source_path():
    assert set(b.USED[b.B27R])=={'candidate_pairs'}
    assert all('results_' not in table for tables in b.USED.values() for table in tables)
    assert b.B27R.name.startswith('b27r_')


def test_resource_limits(db):
    assert b.n(db,"SELECT current_setting('threads')")==2
    assert b.n(db,"SELECT current_setting('temp_directory')") == ''
    assert b.n(db,"SELECT current_setting('memory_limit')") == '2.0 GiB'
