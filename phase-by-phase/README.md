# Phase-by-Phase Drug Development Prediction

This project extension reorganizes clinical-trial data around a longitudinal
**drug-indication program** rather than treating every registered trial as an
independent observation.

## Research question

> Given the information available at a specific point in development, how far
> will a drug-indication program progress, and how does that prediction change
> after Phase 1 and Phase 2 evidence becomes available?

## Unit of analysis

The primary entity is a drug-indication program:

```text
program_id = normalized drug + normalized indication
```

A drug studied for two indications is represented by two programs. A program
may contain multiple trials within the same phase.

## Prediction checkpoints

1. **Baseline:** information available before Phase 1 begins.
2. **After Phase 1:** baseline information plus Phase 1 design, status, timing,
   enrollment, safety, and available results.
3. **After Phase 2:** all earlier information plus equivalent Phase 2 evidence.

Every feature must have been observable by its checkpoint date. Later-phase
information must never be included in an earlier prediction.

## Primary outcome

The initial primary outcome is whether a program eventually reaches Phase 3.
Secondary outcomes include:

- Reaching Phase 2
- Receiving FDA approval
- Highest phase reached
- Time to the next phase
- Apparent discontinuation

Programs without enough follow-up will be marked as censored rather than
automatically labeled as failures.

## Planned data products

The pipeline will produce four connected tables:

1. **Trials:** one row per ClinicalTrials.gov study.
2. **Programs:** one row per drug-indication program with final outcomes.
3. **Phase history:** one row per program and clinical phase.
4. **Snapshots:** one model-ready row per program and prediction checkpoint.

## Initial modeling plan

- Begin with interpretable logistic-regression baselines.
- Split data chronologically and keep all rows from a program in one split.
- Compare baseline predictions with predictions updated after Phase 1.
- Report discrimination, calibration, Brier score, log loss, and bootstrap
  uncertainty intervals.
- Report odds ratios, confidence intervals, and corrected p-values for
  prespecified explanatory features.

## Proposed structure

```text
phase-by-phase/
├── README.md
├── config/
├── notebooks/
├── outputs/
├── src/
└── tests/
```

The next step is to audit the existing data pipeline, count usable programs at
each checkpoint, and document the cleaning rules before training a model.
