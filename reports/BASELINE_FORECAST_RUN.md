# Baseline Forecast Run - Unilever Category A (MA3 / Naive / SBA)

- ABC period used: `2026-02`  (latest real demand month: `2026-02`)
- Methods: naive, ma3 (window=3), sba (alpha=0.1, tuned=False)
- Holdout fraction: 0.2  ·  MASE gate: 1.0  ·  eligibility: months_with_sales >= 3
- Report-only run (no `--write`).

## Counts

| total Tier A | ok | insufficient_data | dead_sku | LP-fallback (ins+dead) |
|---|---|---|---|---|
| 189 | 175 | 9 | 5 | 14 |

## Aggregate accuracy (status='ok', own valid subset per method)

| metric | naive | ma3 | sba |
|---|---|---|---|
| MASE median | 1.088 | 1.024 | 1.038 |
| MASE mean | 1.269 | 1.153 | 1.210 |
| MASE<1.0 % | 42.857 | 48.571 | 46.286 |
| MAPE median | 0.540 | 0.504 | 0.496 |
| MAPE<20% % | 9.884 | 10.465 | 7.558 |
| MAE median | 1008.250 | 868.238 | 1104.800 |
| RMSE median | 1149.854 | 975.463 | 1301.292 |
| outright wins (oracle) | 70 | 51 | 54 |

## Pass rates (MASE<1.0)

| selection | pass | rate |
|---|---|---|
| oracle (upper bound) | 112/175 | 64.0% |
| rule (deployable) | 81/175 | 46.3% |
| plain MA3 alone | 85/175 | 48.6% |

## rule_method mapping

Derived from the full 1,807-SKU catalog (1,096 evaluable, all tiers), applied to Tier A only.

| class | -> method |
|---|---|
| smooth | sba |
| erratic | sba |
| intermittent | naive |
| lumpy | naive |
| unclassifiable | naive |

### Full-catalog class x method win counts (evidence)

| class (n) | naive | ma3 | sba | croston | tsb |
|---|---|---|---|---|---|
| smooth (263) | 50 | 68 | 112 | 25 | 8 |
| erratic (39) | 2 | 14 | 16 | 1 | 6 |
| intermittent (426) | 204 | 81 | 88 | 40 | 13 |
| lumpy (358) | 152 | 72 | 80 | 18 | 36 |

MA3 is never the #1 method in any single class, so a class-conditional rule never selects it.

