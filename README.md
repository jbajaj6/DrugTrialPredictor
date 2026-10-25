# DrugTrialPredictor

CIS 5450 (Big Data Analytics) Final Project, Fall 2026

Predicting whether a clinical drug trial will succeed, using trial design data from ClinicalTrials.gov combined with news and public-attention ("hype") signals.

## Objective

Every year thousands of drug trials are started and a large share never finish. If we can predict at registration time which trials are likely to be terminated or withdrawn, sponsors, investors, and patients get an early risk signal.

Second question: **does hype predict success?** Do trials that get lots of news coverage and public attention succeed more often, or is hype noise (or even a warning sign)?

## Unit of analysis and target

- **Row:** one interventional drug trial registered on ClinicalTrials.gov with a final status.
- **Target (binary):** `success` = 1 if `Completed`, 0 if `Terminated` or `Withdrawn`. Ongoing trials are dropped because their outcome is unknown.
- **Secondary target:** a stricter "efficacy/safety failure" label built from `why_stopped`, which separates trials that failed on the science from ones that ended over funding or slow enrollment.
- **Stretch:** join Drugs@FDA to label FDA approval for the subset of trials we can match to an approved product.

> The proposal must confirm 50,000+ rows remain after cleaning. Run the count query on AACT before submitting.

## Data sources

All sources are free, public, and legal. None are synthetic.

| Source | What it gives us | Access |
| --- | --- | --- |
| [AACT](https://aact.ctti-clinicaltrials.org/) (ClinicalTrials.gov) | Core trial table: phase, design, sponsor, enrollment, sites, conditions, status | Free account; Postgres connection or static download |
| [Drugs@FDA](https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files) | Approval records for the stretch FDA label | Bulk download |
| [GDELT 2.0](https://www.gdeltproject.org/) | Global news coverage counts and pre-computed tone per drug/sponsor over time (2015+) | Raw CSV files or Google BigQuery public dataset |
| [Wikimedia Pageviews API](https://wikimedia.org/api/rest_v1/) | Daily page views for drug, sponsor, and condition articles (mid-2015+) | Free REST API |
| [SEC EDGAR](https://www.sec.gov/edgar) (optional) | Count of 8-K filings mentioning a drug, for public-company sponsors | Free API |

## Features

**Trial design (AACT):** phase, anticipated enrollment, sponsor class (industry / NIH / academic), number of sites and countries, condition category (MeSH), allocation, masking, intervention model, number of arms, has data monitoring committee, start year, number of collaborators.

**Hype (news / attention):** news article count and average tone in the window before trial start, Wikipedia page views for the drug and sponsor, attention trend (growth rate), and a `has_news` flag. GDELT tone is already computed, so no heavy NLP is needed.

## Leakage rules

Every feature must be knowable at or before trial start:

- Use **anticipated** enrollment, not actual.
- Exclude `why_stopped`, posted results, completion dates, and anything updated after the outcome (except when building the secondary label).
- Hype features are measured only in a fixed window **before** the trial's start date. Coverage after a termination is announced would leak the answer.

## Planned pipeline

1. **Ingest:** pull AACT tables (`studies`, `designs`, `sponsors`, `facilities`, `conditions`, `interventions`) and save a snapshot locally.
2. **Wrangle and join:** build one row per trial with SQL joins and aggregations. Normalize drug names (regex) to match against GDELT, Wikipedia, and Drugs@FDA.
3. **Hype join:** for each trial, aggregate news and page-view metrics over the pre-start window.
4. **EDA:** termination rate by phase, sponsor type, disease area, and year; hype distributions; hype vs. outcome.
5. **Modeling:** logistic regression baseline, then tree ensembles (random forest, gradient boosting). Handle class imbalance with class weights. Report ROC-AUC, PR-AUC, and F1. Ablation: design-only model vs. design + hype.
6. **Hypothesis tests (permutation):**
   - H1: termination rate differs between industry and academic sponsors.
   - H2: high-hype trials have a different success rate than low-hype trials (within the industry subset, to avoid confounding).

## Anticipated challenges

- **Sparse hype coverage.** Most academic trials get zero news. Hype features will mostly matter for industry trials of named drugs, so we will report results on that subset and include a `has_news` flag.
- **Entity matching.** Drug names vary (brand vs. generic vs. code names like `ABC-123`). Matching across sources needs regex cleanup and alias tables.
- **Termination isn't always failure.** Many trials stop for business reasons, so the secondary label matters.
- **Class imbalance.** Most trials complete.
- **Time coverage.** GDELT and Wikipedia pageviews start around 2015, so hype features only exist for recent trials.

## Milestones

| Milestone | Date |
| --- | --- |
| Proposal | Oct 30 |
| Proposal check-in | Nov 2–6 |
| Intermediate check-in (EDA + baseline done) | Nov 16–20 |
| Final notebook, presentation, concept notebook | Dec 7 |

## Team

| Member | Responsibilities |
| --- | --- |
| TBD | Data ingestion (AACT) and joins |
| TBD | Hype data (GDELT, Wikipedia) and entity matching |
| TBD | EDA and hypothesis testing |
| TBD | Modeling and evaluation |
