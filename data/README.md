# Data inventory

`manifest.json` pins the 12 official quarterly trip archives for 2022–2024, their extracted CSVs, and the latest official station table discovered for the initial audit. It contains 25 entries: 12 archives, 12 trip CSVs, and one station CSV.

Each entry records `filename`, `source_url`, `downloaded_at_utc`, `row_count`, and `sha256`. Archive entries also record the actual CSV member name, including the publisher's `indego-trips-2023-q3-2.csv` filename. Original files live in ignored `data/raw/`; only the manifest, download scripts, and aggregate audit outputs are committed. The downloader verifies cached files and downloaded bytes against the pinned hashes and fails on changes.

Run `python scripts/run_stage0.py` after installing the package. See [the generated audit](../reports/stage0/README.md) for counts and the distinction between pre-window date censoring and genuine date discrepancies.
