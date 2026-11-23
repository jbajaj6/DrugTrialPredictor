# Leo / Giannis Phase-by-Phase Work

## [Open the Leo/Giannis folder and code →](https://github.com/jbajaj6/DrugTrialPredictor/tree/agents/mkae-it-a-new-directory-and-connect-it/leo/giannis)

This extension follows exact-label candidate drug–indication programs through registered trial phases. It is separate from the repository's original trial-level completion and endpoint analyses.

- [Folder README: contents, current status, and future game plan](https://github.com/jbajaj6/DrugTrialPredictor/blob/agents/mkae-it-a-new-directory-and-connect-it/leo/giannis/README.md)
- [Phase-by-phase pipeline, schematic, data rules, and tests](https://github.com/jbajaj6/DrugTrialPredictor/blob/agents/mkae-it-a-new-directory-and-connect-it/leo/giannis/phase-by-phase/README.md)
- [Executed full-cohort findings and limitations](https://github.com/jbajaj6/DrugTrialPredictor/blob/agents/mkae-it-a-new-directory-and-connect-it/leo/giannis/phase-by-phase/RESULTS.md)
- [Visualizations](https://github.com/jbajaj6/DrugTrialPredictor/tree/agents/mkae-it-a-new-directory-and-connect-it/leo/giannis/visualizations)
- [Draft pull request #1](https://github.com/jbajaj6/DrugTrialPredictor/pull/1)

The full ClinicalTrials.gov cohort and cleaning pipeline have been run. The strict, time-separated Phase 3 prediction cohorts have too few independent positive examples, so the real-data models are **not estimable** yet. Raw and processed datasets remain local and Git-ignored.

The implementation lives on branch `agents/mkae-it-a-new-directory-and-connect-it`. This file is a shortcut on `main`; it does **not** merge the branch's code into `main`.
