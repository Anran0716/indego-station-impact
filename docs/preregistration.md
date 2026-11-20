# Preregistration draft

**Status: draft; not frozen.** This file records rules before feasibility counting. Finalize the radius, prediction, and unresolved design details, then commit this document separately before estimating effects on real data. Record the resulting commit link in the README. Later changes must be documented as amendments rather than silently replacing the original design.

## Question and hypotheses

Estimate the effect of a nearby new Indego station on weekly departures from an existing station. Diversion predicts a negative effect; improved network usefulness predicts a positive effect. Both mechanisms may coexist.

## Data and eligibility

Use only public Indego trip files for 2022 Q1–2024 Q4 and the latest official station table. Audit official opening dates against first observed trips and infer quarterly station coordinates from valid departure coordinates. Exclude relocated stations using a 50-metre threshold, with distances calculated in UTM 18N (`EPSG:32618`).

The panel covers Monday-start weeks from 2022-01-03 through the last complete week of 2024, starting 2024-12-23. Existing stations opened before 2022-01-01, have mean weekly departures of at least five in 2022, and have no run of more than eight consecutive zero-trip weeks within the study window. Finalize how boundary weeks enter the baseline calculation before constructing eligibility.

Remove virtual station 3000, missing station IDs, trips shorter than one minute, and trips with identical start and end stations. Preserve zero-trip station-weeks with a complete station-by-week grid and enforce trip-count conservation.

## Radius selection before outcome analysis

Count treated, control, and buffer stations at radii of 400, 600, and 800 metres without inspecting treatment effects or before/after outcome changes.

1. At 400 metres, use 400 metres if there are at least 40 treated and 40 control stations.
2. At 400 metres, retain 400 metres if there are 20–39 treated stations, and explicitly report limited power.
3. If fewer than 20 stations are treated at 400 metres, assess 600 metres.
4. If fewer than 20 are treated at 600 metres, pause station-level estimation and redesign around one-kilometre areas in a separately documented design.

**Unresolved before freezing:** The guide does not specify the decision when 400 metres yields at least 40 treated stations but fewer than 40 controls, nor a minimum control count for the other branches. Resolve these cases explicitly before radius selection. The selected radius remains unset in `config.yaml`.

## Treatment and controls

- Eligible treatment-source openings occur from 2022-04-01 through 2024-09-30.
- Assign each existing station to its first opening within radius R and align opening dates to the Monday of the opening week.
- Exclude existing stations exposed within R in January–March 2022 (`no_pre_period`) or first exposed in October–December 2024 (`no_post_period`).
- Exclude buffer stations with an opening between R and 2R and none within R.
- Never-treated controls have no new station within 2R over the full 2022–2024 period, including openings outside the eligible treatment-source window.
- Flag a second opening within R during the first 12 weeks as `second_hit`; keep these stations in the main analysis and exclude them in a robustness analysis.

Finalize exact distance-boundary conventions and overlapping-exposure rules before treatment assignment.

## Main model and reporting

The primary outcome is `log(1 + weekly departures)`. Use stacked DiD with quarterly cohorts, stack-specific station and week fixed effects, station-clustered standard errors, and treated observations at event weeks -12 through +12. The primary summary is the average effect over post-opening weeks 0–12; finalize the cohort aggregation weights and the relationship between that summary and the pooled model coefficient before estimation. Report the coefficient and transformed percentage estimate with 95% confidence intervals.

Use event week -1 as the event-study reference and report a joint pretrend test. Cross-check with did2s. Demonstrate the ordinary TWFE failure case and validate stacked estimation on simulated data before running the real-data model.

**Prediction:** Pending the researcher's prespecified sign, approximate magnitude, and rationale. Do not infer a prediction from estimated results.

## Prespecified robustness and power

- PPML on trip counts.
- Separate inner-ring and outer-ring effects.
- Exclude stations with `second_hit`.
- Replace departures with arrivals.
- Allow weekly effects to vary by baseline-ridership tercile.
- Shift treatment 26 weeks earlier, using observations before the actual opening.
- Simulate effects of 0%, -3%, -5%, -10%, and -15%, with 200 repetitions per effect, station-clustered inference, and a fixed seed.

Report the null rejection rate, power curve, and the smallest tested absolute effect reaching 80% power; report when no tested effect reaches that target. Interpret findings using confidence intervals and power together. MDE alone does not establish that an effect has been ruled out.

Report a diversion-rate estimate with a station-level bootstrap interval after defining how new-station exposure overlaps enter its numerator and denominator. No results or completed checks are claimed in this draft.
