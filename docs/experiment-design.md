# Randomized opening-order experiment

**Status:** Prospective design proposal informed by the completed Indego analysis. No trial has been implemented. Freeze the final candidate list, allocation procedure, analysis and prospective power calculation before the opening-order lottery. The completed observational preregistration and results remain unchanged.

## Why the next study should randomize opening order

The historical area design has only **55.5% power (about 56%) for an assumed +10% effect**, using observed main-model residuals. It detects +5% effects in 17.0% of simulations and +15% effects in 86.0%. Thus, 15% is the smallest tested positive effect reaching the project's 80% power target. These figures come from 200 physical-area wild-bootstrap draws per effect; the Monte Carlo standard error at +10% is 3.5 percentage points. They describe conditional sensitivity under the historical design, rather than the power of a future trial. [Power table](../reports/area_analysis/empirical_power.csv), [method and assumptions](../reports/area_analysis/power_method.json).

A moderate, operationally meaningful gain can therefore go undetected in the existing design. The positive pooled estimate and its wide interval also leave substantial magnitude uncertainty. Separately, opening times may respond to anticipated local demand, and network densification has made clean, geographically isolated historical controls scarce. The area design passed its registered feasibility gates, but it still requires parallel trends and no cross-boundary spillovers. [Completed analysis](../reports/area_analysis/README.md), [control-count audit](../reports/area_feasibility/README.md).

**Randomize when already approved stations open to create a planned contemporaneous comparison group.** Randomization addresses endogenous timing; sufficient independent clusters, baseline adjustment and allocation planning address precision. Randomization alone does not guarantee 80% power or eliminate network spillovers. The 56% result motivates designing and powering a better comparison, rather than assuming that the label "randomized" solves the problem. [J-PAL: randomization](https://www.povertyactionlab.org/resource/randomization), [J-PAL: power calculations](https://www.povertyactionlab.org/resource/power-calculations).

## Candidate pool, units and allocation

- **Pool:** Locations already approved and operationally ready, in areas already served by existing stations. Set eligibility from information available before randomization. Remove urgent openings whose timing cannot be delayed before the lottery; record the reason. Expansion into previously unserved areas is a separate research question. Randomizing this pool identifies an effect for ready, approved locations, not for every possible future site.
- **Geography:** Start from the fixed 1-kilometre EPSG:32618 grid. Map candidate sites and all baseline operating stations before assignment. Link candidate areas when an opening in either would lie within 400 metres of a baseline station in the other; use connected components as spatial assignment clusters. This reduces close cross-arm exposure, while longer-range spillovers remain possible.
- **Intervention:** Schedule one index opening per assignment cluster during the primary window, selected before the lottery. Other planned openings within that cluster must wait until the window ends. If this is operationally infeasible, redesign and power an explicit multi-station package experiment before assignment; its effect is a package effect, not a per-station effect.
- **Blocking:** Group clusters by operational readiness and prespecified baseline ridership/network characteristics. Within each block, use a documented lottery to assign approximately half to early opening and half to delayed opening, with known assignment probabilities. Freeze the randomization code, seed-generation rule, blocks and restrictions before drawing assignments. Keep an audit of the realized allocation.

Spatial grouping may leave too few independent clusters, even when many stations are available. Report that limitation and revisit feasibility before implementation; do not shrink the spillover grouping after seeing outcomes to increase the sample count.

## Schedule and measurement

1. Collect at least 12 complete baseline weeks before assignment and freeze the eligible existing-station list, coordinates and outcomes.
2. Within each readiness block, open the early group on its assigned schedule. Define week 0 as the first full Monday-start week after the scheduled early-opening week.
3. Keep the delayed group unopened throughout weeks 0–12. Analyze both groups over those same 13 calendar weeks, then open the delayed group from week 13 onward. Additional blocks can run later, each retaining its own concurrent delayed controls.
4. Record actual opening dates, public announcements, installation delays, other nearby openings, station outages and changes in service. Analyze by assigned timing even when implementation slips; delays do not justify moving units between arms.

The primary outcome is the assignment cluster's mean weekly **log(1 + total departures from all stations)** over the follow-up window, including new stations. This measures net local ridership and includes redistribution inside the cluster. The secondary outcome uses only stations operating in the frozen baseline. Retain zero weeks and apply the established trip-cleaning and identity rules. The opening-order comparison is early access versus delayed access, conditional on the approved candidate pool.

## Analysis and prospective power gate

Estimate the intention-to-treat effect of assignment to early opening, using the recorded assignment probabilities, block structure and prespecified baseline adjustment. The assignment cluster is the independent unit. Report 95% intervals using a variance estimator appropriate to the blocked allocation and a within-block randomization test of the sharp null. Specify the exact estimator and interval procedure in the final trial preregistration; individual station-weeks are not independent randomized units. Delays and crossovers remain in the assigned arms, with compliance reported separately.

**Before the lottery, require at least 80% power for a +10% intention-to-treat effect at two-sided alpha = 0.05.** Also report sensitivity at +5% and +15%, the null rejection rate, Monte Carlo uncertainty and the smallest tested effect reaching the target. Set the operationally important effect threshold with the implementing partner before assignment.

Recalculate power for the actual ready-site list and proposed blocked allocation. Use prerandomization outcome covariance, the number and size of independent spatial clusters, serial correlation, implementation delays and plausible cross-arm spillovers. Simulate the intended estimator and randomization procedure. The historical residuals provide an initial calibration; future baseline data must validate it. Adding station-weeks does not create additional independent assignment clusters.

If the design misses the target, consider more independent locations or additional readiness blocks, improved baseline prediction, or a longer feasible delay/follow-up window, and recalculate power. If operational constraints leave the experiment underpowered, report the attainable precision before committing to an efficacy study. No experimental sample size or achieved trial power is claimed here because the future candidate pool is not yet available.

## Interview explanation

"Using observed residuals, the historical design had only about 56% power to detect a 10% gain. I proposed randomizing opening order among ready, approved sites so delayed sites would provide planned contemporaneous controls. Then I would size and block the rollout using the actual candidate pool. Randomization improves comparability; power planning ensures that the resulting comparison is informative."
