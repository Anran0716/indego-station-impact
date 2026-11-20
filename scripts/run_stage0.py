"""Download, normalize, and audit the public study inputs without fitting models."""

from __future__ import annotations

import argparse
import json
import platform
import re
from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyproj
import yaml

from stimpact.audit import (
    detect_relocations,
    quarterly_coordinates,
    reconcile_opening_dates,
    station_identity_candidates,
)
from stimpact.download import download_inputs
from stimpact.io import load_stations, load_trips


def run(root: Path, *, offline: bool = False) -> dict:
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    if offline:
        manifest = json.loads((root / "data/manifest.json").read_text(encoding="utf-8"))
        from stimpact.download import sha256

        for entry in manifest["files"]:
            if sha256(root / "data/raw" / entry["filename"]) != entry["sha256"]:
                raise ValueError(f"SHA256 mismatch: {entry['filename']}")
    else:
        manifest = download_inputs(root)
    trip_files = [entry for entry in manifest["files"] if entry["kind"] == "trip_csv"]
    station_files = [entry for entry in manifest["files"] if entry["kind"] == "station_csv"]
    if len(trip_files) != 12 or len(station_files) != 1:
        raise ValueError("Stage 0 requires twelve quarterly CSVs and one official station table")
    eligibility = config["eligibility"]
    annual = {}
    quarterly = []
    first_dates = []
    coordinates = []
    invalid_coordinates = 0
    quarters_seen = set()
    for entry in trip_files:
        match = re.search(r"(\d{4})-q([1-4])", entry["source_archive"])
        if match is None:
            raise ValueError(f"Unknown quarterly filename: {entry['source_archive']}")
        year, quarter = match.groups()
        expected_quarter = f"{year}Q{quarter}"
        if expected_quarter in quarters_seen:
            raise ValueError(f"Duplicate quarter: {expected_quarter}")
        quarters_seen.add(expected_quarter)
        trips = load_trips(root / "data/raw" / entry["filename"],
                           eligibility["virtual_station_id"])
        counts = trips.attrs["audit"]
        if counts["raw_rows"] != entry["row_count"]:
            raise AssertionError("Loaded raw row count does not match manifest")
        if not trips["start_time"].dt.to_period("Q").astype(str).eq(expected_quarter).all():
            raise ValueError(f"Trip start outside declared quarter: {entry['filename']}")
        annual.setdefault(year, Counter()).update(counts)
        quarterly.append({"quarter": expected_quarter, **counts})
        starts = trips.groupby("start_station")["start_time"].min().rename_axis("station_id")
        ends = trips.groupby("end_station")["end_time"].min().rename_axis("station_id")
        first_dates.append(pd.concat([starts, ends]).groupby(level=0).min())
        coordinate_frame = quarterly_coordinates(trips, config["spatial"]["projected_crs"])
        invalid_coordinates += coordinate_frame.attrs["invalid_coordinate_rows"]
        coordinates.append(coordinate_frame)
        print(f"Audited {expected_quarter}: {len(trips):,} normalized trips", flush=True)
    if quarters_seen != {f"{year}Q{q}" for year in (2022, 2023, 2024) for q in range(1, 5)}:
        raise ValueError("Quarter coverage is not exactly 2022 Q1 through 2024 Q4")
    first_seen = pd.concat(first_dates).groupby(level=0).min().rename("first_trip_date").reset_index()
    coordinate_frame = pd.concat(coordinates, ignore_index=True).sort_values(["station_id", "quarter"])
    relocation = detect_relocations(coordinate_frame, config["spatial"]["relocation_threshold_m"])
    station_entry = station_files[0]
    stations = load_stations(root / "data/raw" / station_entry["filename"],
                             eligibility["virtual_station_id"])
    identity_candidates = station_identity_candidates(stations, coordinate_frame,
                                                       "2022-01-01", "2024-12-31")
    dates = reconcile_opening_dates(stations, first_seen, "2022-01-01",
                                    eligibility["opening_date_tolerance_days"])
    observed = dates["first_trip_date"].notna()
    in_window = observed & dates["official_open_date"].between("2022-01-01", "2024-12-31")
    relocation_full = dates[["station_id", "station_name"]].merge(
        relocation, on="station_id", how="left", validate="one_to_one",
    )
    relocation_full["coordinate_status"] = relocation_full["coordinate_status"].fillna("no_coordinates")
    missing_table = dates.loc[observed & dates["station_name"].isna(), "station_id"].tolist()
    summary = {
        "study_trip_years": [2022, 2023, 2024],
        "station_table": station_entry["filename"],
        "station_table_source_url": station_entry["source_url"],
        "annual_trip_counts": {year: dict(counts) for year, counts in sorted(annual.items())},
        "station_table_rows_including_virtual": station_entry["row_count"],
        "station_table_stations_excluding_virtual": len(stations),
        "observed_stations_excluding_virtual": len(first_seen),
        "observed_ids_missing_from_station_table": missing_table,
        "date_cases_all_comparable_observed": dates.loc[observed, "date_case"].value_counts().to_dict(),
        "date_cases_official_openings_2022_2024": dates.loc[in_window, "date_case"].value_counts().to_dict(),
        "date_status_counts": dates["date_status"].value_counts().to_dict(),
        "official_openings_by_year": {
            str(int(year)): int(count) for year, count in
            stations["official_open_date"].dt.year.value_counts().sort_index().items()
            if pd.notna(year)
        },
        "manual_review_station_count": int(dates["manual_review_required"].sum()),
        "relocation_flagged_station_count": int(relocation["relocated"].sum()),
        "relocation_flagged_station_ids": relocation.loc[relocation["relocated"], "station_id"].tolist(),
        "relocation_flags_are_confirmed_physical_moves": False,
        "station_identity_candidate_pairs": len(identity_candidates),
        "station_identity_candidate_new_ids": int(identity_candidates["later_station_id"].nunique()),
        "coordinate_status_counts": relocation_full["coordinate_status"].value_counts().to_dict(),
        "invalid_departure_coordinate_rows": invalid_coordinates,
        "projected_crs": config["spatial"]["projected_crs"],
        "relocation_threshold_m": config["spatial"]["relocation_threshold_m"],
        "runtime": {"python": platform.python_version(), "duckdb": duckdb.__version__,
                    "pandas": pd.__version__, "numpy": np.__version__, "pyproj": pyproj.__version__},
    }
    output = root / "reports/stage0"
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(quarterly).to_csv(output / "quarterly_counts.csv", index=False)
    dates.sort_values("station_id").to_csv(output / "opening_date_audit.csv", index=False)
    dates.loc[dates["manual_review_required"]].sort_values("station_id").to_csv(
        output / "opening_date_exceptions.csv", index=False,
    )
    coordinate_frame.to_csv(output / "quarterly_coordinates.csv", index=False)
    relocation_full.sort_values("station_id").to_csv(output / "relocation_audit.csv", index=False)
    identity_candidates.to_csv(output / "station_identity_candidates.csv", index=False)
    lines = ["# Stage 0 data audit", "", "Generated by `python scripts/run_stage0.py`.", "",
             "No treatment effects have been estimated. Counts below precede panel exclusions for "
             "short and same-station trips.", "", "## Annual trips", "",
             "| Year | Raw published trips | Missing endpoint | Virtual endpoint | Retained |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for year, counts in summary["annual_trip_counts"].items():
        lines.append(f"| {year} | {counts['raw_rows']:,} | {counts['missing_station_rows']:,} | "
                     f"{counts['virtual_station_rows']:,} | {counts['retained_rows']:,} |")
    lines += ["", "## Station inventory", "",
              f"Official table: [{station_entry['filename']}]({station_entry['source_url']}). "
              f"It has {station_entry['row_count']} nonblank station records including virtual "
              f"station 3000, or {len(stations)} nonvirtual station IDs. "
              f"The 2022–2024 normalized trip files contain {len(first_seen)} observed station IDs.",
              "", f"Observed IDs missing from the table: {missing_table}.", "",
              "## Opening-date checks", "",
              "The first observed trip uses both departures and arrivals. Earlier-than-official "
              "first trips take precedence even when the gap is within 14 days. Exactly +14 days "
              "uses the official date; +15 days requires review.", "",
              "| Case | All observed stations | Official openings in 2022–2024, observed |",
              "| --- | ---: | ---: |"]
    for case in ("within_tolerance", "first_trip_earlier", "first_trip_late_review"):
        lines.append(f"| {case} | {summary['date_cases_all_comparable_observed'].get(case, 0)} | "
                     f"{summary['date_cases_official_openings_2022_2024'].get(case, 0)} |")
    left_censored = summary["date_status_counts"].get("left_censored_pre_window", 0)
    lines += ["", f"Of the apparent late first trips, {left_censored} belong to stations with "
              "official dates before the trip observation window. These are left-censored, not "
              "evidence of delayed opening; retain their official dates. "
              f"{summary['manual_review_station_count']} stations require manual review, listed in "
              "`opening_date_exceptions.csv`; unresolved late dates have no analysis date.", "",
              "Unobserved station-table entries and missing official dates are reported separately "
              "in `summary.json` and `opening_date_audit.csv`.", "",
              "## Coordinate checks", "",
              f"Quarterly medians use valid, nonzero paired departure coordinates, projected to "
              f"{summary['projected_crs']} in metres. Invalid coordinate rows excluded from medians: "
              f"{invalid_coordinates:,}. Flag a station if any pair of quarterly medians differs "
              f"by more than {summary['relocation_threshold_m']} metres; exactly the threshold "
              "does not count as a relocation.", "",
              f"**Stations exceeding the relocation rule: "
              f"{summary['relocation_flagged_station_count']}.** "
              "Their IDs, maximum displacement, and quarter pair are in `relocation_audit.csv`. "
              "Conservatively exclude them from the existing-station sample under the prescribed "
              "rule, but do not equate a coordinate jump with a confirmed physical relocation. "
              "Stations with fewer than two coordinate quarters remain explicitly unaudited.", ""]
    for _, flagged in relocation.loc[relocation["relocated"]].iterrows():
        pair = coordinate_frame.loc[
            coordinate_frame["station_id"].eq(flagged["station_id"])
            & coordinate_frame["quarter"].isin([flagged["quarter_a"], flagged["quarter_b"]])
        ]
        lines += [f"Station {flagged['station_id']}: maximum coordinate jump "
                  f"{flagged['max_displacement_m']:,.1f} metres between "
                  f"{flagged['quarter_a']} and {flagged['quarter_b']}. The less-supported "
                  f"quarter in this pair has {flagged['min_trip_count_in_max_pair']} departure "
                  f"coordinate observations. Latitude span: {pair['latitude'].max() - pair['latitude'].min():.6f} "
                  f"degrees; longitude span: {pair['longitude'].max() - pair['longitude'].min():.6f} "
                  "degrees. A low-support quarter can be dominated by a coordinate error, so "
                  "the physical-relocation interpretation needs separate verification.", ""]
    lines += ["## Station identity review before treatment assignment", "",
              f"The table contains {len(identity_candidates)} repeated-name earlier/later ID pairs "
              f"involving {summary['station_identity_candidate_new_ids']} later IDs opening in "
              "2022–2024. See `station_identity_candidates.csv`. Distances compare the median "
              "of quarterly projected positions for each ID; missing historical coordinates "
              "remain missing. These are possible replacements or renumberings, not automatically "
              "confirmed duplicates. Different names can also conceal replacements, so the list "
              "is not exhaustive. Official opening-year counts are counts of IDs, not necessarily "
              "net additions to physical station sites. Resolve these candidates before freezing "
              "the treatment-source list; no IDs have been merged or dropped on this basis.", "",
              "## Reproduction", "", "```powershell", "python -m pip install -e '.[dev]'",
              "python scripts/run_stage0.py", "```", "",
              "For an existing verified download, use `--offline`. URLs and SHA256 hashes for "
              "both downloaded archives and extracted CSVs are pinned in `data/manifest.json`. "
              "Discovery uses Indego's official public WordPress media index because the current "
              "data-page HTML lists stale 2017 downloads. Raw inputs are ignored by Git.", ""]
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Verify local inputs without network")
    arguments = parser.parse_args()
    run(Path(__file__).resolve().parents[1], offline=arguments.offline)
