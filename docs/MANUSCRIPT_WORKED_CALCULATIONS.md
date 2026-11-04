# Worked calculations: one order, end to end (cycle 2026-03, LP run 6)

> **Hard rule 9.** This file holds per-product sales and pesos for two products. It is committed under the rule's exception
> of 2026-10-23 (per-product figures the manuscript publishes): Tables 4.2.22 to 4.2.24 of the manuscript trace to it, and product
> 69668149 is also published with its arithmetic (`reports/RECEIPTS_WORKED_EXAMPLE_2026-10-23.md`). SSM's buying price from Unilever
> is left out on purpose: the chapter does not publish it and no step below uses it.

Written for: the manuscript (Chapter 4) and the panel. It traces the plan from raw sales to the planned order, first for one product
that is ordered, then for one that is not, and then for the whole plan.

**Notation.** The symbols are the ones in `analytics/optimization/lp.py` (module docstring): F_i forecast, σ demand variability, Z
service factor, SS_i safety stock, w_i weekly rate, R review days, L lead days, T_i target stock, S_i stock on hand at the opening
count, need_i, Q_i order before rounding, plan_q_i order after case-pack rounding. Table 4.1.9 itself is not in the repository,
so whether its symbols match these exactly is **UNVERIFIED**. Check it against the manuscript before quoting.

**How every value was obtained.** All values were read on 2026-10-31 inside `BEGIN; SET TRANSACTION READ ONLY; … ROLLBACK`
against the live database. The recomputation calls the project's own functions (`scripts/run_lp._sigma_d_for_product`,
`safety_stock_for`, `analytics/optimization/lp.target_stock`, `net_need`, `_packs`, `analytics/classification/fsn.classify_fsn`,
`analytics/forecasting/calendar.calendar_factor`) on rows up to 2026-02. 2026-02 is the latest real demand month: the
demand table's maximum `calendar_month` is 2026-02, over 24,906 rows. In the tables below, **Stored** means a database column
was read, and **Recomputed** means the value was rebuilt from rows. Where both columns are given, they agree to the stored
precision.

## A. Product 62687212: CREAM SILK ULT REBORN STRT 24(11+1)13ML (`product_key` 39)

Why this product: it is CRITICAL in the 2026-03 plan. It has 25 months with sales, so it takes the long-history route (the XGBoost
and MA3 average). Its case pack is 24.

### A1. Raw monthly sales (`unilever_sku_demand_fact_real`, 25 rows)

| Month | Pieces | Net ₱ | | Month | Pieces | Net ₱ |
|---|---:|---:|---|---|---:|---:|
| 2024-01 | 4,681 | 310,633.26 | | 2025-02 | 5,381 | 354,491.14 |
| 2024-02 | 40 | 2,715.26 | | 2025-03 | 4,982 | 329,424.44 |
| 2024-03 | *no row* | | | 2025-04 | 5,753 | 379,809.99 |
| 2024-04 | 5,355 | 359,321.92 | | 2025-05 | 4,583 | 295,215.66 |
| 2024-05 | 21 | 1,375.59 | | 2025-06 | 7,714 | 507,583.22 |
| 2024-06 | 4,752 | 341,123.02 | | 2025-07 | 3,909 | 256,675.01 |
| 2024-07 | 159 | 3,676.58 | | 2025-08 | 4,954 | 326,395.98 |
| 2024-08 | 1,998 | 127,425.11 | | 2025-09 | 5,870 | 389,181.22 |
| 2024-09 | 1,571 | 104,016.25 | | 2025-10 | 5,523 | 363,600.17 |
| 2024-10 | 2,798 | 183,393.52 | | 2025-11 | 5,309 | 347,495.07 |
| 2024-11 | 4,938 | 323,081.92 | | 2025-12 | 2,434 | 159,573.58 |
| 2024-12 | 2,408 | 158,261.38 | | 2026-01 | 7,969 | 522,868.15 |
| 2025-01 | 6,965 | 459,404.95 | | 2026-02 | 5,514 | 363,458.66 |

First sale 2024-01. 2024-03 has no row; for Unilever that is a real zero-sale month (CLAUDE.md, "Why data is missing"), and it
enters σ as 0. No month has a blank quantity.

### A2. ABC class (method `t12m_new`, period 2026-02; window 2025-03..2026-02)

Revenue_i = Σ max(0, net ₱ in month m) over the 12 months. Products are ranked by Revenue_i, and a product is Class A while the
cumulative share is at most 0.80.

| Quantity | Value | Stored / Recomputed |
|---|---|---|
| Revenue_i | ₱4,241,281.15 | Recomputed (SQL over the 12 rows above) |
| Σ Revenue, all ranked Unilever products | ₱392,655,664.45 over 1,091 products | Recomputed. The same total is reported in `reports/AUDIT_2026-10-23.md` Part 1c |
| Share = 4,241,281.15 / 392,655,664.45 | 0.010802 | Stored `abc_classification.revenue_share` 0.0108 |
| Rank | 19 of 1,091 | Recomputed |
| Cumulative share through rank 19 | 0.374775 | Stored `cumulative_share` 0.3748 |
| Class | **A** (0.3748 ≤ 0.80; not added by the new-product rule, `added_as_new` false) | Stored `tier` A, run `t12m_new_20261005` |

### A3. FSN (window: the 12 observed months to 2026-02)

| Quantity | Value | Stored / Recomputed |
|---|---|---|
| Months with sales | 12 of 12 | Recomputed (`classify_fsn`) |
| Sold in the last 6 months? | yes, so not N | Recomputed |
| ADI (average demand interval) | 1.000 | Recomputed |
| Rule: F when ADI < 1.32 and ≥ 3 months with sales | 1.000 < 1.32, 12 ≥ 3 | `analytics/params.py` `SBC_ADI_CUT`, `FSN_MIN_FAST_SALES_MONTHS` |
| Class | **F (fast-moving)** | Recomputed. FSN is computed per request (`GET /fsn`); no table stores it |

### A4. Which model, and why (`analytics/forecasting/router.py`)

The route depends on the number of months with sales in the history known at forecast time: 3-11 months go to MA3 (short),
12-23 to TSB (medium), and 24 or more to the average of a global XGBoost model and MA3 (long).

| Quantity | Value | Stored / Recomputed |
|---|---|---|
| Months with sales to 2026-02 | 25 (26-month span; 2024-03 had none) | Stored `model_params.sales_months` 25, `months_span` 26. Recomputed 25 |
| Bin | **long** (25 ≥ 24), so the method is `xgb_ma3_avg` | Stored `model_params.bin`, `method` |
| MA3 = (2,434 + 7,969 + 5,514) / 3 | 5,305.667 | Stored `components.ma3` 5,305.667. Recomputed 5,305.667 |
| XGBoost one-step value | 5,574.381 | **Stored only** (`components.xgb`). It comes from a global model trained on 4,312 rows. Refitting it is a forecast run and was not done |
| Average = (5,305.667 + 5,574.381) / 2 | 5,440.024 | Stored `value_before_calendar` 5,440.024 |
| Calendar factor for March | 1.076244 | Recomputed (`calendar_factor`): March over the mean of the 3 months before, company pieces. 2025: 2,980,860 / 2,550,174.0 = 1.168885. 2024: 3,588,775 / 3,158,238.7 = 1.136322. Geometric mean 1.152489, shrunk by 0.5 toward 1. Stored `calendar_factor` 1.0762 (rounded to 4 places) |
| **F_i** = 5,440.024 × 1.076244 | **5,854.79 pieces** | Stored `forecast_result.forecast_value` 5,854.79 |
| MASE (holdout) | 0.429, which is below 1, so the product passes the LP's gate | Stored `forecast_result.mase` |

### A5. Safety stock and target stock

σ_monthly is the standard deviation (n−1) of the monthly pieces from 2024-01 to 2026-02, with 2024-03 entered as 0. σ_d is that
figure scaled to one business day, assuming independent days. The assumption is disclosed in `lp_run.model.safety_stock_assumption`
and still awaits the adviser's ruling.

| Formula | Value | Stored / Recomputed |
|---|---|---|
| σ_monthly (26 months) | 2,346.221 | Recomputed |
| Average business days per month over those 26 months | 21.7308 | Recomputed (`business_days_in_month`) |
| σ_d = σ_monthly / √21.7308 | 503.3052 | Recomputed |
| SS_i = Z × σ_d × √(R + L) = 1.28 × 503.3052 × √8 | **1,822.16** | Stored `lp_recommendation.ss_i` 1,822.16. Recomputed 1,822.1595 |
| w_i = F_i / (365.25 / 12 / 7) = 5,854.79 / 4.348214 | 1,346.4815 per week | Recomputed |
| T_i = w_i × (R + L) / 5 + SS_i = 1,346.4815 × 8/5 + 1,822.1595 | **3,976.53** | Stored `lp_recommendation.rop_i` 3,976.53 (the column is named `rop_i` but holds T_i). Recomputed 3,976.5298 |

R = 5 and L = 3 business days come from `lp_run.inputs` (`review_days`, `lead_days`). SSM stated them at a meeting; they are not
confirmed in writing (KNOWN_ISSUES.md L4). Z = 1.28 is the 90% service level.

### A6. Stock, need, urgency

| Formula | Value | Stored / Recomputed |
|---|---|---|
| S_i: opening count `_period` 2026-02, taken 2026-03-02 = 4 cases × 24 + 12 loose | **108 pieces** | Stored `planning_mart.opening_stock_pieces` 108. Recomputed from `inventory_fact_real` |
| need_i = max(0, F_i + T_i − S_i) = 5,854.79 + 3,976.53 − 108 | **9,723.32** | Stored `q_i_before_pack_rounding` 9,723.32. Recomputed 9,723.3198 |
| Urgency: S_i < SS_i (108 < 1,822.16) | **CRITICAL** | Stored `planning_mart.urgency` CRITICAL (`backend/stock_status.py`) |

The opening count is the 2 March 2026 count. It is accepted for planning pending SSM's confirmation (`lp_run.inputs.notes`).

### A7. LP decision

The model bounds the order: 0 ≤ Q_i ≤ need_i. Stage 1 fills the need in three layers (this month's demand, then safety stock,
then the rest of the target), as far as the allocation and the warehouse allow. The cost weights (w1 0.45, w2 0.35, w3 0.20) only
decide who gives up a layer when a ceiling binds.

| Check | Value | Source |
|---|---|---|
| Allocation A_unilever = 103% × 2025 pieces / 12 | 1,264,829.1 | Stored `lp_run.model.allocation.monthly_ceiling` |
| Σ Q_i (all 109, before rounding) | 431,443.01, which is below A: allocation slack 833,386.09 | Recomputed (SQL sum of `q_i_before_pack_rounding`) |
| Warehouse W | 3,816,842 | Stored `lp_run.inputs.warehouse_capacity` |
| Σ(S_i + plan_q_i) | 2,232,506 + 435,988 = 2,668,494, which is below W: slack 1,148,348 | Recomputed |
| Result | Neither ceiling binds, so Q_i = need_i = **9,723.32** | Stored `q_i_before_pack_rounding` |

### A8. Case-pack rounding (`analytics/optimization/lp.round_to_case_packs`)

| Formula | Value | Stored / Recomputed |
|---|---|---|
| Q_i / pack = 9,723.32 / 24 | 405.1383 cases | Recomputed |
| Packs below and above | 9,720 and 9,744 | Recomputed (`_packs`) |
| Rule: round up unless that breaks the warehouse or the allocation (both have slack, above) | up | `lp.py` docstring of `round_to_case_packs` |
| **plan_q_i** = 406 × 24 | **9,744 pieces** (20.68 above need, less than one pack) | Stored `lp_recommendation.q_i` 9,744 and `planning_mart.order_pieces` 9,744 |

## B. Product 69668149: SURF POWDER SUN FRESH L 288X65G (`product_key` 853), ordered 0

This is the largest of the 36 plan rows that order 0 while their forecast is positive.

| Step | Value | Stored / Recomputed |
|---|---|---|
| ABC | Revenue ₱5,617,048.01, share 0.014305, rank 14 of 1,091, cumulative 0.316453, Class **A** | Stored 0.0143 / 0.3165, tier A. Recomputed |
| FSN | 12 of 12 months with sales, ADI 1.000, **F** | Recomputed |
| Route | 32 months with sales: **long** (`xgb_ma3_avg`) | Stored `sales_months` 32 |
| MA3 = (39,519 + 118,930 + 62,753) / 3 | 73,734.000 | Stored and recomputed |
| XGBoost | 90,147.746 | Stored only |
| Average, then × 1.076244 | 81,940.873, then **F_i = 88,188.39** | Stored |
| σ_monthly (32 months, 2023-07..2026-02, no zero months) | 25,045.416. Average business days 21.7188, σ_d 5,374.1630 | Recomputed |
| SS_i = 1.28 × 5,374.1630 × √8 | **19,456.55** | Stored `ss_i`. Recomputed 19,456.5485 |
| T_i = (88,188.39 / 4.348214) × 8/5 + SS_i | **51,906.98** | Stored `rop_i`. Recomputed 51,906.9787 |
| S_i: count of 2026-03-02 = 817 cases × 288 + 191 | **235,487 pieces** | Stored `opening_stock_pieces`. Same figure as the receipts worked example |
| F_i + T_i | 140,095.37 | Recomputed |
| need_i = max(0, 140,095.37 − 235,487) | max(0, −95,391.63) = **0** | Stored `q_i_before_pack_rounding` 0.00 |
| plan_q_i | **0** (rounding leaves an order of 0 unchanged) | Stored `q_i` 0 |
| Urgency | S_i ≥ T_i, so PLANNED (`stock_status` IN STOCK) | Stored |

**Why it got nothing.** The binding reason is **stock at or above the target**, not a cost term. Stock on hand at the opening
count (235,487) exceeds this month's forecast plus the target stock (140,095.37) by 95,391.63 pieces. need_i is therefore 0, and
the model's own bound Q_i ≤ need_i forces the order to 0. The cost weights never act on this row. At the forecast's weekly rate
(20,281.52 pieces), the opening stock is 11.6 weeks of sales against a target of 2.6 weeks.

**Is that true of every zero row?** Yes. Of all 36 zero-order rows in the plan, 36 have S_i ≥ F_i + T_i (need 0) and 0 have a
positive need that the LP cut. With neither ceiling binding (A7), no row in this cycle lost any part of its need to a cost term.

**What this rests on.** The 2 March 2026 count. For this product it is 235,487 pieces, against 15,944 at the 3 February count
and 110,431 (383 × 288 + 127) at the 6 April count. The count as a whole is flagged as about twice its neighbours and accepted for
planning pending SSM (STATE.md, Blocked). If that count is overstated for this product, the zero order is overstated too. Nothing
in the data can correct it (KNOWN_ISSUES.md L3: no delivery records).

## C. The whole plan: three urgency subtotals

Query: `mart.planning_mart` joined to `lp_recommendation` on `recommendation_key`, cycle 2026-03-01, `lp_run_key` 6, grouped by
`urgency` with a total (4 result rows). Every column below is a sum of stored values.

| Urgency | Rule | Rows | Ordering | Σ F_i | Σ SS_i | Σ T_i | Σ S_i | Σ need_i | Σ Q_i (before rounding) | **Σ plan_q_i** |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CRITICAL | S_i < SS_i | 18 | 18 | 49,489.42 | 53,537.52 | 71,747.97 | 3,189 | 118,048.39 | 118,048.31 | **118,644** |
| URGENT | SS_i ≤ S_i < T_i | 5 | 5 | 62,997.03 | 18,649.23 | 41,830.05 | 37,612 | 67,215.08 | 67,215.08 | **67,276** |
| PLANNED | S_i ≥ T_i | 86 | 50 | 1,105,147.30 | 485,424.95 | 892,082.89 | 2,191,705 | 246,179.97 | 246,179.62 | **250,068** |
| **Total** | | **109** | **73** | 1,217,633.75 | 557,611.70 | 1,005,660.91 | 2,232,506 | 431,443.44 | 431,443.01 | **435,988** |

118,644 + 67,276 + 250,068 = **435,988**: the plan total in STATE.md (`plan:` rows=109 pieces=435988). Σ SS_i 557,611.70 and
Σ T_i 1,005,660.91 match the totals in `reports/AUDIT_2026-10-23.md` Part 1b. Σ need_i minus Σ Q_i is 0.43 over 109 rows, and the
largest gap on one row is 0.34. That gap comes from the 2-decimal storage of F_i, T_i and Q_i, not from the LP cutting anything.
Rounding added 4,544.99 pieces (435,988 − 431,443.01). No row was rounded down, and every positive plan_q_i is a whole number of
its packs (0 rows fail `plan_q_i mod pack = 0`).

A PLANNED row can still order (50 of 86 do): T_i only sets the label. The order covers the month's forecast as well, so a row at
or above its target still orders when S_i < F_i + T_i.

## What this proves and what it does not

It proves that the stored plan is reproduced from the stored and raw inputs by the documented formulas, for both products and for
the portfolio total. It does **not** prove that Z = 1.28, R = 5, L = 3, the 103% allocation, the warehouse figure or the two costs
are right for SSM (KNOWN_ISSUES.md L4). It does not prove that the XGBoost component is reproducible: it is read as stored. It
does not prove that the daily scaling of σ is valid (that awaits the adviser's ruling).

## Commands and row counts (2026-10-31)

| Command (scratchpad, read-only) | Result rows |
|---|---|
| `trace.py 39`: product, demand extent, raw sales, ABC stored and recomputed, FSN, forecast, LP row, mart row, σ/SS/T/need, stock rows | 25 sales rows, 1 ABC row, 1 forecast row, 1 LP row, 1 mart row, 3 count rows |
| `trace.py 853`: the same | 32 sales rows, 1, 1, 1, 1, 3 |
| `portfolio.py`: calendar factor, urgency rollup, ceilings, zero-order rows | 38 monthly company totals, 4 rollup rows, 36 zero-order rows |
