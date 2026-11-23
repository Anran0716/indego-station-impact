# Area simulation validation (synthetic outcomes only)

**Historical validation:** assumed-noise power below is superseded by the [observed-residual power analysis](../area_analysis/README.md).

Plan committed in [df5127b](https://github.com/Anran0716/indego-station-impact/commit/df5127b5a8d05b623143f08304e648be22c4c6cd). Use 53 actual available areas, 28 treated areas, 8 quarterly cohorts, and 156 calendar weeks. Exact opening dates and clean-control memberships come from the count audit. Every outcome is synthetic; no observed ridership variance or real effect is used.

## Model and independent checks

The pooled prototype retains each treated area's event weeks -12..+12, complete stack-window controls, stack-by-area/calendar-week fixed effects, and physical-area clusters across reused controls. Alternating FE absorption handles the unbalanced trimmed panel. Cluster inference uses CR1 with the full FE rank and t(G-1); a small unbalanced fixture independently checks the coefficient and SE against explicit-dummy OLS and its clustered covariance. The synthetic universe has 53 available areas, but only 49 enter stacked regression (28 treated plus 21 never-exposed). The other four areas were already exposed outside the treatment window and are not clean in any stack. Cluster by the 49 included physical areas, not stack-area copies; t inference uses 48 df.

Ordinary TWFE uses the complete calendar panel and all study-treated post indicators. Both recover a constant -10% effect without noise. Under the counterexample, early areas have larger effects, effects grow over event weeks 0..12 and then plateau. No anticipation or spillovers are simulated. Other openings not assigned a study treatment have zero simulated effect; this is a validation assumption, not a finding about those openings.

| DGP | Method | Log coefficient | Equal-area 0–12 ATT | Pooled design target |
| --- | --- | ---: | ---: | ---: |
| constant_minus_10pct | stacked_pooled | -0.105361 | -0.105361 | -0.105361 |
| constant_minus_10pct | ordinary_twfe | -0.105361 | -0.105361 | -0.105361 |
| constant_minus_10pct | equal_area_clean_contrast | -0.105361 | -0.105361 | -0.105361 |
| heterogeneous_dynamic | stacked_pooled | -0.242044 | -0.243097 | -0.242044 |
| heterogeneous_dynamic | ordinary_twfe | -0.293926 | -0.243097 | -0.242044 |
| heterogeneous_dynamic | equal_area_clean_contrast | -0.243097 | -0.243097 | -0.242044 |

The strict expected-failure test requires TWFE and stacked to recover the same known 0–12-week equal-area ATT within 2 percentage points in this counterexample: TWFE fails as expected and stacked passes. This is a counterexample, not a claim that TWFE always fails or unweighted stacked always recovers an equal-area ATT. The pooled coefficient's exact design-weighted target is also checked separately. The independent clean-area contrast averages each treated area's matched-calendar 12-week pre/13-week post contrast equally and recovers the equal-area ATT exactly.

TWFE's full-panel horizon also differs from the short-window target. For clarity, the heterogeneous DGP's equal-treated-post-observation ATT over the full panel is -0.326012; TWFE returns -0.293926, so it also differs from that full-horizon ATT. `validation.csv` reports both targets rather than attributing every gap solely to forbidden comparisons.

`cohort_weights.csv` compares pooled weights with area shares. Stacked has 0 negative treated-post observation weights in this design; full-panel TWFE has 332. Weight differences remain even when all pooled post weights are nonnegative. Use the equal-area contrast as a simulation aggregation benchmark; final real-data aggregation must be specified separately from this validation. See the authors' [stacked DiD discussion of aggregation weights](https://coadywing.github.io/stacked_did_package/articles/introduction.html).

## Illustrative power, not empirical project power

Assume log-scale AR(1) errors with innovation SD 0.25, rho 0.5, seed 20261120, and 200 replications per effect. Add independent synthetic area intercepts and a common trend/annual seasonal effect. Inject log(1+delta); percentage transformations describe (1+count), as in the planned log1p outcome. Reuse each null noise draw for every constant effect; beta shifts exactly and SE is unchanged. These errors exclude common local shocks, anticipation, and cross-boundary spillovers.

| Injected effect | Rejection rate | MC standard error | 95% coverage | Mean log bias |
| --- | ---: | ---: | ---: | ---: |
| 0% | 6.0% | 1.7% | 94.0% | -0.00089 |
| -3% | 15.5% | 2.6% | 94.0% | -0.00089 |
| -5% | 30.0% | 3.2% | 94.0% | -0.00089 |
| -10% | 83.0% | 2.7% | 94.0% | -0.00089 |
| -15% | 99.5% | 0.5% | 94.0% | -0.00089 |

Smallest tested absolute effect reaching 80% rejection: **10%**.

This is a coarse tested-effect threshold under assumed synthetic variance, not an interpolated MDE or an empirical power claim. Observed-residual power is now the current project analysis. The null rejection rate reports finite-sample size; it is not a new design gate.

## Limitation

The main estimate assumes no cross-boundary spillover. The eight-neighbour exclusion test was not estimable because nearly every control area borders a treated area. The 400-metre distance-based exclusion test is estimable, retaining at least 17 control areas in every stack across all four preregistered grid offsets.

## Reproduction

```powershell
python scripts/validate_area_simulations.py --prereg-commit df5127b5a8d05b623143f08304e648be22c4c6cd
python -m pytest -q tests/test_area_simulation.py -rxX
```
