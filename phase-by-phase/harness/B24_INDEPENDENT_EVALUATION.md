# B24 independent evaluation — supervised attempt 1

**Verdict: PASS for the frozen, descriptive source-only B24 arm-link audit.** This accepts an audited choice set for a separately registered future linkage-policy decision, not a clinical identity, efficacy, feature-availability, model-performance, or preferred-policy claim. I found **no failure in the final builder tree or delivered full output** after the builder's three logged repair rounds. Those three rounds exhaust the authorized repair budget; no fourth repair was requested or made.

## Scope and provenance

I read `AGENTS.md`, `skills/structured-trials/SKILL.md`, `harness/EXECUTION_RULES.md`, the frozen B24 section of `harness/TASK_LEDGER.md`, `harness/B24_BUILDER_PROMPT.md`, the builder handoff, implementation and tests. I did not edit builder files, the ledger, pinned inputs, output/cache files, or any result/holdout source; the only new data artifact is my ignored fresh replay at `data/processed/b24_eval_replay_2026-11-27_v1`. The only tracked edit is this evaluation.

The final manifest is `data/processed/b24_full_2026-11-27_v2/manifest.json`. I independently recomputed SHA-256 for its four source paths, implementation, and all twelve listed output files: **all matched**. The pinned source digests are cohort `91c5bdc96a9f4fee6d53cd2d884338c614962f1b9ce1a698ad6ba9b883fe2912`, links `33e870871d839cfee01862bc5ed99dc0f9dd2749731e54b2560575b9ccc2f407`, arms `5ce46eb65f232a68301b2c3ddc4fde0690b97b48942be598fa990a431fe94047`, interventions `0d5fbede79a3fdaf74e22a498e533deefb75d1b9769c24c43d76d6a00edb2e3`. The implementation digest was `aa32753fb2202743ae614a3349c490d859c279c54ced865e7894c8040e9d2433`. The manifest also pins the B18 metadata/normalizer digests. Its own digest is excluded to avoid self-reference.

Independent DuckDB `EXCEPT ALL` in **both directions** returned zero rows for the exact B15 metadata projection against `trials.parquet`, and for all original source columns and multiplicities of arms, interventions, and links against their output tables (links projected from `assertions.parquet`). These source comparisons joined on exact `(nct_id,nct_version)` keys. A separate reconstruction directly from pinned source links, grouping by exact trial/version/arm/intervention ordinals and directional source, matched all output edge keys and classes in both `EXCEPT ALL` directions; zero duplicate edge keys. This validates the source graph independently of the builder's report and inspection script.

Code inspection shows B15 is read with only `nct_id`, first-public version/date, and pure phase; the frame filter is pure Phase 1/2/3 and first-public date before 2020. Protocol children are joined only by selected exact trial/version keys. The CLI offers only output path and positive pilot limit, not arbitrary sources. The only source reads are the four pinned Parquet files plus the B18 report as hash metadata; the imported B18 module supplies a name normalizer. There is no result/holdout query, remote API call, model fit, or clinical-identity adjudication. DuckDB is fixed at 2 GiB, two threads, disabled insertion-order preservation, and empty temp directory (no spill); failure is not silently converted to a larger budget.

## Independent full-output checks

The table counts obtained by querying the Parquet files were: 68,623 trials, 121,039 arms, 159,113 interventions, **354,917 assertions**, **184,256 edges**, 176,939 exact-name groups, 176,925 folded-name groups, 476,949 policy rows, 205,869 trial-policy rows, and **14,993 review assertions**. The frame has 19,343/29,704/19,576 Phase 1/2/3 trials, no duplicate exact keys, no 2020+ checkpoint (range 2005-06-24 to 2019-12-30), 54,250 linked versions, and 14,373 versions without links.

| Phase | Reciprocal | Intervention-only | Arm_group-only |
| --- | ---: | ---: | ---: |
| Phase 1 | 57,242 | 3,517 | 2,946 |
| Phase 2 | 69,280 | 2,426 | 2,156 |
| Phase 3 | 44,139 | 1,379 | 1,171 |
| **Total** | **170,661** | **7,322** | **6,273** |

Among 13,595 unilateral edges, 13,569 have opposite-direction **exact written-name** evidence at another ordinal, 16 agree only after casefold/trim, and 10 have neither. At arm/name grain there are 23 exact-name one-sided groups; casefold/trim leaves 10 one-sided arm_group groups (8 Phase 1, 2 Phase 2, 0 Phase 3). These are assertion/ordinal descriptions, not registry errors or molecular identity decisions. Output examples confirm `NCT00506246` v0 arm 1 has separate Propofol ordinals in opposing directions, and `NCT01223352` v0 arm 0 has the same bosentan written name at two differently directed ordinals. Original assertion provenance and child text remain reviewable. All 14,993 review rows have blank human adjudication and `unknown` clinical identity.

| Edge policy | Raw DRUG rows | Candidate rows | Primary rows | Primary trials |
| --- | ---: | ---: | ---: | ---: |
| Intervention | 159,311 | 136,373 | 55,714 | 35,209 |
| Union | 165,420 | 141,852 | 58,973 | 35,208 |
| Reciprocal | 152,218 | 129,992 | 52,555 | 35,557 |

All three policies have 53,672 candidate trials. Independently comparing `trial_policy.parquet` showed reciprocal versus intervention primary eligibility **gains 378 trials and loses 30** (gains Phase 1/2/3: 152/93/133; losses: 17/9/4), net +348. This non-monotonicity follows from the one-normalized-candidate and control-sharing rule; it is not evidence that reciprocal links are clinically better. Raw ordinals, B18-normalized candidate names, and primary-eligible trial counts are kept distinct. Multi-DRUG, control-sharing, non-DRUG, uncertainty, and exact-version edge cases are exercised by focused tests; the final full report records no unresolved/obsolete/orphan/date/version flags in this cohort. Zero observed flags do not remove the explicit review fields or imply universal data quality.

## Commands and reproducibility

All commands were run from `phase-by-phase/` against the final builder tree. Exit codes below are my runs, not builder self-report.

| Command/check | Independent result |
| --- | --- |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_arm_link_audit_b24.py` | Exit 0; **13 passed**. |
| `PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests` | Exit 0; **406 passed**, five DuckDB deprecation warnings. |
| `../.venv/bin/python harness/check.py` | Exit 0; **PASS**. |
| `PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.arm_link_audit_b24 --out data/processed/b24_eval_replay_2026-11-27_v1` | Exit 0; fresh full offline run, with no source/cache modification or network request. |
| `hashlib.sha256` over each manifest-listed input, code, and output; byte-hash comparison of every file in full output versus my replay | All digests matched; **13/13 delivered files byte-identical**, including ten Parquet tables, two JSON reports/examples, and manifest. |
| DuckDB `EXCEPT ALL` both ways for B15 frame, arms, interventions, source-link assertions, and source-derived edge keys/classes | Zero missing and zero extra rows in every comparison; no duplicate edge key. |
| DuckDB `GROUP BY` over `trials`, `edges`, `names_exact`, `names_folded`, `policy_rows`, `trial_policy`, and `review` Parquet | Counts and transitions above reproduced independently. |

The builder handoff records three repairs: a synthetic fixture keyword collision, a no-spill 2 GiB allocation failure during wide export, and review JSON extraction after a freed in-memory table. Those failures are documented in `harness/B24_ARM_LINK_AUDIT.md` and their superseded/partial artifacts remain separate. **No failure reproduced in final independent tests, artifact checks, or fresh replay.** Acceptance does not authorize changing the B18 policy or using name agreement as a molecule/dose/formulation/regimen equivalence claim; any such decision requires its own frozen task and evaluation.
