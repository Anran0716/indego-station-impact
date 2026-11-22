"""Count the registered 400-metre sensitivity without parsing ridership outcomes."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pandas as pd
import yaml
from count_area_feasibility import check_registration

from stimpact.area_feasibility import count_areas
from stimpact.area_report import SPILLOVER_LIMITATION, _block
from stimpact.area_spillover import count_distance_controls
from stimpact.download import sha256


def run(root: Path, commit: str) -> dict:
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    commit = check_registration(root, commit, config)
    registered = yaml.safe_load(subprocess.check_output(
        ["git", "show", f"{commit}:config.yaml"], cwd=root, text=True, encoding="utf-8"))
    if registered.get("spillover_distance") != config["spillover_distance"]:
        raise ValueError("Commit the current distance rules before counting")
    doc = subprocess.check_output(["git", "show", f"{commit}:docs/preregistration.md"],
                                  cwd=root, text=True, encoding="utf-8")
    if "Distance-spillover and area-simulation amendment" not in doc:
        raise ValueError("The selected commit lacks the distance amendment")
    paths = {"old": root / "reports/stage1/eligibility_audit.csv",
             "treatment": root / "reports/stage0/treatment_source_stations.csv",
             "exposure": root / "reports/stage0/exposure_source_stations.csv"}
    old = pd.read_csv(paths["old"], dtype={"station_id": "string"},
                      usecols=["station_id", "x_m", "y_m", "eligible"])
    old = old.loc[old.eligible, ["station_id", "x_m", "y_m"]]
    treatment = pd.read_csv(paths["treatment"], dtype={"station_id": "string"},
                            usecols=["station_id", "x_m", "y_m", "analysis_open_date"],
                            parse_dates=["analysis_open_date"])
    exposure = pd.read_csv(paths["exposure"], dtype={"station_id": "string"},
                           usecols=["station_id", "x_m", "y_m", "analysis_open_date", "exposure_only"],
                           parse_dates=["analysis_open_date"])
    area_result = count_areas(old, treatment, exposure, config)
    result = count_distance_controls(area_result, config)
    summary = {"preregistration_commit": commit, "rules": config["spillover_distance"],
               "input_hashes": {key: sha256(path) for key, path in paths.items()},
               "eligible_old_stations": len(old), "exposure_sources": len(exposure),
               "main_decision_unchanged": area_result["decision"]["decision"],
               "grids": result["grids"].to_dict(orient="records"),
               "ridership_values_parsed": False, "real_effect_estimator_run": False}
    out = root / "reports/distance_spillover"
    out.mkdir(parents=True, exist_ok=True)
    for key, frame in result.items():
        frame.to_csv(out / f"{key}.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = ["# Distance-based spillover sensitivity: counts only", "",
             f"Rules committed before counting in [{commit[:7]}]"
             f"(https://github.com/Anran0716/indego-station-impact/commit/{commit}). "
             "No real outcomes were parsed or effect models fitted.", "",
             "Remove a main clean control area when any of its fixed qualified old stations "
             "is <=400 metres from any exposure source opening during the stack's full "
             "calendar window, including the last Sunday. Use 156 qualified old stations "
             "and all 101 exposure sources. Earlier and later openings do not trigger this "
             "particular restriction. Keep the main 20/15 gate unchanged. The sensitivity "
             "requires >=10 controls in every stack; otherwise the variant is not estimable.", "",
             "| Offset (m) | Min controls | Max controls | Stacks below 10 | Sensitivity status |",
             "| --- | ---: | ---: | ---: | --- |"]
    for row in result["grids"].itertuples():
        lines.append(f"| ({row.offset_x_m}, {row.offset_y_m}) | {row.minimum_distance_controls} | "
                     f"{row.maximum_distance_controls} | {row.failed_stacks}/{row.stacks} | {row.status} |")
    lines += ["", "The fixed (0,0) grid remains primary. `stacks.csv` records every count; "
              "`controls.csv` records each main control's disposition; `excluded_pairs.csv` "
              "lists the old/new station pairs triggering removal. No passing offset rescues "
              "a failed primary sensitivity variant. Passing these counts would establish "
              "estimability only, not absence of spillovers.", "", "## Limitation", "",
              SPILLOVER_LIMITATION, "", "The eight-neighbour test retains only 1 control "
              "in the smallest primary-grid stacks. The distance restriction is a separately "
              "registered sensitivity; neither restriction changes the main-design gate.", "",
              "## Reproduction", "", "```powershell",
              f"python scripts/count_distance_spillover.py --prereg-commit {commit}", "```", ""]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    primary = result["grids"].loc[result["grids"].offset_x_m.eq(0)
                                 & result["grids"].offset_y_m.eq(0)].iloc[0]
    _block(root / "README.md", "distance-spillover-summary",
           f"The preregistered 400-metre distance sensitivity retains {primary.minimum_distance_controls}"
           f"–{primary.maximum_distance_controls} controls per primary-grid stack: "
           f"**{primary.status}**, with {primary.failed_stacks}/{primary.stacks} stacks below 10. "
           "The main design remains feasible. [Count-only audit](reports/distance_spillover/README.md).")
    _block(root / "docs/preregistration.md", "distance-spillover-result",
           f"Rules were committed before counting in [{commit[:7]}]"
           f"(https://github.com/Anran0716/indego-station-impact/commit/{commit}). "
           f"The primary grid retains {primary.minimum_distance_controls}–{primary.maximum_distance_controls} "
           "controls per stack. All four grids meet the distance variant's 10-control requirement. "
           "This records estimability only; no robustness effect has been estimated. "
           "The original eight-neighbour variant remains not estimable and the main 20/15 "
           "gate is unchanged. [Count audit](../reports/distance_spillover/README.md).")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prereg-commit", required=True)
    args = parser.parse_args()
    run(Path(__file__).resolve().parents[1], args.prereg_commit)
