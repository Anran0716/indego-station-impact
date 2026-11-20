"""Download public Indego inputs, pin their URLs, and verify file checksums."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://www.rideindego.com"
MEDIA_URL = f"{BASE_URL}/wp-json/wp/v2/media"
USER_AGENT = "indego-station-impact/0.1 (public research data download)"


def fetch(url: str) -> bytes:
    """Fetch one public URL with bounded retries; TLS verification stays enabled."""
    if urlparse(url).hostname != "www.rideindego.com" or not url.startswith("https://"):
        raise ValueError(f"Unexpected input host: {url}")
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=90) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("Unreachable retry state")


def discover_sources(years: tuple[int, ...] = (2022, 2023, 2024)) -> list[dict]:
    """Find exact trip filenames and the latest station CSV in the public media API."""
    sources = []
    for year in years:
        query = MEDIA_URL + "?" + urlencode({"search": f"indego-trips-{year}", "per_page": 100})
        media = json.loads(fetch(query))
        for quarter in range(1, 5):
            filename = f"indego-trips-{year}-q{quarter}.zip"
            matches = [item for item in media if Path(urlparse(item["source_url"]).path).name
                       == filename]
            if len(matches) != 1:
                raise ValueError(f"Expected one official media entry for {filename}")
            sources.append({"filename": filename, "source_url": matches[0]["source_url"],
                            "catalog_url": query, "kind": "trip_archive"})
    query = MEDIA_URL + "?" + urlencode({"mime_type": "text/csv", "per_page": 100})
    media = json.loads(fetch(query))
    stations = [item for item in media if re.fullmatch(
        r"indego-stations-\d{4}-\d{2}-\d{2}\.csv",
        Path(urlparse(item["source_url"]).path).name,
    )]
    if not stations:
        raise ValueError("No current official station CSV found")
    latest = max(stations, key=lambda item: Path(urlparse(item["source_url"]).path).name)
    sources.append({"filename": Path(urlparse(latest["source_url"]).path).name,
                    "source_url": latest["source_url"], "catalog_url": query,
                    "kind": "station_csv"})
    return sources


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def csv_metadata(path: Path) -> tuple[int, list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        columns = next(reader)
        return sum(1 for row in reader if any(row)), columns


def download_inputs(root: Path) -> dict:
    """Reuse pinned manifest entries; changed local or remote bytes fail verification."""
    raw = root / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pinned = {entry["filename"]: entry for entry in manifest["files"]}
    sources = [entry for entry in manifest["files"] if entry["kind"] != "trip_csv"]
    if not sources:
        sources = discover_sources()
    entries = []
    for source in sources:
        path = raw / source["filename"]
        if not path.exists():
            payload = fetch(source["source_url"])
            path.with_suffix(path.suffix + ".part").write_bytes(payload)
            path.with_suffix(path.suffix + ".part").replace(path)
            downloaded_at = datetime.now(timezone.utc).isoformat()
        else:
            downloaded_at = source.get("downloaded_at_utc")
            if downloaded_at is None:
                # A previous interrupted discovery run; preserve the file's UTC timestamp.
                downloaded_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        digest = sha256(path)
        if source.get("sha256") and source["sha256"] != digest:
            raise ValueError(f"SHA256 mismatch: {path.name}")
        entry = {**source, "sha256": digest, "downloaded_at_utc": downloaded_at,
                 "size_bytes": path.stat().st_size}
        if source["kind"] == "trip_archive":
            with zipfile.ZipFile(path) as archive:
                members = [item for item in archive.infolist() if item.filename.lower().endswith(
                    ".csv") and not item.filename.startswith("__MACOSX/")]
                if len(members) != 1:
                    raise ValueError(f"Expected one trip CSV in {path.name}")
                csv_path = raw / Path(members[0].filename).name
                if not csv_path.exists():
                    with archive.open(members[0]) as stream, csv_path.open("wb") as output:
                        shutil.copyfileobj(stream, output)
                csv_digest = sha256(csv_path)
                old_csv = pinned.get(csv_path.name)
                if old_csv and csv_digest != old_csv["sha256"]:
                    raise ValueError(f"SHA256 mismatch: {csv_path.name}")
                # Check the extracted bytes against the archive, even on cache reuse.
                with archive.open(members[0]) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != csv_digest:
                        raise ValueError(f"Extracted CSV does not match {path.name}")
            rows, columns = csv_metadata(csv_path)
            entry.update(row_count=rows, columns=columns, archive_member=members[0].filename)
            entries.append(entry)
            entries.append({"filename": csv_path.name, "kind": "trip_csv",
                            "source_url": source["source_url"], "source_archive": path.name,
                            "downloaded_at_utc": downloaded_at, "sha256": csv_digest,
                            "size_bytes": csv_path.stat().st_size, "row_count": rows,
                            "columns": columns})
        else:
            rows, columns = csv_metadata(path)
            entry.update(row_count=rows, columns=columns)
            entries.append(entry)
        print(f"Verified {path.name}: {rows:,} rows", flush=True)
    result = {"schema_version": 1, "files": entries}
    manifest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
