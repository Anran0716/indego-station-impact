from pathlib import Path

import pandas as pd
import pytest
import yaml

from stimpact.area_spillover import count_distance_controls


def fixture(opening="2023-06-04", distance=400):
    return {
        "stacks": pd.DataFrame([{"offset_x_m": 0, "offset_y_m": 0, "cohort_quarter": "2023Q2",
                                 "stack_first_week": "2023-03-06", "stack_last_week": "2023-05-29"}]),
        "controls": pd.DataFrame([{"offset_x_m": 0, "offset_y_m": 0, "cohort_quarter": "2023Q2",
                                   "cell_id": "1:0", "control_type": "never_exposed"}]),
        "old_cell_map": pd.DataFrame({"offset_x_m": [0, 0], "offset_y_m": [0, 0],
                                      "cell_id": ["1:0", "1:0"], "station_id": ["old1", "old2"],
                                      "x_m": [1800.0, 1000.0], "y_m": [0.0, 0.0]}),
        "source_cell_map": pd.DataFrame({"offset_x_m": [0], "offset_y_m": [0],
                                         "station_id": ["unusable_new"], "exposure_only": [True],
                                         "x_m": [1000.0 - distance], "y_m": [0.0],
                                         "analysis_open_date": pd.to_datetime([opening])}),
    }


@pytest.mark.parametrize("date,distance,kept", [
    ("2023-06-04", 400, False), ("2023-06-04", 400.001, True),
    ("2023-06-05", 0, True), ("2023-03-05", 0, True), ("2023-03-06", 0, False),
])
def test_exact_distance_whole_week_and_any_old_station(date, distance, kept):
    config = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text())
    result = count_distance_controls(fixture(date, distance), config)
    assert bool(result["controls"].iloc[0].kept_after_distance) == kept
    assert len(result["excluded_pairs"]) == int(not kept)
    # The unusable source is in an adjacent cell and still triggers the restriction.
    assert result["grids"].iloc[0].status == "not_estimable"


@pytest.mark.parametrize("number,expected", [(9, "not_estimable"), (10, "estimable")])
def test_ten_is_sensitivity_threshold_and_main_decision_is_untouched(number, expected):
    config = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text())
    inputs = fixture("2024-01-01")
    inputs["controls"] = pd.concat([inputs["controls"]] * number, ignore_index=True)
    # Give every control its own physical area and old station.
    inputs["controls"]["cell_id"] = [str(i) for i in range(number)]
    old = inputs["old_cell_map"].iloc[[0]]
    inputs["old_cell_map"] = pd.concat([old] * number, ignore_index=True)
    inputs["old_cell_map"]["cell_id"] = inputs["controls"].cell_id
    result = count_distance_controls(inputs, config)
    assert result["grids"].iloc[0].status == expected
    assert config["area_feasibility"]["min_clean_controls_per_stack"] == 15
    assert config["spillover_distance"]["changes_main_gate"] is False
