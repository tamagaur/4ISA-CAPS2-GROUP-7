# Pipeline, rollover and API QA on a throwaway local database, 2026-10-30 (kelvin/freeze-package at 5507f41)

Written for: the repo owner and the backend developers, who need to know what a monthly run does when it is run wrongly, and what the QA of 2026-10-24 did not cover.

## What this is, and what it cannot show

| Item | Value |
|---|---|
| Machine | Intel Core i7-13620H, 63.7 GB RAM, Windows 11 Home 10.0.26200, Python 3.13.14 |
| Database | PostgreSQL 17.11 (the Windows installer's binaries), a private cluster on `127.0.0.1:55432`, `fsync=off`, SSL on with a self-signed certificate (the code connects with `sslmode=require`). Data directory `local/pg_throwaway` (git-ignored). Docker, WSL and a system Postgres were not available. |
| Source of the data | `backups/full_backup_20261016T070624Z`: a whole-database backup (4 schemas, 51 tables, 484,575 rows), restored by `scripts/local_pg.py restore` in 25.6 s with 0 structure errors and every table's row count equal to its manifest. Nothing was read from live. No dump was taken. |
| Isolation | `LOCAL_PG_URL` is the only variable the harness reads. `scripts/local_pg.py run` copies it into `SUPABASE_DB_URL` **and `SUPABASE_DIRECT_URL`** (also read by `analytics/config.py:90`) for the child process only, and refuses to start unless the child resolves to `127.0.0.1:55432`. The repo's `.env` is a live fallback for any variable not overridden, which is why both are set. |
| Synthetic month | March 2026 per-SKU sales do not exist in the real sources. `local_pipeline_qa.py synth` generates them from each product's own February (0.8 to 1.2 times, the rule `rollover_scratch_test.py` uses), `_src_file = 'qa_synthetic_march'`. 709 rows. The real loader was not run: it needs raw files for a month that has none. |
| Limit | **Local timings and local behaviour do not establish behaviour on Render or Supabase.** There is no network latency here, `fsync` is off, and the server has one user. The restored data is the backup's (16 Oct), not today's live data. |

## Task 1. The local database, and the 18 skipped tests

| Step | Result |
|---|---|
| Restore the backup | 25.6 s. Plan as restored (cycle 2026-03, unilever): **97 rows, 356,254.11 pieces, lp_run 2**, 98 rows in the cycle including the one accepted legacy row. Not 109 / 435,988: that invariant is live's, and this copy predates 0066 and the orphan exclusion. |
| Migrations 0057 to 0069 through the runner (`--schema public --target-public --schema-only`, driven one file at a time) | **13 of 13 applied, rc 0, 0.1 to 0.2 s each; ledger 57 to 70 entries; the tables of 0067 to 0069 exist.** The backup was at 0056, so the pending set was 13 files, not 4. |
| Plan after each of 0057 to 0069 | Unchanged after every one: 97 rows, 356,254.11 pieces. Migrations change structure, not plan rows. The plan moves only when the LP is re-run on the migrated schema: **97 rows, 360,956 pieces** (case-pack rounding, 0066; run 3). Not investigated why live reads 109 rows (the Tier A basis and ABC at 16 Oct against today were not compared). |
| `tests/etl/test_fills_db.py` (17, needs `FILLS_SCRATCH_SCHEMA`) | **17 passed**, 73 s, on `ssm_fills` built by `rehearse_fills --build` plus `fill_missing` (13 s + 11 s). |
| `tests/etl/test_rollover_scratch.py` (1, needs `ROLLOVER_SCRATCH`) | **Failed three times for reasons that were not the pipeline code, then passed 60 of 60 (28 s).** (1) It pins the live plan, `EXPECTED_PLAN = (109, 435988.0)`; fixed by an opt-in `ROLLOVER_EXPECTED_PLAN="rows,pieces"`, default unchanged. (2) On the pre-0066 plan a decided quantity of 9,118.64 is not a whole number of 24-piece cases (422 `not_whole_cases`); fixed by re-running the LP on the migrated copy, the correct state for a post-0066 database. (3) A real fixture defect: the April scaffold copied `LIMIT 3` ABC rows from February with no method filter and no ORDER BY, so on a restored copy it copied rows of the wrong method and `close_cycle` correctly refused. Fixed in `scripts/rollover_scratch_test.py` (method filter, `ORDER BY product_key`). The docstring says 61 checks; 60 ran. |

This is the first execution of that SQL outside live: the migration path from the 16 Oct schema to 0069 is sound, and the receipt ledger, settlement, opening-stock view and close ran on a Postgres that is not Supabase's.

## Task 2. The pipeline sequence, locally

Order run: load (synthetic March) → ABC (`orchestrate_abc --period 2026-03 --method t12m_new --principal unilever`) → forecast (`run_baseline_forecast.py --write --calendar-factor`, as live was written) → safety stock, target and LP (`run_lp.py --retire-stale-pending`, one script) → marts (`analytics.marts.refresh_marts`) → `close_cycle --cycle 2026-03`.

| Step | Wall clock |
|---|---|
| load (synthetic March, 709 rows) | 0.3 s |
| ABC (1,083 products; A 191 / B 232 / C 660) | 2.9 s |
| forecast (191 Tier A rows to 2026-04-01) | 48.4 s |
| safety stock, target, LP (121 rows for cycle 2026-04) | 33.0 s |
| marts refresh | 19.6 s |
| close_cycle | 0.4 s |
| **Total** | **104.6 s** |

The April plan reads 110 rows ordering more than 0 and 1,213,168 pieces, against 356,254 to 360,956 for March. The jump is consistent with March having been planned from the 2 Mar count, which STATE.md records as about twice its neighbours (blocked on SSM); April used the 6 Apr count. Not investigated further.

### Breaking the sequence (each scenario on a fresh copy of the migrated database)

| # | What was done | What happened | Verdict |
|---|---|---|---|
| a1 | `close_cycle` with nothing run after the load | rc 2, "REFUSED: the ABC run …; the forecast …; the LP run …". Nothing written, no `planning_cycle` row. | Refuses clearly |
| a2 | `close_cycle` after ABC, before the forecast | rc 2, names the forecast and the LP run. Nothing written. | Refuses clearly |
| b1 | forecast then LP, with **no March ABC** | forecast logs `ABC period resolved: 2026-02 (latest real demand month: 2026-03)` at INFO and writes 189 rows; LP rc 0 writes 119 rows (1,213,576 pieces) on February's Tier A. Only `close_cycle` would refuse (finding 2). | Does not refuse; no corruption, cycle is caught at close |
| b2 | LP with **no April forecast** | rc 0. A new `lp_run` (3) for cycle **2026-03**; its 97 pending rows were upserted (finding 1). | Does not refuse |
| c | every step run a second time on the finished database | ABC, forecast and plan fingerprints (a hash of product and value per row) identical before and after; `close_cycle` "already closed … nothing changed". Only bookkeeping grew: `lp_run` 3 to 4, `mart.refresh_log` 17 to 23. | Idempotent |
| d1 | forecast write fails after 60 rows (a trigger raising on the 61st insert) | rc 1; no 2026-04 rows, the 189 March rows untouched. Rerun reproduced the happy-path fingerprint exactly. | Atomic, recovers |
| d2 | LP write fails after 40 rows | rc 1; no 2026-04 rows, no stranded `lp_run` row (runs stay 1, 2). Rerun reproduced the happy-path plan fingerprint exactly (121 rows, 1,213,168 pieces). `lp_run` keys skip a number (the sequence advanced). | Atomic, recovers |
| d3 | `close_cycle`'s second step fails after 30 updates | rc 1; `planning_cycle` = `closing`, steps_done `{settle_receipts}`, no plan row closed. Rerun resumed: `close_plan` ran, 98 rows closed, state `closed`. | Documented state machine works; nothing stranded |
| e | close 2026-04 right after closing 2026-03, with no new data; 2026-03 again; 2026-05; `--expect-cycle` mismatch | 2026-04 and 2026-05: rc 2, all five checks MISSING, nothing written. 2026-03 again: "already closed … nothing changed". Mismatch: argparse error, "nothing written". State fingerprint identical before and after. | Refuses or is idempotent |

No scenario corrupted state or left a cycle stranded. The two that do not refuse (b1, b2) are findings 1 and 2.

## Task 3. The rollover, end to end

`scripts/rollover_scratch_test.py` on a clone of the migrated copy: **60 of 60 checks passed** (28 s, `--keep`). It accepted orders on the March plan (a plain accept, a direct apply, a granted user's change applied at once, a planner's change held then approved, a dismissal), reversed one (its receipt is kept and cancelled; accepting again gives a new live receipt), used the **real 6 Apr 2026 count already loaded** for March (`_period 2026-03`, no April count was loaded by this session), checked that receipts expected on or before the count date settle (2) and later ones stay expected (5), closed the cycle, reopened it, closed again, and proved public, mart and app were byte-identical afterwards.

Formula checked by hand by this session, apart from the test's own checks: April opening = count pieces + receipts still on the way (state `expected`, expected on after the count date, from earlier cycles).

| Product | Count (6 Apr) | On the way | Hand | `stock_opening_v` |
|---|---|---|---|---|
| 38 | 102 | 16,992 | 17,094 | 17,094 |
| 39 | 4,901 | 9,216 | 14,117 | 14,117 |
| 52 | 7,878 | 4,896 | 12,774 | 12,774 |

(The test's own hand checks also match: six products on the projected basis, 159, 260, 52, 70, 174 and 39, and five on the count basis, 159, 260, 52, 70 and 39.)

## Task 4. QA sweep since `QA_BACKEND_2026-10-24.md`

Method: the real FastAPI app in process (`backend.main.app`, TestClient), real users in `app.users`, real sign-in and sessions, on the throwaway database. Harness: `scripts/local_api_qa.py` and `scripts/local_api_qa_*.py`; run `python -m scripts.local_pg run -- python -m scripts.local_api_qa <name>`. Five identities: admin; view-only (staff preset); decide-only (`lp.view` removed, `lp.decide` granted); no-LP (`lp.view` removed); bare (everything removed).

### Findings, ranked (10; every one reproduced)

| # | Severity | Finding | Exact reproduction |
|---|---|---|---|
| 1 | Medium | **Running the LP before the next cycle's forecast exists re-plans the cycle already planned, with no "already planned" notice.** The cycle is named in the log, but its pending rows are upserted and the figures move (356,254 to 360,956 pieces on the migrated copy; 97 rows kept). Anyone who runs `run_lp.py` out of order changes the plan that was reviewed. Decided rows are not touched. | Restore + migrate, then `python -m scripts.local_pg run -- python scripts/run_lp.py --retire-stale-pending`: rc 0, new `lp_run` 3 for `2026-03-01`. Or scenario b2: `python scripts/local_pipeline_qa.py synth` then the same command. |
| 2 | Medium | **Forecast and LP accept a stale ABC period without refusing.** With no March ABC the forecast logs `ABC period resolved: 2026-02 (latest real demand month: 2026-03)` at INFO and the LP plans April's Tier A from February's classification, rc 0. Only `close_cycle` (check `abc_run`) catches it, after the plan exists. | Migrated copy, then `local_pipeline_qa.py synth`; `local_pipeline_qa.py step forecast`; `local_pipeline_qa.py step lp`. Both rc 0, `abc_2026-03_t12m_new: 0` in `local_pipeline_qa.py state`. |
| 3 | Medium-Low | **After a second ABC re-run, `GET /abc` (cached) keeps serving the old classes.** The cache's data version is `mart.refresh_status`, which does not carry `abc_classification.computed_at`. The first re-run flips `planning_stale` and clears the cache; later ones do not move the version. In the standard monthly order a forecast follows the ABC and moves it, so this bites only an ABC run on its own (a basis change, a re-run). | `python -m scripts.local_pg run -- python -m scripts.local_api_qa abc`: after a mart refresh, change 1 is served fresh, changes 2 and 3 are served from the cache (`request after the change was a cache hit: True`, `served == fresh? False`). |
| 4 | Low-Medium | **Running the next month's forecast deletes some of the previous cycle's forecast rows.** `forecast_result` rows at `forecast_date` 2026-03-01 fell 189 to 182 after the April run ("dumped 7 orphaned rows … deleting them"). The only record is `reports/orphaned_sarima_rows_2026-03.json`, in a git-ignored folder. | Migrated copy, `synth`, `step abc`, `step forecast`; then `select count(*) from forecast_result where forecast_date='2026-03-01'`. |
| 5 | Low | **`close_cycle`'s gate tests existence, not completeness.** One forecast row and one LP row for the next cycle pass all five checks and the close writes (98 rows closed). The pipeline cannot produce that state (each write is one transaction, scenarios d1 and d2), so it needs a manual edit to reach. | Scenario d4: after `synth` and `step abc`, insert one `forecast_result` row at `2026-04-01` and one `lp_recommendation` row at `2026-04-01` with an `lp_run_key`, then `step close`. rc 0. |
| 6 | Low | **The response cache does nothing in a fresh process until a mart-reading route has run.** `GET /abc`, `/pareto`, `/category-trends` ×4 in a new process: `entries 0, hits 0, misses 0`. The session check only reads the data version once `marts.present_known()` is true, which `/dashboard` sets. After a restart on Render the first requests are uncached. | In a new process, `GET /pareto?principal=unilever` ×3 then `GET /abc?principal=unilever` ×4 as any signed-in user, then `response_cache.stats()`: `entries 0, hits 0, misses 0`. `GET /dashboard?principal=unilever` twice then caches (entries 1, misses 1). `python -m scripts.local_pg run -- python -m scripts.local_api_qa cache`, section 1, lists `/abc`, `/category-trends` and `/dashboard` as the routes that missed on first use. |
| 7 | Low | **`GET /category-trends?principal=delmonte` sends `revenue: 0.0` on `category_absent` history points** (3 of them). The reason is set and the page nulls them (`frontend/src/components/CategoryTrends.jsx:106`), so no chart plots a zero today. Any other consumer would get a zero for what the rules call a collection gap. | `GET /category-trends?principal=delmonte` as any user with `category_trends.view`; `python -m scripts.local_pg run -- python -m scripts.local_api_qa absent`. |
| 8 | Low | **The permissions PUT accepts and stores a contradictory override.** `{"role":"staff","overrides":{"lp.view":false,"lp.decide":true}}` stores `lp.view:false`, while the effective list contains `lp.view`. The admin screen's `overrides` shows a removal that has no effect. The frontend was not examined. | `PUT /admin/users/{id}/permissions` with that body as admin, then `GET /admin/users/{id}/permissions`: `overrides {"lp.decide":true,"lp.view":false}`, `permissions` includes `lp.view`. |
| 9 | Low | **The forecast runner rewrites a tracked file on every run, including a local or demo one.** `reports/BASELINE_FORECAST_RUN.md` shows modified after `run_baseline_forecast.py` (real or `--source demo`), so a clean tree is not clean after a run, and a rehearsal could be committed by accident. | `python scripts/run_baseline_forecast.py --source demo --principal delmonte --write`, then `git status --short`. |
| 10 | Low | **`kpis.weeks_of_cover.stock_value` is in pesos (46,576,778.51) beside `basis: "pieces"`.** The figure 7.06 is on pieces, as pinned, but anyone dividing that value reproduces the retired pesos basis (6.21). | `GET /dashboard?principal=unilever&period=2026-02`. |

### What held (not repeated)

| Area | Result |
|---|---|
| `lp.decide` implies `lp.view`, walked with the three identities | **No defect found.** Decide-only sees every LP figure on `/recommendations`, `/dashboard`, `/policy-comparison`, `/inventory/current` and the four error-decomposition routes (200), and can decide (200), propose a quantity change (400 `quantity_unchanged` for the same quantity) and read `/recommendations/changes`; it cannot reverse (403 `admin_required`). View-only: reads, but PATCH 403 `lp.decide`. No-LP and bare: `/recommendations` and `/policy-comparison` 403 `lp.view`; `/inventory/current` and the four error-decomposition routes 403 `lp.view`; `/dashboard` and `/sku` leave the LP figures out; `/abc` degrades `stock_status` to `ON HAND`. `/auth/me` and the admin permission read agree on the effective list. **Revoking takes effect on the next request** (PATCH and GET both 403 at once; no stale cached `/dashboard` LP block). A user with only `lp.decide` reaches `/recommendations` and `/policy-comparison` and is still refused `/dashboard`, `/abc` and `/inventory/current` (their own keys). |
| Cache isolation across permissions | **No cross-user leak.** Every one of 17 cached routes, in both orders, for view-only against no-LP and decide-only against no-LP: the answer served from another user's warm entry equals the freshly computed one. Two users with identical permissions get identical bytes, warm or fresh. |
| Stale entries after an `etl_load_event` | A real load event (rows added 5) cleared the cache; a dry-run event and a zero-row event correctly did not. Close and settle cannot leave a stale cached answer: no cached route reads `expected_receipt` or `closed_at`. |
| The 64-entry cap | 8 threads, 192 requests over 90 distinct keys: **0 wrong or non-200 answers**, 64 entries after (cap 64). Eviction cannot drop the entry being stored (`move_to_end` before `popitem`). |
| Phase D, pesos cover basis | **No path returns it.** `kpis.weeks_of_cover` = 7.06 on `basis: pieces` (pinned figure, reproduced on this copy); `inventory.weeks_of_cover` and `cover_series` are null; per-SKU `days_of_cover` checked by hand on SKUs 69668148 (59.6 days), 69668140 (452.2) and 68690510 (72.2) with the 3-month window the code documents, all equal. No peso field remains on a recommendation item. (See finding 10 for the one pesos value that sits next to it.) |
| Phase D, `category_absent` | Class changes send `revenue: None` with `category_absent` / `not_collected` on every Del Monte comparison tried (2025 against 2024, against 2023, 2023 against 2022, mid-gap). The only chart consuming `category_absent` plots a break, not a zero. See finding 7 for the API value. |
| The demo path | Builds and plans run on the migrated schema (`run_baseline_forecast --source demo` for both principals 5 s and 4 s, `run_lp --source demo` 4 s and 12 s; run 7 and 8, Del Monte plan 5 rows, Unilever 96). **`verify_demo_isolation`: PASS, 18 relations unchanged, 0 `is_demo` rows in a `_Real` view, 0 generated months in `SellOut_Fact_Real`.** With the flag off every `/demo/*` is 404 and `X-Data-Mode: preview` adds nothing. With it on, 15 real endpoints are byte-identical without the preview header; with it, `demonstration: true` and `data_source: synthetic_demonstration` are on every demo response, origins are only the sanctioned ones, and no accuracy field (mape, mase, wape, confidence) appears in a demonstration response. The demo order plan and policy comparison are hidden from a user without `lp.view` (BE-13). `tests/demo`: 41 passed. |
| Invariants on this copy | `tests/invariants`: 11 passed, 1 failed. The failure is the STATE.md plan line (109 / 435,988 / run 6) against this copy (97 / 360,956 / run 3): correct for a 16 Oct backup, not a defect. The pinned-figures invariant passes here. |

### Looked at and left out

Findings I could not reproduce are not listed. Not run: concurrent writers racing on one committed row, the frontend (out of scope), `/auth/mfa/*`, the real loader on a real March file, and Render or Supabase behaviour.

## What was added, and how to rerun

| File | Purpose |
|---|---|
| `scripts/local_pg.py` | start / stop / restore / run for the throwaway cluster, with the localhost guard |
| `scripts/local_pipeline_qa.py` | synthetic March, each pipeline step, state fingerprints, the happy path |
| `scripts/local_api_qa.py` and `local_api_qa_*.py` | the API harness and the sweeps above |
| `scripts/rollover_scratch_test.py` | `ROLLOVER_EXPECTED_PLAN` override; deterministic ABC scaffold |

Rerun: `python -m scripts.local_pg start`; `python -m scripts.local_pg restore backups/full_backup_20261016T070624Z`; apply 0057 to 0069 through the runner under `local_pg run`; then the commands in each table. A Docker compose file was not written: Docker was not installed, so it could not have been run.

## Figures that moved
none (live was not read or written; the local copy reads 97 rows / 356,254 pieces restored, 360,956 after an LP re-run, and the 109 / 435,988 invariant is live's)

## Decisions needed
Finding 1 and 2: whether the LP should refuse a cycle it has already planned, and a stale ABC period, or only warn. Finding 4: whether the previous cycle's forecast rows should survive the next run.

## Contradictions found
`rollover_scratch_test.py` says it asserts 61 checks; 60 ran. RUNNING.md and the test's pinned 109 / 435,988 describe live, not a restored backup.
