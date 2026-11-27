# Phase 3 endpoint review gate (development data only)

This is a scientific critique and review specification, **not an implemented efficacy label or model**. It uses the sealed-holdout-safe B19 development audit. Do not treat B17's reason codes as clinical truth: the older grader treated any populated `non_inferiority_type`, including `SUPERIORITY`, as non-inferiority review. B19 preserves the actual enum and nullable tested flag separately without changing B17 labels.

## What the source can establish

Anamnesis supplies a dated trial-result version and structured primary outcome, group, measurement, analysis, arm, and analysis-group records. Exact joins require `(nct_id, nct_version, outcome_ord)` plus each child ordinal/group ID. A reported p-value is evidence of a statistical test, **not** evidence that treatment helped, that the test was superiority, or that its endpoint was clinically important. Multiple primary endpoints, multiple analyses, one-group analyses, non-inferiority/equivalence, and missing comparator roles prevent a simple `p<.05` → “drug worked” rule.

B19 has 8,414 selected trial versions and 15,295 primary outcomes. Of those outcomes, 5,656 have a parsed p-value and 1,713 have an explicit two-group role contrast; the cumulative structural availability funnel reaches 1,417 *before* multiplicity, analysis-type, endpoint-direction, and clinical-review gates. The deliberately rare-case-enriched 120-trial sample includes 35 single-primary trials, only five with both a parsed p and explicit role contrast, and only one of those with exactly one `SUPERIORITY` enum analysis. These are **not representative prevalence estimates** or sufficient support for precision/AUC claims.

## Examples that make a blanket rule unsafe

- `NCT00541385` version 7: the `<.0001` p-value is attached to a one-group analysis, while a two-group analysis reports `.3728` and is tagged `NON_INFERIORITY`. Choosing the smallest p would attach the wrong claim to the comparison.
- `NCT01151410` version 12: p=`.0040` belongs to a combined non-inferiority/equivalence analysis. It cannot be read as superiority without the margin, confidence interval, and estimand.
- `NCT00122980` version 16: two primary endpoints and arm/group labels that do not biject; picking one endpoint or assigning a comparator by position would be arbitrary.
- `NCT02686138` version 6: response counts 107 versus 71 and p<`.001` under `SUPERIORITY` are promising *review candidates*, but the response definition, denominator, clinical direction, and comparison still need sign-off. This is not an accepted “worked” label.
- `NCT00440310` version 30: descriptive overall-survival day values lack a corresponding analysis. An unfavorable difference without a p-value is not a statistically established negative outcome.

## Gate before new label/model work

1. Freeze a rulebook on development data: exact-version/date guards; a declared primary endpoint and analysis; explicit two-group analysis IDs; an explicit experimental versus active/placebo comparator; finite p-value interval/qualifier semantics; and conservative abstention on ambiguity. Do **not** infer favorable direction from a number, parameter type, or unit alone. A preapproved endpoint-family whitelist must state the clinically favorable direction and exceptions.
2. Obtain independent, blinded clinical review of an enriched candidate-positive **and** random-negative development sample. Reviewers record endpoint definition, treatment/comparator identity, analysis type, multiplicity, direction, effect magnitude, and a reasoned category: reported favorable superiority; benefit not demonstrated under an assessable test; non-inferiority; equivalence; indeterminate; or non-efficacy endpoint. Resolve disagreements explicitly. The model target, if any, should be called **reported statistically favorable superiority**, not FDA approval or clinical benefit.
3. Before scaling, report coverage, abstention, false-positive error types, inter-rater agreement, and positive predictive value with interval by endpoint family, era, comparator/mapping state, multiplicity, analysis enum, and p qualifier. Compare proposed rule, B17, and simple p<.05 proxy on the *same* adjudicated records. If class support is still too small, report **not estimable** and retain completion as a separate target.
4. Historical earlier-phase evidence may become a feature only when its result version was publicly available at the later checkpoint (or in the separately labeled sponsor-knowledge scenario). Later Phase 3 result rows create labels only. Keep 2024+ final outcomes sealed until source, split, rulebook, features, and tuning are frozen.

No NLP/LLM-generated labels are training truth in this structured stage. A future text analysis may assist reviewer triage, but it cannot silently replace these checks.
