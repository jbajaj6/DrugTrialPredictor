# DrugTrialPredictor

CIS 5450 (Big Data Analytics) Final Project, Fall 2026

Predicting whether a clinical drug trial will succeed, using trial design data from ClinicalTrials.gov combined with NIH grant funding data and news and public-attention ("hype") signals.

## Objective

Roughly 1 in 7 drug trials that reach a final status is terminated or withdrawn. If we can predict at registration time which trials are likely to stop early, sponsors, funders, and patients get an early risk signal.

A trial that *finishes* is not the same as a drug that *works*: most terminations happen for operational reasons like slow enrollment, not because the drug failed (Williams et al. 2015). So we model both questions separately, then ask what kind of outside signal helps:

- **Q1 (completion):** can trial design features predict whether a trial completes or is stopped?
- **Q2 (efficacy):** among completed trials with posted results, can the same features predict whether the trial met its primary endpoint? Do the important features differ from Q1?
- **Q3 (money vs. hype):** do funding and track record (NIH grants) or public attention (news, Wikipedia) improve either model beyond design features alone?

See [docs/related-work.md](docs/related-work.md) for prior work and how this project differs.

## Unit of analysis and targets

- **Row:** one interventional drug trial registered on ClinicalTrials.gov with a final status and a start date from 2005 through 2019. The 2019 cutoff avoids survivorship bias: recent trials that have already finished are disproportionately short ones.
- **Target A (Q1, binary):** `completed` = 1 if `Completed`, 0 if `Terminated` or `Withdrawn`. Ongoing trials are dropped because their outcome is unknown. Withdrawn trials (never enrolled) may be modeled separately from terminated ones.
- **Target B (Q2, binary):** `met_primary` = 1 if the primary outcome analysis reports p < 0.05, from AACT `outcome_analyses`. Only trials with posted results and a primary-outcome p-value are included. The HINT benchmark labels (Fu et al. 2022) are a fallback or cross-check.
- **Stretch:** join Drugs@FDA to label FDA approval for the subset of trials we can match to an approved product.

### Row counts

Counts from the ClinicalTrials.gov API v2 on 2026-10-27: interventional trials with at least one drug intervention, start date 2005-01-01 to 2019-12-31, before cleaning. Re-run on AACT for the final numbers.

| Group | Trials |
| --- | --- |
| Completed | 78,047 |
| Terminated | 13,329 |
| Withdrawn | 4,342 |
| **Target A pool** | **~95,700** (about 14% stopped) |
| Completed with posted results | 31,922 |
| Terminated with posted results | 6,854 |
| **Target B pool** (before requiring a primary-outcome p-value) | **~38,800** |
| Industry-sponsored, final status (hype subset pool) | 44,256 |

Target A clears the 50,000-row requirement. Target B will shrink once filtered to trials with a primary-outcome p-value.

## Data sources

All sources are free, public, and legal. None are synthetic.

| Source | What it gives us | Access |
| --- | --- | --- |
| [AACT](https://aact.ctti-clinicaltrials.org/) (ClinicalTrials.gov) | Core trial table: phase, design, sponsor, enrollment, sites, conditions, status, posted results | Free account; Postgres connection or static download |
| [NIH RePORTER / ExPORTER](https://reporter.nih.gov/exporter) | NIH grants linked to the ClinicalTrials.gov trials they support (Clinical Studies file, joined on core project number): award amount, funding institute, activity code, PI history, abstracts | Bulk CSV download; no account |
| [Drugs@FDA](https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files) | Approval records for the stretch FDA label | Bulk download |
| [GDELT 2.0](https://www.gdeltproject.org/) | Global news coverage counts and pre-computed tone per drug/sponsor over time (2015+) | Raw CSV files or Google BigQuery public dataset |
| [Wikimedia Pageviews API](https://wikimedia.org/api/rest_v1/) | Daily page views for drug, sponsor, and condition articles (mid-2015+) | Free REST API |
| [SEC EDGAR](https://www.sec.gov/edgar) (optional) | Count of 8-K filings mentioning a drug, for public-company sponsors | Free API |

## Features

**Trial design (AACT):** phase, anticipated enrollment, sponsor class (industry / NIH / academic), number of sites and countries, condition category (MeSH), allocation, masking, intervention model, number of arms, has data monitoring committee, start year, number of collaborators, biomarker-based patient selection (from eligibility text; Wong et al. 2019 found it raises success rates).

**Funding and track record (NIH RePORTER):** has NIH grant, total award amount, funding institute (NCI, NHLBI, ...), activity code (R01, U01, ...), number of linked grants, and the PI's and organization's prior grant and trial counts. These cover the academic trials that hype data mostly misses. Only grants awarded before the trial start date count.

**Hype (news / attention):** news article count and average tone in the window before trial start, Wikipedia page views for the drug and sponsor, attention trend (growth rate), and a `has_news` flag. GDELT tone is already computed, so no heavy NLP is needed.

## Leakage rules

Every feature must be knowable at or before trial start:

- Use **anticipated** enrollment, not actual. AACT overwrites `enrollment` with the actual count when a trial ends (withdrawn trials become 0), so the original anticipated value has to come from ClinicalTrials.gov record history, or the feature is dropped.
- Site and country counts can change after a trial starts. Treat them with care and test the models with and without them.
- Exclude `why_stopped`, posted results, completion dates, and anything updated after the outcome, except when building labels.
- Grant and hype features are measured only in a fixed window **before** the trial's start date. Coverage after a termination is announced would leak the answer.

## Planned pipeline

1. **Ingest:** pull AACT tables (`studies`, `designs`, `sponsors`, `facilities`, `conditions`, `interventions`, `eligibilities`, `outcomes`, `outcome_analyses`) and the NIH ExPORTER projects and clinical studies files; save snapshots locally.
2. **Wrangle and join:** build one row per trial with SQL joins and aggregations. Join NIH grants on NCT ID through the clinical studies link. Normalize drug names (regex) to match against GDELT, Wikipedia, and Drugs@FDA.
3. **Hype join:** for each trial, aggregate news and page-view metrics over the pre-start window.
4. **EDA:** termination rate by phase, sponsor type, disease area, and year; funding and hype distributions; each against outcome.
5. **Modeling:** a phase + disease-area baseline, then logistic regression, then tree ensembles (random forest, gradient boosting). Handle class imbalance with class weights. Report ROC-AUC, PR-AUC, and F1. Ablation: design only vs. design + funding vs. design + hype vs. all.
6. **Hypothesis tests (permutation):**
   - H1: termination rate differs between industry and academic sponsors.
   - H2: high-hype trials have a different success rate than low-hype trials (within the industry subset, to avoid confounding).
   - H3: NIH-funded trials have a different completion rate than comparable academic trials without NIH funding.

## Anticipated challenges

- **Sparse hype coverage.** Most academic trials get zero news. Hype features will mostly matter for industry trials of named drugs, so we will report results on that subset and include a `has_news` flag.
- **Funding coverage.** NIH grant links cover academic and NIH-supported trials, not industry trials. Funding features apply to that subset, with a `has_nih_grant` flag.
- **Entity matching.** Drug names vary (brand vs. generic vs. code names like `ABC-123`). Matching across sources needs regex cleanup and alias tables.
- **Termination isn't always failure.** Many trials stop for business or enrollment reasons, which is why Target B exists.
- **Anticipated enrollment.** AACT keeps only the final value; recovering the original may require record history for a sample.
- **Class imbalance.** About 86% of trials complete.
- **Time coverage.** GDELT and Wikipedia pageviews start around 2015, so hype features only exist for 2015–2019 trials.

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
| TBD | Funding (NIH RePORTER) and hype data (GDELT, Wikipedia), entity matching |
| TBD | EDA and hypothesis testing |
| TBD | Modeling and evaluation |
