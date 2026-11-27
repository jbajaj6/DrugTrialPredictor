# B31 builder handoff: manual endpoint review package

2026-11-27. Builder checks completed with one targeted repair; independent evaluator acceptance remains pending. This handoff does not decide clinical annotation or model readiness. The coordinator owns the ledger, which the builder has not edited.

## Delivered scope and access boundary

Only new `src/phase_by_phase/endpoint_review_package_b31.py`, `tests/test_endpoint_review_package_b31.py`, this handoff, and fresh ignored `data/processed/b31_*` artifacts were created. Existing code, protected tests, source snapshots, earlier outputs, ledger and README remain unchanged. The builder read `AGENTS.md`, the structured-trials skill, execution rules, frozen B31 ledger section, B31 prompt, and B29/B30 independent evaluations before implementation.

The module authenticates seven inputs before DuckDB connection or source row queries: pinned B30 manifest, trial summary and planned rows; B17 full-v3 manifest and outcome-header Parquet; inherited B29 manifest and queue. It verifies declared B30/B29 lineage, declared child hashes, required footer columns and frozen row counts. No B29 queue row query is needed. No other B17 child is opened.

The B30 case projection contains first-public and selected-result metadata, B29 selection metadata, inherited outcome pointer and planned coverage metadata. It never projects a proxy class or grade. The B17 text projection is restricted to NCT/version/outcome ordinal, type, title, description, time frame, obsolete flags/pointer, and adapter source/version-public-date/core flag/commit/table. It excludes analyses, p/CI, measurement values, measurement parameters/units, groups, arms, populations and result summaries. No NLP, semantic inference, network access, holdout access or model operation is part of B31.

Before materializing reported text, a key/date-only query checks the exact 269 selected result NCT/version pairs. Any source public-date mismatch, null date, date at/before first-public checkpoint or date in 2024+ fails closed. The text-bearing query then explicitly semijoins those keys **inside DuckDB**, including exact public-date equality, strict chronology and pre-2024 conditions, and filters exact `type='PRIMARY'`. Other versions never supply fallback wording. This is a logical materialization boundary; it does not claim physical Parquet reads exclude every unrelated byte.

All exact PRIMARY physical rows are preserved in `audit_only/reported.*`, including obsolete/unknown rows if present. Reviewer reported rows require both child and core obsolete flags false and no obsolete pointer. Null and duplicate ordinals remain represented; no row is deduplicated or chosen by a pointer. Audit case counts distinguish missing exact header, missing PRIMARY header, unknown type, no eligible nonobsolete header, obsolete/unknown flags, duplicate/null ordinals, and no selected result. Missing values stay null/unknown.

All 452 B30 planned rows retain their original raw fields, source keys, physical source part/row, digests, source dataset/commit/license, whole-version checkpoint association and structural states in `audit_only/planned.*`. Planned and reported rows are separate tables with separate opaque row IDs. There is no planned/reported row join, similarity computation, ordinal pairing, endpoint match or automatic clinical label. The inherited B29 outcome pointer is audit metadata only; all eligible headers survive even without that pointer.

## Review and audit delivery

Use **`data/processed/b31_full_2026-11-27_v2/reviewer/`** for manual review. Share only that directory with proxy-class/significance-blinded reviewers. It contains:

- `casebook.html`: 343 opaque cases in deterministic hash order, separate planned/reported lists and blank manual fields. Study prose is HTML-escaped. This static display does not save typed notes; its notice directs reviewers to the blank CSVs or printing.
- `cases.csv` / `cases.parquet`: opaque case ID, reviewer-order hash, planned/reported availability and five blank human fields.
- `planned.csv` / `planned.parquet`: case ID, opaque planned row ID, measure, description, time frame and blank human fields.
- `reported.csv` / `reported.parquet`: case ID, opaque reported row ID, title, description, time frame and blank human fields.

The five fields are `human_planned_reported_correspondence`, `human_prespecification_assessment`, `human_notes`, `human_reviewer` and `human_review_date`; all are null/blank. No annotation options or decisions are prefilled. Reviewer schemas exclude NCT/version/dates, source paths/ordinals, B22 reason/proxy class, B29 stratum/known-anchor metadata, B17 grade, analysis and p/value fields. IDs and order hashes depend only on domain-separated hashes of NCT, never selection reason, stratum, class or result content. These are opaque handles, not a cryptographic anonymization guarantee.

`audit_only/cases.*` is the exact-key crosswalk with selection metadata and structural counts. `audit_only/planned.*` and `audit_only/reported.*` retain raw source wording and provenance. `audit_only/report.json` contains structural counts by audit-only selection strata; `manifest.json` contains input, code and output digests. Keep the audit directory, manifest and this source-keyed handoff separate from reviewers.

**Proxy-class/significance blinding only:** reported-header presence remains visible, and study prose may reidentify a case. Explicit literal registry IDs are masked in reviewer text only, using the case-insensitive pattern `\bNCT[ -]?[0-9]{8}\b` and replacement `[registry identifier masked]`. Raw audit text remains byte-for-byte the source string. This mechanical identifier suppression does not interpret endpoint language. One reported description field needed this suppression in the actual run; no planned text field did. The package makes no claim of complete study deidentification.

Clinical annotation requires two independent human reviewers and a separately prespecified reconciliation rubric. Equal wording or ordinal does not prove endpoint identity; difference does not prove switching. A first-public version does not establish original prespecification or independent child-field timing. This enriched queue does not support population prevalence, efficacy, benefit or label-recoverability conclusions.

## Observed structural output

| Item | Count |
| --- | ---: |
| Opaque cases | 343 |
| Exact first-public B30 planned rows | 452 |
| Cases with no exact first-public planned rows, explicitly unknown | 14 |
| Selected result NCT/version/date pointers | 269 |
| Selected result cases without inherited outcome pointer | 52 |
| No selected result, explicitly unknown | 74 |
| Exact selected-version reported PRIMARY headers | 396 |
| Nonobsolete reported headers delivered for review | 396 |
| Selected result cases with eligible header(s) | 269 |
| Missing exact header / missing PRIMARY / no eligible PRIMARY cases among selected results | 0 / 0 / 0 |
| Null ordinal / duplicate-ordinal / obsolete / unknown-obsolete reported rows | 0 / 0 / 0 / 0 |

Zero anomalous rows are observations in this snapshot; synthetic fixtures exercise these states. Both reported and planned text remain many-per-case, and no endpoint pairing is emitted.

## Exact checks, failure and repair

Commands ran from `phase-by-phase/` with `PYTHONDONTWRITEBYTECODE=1`; module and pytest commands also used `PYTHONPATH=src`. Full argv, UTC completion times, exit codes, elapsed times and unabridged logs are in `data/processed/b31_checks_2026-11-27_v1/commands.jsonl` and the corresponding named logs. The command recorder is `run_check.py` in that directory; it executes argv without a shell and preserves the child exit code.

| Check | Exact child command | Exit and observation |
| --- | --- | --- |
| Initial focused | `../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_endpoint_review_package_b31.py` | 0; 37 passed |
| Initial full | `../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 0; 649 passed, five existing Arrow deprecations and one joblib core-detection warning |
| Initial harness | `../.venv/bin/python harness/check.py` | 0; PASS |
| Initial bounded run | `../.venv/bin/python -m phase_by_phase.endpoint_review_package_b31 --out data/processed/b31_full_2026-11-27_v1` | 0; 343 / 452 / 396 rows |
| Initial source/blinding check | `../.venv/bin/python data/processed/b31_checks_2026-11-27_v1/source_blinding_audit.py` | **1; AssertionError at line 88**, `assert 'NCT' not in str(...reviewer rows...)`; one reported description contained an explicit earlier-study registry identifier |
| Repair 1 focused | `../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_endpoint_review_package_b31.py` | 0; 38 passed |
| Repair 1 bounded run | `../.venv/bin/python -m phase_by_phase.endpoint_review_package_b31 --out data/processed/b31_full_2026-11-27_v2` | 0; 343 / 452 / 396 rows |
| Repair 1 source/blinding check | `../.venv/bin/python data/processed/b31_checks_2026-11-27_v1/source_blinding_audit.py` | 0; all seven input and 14 content-output hashes match; raw header/planned/case multisets have 0 missing/0 extra; reviewer-schema/blank-field/HTML/ID-order checks pass |
| Repair 1 harness | `../.venv/bin/python harness/check.py` | 0; PASS |
| Repair 1 full suite | `../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | 0; **650 passed**, same six existing warnings |
| Final source/blinding cross-check | `../.venv/bin/python data/processed/b31_checks_2026-11-27_v1/source_blinding_audit.py` | 0; additionally verifies all 14 zero-planned cases are explicitly unknown |
| Fresh replay | `../.venv/bin/python -m phase_by_phase.endpoint_review_package_b31 --out data/processed/b31_replay_2026-11-27_v2` | 0; same counts |
| Byte replay comparison | `diff -rq data/processed/b31_full_2026-11-27_v2 data/processed/b31_replay_2026-11-27_v2` | 0; **all 15 files byte-identical**, including manifest |
| Final scope/whitespace check | `../.venv/bin/python data/processed/b31_checks_2026-11-27_v1/final_preservation.py` | 0; original-file hashes unchanged; exactly three new assigned nonignored files; no trailing whitespace |

**Targeted repair round 1:** Added literal registry-ID masking only to reviewer text and a synthetic test proving audit text stays exact. The initial failed check script is preserved as `source_blinding_audit_pre_repair.py`; `source_blinding.log` retains the traceback. Initial output `b31_full_2026-11-27_v1` is retained unchanged as a failed blinding attempt and must not be distributed for blinded review. Both v2 directories are fresh outputs. No additional failing command or repair round occurred. No unresolved engineering blocker was observed by the builder; independent evaluation is still required.

The source/blinding script does not import the B31 module. It reauthenticates all seven source files before connection, checks all output digests, independently reconstructs the 269-key/date semijoin and compares raw header fields plus physical B17 row number in both directions with `EXCEPT ALL`. It separately compares every retained planned source/provenance field and B30 case metadata, reconstructs opaque IDs/order, verifies reviewer schemas and all null human fields in Parquet/CSV, checks HTML identifiers/sections/blank fields, and compares reviewer text to the raw audit projection after only documented identifier masking. This is builder evidence, not an independent evaluator verdict. Its exact SQL and results are in `source_blinding_audit.py` / `.json` in the check directory.

## Source-key audit examples

These are audit-only examples, not endpoint correspondences or clinical interpretations. Physical row numbers refer to the authenticated B17 header Parquet, not its upstream raw part.

| NCT | Selected result version / public date | Reported PRIMARY source ordinals | B17 physical rows |
| --- | --- | --- | --- |
| NCT00132873 | 4 / 2013-11-25 | 0, 1 | 39275, 39276 |
| NCT00598806 | 9 / 2017-08-15 | 0 | 6035 |
| NCT00672854 | 13 / 2014-08-01 | 0 | 10330 |
| NCT02314117 | 36 / 2018-05-02 | 0 | 76584 |

The first case has no inherited B29 outcome pointer; both PRIMARY headers are retained. These keys remain separate from B30 first-public planned version/ordinals. The audit rows also retain upstream source part, source commit/table, source public date, B17 file and manifest hashes, raw obsolete flags and ordinal state. No source result-analysis or measurement table was queried to produce these examples.

## SHA-256 evidence

The v2 manifest enumerates seven authenticated inputs and all 14 content outputs. Input pins are the frozen ledger pins, including B30 manifest `bc78b2f363f599988f9b37f96d75273873bee458b170b764bf9903934a7ab358`, B17 manifest `778d4a5f97d4afa868747d8d44269ff3bde203faeb08b5b0442d84d872a0cdd2` and B17 header `fdc66c89dee518f6a78ac18b8c731fa30c3949772fd05409cd8a2b10ebfd2517`.

| Artifact | SHA-256 |
| --- | --- |
| B31 module | `568ecbb86b2b0655bb4544074dc3cd28b4f9de703e969c0c91ccf1d4c6e2a623` |
| Focused tests | `b579234eadfe9ae9de3bbd150c4963318efe7b17e186e4b947a4f46de7a67c80` |
| V2 full/replay manifest | `f8cf3bfc4b32184ac8a59c680f51a24aa76aae1e675f87ff92f51c635a4d7bb1` |
| Reviewer casebook HTML | `66ec8e1f4e58b133f7f14ad39c75638753ccd0e6a4898a3b5cac3608f4c527bd` |
| Audit report | `1ed317fab51f5c58c612934362902bbe06a04ea5d06d889763fdc3558841c823` |
| Source/blinding audit script | `0c4ad5d61d66278ab8d31e00ffce161cc7a8ce3f6c9bb183b40b740f24f95e9d` |
| Source/blinding audit JSON | `f141fb84830dad0bca845aa03f2a558b4313db75101b032f9dcf80e761ed99e0` |

`baseline.json`, `final_preservation.json` and `execution_manifest.json` in the check directory provide original-file preservation, final scope and execution-artifact digests for coordinator/evaluator review. This document is the builder's command/failure handoff for the coordinator-owned ledger; it does not modify frozen acceptance criteria or authorize annotation, labels or modeling.
