"""Area outcome aggregation, event-study/PPML inference, and empirical-residual power."""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
from scipy.stats import f, t

from stimpact.area_feasibility import grid_membership
from stimpact.area_simulation import AreaRegression, absorb


def area_panel(weekly: pd.DataFrame, registry: pd.DataFrame, old_ids: set[str],
               areas: pd.DataFrame, offset: tuple[int, int], config: dict) -> tuple[pd.DataFrame, dict]:
    """All stations enter primary counts; only qualified old stations enter secondary counts."""
    if registry.station_id.duplicated().any():
        raise ValueError("Duplicate canonical station IDs")
    observed = set(weekly.loc[weekly.departures.gt(0), "station_id"])
    positions = registry.set_index("station_id")
    if not observed <= set(positions.index):
        raise ValueError("Observed departure station is absent from the registry")
    coordinates = positions.loc[sorted(observed), ["x_m", "y_m"]].reset_index()
    if not np.isfinite(coordinates[["x_m", "y_m"]].to_numpy()).all():
        raise ValueError("Observed departure station has an unresolved position")
    station_cells = grid_membership(coordinates, offset, config).set_index("station_id").cell_id
    mapped = weekly.copy()
    mapped["cell_id"] = mapped.station_id.map(station_cells)
    mapped["old_departures"] = mapped.departures.where(mapped.station_id.isin(old_ids), 0)
    if mapped.loc[mapped.departures.gt(0), "cell_id"].isna().any():
        raise AssertionError("Departure mapping lost a station")
    cells = areas.loc[areas.offset_x_m.eq(offset[0]) & areas.offset_y_m.eq(offset[1])
                     & areas.eligible_area & ~areas.excluded, "cell_id"].sort_values()
    weeks = pd.date_range(config["study"]["panel_start"],
                          config["study"]["last_complete_week_start"], freq="W-MON")
    if not mapped.week.isin(weeks).all():
        raise ValueError("Station weeks exceed the registered complete-week panel")
    totals = mapped.groupby(["cell_id", "week"])[["departures", "old_departures"]].sum()
    grid = pd.MultiIndex.from_product([cells, weeks], names=["cell_id", "week"])
    panel = totals.reindex(grid, fill_value=0).reset_index()
    inside = mapped.cell_id.isin(cells)
    audit = {"offset_x_m": offset[0], "offset_y_m": offset[1], "areas": len(cells),
             "weeks": len(weeks), "all_cleaned_departures": int(mapped.departures.sum()),
             "departures_inside_sample": int(mapped.loc[inside, "departures"].sum()),
             "departures_outside_sample": int(mapped.loc[~inside, "departures"].sum()),
             "qualified_old_departures_inside": int(mapped.loc[inside, "old_departures"].sum())}
    if (int(panel.departures.sum()) != audit["departures_inside_sample"]
            or audit["all_cleaned_departures"] != audit["departures_inside_sample"] + audit["departures_outside_sample"]
            or (panel.old_departures > panel.departures).any()):
        raise AssertionError("Area panel does not conserve departures")
    return panel, audit


def ordered_outcome(panel: pd.DataFrame, design: dict, column="departures") -> np.ndarray:
    weeks = pd.date_range(design["panel_start"], periods=design["weeks"], freq="W-MON")
    index = pd.MultiIndex.from_product([[a["cell_id"] for a in design["areas"]], weeks],
                                     names=["cell_id", "week"])
    y = panel.set_index(["cell_id", "week"])[column].reindex(index)
    if y.isna().any() or (y < 0).any():
        raise ValueError("Incomplete or negative area outcome")
    return y.to_numpy(dtype=float)


def contrast(beta: np.ndarray, covariance: np.ndarray, weights: np.ndarray, groups: int) -> dict:
    value = float(weights @ beta)
    se = float(np.sqrt(max(float(weights @ covariance @ weights), 0)))
    critical = t.ppf(0.975, groups - 1)
    return {"coefficient": value, "se": se, "ci_low": value - critical * se,
            "ci_high": value + critical * se,
            "p_value": float(2 * t.sf(abs(value) / max(se, 1e-15), groups - 1))}


def event_reference_diagnostic(coefficients: pd.DataFrame, covariance: np.ndarray,
                               event_order: np.ndarray, groups: int) -> dict:
    """Post-result interpretation only; retain the registered week -1 coefficients."""
    series = coefficients.set_index("event_week").coefficient.sort_index()
    if series.index.duplicated().any() or set(series.index) != set(range(-12, 13)):
        raise ValueError("Reference diagnostic requires all event weeks -12..12")
    if series.loc[-1] != 0 or set(event_order) != set(series.index) - {-1}:
        raise ValueError("Registered event reference must be week -1")
    beta = series.loc[event_order].to_numpy()
    # Week -1 has coefficient/variance zero but belongs to the full 12-week pre-period.
    weights = np.where(event_order >= 0, 1 / 13, -1 / 12)
    full_pre = contrast(beta, covariance, weights, groups)
    return {"status": "posthoc_descriptive_diagnostic", "reference_week": -1,
            "pre_mean_minus12_to_minus2": float(series.loc[-12:-2].mean()),
            "pre_mean_minus12_to_minus1": float(series.loc[-12:-1].mean()),
            "post_mean_0_to_12": float(series.loc[0:12].mean()),
            "post_minus_full_pre": full_pre,
            "post_minus_full_pre_relative": float(np.expm1(full_pre["coefficient"])),
            "post_minus_nonreference_pre_relative": float(np.expm1(
                series.loc[0:12].mean() - series.loc[-12:-2].mean())),
            "early_post_mean_1_to_2_log": float(series.loc[1:2].mean()),
            "later_post_mean_3_to_12_log": float(series.loc[3:12].mean())}


def type_m_diagnostic(draws: pd.DataFrame, assumed_effect=0.10) -> dict:
    """Conditional exaggeration in existing draws, not a correction to the observed estimate."""
    if assumed_effect <= -1 or assumed_effect == 0:
        raise ValueError("Type M requires a nonzero assumed effect greater than -1")
    selected_effect = draws.loc[np.isclose(draws.effect, assumed_effect)]
    significant = selected_effect.loc[selected_effect.rejected]
    result = {"status": "posthoc_assumption_conditional_diagnostic", "assumed_effect": assumed_effect,
              "repetitions": len(selected_effect), "significant_repetitions": len(significant)}
    if selected_effect.empty or significant.empty:
        return {**result, "estimable": False}
    return {**result, "estimable": True, "power": len(significant) / len(selected_effect),
            "conditional_log_magnitude_ratio": float(significant.log_estimate.abs().mean()
                                                       / abs(np.log1p(assumed_effect))),
            "conditional_mean_relative_estimate": float(np.expm1(significant.log_estimate).mean())}


def fit_multiple(model: AreaRegression, y: np.ndarray, x: np.ndarray) -> dict:
    rx, ry = absorb(x, model.groups), absorb(y, model.groups)
    if np.linalg.matrix_rank(rx) != x.shape[1]:
        raise ValueError("Event-study regressors are not identified")
    bread = np.linalg.inv(rx.T @ rx)
    beta = bread @ rx.T @ ry
    residual = ry - rx @ beta
    groups = int(model.clusters.max()) + 1
    scores = np.zeros((groups, x.shape[1]))
    np.add.at(scores, model.clusters, rx * residual[:, None])
    n, k = len(y), model.fixed_effect_rank + x.shape[1]
    covariance = groups / (groups - 1) * (n - 1) / (n - k) * bread @ scores.T @ scores @ bread
    covariance = (covariance + covariance.T) / 2
    return {"coefficient": beta, "covariance": covariance, "residual": residual,
            "clusters": groups, "observations": n, "parameters": k}


def event_study(model: AreaRegression, panel_y: np.ndarray, pre=12, post=12) -> dict:
    events = np.array([week for week in range(-pre, post + 1) if week != -1])
    x = np.column_stack([model.event_time == week for week in events]).astype(float)
    result = fit_multiple(model, panel_y[model.panel_rows], x)
    beta, covariance, groups = result["coefficient"], result["covariance"], result["clusters"]
    rows = []
    for index, event in enumerate(events):
        weights = np.eye(len(events))[index]
        rows.append({"event_week": int(event), **contrast(beta, covariance, weights, groups)})
    rows.append({"event_week": -1, "coefficient": 0, "se": 0, "ci_low": 0, "ci_high": 0,
                 "p_value": np.nan})
    before = np.flatnonzero(events < -1)
    cov_pre = covariance[np.ix_(before, before)]
    if np.linalg.matrix_rank(cov_pre) < len(before) or groups <= len(before):
        joint = {"status": "not_estimable", "reason": "insufficient_cluster_covariance_rank"}
    else:
        statistic = float(beta[before] @ np.linalg.solve(cov_pre, beta[before]) / len(before))
        joint = {"status": "estimated", "F": statistic, "df_num": len(before),
                 "df_den": groups - 1, "p_value": float(f.sf(statistic, len(before), groups - 1))}
    average_weights = (events >= 0).astype(float) / (post + 1)
    return {"coefficients": pd.DataFrame(rows).sort_values("event_week"), "covariance": covariance,
            "event_order": events, "pretrend": joint,
            "post_average": contrast(beta, covariance, average_weights, groups), "fit": result}


def weighted_absorb(values: np.ndarray, groups: tuple, weights: np.ndarray,
                    tolerance=1e-10) -> np.ndarray:
    result = np.asarray(values, dtype=float).copy()
    denominators = [np.bincount(group, weights=weights) for group in groups]
    for _ in range(2000):
        largest = 0.0
        for group, denominator in zip(groups, denominators, strict=True):
            sums = np.zeros((len(denominator), result.shape[1]))
            np.add.at(sums, group, weights[:, None] * result)
            means = sums / denominator[:, None]
            largest = max(largest, float(np.abs(means).max()))
            result -= means[group]
        if largest < tolerance:
            return result
    raise ArithmeticError("Weighted FE absorption did not converge")


def ppml(model: AreaRegression, counts: np.ndarray, max_iterations=100, tolerance=1e-8) -> dict:
    """Poisson IRLS with absorbed FE; no observations are silently dropped for separation."""
    y = np.asarray(counts)[model.panel_rows]
    if np.any(y < 0) or not np.isfinite(y).all():
        raise ValueError("PPML requires finite nonnegative counts")
    for group in model.groups:
        if np.any(np.bincount(group, weights=y) == 0):
            raise ValueError("PPML separation: an entire FE group has zero counts")
    eta = np.full(len(y), np.log(y.mean()))
    coefficient = 0.0
    for iteration in range(1, max_iterations + 1):
        mu = np.exp(eta)
        z = eta + (y - mu) / mu
        residualized = weighted_absorb(np.column_stack([model.treated_post, z]), model.groups, mu)
        rx, rz = residualized.T
        information = float((mu * rx) @ rx)
        beta = float((mu * rx) @ rz / information)
        proposed = z - rz + rx * beta
        loglik = float(np.sum(y * eta - mu))
        step = 1.0
        while step >= 2**-20:
            candidate = eta + step * (proposed - eta)
            if np.max(np.abs(candidate)) < 40 and float(np.sum(y * candidate - np.exp(candidate))) >= loglik - 1e-7:
                break
            step /= 2
        if step < 2**-20:
            raise ArithmeticError("PPML line search failed")
        difference = float(np.max(np.abs(candidate - eta)))
        coefficient += step * (beta - coefficient)
        eta = candidate
        if difference < tolerance:
            break
    else:
        raise ArithmeticError("PPML did not converge")
    mu = np.exp(eta)
    rx = weighted_absorb(model.treated_post[:, None], model.groups, mu)[:, 0]
    information = float((mu * rx) @ rx)
    groups = int(model.clusters.max()) + 1
    scores = np.bincount(model.clusters, weights=rx * (y - mu))
    n, k = len(y), model.fixed_effect_rank + 1
    se = float(np.sqrt(groups / (groups - 1) * (n - 1) / (n - k) * (scores @ scores)) / information)
    result = contrast(np.array([coefficient]), np.array([[se**2]]), np.ones(1), groups)
    score_error = max(abs(float(rx @ (y - mu))),
                      *(float(np.max(np.abs(np.bincount(g, weights=y - mu)))) for g in model.groups))
    if score_error > 1e-6 * max(1, y.sum()):
        raise ArithmeticError("PPML score equations did not converge")
    return {**result, "clusters": groups, "observations": n, "parameters": k,
            "iterations": iteration, "max_score_error": score_error, "status": "estimated"}


def distance_design(design: dict, membership: pd.DataFrame, minimum=10) -> dict:
    result = deepcopy(design)
    for stack in result["stacks"]:
        keep = membership.loc[membership.cohort_quarter.eq(stack["cohort"])
                              & membership.kept_after_distance, "cell_id"]
        if len(keep) < minimum:
            raise ValueError("Distance restriction is not estimable: too few controls")
        if not set(keep) <= set(stack["controls"]):
            raise ValueError("Distance restriction introduced a nonclean control")
        stack["controls"] = sorted(keep.tolist())
    return result


def placebo_design(design: dict, shift=26) -> tuple[dict, list[dict]]:
    result, omitted, kept = deepcopy(design), [], []
    for stack in result["stacks"]:
        if stack["first_index"] - shift < 0 or stack["last_index"] - shift >= design["weeks"]:
            omitted.append({"cohort": stack["cohort"], "reason": "shifted_full_window_outside_panel"})
        else:
            stack["first_index"] -= shift
            stack["last_index"] -= shift
            kept.append(stack)
    result["stacks"] = kept
    supported = {s["cohort"] for s in kept}
    for area in result["areas"]:
        if area["treated"]:
            if area["cohort"] in supported:
                real_opening = area["opening_index"]
                area["opening_index"] -= shift
                if area["opening_index"] + design["post_weeks"] >= real_opening:
                    raise ValueError("Placebo reaches real treatment")
            else:
                area["treated"], area["cohort"], area["opening_index"] = False, None, None
    if not kept:
        raise ValueError("No fully supported placebo cohort")
    return result, omitted


def empirical_power(model: AreaRegression, panel_log_y: np.ndarray, settings: dict) -> dict:
    # Fitted nuisance FE need not be materialized: the same absorption operator
    # annihilates them in every bootstrap fit. Keep one sign per physical area.
    fit = model.fit(panel_log_y)
    residual = absorb(panel_log_y[model.panel_rows], model.groups) - model.residual_x * fit["coefficient"]
    residual *= np.sqrt(fit["observations"] / (fit["observations"] - fit["parameters"]))
    rng = np.random.default_rng(settings["seed"])
    signs = rng.choice([-1.0, 1.0], size=(fit["clusters"], settings["repetitions"]))
    errors = residual[:, None] * signs[model.clusters]
    bootstrap = model.fit_rows(errors)
    critical = t.ppf(1 - settings["alpha"] / 2, fit["clusters"] - 1)
    beta0, se = bootstrap["coefficient"], bootstrap["se"]
    rows, draws = [], []
    for delta in settings["injected_effects"]:
        target = np.log1p(delta)
        betas = beta0 + target
        rejection = np.abs(betas / se) > critical
        coverage = np.abs(betas - target) <= critical * se
        rate = float(rejection.mean())
        rows.append({"effect": delta, "target_log": float(target), "repetitions": len(se),
                     "mean_log_estimate": float(betas.mean()), "bias_log": float(beta0.mean()),
                     "rejection_rate": rate, "monte_carlo_se": float(np.sqrt(rate * (1 - rate) / len(se))),
                     "coverage_95": float(coverage.mean()), "mean_cluster_se": float(se.mean())})
        for index, (value, sigma, reject) in enumerate(zip(betas, se, rejection, strict=True)):
            draws.append({"effect": delta, "replication": index, "log_estimate": value,
                          "area_cluster_se": sigma, "rejected": bool(reject)})
    mdes = {}
    for name, direction in (("positive", 1), ("negative", -1)):
        candidates = [abs(r["effect"]) for r in rows if r["effect"] * direction > 0
                      and r["rejection_rate"] >= settings["target_power"]]
        mdes[name] = min(candidates) if candidates else None
    return {"power": pd.DataFrame(rows), "draws": pd.DataFrame(draws), "smallest_tested_80pct": mdes,
            "residual_sd_before_scale": float(np.std(residual) * np.sqrt(
                (fit["observations"] - fit["parameters"]) / fit["observations"])),
            "method": "physical_area_wild_bootstrap_of_empirical_residuals",
            "uses_observed_variance": True, "settings": settings}
