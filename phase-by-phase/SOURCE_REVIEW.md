# Source spot-checks: 2026-11-19

Eight candidate programs were inspected against the saved ClinicalTrials.gov
records during pipeline development. This was a bounded agent-assisted source
consistency check, **not clinical adjudication or an estimate of linkage accuracy**.
The review queue's clinical adjudication fields remain `NOT_REVIEWED`.

## Concrete errors corrected

| Source | Finding | Implemented response |
| --- | --- | --- |
| [NCT05572515](https://clinicaltrials.gov/study/NCT05572515) | One experimental arm offers PVd or Kd, not all four drugs together | Exclude alternative-regimen arm; retain separate Teclistamab arm |
| [NCT06281964](https://clinicaltrials.gov/study/NCT06281964) | PLB1004 arm describes monotherapy, but its intervention description includes chemotherapy | Evidence-matched quarantine; correction of source text removes the condition for quarantine |
| [NCT07336732](https://clinicaltrials.gov/study/NCT07336732) | A single arm label describes optional chemotherapy and a comparator | Exclude ambiguous alternative/comparison arm |

Regression tests cover these patterns and distinguish explicit alternatives
from harmless narrative wording about progression or toxicity. Raw descriptions
are retained in the organized intervention table and original downloaded pages.

## Why candidate programs are not yet clinical truth

| Candidate | Inspected records | Remaining interpretation issue |
| --- | --- | --- |
| Metformin / type 2 diabetes | NCT02366377, NCT01787396 | Background therapy and research of another drug can share the same ingredient/condition |
| Prucalopride / constipation | NCT00903747, NCT01116206 | A healthy-volunteer QT study can carry a disease condition label |
| PLB1004 / NSCLC | NCT06281964, NCT07336732 | Contradictory/alternative regimen descriptions, now quarantined |
| Teclistamab / multiple myeloma | NCT06425991, NCT05243797, NCT05572515 | Later Phase 1 manufacturing-comparability work follows earlier Phase 3 studies |
| Dexmedetomidine / anesthesia | NCT00921284, NCT05619627 | Route, population, and use differ despite broad matching labels |
| Ibuprofen / pain | NCT02666846, NCT01562717, NCT01563289 | Formulation and healthy-volunteer experimental-pain work differ from injury efficacy studies |
| LEO 80185 gel / psoriasis | NCT02605057, NCT02668692 | A product code can conceal multiple ingredients; observed phase order is not monotonic |
| SR-T100 gel / actinic keratosis | NCT01493921, NCT02029066, NCT02559934 | Later Phase 1 pharmacokinetic studies do not imply new initial development |

Chronology exclusions correctly prevent many of these candidates from becoming
Phase 1 entry examples. That does not establish that all remaining candidates
are correctly linked. Molecule/formulation identity, indication granularity,
background therapies, and research purpose still need reviewed mappings.

The broad lesson is that **data integrity, record linkage, and scientific
validity are different checks**. A successful SQL/Python join cannot alone
establish a true drug-development program.
