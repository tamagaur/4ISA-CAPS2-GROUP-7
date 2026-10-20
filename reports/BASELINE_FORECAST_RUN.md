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
| MASE median | 1.068 | 1.002 | 1.038 |
| MASE mean | 1.232 | 1.130 | 1.208 |
| MASE<1.0 % | 44.571 | 49.714 | 46.286 |
| MAPE median | 0.532 | 0.497 | 0.491 |
| MAPE<20% % | 10.000 | 10.588 | 7.647 |
| MAE median | 1008.250 | 838.583 | 1075.750 |
| RMSE median | 1149.854 | 966.050 | 1245.766 |
| outright wins (oracle) | 70 | 50 | 55 |

## Pass rates (MASE<1.0)

| selection | pass | rate |
|---|---|---|
| oracle (upper bound) | 115/175 | 65.7% |
| rule (deployable) | 81/175 | 46.3% |
| plain MA3 alone | 87/175 | 49.7% |

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

