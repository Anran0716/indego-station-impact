from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from stimpact.treatment import assign_treatment, clean_control_mask


@pytest.fixture
def config():
    values = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text())
    values["spatial"]["treatment_radius_m"] = values["spatial"]["candidate_radii_m"][0]
    return values


def old_station(excluded=False):
    return pd.DataFrame({"station_id": ["old"], "x_m": [0.0], "y_m": [0.0],
                         "identity_excluded": [excluded]})


def new_source(distance, *, unusable=False, date="2023-05-01"):
    return pd.DataFrame({"station_id": ["new"], "x_m": [float(distance)], "y_m": [0.0],
                         "analysis_open_date": pd.to_datetime([date]), "exposure_only": [unusable]})


@pytest.mark.parametrize("distance_multiplier", [0, 1, 1.5, 2])
def test_excluded_source_within_2r_never_creates_a_control(config, distance_multiplier):
    radius = config["spatial"]["treatment_radius_m"]
    exposure = new_source(radius * distance_multiplier, unusable=True)
    result = assign_treatment(old_station(), exposure.iloc[:0], exposure, config).iloc[0]
    assert result.group == "excluded"
    assert result.reason == "exposed_to_unusable_source"
    assert result.unusable_source_ids == "new"
    assert pd.isna(result.cohort_week)


def test_excluded_source_beyond_2r_does_not_contaminate_control(config):
    radius = config["spatial"]["treatment_radius_m"]
    exposure = new_source(radius * config["spatial"]["buffer_outer_multiplier"] + 1, unusable=True)
    result = assign_treatment(old_station(), exposure.iloc[:0], exposure, config).iloc[0]
    assert result.group == "control"


def test_cohort_uses_treatment_table_and_unusable_source_stays_a_guard(config):
    radius = config["spatial"]["treatment_radius_m"]
    usable = new_source(radius - 1)
    unusable = new_source(radius * 1.5, unusable=True, date="2022-08-01")
    unusable["station_id"] = "unusable"
    exposure = pd.concat([usable, unusable], ignore_index=True)
    result = assign_treatment(old_station(), usable, exposure, config).iloc[0]
    assert result.group == "excluded"
    assert result.reason == "exposed_to_unusable_source"
    assert pd.isna(result.cohort_week)


def test_known_low_support_source_can_define_a_treatment_cohort(config):
    source = new_source(0)
    source["low_coordinate_support"] = True
    result = assign_treatment(old_station(), source, source, config).iloc[0]
    assert result.group == "treated"
    assert result.cohort_week == pd.Timestamp("2023-05-01")


@pytest.mark.parametrize("date,clean", [("2023-05-07", False), ("2023-05-08", True)])
def test_clean_controls_use_all_exposure_sources_and_the_entire_final_week(config, date, clean):
    radius = config["spatial"]["treatment_radius_m"]
    exposure = new_source(radius * 1.5, unusable=True, date=date)
    mask = clean_control_mask(old_station(), exposure, "2023-05-01", config)
    assert bool(mask.iloc[0]) == clean


def test_excluded_old_identity_cannot_return_to_any_pool(config):
    exposure = new_source(0)
    result = assign_treatment(old_station(excluded=True), exposure, exposure, config).iloc[0]
    assert result.group == "excluded"
    assert result.reason == "existing_identity_excluded"
    assert not clean_control_mask(old_station(excluded=True), exposure, "2022-01-01", config).iloc[0]


def test_missing_exposure_location_fails_instead_of_declaring_a_control(config):
    exposure = new_source(np.nan)
    with pytest.raises(ValueError, match="coordinates are missing"):
        assign_treatment(old_station(), exposure, exposure, config)
    with pytest.raises(ValueError, match="position or opening date is missing"):
        clean_control_mask(old_station(), exposure, "2023-05-01", config)


@pytest.mark.parametrize("date,reason", [("2022-02-01", "no_pre_period"), ("2024-11-01", "no_post_period")])
def test_opening_outside_treatment_window_still_prevents_a_control(config, date, reason):
    exposure = new_source(0, date=date)
    result = assign_treatment(old_station(), exposure.iloc[:0], exposure, config).iloc[0]
    assert result.group == "excluded"
    assert result.reason == reason
