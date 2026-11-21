"""Count fixed-grid area feasibility using locations and opening dates only."""

from __future__ import annotations

import numpy as np
import pandas as pd


def grid_membership(points: pd.DataFrame, offset: tuple[int, int], config: dict) -> pd.DataFrame:
    area = config["area_feasibility"]
    if area["cell_size_m"] <= 0:
        raise ValueError("Grid cell size must be positive")
    if not np.isfinite(points[["x_m", "y_m"]].to_numpy()).all():
        raise ValueError("Area membership requires known finite positions")
    result = points.copy()
    result["cell_col"] = np.floor((result.x_m - area["anchor_x_m"] - offset[0]) / area["cell_size_m"]).astype(int)
    result["cell_row"] = np.floor((result.y_m - area["anchor_y_m"] - offset[1]) / area["cell_size_m"]).astype(int)
    result["cell_id"] = result.cell_col.astype(str) + ":" + result.cell_row.astype(str)
    result["offset_x_m"], result["offset_y_m"] = offset
    return result


def _week(date) -> pd.Timestamp:
    date = pd.Timestamp(date).normalize()
    return date - pd.Timedelta(days=date.weekday())


def passes_gate(treated: int, controls: list[int], config: dict) -> bool:
    area = config["area_feasibility"]
    return bool(treated >= area["min_treated_areas"] and controls
                and all(count >= area["min_clean_controls_per_stack"] for count in controls))


def area_decision(counts: pd.DataFrame, config: dict) -> dict:
    area = config["area_feasibility"]
    dx, dy = area["primary_offset_m"]
    primary = counts.loc[counts.offset_x_m.eq(dx) & counts.offset_y_m.eq(dy)]
    if len(primary) != 1:
        raise ValueError("Exactly one fixed primary grid is required")
    row = primary.iloc[0]
    passed = bool(row.passes_main_gate)
    return {"decision": "primary_area_feasible" if passed else "stop_causal_estimation",
            "primary_offset_m": [dx, dy], "primary_treated_areas": int(row.treated_areas),
            "primary_min_clean_controls": int(row.minimum_clean_controls_per_stack),
            "primary_failed_stacks": int(row.failed_stacks),
            "min_treated_areas_required": area["min_treated_areas"],
            "min_controls_per_stack_required": area["min_clean_controls_per_stack"],
            "all_offsets_pass": bool(counts.passes_main_gate.all()),
            "all_adjacency_diagnostics_pass": bool(counts.passes_adjacency_gate.all()),
            "passing_offsets": [[int(row.offset_x_m), int(row.offset_y_m)]
                                for row in counts.loc[counts.passes_main_gate].itertuples()],
            "action": "review_diagnostics_before_any_estimation" if passed
            else "retain_feasibility_reports_and_plan_power_and_randomized_rollout"}


def count_areas(eligible_old: pd.DataFrame, treatment: pd.DataFrame,
                exposure: pd.DataFrame, config: dict) -> dict[str, pd.DataFrame | dict]:
    """Count every prespecified grid without reading or constructing an outcome."""
    if config["spatial"]["projected_crs"] != "EPSG:32618":
        raise ValueError("The registered area design requires EPSG:32618")
    for name, frame in (("eligible old", eligible_old), ("treatment", treatment), ("exposure", exposure)):
        if frame.station_id.isna().any() or frame.station_id.duplicated().any():
            raise ValueError(f"Missing or duplicate IDs in {name} input")
    if not set(treatment.station_id) <= set(exposure.station_id):
        raise ValueError("Treatment sources must be included among exposure sources")
    if exposure.analysis_open_date.isna().any():
        raise ValueError("Exposure opening dates are missing")
    # The same canonical source must have one position/date in both source tables.
    shared = treatment.merge(exposure, on="station_id", suffixes=("_t", "_e"), validate="one_to_one")
    for column in ("x_m", "y_m"):
        if not np.allclose(shared[f"{column}_t"], shared[f"{column}_e"], rtol=0, atol=1e-6):
            raise ValueError("Treatment/exposure positions disagree")
    if not shared.analysis_open_date_t.eq(shared.analysis_open_date_e).all():
        raise ValueError("Treatment/exposure dates disagree")
    area = config["area_feasibility"]
    summaries, cell_tables, stack_rows, control_rows, old_maps, source_maps = [], [], [], [], [], []
    for offset_values in area["offsets_m"]:
        offset = tuple(offset_values)
        old = grid_membership(eligible_old, offset, config)
        sources = grid_membership(exposure, offset, config)
        sources["in_treatment_table"] = sources.station_id.isin(treatment.station_id)
        sources["opening_week"] = sources.analysis_open_date.map(_week)
        old_maps.append(old)
        source_maps.append(sources)
        old_counts = old.groupby("cell_id").station_id.size()
        keys = pd.concat([old[["cell_id", "cell_col", "cell_row"]],
                          sources[["cell_id", "cell_col", "cell_row"]]]).drop_duplicates("cell_id")
        records = []
        for key in keys.sort_values(["cell_col", "cell_row"]).itertuples():
            in_cell = sources.loc[sources.cell_id.eq(key.cell_id)]
            new = in_cell.loc[in_cell.in_treatment_table].sort_values(["analysis_open_date", "station_id"])
            unusable = in_cell.loc[in_cell.exposure_only]
            n_old = int(old_counts.get(key.cell_id, 0))
            eligible = n_old >= area["min_eligible_old_stations"]
            excluded = eligible and not unusable.empty
            treated = eligible and not excluded and not new.empty
            first_treatment_date = new.iloc[0].analysis_open_date if not new.empty else pd.NaT
            first_treatment_week = new.iloc[0].opening_week if not new.empty else pd.NaT
            first_exposure_date = in_cell.analysis_open_date.min()
            first_exposure_week = in_cell.opening_week.min()
            role = ("excluded_unusable_exposure" if excluded else "treated" if treated else
                    "eligible_never_exposed" if eligible and in_cell.empty else
                    "eligible_with_other_or_future_exposure" if eligible else "outside_eligible_sample")
            records.append({"offset_x_m": offset[0], "offset_y_m": offset[1], "cell_id": key.cell_id,
                            "cell_col": key.cell_col, "cell_row": key.cell_row,
                            "eligible_old_stations": n_old, "eligible_area": eligible, "excluded": excluded,
                            "reason": "area_contains_unusable_exposure" if excluded else "",
                            "treated": treated, "role": role,
                            "treatment_sources": len(new), "exposure_sources": len(in_cell),
                            "unusable_source_ids": ";".join(unusable.station_id.astype(str)),
                            "first_treatment_date": first_treatment_date,
                            "cohort_week": first_treatment_week,
                            "cohort_quarter": str(first_treatment_week.to_period("Q"))
                            if pd.notna(first_treatment_week) else None,
                            "first_exposure_date": first_exposure_date,
                            "first_exposure_week": first_exposure_week,
                            "prior_exposure_before_eligible_cohort": bool(
                                treated and pd.notna(first_exposure_date)
                                and first_exposure_date < first_treatment_date)})
        cells = pd.DataFrame(records)
        if (int(cells.eligible_old_stations.sum()) != len(old)
                or int(cells.exposure_sources.sum()) != len(sources)
                or int(cells.treatment_sources.sum()) != len(treatment)):
            raise AssertionError("Grid aggregation loses existing stations or opening sources")
        cell_tables.append(cells)
        available = cells.loc[cells.eligible_area & ~cells.excluded]
        treated_cells = cells.loc[cells.treated]
        current_stacks = []
        for cohort, cohort_cells in treated_cells.groupby("cohort_quarter"):
            start = cohort_cells.cohort_week.min() - pd.Timedelta(weeks=config["estimation"]["event_pre_weeks"])
            end = cohort_cells.cohort_week.max() + pd.Timedelta(weeks=config["estimation"]["event_post_weeks"])
            if start < pd.Timestamp(config["study"]["panel_start"]) or end > pd.Timestamp(
                config["study"]["last_complete_week_start"]):
                raise AssertionError("Area stack exceeds the complete-week study window")
            clean = available.loc[available.first_exposure_week.isna() | available.first_exposure_week.gt(end)]
            active = sources.loc[sources.opening_week.le(end), ["cell_id", "cell_col", "cell_row"]].drop_duplicates()
            kept_after_adjacency = 0
            for control in clean.itertuples():
                col_delta = (active.cell_col - control.cell_col).abs()
                row_delta = (active.cell_row - control.cell_row).abs()
                adjacent = active.loc[col_delta.le(1) & row_delta.le(1) & (col_delta.gt(0) | row_delta.gt(0))]
                kept = adjacent.empty
                kept_after_adjacency += int(kept)
                control_rows.append({"offset_x_m": offset[0], "offset_y_m": offset[1],
                                     "cohort_quarter": cohort, "cell_id": control.cell_id,
                                     "control_type": "never_exposed" if pd.isna(control.first_exposure_week)
                                     else "not_yet_exposed",
                                     "kept_after_adjacency": kept,
                                     "adjacent_active_exposure_cells": ";".join(adjacent.cell_id)})
            never = int(clean.first_exposure_week.isna().sum())
            row = {"offset_x_m": offset[0], "offset_y_m": offset[1], "cohort_quarter": cohort,
                   "treated_areas": len(cohort_cells), "stack_first_week": start, "stack_last_week": end,
                   "never_exposed_controls": never, "not_yet_exposed_controls": len(clean) - never,
                   "clean_controls": len(clean), "adjacency_restricted_controls": kept_after_adjacency,
                   "passes_min_controls": len(clean) >= area["min_clean_controls_per_stack"],
                   "adjacency_passes_min_controls": kept_after_adjacency >= area["min_clean_controls_per_stack"]}
            stack_rows.append(row)
            current_stacks.append(row)
        control_counts = [row["clean_controls"] for row in current_stacks]
        adjacency_counts = [row["adjacency_restricted_controls"] for row in current_stacks]
        summaries.append({"offset_x_m": offset[0], "offset_y_m": offset[1],
                          "is_primary": list(offset) == area["primary_offset_m"],
                          "eligible_areas": int(cells.eligible_area.sum()),
                          "excluded_unusable_areas": int(cells.excluded.sum()),
                          "treated_areas": len(treated_cells),
                          "never_exposed_control_areas": int(available.first_exposure_week.isna().sum()),
                          "exposure_cells_without_eligible_old": int((~cells.eligible_area & cells.exposure_sources.gt(0)).sum()),
                          "cohort_stacks": len(current_stacks),
                          "minimum_clean_controls_per_stack": min(control_counts, default=0),
                          "minimum_adjacency_controls_per_stack": min(adjacency_counts, default=0),
                          "failed_stacks": sum(not row["passes_min_controls"] for row in current_stacks),
                          "passes_main_gate": passes_gate(len(treated_cells), control_counts, config),
                          "passes_adjacency_gate": passes_gate(len(treated_cells), adjacency_counts, config)})
    counts = pd.DataFrame(summaries)
    stacks = pd.DataFrame(stack_rows, columns=[
        "offset_x_m", "offset_y_m", "cohort_quarter", "treated_areas", "stack_first_week", "stack_last_week",
        "never_exposed_controls", "not_yet_exposed_controls", "clean_controls",
        "adjacency_restricted_controls", "passes_min_controls", "adjacency_passes_min_controls",
    ])
    membership = pd.DataFrame(control_rows, columns=[
        "offset_x_m", "offset_y_m", "cohort_quarter", "cell_id", "control_type",
        "kept_after_adjacency", "adjacent_active_exposure_cells",
    ])
    return {"grid_counts": counts, "areas": pd.concat(cell_tables, ignore_index=True),
            "stacks": stacks, "controls": membership,
            "old_cell_map": pd.concat(old_maps, ignore_index=True),
            "source_cell_map": pd.concat(source_maps, ignore_index=True),
            "decision": area_decision(counts, config)}
