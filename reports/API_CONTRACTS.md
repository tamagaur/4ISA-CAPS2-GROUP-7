# API contracts — endpoints the mind map needs

**Draft — Phase 0.** One row per endpoint the approved map requires. Lets Audrey
(backend) and Maika/Kelvin (frontend) build against stubs in parallel while the
analytics phases land. Shapes follow existing conventions: FastAPI router with a
`prefix`, Pydantic schema, JWT auth, `{items: [...], count, ...summary}` response,
**Unilever-only** for now (every query filters `principal='unilever'`; keep the
code principal-parametrized for Del Monte later).

Conventions from the existing codebase:
- money = `float` (₱), shares = `float` 0–1, periods = `"YYYY-MM"` strings.
- `null` (not `0`) when a value has no source — e.g. `current_stock` is `null`
  when `Inventory_Fact_Real` has no row (see `backend/schemas/abc.py`).
- Every list response also returns `count` and, where useful, a rolled-up summary
  so the frontend never sums client-side.

---

## Existing endpoints (stable — no change unless noted)

| Method | Path | Returns | Note |
|---|---|---|---|
| POST | `/auth/login`, `/auth/register` | JWT | |
| GET/PATCH/DELETE | `/users`, `/users/{id}` | user rows | |
| GET | `/inventory/current` | on-hand per SKU | `inventory_fact_real` |
| GET | `/inventory/movement` | purchases/sales by period | |
| GET | `/abc` | `{items:[ABCItem], count, classification_period, tier_summary}` | **extended in Phase 2 — see below** |
| GET | `/forecast/{sku_id}` | `{sku_id, forecast:[...], history:[...]}` | MA3, Unilever, 404 if not a UL row |
| GET | `/recommendations` | `{items:[RecommendationItem], count}` | **extended in Phase 4 — see below** |
| PATCH | `/recommendations/{key}` | accept / dismiss | |
| GET | `/dashboard` | KPI bundle | many fields deliberately `null` (no cost source) |
| GET/POST/PATCH | `/sku`, `/sku/{product_key}` | product-dimension row | `unit_price`, `lead_time_days`, `status`, `notes` |
| GET | `/bo-monitoring` | BO incidents + trend | **empty today** (`salesreturn_fact` = 0); lit up in Phase 1 |
| GET/POST | `/audit-log` | audit rows | |

---

## New / changed endpoints

### D1 — Category & Brand ABC  *(Phase 2)*

**`GET /abc?grain={category|brand|sku}`** — extend the existing `/abc` with a
`grain` query param (default `sku` = current behaviour).

```jsonc
// GET /abc?grain=brand
{
  "grain": "brand",
  "classification_period": "2026-02",
  "items": [
    { "key": "SURF",  "product_name": null, "principal": "unilever",
      "tier": "A", "revenue": 295390000.0, "revenue_share": 0.19,
      "cumulative_share": 0.19, "sku_count": 284, "boundary_flag": false }
  ],
  "count": 25,
  "tier_summary": [ { "tier": "A", "key_count": 4, "revenue_share_total": 0.51 } ]
}
```
`key` = brand name or `category_path` (instead of `sku_id`). `sku_count` = how
many SKUs roll up into this brand/category. Everything else mirrors `ABCItem`.

### D2 — SKU ABC within a category  *(Phase 2)*

**`GET /abc?grain=sku&within=<category_path>`** — the existing per-SKU shape, but
tiered **relative to that category** rather than the global Pareto.

```jsonc
// GET /abc?grain=sku&within=FABRIC CLEANING
{
  "grain": "sku", "within": "FABRIC CLEANING", "classification_period": "2026-02",
  "items": [ { "sku_id": "20292808", "product_name": "...", "principal": "unilever",
               "tier": "A", "revenue_share": 0.08, "cumulative_share": 0.08,
               "parent_category": "FABRIC CLEANING", "boundary_flag": false,
               "current_stock": 127584.0, "stock_status": "IN STOCK" } ],
  "count": 94
}
```

### D3 — FSN (movement frequency)  *(Phase 2)*

Two options — **decide with Audrey**:
- **(a)** a `movement` field added to every `ABCItem`: `"fast" | "slow" | "non_moving"`.
- **(b)** a dedicated **`GET /fsn`** → `{ items:[{sku_id, movement, months_with_sales, last_sale_period}], count, summary:{fast, slow, non_moving} }`.

FSN is distinct from the ABC tier (revenue) and from `demand_class` (ADI/CV²
shape) — it's about *how often the SKU moves*.

### D4 — Demand decomposition (trend + variability)  *(Phase 2, descriptive)*

**`GET /decomposition?grain={category|portfolio}&key=<name>`**

```jsonc
{
  "grain": "category", "key": "FABRIC CLEANING",
  "series":   [ { "period": "2023-01", "actual": 812345.0, "trend": 790000.0, "remainder": 22345.0 } ],
  "seasonal_component": null,        // explicit: tested, none found on this data
  "seasonality_note": "No annual seasonal component (lag-12 significant in 5.1% of SKUs = chance).",
  "trend_direction": "declining",    // "growing" | "flat" | "declining"
  "trend_slope_pct_per_year": -3.2
}
```
Runs at category / portfolio grain only — per-SKU series are too noisy.

### P1 — Category growth/decline trajectories  *(Phase 3)*

**`GET /forecast/categories`** — direction + magnitude + a 12-month range per
category, **not** a precise monthly path (multi-step per-SKU forecasting is not
defensible on this data).

```jsonc
{
  "as_of": "2026-02",
  "items": [
    { "category": "HAIR CARE", "trend_direction": "growing",
      "slope_pct_per_year": 6.4, "current_monthly_demand": 1_250_000.0,
      "projected_12mo_low": 13_100_000.0, "projected_12mo_high": 15_800_000.0,
      "r_squared": 0.41, "confidence": "low" } ],
  "count": 13
}
```

### PR2 — Order-Up-To Level on the recommendation  *(Phase 4)*

Extend `RecommendationItem` with the target level. `rop_i` stays as the **trigger**,
`s_i` is the new **target** ("order up to S").

```jsonc
{
  "recommendation_key": 123, "sku_id": "20292808", "product_name": "...",
  "principal": "unilever", "planning_cycle_date": "2026-03-01",
  "rop_i": 2443.0,          // trigger: reorder when on-hand <= this
  "s_i": 3980.0,            // NEW — target: order up to this
  "q_i": 1537.0,            // recommended order = S - on_hand (post-restructure)
  "ss_i": 610.0,            // safety stock component (monthly-scaled after the σ fix)
  "current_stock": 1820.0, "urgency": "URGENT", "status": "pending",
  "model_version": "2026-09-ma3"   // NEW — so stale pre-MA3 rows are filterable
}
```
`/recommendations` gains a default `WHERE model_version = <current>` filter so the
430 stale rows never reach the dashboard.

### PR4 — Policy comparison (the north-star payoff)  *(Phase 4)*

**`GET /policy-comparison`** — per SKU, the model policy vs SSM's blanket 3-week
rule, plus a portfolio rollup.

```jsonc
{
  "as_of": "2026-03",
  "portfolio": {
    "blanket_3wk":   { "working_capital": 41_200_000.0, "avg_weeks_cover": 3.0,  "est_stockout_rate": 0.11 },
    "model_policy":  { "working_capital": 28_600_000.0, "avg_weeks_cover": 2.4,  "est_stockout_rate": 0.09 },
    "capital_freed": 12_600_000.0
  },
  "items": [
    { "sku_id": "20292808", "product_name": "...",
      "blanket_3wk":  { "target_units": 5320.0, "working_capital": 340000.0, "weeks_cover": 3.0, "est_stockout_risk": 0.10 },
      "model_policy": { "target_units": 3980.0, "working_capital": 254000.0, "weeks_cover": 2.2, "est_stockout_risk": 0.10 },
      "capital_freed": 86000.0 } ],
  "count": 67
}
```
`working_capital` = `on_hand_cases × unit_cost_per_case` (or the model target ×
cost). `est_stockout_risk` = P(demand over the window > available), normal on
monthly σ — **assumption stated in the response and the docs**. Backed by a new
`Policy_Comparison` table.

---

## Owning phase / dependency summary

| Endpoint | Phase | Hard dependency |
|---|---|---|
| `/abc?grain=category\|brand` (D1) | 2 | `Product_Dimension.category_path` backfilled (Phase 1c) |
| `/abc?grain=sku&within=` (D2) | 2 | same |
| `/fsn` or `movement` field (D3) | 2 | none |
| `/decomposition` (D4) | 2 | category backfill |
| `/forecast/categories` (P1) | 3 | category backfill + `category_trend.py` |
| `s_i` + `model_version` on `/recommendations` (PR2) | 4 | horizon ruling (Sir CG), `LP_Recommendation.s_i` column |
| `/policy-comparison` (PR4) | 4 | `unit_cost_per_case` wired, `Policy_Comparison` table |
| `/bo-monitoring` (lit up) | 1 | `SalesReturn_Fact` loaded. **D5 is a bad-order value/count trend at principal × month — NOT a rate. FINAL (data fact, 2026-09-09):** no Unilever purchase data exists and `Purchase_Fact.units_received` is 0/353, so there is no denominator to divide by. Not a pending decision. The response carries `bo_value` / `bo_count` per month and **no `bo_rate` field.** |

Frontend can stub all of these against the shapes above from now.
