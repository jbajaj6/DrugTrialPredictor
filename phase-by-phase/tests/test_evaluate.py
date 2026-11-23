import pandas as pd

from phase_by_phase.clean import build_program_trials
from phase_by_phase.evaluate import evaluate_identity, markdown_report


def test_identity_eval_passes_clean_fixture():
    raw = pd.DataFrame(
        {
            "nct_id": ["NCT1", "NCT2"],
            "drug_name": ["Drug A", "Drug B"],
            "condition_name": ["Disease X", "Disease Y"],
        }
    )
    report = evaluate_identity(raw, build_program_trials(raw))
    assert report["overall"] == "PASS"
    assert report["summary"]["mapping_coverage"] == 1.0
    assert "Identity-cleaning evaluation" in markdown_report(report)


def test_identity_eval_warns_when_mapping_coverage_is_low():
    raw = pd.DataFrame(
        {
            "nct_id": ["NCT1", "NCT2"],
            "drug_name": ["Drug A", "Placebo"],
            "condition_name": ["Disease X", "Disease Y"],
        }
    )
    report = evaluate_identity(raw, build_program_trials(raw))
    coverage = next(c for c in report["checks"] if c["name"] == "mapping_coverage")
    assert coverage["status"] == "WARN"
