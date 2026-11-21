# Distance-based spillover sensitivity: counts only

Rules committed before counting in [df5127b](https://github.com/Anran0716/indego-station-impact/commit/df5127b5a8d05b623143f08304e648be22c4c6cd). No real outcomes were parsed or effect models fitted.

Remove a main clean control area when any of its fixed qualified old stations is <=400 metres from any exposure source opening during the stack's full calendar window, including the last Sunday. Use 156 qualified old stations and all 101 exposure sources. Earlier and later openings do not trigger this particular restriction. Keep the main 20/15 gate unchanged. The sensitivity requires >=10 controls in every stack; otherwise the variant is not estimable.

| Offset (m) | Min controls | Max controls | Stacks below 10 | Sensitivity status |
| --- | ---: | ---: | ---: | --- |
| (0, 0) | 18 | 41 | 0/8 | estimable |
| (500, 0) | 18 | 42 | 0/7 | estimable |
| (0, 500) | 17 | 42 | 0/7 | estimable |
| (500, 500) | 19 | 41 | 0/9 | estimable |

The fixed (0,0) grid remains primary. `stacks.csv` records every count; `controls.csv` records each main control's disposition; `excluded_pairs.csv` lists the old/new station pairs triggering removal. No passing offset rescues a failed primary sensitivity variant. Passing these counts would establish estimability only, not absence of spillovers.

## Limitation

The main estimate assumes no cross-boundary spillover; the planned exclusion test was not estimable because nearly every control area borders a treated area.

The sentence above refers to the original eight-neighbour test, whose minimum remaining control count is 1 on the primary grid. It remains not estimable; the distance rule is a separately registered sensitivity, not a replacement main-design gate.

## Reproduction

```powershell
python scripts/count_distance_spillover.py --prereg-commit df5127b5a8d05b623143f08304e648be22c4c6cd
```
