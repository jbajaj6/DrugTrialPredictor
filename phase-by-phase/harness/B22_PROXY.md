# B22: reported Phase 3 superiority-p proxy audit

This is a **development-only label audit**, not clinical efficacy grading or a
prediction model. A positive row means that one reported primary, explicit
superiority analysis of two candidate mapped treatment/comparator groups has
an interpretable p interval wholly below 0.05. A negative row means that its
p interval lies wholly at or above 0.05. Neither label establishes direction,
clinical benefit, drug approval, or completion. Unknown is distinct from 0.

## Inputs and gates

- The denominator is all 19,576 unique pure Phase 3 target NCTs from pinned
  B15 `development_rows.parquet` with first-public design in 2005–2019.
- B19 contributes exactly one selected result version per NCT and per-primary
  evidence. Its source is the preserved B17 pre-2024 development child tables.
  The CLI verifies the three pinned manifests and all their output hashes,
  checks B19/B17/B15 provenance, and rechecks **all** preserved B17 child
  public dates against the selected exact version before reading result values.
- Every target is retained. An absent result, missing/multiple primary or
  analysis, incomplete group/arm mapping, absent comparator role, non-explicit
  superiority type, NI/equivalence conflict or comment, and ambiguous p bound
  receives an explicit unknown reason. The report also counts overlapping
  uncertainty states; reason codes are exclusive by fixed priority.
- `=0.049` and `<0.05` are positive; `=0.05`, `>0.05`, and `>=0.05` are
  negative; `<=0.05`, `<0.1`, and `>0.01` are unknown. Parsed p must be finite
  in `[0,1]`. `SUPERIORITY_OR_OTHER` is not explicit superiority. A missing
  tested-NI flag can coexist with an explicit superiority enum, but a true
  flag, conflicting enum, or nonempty NI comment forces unknown.
- Exact analysis-group IDs are checked against the preserved child table.
  Determinate rows retain the raw analysis source file/commit/public date,
  linked result-group IDs and source files, and candidate arm ordinals, labels,
  roles and source files. An exact candidate label bijection is not verified
  drug identity or evidence of a favorable effect.

The outputs are `all_target_labels.parquet` (one NCT),
`exact_analysis_evidence.parquet` (one exact referenced analysis),
`determinate_group_arm_evidence.parquet` (two linked groups per determinate
analysis), `review_sheet.csv` (deterministic small sample of each reason),
`report.json`, and `manifest.json`. They are label/audit artifacts only and
must never enter earlier-phase model features.

## Executed builder checks (2026-11-27)

Commands below run from `phase-by-phase/` with the project virtual environment.
Each output directory was fresh and Git-ignored; prior artifacts were not
overwritten.

```sh
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_reported_superiority_b22.py
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.reported_superiority_b22 --out data/processed/b22_pilot_2026-11-27_v1 --limit-targets 1000
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.reported_superiority_b22 --out data/processed/b22_pilot_2026-11-27_v2 --limit-targets 1000
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.reported_superiority_b22 --out data/processed/b22_full_2026-11-27_v1
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
../.venv/bin/python harness/check.py
```

Focused tests exit 0: 32 passed. Pilot v1 exit 0: 1,000 targets, three
determinate. After adding explicit group/arm source-file provenance, pilot v2
first exited 1 (`AttributeError: 'Pandas' object has no attribute
'adapter_source_file'`): the projection of analysis-group rows omitted that
source column. Targeted repair round 1 included the original source column;
the fresh-output pilot v2 rerun exited 0 with the same 1,000/three counts.
Its 1,000 target IDs are unique; all five output-file hashes match; three
determinate analyses have six unique group/arm rows and source public dates
equal their selected result dates. Examples: NCT00145470 v15 `=0.0257`
positive; NCT00118209 v513 `=0.6519` negative; NI/equivalence
NCT00116805 `<0.001` unknown.

Full development replay exit 0: **19,576 unique targets; 297 determinate
proxy labels (170 positive, 127 negative); 19,279 unknown**. Reasons:
11,162 no posted primary result; 2,408 primary missing/multiple; 3,550
analysis missing/multiple; 1,200 not explicit superiority; 542 NI-comment
review; 301 arm mapping; 98 comparator role; nine contrast; nine p missing;
297 determinate. Overlapping uncertainty counts are in `report.json` and
cannot be added to the exclusive reason totals. Every one of 297 determinate
dates is in 2017–2023: **zero training labels were public before 2016**.
This proxy cannot be trained under the earlier fixed 2005–2015 / 2016–2019
split. No RF, boosting, NLP, approval analysis, or final-holdout score ran.

Full artifact inspection exited 0: 19,576 unique labels, zero invalid
checkpoint/result chronology, 2,456 unique exact raw analysis rows, 594
unique determinate group/arm rows, and all five recorded output hashes match.
Full suite exit 0: **381 passed**, five preexisting DuckDB deprecation
warnings. Harness check exit 0/PASS. The initial un-escalated Python schema
inspection failed before launch because macOS Python framework access was
sandbox-blocked; approved read-only retry exited 0. The independent evaluator
must inspect the code, artifacts and representative positives/negatives/
unknowns before accepting B22; builder tests are not scientific validation.

## Independent evaluation and exact-key repair

The independent evaluator found an **acceptance failure** in the initial
outputs: nullable `nct_version`, `outcome_ord`, and `analysis_ord` in
`all_target_labels.parquet` were inferred as `DOUBLE`; the same exact-key
columns were `DOUBLE` in `determinate_group_arm_evidence.parquet`. Floats can
silently change ordinal values above 2^53. This was a schema/provenance bug,
not a reason to change any clinical or p-value rule. Repair round 2 builds
those columns directly from original records as nullable `Int64` before any
join or Parquet write; the group/arm output also preserves `arm_ord` as
`Int64`. A synthetic 2^53+1 ordinal round-trip test checks exact identity.

The v3 pilot/full were successful preliminary replays but still had the
group/arm schema defect; they are superseded by **fresh v4 outputs**. Nothing
was overwritten. Additional executed commands from `phase-by-phase/`:

```sh
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_reported_superiority_b22.py
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.reported_superiority_b22 --out data/processed/b22_pilot_2026-11-27_v4 --limit-targets 1000
PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.reported_superiority_b22 --out data/processed/b22_full_2026-11-27_v4
PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
../.venv/bin/python harness/check.py
```

All exit 0: focused **34 passed**; pilot 1,000 targets/three determinate;
full 19,576 targets/**297 determinate** (170 positive, 127 negative);
full suite **391 passed** with five preexisting deprecation warnings;
harness **PASS**. The fresh v4 artifact inspection exited 0: all five
recorded output hashes match; `all_target_labels.parquet` has 19,576 rows,
`exact_analysis_evidence.parquet` 2,456, and
`determinate_group_arm_evidence.parquet` 594. Parquet schemas show exact
`int64` for `nct_version`, `outcome_ord`, and `analysis_ord` in all three
files, plus `arm_ord` `int64` in the group/arm file. Representative determinate
rows: NCT00118209 v513 p=0.6519 negative; NCT00145470 v15 p=0.0257
positive; NCT00182754 v157 p=0.17 negative. A no-posted-primary unknown is
NCT00115570. These are **proxy evidence only**, not clinical efficacy.

Chronology/class support remains unchanged: zero labels known by the 2016
training cutoff. For rolling 2018, only 19 training labels (8 positive,
11 negative) are available, with 28 validation labels; 2019 has 65 training
(29 positive, 36 negative) and 25 validation. These are descriptive support
counts, not a model score. No model was trained or final holdout opened.
Independent evaluator acceptance is still pending on v4.
