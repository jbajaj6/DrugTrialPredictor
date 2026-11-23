import json

import pandas as pd
import pytest

from phase_by_phase.fetch_details import development_sample_ids, eligible_ids, load_details, retrieve


def _study(nct_id):
    return {"protocolSection": {"identificationModule": {"nctId": nct_id}},
            "resultsSection": {"outcomeMeasuresModule": {}}}


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        nct_id = url.rsplit("/", 1)[-1]
        self.calls.append(nct_id)
        return _Response(_study(nct_id))


def test_eligible_ids_are_canonical_and_selected(tmp_path):
    path = tmp_path / "trials.parquet"
    pd.DataFrame({"nct_id": ["NCT00000002", "NCT00000001"],
                  "has_results": [False, True]}).to_parquet(path)
    assert eligible_ids(path) == ["NCT00000001"]
    pd.DataFrame({"nct_id": ["nct00000001"], "has_results": [True]}).to_parquet(path)
    with pytest.raises(ValueError, match="Invalid"):
        eligible_ids(path)


def test_resumable_hash_checked_retrieval(tmp_path):
    ids = ["NCT00000001", "NCT00000002"]
    session = _Session()
    manifest = retrieve(ids, tmp_path, session=session)
    assert manifest["complete"] and len(session.calls) == 2
    studies, loaded = load_details(tmp_path)
    assert len(studies) == 2 and loaded["complete"]
    retrieve(ids, tmp_path, session=session)
    assert len(session.calls) == 2
    with pytest.raises(ValueError, match="different ID set"):
        retrieve(ids[:1], tmp_path, session=session)
    path = tmp_path / "NCT00000001.json.gz"
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash"):
        load_details(tmp_path)


def test_reject_mismatched_id(tmp_path):
    class Wrong(_Session):
        def get(self, url, **kwargs):
            return _Response(_study("NCT99999999"))

    with pytest.raises(ValueError, match="Unexpected NCT"):
        retrieve(["NCT00000001"], tmp_path, session=Wrong())
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert not manifest["complete"] and manifest["records"] == {}


def test_development_sample_does_not_use_labels_or_holdout_year(tmp_path):
    path = tmp_path / "trials.parquet"
    pd.DataFrame({"nct_id": ["NCT00000001", "NCT00000002", "NCT00000003"],
                  "has_results": [True, True, True],
                  "phase": ["PHASE2", "PHASE2", "PHASE2"],
                  "start_date": ["2015-01", "2015-06", "2024-01-01"]}).to_parquet(path)
    assert development_sample_ids(path, 1) == ["NCT00000001"]
