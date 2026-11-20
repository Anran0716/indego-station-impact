"""Apply prespecified eligibility and radius rules without estimating treatment effects."""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd

from stimpact.treatment import assign_treatment, clean_control_mask


def weekly_departures(trips: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, dict]:
    """Use already canonicalized endpoints and the same cleaning as the planned panel."""
    short = trips.duration_seconds.lt(config["eligibility"]["min_trip_duration_seconds"])
    same = ~short & trips.start_station.eq(trips.end_station)
    clean = trips.loc[~short & ~same].copy()
    clean["week"] = clean.start_time.dt.to_period("W-SUN").dt.start_time
    within = clean.week.between(pd.Timestamp(config["study"]["panel_start"]),
                                pd.Timestamp(config["study"]["last_complete_week_start"]))
    counts = clean.loc[within].groupby(["start_station", "week"]).size().rename("departures").reset_index()
    counts = counts.rename(columns={"start_station": "station_id"})
    audit = {"normalized_trips": len(trips), "short_trips": int(short.sum()),
             "same_physical_station_trips": int(same.sum()),
             "outside_complete_weeks": int((~within).sum()), "counted_departures": int(within.sum())}
    if len(trips) != sum(audit[key] for key in (
        "short_trips", "same_physical_station_trips", "outside_complete_weeks", "counted_departures",
    )) or int(counts.departures.sum()) != audit["counted_departures"]:
        raise AssertionError("Cleaning and weekly departure counts do not conserve trips")
    return counts, audit


def longest_zero_run(values) -> int:
    longest, current = 0, 0
    for value in values:
        current = current + 1 if value == 0 else 0
        longest = max(longest, current)
    return longest


def screen_existing_stations(canonical: pd.DataFrame, weekly: pd.DataFrame,
                              config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    study, eligibility = config["study"], config["eligibility"]
    old = canonical.loc[canonical.analysis_open_date.lt(
        pd.Timestamp(study["existing_station_opened_before"]))].copy()
    weeks = pd.date_range(study["panel_start"], study["last_complete_week_start"], freq="7D")
    baseline_weeks = pd.date_range(eligibility["baseline_first_week"], eligibility["baseline_last_week"], freq="7D")
    if not set(baseline_weeks) <= set(weeks):
        raise ValueError("Baseline weeks are outside the complete-week study window")
    if old.station_id.duplicated().any():
        raise ValueError("Duplicate canonical existing-station ID")
    grid = pd.MultiIndex.from_product([old.station_id, weeks], names=["station_id", "week"])
    old_counts = weekly.loc[weekly.station_id.isin(old.station_id)]
    grouped = old_counts.groupby(["station_id", "week"]).departures.sum()
    dense = grouped.reindex(grid, fill_value=0).rename("departures").reset_index()
    relevant_sum = old_counts.loc[old_counts.week.isin(weeks), "departures"].sum()
    if int(dense.departures.sum()) != int(relevant_sum):
        raise AssertionError("Existing-station eligibility grid loses departures")
    means = dense.loc[dense.week.isin(baseline_weeks)].groupby("station_id").departures.mean()
    zero_runs = dense.groupby("station_id").departures.agg(longest_zero_run)
    old["baseline_weeks"] = len(baseline_weeks)
    old["baseline_weekly_departures"] = old.station_id.map(means)
    old["longest_zero_run_weeks"] = old.station_id.map(zero_runs)
    old["eligible"] = False
    old["eligibility_reason"] = ""
    for index, station in old.iterrows():
        if station.identity_excluded or not station.eligible_existing_identity:
            reason = "identity_excluded"
        elif not np.isfinite(station.x_m) or not np.isfinite(station.y_m):
            reason = "missing_coordinates"
        elif station.baseline_weekly_departures < eligibility["min_baseline_weekly_departures"]:
            reason = "baseline_below_minimum"
        elif station.longest_zero_run_weeks > eligibility["exclude_zero_runs_longer_than_weeks"]:
            reason = "inactive_zero_run"
        else:
            reason = ""
        old.loc[index, "eligible"] = reason == ""
        old.loc[index, "eligibility_reason"] = reason
    return old, dense


def decide_radius(counts: pd.DataFrame, config: dict) -> dict:
    radii = config["spatial"]["candidate_radii_m"]
    minimum = config["feasibility"]["min_treated_stations"]
    preferred = config["feasibility"]["preferred_treated_stations"]
    indexed = counts.set_index("radius_m")
    chosen = radii[0]
    if indexed.loc[chosen, "treated_stations"] < minimum:
        chosen = radii[1]
    treated = int(indexed.loc[chosen, "treated_stations"])
    if treated < minimum:
        status, reason = "redesign_area_level", "fewer_than_minimum_treated_at_fallback_radius"
    elif not indexed.loc[chosen, "all_stacks_have_min_controls"]:
        status, reason = "redesign_area_level", "insufficient_clean_controls_in_at_least_one_stack"
    else:
        status, reason = "station_level_feasible", "prespecified_station_count_rules_pass"
    return {"decision": status, "reason": reason, "radius_from_treated_count_rule_m": chosen,
            "selected_radius_m": chosen if status == "station_level_feasible" else None,
            "limited_treated_sample": treated < preferred,
            "min_controls_required": config["estimation"]["min_controls_per_stack"]}


def radius_feasibility(existing: pd.DataFrame, treatment: pd.DataFrame, exposure: pd.DataFrame,
                       config: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    radius_records, all_assignments, stack_records = [], [], []
    required = config["estimation"]["min_controls_per_stack"]
    for radius in config["spatial"]["candidate_radii_m"]:
        settings = deepcopy(config)
        settings["spatial"]["treatment_radius_m"] = radius
        assigned = assign_treatment(existing, treatment, exposure, settings)
        assigned.insert(0, "radius_m", radius)
        all_assignments.append(assigned)
        groups = assigned.group.value_counts()
        never_ids = set(assigned.loc[assigned.group.eq("control"), "station_id"])
        treated = assigned.loc[assigned.group.eq("treated")]
        current_stacks = []
        for cohort, cohort_rows in treated.groupby("cohort_quarter"):
            first_week = cohort_rows.cohort_week.min() - pd.Timedelta(weeks=settings["estimation"]["event_pre_weeks"])
            last_week = cohort_rows.cohort_week.max() + pd.Timedelta(weeks=settings["estimation"]["event_post_weeks"])
            if first_week < pd.Timestamp(settings["study"]["panel_start"]) or last_week > pd.Timestamp(
                settings["study"]["last_complete_week_start"]):
                raise AssertionError("A stack extends outside the complete-week study window")
            mask = clean_control_mask(existing, exposure, last_week, settings)
            clean_ids = set(existing.loc[mask, "station_id"])
            if not never_ids <= clean_ids:
                raise AssertionError("A never-exposed control failed the stack clean-control check")
            use_fallback = len(never_ids) < required
            used = clean_ids if use_fallback else never_ids
            record = {"radius_m": radius, "cohort_quarter": cohort,
                      "treated_stations": len(cohort_rows), "stack_first_week": first_week,
                      "stack_last_week": last_week, "never_treated_controls": len(never_ids),
                      "additional_clean_controls_available": len(clean_ids - never_ids),
                      "all_clean_controls_available": len(clean_ids), "controls_used": len(used),
                      "control_mode": "augmented_clean_controls" if use_fallback else "never_treated",
                      "passes_min_controls": len(used) >= required}
            stack_records.append(record)
            current_stacks.append(record)
        min_controls = min((row["controls_used"] for row in current_stacks), default=0)
        all_pass = bool(current_stacks) and all(row["passes_min_controls"] for row in current_stacks)
        radius_records.append({"radius_m": radius, "eligible_existing_stations": len(existing),
                               "treated_stations": int(groups.get("treated", 0)),
                               "never_treated_controls": int(groups.get("control", 0)),
                               "buffer_stations": int(groups.get("buffer", 0)),
                               "excluded_stations": int(groups.get("excluded", 0)),
                               "cohort_stacks": len(current_stacks),
                               "minimum_controls_used_per_stack": min_controls,
                               "all_stacks_have_min_controls": all_pass,
                               "treated_with_multiple_sources": int(treated.n_new_within_r.gt(1).sum())})
        if sum(int(groups.get(group, 0)) for group in ("treated", "control", "buffer", "excluded")) != len(existing):
            raise AssertionError("Group counts do not conserve eligible existing stations")
    counts = pd.DataFrame(radius_records)
    assignments = pd.concat(all_assignments, ignore_index=True)
    stacks = pd.DataFrame(stack_records, columns=[
        "radius_m", "cohort_quarter", "treated_stations", "stack_first_week", "stack_last_week",
        "never_treated_controls", "additional_clean_controls_available", "all_clean_controls_available",
        "controls_used", "control_mode", "passes_min_controls",
    ])
    return counts, assignments, stacks, decide_radius(counts, config)
