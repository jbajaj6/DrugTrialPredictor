"""B29 metadata-only human review preparation; no new labels or value reads.

Only the two explicit SQL projections below may read source rows. Authentication
precedes the DuckDB connection. B19 summaries describe selected result versions,
not original prespecification or verified clinical identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import duckdb

ROOT = Path(__file__).resolve().parents[2]
B22 = ROOT / 'data/processed/b22_full_2026-11-27_v4'
B19 = ROOT / 'data/processed/b19_full_2026-11-27_v1'
PINS = {
    B22: '90dbc788896ed5340e3ba7899851ed62feeb1d6b0f27a9f95fc286cc0207235f',
    B19: '44303770c8b9db387bb008d215f44bd1a70ef1025d611fe5a5ae01cbf5a37107',
}
USED = {B22: 'all_target_labels.parquet', B19: 'trial_evidence.parquet'}
SEED = 20261127
KNOWN = 'determinate_reported_superiority_p'
REASONS = {
    'no_posted_primary_result': 11162, 'primary_missing_or_multiple': 2408,
    'analysis_missing_or_multiple': 3550, 'not_explicit_superiority': 1200,
    'noninferiority_comment_requires_review': 542, 'arm_mapping_unverified': 301,
    'comparator_role_unverified': 98, 'analysis_contrast_unverified': 9,
    'p_missing': 9, KNOWN: 297,
}
RARE = tuple(sorted(set(REASONS) - {'no_posted_primary_result', KNOWN}))
B22_COLUMNS = (
    'nct_id', 'target_checkpoint', 'target_first_public_version', 'reason_code',
    'nct_version', 'result_date', 'outcome_ord', 'analysis_ord',
    'arm_mapping_state', 'comparator_role_state', 'analysis_type_enum',
    'tested_flag_state', 'overlapping_uncertainty_states', 'adapter_source_file',
    'adapter_source_commit', 'adapter_source_table', 'adapter_version_public_date',
)
B19_STATES = (
    'primary_outcome_count', 'primary_source_row_count', 'missing_primary_key_rows',
    'primary_count_state', 'mapping_states', 'contrast_states',
    'comparator_role_states', 'noninferiority_states', 'equivalence_states',
    'tested_non_inferiority_states', 'analysis_type_enum_states',
    'analysis_type_consistency_states', 'analysis_count', 'direction_state',
)
B19_COLUMNS = ('nct_id', 'nct_version', 'result_date') + B19_STATES
ADJUDICATION = (
    'human_prespecification', 'human_multiplicity', 'human_comparator_arm_map',
    'human_effect_direction', 'human_ni_eq', 'human_clinical_relevance',
    'human_reviewer', 'human_adjudication_date',
)
BOUNDARY = (
    'Metadata-only preparatory queue, not clinical annotation, expanded labels, '
    'benefit, recoverability or model evidence. Historical PRIMARY does not prove '
    'original prespecification. Exact label maps do not verify clinical identity. '
    'NI/EQ is a different estimand. No minimum-p selection. Missing remains unknown. '
    'Only the uniform component has a probability-sample interpretation; enriched '
    'and anchor cases cannot estimate prevalence. Actual human review requires a '
    'separately frozen protocol and exact source versions/original endpoints.'
)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, sort_keys=True, indent=2) + '\n')


def sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def verify_inputs(pins=None, used=None):
    pins = PINS if pins is None else pins
    used = USED if used is None else used
    authenticated = {}
    # Authenticate every manifest before trusting any declared child digest.
    for directory, expected in pins.items():
        path = directory / 'manifest.json'
        if sha(path) != expected:
            raise ValueError(f'Pinned manifest SHA-256 mismatch: {path}')
        authenticated[str(path)] = expected
    for directory, name in used.items():
        manifest = json.loads((directory / 'manifest.json').read_text())
        expected = manifest['output_sha256'][name]
        path = directory / name
        if sha(path) != expected:
            raise ValueError(f'Used Parquet SHA-256 mismatch: {path}')
        authenticated[str(path)] = expected
    if pins == PINS:
        b22 = json.loads((B22 / 'manifest.json').read_text())
        if (b22['input_sha256']['b19_manifest'] != PINS[B19]
                or b22['input_sha256']['b19_trial'] != authenticated[str(B19 / USED[B19])]):
            raise ValueError('B22/B19 declared lineage mismatch')
    return authenticated


def connect():
    return duckdb.connect(config={
        'memory_limit': '2GiB', 'threads': 2, 'temp_directory': '',
        'max_temp_directory_size': '0B', 'preserve_insertion_order': True,
    })


def n(db, query):
    return db.execute(query).fetchone()[0]


def records(db, query):
    cursor = db.execute(query)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def load(db, b22_path, b19_path):
    # Projection occurs INSIDE DuckDB. Never read either complete file into Arrow,
    # pandas, Python records, or a SELECT * source view.
    for table, path, columns in (
        ('targets', b22_path, B22_COLUMNS), ('b19', b19_path, B19_COLUMNS),
    ):
        db.execute(f'CREATE TABLE {table} AS SELECT {",".join(columns)} '
                   f'FROM read_parquet({sql_string(path)})')


def unique(db, table):
    if n(db, f'SELECT count(*) FROM {table} WHERE nct_id IS NULL'):
        raise ValueError(f'Missing NCT: {table}')
    if n(db, f'SELECT count(*) FROM (SELECT nct_id FROM {table} GROUP BY 1 HAVING count(*)>1)'):
        raise ValueError(f'Duplicate NCT: {table}')


def validate(db, expected_counts=None):
    for table in ('targets', 'b19'):
        unique(db, table)
    if n(db, """SELECT count(*) FROM targets WHERE target_first_public_version IS NULL
        OR target_checkpoint IS NULL OR target_checkpoint < DATE '2005-01-01'
        OR target_checkpoint >= DATE '2020-01-01'
        OR (result_date IS NOT NULL AND (result_date <= target_checkpoint
            OR result_date >= DATE '2024-01-01'))
        OR ((nct_version IS NULL) != (result_date IS NULL))
        OR (analysis_ord IS NOT NULL AND outcome_ord IS NULL)"""):
        raise ValueError('Invalid target/result dates or pointer separation')
    if n(db, """SELECT count(*) FROM b19 WHERE nct_version IS NULL OR result_date IS NULL
        OR result_date >= DATE '2024-01-01'"""):
        raise ValueError('Missing/holdout B19 version/date')
    observed = dict(db.execute('SELECT reason_code,count(*) FROM targets GROUP BY 1').fetchall())
    if not set(observed).issubset(REASONS):
        raise ValueError('Unknown/null exclusive reason')
    if expected_counts is not None and observed != expected_counts:
        raise ValueError(f'Frozen reason/denominator mismatch: {observed}')


def build_ledger(db):
    exact = '(t.nct_version=b.nct_version AND t.result_date=b.result_date)'
    states = ','.join(f'CASE WHEN {exact} THEN b.{col} END AS b19_{col}' for col in B19_STATES)
    single = f'({exact} AND b.primary_count_state=\'single\' AND b.primary_outcome_count=1 '
    single += 'AND b.primary_source_row_count=1 AND b.missing_primary_key_rows=0)'
    db.execute(f'''CREATE TABLE ledger AS SELECT
        t.nct_id,t.target_first_public_version,t.target_checkpoint,
        t.nct_version AS selected_result_version,t.result_date AS selected_result_date,
        t.reason_code AS b22_exclusive_reason,t.overlapping_uncertainty_states,
        t.arm_mapping_state AS b22_arm_mapping_state,
        t.comparator_role_state AS b22_comparator_role_state,
        t.analysis_type_enum AS b22_analysis_type_enum,t.tested_flag_state AS b22_tested_flag_state,
        t.adapter_source_file,t.adapter_source_commit,t.adapter_source_table,t.adapter_version_public_date,
        CASE WHEN t.nct_version IS NULL THEN 'unknown_no_b22_result_pointer'
            WHEN b.nct_id IS NULL THEN 'unknown_missing_b19'
            WHEN {exact} THEN 'exact_nct_version_date'
            ELSE 'unknown_b19_version_or_date_mismatch' END AS b19_lineage_status,
        CASE WHEN {exact} THEN b.nct_version END AS b19_selected_result_version,
        CASE WHEN {exact} THEN b.result_date END AS b19_selected_result_date,
        {states},
        CASE WHEN {single} AND t.outcome_ord IS NOT NULL THEN t.outcome_ord END AS outcome_ord,
        CASE WHEN {single} AND b.analysis_count=1 AND t.analysis_ord IS NOT NULL
            THEN t.analysis_ord END AS analysis_ord,
        CASE WHEN {single} AND t.outcome_ord IS NOT NULL THEN 'exact_b22_pointer'
            ELSE 'unknown_missing_ambiguous_or_unlinked' END AS outcome_pointer_status,
        CASE WHEN {single} AND b.analysis_count=1 AND t.analysis_ord IS NOT NULL
            THEN 'exact_b22_pointer' ELSE 'unknown_missing_ambiguous_or_unlinked' END AS analysis_pointer_status,
        CASE WHEN year(t.target_checkpoint)<2010 THEN '2005-09'
            WHEN year(t.target_checkpoint)<2015 THEN '2010-14' ELSE '2015-19' END AS target_era,
        sha256('{SEED}|' || t.nct_id) AS selection_sha256
        FROM targets t LEFT JOIN b19 b ON t.nct_id=b.nct_id''')


def sample(db):
    db.execute('''CREATE TABLE selections(nct_id VARCHAR, inclusion_group VARCHAR,
        selection_stratum VARCHAR, selection_order BIGINT, inclusion_logic VARCHAR,
        probability_sample BOOLEAN, uniform_draw_probability DOUBLE)''')
    db.execute('''INSERT INTO selections SELECT nct_id,'uniform','all_targets',
        row_number() OVER (ORDER BY selection_sha256,nct_id),
        'first 150 SHA256(20261127|NCT), ties NCT',true,
        least(150,count(*) OVER ())::DOUBLE / count(*) OVER ()
        FROM ledger ORDER BY selection_sha256,nct_id LIMIT 150''')
    for reason in (*RARE, KNOWN):
        group = 'known_anchor' if reason == KNOWN else 'rare_reason'
        # Round-robin = within-era SHA rank first, chronological era second;
        # exhausted eras simply have no next row. No cross-stratum top-up.
        db.execute(f'''INSERT INTO selections
            WITH eligible AS (SELECT l.*,row_number() OVER (
                PARTITION BY target_era ORDER BY selection_sha256,nct_id) AS era_rank
                FROM ledger l ANTI JOIN selections s USING(nct_id)
                WHERE b22_exclusive_reason={sql_string(reason)})
            SELECT nct_id,{sql_string(group)},{sql_string(reason)},
                row_number() OVER (ORDER BY era_rank,target_era,selection_sha256,nct_id),
                'exclude uniform; era round-robin by SHA256(20261127|NCT), ties NCT; at most 25',
                false,NULL FROM eligible
                ORDER BY era_rank,target_era,selection_sha256,nct_id LIMIT 25''')
    blank = ','.join(f'CAST(NULL AS VARCHAR) AS {col}' for col in ADJUDICATION)
    db.execute(f'''CREATE TABLE metadata_ledger AS SELECT l.*,
        coalesce(s.inclusion_group,'not_selected') AS inclusion_group,s.selection_stratum,
        s.selection_order,s.inclusion_logic,coalesce(s.probability_sample,false) AS probability_sample,
        s.uniform_draw_probability,{blank}
        FROM ledger l LEFT JOIN selections s USING(nct_id) ORDER BY l.nct_id''')
    db.execute('''CREATE TABLE review_queue AS SELECT * FROM metadata_ledger
        WHERE inclusion_group!='not_selected' ORDER BY inclusion_group,selection_stratum,selection_order,nct_id''')
    unique(db, 'review_queue')


def summarize(db):
    sampling = []
    for reason in ('all_targets', *RARE, KNOWN):
        group = 'uniform' if reason == 'all_targets' else 'known_anchor' if reason == KNOWN else 'rare_reason'
        requested = 150 if group == 'uniform' else 25
        clause = '' if group == 'uniform' else ' WHERE b22_exclusive_reason=' + sql_string(reason)
        total = n(db, 'SELECT count(*) FROM ledger' + clause)
        selected = n(db, 'SELECT count(*) FROM selections WHERE selection_stratum=' + sql_string(reason))
        excluded = 0 if group == 'uniform' else n(db, f'''SELECT count(*) FROM ledger l
            JOIN selections s USING(nct_id) WHERE s.inclusion_group='uniform'
            AND l.b22_exclusive_reason={sql_string(reason)}''')
        sampling.append(dict(inclusion_group=group, selection_stratum=reason, population=total,
                             excluded_uniform=excluded, available_after_uniform=total-excluded,
                             requested=requested, selected=selected, shortfall=requested-selected))
    return {
        'boundary': BOUNDARY, 'target_count': n(db, 'SELECT count(*) FROM metadata_ledger'),
        'queue_count': n(db, 'SELECT count(*) FROM review_queue'), 'sampling': sampling,
        'exclusive_reasons': records(db, '''SELECT b22_exclusive_reason,count(*) AS targets
            FROM metadata_ledger GROUP BY 1 ORDER BY 1'''),
        'lineage': records(db, '''SELECT b19_lineage_status,count(*) AS targets
            FROM metadata_ledger GROUP BY 1 ORDER BY 1'''),
        'pointer_states': records(db, '''SELECT outcome_pointer_status,analysis_pointer_status,count(*) AS targets
            FROM metadata_ledger GROUP BY 1,2 ORDER BY 1,2'''),
        'queue_eras': records(db, '''SELECT inclusion_group,selection_stratum,target_era,count(*) AS targets
            FROM review_queue GROUP BY 1,2,3 ORDER BY 1,2,3'''),
        'queue_schema': [dict(name=r[0], type=r[1]) for r in db.execute('DESCRIBE review_queue').fetchall()],
        'source_projection': {'B22': list(B22_COLUMNS), 'B19': list(B19_COLUMNS)},
        'source_grain': 'B19 trial summary only; endpoint/analysis counts overlap and are not additive.',
        'settings': {'seed': SEED, 'memory_limit': '2GiB', 'threads': 2,
                     'temp_directory': '', 'max_temp_directory_size': '0B'},
    }


def prepare_output(out):
    out = Path(out).resolve()
    if out.parent != (ROOT / 'data/processed').resolve() or not out.name.startswith('b29_'):
        raise ValueError('Output must be a new data/processed/b29_* directory')
    if out.exists():
        raise FileExistsError(f'Refusing existing output: {out}')
    ignored = subprocess.run(['git', 'check-ignore', '-q', str(out / 'manifest.json')], cwd=ROOT)
    if ignored.returncode != 0:
        raise ValueError('Output must be Git-ignored')
    return out


def run(out):
    out = prepare_output(out)
    authenticated = verify_inputs()  # Must finish before any source row query.
    with connect() as db:
        load(db, B22 / USED[B22], B19 / USED[B19])
        validate(db, REASONS)
        build_ledger(db)
        sample(db)
        report = summarize(db)
        out.mkdir()
        for table in ('metadata_ledger', 'review_queue'):
            order = 'nct_id' if table == 'metadata_ledger' else 'inclusion_group,selection_stratum,selection_order,nct_id'
            db.execute(f'COPY (SELECT * FROM {table} ORDER BY {order}) '
                       f'TO {sql_string(out / (table + ".parquet"))} (FORMAT PARQUET, COMPRESSION ZSTD)')
        db.execute(f'''COPY (SELECT * EXCLUDE(overlapping_uncertainty_states),
            to_json(overlapping_uncertainty_states) AS overlapping_uncertainty_states
            FROM review_queue ORDER BY inclusion_group,selection_stratum,selection_order,nct_id)
            TO {sql_string(out / 'review_queue.csv')} (FORMAT CSV, HEADER true)''')
        dump(out / 'report.json', report)
        manifest = {
            'input_sha256': {str(Path(path).relative_to(ROOT)): value for path, value in authenticated.items()},
            'code_sha256': sha(Path(__file__)), 'settings': report['settings'],
            'output_sha256': {p.name: sha(p) for p in sorted(out.iterdir())},
        }
        dump(out / 'manifest.json', manifest)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.out)
    print(json.dumps({'targets': report['target_count'], 'queue': report['queue_count']}, sort_keys=True))


if __name__ == '__main__':
    main()
