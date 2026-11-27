"""B30 exact-first-public planned-primary coverage; offline human review package.

No result-child access, semantic matching, label assignment or model. Only the
pinned B29 metadata queue and versioned primary_outcomes are eligible row sources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import duckdb
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / 'data/processed/anamnesis_full_source_manifest_2026-11-25.json'
INVENTORY_SHA = 'a1b318aafc861a6948a53d74fbffabd3694e82aa986d8227ddc14187edea2219'
B29 = ROOT / 'data/processed/b29_full_2026-11-27_v1'
B29_SHA = '1030acd767d2c032b009200f78e29275673c4b45cad6d0e1f12df92856d8dd99'
QUEUE_SHA = '8cc1aa8ffea76b8c5d69d97d5a33b81808d04b20fecbd8c921f99ed3d45527cf'
PLANNED = ('nct_id', 'nct_version', 'ord', 'measure', 'time_frame', 'description',
           'is_obsolete', 'obsolete_by')
QUEUE = ('nct_id', 'target_first_public_version', 'target_checkpoint', 'target_era',
         'inclusion_group', 'selection_stratum', 'selection_order', 'b22_exclusive_reason',
         'selected_result_version', 'selected_result_date', 'outcome_ord', 'analysis_ord',
         'outcome_pointer_status', 'analysis_pointer_status', 'b19_lineage_status')
HUMAN = ('human_later_result_wording', 'human_prespecification_review',
         'human_reviewer', 'human_review_date')
TIMING = 'B29 whole-version association only; child public availability independently unknown'
BOUNDARY = ('Planned-primary coverage of the enriched B29 queue only. No population prevalence, '
            'CI, clinical identity, efficacy, original-prespecification proof or endpoint-switching '
            'claim. Ordinals across versions do not establish semantic identity. Missing stays '
            'unknown. Zero child rows are not_observed, never evidence of no_primary_planned. '
            'Clinical comparison requires separately preregistered human review.')
SETTINGS = {'memory_limit': '2GiB', 'threads': 2, 'temp_directory': '',
            'max_temp_directory_size': '0B', 'preserve_insertion_order': True}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sp(value):
    return "'" + str(value).replace("'", "''") + "'"


def dump(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, default=str) + '\n')


def records(db, sql):
    cur = db.execute(sql)
    return [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]


def n(db, sql):
    return db.execute(sql).fetchone()[0]


def verify_inputs():
    """All byte authentication finishes before connection/schema/row queries."""
    authenticated = {}

    def check(path, expected):
        if sha(path) != expected:
            raise ValueError(f'SHA-256 mismatch: {path}')
        authenticated[str(path)] = expected

    check(INVENTORY, INVENTORY_SHA)
    check(B29 / 'manifest.json', B29_SHA)
    manifest = json.loads((B29 / 'manifest.json').read_text())
    if manifest['output_sha256']['review_queue.parquet'] != QUEUE_SHA:
        raise ValueError('B29 queue declared digest contradiction')
    check(B29 / 'review_queue.parquet', QUEUE_SHA)
    source = json.loads(INVENTORY.read_text())
    table = source['tables']['primary_outcomes']
    if table['columns'] != list(PLANNED) or table['rows'] != 7967548:
        raise ValueError('Planned-primary inventory schema/count contradiction')
    expected_names = {f'primary_outcomes/part-{i:05d}-of-00016.parquet' for i in range(16)}
    if (len(table['files']) != 16
            or {f['relative_path'] for f in table['files']} != expected_names):
        raise ValueError('Expected exactly 16 pinned primary-outcome parts')
    parts = []
    for item in sorted(table['files'], key=lambda f: f['relative_path']):
        path = Path(source['source_root']) / item['relative_path']
        path.resolve().relative_to((ROOT / 'data/raw/anamnesis').resolve())
        check(path, item['sha256'])
        parts.append(path)
    # Footer-only checks cannot materialize planned or result text.
    total = 0
    for path, item in zip(parts, sorted(table['files'], key=lambda f: f['relative_path'])):
        footer = pq.ParquetFile(path)
        schema = footer.schema_arrow
        if (schema.names != list(PLANNED)
                or hashlib.sha256(schema.serialize().to_pybytes()).hexdigest() != table['schema_sha256']
                or footer.metadata.num_rows != item['rows'] or path.stat().st_size != item['bytes']):
            raise ValueError(f'Planned-primary source schema/footer contradiction: {path}')
        total += footer.metadata.num_rows
    if total != table['rows']:
        raise ValueError('Planned-primary footer total contradiction')
    return authenticated, parts, source


def connect():
    return duckdb.connect(config=SETTINGS)


def load_queue(db, path, expected_count=343):
    db.execute(f'CREATE TABLE queue AS SELECT {",".join(QUEUE)} FROM read_parquet({sp(path)})')
    if (n(db, 'SELECT count(*) FROM queue') != expected_count
            or n(db, 'SELECT count(DISTINCT nct_id) FROM queue') != expected_count):
        raise ValueError('Missing/duplicate B29 NCT or frozen queue count contradiction')
    if n(db, """SELECT count(*) FROM queue WHERE nct_id IS NULL
        OR target_first_public_version IS NULL OR target_first_public_version<0
        OR target_checkpoint IS NULL OR target_checkpoint<DATE '2005-01-01'
        OR target_checkpoint>=DATE '2020-01-01'
        OR target_era IS DISTINCT FROM CASE WHEN year(target_checkpoint)<2010 THEN '2005-09'
            WHEN year(target_checkpoint)<2015 THEN '2010-14' ELSE '2015-19' END
        OR inclusion_group IS NULL OR inclusion_group NOT IN ('uniform','rare_reason','known_anchor')
        OR selection_stratum IS NULL OR b22_exclusive_reason IS NULL
        OR ((selected_result_version IS NULL)!=(selected_result_date IS NULL))
        OR (selected_result_date IS NOT NULL AND (selected_result_date<=target_checkpoint
            OR selected_result_date>=DATE '2024-01-01'))
        OR (outcome_ord IS NOT NULL AND selected_result_version IS NULL)
        OR (analysis_ord IS NOT NULL AND outcome_ord IS NULL)"""):
        raise ValueError('B29 source key/timing/metadata contradiction')
    # Result pointers stay in queue; the raw-text join uses only these keys.
    db.execute('''CREATE TABLE keys AS SELECT nct_id,
        target_first_public_version AS nct_version FROM queue''')


def load_planned(db, parts, source):
    paths = '[' + ','.join(sp(p) for p in parts) + ']'
    # Explicit source projection. No result sources and no full-source text table.
    db.execute(f'''CREATE VIEW planned_source AS SELECT {','.join(PLANNED)},
        filename,file_row_number FROM read_parquet({paths},filename=true,file_row_number=true)''')
    # Key-only NCT-level audit distinguishes exact misses from NCTs never observed.
    # It never projects text from a nonmatching version into a materialized table.
    db.execute('''CREATE TABLE key_coverage AS SELECT s.nct_id,
        count(*) AS source_nct_rows,
        count(*) FILTER(WHERE s.nct_version IS NULL) AS source_null_version_rows,
        count(*) FILTER(WHERE s.nct_version=k.nct_version) AS exact_key_rows,
        count(*) FILTER(WHERE s.nct_version!=k.nct_version) AS other_version_rows
        FROM planned_source s JOIN keys k ON s.nct_id=k.nct_id GROUP BY s.nct_id''')
    db.execute(f'''CREATE TABLE source_parts(source_file VARCHAR,source_part_sha256 VARCHAR)''')
    hashes = {f['relative_path']: f['sha256'] for f in source['tables']['primary_outcomes']['files']}
    db.executemany('INSERT INTO source_parts VALUES (?,?)',
                   [(str(p), hashes[p.relative_to(Path(source['source_root'])).as_posix()]) for p in parts])
    projected = ','.join('s.' + c for c in PLANNED)
    db.execute(f'''CREATE TABLE exact_planned AS SELECT {projected},
        s.filename AS source_file,s.file_row_number AS source_file_row,
        p.source_part_sha256,{sp(INVENTORY_SHA)} AS source_inventory_sha256,
        {sp(source['source_commit'])} AS source_commit,'primary_outcomes' AS source_table,
        {sp(source['dataset'])} AS source_dataset,{sp(source['license'])} AS source_license,
        {sp(B29_SHA)} AS b29_manifest_sha256,{sp(QUEUE_SHA)} AS b29_queue_sha256
        FROM (SELECT {projected},s.filename,s.file_row_number FROM planned_source s
            SEMI JOIN keys k ON s.nct_id=k.nct_id AND s.nct_version=k.nct_version) s
        JOIN source_parts p ON s.filename=p.source_file''')


def build(db):
    blank = ','.join(f'CAST(NULL AS VARCHAR) AS {field}' for field in HUMAN)
    # Preserve each physical row, including exact duplicates; never deduplicate.
    db.execute(f'''CREATE TABLE planned_primary_rows AS
        WITH counted AS (SELECT e.*,count(*) OVER(PARTITION BY nct_id,nct_version,ord)
            AS ordinal_source_row_count FROM exact_planned e)
        SELECT e.*,q.target_checkpoint AS whole_version_association_date,
        {sp(TIMING)} AS timing_provenance,
        CASE WHEN ord IS NULL THEN 'unknown_null_ordinal'
            WHEN ordinal_source_row_count>1 THEN 'ambiguous_duplicate_ordinal'
            ELSE 'unique_source_ordinal' END AS ordinal_state,
        CASE WHEN is_obsolete IS NULL THEN 'unknown_obsolete_flag'
            WHEN is_obsolete THEN 'obsolete'
            WHEN obsolete_by IS NOT NULL THEN 'unknown_flag_pointer_conflict'
            ELSE 'nonobsolete_source_flag' END AS obsolete_state,
        {blank} FROM counted e JOIN queue q ON e.nct_id=q.nct_id''')
    db.execute(f'''CREATE TABLE trial_summary AS WITH aggregate_rows AS (
        SELECT nct_id,count(*) AS planned_source_rows,
        count(DISTINCT ord) AS distinct_nonnull_ordinals,
        count(*) FILTER(WHERE ord IS NULL) AS null_ordinal_rows,
        count(*) FILTER(WHERE ordinal_state='ambiguous_duplicate_ordinal') AS duplicate_ordinal_rows,
        count(*) FILTER(WHERE obsolete_state='obsolete') AS obsolete_rows,
        count(*) FILTER(WHERE obsolete_state LIKE 'unknown%') AS unknown_obsolete_rows,
        count(*) FILTER(WHERE obsolete_state='nonobsolete_source_flag') AS nonobsolete_flag_rows,
        count(*) FILTER(WHERE measure IS NULL) AS missing_measure_rows,
        count(*) FILTER(WHERE time_frame IS NULL) AS missing_time_frame_rows,
        count(*) FILTER(WHERE description IS NULL) AS missing_description_rows
        FROM planned_primary_rows GROUP BY nct_id)
        SELECT q.*,
        CASE WHEN coalesce(a.planned_source_rows,0)>0 THEN 'observed'
            ELSE 'not_observed' END AS planned_presence_state,
        CASE WHEN coalesce(a.planned_source_rows,0)>0 THEN 'exact_nct_version_observed'
            WHEN k.nct_id IS NULL THEN 'unknown_source_nct_not_observed'
            ELSE 'unknown_exact_version_not_observed' END AS source_key_state,
        coalesce(k.source_nct_rows,0) AS source_nct_rows,
        coalesce(k.source_null_version_rows,0) AS source_null_version_rows,
        coalesce(k.other_version_rows,0) AS other_version_rows,
        {','.join(f'coalesce(a.{c},0) AS {c}' for c in (
            'planned_source_rows','distinct_nonnull_ordinals','null_ordinal_rows',
            'duplicate_ordinal_rows','obsolete_rows','unknown_obsolete_rows','nonobsolete_flag_rows',
            'missing_measure_rows','missing_time_frame_rows','missing_description_rows'))},
        {sp(INVENTORY_SHA)} AS source_inventory_sha256,{sp(B29_SHA)} AS b29_manifest_sha256,
        {sp(QUEUE_SHA)} AS b29_queue_sha256,{sp(TIMING)} AS timing_provenance,
        'unknown_not_independently_dated' AS child_public_availability_state,
        'unknown_not_assessed' AS no_primary_planned_state,{blank}
        FROM queue q LEFT JOIN aggregate_rows a USING(nct_id) LEFT JOIN key_coverage k USING(nct_id)''')


def summarize(db):
    return {
        'boundary': BOUNDARY, 'timing_provenance': TIMING,
        'trial_count': n(db, 'SELECT count(*) FROM trial_summary'),
        'planned_row_count': n(db, 'SELECT count(*) FROM planned_primary_rows'),
        'presence_states': records(db, '''SELECT planned_presence_state,count(*) AS trials
            FROM trial_summary GROUP BY 1 ORDER BY 1'''),
        'no_primary_planned': {'trials_established': 0,
            'interpretation': 'Not identifiable from child-table absence; all trials unknown_not_assessed.'},
        'by_selection_era': records(db, '''SELECT inclusion_group,selection_stratum,b22_exclusive_reason,
            target_era,planned_presence_state,source_key_state,count(*) AS trials,
            sum(planned_source_rows) AS planned_source_rows,
            sum(null_ordinal_rows) AS null_ordinal_rows,sum(duplicate_ordinal_rows) AS duplicate_ordinal_rows,
            sum(obsolete_rows) AS obsolete_rows,sum(unknown_obsolete_rows) AS unknown_obsolete_rows
            FROM trial_summary GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4,5,6'''),
        'row_states': records(db, '''SELECT ordinal_state,obsolete_state,count(*) AS source_rows
            FROM planned_primary_rows GROUP BY 1,2 ORDER BY 1,2'''),
        'settings': SETTINGS, 'source_projection': list(PLANNED), 'queue_projection': list(QUEUE),
        'software': {'duckdb': duckdb.__version__},
    }


def prepare_output(out):
    out = Path(out).resolve()
    if out.parent != (ROOT / 'data/processed').resolve() or not out.name.startswith('b30_'):
        raise ValueError('Output must be a new data/processed/b30_* directory')
    if out.exists():
        raise FileExistsError(f'Refusing existing output: {out}')
    if subprocess.run(['git', 'check-ignore', '-q', str(out / 'manifest.json')], cwd=ROOT).returncode:
        raise ValueError('Output must be Git-ignored')
    return out


def run(out):
    out = prepare_output(out)
    authenticated, parts, source = verify_inputs()
    with connect() as db:
        load_queue(db, B29 / 'review_queue.parquet')
        load_planned(db, parts, source)
        build(db)
        report = summarize(db)
        out.mkdir()
        for table, order in (('trial_summary', 'nct_id'),
                             ('planned_primary_rows', 'nct_id,nct_version,ord NULLS FIRST,source_file,source_file_row')):
            for suffix, options in (('parquet', 'FORMAT PARQUET, COMPRESSION ZSTD'),
                                    ('csv', 'FORMAT CSV, HEADER true')):
                db.execute(f'COPY (SELECT * FROM {table} ORDER BY {order}) '
                           f'TO {sp(out / (table + "." + suffix))} ({options})')
        dump(out / 'report.json', report)
        dump(out / 'manifest.json', {
            'input_sha256': {str(Path(p).relative_to(ROOT)): h for p, h in authenticated.items()},
            'code_sha256': sha(Path(__file__)), 'settings': SETTINGS,
            'source_commit': source['source_commit'], 'source_dataset': source['dataset'],
            'output_sha256': {p.name: sha(p) for p in sorted(out.iterdir())},
        })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    report = run(parser.parse_args().out)
    print(json.dumps({k: report[k] for k in ('trial_count', 'planned_row_count')}, sort_keys=True))


if __name__ == '__main__':
    main()
