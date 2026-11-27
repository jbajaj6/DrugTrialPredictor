"""Safety and identity checks for drug-name candidate linkage."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from phase_by_phase.drug_level_candidates import build, normalize_drug_name


@pytest.mark.parametrize("raw,expected", [
    ("  Drug-X  ", "drug x"),
    ("DRUG X", "drug x"),
    ("placebo", None),
    ("Vehicle control", None),
    ("saline", None),
    (None, None),
])
def test_conservative_name_normalization(raw, expected):
    assert normalize_drug_name(raw) == expected


def _parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = pd.DataFrame(rows)
    connection = duckdb.connect()
    connection.register("data", data)
    connection.execute(f"COPY data TO '{path}' (FORMAT PARQUET)")
    connection.close()


def test_asof_retraction_and_drug_rollup(tmp_path):
    root = tmp_path / "input"
    protocol, results, core = root / "protocol", root / "results", root / "core"
    # One drug across two prior NCTs and two Phase 3 targets. A fourth prior
    # trial first appears on the Phase 3 checkpoint and must not contribute.
    trials = [
        ("P1A", "PHASE1", date(2010, 1, 1)),
        ("P2A", "PHASE2", date(2012, 1, 1)),
        ("P1LATE", "PHASE1", date(2017, 1, 1)),
        ("P3A", "PHASE3", date(2017, 1, 1)),
        ("P3B", "PHASE3", date(2019, 1, 1)),
    ]
    _parquet(root / "cohort.parquet", [dict(nct_id=n, pure_phase=p,
        first_public_nct_version=0, first_public_date=d) for n,p,d in trials])
    _parquet(root / "design.parquet", [dict(nct_id=n,
        first_public_nct_version=0, first_public_date=d) for n,p,d in trials])
    _parquet(protocol / "interventions_clean.parquet", [dict(nct_id=n,nct_version=0,
        ord=0,intervention_name="Drug-X",intervention_type="DRUG",description="Dose text",
        adapter_source_file="fixture",is_obsolete=False) for n,p,d in trials])
    _parquet(protocol / "arms_clean.parquet", [dict(nct_id=n,nct_version=0,
        ord=0,arm_label="Treatment",arm_type="EXPERIMENTAL",description="Regimen text",
        is_obsolete=False) for n,p,d in trials])
    _parquet(protocol / "arm_intervention_links.parquet", [dict(nct_id=n,nct_version=0,
        source="intervention",intervention_ord=0,arm_group_ord=0,
        adapter_link_status="resolved",adapter_source_file="fixture",is_obsolete=False)
        for n,p,d in trials])
    _parquet(protocol / "intervention_aliases_clean.parquet", [dict(nct_id="P1A",
        nct_version=0,intervention_ord=0,other_name="Drug X Alias",
        adapter_link_status="resolved",adapter_source_file="fixture",is_obsolete=False)])
    # P1A originally had a primary outcome, then whole-record version 2
    # removed it. It must not be carried forward to the 2017 landmark.
    _parquet(core / "part.parquet", [dict(nct_id=n,nct_version=v,
        study_first_post_date=d,last_update_post_date=d,is_obsolete=False)
        for n,v,d in [
            ("P1A",0,date(2010,1,1)),("P1A",1,date(2014,1,1)),
            ("P1A",2,date(2016,1,1)),("P2A",0,date(2012,1,1)),
            ("P2A",1,date(2015,1,1)),("P1LATE",0,date(2017,1,1)),
            ("P3A",0,date(2017,1,1)),("P3B",0,date(2019,1,1))]])
    _parquet(results / "results_outcome_measures_clean.parquet", [
        dict(nct_id=n,nct_version=1,adapter_version_public_date=d,
             type="PRIMARY",is_obsolete=False)
        for n,d in [("P1A",date(2014,1,1)),("P2A",date(2015,1,1))]])
    _parquet(results / "results_adverse_serious_event_stats_clean.parquet", [
        dict(nct_id="P2A",nct_version=1,adapter_version_public_date=date(2015,1,1),
             num_at_risk=100,num_affected=2,is_obsolete=False)])
    _parquet(root / "grades.parquet", [dict(nct_id=n,
        efficacy_grade="ungradable",reason_code="fixture",safety_signal="unknown",
        result_date=date(2020,1,1)) for n in ("P3A","P3B")])
    out = root / "output"
    report = build(cohort=root/"cohort.parquet",design=root/"design.parquet",
        protocol=protocol,results=results,grades=root/"grades.parquet",core=core,out=out)
    assert report["phase3_target_ncts"] == 2
    assert report["drug_rollup_rows"] == 1
    connection = duckdb.connect()
    rows = connection.execute("SELECT target_nct_id,prior_p1_trials,prior_p2_trials,"
        "prior_p1_result_trials,prior_p2_result_trials,phase3_grade_unknown_denominator "
        "FROM read_parquet(?) ORDER BY 1",[str(out/"drug_landmarks.parquet")]).fetchall()
    assert rows == [("P3A",1,1,0,1,1),("P3B",2,1,0,1,1)]
    rollup = connection.execute("SELECT phase3_trial_count,phase3_graded_count,"
        "phase3_unknown_or_ambiguous_denominator FROM read_parquet(?)",
        [str(out/"drug_rollup.parquet")]).fetchone()
    assert rollup == (2,0,2)
    assert not connection.execute("SELECT 1 FROM read_parquet(?) WHERE prior_nct_id='P1LATE' "
        "AND target_nct_id='P3A'",[str(out/"prior_contributions.parquet")]).fetchall()
