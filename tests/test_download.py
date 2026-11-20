import io
import json
import zipfile

import pytest

from stimpact import download


def test_pinned_manifest_verifies_both_archive_and_extracted_bytes(tmp_path, monkeypatch):
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    (tmp_path / "data/manifest.json").write_text('{"files": []}')
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("nested/trips.csv", 'trip_id,note\n1,"line one\nline two"\n')
    source = {"filename": "trips.zip", "kind": "trip_archive",
              "source_url": "https://www.rideindego.com/example.zip"}
    monkeypatch.setattr(download, "discover_sources", lambda: [source])
    monkeypatch.setattr(download, "fetch", lambda url: payload.getvalue())
    manifest = download.download_inputs(tmp_path)
    assert [entry["row_count"] for entry in manifest["files"]] == [1, 1]
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])
    monkeypatch.setattr(download, "fetch", lambda url: pytest.fail("Cached run made a network call"))
    assert download.download_inputs(tmp_path) == manifest
    (raw / "trips.csv").write_text("tampered\n")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        download.download_inputs(tmp_path)
    assert json.loads((tmp_path / "data/manifest.json").read_text()) == manifest
