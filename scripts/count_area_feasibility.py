"""Count the preregistered area design without reading ridership values or fitting effects."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pandas as pd
import yaml

from stimpact.area_feasibility import count_areas
from stimpact.download import sha256


def check_registration(root: Path, commit: str, config: dict) -> str:
    full_commit = subprocess.check_output(["git", "rev-parse", f"{commit}^{{commit}}"], cwd=root,
                                          text=True, encoding="utf-8").strip()
    registered = yaml.safe_load(subprocess.check_output(
        ["git", "show", f"{full_commit}:config.yaml"], cwd=root, text=True, encoding="utf-8"))
    if registered.get("area_feasibility") != config["area_feasibility"]:
        raise ValueError("Commit the current area rules before counting; registered grid settings differ")
    for key in ("event_pre_weeks", "event_post_weeks"):
        if registered["estimation"][key] != config["estimation"][key]:
            raise ValueError("Event-window rules differ from the preregistered commit")
    for key in ("panel_start", "last_complete_week_start"):
        if registered["study"][key] != config["study"][key]:
            raise ValueError("Study window differs from the preregistered commit")
    document = subprocess.check_output(["git", "show", f"{full_commit}:docs/preregistration.md"], cwd=root,
                                       text=True, encoding="utf-8")
    if "Area-level feasibility amendment committed before counting" not in document:
        raise ValueError("The selected commit does not contain the area feasibility amendment")
    return full_commit


def run(root: Path, prereg_commit: str) -> dict:
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    registered_commit = check_registration(root, prereg_commit, config)
    paths = {"eligible_existing_stations": root / "reports/stage1/eligibility_audit.csv",
             "treatment_sources": root / "reports/stage0/treatment_source_stations.csv",
             "exposure_sources": root / "reports/stage0/exposure_source_stations.csv"}
    # Deliberately do not parse baseline ridership, zero-run counts, or raw trip files.
    old = pd.read_csv(paths["eligible_existing_stations"], dtype={"station_id": "string"},
                      usecols=["station_id", "x_m", "y_m", "eligible"])
    old = old.loc[old.eligible, ["station_id", "x_m", "y_m"]]
    treatment = pd.read_csv(paths["treatment_sources"], dtype={"station_id": "string"},
                            usecols=["station_id", "x_m", "y_m", "analysis_open_date"],
                            parse_dates=["analysis_open_date"])
    exposure = pd.read_csv(paths["exposure_sources"], dtype={"station_id": "string"},
                           usecols=["station_id", "x_m", "y_m", "analysis_open_date", "exposure_only"],
                           parse_dates=["analysis_open_date"])
    result = count_areas(old, treatment, exposure, config)
    summary = {"preregistration_commit": registered_commit, "grid_crs": config["spatial"]["projected_crs"],
               "registered_area_settings": config["area_feasibility"], "eligible_old_stations": len(old),
               "treatment_sources": len(treatment), "exposure_sources": len(exposure),
               "input_hashes": {name: sha256(path) for name, path in paths.items()},
               "grid_counts": result["grid_counts"].to_dict(orient="records"), "decision": result["decision"],
               "ridership_values_parsed": False, "treatment_effect_estimator_run": False}
    output = root / "reports/area_feasibility"
    output.mkdir(parents=True, exist_ok=True)
    for key, filename in (("grid_counts", "grid_counts"), ("areas", "area_assignments"),
                          ("stacks", "stack_control_counts"), ("controls", "control_membership"),
                          ("old_cell_map", "eligible_old_cell_map"), ("source_cell_map", "source_cell_map")):
        result[key].to_csv(output / f"{filename}.csv", index=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    decision = result["decision"]
    lines = ["# Area-level feasibility audit", "",
             f"Design registered before counting in [{registered_commit[:7]}]"
             f"(https://github.com/Anran0716/indego-station-impact/commit/{registered_commit}). "
             f"Inputs: {len(old)} fixed eligible old stations, {len(treatment)} treatment sources, "
             f"and {len(exposure)} exposure sources. No ridership values were parsed, no outcomes "
             "were constructed, and no treatment-effect estimator was run.", "",
             "## Fixed geography and samples", "",
             "Use 1,000-metre EPSG:32618 cells with the committed anchor and half-open boundary "
             "conventions. A study cell must contain an eligible old station; a new-only cell "
             "does not become a treatment unit. A cell containing an unusable exposure source "
             "is excluded. Treatment timing is the first eligible treatment opening inside "
             "the cell. The first opening from any exposure source determines control cleanliness. "
             "Already-exposed cells cannot serve as controls in later stacks.", "",
             "## Counts by preregistered grid offset", "",
             "| Offset x,y metres | Eligible areas | Excluded areas | Treated areas | Never-exposed controls | Min clean controls | Min after adjacency removal | Failed stacks | Main gate |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for row in result["grid_counts"].itertuples():
        lines.append(f"| ({row.offset_x_m}, {row.offset_y_m}) | {row.eligible_areas} | "
                     f"{row.excluded_unusable_areas} | {row.treated_areas} | "
                     f"{row.never_exposed_control_areas} | {row.minimum_clean_controls_per_stack} | "
                     f"{row.minimum_adjacency_controls_per_stack} | {row.failed_stacks}/{row.cohort_stacks} | "
                     f"{row.passes_main_gate} |")
    lines += ["", "The primary grid is fixed at (0,0). The other offsets cannot replace a "
              "failed primary grid. Each grid is evaluated against the same prespecified "
              f"thresholds: at least {decision['min_treated_areas_required']} treated areas and "
              f"at least {decision['min_controls_per_stack_required']} clean controls in every "
              "stack. Adjacency counts are separate sensitivity diagnostics, not a post-hoc "
              "way to change the primary gate.", "",
              "## Stack controls and boundary spillovers", "",
              "Quarterly stacks use the earliest cohort opening minus the configured pre-period "
              "through the latest opening plus the configured post-period. Clean controls have "
              "no exposure opening on or before the last stack week. Eight-neighbour sensitivity "
              "removes controls adjacent by edge or corner to any exposure cell active by then, "
              "including adjacent expansion-only cells. Future exposures after the stack end "
              "do not trigger this restriction. There is no station-radius or 2R buffer in "
              "the main area design.", "",
              "`stack_control_counts.csv` reports all cohort counts. `control_membership.csv` "
              "records each main clean control and its adjacency status. `area_assignments.csv` "
              "records cell eligibility, first dates, additional sources, exclusions, and any "
              "exposure preceding the eligible treatment cohort. Earlier exposure is a registered "
              "timing diagnostic, not a new outcome-driven exclusion.", "",
              "## Decision", "", f"**{decision['decision']}**. On the primary grid, "
              f"there are {decision['primary_treated_areas']} treated areas and a minimum of "
              f"{decision['primary_min_clean_controls']} clean controls across stacks; "
              f"{decision['primary_failed_stacks']} stacks fall below the control threshold.", ""]
    if decision["decision"] == "stop_causal_estimation":
        lines += ["The prespecified area design fails its feasibility gate. Stop observational "
                  "causal estimation; do not lower thresholds, drop failing cohorts, or select "
                  "a favourable grid offset. The project next needs real-variance power "
                  "calculations and a randomized staggered-rollout experiment design alongside "
                  "the feasibility reports. Those follow-up deliverables are not claimed as "
                  "completed by this count-only command.", ""]
    else:
        lines += ["The primary count gate passes. Review the registered adjacency, grid, and "
                  "timing diagnostics before separately specifying or implementing an estimator.", ""]
    lines += ["## Reproduction", "", "```powershell",
              f"python scripts/count_area_feasibility.py --prereg-commit {registered_commit}", "```", "",
              "The command verifies that the area settings and event/study windows match "
              "the chosen committed preregistration. Inputs are hashed in `summary.json`; "
              "the eligibility CSV is read only for ID, fixed position, and its existing "
              "qualification flag. Raw trips and baseline/weekly ridership fields are not read.", ""]
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prereg-commit", required=True, help="Commit containing the registered grid rules")
    arguments = parser.parse_args()
    run(Path(__file__).resolve().parents[1], arguments.prereg_commit)
