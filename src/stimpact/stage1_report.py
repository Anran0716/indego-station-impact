"""Record the feasibility decision and its diagnostics without freezing a failed design."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def _replace_block(path: Path, marker: str, content: str) -> None:
    text = path.read_text(encoding="utf-8")
    block = f"<!-- {marker}:start -->\n{content}\n<!-- {marker}:end -->"
    pattern = rf"<!-- {marker}:start -->.*?<!-- {marker}:end -->"
    if re.search(pattern, text, flags=re.DOTALL):
        text = re.sub(pattern, lambda match: block, text, flags=re.DOTALL)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")


def record_results(root: Path, summary: dict, stacks: pd.DataFrame,
                    assignments: pd.DataFrame) -> None:
    output = root / "reports/stage1"
    decision = summary["decision"]
    radius = decision["radius_from_treated_count_rule_m"]
    row = next(item for item in summary["radii"] if item["radius_m"] == radius)
    chosen_stacks = stacks.loc[stacks.radius_m.eq(radius)]
    failed = chosen_stacks.loc[~chosen_stacks.passes_min_controls]
    reasons = assignments.loc[assignments.group.eq("excluded")].groupby(
        ["radius_m", "reason"]).size().rename("stations").reset_index()
    reasons.to_csv(output / "exclusion_reason_counts.csv", index=False)
    if decision["decision"] == "redesign_area_level":
        action = "**Area-level redesign required.** Keep the station-level radius unset; "
        action += "the next preregistration must specify the one-kilometre-area design before estimation."
    else:
        action = f"**Station-level design passes at R = {decision['selected_radius_m']} metres.** "
        action += "Freeze the selected radius and control rule before estimating real-data effects."
    brief = (
        f"Stage 1 screened {summary['eligible_existing_stations']} eligible existing stations. "
        f"At the rule-selected candidate R = {radius} metres: {row['treated_stations']} treated, "
        f"{row['never_treated_controls']} never-exposed controls; the minimum after clean-control "
        f"augmentation is {row['minimum_controls_used_per_stack']}. "
        f"{len(failed)} of {len(chosen_stacks)} stacks fall below "
        f"{decision['min_controls_required']} controls. {action} "
        "See the [feasibility audit](reports/stage1/README.md)."
    )
    _replace_block(root / "README.md", "stage1-summary", brief)
    prereg = (
        f"Feasibility decision before real-data estimation: **{decision['decision']}**. "
        f"The treated-count rule evaluates R = {radius} metres, with {row['treated_stations']} "
        f"treated stations. {len(failed)} of {len(chosen_stacks)} quarterly stacks fail the "
        f"{decision['min_controls_required']}-control minimum after adding clean controls; "
        f"the minimum is {row['minimum_controls_used_per_stack']}. {action} "
        "The original station-level plan remains in this file as a design and feasibility "
        "record. [Generated counts and cohort diagnostics](../reports/stage1/README.md)."
    )
    _replace_block(root / "docs/preregistration.md", "feasibility-result", prereg)
    lines = ["## Cohorts failing at the rule-selected radius", "",
             "| Cohort | Controls after augmentation | Minimum required |",
             "| --- | ---: | ---: |"]
    for stack in failed.itertuples():
        lines.append(f"| {stack.cohort_quarter} | {stack.controls_used} | {decision['min_controls_required']} |")
    lines += ["", "## Assignment exclusions by radius", "",
              "| R metres | Reason | Stations |", "| ---: | --- | ---: |"]
    for excluded in reasons.itertuples():
        lines.append(f"| {excluded.radius_m} | {excluded.reason} | {excluded.stations} |")
    lines += ["", "Treated counts need not increase with radius: the 2R exclusion around "
              "an unusable exposure source expands too. The larger-radius rows are diagnostics; "
              "the selection rule does not permit changing radius merely to recover controls."]
    _replace_block(output / "README.md", "stage1-diagnostics", "\n".join(lines))
