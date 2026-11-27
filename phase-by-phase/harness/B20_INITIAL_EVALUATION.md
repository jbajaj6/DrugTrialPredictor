# B20 initial attempt — independent evaluation

Verdict: **BLOCKED/PARTIAL** for molecular identity evidence; local source-graph engineering checks pass. This is an evaluator rejection of the initial attempt's *full* B20 acceptance, not a negative chemical-match result.

Read-only independent commands from `phase-by-phase/`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_bridge_b20.py
# exit 0; 38 passed
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests
# exit 0; 347 passed; 5 existing deprecation warnings
python3 harness/check.py
# exit 0; PASS
```

The evaluator independently matched all 10 exact-key selected-source child multisets: 150 trial versions, 284 arms, 366 interventions, 152 aliases, 944 arm/intervention assertions, 193 conditions, 415 B18 exposures, 125 alias-review rows, 415 target exposures, and 150 first-public design provenance rows. Source, cache, report and all 16 semantic-output hashes matched. Offline replay was byte-identical at semantic-table grain. Sample quotas were exactly 50/25/25/20/15/15 with no shortfalls.

There are 369 normalized names and a 200-name query cap. The initial pilot attempted only three unique names (six attempts), all `URLError` with empty bodies; the circuit skipped the remaining 197 names within budget, and 169 were outside budget. Thus there were **zero successful ChEMBL responses** and zero molecular candidates. That cannot be interpreted as no molecule matches or as candidate precision. A separate diagnostic showed Python's default HTTPS client failed certificate verification; using the installed trusted CA bundle returned HTTP 200 without disabling verification. A targeted CA/trust and cache replay repair is required before full acceptance. Prior source-only output and failed-response cache remain immutable.
