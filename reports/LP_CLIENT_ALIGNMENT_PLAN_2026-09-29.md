# Proposal: align the LP / reorder plan with how SSM actually orders

- **From:** Audrey
- **Date:** 2026-09-29 (updated the same night, and again after Yuan's answers)
- **Branch:** `fix/audit-2026-09-29` (off `UIFixes_Audrey`)
- **Status:** Steps A–C are done. Step B (the model) follows Yuan's answers, and the Step C dry run is in §8 for us to go through together. Nothing has been written to the database. Step E waits for that review and a backup.

## Yuan's answers, and what was done with them

| # | Yuan's answer | Done |
|---|---|---|
| 1 | No local LP changes; the last LP commit is `8f79729`. | Step B went ahead on `lp.py` / `run_lp.py`. |
| 2 | Step B approved. Add a test that `Q` changes with `--allocation-pct`. Loop in Thea; Sir Catubag must see it too. | `test_the_order_moves_with_allocation_pct`: going from 103% to 108% changes the orders, and each run uses its whole allocation. §9 is the formulation for Thea and Sir Catubag. |
| 3 | Per-SKU target = the statistical one. SSM's 3 weeks = one aggregate constraint on stock value at cost, soft if it can't be met, behind a flag. Dry-run both. | `--cover-rule aggregate` (the default) or `per-sku`. Both are dry-run in §8. |
| 4 | Keep the safety-stock formula, but state its daily-independence assumption in `lp_model_info`. | `lp_model_info()` now carries `safety_stock_assumption`, and §9 states it too. |
| 5 | Placeholders are fine, kept in one place (CLI defaults + `lp_model_info`), and never cited as SSM's figures in the manuscript. Dry-run 105%, plus 103% and 108%. | They live in one dict, `analytics/optimization/lp_inputs.PLACEHOLDERS`, which supplies both `run_lp.py`'s defaults and `lp_model_info()["inputs"]`. Tests pin both. |
| 6 | Step E only after we review Step C together. Back up first. | Not run. |
| 7 | Ask Sir Abe whether "3 weeks" is warehouse-wide or per SKU. | Added to §11. |

## Where the build departs from the plan or from your note (please check)

1. **The cover rule counts month-end stock, not `stock + Q`.** `Q` is the whole month's order, so `stock + Q` includes the month's own sales and is always above 3 weeks (≈ 1.98M pieces against ≈ 0.75M), so that constraint could never bind. Instead it constrains what is left at month end: `Σ c_i (stock_i + Q_i − forecast_i) ≥ 3 weeks × Σ c_i × weekly sales_i`, and it is soft.
2. **The objective is solved in stages.** Each term reads 1.0 at full fill, so the weights put 0.65 on cost and storage against 0.35 on service. A single weighted sum would therefore order for only 5 of the 69 SKUs that need stock, even with unlimited allocation (checked on the dry-run data): the mirror image of the old `Q = ROP`. So the LP first orders as much of the need as the allocation and warehouse allow. Next it meets the cover rule as far as it can. Only then do the 0.45 / 0.35 / 0.20 weights pick who comes up short. Each stage keeps the earlier ones at their optimum.
3. **The need is filled in layers.** The first dry run treated each SKU's need as one block. It ordered 0 for SKUs holding less than a month's forecast (e.g. 64953872: 12 on hand, 315 forecast), because an LP cuts whole SKUs at a corner. Now a short allocation cuts the stock above safety stock first, then safety stock, and this month's demand last. The weights still decide which SKUs lose stock within the layer being cut. Two tests pin this.
4. **The allocation uses calendar 2025**, the same basis as the dashboard's allocation card. The 73 SKUs sold 13,903,319 pieces in 2025, so 105% is 1,216,540 a month. The plan's ≈ 1.18M came from the trailing 12 months.
5. **Cost per piece is per SKU**, from the stock file: unit cost per case ÷ pack size, the same source as the ₱25 median. It prices the order and values stock for the cover rule. All 73 SKUs have one, so the ₱25 placeholder is only a fallback.
6. **Priority when the allocation is short** is each SKU's share of the 73 SKUs' 2025 revenue.
7. **Three SKUs aren't in the March stock file** (64971078, 69731884, 65071335), so they count as 0 on hand. The file lists no zero-stock rows (0 of 785), and all three had dwindling stock in earlier months.
8. **Flags.** `--supplier-ceiling` is gone: the allocation comes from `--allocation-pct`. `--protection-days` is gone: the window is `--review-days` + `--lead-days`. New: `--cover-rule` and `--csv`.

## Done since this was first written

These needed no one's sign-off and write nothing to the database:

| Commit | What |
|---|---|
| `c63b1d9` | **Step A.** The stock card now reads "≈ 3.0 weeks of sales in stock · SSM policy: keep 3 weeks". It is always measured against the last 12 months of sales, whatever date range is on screen; before a follow-up commit it moved between 3.0 and 3.5 with the range. The "blanket 3-week rule" card is relabelled as SSM's own policy. A new **Sales vs supplier allocation** card applies Sir Abe's rule per principal (see §7 for its numbers). The dashboard's forecast card now uses the **same MASE < 1 gate as `run_lp.py`** (73 SKUs; it was MAPE < 20, with 19). Combined peso totals under All principals are labelled as mixing VAT-inclusive (Unilever) and VAT-exclusive (Del Monte) figures. |
| `71b6f9a` | **The `--dry-run` fix** from Step B. The dry run now runs as one psycopg2-managed transaction, made `READ ONLY` by its first statement. Before, it used `set_session(readonly=True, autocommit=True)`, which leaks through the :6543 pooler. Checked on the live pooler: a write inside is refused, and fresh pooled connections afterwards read `default_transaction_read_only = off`. A real run is unchanged (autocommit, same UPSERT). |
| `d143a8b` | Unrelated cleanup: the leftover `GET /bo-monitoring` route, its schema and its test. The Bad Order ETL and `BO_Monitoring_View` are untouched. |
| *(uncommitted)* | **Step B** (files in §4) and the **Step C** dry run (§8). 711 tests pass, 8 skipped. |

Re-checked the same night: the live LP cycle is still the 2026-08-24 run, a median 24.9× the current forecast, so everything in §1 still stands.

---

## 1. Why

In our meeting, Sir Abe (SSM) told us:

- **Ordering:** purchase orders go to Unilever every week, and delivery takes 2–3 days. Del Monte is similar, with near-daily deliveries before Christmas.
- **Allocation:** the yearly allocation is last year's total sales × 103% (minimum), 105% (mid) or 108% (maximum). It is revised in Q4, depending on the market.
- **Weekly allocation:** SSM can add to it or cut it freely, as long as it keeps **3 weeks of sales in stock**. His example: ₱48M a month × 3 ÷ 4 = ₱36M in the warehouse.

The LP before this rework did none of this:

- **Stock on hand is ignored.** It orders `Q_i ≥ ROP_i = forecast + SS` for every SKU.
- **Safety stock is very thin.** It covers only 1 business day (`--protection-days 1`).
- **There's no real allocation.** The supplier ceiling is a placeholder that never binds.
- **The LP has no trade-off to make.** Costs are flat (`unit_price` is empty), so every coefficient is positive and it always returns `Q_i = ROP_i`.
- **The live cycle is stale.** Cycle 2026-03 was solved on 2026-08-24, against forecasts that were rewritten on 2026-09-21. Its `rop_i − ss_i` is a median 24.9× the current forecast, and the Reorder page shows a total order of 86.9M pieces.
- **The real allocation would make it infeasible.** For the 73 planned SKUs, forecast + SS comes to about 1.57M pieces a month, against an allocation of about 1.19–1.25M (103–108% of 2025, §7).

---

## 2. What stays the same

- **Forecasting** is unchanged: monthly forecasts, MA3 / TSB / XGBoost+MA3 with per-bin routing, the MASE < 1 gate, and Category A from the latest ABC run. That is the same 73 planned SKUs.
- **The safety-stock formula** stays: `SS = 1.28 × σ_monthly / √business_days × √window`. The window is now the review period plus the lead time (8 business days). Its daily-independence assumption is stated with every plan (§9).
- **The solver and weights** stay: PuLP/CBC, with weights 0.45 / 0.35 / 0.20. These are `backend/lp_cycle.LP_WEIGHTS`, and a test pins them to `lp.py`. What changes is where they act (§3).
- **The monthly planning cycle** stays (`planning_cycle_date` = the forecast month).
- **The `lp_recommendation` schema** stays, so **no migration** is needed. The columns are reused:
  - `q_i` = the month's order
  - `rop_i` = the target stock
  - `ss_i` = the safety stock
- **The UPSERT behaviour** stays:
  - pending rows are replaced;
  - accepted and dismissed rows are kept;
  - older cycles are hidden on the read side (`lp_cycle`), never deleted.
- **Your work stays as it is:**
  - the ABC `method = 'single'` pins (f2cb309), guarded by `tests/test_abc_reader_pinning.py`. One allowlist entry is pruned there: `lp.py` no longer names `ABC_Classification`, and the test itself says to prune such an entry. The guard is unchanged;
  - the principal scoping in `recommendations.py` / `dashboard.py` (fd4dded), guarded by the backend tests;
  - the ETL and loaders, migrations 0028–0030, the product-master cleanup and synthetic v2. None of these files are edited.

---

## 3. What changes

| Area | Before | Now (built in Step B) |
|---|---|---|
| Order quantity | `Q_i ≥ ROP_i` (forecast + SS), ignoring stock on hand | `0 ≤ Q_i ≤ need_i`, where `need_i = max(0, forecast_i + T_i − stock_i)` |
| Target stock `T_i` | none | statistical: demand over the review period + lead time (1.6 weeks), plus `SS_i`. With `--cover-rule per-sku`, at least 3 weeks of sales |
| SSM's 3 weeks | not modelled | `aggregate` (the default): the planned month-end stock, valued at cost, must cover 3 weeks of these SKUs' sales at cost (soft). `per-sku`: a floor under each `T_i` |
| SS window | 1 business day (`--protection-days`) | 8: `--review-days 5` + `--lead-days 3` |
| Supplier ceiling | placeholder, never binds | the planned SKUs' 2025 sales × `--allocation-pct` ÷ 12 (placeholder: 105%) |
| When the allocation is short | infeasible (hard `Q ≥ ROP`) | the need is filled in layers, then the cover rule applies, then the weights pick who is cut (departures 2–3 above) |
| Costs | one flat fallback (`unit_price` is empty) | each SKU's cost per piece, from the stock file |
| Warehouse | `ΣQ ≤ W` | `Σ(stock + Q) ≤ W`, as if the month's deliveries all arrived at once |
| Display | "ROP" / "LP QTY" | Step D: "Target stock" / "Order this month", split into weekly POs |
| Dashboard | — | **Done (`c63b1d9`):** weeks of cover vs the 3-week target; sales vs allocation (103 / 105 / 108%); the "3-week rule" card relabelled as SSM's policy |

**The three behaviours are pinned by tests** (`tests/optimization/test_lp.py`):

1. With enough allocation, every SKU ends the month at its target.
2. With a short allocation, the stock above safety stock goes first, and the weights pick which SKUs lose it.
3. An overstocked SKU orders 0.

**Worked example: 69767334** (from the dry run at 105%)

| Quantity | Aggregate rule (default) | Per-SKU floor |
|---|---|---|
| Monthly forecast | 30,771 (≈ 7,077 a week) | same |
| Safety stock (8 business days) | 8,902 | same |
| Target stock | 20,225: 1.6 weeks + SS, i.e. 2.86 weeks of sales | 21,230: the 3-week floor |
| Stock on hand | 9,081 | same |
| Need | 41,915 | 42,920 |
| This month's order | **41,915** | **30,592**: short by 12,328, its stock above safety stock (§8) |
| Weekly POs | first ≈ 18,220, then ≈ 7,077 a week | — |

The first version of this plan had 3 weeks = 21,303, at 4.33 weeks a month. The LP now uses the dashboard's 4.35. Today the live row for this SKU shows 1,276,246.

---

## 4. Files touched and not touched

Everything is done on `fix/audit-2026-09-29` first.

**Step A (dashboard), done in `c63b1d9`:**
- `backend/routers/dashboard.py` (new `allocation` and `vat_note` fields; portfolio gate MASE < 1)
- `backend/routers/policy_comparison.py` (wording only)
- `frontend/src/components/Dashboard.jsx`
- `frontend/src/components/Charts.jsx` (new `AllocationWidget`)
- `tests/backend/test_dashboard.py`

**Step B (the model), done, uncommitted:**
- `analytics/optimization/lp_inputs.py` (new): the placeholders, the weeks-per-month convention, the two cover rules and the safety-stock assumption. It has no pulp import, so the API can read it.
- `analytics/optimization/lp.py`:
  - `SKUInput` now carries the month's demand, target stock, stock on hand, safety stock and revenue weight.
  - New `target_stock()`, `net_need()` and `fill_layers()`.
  - `build_lp_model` / `solve_lp` run the stages described in §3.
- `scripts/run_lp.py`:
  - It reads stock in pieces (the `backend/stock_units.py` SQL), each SKU's cost per piece, and 2025 sales.
  - `plan_cycle()` holds the planning and needs no database, so tests drive it directly.
  - Flags as in departure 8, plus `--csv`.
- `scripts/build_preview_outputs.py`: the same `plan_cycle`, with the same defaults. Checked by building into a scratch folder: it still reproduces the live forecasts and writes 75 LP rows. The repo's preview files are not rebuilt; that is part of Step E.
- `backend/lp_cycle.py`: `lp_model_info()` adds `inputs`, `inputs_are_placeholders` and `safety_stock_assumption`. This moved here from Step D, per Yuan. No page shows these fields yet.
- Tests:
  - `tests/optimization/test_lp.py` and `tests/optimization/test_run_lp_script.py`.
  - `tests/backend/test_recommendations.py`: pins `lp_model_info` to the placeholders, and the weeks convention and the 3 weeks to the dashboard's.
  - `tests/test_abc_reader_pinning.py`: one stale allowlist entry pruned.
- `BACKEND_GUIDE.md`: the list of `lp.py` functions.

**Step D (wording and one comparison):**
- `frontend/src/components/ReorderRecommendations.jsx`, `ReorderModal.jsx` and `ABCClassification.jsx`: target stock, order this month, weekly POs. Also show `lp_model_info`'s placeholders and the safety-stock assumption.
- `backend/routers/recommendations.py` (the weekly-PO split)
- **The SSM 3-week policy card** (`backend/routers/policy_comparison.py`, and the sums in `dashboard.py`) compares `ss_i` with 3 weeks of sales. After Step E, that would claim a 35% cut (486k against 749k pieces) that the full target doesn't make (885k, §8). The card must compare the target stock (`rop_i`) instead.
- The same card's assumption text (`Charts.jsx`) and `policy_comparison.py`'s blocked reason still name `--protection-days` and 1 business day.

**Not touched:**
- `analytics/etl/*`
- `analytics/db/migrations/*`
- `scripts/apply_*`
- `scripts/build_synthetic_v2_clean_pool.py`
- `scripts/run_canonical_load.py`
- `scripts/run_baseline_forecast.py`
- the ABC scripts
- any fact, dimension, ABC or forecast table

---

## 5. Database impact

- **Steps A–D** write nothing to the database; they only read it. Each of the six Step C dry runs ran as one `READ ONLY` transaction through the pooler, and none was committed.
- **Step E** is the only write, and only after your OK:
  - `run_lp.py` UPSERTs into `lp_recommendation` for cycle 2026-03.
  - Pending rows are replaced; accepted and dismissed rows are kept.
  - Older cycles are untouched, only hidden in the app.
  - There is no schema change and nothing is deleted.
  - A full backup comes first: `python -m scripts.backup_everything`.
- **Only `run_lp.py` writes `lp_recommendation`.** `apply_product_master_cleanup.py` only reads it, for its `NOT EXISTS` reference check. New rows only reference real Category A products, so the category-row cleanup is unaffected.

---

## 6. Steps

| Step | What | Writes to the DB? | Status |
|---|---|---|---|
| A | Dashboard: weeks-of-cover card, sales-vs-allocation card, relabel the 3-week card | No | **Done** (`c63b1d9`) |
| B | Rework `lp.py` / `run_lp.py` / the preview builder, add tests | No | **Done** (uncommitted) |
| C | Dry run with the placeholders | No | **Done** (§8); review together |
| D | Page wording; the policy card compares the target stock | No | after the review |
| E | Real run for cycle 2026-03, hide the leftover old rows, rebuild the preview files, re-check every page | **Yes** (`lp_recommendation` only) | after the review + a backup |
| F | Replace the placeholders with Sir Abe's figures | — | his answers |

---

## 7. Placeholders until Sir Abe confirms

All of them live in `analytics/optimization/lp_inputs.PLACEHOLDERS`. **They are not SSM's figures**, and the manuscript must not cite them as such.

| Input | Placeholder | Basis |
|---|---|---|
| Allocation % | 105% | The midpoint of his 103–108%. On the 73 SKUs' 2025 sales (13,903,319 pieces), that is 1,193,368 / **1,216,540** / 1,251,299 pieces a month at 103 / 105 / 108%. Forecast demand is ≈ 1.09M a month (≈ 250k a week). |
| Review period / lead time | 1 week / 3 days | He said weekly POs, delivered in 2–3 days. Hence an SS window of 8 business days. |
| Target | 3 weeks of sales | His rule |
| Cover rule | aggregate | Yuan's reading of Sir Abe's peso example; not yet confirmed (§11) |
| Warehouse capacity | 3,800,000 pieces | The most stock held: 3,816,842, in Jan 2025 |
| Purchase cost | per SKU, from the stock file; ₱25 only as a fallback | The fallback is the median of the 73 SKUs (₱24.55) |
| Storage cost | ₱0.50 per piece per month | 2% of ₱25 a month (≈ 24% a year) |

What the dashboard's allocation card shows with this rule (in pesos, from the sales data):

| Principal | Basis | 105% a month | This year so far |
|---|---|---|---|
| Unilever | 2025 sales ₱393.4M (12 months, incl. VAT) | ₱34.4M | 2026 averages ₱32.5M a month over 2 months, **95%** of the mid pace |
| Del Monte | 2024 has only 2 months of sales on record | — | shown, but the card calls the basis partial and gives no percentage |

---

## 8. Step C dry run (2026-09-29), for the joint review

Cycle 2026-03, the 73 planned SKUs, with the placeholders above. The per-SKU plans are in `reports/lp_dry_run_2026-09-29/plan_<rule>_<pct>.csv`.

| Pieces a month | Aggregate 103% | Aggregate 105% | Aggregate 108% | Per-SKU 103% | Per-SKU 105% | Per-SKU 108% |
|---|---|---|---|---|---|---|
| Allocation | 1,193,368 | 1,216,540 | 1,251,299 | 1,193,368 | 1,216,540 | 1,251,299 |
| Need | 1,255,471 | 1,255,471 | 1,255,471 | 1,290,244 | 1,290,244 | 1,290,244 |
| Ordered | = allocation | = allocation | = allocation | = allocation | = allocation | = allocation |
| Short | 62,103 | 38,931 | 4,173 | 96,875 | 73,703 | 38,945 |
| SKUs short | 45 | 40 | 18 | 48 | 43 | 37 |
| … of the top 10 by revenue | 0 | 0 | 1 | 5 | 5 | 4 |
| Month-end stock, weeks of sales at cost | 3.00 | 3.00 | 3.23 | 2.47 | 2.52 | 2.79 |
| Month-end stock, weeks of sales in pieces | 3.48 | 3.57 | 3.71 | 3.48 | 3.57 | 3.71 |

The same in all six runs:
- total safety stock is 485,541 pieces;
- no SKU is planned below its safety stock, or to run out;
- 4 SKUs are overstocked and order 0;
- stock + orders use 1.95–2.01M of the 3.8M-piece warehouse, so capacity never binds;
- all 73 SKUs get their cost per piece from the stock file;
- 3 SKUs count as 0 stock (departure 7).

What it shows:

1. **The order moves with the allocation %.** The allocation binds at 103, 105 and 108% in both versions: even at 108%, the aggregate version is 4,173 pieces short of its need.
2. **The aggregate rule meets SSM's 3 weeks; the per-SKU floor doesn't.**
   - Aggregate needs 34,773 fewer pieces, because the floor lifts 36 of the 73 targets to 3 weeks.
   - Aggregate ends the month at exactly 3.00 weeks at cost at 103% and 105%, where the rule binds.
   - The per-SKU version can't fund all its floors, and it ends at 2.5–2.8 weeks at cost.
3. **The SKUs that cost the most per piece come up short.**
   - The allocation is in pieces, and the weights put 0.45 on cost against 0.35 on service. So a ₱60 piece is trimmed before a ₱5 one. The short SKUs' median cost is ₱46–107 a piece, against ₱24.55 across all 73.
   - In the per-SKU version at 105%, that reaches 5 of the top 10 by revenue. 69767334 keeps its month of demand and its safety stock, but loses the 12,328 pieces above them.
   - The aggregate version protects them, because its rule counts stock at cost.
   - If Sir Abe's allocation is in pesos, this ranking changes.
4. **The statistical targets hold more than 3 weeks in total:** 3.26 weeks of sales at cost, or 3.55 in pieces.
   - 36 SKUs are below 3 weeks: 34,772 pieces, ₱0.46M under.
   - 37 are above: 170,912 pieces, ₱1.17M over. These are the volatile SKUs; 69668140's target is 11 weeks.
   - Safety stock is about half the median target.
   - So with these placeholders the model moves stock from steady SKUs to volatile ones and adds about ₱0.7M overall, rather than freeing capital.
   - The safety-stock ruling (the window and the daily-independence assumption) moves this number the most.
5. **"3 weeks" depends on the unit.** Today these 73 SKUs hold 3.04 weeks of sales in pieces, but only 2.23 weeks at cost (₱6.1M), because the cheaper items are the better-stocked ones. §11 asks Sir Abe whether he means pieces, cost or selling price.

**To decide together:**
- Which cover rule goes into Step E, until Sir Abe answers? The runs favour `aggregate`.
- Whether the staged objective and the layered fill are OK (departures 2–3).
- Whether cutting the priciest pieces first is acceptable, or we wait for the pesos-or-pieces answer.
- Whether the three SKUs counted as 0 stock are OK.
- What finding 4 means for what we claim about savings.

---

## 9. The formulation, for Thea and Sir Catubag

Yuan asked that Thea (manuscript) and Sir Catubag see this. The LP changes from "`Q_i ≥ ROP_i`, minimise one weighted sum" to the model below.

**Per planned SKU `i`** (Category A, forecast MASE < 1), for the month's cycle, in pieces:
- `w_i = F_i / 4.348`: weekly demand, from the month's forecast `F_i`
- `SS_i = 1.28 × (σ_monthly,i / √(business days per month)) × √(R + L)`
  - This **assumes demand is independent from one day to the next.** Monthly data can't test that (66% of months are zero), and it awaits the safety-stock ruling.
- `T_i = w_i × (R + L) / 5 + SS_i`: the target stock
  - Per-SKU variant: `max(T_i, N × w_i)`
- `need_i = max(0, F_i + T_i − S_i)`, where `S_i` is stock on hand
  - It splits into three layers: this month's demand `max(0, F_i − S_i)`, then safety stock, then the rest of the target.

**Decision variable:** `0 ≤ Q_i ≤ need_i`, the month's order, released as weekly POs.

**Constraints:**
- warehouse: `Σ_i (S_i + Q_i) ≤ W`
- allocation, per principal `p`: `Σ_{i∈p} Q_i ≤ A_p`, where `A_p = a% × last year's sales_p ÷ 12`
- aggregate variant only: `Σ_i c_i (S_i + Q_i − F_i) + z ≥ N × Σ_i c_i w_i`, with `z ≥ 0`. This is SSM's 3 weeks at cost, as a soft constraint.

**Objective**, lexicographic (each stage holds the earlier ones at their optimum):
1. maximise the pieces filled in each layer, in order: demand, then safety stock, then the rest of the target;
2. minimise `z`;
3. minimise `0.45 × TC/TC* − 0.35 × SL + 0.20 × SC/SC*`, where:
   - `TC = Σ c_i Q_i`
   - `SC = Σ h Q_i`
   - `SL = Σ r_i Q_i / Σ r_i need_i`
   - `*` marks the value at full fill.

**Where the inputs come from:**
- `c_i` is the stock file's cost per piece.
- `r_i` is the SKU's share of 2025 revenue.
- `R`, `L`, `N`, `a`, `W` and `h` are the §7 placeholders. The manuscript must not present them as SSM's figures.

---

## 10. Known limits

- **Stock counts are monthly.** So the plan is monthly, split into weekly POs, and the March snapshot is taken as the month's opening stock. Real week-by-week re-planning needs weekly stock or purchase receipts.
- **Unilever has no purchase records.** So the allocation is estimated from last year's sales, per Sir Abe's rule.
- **Del Monte has no SKU-level sales.** It is still not planned.
- **Only the 73 SKUs with reliable forecasts get an LP row,** as before. The other 59 Category A SKUs don't.
- **The allocation is in pieces** until Sir Abe says otherwise, and that drives who is cut (§8, finding 3).
- **An LP cuts at corners.** Within the layer being cut, the lowest-ranked SKUs lose all of it before the others lose any.
- **The warehouse check** compares only the 73 SKUs with the whole warehouse's peak, and it counts the month's deliveries as if they all arrived at once. It is far from binding either way.

## 11. Questions for Sir Abe (before Step F)

- **The ₱48M example:** is that all principals, or Unilever only? The Unilever data runs ≈ ₱32–33M a month, including VAT.
- **The allocation:** is it set in pesos or in cases/pieces, and in total or per SKU? Can SSM share the weekly allocation list?
- **"3 weeks of sales": is it a warehouse-wide total, or per SKU?** (Yuan's question; §8 runs both.)
- **"3 weeks of sales": is it counted in pieces, at cost or at selling price?** Today's stock of the 73 SKUs is 3.0 weeks in pieces but 2.2 at cost.
- **2026:** which % applies?
