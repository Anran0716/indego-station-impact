"""Download and audit inputs, resolve station identities, and retain physical openings."""

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
    representative_positions,
)
from stimpact.download import download_inputs, sha256
from stimpact.identity import (
    activity_dates,
    merged_station_weeks,
    resolve_identities,
    source_tables,
)
from stimpact.io import load_stations, load_trips
from stimpact.stage0_report import write_report


def run(root: Path, *, offline: bool = False) -> dict:
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    if offline:
        manifest = json.loads((root / "data/manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            if sha256(root / "data/raw" / entry["filename"]) != entry["sha256"]:
                raise ValueError(f"SHA256 mismatch: {entry['filename']}")
    else:
        manifest = download_inputs(root)
    trip_files = [entry for entry in manifest["files"] if entry["kind"] == "trip_csv"]
    station_files = [entry for entry in manifest["files"] if entry["kind"] == "station_csv"]
    if len(trip_files) != 12 or len(station_files) != 1:
        raise ValueError("Stage 0 requires twelve quarterly CSVs and one official station table")
    eligibility, spatial, study = config["eligibility"], config["spatial"], config["study"]
    annual, quarterly, activity, coordinates, weekly = {}, [], [], [], []
    invalid_coordinates, quarters_seen = 0, set()
    for entry in trip_files:
        match = re.search(r"(\d{4})-q([1-4])", entry["source_archive"])
        if match is None:
            raise ValueError(f"Unknown quarterly filename: {entry['source_archive']}")
        year, quarter = match.groups()
        expected_quarter = f"{year}Q{quarter}"
        if expected_quarter in quarters_seen:
            raise ValueError(f"Duplicate quarter: {expected_quarter}")
        quarters_seen.add(expected_quarter)
        trips = load_trips(root / "data/raw" / entry["filename"], eligibility["virtual_station_id"])
        counts = trips.attrs["audit"]
        if counts["raw_rows"] != entry["row_count"]:
            raise AssertionError("Loaded raw row count does not match manifest")
        if not trips["start_time"].dt.to_period("Q").astype(str).eq(expected_quarter).all():
            raise ValueError(f"Trip start outside declared quarter: {entry['filename']}")
        annual.setdefault(year, Counter()).update(counts)
        quarterly.append({"quarter": expected_quarter, **counts})
        activity.append(activity_dates(trips))
        coordinate_frame = quarterly_coordinates(
            trips, spatial["projected_crs"], spatial["min_trips_per_quarter_coordinate"],
        )
        invalid_coordinates += coordinate_frame.attrs["invalid_coordinate_rows"]
        coordinates.append(coordinate_frame)
        weekly.append(trips.assign(week=trips.start_time.dt.to_period("W-SUN").dt.start_time).groupby(
            ["start_station", "week"]).size().rename("departures").reset_index().rename(
                columns={"start_station": "station_id"}))
        print(f"Audited {expected_quarter}: {len(trips):,} normalized trips", flush=True)
    if quarters_seen != {f"{year}Q{quarter}" for year in (2022, 2023, 2024) for quarter in range(1, 5)}:
        raise ValueError("Quarter coverage is not exactly 2022 Q1 through 2024 Q4")
    lifetimes = pd.concat(activity).groupby("station_id", as_index=False).agg(
        first_trip_date=("first_trip_date", "min"), last_trip_date=("last_trip_date", "max"),
        departure_trip_count=("departure_trip_count", "sum"), arrival_trip_count=("arrival_trip_count", "sum"),
    )
    lifetimes[["first_trip_date", "last_trip_date"]] = lifetimes[
        ["first_trip_date", "last_trip_date"]].apply(lambda column: column.dt.normalize())
    coordinate_frame = pd.concat(coordinates, ignore_index=True).sort_values(["station_id", "quarter"])
    relocation = detect_relocations(coordinate_frame, spatial["relocation_threshold_m"],
                                    spatial["min_trips_per_quarter_coordinate"])
    station_entry = station_files[0]
    stations = load_stations(root / "data/raw" / station_entry["filename"],
                             eligibility["virtual_station_id"])
    dates = reconcile_opening_dates(stations, lifetimes, study["control_exposure_start"],
                                    eligibility["opening_date_tolerance_days"])
    observed = dates.first_trip_date.notna()
    dates[["departure_trip_count", "arrival_trip_count"]] = dates[
        ["departure_trip_count", "arrival_trip_count"]].fillna(0).astype(int)
    missing_table = dates.loc[observed & dates.station_name.isna(), "station_id"].tolist()
    if missing_table:
        raise ValueError(f"Observed IDs absent from station table: {missing_table}")
    pairs, id_map, canonical = resolve_identities(dates, coordinate_frame, relocation, config)
    treatment_sources, exposure_sources = source_tables(canonical)
    locations = representative_positions(coordinate_frame, spatial["min_trips_per_quarter_coordinate"])
    evidence = dates.rename(columns={"station_id": "raw_station_id"}).merge(
        locations.reset_index().rename(columns={"station_id": "raw_station_id"}),
        on="raw_station_id", how="left", validate="one_to_one")
    evidence["has_known_position"] = np.isfinite(evidence.x_m) & np.isfinite(evidence.y_m)
    evidence = evidence.merge(id_map, on="raw_station_id", validate="one_to_one")
    roles = canonical[["station_id", "is_treatment_source", "is_exposure_source", "exposure_only",
                       "eligible_existing_identity"]].rename(columns={"station_id": "canonical_station_id"})
    evidence = evidence.merge(roles, on="canonical_station_id", validate="many_to_one")
    audit_ids = set(exposure_sources.loc[
        exposure_sources.exposure_only | exposure_sources.low_coordinate_support, "station_id"])
    audit_ids.update(pairs.loc[pairs.classification.isin(["missing_coordinates", "concurrent_operation"]),
                               "earlier_station_id"])
    independent = pairs.loc[pairs.classification.eq("new_after_unobserved_predecessor")]
    audit_ids.update(independent.earlier_station_id)
    audit_ids.update(independent.later_station_id)
    restored = sorted(set(independent.later_station_id) & set(treatment_sources.station_id))
    in_window = observed & dates.official_open_date.between(
        study["control_exposure_start"], study["control_exposure_end"])
    original_openings = dates.loc[observed & dates.analysis_open_date.between(
        study["control_exposure_start"], study["control_exposure_end"]),
        ["station_id", "station_name", "analysis_open_date"]].rename(columns={
            "station_id": "raw_station_id", "analysis_open_date": "raw_analysis_open_date"})
    screening = original_openings.merge(id_map, on="raw_station_id", validate="one_to_one")
    screening = screening.merge(canonical[["station_id", "analysis_open_date", "is_new_station_2022_2024"]],
                                 left_on="canonical_station_id", right_on="station_id",
                                 validate="many_to_one").drop(columns="station_id")
    screening["screening_result"] = "retained_new_station"
    screening.loc[screening.raw_station_id.ne(screening.canonical_station_id), "screening_result"] = (
        "merged_replacement")
    screening.loc[screening.identity_excluded, "screening_result"] = "excluded_identity"
    retained = canonical.loc[canonical.is_new_station_2022_2024]
    if int(screening.screening_result.eq("retained_new_station").sum()) != len(retained):
        raise AssertionError("Raw opening screening does not reconcile to canonical openings")
    raw_weekly = pd.concat(weekly, ignore_index=True)
    merged_weekly = merged_station_weeks(raw_weekly, id_map, study["panel_start"],
                                          study["last_complete_week_start"])
    relocation_full = dates[["station_id", "station_name"]].merge(
        relocation, on="station_id", how="left", validate="one_to_one")
    relocation_full["coordinate_status"] = relocation_full.coordinate_status.fillna("no_coordinates")
    named = pairs.found_by_name.astype(bool)
    cases = ("renumbered", "concurrent_operation", "interrupted_reopening", "relocated",
             "missing_coordinates", "missing_activity", "ambiguous_timeline",
             "new_after_unobserved_predecessor")
    counts_by_discovery = {}
    for discovery in ("name", "proximity_only"):
        counts = pairs.loc[pairs.discovery.eq(discovery), "classification"].value_counts()
        counts_by_discovery[discovery] = {case: int(counts.get(case, 0)) for case in cases}
    screening_counts = screening.screening_result.value_counts().to_dict()
    if len(original_openings) != sum(screening_counts.values()):
        raise AssertionError("Opening screening count is not conserved")
    summary = {
        "study_trip_years": [2022, 2023, 2024],
        "station_table": station_entry["filename"],
        "station_table_source_url": station_entry["source_url"],
        "annual_trip_counts": {year: dict(counts) for year, counts in sorted(annual.items())},
        "station_table_rows_including_virtual": station_entry["row_count"],
        "station_table_stations_excluding_virtual": len(stations),
        "observed_stations_excluding_virtual": len(lifetimes),
        "observed_ids_missing_from_station_table": missing_table,
        "date_cases_all_comparable_observed": dates.loc[observed, "date_case"].value_counts().to_dict(),
        "date_cases_official_openings_2022_2024": dates.loc[in_window, "date_case"].value_counts().to_dict(),
        "date_status_counts": dates.date_status.value_counts().to_dict(),
        "official_openings_by_year": {
            str(int(year)): int(count) for year, count in
            stations.official_open_date.dt.year.value_counts().sort_index().items() if pd.notna(year)
        },
        "manual_review_station_count": int(dates.manual_review_required.sum()),
        "relocation_flagged_station_count": int(relocation.relocated.sum()),
        "relocation_flagged_station_ids": relocation.loc[relocation.relocated, "station_id"].tolist(),
        "coordinate_status_counts": relocation_full.coordinate_status.value_counts().to_dict(),
        "invalid_departure_coordinate_rows": invalid_coordinates,
        "low_support_station_quarters": int((~coordinate_frame.coordinate_usable).sum()),
        "min_trips_per_quarter_coordinate": spatial["min_trips_per_quarter_coordinate"],
        "projected_crs": spatial["projected_crs"],
        "relocation_threshold_m": spatial["relocation_threshold_m"],
        "station_identity_candidate_pairs": len(pairs),
        "station_identity_name_pairs": int(named.sum()),
        "station_identity_additional_proximity_pairs": int((~named).sum()),
        "identity_pair_classification_counts": pairs.classification.value_counts().to_dict(),
        "identity_pair_counts_by_discovery": counts_by_discovery,
        "original_opening_ids_2022_2024": len(original_openings),
        "opening_id_screening_counts": screening_counts,
        "retained_physical_openings_2022_2024": len(retained),
        "retained_physical_openings_by_year": {
            str(int(year)): int(count) for year, count in
            retained.analysis_open_date.dt.year.value_counts().sort_index().items()
        },
        "retained_treatment_source_openings": int(canonical.is_treatment_source.sum()),
        "restored_independent_treatment_source_ids": restored,
        "other_eligible_treatment_sources": len(treatment_sources) - len(restored),
        "exposure_source_openings": len(exposure_sources),
        "eligible_exposure_sources_outside_treatment_window": int(
            (~exposure_sources.is_treatment_source & ~exposure_sources.exposure_only).sum()),
        "exposure_only_source_ids": exposure_sources.loc[exposure_sources.exposure_only, "station_id"].tolist(),
        "low_coordinate_support_source_ids": exposure_sources.loc[
            exposure_sources.low_coordinate_support, "station_id"].tolist(),
        "operating_openings_without_position": canonical.loc[
            canonical.is_exposure_candidate & ~canonical.is_exposure_source, "station_id"].tolist(),
        "source_role_audit_ids": sorted(audit_ids),
        "merged_raw_ids": int(id_map.canonical_station_id.ne(id_map.raw_station_id).sum()),
        "identity_mapping_rows": len(id_map),
        "canonical_station_rows": len(canonical),
        "ambiguous_predecessor_excluded_ids": int(
            id_map.reason.str.contains("ambiguous_multiple_predecessors").sum()),
        "identity_weekly_departures_sum": int(merged_weekly.departures.sum()),
        "identity_weekly_rows": len(merged_weekly),
        "runtime": {"python": platform.python_version(), "duckdb": duckdb.__version__,
                    "pandas": pd.__version__, "numpy": np.__version__, "pyproj": pyproj.__version__},
    }
    output = root / "reports/stage0"
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    tables = {"quarterly_counts": pd.DataFrame(quarterly), "opening_date_audit": dates,
              "opening_date_exceptions": dates.loc[dates.manual_review_required],
              "quarterly_coordinates": coordinate_frame, "relocation_audit": relocation_full,
              "station_identity_candidates": pairs, "station_id_map": id_map,
              "canonical_station_registry": canonical, "opening_identity_screening": screening,
              "new_stations": retained, "treatment_source_stations": treatment_sources,
              "exposure_source_stations": exposure_sources,
              "source_evidence_audit": evidence,
              "observed_sources_without_position": canonical.loc[
                  canonical.is_exposure_candidate & ~canonical.is_exposure_source]}
    for name, frame in tables.items():
        frame.to_csv(output / f"{name}.csv", index=False)
    interim = root / "data/interim"
    interim.mkdir(parents=True, exist_ok=True)
    merged_weekly.to_csv(interim / "identity_weekly_departures.csv", index=False)
    write_report(output, summary, config)
    print(json.dumps(summary, indent=2), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Verify local inputs without network")
    arguments = parser.parse_args()
    run(Path(__file__).resolve().parents[1], offline=arguments.offline)
