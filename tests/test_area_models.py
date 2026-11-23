from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
import yaml
from scipy.linalg import qr
from statsmodels.stats.sandwich_covariance import cov_cluster

from stimpact.area_models import (
    area_panel,
    distance_design,
    empirical_power,
    event_study,
    fit_multiple,
    placebo_design,
    ppml,
)
from stimpact.area_simulation import make_regression


@pytest.fixture
def design():
    areas = [{"cell_id": str(i), "treated": i < 3,
              "opening_index": [13, 16, 25][i] if i < 3 else None,
              "cohort": ("A" if i < 2 else "B") if i < 3 else None} for i in range(16)]
    return {"areas": areas, "weeks": 50, "panel_start": "2022-01-03", "pre_weeks": 12,
            "post_weeks": 12, "stacks": [
                {"cohort": "A", "first_index": 1, "last_index": 28,
                 "controls": [str(i) for i in range(3, 16)]},
                {"cohort": "B", "first_index": 13, "last_index": 37,
                 "controls": [str(i) for i in range(3, 16)]}]}


def independent_full_rank_x(model, x):
    fe = np.column_stack([np.eye(g.max() + 1)[g] for g in model.groups])
    _, r, pivot = qr(fe, mode="economic", pivoting=True)
    rank = np.linalg.matrix_rank(r)
    return np.column_stack([fe[:, pivot[:rank]], x])


def test_event_study_recovers_known_dynamic_profile_and_excludes_control_event_times(design):
    model = make_regression(design)
    panel = np.empty((16, 50))
    for i, area in enumerate(design["areas"]):
        panel[i] = i / 10 + np.sin(np.arange(50) / 5)
        if area["treated"]:
            event = np.arange(50) - area["opening_index"]
            panel[i] += np.where(event >= 0, 0.02 * (event + 1), 0)
    result = event_study(model, panel.ravel())
    coefficients = result["coefficients"].set_index("event_week").coefficient
    for event in range(-12, 13):
        assert coefficients[event] == pytest.approx(0.02 * (event + 1) if event >= 0 else 0, abs=1e-9)
    assert result["post_average"]["coefficient"] == pytest.approx(0.14, abs=1e-9)


def test_multiple_regressor_cluster_covariance_matches_dummy_ols(design):
    model = make_regression(design)
    rng = np.random.default_rng(456)
    x = np.column_stack([model.treated_post, rng.normal(size=len(model.panel_rows))])
    y = rng.normal(size=len(x)) + x @ np.array([0.3, -0.2])
    explicit_x = independent_full_rank_x(model, x)
    oracle = sm.OLS(y, explicit_x).fit()
    covariance = cov_cluster(oracle, model.clusters)
    result = fit_multiple(model, y, x)
    assert result["coefficient"] == pytest.approx(oracle.params[-2:], abs=1e-9)
    assert result["covariance"] == pytest.approx(covariance[-2:, -2:], rel=1e-8, abs=1e-10)


def test_ppml_with_zero_observations_matches_independent_glm_and_cluster_se(design):
    model = make_regression(design)
    x = independent_full_rank_x(model, model.treated_post)
    # Populate only the rows used by this unbalanced prototype. Repeated panel
    # cells must share the same real response across stack copies.
    panel = np.random.default_rng(35).poisson(2, size=16 * 50).astype(float)
    y = panel[model.panel_rows]
    assert (y == 0).any()
    oracle = sm.GLM(y, x, family=sm.families.Poisson()).fit(maxiter=200, tol=1e-11)
    covariance = cov_cluster(oracle, model.clusters)
    result = ppml(model, panel)
    assert result["coefficient"] == pytest.approx(oracle.params[-1], abs=1e-7)
    assert result["se"] == pytest.approx(np.sqrt(covariance[-1, -1]), rel=1e-6)
    assert result["max_score_error"] < 1e-5


def test_ppml_recovers_known_effect_without_poisson_sampling_noise(design):
    model = make_regression(design)
    panel = np.array([np.exp(2 + i / 20 + np.arange(50) / 100
                     + np.where(np.arange(50) >= a["opening_index"], np.log(1.1), 0))
                      if a["treated"] else np.exp(2 + i / 20 + np.arange(50) / 100)
                      for i, a in enumerate(design["areas"])]).ravel()
    assert np.expm1(ppml(model, panel)["coefficient"]) == pytest.approx(0.1, abs=1e-8)


def test_ppml_separation_is_reported_without_silent_sample_changes(design):
    model = make_regression(design)
    with pytest.raises(ValueError, match="separation"):
        ppml(model, np.zeros(16 * 50))


def test_empirical_power_uses_residuals_and_removes_fitted_treatment_effect(design):
    model = make_regression(design)
    panel = np.random.default_rng(80).normal(size=16 * 50)
    treatment = np.zeros((16, 50))
    for i, area in enumerate(design["areas"]):
        if area["treated"]:
            treatment[i, area["opening_index"]:] = 0.3
    settings = {"seed": 3, "repetitions": 40, "injected_effects": [0, 0.1],
                "alpha": 0.05, "target_power": 0.8}
    first = empirical_power(model, panel, settings)
    shifted = empirical_power(model, panel + treatment.ravel(), settings)
    assert first["uses_observed_variance"]
    assert first["draws"].log_estimate.to_numpy() == pytest.approx(
        shifted["draws"].log_estimate.to_numpy(), abs=1e-9)
    assert first["draws"].area_cluster_se.to_numpy() == pytest.approx(
        shifted["draws"].area_cluster_se.to_numpy(), abs=1e-9)


def test_placebo_keeps_only_fully_supported_cohorts_and_never_reaches_real_treatment(design):
    placebo, omitted = placebo_design(design, shift=13)
    assert omitted == [{"cohort": "A", "reason": "shifted_full_window_outside_panel"}]
    assert [s["cohort"] for s in placebo["stacks"]] == ["B"]
    area = placebo["areas"][2]
    assert area["opening_index"] + 12 < design["areas"][2]["opening_index"]


def test_placebo_rejects_a_shift_that_reaches_the_real_opening(design):
    with pytest.raises(ValueError, match="reaches real treatment"):
        placebo_design(design, shift=12)


def test_distance_filter_cannot_add_controls_or_bypass_the_minimum(design):
    membership = pd.DataFrame({"cohort_quarter": ["A", "B"], "cell_id": ["3", "3"],
                               "kept_after_distance": [True, True]})
    with pytest.raises(ValueError, match="too few"):
        distance_design(design, membership, minimum=10)


def test_area_counts_include_new_and_ineligible_old_stations_and_keep_zero_weeks():
    config = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text())
    config["study"]["last_complete_week_start"] = "2022-01-10"
    weekly = pd.DataFrame({"station_id": ["old", "new", "ineligible", "outside"],
                           "week": pd.to_datetime(["2022-01-03"] * 4), "departures": [2, 3, 4, 7]})
    registry = pd.DataFrame({"station_id": weekly.station_id, "x_m": [100, 200, 300, 2500], "y_m": [0] * 4})
    areas = pd.DataFrame({"offset_x_m": [0, 0], "offset_y_m": [0, 0], "cell_id": ["0:0", "1:0"],
                          "eligible_area": [True, True], "excluded": [False, False]})
    panel, audit = area_panel(weekly, registry, {"old"}, areas, (0, 0), config)
    assert len(panel) == 4 and panel.departures.sum() == 9 and panel.old_departures.sum() == 2
    assert audit["departures_outside_sample"] == 7
    registry.loc[registry.station_id.eq("new"), "x_m"] = np.nan
    with pytest.raises(ValueError, match="unresolved position"):
        area_panel(weekly, registry, {"old"}, areas, (0, 0), config)
