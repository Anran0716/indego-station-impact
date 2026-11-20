"""Audit station opening dates and station-quarter coordinates without estimating effects."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer


def reconcile_opening_dates(stations: pd.DataFrame, first_seen: pd.DataFrame,
                            observation_start: str, tolerance_days: int = 14) -> pd.DataFrame:
    """Earlier first trips take precedence; late evidence is left-censored for legacy stations."""
    result = stations.merge(first_seen, on="station_id", how="outer", validate="one_to_one")
    first = pd.to_datetime(result["first_trip_date"]).dt.normalize()
    official = pd.to_datetime(result["official_open_date"]).dt.normalize()
    delta = (first - official).dt.days
    both = first.notna() & official.notna()
    early = both & (delta < 0)
    within = both & delta.between(0, tolerance_days)
    late = both & (delta > tolerance_days)
    result["first_trip_date"] = first
    result["date_gap_days"] = delta
    result["date_case"] = "not_comparable"
    result.loc[early, "date_case"] = "first_trip_earlier"
    result.loc[within, "date_case"] = "within_tolerance"
    result.loc[late, "date_case"] = "first_trip_late_review"
    result["date_status"] = result["date_case"]
    left_censored = late & (official < pd.Timestamp(observation_start))
    result.loc[left_censored, "date_status"] = "left_censored_pre_window"
    result.loc[first.isna(), "date_status"] = "unobserved_in_trip_window"
    result.loc[official.isna(), "date_status"] = "missing_official_date"
    result["analysis_open_date"] = pd.NaT
    use_official = within | left_censored
    result.loc[use_official, "analysis_open_date"] = official.loc[use_official]
    result.loc[early, "analysis_open_date"] = first.loc[early]
    # Unobserved table stations keep their official dates, but cannot enter old-station analysis.
    unobserved = first.isna() & official.notna()
    result.loc[unobserved, "analysis_open_date"] = official.loc[unobserved]
    result["manual_review_required"] = (late & ~left_censored) | official.isna()
    return result


def quarterly_coordinates(trips: pd.DataFrame, projected_crs: str) -> pd.DataFrame:
    """Use paired valid departure coordinates; zero/missing pairs never enter medians."""
    valid = (trips["start_lat"].between(-90, 90) & trips["start_lon"].between(-180, 180)
             & trips["start_lat"].ne(0) & trips["start_lon"].ne(0))
    frame = trips.loc[valid, ["start_station", "start_time", "start_lat", "start_lon"]].copy()
    frame["quarter"] = frame["start_time"].dt.to_period("Q").astype(str)
    result = frame.groupby(["start_station", "quarter"], as_index=False).agg(
        latitude=("start_lat", "median"), longitude=("start_lon", "median"),
        coordinate_trip_count=("start_lat", "size"),
    ).rename(columns={"start_station": "station_id"})
    transformer = Transformer.from_crs("EPSG:4326", projected_crs, always_xy=True)
    result["x_m"], result["y_m"] = transformer.transform(result["longitude"].to_numpy(),
                                                       result["latitude"].to_numpy())
    result.attrs["invalid_coordinate_rows"] = int((~valid).sum())
    return result


def detect_relocations(coordinates: pd.DataFrame, threshold_m: float) -> pd.DataFrame:
    """Flag a station when any pair of quarterly medians is more than the threshold apart."""
    records = []
    for station_id, rows in coordinates.groupby("station_id", sort=True):
        points = rows[["x_m", "y_m"]].to_numpy()
        distances = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
        left, right = np.unravel_index(np.argmax(distances), distances.shape)
        maximum = float(distances[left, right])
        support = (int(min(rows.iloc[left]["coordinate_trip_count"],
                           rows.iloc[right]["coordinate_trip_count"]))
                   if "coordinate_trip_count" in rows else None)
        records.append({"station_id": station_id, "quarters_observed": len(rows),
                        "max_displacement_m": maximum, "relocated": maximum > threshold_m,
                        "quarter_a": rows.iloc[left]["quarter"],
                        "quarter_b": rows.iloc[right]["quarter"],
                        "min_trip_count_in_max_pair": support,
                        "coordinate_status": "insufficient_quarters" if len(rows) < 2 else "audited"})
    return pd.DataFrame(records)


def station_identity_candidates(stations: pd.DataFrame, coordinates: pd.DataFrame,
                                opening_start: str, opening_end: str) -> pd.DataFrame:
    """List repeated-name IDs for review; never automatically merge or drop stations."""
    centers = coordinates.groupby("station_id")[["x_m", "y_m"]].median()
    inventory = stations.merge(centers, on="station_id", how="left", validate="one_to_one")
    inventory["name_key"] = inventory["station_name"].str.strip().str.casefold()
    columns = ["station_name", "earlier_station_id", "later_station_id", "earlier_open_date",
               "later_open_date", "representative_distance_m", "review_status"]
    records = []
    for _, group in inventory.groupby("name_key"):
        rows = group.sort_values(["official_open_date", "station_id"])
        for index in range(1, len(rows)):
            later = rows.iloc[index]
            if pd.isna(later["official_open_date"]) or not (
                pd.Timestamp(opening_start) <= later["official_open_date"] <= pd.Timestamp(opening_end)
            ):
                continue
            for _, earlier in rows.iloc[:index].iterrows():
                distance = float(np.hypot(later["x_m"] - earlier["x_m"],
                                          later["y_m"] - earlier["y_m"]))
                records.append({"station_name": later["station_name"].strip(),
                                "earlier_station_id": earlier["station_id"],
                                "later_station_id": later["station_id"],
                                "earlier_open_date": earlier["official_open_date"],
                                "later_open_date": later["official_open_date"],
                                "representative_distance_m": distance,
                                "review_status": "unresolved_possible_replacement"})
    return pd.DataFrame(records, columns=columns)
