# Related work

Prior research on predicting clinical trial and drug outcomes, and where this project fits. Compiled 2026-10-27 from quick searches, not a systematic review, so treat the "gap" claim as "to our knowledge."

## Predicting trial termination

**Elkin & Zhu (2021), "Predictive modeling of clinical trial terminations using feature engineering and embedding learning," *Scientific Reports*.** [PMC7876037](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7876037/)

- About 69,000 ClinicalTrials.gov trials, 640 engineered features including text embeddings of eligibility criteria.
- Over 0.73 ROC-AUC and about 67% balanced accuracy for completed vs. terminated.
- Eligibility criteria and sponsor type were among the most informative features.
- **Our Q1 benchmark.** A design-feature model near 0.70 AUC is in line with published work.

**Williams et al. (2015), "Terminated trials in the ClinicalTrials.gov results database," *PLOS ONE*.** [PMC4444136](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4444136/)

- Of 905 terminated trials with posted results, 68% stopped for reasons unrelated to the trial's data, mostly insufficient accrual (57% of those).
- Only 21% stopped for efficacy or toxicity.
- **Justifies separating Target A (completion) from Target B (efficacy).**

## Predicting drug approval and phase success

**Lo, Siah & Wong (2019), "Machine learning with statistical imputation for predicting drug approvals," *Harvard Data Science Review*.** [Summary](https://cancerx.mit.edu/machine-learning-with-statistical-imputation-for-predicting-drug-approvals)

- 0.78 AUC (Phase 2 → approval) and 0.81 (Phase 3 → approval), on proprietary Informa data from 2003–2015.
- Strongest predictors included trial outcome, trial status, accrual rate, duration, prior approval for another indication, and sponsor track record.
- Statistical imputation beat dropping incomplete rows.
- **Motivates the track-record features in our NIH funding group.**

**Wong, Siah & Lo (2019), "Estimation of clinical trial success rates and related parameters," *Biostatistics* 20(2).** [PubMed](https://pubmed.ncbi.nlm.nih.gov/29394327/) · [Corrigendum](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6409416/)

- Traced phase transitions for about 21,000 compounds from 2000–2015.
- Oncology Phase 1 → approval success was 3.4%. Trials using biomarkers for patient selection succeeded more often.
- Use the corrected tables from the corrigendum when citing phase-transition rates.
- **Motivates the biomarker feature and the phase + disease-area baseline.**

## Deep-learning trial outcome prediction and benchmarks

**Fu et al. (2022), "HINT: Hierarchical Interaction Network for clinical trial outcome prediction," *Patterns* 3(4).** [arXiv 2102.04252](https://ar5iv.labs.arxiv.org/html/2102.04252) · [Code and data](https://github.com/futianfan/clinical-trial-outcome-prediction)

- Graph model over drug molecules, diseases, and eligibility criteria.
- F1 of 0.665 / 0.620 / 0.847 for Phase 1 / 2 / 3 on about 9,000 trials.
- **Public labels are a fallback or cross-check for Target B.**

**Gao et al. (2024), "Automatically labeling clinical trial outcomes: a large-scale benchmark for drug development" (CTO).** [arXiv 2406.10292](https://arxiv.org/abs/2406.10292v3)

- Weakly supervised success/failure labels for about 125,000 trials, built from LLM reading of publications, phase progression, news sentiment, and sponsor stock prices.
- About 91 F1 against expert annotations across phases.
- **Key distinction:** CTO uses news written *after* results to *build labels*. We use attention *before* trial start as a *predictor*, which is a different question with strict leakage rules.

## News, attention, and biotech

**Event study of news and biopharma stock prices.** [PMC10817120](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10817120/)

- Drug-development setbacks produce significant negative returns; trial news shows signs of leakage over longer windows.
- Measures market reaction *after* news, not whether prior attention predicts outcomes.

No peer-reviewed study was found that tests whether pre-trial news coverage or Wikipedia attention predicts trial outcomes.

## Grant data

**NIH RePORTER / ExPORTER.** [ExPORTER](https://reporter.nih.gov/exporter) · [Clinical studies link](https://support.analytics.nih.gov/hc/en-us/articles/16841007309083)

- Bulk CSVs of funded NIH projects, abstracts, publications, and a clinical studies file linking grants to ClinicalTrials.gov trials by core project number.
- Covers only funded grants, so it cannot be used to predict grant success. It works as a feature source for trials.

Datasets with both funded and rejected proposals exist but are too small or restricted for this project: the University of Melbourne Kaggle grants data (2005–2008, via R [`modeldata::grants`](https://modeldata.tidymodels.org/reference/grants.html)), ERC proposal studies ([Seeber et al. 2022](https://ideas.repec.org/a/eee/tefoso/v184y2022ics0040162522005303.html)), and the FIND NSF awards database ([arXiv 2510.10336](https://arxiv.org/html/2510.10336v1)).

## Where this project fits

1. **Two targets, compared.** Most work predicts either termination or approval. We model completion and efficacy on the same trials and compare which features matter for each.
2. **Pre-start attention as a predictor.** To our knowledge, no prior study tests whether news and Wikipedia attention *before* trial start predicts outcomes.
3. **Funding vs. hype.** NIH grant features (money, institute, PI track record) cover academic trials, and hype covers industry trials. The ablation asks which outside signal adds more beyond design features.
4. **Free, reproducible data.** Unlike Lo et al. (proprietary Informa data), every source here is public.
