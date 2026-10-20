# Demonstration data (schema `demo`)

Everything generated that the app can display lives in schema `demo`. It is synthetic, labelled, and off by default.
Approved by Kelvin on 2026-10-15 (Sir Catubag informed); extended by Kelvin on 2026-10-16 first to stock and the
Del Monte order plan (migration 0056), then the same day to DAIRY, the Unilever forecast wiring, both principals'
order plans, dead stock and policy comparison (migration 0057) — the standing instruction behind the second pass:
with the toggle on, no card is empty and no endpoint answers "not available" for either principal; a gap is
generated and labelled instead. The rule is in `CLAUDE.md` hard rule 2; this file is the detail. Sales/forecast
figures for the first pass were queried 2026-10-15 (migrations 0052-0055); everything else was queried live
2026-10-16 (migrations 0056-0057).

**Read first: five rules**
1. Unilever gaps render as **zero** and are never filled.
2. Del Monte gaps are **filled and labelled** (`interpolated`, `bridged`, `forward_filled`, `backcast`).
3. `demo.*` is the **only** display source for generated data. The older `synthetic_v2` rows are retired for
   display (nothing deleted).
4. Del Monte stock on hand has **no real anchor at all** (every row is generated — see §8): it is a different
   kind of generated data than sales, not a copy or an interpolation of anything real.
5. Unilever's demonstration order plan uses **real** stock on hand (§11) — Del Monte's uses **generated** stock
   (§10). Not the same confidence; every row's `demonstration_note` says which.

## 1. What is in `demo.*`

| Run | Principal | Grain | real_copy | interpolated | bridged | forward_filled | backcast |
|---|---|---|---:|---:|---:|---:|---:|
| 7 `demonstration` | Del Monte | category | 747 | 272 | 978 | 6 | 2,147 |
| 8 `demonstration_unilever` | Unilever | SKU | 24,906 | 0 | 0 | 0 | 12,816 |

- **Del Monte:** 82 of the 87 real category paths are covered. 5 are left out entirely because they have one real
  month and so no coefficient of variation to generate from: `/FIBER/PROMO`, `/GOURMET SPAG SAUCE/PROMO`,
  `/MIXED FRUITS/TODAY'S`, `/OYSTER SAUCE/BASE`, `/TOTAL 100% JUICES/ACE - PROMO CANNED`. Every month 2021-01..2025-12
  has rows (60 of 60). Backcast splits 1,560 (65 categories, `anchor_override = false`) and 587 (17 categories,
  `anchor_override = true`). Bridged covers 77 paths. Forward-filled covers 1 category (DAIRY, 6 months — §13).
- **Unilever:** 534 of 1,807 SKUs are back-cast. 1,273 are not: 1,214 first sold after 2023-01 (genuine launches,
  never back-cast), 59 have fewer than 3 months with sales. No in-span gap is filled.
- Tables: `demo.run`, `demo.dm_category_sales`, `demo.dm_category_param`, `demo.dm_forecast`, `demo.dm_excluded`,
  `demo.unilever_sku_sales`, `demo.backcast_excluded`, `demo.dm_category_stock`, `demo.unilever_sku_forecast`,
  `demo.dm_category_lp`, `demo.unilever_sku_lp`, view `demo.dm_monthly_total`.
- Every row carries `is_demo = true` and `fill_source = 'synthetic_dm_pipeline_demo'` (CHECK constraints). No table
  has an accuracy column (mape / mase / wape) or a confidence band; `tests/demo/test_demo_schema.py` fails if one
  appears.
- Migrations: 0052 schema, 0053 Unilever + back-cast, 0054 `anchor_override`, 0055 canonical total, 0056 stock +
  predictive + prescriptive, 0057 `forward_filled` + the Unilever order plan + `blank_capture_filled`.
- Rebuild: `python -m scripts.build_dm_demo --write --replace` and `python -m scripts.build_unilever_demo --write
  --replace` (sales/stock/forecast), then `python -m scripts.run_lp --source demo --principal delmonte --write`
  and `--principal unilever --write` (the order plans). Seed 20261015, recorded in `demo.run`; the same series
  regenerates identically.

## 2. The five Del Monte sales origins

| origin | meaning | is it extrapolation? |
|---|---|---|
| `real_copy` | a real month, copied | no |
| `interpolated` | between two real months of the same series (anchored on both sides) | no |
| `bridged` | across the 2024-03..2025-02 taxonomy change: a pre-2025 Del Monte path carried forward from its last real month through 2025-02. Real data on one side only | **yes** |
| `forward_filled` | a LIVE 2025 category (not a pre-2025 path) whose real data simply stops before the window ends, carried forward flat at its own level — not a taxonomy change, so never `bridged` (migration 0057, §13) | **yes** |
| `backcast` | 2021-01..2022-12 (and, for Del Monte series first seen later, up to the month before their first real month). No real data on either side | **yes** |

**Bridged and backcast are extrapolation.** They are flat at the series' own level with seeded jitter, no trend:
any growth or decline before or after the data would be invented direction. They are generated for visualisation
only and are never a result.

- **Jitter** is a multiplier on each series' own coefficient of variation: `sd = 0.25 x CV x level`. It is not a
  fixed value. Measured: generated CV is 0.24 x the real CV (median; p10 0.20, p90 0.29) and correlates 0.96 with
  it, so steady products wobble little and volatile ones more. The 0.25 damping is declared, not measured, and
  means generated series are about a quarter as volatile as the real ones.
- **Anchor override (Del Monte only).** Unilever's back-cast requires the first real month to be 2023-01 (a SKU first
  sold later is a launch; back-casting it would invent that it existed). Del Monte's does not: its five 2025
  categories (BEVERAGE, CULINARY, DAIRY, FRUITS, INNOVATION) and 12 sub-categories first seen after 2023-01 are a
  relabelling of a business that existed in 2021. Those back-cast rows stay `origin = 'backcast'` and carry
  `anchor_override` (API: `generated_before_first_observation: true`).

## 3. The canonical-series rule (Del Monte totals)

The pre-2025 paths and the 2025 categories are the same business in two vocabularies, and both are generated over
2023-01..2025-02. One canonical series per month: **the old paths through 2025-02, the five live categories from
2025-03.** A back-cast row generated before its series' own first observation (`in_canonical_total = false`) is
excluded from every aggregate and served only when that single series is charted on its own.

Without the rule a 2023-01 total read **₱15.10M against a real ₱6.13M**; canonical is ₱6.14M. Aggregate only through
`demo.dm_monthly_total` / `GET /demo/totals`, in pesos (Del Monte's quantity unit is unconfirmed). A build-time
check and `tests/demo/test_canonical_total.py` fail if a month in 2023-01..2025-02 exceeds real + interpolated +
bridged.

## 4. The switch

`DM_DEMO_ENABLED` defaults **OFF** (unset, empty, or anything but `1/true/yes/on`). With it off every demo route is
a plain 404, every endpoint below behaves exactly as it did before this feature existed, and `X-Data-Mode: preview`
reads real data only (it is a separate, older mechanism — §4a). Routes (all `forecast.view`):
`GET /demo/series?principal=&key=`, `GET /demo/index?principal=`, `GET /demo/totals`; also wired into:

| Endpoint | Del Monte (toggle on) | Unilever (toggle on) |
|---|---|---|
| `GET /forecast/{sku}?principal=&category=` | demo series + MA3 forecast | demo series + MA3 forecast (§9) |
| `GET /recommendations?principal=` | `demo_forecasts`, `demo_stock`, `order_plan` (own payload, real items stay `[]`) | `demo_unilever.order_plan` ADDED beside the real items (§11) — never replaces them |
| `GET /dashboard` | `demonstration` block: `index`, `monthly_totals`, `forecasts`, `stock`, `order_plan`, `policy_comparison`, `dead_stock` | unaffected (Unilever's real dashboard cards are already populated) |

Every demo row returns `demonstration: true` and `demonstration_note`; the payload has `data_source:
"synthetic_demonstration"` (inside the `demonstration` / `demo_unilever` block, whose other fields are real).

### 4a. This is NOT the older `X-Data-Mode: preview` mechanism

`backend/data_mode.py` is a separate, older feature (Audrey, 2026-09-23): a header-activated five-year dashboard
view, file-backed for predictive/prescriptive (`scripts/build_preview_outputs.py` → `reports/preview/app_*`).
It also reads `demo.unilever_sku_sales`' back-cast rows for its descriptive recompute, and is gated on
`DM_DEMO_ENABLED` too, but it is activated by the `X-Data-Mode: preview` header, not read by anything in this
file's table above, and this session did not change it. Do not confuse the two: this file is about
`DM_DEMO_ENABLED` alone, with no header needed.

## 5. What changed on screen when `synthetic_v2` was retired

- Preview with the flag **off** is real data only: 2021-22 is empty on the toggle, and those points return
  `sales: null` with `sales_reason: no_data_recorded_before_2023`.
- Preview with the flag **on** reads `demo.*`. Unilever 2021-22 is flat (monthly-total swing 2.6%, against 27% in
  `synthetic_v2` and 18% in the real 2023-01..2026-02 data) and every back-cast SKU is present from 2021-01
  (`synthetic_v2` ramped 393 SKUs in 2021 to 486 in 2022). Pesos: 2021 ₱280M against ₱186M, 2022 ₱282M against
  ₱273M. There is a visible step at 2023-01 (₱23.9M in 2022-12 to ₱31.7M real) because the back-cast sits at each
  SKU's own mean. **This is by design. Do not "fix" it.**
- The file-backed preview forecasts and LP (built on the retired rows) are no longer served.
- The filled sales rows in `mart.sales_mart` (3,130 `synthetic_category_split`, 4 `synthetic_v2_gap`) and the
  generated ones (914 Del Monte, the Unilever 2026-03..08 placeholders) are no longer served: no estimated sales
  points on the dashboard chart, and `/dashboard/product-sales` for Del Monte is empty.
- **2026-10-16 (B1):** two siblings of this retirement were missed the first time, because they read the fact
  tables' `is_demo`/`fill_source` straight into `mart.flow_month` and `mart.inventory_mart` instead of going
  through `mart.sales_mart`. `backend.marts.flow_by_period` was still turning filled `returns` rows (always
  `synthetic_v2` / `synthetic_v2_gap` / `synthetic_rate_transfer` / `synthetic_branch_adjacent` — `salesreturn_fact`
  has no other fill_source) into `returns_estimated`, so with the demo switch off Unilever's whole Returns line
  (it has no real returns at all) was 100% synthetic for every month 2021-01..2026-02, and Del Monte's was
  synthetic for 18 months. `estimated_stock_by_period` was doing the same for `stock_on_hand_estimated`, both
  principals, worse in preview (adds `generated`/`synthetic_v2`). Both are retired now: `flow_by_period` never
  estimates `returns` (it still does for `estimated_receipts` — that one is a genuine derived figure,
  `derived_receipt_fact`, not synthetic placeholder data, and keeps working exactly as before); 
  `estimated_stock_by_period` always returns `{}`, same retirement as `estimated_sales_by_period` above. Neither
  returns/stock chart line has a `demo.*` replacement wired in — a gap just shows nothing, not a wrong number.

## 6. Why Unilever is not filled

Unilever's sales listing has no row for a month a product sold nothing. The evidence that these gaps are real
zero-sale months and not missing records (`Unilever_SKU_Demand_Fact_Real`, 4,473 in-span gap-months across 714 of
1,807 products):

- gap rate **38.3%** in the slowest-moving volume quartile against **5.7-9.5%** in the other three;
- gaps come in long contiguous runs (4 of 526 multi-gap products have a regular interval);
- no clustering in real time (8-22% every month), so no collection outage.

They are rendered as **zero** with `reason: "no_sale"`. Do not fill them. **Provisional** until SSM confirms in
writing that its listing omits zero-sale months. Del Monte is different: 226 of its 272 gap-months fall in months
where every category is absent at once (2023-07, 10, 12 and 2025-05, 07, 10, 11): a collection failure.

## 7. Forecast accuracy is the one card that stays empty, and cannot be filled

Safety stock, reorder point, order plan, dead stock and policy comparison are now filled with demo-path values
(§§8-13) under Kelvin's 2026-10-16 standing instruction. **Forecast accuracy (mape / mase / wape, a confidence
band) is different and is NOT filled**: CLAUDE.md hard rule 2's sanctioned exception explicitly forbids an
accuracy metric anywhere in `demo.*` (no table may carry one; `tests/demo/test_demo_schema.py` enforces it), and
the demonstration never calls `evaluate_sku` or `backtest`. Scoring a generated forecast against generated
actuals would not measure anything real, so there is no honest number to generate — this card has no demo value,
on purpose, not an oversight.

## 8. Del Monte stock on hand (migration 0056)

There is **no real Del Monte stock count at category grain anywhere in SSM's data**, confirmed live 2026-10-16:
`Inventory_Fact_Real` for Del Monte is SKU grain only (597 products, 5,541 rows, 2023-01..2025-12) and 0 of those
597 SKU rows carry a `category_path` (it is NULL on every one). So `demo.dm_category_stock` has no `real_copy`
origin at all — every row's origin is `generated_months_of_cover`.

Method (`analytics/demo/stock.py`): a seeded draw centred on SSM's own stated policy, "about 3 weeks of sales in
stock" (Sir Abe; `analytics.params.POLICY_COVER_WEEKS`, the same constant the real LP's `--target-weeks` default
uses — 3 weeks / `WEEKS_PER_MONTH` ≈ 0.690 months of cover), multiplied by that category's own demonstration
demand for that month (whatever origin the sales generator produced).

**Spread (`STOCK_SPREAD = 0.45`, declared 2026-10-16), not tied to demand CV.** The first version (2026-10-15)
jittered the draw by each category's own sales CV, the same way sales interpolation does. That made the order
plan pointless: every category's cover sat so close to the 3-week centre that 3 of the 4 forecastable categories
always ordered 0 (§10 as it stood before this fix). Demand variability and STOCKING variability (replenishment
timing, how close the last delivery landed to target) are different things, so the spread is now a fixed,
declared 45% of the centre, independent of each category's CV — wide enough that a meaningful share of draws
land below their reorder point, which is the entire point of generating a stock figure for a plan to act on.

Live: 4,150 rows, 82 categories, run_id 7 (the same run as the Del Monte sales/forecast build —
`python -m scripts.build_dm_demo --write --replace` now writes stock too).

## 9. Unilever demonstration forecast (migration 0056/0057) — wired 2026-10-16

A one-step MA3 per SKU (`scripts/build_unilever_demo.py`), over each SKU's own last 3 real months — real sales
copied plus real in-span zeros, the same window `backend/series_gaps.unilever_points` renders — never the
back-cast. **Wired into `GET /forecast/{sku}?principal=unilever` behind `DM_DEMO_ENABLED`** (`backend/demo_data.
unilever_forecast`): the chart (`demo.unilever_sku_sales`) and the forecast now come from the same source, as
asked. Unilever's real `Forecast_Result` is unaffected and stays what the app serves with the toggle off.

**A single blank-capture month inside the averaging window is now filled — for the average only** (migration
0057): the mean of the window's other two months, flagged `blank_capture_filled`. `demo.unilever_sku_sales`
itself is never touched, so the chart still renders that month blank (`REASON_BLANK_CAPTURE`: "not zero, no value
shown"). Two or more blanks in the window are still left out.

Live, run_id 8: **1,425 of 1,807 SKUs forecast** (29 rescued by the blank-fill, up from 1,396). 382 excluded:
- **378 (304 with 1 real month, 74 with 2) — correct, not a gap, the same bar as the 77 Del Monte paths in §13.**
  A SKU's entire real life (first sale to last) spans too few months to establish a level; most of these are
  either genuine recent launches or short-lived SKUs. Projecting data before a SKU's first real month would
  invent that it existed before it did (the same anchor rule that already keeps Unilever's back-cast from
  projecting a launch backward, §2) — there is no legitimate way to generate 3 clean months for these, so they
  stay out.
- **4 — still excluded**: more than one blank-capture month in the window, too little real signal in 3 months
  to average meaningfully even after one fill.

Measured against `Forecast_Result` (189 Tier A SKUs; the real deployed model is per-SKU, not always MA3 — short-
lived SKUs get MA3, medium TSB, long an XGBoost+MA3 average, `model_params.method`): of 179 SKUs comparable, the
**37 whose real row is `ma3` match with median difference 0.0** (max 459.67, one outlier); the **143 whose real
row uses a different method differ by a median 8.5%** — a model-routing difference, not a demo-generation bug.
"Barely differs from real" holds exactly where the real path also used MA3, and only there.

## 10. Del Monte demonstration order plan (migration 0056/0057)

`analytics/demo/prescriptive.py`: the real formulas (`analytics.optimization.lp.compute_safety_stock` /
`target_stock`, the same `SERVICE_Z` and the same review/lead-day placeholders the real LP applies) over the
demonstration's own forecast (§13) and stock (§8) — **two layers of generated input**, said explicitly in every
row's `demonstration_note`, not just a generic synthetic flag. **No allocation or warehouse ceiling**: Del Monte
has neither an SSM-confirmed yearly allocation nor a warehouse capacity, and reusing Unilever's real
`warehouse_capacity` (3.8M pieces, measured from Unilever's own stock history) would conflate two different
businesses and quantity units (DEC-31: Del Monte's unit is unconfirmed). `order_qty` is the real LP's `net_need`,
`max(0, F + T - S)`: the forecast month's demand **F** plus the target **T**, less the opening stock **S**, floored
(inside T) at `target_weeks` of the month's own demand since there is no portfolio LP here to enforce SSM's "3 weeks
of cover" softly instead. **Corrected 2026-10-20 (audit DATA-6):** it used `max(0, T - S)`, so the month's own demand
was in no order — stock sitting just above target ordered 0 against a full month of sales. Same run_id 7, regenerated
with `run_lp --source demo`; the demand an order has to cover, BEVERAGE 2026-01: F = 3,418.82 was in 0 before
(order 0.00 with S = 3,016.25 and T = 2,358.78), and is in 2,761.35 now.

Live, run_id 7 (same run as the sales/stock/forecast build): **5 rows** — one per category with a forecast
(BEVERAGE, CULINARY, DAIRY, FRUITS, INNOVATION — §13). After the correction **all 5 order**: BEVERAGE 2,761.35,
CULINARY 10,997.05, DAIRY 0.06, FRUITS 2,274.01, INNOVATION 31.27 (before: 0, 0, 0, 15.71, 1.91). Run with
`python -m scripts.run_lp --source demo --principal delmonte --write`; served at
`GET /recommendations?principal=delmonte` (`order_plan.available`) and in `GET /dashboard`'s `demonstration`
block, behind `DM_DEMO_ENABLED`.

## 11. Unilever demonstration order plan (migration 0057) — new 2026-10-16

`scripts/run_lp.py`'s `_run_demo_lp_unilever`: the dominant forecast cohort of §9 (the one `forecast_period` most
SKUs share — 711 of 1,425, forecasting 2026-03) against **REAL** stock on hand and **REAL** cost
(`fetch_stock_counts` / `opening_counts` / `fetch_stock_and_cost` — the exact functions the real LP uses, reading
the real February-2026 count) and **DEMO** sigma (`_sigma_d_for_product` over `demo.unilever_sku_sales`' full
history, including the 2021-22 back-cast). `plan_cycle()` is the unmodified real LP, run with Unilever's own real
placeholders (warehouse capacity, allocation %) — not Del Monte's missing ones. `stock_source = 'real'` on every
row, read from `demo.unilever_sku_lp` (`demo_data.unilever_order_plan`).

Live, run_id 8: **711 planned, 0 skipped** (real February-2026 stock covers the whole cohort). Served at
`GET /recommendations` as `demo_unilever.order_plan`, **beside** the real items — it never replaces them, since
Unilever's real recommendations are good.

**Real-vs-demo (sigma, target stock, order quantity)** — 97 products in both this run and the real
`LP_Recommendation` at planning cycle 2026-03-01 (98 real rows):
- **sigma**: unchanged (< 1% difference) for 54 of 97 (56%); moved by more than 10% — expected, since the demo
  history includes the 2021-22 back-cast and the real one does not — for 42 of 97 (43%, up to 669% on one SKU).
  Median change across all 97 is ~0% (the unaffected majority dominates the median); the real story is this
  bimodal split, not a single "typical" number.
- **target stock (reorder point)**: moves for more SKUs than sigma alone explains, because `target_stock` also
  depends on the forecast (§9 shows only 37 of 179 comparable SKUs share the real path's MA3; most real forecasts
  come from TSB or the XGBoost+MA3 average) — two independent sources of difference, both real.
  `pk=613`/`618`/`667`/`853` are examples where sigma is identical to 4-5 significant figures yet target stock
  still differs by thousands of pieces, purely from the forecast-model difference.
  - `pk=494` (`68690510`): real sigma 11,414.93 → demo 9,006.04; real target 64,562 → demo 53,359.
- **order quantity**: differs by far more than sigma or target stock alone would suggest, for a THIRD reason: the
  demo cohort (711 SKUs) is much larger than the real LP's gated cohort (98 SKUs at this cycle — Tier A with
  `mase < MASE_GATE`), and the LP's allocation ceiling is shared pro-rata across whichever cohort is planned, so
  every SKU's slice of it changes with the cohort size even when its own forecast and sigma do not. This is a
  genuine scoping difference between "every SKU with 3 clean demo months" and "the real Tier A gated pool," not
  a data-generation artifact — disclosed here rather than left to look like noise.

## 12. Del Monte dead stock and policy comparison (migration 0056) — new 2026-10-16

Neither is the real dashboard's own formula verbatim — Del Monte has no ABC tier (it is not in the ABC cohort)
and no `stock_status` flag, so the real `tier_stock` dead-stock bucket has no grain to attach to. Both are
computed instead from the demonstration's own numbers (`backend/demo_data.dead_stock` /
`backend/demo_data.policy_comparison`), served in `GET /dashboard`'s `demonstration` block.

- **Dead stock**: every one of the 82 generated categories (not only the 5 with a forecast — this needs only
  stock and demand, which all 82 have), classed by `months_of_cover` against the same policy centre the stock
  draw and the order plan both use: `dead_stock` above 2x centre, `critical` below 0.5x centre, else `in_stock`.
  Live: **1 dead_stock, 11 critical, 70 in_stock**.
- **Policy comparison**: the real `GET /policy-comparison` formula (`POLICY_WEEKS x forecast / AVG_WEEKS_PER_MONTH`
  against the LP's own target/safety stock), summed over the 5 forecastable categories from `demo.dm_category_lp`.
  Pesos are left out (Del Monte's demo quantity unit has no confirmed price basis either). Live: `target_vs_rule_
  pct` reads ~0% — expected, not a bug: `plan_category`'s `target_weeks` floor and the rule's own weeks constant
  are the SAME declared figure (`POLICY_COVER_WEEKS = 3`), so the two sides anchor to the same number by
  construction.

## 13. Why DAIRY and the 77 pre-2025 paths differ

Both are Del Monte categories whose real data does not reach the window end (2025-12), but only one is extended:

- **The 77 pre-2025 paths (e.g. `/ACE/BASE`) stay excluded from any forecast — correct, not a gap.** They are
  superseded: the January-2025 taxonomy renamed the whole business into 5 new categories, so extending a
  pre-2025 path past 2025-02 (already `bridged` that far) would describe the SAME sales under TWO taxonomies at
  once — exactly the double-count migration 0055 exists to prevent. 64 of the 77 stop at 2024-02 exactly (their
  real data), 13 earlier.
- **DAIRY (a live 2025 category) is different: its real data is just thin, not superseded.** Real months are
  2025-03 (qty 1.21), 2025-04 (qty −1.00, a return), 2025-06 (qty 2.25) — three months, barely above the
  MIN_MONTHS=3 floor fill_series already uses, then nothing through 2025-12 while BEVERAGE/CULINARY/FRUITS/
  INNOVATION keep reporting. Since extending DAIRY does NOT double-count anything (no other series covers
  2025-07..12 for the same business), it is carried forward flat at its own (near-zero) level, origin
  `forward_filled` (§2), giving it a forecast too: BEVERAGE, CULINARY, **DAIRY**, FRUITS, INNOVATION — all 5 of
  the live 2025 categories now reach the window end and get a one-step MA3.

## 14. API reason codes

Defined once in `backend/series_gaps.py` (text and vocabulary); read that file rather than a copy here. Chart
endpoints: `no_sale`, `blank_capture`, `outside_product_lifespan`, `not_collected`, `category_absent`. Demonstration
only: `no_data_recorded_before_2023`, `no_observation_before_series_start`, `interpolated`,
`taxonomy_change_bridge`, `series_gap_forward_filled`. Any response containing a reason carries a `gap_note`
explaining the codes present.

## 14. Audit corrections, 2026-10-20 (FE-3, FE-4, FE-5, DATA-6, BE-3)

| item | path | what the generator / reader now does |
|---|---|---|
| DATA-6 order omits a month | demo | order = `net_need` = `F + T - S` (§10). `demo.dm_category_lp` rewritten for run 7 (backup `backups/tables_20261020T112333Z`). |
| FE-3 "vs a year ago", 22 months apart | real only | the stock card compared Dec 2025 with Feb 2024 (Del Monte's counts run to 2024-02, then 2025-03 on). `kpi_trend` now gives no percentage past `MAX_COMPARE_GAP_MONTHS` (12) and says so (`delta_blocked_reason`). The demonstration has no such gap: `demo.dm_category_stock` holds all 60 months 2021-01..2025-12 for every category, so every month from 2022-01 has a count 12 months back (0 missing, queried). |
| FE-4 "0 a year earlier" | real only | the API already returned null + reason; the card rendered null as "₱0". It now prints the reason. Nothing generated is involved. |
| FE-5 "counted Dec 1, 2025" | both | Del Monte's `snapshot_date` is a 1st-of-month placeholder (DEC-12). No endpoint offers it as a count date now (`/sku`, `/abc`, `/recommendations`); `stock_count_note` says why, and states that demonstration stock is generated (`generated_months_of_cover`), not counted. |
| BE-3 "Non-moving" x80 | real (view=last_known) | a retired old-vocabulary Del Monte category is no longer carried past its last real month (80 at anchor 2025-12; the five 2025 categories stay). `retired_series_count` reports it. **The generator already stops each series where this rule says it should** — see below. |

**Series ends in the generator (BE-3, checked by query, 2026-10-20).** Rows after a series' own last real month, run 7:
`bridged` 978 rows / 77 old paths, 2023-04..2025-02 only; `forward_filled` 6 rows / DAIRY, 2025-07..12. No other
origin exists past a series' last real month. No old path has a row past 2025-02 (the end of its canonical window),
and the five 2025 categories have none past their own last real month except DAIRY's `forward_filled`. The
bridge is the canonical series' definition (old paths *through* 2025-02, §3 / migration 0055) rather than an
extension of a retired series, so it was kept: removing it would leave 2024-03..2025-02 with no canonical total.
