# Predicting Drug Trial Outcomes at Registration: Final Report

Jai Bajaj, Leo Susser, Giannis Bitounis, Samuel Sosa Sanchez

Code and full analysis: [`notebooks/drug_trial_predictor.ipynb`](../notebooks/drug_trial_predictor.ipynb). Setup and pipeline: [README](../README.md).

## Summary

On the day a drug trial is registered, can we tell whether it will finish, and whether it will work? We built one row per trial for 73,842 interventional drug trials on ClinicalTrials.gov that started between 2005 and 2019. We trained on trials that started through 2015 and tested on trials that started 2016–2019.

- **Completion (Q1)** is moderately predictable: ROC-AUC 0.68 for the tuned tree models, against 0.62 for a phase-and-disease lookup.
- **Meeting the primary endpoint (Q2)** reaches ROC-AUC ≈ 0.73 on the 9,030 completed trials that posted a p-value.
- **The sponsor's own track record** is the only outside signal that clearly helps (+0.025 ROC-AUC for Q1, 95% CI +0.021 to +0.030). It helps predict whether a sponsor finishes its trials, but not whether its drugs work.
- **Funding, public attention and prior science add nothing measurable.** NIH grants, Wikipedia views, GDELT news, PubMed literature, ChEMBL mechanisms and prior FDA approval all fail a paired bootstrap test.

## 1. Motivation and questions

About one in five trials in our cohort is terminated or withdrawn, after money has been spent and patients enrolled. An early risk score would let funders, sponsors and review boards look harder at the riskiest trials before they start.

Finishing and working are different outcomes. Most trials stop over enrollment or business problems, not because the drug failed. So we model them separately:

- **Q1 (completion):** does the trial finish (Completed) or stop (Terminated or Withdrawn)?
- **Q2 (efficacy):** among completed trials with posted results, was the smallest primary-outcome p-value below 0.05?
- **Q3 (money vs. hype):** do NIH funding or public attention improve either model beyond trial design?
- **Q4 (science):** does what was known about the drug before the trial (literature, mechanism, prior approval, the trial's own description) add signal?
- **Stretch:** do our labels track later FDA approval?

## 2. Data

| Source | What it contributes | Join key |
| --- | --- | --- |
| AACT (ClinicalTrials.gov, Postgres) | Design, sponsor, eligibility, conditions (MeSH), planned outcomes, status, posted p-values; 13 tables aggregated to one row per trial | NCT ID |
| AACT, all interventional trials (~460k) | Sponsor track record | Sponsor name, dates |
| NIH ExPORTER + RePORTER | Grants linked to trials: amount, activity code, institute, grant-years | NCT ID → core project number |
| Wikimedia Pageviews | Monthly views of the drug's Wikipedia article (mid-2015 onward) | Cleaned drug name |
| GDELT 2.0 (BigQuery) | News article counts and tone per drug (2015 onward) | Drug name in article URL |
| PubMed, ChEMBL, Drugs@FDA | Prior papers, mechanism and target, prior and later FDA approval | Cleaned drug name |
| ClinicalTrials.gov API | Titles and summaries, embedded with PubMedBERT | NCT ID |

The hardest join is entity linking. Intervention fields mix brand, generic and code names with free-text arm descriptions. We strip dose, route, salt and formulation words with regular expressions and keep only names that exist in ChEMBL or Drugs@FDA. Without that filter, words like "local" and "impact" matched thousands of unrelated news URLs.

**Cohort.** Trials with a final status and a start date in 2005–2019, registered no more than 90 days after starting. About 15% of completed trials were registered over a year late, often after they had finished, vs. 3% of withdrawn ones. Keeping them would let a model learn the outcome from the registration date.

| | Trials | Stopped |
| --- | --- | --- |
| Q1 cohort | 73,842 | 20.7% |
| Q2 cohort (completed, primary p-value posted) | 9,030 | — |

## 3. Leakage

Every feature has to be knowable at registration. Three features looked predictive and turned out to encode the outcome:

1. **Late registration** (handled by the cohort rule above).
2. **Site and country counts.** 34% of withdrawn trials list zero sites, vs. 4–7% of the rest, because sites are removed after cancellation. Adding them inflates ROC-AUC by about 0.04. We report this only as a leakage check.
3. **Registration lag of withdrawn trials.** Their planned start dates are pushed back before cancellation, so the lag records later postponements.

Other rules: no actual enrollment (AACT overwrites the planned value), no `why_stopped`, results or completion dates. Sponsor history counts only trials that started or ended before this one. Grant, attention and science features use only information dated before the start.

## 4. Exploratory findings

- **Why trials stop.** Bucketing the free-text reason: enrollment problems ≈34%, business decisions ≈18%, efficacy ≈6%, safety ≈4%. "Terminated" mostly means the trial could not be run.
- **Phase and disease.** Phase 1 trials stop least (≈15%); Phase 2 and Phase 1/2 most (≈25–30%). Oncology stops most often (≈29%). The two compound: early-phase oncology trials stop ≈35% of the time, vs. ≈7–9% for Phase 1 trials outside cancer.
- **Sponsor.** Industry trials stop less than academic ones (≈16% vs ≈25%) in every year. Trials from sponsors in the worst track-record quintile stop 2.6× as often as the best (≈33% vs ≈13%).
- **Censoring.** Stop rates climb from ≈20% to ≈26% across 2016–2019, partly because long trials that are still running aren't in the data yet. The test years therefore have a higher base rate than the training years. This does not affect ROC-AUC, but it would affect calibrated probabilities.
- **No single strong feature.** Every feature has |ρ| < 0.2 with completion, which favors models that combine many weak signals.

## 5. Hypothesis tests

Two-sided permutation tests, 10,000 shuffles each (p ≈ 1e-4 is the smallest reportable value).

| Hypothesis | Result | p |
| --- | --- | --- |
| H1: industry vs. academic completion | Industry +9 points | ≈ 1e-4 |
| H2: high vs. low hype (Wikipedia; GDELT) | +1.6 points; −0.5 points | 0.44; 0.85 |
| H3: academic trials with vs. without an NIH grant | Funded +4 points | ≈ 1e-4 |
| H4: best vs. worst sponsor track-record quartile | Large gap in favor of the best | ≈ 1e-4 |
| H5: most- vs. least-studied drugs meeting their endpoint | Most-studied **−19 points** | ≈ 1e-4 |

H5 is mostly confounding. The most-studied quartile is dominated by old, already-approved drugs (83% vs 8%) tested by academic sponsors in new uses. The least-studied quartile is new industry compounds in later phases. All of these are associations, not causal effects.

## 6. Modeling

**Setup.** Time split: train 2005–2015, test 2016–2019. Pre-processing lives inside a scikit-learn pipeline fit on training trials only: median imputation with missing-value flags, clipping to training 1st/99th percentiles, one-hot encoding with rare levels grouped, standardization, and dropping one near-duplicate feature (ρ = 0.98). For class imbalance we compared no adjustment, class weights, under/oversampling and SMOTE on a 2013–2015 validation split. Class weights gave the best stopped-class F1 (0.41 vs 0.04 unadjusted) without discarding or inventing trials. Models: regularized logistic regression, random forest and histogram gradient boosting, each tuned with a randomized search on the validation split.

**Ablation (best model per row, test ROC-AUC).**

| Features | Q1 | Q2 |
| --- | --- | --- |
| Phase + disease-area baseline | 0.62 | 0.64 |
| Design | 0.66 | 0.73 |
| Design + sponsor track record | **0.68** | 0.73 |
| + NIH funding | 0.68 | 0.73 |
| + science (PubMed, ChEMBL, Drugs@FDA) | 0.68 | 0.73 |
| + text embeddings | 0.69 | 0.73 |
| All of the above | 0.69 | 0.73 |
| Hype split (train 2016–17, test 2018–19): + Wikipedia + GDELT | 0.69 → 0.69 | — |

**Tuned models (design + sponsor track record), 95% bootstrap intervals.**

| Model | Q1 | Q2 |
| --- | --- | --- |
| Logistic regression | 0.659 [0.651–0.667] | 0.711 [0.690–0.731] |
| Random forest | 0.681 [0.673–0.689] | 0.725 [0.705–0.746] |
| Gradient boosting | 0.681 [0.673–0.689] | 0.719 [0.698–0.739] |

Tuning moved test ROC-AUC by under 0.005, except Q2 gradient boosting (+0.011). The train-vs-validation curves show why. Deeper forests and longer boosting only memorize the training years, while logistic regression is underfit but gains nothing from less regularization. The ceiling comes from the features, not the model settings. Random forest and gradient boosting are statistically tied for Q1, and both beat logistic regression.

**What drives the predictions.** Permutation importance and logistic coefficients agree. Completion odds go down with the sponsor's past stop rate, academic sponsorship, combination-phase designs (1/2, 2/3), and oncology and cardiovascular trials. They go up for healthy-volunteer studies, Phase 1 and Phase 3, industry sponsors and crossover designs. The model ranks risk best for Phase 1 (AUC ≈ 0.74) and worst for Phases 2–3 (≈ 0.61–0.64), where whether the drug works starts to matter.

**Paired bootstrap of each gain (1,000 resamples of the same test trials).** Only the sponsor track record is a clear gain for Q1 (+0.025, CI +0.021 to +0.030). Funding, hype and science intervals sit at or below zero. Text embeddings for Q2 are borderline: +0.012, CI −0.004 to +0.029.

**Stretch: FDA approval.** Of 39,868 trials testing a named drug not yet approved at the start, 8.4% were followed by an FDA approval of that drug. In Phase 3, completed trials' drugs were approved twice as often as stopped ones (15.4% vs 7.5%). Trials that met their primary endpoint were followed by approval 20.5% of the time, vs 8.9% for those that missed. Both labels track the outcome that ultimately matters, and Q2 tracks it more closely.

## 7. Conclusions

1. **Completion is moderately predictable at registration** from design and sponsor alone (ROC-AUC 0.68). Tree models beat an additive model because risk depends on interactions such as phase within disease area.
2. **Who runs the trial matters most.** A sponsor's history of stopping trials is the strongest single signal for completion. It carries no information about efficacy.
3. **Money, hype and prior science don't add predictive power.** Funded trials do complete more often (H3), but that is already explained by who runs the trial and how it is designed. Public attention to a drug carries no signal about whether its trial will finish.
4. **Finishing and working are different problems.** Most stops are operational, so the features that predict completion differ from those that predict efficacy.

**For stakeholders.** Funders and review boards can treat a poor sponsor track record, early-phase oncology and combination-phase designs as the clearest red flags available at registration, and look harder at enrollment plans. For ranking trials by risk, use the random forest. For explaining risk, the logistic model gives signed effects at a cost of ≈ 0.02 ROC-AUC.

## 8. Limitations

- **Planned enrollment is missing.** It is likely the strongest predictor, but AACT keeps only the final count, and ClinicalTrials.gov's record-history endpoint is not public (HTTP 403).
- **Latest versions only.** Summaries, planned outcomes and eligibility text can be edited after registration.
- **The Q2 label is crude.** A primary p < 0.05 ignores non-inferiority designs and multiple testing.
- **Name matching covers part of the cohort.** ≈59% of trials match PubMed and ≈44% match ChEMBL. GDELT matching uses article URLs, not full text.
- **Censoring** shifts the base rate in the test years.
- **The planned LLM reading of each trial** (plausibility, surrogate vs. clinical endpoint) was not run because it needs a paid API. Local PubMedBERT embeddings stand in for it.

## 9. Future work

- Recover planned enrollment for a sample of trials from archived record versions.
- Model withdrawn and terminated trials separately; their causes differ.
- Calibrate probabilities for the higher test-year stop rate.
- Run an LLM extraction on a sample of trials, with a check for whether the model already knows the outcome.
- Add site-level features known at registration, such as each site's own past stop rate.

## References

- Williams, R. J., et al. (2015). Terminated trials in the ClinicalTrials.gov results database. *PLOS ONE*.
- Wong, C. H., Siah, K. W., & Lo, A. W. (2019). Estimation of clinical trial success rates and related parameters. *Biostatistics*, 20(2).
- Fu, T., et al. (2022). HINT: Hierarchical interaction network for clinical trial outcome prediction. *Patterns*, 3(4).
- See [related-work.md](related-work.md) for the full list.
