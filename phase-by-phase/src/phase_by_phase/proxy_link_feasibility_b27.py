"""B27 offline feasibility counts, never model features or clinical identity.

Only known-label targets expand into candidate pairs. Labels remain audit-only;
prior primary result values are reduced to nonempty presence after exact-key
semijoins. A whole-record as-of gate prevents persistence of withdrawn results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
B22 = ROOT / 'data/processed/b22_full_2026-11-27_v4'
B26 = ROOT / 'data/processed/b26_full_2026-11-27_v2'
B11 = ROOT / 'data/processed/anamnesis_full_b11b_2026-11-25'
INVENTORY = ROOT / 'data/processed/anamnesis_full_source_manifest_2026-11-25.json'
B18 = ROOT / 'data/processed/anamnesis_drug_candidates_b18_full_v2_2026-11-25/prior_contributions.parquet'
PINS = {
    B22/'manifest.json': '90dbc788896ed5340e3ba7899851ed62feeb1d6b0f27a9f95fc286cc0207235f',
    B26/'manifest.json': '981a3820c29c0af99ee70437ab256c89e0898dc18c1c421773dd1f485956ff97',
    B11/'manifest.json': 'ac4ab7c684bea7867a3814d06dfb031e0ada7883cd18444950e4d09c594e4889',
    INVENTORY: 'a1b318aafc861a6948a53d74fbffabd3694e82aa986d8227ddc14187edea2219',
    B18: '74595949abfdc9fee7862bff249de442e5d3b0984ec08f5d55ae8455ee400ba3',
}
BOUNDARY = ('Feasibility audit only. Same-name candidate registrations are not verified drug, '
            'arm, regimen, indication or program identities. Header/measurement presence is '
            'not a p-value, benefit or efficacy estimate. No model or feature promotion. '
            'B18 is a restricted comparison lower bound; absence there is unknown.')
SETTINGS = {'memory_limit': '2GiB', 'threads': 2, 'spill': False, 'offline': True,
            'strict_prior_date': True, 'high_fanout_threshold': 100}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, default=str)+'\n')


def sp(value):
    return "'"+str(value).replace("'", "''")+"'"


def read(path):
    return f'read_parquet({sp(path)})'


def records(db, sql):
    cur = db.execute(sql)
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def n(db, sql):
    return db.execute(sql).fetchone()[0]


def connect():
    db = duckdb.connect()
    db.execute("SET memory_limit='2GiB'")
    db.execute('SET threads=2')
    db.execute("SET temp_directory=''")
    db.execute('SET preserve_insertion_order=false')
    return db


def version(expr):
    # Never round floats, accept signed/fractional strings, or lose >2**53 keys.
    return f"CASE WHEN regexp_full_match(CAST({expr} AS VARCHAR),'[0-9]+') THEN try_cast({expr} AS BIGINT) END"


def verify_inputs():
    """All authentication completes before any row query, including label rows."""
    used = dict(PINS)
    for path, expected in used.items():
        if sha(path) != expected:
            raise ValueError(f'Pinned SHA-256 mismatch: {path}')
    for directory, key, files in (
        (B22, 'output_sha256', ['all_target_labels.parquet']),
        (B26, 'output_sha256', [x+'.parquet' for x in (
            'trials', 'name_trials', 'name_coverage', 'later_trial_coverage', 'intervention_names')]),
        (B11, 'output_files_sha256', ['results_outcome_measures_clean.parquet',
                                     'results_outcome_measurements_clean.parquet']),
    ):
        m = json.loads((directory/'manifest.json').read_text())
        for filename in files:
            path = directory/filename
            expected = m[key][filename]
            if sha(path) != expected:
                raise ValueError(f'Used child SHA-256 mismatch: {path}')
            used[path] = expected
    source = json.loads(INVENTORY.read_text())
    source_root = Path(source['source_root'])
    source_root.resolve().relative_to((ROOT/'data/raw/anamnesis').resolve())
    parts = source['tables']['core']['files']
    if len(parts) != 9:
        raise ValueError('Expected nine pinned core parts')
    paths = []
    for part in parts:
        relative = Path(part['relative_path'])
        if len(relative.parts) != 2 or relative.parts[0] != 'core' or '..' in relative.parts:
            raise ValueError('Non-core source part refused')
        path = source_root/relative
        if sha(path) != part['sha256']:
            raise ValueError(f'Used core SHA-256 mismatch: {path}')
        used[path] = part['sha256']
        paths.append(path)
    return {str(p.relative_to(ROOT)): h for p, h in sorted(used.items())}, paths, source['source_commit']


def unique(db, table, keys):
    if n(db, f'SELECT count(*) FROM {table} WHERE '+ ' OR '.join(f'{k} IS NULL' for k in keys)):
        raise ValueError(f'Missing key: {table}')
    if n(db, f'SELECT count(*) FROM (SELECT {",".join(keys)} FROM {table} GROUP BY ALL HAVING count(*)>1)'):
        raise ValueError(f'Duplicate key: {table}')


def build_candidates(db):
    """Inputs: labels, trials, name_trials, name_coverage, later_trial_coverage.

    labels is deliberately a narrow projection with explicit audit/label names.
    No label-result version participates in the first-public or prior joins.
    """
    unique(db, 'labels', ['target_nct_id'])
    unique(db, 'trials', ['nct_id'])
    unique(db, 'name_trials', ['candidate_key', 'nct_id'])
    db.execute('''CREATE TABLE targets_base AS SELECT l.*, t.nct_version AS b26_first_public_version,
        t.checkpoint_date AS b26_first_public_date,c.candidate_names,c.names_with_prior_p1,
        c.names_with_prior_p2,c.names_with_any_prior
        FROM labels l LEFT JOIN trials t ON l.target_nct_id=t.nct_id
        AND l.target_first_public_version=t.nct_version AND l.target_checkpoint=t.checkpoint_date
        AND t.pure_phase='PHASE3'
        LEFT JOIN later_trial_coverage c ON t.nct_id=c.nct_id AND t.nct_version=c.nct_version
        AND t.checkpoint_date=c.checkpoint_date''')
    if n(db, '''SELECT count(*) FROM targets_base WHERE b26_first_public_version IS NULL
             OR candidate_names IS NULL OR target_checkpoint IS NULL
             OR target_checkpoint>=DATE '2020-01-01' OR target_checkpoint<DATE '2005-01-01'
             OR (label_proxy_class IS NOT NULL AND label_proxy_class NOT IN (0,1))
             OR label_result_public_date>=DATE '2024-01-01'
             OR label_result_public_date<=target_checkpoint
             OR (label_proxy_class IS NOT NULL AND
                 (label_result_public_date IS NULL OR audit_label_result_version IS NULL))'''):
        raise ValueError('B22/B26 first-public join or development label boundary failed')
    db.execute('''CREATE TABLE known AS SELECT * FROM targets_base WHERE label_proxy_class IN (0,1)''')
    db.execute('''CREATE TABLE name_fanout AS SELECT candidate_key,count(DISTINCT nct_id) AS name_trial_fanout
        FROM name_trials GROUP BY 1''')
    db.execute('''CREATE TABLE candidate_keys AS SELECT k.target_nct_id,k.target_first_public_version,
        k.target_checkpoint,k.label_proxy_class,k.label_result_public_date,
        year(k.target_checkpoint) AS target_year,l.candidate_key,
        p.nct_id AS prior_nct_id,p.nct_version AS prior_first_public_version,
        p.checkpoint_date AS prior_first_public_date,p.pure_phase AS prior_phase,
        l.intervention_ordinals AS target_intervention_ordinals,
        p.intervention_ordinals AS prior_intervention_ordinals,
        l.has_control_role AS target_control_role,p.has_control_role AS prior_control_role,
        l.has_unlinked AS target_unlinked,p.has_unlinked AS prior_unlinked,
        l.has_one_sided AS target_one_sided,p.has_one_sided AS prior_one_sided,
        l.shared_experimental_control AS target_shared_roles,p.shared_experimental_control AS prior_shared_roles,
        l.possible_combination_or_conflict AS target_combination_conflict,
        p.possible_combination_or_conflict AS prior_combination_conflict,
        f.name_trial_fanout,f.name_trial_fanout>=100 AS high_fanout
        FROM known k JOIN name_trials l ON k.target_nct_id=l.nct_id
        AND k.target_first_public_version=l.nct_version AND k.target_checkpoint=l.checkpoint_date
        JOIN name_trials p ON l.candidate_key=p.candidate_key
        AND p.pure_phase IN ('PHASE1','PHASE2') AND p.nct_id<>k.target_nct_id
        AND p.checkpoint_date<k.target_checkpoint
        JOIN name_fanout f ON l.candidate_key=f.candidate_key
        WHERE '''+version('p.nct_version')+''' IS NOT NULL''')
    unique(db, 'candidate_keys', ['target_nct_id','candidate_key','prior_nct_id'])
    # Aggregate source is a cross-check only, never a list of prior candidates.
    if n(db, '''WITH actual AS (SELECT target_nct_id,candidate_key,prior_phase,count(*) AS cnt
        FROM candidate_keys GROUP BY ALL), expected AS (
        SELECT c.nct_id AS target_nct_id,c.candidate_key,c.prior_phase,c.earlier_name_trials AS cnt
        FROM name_coverage c JOIN known k ON c.nct_id=k.target_nct_id
        AND c.nct_version=k.target_first_public_version AND c.checkpoint_date=k.target_checkpoint
        WHERE c.earlier_name_trials>0)
        SELECT count(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected
        UNION ALL (SELECT * FROM expected EXCEPT SELECT * FROM actual))'''):
        raise ValueError('Reconstructed pair counts differ from B26 name coverage')
    db.execute('''CREATE TABLE requests AS SELECT DISTINCT target_nct_id,prior_nct_id,target_checkpoint
        FROM candidate_keys''')
    db.execute('''CREATE TABLE prior_limits AS SELECT prior_nct_id AS nct_id,max(target_checkpoint) AS max_checkpoint
        FROM requests GROUP BY 1''')


def result_audit(db):
    """Inputs core_source, header_source, measurement_source. Only prior P1/P2.

    core_source contains metadata only. Header payload is never projected.
    Measurement value is evaluated only after exact NCT/version/outcome semijoin
    to dated nonobsolete primary headers and whole core records.
    """
    db.execute('''CREATE TABLE core_meta AS SELECT c.*,
        '''+version('c.nct_version')+''' AS exact_version
        FROM core_source c SEMI JOIN prior_limits p ON c.nct_id=p.nct_id''')
    # A missing version is an inspectable unavailable revision, not a usable
    # key. Retain it for the request's unknown gate; duplicate revisions fail.
    if n(db, '''SELECT count(*) FROM (SELECT nct_id,nct_version FROM core_meta
                GROUP BY ALL HAVING count(*)>1)'''):
        raise ValueError('Duplicate key: core_meta')
    db.execute('''CREATE TABLE eligible_versions AS SELECT c.* FROM core_meta c JOIN prior_limits p USING(nct_id)
        WHERE c.exact_version IS NOT NULL AND c.public_date<p.max_checkpoint
        AND c.public_date<DATE '2024-01-01' AND c.is_obsolete=false''')
    # Header metadata only, including key/date diagnostics outside eligible versions.
    db.execute('''CREATE TABLE prior_headers AS SELECT h.nct_id,h.nct_version,h.outcome_ord,h.type,
        h.is_obsolete,h.adapter_version_public_date,h.adapter_core_is_obsolete,
        h.adapter_source_file,h.source_row,h.adapter_source_commit
        FROM header_source h SEMI JOIN prior_limits p ON h.nct_id=p.nct_id''')
    db.execute('''CREATE TABLE primary_headers AS SELECT h.*,c.public_date AS core_public_date,
        h.is_obsolete=false AND h.adapter_core_is_obsolete=false
        AND h.adapter_version_public_date=c.public_date AND h.outcome_ord IS NOT NULL AS valid_header
        FROM prior_headers h JOIN eligible_versions c ON h.nct_id=c.nct_id
        AND h.nct_version=c.exact_version WHERE h.type='PRIMARY' ''')
    db.execute('''CREATE TABLE primary_keys AS SELECT DISTINCT nct_id,nct_version,outcome_ord,core_public_date
        FROM primary_headers WHERE valid_header''')
    # Materialize the allowed child row keys without value, then reduce only
    # those rows to nonempty presence. Source row indexes are exact int64.
    db.execute('''CREATE TABLE allowed_measurement_rows AS SELECT m.nct_id,m.nct_version,
        m.outcome_ord,m.source_row FROM measurement_source m SEMI JOIN primary_keys k
        ON m.nct_id=k.nct_id AND m.nct_version=k.nct_version AND m.outcome_ord=k.outcome_ord''')
    db.execute('''CREATE TABLE measurement_presence AS SELECT m.nct_id,m.nct_version,m.outcome_ord,
        m.class_ord,m.category_ord,m.measurement_ord,m.group_id,m.adapter_version_public_date,
        m.adapter_source_file,m.source_row,m.adapter_source_commit,
        m.is_obsolete=false AND m.adapter_core_is_obsolete=false
        AND m.adapter_version_public_date=k.core_public_date AS valid_measurement,
        nullif(trim(m.value),'') IS NOT NULL AS nonempty_value
        FROM (SELECT m.* FROM measurement_source m SEMI JOIN allowed_measurement_rows a
        ON m.nct_id=a.nct_id AND m.nct_version=a.nct_version
        AND m.outcome_ord=a.outcome_ord AND m.source_row=a.source_row) m
        JOIN primary_keys k ON m.nct_id=k.nct_id
        AND m.nct_version=k.nct_version AND m.outcome_ord=k.outcome_ord''')
    db.execute('''CREATE TABLE version_evidence AS WITH h AS (
        SELECT nct_id,nct_version,count(*) AS primary_rows,
        count(*) FILTER(WHERE valid_header) AS valid_primary_rows,
        count(*) FILTER(WHERE NOT coalesce(valid_header,false)) AS invalid_primary_rows
        FROM primary_headers GROUP BY 1,2), m AS (
        SELECT nct_id,nct_version,count(*) AS measurement_rows,
        count(*) FILTER(WHERE valid_measurement AND nonempty_value) AS valid_nonempty_measurement_rows,
        count(*) FILTER(WHERE NOT coalesce(valid_measurement,false)) AS invalid_measurement_rows
        FROM measurement_presence GROUP BY 1,2)
        SELECT c.*,coalesce(h.primary_rows,0) AS primary_rows,
        coalesce(h.valid_primary_rows,0) AS valid_primary_rows,
        coalesce(h.invalid_primary_rows,0) AS invalid_primary_rows,
        coalesce(m.measurement_rows,0) AS measurement_rows,
        coalesce(m.valid_nonempty_measurement_rows,0) AS valid_nonempty_measurement_rows,
        coalesce(m.invalid_measurement_rows,0) AS invalid_measurement_rows,
        count(*) OVER(PARTITION BY c.nct_id,c.public_date) AS versions_on_public_day
        FROM eligible_versions c LEFT JOIN h ON c.nct_id=h.nct_id AND c.exact_version=h.nct_version
        LEFT JOIN m ON c.nct_id=m.nct_id AND c.exact_version=m.nct_version''')
    db.execute('''CREATE TABLE request_diagnostics AS SELECT r.*,
        count(*) FILTER(WHERE c.public_date IS NULL) AS missing_core_dates,
        count(*) FILTER(WHERE c.exact_version IS NULL) AS malformed_core_versions,
        count(*) FILTER(WHERE c.public_date=r.target_checkpoint) AS tied_core_dates,
        count(*) FILTER(WHERE c.public_date>r.target_checkpoint AND c.public_date<DATE '2024-01-01') AS later_core_dates,
        count(*) FILTER(WHERE c.is_obsolete IS NULL) AS unknown_core_obsolete
        FROM requests r LEFT JOIN core_meta c ON r.prior_nct_id=c.nct_id GROUP BY ALL''')
    db.execute('''CREATE TABLE request_history AS SELECT r.target_nct_id,r.prior_nct_id,
        bool_or(v.valid_primary_rows>0 AND v.versions_on_public_day=1) AS ever_posted_before_checkpoint,
        bool_or(v.valid_nonempty_measurement_rows>0 AND v.versions_on_public_day=1) AS ever_measurement_before_checkpoint,
        count(*) AS earlier_core_versions,
        sum(v.invalid_primary_rows) AS earlier_invalid_primary_rows,
        sum(v.invalid_measurement_rows) AS earlier_invalid_measurement_rows
        FROM requests r JOIN version_evidence v ON r.prior_nct_id=v.nct_id
        AND v.public_date<r.target_checkpoint GROUP BY 1,2''')
    db.execute('''CREATE TABLE request_header_diagnostics AS SELECT r.target_nct_id,r.prior_nct_id,
        count(h.nct_id) AS all_primary_header_rows,
        count(*) FILTER(WHERE h.adapter_version_public_date IS NULL AND h.nct_id IS NOT NULL) AS missing_primary_dates,
        count(*) FILTER(WHERE h.adapter_version_public_date=r.target_checkpoint) AS tied_primary_dates,
        count(*) FILTER(WHERE h.adapter_version_public_date>r.target_checkpoint) AS later_primary_dates,
        count(*) FILTER(WHERE h.adapter_version_public_date<r.target_checkpoint) AS earlier_primary_dates,
        count(*) FILTER(WHERE h.nct_id IS NOT NULL AND c.exact_version IS NULL) AS unmatched_primary_versions,
        count(*) FILTER(WHERE h.adapter_version_public_date<>c.public_date) AS primary_core_date_mismatches
        FROM requests r LEFT JOIN prior_headers h ON r.prior_nct_id=h.nct_id AND h.type='PRIMARY'
        LEFT JOIN core_meta c ON h.nct_id=c.nct_id AND h.nct_version=c.exact_version GROUP BY 1,2''')
    db.execute('''CREATE TABLE asof_selected AS SELECT r.target_nct_id,r.prior_nct_id,v.*
        FROM requests r JOIN version_evidence v ON r.prior_nct_id=v.nct_id
        AND v.public_date<r.target_checkpoint
        QUALIFY row_number() OVER(PARTITION BY r.target_nct_id,r.prior_nct_id
        ORDER BY v.public_date DESC,v.exact_version DESC)=1''')
    db.execute('''CREATE TABLE availability_base AS SELECT r.*,d.* EXCLUDE(target_nct_id,prior_nct_id),
        s.exact_version AS asof_core_version,
        s.public_date AS asof_core_public_date,s.source_file AS asof_core_source_file,
        s.source_row AS asof_core_source_row,s.source_commit AS asof_core_source_commit,
        coalesce(s.versions_on_public_day,0) AS asof_versions_on_day,
        coalesce(s.valid_primary_rows,0) AS asof_exact_primary_rows,
        coalesce(s.valid_nonempty_measurement_rows,0) AS asof_exact_nonempty_measurement_rows,
        coalesce(h.ever_posted_before_checkpoint,false) AS ever_posted_before_checkpoint,
        coalesce(h.ever_measurement_before_checkpoint,false) AS ever_measurement_before_checkpoint,
        coalesce(h.earlier_core_versions,0) AS earlier_core_versions,
        coalesce(h.earlier_invalid_primary_rows,0) AS earlier_invalid_primary_rows,
        coalesce(h.earlier_invalid_measurement_rows,0) AS earlier_invalid_measurement_rows,
        r.missing_core_dates=0 AND r.malformed_core_versions=0 AND r.unknown_core_obsolete=0
        AND coalesce(s.versions_on_public_day,0)=1 AS asof_gate_known
        FROM request_diagnostics r LEFT JOIN asof_selected s USING(target_nct_id,prior_nct_id)
        LEFT JOIN request_history h USING(target_nct_id,prior_nct_id)
        JOIN request_header_diagnostics d USING(target_nct_id,prior_nct_id)''')
    db.execute('''CREATE TABLE availability AS SELECT *,
        asof_gate_known AND asof_exact_primary_rows>0 AS asof_current_primary_header,
        asof_gate_known AND asof_exact_nonempty_measurement_rows>0 AS asof_current_primary_measurement,
        CASE WHEN malformed_core_versions>0 THEN 'unknown_malformed_version'
        WHEN missing_core_dates>0 THEN 'unknown_missing_core_date'
        WHEN unknown_core_obsolete>0 THEN 'unknown_core_obsolete'
        WHEN asof_versions_on_day>1 THEN 'unknown_ambiguous_asof_public_day'
        WHEN asof_core_version IS NULL THEN 'no_strictly_earlier_core'
        WHEN asof_exact_primary_rows=0 AND ever_posted_before_checkpoint THEN 'asof_withdrawn_primary'
        WHEN asof_exact_primary_rows=0 AND earlier_invalid_primary_rows>0 THEN 'no_valid_primary_source_date_or_version'
        WHEN asof_exact_primary_rows=0 THEN 'no_asof_primary'
        WHEN asof_exact_nonempty_measurement_rows=0 THEN 'primary_header_without_measurement'
        ELSE 'asof_primary_with_measurement' END AS availability_status
        FROM availability_base''')
    db.execute('''CREATE TABLE candidate_pairs AS SELECT c.*,a.* EXCLUDE(target_nct_id,prior_nct_id,target_checkpoint)
        FROM candidate_keys c JOIN availability a USING(target_nct_id,prior_nct_id)''')


def comparison(db):
    # A separate output; B18 never filters candidate_keys or availability.
    db.execute('''CREATE TABLE b18_comparison AS SELECT DISTINCT b.target_nct_id,b.candidate_drug_key,
        b.prior_nct_id,b.prior_phase,b.prior_asof_record_version,b.prior_asof_record_date,
        b.prior_result_version,b.prior_result_date,
        b.prior_result_version IS NOT NULL AND b.prior_result_version=b.prior_asof_record_version
        AND b.prior_result_date=b.prior_asof_record_date AND b.prior_result_date<k.target_checkpoint
        AS restricted_b18_dated_asof_result
        FROM b18_source b JOIN known k ON b.target_nct_id=k.target_nct_id
        AND b.target_version=k.target_first_public_version AND b.checkpoint_date=k.target_checkpoint
        WHERE b.prior_phase IN ('PHASE1','PHASE2') AND b.prior_design_date<k.target_checkpoint''')
    db.execute('''CREATE TABLE target_feasibility AS WITH p AS (
        SELECT target_nct_id,count(*) AS candidate_name_prior_pairs,count(DISTINCT prior_nct_id) AS prior_ncts,
        count(DISTINCT candidate_key) AS candidate_prior_names,
        bool_or(prior_phase='PHASE1') AS has_prior_p1,bool_or(prior_phase='PHASE2') AS has_prior_p2,
        bool_or(ever_posted_before_checkpoint) AS has_ever_primary,
        bool_or(ever_measurement_before_checkpoint) AS has_ever_measurement,
        bool_or(asof_current_primary_header) AS has_asof_primary,
        bool_or(asof_current_primary_measurement) AS has_asof_measurement
        FROM candidate_pairs GROUP BY 1), b AS (
        SELECT target_nct_id,true AS b18_restricted_covered,
        bool_or(restricted_b18_dated_asof_result) AS b18_restricted_dated_result FROM b18_comparison GROUP BY 1)
        SELECT t.*,year(t.target_checkpoint) AS target_year,
        coalesce(p.candidate_name_prior_pairs,0) AS candidate_name_prior_pairs,
        coalesce(p.prior_ncts,0) AS prior_ncts,coalesce(p.candidate_prior_names,0) AS candidate_prior_names,
        CASE WHEN t.label_proxy_class IS NULL THEN 'not_expanded_unknown_label' ELSE 'known_label_audited' END AS prior_result_audit_scope,
        CASE WHEN t.label_proxy_class IS NOT NULL THEN coalesce(p.has_prior_p1,false) END AS has_prior_p1,
        CASE WHEN t.label_proxy_class IS NOT NULL THEN coalesce(p.has_prior_p2,false) END AS has_prior_p2,
        CASE WHEN t.label_proxy_class IS NOT NULL THEN coalesce(p.has_ever_primary,false) END AS has_ever_primary,
        CASE WHEN t.label_proxy_class IS NOT NULL THEN coalesce(p.has_ever_measurement,false) END AS has_ever_measurement,
        CASE WHEN t.label_proxy_class IS NOT NULL THEN coalesce(p.has_asof_primary,false) END AS has_asof_primary,
        CASE WHEN t.label_proxy_class IS NOT NULL THEN coalesce(p.has_asof_measurement,false) END AS has_asof_measurement,
        b.b18_restricted_covered,b.b18_restricted_dated_result
        FROM targets_base t LEFT JOIN p USING(target_nct_id) LEFT JOIN b USING(target_nct_id)''')


def grain_counts(db, where='true', group=''):
    prefix = group+',' if group else ''
    return records(db, f'''SELECT {prefix} count(DISTINCT target_nct_id) AS targets,
        count(DISTINCT prior_nct_id) AS prior_ncts,count(DISTINCT candidate_key) AS names,
        count(*) AS name_prior_pairs,
        count(DISTINCT (target_nct_id,prior_nct_id)) AS target_prior_pairs
        FROM candidate_pairs WHERE {where} ''' + (f'GROUP BY {group} ORDER BY {group}' if group else ''))


def make_report(db):
    gates = {}
    for gate in ('true','ever_posted_before_checkpoint','ever_measurement_before_checkpoint',
                 'asof_current_primary_header','asof_current_primary_measurement'):
        gates[gate] = {'total': grain_counts(db, gate),
                      'by_phase_class_year': grain_counts(db, gate, 'prior_phase,label_proxy_class,target_year'),
                      'by_phase': grain_counts(db, gate, 'prior_phase'),
                      'by_class': grain_counts(db, gate, 'label_proxy_class'),
                      'phase_overlap': records(db, f'''WITH t AS (
                          SELECT target_nct_id,bool_or(prior_phase='PHASE1') AS p1,
                          bool_or(prior_phase='PHASE2') AS p2 FROM candidate_pairs WHERE {gate} GROUP BY 1)
                          SELECT count(*) AS union_targets,count(*) FILTER(WHERE p1 AND p2) AS both_phase_targets,
                          count(*) FILTER(WHERE p1 AND NOT p2) AS p1_only_targets,
                          count(*) FILTER(WHERE p2 AND NOT p1) AS p2_only_targets FROM t''')}
    cutoffs = []
    for year in range(2016,2025):
        cutoff = f"DATE '{year}-01-01'"
        cutoffs.append({'exclusive_label_public_cutoff': f'{year}-01-01',
            'all_known_targets': records(db, f'''SELECT label_proxy_class,count(*) AS targets FROM known
                WHERE label_result_public_date<{cutoff} GROUP BY 1 ORDER BY 1'''),
            'candidate_pairs': grain_counts(db, f'label_result_public_date<{cutoff}', 'prior_phase,label_proxy_class'),
            'asof_measurement_pairs': grain_counts(db,
                f'label_result_public_date<{cutoff} AND asof_current_primary_measurement', 'prior_phase,label_proxy_class')})
    return {'boundary': BOUNDARY, 'settings': SETTINGS,
        'target_denominator': n(db,'SELECT count(*) FROM target_feasibility'),
        'target_classes': records(db,'''SELECT label_proxy_class,count(*) AS targets FROM target_feasibility GROUP BY 1 ORDER BY 1 NULLS LAST'''),
        'gates': gates,'target_label_publication_cutoffs':cutoffs,
        'availability': grain_counts(db,'true','availability_status'),
        'pair_ambiguity': records(db,'''SELECT count(*) FILTER(WHERE high_fanout) AS high_fanout,
            count(*) FILTER(WHERE target_control_role OR prior_control_role) AS control_role,
            count(*) FILTER(WHERE target_unlinked OR prior_unlinked) AS unlinked,
            count(*) FILTER(WHERE target_one_sided OR prior_one_sided) AS one_sided,
            count(*) FILTER(WHERE target_shared_roles OR prior_shared_roles) AS shared_roles,
            count(*) FILTER(WHERE target_combination_conflict OR prior_combination_conflict) AS combination_conflict
            FROM candidate_pairs'''),
        'b18_restricted_comparison': records(db,'''SELECT count(DISTINCT target_nct_id) AS targets,
            count(DISTINCT target_nct_id) FILTER(WHERE restricted_b18_dated_asof_result) AS dated_asof_result_targets
            FROM b18_comparison'''),
        'source_diagnostics': records(db,'''SELECT sum(missing_core_dates) AS request_missing_core_dates,
            sum(malformed_core_versions) AS request_malformed_core_versions,
            sum(tied_core_dates) AS request_tied_core_dates,sum(later_core_dates) AS request_later_core_dates,
            sum(earlier_invalid_primary_rows) AS request_invalid_primary_rows,
            sum(earlier_invalid_measurement_rows) AS request_invalid_measurement_rows FROM availability'''),
        'request_primary_date_version_diagnostics': records(db,'''SELECT
            count(*) FILTER(WHERE all_primary_header_rows=0) AS requests_without_any_primary_header,
            count(*) FILTER(WHERE earlier_primary_dates=0) AS requests_without_earlier_primary_header,
            sum(missing_primary_dates) AS missing_primary_dates,sum(tied_primary_dates) AS tied_primary_dates,
            sum(later_primary_dates) AS later_primary_dates,sum(unmatched_primary_versions) AS unmatched_primary_versions,
            sum(primary_core_date_mismatches) AS primary_core_date_mismatches FROM availability'''),
        'prior_child_key_date_diagnostics': records(db,'''SELECT count(*) AS primary_header_rows,
            count(*) FILTER(WHERE c.exact_version IS NULL) AS unmatched_core_version,
            count(*) FILTER(WHERE h.adapter_version_public_date IS NULL) AS missing_child_date,
            count(*) FILTER(WHERE h.adapter_version_public_date<>c.public_date) AS core_child_date_mismatch,
            count(*) FILTER(WHERE h.adapter_version_public_date>=p.max_checkpoint) AS tied_or_later_than_last_checkpoint
            FROM prior_headers h JOIN prior_limits p USING(nct_id)
            LEFT JOIN core_meta c ON h.nct_id=c.nct_id AND h.nct_version=c.exact_version
            WHERE h.type='PRIMARY' ''')}


OUTPUTS = {
    'target_feasibility': 'target_nct_id',
    'candidate_pairs': 'target_nct_id,candidate_key,prior_nct_id',
    'availability': 'target_nct_id,prior_nct_id',
    'core_meta': 'nct_id,nct_version',
    'version_evidence': 'nct_id,exact_version',
    'primary_headers': 'nct_id,nct_version,outcome_ord,source_row',
    'prior_headers': 'nct_id,nct_version,outcome_ord,source_row',
    'measurement_presence': 'nct_id,nct_version,outcome_ord,class_ord,category_ord,measurement_ord,group_id,source_row',
    'b18_comparison': 'target_nct_id,candidate_drug_key,prior_nct_id,prior_phase',
}


def run(out):
    out = Path(out)
    if out.exists():
        raise FileExistsError(f'Refusing to overwrite: {out}')
    inputs, core_paths, commit = verify_inputs()
    db = connect()
    db.execute(f'''CREATE TABLE labels AS SELECT nct_id AS target_nct_id,
        CAST(target_checkpoint AS DATE) AS target_checkpoint,target_first_public_version,
        CAST(proxy_label AS INTEGER) AS label_proxy_class,reason_code AS label_reason_code,
        nct_version AS audit_label_result_version,CAST(result_date AS DATE) AS label_result_public_date
        FROM {read(B22/'all_target_labels.parquet')}''')
    for table in ('trials','name_trials','name_coverage','later_trial_coverage'):
        db.execute(f'CREATE VIEW {table} AS SELECT * FROM {read(B26/(table+".parquet"))}')
    build_candidates(db)
    if n(db,'SELECT count(*) FROM targets_base') != 19576 or n(db,'SELECT count(*) FROM known') != 297:
        raise ValueError('Frozen B22 denominator changed')
    paths = '['+','.join(sp(p) for p in core_paths)+']'
    db.execute(f'''CREATE VIEW core_source AS SELECT nct_id,nct_version,
        CAST(last_update_post_date AS DATE) AS public_date,is_obsolete,
        filename AS source_file,file_row_number AS source_row,{sp(commit)} AS source_commit
        FROM read_parquet({paths},filename=true,file_row_number=true)''')
    db.execute(f'''CREATE VIEW header_source AS SELECT *,file_row_number AS source_row FROM
        read_parquet({sp(B11/'results_outcome_measures_clean.parquet')},file_row_number=true)''')
    db.execute(f'''CREATE VIEW measurement_source AS SELECT *,file_row_number AS source_row FROM
        read_parquet({sp(B11/'results_outcome_measurements_clean.parquet')},file_row_number=true)''')
    result_audit(db)
    db.execute(f'CREATE VIEW b18_source AS SELECT * FROM {read(B18)}')
    comparison(db)
    report = make_report(db)
    out.mkdir(parents=True)
    for table, order in OUTPUTS.items():
        db.execute(f'COPY (SELECT * FROM {table} ORDER BY {order}) TO {sp(out/(table+".parquet"))} (FORMAT PARQUET,COMPRESSION ZSTD)')
    dump(out/'report.json',report)
    dump(out/'examples.json', records(db,'''SELECT * FROM candidate_pairs
        QUALIFY row_number() OVER(PARTITION BY availability_status ORDER BY target_nct_id,candidate_key,prior_nct_id)<=3
        ORDER BY availability_status,target_nct_id,candidate_key,prior_nct_id'''))
    files = sorted(out.iterdir())
    dump(out/'manifest.json',{'boundary':BOUNDARY,'settings':SETTINGS,'input_sha256':inputs,
        'code_sha256':sha(Path(__file__)), 'output_sha256':{p.name:sha(p) for p in files}})
    db.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    args = parser.parse_args()
    report = run(args.out)
    print(json.dumps({'target_denominator':report['target_denominator'],
                      'candidate_counts':report['gates']['true']['total'],
                      'asof_measurement':report['gates']['asof_current_primary_measurement']['total']},sort_keys=True))


if __name__ == '__main__':
    main()
