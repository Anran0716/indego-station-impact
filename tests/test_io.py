import csv

import pandas as pd
import pytest

from stimpact.io import load_stations, load_trips


@pytest.fixture
def trip_row():
    return {"trip_id": "1", "duration": "2", "start_time": "1/1/2022 0:01",
            "end_time": "1/1/2022 0:03", "start_station": "03004.0", "end_station": "3005",
            "start_lat": "39.95", "start_lon": "-75.16", "end_lat": "39.96", "end_lon": "-75.17"}


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.mark.parametrize("aliases,iso", [(False, False), (True, True)])
def test_schema_and_datetime_variants(tmp_path, trip_row, aliases, iso):
    if iso:
        trip_row.update(start_time="2022-01-01T00:01:00", end_time="2022-01-01 00:03:00")
    if aliases:
        trip_row = {key.replace("_", " ").title(): value for key, value in trip_row.items()}
        trip_row["Start Station ID"] = trip_row.pop("Start Station")
    result = load_trips(write_csv(tmp_path / "trips.csv", [trip_row]))
    assert result.loc[0, "start_station"] == "3004"
    assert result.loc[0, "start_time"] == pd.Timestamp("2022-01-01 00:01")
    assert result.loc[0, "duration_seconds"] == 120


def test_unknown_schema_fails(tmp_path, trip_row):
    trip_row["mystery_column"] = "not silently discarded"
    with pytest.raises(ValueError, match="Unrecognized schema"):
        load_trips(write_csv(tmp_path / "trips.csv", [trip_row]))


def test_unknown_datetime_fails(tmp_path, trip_row):
    trip_row["start_time"] = "yesterday"
    with pytest.raises(ValueError, match="datetime"):
        load_trips(write_csv(tmp_path / "trips.csv", [trip_row]))


def test_virtual_and_missing_endpoint_exclusions_are_counted(tmp_path, trip_row):
    rows = [trip_row, {**trip_row, "start_station": "3000.0"},
            {**trip_row, "end_station": ""}, {**trip_row, "end_station": "3000"}]
    result = load_trips(write_csv(tmp_path / "trips.csv", rows))
    assert len(result) == 1
    assert result.attrs["audit"] == {"raw_rows": 4, "missing_station_rows": 1,
                                     "virtual_station_rows": 2, "retained_rows": 1}


def test_current_station_header_and_blank_records(tmp_path):
    rows = [
        {"Station_ID": "3000", "Station_Name": "Virtual", "Day of Go_live_date": "4/23/2015",
         "Status": "Active"},
        {"Station_ID": "3004", "Station_Name": "Old", "Day of Go_live_date": "4/23/2015",
         "Status": "Active"},
        {"Station_ID": "3005", "Station_Name": "New", "Day of Go_live_date": "2023-04-01",
         "Status": "Active"},
        {"Station_ID": "", "Station_Name": "", "Day of Go_live_date": "", "Status": ""},
    ]
    result = load_stations(write_csv(tmp_path / "stations.csv", rows))
    assert result["station_id"].tolist() == ["3004", "3005"]
    assert result["official_open_date"].tolist() == [pd.Timestamp("2015-04-23"),
                                                    pd.Timestamp("2023-04-01")]


def test_duplicate_station_table_ids_fail(tmp_path):
    row = {"Station_ID": "3004", "Station_Name": "Old", "Day of Go_live_date": "4/23/2015",
           "Status": "Active"}
    with pytest.raises(ValueError, match="duplicate station ID"):
        load_stations(write_csv(tmp_path / "stations.csv", [row, row]))


def test_loader_applies_identity_map_to_both_endpoints(tmp_path, trip_row):
    mapping = pd.DataFrame({"raw_station_id": ["3004", "3005"],
                            "canonical_station_id": ["3004", "3004"],
                            "identity_excluded": [False, False]})
    result = load_trips(write_csv(tmp_path / "trips.csv", [trip_row]), station_id_map=mapping)
    assert len(result) == 1
    assert result.iloc[0].start_station == result.iloc[0].end_station == "3004"
    assert result.attrs["audit"]["retained_rows"] == 1


def test_an_excluded_other_endpoint_does_not_erase_a_valid_departure(tmp_path, trip_row):
    mapping = pd.DataFrame({"raw_station_id": ["3004", "3005"],
                            "canonical_station_id": ["3004", "3005"],
                            "identity_excluded": [False, True]})
    result = load_trips(write_csv(tmp_path / "trips.csv", [trip_row]), station_id_map=mapping)
    assert len(result) == 1
    assert result.iloc[0].start_station == "3004"
    assert result.iloc[0].end_station == "3005"
