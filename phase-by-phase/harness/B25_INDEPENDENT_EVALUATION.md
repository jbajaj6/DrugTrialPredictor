# B25 independent evaluation — exact preferred-name rescue

**Verdict: PASS_REAL_DATA_CHECKS for the bounded 60-name, positive-only acquisition audit.** This does not validate clinical identity, historical feature availability, a linkage policy, a model, or the unauthorized 400-trial scale. The initial restricted-network pilot was blocked and remains a separate failed attempt, not negative evidence. The later approved network-enabled pilot passed, the gated full acquisition completed, and my new offline replay reproduced all six full-output files byte-for-byte.

## Frozen inputs and provenance

I read the local AGENTS, structured-trials skill, execution rules, frozen B25 ledger section, builder prompt, handoff, module and tests. I did not edit builder code/tests, the ledger, B23 inputs/cache, or result/holdout sources. My only new data artifact is the ignored offline replay 'data/processed/b25_eval_full_offline_replay_2026-11-27_v1'; this document is the only tracked edit.

Independent SHA-256 checks matched the three frozen B23 inputs: cache index '269c2f8b72d083a869858b1a2312d7c3413eb9d114fdcfcdd7be5714f4c385d2', pre-manifest v1 '6ee1379dd8498f623a35eda9a559f58de3f56acd8ee20f08db4b7f643bacdfcf', and report '0fa4d6814a40b1dd6510b2684798eb5c75c7a7402971e715df9b49050c1904ec'. I independently rehashed all **393** original B23 response captures against the pinned index. Its 60 'page_cap' names exactly equal the sorted 60 B25 pre-manifest/full-cache names and are in the frozen 229-name order.

**B23 lineage nuance:** B25 preregistration pins B23 pre-manifest **v1**, while the original B23 live cache index points to **v2** SHA-256 '790c2aac45db80fe64fb710773aeae7d11f1c7b0aae947dcf7dd676a1a459e95'. My read-only JSON comparison found one differing key, 'code_sha256'; the two manifests are deeply equal after excluding only that key. Thus v1 is **not** represented as the live acquisition manifest. The independently executed immutable index-to-v2 attestation, plus B25's pinned v1/index/report and archived-body checks, suffices for this bounded source-name selection. This attestation is documented here, not implemented as an additional guard inside the frozen B25 module; changing that module now would invalidate its acquisition code hash.

B25 pre-manifest SHA-256 is 'eb752de11455edc8f583ef5c462ec9cbfd4bde2bb7f104f15e842a073ff26b46'; current module SHA-256 matches its pin 'ffd82fa5abaf5ab2c092fbe9a54173d7d186a173b40e22c54bf6814f44403509'. The pre-manifest contains exactly 60 sorted names and 180 planned page URLs, and its mtime precedes every request start. Full and pilot caches point to that pre-manifest; the full index pins pilot index digest 'f1c7cf4af03085325cf16413ff7a27fde4aff04e0a1d21f83e53ed84fd94b4c8', and all ten pilot records are identical in the full index. Full index SHA-256 is '049fc55c67058ace78a62f5807df2b25bf77600a3a53b507d27ca3d1d3d4a512'.

## Acquisition and evidence

The code restricts requests to verified-HTTPS 'molecule.json?pref_name__iexact=<encoded name>' URLs, refuses redirects, uses certificate/hostname-verifying SSL context with configured or certifi CA, and never follows server-supplied pagination URLs. Frozen guards are two attempts/page, ten-second timeout, at least 0.3-second spacing, three pages/name, 8 MiB capture cap and 400 total attempts, with a 429 circuit stop. No credential/email parameter, results/holdout read, model operation, or ChEMBL max-phase/approval/indication historical feature appears.

The approved pilot had ten complete zero-preferred-name-hit **molecular-unknown** statuses in 12 attempts. The full cache accounts for **60/60 names and 97 attempts including pilot**: 37 HTTP 200/no-error, 37 'TimeoutError' without HTTP status, 23 HTTP 500 'HTTPError'; no 429 or truncation. I rehashed every response/error body and checked all exact HTTPS URLs/offsets, pilot reuse and request times. Minimum within-stage gaps were 1.039 seconds for pilot and 0.458 for full. Every HTTP 200 response independently passed integer total/offset/limit, exact result count, next/previous availability, completion, casefolded exact preferred name and CHEMBL ID shape. No fourth page was needed. Failure names contributed no candidate rows.

Independent classification: **5 complete positive preferred-name searches, 32 complete zero-hit molecular-unknown searches, and 23 HTTP/transport-unknown searches**. The five candidate rows retain normalized name, query URL, response digest, retrieval timestamp, matched preferred name and molecule ID:

| Normalized name | Matched preferred name | Molecule ID |
| --- | --- | --- |
| amphotericin b | AMPHOTERICIN B | CHEMBL267345 |
| citalopram hydrobromide | CITALOPRAM HYDROBROMIDE | CHEMBL1200781 |
| daunorubicin hydrochloride | DAUNORUBICIN HYDROCHLORIDE | CHEMBL1563 |
| paclitaxel | PACLITAXEL | CHEMBL428647 |
| pegaptanib sodium | PEGAPTANIB SODIUM | CHEMBL1201421 |

These are contemporary retrospective **candidates**, not verified active ingredients or trial-regimen matches; salts and parent molecules must not be silently equated. Zero preferred-name hits do not prove synonym absence or negative molecular matches. HTTP/transport failures are unknown. Candidate rows retain 'clinical_identity: unknown', and no historical availability is established.

The 100 sampled trials retain original B23 statuses **47 candidate-present / 20 no-exact-candidate / 33 unknown** and positive-only augmented statuses **50 / 20 / 30**. Five name occurrences received positive evidence, but only three trials newly become candidate-present. The partial-identification interval changes **47%–80% to 50%–80% within this 100-trial sample**, a three-percentage-point sample lower-bound increase. This is not a guaranteed bound for the 19,576-trial Phase 3 frame; population sampling uncertainty and clinical precision remain unquantified.

## Independent commands and exact results

All commands ran from 'phase-by-phase/'. The initial DNS-blocked pilot/full-gate failure is preserved in the builder handoff and did not enter the successful cache.

| Command/check | Independent result |
| --- | --- |
| 'PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_prefname_rescue_b25.py' | Exit 0; **24 passed**. |
| 'PYTHONPATH=src ../.venv/bin/python -m pytest -q -p no:cacheprovider tests' | Exit 0; **430 passed**, five existing DuckDB deprecation warnings. |
| '../.venv/bin/python harness/check.py' | Exit 0; **PASS**. |
| 'PYTHONPATH=src ../.venv/bin/python -m phase_by_phase.prefname_rescue_b25 offline --pre data/processed/b25_pre_2026-11-27_v1 --cache data/raw/b25_prefname_full_cache_network_2026-11-27_v1 --compare data/processed/b25_prefname_full_network_2026-11-27_v1 --out data/processed/b25_eval_full_offline_replay_2026-11-27_v1' | Exit 0; **all six files byte-identical**. Offline mode invokes no acquisition transport. |
| Independent Python SHA-256/JSON inspection of B23 v1/v2/index/393 bodies, B25 pre/pilot/full indices/97 bodies, 37 successful pages, five candidates, 100 trial rows and output manifest | Exit 0; all digests, selection, provenance, attempts, statuses and positive-only transitions above reproduced. |

The completed full-output manifest hashes all five semantic content files. I recomputed these digests and compared the sixth manifest and five content files with my fresh replay: **6/6 byte-identical**. The original restricted-network pilot's 20 DNS failures and blocked full gate were correctly retained as unknown. No targeted builder code-repair rounds were used. Acceptance authorizes only this bounded candidate-evidence audit, not B18/B23 policy changes, synonym coverage, a historical feature, clinical identity, model performance, or 400-trial expansion.
