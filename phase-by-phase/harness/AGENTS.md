# Leo's phase-by-phase scope

This folder is installed at `phase-by-phase/harness/`. Work only inside
`phase-by-phase/`. Read broader project files and existing datasets as needed,
but do not change `src/dtp`, `sql`, the root notebook, root dependency files,
or the broader project's README. No new downloads, NLP, API keys, or paid runs.

## Scientific contract

- One row per NCT ID; Phase 1, 2, and 3 each have separate completion and
  reported-significance tasks. Combined and early phases remain separate and
  are excluded from the initial six tasks; never duplicate them into two phases.
- Completion: COMPLETED=1, TERMINATED/WITHDRAWN=0, other status unknown.
- Q2: existing numeric minimum reported primary p-value <.05, conditional on
  completion and p-value reporting. Unknown stays unknown. Call it reported
  significance, never beneficial efficacy or endpoint attainment.
- No highest-phase or advancement probability without explicit linked
  transition labels. Never multiply the six outputs into such a probability.
- Use policy.FEATURES only. No text-derived eligibility counts, embeddings,
  post_* fields, label_* fields, status, actual enrollment, sites, registration
  lag, funding, hype, science, or identifiers as model inputs. Exclude existing
  sponsor_prior_stop_rate: its global smoothing prior uses outcomes through
  2015 and contaminates the new earlier fit/validation partitions.
- Current-record structured fields may also have changed over time. Output is
  explicitly retrospective, not validated registration-time forecasting.

## Coordinator protocol

1. Read README.md, LESSONS_FROM_EXISTING_WORK.md, config.json, tasklist.json,
   and the latest progress record. State how a prior finding applies to this
   phase-specific task; never present pooled results as newly measured results.
2. Give each agent one task, input paths, allowed write paths, and acceptance
   criteria. Parallelize independent read-only reviews; serialize dependent
   work and all shared-file changes. One writer owns each file.
3. Data auditor reads inputs and produces audit.json and schema/provenance
   findings. Missing data produces BLOCKED, never synthetic research results.
4. Builder implements one incomplete acceptance item and runs local checks.
5. Independent evaluator checks artifacts and tests, not the builder's claims.
   A passing narrative cannot override a failing deterministic check.
6. Route exact failure IDs to builder. Maximum three repair rounds per item;
   then stop with BLOCKED and preserve evidence. No unbounded improvement loop.
7. Update tasklist.json and append progress.jsonl after each checkpoint. Record
   agent/model identity, commands, exit codes, touched files, artifact hashes,
   elapsed time, and unresolved limitations. Do not request hidden reasoning.
8. Freeze the experiment before final test. No agent sees test predictions or
   metrics until the evaluator's one final evaluation. The evaluator owns the
   final-test tool; other agents must not call it. A local sentinel is an
   accidental-rerun safeguard, not an adversarial security boundary.
9. After final test, report limitations and results; do not start optimizing
   against the exposed test. A new hypothesis needs a genuinely new holdout.

## Completion contract

Distinguish IMPLEMENTED, TESTED_SYNTHETIC, TESTED_REAL, UNSUPPORTED, BLOCKED,
and NOT_IMPLEMENTED. Unit tests do not establish real-data model validity.
Do not edit this scope, label policy, test lock, or eval assertions to obtain
a pass. Report proposed scientific policy changes separately for Leo to decide.

## Proposed stopping-reason extension

Read STOPPING_REASON_DESIGN.md before RF-14 through RF-16. Existing categorized
stopping reasons are label-only. No new NLP predictors or broader-repository
changes are authorized by this extension. Retain unknown/ambiguous reasons,
audit first-match label noise, and require per-class support. Do not claim the
binary runner supports multiclass targets yet. Study-level intervention count
is not validated active-regimen burden; explanations must express associations,
not causes. Never hard-code penalties from the earlier reason percentages.
