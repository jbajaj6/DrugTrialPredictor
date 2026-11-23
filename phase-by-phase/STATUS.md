# Phase-by-phase implementation status

Updated 2026-11-19 after the full-cohort build. See [RESULTS.md](RESULTS.md)
for the executed findings and [README.md](README.md) for commands and methods.

## Implemented and executed

- Complete ClinicalTrials.gov query: **151,081 records**, 152 checksummed pages.
- Saved query, retrieval timestamps, page hashes, record counts and offline replay.
- Arm-aware DRUG/BIOLOGICAL organization with raw source provenance.
- Conservative single-indication candidate linkage; explicit review/exclusion reasons.
- **67,109 retained trials**, **71,485 candidate programs**, **112,292 arm-level links**.
- **5,333** multi-trial candidates and **2,522** candidates spanning phase labels.
- All source trials accounted for. Structural audit **PASS**; overall **WARN**
  because clinical identity and historical feature versions remain unvalidated.
- Registry-entry and post-results snapshots, fixed-horizon labels, follow-up
  exclusions, grouped temporal splits, and outcome-availability embargoes.
- Logistic/rate/forest analysis code with enforced sample-support gates.
- Machine-readable audits, source-linked review queue, report and cohort figure.
- **118 tests passed**, including offline CLI integration, deliberately corrupted
  inputs, treatment-arm counterexamples, and leakage/censoring contracts.
- Source-consistency corrections from the bounded [spot review](SOURCE_REVIEW.md).

## What “clean” means here

The tables obey explicit structural and temporal rules. That does not prove
that every exact drug/condition label is the same clinical development program.
Unreviewed aliases, formulations, background therapies, broad indications and
missing historical versions remain scientific limitations.

The earlier 1,000-record prototype and its 1,755 program IDs are superseded.
Its trial-wide drug pooling is not used by the full analysis.

## Not implemented or not established

- Clinically reviewed molecule/indication identity resolution.
- Historical protocol versions establishing truly as-of baseline fields.
- Standardized biological safety/efficacy result extraction.
- Indication-specific FDA approval outcomes.
- Individual-drug probability intervals or coefficient p-values.
- Prospective prediction validity.

The model runner will not fit a real-data model if the source is incomplete or
the held-out event support is insufficient. Synthetic model tests establish
software behavior, not prediction performance on actual drug programs.

## Reproducibility

Raw snapshot: `data/raw/phase_by_phase_full_2026-11-19/`.
Final output: `data/processed/phase_by_phase_final_2026-11-19/`.

These directories are Git-ignored. The output manifest records Python/package
versions, code hashes, input-manifest hash, cutoff, horizon and bootstrap settings.
The first full run and the optimization-equivalence run are preserved separately;
use the **final** output for conclusions. Acquisition is a live API extraction,
not a transactionally frozen registry database.

The `leo/giannis` branch tracks code, tests, documentation, and visualizations
under `phase-by-phase/`; raw and processed data remain local and Git-ignored.
