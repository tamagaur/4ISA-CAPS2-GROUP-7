# LP logic check: order plan cycle 2026-03 and the policy card (2026-10-03)

This was a read-only check: no database writes, no migrations, no application code changes. It was done on branch
`kelvin/lp-logic-check`, cut from `kelvin-etl` at 83cafc4. Every file:line reference was re-checked against `kelvin-etl`
at 953cda3: all 59 point to unchanged lines (`check_refs.py`). A teammate raised four issues. Each one gets a verdict
backed by file:line references and figures from a named query or file.

**Terms.**
- LP = linear programming, the order optimizer (`analytics/optimization/lp.py`). The LP pool = the 73 Unilever products
  the March 2026 plan covers.
- SS = safety stock. Target (order-up-to level, `rop_i`) = the stock the plan aims to end the month at.
  Need = forecast + target − stock on hand.
- SSM = San San Marketing, the client. SSIS = the name of SSM's monthly Unilever workbooks (`data/raw/SSIS`), each
  holding a stock count, a sales register and an inventory schedule.
- SOH = stock on hand, the name of the stock-count sheet. PO = purchase order. SKU = stock-keeping unit (product code).
- KPI = key performance indicator (a dashboard card). API = the backend's web interface the dashboard reads.
  DEC-nn = an entry in `ARCHITECTURE.md`'s decision register. NULL = an empty database value.
- CBC and HiGHS = linear-programming solvers. CBC is the one PuLP and the app use; HiGHS (in scipy) was used only for
  the independent recompute.
- MASE = mean absolute scaled error.
- MA3 = 3-month moving average. TSB = Teunter–Syntetos–Babai, a method for intermittent demand. XGBoost+MA3 = the
  average of a gradient-boosted tree model and MA3.
- Bin = history-length group: short 3-11 months of sales, medium 12-23, long 24+.
- Tier A (Category A) = products in the top revenue band of the ABC classification, and always means **Tier A as of
  2026-02** (method `single`, 132 Unilever products).

**Price bases.** Every peso figure says which of these it is on:

| basis | what it is |
|---|---|
| **selling price, VAT-inclusive** | `net_amount`, "Total Sales Amt Inc. Tax"; VAT = value-added tax, 12% |
| **last purchase price** | "Last Purchase Price (GSV/CS)": Unilever's GSV list price per case, without VAT. Every stock value and every LP peso figure here is on this basis. The database and dashboard call it "cost" |
| **GSV** | gross sales value: list price before discounts, without VAT. Used for the La Union file's `gsv` column and the Ilocos Sur register's "UL GSV" (Unilever GSV), the same list as the last purchase price |
| **at cost** | SSM's own "AT COST without VAT": a flat 91.78% of the last purchase price (section 5). No figure in this report is at cost |

**Data.** Everything was read-only:
- Two database pulls, each one `REPEATABLE READ, READ ONLY` transaction, rolled back: `pull_data.py` (snapshot
  2026-10-03 06:31 UTC) and `pull_balance.py` (06:50 UTC).
- Small read-only queries: three inline (flag counts in the base tables, the location of the 209 derived-cost inventory
  rows, a table and column listing) and `check_counts_real.py`.
- `read_ssis_sales.py` and `read_ssis_soh.py`, which read 13 SSIS monthly workbooks in `data/raw/SSIS`.

The raw pulls sit in `scratch/lp_logic_check_2026-10-03/pull/`, which is gitignored because it is client data. The
analysis scripts work offline from those files.

**Generated data excluded (flag used per source).**

| source | used for | how generated rows are kept out |
|---|---|---|
| `inventory_fact_real`, `unilever_sku_demand_fact_real`, `sellout_fact_real` | stock counts, sales, sigma, allocation | view filter `is_demo = false` (`analytics/db/schema.sql:859-866`) |
| `forecast_result`, `abc_classification`, `lp_recommendation`, `lp_run` | forecasts, Tier A, stored plan | no generated rows; these are model outputs computed from the views above |
| `product_dimension` | names, pack sizes | a dimension table, no fact rows |
| base tables in `pull_balance.py` / `check_counts_real.py` | showing which sources exist | grouped by `is_demo`, `fill_source` and `valuation_source`; only `is_demo = false` counts as real |
| `derived_receipt_fact` (`is_demo = true`) | only the per-SKU negative-balance counts in section 5, labelled as derived | not a real figure anywhere |
| SSIS workbooks (`data/raw/SSIS`) | March 2026 sales, open POs, inventory schedule | real client files; the `Synthetic Data` folder was not read |

In the base tables, every row with `fill_source` set is `is_demo = true`, so the views drop it: 24,144 `synthetic_v2`
and 3,906 `synthetic_v2_gap` inventory rows, and 12,243 `synthetic_v2` demand rows. The 209 real inventory rows with
`valuation_source = 'derived_cost'` are Del Monte 2023-02/03, outside every figure here. The 13 Unilever counts used
(2025-03..2026-03) are all real rows: `is_demo = false`, no `fill_source`, no `valuation_source`, with row counts and
values identical to the pull (`counts_are_real.csv`).

## Summary

| # | Issue | Verdict | Evidence | Numbers (cycle 2026-03 = March 2026) | Recommended fix | Effort |
|---|---|---|---|---|---|---|
| 1 | Stock timing | **CONFIRMED** | Stock comes from each principal's latest count, never tied to the cycle: `backend/stock_units.py:101-114`, `scripts/run_lp.py:233-251, 784`. `lp.py:99` defines it as start-of-month stock | Total need for March 2026: 1,255,471 pieces with the count dated 2026-04-06 (used now) vs 325,468 pieces with the count dated 2026-03-02 (opening). Short at 103% allocation: 45 products / 62,103 pieces vs 0 / 0. Tier A products below SS: 35 of 70 vs 6 of 72 | Plan cycle M from the count of period M−1. **Decided:** refuse the cycle if that count is missing; **accept the 2026-03-02 count, pending SSM confirmation** | M: about 1 day of code and tests, then an LP rerun |
| 2 | MASE < 1 gate | **CONFIRMED** (standard in-sample naive one-step scale); 15 products flip | `scripts/run_baseline_forecast.py:887-892`, `analytics/forecasting/diagnostic_metrics.py:63-83`. Recomputed 47/47 short- and medium-bin products | 107 products scorable on both windows: 64 pass on the stored window, 77 on the common window. 15 flip: 14 fail→pass, 1 pass→fail. Only that 1 is in the LP pool | Wording only, proposed below | S: under 1 hour |
| 3 | Weeks of cover | **CONFIRMED** basis mismatch. The "markup" part is **not supported** | `backend/routers/dashboard.py:1337-1368` (formula), `:584-616` (sales = VAT-inclusive `net_amount`), `:772-778` (stock = source valuation) | Unilever, count of 2026-04-06, sales 2025-03..2026-02: 3.03 weeks shown (stock at last purchase price ÷ sales at selling price, VAT-inclusive) vs 3.31 weeks with sales at GSV (ratio 0.9158). Cross-check with sales at last purchase price per piece: 3.34 weeks | Put weekly sales on the GSV basis (× Σgsv/Σnet, same rows), or relabel the card | S: 2-3 hours |
| 4 | Policy card ("35.2% less") | **PARTLY** | `dashboard.py:1810-1866`, `frontend/src/components/Charts.jsx:1822-1826` | 73 products, cycle 2026-03, pesos at last purchase price. Peak: targets ₱8,917,570 vs rule ₱8,211,106 = **+₱706,464 (+8.6%)**, confirmed. Average: ₱5,906,832 = **28.1% less**. The 18.5% figure is the pieces version. 35.2% is safety stock alone, in pieces | Show peak and average in pesos with the formulas. Stop citing 35.2% | M: about half a day |

## 1. Stock timing: which count the March plan uses

### How a count is chosen for a cycle

| step | what happens | file:line |
|---|---|---|
| 1 | The cycle month is the latest `Forecast_Result.forecast_date`: 2026-03-01 | `scripts/run_lp.py:184-205, 812` |
| 2 | Stock is fetched **once, before cycles are formed**, through `STOCK_AT_LATEST_SQL` | `scripts/run_lp.py:229-251, 784` |
| 3 | `STOCK_AT_LATEST_SQL` takes each principal's `MAX(_period)`, with no reference to the cycle | `backend/stock_units.py:101-114` |
| 4 | Unilever's `MAX(_period)` is 2026-03: file `SSIS MARCH 2026.xlsx`, **counted 2026-04-06** | `issue1_unilever_stock_counts.csv`; `ARCHITECTURE.md:90` (DEC-20) |
| 5 | That count becomes S_i, and need_i = F_i + T_i − S_i | `scripts/run_lp.py:469-477`; `analytics/optimization/lp.py:148-151` |
| 6 | The LP itself defines S_i as "stock at the start of the month" | `analytics/optimization/lp.py:99`, `:22-23` |
| 7 | The dashboard's below-SS KPI and the reorder page also use the latest count | `dashboard.py:723-734, 1175, 1229-1257`; `backend/routers/recommendations.py:391` |
| 8 | `Inventory_Fact.demand_period` is meant to say which month a count opens, but it is NULL on every row | `analytics/db/migrations/0010_gsv_and_guards.sql:35-44`; `days_offset_populated = 0` in the pull |

**Effect.** The 2026-04-06 count is the stock left *after* March's sales. Subtracting it from March's forecast plus
target counts March's demand twice: once in F, and once already gone from S. The count that opens March is period
2026-02, counted **2026-03-02**.

### Recomputed both ways (Unilever, 73 products, allocation 103%, other inputs at placeholder defaults)

First, a replay check. Re-running `run_lp`'s own functions on its own inputs matches the 73 stored pending rows to
within 0.005 pieces (`rop_i`, `ss_i`, and `q_i` at 105%, the stored run's allocation). It also reproduces
`reports/evidence/ch08_totals.csv` at 103% exactly. The only thing changed below is the stock count. Price per piece
(last purchase price per case ÷ pack size, `run_lp`'s "cost per piece") is held at `run_lp`'s value.
`independent_recompute.py` re-derives every headline number below with separate code and a different solver (scipy
HiGHS instead of CBC) and gets the same figures.

| measure | count of 2026-04-06 (used now) | count of 2026-03-02 (opening) |
|---|---|---|
| stock on hand, 73 products (pieces) | 759,258 | 2,093,786 |
| same stock at last purchase price (₱) | 6,105,203 | 16,782,794 |
| products not in the count (counted as 0, Unilever rule) | 3 | 1 |
| **total need, March 2026 (pieces)** | **1,255,471** | **325,468** |
| allocation ceiling at 103% (pieces a month) | 1,193,368 (binds) | 1,193,368 (does not bind) |
| ordered (pieces) | 1,193,368 | 325,468 |
| **short: products / pieces** | **45 / 62,103** | **0 / 0** |
| products ordering 0 (already above target) | 4 | 31 |
| planned month-end cover, aggregate (weeks) | 3.000 | 4.328 |
| **Tier A below SS / comparable** (dashboard rule: no stock row = excluded) | **35 of 70** | **6 of 72** |

Per-product figures are in `issue1_stock_timing_per_product.csv` and the totals in `issue1_totals.csv`.

### The opening count is flagged as an outlier: decided ACCEPT, pending SSM confirmation

`backend/data_notes.py:26-29` marks the 2026-02 Unilever count: *"About twice the stock counted the month before and
after (₱46.6M vs ₱24.3M and ₱22.7M); treated as an outlier (team review, 2026-09-29)."* Decision (2026-10-03): the plan
**accepts** this count, **pending SSM confirmation**. Section 5 has the balance evidence. What the counts themselves show:

| check | value |
|---|---|
| whole Unilever count at last purchase price: 2026-02-03 / 2026-03-02 / 2026-04-06 | ₱24,339,386 / ₱46,576,779 / ₱22,700,826 |
| per product, 2026-03-02 ÷ 2026-02-03 value (704 products in both counts) | quartiles 0.87× / 1.67× / 4.14×; 376 products above 1.5×. The jump is spread out, not one flat multiple |
| the 73 LP products | median 2.91× the 2026-02-03 count; 50 of 72 above 1.5× |
| implied February 2026 receipts (**estimate**: closing − opening + the La Union file's pieces sold × last purchase price per piece; Unilever has no purchase records) | ₱47.3M, vs ₱11.3M–₱48.9M in the 12 months before (June 2025: ₱48.9M). Section 5 redoes this with the Ilocos Sur register's sales: ₱55.9M |

UNVERIFIED: a large February purchase would explain the jump, but the data can't confirm it (section 5).

## 2. MASE < 1 gate

**Scale: confirmed standard.** The stored `Forecast_Result.mase` is the mean |actual − forecast| over the test months
divided by the mean |month-to-month change| over the training months.
- Test months are the last 20% of the product's months (`analytics/params.py:48`, `analytics/forecasting/split.py:17`).
  At each test month the model forecasts one month ahead, with the served model held fixed
  (`scripts/run_baseline_forecast.py:887-889`, `analytics/forecasting/router.py:134-146`).
- The scale is `naive_scale(train)`, the mean |lag-1 difference| of the training months
  (`diagnostic_metrics.py:78-83`). That is the in-sample naive one-step error of Hyndman & Koehler (2006).
- The gate is MASE < 1 (`analytics/params.py:29`, applied in `scripts/run_lp.py:202`).
- Verified: I recomputed MASE for 47 of 47 short- and medium-bin products offline, and it matched to 3 decimals.
  `reports/diagnostics/fit_diagnosis_2026-10/README.md` reproduced all 119, including the XGBoost bin.
- Caveat: each series starts at the product's first month on file and zero-fills gaps
  (`run_baseline_forecast.py:196-206`), so zero months count toward the scale.

**Flips when the test window moves.** The stored window is each product's last 20% of months (2-8 months ending
2026-02). The moved window is the common 2025-09..2026-02 (6 months) from
`reports/diagnostics/fit_diagnosis_2026-10/per_sku.csv`. 107 products can be scored on both; the 12 short-bin products
only have the stored window. Passing products go from 64 to 77, and 15 flip (`issue2_mase_flips.csv`):

| product (SKU) | bin / served | stored window | MASE stored | MASE common | flip | in LP pool 2026-03 |
|---|---|---|---|---|---|---|
| KNORR BN CUBES BEEF SINGLES 48X12X10G (68438418) | long / XGBoost+MA3 | 2025-07..2026-02 | 0.996 | 1.019 | pass → fail | **yes** |
| KNORR SOUP CHICKEN&CORN 60X60G (67975949) | long / XGBoost+MA3 | 2025-07..2026-02 | 1.024 | 0.695 | fail → pass | no |
| KNORR BN CUBES BEEF SAVERS 36X120G (68438405) | long / XGBoost+MA3 | 2025-07..2026-02 | 1.027 | 0.925 | fail → pass | no |
| LADY'S CHOICE REAL MAYO 72X80ML (69695555) | long / XGBoost+MA3 | 2025-10..2026-02 | 1.031 | 0.833 | fail → pass | no |
| LADY'S CHOICE SS CHICKEN 72X27ML (68763997) | medium / TSB | 2025-11..2026-02 | 1.033 | 0.741 | fail → pass | no |
| CREAM SILK TRI-KRTN SCD STRT 288X14ML (64900598) | short / MA3 | 2026-01..2026-02 | 1.060 | 0.637 | fail → pass | no |
| KNORR BN CUBES CHICKEN SAVERS 36X120G (68438412) | long / XGBoost+MA3 | 2025-07..2026-02 | 1.063 | 0.980 | fail → pass | no |
| LADY'S CHOICE REAL MAYO 72X27ML (69695566) | long / XGBoost+MA3 | 2025-10..2026-02 | 1.071 | 0.940 | fail → pass | no |
| SURF FABCON LUXE PERFUME STR 360X25ML (64856638) | short / MA3 | 2026-01..2026-02 | 1.082 | 0.544 | fail → pass | no |
| LADY'S CHOICE SS PLAIN JAR 24X220ML (68764014) | medium / TSB | 2025-11..2026-02 | 1.165 | 0.734 | fail → pass | no |
| LADY'S CHOICE SS PLAIN DOY 24X220ML (68764017) | medium / TSB | 2025-11..2026-02 | 1.173 | 0.923 | fail → pass | no |
| REX WMN DLN POWDER DRY + BRGHT 360X3ML (64824382) | medium / TSB | 2025-12..2026-02 | 1.196 | 0.765 | fail → pass | no |
| SURF POWDER TAWAS L 40(6+1)57G (64861490) | short / MA3 | 2026-01..2026-02 | 1.899 | 0.744 | fail → pass | no |
| VITAKERATIN TMT BRZLN STRAIGHT 288X22ML (64926066) | short / MA3 | 2026-01..2026-02 | 1.974 | 0.580 | fail → pass | no |
| SURF POWDER KALAMANSI L 40(6+1)57G (64861486) | short / MA3 | 2026-01..2026-02 | 2.194 | 0.861 | fail → pass | no |

Only one flip changes the 2026-03 plan: the Knorr beef singles would leave the pool. The other 14 would join it.
18 of 107 products have a stored MASE within ±0.1 of 1.

**Proposed wording (no code change).**
- *Paper:* "Each product's forecast is tested on its most recent months: the last 20% of its sales history, which is
  2 to 8 months ending February 2026. At each test month the model forecasts one month ahead from earlier months only.
  The mean absolute scaled error (MASE) divides the forecast's average miss over those months by the average
  month-to-month change in the product's sales during the earlier training months. That divisor is the error of a
  'same as last month' guess on the training data (Hyndman & Koehler, 2006). A MASE below 1 means the forecast missed
  by less than that benchmark, and only those products enter the order plan. The result depends on which months are
  tested. Scoring every product on the same six months (September 2025 to February 2026) changes the result for 15 of
  107 products, and 18 of 107 lie within 0.1 of the cut-off. The gate is a screen, not a fine ranking."
- *Dashboard tooltip:* "Forecast check passed (MASE below 1): in recent test months this forecast missed by less,
  on average, than this product's usual month-to-month change in sales. Values near 1 are borderline and can change
  as new months arrive."

## 3. Weeks of cover

**Formula shown** (`dashboard.py:1337-1368`, `:899-920`): weeks = stock value ÷ (average monthly sales ÷ 4.348).
- Stock value: ₱22,700,825.83 at last purchase price, Unilever count of 2026-04-06. This is the source file's own
  valuation (`dashboard.py:772-778`), priced at "Last Purchase Price (GSV/CS)" (`ARCHITECTURE.md:89`, DEC-19).
- Average monthly sales: `net_amount` at selling price, VAT-inclusive ("Total Sales Amt Inc. Tax",
  `analytics/db/migrations/0010_gsv_and_guards.sql:24-33`). Averaged over the 12 months 2025-03..2026-02 (12 of 12
  months have data): ₱32,592,762 a month. Divided by 4.348 weeks a month (= 365.25 ÷ 12 ÷ 7,
  `analytics/params.py:113-114`), that is ₱7,495,666 a week.

| basis (Unilever; stock counted 2026-04-06 at last purchase price; sales 2025-03..2026-02) | sales ratio vs shown | weeks |
|---|---|---|
| **shown:** sales at selling price, VAT-inclusive | 1.0000 | **3.03** |
| **GSV-matched:** sales at the demand file's own GSV column | 0.9158 | **3.31** |
| cross-check: pieces sold × last purchase price per piece (`run_lp`'s cost per piece; covers 99.8% of net sales) | 0.9073 | 3.34 |
| VAT removed only (selling price ÷ 1.12) | 0.8929 | 3.39 |
| pieces ÷ pieces (no price) | n/a | 3.13 |

**Where the matching ratio comes from:** Σ GSV ÷ Σ `net_amount` over the same 12 months and the same rows. Both columns
are in the La Union source file (`Unilever_SKU_Demand_Fact.gsv`, migration 0010). GSV is the price list the stock is
valued on (DEC-19). 21 of 8,735 rows in the window have no GSV. The cost-per-piece cross-check lands within 1% of it.

**"Markup" is not supported.** Once VAT is removed, net sales come to 97.5% of GSV (0.8929 ÷ 0.9158). So the 3.03 vs 3.31
gap is VAT, partly offset by about 2.5% of discounts or price differences, not markup. Whether SSM actually pays GSV
or less for its stock is UNVERIFIED: the column is a list price.

Section 5 adds a caveat. The counts come from workbooks headed "Ilocos Sur", while these sales are documented as La
Union only. Which territory the counted warehouse serves is UNVERIFIED. If it serves the Ilocos Sur register's sales,
the like-for-like figure is **2.10 weeks** (count of 2026-04-06, sales at UL GSV, 2025-03..2026-02), not 3.31.

## 4. Policy card

Same 73 pending products, cycle 2026-03, 90% service level (Z = 1.28, the normal-distribution factor for 90%). Pesos
are at last purchase price per piece, `run_lp`'s "cost per piece" (73 of 73 from the stock file). Per product:
w_i = F_i ÷ 4.348 (weekly forecast, pieces), rule_i = 3 × w_i, and pesos = Σ price per piece × pieces.
- **(a) Peak = order-up-to level:** T_i = w_i × (R + L) ÷ 5 + SS_i with R = 5 and L = 3 business days (placeholders),
  so T_i = 1.6 × w_i + SS_i (`lp.py:141-145`). This is the stored `rop_i`.
- **(b) Average on hand ≈ SS_i + half the cycle order quantity.** One weekly purchase order covers one week's demand,
  w_i × R ÷ 5 = w_i, so the average is SS_i + w_i ÷ 2.

| measure (cycle 2026-03, 73 products) | pieces | pesos (last purchase price) | vs 3-week rule |
|---|---|---|---|
| 3-week rule | 748,716 | ₱8,211,106 | n/a |
| (a) peak, per-product targets | 884,856 | ₱8,917,570 | **+₱706,464 (+8.6%)**; pieces +18.2% |
| (b) average on hand | 610,327 | ₱5,906,832 | **−₱2,304,274 (−28.1%)**; pieces −18.5% |
| safety stock alone (the card's old headline) | 485,541 | n/a | pieces −35.2% |
| sensitivity: rule's own average if its 3 weeks is a peak (3w − w/2) | n/a | ₱6,842,589 | (b) is 13.7% less than this |
| SSM's actual stock on these 73 at the 2026-04-06 / 2026-03-02 counts | n/a | ₱6,105,203 / ₱16,782,794 | n/a |

**Verdict.** The +₱0.71M at peak is confirmed. The 18.5% "less at average" is right in pieces but not in pesos, where
it is **28.1% less**. Pesos weight each product by its price per piece, and the products with the larger peso volume
carry less safety stock per week of sales. "35.2% less" is safety stock alone against the rule, in pieces
(`lp_vs_rule_pct`, `dashboard.py:1859`). Since d7b30dd (2026-10-01) the card's headline has been `target_vs_rule_pct`,
which reads "18.2% more" (`dashboard.py:1836-1851`, `Charts.jsx:1822-1826`). If 35.2% is still on screen, the deployed
app predates d7b30dd. That is UNVERIFIED; I did not check Render or Vercel. Per-product figures are in
`issue4_policy_card_per_product.csv` (pieces; the per-product pesos are in its `local/` copy, see Files).

## 5. Stock balance check for the 2 March count (follow-up, 2026-10-03)

Decisions recorded 2026-10-03:
1. A missing opening count **refuses the plan** (rule 2 of the proposed fix).
2. The dashboard **keeps the latest count** as "stock now" and always shows the count date.
3. The 2 March 2026 count is **ACCEPTED, pending SSM confirmation**.

The evidence below shows why decision 3 stays pending: the balance cannot prove the count either way. Scripts:
`pull_balance.py` (database, read-only, snapshot 2026-10-03 06:50 UTC), `read_ssis_sales.py` and `read_ssis_soh.py` (raw
workbooks, read-only), `analyse_balance.py`.

### Sources found

| need | in the database | in the raw files |
|---|---|---|
| March 2026 sales | **No real rows.** All 644 Unilever SKU rows for 2026-03 are synthetic placeholders (`is_demo = true`, `fill_source = synthetic_v2`). `etl_coverage` marks 2026-03 "synthetic" with 0 real rows | **`SSIS MARCH 2026.xlsx`** (already in `data/raw/SSIS/2026`) holds the full March 2026 daily sales report: sheet `INVOICE REG(MARCH 2026)`, 8,567 lines. It has the same layout and totals as the "SSIS SALES SUMMARY REPORT" files: for December 2025 both give net UL GSV ₱30,262,612. So `SSISSALESSUMMARYREPORTMARCH2026.xlsx` most likely duplicates what is on disk; adding it would confirm, not add |
| receipts / deliveries, any month | **None.** `purchase_fact` has no Unilever rows at all, only Del Monte. `derived_receipt_fact` is this same balance run backwards (`is_demo = true`), not a record | **None.** The SSIS workbooks have no receiving sheet. The SOH sheets' `PO Qty` column is purchase orders open at the count date (placed, not yet received). It is used below as a signal, not as receipts |

### What the counts cover (this decides which sales to use)

- The SSIS workbooks are headed "SANSAN ILOCOS SUR DAILY SALES REPORT", with distributor
  "4019 SAN SAN MARKETING - MAG (Ilocos Sur)" (`ssis_workbooks.csv`).
- Their SOH sheets are the stock counts. All 13 counts (2025-03..2026-03) equal the database value, and they equal the
  workbook's own "SANSAN ILOCOS … INVENTORY: Whse Inventory - Retail, without VAT" line (`ssis_soh_columns.csv`). That
  includes ₱46,576,778.51 (last purchase price) for 2 March: **SSM's own file reports that figure twice**, so it is not
  a loading error. Whether the physical count itself is right remains UNVERIFIED.
- The SKU sales the LP and dashboard use come from the La Union file, documented as "La Union territory only"
  (`profiling/grain_map.md:99`; `etl_coverage.real_sites = ['la_union']`).
- In every month 2025-04..2026-02, La Union sales (at GSV) are 57%–76% (median 62%) of the Ilocos Sur register's sales
  (at UL GSV).
- **UNVERIFIED, a question for SSM:** does the counted warehouse also serve La Union? Until that is answered, both
  sales series are shown. The Ilocos Sur register is the one from the same workbooks as the counts.

### Balance, month by month (₱; counts at last purchase price, sales at GSV / UL GSV, all without VAT)

The equation is opening count + receipts − sales = closing count. No receipts are recorded, so the table gives the
receipts each pair of counts **implies** (closing − opening + sales), which is an estimate. Ilocos Sur sales are the
register's UL GSV (Unilever's GSV of the goods sold, no VAT), net of credit notes. Over 2025-03..2026-02, UL GSV is 98.0%
of the register's own GSV.

| month | opening count | closing count | sales, Ilocos Sur register | closing if no receipts | **implied receipts** (× sales) | open POs at opening count | sales, La Union file (GSV) | implied receipts on La Union sales |
|---|---|---|---|---|---|---|---|---|
| 2025-11 | 23,952,053 (3 Nov) | 29,965,754 (1 Dec) | 50,663,301 | −26,711,248 | 56,677,001 (1.12×) | 20,821,061 | 30,422,228 | 36,435,929 |
| 2025-12 | 29,965,754 (1 Dec) | 36,277,134 (1 Jan) | 30,262,612 | −296,858 | 36,573,992 (1.21×) | 26,755,276 | 17,923,426 | 24,234,806, below open POs |
| 2026-01 | 36,277,134 (1 Jan) | 24,339,386 (3 Feb) | 54,970,350 | −18,693,217 | 43,032,603 (0.78×) | 25,297,925 | 33,964,411 | 22,026,663, below open POs |
| **2026-02** | 24,339,386 (3 Feb) | **46,576,779 (2 Mar)** | 33,706,098 | −9,366,711 | **55,943,490 (1.66×)** | 20,296,406 | 25,502,319 | 47,739,711 |
| **2026-03** | **46,576,779 (2 Mar)** | 22,700,826 (6 Apr) | 55,985,543 | −9,408,764 | **32,109,590 (0.57×)** | 17,592,964 | none (no real March rows) | n/a |
| baseline 2025-04..2026-01 (10 months) | | | | | ₱36.6M–₱64.7M, median ₱45.6M; 0.77×–1.32×, median 1.06× | | | |

All 12 months are in `balance_monthly.csv`.

### What it shows

- **March.** For 2 March count + March receipts − March sales to equal the 6 April count, March receipts must be
  ₱32.1M (0.57× March sales). That is below every baseline month: the lowest was ₱36.6M (December 2025) and the lowest
  ratio 0.77× (January 2026).
- **February.** For the 3 February count + receipts − February sales to equal the 2 March count, February needs ₱55.9M
  of receipts (1.66× sales). The peso amount is inside the baseline range (June 2025 was ₱64.7M), but the ratio is the
  highest of any month (baseline maximum 1.32×).
- **The two months together close normally.** Going from ₱24.3M on 3 February to ₱22.7M on 6 April with ₱89.7M of sales
  needs ₱88.1M of receipts, or 0.98× sales. That is inside the baseline range for consecutive two-month pairs
  (0.92×–1.24×). The 2 March count moves receipts between February and March; it does not break the two-month balance.
- **Without receipt records the balance cannot tell a February forward buy from an overstated count.** For scale: had
  February's receipts been at the median ratio (1.06× sales), the 2 March count would be about ₱26.4M, which is
  ₱20.2M less than reported. That figure is a derived hypothetical. Neither explanation (forward buy or overstated
  count) is verified.
- **Open purchase orders.** On the Ilocos Sur basis, implied receipts are never below the purchase orders open at the
  opening count (0 of 12 months). On the La Union basis they are below in 3 of 11 months (August 2025, December 2025,
  January 2026). The 2 March count had the lowest open POs of the 13 counts (₱17.6M; range ₱17.6M–₱26.8M).
- **Open customer orders** on 2 March were ₱0.26M, so they are not the source of the jump.
- **Per SKU, La Union basis.** Each month 133–237 of 601–716 SKUs (2025-09..2026-01) show stock falling by more than
  their La Union sales explain (`derived_receipt_fact`, flag `negative_balance`, a derived estimate); February 2026 had
  146. That is consistent with the counts covering more than La Union's sales, which remains UNVERIFIED.

**What would settle it:** Unilever's February and March 2026 delivery invoices (or SSM's receiving report) for the
Ilocos warehouse, and SSM's answer on which territories that warehouse serves.

### Weeks of cover on both counts (matched price basis)

Weeks of cover = stock at last purchase price ÷ average weekly sales at GSV (both without VAT, same price list). Sales
are averaged over 2025-03..2026-02 (12 of 12 months) and divided by 4.348 weeks a month. Output:
`cover_both_counts.csv`.

| scope | sales basis | 2 March count | 6 April count |
|---|---|---|---|
| 73 LP products (₱16,782,794 / ₱6,105,203) | La Union file GSV, ₱2,825,076 a week | **5.94 weeks** | **2.16 weeks** |
| whole count (₱46,576,779 / ₱22,700,826) | La Union file GSV, ₱6,864,739 a week | 6.78 weeks | 3.31 weeks |
| whole count | Ilocos Sur register UL GSV, ₱10,804,764 a week | 4.31 weeks | 2.10 weeks |

The 73 products have no Ilocos Sur figure because the register has no SKU column. If the counted warehouse serves more
than La Union, every La Union-based cover is overstated by about 1.6× (3.31 vs 2.10 weeks at 6 April), the
dashboard's included. The workbook's own "AT COST without VAT" column is a flat 91.78% of the GSV value on all 13
counts. The database stock value, which the dashboard calls "at cost", is the last purchase price. A cover at SSM's cost would need
sales at cost too, so these ratios are unchanged on a like-for-like basis.

## Proposed fix for issue 1 (not implemented; implementation spec)

Line numbers are at `kelvin-etl` 953cda3. Decisions this spec follows (2026-10-03):
1. A missing opening count refuses the plan.
2. The dashboard keeps the latest count as "stock now" and always shows its date.
3. The 2 March 2026 count is accepted, pending SSM confirmation.

**Rule.**
1. **Opening count.** For cycle M (`planning_cycle_date` = first day of month M), stock comes from that principal's
   count with `_period` = M − 1. Cycle 2026-03 uses period 2026-02, counted 2026-03-02 (`inventory_fact_real.snapshot_date`).
   Per DEC-20, counts land 1-6 days after the period ends.
2. **Missing opening count, refuse (decision 1).** If `inventory_fact_real` has no row for that principal at M − 1:
   - skip that principal's products for the cycle;
   - write nothing for them: no `lp_run` row, no upsert, and no `--retire-stale-pending` for that cycle;
   - log an ERROR "opening stock count for <principal> <M−1> missing; cycle <M> not planned";
   - list it in the run summary as infeasible cycles are listed (`run_lp.py:829-834, 915-917`).

   Never substitute an older or a later count.
3. **Look-ahead guard.** A count with `_period` ≥ M is never read for cycle M.
4. **Present count, product absent:** unchanged. Unilever = 0 on hand (`in_stock_file = False`), Del Monte = NO DATA
   (`run_lp.py:56-60`). Del Monte is not planned today.
5. **Flagged count, accept (decision 3).** If `(principal, M − 1)` is in `backend/data_notes.UNUSUAL_STOCK_SNAPSHOTS`,
   plan from it, but:
   - log a WARNING with the note's text;
   - store the note in `lp_run.inputs["stock_count"][principal]["flag"]`;
   - change the note at `backend/data_notes.py:26-29` to read "accepted for planning, pending SSM confirmation
     (2026-10-03)" instead of "treated as an outlier".

**Code changes.**
- `backend/stock_units.py` (beside `STOCK_AT_PERIOD_SQL` 83-92 / `STOCK_AT_LATEST_SQL` 101-114):
  - `def opening_period(planning_cycle_date: datetime.date | str) -> str` returns the previous month as 'YYYY-MM'.
  - `STOCK_AT_PERIOD_PG_SQL` has the SELECT of `STOCK_AT_PERIOD_SQL` with psycopg2 parameters:
    `WHERE inv.principal = %(principal)s AND inv._period = %(period)s`.
  - `COUNT_DATE_PG_SQL` is `SELECT MIN(snapshot_date) FROM inventory_fact_real WHERE principal = %(principal)s AND
    _period = %(period)s`. NULL means no count.
  - Keep `STOCK_AT_LATEST_SQL` for the "stock now" screens (decision 2).
- `scripts/run_lp.py`:
  - `STOCK_AND_COST_QUERY` (233-251): join `STOCK_AT_PERIOD_PG_SQL` instead of `STOCK_AT_LATEST_SQL`. Leave the cost
    LATERAL (242-249) unchanged.
  - `fetch_stock_and_cost` (403-409) becomes `fetch_stock_and_cost(cur, product_keys, principal, period)` and returns
    the same dict.
  - `main()`:
    - Step B (784) fetches demand only.
    - Step C (794-812) computes `sigma_d` and groups candidates by `(forecast_date, principal)`. It does not call
      `product_input` yet, because that needs stock.
    - Step D (823+), for each cycle and principal: `period = opening_period(cycle)`; run `COUNT_DATE_PG_SQL`; if NULL,
      refuse (rule 2); otherwise call `fetch_stock_and_cost`, then `product_input` (464-480, unchanged), then
      `plan_cycle` (503-539, unchanged).
  - `run_record` (575-596): add `inputs["stock_count"] = {principal: {"period": ..., "counted_on": ..., "flag": note or
    None}}`.
  - `plan_rows` (542-560): add `stock_period` and `stock_counted_on` columns.
  - `_log_cycle` (684-698): log the count used per principal.
  - Module docstring (51-60): "stock on hand: pieces at the count that opens the planning month (period M − 1)".
- Dashboard and reorder API (decision 2, latest count kept):
  - `backend/routers/dashboard.py`: keep `_latest_inventory_period` (723-734). Add `stock_period` and
    `stock_counted_on` (MIN `snapshot_date` of that principal and period) to `safety_stock_exposure` (dicts at
    1299-1313) and to the payload beside `kpis.safety_stock_rate`.
  - `backend/schemas/recommendations.py` `RecommendationsResponse` (101-116): add `stock_period: str | None` and
    `stock_counted_on: datetime.date | None`, filled in `backend/routers/recommendations.py` where `inv_period` is
    resolved (391, 492).
- Frontend:
  - `frontend/src/components/Dashboard.jsx` (exposure card, 520-528): show "stock counted <date>".
  - `frontend/src/components/ReorderRecommendations.jsx` (109): the on-hand text adds "(stock counted <date>)".
- `analytics/optimization/lp.py`: no change; `:99` already defines S_i as start-of-month stock.
- `ARCHITECTURE.md`:
  - add DEC-32: "LP stock = the count that opens the planning month (period M − 1); missing = refuse; Unilever
    2026-02 count accepted pending SSM";
  - correct DEC-20 (line 90): `days_offset` / `demand_period` are NULL on all rows (verified 2026-10-03).

**Tests to add** (offline unless marked live).
1. `opening_period(date(2026, 3, 1)) == "2026-02"` and `opening_period("2026-01-01") == "2025-12"`.
2. `tests/optimization/test_run_lp_script.py`, with a fake cursor that records SQL and parameters: for cycle 2026-03
   the stock query gets `period = "2026-02"`, and no executed SQL contains `MAX(_period)`.
3. Same fake cursor holding counts for 2026-02 and 2026-03: `ProductInput.stock_on_hand` equals the 2026-02 value.
4. `COUNT_DATE_PG_SQL` returns NULL: the cycle is refused, no `LP_RUN_INSERT_QUERY`, `UPSERT_QUERY` or `RETIRE_QUERY`
   is executed, and the summary names the refusal.
5. No query for cycle M ever binds a period ≥ M.
6. Flagged count (fixture `UNUSUAL_STOCK_SNAPSHOTS` entry): the plan is produced, `run_record()["inputs"]["stock_count"]`
   carries the note, and a WARNING is logged (`caplog`).
7. `plan_rows()` rows include `stock_period` and `stock_counted_on`.
8. `tests/backend/test_dashboard.py` and `tests/backend/test_recommendations.py`: responses include `stock_period` and
   `stock_counted_on`, equal to the latest count's period and date.
9. Live, read-only, after the change: `python scripts/run_lp.py --dry-run --allocation-pct 103` logs stock period
   2026-02 counted 2026-03-02, a need of 325,468 pieces, and 0 products / 0 pieces short. This holds while the inputs
   are unchanged since the 2026-10-03 06:31 UTC snapshot. Then `python scripts/smoke_api.py` passes.

**Out of scope for this fix:**
- rerunning the LP to write cycle 2026-03 (a database write, needs Yuan's approval);
- the territory question (section 5);
- subtracting stock already on order (open POs).

## Side findings

- `Inventory_Fact.days_offset` and `demand_period` are NULL on all rows. DEC-20 (`ARCHITECTURE.md:90`) says they were
  backfilled 27,282/27,282, and they are exactly the columns that would have prevented issue 1.
- The `*_Real` views were created before `fill_source` existed (`SELECT *` froze the column list), so they don't expose
  it. Today every fill row is `is_demo = true`, so nothing leaks.
- `lp_run` exists on public with 0 rows, and all 74 cycle 2026-03 rows have `lp_run_key` NULL. The app therefore can't
  show what that run used (`backend/lp_cycle.stored_run`).
- `kelvin-etl` moved from 83cafc4 to 953cda3 during the session. The changes touching cited files are the migration
  renumber 0035 → 0037 (ef08b70: comment and message text in `run_lp.py` / `lp_cycle.py`, same line counts) and
  `ARCHITECTURE.md` edits. All 59 file:line references in this report point to unchanged lines at 953cda3
  (`check_refs.py`).

## Files

| file | contents |
|---|---|
| `pull_data.py` | the one read-only pull, reusing `run_lp`'s own queries |
| `analyse.py` | offline replay and every figure above; writes `figures.json` |
| `issue1_stock_timing_per_product.csv` / `issue1_totals.csv` | both stock counts per product (pieces; price per piece in the `local/` copy only) and in total |
| `issue1_unilever_stock_counts.csv` | Unilever counts 2025-01..2026-03: count date, value and sales at last purchase price, implied receipts (estimate) |
| `issue2_mase_flips.csv` | the 15 flips |
| `issue3_weeks_of_cover.csv` | weeks of cover by basis |
| `issue4_policy_card_per_product.csv` / `issue4_policy_card_totals.csv` | peak, average and rule: per product in pieces (pesos in the `local/` copy only), totals in pesos |
| `pull_balance.py` | section 5's read-only pull: every Unilever sales, returns, purchase and receipt source, by month |
| `read_ssis_sales.py` → `ssis_sales_monthly.csv`, `ssis_workbooks.csv` | SSIS invoice-register totals per month and billing type (no names), plus distributor headers |
| `read_ssis_soh.py` → `ssis_soh_columns.csv` | each count's SOH sheet in pesos (stock, open POs, open customer orders) and the INVENTORY summary lines |
| `analyse_balance.py` → `balance_monthly.csv`, `cover_both_counts.csv`, `balance_figures.json` | section 5's balance and weeks of cover |
| `check_counts_real.py` → `counts_are_real.csv` | the 13 counts in the base table, by `is_demo` / `fill_source` / `valuation_source` |
| `check_refs.py` | every file:line reference re-read at a revision (953cda3) |
| `independent_recompute.py` → `independent_recompute.json` | the headline numbers re-derived with separate code and scipy HiGHS |
| `arithmetic_check.py` → `arithmetic_check.csv` | totals vs per-product and per-month sums |
| `number_check.py` → `number_check.csv` | every number in this README traced to a source file, or listed as constant / input / unsourced |

**Client data kept out of git (2026-10-05).** The project rule is that per-product sales and prices are never
committed. The two per-product tables here therefore carry pieces, counts and flags only. Their full-detail versions,
with the same file names, live in the git-ignored `local/` subfolder. `analyse.py` writes both copies (its
`CLIENT_COLUMNS` pattern decides which columns stay out), and `arithmetic_check.py` and `number_check.py` read the
`local/` copy for the policy card's per-product pesos. Without `local/`, rerun `analyse.py` to recreate it. Totals and
every other table are unchanged. Columns held in `local/` only:

| file | columns in the `local/` copy only |
|---|---|
| `issue1_stock_timing_per_product.csv` | `cost_per_piece_php` |
| `issue4_policy_card_per_product.csv` | `cost_per_piece_php`, `peak_target_php`, `avg_target_php`, `rule_3wk_php`, `stock_2026-04-06_php` |

Reproduce: `python pull_data.py` and `python pull_balance.py` (read-only, write `scratch/…/pull`), then
`python read_ssis_sales.py`, `python read_ssis_soh.py` (they read `C:/Users/kyuan/Capstone-Project/data/raw/SSIS`),
`python analyse.py` and `python analyse_balance.py`, then the checks: `independent_recompute.py`,
`arithmetic_check.py`, `number_check.py`, `check_refs.py 953cda3`. A fresh pull will differ if the database changed after
2026-10-03 06:31 UTC (first pull) or 06:50 UTC (second pull).
