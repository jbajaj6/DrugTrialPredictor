# Project Proposal: DrugTrialPredictor

CIS 5450, Fall 2026. Due Oct 30, 11:59 PM EST on Gradescope. One person submits and adds all teammates, and must re-add them after every resubmission.

## 1. Group members and duties

| Member | Duties |
| --- | --- |
| Jai Bajaj | AACT ingestion, SQL joins, building one row per trial, cleaning |
| Leo Susser | NIH RePORTER funding features; Target B (primary endpoint) labels |
| Giannis Bitounis | Hype data (GDELT news, Wikipedia pageviews), drug-name matching with regex |
| Samuel Sosa Sanchez | EDA, hypothesis tests, modeling and evaluation |

Everyone helps with the final notebook and presentation.

## 2. Data source

- **Primary: AACT**, a free public relational copy of ClinicalTrials.gov maintained by CTTI (Duke/FDA). One row per interventional drug trial with a final status and a start date from 2005 through 2019.
  - **Size:** about 95,700 trials (78,047 completed, 13,329 terminated, 4,342 withdrawn; ClinicalTrials.gov API, 10/27). This is well above 50,000 after cleaning.
  - **Features (15+):** phase, anticipated enrollment, sponsor class, number of sites and countries, condition category (MeSH), allocation, masking, intervention model, number of arms, data monitoring committee, start year, number of collaborators.
- **Joined sources (all free and public):**
  - NIH RePORTER: grants linked to trials by NCT ID.
  - GDELT 2.0: news volume and tone.
  - Wikimedia Pageviews: public attention.
  - Drugs@FDA: approvals, as a stretch goal.
- No synthetic data and no Kaggle data. All data is structured; GDELT tone comes pre-computed, so no NLP is needed.

## 3. Objective and value proposition

Roughly 1 in 7 drug trials is stopped early, after sponsors have spent years and millions of dollars and patients have enrolled. We want to know whether a trial's outcome can be predicted **at the moment it is registered**, and whether outside signals add anything beyond the trial's design:

- **Money:** NIH funding and the investigator's track record.
- **Hype:** news coverage and Wikipedia attention.

The result is an early risk score that funders, investors, and patients could use. It also tests whether hype around a drug is real signal or just noise.

## 4. Modeling plan

Both targets are **binary classification**.

- **Target A (main):** completed vs. terminated or withdrawn, on the full ~95.7k trials.
- **Target B (secondary):** among completed trials with posted results, whether the primary endpoint was met (p < 0.05).
  - This separates "the trial finished" from "the drug worked."
  - The pool is about 38,800 before filtering to trials that report a primary p-value.

**Models:**
- A majority-class / phase-only baseline.
- Logistic regression (regularized).
- Random forest and gradient boosting, with class weights for the 86/14 imbalance.

**Evaluation:**
- ROC-AUC, PR-AUC, and F1 on a time-based split: train on early start years, test on later ones.
- **Ablation:** design-only vs. + funding vs. + hype, to measure what each signal adds.
- **Leakage rule:** every feature must be knowable at trial start. That means anticipated (not actual) enrollment, and news and grants only from before the start date.

## 5. Hypothesis testing

All three tests are permutation tests, using simulation as covered in class: shuffle group labels 10,000 times to build the null distribution and compute a two-sided p-value.

- **H1 (sponsor type).**
  - H0: completion rate is the same for industry-sponsored and academic-sponsored trials.
  - Test statistic: difference in completion rates.
- **H2 (hype).** Run within industry trials that started in 2015–2019, the years where hype data exists.
  - H0: completion rate is the same for trials in the top quartile of pre-start news volume and trials in the bottom quartile.
  - Test statistic: difference in completion rates.
- **H3 (funding).**
  - H0: among academic trials, completion rate is the same with and without a linked NIH grant.
  - Test statistic: difference in completion rates.

## 6. Anticipated obstacles

- **Entity matching.** Drug names come as brand, generic, and code names (e.g. "ABC-123"), so matching to news, Wikipedia, and FDA records needs regex cleanup and alias tables.
- **Sparse coverage.**
  - Hype data only exists from 2015 on and mostly covers industry trials.
  - NIH grants mostly cover academic trials.
  - We will use `has_news` / `has_nih_grant` flags and report subset results.
- **Leakage.** AACT overwrites anticipated enrollment with actual enrollment when a trial ends, so the original value has to come from record history, or the feature is dropped.
- **Label noise.** Many terminations are for business or enrollment reasons rather than drug failure, which is why Target B exists.
- **Class imbalance.** About 86% of trials complete.
- **Stretch: AI science features.** Embeddings and an LLM reading of trial text and PubMed abstracts. This is extra NLP, so we treat it as optional and will confirm the scope with our TA.
