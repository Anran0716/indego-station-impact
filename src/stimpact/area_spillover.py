"""Distance-based control restrictions; never a main-design feasibility gate."""

from __future__ import annotations

import numpy as np
import pandas as pd


def count_distance_controls(area_result: dict, config: dict) -> dict[str, pd.DataFrame]:
    rules = config["spillover_distance"]
    if rules["changes_main_gate"] or rules["radius_m"] <= 0:
        raise ValueError("Distance sensitivity must not change the main gate")
    counts, memberships, hits = [], [], []
    for stack in area_result["stacks"].itertuples():
        dx, dy, cohort = stack.offset_x_m, stack.offset_y_m, stack.cohort_quarter
        sources = area_result["source_cell_map"]
        sources = sources.loc[sources.offset_x_m.eq(dx) & sources.offset_y_m.eq(dy)]
        # Raw dates, inclusive whole calendar weeks, not only dates before the last Monday.
        active = sources.loc[sources.analysis_open_date.ge(pd.Timestamp(stack.stack_first_week))
                             & sources.analysis_open_date.lt(
                                 pd.Timestamp(stack.stack_last_week) + pd.Timedelta(days=7))]
        old = area_result["old_cell_map"]
        old = old.loc[old.offset_x_m.eq(dx) & old.offset_y_m.eq(dy)]
        controls = area_result["controls"]
        controls = controls.loc[controls.offset_x_m.eq(dx) & controls.offset_y_m.eq(dy)
                                & controls.cohort_quarter.eq(cohort)]
        kept = 0
        for control in controls.itertuples():
            local_old = old.loc[old.cell_id.eq(control.cell_id)]
            if local_old.empty:
                raise ValueError("A control area has no qualified old station")
            distances = np.linalg.norm(local_old[["x_m", "y_m"]].to_numpy()[:, None, :]
                                       - active[["x_m", "y_m"]].to_numpy()[None, :, :], axis=2)
            pairs = np.argwhere(distances <= rules["radius_m"])
            for old_index, new_index in pairs:
                hits.append({"offset_x_m": dx, "offset_y_m": dy, "cohort_quarter": cohort,
                             "cell_id": control.cell_id,
                             "old_station_id": local_old.iloc[old_index].station_id,
                             "new_station_id": active.iloc[new_index].station_id,
                             "opening_date": active.iloc[new_index].analysis_open_date,
                             "distance_m": distances[old_index, new_index]})
            keep = not len(pairs)
            kept += int(keep)
            memberships.append({"offset_x_m": dx, "offset_y_m": dy, "cohort_quarter": cohort,
                                "cell_id": control.cell_id, "control_type": control.control_type,
                                "kept_after_distance": keep, "nearby_opening_pairs": len(pairs),
                                "minimum_distance_m": float(distances.min()) if distances.size else np.nan,
                                "reason": "" if keep else "old_station_within_400m_of_stack_opening"})
        counts.append({"offset_x_m": dx, "offset_y_m": dy, "cohort_quarter": cohort,
                       "stack_first_week": stack.stack_first_week,
                       "stack_last_week": stack.stack_last_week,
                       "main_clean_controls": len(controls), "openings_during_stack": len(active),
                       "removed_controls": len(controls) - kept, "distance_controls": kept,
                       "minimum_required": rules["min_controls_per_stack"],
                       "status": "estimable" if kept >= rules["min_controls_per_stack"]
                       else "not_estimable"})
    stacks = pd.DataFrame(counts)
    grids = []
    for (dx, dy), group in stacks.groupby(["offset_x_m", "offset_y_m"], sort=False):
        failures = group.status.ne("estimable")
        grids.append({"offset_x_m": dx, "offset_y_m": dy, "stacks": len(group),
                      "minimum_distance_controls": int(group.distance_controls.min()),
                      "maximum_distance_controls": int(group.distance_controls.max()),
                      "failed_stacks": int(failures.sum()),
                      "status": "not_estimable" if failures.any() else "estimable"})
    return {"stacks": stacks, "controls": pd.DataFrame(memberships),
            "excluded_pairs": pd.DataFrame(hits), "grids": pd.DataFrame(grids)}
