from pathlib import Path

import pandas as pd
import pytest
import yaml

from stimpact.feasibility import (
    decide_radius,
    radius_feasibility,
    screen_existing_stations,
    weekly_departures,
)


@pytest.fixture
def config():
    return yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text())


def old_inventory():
    return pd.DataFrame({"station_id": ["1", "2"],
                         "analysis_open_date": pd.to_datetime(["2015-01-01"] * 2),
                         "identity_excluded": [False, False], "eligible_existing_identity": [True, True],
                         "x_m": [0.0, 1000.0], "y_m": [0.0, 0.0]})


def complete_counts(config, first_count=5, second_count=5):
    weeks = pd.date_range(config["study"]["panel_start"], config["study"]["last_complete_week_start"], freq="7D")
    return pd.DataFrame([{"station_id": station, "week": week, "departures": count}
                         for station, count in (("1", first_count), ("2", second_count)) for week in weeks])


def test_baseline_has_all_52_weeks_and_exactly_five_is_eligible(config):
    audit, dense = screen_existing_stations(old_inventory(), complete_counts(config, 5, 4), config)
    result = audit.set_index("station_id")
    assert result.loc["1", "eligible"]
    assert result.loc["1", "baseline_weeks"] == 52
    assert result.loc["1", "baseline_weekly_departures"] == 5
    assert not result.loc["2", "eligible"]
    assert result.loc["2", "eligibility_reason"] == "baseline_below_minimum"
    assert len(dense) == 2 * 156


def test_missing_weeks_are_zero_and_eight_vs_nine_week_inactivity_boundary(config):
    counts = complete_counts(config)
    # Omit observations entirely: the eligibility grid must reconstruct the zero weeks.
    end = pd.Timestamp(config["study"]["last_complete_week_start"])
    absent1 = counts.station_id.eq("1") & counts.week.gt(end - pd.Timedelta(weeks=8))
    absent2 = counts.station_id.eq("2") & counts.week.gt(end - pd.Timedelta(weeks=9))
    audit, dense = screen_existing_stations(old_inventory(), counts.loc[~absent1 & ~absent2], config)
    result = audit.set_index("station_id")
    assert result.loc["1", "longest_zero_run_weeks"] == 8
    assert result.loc["1", "eligible"]
    assert result.loc["2", "longest_zero_run_weeks"] == 9
    assert result.loc["2", "eligibility_reason"] == "inactive_zero_run"
    assert len(dense) == 2 * 156


def test_identity_exclusion_precedes_volume_and_inactivity_rules(config):
    inventory = old_inventory()
    inventory.loc[0, "identity_excluded"] = True
    audit, _ = screen_existing_stations(inventory, complete_counts(config), config)
    assert audit.iloc[0].eligibility_reason == "identity_excluded"


def test_cleaning_and_baseline_year_boundary_preserve_departures(config):
    trips = pd.DataFrame({"start_station": ["1"] * 6,
                          "end_station": ["2", "2", "2", "2", "1", "2"],
                          "duration_seconds": [120, 120, 120, 30, 120, 120],
                          "start_time": pd.to_datetime([
                              "2022-12-31 23:59", "2023-01-01 23:59", "2023-01-02 00:00",
                              "2023-01-02 00:01", "2023-01-02 00:02", "2024-12-30 00:00"])})
    counts, audit = weekly_departures(trips, config)
    by_week = counts.set_index("week").departures
    assert by_week[pd.Timestamp("2022-12-26")] == 2
    assert by_week[pd.Timestamp("2023-01-02")] == 1
    assert audit == {"normalized_trips": 6, "short_trips": 1, "same_physical_station_trips": 1,
                     "outside_complete_weeks": 1, "counted_departures": 3}


@pytest.mark.parametrize("n400,n600,c400,c600,decision,radius", [
    (40, 60, 30, 40, "station_level_feasible", 400),
    (20, 40, 30, 40, "station_level_feasible", 400),
    (19, 25, 30, 30, "station_level_feasible", 600),
    (19, 19, 30, 30, "redesign_area_level", None),
    (40, 60, 29, 50, "redesign_area_level", None),
])
def test_radius_rules_do_not_switch_radius_to_rescue_controls(config, n400, n600, c400, c600,
                                                             decision, radius):
    counts = pd.DataFrame({"radius_m": config["spatial"]["candidate_radii_m"],
                           "treated_stations": [n400, n600, 80],
                           "all_stacks_have_min_controls": [c400 >= 30, c600 >= 30, True]})
    result = decide_radius(counts, config)
    assert result["decision"] == decision
    assert result["selected_radius_m"] == radius
    if n400 >= 20:
        assert result["radius_from_treated_count_rule_m"] == config["spatial"]["candidate_radii_m"][0]


def test_clean_control_fallback_must_pass_in_every_stack(config):
    config["estimation"]["min_controls_per_stack"] = 2
    config["feasibility"]["min_treated_stations"] = 1
    config["feasibility"]["preferred_treated_stations"] = 2
    existing = pd.DataFrame({"station_id": ["old1", "old2", "never"],
                             "x_m": [0.0, 2000.0, 4000.0], "y_m": [0.0] * 3,
                             "identity_excluded": [False] * 3})
    sources = pd.DataFrame({"station_id": ["new1", "new2"], "x_m": [0.0, 2000.0], "y_m": [0.0, 0.0],
                            "analysis_open_date": pd.to_datetime(["2023-05-01", "2024-05-01"]),
                            "exposure_only": [False, False]})
    radii, assignments, stacks, decision = radius_feasibility(existing, sources, sources, config)
    base = config["spatial"]["candidate_radii_m"][0]
    first = stacks.loc[stacks.radius_m.eq(base)].set_index("cohort_quarter")
    assert first.loc["2023Q2", "never_treated_controls"] == 1
    assert first.loc["2023Q2", "controls_used"] == 2
    assert first.loc["2023Q2", "passes_min_controls"]
    assert first.loc["2024Q2", "controls_used"] == 1
    assert not first.loc["2024Q2", "passes_min_controls"]
    assert decision["decision"] == "redesign_area_level"
    assert radii.loc[radii.radius_m.eq(base), "treated_stations"].iloc[0] == 2
    assert len(assignments) == len(existing) * len(config["spatial"]["candidate_radii_m"])
