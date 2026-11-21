from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from stimpact.area_feasibility import area_decision, count_areas, grid_membership, passes_gate


@pytest.fixture
def config():
    return yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text())


def old_points(xs, ys=None):
    return pd.DataFrame({"station_id": [f"old{index}" for index in range(len(xs))],
                         "x_m": xs, "y_m": ys if ys is not None else [0.0] * len(xs)})


def sources(xs, dates, *, unusable=None, ys=None):
    return pd.DataFrame({"station_id": [f"new{index}" for index in range(len(xs))], "x_m": xs,
                         "y_m": ys if ys is not None else [0.0] * len(xs),
                         "analysis_open_date": pd.to_datetime(dates),
                         "exposure_only": unusable if unusable is not None else [False] * len(xs)})


def primary(result, key):
    frame = result[key]
    return frame.loc[frame.offset_x_m.eq(0) & frame.offset_y_m.eq(0)]


@pytest.mark.parametrize("offset,x,y,col,row", [
    ((0, 0), 0, 0, 0, 0), ((0, 0), 999.999, 999.999, 0, 0),
    ((0, 0), 1000, 1000, 1, 1), ((500, 500), 499.999, 499.999, -1, -1),
    ((500, 500), 500, 500, 0, 0), ((500, 0), 1500, 1000, 1, 1),
])
def test_grid_boundaries_use_floor_and_half_open_cells(config, offset, x, y, col, row):
    result = grid_membership(old_points([x], [y]), offset, config).iloc[0]
    assert result.cell_col == col and result.cell_row == row


def test_multiple_old_stations_in_one_cell_count_as_one_area_and_new_only_cells_are_not_units(config):
    exposure = sources([200.0, 3000.0], ["2023-05-01", "2023-05-02"])
    result = count_areas(old_points([0.0, 500.0]), exposure, exposure, config)
    grid = primary(result, "grid_counts").iloc[0]
    assert grid.eligible_areas == grid.treated_areas == 1
    assert grid.exposure_cells_without_eligible_old == 1
    area = primary(result, "areas").set_index("cell_id")
    assert area.loc["0:0", "eligible_old_stations"] == 2
    assert not area.loc["3:0", "eligible_area"]


def test_earliest_treatment_in_cell_sets_cohort_and_counts_extra_sources(config):
    exposure = sources([200.0, 300.0], ["2023-05-08", "2023-05-02"])
    result = count_areas(old_points([0.0]), exposure, exposure, config)
    area = primary(result, "areas").iloc[0]
    assert area.cohort_week == pd.Timestamp("2023-05-01")
    assert area.treatment_sources == 2


def test_unusable_exposure_excludes_only_its_own_eligible_area(config):
    exposure = sources([100.0, 1100.0], ["2023-05-01", "2023-04-01"], unusable=[False, True])
    result = count_areas(old_points([0.0, 1000.0, 2000.0]), exposure.iloc[[0]], exposure, config)
    areas = primary(result, "areas").set_index("cell_id")
    assert areas.loc["1:0", "excluded"]
    assert areas.loc["1:0", "reason"] == "area_contains_unusable_exposure"
    assert not areas.loc["2:0", "excluded"]
    members = primary(result, "controls")
    assert "2:0" in set(members.cell_id)


@pytest.mark.parametrize("opening,clean", [("2023-07-30", False), ("2023-07-31", True)])
def test_control_must_remain_unexposed_through_the_entire_last_stack_week(config, opening, clean):
    exposure = sources([100.0, 2100.0], ["2023-05-01", opening])
    result = count_areas(old_points([0.0, 2000.0, 4000.0]), exposure, exposure, config)
    controls = primary(result, "controls")
    early = controls.loc[controls.cohort_quarter.eq("2023Q2")]
    assert ("2:0" in set(early.cell_id)) == clean


def test_previously_exposed_cell_is_not_a_control_even_without_an_opening_in_the_stack(config):
    exposure = sources([100.0, 2100.0], ["2023-05-01", "2022-02-01"])
    result = count_areas(old_points([0.0, 2000.0, 4000.0]), exposure.iloc[[0]], exposure, config)
    assert "2:0" not in set(primary(result, "controls").cell_id)


def test_adjacent_new_only_exposure_cell_is_used_in_spillover_diagnostic(config):
    exposure = sources([100.0, 1100.0], ["2023-05-01", "2023-04-01"], unusable=[False, True])
    result = count_areas(old_points([0.0, 2000.0, 5000.0]), exposure.iloc[[0]], exposure, config)
    controls = primary(result, "controls").set_index("cell_id")
    assert "2:0" in controls.index  # No 2R buffer in the main area design.
    assert not controls.loc["2:0", "kept_after_adjacency"]
    assert controls.loc["5:0", "kept_after_adjacency"]


def test_diagonal_adjacency_is_excluded_but_future_exposures_are_not(config):
    exposure = sources([100.0, 1100.0, 3100.0], ["2023-05-01", "2023-04-01", "2024-11-01"],
                        ys=[100.0, 1100.0, 1100.0], unusable=[False, True, False])
    result = count_areas(old_points([0.0, 2000.0, 4000.0], [0.0, 2000.0, 2000.0]),
                         exposure.iloc[[0]], exposure, config)
    controls = primary(result, "controls").set_index("cell_id")
    assert not controls.loc["2:2", "kept_after_adjacency"]
    assert controls.loc["4:2", "kept_after_adjacency"]


@pytest.mark.parametrize("treated,controls,expected", [
    (20, [15, 15], True), (19, [15, 15], False), (20, [15, 14], False), (20, [], False),
])
def test_every_stack_and_treated_count_must_meet_fixed_thresholds(config, treated, controls, expected):
    assert passes_gate(treated, controls, config) == expected


def test_a_passing_shift_cannot_rescue_the_failed_primary_grid(config):
    counts = pd.DataFrame({"offset_x_m": [0, 500, 0, 500], "offset_y_m": [0, 0, 500, 500],
                           "passes_main_gate": [False, True, True, True],
                           "adjacency_sample_sufficient": [False] * 4,
                           "treated_areas": [19, 25, 25, 25],
                           "minimum_clean_controls_per_stack": [15, 20, 20, 20],
                           "failed_stacks": [0, 0, 0, 0]})
    result = area_decision(counts, config)
    assert result["decision"] == "stop_causal_estimation"
    assert result["primary_offset_m"] == [0, 0]
    assert len(result["passing_offsets"]) == 3


def test_unknown_position_is_not_silently_assigned_to_a_cell(config):
    with pytest.raises(ValueError, match="finite positions"):
        grid_membership(old_points([np.nan]), (0, 0), config)


def test_insufficient_adjacency_sample_does_not_overrule_a_passing_main_gate(config):
    counts = pd.DataFrame({"offset_x_m": [0], "offset_y_m": [0],
                           "passes_main_gate": [True], "adjacency_sample_sufficient": [False],
                           "treated_areas": [28], "minimum_clean_controls_per_stack": [21],
                           "failed_stacks": [0]})
    assert area_decision(counts, config)["decision"] == "primary_area_feasible"
