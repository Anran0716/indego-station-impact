import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stimpact.area_simulation import (
    clean_area_contrast,
    equal_area_truth,
    make_regression,
    synthetic_effect,
    untreated_panel,
)


@pytest.fixture(scope="module")
def area_design():
    return json.loads((Path(__file__).parent / "fixtures/area_design.json").read_text())


def test_real_area_structure_is_preserved_without_outcomes(area_design):
    assert len(area_design["areas"]) == 53
    assert area_design["weeks"] == 156
    assert area_design["contains_real_outcomes"] is False
    assert [sum(a["cohort"] == s["cohort"] for a in area_design["areas"])
            for s in area_design["stacks"]] == [4, 1, 1, 10, 5, 4, 2, 1]
    for stack in area_design["stacks"]:
        treated = {a["cell_id"] for a in area_design["areas"] if a["cohort"] == stack["cohort"]}
        assert not treated & set(stack["controls"])
        last_week = pd.Timestamp(area_design["panel_start"]) + pd.Timedelta(weeks=stack["last_index"])
        for area in area_design["areas"]:
            if area["cell_id"] in stack["controls"] and area["first_exposure_week"] is not None:
                assert pd.Timestamp(area["first_exposure_week"]) > last_week


@pytest.mark.parametrize("method", [
    "stacked",
    pytest.param("twfe", marks=pytest.mark.xfail(
        strict=True, raises=AssertionError,
        reason="TWFE does not recover the 0–12-week ATT under heterogeneous dynamics")),
])
def test_known_heterogeneous_dynamic_effect(area_design, method):
    effect = synthetic_effect(area_design, heterogeneous=True)
    truth = equal_area_truth(area_design, effect)
    baseline = untreated_panel(area_design, seed=20261120, noise_sd=0)[:, 0]
    estimate = make_regression(area_design, method).fit(baseline + effect)["coefficient"]
    assert abs(np.expm1(estimate) - np.expm1(truth)) < 0.02


def test_stacked_recovers_minus_ten_percent_and_trims_each_treated_area(area_design):
    model = make_regression(area_design)
    baseline = untreated_panel(area_design, seed=20261120, noise_sd=0)[:, 0]
    effect = synthetic_effect(area_design, -0.10)
    result = model.fit(baseline + effect)
    assert np.expm1(result["coefficient"]) == pytest.approx(-0.10, abs=1e-9)
    # Four other-exposure areas are never clean in any stack; they are simulated
    # as part of the 53-area universe but cannot enter this registered regression.
    assert result["clusters"] == 49
    unit, week = np.divmod(model.panel_rows, area_design["weeks"])
    for index, area in enumerate(area_design["areas"]):
        if area["treated"]:
            # A treated area may additionally be a clean control in an earlier stack.
            post_rows = (unit == index) & model.treated_post.astype(bool)
            assert sorted((week[post_rows] - area["opening_index"]).tolist()) == list(range(13))


def test_pooled_weights_and_equal_area_target_are_reported_separately(area_design):
    model = make_regression(area_design)
    effect = synthetic_effect(area_design, heterogeneous=True)
    baseline = untreated_panel(area_design, seed=20261120, noise_sd=0)[:, 0]
    weighted_truth = model.coefficient_weights @ effect[model.panel_rows]
    assert model.post_weights.sum() == pytest.approx(1)
    assert model.fit(baseline + effect)["coefficient"] == pytest.approx(weighted_truth, abs=1e-9)
    assert clean_area_contrast(area_design, baseline + effect) == pytest.approx(
        equal_area_truth(area_design, effect), abs=1e-9)
    assert abs(weighted_truth - equal_area_truth(area_design, effect)) > 1e-4


def test_twfe_code_recovers_homogeneous_effect_before_its_expected_failure(area_design):
    baseline = untreated_panel(area_design, seed=20261120, noise_sd=0)[:, 0]
    result = make_regression(area_design, "twfe").fit(baseline + synthetic_effect(area_design))
    assert np.expm1(result["coefficient"]) == pytest.approx(-0.10, abs=1e-9)


def test_stacked_recovers_known_effect_with_noisy_area_panel(area_design):
    model = make_regression(area_design)
    baseline = untreated_panel(area_design, seed=20261120, noise_sd=0.25, rho=0.5, repetitions=200)
    result = model.fit(baseline + synthetic_effect(area_design)[:, None])
    assert abs(np.expm1(result["coefficient"].mean()) - (-0.10)) < 0.02
    assert np.all(result["se"] > 0)


def test_absorbed_coefficient_and_physical_area_cluster_se_match_independent_dummy_ols():
    # Small unbalanced panel; the same four controls are reused in two stacks.
    areas = [{"cell_id": str(i), "treated": i < 2, "opening_index": 13 + 6 * i if i < 2 else None,
              "cohort": f"cohort{i}" if i < 2 else None} for i in range(6)]
    design = {"areas": areas, "weeks": 40, "pre_weeks": 12, "post_weeks": 12,
              "stacks": [{"cohort": f"cohort{i}", "first_index": 1 + 6 * i,
                          "last_index": 25 + 6 * i, "controls": ["2", "3", "4", "5"]}
                         for i in range(2)]}
    model = make_regression(design)
    y = untreated_panel(design, seed=123, noise_sd=0.2)[:, 0] + synthetic_effect(design)
    dummy_x = np.column_stack([np.eye(g.max() + 1)[g] for g in model.groups]
                              + [model.treated_post])
    beta, _, rank, _ = np.linalg.lstsq(dummy_x, y[model.panel_rows], rcond=None)
    residual = y[model.panel_rows] - dummy_x @ beta
    slope_influence = np.linalg.pinv(dummy_x)[-1] * residual
    clusters = model.panel_rows // design["weeks"]
    score = np.bincount(clusters, weights=slope_influence)
    groups = len(np.unique(clusters))
    correction = groups / (groups - 1) * (len(residual) - 1) / (len(residual) - rank)
    se = np.sqrt(correction * score @ score)
    result = model.fit(y)
    assert result["coefficient"] == pytest.approx(beta[-1], abs=1e-9)
    assert result["parameters"] == rank
    assert result["clusters"] == 6
    assert result["se"] == pytest.approx(se, rel=1e-8)
