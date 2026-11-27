"""Pinned, offline B26 source-name audit. No clinical or result linkage is inferred.

Canonical DRUG names use B18 verbatim. Alias/condition children never enlarge name
links. Date aggregates replace global intervention pairs; all later coverage is
retrospective descriptive output, not a training feature table.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

import duckdb

from .drug_level_candidates import normalize_drug_name

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / 'data/processed/b24_full_2026-11-27_v2'
GRAPH_SHA = 'f193bf4d65424b415552ac644be20b8591495537ae85923ca2248aaab66318c0'
ALIASES = ROOT / 'data/processed/anamnesis_full_b11a_repair2_2026-11-25/intervention_aliases_clean.parquet'
ALIAS_SHA = '3b22aeca92560c8f21ff30d87e656cc16f429f17d1c8037fa749a958eed4e583'
SOURCE_MANIFEST = ROOT / 'data/processed/anamnesis_full_source_manifest_2026-11-25.json'
SOURCE_SHA = 'a1b318aafc861a6948a53d74fbffabd3694e82aa986d8227ddc14187edea2219'
GRAPH_TABLES = ('trials', 'arms', 'interventions', 'assertions', 'edges')
B24_FILES = {x+'.parquet' for x in (*GRAPH_TABLES, 'names_exact', 'names_folded',
                                  'policy_rows', 'trial_policy', 'review')} | {'report.json', 'review_examples.json'}
HIGH_FANOUT = 100  # descriptive flag; never an exclusion or a linkage policy
BOUNDARY = ('Exploratory candidate-name overlap only; clinical identity and earlier result '
            'availability unknown. No molecule, regimen, indication or program verification. '
            'All coverage and cross-phase counts are retrospective descriptive audits, not '
            'prediction features. No chemical annotations, results, holdout, network or model.')
FORBIDDEN = re.compile(r'(?i)\b(final_status|overall_status|enrollment|stopping_reason|p_value|'
                       r'pvalue|outcome\w*|result\w*|chembl\w*|max_phase|approved|'
                       r'target_label|holdout\w*|prediction\w*|model_score)\b')
OUTPUT_TABLES = ('aliases', 'conditions', 'alias_summary', 'intervention_names',
                 'name_trials', 'name_dates', 'name_summary', 'name_coverage',
                 'later_trial_coverage', 'trial_child_coverage')


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, default=str)+'\n')


def sp(path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def rows(db, query):
    cur = db.execute(query)
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def count(db, query):
    return db.execute(query).fetchone()[0]


def connect():
    db = duckdb.connect()
    db.execute("SET memory_limit='2GiB'")
    db.execute('SET threads=2')
    db.execute('SET preserve_insertion_order=false')
    db.execute("SET temp_directory=''")
    db.create_function('b18_key', normalize_drug_name, ['VARCHAR'], 'VARCHAR', null_handling='special')
    db.create_function('alias_fold', lambda x: x.casefold().strip() or None if x is not None else None,
                       ['VARCHAR'], 'VARCHAR', null_handling='special')
    return db


def check_hash(path, expected):
    if sha(path) != expected:
        raise ValueError(f'SHA-256 mismatch: {path}')


def verify_inputs():
    """Authenticate before any source row query; never follow arbitrary manifests."""
    check_hash(GRAPH/'manifest.json', GRAPH_SHA)
    check_hash(ALIASES, ALIAS_SHA)
    check_hash(SOURCE_MANIFEST, SOURCE_SHA)
    manifest = json.loads((GRAPH/'manifest.json').read_text())
    if set(manifest['output_sha256']) != B24_FILES:
        raise ValueError('Unexpected B24 file inventory')
    inputs = {str(p.relative_to(ROOT)): h for p, h in (
        (GRAPH/'manifest.json', GRAPH_SHA), (ALIASES, ALIAS_SHA), (SOURCE_MANIFEST, SOURCE_SHA))}
    for name, h in sorted(manifest['output_sha256'].items()):
        p = GRAPH/name
        check_hash(p, h)
        inputs[str(p.relative_to(ROOT))] = h
    normalizer = Path(__file__).with_name('drug_level_candidates.py')
    check_hash(normalizer, manifest['b18_normalizer_code_sha256'])
    source = json.loads(SOURCE_MANIFEST.read_text())
    parts = source['tables']['conditions']['files']
    if len(parts) != 20:
        raise ValueError('Expected 20 pinned condition parts')
    paths = []
    for part in parts:
        relative = Path(part['relative_path'])
        if relative.parts[0] != 'conditions' or len(relative.parts) != 2 or '..' in relative.parts:
            raise ValueError('Non-condition source path refused')
        p = Path(source['source_root'])/relative
        p.resolve().relative_to((ROOT/'data/raw/anamnesis').resolve())
        check_hash(p, part['sha256'])
        inputs[str(p.relative_to(ROOT))] = part['sha256']
        paths.append(p)
    return inputs, paths, source['source_commit'], source['tables']['conditions']


def firewall(db, table):
    # Includes nested struct member names/types in B24 assertions.
    for column in db.execute(f'DESCRIBE {table}').fetchall():
        if FORBIDDEN.search(column[0]+' '+column[1]):
            raise ValueError(f'Forbidden non-source field in {table}: {column[0]}')


def unique(db, table, keys):
    missing = ' OR '.join(f'{k} IS NULL' for k in keys)
    if count(db, f'SELECT count(*) FROM {table} WHERE {missing}'):
        raise ValueError(f'Missing {table} natural key')
    if count(db, f'SELECT count(*) FROM (SELECT {",".join(keys)} FROM {table} GROUP BY ALL HAVING count(*)>1)'):
        raise ValueError(f'Duplicate {table} natural key')


def load_children(db, alias_path, condition_paths, source_commit):
    """Materialize values ONLY after exact-version semijoin; key-only exclusion audit."""
    db.execute(f'CREATE VIEW alias_source AS SELECT * FROM read_parquet({sp(alias_path)})')
    firewall(db, 'alias_source')
    paths = '['+','.join(sp(p) for p in condition_paths)+']'
    db.execute(f'''CREATE VIEW condition_source AS SELECT * FROM read_parquet({paths},
                   filename=true,file_row_number=true)''')
    firewall(db, 'condition_source')
    # Conditions in the pinned source have no independent public-date field.
    condition_columns = {r[0] for r in db.execute('DESCRIBE condition_source').fetchall()}
    if condition_columns != {'nct_id','nct_version','ord','condition','is_obsolete','obsolete_by',
                             'filename','file_row_number'}:
        raise ValueError('Condition schema changed: inspect public-date provenance before use')
    db.execute('''CREATE TABLE aliases AS SELECT s.* FROM alias_source s
                  SEMI JOIN trials t USING(nct_id,nct_version)''')
    db.execute(f'''CREATE TABLE conditions AS SELECT s.* EXCLUDE(filename,file_row_number),
        filename AS b26_source_file,file_row_number AS b26_source_row,
        {sp(source_commit)} AS b26_source_commit,t.checkpoint_date AS b26_exact_version_checkpoint,
        'exact_version_only_no_independent_public_date' AS b26_public_date_provenance
        FROM condition_source s JOIN trials t USING(nct_id,nct_version)''')
    audit = {}
    for label, source in (('aliases','alias_source'),('conditions','condition_source')):
        audit[label] = {
            'selected_exact_version_rows': count(db, f'SELECT count(*) FROM {label}'),
            'other_versions_of_selected_ncts_key_only': count(db, f'''SELECT count(*) FROM {source} s
                SEMI JOIN trials t USING(nct_id)
                ANTI JOIN trials x ON s.nct_id=x.nct_id AND s.nct_version=x.nct_version'''),
        }
    return audit


def validate_graph(db):
    for t in (*GRAPH_TABLES, 'aliases', 'conditions'):
        firewall(db, t)
    for t, k in (('trials',['nct_id','nct_version']),('arms',['nct_id','nct_version','ord']),
                 ('interventions',['nct_id','nct_version','ord']),('assertions',['assertion_id']),
                 ('edges',['nct_id','nct_version','arm_group_ord','intervention_ord']),
                 ('aliases',['nct_id','nct_version','intervention_ord','other_name_ord']),
                 ('conditions',['nct_id','nct_version','ord'])):
        unique(db, t, k)
    unique(db, 'trials', ['nct_id'])  # one first-public row; different phases cannot be same NCT
    if count(db, "SELECT count(*) FROM trials WHERE pure_phase NOT IN ('PHASE1','PHASE2','PHASE3') OR pure_phase IS NULL OR checkpoint_date>=DATE '2020-01-01'"):
        raise ValueError('Non-development first-public cohort')
    for table in (*GRAPH_TABLES[1:], 'aliases', 'conditions'):
        if count(db, f'SELECT count(*) FROM {table} ANTI JOIN trials USING(nct_id,nct_version)'):
            raise ValueError(f'Orphan/version bleed in {table}')
    # B24's first-public graph must attest the canonical/role source date, not
    # merely carry a first-public key next to a future child. Fail closed rather
    # than silently changing the exploratory name denominator. Unknown trial
    # checkpoints stay inspectable and cannot enter a strict earlier-date link.
    for table in ('arms', 'interventions'):
        if count(db, f'''SELECT count(*) FROM {table} JOIN trials USING(nct_id,nct_version)
            WHERE checkpoint_date IS NOT NULL AND (adapter_version_public_date IS NULL
              OR adapter_version_public_date<>checkpoint_date)'''):
            raise ValueError(f'Unverifiable first-public {table} public date')
    for col, child in (('intervention_ord','interventions'),('arm_group_ord','arms')):
        if count(db, f'''SELECT count(*) FROM edges e ANTI JOIN {child} c
            ON e.nct_id=c.nct_id AND e.nct_version=c.nct_version AND e.{col}=c.ord'''):
            raise ValueError(f'Orphan edge {child}')


def analyze(db):
    validate_graph(db)
    db.execute('''CREATE TABLE alias_summary AS WITH a AS (
        SELECT a.*,i.intervention_name AS parent_raw_name,
        CASE WHEN upper(i.intervention_type)='DRUG' THEN b18_key(i.intervention_name) END AS parent_candidate_key,
        alias_fold(a.other_name) AS alias_written_key,i.ord IS NULL AS orphan_parent,
        a.intervention_name IS DISTINCT FROM i.intervention_name AS parent_written_name_mismatch,
        a.adapter_version_public_date IS NULL AS public_date_missing,
        coalesce(a.adapter_version_public_date<>t.checkpoint_date,false) AS public_date_mismatch
        FROM aliases a JOIN trials t USING(nct_id,nct_version)
        LEFT JOIN interventions i ON a.nct_id=i.nct_id AND a.nct_version=i.nct_version AND a.intervention_ord=i.ord
      ), collisions AS (SELECT alias_written_key,count(DISTINCT parent_candidate_key) AS canonical_names
        FROM a WHERE alias_written_key IS NOT NULL GROUP BY 1)
      SELECT a.*,coalesce(c.canonical_names,0) AS alias_canonical_name_count,
        coalesce(c.canonical_names>1,false) AS alias_collision,
        alias_written_key=alias_fold(parent_raw_name) AS self_alias_written
      FROM a LEFT JOIN collisions c USING(alias_written_key)''')
    db.execute('''CREATE TABLE arm_multiplicity AS SELECT e.nct_id,e.nct_version,e.arm_group_ord,
        count(DISTINCT e.intervention_ord) FILTER(WHERE upper(i.intervention_type)='DRUG') AS raw_drugs
        FROM edges e JOIN interventions i ON e.nct_id=i.nct_id AND e.nct_version=i.nct_version AND e.intervention_ord=i.ord
        GROUP BY 1,2,3''')
    db.execute('''CREATE TABLE intervention_names AS WITH edge_flags AS (
        SELECT e.nct_id,e.nct_version,e.intervention_ord,count(*) AS arm_edges,
        count(*) FILTER(WHERE e.edge_class='reciprocal') AS reciprocal_edges,
        count(*) FILTER(WHERE e.edge_class='intervention_only') AS intervention_only_edges,
        count(*) FILTER(WHERE e.edge_class='arm_group_only') AS arm_group_only_edges,
        bool_or(m.raw_drugs>1) AS possible_multi_drug_arm_or_direction_conflict,
        bool_or(a.arm_type='EXPERIMENTAL') AS experimental_role,
        bool_or(a.arm_type IN ('ACTIVE_COMPARATOR','PLACEBO_COMPARATOR','SHAM_COMPARATOR','NO_INTERVENTION')) AS control_role,
        bool_or(a.arm_type IS NULL OR a.arm_type NOT IN ('EXPERIMENTAL','ACTIVE_COMPARATOR','PLACEBO_COMPARATOR','SHAM_COMPARATOR','NO_INTERVENTION')) AS unknown_or_other_role
        FROM edges e JOIN arms a ON e.nct_id=a.nct_id AND e.nct_version=a.nct_version AND e.arm_group_ord=a.ord
        JOIN arm_multiplicity m ON e.nct_id=m.nct_id AND e.nct_version=m.nct_version
          AND e.arm_group_ord=m.arm_group_ord GROUP BY 1,2,3
      ), base AS (SELECT i.*,t.pure_phase,t.checkpoint_date,
        CASE WHEN upper(i.intervention_type)='DRUG' THEN b18_key(i.intervention_name) END AS candidate_key,
        coalesce(e.arm_edges,0) AS arm_edges,coalesce(e.reciprocal_edges,0) AS reciprocal_edges,
        coalesce(e.intervention_only_edges,0) AS intervention_only_edges,
        coalesce(e.arm_group_only_edges,0) AS arm_group_only_edges,
        coalesce(e.possible_multi_drug_arm_or_direction_conflict,false) AS possible_multi_drug_arm_or_direction_conflict,
        coalesce(e.experimental_role,false) AS experimental_role,coalesce(e.control_role,false) AS control_role,
        coalesce(e.unknown_or_other_role,true) AS unknown_or_other_role,
        i.adapter_version_public_date IS NULL AS public_date_missing,
        coalesce(i.adapter_version_public_date<>t.checkpoint_date,false) AS public_date_mismatch,
        regexp_matches(coalesce(i.intervention_name,''),'(?i)([+/&]|\\b(and|plus|combination)\\b)') AS possible_combination_string
        FROM interventions i JOIN trials t USING(nct_id,nct_version)
        LEFT JOIN edge_flags e ON i.nct_id=e.nct_id AND i.nct_version=e.nct_version AND i.ord=e.intervention_ord)
      SELECT *,arm_edges=0 AS unlinked,intervention_only_edges+arm_group_only_edges>0 AS has_one_sided,
        experimental_role AND control_role AS shared_experimental_control,
        CASE WHEN upper(intervention_type)<>'DRUG' OR intervention_type IS NULL THEN 'non_drug'
             WHEN intervention_name IS NULL OR trim(intervention_name)='' THEN 'empty_or_null'
             WHEN candidate_key IS NULL THEN 'b18_control_or_empty_exclusion' ELSE 'candidate' END AS name_status
      FROM base''')
    # One row/name/trial. All DRUG strings survive irrespective of arm support or role.
    db.execute('''CREATE TABLE name_trials AS SELECT candidate_key,nct_id,nct_version,pure_phase,checkpoint_date,
        count(*) AS intervention_rows,bool_or(unlinked) AS has_unlinked,
        bool_or(has_one_sided) AS has_one_sided,bool_or(reciprocal_edges>0) AS has_reciprocal,
        bool_or(control_role) AS has_control_role,bool_or(shared_experimental_control) AS shared_experimental_control,
        bool_or(possible_combination_string OR possible_multi_drug_arm_or_direction_conflict) AS possible_combination_or_conflict,
        list(ord ORDER BY ord) AS intervention_ordinals
        FROM intervention_names WHERE candidate_key IS NOT NULL GROUP BY 1,2,3,4,5''')
    db.execute('''CREATE TABLE name_dates AS WITH dates AS (
        SELECT candidate_key,pure_phase,checkpoint_date,count(*) AS trial_count,min(nct_id) AS date_example_nct
        FROM name_trials WHERE checkpoint_date IS NOT NULL GROUP BY 1,2,3)
      SELECT *,sum(trial_count) OVER w AS cumulative_trials,
        first_value(date_example_nct) OVER w AS earliest_example_nct,
        min(checkpoint_date) OVER w AS earliest_checkpoint
        FROM dates WINDOW w AS (PARTITION BY candidate_key,pure_phase ORDER BY checkpoint_date
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)''')
    db.execute('''CREATE TABLE name_summary AS WITH names AS (
        SELECT candidate_key,count(*) AS distinct_trials,count(DISTINCT pure_phase) AS phases,
        min(checkpoint_date) AS first_checkpoint,max(checkpoint_date) AS last_checkpoint,
        count(*) FILTER(WHERE checkpoint_date IS NULL) AS missing_dates,
        sum(intervention_rows) AS intervention_rows,count(*) FILTER(WHERE has_unlinked) AS unlinked_trials,
        count(*) FILTER(WHERE has_one_sided) AS one_sided_trials,
        count(*) FILTER(WHERE has_reciprocal) AS reciprocal_trials,
        count(*) FILTER(WHERE has_control_role) AS control_role_trials,
        count(*) FILTER(WHERE possible_combination_or_conflict) AS combination_or_conflict_trials
        FROM name_trials GROUP BY 1), raw AS (
        SELECT candidate_key,count(DISTINCT intervention_name) AS raw_name_variants
        FROM intervention_names WHERE candidate_key IS NOT NULL GROUP BY 1)
      SELECT *,distinct_trials>='''+str(HIGH_FANOUT)+''' AS high_fanout,
        raw_name_variants>1 AS normalization_written_name_collision
        FROM names JOIN raw USING(candidate_key)''')
    db.execute('''CREATE TABLE prior_totals AS SELECT candidate_key,pure_phase,count(*) AS total_trials,
        count(*) FILTER(WHERE checkpoint_date IS NULL) AS missing_dates
        FROM name_trials GROUP BY 1,2''')
    pieces = []
    for prior, later in (('PHASE1','PHASE2'),('PHASE1','PHASE3'),('PHASE2','PHASE3')):
        pieces.append(f'''SELECT l.*, '{prior}' AS prior_phase,
          coalesce(d.cumulative_trials,0)::BIGINT AS earlier_name_trials,
          CASE WHEN d.cumulative_trials>0 THEN d.earliest_example_nct END AS earlier_example_nct,
          CASE WHEN d.cumulative_trials>0 THEN d.earliest_checkpoint END AS earlier_example_checkpoint,
          coalesce(tie.trial_count,0)::BIGINT AS tied_name_trials,
          coalesce(p.missing_dates,0)::BIGINT AS missing_prior_dates,
          CASE WHEN l.checkpoint_date IS NOT NULL THEN
            coalesce(p.total_trials,0)-coalesce(p.missing_dates,0)-coalesce(d.cumulative_trials,0)-coalesce(tie.trial_count,0)
          END::BIGINT AS future_name_trials,
          l.checkpoint_date IS NULL AS later_date_missing
          FROM (SELECT * FROM name_trials WHERE pure_phase='{later}') l
          ASOF LEFT JOIN (SELECT * FROM name_dates WHERE pure_phase='{prior}') d
            ON l.candidate_key=d.candidate_key AND l.checkpoint_date>d.checkpoint_date
          LEFT JOIN prior_totals p ON l.candidate_key=p.candidate_key AND p.pure_phase='{prior}'
          LEFT JOIN name_dates tie ON l.candidate_key=tie.candidate_key AND tie.pure_phase='{prior}'
            AND l.checkpoint_date=tie.checkpoint_date''')
    db.execute('CREATE TABLE name_coverage AS '+' UNION ALL '.join(pieces))
    db.execute('''CREATE TABLE later_trial_coverage AS WITH c AS (
        SELECT nct_id,nct_version,count(DISTINCT candidate_key) AS candidate_names,
        count(DISTINCT candidate_key) FILTER(WHERE prior_phase='PHASE1' AND earlier_name_trials>0) AS names_with_prior_p1,
        count(DISTINCT candidate_key) FILTER(WHERE prior_phase='PHASE2' AND earlier_name_trials>0) AS names_with_prior_p2,
        count(DISTINCT candidate_key) FILTER(WHERE earlier_name_trials>0) AS names_with_any_prior,
        bool_or(has_unlinked) AS has_unlinked_name,bool_or(has_one_sided) AS has_one_sided_name,
        bool_or(has_reciprocal) AS has_reciprocal_name
        FROM name_coverage GROUP BY 1,2)
      SELECT t.*,coalesce(c.candidate_names,0) AS candidate_names,
        coalesce(c.names_with_prior_p1,0) AS names_with_prior_p1,coalesce(c.names_with_prior_p2,0) AS names_with_prior_p2,
        coalesce(c.names_with_any_prior,0) AS names_with_any_prior,
        coalesce(c.has_unlinked_name,false) AS has_unlinked_name,
        coalesce(c.has_one_sided_name,false) AS has_one_sided_name,
        coalesce(c.has_reciprocal_name,false) AS has_reciprocal_name
        FROM trials t LEFT JOIN c USING(nct_id,nct_version) WHERE t.pure_phase IN ('PHASE2','PHASE3')''')
    # Child counts are independently aggregated, never multiplied together.
    child_joins, child_fields = [], []
    for child in ('arms','interventions','assertions','edges','aliases','conditions'):
        child_joins.append(f'LEFT JOIN (SELECT nct_id,nct_version,count(*) AS n FROM {child} GROUP BY 1,2) {child} USING(nct_id,nct_version)')
        child_fields.append(f'coalesce({child}.n,0) AS {child}_rows')
    db.execute('CREATE TABLE trial_child_coverage AS SELECT t.*,'+','.join(child_fields)+
               ' FROM trials t '+' '.join(child_joins))
    return report(db)


def report(db):
    tables = {t:count(db,f'SELECT count(*) FROM {t}') for t in (*GRAPH_TABLES,*OUTPUT_TABLES)}
    coverage = []
    for prior, later in (('PHASE1','PHASE2'),('PHASE1','PHASE3'),('PHASE2','PHASE3')):
        field = 'names_with_prior_p1' if prior=='PHASE1' else 'names_with_prior_p2'
        coverage.append({'prior_phase':prior,'later_phase':later,
            'later_trials':count(db,f"SELECT count(*) FROM later_trial_coverage WHERE pure_phase='{later}'"),
            'covered_distinct_later_trials':count(db,f"SELECT count(*) FROM later_trial_coverage WHERE pure_phase='{later}' AND {field}>0")})
    coverage.append({'prior_phase':'PHASE1_OR_PHASE2','later_phase':'PHASE3',
        'later_trials':count(db,"SELECT count(*) FROM later_trial_coverage WHERE pure_phase='PHASE3'"),
        'covered_distinct_later_trials':count(db,"SELECT count(*) FROM later_trial_coverage WHERE pure_phase='PHASE3' AND names_with_any_prior>0")})
    return {
        'boundary':BOUNDARY,'resources':{'memory_limit':'2GiB','threads':2,'spill':False},
        'method':{'name_normalizer':'B18 normalize_drug_name, unchanged; canonical DRUG names only',
                  'aliases':'attached children; casefold/trim collision audit only; never name-link expansion',
                  'conditions':'trial-level raw children; not verified indications; no independent public date column',
                  'timing':'strictly earlier checkpoint; distinct first-public NCTs; results availability unknown',
                  'canonical_provenance':'known checkpoint requires matching nonmissing arm/intervention source-public date; otherwise fail closed',
                  'high_fanout_threshold_distinct_trials':HIGH_FANOUT,
                  'combination_flag':'raw + / & or and/plus/combination marker OR multi-DRUG union arm; heuristic only',
                  'missing_children':'zero rows means source absence, not negative clinical evidence'},
        'tables':tables,'phase_trials':rows(db,'SELECT pure_phase,count(*) AS trials FROM trials GROUP BY 1 ORDER BY 1'),
        'coverage':coverage,
        'name_counts':{'unique':count(db,'SELECT count(*) FROM name_summary'),
            'at_least_two_phases':count(db,'SELECT count(*) FROM name_summary WHERE phases>=2'),
            'all_three_phases':count(db,'SELECT count(*) FROM name_summary WHERE phases=3'),
            'high_fanout':count(db,'SELECT count(*) FROM name_summary WHERE high_fanout'),
            'written_name_collisions':count(db,'SELECT count(*) FROM name_summary WHERE normalization_written_name_collision')},
        'timing_exclusions':rows(db,'''SELECT prior_phase,pure_phase AS later_phase,
            count(*) AS later_name_trial_rows,sum(tied_name_trials) AS tied_name_trial_comparisons,
            sum(future_name_trials) AS future_name_trial_comparisons,
            sum(missing_prior_dates) AS missing_prior_date_comparisons,
            count(*) FILTER(WHERE later_date_missing) AS missing_later_date_rows
            FROM name_coverage GROUP BY 1,2 ORDER BY 1,2'''),
        'intervention_denominators':rows(db,'''SELECT pure_phase,name_status,count(*) AS source_rows,
            count(DISTINCT nct_id) AS trials,count(*) FILTER(WHERE unlinked) AS unlinked_rows,
            count(*) FILTER(WHERE has_one_sided) AS one_sided_rows,
            count(*) FILTER(WHERE reciprocal_edges>0) AS reciprocal_rows,
            count(*) FILTER(WHERE possible_combination_string) AS combination_string_rows,
            count(*) FILTER(WHERE possible_multi_drug_arm_or_direction_conflict) AS multi_drug_or_conflict_rows,
            count(*) FILTER(WHERE control_role) AS control_role_rows,
            count(*) FILTER(WHERE shared_experimental_control) AS shared_control_rows,
            count(*) FILTER(WHERE unknown_or_other_role) AS unknown_or_other_role_rows,
            count(*) FILTER(WHERE public_date_missing) AS public_date_missing,
            count(*) FILTER(WHERE public_date_mismatch) AS public_date_mismatch
            FROM intervention_names GROUP BY 1,2 ORDER BY 1,2'''),
        'edge_counts':rows(db,'SELECT pure_phase,edge_class,count(*) AS edges FROM edges GROUP BY 1,2 ORDER BY 1,2'),
        'alias_flags':rows(db,'''SELECT orphan_parent,parent_written_name_mismatch,public_date_missing,
            public_date_mismatch,alias_collision,self_alias_written,count(*) AS source_rows
            FROM alias_summary GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4,5,6'''),
        'child_coverage':rows(db,'''SELECT pure_phase,count(*) AS trials,
            count(*) FILTER(WHERE arms_rows=0) AS no_arms,count(*) FILTER(WHERE interventions_rows=0) AS no_interventions,
            count(*) FILTER(WHERE aliases_rows=0) AS no_aliases,count(*) FILTER(WHERE conditions_rows=0) AS no_conditions,
            count(*) FILTER(WHERE edges_rows=0) AS no_edges FROM trial_child_coverage GROUP BY 1 ORDER BY 1'''),
        'source_date_flags':{t:rows(db,f'''SELECT adapter_version_public_date IS NULL AS public_date_missing,
            coalesce(adapter_version_public_date<>checkpoint_date,false) AS public_date_mismatch,count(*) AS source_rows
            FROM {t} JOIN trials USING(nct_id,nct_version) GROUP BY 1,2 ORDER BY 1,2''')
            for t in ('arms','interventions','aliases')},
    }


def write_outputs(db, out, result, inputs):
    out.mkdir(parents=True, exist_ok=False)
    # Exact byte copies keep wide B24 assertion structs out of sorting/memory pressure.
    for table in GRAPH_TABLES:
        shutil.copyfile(GRAPH/(table+'.parquet'), out/(table+'.parquet'))
    orders = {
        'aliases':'nct_id,nct_version,intervention_ord,other_name_ord',
        'conditions':'nct_id,nct_version,ord', 'alias_summary':'nct_id,nct_version,intervention_ord,other_name_ord',
        'intervention_names':'nct_id,nct_version,ord','name_trials':'candidate_key,pure_phase,checkpoint_date,nct_id',
        'name_dates':'candidate_key,pure_phase,checkpoint_date','name_summary':'candidate_key',
        'name_coverage':'nct_id,nct_version,candidate_key,prior_phase',
        'later_trial_coverage':'nct_id,nct_version','trial_child_coverage':'nct_id,nct_version'}
    for table in OUTPUT_TABLES:
        db.execute(f"COPY (SELECT * FROM {table} ORDER BY {orders[table]}) TO {sp(out/(table+'.parquet'))} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 16384)")
    examples = {
        'boundary':BOUNDARY,
        'high_fanout':rows(db,'SELECT * FROM name_summary ORDER BY distinct_trials DESC,candidate_key LIMIT 25'),
        'strict_earlier_candidates':rows(db,'''SELECT * FROM name_coverage WHERE earlier_name_trials>0
            ORDER BY prior_phase,pure_phase,candidate_key,nct_id LIMIT 30'''),
        'timing_excluded':rows(db,'''SELECT * FROM name_coverage WHERE tied_name_trials>0 OR future_name_trials>0 OR later_date_missing
            ORDER BY nct_id,candidate_key,prior_phase LIMIT 20'''),
        'unlinked':rows(db,'SELECT * FROM intervention_names WHERE unlinked ORDER BY nct_id,ord LIMIT 10'),
        'one_sided':rows(db,'SELECT * FROM intervention_names WHERE has_one_sided ORDER BY nct_id,ord LIMIT 10'),
        'combination_control':rows(db,'''SELECT * FROM intervention_names WHERE possible_combination_string OR shared_experimental_control
            ORDER BY nct_id,ord LIMIT 10'''),
        'alias_collisions':rows(db,'SELECT * FROM alias_summary WHERE alias_collision ORDER BY nct_id,intervention_ord,other_name_ord LIMIT 10'),
        'conditions':rows(db,'SELECT * FROM conditions ORDER BY nct_id,ord LIMIT 10'),
    }
    dump(out/'examples.json',examples)
    dump(out/'report.json',result)
    dump(out/'manifest.json',{
        'boundary':BOUNDARY,'input_sha256':inputs,
        'code_sha256':sha(Path(__file__)),
        'normalizer_code_sha256':sha(Path(__file__).with_name('drug_level_candidates.py')),
        'settings':{'high_fanout':HIGH_FANOUT,'memory':'2GiB','threads':2,'spill':False,'offline_only':True},
        'output_sha256':{p.name:sha(p) for p in sorted(out.iterdir())},
    })


def build(out: Path):
    out = out.resolve()
    out.relative_to((ROOT/'data/processed').resolve())
    if not out.name.startswith('b26_') or out.exists():
        raise ValueError('Use a new Git-ignored data/processed/b26_* directory')
    inputs, paths, commit, metadata = verify_inputs()
    db = connect()
    try:
        for table in GRAPH_TABLES:
            db.execute(f'CREATE VIEW {table} AS SELECT * FROM read_parquet({sp(GRAPH/(table+".parquet"))})')
        joins = load_children(db, ALIASES, paths, commit)
        result = analyze(db)
        result['exact_version_join_audit'] = joins
        result['condition_source'] = {'parts':len(paths),'pinned_all_version_rows':metadata['rows'],
            'observed_all_version_footer_rows':sum(count(db,f'SELECT count(*) FROM read_parquet({sp(p)})') for p in paths),
            'public_date_columns':[], 'provenance':'exact version join to B24; no independent date claimed'}
        expected = {'trials':68623,'arms':121039,'interventions':159113,'assertions':354917,'edges':184256,
                    'aliases':77458,'conditions':108097}
        result['frozen_count_audit'] = {t:{'expected':n,'observed':result['tables'][t],
            'matches':n==result['tables'][t]} for t,n in expected.items()}
        result['preflight_name_audit'] = {'expected_unique':42844,'expected_at_least_two_phases':5702,
            'expected_all_three_phases':1599,'expected_p1_to_p2':14631,'expected_p1_or_p2_to_p3':10300,
            'observed':result['name_counts'], 'observed_coverage':result['coverage'],
            'discrepancy_policy':'audit observations only; never force counts or change policy'}
        write_outputs(db,out,result,inputs)
        return result
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    args = p.parse_args()
    result = build(args.out)
    print(json.dumps({'tables':result['tables'],'coverage':result['coverage']},sort_keys=True))


if __name__ == '__main__':
    main()
