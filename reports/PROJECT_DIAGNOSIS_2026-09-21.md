# Project diagnosis — forecast-router UI alignment and follow-up

**For:** Kelvin · **Date:** 2026-09-21 (updated after the follow-up work the same day)
**Basis:** `kelvin-etl` at `99df2e7`, fast-forwarded into `UIFixes_Audrey`, plus uncommitted work: Yuan's "UI Tasks — Forecast Router Alignment" (sections A–E) and the follow-up list from the first version of this note. Nothing is on a remote branch yet; the branch name will follow.

## TL;DR — what needs you

1. **Rerun the LP. It's now safe to rerun, but it needs your inputs.** `scripts/run_lp.py` has a `--dry-run`, no longer undoes accepted or rejected rows, and has a `--protection-days` option. The checklist and today's dry-run numbers are in §2.
2. **Decide the safety stock's protection period.** Safety stock covers **1 business day** of demand variability. The dashboard headline, "LP holds 71% less than the 3-week rule", depends almost entirely on that choice (§1.2).
3. **SKU `64314335` has a structural break and a negative-quantity month.** That explains why TSB serves 3.6× the MA3 benchmark. There are two suggestions for the forecasting pipeline (§1.3).
4. **Confirm the reliability gate.** The dashboard now flags a forecast as unreliable at MASE ≥ 1: 46 of 119 evaluated. The old MAPE ≥ 20% rule flagged 100 of 132 (§1.4).
5. **The `xgboost==3.4.1` pin needs Python 3.12 or newer**, but the README said 3.11+ (§1.5).
6. **Six modelling decisions for you and Yuan**, set out with their options in §5.

---

## 1. Findings that need you

### 1.1 The LP run predates the forecasts — high

- `lp_recommendation` for the 2026-03 cycle was written 2026-08-23 08:43 → 2026-08-24 07:12 UTC: 250 pending rows and 1 accepted.
- `forecast_result` was rewritten 2026-09-21 10:08 UTC by the per-bin router.
- **Impact:**
  - Reorder Recs' `q_i` and `rop_i` (ROP = Ŷ + SS) still come from the old MA3 forecasts, while the forecast page shows the new served models.
  - The dashboard's policy comparison joins the old run's `ss_i` with the new `forecast_value`.
  - `ss_i` = Z·σ_d comes from demand history, so it doesn't depend on the model. ROP and Q do.
- **Rerun checklist:** §2.

### 1.2 Safety stock covers one business day — decision needed

`run_lp.py` computes `σ_daily = σ_monthly / √(≈21.7 business days)` and `SS = 1.28 × σ_daily`. There's no review period or lead time, so the buffer protects against **one business day** of demand variability. The blanket rule holds three weeks of demand, so the comparison favours the LP almost by construction.

| Protection period (business days) | LP safety stock vs the 3-week rule |
|---|---|
| 1 (today) | 71% less |
| 5 (weekly review, as the analytical mapping specifies) | 36% less |
| 10 (weekly review + 1-week lead time) | 9% less |
| ≈21.7 (monthly review) | 34% **more** |

- **Lead time:** `product_dimension.lead_time_days` is empty for all 17,406 products, so there's no data-backed lead time.
- **What the code does now:**
  - `run_lp.py` takes `--protection-days` (default 1, so earlier behaviour is unchanged): `SS = Z · σ_d · √protection_days`.
  - The dashboard's policy card states the assumption beside the number.

### 1.3 SKU `64314335`: a break, and a negative month

Monthly units, 2024-04 → 2025-11, sat steadily at 30,000–60,000. Then:

| 2025-12 | 2026-01 | 2026-02 |
|---|---|---|
| **−124** | 1,693 | 15,656 |

- **MA3 (5,742)** averages the collapse, negative month included.
- **TSB (20,714)** still leans on the long-run level.
- **Naive (15,656)** repeats the last month.
- **Holdout:** served WAPE 1.1623 vs MA3's 0.8648; MASE 1.47.
- **No guard fires.** "Reverting toward a level from before a break" isn't caught by the above-historical-max or below-zero checks.

**Suggestions:**
- (a) Negative monthly quantities (net returns larger than sales) go straight into every model. Clip them at 0, or flag them upstream.
- (b) Add a recency / structural-break guard. For example, if the last 3 months are far below the prior 12-month median, serve MA3 or flag the SKU.

### 1.4 The reliability gate is now MASE — please confirm

- **Change:** `forecast.unreliable_count` counts `mase >= 1` (`MASE_UNRELIABLE_GATE = 1.0`). New field `forecast.evaluated_count` counts the rows that have a MASE.
- **Live result:** 46 unreliable of 119 evaluated, out of 132.
- **Why MASE ≥ 1:** it's the LP's own gate (`run_lp.py MASE_GATE`). The old MAPE ≥ 20% rule flagged 100 of 132 whatever the model, so it told users nothing.
- **Unchanged:** the portfolio card still gates on `mape < 20`, via the renamed constant `MAPE_PORTFOLIO_GATE` (19 gated SKUs).
- **Now in the UI:**
  - Dashboard card: "Beat naive (MASE < 1): 73 / 119".
  - Forecast page: each SKU's MASE with "beats / no better than a naive forecast".

### 1.5 The xgboost pin vs Python

- `xgboost` 3.3.0 dropped Python 3.11, and `requirements.txt` pins 3.4.1.
- On the machine this work was done on (Python 3.11.9) the pin can't install, so `xgboost==3.2.0` is installed instead. All 49 forecasting tests pass on it.
- **Docs updated:**
  - README and RUNNING now say Python 3.12+, with 3.2.0 as the 3.11 fallback.
  - `requirements.txt` has a comment on the pin; the pin itself is unchanged.
- **Your call:** keep the 3.12 requirement, or allow a range. A different xgboost version can shift the long-bin forecasts slightly.

### 1.6 Bad-order data

- **Coverage:** `salesreturn_fact_real` is Del Monte only.
  - Typed returns exist for **Mar, Apr, Jun, Aug, Sep and Dec 2025**.
  - **May, Jul, Oct and Nov are missing entirely**: no BO and no GS rows.
  - Before 2025, `return_type` is NULL, so bad orders can't be separated from good-stock returns.
- **Other gaps:**
  - None of the 151 BO rows has a `return_date`.
  - `bo_units` is never filled.
  - Purchases (the rate's denominator) are missing for Sep 2025.
- **API vs contract:** `API_CONTRACTS.md` says `/bo-monitoring` returns no rate. The router does return a value-based one (BO net amount ÷ purchase net amount), which schema.sql documents. It now divides only over months that have both: **0.11%** over 5 months, where the old figure was 0.08%.
- **Asks:**
  - Are there Unilever returns to load?
  - Can the four missing Del Monte months be recovered?

### 1.7 Del Monte category trends have too little data

Del Monte's 2025 sell-out covers only 6 months (the same gaps as returns). Its categories restart at the Jan 2025 regrouping, so no category has the 12 months a trend projection needs yet. The Category Trends page says so rather than fitting 6 points.

---

## 2. LP rerun checklist

1. Supply the four inputs no data source has: supplier ceiling per principal, warehouse capacity, storage cost per unit, and fallback purchase cost per unit (`unit_price` is empty).
2. Dry run first. It uses a read-only session, so nothing can be written:
   ```
   python scripts/run_lp.py --dry-run \
     --supplier-ceiling unilever=<units> --supplier-ceiling delmonte=<units> \
     --warehouse-capacity <units> --storage-cost-per-unit <₱> \
     --default-procurement-cost-per-unit <₱> [--protection-days <days>]
   ```
3. If it looks right, run the same command without `--dry-run`.

**Today's dry run** (placeholder inputs, so ignore Q_i; SS and ROP don't depend on the inputs):

| | |
|---|---|
| SKUs passing the gate (Tier A, status ok, MASE < 1) | 73. All 73 would be refreshed. |
| Pending 2026-03 rows left unchanged (products outside the pool) | 177. Delete or expire them? Your call. |
| Accepted row (SKU `20292811`) | Not in the pool, so untouched. Reruns now never change decided rows. |
| Total SS in 2026-03 | 171,665 units at 1 day; 383,854 at 5 |
| Older cycles still pending | 33 cycles, 179 rows, 2023-05 → 2026-02. Reorder Recs lists them by date range. |

**What changed in `run_lp.py`:**
- `--dry-run`.
- `UPSERT_QUERY` has `WHERE LP_Recommendation.status = 'pending'`, so decided rows are left alone.
- `--protection-days`.
- The summary reports refreshed rows, decided rows kept, stale pending rows, older pending cycles and total SS.
- Tests: `tests/optimization/test_run_lp_script.py`.

---

## 3. Analytical mapping coverage — now

| # | Question (technique) | Status | Where |
|---|---|---|---|
| D1 | Brands and categories driving demand (brand / category ABC) | Yes | ABC page "What drives revenue" card, `GET /pareto`. Unilever by brand or category; Del Monte by category (it has no brand). Same revenue measure and 80/95% cutoffs as the SKU ABC. |
| D2 | SKUs holding the value (SKU ABC) | Yes | ABC page. Note: it ranks by **sales** value, not inventory value as the mapping words it. |
| D3 | Fast / slow / non-moving (FSN) | Yes | ABC page FSN column, filter and ABC × FSN matrix, `GET /fsn`. Rules below. |
| D4 | Trend and variability (STL) | Yes | Diagnostics panel Seasonality tile, `GET /decomposition` (STL, period 12, robust; needs 24 months). CV and Mann-Kendall tiles as before. |
| D5 | BO loss rate by principal and period (BO monitoring) | Yes, within the data limits | New **Bad Orders** page, `GET /bo-monitoring` (§1.6). |
| P1 | Category trajectories over the next year (category trend) | Yes for Unilever; Del Monte not enough data | New **Category Trends** page, `GET /category-trends` (§1.7). |
| P2 | Next-month demand per Category A SKU (time-series model) | Yes | SKU Forecast page, per-bin router. |
| P3 | Accuracy on held-out months (error metrics) | Yes | Per-SKU WAPE and MASE, dashboard MASE count, portfolio MAPE. |
| R1 | Buffer stock per SKU (safety stock) | Yes, with a caveat | `ss_i`; protection period (§1.2). |
| R2 | Target stock at the weekly review (order-up-to S) | Partial | ROP covers a **month**; Q ≥ ROP doesn't net stock on hand (§5). |
| R3 | Allocation within a fixed allocation (LP) | Partial | The ceiling is a CLI input per run; no fixed ordering cost (§5). |
| R4 | Per-SKU policy vs the 3-week rule (policy comparison) | Partial | Dashboard headline in units and percent with the assumption; per-SKU `GET /policy-comparison`. Pesos wait for a cost per piece; stockout exposure waits for §1.2. |

**FSN rules** (`analytics/classification/fsn.py`), over the last 12 months that have data:

| Class | Rule |
|---|---|
| Non-moving | No sale in the last 6 months with data (the pipeline's dead-SKU rule) |
| Fast | ADI ≤ 1.32 (the Syntetos–Boylan cutoff) and at least 3 months of sales |
| Slow | Everything else |

Months with no data at all are left out, so a missing Del Monte file doesn't count as zero sales.

**North-star verdict: mostly answered.** Every descriptive and predictive question now has a screen. What's left is the prescriptive payoff:
- working capital in **pesos** (needs a cost per piece);
- the **fixed annual allocation** (needs SSM's figures and §5 decision 4);
- a settled **protection period** (§1.2) before the "less safety stock" headline and stockout exposure can be stated firmly.

---

## 4. What changed today (for your code)

### 4.1 API

| Endpoint | Change |
|---|---|
| `GET /forecast/{sku}` | Adds `status` and `mase`. `principal` is the product's own; it was hard-coded `"unilever"`. |
| `GET /segment` | `traits` adds `adi`, `trend_pvalue` and `trend_slope` (migration 0022; `.get()` so older rows read as null). |
| `GET /dashboard` | Adds `latest_data_period` and `latest_data_period_by_principal`; `forecast.evaluated_count`; `policy_comparison.lp_vs_rule_pct`. `unreliable_count` uses MASE. `principal` is now the scope. `scope_label` no longer says "MA3". |
| `GET /policy-comparison` | **New.** Per-SKU LP SS vs the rule, in units, plus a roll-up that matches the dashboard exactly. Peso and stockout fields are null with a reason. |
| `GET /bo-monitoring` | Output reworked: gap months are explicit (`has_data`); the rate uses matched months only; principal and region breakdowns; each incident's `period` and `region`. Placeholder values ("Unilever", `qty 0`, …) are now null. `brand_breakdown` is removed; it was fake. |
| `GET /fsn` | **New.** FSN per product, per principal window. |
| `GET /pareto` | **New.** Brand / category ABC, `months=1\|12`. |
| `GET /decomposition` | **New.** STL of one Unilever SKU, computed on request. |
| `GET /category-trends` | **New.** Category revenue history and a 12-month Theil–Sen trend projection with Mann–Kendall significance. |

**New pure modules, all with tests:**
- `analytics/classification/fsn.py`
- `analytics/forecasting/decomposition.py`
- `analytics/forecasting/category_trend.py` (reuses `analytics/segmentation/traits.trend_stats`)

### 4.2 `model_params` keys the UI depends on

Please keep these stable, or tell us before renaming any:
- **Keys:** `method`, `bin`, `sales_months`, `ma3_value`, `components.xgb`, `components.ma3`, `backup_fired`, `backup_reason`, `wape`, `holdout_protocol`, `provisional`, `observed_months_used` (or `months_with_sales`), `min_months_threshold`, and `holdout_metrics_served.months` (or `holdout_months`).
- **Method values:** `ma3`, `tsb`, `xgb_ma3_avg`, `trailing_average`, `zero_no_order`.
- **Reason codes:** `above_historical_max`, `below_zero`, `xgb_unavailable`, `xgb_no_forecast`, `xgb_failed`.
- **Status values:** `insufficient_data` and `dead_sku` are read as not-a-forecast.

### 4.3 UI (summary)

- **SKU Forecast:**
  - each SKU's served model, with a "How this forecast was made" block: model, bin, MA3 benchmark, components and MASE;
  - WAPE holdout error and a fallback chip;
  - provisional, no-order, Category B/C and Del Monte states;
  - no browser-computed forecast for SKUs whose model isn't MA3.
- **Diagnostics panel:** the SKU's bin and a Seasonality tile.
- **ABC:**
  - Del Monte labelled by product category, with the Jan 2025 regrouping note;
  - FSN column and filter;
  - brand / category Pareto;
  - ABC × FSN matrix.
- **Dashboard:** neutral "Forecast" labels, the MAPE tooltip, the MASE count, and the policy headline with its assumption.
- **New pages:** Bad Orders and Category Trends.
- **`frontend/src/dataCoverage.js`:** the one place the Feb 2026 date-picker ceiling lives; `/dashboard` now returns it too.

### 4.4 Tests and docs

- **Full suite: 495 passed, 8 skipped, 0 failed.** This morning it was 401 passed, 1 failed, 2 errors.
- **`test_abc_schema_contract`:** now filters `table_schema = 'public'`. Supabase has the experiment schemas `ssm_abc_repro`, `ssm_synth_v2` and `ssm_abc_phase2`, whose copies of the table duplicated the key columns.
- **README / RUNNING:** Python and xgboost notes, current test counts, a pipeline status that reflects the live database, and SARIMA shown as retired.

---

## 5. Decisions for you and Yuan

| # | Decision | Options | What it changes | Data needed |
|---|---|---|---|---|
| 1 | Safety-stock protection period (review period + lead time) | 1 day (today) · 5 (weekly review) · 5 + lead time | SS, ROP, the policy headline, stockout exposure | Lead times: `lead_time_days` is empty |
| 2 | Review period for S | Monthly (today: S = next month's forecast + SS) · weekly (the mapping: a week's demand + SS) | The size of ROP and Q; the mapping's R2 | None, beyond decision 1 |
| 3 | Net stock on hand in the order quantity | Keep Q ≥ ROP · order-up-to Q = S − inventory position | Q per SKU | On-hand coverage in `inventory_fact` is partial |
| 4 | The fixed annual allocation | CLI ceiling per run (today) · a `Supplier_Allocation` table (principal, year, units or ₱) read by `run_lp.py`, with the CLI as an override | Constraint 2's source; answers "under a pre-set fixed annual allocation" | SSM's actual allocation figures |
| 5 | Ordering cost | Add a fixed cost per order (makes the LP a MILP with order indicators) · keep it linear and drop "ordering cost" from the mapping's wording | The LP's objective, the solver and run time | A cost per order from SSM |
| 6 | Pesos for PR4 | Keep units + % (today) · adopt a cost-per-piece source | working_capital / capital_freed | A reliable cost per piece (e.g. SSM's price list) |
| 7 | Negative quantities and breaks in forecasting | Clip or flag negatives · add a structural-break guard (§1.3) | Served values for broken SKUs like `64314335` | None |
