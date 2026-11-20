"""Assign groups with distinct treatment sources and all operating exposure sources."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _monday(date) -> pd.Timestamp:
    date = pd.Timestamp(date).normalize()
    return date - pd.Timedelta(days=date.weekday())


def assign_treatment(existing: pd.DataFrame, treatment_sources: pd.DataFrame,
                     exposure_sources: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Accept an eligibility-screened old-station pool; count no real-data radius here.

    An unusable source within 2R excludes a station before either treated/control
    assignment. Exposure sources outside the treatment window remain valid for
    buffer and no-pre/no-post checks. Renumbered aliases are already canonicalized.
    """
    spatial, study, estimation = config["spatial"], config["study"], config["estimation"]
    radius = spatial["treatment_radius_m"]
    if radius is None or not np.isfinite(radius) or radius <= 0:
        raise ValueError("Select a positive treatment_radius_m before group assignment")
    outer = radius * spatial["buffer_outer_multiplier"]
    if not set(treatment_sources.station_id) <= set(exposure_sources.station_id):
        raise ValueError("Treatment sources must also appear in exposure sources")
    if exposure_sources[["x_m", "y_m"]].isna().any().any():
        raise ValueError("Exposure source coordinates are missing")
    if exposure_sources.analysis_open_date.isna().any():
        raise ValueError("Exposure source opening dates are missing")
    if existing.station_id.duplicated().any() or exposure_sources.station_id.duplicated().any():
        raise ValueError("Duplicate station ID in group-assignment inputs")
    source_ids = set(treatment_sources.station_id)
    records = []
    for station in existing.itertuples():
        distances = np.hypot(exposure_sources.x_m - station.x_m, exposure_sources.y_m - station.y_m)
        within_outer = exposure_sources.loc[distances.le(outer)].copy()
        within_inner = exposure_sources.loc[distances.le(radius)].copy()
        usable_inner = within_inner.loc[within_inner.station_id.isin(source_ids)].copy()
        usable_inner = usable_inner.sort_values(["analysis_open_date", "station_id"])
        unusable = within_outer.loc[within_outer.exposure_only]
        result = {"station_id": station.station_id, "group": "control", "reason": "never_exposed",
                  "cohort_week": pd.NaT, "cohort_quarter": None,
                  "n_new_within_r": len(usable_inner),
                  "nearest_new_m": float(distances.min()) if len(distances) else np.nan,
                  "second_hit": False,
                  "unusable_source_ids": ";".join(sorted(unusable.station_id.astype(str)))}
        if getattr(station, "identity_excluded", False):
            result.update(group="excluded", reason="existing_identity_excluded")
        elif not np.isfinite(station.x_m) or not np.isfinite(station.y_m):
            result.update(group="excluded", reason="missing_existing_coordinates")
        elif not unusable.empty:
            result.update(group="excluded", reason="exposed_to_unusable_source")
        elif not within_inner.empty:
            first = within_inner.sort_values(["analysis_open_date", "station_id"]).iloc[0]
            date = pd.Timestamp(first.analysis_open_date)
            if date < pd.Timestamp(study["treatment_opening_start"]):
                result.update(group="excluded", reason="no_pre_period")
            elif date > pd.Timestamp(study["treatment_opening_end"]):
                result.update(group="excluded", reason="no_post_period")
            elif first.station_id not in source_ids:
                raise ValueError("Usable in-window exposure is missing from treatment sources")
            else:
                week = _monday(first.analysis_open_date)
                second = usable_inner.loc[usable_inner.station_id.ne(first.station_id)]
                second_weeks = second.analysis_open_date.map(_monday)
                second_hit = second_weeks.le(week + pd.Timedelta(weeks=estimation["event_post_weeks"])).any()
                result.update(group="treated", reason="eligible_opening", cohort_week=week,
                              cohort_quarter=str(week.to_period("Q")), second_hit=bool(second_hit))
        elif not within_outer.empty:
            result.update(group="buffer", reason="exposed_between_r_and_2r")
        records.append(result)
    result = pd.DataFrame(records)
    if len(result) != len(existing) or result.station_id.duplicated().any():
        raise AssertionError("Every existing station must be assigned exactly once")
    return result


def clean_control_mask(existing: pd.DataFrame, exposure_sources: pd.DataFrame,
                       stack_last_week, config: dict) -> pd.Series:
    """No exposure of any eligibility type may occur during or before the stack end week."""
    radius = config["spatial"]["treatment_radius_m"]
    if radius is None or radius <= 0:
        raise ValueError("Select a positive treatment_radius_m before checking controls")
    if exposure_sources[["x_m", "y_m", "analysis_open_date"]].isna().any().any():
        raise ValueError("Exposure source position or opening date is missing")
    outer = radius * config["spatial"]["buffer_outer_multiplier"]
    end = _monday(stack_last_week)
    exposed_weeks = exposure_sources.analysis_open_date.map(_monday)
    safe = []
    for station in existing.itertuples():
        distances = np.hypot(exposure_sources.x_m - station.x_m, exposure_sources.y_m - station.y_m)
        valid_position = np.isfinite(station.x_m) and np.isfinite(station.y_m)
        safe.append(bool(valid_position and not getattr(station, "identity_excluded", False)
                         and not (distances.le(outer) & exposed_weeks.le(end)).any()))
    return pd.Series(safe, index=existing.index, name="clean_control")
