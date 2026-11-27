"""B28 exact-ordinal descriptive audit; no outcome values or identity inference.

The CLI authenticates every used input before opening DuckDB. Only the accepted
B27R presence flag selects pairs. Proxy classes are isolated from tier assignment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
B27R = ROOT / 'data/processed/b27r_clean_2026-11-27_v1'
B26 = ROOT / 'data/processed/b26_full_2026-11-27_v2'
B24 = ROOT / 'data/processed/b24_full_2026-11-27_v2'
PINS = {
    B27R: 'cfb0c06e1f90da5adce0351d95674ce0720b1d70758ef89e9b2530b20e80d68b',
    B26: '981a3820c29c0af99ee70437ab256c89e0898dc18c1c421773dd1f485956ff97',
    B24: 'f193bf4d65424b415552ac644be20b8591495537ae85923ca2248aaab66318c0',
}
USED = {B27R: ('candidate_pairs',), B26: ('trials', 'intervention_names', 'conditions'),
        B24: ('arms', 'edges', 'assertions')}
TIERS = {1: 'reciprocal_single_drug_experimental_both',
         2: 'explicit_control_or_combination', 3: 'reciprocal_ambiguous',
         4: 'one_sided', 5: 'unlinked_unknown'}
BOUNDARY = ('Descriptive feasibility only. Same normalized strings and reciprocal edges do not '
            'verify molecule, regimen, indication, benefit or sponsor program. Prior measurement '
            'presence is not an interpretable effect. No target result values, holdout, chemical '
            'data, NLP, model or feature promotion. Conditions and fanout are sensitivities only.')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, sort_keys=True, indent=2, default=str) + '\n')


def sp(path):
    return "'" + str(path).replace("'", "''") + "'"


def verify_inputs():
    used = {}
    # Authenticate all manifests before trusting any file digest within them.
    for directory, expected in PINS.items():
        path = directory / 'manifest.json'
        if sha(path) != expected:
            raise ValueError(f'Pinned manifest SHA-256 mismatch: {path}')
        used[str(path.relative_to(ROOT))] = expected
    for directory, tables in USED.items():
        manifest = json.loads((directory / 'manifest.json').read_text())
        for table in tables:
            path = directory / (table + '.parquet')
            expected = manifest['output_sha256'][path.name]
            if sha(path) != expected:
                raise ValueError(f'Used child SHA-256 mismatch: {path}')
            used[str(path.relative_to(ROOT))] = expected
    return dict(sorted(used.items()))


def connect():
    db = duckdb.connect()
    db.execute("SET memory_limit='2GiB'")
    db.execute('SET threads=2')
    db.execute('SET preserve_insertion_order=false')
    db.execute("SET temp_directory=''")
    return db


def records(db, query):
    c = db.execute(query)
    return [dict(zip([x[0] for x in c.description], row)) for row in c.fetchall()]


def n(db, query):
    return db.execute(query).fetchone()[0]


def unique(db, table, keys):
    key = ','.join(keys)
    if n(db, f'SELECT count(*) FROM {table} WHERE ' + ' OR '.join(k+' IS NULL' for k in keys)):
        raise ValueError(f'Missing natural key: {table}')
    if n(db, f'SELECT count(*) FROM (SELECT {key} FROM {table} GROUP BY ALL HAVING count(*)>1)'):
        raise ValueError(f'Duplicate natural key: {table}')


def load(db):
    # No target labels, outcome text, measurement values or name-level OR flags.
    db.execute(f'''CREATE TABLE selected AS SELECT target_nct_id,target_first_public_version,
        target_checkpoint,prior_nct_id,prior_first_public_version,prior_first_public_date,
        prior_phase,candidate_key,target_intervention_ordinals,prior_intervention_ordinals,
        name_trial_fanout,asof_current_primary_measurement
        FROM read_parquet({sp(B27R/'candidate_pairs.parquet')})
        WHERE asof_current_primary_measurement IS TRUE''')
    db.execute(f'''CREATE TABLE proxy_classes AS SELECT DISTINCT target_nct_id,label_proxy_class
        FROM read_parquet({sp(B27R/'candidate_pairs.parquet')})
        WHERE asof_current_primary_measurement IS TRUE''')
    prepare_requests(db)
    # Candidate trial/version semijoin precedes child value materialization. All
    # ordinals in those versions are needed to count the actual arm's regimen.
    for table, path in (('trials', B26/'trials.parquet'),
                        ('interventions', B26/'intervention_names.parquet'),
                        ('conditions', B26/'conditions.parquet'),
                        ('arms', B24/'arms.parquet'), ('edges', B24/'edges.parquet')):
        db.execute(f'''CREATE TABLE {table} AS SELECT s.* FROM read_parquet({sp(path)}) s
            SEMI JOIN requests r USING(nct_id,nct_version)''')
    db.execute(f'''CREATE TABLE source_assertions AS SELECT s.*
        FROM read_parquet({sp(B24/'assertions.parquet')}) s
        SEMI JOIN requests r USING(nct_id,nct_version)''')


def prepare_requests(db):
    unique(db, 'selected', ['target_nct_id', 'candidate_key', 'prior_nct_id'])
    unique(db, 'proxy_classes', ['target_nct_id'])
    if n(db, '''SELECT count(*) FROM selected WHERE target_checkpoint IS NULL
        OR prior_first_public_date IS NULL OR prior_first_public_date>=target_checkpoint
        OR target_checkpoint>=DATE '2020-01-01' OR target_nct_id=prior_nct_id
        OR prior_phase NOT IN ('PHASE1','PHASE2') OR prior_phase IS NULL
        OR asof_current_primary_measurement IS DISTINCT FROM true
        OR target_first_public_version IS NULL OR prior_first_public_version IS NULL'''):
        raise ValueError('Invalid selected pair dates/version/phase/presence')
    db.execute('''CREATE TABLE pairs AS SELECT row_number() OVER (ORDER BY target_nct_id,
        candidate_key,prior_nct_id) AS pair_id,* FROM selected''')
    db.execute('''CREATE TABLE requests AS SELECT target_nct_id AS nct_id,
        target_first_public_version AS nct_version,target_checkpoint AS checkpoint_date,
        'PHASE3' AS pure_phase FROM pairs UNION SELECT prior_nct_id,
        prior_first_public_version,prior_first_public_date,prior_phase FROM pairs''')
    unique(db, 'requests', ['nct_id'])
    db.execute('''CREATE TABLE ordinal_requests AS
        SELECT DISTINCT target_nct_id AS nct_id,target_first_public_version AS nct_version,
            candidate_key,unnest(target_intervention_ordinals) AS intervention_ord FROM pairs
        UNION SELECT prior_nct_id,prior_first_public_version,candidate_key,
            unnest(prior_intervention_ordinals) FROM pairs''')
    unique(db, 'ordinal_requests', ['nct_id','nct_version','candidate_key','intervention_ord'])


def validate(db):
    for table, keys in (
        ('trials', ['nct_id']), ('interventions', ['nct_id','nct_version','ord']),
        ('arms', ['nct_id','nct_version','ord']),
        ('edges', ['nct_id','nct_version','intervention_ord','arm_group_ord']),
        ('conditions', ['nct_id','nct_version','ord'])):
        unique(db, table, keys)
    if n(db, '''SELECT count(*) FROM requests r LEFT JOIN trials t USING(nct_id,nct_version)
        WHERE t.nct_id IS NULL OR t.checkpoint_date IS DISTINCT FROM r.checkpoint_date
        OR t.pure_phase IS DISTINCT FROM r.pure_phase'''):
        raise ValueError('First-public frame date/version/phase mismatch')
    for table in ('interventions', 'arms'):
        if n(db, f'''SELECT count(*) FROM {table} s JOIN requests r USING(nct_id,nct_version)
            WHERE s.adapter_version_public_date IS DISTINCT FROM r.checkpoint_date'''):
            raise ValueError(f'Missing/mismatched first-public child date: {table}')
    if n(db, '''SELECT count(*) FROM edges e JOIN requests r USING(nct_id,nct_version)
        WHERE e.checkpoint_date IS DISTINCT FROM r.checkpoint_date'''):
        raise ValueError('Edge checkpoint mismatch')
    # A label is never joined into exposure construction; only report strata.
    if n(db, 'SELECT count(*) FROM proxy_classes WHERE label_proxy_class IS NULL OR label_proxy_class NOT IN (0,1)'):
        raise ValueError('Unexpected proxy class in measurement-present denominator')


def build(db):
    """Build only from first-public exact keys; missing edges remain null paths."""
    validate(db)
    db.execute('''CREATE TABLE arm_regimens AS SELECT e.nct_id,e.nct_version,e.arm_group_ord,
        count(DISTINCT i.ord) FILTER(WHERE upper(i.intervention_type)='DRUG') AS drug_ordinals,
        count(DISTINCT i.candidate_key) FILTER(WHERE upper(i.intervention_type)='DRUG') AS candidate_drugs,
        count(*) FILTER(WHERE i.ord IS NULL) AS missing_interventions,
        count(*) FILTER(WHERE e.audit_uncertain IS DISTINCT FROM false) AS uncertain_regimen_edges,
        count(*) FILTER(WHERE upper(i.intervention_type)<>'DRUG' OR i.intervention_type IS NULL) AS nondrug_edges,
        list(DISTINCT e.intervention_ord ORDER BY e.intervention_ord) AS all_intervention_ordinals,
        list(DISTINCT i.candidate_key ORDER BY i.candidate_key) FILTER(WHERE i.candidate_key IS NOT NULL) AS candidate_keys
        FROM edges e LEFT JOIN interventions i ON i.nct_id=e.nct_id AND i.nct_version=e.nct_version
            AND i.ord=e.intervention_ord GROUP BY 1,2,3''')
    db.execute('''CREATE TABLE ordinal_sources AS SELECT r.*,i AS intervention_record,
        i.ord IS NULL AS missing_intervention,i.intervention_name AS raw_name,
        i.possible_combination_string AS combination_string,
        i.adapter_version_public_date AS intervention_public_date,
        i.is_obsolete IS DISTINCT FROM false OR i.adapter_core_is_obsolete IS DISTINCT FROM false
            OR i.adapter_version_key_resolved IS DISTINCT FROM true AS intervention_uncertain
        FROM ordinal_requests r LEFT JOIN interventions i ON r.nct_id=i.nct_id
            AND r.nct_version=i.nct_version AND r.intervention_ord=i.ord
            AND r.candidate_key=i.candidate_key AND upper(i.intervention_type)='DRUG' ''')
    # Structs retain all source provenance without importing trial/name OR summaries
    # into a role decision. They are review evidence only.
    db.execute('''CREATE TABLE arm_review_base AS SELECT o.*,e.arm_group_ord,e AS edge_record,
        a AS arm_record,m AS regimen_record,
        e.edge_class,e.valid_intervention,e.valid_arm_group,e.audit_uncertain,
        a.arm_type,a.adapter_version_public_date AS arm_public_date,
        e.arm_group_ord IS NULL AS no_link,
        a.arm_type='EXPERIMENTAL' AS experimental,
        a.arm_type IN ('ACTIVE_COMPARATOR','PLACEBO_COMPARATOR','SHAM_COMPARATOR','NO_INTERVENTION') AS control,
        a.arm_type IS NULL OR a.arm_type NOT IN
          ('EXPERIMENTAL','ACTIVE_COMPARATOR','PLACEBO_COMPARATOR','SHAM_COMPARATOR','NO_INTERVENTION') AS unknown_role,
        e.edge_class='reciprocal' AND e.has_intervention IS TRUE AND e.has_arm_group IS TRUE
          AND e.valid_intervention IS TRUE AND e.valid_arm_group IS TRUE
          AND e.audit_uncertain IS FALSE AS same_key_valid_reciprocal,
        m.drug_ordinals>1 OR m.candidate_drugs>1 AS multi_drug,
        m.drug_ordinals=1 AND m.candidate_drugs=1 AND m.missing_interventions=0
          AND m.uncertain_regimen_edges=0 AS single_candidate_drug
        FROM ordinal_sources o LEFT JOIN edges e USING(nct_id,nct_version,intervention_ord)
        LEFT JOIN arms a ON e.nct_id=a.nct_id AND e.nct_version=a.nct_version AND e.arm_group_ord=a.ord
        LEFT JOIN arm_regimens m ON e.nct_id=m.nct_id AND e.nct_version=m.nct_version
          AND e.arm_group_ord=m.arm_group_ord''')
    db.execute('''CREATE TABLE ordinal_review AS SELECT nct_id,nct_version,candidate_key,intervention_ord,
        any_value(raw_name) AS raw_name,any_value(intervention_public_date) AS intervention_public_date,
        any_value(intervention_record) AS intervention_record,
        bool_or(missing_intervention) AS missing_intervention,
        count(arm_group_ord) AS linked_arms,
        count(arm_group_ord) FILTER(WHERE experimental) AS experimental_arms,
        bool_or(control) AS control,bool_or(unknown_role) AS unknown_role,
        bool_or(multi_drug OR combination_string) AS combination,
        bool_or(edge_class='reciprocal') AS reciprocal,
        bool_or(same_key_valid_reciprocal) AS valid_reciprocal,
        bool_or(edge_class IN ('intervention_only','arm_group_only')) AS one_sided,
        bool_or(no_link) AS no_link,
        count(arm_group_ord)=1 AND count(arm_group_ord) FILTER(WHERE experimental)=1
          AND bool_and(coalesce(same_key_valid_reciprocal,false))
          AND bool_and(coalesce(single_candidate_drug,false))
          AND NOT bool_or(coalesce(combination_string,true))
          AND NOT bool_or(intervention_uncertain) AS strict_exposed
        FROM arm_review_base GROUP BY 1,2,3,4''')
    db.execute('''CREATE TABLE arm_review AS SELECT a.*,o.linked_arms,o.experimental_arms,
        o.strict_exposed FROM arm_review_base a JOIN ordinal_review o
        USING(nct_id,nct_version,candidate_key,intervention_ord)''')
    # Keep every pair even if its ordinal list or matching child is absent.
    db.execute('''CREATE TABLE ordinal_pairs AS SELECT p.pair_id,p.target_nct_id,p.prior_nct_id,
        p.prior_phase,p.candidate_key,t AS target_ordinal,r AS prior_ordinal,
        t.intervention_ord AS target_intervention_ord,r.intervention_ord AS prior_intervention_ord,
        t.raw_name=r.raw_name AS exact_raw_name_equal,
        t.strict_exposed IS TRUE AND r.strict_exposed IS TRUE AS strict_both,
        t.control IS TRUE OR r.control IS TRUE AS control,
        t.combination IS TRUE OR r.combination IS TRUE AS combination,
        t.reciprocal IS TRUE AND r.reciprocal IS TRUE AS reciprocal_both,
        t.one_sided IS TRUE OR r.one_sided IS TRUE AS one_sided,
        t.no_link IS TRUE OR r.no_link IS TRUE OR t.intervention_ord IS NULL
          OR r.intervention_ord IS NULL AS unlinked_unknown,
        t.missing_intervention IS TRUE OR r.missing_intervention IS TRUE AS missing_intervention
        FROM pairs p LEFT JOIN ordinal_review t ON p.target_nct_id=t.nct_id
          AND p.target_first_public_version=t.nct_version AND p.candidate_key=t.candidate_key
        LEFT JOIN ordinal_review r ON p.prior_nct_id=r.nct_id
          AND p.prior_first_public_version=r.nct_version AND p.candidate_key=r.candidate_key''')
    db.execute('''CREATE TABLE arm_pairs AS SELECT o.pair_id,o.target_nct_id,o.prior_nct_id,
        o.prior_phase,o.candidate_key,o.target_intervention_ord,o.prior_intervention_ord,
        t.arm_group_ord AS target_arm_group_ord,r.arm_group_ord AS prior_arm_group_ord,
        t AS target_arm,r AS prior_arm,o.exact_raw_name_equal,
        CASE WHEN o.strict_both THEN 1
          WHEN t.control IS TRUE OR r.control IS TRUE OR t.multi_drug IS TRUE
            OR r.multi_drug IS TRUE OR t.combination_string IS TRUE OR r.combination_string IS TRUE THEN 2
          WHEN t.edge_class='reciprocal' AND r.edge_class='reciprocal' THEN 3
          WHEN t.edge_class IN ('intervention_only','arm_group_only')
            OR r.edge_class IN ('intervention_only','arm_group_only') THEN 4 ELSE 5 END AS tier_rank
        FROM ordinal_pairs o LEFT JOIN arm_review t ON o.target_nct_id=t.nct_id
          AND o.target_ordinal.nct_version=t.nct_version AND o.candidate_key=t.candidate_key
          AND o.target_intervention_ord=t.intervention_ord
        LEFT JOIN arm_review r ON o.prior_nct_id=r.nct_id
          AND o.prior_ordinal.nct_version=r.nct_version AND o.candidate_key=r.candidate_key
          AND o.prior_intervention_ord=r.intervention_ord''')
    db.execute('''CREATE TABLE condition_sets AS SELECT r.nct_id,r.nct_version,
        list(DISTINCT c.condition ORDER BY c.condition) FILTER(WHERE c.condition IS NOT NULL
          AND trim(c.condition)<>'' AND c.is_obsolete IS FALSE) AS condition_strings
        FROM requests r LEFT JOIN conditions c USING(nct_id,nct_version) GROUP BY 1,2''')
    db.execute('''CREATE TABLE pair_review AS WITH a AS (SELECT pair_id,min(tier_rank) AS tier_rank,
        count(*) AS arm_paths,count(*) FILTER(WHERE target_arm_group_ord IS NOT NULL
          AND prior_arm_group_ord IS NOT NULL) AS linked_arm_pairs FROM arm_pairs GROUP BY 1),
        o AS (SELECT pair_id,count(*) AS ordinal_paths,bool_or(strict_both) AS strict_both,
          bool_or(control) AS control,bool_or(combination) AS combination,
          bool_or(reciprocal_both) AS reciprocal_both,bool_or(one_sided) AS one_sided,
          bool_or(unlinked_unknown) AS unlinked_unknown,bool_or(missing_intervention) AS missing_intervention,
          bool_or(exact_raw_name_equal) AS any_exact_raw_name_equal FROM ordinal_pairs GROUP BY 1)
        SELECT p.*,a.* EXCLUDE(pair_id),o.* EXCLUDE(pair_id),
        t.condition_strings AS target_condition_strings,r.condition_strings AS prior_condition_strings,
        CASE WHEN len(t.condition_strings)>0 AND len(r.condition_strings)>0 THEN
          len(list_intersect(t.condition_strings,r.condition_strings))>0 END AS exact_condition_overlap,
        p.name_trial_fanout>=100 AS high_fanout FROM pairs p JOIN a USING(pair_id) JOIN o USING(pair_id)
        LEFT JOIN condition_sets t ON p.target_nct_id=t.nct_id AND p.target_first_public_version=t.nct_version
        LEFT JOIN condition_sets r ON p.prior_nct_id=r.nct_id AND p.prior_first_public_version=r.nct_version''')
    db.execute('''CREATE TABLE target_review AS SELECT target_nct_id,
        any_value(target_first_public_version) AS target_first_public_version,
        any_value(target_checkpoint) AS target_checkpoint,min(tier_rank) AS tier_rank,
        count(*) AS name_prior_pairs,count(DISTINCT prior_nct_id) AS prior_trials,
        bool_or(strict_both) AS strict_both,bool_or(control) AS control,
        bool_or(combination) AS combination,bool_or(one_sided) AS one_sided,
        bool_or(unlinked_unknown) AS unlinked_unknown FROM pair_review GROUP BY 1''')


def grain_counts(db, where='true', groups=''):
    prefix = groups+',' if groups else ''
    return records(db, f'''SELECT {prefix}count(DISTINCT p.target_nct_id) AS targets,
        count(DISTINCT p.pair_id) AS name_prior_pairs,
        count(DISTINCT (p.target_nct_id,p.prior_nct_id)) AS target_prior_pairs,
        count(DISTINCT p.candidate_key) AS names,count(DISTINCT p.prior_nct_id) AS prior_trials,
        count(DISTINCT (o.pair_id,o.target_intervention_ord,o.prior_intervention_ord))
          FILTER(WHERE o.target_intervention_ord IS NOT NULL AND o.prior_intervention_ord IS NOT NULL) AS ordinal_pairs,
        count(DISTINCT (a.pair_id,a.target_intervention_ord,a.prior_intervention_ord,
          a.target_arm_group_ord,a.prior_arm_group_ord)) FILTER(WHERE a.target_arm_group_ord IS NOT NULL
          AND a.prior_arm_group_ord IS NOT NULL) AS arm_pairs
        FROM pair_review p JOIN proxy_classes c USING(target_nct_id)
        JOIN ordinal_pairs o USING(pair_id)
        JOIN arm_pairs a ON o.pair_id=a.pair_id
          AND o.target_intervention_ord IS NOT DISTINCT FROM a.target_intervention_ord
          AND o.prior_intervention_ord IS NOT DISTINCT FROM a.prior_intervention_ord
        WHERE {where} {('GROUP BY '+groups+' ORDER BY '+groups) if groups else ''}''')


def report(db):
    return {
        'boundary': BOUNDARY, 'tiers': TIERS,
        'tier_precedence': 'Lowest rank wins at pair and target level; overlapping flags retained. High fanout never changes rank.',
        'strict_definition': 'One linked arm for that exact ordinal, experimental; same-key reciprocal, both valid, audit_uncertain=false; exactly one raw DRUG ordinal and one candidate DRUG in its union-edge arm, no uncertain regimen edge or combination-string flag; source intervention valid. Conditions/fanout not gates.',
        'denominator': grain_counts(db),
        'by_prior_phase_proxy_class': grain_counts(db, groups='p.prior_phase,c.label_proxy_class'),
        'pair_tiers': grain_counts(db, groups='p.tier_rank'),
        'pair_tiers_by_prior_phase_proxy_class': grain_counts(db, groups='p.prior_phase,c.label_proxy_class,p.tier_rank'),
        'path_tiers': grain_counts(db, groups='a.tier_rank'),
        'target_tiers': records(db, '''SELECT t.tier_rank,c.label_proxy_class,count(*) AS targets
            FROM target_review t JOIN proxy_classes c USING(target_nct_id) GROUP BY 1,2 ORDER BY 1,2'''),
        'sensitivities': {flag: grain_counts(db, where=expr, groups='p.prior_phase,c.label_proxy_class')
            for flag, expr in {
                'strict_both':'p.strict_both', 'control':'p.control','combination':'p.combination',
                'reciprocal_both':'p.reciprocal_both','one_sided':'p.one_sided',
                'unlinked_unknown':'p.unlinked_unknown','missing_intervention':'p.missing_intervention',
                'exact_raw_name_equal':'p.any_exact_raw_name_equal','high_fanout':'p.high_fanout',
                'condition_overlap':'p.exact_condition_overlap IS TRUE',
                'condition_mismatch':'p.exact_condition_overlap IS FALSE',
                'condition_unknown':'p.exact_condition_overlap IS NULL',
                'strict_low_fanout':'p.strict_both AND NOT p.high_fanout',
                'strict_condition_overlap':'p.strict_both AND p.exact_condition_overlap IS TRUE',
                'strict_low_fanout_condition_overlap':'p.strict_both AND NOT p.high_fanout AND p.exact_condition_overlap IS TRUE',
            }.items()},
        'tables': {t: n(db, f'SELECT count(*) FROM {t}') for t in TABLE_ORDER},
        'condition_provenance': 'Exact first-public version only; raw conditions have no independent public date. Unknown if either side lacks a nonobsolete nonempty string.',
        'resources': {'memory_limit':'2GiB','threads':2,'spill':False},
        'denominator_discrepancy': 'None' if n(db,'SELECT count(*) FROM pairs')==2448 and
            n(db,'SELECT count(*) FROM target_review')==91 else 'Non-frozen denominator: synthetic/test input or source discrepancy; CLI fails closed.',
    }


TABLE_ORDER = {
    'target_review':'target_nct_id', 'pair_review':'pair_id',
    'ordinal_review':'nct_id,nct_version,candidate_key,intervention_ord',
    'ordinal_pairs':'pair_id,target_intervention_ord,prior_intervention_ord',
    'arm_review':'nct_id,nct_version,candidate_key,intervention_ord,arm_group_ord',
    'arm_pairs':'pair_id,target_intervention_ord,prior_intervention_ord,target_arm_group_ord,prior_arm_group_ord',
    'arm_regimens':'nct_id,nct_version,arm_group_ord',
    'conditions':'nct_id,nct_version,ord', 'source_assertions':'assertion_id',
    'proxy_classes':'target_nct_id',
}


def run(out):
    out = Path(out)
    out.resolve().relative_to((ROOT/'data/processed').resolve())
    if not out.name.startswith('b28_') or out.exists():
        raise ValueError('Use a new ignored data/processed/b28_* output directory')
    inputs = verify_inputs()  # before connection, schema probing or row queries
    out.mkdir(parents=True)
    db = connect()
    try:
        load(db)
        build(db)
        result = report(db)
        if result['denominator_discrepancy'] != 'None':
            dump(out/'failed_denominator.json', result)
            raise ValueError('Frozen 91 targets / 2448 name-prior pairs changed')
        for table, order in TABLE_ORDER.items():
            db.execute(f'''COPY (SELECT * FROM {table} ORDER BY {order} NULLS LAST)
                TO {sp(out/(table+'.parquet'))} (FORMAT PARQUET,COMPRESSION ZSTD)''')
        dump(out/'report.json', result)
        examples = {TIERS[rank]: records(db, f'''SELECT * FROM arm_pairs WHERE tier_rank={rank}
            ORDER BY pair_id,target_intervention_ord,prior_intervention_ord,
              target_arm_group_ord,prior_arm_group_ord LIMIT 3''') for rank in TIERS}
        dump(out/'examples.json', examples)
        dump(out/'manifest.json', {'boundary':BOUNDARY,'input_sha256':inputs,
            'code_sha256':sha(Path(__file__)), 'settings':result['resources'],
            'output_sha256':{p.name:sha(p) for p in sorted(out.iterdir())}})
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = run(args.out)
    print(json.dumps({'denominator':result['denominator'],'pair_tiers':result['pair_tiers']}, sort_keys=True))


if __name__ == '__main__':
    main()
