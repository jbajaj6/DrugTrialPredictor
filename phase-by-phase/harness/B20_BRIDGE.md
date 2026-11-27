# B20 retrospective molecular-candidate pilot: builder handoff

Builder execution is complete. Independent evaluation/acceptance is pending. The real run is **source-only because external API access failed**, not a successful real molecular mapping. No precision, efficacy, model, significance, or cross-phase validity estimate is established.

## Files and reproducible commands

New implementation: `src/phase_by_phase/bridge_b20.py`; focused fixtures: `tests/test_bridge_b20.py`. Existing implementation, protected tests, main README, raw snapshots, and prior outputs are unchanged. The ledger contains appended builder evidence only; fixed B20 acceptance criteria remain unchanged.

Run from `phase-by-phase/` with `PYTHONPATH=src`:

```sh
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_bridge_b20.py
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
python3 harness/check.py
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.bridge_b20 --out data/processed/b20_pilot_2026-11-27_v1 --cache data/raw/b20_chembl_cache_2026-11-27_v1 --mode online
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.bridge_b20 --out data/processed/b20_offline_2026-11-27_v1 --cache data/raw/b20_chembl_cache_2026-11-27_v1 --mode offline
```

Those output/cache paths already exist and cannot be overwritten. An evaluator must choose a fresh output path for replay, retaining the cache. `--mode source-only` creates a fresh explicit no-network cache; it is available when acquisition is intentionally deferred. `--name-limit` is restricted to 0–200; pilot default is 200. Replay verifies the exact ordered name plan, name limit and every cached byte digest before parsing, and does not call the transport. Manifest mode/output timestamps need not match; semantic tables and report do match exactly.

Executed command arrays, exits, durations and logs: `data/processed/b20_execution_2026-11-27_v1/commands.jsonl`. Source schema/manifests and initial byte verification: `source_inspection_v2.log`. Read-only graph/source audit: `audit_outputs_v2.py`, `output_audit_v2.log`. Raw examples actually inspected: `inspected_graphs.json`. Initial failed probes/logs are preserved and explained in the ledger.

## Sample and source boundary

Universe: 19,576 pre-2020 B15 Phase 3 first-public metadata keys. Only NCT, version, phase, public date are projected from the development cohort; its label columns are not scanned. B18 report hashes pin the three exposure/alias inputs, B15 cohort metadata source, B12 design, and organized protocol files. B12 pins the protocol manifest and design bytes; the protocol manifest verifies its four child files. The raw inventory pins all 20 condition files. Thirty-three source/manifest digests are recorded in each pilot manifest. No outcome table, grade table, current status, raw MeSH, or 2024+ target row is queried.

Sampling seed `20261127`; within each quota, ascending SHA256 of `seed|nct_id|nct_version` with exact-key tie break. Apply quotas in listed order and remove **selected** keys before the next quota. Eligibility pools can overlap; actual selected strata are disjoint. A primary-stratum trial can contain comparator or combination arms too. Nonexperimental-only means all its B18 candidate exposure flags are nonexperimental. Alias collision requires B18 `canonical_count > 1`; self-alias alone is insufficient. No replacement of a short stratum is permitted. The manifest contains all exact selected NCT/version IDs and ordered lookup names.

| Selected stratum | Requested/selected | Remaining eligible at selection |
| --- | ---: | ---: |
| primary single-drug | 50/50 | 9,499 |
| multi-drug | 25/25 | 2,106 |
| no-link | 25/25 | 4,607 |
| shared-control | 20/20 | 921 |
| nonexperimental-only | 15/15 | 2,453 |
| alias-collision | 15/15 | 3,904 |

There are zero shortfalls. This is an enriched diagnostic sample, not a population prevalence sample.

## Separate output grains

All tables are canonical sorted JSONL: each row is independently inspectable; nested candidate evidence remains structured. The manifest lists each semantic table SHA-256. Empty evidence tables are intentionally empty files, with their names/counts recorded in the report and manifest.

| Table | Grain / source key | Observed rows |
| --- | --- | ---: |
| trials | NCT + version, checkpoint, selected stratum | 150 |
| design_provenance | NCT + version; B12 public date, original first-post date, archive-left-truncation flag and source file | 150 |
| arms | NCT + version + ord; all original columns | 284 |
| interventions | NCT + version + ord; all original columns, all types preserved | 366 |
| aliases | NCT + version + intervention_ord + other_name_ord; all original columns | 152 |
| links | NCT + version + source + parent_ord + item_ord; both assertion directions retained | 944 |
| conditions | NCT + version + ord; raw condition and source file, no MeSH | 193 |
| b18_exposures | original exposure assertion rows and flags | 415 |
| b18_target_exposures | original target exposure rows plus explicit NCT/version keys | 415 |
| b18_alias_review | original alias review rows, not identity proof | 125 |
| name_occurrences | DRUG intervention key + name origin + alias ordinal where applicable | 463 |
| query_status | unique normalized recorded name, status and request count | 369 |
| chembl_evidence | queried name + search-result rank + molecule ID, exact evidence, synonyms, hierarchy | 0 |
| molecular_candidates | name occurrence × exact returned candidate evidence | 0 |
| unresolved_collisions | name occurrences with anything other than one complete exact candidate | 463 |
| review_sheet | every DRUG intervention key, source flags, candidate/parent sets, unknown clinical identity and blank human adjudication | 331 |

The 35 non-DRUG interventions and their source graph remain inspectable but do not contribute lookup names. Twenty-five selected trials lack arms/links; 87 lack aliases. No absence is filled. All 944 preserved assertions are source-resolved; that means exact structural key integrity only. There are no obsolete rows in this selected graph, but source flags are preserved without deletion. Report counts by sample stratum, original B18 identity flag, name status, missing children, and assertion status are separate denominators.

## Molecular matching and API limits

Normalization is NFKC Unicode normalization, casefolding and whitespace collapsing only. Punctuation, doses, salt names and combination strings are preserved. Names are ordered lexicographically; aliases retain their intervention and alias ordinals. Whole names may match only an exact normalized ChEMBL pref-name or synonym. Fuzzy results are archived evidence with `exact_match=false`, never candidates. An alias-derived hit is tied to that recorded alias; it does not prove that the entire intervention/regimen is that molecule. Review keeps candidate sets across names ambiguous when molecule or parent IDs differ. Shared parent IDs never merge molecules. Original, parent, active and returned molecule IDs remain separate nullable fields. No contemporary approval, indication, maximum phase, or result fields enter semantic tables. Raw responses may contain contemporary fields; those bytes are acquisition evidence only.

Each name uses one bounded search page of at most 100 molecules; a nonempty next page or total larger than the returned count makes the whole search unresolved, while retaining any exact candidates already observed. Missing synonyms/malformed payloads remain invalid/unknown. Each request has a 10-second timeout, at most two attempts, at least 0.3-second spacing (1-second retry pause), 8 MiB response bound, and a circuit breaker after three consecutive failed names. All response bytes (including empty bytes when no HTTP response exists), fixed public URL, UTC time, HTTP status, safe exception class, byte-truncation flag and SHA-256 are archived in a fresh Git-ignored cache. No credentials or exception text are logged. The cache index is the evidence metadata archive; the semantic evidence links to response digests.

References consulted: [ChEMBL public data services](https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services) and [compound/parent questions](https://chembl.gitbook.io/chembl-interface-documentation/frequently-asked-questions/drug-and-compound-questions). These describe API structure, not project-trial validity.

## Actual acquisition and inspection

All six attempts on the first three names returned no HTTP status and `URLError`; each archived empty body has SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. These were `1.0% al-8309b ophthalmic solution`, `1.75% al-8309b ophthalmic solution`, and `17 ohpc`. The error class is recorded without claiming whether the cause is DNS, transport policy or service availability. There are 3 failed queried names, 197 unqueried because of the circuit breaker, and 169 unqueried because of the 200-name budget. Zero successful responses means zero observed candidates; molecular coverage and precision are **not estimable**, not negative. The user-provided aspirin smoke result was not inserted into this cache or attributed to any project trial.

Cache-only replay reproduces all 16 semantic files and `report.json` byte-for-byte. Actual nonempty molecular-response replay is demonstrated with synthetic fixtures only. The real replay demonstrates preservation of source graphs and unavailable-network states.

Builder read-only audits compared complete source child multisets at exact selected keys, checked every input/output/cache digest, reconciled B18 checkpoint dates, and confirmed all 331 DRUG interventions appear in the 463 recorded-name occurrences. Seventy baseline code/document files were checked for preservation (ledger is append-only). Example graphs inspected:

- `NCT00623103` v0: capsule and transdermal patch have distinct ordinals and share Exelon/Prometax aliases; neither is merged.
- `NCT00615602` v0: seven recorded interventions, including distinct Trastuzumab ordinals 1 and 6, with 24 assertions and multiple combination-arm drugs retained.
- `NCT00129935` v0: three drugs, no arms or links; missing linkage remains unknown.
- `NCT01149369` v0: active comparator and placebo plus Emend alias retained; no experimental-arm identity is invented.
- `NCT00704509` v0: experimental Bifeprunox plus placebo and Quetiapine comparator all retained.
- `NCT00532662` v0: one S(+)-ketamine intervention linked to experimental and active-comparator arms remains shared-control.

## Verification and repairs

Focused: **38 passed**. Full: **347 passed**, six existing/environment warnings. Harness: **PASS**. Source and artifact audit v2: exit 0. Offline replay: exit 0. Existing files and prior/source hashes match. No implementation repair was needed after initial fixtures or real pilot.

One verification repair round corrected the builder audit's relative-versus-absolute filename comparison: the failed script normalized only `source_file` but DuckDB also preserved `filename`. The corrected script scans the same absolute source paths as the CLI and compares both provenance columns exactly. Failed audit and fresh successful audit logs are retained. Source/output bytes and scientific criteria were unchanged. Preflight path and command-wrapper errors are listed separately in the ledger.

The next decision belongs to the independent evaluator. A real ChEMBL acquisition will require network access and a **new** cache/output directory; this pilot cannot establish molecular validity or historical public availability.

## Verified-CA transport repair (2026-11-27)

The first network run above remains a preserved failure. A later fresh online v2 run using an explicitly verified `SSL_CERT_FILE` succeeded in obtaining real ChEMBL responses; its immutable cache is `data/raw/b20_chembl_cache_network_2026-11-27_v2` and output is `data/processed/b20_pilot_network_2026-11-27_v2`. This repair makes that verified TLS setup reproducible without requiring a shell variable: `transport()` now creates a certificate-verifying SSL context from `SSL_CERT_FILE` when deliberately configured, otherwise from the explicit `certifi` dependency. It does not disable hostname checking or certificate verification. A missing/invalid bundle fails closed as a transport error; no credential or exception text is logged.

Focused TLS tests inspect the context passed to `urlopen` without network calls. `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_bridge_b20.py` exited 0 with **40 passed**. The full suite with `tests` exited 0 with **349 passed**, five pre-existing DuckDB deprecation warnings. `../.venv/bin/python harness/check.py` exited 0/PASS. Installed `certifi` was 2024.8.30; the selected bundle SHA-256 was `94edeb66e91774fcae93a05650914e29096259a5c7e871a1f65d461ab5201b47`.

Fresh offline command (exit 0):

```sh
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.bridge_b20 \
  --out data/processed/b20_offline_verified_ca_replay_2026-11-27_v1 \
  --cache data/raw/b20_chembl_cache_network_2026-11-27_v2 --mode offline
```

All **16 semantic JSONL files and `report.json` are byte-identical** to the successful v2 output. Their manifest SHA-256 differs by design because it records the new code hash and offline mode: original `f8510b57e99b29a51339936ba6cba9b6b49bd389815b02c836c33287a10e0343`, replay `6c833c19462a37f192ea44d6361fe233d27ad355a74dde562077002e26edcd3a`. The replay required no network request and did not overwrite the online cache or prior outputs. It still establishes only retrospective molecular *candidates*, not clinical identity or historical availability; independent evaluator acceptance is pending.
