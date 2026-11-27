# Structured clinical-trial implementation

Use this skill for the phase-by-phase structured-data pipeline. Read the local `AGENTS.md` and `harness/EXECUTION_RULES.md` first. The task specification is phase-specific completion and reported primary statistical significance, comparing design-only to design plus already-public earlier-phase evidence on identical later trials. Advancement is separate and must retain its own censoring and linkage logic.

Resume from `harness/CURRENT_STATE.md` using `harness/RECOVERY_POLICY.md`. Fix local engineering failures without rebuilding valid data; distinguish scientific changes and non-estimable questions from code defects. Update only affected dependencies and state at meaningful checkpoints; evidence and independent evaluation remain required.

Implement child tables for arms, participant flow, outcomes, analyses, and adverse events. Preserve raw values, arm/outcome IDs, units, denominators, p-value qualifiers, and source dates. A count of events is not a count of affected people; never sum overlapping adverse-event categories. Any ambiguous treatment-to-comparator mapping remains unknown. Exact-label program links are candidate identities, not clinical verification.

Run focused synthetic tests first, then replay real source data and inspect artifacts. Maintain a leakage firewall: final holdout labels are not available to builders during model development. Validation is for prespecified selection; the final test may be evaluated once after freezing code, inputs, and settings. Report unsupported tasks explicitly. Keep the README aligned to executed commands and observed results.
