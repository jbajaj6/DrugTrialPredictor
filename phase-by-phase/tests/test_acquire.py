import gzip
import json

import pytest

from phase_by_phase.acquire import download_snapshot, load_snapshot, sha256, study_query


def snapshot(tmp_path, ids, complete=True, total=None):
    page = tmp_path / "page_00000.json.gz"
    studies = [{"protocolSection": {"identificationModule": {"nctId": x}}} for x in ids]
    with gzip.open(page, "wt") as handle:
        json.dump({"studies": studies}, handle)
    manifest = {"complete": complete, "records": len(ids), "total_count": total or len(ids),
                "pages": [{"file": page.name, "sha256": sha256(page), "records": len(ids)}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return page, manifest


def test_offline_replay_preserves_every_record(tmp_path):
    snapshot(tmp_path, ["NCT00000001", "NCT00000002"])
    records, manifest = load_snapshot(tmp_path)
    assert len(records) == 2 and manifest["complete"]


def test_corrupt_download_is_not_used(tmp_path):
    page, _ = snapshot(tmp_path, ["NCT00000001"])
    page.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Checksum"):
        load_snapshot(tmp_path)


def test_duplicate_pagination_records_rejected(tmp_path):
    snapshot(tmp_path, ["NCT00000001", "NCT00000001"])
    with pytest.raises(ValueError, match="duplicate"):
        load_snapshot(tmp_path)


def test_incomplete_extraction_not_claimed_complete(tmp_path):
    snapshot(tmp_path, ["NCT00000001"], complete=False, total=200)
    _, manifest = load_snapshot(tmp_path)
    assert not manifest["complete"]


def test_false_complete_total_rejected(tmp_path):
    snapshot(tmp_path, ["NCT00000001"], total=200)
    with pytest.raises(ValueError, match="Complete snapshot count"):
        load_snapshot(tmp_path)


def test_empty_or_negative_limit_rejected_before_network(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        download_snapshot(tmp_path, "2026-11-19", 0)


def test_query_keeps_ongoing_followup_and_biologics():
    query = study_query("2026-11-19")
    assert "BIOLOGICAL" in query
    assert "EARLY_PHASE1" in query
    assert "11/19/2026" in query
    assert "OverallStatus" not in query


def test_pagination_persists_complete_snapshot_and_replays_without_network(tmp_path, monkeypatch):
    from phase_by_phase import acquire
    calls = []
    pages = [
        {"totalCount": 2, "studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}}], "nextPageToken": "next"},
        {"totalCount": 2, "studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT00000002"}}}]},
    ]

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def mount(self, *args):
            pass

        def get(self, url, params, timeout):
            calls.append(params.copy())
            payload = pages.pop(0)

            class Response:
                def raise_for_status(self):
                    pass

                def json(self):
                    return payload

            return Response()

    monkeypatch.setattr(acquire.requests, "Session", Session)
    monkeypatch.setattr(acquire.time, "sleep", lambda _: None)
    result = download_snapshot(tmp_path, "2026-11-19")
    assert result["complete"] and result["records"] == 2
    assert "pageToken" not in calls[0] and calls[1]["pageToken"] == "next"
    assert len(load_snapshot(tmp_path)[0]) == 2
    # If a completed download attempted another GET, the empty pages list fails.
    assert download_snapshot(tmp_path, "2026-11-19")["complete"]
    assert len(calls) == 2
