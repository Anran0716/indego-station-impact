import numpy as np
import pandas as pd
import pytest

from stimpact.audit import (
    detect_relocations,
    quarterly_coordinates,
    reconcile_opening_dates,
    station_identity_candidates,
)


@pytest.mark.parametrize("gap,case,use_official", [
    (-14, "first_trip_earlier", False), (-1, "first_trip_earlier", False),
    (0, "within_tolerance", True), (14, "within_tolerance", True),
    (15, "first_trip_late_review", False),
])
def test_opening_date_cases_and_boundary(gap, case, use_official):
    official = pd.Timestamp("2023-05-01")
    first = official + pd.Timedelta(days=gap)
    stations = pd.DataFrame({"station_id": ["1"], "official_open_date": [official]})
    first_seen = pd.DataFrame({"station_id": ["1"], "first_trip_date": [first]})
    result = reconcile_opening_dates(stations, first_seen, "2022-01-01").iloc[0]
    assert result["date_case"] == case
    if gap > 14:
        assert pd.isna(result["analysis_open_date"])
        assert result["manual_review_required"]
    else:
        assert result["analysis_open_date"] == (official if use_official else first)


def test_legacy_station_is_left_censored():
    official = pd.Timestamp("2015-04-23")
    stations = pd.DataFrame({"station_id": ["1"], "official_open_date": [official]})
    first = pd.DataFrame({"station_id": ["1"], "first_trip_date": [pd.Timestamp("2022-01-01")]})
    result = reconcile_opening_dates(stations, first, "2022-01-01").iloc[0]
    assert result["date_status"] == "left_censored_pre_window"
    assert result["analysis_open_date"] == official
    assert not result["manual_review_required"]


@pytest.mark.parametrize("distance,relocated", [(49, False), (50, False), (50.001, True)])
def test_relocation_strict_boundary(distance, relocated):
    coordinates = pd.DataFrame({"station_id": ["1", "1"], "quarter": ["2022Q1", "2022Q2"],
                                "x_m": [0, distance], "y_m": [0, 0]})
    result = detect_relocations(coordinates, 50).iloc[0]
    assert bool(result["relocated"]) == relocated


def test_relocation_checks_nonadjacent_quarters():
    coordinates = pd.DataFrame({"station_id": ["1"] * 3, "quarter": ["Q1", "Q2", "Q3"],
                                "x_m": [0, 30, 60], "y_m": [0, 0, 0]})
    result = detect_relocations(coordinates, 50).iloc[0]
    assert result["relocated"]
    assert result["max_displacement_m"] == 60


def test_zero_and_missing_coordinate_pairs_do_not_change_medians():
    trips = pd.DataFrame({"start_station": ["1"] * 5,
                          "start_time": pd.to_datetime(["2022-01-01"] * 5),
                          "start_lat": [39.94, 39.96, 0, np.nan, 39.90],
                          "start_lon": [-75.16, -75.18, -75.16, -75.16, 0]})
    result = quarterly_coordinates(trips, "EPSG:32618")
    assert result.iloc[0]["latitude"] == pytest.approx(39.95)
    assert result.iloc[0]["longitude"] == pytest.approx(-75.17)
    assert result.iloc[0]["coordinate_trip_count"] == 2
    assert result.attrs["invalid_coordinate_rows"] == 3


def test_name_reuse_is_a_review_candidate_and_future_ids_are_excluded():
    stations = pd.DataFrame({"station_id": ["1", "2", "3"],
                             "station_name": ["Ridge & Ferry ", "ridge & ferry", "Ridge & Ferry"],
                             "official_open_date": pd.to_datetime(
                                 ["2021-01-01", "2023-01-01", "2025-01-01"])})
    coordinates = pd.DataFrame({"station_id": ["1", "1", "2", "3"],
                                "x_m": [0, 0, 2, 3], "y_m": [0, 0, 0, 0]})
    result = station_identity_candidates(stations, coordinates, "2022-01-01", "2024-12-31")
    assert len(result) == 1
    assert result.iloc[0]["earlier_station_id"] == "1"
    assert result.iloc[0]["later_station_id"] == "2"
    assert result.iloc[0]["representative_distance_m"] == 2
    assert result.iloc[0]["review_status"] == "unresolved_possible_replacement"
    assert len(stations) == 3
