# Fewer round trips + response cache — 2026-10-04

Branch `kelvin/speed-cache`, started from `kelvin-etl` @ `282df97` and merged with
`kelvin-etl` @ `5f635a7` (data-mart decisions, 0043, speed baseline) before the final
measurements. Measured with this folder's
`speed_baseline.py`, a copy of the one on `kelvin/speed-baseline`
(`reports/diagnostics/speed_baseline_2026-10-04/`, merged into `kelvin-etl` at `5f635a7`) with the changes listed in
its docstring. Local FastAPI on a laptop in the Philippines against the **live** Supabase
DB (pooler `aws-0-ap-south-1`, Mumbai). Every number below is in a file in `results/`
(copied from the script's `out/`, which is git-ignored with the raw per-request logs).

"Before" = the unchanged code (`kelvin-etl` @ `5f635a7`, a detached worktree) on the same
DB, measured the same way minutes earlier. Both were checked against each other first (§4).
The same comparison was first run against `282df97`, before the merge; its numbers agree
(page medians within 9.1% of each other) and are not repeated here.

## 1. What changed

| # | change | where |
|---|---|---|
| 1 | No pool pre-ping: connections recycled after 280 s, kept open with TCP keepalives | `backend/deps.py` |
| 1 | GET/HEAD requests use a second, **autocommit** pool: no BEGIN, no ROLLBACK, no SET | `backend/deps.py` (`get_db`, `_get_read_engine`) |
| 1 | Writes keep the transactional pool; `BEGIN READ WRITE` now comes from marking each new connection read-write once (psycopg2 adds it to BEGIN), not from the `postgresql_readonly` engine option, which added a round trip to every pre-ping | `backend/deps.py` (`_get_engine`) |
| 1 | The session check also reads the user's permission overrides and (on a read) the data version: one round trip instead of up to three | `backend/deps.py` (`_principal_sql`), `backend/permissions.py` |
| 1 | Which optional tables exist (0034, 0037, 0041) is asked once at startup, in one round trip, and remembered | `deps.check_db_connection`, `lp_cycle.lp_run_present`, `marts.present` |
| 2 | Several reads sent as **one statement** (each query a JSON subquery); a query not prefetched still runs on its own, so a mismatch costs speed, never correctness | `backend/batch.py` (new) |
| 2 | `GET /dashboard` prefetches its statements in 3 waves (request → LP cycle / range / counts → product keys) | `backend/routers/dashboard.py` (`_prefetch`) |
| 2 | The helpers it reads through expose their SQL (`*_query`) and read via `batch` | `lp_cycle.py`, `marts.py`, `principals.py`, `stock_units.py` |
| 3 | Response cache keyed by endpoint + every parameter + the user's **effective permission set**; cleared when the data version changes, and at once by this server's own writes | `backend/response_cache.py` (new), 10 GET routes |

**Cache scope.** `GET /dashboard`, `/sku`, `/abc`, `/fsn`, `/pareto`, `/forecast/{sku}`,
`/segment`, `/decomposition`, `/recommendations`, `/category-trends`. Not cached: preview
mode, errors (e.g. the 404s), and anything without a data version or permission set.

**Cleared when.** The data version is read with the session check on every GET:
`mart.refresh_status` (moves with every data load, fill, forecast run, LP run and mart
refresh), `MAX(lp_recommendation.decided_at)` (reorder decisions) and the latest
`Add SKU`/`Edit SKU` row in `audit_log`. A change made from any machine clears this
server's cache on its next request. `PATCH /recommendations`, `POST`/`PATCH /sku` also
clear it straight away. A data load that isn't followed by a mart refresh still clears it:
`etl_load_event` is one of `refresh_status`'s inputs.

**LP fields.** A user without `lp.view` has a different permission set, so a different
key: the response built for them (LP figures stripped by the route) is the only one they
can be served. Tested: `tests/backend/test_response_cache.py::test_the_dashboard_never_serves_lp_figures_to_a_user_without_lp_view`.

## 2. Statements per request (`results/statements_per_request.csv`)

| request | before | after, cache cold | after, cache warm |
|---|---:|---:|---:|
| `/dashboard` Unilever 12m | 30 + pre-ping (2 RT) + BEGIN, ROLLBACK after | **4** | **1** |
| `/dashboard` Del Monte 12m | 23 + pre-ping + BEGIN | **4** | **1** |
| `/dashboard` all principals 12m | 31 + pre-ping + BEGIN (side-by-side capture, §4) | **4** | **1** |
| `/dashboard`, any of the 21 principal × range variants (§4) | 21–31 | **4** | **1** |
| `/dashboard`, preview mode | not measured | 5–7 (not cached) | 5–7 |
| `/sku`, `/abc`, `/fsn`, `/pareto`, `/category-trends` | 2–5 + pre-ping + BEGIN | 2–5 | 1 |
| `/recommendations` | 7–12 + pre-ping + BEGIN | 7–11 (not batched) | 1 |

"30" counts the session check: 29 route statements, the figure in the request. The 4 are:
session check (+ permissions + data version), wave 1 (month marts, LP cycle, forecast
dates/counts, ABC periods, refresh status), wave 2 (freshness, counts, plan rows, Pareto,
stock counts, gated forecasts, reorder preview, policy rows, accuracy, idle stock), wave 3
(stock per Tier A product, stock status per ranked product, actuals per gated product).

Fixed cost per request, `results/select1.json` (20 runs each, median):

| path | ms | round trips |
|---|---:|---:|
| raw `SELECT 1`, one open autocommit connection (the network floor) | 101.5 | 1 |
| GET pool: checkout + `SELECT 1` + return | 101.2 | 1 |
| write pool: checkout + `SELECT 1` + commit + return | 305.5 | 3 (BEGIN READ WRITE, statement, COMMIT; no SET) |
| old engine: checkout (pre-ping) + BEGIN + `SELECT 1` + return (baseline README §4) | 518.2 | ~5 |

## 3. Page timings, local (ms; 3 runs each; calls in a wave fired in parallel like the browser)

Before: `results/pages_before_merge.csv`. After: `results/cache_merged.csv`. **Cold** = the
cache emptied just before (harness-only `POST /__speed/invalidate`), so every call
computes; **warm** = the same page loaded straight after.

| page | principal | before median (slowest) | after **cold** median (slowest) | after **warm** median (slowest) |
|---|---|---:|---:|---:|
| Dashboard (12m default) | Unilever | 4,266 (4,403) | **882** (937) | **146** (146) |
| SKU Management | Unilever | 1,250 (1,259) | 609 (610) | 144 (144) |
| ABC | Unilever | 3,119 (3,518) | 1,539 (2,548) | 341 (346) |
| SKU Forecast | Unilever | 2,291 (2,410) | 1,561 (1,828) | 365 (366) |
| Reorder | Unilever | 1,698 (1,801) | 1,434 (1,479) | 181 (186) |
| Category Trends | Unilever | 701 (704) | 391 (441) | 137 (138) |
| Dashboard (12m default) | Del Monte | 3,009 (3,011) | **924** (1,202) | **140** (143) |
| SKU Management | Del Monte | 1,135 (1,161) | 842 (843) | 135 (139) |
| ABC | Del Monte | 2,137 (2,333) | 1,450 (1,474) | 308 (325) |
| SKU Forecast | Del Monte | 1,906 (1,916) | 1,083 (1,328) | 446 (458) |
| Reorder | Del Monte | 1,146 (1,164) | 833 (840) | 165 (168) |
| Category Trends | Del Monte | 538 (540) | 236 (242) | 140 (140) |

**First request after the server starts** (dashboard 12m Unilever, cache empty, pools just
opened): **2,350 ms** (`cache_merged.csv`, state `first request`). Every cold view is under
3 s; the slowest cold run of any view is ABC Unilever's first, 2,548 ms.

Warm Del Monte SKU Forecast stays ~460 ms: its `/forecast`, `/segment` and
`/decomposition` calls answer 404 (side finding F1 of the baseline) and errors are not
cached.

## 4. Same answers

Every frontend GET (59 endpoint × principal × range combinations, including 7 date ranges
per principal for `/dashboard`; the captures are not committed: they hold sales) was
fetched from the old (`5f635a7`) and the new (merged) code against the same data and
compared field by field:
**0 of 58 data responses differ**, both freshly computed and served from the cache. The
59th, `/auth/me`, differs only in name and email: the new harness signs in as a real admin
row (§ docstring). Preview mode (`X-Data-Mode: preview`, dashboard × 2 ranges, `/abc`,
`/recommendations`, 3 scopes): **0 of 24 differ**.

An earlier pass showed differences that were not the code: another session applied
migration `0043_mart_stock_limited_rule.sql` and refreshed the marts (trigger
`migration 0043`, 14:41 UTC) between the two captures, which changed
`possibly_stock_limited`. Recaptured side by side afterwards.

## 5. Not done / risks

- **Render not re-timed** (needs a signed-in token; the deploy happens on merge). From
  Render each removed round trip is worth more than locally (Oregon → Mumbai).
- **No pre-ping**: a pooled connection the server or a proxy dropped silently fails the one
  request that draws it (500), then is replaced. Recycle at 280 s and TCP keepalives make
  that rare; pre-ping would have hidden it at the cost of 2 round trips per request.
- **Cache memory**: at most 64 entries (LRU). A `/sku` response is the largest, ~0.7–0.9 MB
  as JSON (as Python objects it is larger; not measured). Render's memory limit is
  UNVERIFIED here: check the service's plan before raising `MAX_ENTRIES`.
- **Not batched**: `/recommendations` (7–11 statements cold), preview-mode dashboard (5–7).
- **Separate finding, not changed**: `/abc` cold stays ~0.6 s server-side on 4–5
  statements; the baseline's §3b missing indexes (`inventory_fact(principal, _period)`,
  `abc_classification(...)`) would be a migration.

## Rerun

```
P=reports/diagnostics/speed_cache_2026-10-04/speed_baseline.py
python $P select1
python $P serve --port 8094 --label merged &           # instrumented, real session-check SQL
python $P cache --base http://127.0.0.1:8094 --label merged        # first, cold, warm per page
python $P pages --base http://127.0.0.1:8093 --label before_merge  # against an old-code serve
```
