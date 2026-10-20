# SSM Decision Support Dashboard (DSD) — Capstone Group 7

## Project
3ISA/4ISA Group 7, IS-BA Track, UST CICS. SSM Decision Support Dashboard for San San Marketing (SSM), FMCG distributor, Urdaneta, Pangasinan. Two principals only: Unilever Philippines, Del Monte Philippines. Magnolia is OUT OF SCOPE — ignore Magnolia refs in old files. Never call it "DSS" — it's DSD.

Problem: SSM's blanket 3-week safety stock rule causes trapped capital + spoilage. DSD gives per-SKU data-driven replenishment recommendations.

Pipeline: ETL → ABC/Pareto classification → forecasting (deployed: MA3, 3-month moving average — see run_baseline_forecast.py:748; SARIMA was bake-off'd against 16 other models and retired, never deployed) → safety stock/ROP → multi-objective LP optimization (PuLP, w1=0.45, w2=0.35, w3=0.20) → dashboard.

Tier A basis (DEC-38, PENDING TA CONFIRMATION, 2026-10-05): Unilever Tier A = Class A on the last 12 months + products first sold within 12 months that are Class A on the last 3 (ABC method `t12m_new`; 189 products as of 2026-02). The setting is `analytics.params.TIER_A_BASIS`; read it through `abc_method()` / `abc_method_sql()`, never a literal `method = 'single'`. Del Monte stays on `single`.

## Repo
https://github.com/4ISA-Capstone-Group-7/SSM_DSD (UNDERSCORE) — remote `newrepo`. Push and pull ONLY here: backend to `Main-BE`, frontend to `Main-FE`, `Main-Final` by pull request (see "Branch convention" below). Local `kelvin-etl` tracks `newrepo/Main-BE`; push with an explicit refspec, e.g. `git push newrepo kelvin-etl:Main-BE`. Retired, never push there (corrected 2026-10-19): `group7` = 4ISA-Capstone-Group-7/SSM-DSD (HYPHEN), whose `kelvin-etl` was the old base branch, and KYG07/Capstone-Project.
Each session works in its own worktree on a branch named `kelvin/<name>`.
Migrations: 0046 (planning mart `mart.planning_mart`, part of DEC-36, 2026-10-05) is the latest on public, after 0044 (Tier A basis `t12m_new`, DEC-38, 2026-10-05), 0043 (mart stock-limited rule, DEC-36), 0042 (in-transit stock + review flag, DEC-33/34) and 0041 (data marts, schema `mart`, DEC-36), all 2026-10-04. 0045 (`Product_Dimension.unit_cost` + `lead_time_days`) and 0047 (`planning_stale` knows the Tier A basis) are now used too (files on kelvin-etl; whether they are applied to public is not recorded here). 0048-0051 are applied (app schema, planning-mart tier anchor, inventory index + month marts, stability_group pattern). 0052-0055 (schema `demo`: the labelled demonstration pipeline, its back-cast, the Del Monte bridge, `anchor_override` and the canonical-total column and view; rule 2) are applied 2026-10-15. 0056 (`demo.dm_category_stock`, `demo.unilever_sku_forecast`, `demo.dm_category_lp` — Del Monte stock, the Unilever demonstration forecast, and the Del Monte demonstration order plan; rule 2 extended by Kelvin 2026-10-16) and 0057 (`forward_filled` origin, `demo.dm_category_lp.stock_source`, `demo.unilever_sku_forecast.blank_capture_filled`, `demo.unilever_sku_lp` — DAIRY's forecast, the Unilever demonstration order plan on real stock, and the "no empty card" standing instruction) are applied 2026-10-16. 0058 (`app.users.avatar_data_url`, base64 profile pictures) IS APPLIED to public (2026-10-16 11:01 UTC) and is never edited or renumbered now that it's live — retired instead by 0060 (below), per hard rule 8's "a column can't be un-applied by deleting its migration file." 0059 (`app.users.avatar_path`, a Supabase Storage object path) and 0060 (drops `avatar_data_url`: base64 image bytes in a column are uncacheable and were costing ~400MB/month of egress against a 5GB free-tier budget) were written on kelvin/merge-main-final-conflict, 2026-10-18, resolving a genuine number collision where 0058 was independently used by two files (caught by `scripts/run_canonical_load._assert_no_new_number_collision`; see 0059's header comment), and APPLIED to public 2026-10-19 (09:01 / 09:03 UTC, backup `backups/tables_20261019T090050Z`). 0060 as first written failed on live (it dropped the column while `public.users` still selected it) and was fixed before it ever applied: drop view, drop column, re-create view, repeat 0048's REVOKE. The one non-null `avatar_data_url` (1 of 5 users) is gone from live and kept only in that backup. Main-Final's backend still reads `avatar_data_url`; a server running it must be restarted (its column check caches "ready"). 0061 (`planning_stale` also knows the review flags) is applied. 0062 (`lp_recommendation.decided_q_i` + `decision_reason`: the planner's quantity and reason, capture only; nothing in forecasting, safety stock or the LP reads them) is APPLIED to public 2026-10-21, backup `backups/tables_20261020T174604Z`. The next free number is 0063.

**Any migration that adds or drops a column on `app.users` must re-create `public.users` (the compatibility view, 0048) with app.users' COMPLETE current column list, not just the column it's touching** — CREATE OR REPLACE VIEW silently drops any column left out, so two migrations each listing only their own column means whichever applies second erases the other's from the view (this is exactly how 0058/0059 collided). `tests/backend/test_migrations.py` statically checks every `public.users` view against every `ALTER TABLE app.users ADD/DROP COLUMN` up to that point in the migration order and fails the build if they disagree.

## Branch convention (canonical repo: 4ISA-Capstone-Group-7/SSM_DSD, underscore)
`Main-Final` is the integration branch and receives merges via pull request only — nobody pushes directly to it.
Backend work goes to `Main-BE`; frontend work goes to `Main-FE`. (This is a team convention, not a
GitHub-enforced rule: branch protection needs GitHub Pro or a public repo, and this repo stays private.)

## Stack
Python/pandas ETL, FastAPI backend, Next.js/Tailwind frontend, Supabase (Postgres), Vercel (frontend host), Render (backend host).

## Team
Yuan — ETL, DB schema, Supabase, orchestration, repo owner, all pipeline decisions, demo data
Maika — frontend, auth, deployment, backend
Audrey — backend endpoints, backend & frontend, LP
Thea — models, manuscript, SSM liaison, frontend design
Kelvin — frontend integration (kelvin-etl branch)
Advisers: Sir Catubag (technical)

## Hard rules
1. **Data interface rule**: model code reads the `_Real` views (schema.sql:698-714 — `Sales_Fact_Real`, `Inventory_Fact_Real`, `Unilever_SKU_Demand_Fact_Real`, etc.), never the base fact tables directly and never raw files. These views structurally exclude `is_demo=true` rows (`WHERE is_demo = false`), so a real-vs-synthetic mixup is a query-target mistake, not a filter a caller can forget. (`get_demand_series()` does not exist anywhere in this codebase — corrected 2026-08.)
2. **Anti-fabrication rule (sanctioned exception)**: no invented numbers in manuscript/defense/reported results. Synthetic data (is_demo=true) IS approved for frontend validation only — don't relitigate, adviser already approved it. **Generated/filled data never feeds KPIs, forecasts, ABC or the LP; charts may show it labelled as estimated.**
   **Sanctioned demonstration path (approved by Kelvin, 2026-10-15; Sir Catubag informed — recorded here so a later session does not revert it):** a labelled demonstration pipeline (Del Monte categories, Unilever SKUs for the 2021-2022 back-cast only) may write generated data, but only to the separate `demo` schema, every row `is_demo=true` and `fill_source='synthetic_dm_pipeline_demo'`, with no accuracy metrics (no mape/mase/wape, no confidence bands; a schema test enforces it), in its own `demo.run`, never in a real cohort, and exposed only behind an explicit API demonstration flag (`demonstration: true`, `data_source: "synthetic_demonstration"`). Generated months carry one of four origins, kept strictly apart in data, API and reports: `real_copy`; `interpolated` (between two real months of the same series); `bridged` (Del Monte only: each pre-2025 path carried from its last real month through 2025-02 across the taxonomy change; that is extrapolation, and rule 14 is suspended for that window only, by Kelvin's decision of 2026-10-15); `backcast` (2021-01 onward, no real data on either side; flat at the series' own level with seeded jitter, no trend). **Anchor override, Del Monte only:** Unilever's back-cast requires the series' first real month to be 2023-01 (a SKU first sold later is a genuine launch; projecting it back would invent that it existed); Del Monte's does not, because its five 2025 categories (BEVERAGE, CULINARY, DAIRY, FRUITS, INNOVATION) and its sub-categories first seen after 2023-01 are a relabelling of a business that existed in 2021, not new products. Those rows stay `origin='backcast'` and carry `anchor_override` (API: `generated_before_first_observation: true`). Unilever's in-span gaps are never filled: they are real zero-sale months (see "Why data is missing"). `demo.*` is the SINGLE display source for anything generated, both principals: the older `synthetic_v2` rows (8,444 Unilever and 2,932 Del Monte base rows, 914 Del Monte rows in `mart.sales_mart`) are retired for display, and so are the filled sales rows in `mart.sales_mart` (3,130 `synthetic_category_split`, 4 `synthetic_v2_gap`): no reader serves a non-real sales row any more, nothing is deleted, and `X-Data-Mode: preview` reads `demo.*` only when the flag is on. Nothing generated reaches a `_Real` view, a real forecast, accuracy or the LP, and results from it are never presented as real.
   **Extended by Kelvin, 2026-10-16 (migration 0056) to stock and the order plan:** `demo.dm_category_stock` adds a
   FIFTH kind of generated row, Del Monte stock on hand, with its own origin `generated_months_of_cover` — unlike
   the four sales origins above it has NO real anchor anywhere (`Inventory_Fact_Real` is SKU grain only for Del
   Monte and carries no `category_path`), so it is never `real_copy`: a seeded draw centred on SSM's "about 3
   weeks of sales in stock" policy (`analytics.params.POLICY_COVER_WEEKS`), jittered by the category's own CV,
   against that category's own demonstration demand (`analytics/demo/stock.py`). `demo.unilever_sku_forecast`
   adds a one-step MA3 per Unilever SKU over real_copy months only (`scripts/build_unilever_demo.py`) — not wired
   into any endpoint, since Unilever's real `Forecast_Result` already exists and is unaffected; it matches the
   real forecast exactly where the real deployed model for that SKU is also MA3 (36 of 179 comparable SKUs,
   median difference 0.0), and differs where the real model is TSB or the XGBoost+MA3 average instead (a
   model-routing difference, not a demo-generation bug). `demo.dm_category_lp` adds the Del Monte demonstration
   order plan (`analytics/demo/prescriptive.py`): the real safety-stock/target-stock formulas over the
   demonstration's own forecast AND stock — two generated layers, stated in every row's `demonstration_note` —
   with NO allocation or warehouse ceiling (neither exists for Del Monte; reusing Unilever's real
   `warehouse_capacity` would conflate two different quantity units, DEC-31). `run_lp --source demo` is now
   accepted for `--principal delmonte` only (still refused for `unilever`/`both`); `/recommendations` and
   `/dashboard` now serve `order_plan.available: true` with items once that run has been written.
   **Audit fix, Kelvin, 2026-10-16 (B1/B2/B3):** "no reader serves a non-real sales row any more" above was
   scoped to `mart.sales_mart` only and missed two siblings still reading the retired synthetic family straight
   out of the fact tables: `mart.flow_month`'s `returns` (synthetic_v2/synthetic_v2_gap/synthetic_rate_transfer/
   synthetic_branch_adjacent — Unilever has no real returns at all, so with the demo switch off its whole
   Returns line was 100% synthetic) and `mart.inventory_mart`'s stock pesos (same family, both principals, in
   preview too). `backend/marts.flow_by_period` now never estimates `returns`; `estimated_stock_by_period`
   always returns `{}` (same retirement as `estimated_sales_by_period`, no demo stock/returns analog is wired
   into this chart). Separately, `backend/marts._unranked_side` (class-changes) and `pareto()`'s "ranked
   nothing" message used to treat "no real sales row in the range" as a real zero for every principal; for Del
   Monte that is two different things — a genuine zero vs the Mar2024-Feb2025 taxonomy-break gap where nothing
   was collected at all — and conflating them fabricated a joined category's whole revenue as growth. Fixed:
   `principal_collected()` checks whether the principal has any real row at all in the range; `_unranked_side`
   returns `None`/`not_collected` (not `0.0`) for Del Monte when it doesn't, and `pareto_blocked_reason()` gives
   the right cause (`not_collected` vs "nothing sold" vs "returns matched or exceeded sales everywhere").
3. **No fabricated metrics as fallback, ever.** If a real computation isn't possible (e.g. <12mo history, model exception), the correct value is a flagged "insufficient data" status — never a hardcoded number pretending to be measured.
4. **Hard gates**: M0, M2, M3 are human-review checkpoints. Don't cross a gate in one session — stop and report at gate boundaries.
5. **Commit only on your own branch; merge or push only when asked.**
6. **Verify before asserting.** Never state file counts, row counts, or test results without actually running something. Never describe planned/intended behavior as current state.
7. **Database (Supabase via the :6543 pooler): never `set_session(readonly=True)` or any session-level `SET`.** Read-only = `BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK`.
8. **Live database writes only through committed, numbered migrations + the runner (`scripts/run_canonical_load.py --schema public --target-public --schema-only`), after a backup.**
9. **No per-product sales or prices committed to git** — keep them in the git-ignored `local/` folder.

## Known open items (2026-09)
- Retired: run_sarima.py (dead code, not deployed — deployed method is MA3, run_baseline_forecast.py:748). Confirmed bugs on record if it's ever revived: fast_grid override disables seasonality, fabricated MAPE=15.0 fallbacks in 2 paths, loose 5x overshoot guard, and scripts/generate_sarima_artifact.py queries `fr.forecast_quantity` but the real column is `forecast_value` (schema.sql:418) — will crash as-is. None of this is on the deployed path.
- Del Monte sell_out taxonomy break Jan 2025: **82** distinct `category_path` values with real rows before 2025 (2023-01..2024-02), **5** from 2025-03 (BEVERAGE, CULINARY, DAIRY, FRUITS, INNOVATION), 87 distinct in all — queried on `SellOut_Fact_Real` 2026-10-15. The earlier "94 pre-2025, 57 post-2025" (2026-08) counted distinct strings across the whole table, not real rows in the window; do not quote it. No mapping exists between the two sets and there are no real rows 2024-03..2025-02. Adviser ruling needed on DEC-03 vocabulary.
- ssis_summary: no product/SKU grain anywhere in the family (95.6% of 1.95M rows are product-less outlet×day×invoice sales value); 0 real DB rows trace to it. `source_of_truth.yaml`'s `sales.unilever` entry removed 2026-09-09 (Phase 1) as a dead mapping — see reports/PROJECT_STATE_2026-09.md §8.
- Safety stock uses monthly σ for Unilever SKU grain (daily series impossible per DEC-03) — needs adviser ruling.
- LP blocked on 4 missing cost params from SSM: procurement cost, storage cost, warehouse capacity, supplier ceilings.
- `scripts/clean_dead_skus.py` (gated 2026-10-21; NOT run): on 2026-10-20 it would have disabled 837 of 1,807 Unilever SKUs including 5 Tier A, with no gate. It is now a dry run by default (prints the count, the Tier A count and a sample, writes nothing) and writes only with `--approved-by NAME --expect-disable N` where N equals the dry-run count. Nobody has approved disabling: the 837 is a measurement of a rule (no sale in 6 months), not a decision. Test: `tests/test_clean_dead_skus.py`.
- Reorder decisions (2026-10-21): a decided row (`accepted`/`dismissed`) is still the plan (`backend/lp_cycle.PLAN_STATUSES`); only open-action counts stay `pending`. A decision is made once, on a row of its principal's current cycle (409 otherwise). `decided_q_i`/`decision_reason` are capture only: no feedback into forecasts, safety stock or the LP (`tests/backend/test_recommendation_decisions.py` fails if anything outside the endpoint reads them).
- Destructive one-off scripts (2026-10-21): `scripts/delete_future_months.py` DELETED (22 module-level lines, no guard — importing it deleted `SellOut_Fact`/`Inventory_Fact` rows from 2026-07 and committed; recoverable from git history only). `scripts/map_dm_sales_to_skus.py` MOVED to `scripts/archive/` (assigned real Del Monte sell-out rows to random unseeded SKUs; already reverted by migrations 0006/0007; nothing calls it). `scripts/apply_real_recovery_to_public.py --restore` now refuses a backup whose manifest target is `public` unless `--confirm-restore-public <backup dir name>` is also given (it deletes across 10 tables incl. `schema_migrations`); `--rollback` is the targeted undo and is unchanged. Test: `tests/test_restore_public_guard.py`.
- Accuracy figures to quote: `docs/ACCURACY_AS_SERVED.md` (regenerate with `python -m scripts.accuracy_as_served --write`). Stored `mart.forecast_run` 5 and 7 predate c0b2727 and score only months with a sales row; do not quote them as served accuracy.
- Backend: all 18 routes across 11 routers are DB-backed (verified 2026-08 — no mock/hardcoded return anywhere in backend/routers/*.py). Real Pydantic schema shapes: `backend/schemas/*.py` (11 modules — the definitions themselves are the source of truth). **Corrected 2026-09-20**: this line used to point at `reports/BACKEND_HANDOFF.md`, which has never existed. `reports/API_CONTRACTS.md` is NOT a substitute — it is a Phase 0 *draft spec* of endpoints the mind map wanted, still says "Unilever-only", and pre-dates the principal param being restored 2026-09-17.
- Frontend: `frontend/src/components/Dashboard.jsx` calls `getDashboardData()` (`frontend/src/api/dashboard.js`) against live `GET /dashboard` — verified 2026-09-11 by reading the file directly (zero `MOCK_*` references, real `useEffect`/`useState` fetch). Corrected from an earlier claim that it was static mock data.
- **Frontend broken after a pull? Run `python scripts/smoke_api.py` first** (read-only, ~10s, drives all 17 frontend-facing routes × 3 principal scopes against live). All PASS = the bug is in the frontend. Diagnosis, known-good null shapes for Del Monte, and the two gotchas (stale `starlette` pin; `--schema` now required on `orchestrate_abc.py`/`orchestrate_segment.py`) are in `reports/FRONTEND_HANDOFF_2026-09-20.md`. Verified 2026-09-20: 17/17 routes 200, `npm run build` exit 0.

## Why data is missing (read before investigating gaps)
Detail, with the queried figures: [docs/DEMO_DATA.md](docs/DEMO_DATA.md). Three rules without opening it: **Unilever gaps render as zero and are never filled; Del Monte gaps are filled and labelled; `demo.*` is the only display source for generated data and `synthetic_v2` is retired.**
**Unilever: a month with no sales row = the product sold nothing. Render it as ZERO. Never fill it, never generate a value for it.**
**Del Monte: a missing month = a collection failure. Never zero, never filled by real-path code.**
- UNILEVER (provisional until SSM confirms its sales listing omits zero-sale months). Evidence, `Unilever_SKU_Demand_Fact_Real`, 2026-10-15:
  4,473 in-span gap-months across 714 of 1,807 products; gap rate 38.3% in the lowest volume quartile vs 5.7-9.5% in the other three; gaps come in
  long contiguous runs (4 of 526 multi-gap products have a regular interval); no clustering in real time (8-22% every month), so no collection outage.
  Chart endpoints return such a month as `quantity: 0` with `reason: "no_sale"`; `build_series`, the forecast runner and the LP are unchanged.
- DEL MONTE. 226 of 272 in-span gap-months fall in months where every category is absent at once (2023-07, 2023-10, 2023-12, 2025-05, -07, -10, -11):
  a collection failure, not behaviour. Also: no product-level sales exist at all (the Sales Register is invoice-level); the category taxonomy changed
  in Jan 2025 from 82 paths to 5 with no mapping; real sales stop at 2025-12. Product-level Del Monte forecasting is permanently impossible from
  these sources.
- NULL QUANTITY. A row that exists with `quantity_sold` NULL is a blank capture: excluded everywhere, never read as zero (71 rows, 63 SKUs).
  The STL endpoint returns `available: false` for a SKU with a blank after its first sale (59 of the 63): expected, not a bug.
- API. Every chart-feeding endpoint (`/forecast/{sku}` actuals, `/decomposition` series, `/category-trends` history and `skipped_months`) puts a
  `reason` on each missing or zero point and a `gap_note` on the response: `no_sale`, `blank_capture`, `outside_product_lifespan` (before the first or
  after the last sale; value null), `not_collected` (Del Monte, no category reported), `category_absent` (Del Monte category missing in a reported
  month). Codes and text: `backend/series_gaps.py`.
- NO REAL DATA BEFORE 2023-01, EITHER PRINCIPAL. SSM has no 2021-2022 data at all (confirmed with the team 2026-10-15): real Del Monte and Unilever sales both start 2023-01. The 2021-2022 range exists only as `origin: backcast` in the `demo` schema (flat at the series' own level, seeded jitter, no trend), served only when `DM_DEMO_ENABLED` is on (default off): `GET /demo/series`, `GET /demo/index`, and wired into `GET /forecast/{sku}?category=`, `GET /recommendations?principal=delmonte` and `GET /dashboard` (`demonstration` block), with `reason: no_data_recorded_before_2023`. Four origins, never mixed: `real_copy`, `interpolated`, `bridged` (reason `taxonomy_change_bridge`), `backcast`. The older `synthetic_v2` rows are retired for display (rule 2). **Del Monte demo totals are one canonical series per month (migration 0055):** the pre-2025 paths through 2025-02, the five live categories from 2025-03. The pre-2025 paths and the 2025 categories are the same business in two vocabularies, so a back-cast row generated before its series' own first observation (`in_canonical_total = false`: the five live categories before 2025-03, and sub-categories first seen after 2023-01) is excluded from every aggregate and served only on its own series. Aggregate only through `demo.dm_monthly_total` / `GET /demo/totals`, in pesos; never sum `demo.dm_category_sales` yourself (before this rule a 2023-01 total was ₱15.1M against ₱6.13M real). `GET /demo/index` tags each series' taxonomy. **Del Monte's demo yields 5 category forecasts** (BEVERAGE, CULINARY, DAIRY, FRUITS, INNOVATION — all 5 live 2025 categories): a forecast needs a real month at 2025-12; 77 pre-2025 paths stay excluded on purpose (extending them would double-count against the 5 live categories, migration 0055), and DAIRY — whose real data is thin and stops at 2025-06 — is carried forward flat (origin `forward_filled`, migration 0057, Kelvin 2026-10-16) since it is not superseded by anything. **The demo order plan (migrations 0056-0057, 2026-10-16):** Del Monte stock on hand is generated too (`demo.dm_category_stock`, origin `generated_months_of_cover`, no real anchor, a declared 45% spread independent of demand CV so a meaningful share lands below reorder point — see rule 2), and `run_lp --source demo --principal delmonte --write` plans all 5 forecastable categories (`demo.dm_category_lp`; 2 of 5 order >0), served at `order_plan.available`, `policy_comparison` and `dead_stock` on `/recommendations` and `/dashboard`. **Unilever's demo forecast is wired too** (`GET /forecast/{sku}?principal=unilever`, migration 0056/0057) and its own order plan (`run_lp --source demo --principal unilever --write`, demo forecast + REAL stock, `demo.unilever_sku_lp`) is served as `demo_unilever.order_plan` beside Unilever's real `/recommendations` items — never replacing them, since Unilever's real plan is good. Forecast accuracy (mape/mase/wape, a confidence band) is the one card that stays empty on purpose: rule 2's sanctioned exception forbids any accuracy metric in `demo.*`.
- DEL MONTE CARDS THAT ARE EMPTY ON PURPOSE: safety stock, reorder point, order plan, forecast accuracy, dead stock and policy comparison all need
  per-product forecasts that cannot exist for Del Monte. They are not unfinished work. Only the labelled demonstration path (`demo` schema,
  rule 2) shows anything there.

## Data realities
- Del Monte genuine data starts Jan 2023 (not 2021)
- Unilever per-SKU data: Jan 2023–Feb 2026
- Sales Register is invoice-level only, no SKU column — SKU-level Del Monte forecasting from that source is impossible
- bo_units has no source column in any RMR YAML — BO monitoring is value-based only
- Only confirmed SKU-level Unilever source: La Union MHTML file (needs Python `email` module magic-byte dispatch, it's disguised as .xls)

## Decision register
DEC-01 through DEC-10+ live in ARCHITECTURE.md. Check there before assuming behavior on ambiguous points (grain, taxonomy, etc).

## Full re-check standing rules (2026-09, apply to every phase of the mind-map re-check — see reports/PROJECT_STATE_2026-09.md)
1. **Never cross a phase gate in one session.** Stop at the gate and wait for review.
2. **Show the raw data before proposing a rule.** If the actual rows haven't been opened, report what was found and stop — don't propose a resolution.
3. **No invented numbers, no invented targets.** Every figure traces to a query or file you name; every threshold or gate to a measurement or a decision on record. If it doesn't exist, say so instead of picking one.
4. **When a staging defect is found, check whether it's also in the live DB.** A bad mapping usually affects rows that didn't collide too, not just the ones that surfaced as conflicts.
5. **State the expected outcome before running anything that writes** — row counts, tier counts — so a delta is visible rather than assumed correct.
6. **Cite file and line for any claim about the code.** If unverified, mark it UNVERIFIED.
7. **Scratch schema until Yuan approves a cutover**; live writes then follow hard rule 8. No DROP, no TRUNCATE, no reset of public.
8. **Every reference to the ABC cohort names its period** — "Tier A as of 2026-02," never bare "Tier A."
9. **Nothing prescriptive** (LP, safety stock, order-up-to, policy comparison) until Yuan lifts the hold.
10. **One live report per phase.** Fold finished work into `reports/PROJECT_STATE_2026-09.md`, archive the rest (`reports/archive/`). Don't create a new `.md` per sub-task.

## Efficiency rules (2026-09-16)
12. **Push work to the database, not through Python.** Bulk copies, diffs, and set comparisons run as SQL (`INSERT INTO ... SELECT`, `CREATE TABLE AS`, `EXCEPT`, `FULL OUTER JOIN`) against the server. Never pull rows into pandas to move or compare them.
13. **Before running anything expected to take over a minute, say so and state the faster alternative.** If there isn't one, say that.
14. **When a subtask starts needing its own bug fixes, stop and report.** That's a signal the approach is wrong, not that it needs more code.
15. **Report findings in tables, not narrative.** One row per item, with counts. Prose only for the decision that needs making.
16. **Drop the scratch schema after a verified public apply.** Once counts match and the write lands in `public`, the scratch copy is done — `DROP SCHEMA <name> CASCADE` it rather than leaving it to accumulate storage (2026-09-18: five stale scratch schemas hit 548MB before cleanup).

## Working style
- Plain language; spell out jargon and acronyms. Compact responses, no long prose recaps.
- Ask only if something fails or a decision isn't covered; otherwise follow the pre-approved thresholds in the prompt.
- Tests: run only the tests for code you touched; the full suite runs in a final QA session.
- After any code change: `git diff <file>` to verify it's a structural fix, not a string-prefix patch.
- Token-efficient: targeted edits over full-file rewrites.
