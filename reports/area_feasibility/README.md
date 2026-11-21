# Area-level feasibility audit

Design registered before counting in [cd44b51](https://github.com/Anran0716/indego-station-impact/commit/cd44b51f66767b97fca5a9fc3c154c4b0cb05d06). Inputs: 156 fixed eligible old stations, 94 treatment sources, and 101 exposure sources. No ridership values were parsed, no outcomes were constructed, and no treatment-effect estimator was run.

## Fixed geography and samples

Use 1,000-metre EPSG:32618 cells with the committed anchor and half-open boundary conventions. A study cell must contain an eligible old station; a new-only cell does not become a treatment unit. A cell containing an unusable exposure source is excluded. Treatment timing is the first eligible treatment opening inside the cell. The first opening from any exposure source determines control cleanliness. Already-exposed cells cannot serve as controls in later stacks.

## Counts by preregistered grid offset

| Offset x,y metres | Eligible areas | Excluded areas | Treated areas | Never-exposed controls | Min clean controls | Min after adjacency removal | Failed stacks | Main gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| (0, 0) | 54 | 1 | 28 | 21 | 21 | 1 | 0/8 | True |
| (500, 0) | 55 | 1 | 31 | 20 | 20 | 1 | 0/7 | True |
| (0, 500) | 56 | 1 | 33 | 20 | 20 | 2 | 0/7 | True |
| (500, 500) | 54 | 1 | 32 | 21 | 21 | 1 | 0/9 | True |

The primary grid is fixed at (0,0). The other offsets cannot replace a failed primary grid. Each grid is evaluated against the same prespecified thresholds: at least 20 treated areas and at least 15 clean controls in every stack. Adjacency counts are separate sensitivity diagnostics, not a post-hoc way to change the primary gate.

## Stack controls and boundary spillovers

Quarterly stacks use the earliest cohort opening minus the configured pre-period through the latest opening plus the configured post-period. Clean controls have no exposure opening on or before the last stack week. Eight-neighbour sensitivity removes controls adjacent by edge or corner to any exposure cell active by then, including cells outside the eligible unit sample (such as expansion-only cells). Future exposures after the stack end do not trigger this restriction. There is no station-radius or 2R buffer in the main area design.

`stack_control_counts.csv` reports all cohort counts. `control_membership.csv` records each main clean control and its adjacency status. `area_assignments.csv` records cell eligibility, first dates, additional sources, exclusions, and any exposure preceding the eligible treatment cohort. Earlier exposure is a registered timing diagnostic, not a new outcome-driven exclusion.

## Decision

**primary_area_feasible**. On the primary grid, there are 28 treated areas and a minimum of 21 clean controls across stacks; 0 stacks fall below the control threshold.

The primary count gate passes. Review the registered adjacency, grid, and timing diagnostics before separately specifying or implementing an estimator. Passing counts under all offsets does not establish that an unestimated ridership effect is robust to grid location. The adjacency-restricted sample has its own reported counts; a shortfall there is not described as a passed robustness analysis.

## Reproduction

```powershell
python scripts/count_area_feasibility.py --prereg-commit cd44b51f66767b97fca5a9fc3c154c4b0cb05d06
```

The command verifies that the area settings and event/study windows match the chosen committed preregistration. Inputs are hashed in `summary.json`; the eligibility CSV is read only for ID, fixed position, and its existing qualification flag. Raw trips and baseline/weekly ridership fields are not read.
