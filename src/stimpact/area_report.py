"""Record count-only area decisions while keeping robustness limitations visible."""

import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit

SPILLOVER_LIMITATION = (
    "The main estimate assumes no cross-boundary spillover. The eight-neighbour exclusion "
    "test was not estimable because nearly every control area borders a treated area. "
    "The 400-metre distance-based exclusion test is estimable, retaining at least 17 control "
    "areas in every stack across all four preregistered grid offsets."
)


def _block(path: Path, name: str, content: str) -> None:
    text = path.read_text(encoding="utf-8")
    replacement = f"<!-- {name}:start -->\n{content}\n<!-- {name}:end -->"
    pattern = rf"<!-- {name}:start -->.*?<!-- {name}:end -->"
    if re.search(pattern, text, flags=re.DOTALL):
        text = re.sub(pattern, lambda match: replacement, text, flags=re.DOTALL)
    else:
        text = text.rstrip() + "\n\n" + replacement + "\n"
    path.write_text(text, encoding="utf-8")


def root_links_in_reports(content: str) -> str:
    """Keep root-relative Markdown links valid after moving technical notes into reports/."""
    def relocate(match):
        target = match.group(1)
        if target.startswith(("#", "/")) or urlsplit(target).scheme:
            return match.group(0)
        return "](" + posixpath.relpath(target, "reports") + ")"

    return re.sub(r"\]\(([^)]+)\)", relocate, content)


def record_summary(root: Path, name: str, content: str) -> None:
    """Generated technical summaries belong in reports, leaving the short landing page editorial."""
    notes = root / "reports/project-notes.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    if not notes.exists():
        notes.write_text("# Project notes and reproducibility\n", encoding="utf-8")
    _block(notes, name, root_links_in_reports(content))


def record_area_result(root: Path, summary: dict) -> None:
    decision = summary["decision"]
    primary = next(row for row in summary["grid_counts"] if row["is_primary"])
    prereg = summary["preregistration_commit"]
    if decision["decision"] == "stop_causal_estimation":
        action = "The fixed primary grid fails its gate: stop observational causal estimation."
    else:
        action = "The fixed primary grid passes the basic count gate."
        if not decision["all_adjacency_samples_sufficient"]:
            minimums = [row["minimum_adjacency_controls_per_stack"] for row in summary["grid_counts"]]
            action += (f" After the registered conservative eight-neighbour exclusion, the "
                       f"minimum control counts range from {min(minimums)} to {max(minimums)} "
                       "across grids. That robustness analysis is **not estimable** "
                       f"(the primary grid retains only {primary['minimum_adjacency_controls_per_stack']} "
                       "control(s) in its smallest stacks). "
                       "This does not change the main-design gate; simulation validation "
                       "must precede real-data estimation.")
    brief = (
        f"**Area feasibility:** the primary (0,0) grid has {primary['eligible_areas']} eligible "
        f"areas, {primary['excluded_unusable_areas']} excluded area(s), {primary['treated_areas']} "
        f"treated areas, and at least {primary['minimum_clean_controls_per_stack']} clean controls "
        f"per stack. The fixed gates are {decision['min_treated_areas_required']} treated areas "
        f"and {decision['min_controls_per_stack_required']} controls per stack. "
        f"All four offsets pass the basic gate: {decision['all_offsets_pass']}. {action} "
        "This is a count-only result; no outcome or treatment-effect estimate was produced. "
        "[Area count report](reports/area_feasibility/README.md)."
    )
    record_summary(root, "area-feasibility-summary", brief)
    record_summary(root, "spillover-limitation", SPILLOVER_LIMITATION)
    status = (
        f"Area rules were committed before counting in [{prereg[:7]}]"
        f"(https://github.com/Anran0716/indego-station-impact/commit/{prereg}). "
        f"The primary grid has {primary['treated_areas']} treated areas and a minimum of "
        f"{primary['minimum_clean_controls_per_stack']} clean controls per stack, against "
        f"the fixed {decision['min_treated_areas_required']}/{decision['min_controls_per_stack_required']} gates. "
        f"Decision: **{decision['decision']}**. {action} "
        "The committed rules and thresholds above are unchanged. This amendment registered "
        "feasibility only; the area estimator and any subsequent analysis are not frozen here. "
        "[Counts and diagnostic memberships](../reports/area_feasibility/README.md)."
    )
    _block(root / "docs/preregistration.md", "area-feasibility-result", status)
