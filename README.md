An independent project estimating how new Indego stations affect ridership at nearby existing stations.

# Indego station impact

**Status:** Stage 0 data download and input audit completed. Treatment assignment and estimation have not started. The estimated effect, confidence interval, minimum detectable effect (MDE), and diversion rate are pending. The main identification risk is that new stations may be placed where demand is already growing.

See the generated [Stage 0 audit](reports/stage0/README.md) for annual trip counts, opening-date checks, coordinate flags, and possible station-ID replacements. A coordinate jump is a review flag, not a confirmed physical relocation. Resolve station identities before freezing treatment sources.

## Research question

How did new Indego stations opening in 2022–2024 affect weekly departures at nearby existing stations in Philadelphia? New stations could divert trips from existing stations, improve the network and increase their use, or do both. The target is the net effect on existing stations.

## Planned design

- Use publicly available Indego quarterly trip files for 2022 Q1–2024 Q4 and the latest official station table. Audit opening dates and station coordinates before assigning treatment.
- Select a treatment radius using a prespecified station-count rule and keep the buffer at twice that radius. Require 30 controls per stack: first use never-treated stations, then add stations whose first exposure within 2R occurs after the entire stack window if needed. If any stack remains below 30, redesign at the area level.
- Estimate a stacked difference-in-differences model of `log(1 + weekly departures)` with stack-specific station and week fixed effects and standard errors clustered by station. The event window is 12 weeks before through 12 weeks after opening.
- Use simulations to demonstrate a failure of ordinary two-way fixed effects under heterogeneous treatment effects before estimating effects on real data. Report event-study intervals, pretrend diagnostics, robustness checks, and simulation-based power.

The [preregistration draft](docs/preregistration.md) records the planned rules. Radius selection and a dated, separate preregistration commit must be completed before real-data estimation. This initial scaffold commit is not a completed preregistration.

## Repository

```text
config.yaml                 Study parameters; radius awaits feasibility check
data/manifest.json          Pinned input URLs, row counts, and SHA256 hashes
docs/preregistration.md     Design rules; freeze after the feasibility check
reports/stage0/             Generated input-audit tables and summary
scripts/                    Download and Stage 0 entry points
sql/                        DuckDB panel construction, to be implemented
src/stimpact/               Python analysis package
tests/                      Synthetic input-validation tests
```

Python 3.11 is the target runtime and is used in CI. Dependencies are pandas, DuckDB, NumPy, pyproj, pyfixest, Matplotlib, and PyYAML; Ruff and pytest support development. CI checks lint, syntax, and synthetic-fixture tests without downloading real inputs. The audit records its actual runtime versions in `reports/stage0/summary.json`. DuckDB is pinned to 1.4.4 after an explicit strict-mode CSV read returned zero rows under 2.0.1 in the local environment; the manifest row-count assertion caught that failure.

## Reproduction status

Install the project and run the current download-and-audit pipeline:

```powershell
python -m pip install -e '.[dev]'
python scripts/run_stage0.py
```

For a verified existing download, use `python scripts/run_stage0.py --offline`. Each archive and extracted CSV has its source URL, download date, row count, and SHA256 recorded in the committed [manifest](data/manifest.json). URLs are pinned on the first successful discovery, so future runs do not silently switch to a newer station table. Raw and intermediate data stay outside version control. The later download-to-figures analysis pipeline remains to be implemented.

## Assumptions and limitations

1. Station placement is not random. A causal interpretation requires parallel trends and no anticipation; pretrend diagnostics cannot establish these assumptions on their own.
2. Spillovers may extend beyond the buffer and affect control stations.
3. The opening week contains only partial exposure because opening dates are aligned to the preceding Monday.
4. Evidence from one city may not generalize to other systems.
5. Interpreting reduced trips at existing stations as diversion also requires assumptions about other concurrent changes and how exposure overlaps across new stations.

All eventual estimates will include uncertainty. A nonsignificant estimate will be interpreted with its confidence interval and MDE rather than treated as evidence of zero effect.
