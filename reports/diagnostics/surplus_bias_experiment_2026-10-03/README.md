# Surplus-bias fix experiment, stock-aware: Unilever Tier A as of 2026-02

Read-only, offline experiment, 2026-10-03, branch `kelvin/surplus-bias-experiment`.

**Scope.** Tier A is the top class of the ABC (Pareto) classification by sales value (method `single`). This
experiment covers the 107 Unilever products in Tier A as of 2026-02 that the forecast-error diagnostic scores on
its common window. Del Monte has no product-level sales, so it is not forecast.

**Units.** Quantities are in pieces. Money is in pesos (₱) **at selling price, VAT-inclusive (value-added
tax)**, averaged per month over the window named next to it. Products are named first, with the SKU
(stock-keeping unit) code after.

Two test windows, both rebuilt from the served forecast router and checked against the forecast-error
diagnostic (`kelvin/forecast-error-business`, commit `b4f6b77`):

| Window | Test months | Product-months scored | How the model's history bin is chosen |
|---|---|---:|---|
| **6 months** | 2025-09 to 2026-02 | 642 | The product's served bin as of 2026-03, held fixed (that diagnostic's window A) |
| **29 months** | 2023-10 to 2026-02 | 2,419 | Re-worked each month from the history known then (that diagnostic's window C) |

## Decisions recorded (user, 2026-10-03)

| # | Decision | What it means here |
|---|---|---|
| 1 | **Threshold.** A forecast change must remove at least **5% of surplus pesos** over the 29-month window (2023-10 to 2026-02), **and** must not add more shortage pesos than it removes. | No candidate passes. Over 29 months the largest surplus cut is 1.0% (E1), and A, B and C each add more shortage than they remove. **Recommendation: D (flag only).** The test is recorded in `long_window/candidates_summary.csv`, column `meets_recorded_threshold`. |
| 2 | **The 2026-02 stock count** (taken 2026-03-02) is **accepted**, pending confirmation from SSM (San San Marketing). | The main results use it as recorded. Treating it as missing is kept only as a sensitivity check. |
| 3 | **The 2025-05 stock count** keeps the "missing from the count = 0" rule and is labelled **"possibly partial"**. Open question for SSM. | The main results use it as recorded. The label is in `part0_count_completeness.csv`, column `count_note`. |
| 4 | **Territory.** The counts appear to be Ilocos Sur's and the sales La Union's. **UNVERIFIED.** | The 2-week La Union fallback is reported below. It gives the same answer. |

## The answer in plain language

### After accounting for stockouts, do misses really lean surplus?

Yes, slightly. Stockouts do not explain it, but the lean is smaller than the 6-month figures suggest. In the
figures below, "share over" means over-forecast ÷ (over-forecast + under-forecast). A month forecast exactly
right counts as neither; there is 1 such product-month in the 29-month window.

- **6 months, 2025-09 to 2026-02** (642 product-months):
  - As measured: 361 over-forecast, 281 under-forecast (56.2% over). Surplus ₱3,789,634 per month against
    shortage ₱3,030,238 per month, at selling price, VAT-inclusive.
  - With the 250 possibly stock-limited product-months left out: 231 over, 161 under (58.9% over). Surplus
    ₱2,441,152 per month against shortage ₱1,564,961 per month, same price basis.
- **29 months, 2023-10 to 2026-02** (2,419 product-months):
  - As measured: 1,249 over, 1,169 under, 1 exactly right (51.7% over). Surplus ₱2,924,119 per month against
    shortage ₱2,797,902 per month, at selling price, VAT-inclusive.
  - With the 1,142 possibly stock-limited product-months left out: 672 over, 604 under (52.7% over). Surplus
    ₱1,537,542 per month against shortage ₱1,331,014 per month, same price basis.
- **The lean flips only if every possibly stock-limited month is assumed to be a real shortage.** The data
  argue against that. Over 2025-09 to 2026-02, those months sold 0.92× to 0.97× of their own 12-month average
  pieces, against 0.86× for the other months. They were also over-forecast in 48.5% to 55.3% of cases,
  against 59.4% for the other months. A low count usually followed strong sales. It did not cap them.

**"Possibly stock-limited" is an approximation from monthly counts.** It means the stock count at the start
or end of the month was below one week of the product's average sales. The counts are snapshots, so they
cannot show what happened between them.

### Which fix, how much surplus does it remove, and what does it cost in shortage?

None passes the recorded threshold, so **the recommendation is D: flag products for review and change no
forecast.**

| Candidate | Surplus removed, 6 months (2025-09 to 2026-02), ₱ per month at selling price, VAT-inclusive | Shortage added, same window and basis | Surplus removed, 29 months (2023-10 to 2026-02), ₱ per month at selling price, VAT-inclusive | Shortage added, same window and basis | Products better / worse, 29 months |
|---|---:|---:|---:|---:|---:|
| A. Collapse cap | ₱89,411 (2.4%) | ₱87,105 | ₱25,572 (0.9%) | ₱36,660 | 4 / 9 |
| B. Bias correction, k = 0.25, 3-month bias | ₱103,199 (2.7%) | ₱73,680 | ₱21,646 (0.7%) | ₱42,288 | 29 / 69 |
| C. A + B | ₱116,983 (3.1%) | ₱92,155 | ₱25,466 (0.9%) | ₱56,251 | 29 / 69 |

- **A, B and C miss the threshold.** They pass the original three-part rule in both windows. Over 29 months,
  though, each removes under 1% of surplus pesos and adds more shortage pesos than it removes, so each fails
  the recorded threshold twice over.
- **A's 6-month gain is mostly one product.** SURF POWDER CHERRY BLOSSOM L 288X65G (69668140) accounts for
  ₱381,390 of the ₱536,467 of surplus removed over 2025-09 to 2026-02, at selling price, VAT-inclusive (71%).
- **Stronger bias correction makes it worse.** With k = 0.5 or 1, surplus goes *up* in both windows, because
  the last few months' bias does not predict next month's.
- **E misses as well.** Training without the possibly stock-limited months (E1) removes 1.0% of surplus over
  29 months, on the 1,277 product-months that were not stock-limited, which is short of 5%.

**D, the review flag:**

- It marks 12 to 26 of the 107 products a month over 2025-09 to 2026-02, and 2 to 26 a month over
  2023-10 to 2026-02.
- Flagged product-months carry 18.5% of surplus pesos with 11.1% of sales pesos over the 6 months, and
  12.3% with 9.8% over the 29 months, at selling price, VAT-inclusive.
- They are **not** more often over-forecast: 55.7% against 56.3% (6 months), and 52.7% against 51.5% (29
  months). So the flag means "big miss likely, review it", not "cut the order".

**Territory (decision 4, UNVERIFIED).** The LP (linear-programming order plan) logic check
(`kelvin/lp-logic-check` 65ed2cc, `reports/diagnostics/lp_logic_check_2026-10-03/README.md:216-225`) found
that the stock counts come from the Ilocos Sur workbooks, while the product sales are La Union only. La Union
sales run 57% to 76% (median 62%) of the Ilocos Sur register over 2025-04 to 2026-02. If the counted warehouse
serves both territories:

- 1 week of La Union sales is about 0.6 weeks of the warehouse's own sales.
- The 2-week La Union fallback, about 1.1 to 1.5 weeks of warehouse sales, is the closer like-for-like test.
- It gives the same answer. With possibly stock-limited months left out, 59.3% of misses are over-forecast
  over 2025-09 to 2026-02, with surplus ₱607,667 per month above shortage. Over 2023-10 to 2026-02 the
  figures are 53.8% and ₱84,931 per month, at selling price, VAT-inclusive.

The Ilocos Sur register has no product column, so a per-product correction is not possible.

---

## Terms

| Term | Meaning here |
|---|---|
| Error | Forecast − actual, in pieces. Positive = **over-forecast** (surplus side); negative = **under-forecast** (shortage side). |
| Surplus / shortage pesos | Positive error × price per piece / negative error × price per piece, at selling price, VAT-inclusive, summed over products and divided by the window's months. Price per piece = Σ `net_amount` ÷ Σ pieces over the product's own test months (the forecast-error diagnostic's rule). This is money exposed, not money lost. Surplus + shortage = the total miss in pesos. |
| Share over | Over-forecast ÷ (over-forecast + under-forecast) product-months. A product-month with error exactly 0 is in neither. |
| WAPE | Weighted absolute percentage error = Σ\|error\| ÷ Σ\|actual\|. **Median product WAPE**: worked out per product, then the median across products. **Total WAPE**: pooled over every product-month. |
| Signed bias | Σ error ÷ Σ\|actual\|. Plus = forecasts above sales overall. |
| History bin | The router's model choice by number of months with sales: 3-11 months → MA3 (moving average of the last 3 months), 12-23 → TSB (Teunter–Syntetos–Babai smoothing, a method for patchy demand), 24+ → the average of XGBoost (a gradient-boosted decision-tree model trained across all Tier A products) and MA3 (`analytics/forecasting/router.py:39`). |
| k | Strength of the bias correction in candidate B: the share of the recent bias that is taken off the forecast. |
| Halves | 6 months: 2025-09 to 2025-11 / 2025-12 to 2026-02. 29 months: 2023-10 to 2024-12 / 2025-01 to 2026-02. |
| Possibly stock-limited, high carryover | Approximations from monthly stock counts, defined in Part 0.1. |
| SSM | San San Marketing, the distributor. |

## Data used

| What | Where from | Generated data excluded by |
|---|---|---|
| Tier A list, monthly pieces and pesos, the `forecast_result` copy, product dimension | The forecast-error diagnostic's read-only pull on 2026-10-03, copied unchanged into `inputs/` | Demand read from `Unilever_SKU_Demand_Fact_Real`, the view that keeps `is_demo = false` rows only (`analytics/db/schema.sql:865-866`). `fill_source` can only be set on `is_demo = true` rows (`0038_data_fills.sql:46-57`). |
| Stock counts | `pull_stock_counts.py`, one read-only transaction (BEGIN; SET TRANSACTION READ ONLY; …; ROLLBACK), 2026-10-03 | `inventory_fact` filtered on **both** flags, `is_demo = false AND fill_source IS NULL`. Not read: 24 monthly `synthetic_v2` counts (periods 2021-01 to 2022-12) and 6 `synthetic_v2_gap` counts (periods 2026-04 to 2026-09). |

Real Unilever counts exist for 39 months, periods 2023-01 to 2026-03, one count per month. Each is taken in
the first days of the next month: the period 2026-02 count is dated 2026-03-02. In the Tier A rows there are:

- 0 NaN (not-a-number) quantities;
- 0 duplicate product-months;
- 132 of 132 products with a usable pack size;
- 0 count rows at zero pieces, so a zero only ever comes from a product missing from a count.

These facts are in `*/results.json` under `data_facts`.

**Reproduction (the run stops if any check fails):**

- **6 months.** `forecast_result` matched on 132 of 132 rows. `reports/simulation/synthetic_2026-10/series.csv`
  matched on 642 of 642 product-months, with a largest forecast gap of 0.0000005 pieces.
- **29 months.** Rebuilt with that diagnostic's own `run_followups.run_jobs` (`route()` with no forced bin),
  read from commit `b4f6b77`. That commit replaced `eebd741` when client data was stripped: the backtest code is
  unchanged, but the per-row table is no longer committed. Checked three ways:
  - **Per row:** matched on 2,419 of 2,419 product-months, against the diagnostic's own full table in its
    git-ignored `local/` folder. The largest gap is 0.00005 pieces (that file is rounded to 4 decimals). That
    table exists on this machine only, and the run says so if it is missing.
  - **Per product:** matched on 107 of 107 products (months, WAPE, MA3 and naive WAPE, mean miss, bias),
    against the committed `longwindow_per_product_summary.csv`.
  - **Window totals:** product-months, over / under / exactly right, and surplus and shortage pesos, against
    the committed `window_comparison.csv`.
- **Candidate E's retraining code**, run with nothing excluded, reproduces the baseline exactly (gap 0 pieces).

---

## Part 0: stock-aware check

### 0.1 Rules (approximations from monthly counts)

| Rule | Exact definition |
|---|---|
| Opening count of month M | The count for period M−1, taken in the first days of M |
| Closing count of month M | The count for period M |
| Stock in pieces | cases × pack size + loose pieces (`backend/stock_units.py`, `STOCK_PIECES_EXPR`) |
| Product not in a taken count | 0 on hand, flagged `stock_not_in_count`. Unilever's count never lists zero rows (`backend/stock_status.py`, `COUNT_OMITS_ZERO_STOCK`). A month with no real count at all = "no count" (unknown), never 0. |
| Average sales | Mean monthly pieces over the 12 months **before** M, counted from the first sale, with a month without a row = 0. Needs at least 3 months. 1 week = average × 12 ÷ 52. The month itself is left out, so a stockout month cannot lower its own yardstick. |
| **Possibly stock-limited** | Opening or closing count is 0, or below **1 week** of average sales. Also run at 0.5 and 2 weeks. |
| **High carryover** | Opening count above **6 weeks** of average sales |

Each month uses its own counts, never the latest count. 5 product-months in the 6-month window have fewer than
3 months of history, so they get no label; they stay in view (b) below.

### 0.2 Recount: does "leans surplus" survive?

**6 months, 2025-09 to 2026-02** (642 product-months, 250 possibly stock-limited; ₱ per month at selling
price, VAT-inclusive):

| View | Over / under / exactly right, product-months | Share over | Surplus, ₱ per month | Shortage, ₱ per month | Surplus − shortage, ₱ per month |
|---|---|---:|---:|---:|---:|
| (a) as measured | 361 / 281 / 0 | 56.2% | ₱3,789,634 | ₱3,030,238 | +₱759,396 |
| (b) stock-limited months excluded | 231 / 161 / 0 | 58.9% | ₱2,441,152 | ₱1,564,961 | +₱876,191 |
| (c) stock-limited months relabelled as shortage | 231 / 411 / 0 | 36.0% | ₱2,441,152 | at least ₱3,030,238 | at most −₱589,086 |

**29 months, 2023-10 to 2026-02** (2,419 product-months, 1,142 possibly stock-limited; ₱ per month at selling
price, VAT-inclusive):

| View | Over / under / exactly right, product-months | Share over | Surplus, ₱ per month | Shortage, ₱ per month | Surplus − shortage, ₱ per month |
|---|---|---:|---:|---:|---:|
| (a) as measured | 1,249 / 1,169 / 1 | 51.7% | ₱2,924,119 | ₱2,797,902 | +₱126,217 |
| (b) stock-limited months excluded | 672 / 604 / 1 | 52.7% | ₱1,537,542 | ₱1,331,014 | +₱206,528 |
| (c) stock-limited months relabelled as shortage | 672 / 1,746 / 1 | 27.8% | ₱1,537,542 | at least ₱2,797,902 | at most −₱1,260,360 |

In (c), a relabelled month's surplus is dropped. Its shortage is only known to be at least what was
measured, because sales data does not record unfilled orders, so the true shortfall is unknown.

**Sensitivity** (`part0_recount.csv` has all 9 settings per window). The settings vary the low-stock line
(0.5, 1 or 2 weeks) and treat the 2026-02 or 2025-05 count as missing.

- View (b) stays between 57.9% and 59.3% over in the 6-month window, and between 52.1% and 53.8% in the
  29-month window.
- Surplus stays above shortage in every setting, by at least ₱51,983 per month at selling price,
  VAT-inclusive (29 months, 2-week line, 2025-05 count treated as missing).

**Is the label picking out real stockouts?** Split by which count was low (₱ per month at selling price,
VAT-inclusive):

| Group, 6 months (2025-09 to 2026-02) | Product-months | Over-forecast | Median pieces sold ÷ 12-month average | Surplus, ₱ per month at selling price, VAT-inclusive | Shortage, ₱ per month, same basis |
|---|---:|---:|---:|---:|---:|
| not stock-limited | 387 | 59.4% | 0.86× | ₱2,438,802 | ₱1,539,405 |
| opening count low only | 99 | 48.5% | 0.97× | ₱814,388 | ₱408,091 |
| closing count low only | 75 | 53.3% | 0.96× | ₱207,988 | ₱512,953 |
| both counts low | 76 | 55.3% | 0.92× | ₱326,106 | ₱544,233 |
| no label (fewer than 3 months of history) | 5 | 20.0% | n/a | ₱2,350 | ₱25,556 |

| Group, 29 months (2023-10 to 2026-02) | Product-months | Over-forecast | Median pieces sold ÷ 12-month average | Surplus, ₱ per month at selling price, VAT-inclusive | Shortage, ₱ per month, same basis |
|---|---:|---:|---:|---:|---:|
| not stock-limited | 1,277 | 52.6% | 0.97× | ₱1,537,542 | ₱1,331,014 |
| opening count low only | 402 | 49.0% | 1.00× | ₱560,626 | ₱453,819 |
| closing count low only | 375 | 50.9% | 0.98× | ₱344,052 | ₱412,918 |
| both counts low | 365 | 51.8% | 1.00× | ₱481,899 | ₱600,150 |

If stockouts were hiding demand, the possibly stock-limited months would sell *below* their usual level and
look *more* over-forecast. They do the opposite. The rule also tags 27% to 43% of products each month over
2025-09 to 2026-02, and 16% to 83% over 2023-10 to 2026-02 (`part0_labels_by_month.csv`). SSM orders weekly,
so a count below one week's sales looks like the normal low point between deliveries, not a stockout.

### 0.3 The over-forecast runs (3 or more over-forecast months in a row)

| | 6 months, 2025-09 to 2026-02 | 29 months, 2023-10 to 2026-02 |
|---|---:|---:|
| Products with a run of 3+ over-forecast months | 44 | 87 |
| Product-months inside those runs | 161 | 545 |
| …of which possibly stock-limited | **60 (37.3%)** | **255 (46.8%)** |
| For comparison: share of *all* test product-months that are possibly stock-limited | 38.9% (250 of 642) | 47.2% (1,142 of 2,419) |
| Products with at least one possibly stock-limited run month | 23 | 73 |
| Products whose run months were *all* possibly stock-limited | 7 | 18 |
| Run product-months with high carryover | 36 | 105 |

Run months are possibly stock-limited at the same rate as any other month, so stockouts do not explain the
runs. The 7 products whose run months were all possibly stock-limited over 2025-09 to 2026-02:

- CREAM SILK RO ULTREBORN HFALL 288X22ML (62718193)
- CREAM SILK RO ULTREBORN STRT 288X22ML (62718199)
- SURF POWDER KALAMANSI L 40(6+1)57G (64861486)
- SURF POWDER TAWAS L 40(6+1)57G (64861490)
- CLOSEUP RED HOT NEW 12(11+1)X(2X10G) (68200184)
- SURF POWDER SUN FRESH L 12X1100G (69668150)
- SURF PWDR PURPLE BLOOMS L 40(6+1)65G (64861488)

The 12 products still in a run at 2026-02 have 10 possibly stock-limited months among their 43 run months
(`six_months/part0_overrun_products.csv`).

### 0.4 Does high carryover come before a sales dip (stock pushed to stores)?

"Average" is the product's 12-month average pieces sold before month M.

| Months compared | Group | Product-months | Median pieces sold in M ÷ average | Median pieces sold in M+1 ÷ average | M+1 below average | M+1 below 70% of average |
|---|---|---:|---:|---:|---:|---:|
| 2023-02 to 2026-01, all labelled months | high carryover (opening count > 6 weeks of sales) | 429 | 0.99× | 1.00× | 50.8% | 19.1% |
| 2023-02 to 2026-01 | neither | 1,024 | 0.99× | 0.98× | 52.4% | 16.2% |
| 2023-02 to 2026-01 | possibly stock-limited | 1,126 | 0.99× | 0.98× | 52.3% | 20.7% |
| 2025-09 to 2026-01 | high carryover | 116 | 0.98× | 0.89× | 63.8% | 29.3% |
| 2025-09 to 2026-01 | neither | 210 | 0.84× | 0.80× | 70.5% | 34.3% |
| 2023-10 to 2026-01 | high carryover | 399 | 0.99× | 0.99× | 51.6% | 19.8% |
| 2023-10 to 2026-01 | neither | 866 | 0.99× | 0.97× | 53.6% | 18.5% |

**No.** The month after high carryover sells about the same as, or slightly above, the month after an
ordinary month. There is no sign that stock is pushed out and then dips.

### 0.5 Coverage: where we can and can't tell

| Product-months | 6 months, 2025-09 to 2026-02 | 6 months, 2026-02 count treated as missing | 29 months, 2023-10 to 2026-02 | 29 months, 2025-05 count treated as missing |
|---|---:|---:|---:|---:|
| Usable count on both sides | 642 of 642 | 535 | 2,419 of 2,419 | 2,238 |
| Opening count only / closing count only | 0 / 0 | 107 / 0 | 0 / 0 | 89 / 92 |
| A side rests on "missing from the count = 0" | 52 | 50 | 289 | 238 |
| Possibly stock-limited **only** because a product was missing from the count | 28 | 27 | 165 | 149 |
| No label (fewer than 3 months of history) | 5 | 5 | 0 | 0 |

Under decision 2, the 2026-02 count is accepted, so the first and third columns are the results.

What the counts cannot tell us:

- **A count is a snapshot at the month boundary.** A mid-month stockout refilled before the count can't be
  seen. A low count taken just before a weekly delivery is not a stockout.
- **The size of a real shortage is unknown.** The sales file records what was sold, not what was asked for.
- **Deliveries and stock on order aren't visible.** "PO Qty" (purchase-order quantity) is kept as unparsed
  text (`config/column_maps/ssis_soh.yaml:81-89`).
- **"Missing = 0" is an assumption.** It is the project's rule for Unilever. The 2025-05 count is labelled
  possibly partial (decision 3, table below).
- **The territory is unverified.** The counts and the sales may come from different territories (decision 4).

| Count period (excerpt; all 38 periods 2023-01 to 2026-02 in `*/part0_count_completeness.csv`) | Unilever rows in the count | Tier A products selling that month | …of which missing from the count | Note |
|---|---:|---:|---:|---|
| 2025-04 | 608 | 92 | 13 (14.1%) | |
| **2025-05** | **404** | **96** | **36 (37.5%)** | possibly partial; open question for SSM |
| 2025-06 | 513 | 101 | 13 (12.9%) | |
| 2026-02 | 812 | 132 | 3 (2.3%) | team-flagged outlier; accepted, pending SSM confirmation |

Every other real count has 513 to 812 rows (`data_facts` in `*/results.json`).

---

## Candidate fixes

All candidates are scored against the baseline (the served router) on the same products and the same test
months. Every rule reads only what was known before the month it forecasts.

| Candidate | Rule as implemented |
|---|---|
| **A. Collapse cap** | If the last-3-month average is below 50% of the last-12-month average (history before M, at least 12 months since first sale), forecast = min(model forecast, last-3-month average). |
| **B. Bias correction** | **Recent bias** = Σ(baseline forecast − actual) ÷ Σ\|actual\| over the previous 3 or 6 months; the window must be complete. It is a sales-weighted average: a plain average of monthly % errors blows up on months with tiny or negative sales, such as DOVE SH KERATIN STRT&SILKY 288X13.5ML (64314335), whose 2025-12 net sales were negative. **When it applies:** at least 3 of those months have the same sign as the bias (for the 3-month window, all three). **Correction:** forecast × (1 − k × bias), with k × bias capped at ±30% and the forecast floored at 0; k ∈ {0.25, 0.5, 1.0}. The errors used are the baseline's own forecasts, made each month before. |
| **C. A + best B** | B's best setting, then A's cap. "Best" = the B setting with the largest surplus cut among those that keep median WAPE within +1 point, picked on the same test months (so C is slightly flattered). B with k = 0.25 and a 3-month bias was best in both windows. |
| **D. Review flag only** | Flag a product in month M if it is in a 3+ month over-forecast run ending in M−1, or if the collapse rule trips. No forecast changes. |
| **E. Train without possibly stock-limited months** | **E1:** XGBoost leaves out every training row whose target month is possibly stock-limited, about 47% of rows (6-month window: 977 to 1,204 rows dropped and 1,073 to 1,396 kept per target month). Its inputs still read the real history, and MA3 and TSB are unchanged, so only the 24+ month bin moves. **E2:** E1 plus MA3 and TSB worked out on the history with those months removed. Months are left out, not down-weighted: no weight value is on record. Scored only on months that are not possibly stock-limited (387 of 642; 1,277 of 2,419), against the baseline on the same rows. |

**Decision rules.**

- *Original:* a candidate must cut surplus pesos, raise median product WAPE by no more than 1.0 point, and
  hold in each half (surplus falls *and* median WAPE stays within +1 point in each half).
- *Recorded threshold (decision 1):* over the 29-month window it must also remove at least 5% of surplus
  pesos and add no more shortage pesos than it removes.

### 6 months, 2025-09 to 2026-02 (₱ per month at selling price, VAT-inclusive)

| Candidate | Product-months changed (products) | Median product WAPE (change, points) | Total WAPE | Signed bias | Surplus change, ₱ per month | Shortage change, ₱ per month | Products better / worse | Surplus change 1st / 2nd half, ₱ per month | Meets original rule |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| Baseline, all 642 | — | 29.3% | 36.9% | +8.9% | ₱3,789,634 | ₱3,030,238 | — | — | — |
| A. Collapse cap | 16 (8) | 29.3% (0.00) | 36.9% | +7.3% | −₱89,411 (−2.4%) | +₱87,105 | 3 / 5 | −₱148,155 / −₱30,668 | yes |
| B k=0.25, 3-month | 168 (76) | 30.1% (+0.81) | 36.7% | +6.4% | −₱103,199 (−2.7%) | +₱73,680 | 32 / 44 | −₱146,388 / −₱60,011 | yes |
| B k=0.5, 3-month | 168 (76) | 31.4% (+2.07) | 37.5% | +5.8% | −₱31,832 (−0.8%) | +₱118,754 | 22 / 54 | +₱7,992 / −₱71,655 | no |
| B k=1, 3-month | 168 (76) | 33.0% (+3.71) | 38.7% | +6.2% | +₱167,120 (+4.4%) | +₱105,925 | 18 / 58 | +₱348,858 / −₱14,618 | no |
| B k=0.25, 6-month | 536 (107) | 29.5% (+0.15) | 37.1% | +7.3% | +₱13,106 (+0.3%) | −₱3,532 | 36 / 71 | +₱24,373 / +₱1,839 | no |
| B k=0.5, 6-month | 536 (107) | 30.1% (+0.79) | 38.0% | +6.1% | +₱113,803 (+3.0%) | +₱41,748 | 33 / 74 | +₱150,336 / +₱77,270 | no |
| B k=1, 6-month | 536 (107) | 32.5% (+3.22) | 39.5% | +5.7% | +₱411,375 (+10.9%) | +₱21,920 | 29 / 78 | +₱488,118 / +₱334,632 | no |
| C. A + B k=0.25, 3-month | 169 (76) | 30.1% (+0.81) | 36.7% | +6.1% | −₱116,983 (−3.1%) | +₱92,155 | 31 / 45 | −₱172,837 / −₱61,128 | yes |
| *Baseline, 387 months not possibly stock-limited* | — | 27.8% | 38.1% | +13.2% | ₱2,438,802 | ₱1,539,405 | — | — | — |
| E1. XGBoost rows excluded | 432 (72) | 27.8% (−0.04) | 37.0% | +12.1% | −₱86,465 (−3.5%) | +₱27,751 | 35 / 33 | −₱141,142 / −₱31,788 | no: median WAPE +1.24 points in the 1st half |
| E2. + MA3/TSB on cleaned history | 582 (102) | 28.5% (+0.70) | 38.0% | +13.3% | −₱436 (0.0%) | +₱40,176 | 48 / 48 | −₱36,176 / +₱35,305 | no |

With possibly stock-limited months excluded, A, B (k = 0.25, 3-month) and C cut surplus by ₱64,689, ₱115,063
and ₱128,847 per month over 2025-09 to 2026-02, at selling price, VAT-inclusive.

### 29 months, 2023-10 to 2026-02 (₱ per month at selling price, VAT-inclusive)

| Candidate | Product-months changed (products) | Median product WAPE (change, points) | Total WAPE | Signed bias | Surplus change, ₱ per month | Shortage change, ₱ per month | Products better / worse | Surplus change 1st / 2nd half, ₱ per month | Meets original rule | Meets recorded threshold |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| Baseline, all 2,419 | — | 26.9% | 28.5% | +3.3% | ₱2,924,119 | ₱2,797,902 | — | — | — | — |
| A. Collapse cap | 23 (13) | 26.9% (0.00) | 28.5% | +3.0% | −₱25,572 (−0.9%) | +₱36,660 | 4 / 9 | −₱12,156 / −₱39,946 | yes | no |
| B k=0.25, 3-month | 492 (98) | 27.0% (+0.10) | 28.4% | +2.5% | −₱21,646 (−0.7%) | +₱42,288 | 29 / 69 | −₱23,058 / −₱20,134 | yes | no |
| B k=0.5, 3-month | 492 (98) | 27.9% (+1.09) | 28.8% | +2.1% | +₱20,530 (+0.7%) | +₱74,201 | 19 / 79 | −₱6,723 / +₱49,730 | no | no |
| B k=1, 3-month | 492 (98) | 29.1% (+2.25) | 29.3% | +2.0% | +₱124,696 (+4.3%) | +₱100,050 | 15 / 83 | +₱32,073 / +₱223,935 | no | no |
| B k=0.25, 6-month | 1,904 (96) | 26.9% (+0.04) | 28.7% | +2.7% | +₱27,725 (+0.9%) | +₱19,021 | 21 / 75 | +₱10,178 / +₱46,524 | no | no |
| B k=0.5, 6-month | 1,904 (96) | 27.7% (+0.88) | 29.3% | +2.3% | +₱90,718 (+3.1%) | +₱61,652 | 15 / 81 | +₱39,101 / +₱146,021 | no | no |
| B k=1, 6-month | 1,904 (96) | 29.2% (+2.31) | 30.6% | +1.8% | +₱285,252 (+9.8%) | +₱153,791 | 12 / 84 | +₱134,591 / +₱446,674 | no | no |
| C. A + B k=0.25, 3-month | 493 (98) | 27.0% (+0.10) | 28.4% | +2.5% | −₱25,466 (−0.9%) | +₱56,251 | 29 / 69 | −₱24,922 / −₱26,049 | yes | no |
| *Baseline, 1,277 months not possibly stock-limited* | — | 25.4% | 28.3% | +3.7% | ₱1,537,542 | ₱1,331,014 | — | — | — | — |
| E1. XGBoost rows excluded | 759 (67) | 25.5% (+0.19) | 28.1% | +3.5% | −₱15,157 (−1.0%) | +₱1,961 | 29 / 34 | ₱0 / −₱31,396 | no | no |
| E2. + MA3/TSB on cleaned history | 2,111 (103) | 25.7% (+0.32) | 28.7% | +4.6% | +₱26,576 (+1.7%) | +₱19,813 | 53 / 49 | +₱94,469 / −₱46,166 | no | no |

With possibly stock-limited months excluded, A, B (k = 0.25, 3-month) and C cut surplus by ₱13,400, ₱24,297
and ₱27,153 per month over 2023-10 to 2026-02, at selling price, VAT-inclusive.

E1 leaves the 29-month first half unchanged. The data start in 2023-01, so no product reached 24 months of
sales before 2025-01, and only the 24+ month bin uses XGBoost.

### By history bin

The full table is in `*/candidates_summary.csv`, in the rows whose `scope` is a bin. Pesos per month always
divide by the window's months, so the three bins add up to the overall row. The 24+ month bin only exists
from 2025-01 in the 29-month window. The main points:

- **A, B and C help only in the 24+ month bin.** Over 2025-09 to 2026-02 they cut that bin's surplus by 2.8%,
  3.1% and 3.6% (₱82,236, ₱92,757 and ₱105,981 per month at selling price, VAT-inclusive). In the 3-11 and
  12-23 month bins, B and C raise median WAPE by 1.6 to 2.1 points.
- **E1 passes the original rule inside the 24+ month bin over 2025-09 to 2026-02.**
  - Median WAPE falls 1.05 points, and surplus falls ₱86,465 per month at selling price, VAT-inclusive
    (4.5%), with 35 products better and 33 worse.
  - It fails overall only because the first-half median across all products rose 1.24 points, although no
    product outside that bin changed. A median taken across mixed bins can move like that.
  - Over 2023-10 to 2026-02 the same bin cuts ₱15,157 per month at selling price, VAT-inclusive, averaged over
    all 29 months (2.5% of that bin's surplus), with median WAPE up 0.81 points. It can't be tested in the
    first half.
  - **E1 is the only candidate worth re-testing, and only once a cleaner stockout signal exists** (see 0.2).
- **E2's 12-23 month gain does not hold up.** Over 2025-09 to 2026-02 it cuts ₱34,180 per month at selling
  price, VAT-inclusive, with median WAPE down 2.71 points, but that rests on 16 products and 53 product-months.
  Over 2023-10 to 2026-02 it reverses: surplus up ₱29,669 per month (same basis, averaged over all 29 months)
  and median WAPE up 2.45 points.

### D: review flag only

Shares are of pesos at selling price, VAT-inclusive, in the same month.

| Month | Products flagged (of 107) | By over-run | By collapse | Flagged: over-forecast | Not flagged: over-forecast | Flagged share of surplus ₱ | of shortage ₱ | of sales ₱ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025-09 | 13 | 13 | 1 | 84.6% | 48.9% | 52.5% | 1.8% | 8.4% |
| 2025-10 | 16 | 16 | 4 | 56.2% | 52.7% | 9.9% | 4.2% | 13.5% |
| 2025-11 | 13 | 13 | 4 | 61.5% | 56.4% | 5.6% | 11.7% | 10.7% |
| 2025-12 | 26 | 24 | 4 | 76.9% | 81.5% | 17.2% | 9.4% | 12.4% |
| 2026-01 | 26 | 25 | 2 | 23.1% | 34.6% | 16.1% | 20.8% | 13.1% |
| 2026-02 | 12 | 12 | 4 | 41.7% | 64.2% | 13.7% | 18.1% | 8.1% |
| **2025-09 to 2026-02** | 106 product-months | 103 | 19 | 55.7% | 56.3% | 18.5% | 12.0% | 11.1% |
| **2023-10 to 2026-02** (2 to 26 products a month, median 7) | 283 product-months | 280 | 26 | 52.7% | 51.5% | 12.3% | 9.7% | 9.8% |

A flagged product-month carries more surplus pesos than its share of sales pesos: 1.7× over 2025-09 to
2026-02 and 1.3× over 2023-10 to 2026-02. It is not more often over-forecast, so the flag says "large miss
likely, check it before ordering", not which way to adjust. Every month is in
`*/candidate_D_review_flag.csv`.

---

## Limits

- **The possibly stock-limited label is a loose approximation from monthly counts.** It tags 39% (2025-09 to
  2026-02) to 47% (2023-10 to 2026-02) of product-months. The evidence in 0.2 suggests it mostly catches normal low points between weekly
  deliveries, which also limits what E can show.
- **The counts and the sales may not be from the same territory** (decision 4, UNVERIFIED). If so, weeks of
  cover here are overstated by about 1.3× to 1.75× (from La Union's 57% to 76% share of the Ilocos Sur register,
  2025-04 to 2026-02). Possibly stock-limited would then be under-counted and
  high carryover over-counted. The 2-week fallback covers the first. The "no dip after high carryover"
  finding compares groups, so the scale does not affect it.
- **Both test windows share their last 6 months.** The 29-month window re-works the bin each month, and the
  6-month window holds the 2026-03 bin fixed, as each source window does.
- **B's best setting and C were picked on the same test months they were scored on.**
- **The pesos are at selling price.** They show what is exposed, not what is lost: storage and procurement
  costs are still owed by SSM.
- **Scope:** only the 107 commonly scored Tier A products as of 2026-02. The 12 products scored on one month
  and the 13 unscored products are out.
- **Not run:** down-weighting instead of excluding in E (no weight value is on record), and a stockout signal
  from deliveries ("PO Qty"), which is not parsed.

## Quality check

`quality_check.py` re-checks this report read-only. It covers six areas:

- **Numbers.** Every number here is traced to a committed file, a stated formula or a rule constant, and the
  main tables are checked cell by cell.
- **Arithmetic.** The surplus, shortage, over/under, per-product, bin, half and flag totals all add up.
- **Independent recompute.** The 29-month share over-forecast and candidate A's surplus removed and shortage
  added are recomputed with fresh code.
- **Data rules.** Generated rows are excluded, the counts are real, and each month uses its own opening count.
- **Wording.** Every number carries its period, unit and price basis, and product names come before SKU codes.
- **Repo hygiene.** No client data is committed: no raw pulls, and no per-product sales or prices.

A self-test plants deliberate errors in a copy of this README and confirms each one is caught. Results and
evidence are in `quality_check/checks.csv`, every README number with its source is in
`quality_check/number_check.csv`, and what the check changed is in `quality_check/fixes.csv`.

## Files

| File | What it holds |
|---|---|
| `pull_stock_counts.py` | The read-only stock-count pull. |
| `inputs/` | Everything pulled. **Not committed**, because it is client data (`.gitignore` beside this file, which also ignores `local/`). The raw count fields (cases, loose pieces, stock value) stay there; outputs carry weeks of cover only. |
| `run_experiment.py` | Offline. Rebuilds and checks the baseline, labels stock, and scores A to E. `--window long_window` runs the 29-month window. |
| `quality_check.py`, `quality_check/` | The final quality check (number check, arithmetic, independent recompute, data rules, wording, repo hygiene) and its results. |
| `six_months/`, `long_window/` | One set of the files below per window. |
| `local/<window>/per_product_month.csv` | **Not committed** (git-ignored): per-product monthly sales and prices are client data (Yuan, 2026-10-03). Per product-month: actual, baseline, price, weeks of cover, possibly stock-limited and reason, high carryover, collapse ratio, recent bias, over-run, D flag, and every candidate's forecast. `run_experiment.py` recreates it. |
| `part0_*.csv` | Part 0 tables: `recount`, `coverage`, `stock_limited_by_side`, `overrun_products`, `carryover_next_month`, `labels_by_month`, `count_completeness`. |
| `candidates_summary.csv` | Every candidate × (all, 3 bins): WAPE (median and total), bias, surplus and shortage per month (also with possibly stock-limited months excluded), better/worse, each half, and the decision-rule and threshold columns. |
| `candidate_D_review_flag.csv`, `per_product_candidates.csv` | D per month; WAPE per product per candidate. |
| `results.json` | Recorded decisions, data facts, reproduction checks, label counts, run counts, training rows dropped in E, and product-months changed per candidate. |

Rerun from the worktree root, in this order:

```
../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/surplus_bias_experiment_2026-10-03/run_experiment.py
../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/surplus_bias_experiment_2026-10-03/run_experiment.py --window long_window
../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/surplus_bias_experiment_2026-10-03/quality_check.py
```

The 29-month run reads `run_followups.py`, `run_analysis.py`, `longwindow_per_product_summary.csv` and
`window_comparison.csv` from commit `b4f6b77` (`git show`), so later edits in that branch's folder cannot change
it. It stops if the rebuilt forecasts differ from those files, or from the diagnostic's git-ignored per-row
table when that table is present.
