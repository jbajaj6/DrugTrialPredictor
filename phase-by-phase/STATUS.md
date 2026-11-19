# Phase-by-phase implementation status

Publication review: 2026-11-19. Modeling remains paused.

## What is implemented

| Stage | Current implementation | Status |
| --- | --- | --- |
| Acquisition | Paginated ClinicalTrials.gov API query for interventional drug trials, Phases 1-3, starting 2005-2019 | Pilot downloader implemented |
| Storage | Compressed raw JSON, trial metadata, and long-form drug-condition input tables | Local, Git-ignored data |
| Cleaning | Surface name normalization, placebo/sham filtering, stable identifiers, deduplicated trial-program links | Provisional candidate links |
| Evaluations | Null-key, duplicate-link, ID-collision, placebo, coverage, and multi-indication checks | Structural diagnostics only |
| Documentation | Project schematic, planned schema, testing walkthrough, and modeling roadmap | See [README](README.md) |
| Longitudinal modeling | Historical snapshots, transition labels, censoring, calibration, and prediction models | Not implemented |

## Verification

From the repository root, run:

```bash
python3 -m pytest -q
python3 -m compileall -q phase-by-phase/src/phase_by_phase
```

On 2026-11-19, all **12 tests passed** and Python compilation completed without
errors. These are small function tests, not independent clinical validation.
Downloader pagination, empty/malformed API responses, arm-aware linkage, and
end-to-end failure handling are not currently covered by the test suite.

## Saved pilot audit

The following values come from the local report produced during the 2026-11-13
pilot run. They were inspected again on 2026-11-19; no fresh download was run
as part of publication.

| Metric | Saved value |
| --- | ---: |
| Downloaded studies in pilot | 1,000 |
| Flattened drug-condition rows | 3,519 |
| Distinct trials represented in those inputs | 1,000 |
| Trials producing candidate links | 989 |
| Candidate program identifiers | 1,755 |
| Trials flagged for multiple indications | 260 |
| Duplicate trial-program rows | 0 |
| Null output identifiers | 0 |
| Identifier collisions detected | 0 |

The saved structural report says PASS. This does **not** establish that the
1,755 candidates are distinct drug-development programs or that 98.9% of links
are scientifically correct. Coverage is computed relative to trials present
in the flattened mapping inputs, not necessarily every downloaded study.
The 1,000 records are an API-limited pilot, not a random sample or a census.

## Remaining work before modeling

1. **Resolve treatment arms.** The current cleaner pools all DRUG intervention
   names within an NCT ID into one candidate regimen. Drugs in separate
   comparator arms can therefore be combined incorrectly. An A-versus-B trial
   must not be treated as an A-plus-B therapy. Do not use these candidate IDs
   as final longitudinal program identities yet.
2. **Resolve identities and indications.** Brand names, development codes,
   and ingredient aliases are not reconciled. The downloader cross-joins drug
   names and condition strings; it does not establish drug-condition causality
   or assign study-level MeSH terms to individual conditions.
3. **Strengthen the audit.** Account for all downloaded studies, explain dropped
   records, retain provenance, and manually review a reproducible sample.
   Currently, coverage WARN can coexist with overall PASS, and a FAIL report
   does not cause a nonzero runner exit. Reports are diagnostics, not CI gates.
4. **Preserve reproducibility.** Add a retrieval manifest, query/version metadata,
   content hashes, explicit ordering, and offline replay. Fresh API calls can
   return different records, and the current runner overwrites the output files.
5. **Complete phase handling.** The phase-normalization helper is tested on some
   inputs but is not called by the real-data runner. Its canonical
   `EARLY_PHASE1` spelling currently normalizes to an unrecognized alias.
6. **Build temporal outcomes.** A 2005-2019 start-date pilot cannot establish
   complete development histories or later advancement. Later follow-up,
   feature-availability dates, indication-specific approval evidence, and
   censoring rules still need to be implemented.

The raw download and derived Parquet files stay local under the repository's
existing data ignore rules. This publication includes source, tests, plans,
and this status summary; it does not publish patient data or model results.
