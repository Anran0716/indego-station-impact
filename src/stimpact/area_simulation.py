"""Synthetic area-panel validation. This module never loads real ridership."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import t


def design_from_counts(areas: pd.DataFrame, stacks: pd.DataFrame,
                       controls: pd.DataFrame, config: dict) -> dict:
    """Freeze only geography/timing metadata, suitable for a small public test fixture."""
    dx, dy = config["area_simulation"]["primary_offset_m"]

    def primary(frame):
        return frame.loc[frame.offset_x_m.eq(dx) & frame.offset_y_m.eq(dy)]

    areas = primary(areas)
    areas = areas.loc[areas.eligible_area & ~areas.excluded].sort_values("cell_id")
    weeks = pd.date_range(config["study"]["panel_start"],
                          config["study"]["last_complete_week_start"], freq="W-MON")
    records = []
    for area in areas.itertuples():
        week = pd.Timestamp(area.cohort_week) if area.treated else None
        records.append({"cell_id": area.cell_id, "treated": bool(area.treated),
                        "opening_index": int((week - weeks[0]).days // 7) if week is not None else None,
                        "cohort": area.cohort_quarter if area.treated else None,
                        "first_exposure_week": str(area.first_exposure_week)
                        if pd.notna(area.first_exposure_week) else None})
    experiments = []
    for stack in primary(stacks).itertuples():
        clean = primary(controls)
        clean = clean.loc[clean.cohort_quarter.eq(stack.cohort_quarter)]
        experiments.append({"cohort": stack.cohort_quarter,
                            "first_index": int((pd.Timestamp(stack.stack_first_week) - weeks[0]).days // 7),
                            "last_index": int((pd.Timestamp(stack.stack_last_week) - weeks[0]).days // 7),
                            "controls": sorted(clean.cell_id.tolist())})
    return {"panel_start": str(weeks[0].date()), "weeks": len(weeks), "areas": records,
            "stacks": experiments, "pre_weeks": config["estimation"]["event_pre_weeks"],
            "post_weeks": config["estimation"]["event_post_weeks"],
            "contains_real_outcomes": False}


def absorb(values: np.ndarray, groups: tuple[np.ndarray, ...], tolerance=1e-11) -> np.ndarray:
    """Alternating projections also handle the trimmed, unbalanced stacked panel."""
    result = np.asarray(values, dtype=float).copy()
    if not np.isfinite(result).all():
        raise ValueError("Non-finite synthetic outcome or regressor")
    counts = [np.bincount(group) for group in groups]
    for _ in range(1000):
        largest = 0.0
        for group, count in zip(groups, counts, strict=True):
            sums = np.zeros((len(count),) + result.shape[1:])
            np.add.at(sums, group, result)
            means = sums / count.reshape((-1,) + (1,) * (result.ndim - 1))
            largest = max(largest, float(np.abs(means).max()))
            result -= means[group]
        if largest < tolerance:
            return result
    raise ArithmeticError("Fixed-effect absorption did not converge")


@dataclass
class AreaRegression:
    panel_rows: np.ndarray
    clusters: np.ndarray
    groups: tuple[np.ndarray, np.ndarray]
    treated_post: np.ndarray
    fixed_effect_rank: int

    def __post_init__(self):
        self.residual_x = absorb(self.treated_post, self.groups)
        self.information = float(self.residual_x @ self.residual_x)
        if self.information <= 1e-10:
            raise ValueError("Synthetic design does not identify treated_post")
        self.coefficient_weights = self.residual_x / self.information
        self.post_weights = self.coefficient_weights * self.treated_post

    def fit(self, panel_y: np.ndarray) -> dict:
        y = np.asarray(panel_y)[self.panel_rows]
        residual_y = absorb(y, self.groups)
        beta = self.coefficient_weights @ residual_y
        residuals = residual_y - np.multiply.outer(self.residual_x, beta) if y.ndim == 2 else (
            residual_y - self.residual_x * beta)
        score = residuals * self.residual_x.reshape((-1,) + (1,) * (y.ndim - 1))
        n_clusters = int(self.clusters.max()) + 1
        sums = np.zeros((n_clusters,) + score.shape[1:])
        np.add.at(sums, self.clusters, score)
        n, k = len(y), self.fixed_effect_rank + 1
        correction = n_clusters / (n_clusters - 1) * (n - 1) / (n - k)
        se = np.sqrt(correction * np.square(sums).sum(axis=0)) / self.information
        critical = t.ppf(0.975, n_clusters - 1)
        return {"coefficient": beta, "se": se, "ci_low": beta - critical * se,
                "ci_high": beta + critical * se,
                "p_value": 2 * t.sf(np.abs(beta) / np.maximum(se, 1e-15), n_clusters - 1),
                "clusters": n_clusters, "observations": n, "parameters": k}


def make_regression(design: dict, method="stacked") -> AreaRegression:
    n_units, n_weeks = len(design["areas"]), design["weeks"]
    by_id = {area["cell_id"]: index for index, area in enumerate(design["areas"])}
    rows, unit_keys, week_keys, physical_units, d = [], [], [], [], []
    if method == "twfe":
        for unit, area in enumerate(design["areas"]):
            for week in range(n_weeks):
                rows.append(unit * n_weeks + week)
                unit_keys.append(unit)
                week_keys.append(week)
                physical_units.append(unit)
                d.append(float(area["treated"] and week >= area["opening_index"]))
        rank = n_units + n_weeks - 1
    elif method == "stacked":
        for stack_number, stack in enumerate(design["stacks"]):
            treated = {a["cell_id"] for a in design["areas"] if a["cohort"] == stack["cohort"]}
            controls = set(stack["controls"])
            if treated & controls or not controls:
                raise ValueError("A stack requires disjoint treated areas and clean controls")
            for cell_id in sorted(treated | controls):
                unit = by_id[cell_id]
                area = design["areas"][unit]
                for week in range(stack["first_index"], stack["last_index"] + 1):
                    event = week - area["opening_index"] if cell_id in treated else None
                    if event is not None and not -design["pre_weeks"] <= event <= design["post_weeks"]:
                        continue
                    rows.append(unit * n_weeks + week)
                    unit_keys.append((stack_number, unit))
                    week_keys.append((stack_number, week))
                    physical_units.append(unit)
                    d.append(float(event is not None and event >= 0))
        # Each stack's FE bipartite graph is connected by its complete-week controls.
        rank = len(set(unit_keys)) + len(set(week_keys)) - len(design["stacks"])
    else:
        raise ValueError("Unknown estimator")
    codes = tuple(pd.factorize(pd.Series(keys))[0] for keys in (unit_keys, week_keys))
    clusters = pd.factorize(pd.Series(physical_units))[0]  # Physical area, never stack-area.
    return AreaRegression(np.array(rows), clusters, codes, np.array(d), rank)


def synthetic_effect(design: dict, delta=-0.10, *, heterogeneous=False) -> np.ndarray:
    effect = np.zeros((len(design["areas"]), design["weeks"]))
    openings = [a["opening_index"] for a in design["areas"] if a["treated"]]
    first, last = min(openings), max(openings)
    for unit, area in enumerate(design["areas"]):
        if not area["treated"]:
            continue
        event = np.arange(design["weeks"]) - area["opening_index"]
        tau = np.log1p(delta)
        if heterogeneous:
            # Larger effects for early cohorts and growth over the first 13 weeks,
            # followed by a plateau. All assumptions are synthetic, not fitted to Y.
            tau *= 1 + (last - area["opening_index"]) / max(last - first, 1)
            values = tau * (1 + np.minimum(np.maximum(event, 0), 12) / 12)
        else:
            values = np.full(design["weeks"], tau)
        effect[unit, event >= 0] = values[event >= 0]
    return effect.ravel()


def untreated_panel(design: dict, *, seed: int, noise_sd=0.25, rho=0.5,
                    repetitions=1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n_units, n_weeks = len(design["areas"]), design["weeks"]
    area_effect = 6.0 + rng.normal(0, 0.4, (n_units, 1, 1))
    week = np.arange(n_weeks)
    calendar = (0.003 * week + 0.2 * np.sin(2 * np.pi * week / 52))[None, :, None]
    errors = rng.normal(0, noise_sd, (n_units, n_weeks, repetitions))
    errors[:, 0, :] /= np.sqrt(1 - rho**2)
    for index in range(1, n_weeks):
        errors[:, index, :] += rho * errors[:, index - 1, :]
    return (area_effect + calendar + errors).reshape(n_units * n_weeks, repetitions)


def equal_area_truth(design: dict, effect: np.ndarray) -> float:
    panel = effect.reshape(len(design["areas"]), design["weeks"])
    return float(np.mean([panel[i, a["opening_index"]:a["opening_index"] + design["post_weeks"] + 1].mean()
                          for i, a in enumerate(design["areas"]) if a["treated"]]))


def clean_area_contrast(design: dict, y: np.ndarray) -> float:
    """Independent equal-area clean DiD benchmark, not the pooled regression estimand."""
    panel = y.reshape(len(design["areas"]), design["weeks"])
    by_id = {a["cell_id"]: i for i, a in enumerate(design["areas"])}
    clean = {s["cohort"]: [by_id[c] for c in s["controls"]] for s in design["stacks"]}
    estimates = []
    for unit, area in enumerate(design["areas"]):
        if not area["treated"]:
            continue
        start = area["opening_index"]
        controls = panel[clean[area["cohort"]]].mean(axis=0)
        difference = panel[unit] - controls
        estimates.append(difference[start:start + design["post_weeks"] + 1].mean()
                         - difference[start - design["pre_weeks"]:start].mean())
    return float(np.mean(estimates))
