# Dashboard speed baseline — 2026-10-04

READ-ONLY measurement. Base: `kelvin-etl` @ `1edf5cf`. Nothing here changes code,
schema or data. Every number below comes from a file in `results/`; rerun with
`speed_baseline.py` (commands at the end).

- **Local** = this checkout's FastAPI (uvicorn, `serve` subcommand) on a laptop in
  the Philippines, against the **live** Supabase DB. Auth: a minted JWT. `serve`
  still runs the real session-check SELECT (`deps.ACTIVE_PRINCIPAL_SQL`) on every
  request, so the round trip is counted, but it never opens a session row.
- **Render** = `https://logincred.onrender.com` (the live backend). Only
  token-free paths were measured: cold start, warm `/health`, the 401 path and
  one public read. Per-route Render times are **estimates** (§2c).
- Range: latest data month is **2026-02** (`frontend/src/dataCoverage.js:11`).
  **12m** = 2025-03…2026-02, the default range (`DashboardLayout.jsx:82`, 11 months back).
  **1m** = 2026-02…2026-02. The picker's minimum is 6 months
  (`DashboardLayout.jsx:96`), so 1m can only be reached through the API.
  1m/12m only applies to `/dashboard` (`start_period`) and `/pareto` (`months`).
  Every other call takes no range from the picker.
- Principals: `unilever` (the default) and `delmonte`. `all` is hidden in the UI
  (`SHOW_ALL_PRINCIPALS = false`, `principals.js:20`).
- Sample SKU (Forecast page) = first item of `/abc?principal=<p>`: Unilever
  `69767334`, Del Monte `CULINARY` (see side finding F1).

## 1. What each page calls

`appendPrincipal` adds `principal=` only when it isn't `all` (`principals.js:66`).
No call sends `from`/`to`, and only `/dashboard` and `/pareto` take a range.

| page (route) | call | filters sent | issued from |
|---|---|---|---|
| every page (layout) | `GET /auth/me` | — | `permissions/PermissionsProvider.jsx:32`, once per load |
| every page (layout) | `GET /status` | — (no auth) | `Sidebar.jsx:69`, every 60 s |
| every page, preview mode only | `GET /data-mode` | — | `DashboardLayout.jsx:276` (not timed: preview only) |
| Dashboard `/` | `GET /dashboard` | `period`=range end, `start_period`=range start, `principal` | `Dashboard.jsx:326` |
| SKU Management `/sku-management` | `GET /sku` | `principal` | `SKUManagement.jsx:47` |
| ABC `/abc` — wave 1 | `GET /abc` | `classification_period`=range end, `view=last_known`, `principal` | `ABCClassification.jsx:347` |
| ABC — wave 1 | `GET /sku` | `principal` (brand lookup) | `utils/useBrandLookup.js:23` |
| ABC — wave 2 (waits for `/abc`) | `GET /fsn` | `principal`, `period`=ABC's classification_period | `ABCClassification.jsx:427` |
| ABC — wave 2 (waits for `/abc`) | `GET /pareto` | `grain` brand (Del Monte: category), `months` 1 or 12 (toggle), `principal`, `period` | `AbcBreakdowns.jsx:71` |
| SKU Forecast `/forecast` — wave 1 | `GET /abc` | `principal` only | `SKUForecast.jsx:267` |
| SKU Forecast — wave 1 | `GET /sku` | `principal` (brand lookup) | `useBrandLookup.js:23` |
| SKU Forecast — wave 2 (on SKU pick) | `GET /forecast/{sku}` | `principal` | `SKUForecast.jsx:489` |
| SKU Forecast — wave 2 | `GET /segment` | `sku`, `principal` | `SkuDemandPatternPanel.jsx:93` |
| SKU Forecast — wave 2 | `GET /decomposition` | `sku`, `principal` | `SkuDemandPatternPanel.jsx:113` |
| Reorder `/reorder` | `GET /recommendations` | `status=pending`, `principal` | `ReorderRecommendations.jsx:177` |
| Reorder | `GET /sku` | `principal` (brand lookup) | `useBrandLookup.js:23` |
| Reorder — row modal | `GET /segment`, `GET /decomposition` | `sku`, `principal` | `ReorderModal.jsx:130` |
| Category Trends `/category-trends` | `GET /category-trends` | `principal` | `CategoryTrends.jsx:347` |
| Audit Log `/audit-log` | `GET /audit-log/users` | — | `AuditLog.jsx:89` |
| Audit Log | `GET /audit-log` | `exclude_action=Login&exclude_action=Logout`, `limit=10` | `AuditLog.jsx:90` |
| Users `/users` | `GET /users` | — | `utils/usersApi.js:24` |
| Users — permissions modal | `GET /admin/permissions/catalog`, `GET /admin/users/{id}/permissions` | — | `PermissionsModal.jsx:87,93` |
| Data Management `/upload` | none | — | — |

## 2. Timings

### 2a. Local FastAPI → live DB (ms, 3 runs, sequential; `results/timings_local.csv`)

`queries` counts every SQL statement in the request, including the session
check. Dashboard rows are from the rerun (`results/timings_local_rerun.csv`): the
first pass had one 5,866 ms Unilever-1m outlier, a DB stall (see §3c), and the
rerun's median matches the first pass (4,600 vs 4,730).

| endpoint | principal | 1m median | 1m slowest | 12m median | 12m slowest | queries | payload KB |
|---|---|---:|---:|---:|---:|---:|---:|
| `/dashboard` | unilever | 4,730 | 4,868 | 4,577 | 4,624 | 38 / 37 | 8 / 14 |
| `/dashboard` | delmonte | 3,712 | 3,768 | 3,700 | 3,804 | 32 | 5 / 9 |
| `/pareto` | unilever (brand) | 647 | 660 | 666 | 668 | 3 | 3 |
| `/pareto` | delmonte (category) | 637 | 644 | 636 | 660 | 3 | 1 |

| endpoint (no range) | principal | median | slowest | queries | payload KB |
|---|---|---:|---:|---:|---:|
| `/auth/me` | — | 402 | 423 | 1 | 0.2 |
| `/status` | — | 3 | 4 | 0 | 0 |
| `/sku` | unilever | 1,298 | 1,343 | 4 | 695 |
| `/sku` | delmonte | 1,106 | 1,138 | 4 | 225 |
| `/abc` (last_known, ABC page) | unilever | 1,412 | 1,429 | 5 | 594 |
| `/abc` (last_known, ABC page) | delmonte | 924 | 1,005 | 5 | 35 |
| `/abc` (Forecast page) | unilever | 1,101 | 1,147 | 4 | 253 |
| `/abc` (Forecast page) | delmonte | 803 | 818 | 4 | 2 |
| `/fsn` | unilever | 1,198 | 1,230 | 3 | 184 |
| `/fsn` | delmonte | 720 | 764 | 3 | 14 |
| `/forecast/{sku}` | unilever | 752 | 769 | 4 | 3 |
| `/forecast/{sku}` | delmonte | 619 (404) | 636 | 2 | 0 |
| `/segment` | unilever | 728 | 732 | 4 | 1 |
| `/segment` | delmonte | 631 (404) | 647 | 2 | 0 |
| `/decomposition` | unilever | 731 | 742 | 4 | 0.3 |
| `/decomposition` | delmonte | 601 (404) | 628 | 2 | 0.1 |
| `/recommendations` | unilever | 1,584 | 1,625 | 11 | 40 |
| `/recommendations` | delmonte | 947 | 953 | 6 | 1 |
| `/category-trends` | unilever | 693 | 699 | 2 | 41 |
| `/category-trends` | delmonte | 511 | 528 | 2 | 3 |
| `/audit-log/users` | — | 527 | 540 | 2 | 1 |
| `/audit-log` | — | 509 | 529 | 2 | 2 |
| `/users` | — | 523 | 528 | 2 | 0.4 |
| `/admin/permissions/catalog` | — | 410 | 420 | 1 | 1.5 |

### 2b. Local page loads (calls fired in parallel per wave, as the browser does; `results/pages_local.csv`, ms)

| page | calls / waves | unilever median | slowest | delmonte median | slowest |
|---|---|---:|---:|---:|---:|
| Dashboard (12m default) | 1 / 1 | 4,484 | 4,501 | 3,767 | 4,001 |
| SKU Management | 1 / 1 | 1,362 | 1,402 | 1,145 | 1,155 |
| ABC | 4 / 2 | 2,729 | 2,794 | 1,934 | 1,954 |
| SKU Forecast (incl. first SKU) | 5 / 2 | 2,032 | 2,187 | 1,828 | 1,836 |
| Reorder | 2 / 1 | 1,647 | 1,787 | 1,154 | 1,161 |
| Category Trends | 1 / 1 | 712 | 722 | 508 | 529 |

### 2c. Render (live site)

No signed-in token was used (Yuan, 2026-10-04: skip the authenticated pass).
Only token-free paths were **measured**. Every per-route and per-page Render
number is an **estimate** derived from them.

**Measured** (`render` subcommand, 10 runs each over one keep-alive connection;
`results/render_probe.csv`, `results/render_probe_summary.json`):

| probe | DB work | Render median | min | max | local median |
|---|---|---:|---:|---:|---:|
| `GET /health` (warm) | none | 114.5 | 107.8 | 123.5 | 3 |
| `GET /auth/me`, no token → 401 | none | 113.8 | 110.1 | 120.6 | — |
| `GET /auth/me`, bad signature → 401 | none | 113.6 | 109.9 | 120.3 | — |
| `POST /auth/link-info`, short token → 422 | none | 114.3 | 109.8 | 121.4 | 3.8 |
| `POST /auth/link-info`, unknown token → 400 | 1 SELECT (`account_links.PEEK_SQL`) | 433.0 | 430.4 | 472.7 | 513.9 |

- The 401 path costs the same as `/health`: a missing or invalid token is
  refused before any DB work (`deps.get_token_payload`). A token signed with
  this checkout's `JWT_SECRET_KEY` is also refused at the signature on Render,
  because Render's secret differs. So no authenticated path, and no session
  check, is reachable without a real sign-in.
- `/auth/link-info` is the one public route that reads the DB and writes
  nothing. A well-formed unknown token runs one SELECT and gets 400. A short
  token fails body validation (422) first, with no DB work.
- **Oregon → Mumbai round trip: it isn't one.** Render's DB-attributable delta
  (400 − 422) = **319 ms** (329 ms in an earlier run, console only; `results/` holds the later run). The same pair locally
  = 510 ms at a known 94.5 ms RTT (§4), i.e. 5.39 round-trip-equivalents
  (pre-ping 2, BEGIN 1, SELECT 1, plus the ROLLBACK this error path waits for,
  plus server time). 319 / 5.39 = **≈ 59 ms per round trip** from Render to
  Supabase (61 ms in the earlier run). That's faster than the laptop, and
  physically impossible for Oregon↔Mumbai (~12,900 km great-circle; light in
  fibre alone needs ≥ ~130 ms for the round trip). The `gcp-us-west1`
  CNAME is not where the service runs. Its region is **UNVERIFIED**: check the
  Render dashboard. 59 ms fits Singapore.
- Browser → Render overhead per request ≈ 114 ms (Cloudflare edge `HKG`,
  brotli on).

**Cold start** (measured, `/health` after the service had been idle):

| when (UTC) | idle before | result | source |
|---|---|---|---|
| 12:29:09 | unknown (first contact of the day) | 1st request: **no response in 180 s** (curl timeout); retry answered 200 after **64.4 s**; ≈ 4 min end to end | curl, this session (not in `results/`) |
| 14:49:20 | 16 min (no traffic from this session since 14:33:20) | **64.1 s** to the first 200, one attempt | `results/render_cold.jsonl` |

Two observations. 64 s is the repeatable part. The 180 s no-answer at
12:29 is a single event with an unknown cause (possibly a deploy or restart in
progress, UNVERIFIED). Warm `/health` right afterwards: ~110–115 ms. Our own
boot accounts for ≤ 5 s of the 64 s (§5b, cold-start row). The rest is
Render's spin-up of a sleeping free-tier instance.

**Estimated Render times** (`estimate` subcommand, `results/render_estimates.csv`).
Model: Render ≈ 114 ms (measured no-DB request) + (local median − 4 ms) ×
59.1 / 94.5, once per wave of parallel calls. This is valid because local time
is almost all DB round trips (§3a). It ignores Render's CPU (free tier,
unmeasured; pandas/pydantic would be slower there) and the browser's download
of the compressed body. **These are estimates, not measurements.**

| endpoint | principal | range | local median | Render est. |
|---|---|---|---:|---:|
| `/dashboard` | unilever | 1m / 12m | 4,730 / 4,577 | ~3,070 / ~2,970 |
| `/dashboard` | delmonte | 1m / 12m | 3,712 / 3,700 | ~2,430 / ~2,430 |
| `/recommendations` | unilever / delmonte | — | 1,584 / 947 | ~1,100 / ~700 |
| `/abc` last_known | unilever / delmonte | — | 1,412 / 924 | ~1,000 / ~690 |
| `/sku` | unilever / delmonte | — | 1,298 / 1,106 | ~920 / ~800 |
| `/fsn` | unilever / delmonte | — | 1,198 / 720 | ~860 / ~560 |
| `/pareto` | unilever | 1m / 12m | 647 / 666 | ~520 / ~530 |
| `/forecast`, `/segment`, `/decomposition` | unilever | — | 728–752 | ~570–580 |
| `/auth/me` | — | — | 402 | ~360 |

| page (parallel waves) | unilever local → Render est. | delmonte local → Render est. |
|---|---:|---:|
| Dashboard (12m default) | 4,484 → ~2,900 | 3,767 → ~2,470 |
| ABC | 2,729 → ~1,930 | 1,934 → ~1,430 |
| SKU Forecast (incl. first SKU) | 2,032 → ~1,500 | 1,828 → ~1,370 |
| Reorder | 1,647 → ~1,140 | 1,154 → ~830 |
| SKU Management | 1,362 → ~960 | 1,145 → ~830 |
| Category Trends | 712 → ~560 | 508 → ~430 |

To replace the estimates with measurements, rerun `time`/`pages` with
`--base https://logincred.onrender.com --token-env DSD_TOKEN` (see Rerun).

## 3. Per endpoint: queries, slowest statements, pandas, caching

### 3a. Where each request's time goes (local)

Fixed cost per request, measured with the backend's own engine (`select1`,
plus a phase breakdown):

| step | round trips | ms (local) | why |
|---|---:|---:|---|
| pool checkout `pool_pre_ping` | 2 | ~200 | the ping runs in autocommit, and with `postgresql_readonly=False` (`deps.py:73`) that adds a SET; without the option the ping costs 1 RT (97 ms), without pre-ping 0 |
| `BEGIN READ WRITE` (psycopg2 sends it before the first statement) | 1 | ~97 | |
| session check `ACTIVE_PRINCIPAL_SQL` (`deps.py:127`) | 1 | ~100 | every authenticated request, by design since 2026-09-28 |
| `ROLLBACK` when the session returns to the pool | 1 | ~97 | runs after the response body is sent, so the browser doesn't wait on it; it still holds a worker thread |
| **floor before the route's first query** | **4** | **~400** | `/admin/permissions/catalog` (no route query) = 410 ms |
| each route query | 1 + server exec | ~100–125 typical | |

In-process profile (cProfile, `results/profile_inprocess.csv`, auth check
bypassed): **pandas/numpy ≤ 27 ms** on every endpoint (`/pareto` 21–27,
`/category-trends` 21, `/fsn` 16, all others 0). Pydantic/JSON ≤ 50 ms
(`/abc` last_known). The rest is psycopg2 wait plus ~245 ms of
connection-protocol overhead (the SET/ROLLBACK round trips above).

| endpoint (unilever) | route queries | returning ≤ 1 row | duplicates in the same request | route-query DB ms |
|---|---:|---:|---|---:|
| `/dashboard` 12m | 36 | 24 | `MAX(planning_cycle_date)` ×2, monthly sales `SUM` ×3, inventory coverage ×2, `MAX(classification_period)` ×2 | 4,066 |
| `/dashboard` 12m (delmonte) | 31 | 22 | `MAX(planning_cycle_date)` ×2, sell-out `SUM` ×4, `MAX(classification_period)` ×2 | 3,100 |
| `/recommendations` | 10 | 9 | `MAX(planning_cycle_date)` ×2; 5 are the same LP-freshness lookups `/dashboard` runs | 1,189 |
| `/abc` last_known | 4 | 3 | — | ~850 |
| `/sku` | 3 | 2 | — | ~760 |
| `/fsn` | 2 | 1 | — (returns 8,735 rows for numpy) | ~640 |

### 3b. Slowest statements — EXPLAIN (ANALYZE, BUFFERS) in a read-only transaction

Full plans: `results/explain_local.md` (run 3). "Seen" = slowest time in the timing
runs, measured client-side, so it includes the round trip and row transfer.

| # | endpoint | seen ms | server exec ms (run 2 / run 3) | rows | what dominates |
|---|---|---:|---:|---:|---|
| 1 | `/sku` | 612 | 90 / 88 | 2,098 | "latest inventory period" subquery: 2 seq scans of `inventory_fact` (61k rows, 28k of them demo) ~34 ms; `DISTINCT ON` latest ABC tier over 23k `abc_classification` rows ~45 ms |
| 2 | `/abc` last_known | 606 | 124 / 120 | 1,531 | the same two subqueries + pool_run aggregate |
| 3 | `/fsn` | 536 | 41 / 30 | 8,735 | hash agg of the demand fact; the transfer of 8.7k rows is most of "seen" |
| 4 | `/abc` (Forecast page) | 460 | 56 / 55 | 710 | same inventory subquery ~34 ms |
| 5 | `/recommendations` | 252 | 52 / 53 | 73 | |
| 6 | `/category-trends` | 221 | 21 / 21 | — | |
| — | every `/dashboard` statement | ≤ 660 | ≤ 12 | ≤ 710 | none is expensive; 36 of them in sequence is the cost |

Existing indexes don't cover `inventory_fact(principal, _period)` or
`abc_classification(product_key, classification_period DESC) WHERE method='single'`.
The scans those indexes would replace cost ~34 ms and ~45 ms of server time.
That is an upper bound on what the indexes could save; they weren't built
(no writes).

### 3c. Run-to-run noise in the DB

Three times a statement ran 10–20× slower than its own rerun: EXPLAIN run 1
(`/sku` 2,113 ms against 90/88; one `/dashboard` query 653 ms against 7), the
first local `/dashboard` 1m Unilever (5,866 ms against ~4,600), and the profile's
`/dashboard` 12m (12,844 ms). In EXPLAIN run 1, an in-memory scan of the same
3,063 pages took 9 ms once and 1,426 ms again inside the same plan. That points
to the DB host's CPU, not to the query. `pg_stat_activity` showed no other
active query at the time. Each was rerun, and the tables use the reruns.

### 3d. Existing caching

| layer | what exists |
|---|---|
| browser | `api/cache.js`: **request de-duplication only**. Retention removed 2026-09-23 by request (TTL 0): every mount refetches. |
| HTTP | no `Cache-Control`/`ETag` on any route. Cloudflare in front of Render serves `cf-cache-status: DYNAMIC` (not cached) and compresses with brotli (`Content-Encoding: br`), so the 0.7 MB `/sku` and `/abc` bodies are compressed on the wire. |
| backend | no response or query cache. Only `auth_utils` `lru_cache` (secret key), `data_mode._outputs_cache` (preview files), `permissions._ready_cache` (table-exists check). |
| DB | no materialized views (`pg_matviews` empty) and no mart tables for the dashboard. |

## 4. `SELECT 1` × 20 to Supabase (`results/select1.json`, from the laptop)

| measurement | median | min | p90 | max |
|---|---:|---:|---:|---:|
| `SELECT 1` on one open connection, autocommit (pure RTT) | 94.5 | 93.6 | 96.2 | 96.9 |
| backend engine: checkout (pre-ping) + BEGIN + `SELECT 1` + return | 518.2 | 511.5 | 532.9 | 545.7 |
| new connection (TLS + pooler auth), once | 649 | | | |

The DB pooler is `aws-0-ap-south-1` (Mumbai). From Render the same round trip
is ≈ 59 ms (estimated, §2c).

## 5. Where the time goes, and what each lever would save

### 5a. Where it goes

| | Dashboard, unilever 12m (local 4,577 ms) | share |
|---|---:|---:|
| round trips before the route's first query (pre-ping 2, BEGIN 1, session check 1) | ~400 | 9% |
| 36 route queries × 94.5 ms round trip | 3,402 | 74% |
| those queries' server exec + row transfer (36-query total 4,066 − 3,402) | 664 | 15% |
| Python: pandas 0, pydantic ~10, the rest of the handler | ~50–150 | ~2% |

Every other route has the same shape at a smaller scale: 4 floor round trips +
1 per query (§3a), with server exec ≤ 124 ms per statement (§3b). **The cost is
the number of sequential round trips per request, not query cost, not
pandas, not payload size.** Range doesn't matter (1m ≈ 12m) because the query
count doesn't change with it. On Render each round trip is ~59 ms, not 94.5,
so Render pages are ~35% faster than local (estimate, §2c). The same levers
apply to both.

### 5b. What each lever would save

Savings in round trips (RT) × the measured RT: 94.5 ms local, ~59 ms Render
(estimated). Nothing below was built or tested. "Upper bound" = the measured
cost the change would remove.

| lever | where | saves per request | local ms | Render ms (est.) | needs |
|---|---|---|---:|---:|---|
| **Mart for the Dashboard**: one precomputed row set per (principal, period), refreshed by the pipeline after each load | `/dashboard` | 36 route queries → ~2: **34 RT** | ~3,200 | ~2,000 | a migration + a refresh step in the pipeline (DB write: Yuan's approval) |
| **Fewer round trips, no mart**: fold the 24 single-row "latest period / MAX / COUNT" lookups into one statement; reuse the 5 LP-freshness lookups shared with `/recommendations` | `/dashboard` (unilever 24 → 1, delmonte 22 → 1) | **21–23 RT** | ~2,000–2,200 | ~1,250–1,350 | code only |
| same, for `/recommendations` | 9 single-row lookups → 1 | **8 RT** | ~760 | ~470 | code only |
| **Turn off `pool_pre_ping`** (keep `pool_recycle`; retry once on a dropped connection) | every DB request | **2 RT** (the ping + the SET it triggers under `postgresql_readonly=False`, `deps.py:73`) | ~190 | ~120 | code only. Keep the readonly option: it's the pooler-leak guard. |
| **Short-lived session-check cache** (per process, e.g. 30 s) | every authenticated request | **1 RT** | ~95 | ~60 | **a decision**: since 2026-09-28 sign-out/demotion take effect on the very next request (`deps.py:138`); a cache delays that by its TTL |
| **Server response cache keyed on a data-version stamp** (stamp bumped by a trigger on every write path; each request does 1 stamp check) | `/dashboard`, `/abc`, `/sku`, `/fsn`, `/category-trends` | Dashboard ~40 RT → ~5 | ~3,300 on Dashboard | ~2,000 | **a decision**: 2026-09-23 removed browser retention ("figure on screen = figure in the DB when the page opened"). A stamp check keeps that rule only if every writer (ETL, pipeline scripts, app PATCHes) bumps the stamp. |
| **Indexes**: `inventory_fact(principal, _period) WHERE NOT is_demo`; `abc_classification(product_key, classification_period DESC) WHERE method='single'` | `/sku`, `/abc` ×2, Dashboard tier queries | server time only, not RT | upper bound ~34 + ~45 per call | same | a migration (DB write: approval). Small: ≤ ~80 ms per call. |
| **Front-end waves**: fire ABC's `/fsn` + `/pareto` with the *requested* period instead of waiting for `/abc` | ABC page | 1 wave ≈ the slower of `/fsn`/`/pareto` | ~1,200 | ~860 | code only. Caveat: the page uses the response's `classification_period`, which can differ from the one requested. |
| **Cold start**: always-on instance (paid) or an external keep-alive ping | first visit after ≥ 15 min idle | the spin-up (§2c) | — | ~64,000 (measured) | a hosting decision. Our own boot is ≤ 5 s (import 3.1 s, of which ~1.4 s is scipy via `backend.routers.abc` → `data_mode` → `analytics.segmentation.traits`, plus a 1.8 s startup DB check), so lazy imports would save ~1.4 s of a 64 s wait. |

Levers stack on round trips. Mart + no pre-ping takes the Dashboard from ~40
RT to ~4 RT (~0.4 s local, ~0.35 s Render est.), and the session cache adds
1 RT on top. Order by size and by needing no decision: Dashboard round-trip
folding → pre-ping → `/recommendations` folding are code-only and cover most of
the gap. The mart, the response cache and the session cache each need a call
from Yuan first.

## Side findings (not speed, not fixed — read-only)

- **F1. Del Monte forecast page always 404s.** The page passes each ABC row's
  `sku_id` (`SKUForecast.jsx:291`). For Del Monte that's the category path, but
  `/forecast` looks up `WHERE sku_code = :sku_id` only (`forecast.py:70-76`),
  and Del Monte rows have no `sku_code`. Same 404 from `/segment` and `/decomposition`.
- **F2. Render's region isn't what DNS suggests.** `logincred.onrender.com`
  CNAMEs to `gcp-us-west1-1.origin.onrender.com`, but the measured Render →
  Supabase (Mumbai) round trip is ≈ 59 ms (§2c), which Oregon can't do. Confirm
  the region in the Render dashboard. There's no evidence of a cross-region
  penalty to fix.

## Rerun

From the repo root with the venv active. Every step is read-only.

```
P=reports/diagnostics/speed_baseline_2026-10-04/speed_baseline.py
python $P select1                                   # §4
python $P serve --port 8077 &                       # instrumented local API -> results/requests_local.jsonl
python $P time  --label local                       # §2a -> results/timings_local.csv
python $P time  --label local --only dashboard      # rerun a subset -> results/timings_local_rerun.csv
python $P pages --label local                       # §2b
python $P explain --label local --top 12            # §3b (uses the jsonl from serve)
python $P profile                                   # §3a pandas/pydantic split
python $P render                                    # §2c token-free Render probes + RTT (needs `serve` running for calibration)
python $P render --cold                             # §2c one cold-start probe; run after >= 15 min with no traffic
python $P estimate                                  # §2c Render estimates -> results/render_estimates.csv
python $P summary local                             # §2a markdown table
# With a real signed-in token (not done 2026-10-04), measured Render instead of estimated:
DSD_TOKEN=<token> python $P time  --base https://logincred.onrender.com --label render --token-env DSD_TOKEN
DSD_TOKEN=<token> python $P pages --base https://logincred.onrender.com --label render --token-env DSD_TOKEN
```

In Git Bash, pass `--only dashboard`, not `--only /dashboard`. MSYS rewrites a
leading `/` into a Windows path.
