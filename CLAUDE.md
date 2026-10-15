# SSM Decision Support Dashboard (DSD) — Capstone Group 7

## Project
3ISA/4ISA Group 7, IS-BA Track, UST CICS. SSM Decision Support Dashboard for San San Marketing (SSM), FMCG distributor, Urdaneta, Pangasinan. Two principals only: Unilever Philippines, Del Monte Philippines. Magnolia is OUT OF SCOPE — ignore Magnolia refs in old files. Never call it "DSS" — it's DSD.

Problem: SSM's blanket 3-week safety stock rule causes trapped capital + spoilage. DSD gives per-SKU data-driven replenishment recommendations.

Pipeline: ETL → ABC/Pareto classification → forecasting (deployed: MA3, 3-month moving average — see run_baseline_forecast.py:748; SARIMA was bake-off'd against 16 other models and retired, never deployed) → safety stock/ROP → multi-objective LP optimization (PuLP, w1=0.45, w2=0.35, w3=0.20) → dashboard.

Tier A basis (DEC-38, PENDING TA CONFIRMATION, 2026-10-05): Unilever Tier A = Class A on the last 12 months + products first sold within 12 months that are Class A on the last 3 (ABC method `t12m_new`; 189 products as of 2026-02). The setting is `analytics.params.TIER_A_BASIS`; read it through `abc_method()` / `abc_method_sql()`, never a literal `method = 'single'`. Del Monte stays on `single`.

## Repo
https://github.com/4ISA-Capstone-Group-7/SSM-DSD — remote `group7`, base branch `kelvin-etl` (NOT master — master is behind, don't trust it as source of truth). Old repo KYG07/Capstone-Project is dead, never push there.
Each session works in its own worktree on a branch named `kelvin/<name>`.
Migrations: 0046 (planning mart `mart.planning_mart`, part of DEC-36, 2026-10-05) is the latest on public, after 0044 (Tier A basis `t12m_new`, DEC-38, 2026-10-05), 0043 (mart stock-limited rule, DEC-36), 0042 (in-transit stock + review flag, DEC-33/34) and 0041 (data marts, schema `mart`, DEC-36), all 2026-10-04. 0045 (`Product_Dimension.unit_cost` + `lead_time_days`) and 0047 (`planning_stale` knows the Tier A basis) are now used too (files on kelvin-etl; whether they are applied to public is not recorded here). 0048-0051 are applied (app schema, planning-mart tier anchor, inventory index + month marts, stability_group pattern). 0052-0053 (schema `demo`: the labelled demonstration pipeline and its 2021-2022 back-cast, rule 2) are applied 2026-10-15. The next free number is 0054.

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
   **Sanctioned demonstration path (approved by Kelvin, 2026-10-15; Sir Catubag informed — recorded here so a later session does not revert it):** a labelled demonstration pipeline (Del Monte categories, Unilever SKUs for the 2021-2022 back-cast only) may write generated data, but only to the separate `demo` schema, every row `is_demo=true` and `fill_source='synthetic_dm_pipeline_demo'`, with no accuracy metrics (no mape/mase/wape, no confidence bands; a schema test enforces it), in its own `demo.run`, never in a real cohort, and exposed only behind an explicit API demonstration flag (`demonstration: true`, `data_source: "synthetic_demonstration"`). Generated months sit between two real months of the same series (interpolated, no extrapolation). Unilever's in-span gaps are never filled: they are real zero-sale months (see "Why data is missing"). Nothing generated reaches a `_Real` view, a real forecast, accuracy or the LP, and results from it are never presented as real.
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
- Backend: all 18 routes across 11 routers are DB-backed (verified 2026-08 — no mock/hardcoded return anywhere in backend/routers/*.py). Real Pydantic schema shapes: `backend/schemas/*.py` (11 modules — the definitions themselves are the source of truth). **Corrected 2026-09-20**: this line used to point at `reports/BACKEND_HANDOFF.md`, which has never existed. `reports/API_CONTRACTS.md` is NOT a substitute — it is a Phase 0 *draft spec* of endpoints the mind map wanted, still says "Unilever-only", and pre-dates the principal param being restored 2026-09-17.
- Frontend: `frontend/src/components/Dashboard.jsx` calls `getDashboardData()` (`frontend/src/api/dashboard.js`) against live `GET /dashboard` — verified 2026-09-11 by reading the file directly (zero `MOCK_*` references, real `useEffect`/`useState` fetch). Corrected from an earlier claim that it was static mock data.
- **Frontend broken after a pull? Run `python scripts/smoke_api.py` first** (read-only, ~10s, drives all 17 frontend-facing routes × 3 principal scopes against live). All PASS = the bug is in the frontend. Diagnosis, known-good null shapes for Del Monte, and the two gotchas (stale `starlette` pin; `--schema` now required on `orchestrate_abc.py`/`orchestrate_segment.py`) are in `reports/FRONTEND_HANDOFF_2026-09-20.md`. Verified 2026-09-20: 17/17 routes 200, `npm run build` exit 0.

## Why data is missing (read before investigating gaps)
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
- NO REAL DATA BEFORE 2023-01, EITHER PRINCIPAL. SSM has no 2021-2022 data at all (confirmed with the team 2026-10-15): real Del Monte and Unilever sales both start 2023-01. The 2021-2022 range exists only as `origin: backcast` in the `demo` schema (flat at the series' own level, seeded jitter, no trend), served by `GET /demo/series` only when `DM_DEMO_ENABLED` is on (default off) with `reason: no_data_recorded_before_2023`. Keep four origins distinct everywhere: `real_copy`, `interpolated` (between two real months), `bridged` (across the 2024-03..2025-02 taxonomy change; not built, the hole is left unfilled), `backcast`. Older `synthetic_v2` placeholder rows (is_demo=true in the base fact tables, shown by `X-Data-Mode: preview`) cover the same 2021-2022 months by a different method: two synthetic histories, never mix them in one chart.
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
