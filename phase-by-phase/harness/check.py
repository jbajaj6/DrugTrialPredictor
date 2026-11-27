"""Verify the local execution contract and record its file hashes.

Run from the repository root: python phase-by-phase/harness/check.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "AGENTS.md",
    "skills/structured-trials/SKILL.md",
    "harness/EXECUTION_RULES.md",
    "harness/TASK_LEDGER.md",
    "harness/RECOVERY_POLICY.md",
    "harness/CURRENT_STATE.md",
    "harness/check.py",
    "requirements.txt",
    "src/phase_by_phase/acquire.py",
    "src/phase_by_phase/organize.py",
    "tests/test_acquire.py",
)


def check() -> dict:
    files = {}
    for relative in REQUIRED:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Required harness/project file missing: {relative}")
        content = path.read_bytes()
        if not content:
            raise ValueError(f"Required harness/project file empty: {relative}")
        files[relative] = hashlib.sha256(content).hexdigest()
    return {"status": "PASS", "root": str(ROOT), "files_sha256": files}


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
