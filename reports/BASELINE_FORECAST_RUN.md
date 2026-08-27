# Baseline Forecast Run - Unilever Category A (MA3 / Naive / SBA)

- ABC period used: `2026-02`  (latest real demand month: `2026-02`)
- Methods: naive, ma3 (window=3), sba (alpha=0.1, tuned=False)
- Holdout fraction: 0.2  ·  MASE gate: 1.0  ·  eligibility: months_with_sales >= 3
- Report-only run (no `--write`).

## Counts

| total Tier A | ok | insufficient_data | dead_sku | LP-fallback (ins+dead) |
|---|---|---|---|---|
| 132 | 119 | 13 | 0 | 13 |

## Aggregate accuracy (status='ok', own valid subset per method)

| metric | naive | ma3 | sba |
|---|---|---|---|
| MASE median | 0.991 | 0.940 | 0.992 |
| MASE mean | 1.116 | 1.021 | 1.147 |
| MASE<1.0 % | 50.420 | 56.303 | 50.420 |
| MAPE median | 0.388 | 0.405 | 0.403 |
| MAPE<20% % | 15.126 | 15.966 | 11.765 |
| MAE median | 1515.429 | 1159.667 | 1771.011 |
| RMSE median | 1842.119 | 1336.920 | 1871.114 |
| outright wins (oracle) | 47 | 35 | 37 |

## Pass rates (MASE<1.0)

| selection | pass | rate |
|---|---|---|
| oracle (upper bound) | 84/119 | 70.6% |
| rule (deployable) | 60/119 | 50.4% |
| plain MA3 alone | 67/119 | 56.3% |

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

