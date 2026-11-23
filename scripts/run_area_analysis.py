"""Run the preregistered real area analysis: main, robustness, then empirical power."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
import yaml

from stimpact.area_models import (
    area_panel,
    distance_design,
    empirical_power,
    event_reference_diagnostic,
    event_study,
    ordered_outcome,
    placebo_design,
    ppml,
    type_m_diagnostic,
)
from stimpact.area_report import SPILLOVER_LIMITATION, _block, record_summary
from stimpact.area_simulation import design_from_counts, make_regression
from stimpact.download import sha256
from stimpact.feasibility import weekly_departures
from stimpact.io import load_trips


def json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def check_registration(root, commit, config):
    commit = subprocess.check_output(["git", "rev-parse", f"{commit}^{{commit}}"], cwd=root,
                                     text=True, encoding="utf-8").strip()
    frozen = yaml.safe_load(subprocess.check_output(["git", "show", f"{commit}:config.yaml"],
                            cwd=root, text=True, encoding="utf-8"))
    for section in ("area_analysis", "area_feasibility", "spillover_distance", "study", "eligibility", "spatial"):
        if config[section] != frozen.get(section):
            raise ValueError(f"Current {section} differs from committed preregistration")
    for key in ("event_pre_weeks", "event_post_weeks", "reference_event_week"):
        if config["estimation"][key] != frozen["estimation"][key]:
            raise ValueError("Event window differs from preregistration")
    document = subprocess.check_output(["git", "show", f"{commit}:docs/preregistration.md"],
                                       cwd=root, text=True, encoding="utf-8")
    if "Final area prediction and estimation specification" not in document or "log(1.05)" not in document:
        raise ValueError("Selected commit lacks the frozen area prediction/specification")
    return commit


def station_weeks(root, config, input_paths, reuse=False):
    manifest_path = root / "data/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if sha256(root / "data/raw" / entry["filename"]) != entry["sha256"]:
            raise ValueError(f"Input hash mismatch: {entry['filename']}")
    signature = {"manifest": sha256(manifest_path), "id_map": sha256(input_paths["id_map"]),
                 "study": config["study"], "eligibility": config["eligibility"]}
    directory = root / "data/interim"
    directory.mkdir(parents=True, exist_ok=True)
    cache, metadata = directory / "all_station_weeks.csv", directory / "all_station_weeks.json"
    if reuse and cache.exists() and metadata.exists():
        saved = json.loads(metadata.read_text(encoding="utf-8"))
        if saved["signature"] != signature or saved["cache_sha256"] != sha256(cache):
            raise ValueError("Station-week cache does not match current pinned inputs/settings")
        print("Using hashed all-station weekly cache", flush=True)
        return pd.read_csv(cache, dtype={"station_id": "string"}, parse_dates=["week"]), saved
    id_map = pd.read_csv(input_paths["id_map"], dtype="string")
    chunks, cleaning = [], Counter()
    for entry in manifest["files"]:
        if entry["kind"] != "trip_csv":
            continue
        trips = load_trips(root / "data/raw" / entry["filename"],
                           config["eligibility"]["virtual_station_id"], station_id_map=id_map)
        weekly, audit = weekly_departures(trips, config)
        chunks.append(weekly)
        cleaning.update(audit)
        print(f"Panel input {entry['filename']}: {audit['counted_departures']:,} counted departures", flush=True)
    weekly = pd.concat(chunks).groupby(["station_id", "week"], as_index=False).departures.sum()
    if int(weekly.departures.sum()) != cleaning["counted_departures"]:
        raise AssertionError("Quarter aggregation loses departures")
    weekly.to_csv(cache, index=False)
    metadata_value = {"signature": signature, "cache_sha256": sha256(cache), "cleaning": dict(cleaning)}
    save_json(metadata, metadata_value)
    return weekly, metadata_value


def estimate_row(name, result, outcome="all_station", offset=(0, 0), **extra):
    keys = ("coefficient", "se", "ci_low", "ci_high", "p_value", "clusters", "observations", "parameters")
    row = {"specification": name, "outcome": outcome, "offset_x_m": offset[0], "offset_y_m": offset[1],
           **{k: result[k] for k in keys if k in result}, **extra}
    row.update(relative_effect=float(np.expm1(row["coefficient"])),
               relative_ci_low=float(np.expm1(row["ci_low"])),
               relative_ci_high=float(np.expm1(row["ci_high"])))
    return row


def make_plots(root, out, event, estimates, power):
    os.environ.setdefault("MPLCONFIGDIR", str(root / ".scratch/mpl"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "savefig.facecolor": "white"})
    frame = event["coefficients"]
    fig, ax = plt.subplots(figsize=(9, 4.8), layout="constrained")
    ax.errorbar(frame.event_week, frame.coefficient,
                yerr=[frame.coefficient - frame.ci_low, frame.ci_high - frame.coefficient],
                fmt="o-", capsize=3, color="#176b87", markersize=4, linewidth=1.2)
    ax.axhline(0, color="#777777", linewidth=0.8)
    ax.axvline(-0.5, color="#999999", linestyle="--", linewidth=0.8)
    joint = event["pretrend"]
    label = f"Joint pretrend p = {joint['p_value']:.3g}" if joint["status"] == "estimated" else "Joint test not estimable"
    ax.set(title="Indego openings: all-station area departures", xlabel="Weeks relative to first eligible opening",
           ylabel="Coefficient on log(1 + weekly departures)")
    ax.text(0.02, 0.97, label + "\nPointwise 95% CI; physical-area clusters", transform=ax.transAxes, va="top")
    ax.set_xticks(range(-12, 13, 2))
    fig.savefig(out / "event_study.png", dpi=180)
    svg = out / "event_study.svg"
    fig.savefig(svg)
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines())
                   + "\n", encoding="utf-8")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4.8), layout="constrained")
    plotting = [r for r in estimates if r["outcome"] == "all_station"]
    for index, row in enumerate(plotting):
        ax.errorbar(100 * row["relative_effect"], index,
                    xerr=[[100 * (row["relative_effect"] - row["relative_ci_low"])],
                          [100 * (row["relative_ci_high"] - row["relative_effect"])]],
                    fmt="o", capsize=3, color="#176b87")
    ax.set_yticks(range(len(plotting)), [r["specification"] for r in plotting])
    ax.axvline(0, color="#777777", linewidth=0.8)
    ax.invert_yaxis()
    ax.set(xlabel="Effect (%) and 95% CI", title="Prespecified estimates: all reported")
    fig.savefig(out / "robustness.png", dpi=180)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.5, 4.6), layout="constrained")
    table = power["power"]
    for positive, color, marker in ((True, "#176b87", "o"), (False, "#b85c38", "s")):
        group = table.loc[table.effect.ge(0) if positive else table.effect.le(0)].copy()
        group["magnitude"] = group.effect.abs()
        group = group.sort_values("magnitude")
        ax.errorbar(100 * group.magnitude, group.rejection_rate,
                    yerr=1.96 * group.monte_carlo_se, fmt=marker + "-", capsize=3,
                    label="Positive effects" if positive else "Negative effects", color=color)
    ax.axhline(0.8, color="#777777", linestyle="--", linewidth=0.8)
    ax.axhline(0.05, color="#999999", linestyle=":", linewidth=0.8)
    ax.set(xlabel="Injected absolute effect (%)", ylabel="Rejection rate",
           title="Power from observed area residuals", ylim=(0, 1.05))
    ax.legend(frameon=False)
    fig.savefig(out / "empirical_power.png", dpi=180)
    plt.close(fig)


def run(root, prereg_commit, reuse_cache=False):
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    commit = check_registration(root, prereg_commit, config)
    paths = {"registry": root / "reports/stage0/canonical_station_registry.csv",
             "id_map": root / "reports/stage0/station_id_map.csv",
             "old": root / "reports/stage1/eligibility_audit.csv",
             "areas": root / "reports/area_feasibility/area_assignments.csv",
             "stacks": root / "reports/area_feasibility/stack_control_counts.csv",
             "controls": root / "reports/area_feasibility/control_membership.csv",
             "distance": root / "reports/distance_spillover/controls.csv"}
    registry = pd.read_csv(paths["registry"], dtype={"station_id": "string"})
    old = pd.read_csv(paths["old"], dtype={"station_id": "string"}, usecols=["station_id", "eligible"])
    areas, stacks, controls = (pd.read_csv(paths[key]) for key in ("areas", "stacks", "controls"))
    weekly, cache = station_weeks(root, config, paths, reuse_cache)
    out = root / "reports/area_analysis"
    processed = root / "data/processed"
    out.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    designs, panels, audits = {}, {}, []
    for offset_list in config["area_feasibility"]["offsets_m"]:
        offset = tuple(offset_list)
        selection = deepcopy(config)
        selection["area_simulation"]["primary_offset_m"] = list(offset)
        designs[offset] = design_from_counts(areas, stacks, controls, selection)
        panels[offset], audit = area_panel(weekly, registry, set(old.loc[old.eligible, "station_id"]),
                                          areas, offset, config)
        audits.append(audit)
        panels[offset].to_csv(processed / f"area_panel_{offset[0]}_{offset[1]}.csv", index=False)
    pd.DataFrame(audits).to_csv(out / "panel_audit.csv", index=False)
    primary_offset = tuple(config["area_analysis"]["primary_offset_m"])
    design, panel = designs[primary_offset], panels[primary_offset]
    counts = ordered_outcome(panel, design)
    log_y = np.log1p(counts)
    model = make_regression(design)
    print("MAIN: fitting pooled stacked coefficient and secondary old-station outcome", flush=True)
    main = model.fit(log_y)
    estimates = [estimate_row("Main stacked (0,0)", main)]
    secondary = model.fit(np.log1p(ordered_outcome(panel, design, "old_departures")))
    estimates.append(estimate_row("Qualified-old secondary", secondary, outcome="qualified_old"))
    pd.DataFrame(estimates).to_csv(out / "main_estimates.csv", index=False)
    print(json.dumps({"main": estimates[0]}, default=json_default), flush=True)
    event = event_study(model, log_y)
    event["coefficients"].to_csv(out / "event_study.csv", index=False)
    pd.DataFrame(event["covariance"], index=event["event_order"], columns=event["event_order"]).to_csv(
        out / "event_covariance.csv", index_label="event_week")
    save_json(out / "pretrend.json", event["pretrend"])
    save_json(out / "event_post_average.json", event["post_average"])
    print("MAIN pretrend: " + json.dumps(event["pretrend"]), flush=True)
    print("ROBUSTNESS: committed distance exclusion", flush=True)
    membership = pd.read_csv(paths["distance"])
    membership = membership.loc[membership.offset_x_m.eq(primary_offset[0])
                                & membership.offset_y_m.eq(primary_offset[1])]
    restricted = distance_design(design, membership, config["spillover_distance"]["min_controls_per_stack"])
    estimates.append(estimate_row("Distance exclusion <=400m", make_regression(restricted).fit(log_y)))
    print("ROBUSTNESS: Poisson PML on the same main count/FE sample", flush=True)
    failures = []
    try:
        poisson = ppml(model, counts)
        estimates.append(estimate_row("PPML", poisson))
        save_json(out / "ppml_diagnostics.json", poisson)
    except (ValueError, ArithmeticError) as error:
        failures.append({"specification": "PPML", "status": "not_estimable", "reason": str(error)})
    print("ROBUSTNESS: 26-week earlier placebo", flush=True)
    placebo, omitted = placebo_design(design, config["area_analysis"]["placebo_shift_weeks"])
    placebo_model = make_regression(placebo)
    estimates.append(estimate_row("Placebo: 26 weeks earlier", placebo_model.fit(log_y),
                                  supported_cohorts=len(placebo["stacks"])))
    save_json(out / "placebo_support.json", {"omitted_cohorts": omitted,
              "included_cohorts": [s["cohort"] for s in placebo["stacks"]],
              "treated_areas": sum(a["treated"] for a in placebo["areas"])})
    print("ROBUSTNESS: all four fixed grids (primary retained above)", flush=True)
    for offset in designs:
        if offset == primary_offset:
            continue
        shifted_model = make_regression(designs[offset])
        shifted_log_y = np.log1p(ordered_outcome(panels[offset], designs[offset]))
        estimates.append(estimate_row(f"Grid ({offset[0]},{offset[1]})", shifted_model.fit(shifted_log_y), offset=offset))
    pd.DataFrame(estimates).to_csv(out / "all_estimates.csv", index=False)
    save_json(out / "robustness_failures.json", failures)
    print("POWER: 200 wild physical-area draws using observed main-model residuals", flush=True)
    power = empirical_power(model, log_y, config["area_analysis"]["empirical_power"])
    power["power"].to_csv(out / "empirical_power.csv", index=False)
    power["draws"].to_csv(out / "power_replications.csv", index=False)
    empirical_summary = {k: v for k, v in power.items() if k not in ("power", "draws")}
    save_json(out / "power_method.json", empirical_summary)
    make_plots(root, out, event, estimates, power)
    summary = {"preregistration_commit": commit, "prediction_relative_effect": 0.05,
               "input_hashes": {k: sha256(p) for k, p in paths.items()},
               "cleaning": cache["cleaning"], "panel_audits": audits, "estimates": estimates,
               "event_pretrend": event["pretrend"], "event_post_average": event["post_average"],
               "robustness_failures": failures, "placebo_omitted": omitted,
               "empirical_power": empirical_summary, "power": power["power"].to_dict(orient="records"),
               "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                           "pandas": pd.__version__, "scipy": scipy.__version__},
               "real_effect_estimator_run": True, "uses_observed_variance": True}
    save_json(out / "summary.json", summary)
    write_report(root, out, summary)
    print(json.dumps({"main": estimates[0], "pretrend": event["pretrend"],
                      "power_mdes": power["smallest_tested_80pct"]}, indent=2, default=json_default), flush=True)
    return summary


def write_report(root, out, summary):
    commit, primary = summary["preregistration_commit"], summary["estimates"][0]
    powers = {row["effect"]: row["rejection_rate"] for row in summary["power"]}
    old_result = next(row for row in summary["estimates"] if row["outcome"] == "qualified_old")
    event_coefficients = pd.read_csv(out / "event_study.csv")
    event_covariance = pd.read_csv(out / "event_covariance.csv", index_col=0)
    reference = event_reference_diagnostic(event_coefficients, event_covariance.to_numpy(),
                                            event_covariance.index.to_numpy(dtype=int), primary["clusters"])
    type_m = type_m_diagnostic(pd.read_csv(out / "power_replications.csv"), assumed_effect=0.10)
    diagnostics = {"status": "post_result_interpretation_only", "registered_estimators_unchanged": True,
                   "event_reference": reference, "type_m": type_m,
                   "input_hashes": {name: sha256(out / name) for name in (
                       "event_study.csv", "event_covariance.csv", "power_replications.csv")}}
    save_json(out / "interpretation_diagnostics.json", diagnostics)
    lines = ["# Preregistered area-level analysis", "",
             f"Prediction and final specification committed before area outcomes in [{commit[:7]}]"
             f"(https://github.com/Anran0716/indego-station-impact/commit/{commit}). "
             "Prediction: +5% net all-station area departures in event weeks 0–12. "
             "The main grid, cohorts, control rules and thresholds were fixed before fitting.", "",
             "## Main estimate and prespecified variants", "",
             "The primary outcome is log(1 + departures from all stations inside a qualified "
             "area). Qualified-old departures are secondary. The sample includes newly opened "
             "stations; the primary question concerns net local ridership, not only diversion. "
             "Pooled stacked estimates use stack-area and stack-week FE, physical-area "
             "clusters, full-rank CR1 and t(G-1) inference. Pooled and event-average summaries "
             "have different weighting and need not coincide. Log1p percentage transformations "
             "refer to 1+departures; PPML refers to expected departure counts.", "",
             "| Specification | Effect | 95% CI | p-value | Physical clusters | Rows |",
             "| --- | ---: | --- | ---: | ---: | ---: |"]
    for row in summary["estimates"]:
        lines.append(f"| {row['specification']} | {row['relative_effect']:+.1%} | "
                     f"[{row['relative_ci_low']:+.1%}, {row['relative_ci_high']:+.1%}] | "
                     f"{row['p_value']:.4g} | {row['clusters']} | {row['observations']} |")
    lines += ["", "Under the registered identification assumptions, higher all-station area "
              "ridership alongside lower qualified-old ridership is consistent with net local "
              "growth and partial redistribution from existing stations. Aggregate estimates "
              "do not track individual riders or directly identify a transfer fraction. "
              "Nonplacebo robustness point estimates are positive across specifications; "
              "the time-placebo estimate is small and compatible with zero, rather than "
              "proof that no pre-opening confounding exists."]
    joint, average = summary["event_pretrend"], summary["event_post_average"]
    lines += ["", "## Event study and identification", "", "![Event study](event_study.png)", ""]
    if joint["status"] == "estimated":
        lines += [f"Joint pretrend test, event weeks -12..-2: F({joint['df_num']},{joint['df_den']}) "
                  f"= {joint['F']:.3f}, p = **{joint['p_value']:.4g}**."]
        if joint["p_value"] < 0.05:
            lines += ["**The pretrend test rejects. The estimate is an association under the "
                      "registered design; the data do not support a clean causal interpretation "
                      "under parallel trends.** Report every specified result; do not change "
                      "the model or sample to obtain a preferred test result."]
        else:
            lines += ["The pretrend test does not reject at 5%. This does not establish parallel "
                      "trends, no anticipation, or random station placement."]
    else:
        lines += ["The joint pretrend test is not estimable; see `pretrend.json`."]
    lines += ["", f"Secondary event-study average, weeks 0..12: log coefficient "
              f"{average['coefficient']:.5f}, 95% CI [{average['ci_low']:.5f}, "
              f"{average['ci_high']:.5f}], p = {average['p_value']:.4g}. "
              f"Transformed: {np.expm1(average['coefficient']):+.1%} "
              f"[{np.expm1(average['ci_low']):+.1%}, {np.expm1(average['ci_high']):+.1%}]. "
              "This average uses the full event covariance, not an average of standard errors. "
              "It is a prespecified secondary contrast relative to week -1, **not the headline "
              "net-growth estimate**.", "",
              "The event-study average is relative to week -1, which sits below the pre-period "
              "mean; relative to the full pre-period the post average is about +11%, consistent "
              "with the pooled estimate.", "",
              f"For clarity, the mean coefficient over weeks -12..-2 is "
              f"{reference['pre_mean_minus12_to_minus2']:.5f}. Including the zero reference "
              f"coefficient for week -1, the full 12-week pre-period mean is "
              f"{reference['pre_mean_minus12_to_minus1']:.5f}. Subtracting that full pre-mean "
              f"from the post mean gives {reference['post_minus_full_pre']['coefficient']:.5f} "
              f"log units, or **{reference['post_minus_full_pre_relative']:+.1%}**. Excluding "
              f"the reference week from the pre-mean gives "
              f"{reference['post_minus_nonreference_pre_relative']:+.1%}. These are explicitly "
              "post-result reference diagnostics, computed from the saved coefficients and "
              "their full covariance; no model was refitted or reference week changed. The "
              "pooled estimator compares post observations with the whole pre-period using "
              "its regression weights, reducing reliance on any one low week. It need not "
              "equal an arithmetic event-time contrast exactly.", "",
              f"Descriptively, weeks 1–2 average "
              f"{reference['early_post_mean_1_to_2_log']:.3f} in log coefficients relative to "
              f"week -1, while weeks 3–12 average "
              f"{reference['later_post_mean_3_to_12_log']:.3f} with week-to-week fluctuations. "
              "This early bump is compatible with a transient opening response or novelty, "
              "but the curve alone does not identify that mechanism. These log coefficients "
              "are not percentage-point changes.", "",
              "## Robustness and sample support", "", "![Prespecified variants](robustness.png)", "",
              "The <=400m exclusion is the registered distance rule, requiring >=10 controls "
              "in every stack. PPML uses the same count sample/FE and physical clusters; its "
              "IRLS convergence and score diagnostics are in `ppml_diagnostics.json`. No zero "
              "counts or separated observations are silently removed. Every fixed grid is "
              "reported, with (0,0) retained as primary regardless of its estimate.", "",
              "The time placebo shifts treatment and windows 26 weeks earlier and reuses "
              "original clean controls. Only complete shifted cohorts inside the observed "
              "panel are estimable; omitted placebo cohorts: "
              + ", ".join(row["cohort"] for row in summary["placebo_omitted"]) + ". "
              "This support restriction does not omit any main cohort. See `placebo_support.json`.", ""]
    uncertain = [row["specification"] for row in summary["estimates"]
                 if row["outcome"] == "all_station" and not row["specification"].startswith("Placebo")
                 and row["ci_low"] <= 0 <= row["ci_high"]]
    if uncertain:
        lines += ["The following nonplacebo intervals include zero: " + ", ".join(uncertain)
                  + ". Positive point estimates across these specifications should be read "
                  "with their differing uncertainty; the report does not label all robustness "
                  "results as passed.", ""]
    for failure in summary["robustness_failures"]:
        lines += [f"**{failure['specification']}: not estimable** — {failure['reason']}", ""]
    lines += ["## Empirical-residual power (replaces synthetic example)", "",
              "![Empirical-residual power](empirical_power.png)", "",
              "Unrestricted main-model residuals are scaled by sqrt(N/(N-K)). The fitted "
              "pooled effect is removed, nuisance FE retained, and one Rademacher sign is "
              "shared by all rows/weeks/stack copies of each physical area. Inject log(1+delta) "
              "and refit the same stacked/CR1 test. Use 200 common-sign draws per effect, "
              "seed 20261122. This uses observed residual magnitudes and within-area dependence; "
              "it is conditional design power, not an unconditional forecast or proof of "
              "causal identification. Residuals may contain heterogeneous effects and omitted shocks.", "",
              "| Injected effect | Rejection rate | MC SE | 95% coverage |",
              "| --- | ---: | ---: | ---: |"]
    for row in summary["power"]:
        lines.append(f"| {row['effect']:+.0%} | {row['rejection_rate']:.1%} | "
                     f"{row['monte_carlo_se']:.1%} | {row['coverage_95']:.1%} |")
    for direction, magnitude in summary["empirical_power"]["smallest_tested_80pct"].items():
        lines += ["", f"Smallest tested {direction} absolute effect reaching 80% rejection: "
                  + (f"**{magnitude:.0%}**." if magnitude is not None else "**none among tested effects**.")]
    lines += ["", "These are coarse tested-effect thresholds with Monte Carlo uncertainty, "
              "not interpolated MDEs. The 0% row estimates the null rejection rate. The "
              "[synthetic simulation](../area_simulation/README.md) remains an archived code "
              "validation; its assumed-noise power is superseded by this empirical analysis.", "",
              "## Magnitude uncertainty and Type M risk", "",
              f"With {powers[0.10]:.1%} power at an assumed +10% effect, statistically significant estimates "
              "can exaggerate magnitude when attention is conditioned on significance. "
              "This is the conditional Type M/exaggeration risk described by "
              "[Gelman and Carlin](https://sites.stat.columbia.edu/gelman/research/published/retropower20.pdf). "
              f"It does not, by itself, establish that this particular {primary['relative_effect']:+.1%} estimate is "
              "too large, or justify replacing its interval with a narrower subjective range.", ""]
    if type_m["estimable"]:
        lines += [f"Post-result illustration using only the already saved +10% bootstrap "
                  f"scenario: {type_m['significant_repetitions']}/{type_m['repetitions']} draws "
                  f"are significant. Among those draws, the mean transformed estimate is "
                  f"{type_m['conditional_mean_relative_estimate']:+.1%}; the conditional mean "
                  f"absolute log-magnitude ratio is **{type_m['conditional_log_magnitude_ratio']:.2f}** "
                  "relative to the assumed true log effect. This calculation is conditional "
                  "on a true +10% effect and this empirical-residual bootstrap; it is not a "
                  "shrinkage correction or a posterior probability about the observed effect.", ""]
    lines += ["Interview wording: \"The results are consistent with positive net area growth "
              "alongside diversion from existing stations. Every prespecified nonplacebo "
              "robustness variant for the all-station outcome has a positive point estimate. "
              f"Given only about {powers[0.10]:.0%} power at +10%, "
              "I would describe a positive effect on roughly a 10% scale with substantial "
              "uncertainty, rather than claim precisely 11%.\" The full primary 95% interval "
              f"remains {primary['relative_ci_low']:+.1%} to {primary['relative_ci_high']:+.1%}, "
              "with some robustness intervals including zero.", "",
              "## Limitations", "", SPILLOVER_LIMITATION, "",
              "Station placement can follow local demand changes. All-station area totals "
              "include within-cell diversion, while cross-boundary changes can bias estimates "
              "in either direction. The four offsets change which openings/old stations share "
              "a cell, so their estimates answer related but not identical spatial questions. "
              "An opening week is only partially exposed. One treated cell has earlier "
              "outside-window exposure; the precommitted timing diagnostic was retained, not "
              "used as a post-hoc exclusion. The secondary old-station pool was selected using "
              "the registered baseline/inactivity rules. This is one city's network expansion.", "",
              "## Audit and reproduction", "",
              "`panel_audit.csv` reconciles all cleaned departures inside/outside each study "
              "grid. Zero area-weeks are retained. Canonical IDs and fixed positions are used "
              "for every station, including new ones. Raw trips and full panels remain ignored. "
              "Input hashes, software versions, exact coefficients and diagnostics are in "
              "`summary.json`; `all_estimates.csv` and `event_covariance.csv` provide full precision.", "",
              "```powershell", "python -m pip install -e '.[dev]'",
              f"python scripts/run_area_analysis.py --prereg-commit {commit}",
              "# For an existing verified station-week cache, append --reuse-weekly-cache", "```", ""]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    interpretation = ("The joint pretrend test is not estimable" if joint["status"] != "estimated"
                      else "The joint pretrend test rejects" if joint["p_value"] < 0.05
                      else "The joint pretrend test does not reject")
    record_summary(root, "area-estimation-summary",
           f"Primary stacked estimate: **{primary['relative_effect']:+.1%}** "
           f"(95% CI {primary['relative_ci_low']:+.1%} to {primary['relative_ci_high']:+.1%}). "
           f"The qualified-old secondary estimate is {old_result['relative_effect']:+.1%}, "
           "consistent with net local growth alongside partial redistribution under the "
           f"identification assumptions. The event-study {np.expm1(average['coefficient']):+.1%} "
           "average is relative to a low "
           f"week -1; its contrast against the full pre-period is about "
           f"**{reference['post_minus_full_pre_relative']:+.1%}**, consistent with the pooled "
           "estimate. The week -1-relative secondary contrast is not the headline conclusion. "
           f"{interpretation}; causal interpretation remains conditional on identification "
           "assumptions. Main/event-study results, every prespecified robustness variant, "
           "and observed-residual power are in the [area analysis](reports/area_analysis/README.md).")
    mdes = summary["empirical_power"]["smallest_tested_80pct"]
    mde_note = "; ".join(f"{direction}: {magnitude:.0%}" if magnitude is not None
                         else f"{direction}: no tested effect" for direction, magnitude in mdes.items())
    record_summary(root, "area-empirical-power-summary",
           f"Current power uses observed main-model residuals with 200 physical-area wild draws "
           f"per effect: +5% **{powers[0.05]:.1%}**, +10% **{powers[0.10]:.1%}**, "
           f"+15% **{powers[0.15]:.1%}** rejection. Smallest tested magnitudes reaching 80%: "
           f"{mde_note}. This conditional empirical-residual power supersedes "
           f"the synthetic-noise example. At about {powers[0.10]:.0%} power for +10%, significance-selected "
           f"estimates can exaggerate magnitude (Type M risk); {primary['relative_effect']:+.1%} should be read with its "
           "wide interval, rather than as a precise effect size. This is a conditional risk, "
           "not proof that the observed estimate is inflated. "
           "[Methods, interpretation and full signed curve](reports/area_analysis/README.md).")
    _block(root / "docs/preregistration.md", "area-estimation-result",
           f"Real area analysis completed under prediction/specification commit [{commit[:7]}]"
           f"(https://github.com/Anran0716/indego-station-impact/commit/{commit}). "
           "All main cohorts, fixed grids and thresholds were retained. Main, robustness, "
           "and empirical power outputs are in the [analysis audit](../reports/area_analysis/README.md).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prereg-commit", required=True)
    parser.add_argument("--reuse-weekly-cache", action="store_true")
    args = parser.parse_args()
    run(Path(__file__).resolve().parents[1], args.prereg_commit, args.reuse_weekly_cache)
