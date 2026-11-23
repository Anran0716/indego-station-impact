An independent project studying how new Indego stations change local ridership in Philadelphia.

# Indego station impact

**Status:** The preregistered area analysis is complete: pooled stacked estimate, event study and joint pretrend test, distance exclusion, PPML, time placebo, all four fixed grids, and power based on observed residuals. The eight-neighbour robustness test remains not estimable. Station placement following demand trends and cross-boundary spillovers remain identification risks; estimates require the registered identification assumptions.

<!-- area-estimation-summary:start -->
Primary stacked estimate: **+11.4%** (95% CI +1.5% to +22.2%). The qualified-old secondary estimate is -8.3%, consistent with net local growth alongside partial redistribution under the identification assumptions. The event-study +15.7% average is relative to a low week -1; its contrast against the full pre-period is about **+11.3%**, consistent with the pooled estimate. The week -1-relative secondary contrast is not the headline conclusion. The joint pretrend test does not reject; causal interpretation remains conditional on identification assumptions. Main/event-study results, every prespecified robustness variant, and observed-residual power are in the [area analysis](reports/area_analysis/README.md).
<!-- area-estimation-summary:end -->

<!-- area-empirical-power-summary:start -->
Current power uses observed main-model residuals with 200 physical-area wild draws per effect: +5% **17.0%**, +10% **55.5%**, +15% **86.0%** rejection. Smallest tested magnitudes reaching 80%: positive: 15%; negative: 15%. This conditional empirical-residual power supersedes the synthetic-noise example. At about 56% power for +10%, significance-selected estimates can exaggerate magnitude (Type M risk); +11.4% should be read with its wide interval, rather than as a precise effect size. This is a conditional risk, not proof that the observed estimate is inflated. [Methods, interpretation and full signed curve](reports/area_analysis/README.md).
<!-- area-empirical-power-summary:end -->

See the generated [Stage 0 audit](reports/stage0/README.md) for trip counts, first/last activity dates, supported coordinates, and rule-based identity resolution. Renumbered IDs share a continuous canonical identity. An unobserved earlier ID does not exclude an independently eligible opening; concurrent-operation and unresolved observed-identity cases carry explicit exclusion reasons.

<!-- area-feasibility-summary:start -->
**Area feasibility:** the primary (0,0) grid has 54 eligible areas, 1 excluded area(s), 28 treated areas, and at least 21 clean controls per stack. The fixed gates are 20 treated areas and 15 controls per stack. All four offsets pass the basic gate: True. The fixed primary grid passes the basic count gate. After the registered conservative eight-neighbour exclusion, the minimum control counts range from 1 to 2 across grids. That robustness analysis is **not estimable** (the primary grid retains only 1 control(s) in its smallest stacks). This does not change the main-design gate; simulation validation must precede real-data estimation. This is a count-only result; no outcome or treatment-effect estimate was produced. [Area count report](reports/area_feasibility/README.md).
<!-- area-feasibility-summary:end -->

**Original station-level feasibility record**

<!-- stage1-summary:start -->
Stage 1 screened 156 eligible existing stations. At the rule-selected candidate R = 400 metres: 52 treated, 17 never-exposed controls; the minimum after clean-control augmentation is 17. 5 of 9 stacks fall below 30 controls. **Area-level redesign required.** Keep the station-level radius unset; the next preregistration must specify the one-kilometre-area design before estimation. See the [feasibility audit](reports/stage1/README.md).
<!-- stage1-summary:end -->

<!-- network-densification-finding:start -->
Conditional on the 156 prespecified eligible existing stations, 139 (89.1%) have a study-period opening within 800 metres. Never-exposed controls number 17; the additional not-yet-exposed controls decline from 89 in 2022Q2 to 0 in 2024Q2. This is a geometry-and-opening-date finding about widespread network densification and comparison-group scarcity, conditional on the fixed eligibility sample. It does not estimate a ridership effect or use before/after effect estimates.
<!-- network-densification-finding:end -->

<!-- stage0-summary:start -->
Stage 0 found 23 name-based identity pairs and 0 additional proximity/timing pairs. The identity rules retain 100 canonical openings in 2022–2024, including 94 in the treatment-source window. The separate exposure table retains 101 operating, located openings, including treatment-ineligible sources. 96 station-table IDs have no observed trip in the study files and are reported separately from opening-date discrepancies.
<!-- stage0-summary:end -->

## Research question

How did new Indego stations opening in 2022–2024 change weekly departures in areas already served by old stations? The primary area outcome includes all stations, including new ones, and targets the net local ridership change. The secondary outcome includes only qualified old stations and addresses diversion. The original station-level question and its failed feasibility audit remain recorded below.

## Design records

The area design uses fixed 1-kilometre EPSG:32618 cells containing qualified old stations. Its primary outcome includes departures from all stations, including new stations; qualified-old departures are secondary. The +5% net-effect prediction and final estimator were committed in [8bb670b](https://github.com/Anran0716/indego-station-impact/commit/8bb670b05303304c4579c72941ae915b0694b9bc) before building real area outcomes. The [analysis report](reports/area_analysis/README.md) contains all fixed-grid and spillover checks. The station-level specifications below remain the original design record.

- Use publicly available Indego quarterly trip files for 2022 Q1–2024 Q4 and the pinned official station table. Require 20 coordinate observations per quarter for relocation checks; retain known lower-support locations with a flag. Resolve replacement IDs, then separate eligible treatment sources from all operating, positioned exposure sources before grouping stations. Candidate discovery uses both names and name-independent distance/retirement timing.
- Select a treatment radius using a prespecified station-count rule and keep the buffer at twice that radius. Require 30 controls per stack: first use never-treated stations, then add stations whose first exposure within 2R occurs after the entire stack window if needed. If any stack remains below 30, redesign at the area level.
- Estimate a stacked difference-in-differences model of `log(1 + weekly departures)` with stack-specific station and week fixed effects and standard errors clustered by station. The event window is 12 weeks before through 12 weeks after opening.
- Use simulations to demonstrate a failure of ordinary two-way fixed effects under heterogeneous treatment effects before estimating effects on real data. Report event-study intervals, pretrend diagnostics, robustness checks, and simulation-based power.

The [preregistration](docs/preregistration.md) records the original station plan, area-count and distance/simulation amendments, and the frozen area prediction and analysis. The station radius remains unset following its failed gate; the area design proceeds under its separate committed rules.

The [prospective opening-order experiment](docs/experiment-design.md) uses the observed-residual power of 55.5% at +10% as motivation for planned early/delayed controls and a separately powered randomized rollout. It specifies candidate readiness, spatial assignment clusters, a full delayed-control window and a prospective 80% power target; it is a proposal, not an implemented trial.

## Repository

```text
config.yaml                 Study parameters; radius awaits feasibility check
data/manifest.json          Pinned input URLs, row counts, and SHA256 hashes
docs/preregistration.md     Design rules; freeze after the feasibility check
docs/experiment-design.md   Proposed randomized opening order and prospective power planning
reports/stage0/             Generated input-audit tables and summary
reports/stage1/             Eligibility, radius counts, and stack-control feasibility
reports/area_feasibility/   Registered grid, clean-control, and boundary counts
reports/distance_spillover/ Registered distance restriction, counts and excluded pairs
reports/area_simulation/    Synthetic recovery, weighting diagnostics and illustrative power
reports/area_analysis/      Real estimates, event-study figures, robustness and empirical power
scripts/                    Download and feasibility entry points
sql/                        DuckDB panel construction, to be implemented
src/stimpact/               Python analysis package
tests/                      Synthetic input-validation tests
```

Python 3.11 is the target runtime and is used in CI. Dependencies are pandas, DuckDB, NumPy, SciPy, pyproj, pyfixest, Matplotlib, and PyYAML; Ruff and pytest support development. CI checks lint, syntax, and synthetic-fixture tests without downloading real inputs. The audit records its actual runtime versions in `reports/stage0/summary.json`. DuckDB is pinned to 1.4.4 after an explicit strict-mode CSV read returned zero rows under 2.0.1 in the local environment; the manifest row-count assertion caught that failure.

## Reproduction status

Install the project and run the current download-and-audit pipeline:

```powershell
python -m pip install -e '.[dev]'
python scripts/run_stage0.py
```

For a verified existing download, use `python scripts/run_stage0.py --offline`. Each archive and extracted CSV has its source URL, download date, row count, and SHA256 recorded in the committed [manifest](data/manifest.json). URLs are pinned on the first successful discovery, so future runs do not silently switch to a newer station table. Raw and intermediate data stay outside version control.

Run the real area analysis with `python scripts/run_area_analysis.py --prereg-commit 8bb670b`. The command verifies the frozen prediction/settings and pinned inputs, builds area panels, then runs main, robustness, and empirical-residual power in order. Full area panels and the hashed station-week cache remain in ignored data directories; figures and aggregate diagnostics are versioned in the report.

Run `python scripts/run_stage1.py` after Stage 0 to reproduce the fixed existing-station eligibility, three-radius counts, and per-stack clean-control checks. Its decision follows the preregistered gates and does not use estimated treatment effects.

Run `python scripts/count_area_feasibility.py --prereg-commit cd44b51` to reproduce the area counts against the rules committed before the first area count. This command reads only fixed eligibility flags, positions, and opening dates from the versioned input tables.

The audit exports `station_id_map.csv`, `canonical_station_registry.csv`, and the surviving opening lists. Pass the ID map to `load_trips(..., station_id_map=...)` before subsequent same-station cleaning and panel construction. An ignored weekly activity grid preserves zero weeks during identity transitions and enforces departure-count conservation.

`treatment_source_stations.csv` defines eligible opening cohorts; `exposure_source_stations.csv` screens controls using all operating, positioned openings, including unusable treatment sources. The pure assignment function and stack clean-control guard are tested on synthetic stations while the real radius remains unset. `source_evidence_audit.csv` records activity and location evidence for the original IDs and their successors.

## Assumptions and limitations

1. Station placement is not random. A causal interpretation requires parallel trends and no anticipation; pretrend diagnostics cannot establish these assumptions on their own.
2. Spillovers may extend beyond the buffer and affect control stations.
3. The opening week contains only partial exposure because opening dates are aligned to the preceding Monday.
4. Evidence from one city may not generalize to other systems.
5. Interpreting reduced trips at existing stations as diversion also requires assumptions about other concurrent changes and how exposure overlaps across new stations.

All eventual estimates will include uncertainty. A nonsignificant estimate will be interpreted with its confidence interval and MDE rather than treated as evidence of zero effect.

<!-- spillover-limitation:start -->
The main estimate assumes no cross-boundary spillover. The eight-neighbour exclusion test was not estimable because nearly every control area borders a treated area. The 400-metre distance-based exclusion test is estimable, retaining at least 17 control areas in every stack across all four preregistered grid offsets.
<!-- spillover-limitation:end -->

<!-- distance-spillover-summary:start -->
The preregistered 400-metre distance sensitivity retains 18–41 controls per primary-grid stack: **estimable**, with 0/8 stacks below 10. The main design remains feasible. [Count-only audit](reports/distance_spillover/README.md).
<!-- distance-spillover-summary:end -->

<!-- area-simulation-summary:start -->
Synthetic validation uses the real 53-area, 28-treated, 8-cohort structure. Stacked recovers the known -10% effect; the heterogeneous-dynamic TWFE test fails as expected. Power results assume synthetic noise. Current power is the [observed-residual analysis](reports/area_analysis/README.md); this synthetic power is historical validation. [Simulation audit](reports/area_simulation/README.md).
<!-- area-simulation-summary:end -->
