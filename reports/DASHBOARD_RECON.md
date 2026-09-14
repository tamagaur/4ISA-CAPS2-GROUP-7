# DASHBOARD_RECON.md — Read-only recon of DSD backend/frontend/DB state

Scope: static code inspection (file:line evidence) + read-only SQL SELECT queries
against the live Supabase Postgres DB (via `SUPABASE_DB_URL`). No pipeline/model
code was run. No files were modified except this report.

---

## 1. SARIMA outputs

**Table**: `Forecast_Result` (DDL: `analytics/db/schema.sql:414-440`). Confirmed
live as `forecast_result` (lowercase, Postgres folds unquoted identifiers).

**Full column list** (from live DB, `information_schema.columns`):

```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name='forecast_result' ORDER BY ordinal_position;
```
Result:
| column | type |
|---|---|
| forecast_key | bigint |
| product_key | bigint |
| forecast_date | date |
| forecast_value | numeric |
| confidence_lower | numeric |
| confidence_upper | numeric |
| mape | numeric |
| model_params | jsonb |
| generated_at | timestamptz |
| mase | numeric |
| status | text |

**Non-null counts** (out of 136 total rows):
```sql
SELECT count(*) AS total, count(forecast_date) AS forecast_date_n,
  count(forecast_value) AS forecast_value_n, count(confidence_lower) AS confidence_lower_n,
  count(confidence_upper) AS confidence_upper_n, count(mape) AS mape_n,
  count(mase) AS mase_n, count(model_params) AS model_params_n,
  count(generated_at) AS generated_at_n, count(status) AS status_n
FROM forecast_result;
```
Result: `total=136, forecast_date_n=136, forecast_value_n=136, confidence_lower_n=0,
confidence_upper_n=0, mape_n=89, mase_n=89, model_params_n=136, generated_at_n=136,
status_n=136`.

- **Always NULL**: `confidence_lower`, `confidence_upper` (0/136 populated). Consistent
  with `scripts/run_sarima.py:221-222` — the UPSERT literally passes `None, None` for
  these two positional params on every insert.
- **Partially NULL**: `mape`/`mase` are NULL on the 47 rows where status is not `'ok'`
  (37 `insufficient_data` + 10 `dead_sku`, both of which `save_result()` calls with
  `mape=None`/no `mase` at `scripts/run_sarima.py:312-313, 318`).

**Row counts by status**:
```sql
SELECT status, count(*) FROM forecast_result GROUP BY status ORDER BY status;
```
Result: `dead_sku=10, insufficient_data=37, ok=89` (total 136).

**Materialized vs recomputed**: Materialized — a real, persisted table. Evidence:
`analytics/db/schema.sql:414-440` DDL; `scripts/run_sarima.py:205-223` does an
`INSERT ... ON CONFLICT (product_key, forecast_date) DO UPDATE` (upsert) into it;
`backend/routers/forecast.py:60-68` reads it with a plain `SELECT ... FROM
forecast_result WHERE product_key = :product_key` — no on-the-fly SARIMA fitting
happens inside the request path.

---

## 2. Inventory

**Table**: `Inventory_Fact` (DDL: `analytics/db/schema.sql:284-315`).

**Distinct snapshot_date / min / max**:
```sql
SELECT count(DISTINCT snapshot_date) AS n, min(snapshot_date), max(snapshot_date)
FROM inventory_fact;
```
Result: `n=67, min=2021-01-01, max=2026-08-01`.

**Row counts by principal AND is_demo**:
```sql
SELECT principal, is_demo, count(*) FROM inventory_fact
GROUP BY principal, is_demo ORDER BY principal, is_demo;
```
Result:
| principal | is_demo | count |
|---|---|---|
| delmonte | false | 5171 |
| delmonte | true | 75269 |
| unilever | true | 242138 |

Note: there is **no** `unilever, is_demo=false` row at all — every Unilever
inventory row currently in the table is synthetic.

**Real (is_demo=false) Del Monte inventory after the sku_code=NULL fix**
(migration `analytics/db/migrations/0007_null_phantom_category_sku_codes.sql` —
this migration nulls `Product_Dimension.sku_code` on 99 phantom Del Monte
category rows and reverts one live edit made against one of them; it does not
itself touch `Inventory_Fact` rows, but is the fix referenced by the task): 5171
real rows (per the query above), spanning these `_period` months:
```sql
SELECT _period, count(*) FROM inventory_fact
WHERE principal='delmonte' AND is_demo=false GROUP BY _period ORDER BY _period;
```
Result: 2023-01(307), 2023-02(200), 2023-03(292), 2023-04(296), 2023-05(309),
2023-06(291), 2023-08(352), 2023-09(311), 2023-12(291), 2024-01(284),
2024-02(308), 2025-03(292), 2025-04(292), 2025-06(304), 2025-08(324),
2025-09(303), 2025-12(415). (Gaps exist — e.g. 2023-07, 2023-10/11,
2024-03..2025-02, 2025-01/05/07/10/11 have no real rows.)

Git log confirms migration 0007 was committed as part of `fc30f7b fix: revert
Del Monte SKU reassignment corruption, remove SARIMA MAPE fabrication`
(`git log --oneline -- analytics/db/migrations/0007_null_phantom_category_sku_codes.sql`
→ `fc30f7b`).

**Value/quantity columns on Inventory_Fact** (live DB column list):
```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name='inventory_fact' ORDER BY ordinal_position;
```
Result: `inventory_key, product_key, sku_code, snapshot_date, principal, region,
quantity_on_hand (numeric), _src_file, _src_sheet, is_demo, _period,
quantity_pieces (numeric), valuation (numeric), cost (numeric)`.

Note: `valuation` and `cost` are **not** documented in `analytics/db/schema.sql`'s
`CREATE TABLE Inventory_Fact` block (schema.sql:284-315 has no such columns) —
they exist live, added by migration `0004_add_valuation.sql` (file present under
`analytics/db/migrations/`), which is out of sync with the header comment at
`backend/routers/dashboard.py:11-16` claiming "inventory_fact has no
valuation/price column anywhere (confirmed against the live schema)". That
comment is stale relative to the live DB as queried here — `valuation`/`cost`
columns do exist, though this recon did not check whether they are ever
populated (not asked; flagging as a fact discrepancy only).

---

## 3. Safety stock / ROP

**Table**: `LP_Recommendation` (DDL: `analytics/db/schema.sql:447-460`), columns
`ss_i` (safety stock) and `rop_i` (reorder point). No separate SS/ROP table or
file exists — grep of `analytics/` and `schema.sql` for `ss_i|rop_i|safety_stock|
reorder_point` turns up only this table's columns and the comment at
`schema.sql:444-446` documenting the formulas (`SS_i = Z * sigma_di`, `ROP_i =
Ŷ_(t+1,i) + SS_i`).

**SKUs with a real (non-null) ROP, per principal**:
```sql
SELECT pd.principal, count(DISTINCT lr.product_key)
FROM lp_recommendation lr
JOIN product_dimension pd ON pd.product_key = lr.product_key
WHERE lr.rop_i IS NOT NULL
GROUP BY pd.principal;
```
Result: `unilever=430`. No `delmonte` row appears at all — confirmed separately:
```sql
SELECT count(*) FROM lp_recommendation;
```
Result: `430` (matches the Unilever-only count exactly — every row in
`LP_Recommendation` is currently Unilever; Del Monte has zero LP recommendations
of any kind, ROP included).

---

## 4. Category

**All category-like columns** (grep of `schema.sql` for `categ|segment|class`,
cross-checked against live DB):
```sql
SELECT table_name, column_name FROM information_schema.columns
WHERE table_schema='public'
  AND (column_name ILIKE '%categ%' OR column_name ILIKE '%segment%' OR column_name ILIKE '%class%')
ORDER BY table_name, column_name;
```
Result:
| table | column |
|---|---|
| abc_classification | classification_key |
| abc_classification | classification_period |
| product_demand_view | category_path |
| product_dimension | category_path |
| sellout_fact | category_path |
| sellout_fact_real | category_path |

(`abc_classification`'s two hits are period/key naming, not a product category —
excluded below. `product_demand_view` is a view over `sellout_fact` +
`Unilever_SKU_Demand_Fact`, not an independent source.) The only genuine
product-category columns are **`SellOut_Fact.category_path`** and
**`Product_Dimension.category_path`** (schema.sql:107, :326) — both Del Monte
only (DEC-03, schema.sql:35-38: Unilever forecasts at SKU grain via
`Unilever_SKU_Demand_Fact`, which carries no category column at all — confirmed
by its own DDL at schema.sql:351-376, no category field present).

**`sellout_fact.category_path`**:
```sql
SELECT count(DISTINCT category_path) FROM sellout_fact;
```
Result: `99` distinct values.
```sql
SELECT category_path, count(*) FROM sellout_fact GROUP BY category_path ORDER BY count(*) DESC LIMIT 3;
```
Sample: `/ACE/NPI` (132), `/ACE/BASE` (132), `/CHUNKS/BASE` (132).

**`product_dimension.category_path`**:
```sql
SELECT count(DISTINCT category_path) FROM product_dimension WHERE category_path IS NOT NULL;
```
Result: `104` distinct values.
```sql
SELECT DISTINCT category_path FROM product_dimension WHERE category_path IS NOT NULL ORDER BY 1 LIMIT 10;
```
Sample: `/BASE`, `/FOUR SEASONS`, `/KETCHUP`, `/PINEAPPLE JUICE`,
`/SPAGHETTI SAUCE`, `ACE/BASE`, `ACE/NPI`, `ACE/PROMO`, `BANANA/BASE`,
`BEVERAGE`.

**Del Monte taxonomy break (DEC-03, per project decision register in
ARCHITECTURE.md)** — real (`is_demo=false`) `sellout_fact.category_path`
coverage by era:
```sql
SELECT (CASE WHEN _period < '2025-01' THEN 'pre-2025' ELSE 'post-2025' END) AS era,
  count(DISTINCT category_path) FROM sellout_fact GROUP BY era;
```
Result: `pre-2025 = 94` distinct category paths, `post-2025 = 57` distinct
category paths. (This recon did not check *overlap* between the two sets —
CLAUDE.md's "Known open items" already asserts "zero overlap" between Era A's
~87 fine categories and Era B's 5 coarse categories; the 57 count here is
larger than the "5 coarse categories" figure in CLAUDE.md, so that count may
itself be stale or referring to a narrower slice (e.g. only real, non-demo
rows within a specific sub-period) — not independently reconciled in this pass,
flagging rather than asserting either number is correct.)

**Unilever category source**: NOT FOUND. `Unilever_SKU_Demand_Fact`
(schema.sql:351-376) has no category column, and no other Unilever-facing
table/view carries one — Unilever's only per-product identity is
`Product_Dimension.sku_code` (DEC-03: Unilever = SKU grain, no category
concept).

**`brand`** (bonus, found while inspecting `product_dimension` — not a
"category" column per the grep criteria but adjacent): `104` distinct
`category_path` and separately `107` distinct `brand` values; one anomalous
value found: `'False  (8)'` appears as a literal `brand` string on `1` row
(`SELECT count(*) FROM product_dimension WHERE brand = 'False  (8)'` → `1`) —
looks like a data-quality artifact from source loading, flagged not
investigated further (out of scope for this recon).

---

## 5. API surface

Routers mounted in `backend/main.py:85-94`: `auth, users, inventory, forecast,
recommendations, abc, bo_monitoring, dashboard, sku, audit_log`.

| Method | Path | Real DB or mock | Evidence |
|---|---|---|---|
| GET | `/health` | N/A (liveness only) | `backend/main.py:97-103` |
| POST | `/auth/login` | Real DB | `backend/routers/auth.py:28-48` (`SELECT ... FROM users`) |
| POST | `/auth/register` | Real DB | `backend/routers/auth.py:51-86` (`INSERT INTO users`) |
| GET | `/users` | Real DB | `backend/routers/users.py:30-39` |
| PATCH | `/users/{user_id}` | Real DB | `backend/routers/users.py:42-93` |
| DELETE | `/users/{user_id}` | Real DB | `backend/routers/users.py:96-115` |
| GET | `/inventory/current` | Real DB | `backend/routers/inventory.py:8-51` (`FROM inventory_fact_real`) |
| GET | `/inventory/movement` | Real DB | `backend/routers/inventory.py:56-133` (`FROM purchase_fact_real` / `sales_fact_real`) |
| GET | `/forecast/{sku_id}` | Real DB | `backend/routers/forecast.py:25-118` (`FROM forecast_result`, `unilever_sku_demand_fact_real`, `SellOut_Fact_Real`) |
| GET | `/recommendations` | Real DB | `backend/routers/recommendations.py:69-88` (`FROM lp_recommendation`) |
| PATCH | `/recommendations/{recommendation_key}` | Real DB | `backend/routers/recommendations.py:91-122` |
| GET | `/abc` | Real DB | `backend/routers/abc.py:72-149` (`FROM abc_classification`) |
| GET | `/bo-monitoring` | Real DB | `backend/routers/bo_monitoring.py:12-154` (`FROM salesreturn_fact_real`, `purchase_fact_real`) |
| GET | `/dashboard` | Real DB, but most fields hard-nulled by policy | `backend/routers/dashboard.py:61-113` — see below |
| GET | `/sku` | Real DB | `backend/routers/sku.py:77-96` (`FROM product_dimension`) |
| POST | `/sku` | Real DB | `backend/routers/sku.py:99-134` |
| PATCH | `/sku/{product_key}` | Real DB | `backend/routers/sku.py:137-172` |
| GET | `/audit-log` | Real DB | `backend/routers/audit_log.py:25-50` |
| POST | `/audit-log` | Real DB | `backend/routers/audit_log.py:53-79` |

**No route in `backend/routers/*.py` returns a hardcoded/mock literal.** Every
route queries the DB via SQLAlchemy `text()` + raw SQL. The one route with
literal Python values is `GET /dashboard`, but those are documented policy
nulls, not fabricated numbers — `backend/routers/dashboard.py:109-113`
literally returns `{"inventory": {"value": None, "weeks_of_cover": None,
"policy_weeks": POLICY_WEEKS}, "recommendations": {"order_value": None,
"product_count": product_count}, ...}` where `product_count` and
`unreliable_count`/`total_count` ARE computed from real queries
(`backend/routers/dashboard.py:74-104`), and the `None` fields are explained in
the module docstring (`backend/routers/dashboard.py:9-29`) as "nothing honest
to compute here yet" (no valuation column reachable the way this endpoint
joins, no LP cost column) — this is the "honest null" policy, not mock data.

This contradicts CLAUDE.md's "Known open items" note ("Dashboard runs on
hardcoded mock data except /users and /abc") — that note is **stale** as of
this recon; as of the current code, every backend router queries real Supabase
data. The actual hardcoded-mock surface lives entirely in the **frontend**
(`Dashboard.jsx`, see §6/§7 below), which never calls `GET /dashboard` at all.

---

## 6. Frontend

Dashboard-relevant components in `frontend/src/components/*.jsx` and what they
call:

| Component | Backend call(s) | Evidence |
|---|---|---|
| `ABCClassification.jsx` | `GET /abc` via `getABCClassification` | `frontend/src/components/ABCClassification.jsx:15` (import), `:181` (call) → `frontend/src/api/abc.js:8` (`apiFetch('/abc?...')`) |
| `SKUForecast.jsx` | `GET /abc` + `GET /forecast/{sku_id}` | `frontend/src/components/SKUForecast.jsx:15-16` (imports), `:71` (`getABCClassification`), `:212` (`getForecast`) |
| `ReorderRecommendations.jsx` | `GET /recommendations`, `PATCH /recommendations/{id}` | `frontend/src/components/ReorderRecommendations.jsx:8` (import), `:62` (call) |
| `SKUManagement.jsx` | `GET/POST/PATCH /sku` | `frontend/src/components/SKUManagement.jsx:8` (import), `:43` (call) |
| `BadOrders.jsx` | `GET /bo-monitoring` | `frontend/src/components/BadOrders.jsx:2` (import), `:243` (call) |
| `AuditLog.jsx` | `GET/POST /audit-log` | `frontend/src/components/AuditLog.jsx:2` (import), `:67` (call) |
| `Dashboard.jsx` | **None** — pure mock | `frontend/src/components/Dashboard.jsx:12-71` (`MOCK_SALES_VS_STOCK`, `MOCK_ABC_DATA`, `MOCK_CATEGORY_STOCK`, `MOCK_PORTFOLIO_FORECAST`, `MOCK_REORDER_ROWS` literals, plus 4 hardcoded KPI values `₱48,000`/`₱6.4M`/`82%`/`0.94` at lines 91-116); the component never imports `getDashboardData` |
| `Charts.jsx` | None — presentational, receives data via props from whatever parent (currently only `Dashboard.jsx`'s mock data) | No `apiFetch`/`fetch`/`api/` reference found in the file; comment at `frontend/src/components/Charts.jsx:29` references `getDashboardData()`'s shape but does not call it |
| `AlertsList.jsx` | None — pure presentational (`{ title, alerts, onViewAll, viewAllPath }` props) | `frontend/src/components/AlertsList.jsx:19`; not imported by any other component (`grep AlertsList frontend/src/components/*.jsx` finds no importer) — currently unused/unwired |
| `KPICard.jsx` | None — presentational | No API import in file |
| `DateFilter.jsx` | None — reads/writes filter state via `useOutletContext()`, no backend call | No API import in file |
| `DashboardLayout.jsx`, `Sidebar.jsx`, `Topbar.jsx` | None — layout/shell only | No API import in any of the three files |
| `DataUpload.jsx` | None found — only imports `logAction` from `../utils/auditLogger` (localStorage-based, not the `/audit-log` API) | `frontend/src/components/DataUpload.jsx:3` |

`frontend/src/api/dashboard.js:6` defines `getDashboardData({ principal })`
which does call the real `GET /dashboard` endpoint, but **no component in the
repo imports or calls it** (confirmed by grep across `frontend/src` — the only
hits for `getDashboardData` are inside `frontend/src/api/dashboard.js` itself
and a comment in `Charts.jsx:29`). `Dashboard.jsx` also carries an explicit
UI disclosure of this at line 83: `<span className="demo-badge">Layout preview
— sample figures, not live data</span>`.

---

## 7. Demo-data isolation

**`get_demand_series()` — NOT FOUND.** Exhaustive search (`Grep` for
`get_demand_series`/`demand_series`, case-insensitive, whole repo) finds **zero**
function definitions or call sites anywhere in `analytics/`, `backend/`,
`scripts/`, or `frontend/`. The only hit in the entire repo is a prose note in
`reports/POST_LOAD_VERIFICATION.md:64`, which itself states: *"no function
named `get_demand_series()` exists anywhere in this codebase — checked, not
assumed; the nearest existing building blocks are `analytics/forecasting/
sarima.py`'s `fit_sarima()`/`forecast_one_step()` and
`analytics/optimization/lp.py`'s `compute_safety_stock()`/`compute_rop()`."*

This means CLAUDE.md's "Hard rule #1" ("all model code calls
`get_demand_series()` only") describes an **intended interface that is not
implemented** in the current codebase, not current behavior. No full
signature/body can be reported — there is none.

**What actually fetches demand data today**: `scripts/run_sarima.py:225-259`
runs a hand-written SQL query directly against `SellOut_Fact_Real` and
`Unilever_SKU_Demand_Fact_Real` (both `_Real` views, i.e. `WHERE is_demo =
false` baked in at the view level — `analytics/db/schema.sql:662-666`), joined
to `ABC_Classification` filtered to `tier = 'A'` at each principal's own latest
`classification_period`.

**Does anything filter `is_demo`?** Yes — not via a function, but via the
`_Real` view family defined at `analytics/db/schema.sql:653-669`
(`Sales_Fact_Real`, `Purchase_Fact_Real`, `Inventory_Fact_Real`,
`SellOut_Fact_Real`, `Unilever_SKU_Demand_Fact_Real`,
`SalesReturn_Fact_Real`), each literally `SELECT * FROM <Fact> WHERE is_demo =
false` (e.g. `analytics/db/schema.sql:665-666`:
`CREATE OR REPLACE VIEW Unilever_SKU_Demand_Fact_Real AS SELECT * FROM
Unilever_SKU_Demand_Fact WHERE is_demo = false;`). `scripts/run_sarima.py`'s
query (line 236, 243) reads from these `_Real` views, not the base tables.

**Did the last SARIMA run include `is_demo=true` rows?** Based on static
evidence only (not re-run, per instructions): **No** — `run_sarima.py`'s query
sources exclusively from `SellOut_Fact_Real` and
`Unilever_SKU_Demand_Fact_Real` (`scripts/run_sarima.py:236-244`), both of
which structurally exclude `is_demo=true` rows at the view definition level
(`schema.sql:662-666`). There is no code path in `run_sarima.py` that reads the
base `SellOut_Fact`/`Unilever_SKU_Demand_Fact` tables directly. This is
inferred from the query text actually executed, not from re-running it, per
the task's instructions on what counts as adequate evidence.

**Per-principal latest calendar_month (Unilever, `is_demo=false` vs overall)**:
```sql
SELECT is_demo, max(calendar_month) FROM unilever_sku_demand_fact GROUP BY is_demo;
```
Result: `is_demo=false → 2026-02`, `is_demo=true → 2026-08`.
```sql
SELECT max(calendar_month) FROM unilever_sku_demand_fact;
```
Result: `2026-08` (i.e. the overall max is driven entirely by synthetic rows —
real Unilever data currently tops out at 2026-02).

**Del Monte equivalent** (`sellout_fact._period`, the analogous demand table
for Del Monte per DEC-03):
```sql
SELECT is_demo, max(_period) FROM sellout_fact GROUP BY is_demo;
```
Result: `is_demo=false → 2025-12`, `is_demo=true → 2026-06`.
```sql
SELECT max(_period) FROM sellout_fact;
```
Result: `2026-06` (again, driven by synthetic rows — real Del Monte SellOut
data currently tops out at 2025-12).

---

### Summary of stale-documentation findings surfaced during this recon
(flagged, not fixed — no files other than this report were modified)

1. CLAUDE.md's "Dashboard runs on hardcoded mock data except /users and /abc"
   is stale: every backend router now queries real Supabase data (§5). The
   only actual hardcoded mock left is `frontend/src/components/Dashboard.jsx`,
   which is disconnected from the `GET /dashboard` endpoint entirely (§6).
2. CLAUDE.md's Hard Rule #1 names a `get_demand_series()` function that does
   not exist anywhere in the codebase (§7) — `reports/POST_LOAD_VERIFICATION.md`
   already documents this same gap independently.
3. `backend/routers/dashboard.py:11-16`'s docstring claim that
   "inventory_fact has no valuation/price column anywhere" does not match the
   live DB, which has both `valuation` and `cost` numeric columns on
   `inventory_fact` (§2) — population/correctness of those columns was not
   checked (out of scope for this recon).
