# Forecast accuracy, as served

Computed 2026-10-21 from code version `c50af3f` (no uncommitted change in the forecasting code) by `scripts/accuracy_as_served.py`. Quote the **as served** rows, and quote them together with this version.

Window 2023-10 to 2026-02, Unilever Tier A the month before each test month (basis `t12m_new`), one month ahead, the router as the live forecast runs it. Latest demand month: 2026-02.

## Headline (quote these)

| Run | Median product WAPE | Pooled WAPE (pieces) | Total WAPE (pesos) | Surplus share of miss (pesos) | Surplus share of miss (pieces) | Products | Product-months |
|---|---|---|---|---|---|---|---|
| **As served** (no calendar factor) | 40.22% | 32.92% | 11.17% | 59.94% | 61.38% | 310 | 4,370 |
| **As served, calendar-adjusted** (the run 7 equivalent) | 42.56% | 32.46% | 12.09% | 60.39% | 61.96% | 310 | 4,370 |

*As served* means: months after a product's last sale are scored (a forecast of 0 against 0 counts); the dead-SKU rule is applied as the live forecast applies it (6 months, positive sales only, returns and blanks are not sales); a net-negative month is 0 in both the history and the actual; a blank-quantity month is not scored. Total WAPE (pesos) is the WAPE of the monthly peso totals over products with a price; surplus share of miss is (over-forecast miss) / (total miss), in the unit named. Median product WAPE is over products whose scored actuals are not all 0 (15 of 310 products have an undefined WAPE in the plain run, 15 in the calendar run).

## What the old figure was, and why it moved

| Run | Median product WAPE | Pooled WAPE (pieces) | Total WAPE (pesos) | Surplus share of miss (pesos) | Surplus share of miss (pieces) | Products | Product-months |
|---|---|---|---|---|---|---|---|
| Stored run 5 (`414cd352`), scored as the accuracy mart scores it | 38.72% | 31.86% | 10.27% | 57.35% | 60.06% | 300 | 3,989 |
| Stored run 7 (`34985eb3`), calendar-adjusted, same scoring | 38.28% | 31.36% | 11.08% | 57.82% | 60.62% | 300 | 3,989 |

Run 5 reproduces the 38.72% median quoted before. It predates c0b2727 (net-negative months as 0, positive-sales dead test) and it never scored a month with no sales row, and it applies no dead-SKU rule. It is not a replay of today's serving code.

Where the as-served number comes from, step by step on the same product-months (plain run):

| Run | Median product WAPE | Pooled WAPE (pieces) | Total WAPE (pesos) | Surplus share of miss (pesos) | Surplus share of miss (pieces) | Products | Product-months |
|---|---|---|---|---|---|---|---|
| As served, **dead rule off** (router's own number) | 40.22% | 33.41% | 11.28% | 60.51% | 61.95% | 310 | 4,370 |
| As served (dead rule on) | 40.22% | 32.92% | 11.17% | 59.94% | 61.38% | 310 | 4,370 |
| Sensitivity: as served, scored against **raw net quantity** (returns stay negative) | 40.77% | 32.94% | 11.31% | 60.09% | 61.42% | 310 | 4,370 |
| Sensitivity: as served, **calendar-adjusted**, raw net quantity | 43.27% | 32.49% | 12.24% | 60.53% | 62.00% | 310 | 4,370 |

The dead-SKU rule fired on 90 of 4,370 scored product-months (plain run) and 90 in the calendar run. Product-months not scored: 64 with fewer than 3 sales months (the live forecast serves a provisional average, not a forecast), 11 with a blank actual.

## Limits of these numbers

- The cohort changes every month (Tier A the month before), so the product count is for the whole window, not for Tier A as of 2026-02 (189 products).
- The MA3 benchmark on the same product-months has a median product WAPE of 39.37% (served: plain 40.22%, calendar 42.56%); MA3 is never calendar-adjusted. The served models are not shown to beat MA3 here, and the calendar factor raises the median error on these months.
- Dead-SKU rule: months-with-history gate and window are the live runner's (`DEAD_SKU_MONTHS` = 6); this script does not change them.
- Per product-month rows are in the git-ignored `local/accuracy_as_served_rows.csv`.
