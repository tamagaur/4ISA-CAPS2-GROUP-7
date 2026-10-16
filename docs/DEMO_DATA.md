# Demonstration data (schema `demo`)

Everything generated that the app can display lives in schema `demo`. It is synthetic, labelled, and off by default.
Approved by Kelvin on 2026-10-15 (Sir Catubag informed) and extended by Kelvin on 2026-10-16 to stock and the
order plan. The rule is in `CLAUDE.md` hard rule 2; this file is the detail. Sales/forecast figures were queried
from the live database on 2026-10-15 (migrations 0052-0055); stock, the Unilever forecast and the order plan were
queried 2026-10-16 (migration 0056).

**Read first: four rules**
1. Unilever gaps render as **zero** and are never filled.
2. Del Monte gaps are **filled and labelled** (`interpolated`, `bridged`, `backcast`).
3. `demo.*` is the **only** display source for generated data. The older `synthetic_v2` rows are retired for
   display (nothing deleted).
4. Del Monte stock on hand has **no real anchor at all** (every row is generated — see §9): it is a different
   kind of generated data than sales, not a copy or an interpolation of anything real.

## 1. What is in `demo.*`

| Run | Principal | Grain | real_copy | interpolated | bridged | backcast |
|---|---|---|---:|---:|---:|---:|
| 4 `demonstration` | Del Monte | category | 747 | 272 | 978 | 2,147 |
| 3 `demonstration_unilever` | Unilever | SKU | 24,906 | 0 | 0 | 12,816 |

- **Del Monte:** 82 of the 87 real category paths are covered. 5 are left out entirely because they have one real
  month and so no coefficient of variation to generate from: `/FIBER/PROMO`, `/GOURMET SPAG SAUCE/PROMO`,
  `/MIXED FRUITS/TODAY'S`, `/OYSTER SAUCE/BASE`, `/TOTAL 100% JUICES/ACE - PROMO CANNED`. Every month 2021-01..2025-12
  has rows (60 of 60). Backcast splits 1,560 (65 categories, `anchor_override = false`) and 587 (17 categories,
  `anchor_override = true`). Bridged covers 77 paths.
- **Unilever:** 534 of 1,807 SKUs are back-cast. 1,273 are not: 1,214 first sold after 2023-01 (genuine launches,
  never back-cast), 59 have fewer than 3 months with sales. No in-span gap is filled.
- Tables: `demo.run`, `demo.dm_category_sales`, `demo.dm_category_param`, `demo.dm_forecast`, `demo.dm_excluded`,
  `demo.unilever_sku_sales`, `demo.backcast_excluded`, view `demo.dm_monthly_total`.
- Every row carries `is_demo = true` and `fill_source = 'synthetic_dm_pipeline_demo'` (CHECK constraints). No table
  has an accuracy column (mape / mase / wape) or a confidence band; `tests/demo/test_demo_schema.py` fails if one
  appears.
- Migrations: 0052 schema, 0053 Unilever + back-cast, 0054 `anchor_override`, 0055 canonical total.
- Rebuild: `python -m scripts.build_dm_demo --write --replace` and `python -m scripts.build_unilever_demo --write
  --replace`. Seed 20261015, recorded in `demo.run`; the same series regenerates identically.

## 2. The four origins

| origin | meaning | is it extrapolation? |
|---|---|---|
| `real_copy` | a real month, copied | no |
| `interpolated` | between two real months of the same series (anchored on both sides) | no |
| `bridged` | across the 2024-03..2025-02 taxonomy change: a pre-2025 Del Monte path carried forward from its last real month through 2025-02. Real data on one side only | **yes** |
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
a plain 404 and `X-Data-Mode: preview` reads real data only. Routes (all `forecast.view`):
`GET /demo/series?principal=&key=`, `GET /demo/index?principal=`, `GET /demo/totals`; also wired into
`GET /forecast/{sku}?principal=delmonte&category=`, `GET /recommendations?principal=delmonte` and a `demonstration`
block in `GET /dashboard`. Every demo row returns `demonstration: true` and `demonstration_note`; the payload has
`data_source: "synthetic_demonstration"` (inside the `demonstration` block on `/dashboard`, whose other fields are
real).

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

## 7. What is empty on purpose for Del Monte

Safety stock, reorder point, order plan, forecast accuracy, dead stock and policy comparison need per-product
forecasts or a stock count that cannot exist: Del Monte has no product-level sales, its taxonomy changed in January
2025 from 82 paths to 5 with no mapping, and real sales stop at 2025-12. The demonstration has no stock count or
purchase parameters, so `run_lp --source demo` is refused and `/recommendations` returns `order_plan.available:
false`.

**Only 4 category forecasts exist** (BEVERAGE, CULINARY, FRUITS, INNOVATION) because a one-step MA3 needs a real
month at the end of the window (2025-12). Of the 82 covered series, 77 end at or before 2024-02 (64 exactly at
2024-02, 13 earlier), DAIRY ends 2025-06, and 4 reach 2025-12.

## 8. Del Monte stock on hand (migration 0056)

There is **no real Del Monte stock count at category grain anywhere in SSM's data**, confirmed live 2026-10-16:
`Inventory_Fact_Real` for Del Monte is SKU grain only (597 products, 5,541 rows, 2023-01..2025-12) and 0 of those
597 SKU rows carry a `category_path` (it is NULL on every one). So `demo.dm_category_stock` has no `real_copy`
origin at all — every row's origin is `generated_months_of_cover`.

Method (`analytics/demo/stock.py`): a seeded draw centred on SSM's own stated policy, "about 3 weeks of sales in
stock" (Sir Abe; `analytics.params.POLICY_COVER_WEEKS`, the same constant the real LP's `--target-weeks` default
uses — 3 weeks / `WEEKS_PER_MONTH` ≈ 0.690 months of cover), jittered by the category's own coefficient of
variation (same `JITTER_SCALE=0.25` as the sales generator), then multiplied by that category's own
demonstration demand for that month (whatever origin the sales generator produced). Live: 4,144 rows, 82
categories, run_id 5 (the same run as the Del Monte sales/forecast build — `python -m scripts.build_dm_demo
--write --replace` now writes stock too).

## 9. Unilever demonstration forecast (migration 0056)

A one-step MA3 per SKU (`scripts/build_unilever_demo.py`), over each SKU's own last 3 real months — real sales
copied plus real in-span zeros, the same window `backend/series_gaps.unilever_points` renders — never the
back-cast. **Not wired into any endpoint**: Unilever's real `Forecast_Result` is unaffected and stays the only
forecast the app serves for Unilever.

Live, run_id 6: 1,396 of 1,807 SKUs forecast (411 excluded: 378 with fewer than 3 real months, 33 with a
blank-capture month inside the window). Measured against `Forecast_Result` (189 Tier A SKUs; the real deployed
model is per-SKU, not always MA3 — short-lived SKUs get MA3, medium TSB, long an XGBoost+MA3 average,
`model_params.method`): of 179 SKUs comparable, the 36 whose real row **is** `ma3` match with **median
difference 0.0** (max 459.67, one outlier); the 143 whose real row uses a different method differ by a median
8.53% — a model-routing difference, not a demo-generation bug. "Barely differs from real" holds exactly where the
real path also used MA3, and only there.

## 10. Del Monte demonstration order plan (migration 0056)

`analytics/demo/prescriptive.py`: the real formulas (`analytics.optimization.lp.compute_safety_stock` /
`target_stock`, the same `SERVICE_Z` and the same review/lead-day placeholders the real LP applies) over the
demonstration's own forecast (§7) and stock (§8) — **two layers of generated input**, said explicitly in every
row's `demonstration_note`, not just a generic synthetic flag. **No allocation or warehouse ceiling**: Del Monte
has neither an SSM-confirmed yearly allocation nor a warehouse capacity, and reusing Unilever's real
`warehouse_capacity` (3.8M pieces, measured from Unilever's own stock history) would conflate two different
businesses and quantity units (DEC-31: Del Monte's unit is unconfirmed). `order_qty` is a plain order-up-to:
`max(0, target_stock - stock_on_hand)`, floored at `target_weeks` of the month's own demand since there is no
portfolio LP here to enforce SSM's "3 weeks of cover" softly instead.

Live, run_id 5 (same run as the sales/stock/forecast build): 4 rows — one per category with a forecast (§7).
`BEVERAGE`, `CULINARY` and `FRUITS` order 0 (the generated stock, drawn around the same ~3-week policy the order
plan targets, already sits above target); `INNOVATION` orders 5.52. This is the honest result of using SSM's
same stated policy figure for both the stock draw and the order target — not a bug, and not adjusted to look
busier. Run with `python -m scripts.run_lp --source demo --principal delmonte --write`; served at
`GET /recommendations?principal=delmonte` (`order_plan.available`) and in `GET /dashboard`'s `demonstration`
block, behind `DM_DEMO_ENABLED`.

## 11. API reason codes

Defined once in `backend/series_gaps.py` (text and vocabulary); read that file rather than a copy here. Chart
endpoints: `no_sale`, `blank_capture`, `outside_product_lifespan`, `not_collected`, `category_absent`. Demonstration
only: `no_data_recorded_before_2023`, `no_observation_before_series_start`, `interpolated`,
`taxonomy_change_bridge`. Any response containing a reason carries a `gap_note` explaining the codes present.
