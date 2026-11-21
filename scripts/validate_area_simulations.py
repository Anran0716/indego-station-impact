"""Validate estimators on synthetic Y with the registered real area timing structure."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import t

from stimpact.area_report import SPILLOVER_LIMITATION, _block
from stimpact.area_simulation import (
    clean_area_contrast,
    design_from_counts,
    equal_area_truth,
    make_regression,
    synthetic_effect,
    untreated_panel,
)
from stimpact.download import sha256


def run(root: Path, prereg_commit: str) -> dict:
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    registered = yaml.safe_load(subprocess.check_output(
        ["git", "show", f"{prereg_commit}:config.yaml"], cwd=root, text=True, encoding="utf-8"))
    for key in ("area_simulation", "area_feasibility", "power"):
        if registered.get(key) != config[key]:
            raise ValueError(f"Commit the simulation plan before running: {key}")
    for section, keys in (("estimation", ("event_pre_weeks", "event_post_weeks")),
                          ("study", ("panel_start", "last_complete_week_start"))):
        if any(registered[section][key] != config[section][key] for key in keys):
            raise ValueError("Simulation windows differ from the committed plan")
    paths = {"areas": root / "reports/area_feasibility/area_assignments.csv",
             "stacks": root / "reports/area_feasibility/stack_control_counts.csv",
             "controls": root / "reports/area_feasibility/control_membership.csv"}
    # Whitelist metadata columns. In particular, never load any real weekly Y.
    areas = pd.read_csv(paths["areas"], usecols=["offset_x_m", "offset_y_m", "cell_id", "eligible_area",
                        "excluded", "treated", "cohort_week", "cohort_quarter", "first_exposure_week"])
    stacks = pd.read_csv(paths["stacks"], usecols=["offset_x_m", "offset_y_m", "cohort_quarter",
                                                 "stack_first_week", "stack_last_week"])
    controls = pd.read_csv(paths["controls"], usecols=["offset_x_m", "offset_y_m", "cohort_quarter", "cell_id"])
    design = design_from_counts(areas, stacks, controls, config)
    fixture = json.loads((root / "tests/fixtures/area_design.json").read_text())
    if design != fixture:
        raise ValueError("The committed synthetic-test design differs from current area metadata")
    model = make_regression(design)
    twfe = make_regression(design, "twfe")
    settings, power = config["area_simulation"], config["power"]
    baseline = untreated_panel(design, seed=power["seed"], noise_sd=0)[:, 0]
    validation = []
    for heterogeneous in (False, True):
        effect = synthetic_effect(design, heterogeneous=heterogeneous)
        truth = equal_area_truth(design, effect)
        weighted_truth = float(model.coefficient_weights @ effect[model.panel_rows])
        full_post_truth = float(effect[effect != 0].mean())
        for name, estimator, target in (("stacked_pooled", model, weighted_truth),
                                        ("ordinary_twfe", twfe, truth)):
            estimate = float(estimator.fit(baseline + effect)["coefficient"])
            validation.append({"dgp": "heterogeneous_dynamic" if heterogeneous else "constant_minus_10pct",
                               "method": name, "coefficient": estimate,
                               "relative_effect": float(np.expm1(estimate)), "target_log": target,
                               "equal_area_ATT_log": truth, "pooled_design_target_log": weighted_truth,
                               "equal_full_post_observation_ATT_log": full_post_truth,
                               "within_2pp_of_equal_area_ATT": bool(abs(np.expm1(estimate) - np.expm1(truth)) < 0.02)})
        validation.append({"dgp": "heterogeneous_dynamic" if heterogeneous else "constant_minus_10pct",
                           "method": "equal_area_clean_contrast", "coefficient": clean_area_contrast(design, baseline + effect),
                           "target_log": truth, "equal_area_ATT_log": truth,
                           "equal_full_post_observation_ATT_log": full_post_truth,
                           "pooled_design_target_log": weighted_truth})
    hetero_checks = [row for row in validation if row["dgp"] == "heterogeneous_dynamic"]
    if not hetero_checks[0]["within_2pp_of_equal_area_ATT"] or hetero_checks[1]["within_2pp_of_equal_area_ATT"]:
        raise AssertionError("The synthetic stacked recovery/TWFE counterexample did not validate")
    # Common random numbers: a constant injected effect shifts beta by log(1+delta),
    # leaving the regression residuals and clustered standard errors unchanged.
    synthetic_null = untreated_panel(design, seed=power["seed"], noise_sd=settings["noise_sd_log"],
                                     rho=settings["noise_ar1"], repetitions=power["repetitions"])
    null_fit = model.fit(synthetic_null)
    beta0, se = null_fit["coefficient"], null_fit["se"]
    critical = t.ppf(1 - power["alpha"] / 2, null_fit["clusters"] - 1)
    power_rows, replication_rows = [], []
    for delta in power["injected_effects"]:
        target = np.log1p(delta)
        estimates = beta0 + target
        rejected = np.abs(estimates / se) > critical
        covered = np.abs(estimates - target) <= critical * se
        rate = float(rejected.mean())
        power_rows.append({"injected_relative_effect": delta, "injected_log_effect": target,
                           "repetitions": power["repetitions"], "mean_log_estimate": float(estimates.mean()),
                           "bias_log": float((estimates - target).mean()), "mean_cluster_se": float(se.mean()),
                           "rejection_rate": rate, "monte_carlo_se": float(np.sqrt(rate * (1-rate) / len(se))),
                           "coverage_95": float(covered.mean())})
        for rep, (beta, sigma, reject) in enumerate(zip(estimates, se, rejected, strict=True)):
            replication_rows.append({"effect": delta, "replication": rep, "log_estimate": beta,
                                     "area_cluster_se": sigma, "rejected_at_5pct": bool(reject)})
    eligible_mde = [abs(row["injected_relative_effect"]) for row in power_rows
                    if row["injected_relative_effect"] and row["rejection_rate"] >= power["target_power"]]
    cohort_rows = []
    row_unit = model.panel_rows // design["weeks"]
    for stack in design["stacks"]:
        ids = [i for i, a in enumerate(design["areas"]) if a["cohort"] == stack["cohort"]]
        cohort_rows.append({"cohort": stack["cohort"], "treated_areas": len(ids),
                            "clean_controls": len(stack["controls"]),
                            "equal_area_share": len(ids) / sum(a["treated"] for a in design["areas"]),
                            "pooled_post_weight": float(model.post_weights[np.isin(row_unit, ids)].sum())})
    summary = {"preregistration_commit": prereg_commit, "real_outcomes_read": False,
               "real_effect_estimator_run": False, "unit": "area", "areas": len(design["areas"]),
               "treated_areas": sum(a["treated"] for a in design["areas"]), "weeks": design["weeks"],
               "stacks": len(design["stacks"]), "stacked_rows": len(model.panel_rows),
               "area_clusters": null_fit["clusters"], "input_hashes": {k: sha256(p) for k, p in paths.items()},
               "assumed_noise": settings, "validation": validation, "power": power_rows,
               "smallest_tested_effect_reaching_80pct": min(eligible_mde) if eligible_mde else None,
               "power_uses_observed_variance": False,
               "stacked_negative_post_weights": int((model.post_weights < -1e-12).sum()),
               "twfe_negative_post_weights": int((twfe.post_weights < -1e-12).sum())}
    out = root / "reports/area_simulation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(validation).to_csv(out / "validation.csv", index=False)
    pd.DataFrame(power_rows).to_csv(out / "illustrative_power.csv", index=False)
    pd.DataFrame(replication_rows).to_csv(out / "replications.csv", index=False)
    pd.DataFrame(cohort_rows).to_csv(out / "cohort_weights.csv", index=False)
    lines = ["# Area simulation validation (synthetic outcomes only)", "",
             f"Plan committed in [{prereg_commit[:7]}]"
             f"(https://github.com/Anran0716/indego-station-impact/commit/{prereg_commit}). "
             f"Use {summary['areas']} actual available areas, {summary['treated_areas']} treated areas, "
             f"{summary['stacks']} quarterly cohorts, and {summary['weeks']} calendar weeks. "
             "Exact opening dates and clean-control memberships come from the count audit. "
             "Every outcome is synthetic; no observed ridership variance or real effect is used.", "",
             "## Model and independent checks", "",
             "The pooled prototype retains each treated area's event weeks -12..+12, complete "
             "stack-window controls, stack-by-area/calendar-week fixed effects, and physical-area "
             "clusters across reused controls. Alternating FE absorption handles the unbalanced "
             "trimmed panel. Cluster inference uses CR1 with the full FE rank and t(G-1); "
             "a small unbalanced fixture independently checks the coefficient and SE against "
             "explicit-dummy OLS and its clustered covariance. The synthetic universe has "
             f"53 available areas, but only {null_fit['clusters']} enter stacked regression "
             "(28 treated plus 21 never-exposed). The other four areas were already exposed "
             "outside the treatment window and are not clean in any stack. Cluster by the "
             "49 included physical areas, not stack-area copies; t inference uses 48 df.", "",
             "Ordinary TWFE uses the complete calendar panel and all study-treated post "
             "indicators. Both recover a constant -10% effect without noise. Under the "
             "counterexample, early areas have larger effects, effects grow over event weeks "
             "0..12 and then plateau. No anticipation or spillovers are simulated. Other "
             "openings not assigned a study treatment have zero simulated effect; this is a "
             "validation assumption, not a finding about those openings.", "",
             "| DGP | Method | Log coefficient | Equal-area 0–12 ATT | Pooled design target |",
             "| --- | --- | ---: | ---: | ---: |"]
    for row in validation:
        lines.append(f"| {row['dgp']} | {row['method']} | {row['coefficient']:.6f} | "
                     f"{row['equal_area_ATT_log']:.6f} | {row['pooled_design_target_log']:.6f} |")
    lines += ["", "The strict expected-failure test requires TWFE and stacked to recover the "
              "same known 0–12-week equal-area ATT within 2 percentage points in this counterexample: "
              "TWFE fails as expected and stacked passes. This is a counterexample, not a claim "
              "that TWFE always fails or unweighted stacked always recovers an equal-area ATT. "
              "The pooled coefficient's exact design-weighted target is also checked separately. "
              "The independent clean-area contrast averages each treated area's matched-calendar "
              "12-week pre/13-week post contrast equally and recovers the equal-area ATT exactly.", "",
              "TWFE's full-panel horizon also differs from the short-window target. For clarity, "
              "the heterogeneous DGP's equal-treated-post-observation ATT over the full panel "
              f"is {hetero_checks[0]['equal_full_post_observation_ATT_log']:.6f}; TWFE returns "
              f"{hetero_checks[1]['coefficient']:.6f}, so it also differs from that full-horizon "
              "ATT. `validation.csv` reports both targets rather than attributing every gap "
              "solely to forbidden comparisons.", "",
              f"`cohort_weights.csv` compares pooled weights with area shares. Stacked has "
              f"{summary['stacked_negative_post_weights']} negative treated-post observation weights "
              f"in this design; full-panel TWFE has {summary['twfe_negative_post_weights']}. "
              "Weight differences remain even when all pooled post weights are nonnegative. "
              "Use the equal-area contrast as a simulation aggregation benchmark; final real-data "
              "aggregation/corrective-weight robustness still needs a separate specification. "
              "See the authors' [stacked DiD discussion of aggregation weights]"
              "(https://coadywing.github.io/stacked_did_package/articles/introduction.html).", "",
              "## Illustrative power, not empirical project power", "",
              f"Assume log-scale AR(1) errors with innovation SD {settings['noise_sd_log']}, "
              f"rho {settings['noise_ar1']}, seed {power['seed']}, and {power['repetitions']} "
              "replications per effect. Add independent synthetic area intercepts and a common "
              "trend/annual seasonal effect. Inject log(1+delta); percentage transformations "
              "describe (1+count), as in the planned log1p outcome. Reuse each null noise draw "
              "for every constant effect; beta shifts exactly and SE is unchanged. These errors "
              "exclude common local shocks, anticipation, and cross-boundary spillovers.", "",
              "| Injected effect | Rejection rate | MC standard error | 95% coverage | Mean log bias |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for row in power_rows:
        lines.append(f"| {row['injected_relative_effect']:.0%} | {row['rejection_rate']:.1%} | "
                     f"{row['monte_carlo_se']:.1%} | {row['coverage_95']:.1%} | {row['bias_log']:.5f} |")
    mde = summary["smallest_tested_effect_reaching_80pct"]
    lines += ["", f"Smallest tested absolute effect reaching 80% rejection: **{mde:.0%}**."
              if mde is not None else "No tested effect reaches 80% rejection.", "",
              "This is a coarse tested-effect threshold under assumed synthetic variance, "
              "not an interpolated MDE or an empirical power claim. A real-variance power "
              "analysis remains pending. The null rejection rate reports finite-sample size; "
              "it is not a new design gate.", "", "## Limitation", "", SPILLOVER_LIMITATION, "",
              "## Reproduction", "", "```powershell",
              f"python scripts/validate_area_simulations.py --prereg-commit {prereg_commit}",
              "python -m pytest -q tests/test_area_simulation.py -rxX", "```", ""]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    _block(root / "README.md", "area-simulation-summary",
           "Synthetic validation uses the real 53-area, 28-treated, 8-cohort structure. "
           "Stacked recovers the known -10% effect; the heterogeneous-dynamic TWFE test fails "
           "as expected. Power results assume synthetic noise and are not empirical project "
           "power. No real area effect has been fitted. [Simulation audit](reports/area_simulation/README.md).")
    _block(root / "docs/preregistration.md", "area-simulation-result",
           "Area-level synthetic validation is complete using the fixed 53-area universe, "
           "28 treated areas and 8 quarterly cohorts. The actual stacked sample contains "
           "49 physical-area clusters; four other-exposure areas are never clean. Known "
           "-10% recovery, the strict expected TWFE failure, and independent clustered OLS "
           "checks are documented in the [simulation audit](../reports/area_simulation/README.md). "
           "Power uses assumed synthetic variance. No real area outcome has been fitted; "
           "the final area estimation specification remains separate from this validation.")
    print(json.dumps({key: value for key, value in summary.items() if key != "input_hashes"}, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prereg-commit", required=True)
    args = parser.parse_args()
    run(Path(__file__).resolve().parents[1], args.prereg_commit)
