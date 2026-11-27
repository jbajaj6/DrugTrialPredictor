# B19 independent evaluation — 2026-11-27

Verdict: **PASS_REAL_DATA_CHECKS for the audit and deterministic sample only.** This is not acceptance of an efficacy label, drug-identity link, or predictive model.

The independent evaluator inspected the B19 implementation, pinned B17 inputs, and the complete B19 replay without editing them. Its read-only checks were:

```bash
cd phase-by-phase
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_audit_b19.py
# 55 passed
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
# 309 passed; 5 existing DuckDB deprecation warnings
python3 harness/check.py
# PASS
GIT_CONFIG_GLOBAL=/dev/null git diff --check
# exit 0
```

The evaluator independently rehashed B19 outputs and code, B17 manifest, all eight B17 output files, and B17 report; every digest matched. There are **8,414 unique selected trial/version keys**, **15,295 unique primary-outcome keys**, and **120 unique sampled trial keys**. Sample keys are within the selected universe. Maximum selected trial/outcome publication date is **2023-12-29**; maximum sampled date is **2023-12-28**; there are no 2024+ dates. Every row retains `direction_state=unknown_not_assessed`.

B17 primary keys exactly match B19. The independent source projection has **10,795 primary analyses**. The recorded enum and nullable-flag counts match the source exactly (flag missing 5,233; false 4,942; true 620). Sample child counts match source projections: 591 primary measures, 311 analyses, 272 arms, 1,334 groups, 3,423 measurements, and 604 analysis-group rows. Regenerating the deterministic sample gives the saved sample exactly. All seven declared sample axes cover their observed categories.

The funnel counts were independently checked: 6,006 trials with one primary endpoint; 7,198 with at least two numeric primary groups; 4,212 with a p-value; 4,207 with a parsed p-value. At primary-outcome grain, 15,160 have a parameter and unit; 11,857 have at least two numeric groups; 5,656 have a parsed p-value; 7,033 have a candidate arm bijection; 3,134 have explicit comparator roles; 1,713 have an explicit role contrast. These counts overlap or use different grains and **must not be read as an eligible-benefit funnel or model training set**.

The raw sample preserves outcome title/description/time frame, arm labels/roles, p/CI/statistical method/comments, and public dates. Exact-label candidate mapping is not verified clinical or molecular identity. No benefit inference or score is authorized by this evaluation. The earlier pilot's incorrect non-inferiority/equivalence interpretation was repaired and the failed pilot preserved; the repaired pilot and full replay passed.
