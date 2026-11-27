"""B24 source-only bidirectional audit; names never establish clinical identity.

Only the four pinned files are opened. B15 is projected to metadata before any
join. All protocol children are restricted to exact first-public development keys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from .drug_level_candidates import normalize_drug_name

ROOT = Path(__file__).resolve().parents[2]
B18_MANIFEST = ROOT / 'data/processed/anamnesis_drug_candidates_b18_full_v2_2026-11-25/report.json'
INPUTS = {
    'cohort': ROOT / 'data/processed/anamnesis_rolling_b15_full_v1_2026-11-25/development_rows.parquet',
    **{k: ROOT / 'data/processed/anamnesis_full_b11a_repair2_2026-11-25' / f for k, f in (
        ('links', 'arm_intervention_links.parquet'), ('arms', 'arms_clean.parquet'),
        ('interventions', 'interventions_clean.parquet'))},
}
PINNED = {
    'cohort': '91c5bdc96a9f4fee6d53cd2d884338c614962f1b9ce1a698ad6ba9b883fe2912',
    'links': '33e870871d839cfee01862bc5ed99dc0f9dd2749731e54b2560575b9ccc2f407',
    'arms': '5ce46eb65f232a68301b2c3ddc4fde0690b97b48942be598fa990a431fe94047',
    'interventions': '0d5fbede79a3fdaf74e22a498e533deefb75d1b9769c24c43d76d6a00edb2e3e',
}
BOUNDARY = ('Descriptive source assertions only. Equal names do not verify molecule, dose, '
            'regimen or clinical identity. Union multi-DRUG flags can reflect direction conflict. '
            'No linkage-policy change, outcomes, holdout evaluation or model fit.')


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, default=str) + '\n')


def sqlpath(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def connect():
    db = duckdb.connect()
    db.execute("SET memory_limit='2GiB'")
    db.execute('SET threads=2')
    db.execute('SET preserve_insertion_order=false')
    db.execute("SET temp_directory=''")  # disabled: fail on memory pressure
    db.create_function('b18_key', normalize_drug_name, ['VARCHAR'], 'VARCHAR', null_handling='special')
    db.create_function('fold_name', lambda x: x.casefold().strip() if x is not None else None,
                       ['VARCHAR'], 'VARCHAR', null_handling='special')
    return db


def verify_sources(inputs: dict, expected: dict) -> dict:
    if set(inputs) != set(PINNED) or set(expected) != set(PINNED):
        raise ValueError('Exactly four allowed source files required')
    actual = {k: sha(p) for k, p in inputs.items()}
    if actual != expected:
        raise ValueError('Source SHA-256 mismatch; no source queries executed')
    return actual


def load(db, inputs: dict, limit: int | None = None) -> None:
    if limit is not None and limit < 1:
        raise ValueError('limit must be positive')
    db.execute(f"""CREATE TABLE frame AS SELECT nct_id,
      first_public_nct_version AS nct_version, CAST(first_public_date AS DATE) AS checkpoint_date,
      pure_phase FROM read_parquet({sqlpath(inputs['cohort'])})
      WHERE pure_phase IN ('PHASE1','PHASE2','PHASE3') AND first_public_date < DATE '2020-01-01'
    """)
    if db.execute('SELECT count(*) FROM frame WHERE nct_id IS NULL OR nct_version IS NULL').fetchone()[0]:
        raise ValueError('Missing frame key')
    if db.execute('SELECT count(*) FROM (SELECT nct_id,nct_version FROM frame GROUP BY ALL HAVING count(*)>1)').fetchone()[0]:
        raise ValueError('Duplicate frame key')
    db.execute(f"""CREATE TABLE trials AS SELECT * FROM frame
      ORDER BY sha256('20261127|' || nct_id || '|' || nct_version), nct_id,nct_version
      {f'LIMIT {limit}' if limit else ''}""")
    if not db.execute('SELECT count(*) FROM trials').fetchone()[0]:
        raise ValueError('Empty development cohort')
    for name in ('arms', 'interventions', 'links'):
        db.execute(f"""CREATE TABLE {name} AS SELECT s.* FROM read_parquet({sqlpath(inputs[name])}) s
            JOIN trials t USING(nct_id,nct_version)""")


def rows(db, sql):
    cur = db.execute(sql)
    names = [c[0] for c in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def analyze(db) -> dict:
    """Operate on exact-key source-only tables; invalid assertions stay in audit."""
    for name in ('arms', 'interventions'):
        if db.execute(f'SELECT count(*) FROM (SELECT nct_id,nct_version,ord FROM {name} GROUP BY ALL HAVING count(*)>1)').fetchone()[0]:
            raise ValueError(f'Duplicate {name} ordinal key would multiply assertions')
    db.execute("""CREATE TABLE assertions AS SELECT
      row_number() OVER (ORDER BY l.nct_id,l.nct_version,l.source,l.parent_ord,l.item_ord,
        l.adapter_source_file,l.adapter_loaded_row_index,l.arm_group_ord,l.intervention_ord) AS assertion_id,
      l.*,t.pure_phase,t.checkpoint_date,a AS arm_record,i AS intervention_record,
      a.arm_type, i.intervention_name AS written_name, i.intervention_type AS category,
      a.ord IS NULL AS orphan_arm, i.ord IS NULL AS orphan_intervention,
      l.arm_group_ord IS NULL OR l.intervention_ord IS NULL AS missing_ordinal,
      coalesce(l.adapter_link_status<>'resolved',true) AS unresolved,
      l.is_obsolete IS NULL OR a.is_obsolete IS NULL OR i.is_obsolete IS NULL AS obsolete_unknown,
      coalesce(l.is_obsolete,false) OR coalesce(a.is_obsolete,false) OR coalesce(i.is_obsolete,false)
        OR coalesce(l.adapter_core_is_obsolete,false) OR coalesce(a.adapter_core_is_obsolete,false)
        OR coalesce(i.adapter_core_is_obsolete,false) AS obsolete,
      l.adapter_version_public_date IS NULL OR a.adapter_version_public_date IS NULL
        OR i.adapter_version_public_date IS NULL AS date_unknown,
      coalesce(l.adapter_version_public_date<>t.checkpoint_date,false)
        OR coalesce(a.adapter_version_public_date<>t.checkpoint_date,false)
        OR coalesce(i.adapter_version_public_date<>t.checkpoint_date,false) AS date_violation,
      l.adapter_version_key_resolved IS DISTINCT FROM true
        OR a.adapter_version_key_resolved IS DISTINCT FROM true
        OR i.adapter_version_key_resolved IS DISTINCT FROM true AS version_unresolved
      FROM links l JOIN trials t USING(nct_id,nct_version)
      LEFT JOIN arms a ON a.nct_id=l.nct_id AND a.nct_version=l.nct_version AND a.ord=l.arm_group_ord
      LEFT JOIN interventions i ON i.nct_id=l.nct_id AND i.nct_version=l.nct_version AND i.ord=l.intervention_ord
    """)
    if db.execute("SELECT count(*) FROM assertions WHERE source NOT IN ('intervention','arm_group') OR source IS NULL").fetchone()[0]:
        raise ValueError('Unknown assertion direction')
    db.execute("""CREATE TABLE edges_base AS SELECT nct_id,nct_version,arm_group_ord,intervention_ord,
      any_value(pure_phase) AS pure_phase,any_value(checkpoint_date) AS checkpoint_date,
      any_value(written_name) AS written_name,any_value(category) AS category,any_value(arm_type) AS arm_type,
      list(assertion_id ORDER BY assertion_id) AS assertion_ids,
      count(*) AS assertion_rows, bool_or(source='intervention') AS has_intervention,
      bool_or(source='arm_group') AS has_arm_group,
      bool_or(orphan_arm OR orphan_intervention OR unresolved OR obsolete OR obsolete_unknown
        OR date_unknown OR date_violation OR version_unresolved) AS audit_uncertain,
      bool_or(source='intervention' AND NOT (orphan_arm OR orphan_intervention OR unresolved OR obsolete
        OR obsolete_unknown OR date_unknown OR date_violation OR version_unresolved)) AS valid_intervention,
      bool_or(source='arm_group' AND NOT (orphan_arm OR orphan_intervention OR unresolved OR obsolete
        OR obsolete_unknown OR date_unknown OR date_violation OR version_unresolved)) AS valid_arm_group
      FROM assertions WHERE NOT missing_ordinal GROUP BY 1,2,3,4""")
    db.execute("""CREATE TABLE edges AS SELECT e.*,
      CASE WHEN has_intervention AND has_arm_group THEN 'reciprocal'
           WHEN has_intervention THEN 'intervention_only' ELSE 'arm_group_only' END AS edge_class,
      EXISTS(SELECT 1 FROM edges_base o WHERE o.nct_id=e.nct_id AND o.nct_version=e.nct_version
        AND o.arm_group_ord=e.arm_group_ord AND o.written_name=e.written_name
        AND o.intervention_ord<>e.intervention_ord AND
        ((e.has_intervention AND o.has_arm_group) OR (e.has_arm_group AND o.has_intervention))) AS opposite_exact_name_other_ordinal,
      EXISTS(SELECT 1 FROM edges_base o WHERE o.nct_id=e.nct_id AND o.nct_version=e.nct_version
        AND o.arm_group_ord=e.arm_group_ord AND fold_name(o.written_name)=fold_name(e.written_name)
        AND o.intervention_ord<>e.intervention_ord AND
        ((e.has_intervention AND o.has_arm_group) OR (e.has_arm_group AND o.has_intervention))) AS opposite_folded_name_other_ordinal,
      b18_key(written_name) AS candidate_key
      FROM edges_base e""")
    for label, expr in (('exact', 'written_name'), ('folded', 'fold_name(written_name)')):
        db.execute(f"""CREATE TABLE names_{label} AS SELECT nct_id,nct_version,arm_group_ord,
          any_value(pure_phase) AS pure_phase,{expr} AS name,
          bool_or(has_intervention) AS has_intervention,bool_or(has_arm_group) AS has_arm_group,
          count(DISTINCT intervention_ord) AS intervention_ordinals,
          list(DISTINCT intervention_ord ORDER BY intervention_ord) AS ordinal_list
          FROM edges WHERE written_name IS NOT NULL GROUP BY nct_id,nct_version,arm_group_ord,{expr}""")
    db.execute("""CREATE TABLE policy_rows AS WITH chosen AS (
      SELECT e.*,p.policy FROM edges e CROSS JOIN (VALUES ('intervention'),('union'),('reciprocal')) p(policy)
      WHERE CASE p.policy WHEN 'intervention' THEN valid_intervention
        WHEN 'union' THEN valid_intervention OR valid_arm_group ELSE valid_intervention AND valid_arm_group END
        AND upper(category)='DRUG'
      ), flagged AS (SELECT *,
        count(DISTINCT candidate_key) OVER (PARTITION BY policy,nct_id,nct_version,arm_group_ord) AS candidate_drugs_in_arm,
        count(DISTINCT intervention_ord) OVER (PARTITION BY policy,nct_id,nct_version,arm_group_ord) AS raw_drugs_in_arm,
        max(CASE WHEN arm_type IS NOT NULL AND arm_type<>'EXPERIMENTAL' THEN 1 ELSE 0 END)
          OVER (PARTITION BY policy,nct_id,nct_version,candidate_key) AS shared_with_control
        FROM chosen)
      SELECT *, candidate_key IS NOT NULL AND arm_type='EXPERIMENTAL'
          AND candidate_drugs_in_arm=1 AND shared_with_control=0 AS primary_candidate
      FROM flagged""")
    db.execute("""CREATE TABLE trial_policy AS SELECT t.*,p.policy,
      count(r.intervention_ord) AS raw_drug_rows,
      count(r.intervention_ord) FILTER(WHERE candidate_key IS NOT NULL) AS candidate_rows,
      count(r.intervention_ord) FILTER(WHERE primary_candidate) AS primary_rows,
      count(DISTINCT candidate_key) FILTER(WHERE primary_candidate) AS primary_candidates
      FROM trials t CROSS JOIN (VALUES ('intervention'),('union'),('reciprocal')) p(policy)
      LEFT JOIN policy_rows r ON t.nct_id=r.nct_id AND t.nct_version=r.nct_version AND p.policy=r.policy
      GROUP BY ALL""")
    db.execute("""CREATE TABLE review AS SELECT a.*,e.edge_class,e.has_intervention,e.has_arm_group,
      e.opposite_exact_name_other_ordinal,e.opposite_folded_name_other_ordinal,
      e.audit_uncertain,e.candidate_key,e.assertion_ids,
      NULL::VARCHAR AS human_adjudication,'unknown' AS clinical_identity
      FROM assertions a LEFT JOIN edges e USING(nct_id,nct_version,arm_group_ord,intervention_ord)
      WHERE e.edge_class<>'reciprocal' OR e.audit_uncertain OR a.missing_ordinal
        OR EXISTS(SELECT 1 FROM names_exact n WHERE n.nct_id=a.nct_id AND n.nct_version=a.nct_version
          AND n.arm_group_ord=a.arm_group_ord AND n.name=a.written_name AND n.intervention_ordinals>1)""")
    return {
      'boundary': BOUNDARY,
      'resources': {'memory_limit': '2GiB', 'threads': 2, 'spill': False},
      'tables': {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in
                 ('trials','arms','interventions','assertions','edges','names_exact','names_folded','policy_rows','trial_policy','review')},
      'phase_trials': rows(db, 'SELECT pure_phase,count(*) AS trials FROM trials GROUP BY 1 ORDER BY 1'),
      'linked_versions': db.execute('SELECT count(*) FROM (SELECT DISTINCT nct_id,nct_version FROM assertions)').fetchone()[0],
      'assertion_flags': rows(db, "SELECT pure_phase,source,category,arm_type,count(*) AS assertions," +
          ','.join(f'count(*) FILTER(WHERE {f}) AS {f}' for f in ('missing_ordinal','unresolved','orphan_arm','orphan_intervention','obsolete','obsolete_unknown','date_unknown','date_violation','version_unresolved')) +
          ' FROM assertions GROUP BY 1,2,3,4 ORDER BY 1,2,3,4'),
      'edge_counts': rows(db, 'SELECT pure_phase,edge_class,count(*) AS edges FROM edges GROUP BY 1,2 ORDER BY 1,2'),
      'unilateral_agreement': rows(db, "SELECT opposite_exact_name_other_ordinal,opposite_folded_name_other_ordinal,count(*) AS edges FROM edges WHERE edge_class<>'reciprocal' GROUP BY 1,2 ORDER BY 1,2"),
      'name_groups': {kind: rows(db, f'SELECT pure_phase,has_intervention,has_arm_group,count(*) AS groups,count(*) FILTER(WHERE intervention_ordinals>1) AS multiple_ordinals FROM names_{kind} GROUP BY 1,2,3 ORDER BY 1,2,3') for kind in ('exact','folded')},
      'policy_counts': rows(db, """SELECT policy,pure_phase,count(*) AS raw_drug_rows,count(DISTINCT nct_id) AS raw_drug_trials,
        count(*) FILTER(WHERE candidate_key IS NOT NULL) AS candidate_rows,
        count(DISTINCT nct_id) FILTER(WHERE candidate_key IS NOT NULL) AS candidate_trials,
        count(*) FILTER(WHERE primary_candidate) AS primary_rows,
        count(DISTINCT nct_id) FILTER(WHERE primary_candidate) AS primary_trials,
        count(*) FILTER(WHERE raw_drugs_in_arm>1) AS rows_in_possible_multi_drug_or_conflict_arm,
        count(*) FILTER(WHERE arm_type<>'EXPERIMENTAL') AS nonexperimental_rows,
        count(*) FILTER(WHERE candidate_key IS NOT NULL AND shared_with_control=1) AS shared_control_rows
        FROM policy_rows GROUP BY 1,2 ORDER BY 1,2"""),
      'primary_trial_transitions': rows(db, """SELECT a.policy AS from_policy,b.policy AS to_policy,
        a.pure_phase,(a.primary_rows>0) AS from_eligible,(b.primary_rows>0) AS to_eligible,count(*) AS trials
        FROM trial_policy a JOIN trial_policy b USING(nct_id,nct_version)
        WHERE a.policy<b.policy GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5"""),
      'child_flags': {t: rows(db, f"""SELECT count(*) FILTER(WHERE s.ord IS NULL) AS missing_ordinal,
        count(*) FILTER(WHERE s.is_obsolete) AS obsolete,
        count(*) FILTER(WHERE s.is_obsolete IS NULL) AS obsolete_unknown,
        count(*) FILTER(WHERE s.adapter_version_public_date IS NULL) AS date_unknown,
        count(*) FILTER(WHERE s.adapter_version_public_date<>t.checkpoint_date) AS date_violation,
        count(*) FILTER(WHERE s.adapter_version_key_resolved IS DISTINCT FROM true) AS version_unresolved
        FROM {t} s JOIN trials t USING(nct_id,nct_version)""")[0] for t in ('arms','interventions')},
    }


def build(out: Path, limit: int | None = None) -> dict:
    if out.exists():
        raise FileExistsError(f'Refusing overwrite: {out}')
    pinned_manifest = json.loads(B18_MANIFEST.read_text())
    if {k: pinned_manifest['input_sha256'][k] for k in PINNED} != PINNED:
        raise ValueError('B18 manifest differs from frozen B24 hashes')
    digests = verify_sources(INPUTS, PINNED)  # before DuckDB opens source
    with connect() as db:
        load(db, INPUTS, limit)
        report = analyze(db)
        report['mode'] = 'pilot' if limit else 'full'
        if not limit and report['tables']['trials'] != 68623:
            raise ValueError('Frozen full cohort size mismatch')
        out.mkdir(parents=True)
        artifacts = {}
        # Release filtered source duplicates before sorting wide, provenance-rich
        # outputs. No spill or persistent intermediate database is permitted.
        for staging in ('frame', 'links', 'edges_base'):
            db.execute(f'DROP TABLE {staging}')
        orders = {
            'trials': 'nct_id,nct_version',
            'arms': 'nct_id,nct_version,ord',
            'interventions': 'nct_id,nct_version,ord',
            'assertions': 'assertion_id',
            'edges': 'nct_id,nct_version,arm_group_ord,intervention_ord',
            'names_exact': 'nct_id,nct_version,arm_group_ord,name',
            'names_folded': 'nct_id,nct_version,arm_group_ord,name',
            'policy_rows': 'policy,nct_id,nct_version,arm_group_ord,intervention_ord',
            'trial_policy': 'policy,nct_id,nct_version',
            'review': 'assertion_id',
        }
        for table in report['tables']:
            order = orders[table]
            path = out / f'{table}.parquet'
            db.execute(f'COPY (SELECT * FROM {table} ORDER BY {order}) TO {sqlpath(path)} (FORMAT PARQUET, COMPRESSION ZSTD)')
            artifacts[path.name] = sha(path)
            db.execute(f'DROP TABLE {table}')
        # Small, deterministic review examples; complete review remains in Parquet.
        review = rows(db, f"SELECT * FROM read_parquet({sqlpath(out / 'review.parquet')}) ORDER BY assertion_id LIMIT 100")
        dump(out / 'review_examples.json', review)
        artifacts['review_examples.json'] = sha(out / 'review_examples.json')
        dump(out / 'report.json', report)
        artifacts['report.json'] = sha(out / 'report.json')
        dump(out / 'manifest.json', {'source_sha256': digests,
             'source_paths': {k: str(p.relative_to(ROOT)) for k,p in INPUTS.items()},
             'b18_manifest_sha256': sha(B18_MANIFEST), 'code_sha256': sha(Path(__file__)),
             'b18_normalizer_code_sha256': sha(ROOT / 'src/phase_by_phase/drug_level_candidates.py'),
             'output_sha256': artifacts, 'limit': limit, 'seed': '20261127',
             'boundary': BOUNDARY})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--limit', type=int)
    args = p.parse_args()
    print(json.dumps(build(args.out, args.limit), sort_keys=True, indent=2, default=str))


if __name__ == '__main__':
    main()
