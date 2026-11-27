"""B31: offline, proxy-class/significance-blinded manual endpoint review package."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import subprocess

import duckdb
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
B30 = ROOT / 'data/processed/b30_full_2026-11-27_v1'
B17 = ROOT / 'data/processed/anamnesis_grade_b17_full_v3_2026-11-25'
B29 = ROOT / 'data/processed/b29_full_2026-11-27_v1'
HEADER = 'results_outcome_measures_clean.parquet'
B30_SHA = 'bc78b2f363f599988f9b37f96d75273873bee458b170b764bf9903934a7ab358'
B17_SHA = '778d4a5f97d4afa868747d8d44269ff3bde203faeb08b5b0442d84d872a0cdd2'
B29_SHA = '1030acd767d2c032b009200f78e29275673c4b45cad6d0e1f12df92856d8dd99'
QUEUE_SHA = '8cc1aa8ffea76b8c5d69d97d5a33b81808d04b20fecbd8c921f99ed3d45527cf'
SUMMARY_SHA = '2cd4b1da9233365a494c3b4a7395b04a71732229feae2ae9d5139147745170e0'
PLANNED_SHA = '3eb6c7b71cd7d4c69353d7f7399e55467a36f556db0d1926a3e0adf026e30683'
HEADER_SHA = 'fdc66c89dee518f6a78ac18b8c731fa30c3949772fd05409cd8a2b10ebfd2517'
SETTINGS = {'memory_limit': '2GiB', 'threads': 2, 'temp_directory': '',
            'max_temp_directory_size': '0B', 'preserve_insertion_order': True}
CASE = ('nct_id', 'target_first_public_version', 'target_checkpoint', 'target_era',
        'inclusion_group', 'selection_stratum', 'selection_order', 'b22_exclusive_reason',
        'selected_result_version', 'selected_result_date', 'outcome_ord',
        'outcome_pointer_status', 'planned_presence_state', 'source_key_state',
        'planned_source_rows', 'timing_provenance')
PLANNED = ('nct_id', 'nct_version', 'ord', 'measure', 'time_frame', 'description',
           'is_obsolete', 'obsolete_by', 'source_file', 'source_file_row',
           'source_part_sha256', 'source_inventory_sha256', 'source_commit', 'source_table',
           'source_dataset', 'source_license', 'b29_manifest_sha256', 'b29_queue_sha256',
           'ordinal_source_row_count', 'whole_version_association_date',
           'timing_provenance', 'ordinal_state', 'obsolete_state')
HEADERS = ('nct_id', 'nct_version', 'outcome_ord', 'type', 'title', 'description',
           'time_frame', 'is_obsolete', 'obsolete_by', 'adapter_source_file',
           'adapter_version_public_date', 'adapter_core_is_obsolete',
           'adapter_source_commit', 'adapter_source_table')
HUMAN = ('human_planned_reported_correspondence', 'human_prespecification_assessment',
         'human_notes', 'human_reviewer', 'human_review_date')
MASK_PATTERN = r'(?i)\bNCT[ -]?[0-9]{8}\b'
MASK_TEXT = '[registry identifier masked]'
NOTICE = ('Proxy-class/significance blinding only. Study prose may reidentify a case, and '
          'reported-header presence is visible. Explicit registry identifiers are masked in reviewer '
          'text; exact source wording remains audit-only. Planned and reported lists are independent: '
          'equal ordinals or wording do not establish identity, and differences do not establish '
          'endpoint switching. Missing stays unknown. Whole-version registration dates do not '
          'independently date child fields or prove original prespecification. Two independent '
          'human reviewers and a separately prespecified reconciliation rubric are required '
          'for clinical annotation. No clinical labels, efficacy, recoverability, population '
          'prevalence, or model-readiness conclusions are produced.')
REVIEW_SCHEMA = {
    'cases': ('case_id', 'reviewer_order_hash', 'planned_availability', 'reported_availability') + HUMAN,
    'planned': ('case_id', 'review_row_id', 'measure', 'description', 'time_frame') + HUMAN,
    'reported': ('case_id', 'review_row_id', 'title', 'description', 'time_frame') + HUMAN,
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sp(value):
    return "'" + str(value).replace("'", "''") + "'"


def dump(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, default=str) + '\n')


def n(db, sql):
    return db.execute(sql).fetchone()[0]


def records(db, sql):
    cur = db.execute(sql)
    return [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]


def connect():
    return duckdb.connect(config=SETTINGS)


def verify_inputs():
    """Authenticate all manifests and used children before connection or row queries."""
    pins = {B30/'manifest.json': B30_SHA, B17/'manifest.json': B17_SHA,
            B29/'manifest.json': B29_SHA, B29/'review_queue.parquet': QUEUE_SHA,
            B30/'trial_summary.parquet': SUMMARY_SHA,
            B30/'planned_primary_rows.parquet': PLANNED_SHA, B17/HEADER: HEADER_SHA}
    for path, expected in pins.items():
        if sha(path) != expected:
            raise ValueError(f'SHA-256 mismatch: {path}')
    m30 = json.loads((B30/'manifest.json').read_text())
    m17 = json.loads((B17/'manifest.json').read_text())
    m29 = json.loads((B29/'manifest.json').read_text())
    if (m30['output_sha256']['trial_summary.parquet'] != SUMMARY_SHA
            or m30['output_sha256']['planned_primary_rows.parquet'] != PLANNED_SHA
            or m17['output_sha256'][HEADER] != HEADER_SHA
            or m29['output_sha256']['review_queue.parquet'] != QUEUE_SHA
            or m30['input_sha256'][str((B29/'manifest.json').relative_to(ROOT))] != B29_SHA
            or m30['input_sha256'][str((B29/'review_queue.parquet').relative_to(ROOT))] != QUEUE_SHA):
        raise ValueError('Manifest lineage contradiction')
    for path, columns, rows in ((B30/'trial_summary.parquet', CASE, 343),
                                (B30/'planned_primary_rows.parquet', PLANNED, 452),
                                (B17/HEADER, HEADERS, 90204)):
        footer = pq.ParquetFile(path)
        if not set(columns) <= set(footer.schema_arrow.names) or footer.metadata.num_rows != rows:
            raise ValueError(f'Schema/footer contradiction: {path}')
    return pins


def load_cases(db, path, expected=(343, 269, 52)):
    db.execute(f'CREATE TABLE cases_input AS SELECT {",".join(CASE)} FROM read_parquet({sp(path)})')
    if (n(db, 'SELECT count(*) FROM cases_input') != expected[0]
            or n(db, 'SELECT count(DISTINCT nct_id) FROM cases_input') != expected[0]
            or n(db, 'SELECT count(*) FROM cases_input WHERE selected_result_version IS NOT NULL') != expected[1]
            or n(db, 'SELECT count(*) FROM cases_input WHERE selected_result_version IS NOT NULL AND outcome_ord IS NULL') != expected[2]):
        raise ValueError('Frozen case/pointer counts contradiction')
    if n(db, """SELECT count(*) FROM cases_input WHERE nct_id IS NULL
        OR target_first_public_version IS NULL OR target_first_public_version<0
        OR target_checkpoint IS NULL OR target_checkpoint<DATE '2005-01-01'
        OR target_checkpoint>=DATE '2020-01-01'
        OR ((selected_result_version IS NULL)!=(selected_result_date IS NULL))
        OR selected_result_version<0
        OR selected_result_date<=target_checkpoint OR selected_result_date>=DATE '2024-01-01'
        OR (outcome_ord IS NOT NULL AND selected_result_version IS NULL)"""):
        raise ValueError('Case key/date contradiction')
    # Only case identity determines ID/order, never reason, pointer, stratum or proxy.
    db.execute("""CREATE TABLE case_keys AS SELECT *,
        'C-'||substr(sha256('B31-case-v1:'||nct_id),1,24) AS case_id,
        sha256('B31-review-order-v1:'||nct_id) AS reviewer_order_hash FROM cases_input""")
    if n(db, 'SELECT count(DISTINCT case_id) FROM case_keys') != expected[0]:
        raise ValueError('Opaque case ID collision')
    db.execute('''CREATE TABLE result_keys AS SELECT nct_id,
        selected_result_version AS nct_version,selected_result_date,target_checkpoint
        FROM case_keys WHERE selected_result_version IS NOT NULL''')


def load_headers(db, path):
    # Key/date-only validation precedes any text-bearing materialization. No alternate version.
    db.execute(f'''CREATE TABLE header_key_audit AS SELECT s.nct_id,s.nct_version,
        count(*) AS selected_header_rows,
        count(*) FILTER(WHERE s.type='PRIMARY') AS primary_header_rows,
        count(*) FILTER(WHERE s.type IS NULL) AS unknown_type_rows,
        count(*) FILTER(WHERE s.adapter_version_public_date IS DISTINCT FROM k.selected_result_date
            OR s.adapter_version_public_date<=k.target_checkpoint
            OR s.adapter_version_public_date>=DATE '2024-01-01') AS invalid_date_rows
        FROM read_parquet({sp(path)}) s JOIN result_keys k
        ON s.nct_id=k.nct_id AND s.nct_version=k.nct_version GROUP BY 1,2''')
    if n(db, 'SELECT coalesce(sum(invalid_date_rows),0) FROM header_key_audit'):
        raise ValueError('Header exact-public-date contradiction; no text materialized')
    projected = ','.join('s.'+c for c in HEADERS)
    db.execute(f'''CREATE TABLE exact_primary_headers AS SELECT {projected},
        s.file_row_number AS source_file_row,{sp(path)} AS source_file,
        {sp(HEADER_SHA)} AS source_file_sha256,{sp(B17_SHA)} AS b17_manifest_sha256
        FROM read_parquet({sp(path)},file_row_number=true) s
        SEMI JOIN result_keys k ON s.nct_id=k.nct_id AND s.nct_version=k.nct_version
            AND s.adapter_version_public_date=k.selected_result_date
            AND s.adapter_version_public_date>k.target_checkpoint
            AND s.adapter_version_public_date<DATE '2024-01-01'
        WHERE s.type='PRIMARY' ''')


def reviewer_text(columns):
    # Literal registry-ID suppression for blinding, without interpreting endpoint language.
    return ','.join(f'regexp_replace({c},{sp(MASK_PATTERN)},{sp(MASK_TEXT)},\'g\') AS {c}'
                    for c in columns)


def build(db, planned_path, expected_planned=452):
    blank = ','.join(f'CAST(NULL AS VARCHAR) AS {c}' for c in HUMAN)
    db.execute(f'CREATE TABLE planned_input AS SELECT {",".join(PLANNED)} FROM read_parquet({sp(planned_path)})')
    if (n(db, 'SELECT count(*) FROM planned_input') != expected_planned
            or n(db, '''SELECT count(*) FROM planned_input p LEFT JOIN case_keys c USING(nct_id)
                WHERE c.nct_id IS NULL OR p.nct_version IS DISTINCT FROM c.target_first_public_version
                OR p.whole_version_association_date IS DISTINCT FROM c.target_checkpoint''')
            or n(db, '''SELECT count(*) FROM case_keys c WHERE c.planned_source_rows !=
                (SELECT count(*) FROM planned_input p WHERE p.nct_id=c.nct_id)''')):
        raise ValueError('Planned exact-key/count contradiction')
    db.execute('''CREATE TABLE audit_planned AS SELECT c.case_id,
        'P-'||substr(sha256(c.case_id||':'||p.source_file||':'||p.source_file_row::VARCHAR),1,24)
            AS review_row_id,p.* FROM planned_input p JOIN case_keys c USING(nct_id)''')
    db.execute('''CREATE TABLE audit_reported AS WITH counted AS (
        SELECT *,count(*) OVER(PARTITION BY nct_id,nct_version,outcome_ord) AS ordinal_source_row_count
        FROM exact_primary_headers)
        SELECT c.case_id,'R-'||substr(sha256(c.case_id||':'||s.source_file_row::VARCHAR),1,24)
            AS review_row_id,s.*,
        CASE WHEN s.outcome_ord IS NULL THEN 'unknown_null_ordinal'
            WHEN ordinal_source_row_count>1 THEN 'ambiguous_duplicate_ordinal'
            ELSE 'unique_source_ordinal' END AS ordinal_state,
        CASE WHEN is_obsolete IS TRUE OR adapter_core_is_obsolete IS TRUE THEN 'obsolete'
            WHEN is_obsolete IS NULL OR adapter_core_is_obsolete IS NULL THEN 'unknown_obsolete_flag'
            WHEN obsolete_by IS NOT NULL THEN 'unknown_flag_pointer_conflict'
            ELSE 'nonobsolete_source_flag' END AS obsolete_state
        FROM counted s JOIN case_keys c USING(nct_id)''')
    db.execute('''CREATE TABLE audit_cases AS WITH counts AS (
        SELECT case_id,count(*) AS primary_rows,
        count(*) FILTER(WHERE obsolete_state='nonobsolete_source_flag') AS eligible_reported_rows,
        count(*) FILTER(WHERE obsolete_state='obsolete') AS obsolete_rows,
        count(*) FILTER(WHERE obsolete_state LIKE 'unknown%') AS unknown_obsolete_rows,
        count(*) FILTER(WHERE outcome_ord IS NULL) AS null_ordinal_rows,
        count(*) FILTER(WHERE ordinal_state='ambiguous_duplicate_ordinal') AS duplicate_ordinal_rows
        FROM audit_reported GROUP BY 1)
        SELECT c.*,coalesce(h.selected_header_rows,0) AS selected_header_rows,
        coalesce(h.unknown_type_rows,0) AS unknown_type_rows,
        coalesce(a.primary_rows,0) AS primary_rows,
        coalesce(a.eligible_reported_rows,0) AS eligible_reported_rows,
        coalesce(a.obsolete_rows,0) AS obsolete_rows,
        coalesce(a.unknown_obsolete_rows,0) AS unknown_obsolete_rows,
        coalesce(a.null_ordinal_rows,0) AS null_ordinal_rows,
        coalesce(a.duplicate_ordinal_rows,0) AS duplicate_ordinal_rows,
        CASE WHEN selected_result_version IS NULL THEN 'unknown_no_selected_result'
            WHEN h.nct_id IS NULL THEN 'unknown_missing_exact_header'
            WHEN coalesce(a.primary_rows,0)=0 THEN 'unknown_missing_primary_header'
            WHEN coalesce(a.eligible_reported_rows,0)=0 THEN 'unknown_no_eligible_primary_header'
            ELSE 'observed_nonobsolete_primary_header' END AS reported_availability
        FROM case_keys c LEFT JOIN header_key_audit h
            ON c.nct_id=h.nct_id AND c.selected_result_version=h.nct_version
        LEFT JOIN counts a USING(case_id)''')
    db.execute(f'''CREATE TABLE review_cases AS SELECT case_id,reviewer_order_hash,
        CASE WHEN planned_source_rows=0 THEN 'unknown_not_observed' ELSE 'observed' END
            AS planned_availability,reported_availability,{blank} FROM audit_cases''')
    db.execute(f'''CREATE TABLE review_planned AS SELECT case_id,review_row_id,
        {reviewer_text(('measure', 'description', 'time_frame'))},{blank} FROM audit_planned''')
    db.execute(f'''CREATE TABLE review_reported AS SELECT case_id,review_row_id,
        {reviewer_text(('title', 'description', 'time_frame'))},{blank} FROM audit_reported
        WHERE obsolete_state='nonobsolete_source_flag' ''')
    for name, schema in REVIEW_SCHEMA.items():
        actual = tuple(r[0] for r in db.execute(f'DESCRIBE review_{name}').fetchall())
        if actual != schema:
            raise ValueError('Reviewer allowlist contradiction')


def summarize(db):
    return {'boundary': NOTICE, 'settings': SETTINGS,
            'case_count': n(db, 'SELECT count(*) FROM audit_cases'),
            'planned_row_count': n(db, 'SELECT count(*) FROM audit_planned'),
            'reported_primary_row_count': n(db, 'SELECT count(*) FROM audit_reported'),
            'reviewer_reported_row_count': n(db, 'SELECT count(*) FROM review_reported'),
            'result_without_outcome_pointer_cases': n(db, '''SELECT count(*) FROM audit_cases
                WHERE selected_result_version IS NOT NULL AND outcome_ord IS NULL'''),
            'by_audit_strata': records(db, '''SELECT inclusion_group,selection_stratum,
                b22_exclusive_reason,target_era,reported_availability,count(*) AS cases,
                sum(planned_source_rows) AS planned_rows,sum(primary_rows) AS primary_rows,
                sum(eligible_reported_rows) AS eligible_reported_rows,
                sum(obsolete_rows) AS obsolete_rows,sum(unknown_obsolete_rows) AS unknown_obsolete_rows,
                sum(null_ordinal_rows) AS null_ordinal_rows,sum(duplicate_ordinal_rows) AS duplicate_ordinal_rows
                FROM audit_cases GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5'''),
            'reported_row_states': records(db, '''SELECT ordinal_state,obsolete_state,count(*) AS rows
                FROM audit_reported GROUP BY 1,2 ORDER BY 1,2'''),
            'availability': records(db, '''SELECT reported_availability,count(*) AS cases
                FROM audit_cases GROUP BY 1 ORDER BY 1'''),
            'projections': {'cases': CASE, 'planned': PLANNED, 'headers': HEADERS},
            'review_schema': REVIEW_SCHEMA, 'software': {'duckdb': duckdb.__version__}}


def casebook(db):
    """Only reviewer allowlist tables are available to this renderer."""
    esc = lambda value: html.escape(str(value)) if value is not None else '[unknown]'
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Endpoint review casebook</title>',
             '<style>body{font:16px sans-serif;max-width:1000px;margin:2em auto;padding:1em} '
             'article{break-before:page;border-top:2px solid #333;margin-top:3em} '
             'li{white-space:pre-wrap;margin:1em 0} textarea{display:block;width:95%;height:5em} '
             'label{display:block;margin:1em 0}</style><h1>Endpoint review casebook</h1>',
             '<p>'+esc(NOTICE)+'</p><p>Blank fields are for future manual review. '
             'This static casebook does not save entries; use the accompanying blank CSV files '
             'or print to retain review notes.</p>']
    for case in records(db, 'SELECT * FROM review_cases ORDER BY reviewer_order_hash,case_id'):
        parts.append('<article><h2>'+esc(case['case_id'])+'</h2>')
        for kind in ('planned', 'reported'):
            parts.append('<h3>'+kind.title()+' headers</h3><p>'+esc(case[kind+'_availability'])+'</p><ul>')
            for row in records(db, f'SELECT * FROM review_{kind} WHERE case_id={sp(case["case_id"])} ORDER BY review_row_id'):
                parts.append('<li><strong>'+esc(row['review_row_id'])+'</strong><br>'+esc(row.get('measure', row.get('title')))
                             +'<br>Description: '+esc(row['description'])+'<br>Time frame: '+esc(row['time_frame'])+'</li>')
            parts.append('</ul>')
        for field in HUMAN:
            parts.append('<label>'+esc(field.removeprefix('human_').replace('_', ' '))+'<textarea aria-label="'
                         +esc(field)+'"></textarea></label>')
        parts.append('</article>')
    return '\n'.join(parts)+'</html>\n'


def prepare_output(out):
    out = Path(out).resolve()
    if out.parent != (ROOT/'data/processed').resolve() or not out.name.startswith('b31_'):
        raise ValueError('Output must be a fresh data/processed/b31_* directory')
    if out.exists():
        raise FileExistsError(f'Refusing existing output: {out}')
    if subprocess.run(['git', 'check-ignore', '-q', str(out/'manifest.json')], cwd=ROOT).returncode:
        raise ValueError('Output must be Git-ignored')
    return out


def run(out):
    out = prepare_output(out)
    authenticated = verify_inputs()
    with connect() as db:
        load_cases(db, B30/'trial_summary.parquet')
        load_headers(db, B17/HEADER)
        build(db, B30/'planned_primary_rows.parquet')
        report = summarize(db)
        out.mkdir()
        (out/'reviewer').mkdir()
        (out/'audit_only').mkdir()
        for prefix, folder in (('review', 'reviewer'), ('audit', 'audit_only')):
            for kind in ('cases', 'planned', 'reported'):
                order = 'case_id' if kind == 'cases' else 'case_id,review_row_id'
                for ext, opts in (('parquet', 'FORMAT PARQUET, COMPRESSION ZSTD'),
                                  ('csv', 'FORMAT CSV, HEADER true')):
                    db.execute(f'COPY (SELECT * FROM {prefix}_{kind} ORDER BY {order}) '
                               f'TO {sp(out/folder/(kind+"."+ext))} ({opts})')
        (out/'reviewer/casebook.html').write_text(casebook(db))
        dump(out/'audit_only/report.json', report)
        dump(out/'manifest.json', {
            'input_sha256': {str(p.relative_to(ROOT)): h for p,h in authenticated.items()},
            'code_sha256': sha(__file__), 'settings': SETTINGS,
            'output_sha256': {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    report = run(parser.parse_args().out)
    print(json.dumps({k: report[k] for k in ('case_count', 'planned_row_count',
                                          'reported_primary_row_count', 'reviewer_reported_row_count')}, sort_keys=True))


if __name__ == '__main__':
    main()
