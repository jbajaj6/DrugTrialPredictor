"""Run download -> identity cleaning -> data-quality evaluation."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .clean import build_program_trials
from .download import download_studies, save_download
from .evaluate import evaluate_identity, save_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-studies", type=int, default=1000)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/phase_by_phase"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/processed/phase_by_phase"))
    args = parser.parse_args()

    studies = download_studies(max_studies=args.max_studies)
    trials_path, mappings_path = save_download(studies, args.raw_dir)
    mappings = pd.read_parquet(mappings_path)
    bridge = build_program_trials(mappings)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    bridge_path = args.out_dir / "program_trials.parquet"
    bridge.to_parquet(bridge_path, index=False)
    report = evaluate_identity(mappings, bridge)
    save_report(report, args.out_dir)

    print(f"trials: {trials_path}")
    print(f"program bridge: {bridge_path}")
    print(f"evaluation: {args.out_dir / 'identity_eval.md'}")
    print(f"overall: {report['overall']}")


if __name__ == "__main__":
    main()
