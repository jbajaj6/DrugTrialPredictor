# Leo / Giannis Phase-by-Phase Work

## [Open the `leo/giannis` branch →](https://github.com/jbajaj6/DrugTrialPredictor/tree/leo/giannis)

The phase-by-phase extension lives on the **`leo/giannis` branch**, in its top-level [`phase-by-phase/` folder](https://github.com/jbajaj6/DrugTrialPredictor/tree/leo/giannis/phase-by-phase). It follows exact-label candidate drug–indication programs through registered trial phases; it is separate from the original trial-level completion and endpoint analyses.

- [Project README: pipeline, current status, and future plan](https://github.com/jbajaj6/DrugTrialPredictor/blob/leo/giannis/phase-by-phase/README.md)
- [Executed full-cohort findings](https://github.com/jbajaj6/DrugTrialPredictor/blob/leo/giannis/phase-by-phase/RESULTS.md)
- [Visualizations](https://github.com/jbajaj6/DrugTrialPredictor/tree/leo/giannis/phase-by-phase/visualizations)

The full ClinicalTrials.gov cohort and cleaning pipeline have been run. The strict, time-separated Phase 3 prediction cohorts have too few independent positive examples, so the real-data models are **not estimable** yet. Raw and processed datasets remain local and Git-ignored.

This file is only a shortcut on `main`; the phase-by-phase code is on `leo/giannis` until that branch is merged.
