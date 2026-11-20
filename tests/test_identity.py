from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from stimpact.audit import detect_relocations
from stimpact.identity import (
    activity_dates,
    canonicalize_trips,
    classify_transition,
    identity_candidates,
    merged_station_weeks,
    resolve_identities,
    source_tables,
)


@pytest.fixture
def config():
    return yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text())


def inventory(ids=("1", "2"), names=("Old name", "New name"),
              openings=("2020-01-01", "2023-01-15"),
              first=("2022-01-01", "2023-01-15"), last=("2023-01-01", "2024-12-31")):
    first_dates = pd.to_datetime(first)
    return pd.DataFrame({"station_id": list(ids), "station_name": list(names),
                         "official_open_date": pd.to_datetime(openings),
                         "analysis_open_date": pd.to_datetime(openings),
                         "first_trip_date": first_dates, "last_trip_date": pd.to_datetime(last),
                         "departure_trip_count": [0 if pd.isna(date) else 1 for date in first_dates],
                         "arrival_trip_count": [0 if pd.isna(date) else 1 for date in first_dates]})


def positions(ids=("1", "2"), x=(0, 2), counts=(20, 20)):
    return pd.DataFrame({"station_id": list(ids), "quarter": ["2023Q1"] * len(ids),
                         "x_m": list(x), "y_m": [0] * len(ids), "coordinate_trip_count": list(counts)})


@pytest.mark.parametrize("distance,gap,expected", [
    (50, 14, "renumbered"), (50.001, 14, "relocated"),
    (49, 15, "interrupted_reopening"), (49, -14, "renumbered"),
    (49, -15, "concurrent_operation"), (np.nan, 0, "missing_coordinates"),
])
def test_transition_distance_gap_and_overlap_boundaries(config, distance, gap, expected):
    limits = config["identity"]
    first_new = pd.Timestamp("2023-01-01") + pd.Timedelta(days=gap)
    case, signed_gap, overlap = classify_transition(
        distance, "2022-01-01", "2023-01-01", first_new, "2024-12-31",
        distance_limit_m=limits["replacement_distance_m"], max_gap_days=limits["max_handoff_gap_days"],
        max_overlap_days=limits["max_overlap_days"],
    )
    assert case == expected
    assert signed_gap == gap
    assert overlap == max(0, -gap)


@pytest.mark.parametrize("old_open", ["2020-01-01", "2022-01-01"])
def test_renamed_replacement_can_be_found_without_a_name_match(config, old_open):
    stations = inventory(openings=(old_open, "2023-01-15"))
    result = identity_candidates(stations, positions(x=(0, 50)), config)
    assert len(result) == 1
    assert result.iloc[0].discovery == "proximity_only"
    assert result.iloc[0].classification == "renumbered"


def test_renamed_zero_distance_adjacent_dates_are_found_by_proximity(config):
    stations = inventory(last=("2023-01-14", "2024-12-31"))
    result = identity_candidates(stations, positions(x=(0, 0)), config)
    assert len(result) == 1
    pair = result.iloc[0]
    assert pair.earlier_station_name != pair.later_station_name
    assert not pair.found_by_name and pair.found_by_proximity
    assert pair.representative_distance_m == 0
    assert pair.handoff_gap_days == 1
    assert pair.classification == "renumbered"


@pytest.mark.parametrize("stop_offset,expected", [(-30, 1), (30, 1), (-31, 0), (31, 0)])
def test_proximity_retirement_window_boundary(config, stop_offset, expected):
    date = pd.Timestamp("2023-03-01")
    stations = inventory(openings=("2020-01-01", "2023-03-01"),
                         first=("2022-01-01", "2023-03-01"),
                         last=(date + pd.Timedelta(days=stop_offset), "2024-12-31"))
    assert len(identity_candidates(stations, positions(), config)) == expected


def test_name_and_spatial_discovery_do_not_double_count_a_pair(config):
    stations = inventory(names=(" Same Name ", "same name"))
    result = identity_candidates(stations, positions(), config)
    assert len(result) == 1
    assert result.iloc[0].found_by_name and result.iloc[0].found_by_proximity
    assert result.iloc[0].discovery == "name"


def test_missing_coordinates_exclude_both_ids_without_an_implicit_zero_distance(config):
    stations = inventory(names=("Same Name", "Same Name"))
    coords = positions(ids=("2",), x=(2,), counts=(20,))
    pairs, mapping, canonical = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    assert pairs.iloc[0].classification == "missing_coordinates"
    assert pd.isna(pairs.iloc[0].representative_distance_m)
    assert mapping.identity_excluded.all()
    assert not canonical.is_new_station_2022_2024.any()
    treatment, exposure = source_tables(canonical)
    assert treatment.empty
    assert exposure.station_id.tolist() == ["2"]
    assert exposure.iloc[0].exposure_only


def test_unobserved_old_id_does_not_pass_missing_coordinates_to_new_source(config):
    stations = inventory(names=("Same Name", "Same Name"), first=(None, "2023-01-15"),
                         last=(None, "2024-12-31"))
    coords = positions(ids=("2",), x=(2,), counts=(20,))
    pairs, mapping, canonical = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    assert pairs.iloc[0].classification == "new_after_unobserved_predecessor"
    assert pairs.iloc[0].action == "keep_new_id"
    assert mapping.set_index("raw_station_id").loc["2", "canonical_station_id"] == "2"
    new = canonical.set_index("station_id").loc["2"]
    assert not new.identity_excluded
    assert new.identity_exclusion_reason == ""
    assert new.analysis_open_date == pd.Timestamp("2023-01-15")
    treatment, exposure = source_tables(canonical)
    assert treatment.station_id.tolist() == exposure.station_id.tolist() == ["2"]


def test_arrival_only_old_id_is_not_a_zero_activity_predecessor(config):
    stations = inventory(names=("Same Name", "Same Name"))
    stations.loc[0, "departure_trip_count"] = 0
    coords = positions(ids=("2",), x=(2,), counts=(20,))
    pairs, _, _ = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    assert pairs.iloc[0].classification == "missing_coordinates"


def test_merge_keeps_old_opening_and_remaps_both_endpoints_without_dropping_trips(config):
    stations = inventory()
    coords = positions()
    _, mapping, canonical = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    assert mapping.canonical_station_id.tolist() == ["1", "1"]
    assert canonical.iloc[0].analysis_open_date == pd.Timestamp("2020-01-01")
    assert not canonical.iloc[0].is_new_station_2022_2024
    trips = pd.DataFrame({"start_station": ["1", "2"], "end_station": ["2", "1"]})
    result = canonicalize_trips(trips, mapping)
    assert len(result) == len(trips)
    assert result.start_station.eq("1").all() and result.end_station.eq("1").all()


def test_interruption_merges_and_preserves_zero_weeks(config):
    stations = inventory(names=("Same", "Same"), last=("2022-03-01", "2024-12-31"))
    coords = positions()
    pairs, mapping, _ = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    assert pairs.iloc[0].classification == "interrupted_reopening"
    weekly = pd.DataFrame({"station_id": ["1", "2"],
                           "week": pd.to_datetime(["2022-02-28", "2023-01-16"]), "departures": [7, 9]})
    result = merged_station_weeks(weekly, mapping, "2022-02-28", "2023-01-16")
    assert result.station_id.nunique() == 1
    assert len(result) == 47
    assert result.iloc[1:-1].departures.eq(0).all()
    assert result.departures.sum() == 16


@pytest.mark.parametrize("distance,last_old,case", [
    (51, "2023-01-01", "relocated"), (2, "2023-03-01", "concurrent_operation"),
])
def test_moving_or_concurrent_ids_never_enter_either_pool(config, distance, last_old, case):
    stations = inventory(names=("Same", "Same"), last=(last_old, "2024-12-31"))
    coords = positions(x=(0, distance))
    pairs, mapping, canonical = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    assert pairs.iloc[0].classification == case
    assert mapping.identity_excluded.all()
    assert not canonical.eligible_existing_identity.any()
    assert not canonical.is_new_station_2022_2024.any()


def test_merge_chains_resolve_to_earliest_id(config):
    stations = inventory(ids=("1", "2", "3"), names=("Same",) * 3,
                         openings=("2021-01-01", "2022-06-02", "2023-01-02"),
                         first=("2022-01-01", "2022-06-02", "2023-01-02"),
                         last=("2022-06-01", "2023-01-01", "2024-12-31"))
    coords = positions(ids=("1", "2", "3"), x=(0, 1, 2), counts=(20,) * 3)
    _, mapping, canonical = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    assert mapping.canonical_station_id.eq("1").all()
    assert not mapping.identity_excluded.any()
    assert len(canonical) == 1


def test_concurrent_exclusion_propagates_through_a_merge_chain(config):
    stations = inventory(ids=("1", "2", "3"), names=("Same",) * 3,
                         openings=("2021-01-01", "2022-06-02", "2023-01-01"),
                         first=("2022-01-01", "2022-06-02", "2023-01-01"),
                         last=("2022-06-01", "2024-12-31", "2024-12-31"))
    coords = positions(ids=("1", "2", "3"), x=(0, 1, 2), counts=(20,) * 3)
    _, mapping, canonical = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    assert mapping.identity_excluded.all()
    assert canonical.identity_exclusion_reason.str.contains("concurrent_operation").all()


def test_conflicting_predecessors_are_excluded_without_fusing_distinct_stations(config):
    stations = inventory(ids=("1", "2", "3"), names=("A", "B", "C"),
                         openings=("2020-01-01", "2021-01-01", "2023-01-02"),
                         first=("2022-01-01", "2022-01-01", "2023-01-02"),
                         last=("2023-01-01", "2023-01-01", "2024-12-31"))
    coords = positions(ids=("1", "2", "3"), x=(0, 80, 40), counts=(20,) * 3)
    _, mapping, _ = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    assert mapping.identity_excluded.all()
    assert mapping.canonical_station_id.tolist() == ["1", "2", "3"]
    assert mapping.reason.str.contains("ambiguous_multiple_predecessors").all()


def test_first_and_last_activity_include_arrivals():
    trips = pd.DataFrame({"start_station": ["1"], "end_station": ["2"],
                          "start_time": pd.to_datetime(["2023-01-01 23:59"]),
                          "end_time": pd.to_datetime(["2023-01-02 00:01"])})
    result = activity_dates(trips).set_index("station_id")
    assert result.loc["2", "last_trip_date"] == pd.Timestamp("2023-01-02 00:01")
    assert result.loc["1", "departure_trip_count"] == 1
    assert result.loc["2", "arrival_trip_count"] == 1


def test_low_support_location_is_retained_for_treatment_and_exposure(config):
    stations = inventory(ids=("2",), names=("New site",), openings=("2023-01-15",),
                         first=("2023-01-15",), last=("2024-12-31",))
    coords = positions(ids=("2",), x=(0,), counts=(11,))
    _, _, canonical = resolve_identities(stations, coords, detect_relocations(coords, 50), config)
    treatment, exposure = source_tables(canonical)
    assert not canonical.iloc[0].identity_excluded
    assert canonical.iloc[0].low_coordinate_support
    assert canonical.iloc[0].position_coordinate_records == 11
    assert treatment.station_id.tolist() == exposure.station_id.tolist() == ["2"]


def test_operating_unlocated_source_blocks_clean_source_construction():
    canonical = pd.DataFrame({"station_id": ["2"], "is_treatment_source": [False],
                              "is_exposure_source": [False], "is_exposure_candidate": [True]})
    with pytest.raises(ValueError, match="Operating opening IDs lack a known position: 2"):
        source_tables(canonical)
