# Preregistration draft

**Status: draft; radius not yet selected.** The design decisions below were recorded on 2026-11-20 before feasibility counting or real-data estimation. After the feasibility check, record the selected radius and control mode in a separate freeze commit before estimating effects on real data. Later changes must be documented as amendments rather than silently replacing the original design.

## Question and hypotheses

Estimate the effect of a nearby new Indego station on weekly departures from an existing station. Diversion predicts a negative effect; improved network usefulness predicts a positive effect. Both mechanisms may coexist.

## Data and eligibility

Use only public Indego trip files for 2022 Q1–2024 Q4 and the latest official station table. Audit official opening dates against first observed trips and infer quarterly station coordinates from valid departure coordinates. Exclude relocated stations using a 50-metre threshold, with distances calculated in UTM 18N (`EPSG:32618`).

The panel covers Monday-start weeks from 2022-01-03 through the last complete week of 2024, starting 2024-12-23. Existing stations opened before 2022-01-01, have mean weekly departures of at least five in the baseline year, and have no run of more than eight consecutive zero-trip weeks within the study window. The baseline is the 52 weeks whose Mondays fall in 2022: 2022-01-03 through 2022-12-26 inclusive. The final baseline week includes 2023-01-01; use the complete 52-week grid, including zero-trip weeks.

Remove virtual station 3000, missing station IDs, trips shorter than one minute, and trips with identical start and end stations. Preserve zero-trip station-weeks with a complete station-by-week grid and enforce trip-count conservation.

## Radius selection before outcome analysis

Count treated, control, and buffer stations at radii of 400, 600, and 800 metres without inspecting treatment effects or before/after outcome changes.

1. At 400 metres, use 400 metres if there are at least 40 treated stations, subject to the control-count requirement below.
2. At 400 metres, retain 400 metres if there are 20–39 treated stations, and explicitly report limited power.
3. If fewer than 20 stations are treated at 400 metres, assess 600 metres.
4. If fewer than 20 are treated at 600 metres, pause station-level estimation and redesign around one-kilometre areas in a separately documented design.

At the radius selected by these treated-count rules, require at least **30 distinct eligible control stations in every stack**. First count never-treated controls. If there are fewer than 30, keep the buffer at 2R and add all eligible not-yet-exposed stations that are clean throughout the entire stack window. Count unique stations within each stack, not pooled station-stack rows. Do not shrink the buffer, choose another radius to recover controls, drop inconvenient cohorts, or select controls using outcome changes. If any stack still has fewer than 30 clean controls, pause station-level estimation and redesign around one-kilometre areas.

For a quarterly stack, the calendar window starts 12 weeks before its earliest treated opening week and ends 12 weeks after its latest treated opening week, inclusive. A not-yet-exposed control's **first opening within 2R**, considering every new opening in 2022–2024, must have an opening week strictly later than the stack's final week. An opening on any day of the final week disqualifies the station. Keep each stack's control set constant across its whole window. This rule requires no anticipation and parallel untreated trends; clean exposure status alone does not establish comparability. The selected radius remains unset in `config.yaml` until the feasibility check.

## Treatment and controls

- Eligible treatment-source openings occur from 2022-04-01 through 2024-09-30.
- Assign each existing station to its first opening within radius R and align opening dates to the Monday of the opening week.
- Exclude existing stations exposed within R in January–March 2022 (`no_pre_period`) or first exposed in October–December 2024 (`no_post_period`).
- Distance boundaries are: treated exposure at d <= R; buffer exposure at R < d <= 2R; unexposed at d > 2R.
- Exclude buffer stations with an opening between R and 2R and none within R from the never-treated control set.
- Never-treated controls have no new station within 2R over the full 2022–2024 period, including openings outside the eligible treatment-source window.
- Assign a treated station to its first new station within R. Break same-day ties by ascending new-station ID. A subsequent opening within R does not change its cohort or assignment; flag an opening within the next 12 event weeks as `second_hit`, keep it in the main analysis, and exclude it in a robustness analysis. Subsequent openings in R < d <= 2R do not change a treated station's group. For control eligibility, however, the first exposure anywhere within 2R still determines whether it is clean.

Not-yet-exposed status is stack-specific: a station can be a clean control in an earlier stack and exposed later. It can never be both treated and control in the same stack. Report never-treated and added clean controls separately for every stack.

## Main model and reporting

The primary outcome is `log(1 + weekly departures)`. Use stacked DiD with quarterly cohorts, stack-specific station and week fixed effects, station-clustered standard errors, and treated observations at event weeks -12 through +12. The **primary summary is the pooled regression coefficient on `treated_post`**. Report the equally weighted average of event-study coefficients at event weeks 0–12 as a secondary summary, using their full covariance matrix for uncertainty. The two summaries can differ: larger cohorts can receive more influence in the pooled regression, and the actual implicit weights also depend on the control composition and regression design. Do not label the pooled coefficient an equally weighted ATT. Report the coefficient and transformed percentage estimate with 95% confidence intervals.

Before real-data estimation, inspect aggregation weights and test the estimator under varying treated/control ratios in simulation. Add a corrective-weight specification to the robustness report if needed; stacking and clean controls alone do not guarantee the desired ATT aggregation ([Wing, Freedman, and Hollingsworth](https://www.nber.org/papers/w32054)).

Use event week -1 as the event-study reference and report a joint pretrend test. Cross-check with did2s. Demonstrate the ordinary TWFE failure case and validate stacked estimation on simulated data before running the real-data model.

**Prediction recorded before outcome analysis:** Approximately **-5%** in existing-station weekly departures over the first 13 event weeks (0–12), corresponding to a primary log coefficient near `log(0.95) = -0.0513`. Nearby riders may switch to the more convenient new station, while easier returns and a denser network may offset part of that diversion. This is an uncertain working prediction, not an estimate or an expected significance claim. Report the eventual result even if its sign or magnitude differs.

## Prespecified robustness and power

- PPML on trip counts.
- Separate inner-ring and outer-ring effects.
- Exclude stations with `second_hit`.
- Replace departures with arrivals.
- Allow weekly effects to vary by baseline-ridership tercile.
- Shift treatment 26 weeks earlier, using observations before the actual opening.
- Simulate effects of 0%, -3%, -5%, -10%, and -15%, with 200 repetitions per effect, station-clustered inference, and a fixed seed.

Report the null rejection rate, power curve, and the smallest tested absolute effect reaching 80% power; report when no tested effect reaches that target. Interpret findings using confidence intervals and power together. MDE alone does not establish that an effect has been ruled out.

For the diversion rate, count each treated existing station once in the numerator and assign it to its first new station within R, using the same tie-break rule as treatment assignment. The denominator includes only distinct new stations assigned at least one treated existing-station neighbour, using their post-opening weeks 0–12. New stations without an assigned treated neighbour do not enter the denominator, and a new station is not repeated for each old neighbour. Bootstrap existing stations and rebuild the assignment-based aggregate within each resample. No results or completed checks are claimed in this draft.
