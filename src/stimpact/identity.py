"""Resolve station-ID transitions before defining physical openings or station pools."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from stimpact.audit import (
    position_coordinates,
    representative_positions,
    station_identity_candidates,
    trusted_coordinates,
)

MERGE_CASES = {"renumbered", "interrupted_reopening"}
INDEPENDENT_NEW_CASE = "new_after_unobserved_predecessor"


def activity_dates(trips: pd.DataFrame) -> pd.DataFrame:
    observations = pd.concat([
        trips[["start_station", "start_time"]].rename(
            columns={"start_station": "station_id", "start_time": "time"}),
        trips[["end_station", "end_time"]].rename(
            columns={"end_station": "station_id", "end_time": "time"}),
    ], ignore_index=True)
    result = observations.groupby("station_id")["time"].agg(
        first_trip_date="min", last_trip_date="max",
    ).reset_index()
    result["departure_trip_count"] = result.station_id.map(trips.start_station.value_counts()).fillna(0).astype(int)
    result["arrival_trip_count"] = result.station_id.map(trips.end_station.value_counts()).fillna(0).astype(int)
    return result


def classify_transition(distance_m: float, old_first, old_last, new_first, new_last,
                        *, distance_limit_m: float, max_gap_days: int,
                        max_overlap_days: int, old_departure_trip_count: int | None = None,
                        old_arrival_trip_count: int | None = None) -> tuple[str, float, float]:
    dates = [pd.Timestamp(value).normalize() if pd.notna(value) else pd.NaT
             for value in (old_first, old_last, new_first, new_last)]
    first_old, last_old, first_new, last_new = dates
    gap = float((first_new - last_old).days) if pd.notna(first_new) and pd.notna(last_old) else np.nan
    overlap = (float(max(0, (min(last_old, last_new) - max(first_old, first_new)).days))
               if all(pd.notna(value) for value in dates) else np.nan)
    if old_departure_trip_count is not None and old_arrival_trip_count is not None:
        if old_departure_trip_count + old_arrival_trip_count == 0:
            if pd.notna(first_old) or pd.notna(last_old):
                raise ValueError("Zero-activity predecessor has inconsistent observed trip dates")
            return INDEPENDENT_NEW_CASE, gap, overlap
    if not np.isfinite(distance_m):
        return "missing_coordinates", gap, overlap
    if distance_m > distance_limit_m:
        return "relocated", gap, overlap
    if any(pd.isna(value) for value in dates):
        return "missing_activity", gap, overlap
    if overlap > max_overlap_days:
        return "concurrent_operation", gap, overlap
    if abs(gap) <= max_gap_days:
        return "renumbered", gap, overlap
    if gap > max_gap_days:
        return "interrupted_reopening", gap, overlap
    return "ambiguous_timeline", gap, overlap


def identity_candidates(stations: pd.DataFrame, coordinates: pd.DataFrame, config: dict) -> pd.DataFrame:
    spatial, identity, study = config["spatial"], config["identity"], config["study"]
    minimum = spatial["min_trips_per_quarter_coordinate"]
    named = station_identity_candidates(stations, coordinates, study["control_exposure_start"],
                                        study["control_exposure_end"], minimum)
    centers = representative_positions(coordinates, minimum)[["x_m", "y_m"]]
    inventory = stations.merge(centers, on="station_id", how="left", validate="one_to_one")
    lookup = inventory.set_index("station_id")
    pairs = {(row.earlier_station_id, row.later_station_id): {
        "found_by_name": True, "found_by_proximity": False,
    } for row in named.itertuples()}
    new_ids = inventory.loc[inventory["analysis_open_date"].between(
        study["control_exposure_start"], study["control_exposure_end"])]
    for later in new_ids.itertuples():
        if pd.isna(later.x_m) or pd.isna(later.y_m):
            continue
        for earlier in inventory.itertuples():
            if earlier.station_id == later.station_id or not (
                earlier.official_open_date < later.official_open_date
            ):
                continue
            distance = float(np.hypot(later.x_m - earlier.x_m, later.y_m - earlier.y_m))
            if not np.isfinite(distance) or distance > identity["replacement_distance_m"]:
                continue
            if pd.isna(earlier.last_trip_date):
                continue
            stop_gap = abs((pd.Timestamp(earlier.last_trip_date).normalize()
                            - pd.Timestamp(later.analysis_open_date).normalize()).days)
            if stop_gap > identity["proximity_retirement_window_days"]:
                continue
            pair = pairs.setdefault((earlier.station_id, later.station_id), {
                "found_by_name": False, "found_by_proximity": False,
            })
            pair["found_by_proximity"] = True
    records = []
    for (old_id, new_id), discovery in sorted(pairs.items()):
        old, new = lookup.loc[old_id], lookup.loc[new_id]
        distance = float(np.hypot(new.x_m - old.x_m, new.y_m - old.y_m))
        case, gap, overlap = classify_transition(
            distance, old.first_trip_date, old.last_trip_date, new.first_trip_date, new.last_trip_date,
            distance_limit_m=identity["replacement_distance_m"],
            max_gap_days=identity["max_handoff_gap_days"], max_overlap_days=identity["max_overlap_days"],
            old_departure_trip_count=old.get("departure_trip_count"),
            old_arrival_trip_count=old.get("arrival_trip_count"),
        )
        records.append({"earlier_station_id": old_id, "later_station_id": new_id,
                        "earlier_station_name": old.station_name, "later_station_name": new.station_name,
                        "earlier_open_date": old.official_open_date,
                        "later_open_date": new.official_open_date,
                        "earlier_first_trip_date": old.first_trip_date,
                        "earlier_last_trip_date": old.last_trip_date,
                        "earlier_departure_trip_count": old.get("departure_trip_count"),
                        "earlier_arrival_trip_count": old.get("arrival_trip_count"),
                        "later_first_trip_date": new.first_trip_date,
                        "later_last_trip_date": new.last_trip_date,
                        "representative_distance_m": distance, "handoff_gap_days": gap,
                        "overlap_days": overlap, **discovery,
                        "discovery": "name" if discovery["found_by_name"] else "proximity_only",
                        "classification": case,
                        "action": ("merge_to_earlier_id" if case in MERGE_CASES else
                                   "keep_new_id" if case == INDEPENDENT_NEW_CASE else "exclude_both"),
                        "reason": "" if case == INDEPENDENT_NEW_CASE else case})
    columns = ["earlier_station_id", "later_station_id", "earlier_station_name", "later_station_name",
               "earlier_open_date", "later_open_date", "earlier_first_trip_date", "earlier_last_trip_date",
               "earlier_departure_trip_count", "earlier_arrival_trip_count",
               "later_first_trip_date", "later_last_trip_date", "representative_distance_m",
               "handoff_gap_days", "overlap_days", "found_by_name", "found_by_proximity", "discovery",
               "classification", "action", "reason"]
    return pd.DataFrame(records, columns=columns)


def resolve_identities(stations: pd.DataFrame, coordinates: pd.DataFrame,
                       relocation: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return pair decisions, a total ID map, and one row per canonical station."""
    pairs = identity_candidates(stations, coordinates, config)
    parent = {station_id: station_id for station_id in stations["station_id"]}
    lookup = stations.set_index("station_id")

    def find(station_id):
        while parent[station_id] != station_id:
            parent[station_id] = parent[parent[station_id]]
            station_id = parent[station_id]
        return station_id

    def priority(station_id):
        date = lookup.loc[station_id, "official_open_date"]
        return (date if pd.notna(date) else pd.Timestamp.max, int(station_id))

    adjacency = defaultdict(set)
    predecessors = defaultdict(set)
    exclusions = defaultdict(set)
    for pair in pairs.itertuples():
        old_id, new_id = pair.earlier_station_id, pair.later_station_id
        if pair.classification == INDEPENDENT_NEW_CASE:
            continue
        if pair.classification in MERGE_CASES:
            roots = sorted({find(old_id), find(new_id)}, key=priority)
            for other in roots[1:]:
                parent[other] = roots[0]
            adjacency[old_id].add(new_id)
            adjacency[new_id].add(old_id)
            predecessors[new_id].add(old_id)
        else:
            exclusions[old_id].add(pair.classification)
            exclusions[new_id].add(pair.classification)
    for target, previous in predecessors.items():
        if len(previous) < 2:
            continue
        visited, pending = set(), [next(iter(previous))]
        while pending:
            node = pending.pop()
            if node in visited or node == target:
                continue
            visited.add(node)
            pending.extend(adjacency[node] - visited - {target})
        if not previous <= visited:
            exclusions[target].add("ambiguous_multiple_predecessors")
    for row in relocation.itertuples():
        if row.relocated:
            exclusions[row.station_id].add("within_id_relocation")
    minimum = config["spatial"]["min_trips_per_quarter_coordinate"]
    trusted = trusted_coordinates(coordinates, minimum)
    positioned = position_coordinates(coordinates, minimum)
    centers = representative_positions(coordinates, minimum)
    for station in stations.itertuples():
        if pd.isna(station.first_trip_date):
            exclusions[station.station_id].add("unobserved_in_trip_window")
        elif station.station_id not in centers.index:
            exclusions[station.station_id].add("missing_coordinates")
        if pd.isna(station.analysis_open_date):
            exclusions[station.station_id].add("unresolved_opening_date")
    components = defaultdict(list)
    for station_id in parent:
        components[find(station_id)].append(station_id)
    resolved_components = {}
    for canonical_id, members in components.items():
        if any("ambiguous_multiple_predecessors" in exclusions[station_id] for station_id in members):
            for station_id in members:
                exclusions[station_id].add("ambiguous_multiple_predecessors")
                resolved_components[station_id] = [station_id]
        else:
            resolved_components[canonical_id] = members
    records, mapping = [], []
    study = config["study"]
    for canonical_id, members in sorted(resolved_components.items()):
        rows = lookup.loc[members]
        reasons = set().union(*(exclusions[station_id] for station_id in members))
        component_points = trusted.loc[trusted.station_id.isin(members), ["x_m", "y_m"]].to_numpy()
        if len(component_points):
            maximum = float(np.linalg.norm(
                component_points[:, None, :] - component_points[None, :, :], axis=2).max())
            if maximum > config["spatial"]["relocation_threshold_m"]:
                reasons.add("canonical_coordinate_displacement")
        else:
            maximum = np.nan
        # A low-support position is retained, but cannot create a relocation flag.
        position_rows = positioned.loc[positioned.station_id.isin(members)]
        if len(position_rows):
            x_m, y_m = position_rows[["x_m", "y_m"]].median()
        else:
            x_m, y_m = np.nan, np.nan
        low_support = len(position_rows) > 0 and len(component_points) == 0
        excluded = bool(reasons)
        opening = rows.analysis_open_date.min()
        observed = rows.first_trip_date.notna().any()
        new = (not excluded and observed and pd.notna(opening)
               and pd.Timestamp(study["control_exposure_start"]) <= opening
               <= pd.Timestamp(study["control_exposure_end"]))
        source = (new and pd.Timestamp(study["treatment_opening_start"]) <= opening
                  <= pd.Timestamp(study["treatment_opening_end"]))
        exposure_candidate = (observed and pd.notna(opening)
                              and pd.Timestamp(study["control_exposure_start"]) <= opening
                              <= pd.Timestamp(study["control_exposure_end"]))
        exposure = exposure_candidate and np.isfinite(x_m) and np.isfinite(y_m)
        reason = ";".join(sorted(reasons))
        records.append({"station_id": canonical_id, "station_name": lookup.loc[canonical_id, "station_name"],
                        "member_ids": ";".join(sorted(members, key=int)), "member_count": len(members),
                        "analysis_open_date": opening, "first_trip_date": rows.first_trip_date.min(),
                        "last_trip_date": rows.last_trip_date.max(), "x_m": x_m, "y_m": y_m,
                        "low_coordinate_support": low_support,
                        "position_coordinate_records": int(position_rows.coordinate_trip_count.sum()),
                        "departure_trip_count": int(rows.departure_trip_count.sum())
                        if "departure_trip_count" in rows else None,
                        "arrival_trip_count": int(rows.arrival_trip_count.sum())
                        if "arrival_trip_count" in rows else None,
                        "max_coordinate_displacement_m": maximum, "identity_excluded": excluded,
                        "identity_exclusion_reason": reason, "is_new_station_2022_2024": new,
                        "is_treatment_source": source,
                        "is_exposure_candidate": exposure_candidate,
                        "is_exposure_source": exposure,
                        "exposure_only": exposure and excluded,
                        "eligible_existing_identity": not excluded and pd.notna(opening)
                        and opening < pd.Timestamp(study["existing_station_opened_before"])})
        for station_id in members:
            mapping.append({"raw_station_id": station_id, "canonical_station_id": canonical_id,
                            "identity_excluded": excluded, "reason": reason,
                            "action": "excluded" if excluded else (
                                "kept" if station_id == canonical_id else "merged")})
    id_map = pd.DataFrame(mapping).sort_values("raw_station_id")
    if id_map.raw_station_id.duplicated().any() or len(id_map) != len(stations):
        raise AssertionError("Identity map is not one row per raw ID")
    if not set(id_map.canonical_station_id) <= set(id_map.raw_station_id):
        raise AssertionError("Canonical ID is absent from source inventory")
    canonical = pd.DataFrame(records)
    # Every decision carries the final component status, including propagated exclusions.
    status = id_map.set_index("raw_station_id")
    pairs["earlier_final_excluded"] = pairs.earlier_station_id.map(status.identity_excluded)
    pairs["later_final_excluded"] = pairs.later_station_id.map(status.identity_excluded)
    pairs["final_component_reason"] = pairs.later_station_id.map(status.reason)
    return pairs, id_map, canonical


def source_tables(canonical: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Treatment eligibility never determines whether an operating site counts as exposure."""
    treatment = canonical.loc[canonical.is_treatment_source].copy()
    exposure = canonical.loc[canonical.is_exposure_source].copy()
    unknown = canonical.loc[canonical.is_exposure_candidate & ~canonical.is_exposure_source]
    if not unknown.empty:
        raise ValueError("Operating opening IDs lack a known position: "
                         + ", ".join(unknown.station_id.astype(str)))
    if not set(treatment.station_id) <= set(exposure.station_id):
        raise AssertionError("A treatment source is missing from exposure sources")
    if exposure[["x_m", "y_m"]].isna().any().any() or exposure.first_trip_date.isna().any():
        raise AssertionError("Exposure sources require observed operation and a known position")
    return treatment, exposure


def canonicalize_trips(trips: pd.DataFrame, id_map: pd.DataFrame) -> pd.DataFrame:
    if id_map.raw_station_id.duplicated().any():
        raise ValueError("Duplicate raw ID in station identity map")
    mapping = id_map.set_index("raw_station_id").canonical_station_id
    result = trips.copy()
    for column in ("start_station", "end_station"):
        converted = result[column].map(mapping)
        if converted.isna().any():
            raise ValueError(f"Unmapped station ID in {column}")
        result[column] = converted.astype("string")
    if len(result) != len(trips):
        raise AssertionError("Trip count changed during identity remapping")
    return result


def merged_station_weeks(weekly_counts: pd.DataFrame, id_map: pd.DataFrame,
                          first_week: str, last_week: str) -> pd.DataFrame:
    """Merge raw-ID departures and retain zeros through identity handoff gaps."""
    mapping = id_map.set_index("raw_station_id").canonical_station_id
    frame = weekly_counts.copy()
    frame["station_id"] = frame.station_id.map(mapping)
    if frame.station_id.isna().any():
        raise ValueError("Unmapped ID in weekly activity")
    frame = frame.loc[frame.week.between(pd.Timestamp(first_week), pd.Timestamp(last_week))]
    grouped = frame.groupby(["station_id", "week"])["departures"].sum()
    grid = pd.MultiIndex.from_product([
        sorted(id_map.canonical_station_id.unique()), pd.date_range(first_week, last_week, freq="7D"),
    ], names=["station_id", "week"])
    result = grouped.reindex(grid, fill_value=0).rename("departures").reset_index()
    if int(result.departures.sum()) != int(frame.departures.sum()):
        raise AssertionError("Departure count changed during identity merging or zero filling")
    return result
