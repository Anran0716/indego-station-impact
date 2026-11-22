# Preregistration draft

**Status: the original station-level plan failed its feasibility gate; all four area grids pass the registered 20/15 count gates.** The primary area design may proceed after simulation validation and a separate final estimation specification. The eight-neighbour robustness restriction is not estimable and is not an additional main-design gate. No real area outcome model has been fitted. The original design and its amendments remain as an audit record.

## Question and hypotheses

Estimate the effect of a nearby new Indego station on weekly departures from an existing station. Diversion predicts a negative effect; improved network usefulness predicts a positive effect. Both mechanisms may coexist.

## Data and eligibility

Use only public Indego trip files for 2022 Q1–2024 Q4 and the latest official station table. Audit official opening dates against first observed trips and infer quarterly station coordinates from valid departure coordinates. Exclude relocated stations using a 50-metre threshold, with distances calculated in UTM 18N (`EPSG:32618`).

The panel covers Monday-start weeks from 2022-01-03 through the last complete week of 2024, starting 2024-12-23. Existing stations opened before 2022-01-01, have mean weekly departures of at least five in the baseline year, and have no run of more than eight consecutive zero-trip weeks within the study window. The baseline is the 52 weeks whose Mondays fall in 2022: 2022-01-03 through 2022-12-26 inclusive. The final baseline week includes 2023-01-01; use the complete 52-week grid, including zero-trip weeks.

Remove virtual station 3000, missing station IDs, trips shorter than one minute, and trips with identical start and end stations. Preserve zero-trip station-weeks with a complete station-by-week grid and enforce trip-count conservation.

## Station identity amendment before feasibility counting

The following rules were specified after the initial input audit and before treatment assignment, radius counting, or real-data estimation. They replace the initial unresolved identity-review placeholder; the original audit remains in Git history.

Use both departure and arrival observations to calculate each ID's first and last observed trip dates in Philadelphia local time. Dates before the 2022 observation window remain left-censored. The `spatial.min_trips_per_quarter_coordinate = 20` threshold applies **only to relocation checks**. Prefer those supported quarterly positions when available. If no supported quarter exists, retain the coordinate-wise median of the valid lower-support quarterly positions with `low_coordinate_support=True`; a known location and treatment eligibility are not removed merely for falling below 20 records. Keep separate `usable_for_relocation` and `usable_for_position` flags. A one-trip coordinate outlier cannot create a relocation when supported quarters are available.

Find candidate pairs using the union of two checks, and deduplicate the same earlier/later ID pair:

- Matching station names after trimming whitespace and ignoring case, with the later ID opening in 2022–2024.
- Regardless of name, a later ID opening in 2022–2024 is within 50 metres of an earlier ID, and the earlier ID's last observed trip is within 30 calendar days before or after the later ID's reconciled opening date. An earlier ID means an earlier opening, including IDs opened after 2022; it need not already qualify for the pre-2022 existing-station pool.

Report the name-based pair count and the additional pairs found only by proximity and retirement timing separately. Exact distance and day limits are inclusive. Use reconciled opening dates for the temporal proximity check. Missing coordinates are never interpreted as zero distance.

Classify each candidate in this order:

0. **Zero-activity predecessor amendment:** If the earlier ID has zero departures **and** zero arrivals throughout the study input files, classify the later ID as `new_after_unobserved_predecessor`. Do not merge it into the earlier ID or inherit any earlier-ID exclusion. Evaluate the later ID's own position, reconciled opening date, and eligibility as an ordinary opening; its exclusion reason stays empty if those checks pass. The inactive earlier ID remains excluded as `unobserved_in_trip_window`. An arrival-only earlier ID is not a zero-activity predecessor. Apply this rule before missing-coordinate checks.
1. Otherwise, missing any known position for either **observed** ID: exclude both IDs from the existing-station pool and treatment sources, with reason `missing_coordinates`. Record which ID lacks the position and its departure/arrival counts. This rule cannot propagate an unobserved earlier ID's problem to an independently eligible new ID.
2. Distance greater than 50 metres: classify as `relocated`; exclude the earlier ID from the existing pool and the later ID from new treatment sources. Conservatively exclude both identities from both pools.
3. Observed operation intervals overlap by more than 14 calendar days: classify as `concurrent_operation`; exclude both IDs from both pools. Overlap is `max(0, min(last_old, last_new) - max(first_old, first_new))` in calendar days; endpoints exactly 14 days apart do not exceed the limit. First/last observations measure an observed operation interval, not proof that a station operated every intervening day.
4. The absolute difference between the earlier ID's last observed trip and the later ID's first observed trip is at most 14 days: classify as `renumbered`, merge into the earlier ID, retain the earlier opening date, and do not count the later ID as a new station.
5. The later ID's first trip is more than 14 days after the earlier ID's last trip: classify as `interrupted_reopening`, merge into the earlier ID and retain the earlier opening date. Fill every intervening station-week with zero before applying the existing inactivity rule; do not restart the station's age.

Missing activity dates or a timeline not covered by these conditions are conservatively excluded with a specific reason, rather than forced into a merge. Merge chains resolve transitively to the earliest ID. Conflicting multiple predecessors are excluded rather than merged into one physical site without support. Exclusions propagate through an approved merge chain. A supported within-ID or merged-chain displacement above 50 metres also excludes that physical station.

Export every pair's distance, first/last dates, signed handoff gap, overlap duration, classification, discovery method, and reason. Export a complete raw-ID-to-canonical-ID map and a canonical station registry. Apply the map to both trip endpoints before same-station-trip cleaning or station-week construction. An identity exclusion controls station-pool membership; it does not discard an otherwise valid trip from another station merely because its other endpoint is excluded. Enforce trip-count conservation under remapping.

Count surviving canonical openings separately for the full 2022–2024 opening audit window and the narrower 2022-04-01 through 2024-09-30 treatment-source window. These are rule-based classifications; do not claim that every replacement is verified operationally or that contaminating openings necessarily bias an estimate toward zero under every design.

## Exposure source amendment before treatment assignment

Keep two source tables. `treatment_source_stations.csv` contains identity-cleared, positioned canonical openings inside the eligible treatment window, including ordinary openings whose earlier same-name IDs have zero study-period activity. `exposure_source_stations.csv` contains all canonical openings in 2022–2024 observed in departures or arrivals with known positions, including treatment-ineligible concurrent sites. A confirmed merged alias does not create another opening. Retain low-support known positions in both tables when otherwise eligible. A table-only ID with no observed trip creates no exposure and does not block a later ID's own eligibility. If an operating opening lacks any known position, stop source construction and report its ID before any clean controls can be declared.

Treatment cohorts are defined only by the treatment table. Never-treated and stack-specific clean controls are screened using the entire exposure table, including openings outside the treatment-source window. If any treatment-unusable exposure source is within 2R of an existing station during the full study window, exclude that existing station with reason `exposed_to_unusable_source`, before assigning treated/control/buffer status. Exclusions of old identities themselves, including the earlier ID of a concurrent pair, also remain in force. For a stack-specific clean-control check, no exposure within 2R may have an opening week on or before the stack's final week. Tests use excluded-source neighbours and renamed, zero-distance, adjacent-date replacements; actual radius counting remains deferred until the feasibility stage.

## Area-level feasibility amendment committed before counting

The station-level design failed its prespecified clean-control gate. This amendment specifies the area feasibility count before applying a grid to the real station coordinates. It does not authorize treatment-effect fitting and does not change the station-level failure or its thresholds.

**Units and fixed geography.** Use square cells of side 1,000 metres in EPSG:32618. The primary grid is anchored at projected (0, 0). For offset (dx, dy), set column = floor((x - dx) / 1000) and row = floor((y - dy) / 1000). Cells are left/bottom inclusive and right/top exclusive; a point on an east or north boundary belongs to the next cell. Use each canonical station's fixed representative position from Stage 0, including flagged low-support known positions. Do not change positions or grid anchoring using outcomes. The four prespecified offsets are (0,0), (500,0), (0,500), and (500,500) metres.

**Eligible areas.** A cell is eligible only if it contains at least one of the already qualified Stage 1 existing stations. Their fixed eligibility list is reused; no ridership values or raw trips enter this count. Cells containing only new stations are expansion areas and are excluded from the study-unit sample, because they answer a different question. Record their exposure locations for the boundary-spillover diagnostic nevertheless.

**Treatment and exposure.** Reuse the separate Stage 0 treatment-source and exposure-source tables, with 94 and 101 sources respectively in this input version. An eligible cell containing an unusable exposure source anywhere in the 2022–2024 opening window is excluded from treated and control samples, with reason `area_contains_unusable_exposure`. Other eligible cells are treated if at least one eligible treatment source opens inside them. The cohort starts at the first eligible treatment opening in the cell, aligned to Monday; ties are broken by station ID. Keep the first-opening cohort when later stations open in the same cell, and report the number of additional sources. Openings outside the eligible treatment window still determine exposure and control cleanliness. Report any earlier exposure before the eligible treatment cohort as a timing diagnostic; do not add a data-dependent exclusion after counting.

**Stacks and clean controls.** Define quarterly cohorts from the Monday-aligned opening week. A stack runs from 12 weeks before the earliest opening week in that cohort through 12 weeks after its latest opening week, inclusive, using the same configured event window as the original design. Every included cell has the complete study window available from the weekly grid. A clean control must be an eligible, nonexcluded cell whose first exposure opening week is strictly later than the stack's final week, or which has no exposure opening at all. Already-exposed cells are never controls merely because no additional station opens during that particular window. Keep each stack's control set fixed throughout its window. Count unique cells, not stations or cell-week rows.

**No 2R buffer.** Main area controls are screened by openings inside their own cell. There is no station-radius or 2R exclusion around a cell. Within-cell diversion is included in the primary total outcome. Cross-boundary spillovers remain a limitation.

**Prespecified boundary and grid diagnostics.** For each stack, also count controls after excluding cells sharing an edge or corner with an exposure-bearing cell that has opened by the stack's final week. This eight-neighbour diagnostic includes adjacent expansion-only or otherwise ineligible cells with known exposure sources, so their potential spillover is not ignored. Future exposure cells opening after the stack end do not trigger adjacency exclusion. Report this more conservative count separately from the main within-cell clean-control count. Repeat all counts under each of the four offsets above. The (0,0) grid is the primary design; the other offsets and adjacency restriction are sensitivity diagnostics, not alternatives used to rescue a failed primary design. Report feasibility for every offset without selecting the one with favourable counts.

**Outcomes if an area design later proceeds.** The primary outcome would be weekly departures from all stations inside an eligible cell, including newly opened stations and other operating IDs; the question is the net change in area ridership from an opening. The secondary outcome would count only departures from the qualified existing stations. Canonicalize approved aliases and preserve trip conservation and zero cell-weeks. This count-only amendment does not construct either outcome or run an estimator. Any subsequent estimation specification must be recorded separately after reviewing feasibility and the prespecified diagnostics.

**Feasibility decision.** On the fixed primary grid, require at least 20 nonexcluded treated areas and at least 15 unique clean-control areas in **every** quarterly stack. If either condition fails, stop observational causal estimation. Do not lower either threshold, omit failing cohorts, or move to a more favourable offset. If the primary passes but prespecified sensitivity counts do not, report that limitation and review the robustness plan before estimation; do not claim that a missing robustness result passed. Record offset-specific and adjacency-restricted counts even when the primary fails.

**Fallback after failure.** The project then becomes a feasibility and experimental-planning deliverable: the station/area feasibility reports, power calculations using real observed variance, and a fully specified randomized staggered opening rollout. Power and experimental design are separate follow-up work; no observational causal coefficient is produced by the present area-count command. Interview language must say that clean comparison groups were insufficient for the prespecified gates, rather than claiming that zero potential controls existed.

## Distance-spillover and area-simulation amendment (2026-11-21)

Commit this amendment before counting the distance-restricted sample or inspecting real area effects. The main 20-treated/15-control gates remain unchanged. The eight-neighbour restriction is a robustness analysis: report it as **not estimable**, including the remaining control count, rather than as passed or as a new feasibility gate.

For each already registered stack and each of the four fixed offsets, start with its main clean-control areas. Remove a control area if **any fixed Stage 1 qualified old station in that area** is at Euclidean distance **<=400 metres** in EPSG:32618 from **any Stage 0 exposure source opening during that stack's calendar window**. Reuse the frozen 156-station old pool; do not substitute cell centroids or only the nearest old station. Include all 101 exposure sources, including treatment-unusable, low-support, outside-treatment-window, and expansion-only sources. Use their canonical fixed coordinates and reconciled opening dates. The window includes the first Monday through the Sunday of the final stack week; openings before that window or after that Sunday do not trigger this particular diagnostic. Own-cell clean-control rules continue to apply independently.

Require at least **10 distinct remaining control areas in every stack** to estimate this distance-restricted robustness variant. Otherwise report **not estimable** for that variant and list the failing stacks/counts. Do not drop stacks, adjust distance, or alter the main-design decision. Count before fitting. Grid-offset checks and both spillover restrictions remain separate from the main gate.

**Reporting clarification (2026-11-22, after distance counting):** Distinguish the two exclusion tests in every report: "The main estimate assumes no cross-boundary spillover. The eight-neighbour exclusion test was not estimable because nearly every control area borders a treated area. The 400-metre distance-based exclusion test is estimable, retaining at least 17 control areas in every stack across all four preregistered grid offsets." This updates reporting language using the completed count audit; it does not change design rules or thresholds. Counts alone cannot validate absence of spillovers or robustness of an unestimated effect.

Before real-data estimation, simulate **area** panels using the fixed primary grid's actual available areas, exact opening weeks, quarterly cohort sizes, stack calendar windows, and clean-control memberships. No real weekly outcomes or baseline ridership values enter this simulation. Reuse the full 156-week grid; retain each treated area's event weeks -12 through +12 within its stack. Absorb stack-by-area and stack-by-calendar-week fixed effects and cluster across reused rows by physical area. Validate constant known effects (including -10%) and a heterogeneous dynamic counterexample; the ordinary TWFE case must be an explicit strict expected failure, while stacked recovery passes. Inspect the pooled coefficient's implicit weights and distinguish its design-weighted target from an equal-area ATT.

Use synthetic additive area/calendar effects and log-scale AR(1) errors with innovation SD 0.25, rho 0.5, and the configured seed. Report power at the five configured effect sizes with 200 repetitions, area-clustered CR1 inference and a t reference with G-1 degrees of freedom. These noise parameters are assumptions, **not measured area variances**; label resulting power/MDE as illustrative simulation validation, not empirical project power. The all-station net-effect prediction and final real-data estimator/robustness specification still require a separate record before fitting real outcomes.

## Radius selection before outcome analysis (original station design)

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
- Assign a treated station to its first new station within R. Break same-day ties by ascending new-station ID. A subsequent opening within R does not change its cohort or assignment; flag an opening after the first opening in event weeks 0–12 inclusive as `second_hit`, keep it in the main analysis, and exclude it in a robustness analysis. Subsequent openings in R < d <= 2R do not change a treated station's group. For control eligibility, however, the first exposure anywhere within 2R still determines whether it is clean.

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

<!-- feasibility-result:start -->
Feasibility decision before real-data estimation: **redesign_area_level**. The treated-count rule evaluates R = 400 metres, with 52 treated stations. 5 of 9 quarterly stacks fail the 30-control minimum after adding clean controls; the minimum is 17. **Area-level redesign required.** Keep the station-level radius unset; the next preregistration must specify the one-kilometre-area design before estimation. The original station-level plan remains in this file as a design and feasibility record. [Generated counts and cohort diagnostics](../reports/stage1/README.md).
<!-- feasibility-result:end -->

<!-- area-feasibility-result:start -->
Area rules were committed before counting in [cd44b51](https://github.com/Anran0716/indego-station-impact/commit/cd44b51f66767b97fca5a9fc3c154c4b0cb05d06). The primary grid has 28 treated areas and a minimum of 21 clean controls per stack, against the fixed 20/15 gates. Decision: **primary_area_feasible**. The fixed primary grid passes the basic count gate. After the registered conservative eight-neighbour exclusion, the minimum control counts range from 1 to 2 across grids. That robustness analysis is **not estimable** (the primary grid retains only 1 control(s) in its smallest stacks). This does not change the main-design gate; simulation validation must precede real-data estimation. The committed rules and thresholds above are unchanged. This amendment registered feasibility only; the area estimator and any subsequent analysis are not frozen here. [Counts and diagnostic memberships](../reports/area_feasibility/README.md).
<!-- area-feasibility-result:end -->

<!-- distance-spillover-result:start -->
Rules were committed before counting in [df5127b](https://github.com/Anran0716/indego-station-impact/commit/df5127b5a8d05b623143f08304e648be22c4c6cd). The primary grid retains 18–41 controls per stack. All four grids meet the distance variant's 10-control requirement. This records estimability only; no robustness effect has been estimated. The original eight-neighbour variant remains not estimable and the main 20/15 gate is unchanged. [Count audit](../reports/distance_spillover/README.md).
<!-- distance-spillover-result:end -->

<!-- area-simulation-result:start -->
Area-level synthetic validation is complete using the fixed 53-area universe, 28 treated areas and 8 quarterly cohorts. The actual stacked sample contains 49 physical-area clusters; four other-exposure areas are never clean. Known -10% recovery, the strict expected TWFE failure, and independent clustered OLS checks are documented in the [simulation audit](../reports/area_simulation/README.md). Power uses assumed synthetic variance. No real area outcome has been fitted; the final area estimation specification remains separate from this validation.
<!-- area-simulation-result:end -->
