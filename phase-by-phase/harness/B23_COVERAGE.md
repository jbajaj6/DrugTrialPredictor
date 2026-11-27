# B23 probability-panel candidate-evidence coverage: builder handoff

This is an audit of **current ChEMBL exact-name candidate evidence** attached to historical first-public Phase 3 protocol records. It is not molecule-identity precision, historical ChEMBL availability, efficacy, an indication-level link, or model performance. The 2024+ final holdout and outcome tables are not read.

## Frozen source-only draw

The frame contains 19,576 unique B15 `PHASE3` first-public NCT/version keys dated before 2020. The code reads only `nct_id`, first-public version/date, and `pure_phase` from B15. It sorts by SHA-256 of `20261127|nct_id|version` (key tie-break), taking the first 100. B18 drug/arm flags and ChEMBL results have no role in selection. A nested 400-key design is preregistered but **was not run**.

The pre-acquisition freeze is `data/processed/b23_pre_100_2026-11-27_v2/pre_acquisition_manifest.json`, SHA-256 `790c2aac45db80fe64fb710773aeae7d11f1c7b0aae947dcf7dd676a1a459e95`. It records the entire frame hash, selected NCT/version/date keys, source and graph file digests, all 229 normalized names, acquisition settings, and implementation code digest. The earlier `v1` freeze was superseded *before network* after correcting the raw arm-type field and rate-limit circuit. Both are retained; neither upstream source nor B20 cache/output was modified.

Exact-version source-only tables: 100 trials and design-provenance rows, 164 arms (73 `EXPERIMENTAL`), 223 interventions (200 `DRUG`), 66 aliases, 468 bidirectional link rows (234 assertions), 129 raw conditions, and 260 nonblank DRUG-name occurrences mapping to 229 distinct normalized names. The source graph retains controls, non-DRUG interventions, original raw text, ordinals, aliases, both link assertion directions, and provenance. Twenty-four trials have no resolved DRUG arm assignment.

The preregistered preflight counted 25 arms with at least two linked DRUG interventions **within each assertion direction**. A conservative union of both directions counts 26. In `NCT01223352` version 0 arm ordinal 0, the `arm_group` assertion links DRUG ordinal 0, while the `intervention` assertion links DRUG ordinal 1. Each direction alone has one drug, but their union has two. The graph is not changed to make these agree; the union flag means *possible multi-drug or conflicting link assertions*, not proof of combination treatment.

## Acquisition and status rules

The ChEMBL search is a retrospective annotation, not a dated predictor. All 229 names are in the frozen plan; none is dropped alphabetically. Pages are at most 100 search results and at most three pages/name, two attempts/page, 10-second request timeout, >=0.3-second spacing, 8 MiB/response and 1,500 global attempts. TLS certificate and hostname checks remain enabled using the configured verified CA or `certifi`. Every attempted response, including error bytes, is archived with URL, offset, status, UTC time, safe error class, body file and byte SHA-256. HTTP 429 opens a rate-limit circuit instead of continuing to hammer the service. Unattempted names and every cap, missing page, malformed response, timeout, rate limit or unresolved exact-ID collision are **unknown**, not negative.

Only exact normalized preferred-name/synonym matches create candidate rows; original, parent, active, and returned molecule IDs remain separate. Contemporary approval, maximum phase, indication and result fields are not projected into candidate semantic tables. Every intervention and arm can be reviewed separately; candidate evidence for a comparator does not establish the sponsor's tested molecule. A human-adjudication field stays blank.

Trial coverage is defined as any recorded DRUG name in the first-public protocol having a complete exact-candidate search. One confirmed candidate proves candidate evidence is present even if other names are unresolved; no evidence is established only when all recorded DRUG names have complete no-exact-candidate searches. Trials with no name or all unresolved names remain unknown. The lower/upper bounds assign unresolved **sampled** trials to uncovered/covered respectively; they are within-sample partial-identification bounds, not bounds for the full frame. Names/arms/interventions within a trial are descriptive clustered records, not independent probability draws. Sampling uncertainty for extrapolation to the frame has not been quantified. A Wilson interval is withheld unless the trial-level binary quantity is fully observed.

## Commands and verification

Run from `phase-by-phase/` with `PYTHONPATH=src` and the project `../.venv/bin/python`:

```sh
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_coverage_b23.py
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.coverage_b23 prepare --out data/processed/b23_pre_100_2026-11-27_v2
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.coverage_b23 online --pre data/processed/b23_pre_100_2026-11-27_v2 --cache data/raw/b23_chembl_cache_100_2026-11-27_v1 --out data/processed/b23_pilot_100_2026-11-27_v1
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.coverage_b23 offline --pre data/processed/b23_pre_100_2026-11-27_v2 --cache data/raw/b23_chembl_cache_100_2026-11-27_v1 --out data/processed/b23_pilot_100_replay_2026-11-27_v1
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
../.venv/bin/python harness/check.py
```

Focused synthetic tests: **10 passed**. Full suite: **393 passed**, 5 pre-existing DuckDB deprecation warnings. Harness: **PASS**. These are code checks, not scientific validation. Source-only selection and graph counts match the frozen preflight. No 400-trial run is authorized before independent review.

## Live and replay result

The fresh, TLS-verified 100-trial run completed with **229/229 names accounted for** and **393 live attempts**, below the 1,500 cap. The immutable cache is `data/raw/b23_chembl_cache_100_2026-11-27_v1`; the live output is `data/processed/b23_pilot_100_2026-11-27_v1`; offline replay is `data/processed/b23_pilot_100_replay_2026-11-27_v1`. Offline replay made no requests and produced all **14 JSONL semantic tables and `report.json` byte-for-byte identical** to the live run. Cache page bodies and attempts are checked by SHA-256 before replay. Neither B20 nor upstream data was changed.

| Name-search state | Distinct normalized names |
| --- | ---: |
| Complete, one exact ChEMBL candidate | 83 |
| Complete, no exact candidate | 69 |
| Complete, multiple exact candidates | 4 |
| Three-page cap, unresolved | 60 |
| HTTP/transport failure, unresolved | 13 |
| **All planned names** | **229** |

There were no 429 rate-limit responses. The 13 failed names comprise **12 double-timeouts and one name with two HTTP 400 responses**; all remain unknown, not no-match. Across all pages the cache has 366 HTTP 200 attempts, 25 no-status transport attempts, and 2 HTTP 400 attempts. The extra no-status attempt was an initial timeout for `pegaptanib sodium`, whose later retry succeeded but whose broad search ultimately hit the page cap. All 393 body files have unique paths and matching SHA-256; none exceeds 8 MiB. The 60 page-capped searches may contain exact candidates on unobserved pages; they remain unresolved. Ninety-one exact candidate rows were recorded from complete searches. They are molecule *candidates*, not verified mappings to the trial's active drug. Candidate rows carry normalized names and molecule IDs; the exact original page URL, offset, retrieval time, and SHA are in the cache index/body and can be reconstructed deterministically by name and returned ID. Explicit per-candidate page provenance is a remaining audit improvement; the independent evaluator should decide whether this is required before any scale run.

Arm/control accounting is separate from name coverage: of 164 arms, 73 are `EXPERIMENTAL`; 56 `ACTIVE_COMPARATOR`, 31 `PLACEBO_COMPARATOR`, 3 `NO_INTERVENTION`, and 1 `SHAM_COMPARATOR` make 91 nonexperimental/control-category arms. Eleven arms have no resolved DRUG link, and 24 of the 100 trials have no resolved DRUG arm assignment. The union of both resolved link directions flags 26 arms as possible multi-DRUG; each direction separately flags 25. The extra union-only arm is the `NCT01223352` directional conflict above, **not** verified combination treatment.

| Trial-level evidence state | Trials |
| --- | ---: |
| At least one complete exact-name candidate | 47 |
| All DRUG-name searches complete, none exact | 20 |
| Unknown because some searches unresolved | 33 |
| **Sample** | **100** |

Assigning all 33 unknowns to uncovered gives a **47% lower bound within the 100 sampled trials**. Assigning them all to covered gives an **80% upper bound within that sample**. These bounds concern **any recorded DRUG-name candidate evidence**, not investigational-drug coverage or the proportion of correctly identified molecules. The sample was drawn from the B15 pre-2020 pure-Phase-3 first-public frame, but 47%–80% are **not guaranteed bounds for all 19,576 frame trials**; extrapolation requires a separate sampling-uncertainty analysis. No Wilson interval is calculated because the binary trial-level status is not fully observed. A full-population coverage or identity claim is not established. Independent evaluation is pending.
