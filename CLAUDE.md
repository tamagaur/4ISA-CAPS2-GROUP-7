## Standing rules

Read STATE.md first. Update it before finishing.

REPO (changed 2026-11-05, Kelvin). The team's repo, and the basis for the final deploys, is
https://github.com/tamagaur/4ISA-CAPS2-GROUP-7 (remote `team`). Today it holds one branch, `thea-dashboardedits`
(Audrey's frontend; unprotected, no rulesets, read with `gh api` 2026-11-05; the repo is PUBLIC). My branch there is
`kelvin-be`: made from Main-BE's tip 4f12e24 with `thea-dashboardedits` (7b91936) merged in by `git merge`, never by copying
files. `4ISA-Capstone-Group-7/SSM_DSD` (remote `newrepo`, branches Main-BE, Main-FE, Main-Final) stays as the history; nothing
new is pushed to it unless the prompt says so. Never touch origin or group7. Never push unless the prompt says so, and read a
branch's protection before pushing to it. No force, no history rewrite. Stage files by name. At most two sessions at once, and
never two that write. A session that finds a dirty working tree stops and reports rather than working around it.

DATABASE. Writes to public only through numbered migrations plus the runner.
Read-only access via transaction-scoped READ ONLY; never a session-level SET on
the :6543 pooler. Back up before anything destructive.

SCOPE FENCE. Only what the prompt names is in scope. Never touch the forecast,
the LP objective, migrations or frontend files unless told to. Log a side
finding in one line; do not investigate it.

NUMERIC GATE. Plan invariant: 115 rows, 330,212 pieces, nothing decided (lp_run 10, live since 2026-11-13: scripts/apply_calendar_grain.py, the calendar factor computed per product with the December rule; lp_run 9 was 110 / 378,700, lp_run 8 110 / 381,484, lp_run 7 110 / 419,344, lp_run 6 109 / 435,988; SPIKE-COPY and GATE-COPY are rehearsal plans of unapplied branches, never live). If a
change moves either, STOP and report. Pinned manuscript figures are verified,
never recomputed into new values.

BLOCKED, DON'T INVENT. A figure must trace to a query, a file or a commit.
Otherwise name it unresolved and say what would settle it. Skipped is not
passed; a test that did not run is not coverage.

ANTI-LOOP. One verification pass, at the end. Separate what passed, what is
still tuning, and what is blocked on someone else. No second round of checks.

REPORT. End with these, each under five lines, "none" when there is none:
  ## Figures that moved
  ## Decisions needed
  ## Contradictions found

# SSM Decision Support Dashboard (DSD) — Capstone Group 7

**Read `STATE.md` first, and update it in the same commit as anything that changes it** (the plan, Main-BE's commit, the next migration number, the pinned figures, what is blocked). It holds current state only; this file holds the rules. Its `plan:` line is checked against the live database by `scripts/check.sh`.

## Project
3ISA/4ISA Group 7, IS-BA Track, UST CICS. SSM Decision Support Dashboard for San San Marketing (SSM), FMCG distributor, Urdaneta, Pangasinan. Two principals only: Unilever Philippines, Del Monte Philippines. Magnolia is OUT OF SCOPE — ignore Magnolia refs in old files. Never call it "DSS" — it's DSD.

Problem: SSM's blanket 3-week safety stock rule causes trapped capital + spoilage. DSD gives per-SKU data-driven replenishment recommendations.

Pipeline: ETL → ABC/Pareto classification → forecasting (deployed: `analytics/forecasting/router.py` serves short history MA3, the 3-month moving average, medium TSB, long the XGBoost+MA3 average, MA3 as fallback, DEC-25/26; SARIMA was bake-off'd against 16 other models and retired, never deployed) → safety stock/ROP → multi-objective LP optimization (PuLP, w1=0.45, w2=0.35, w3=0.20) → dashboard.

Tier A basis (DEC-38; adopted by the team as DEC-42, 2026-11-02; not confirmed by the TA): Unilever Tier A = Class A on the last 12 months + products first sold within 12 months that are Class A on the last 3 (ABC method `t12m_new`; 189 products as of 2026-02). The setting is `analytics.params.TIER_A_BASIS`; read it through `abc_method()` / `abc_method_sql()`, never a literal `method = 'single'`. Del Monte stays on `single`.

## Repo
Canonical now (2026-11-05): https://github.com/tamagaur/4ISA-CAPS2-GROUP-7, remote `team`, branch `kelvin-be` (mine) beside Audrey's
`thea-dashboardedits`; the group chooses how these reach a deploy. It is a PUBLIC repo whose history is Main-BE's up to 136edf2,
so the per-SKU cost files of hard rule 9 (G14) are already readable there: that is a handover decision (G13), not something a push
changes. Not changed by this: nothing below about migrations, tests or the database.
Earlier (still the history): https://github.com/4ISA-Capstone-Group-7/SSM_DSD (UNDERSCORE), remote `newrepo`. Backend went to `Main-BE`, frontend to `Main-FE`; `Main-Final` is the integration branch and took merges by pull request only (a team convention, not GitHub-enforced: branch protection needs GitHub Pro or a public repo, and that repo is private). Local work is on a `kelvin/<name>` branch (`kelvin-be` is the one exception, named by Kelvin on 2026-11-05); push with an explicit refspec. Local `kelvin-etl` still has `newrepo/Main-BE` as its upstream but is stale (174 commits behind on 2026-11-04): do not push from it. Retired (corrected 2026-10-19): `group7` = 4ISA-Capstone-Group-7/SSM-DSD (HYPHEN), whose `kelvin-etl` was the old base branch, and KYG07/Capstone-Project.
Migrations: the latest applied number and the next free number are in STATE.md. An applied migration is never edited or renumbered; a later migration retires it (hard rule 8: a column can't be un-applied by deleting its migration file). `scripts/run_canonical_load._assert_no_new_number_collision` catches a number used twice. Main-Final's backend still reads a column that has since been retired, so it cannot run against the current schema until Main-BE is merged into it; a server already running it must be restarted after the merge.

**Any migration that adds or drops a column on `app.users` must re-create `public.users` (the compatibility view) with app.users' COMPLETE current column list, not just the column it's touching** — CREATE OR REPLACE VIEW silently drops any column left out, so two migrations each listing only their own column means whichever applies second erases the other's from the view (this is exactly how two avatar-column migrations collided). `tests/backend/test_migrations.py` statically checks every `public.users` view against every `ALTER TABLE app.users ADD/DROP COLUMN` up to that point in the migration order and fails the build if they disagree.

## Stack
Python/pandas ETL, FastAPI backend, React + Vite frontend (plain `.jsx`, React Router; no Next.js, no Tailwind), Supabase (Postgres), Vercel (frontend host), Render (backend host).

## Team
Yuan — ETL, DB schema, Supabase, orchestration, repo owner, all pipeline decisions, demo data
Maika — frontend, auth, deployment, backend
Audrey — backend endpoints, backend & frontend, LP
Thea — models, manuscript, SSM liaison, frontend design
Kelvin — frontend integration (kelvin-etl branch)
Advisers: Sir Catubag (technical)

## Hard rules
Rules 5 and 7 were absorbed into the standing block; the numbering keeps its gaps so existing references stay valid.
1. **Data interface rule**: model code reads the `_Real` views (analytics/db/schema.sql:871-887 — `Sales_Fact_Real`, `Inventory_Fact_Real`, `Unilever_SKU_Demand_Fact_Real`, etc.), never the base fact tables directly and never raw files. These views structurally exclude `is_demo=true` rows (`WHERE is_demo = false`), so a real-vs-synthetic mixup is a query-target mistake, not a filter a caller can forget. One copy differs on purpose: the local practice copy's demand view (rule 2, the practice month). (`get_demand_series()` does not exist anywhere in this codebase — corrected 2026-08.)
2. **Anti-fabrication rule (sanctioned exception)**: no invented numbers in manuscript/defense/reported results. Synthetic data (is_demo=true) IS approved for frontend validation only — don't relitigate, adviser already approved it. **Generated/filled data never feeds KPIs, forecasts, ABC or the LP on the real path; charts may show it labelled as estimated.** Generated rows exist in three arrangements, and each is safe only while its condition holds:
   | Arrangement | Where the rows are | What keeps them out of results | The condition it relies on |
   |---|---|---|---|
   | 1. `demo` schema (Path 1) | Schema `demo` on the live database | A separate schema | A generator writes only there; a reader serves it only with `DM_DEMO_ENABLED` on and the caller asking (`X-Data-Mode: preview`, or a `/demo/*` route) |
   | 2. Labelled rows in live base tables | `public` fact and fill tables, beside real rows | A filter, not a schema: the `_Real` views and `data_kind = 'real'` | Every reader goes through those. A new query on a base table has no protection of its own |
   | 3. Practice copy (Path 2) | `ssm_practice` on `127.0.0.1:55432`, never on live | A separate local database; the real pipeline does run on it | The scripts refuse any other server, the forecast's permission is derived from the connection, the API answers 409 from it |
   No arrangement outside these three may write generated rows; the read-only and test uses are listed at the end of this rule.
   **Arrangement 1. Path 1, sanctioned demonstration path (approved by Kelvin, 2026-10-15; Sir Catubag informed — recorded here so a later session does not revert it):** a labelled demonstration pipeline (Del Monte categories, Unilever SKUs for the 2021-2022 back-cast only) may write generated data, but only to the separate `demo` schema, every row `is_demo=true` and `fill_source='synthetic_dm_pipeline_demo'`, with no accuracy metrics (no mape/mase/wape, no confidence bands; a schema test enforces it), in its own `demo.run`, never in a real cohort, and exposed only behind an explicit API demonstration flag (`demonstration: true`, `data_source: "synthetic_demonstration"`). Generated months carry one of four origins, kept strictly apart in data, API and reports: `real_copy`; `interpolated` (between two real months of the same series); `bridged` (Del Monte only: each pre-2025 path carried from its last real month through 2025-02 across the taxonomy change; that is extrapolation, and rule 14 is suspended for that window only, by Kelvin's decision of 2026-10-15); `backcast` (2021-01 onward, no real data on either side; flat at the series' own level with seeded jitter, no trend). **Anchor override, Del Monte only:** Unilever's back-cast requires the series' first real month to be 2023-01 (a SKU first sold later is a genuine launch; projecting it back would invent that it existed); Del Monte's does not, because its five 2025 categories (BEVERAGE, CULINARY, DAIRY, FRUITS, INNOVATION) and its sub-categories first seen after 2023-01 are a relabelling of a business that existed in 2021, not new products. Those rows stay `origin='backcast'` and carry `anchor_override` (API: `generated_before_first_observation: true`). Unilever's in-span gaps are never filled: they are real zero-sale months (see "Why data is missing"). `demo.*` is the SINGLE display source for anything generated, both principals: the older `synthetic_v2` rows (arrangement 2 has the counts) are retired for display, and so are the filled sales rows in `mart.sales_mart` (3,130 `synthetic_category_split`, 4 `synthetic_v2_gap`): no reader serves a non-real sales row any more, nothing is deleted, and `X-Data-Mode: preview` reads `demo.*` only when the flag is on. On this path nothing generated reaches a `_Real` view, a real forecast, accuracy or the LP, and results from it are never presented as real.
   **Path 1, extended by Kelvin, 2026-10-16 (the demo stock/forecast/order-plan migration) to stock and the order plan:** `demo.dm_category_stock` adds a
   FIFTH kind of generated row, Del Monte stock on hand, with its own origin `generated_months_of_cover` — unlike
   the four sales origins above it has NO real anchor anywhere (`Inventory_Fact_Real` is SKU grain only for Del
   Monte and carries no `category_path`), so it is never `real_copy`: a seeded draw centred on SSM's "about 3
   weeks of sales in stock" policy (`analytics.params.POLICY_COVER_WEEKS`), jittered by the category's own CV,
   against that category's own demonstration demand (`analytics/demo/stock.py`). `demo.unilever_sku_forecast`
   adds a one-step MA3 per Unilever SKU over real_copy months only (`scripts/build_unilever_demo.py`) — served since
   then by `GET /forecast/{sku}?principal=unilever` when the demo switch is on (`backend/demo_data.py`), beside Unilever's real `Forecast_Result`, which is unaffected; it matches the
   real forecast exactly where the real deployed model for that SKU is also MA3 (36 of 179 comparable SKUs,
   median difference 0.0), and differs where the real model is TSB or the XGBoost+MA3 average instead (a
   model-routing difference, not a demo-generation bug). `demo.dm_category_lp` adds the Del Monte demonstration
   order plan (`analytics/demo/prescriptive.py`): the real safety-stock/target-stock formulas over the
   demonstration's own forecast AND stock — two generated layers, stated in every row's `demonstration_note` —
   with NO allocation or warehouse ceiling (neither exists for Del Monte; reusing Unilever's real
   `warehouse_capacity` would conflate two different quantity units, DEC-31). `run_lp --source demo` is now
   accepted for `--principal delmonte` and, since the later demo migrations, `--principal unilever` (demo forecast + real stock, `demo.unilever_sku_lp`); still refused for `both`; `/recommendations` and
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
   **Arrangement 2, labelled rows in live base tables (written into this rule 2026-11-03; the rows predate it).** This is the one a reader can break by accident, because no schema separates the rows. `is_demo = true` rows, queried 2026-11-03: `unilever_sku_demand_fact` 12,243 of 37,149 (`fill_source` synthetic_v2); `sales_fact` 44,797 of 62,223 (synthetic_v2, synthetic_v2_gap); `inventory_fact` 28,170 of 60,993 (those two and synthetic_branch_adjacent); `sellout_fact` 4,639 of 6,006; `salesreturn_fact` 3,957 of 5,561 (also synthetic_rate_transfer); `purchase_fact` 2,289 of 2,788. Two tables hold only such rows: `sku_demand_fill` 3,130 (synthetic_category_split) and `derived_receipt_fact` 28,245 (derived_stock_balance, computed from real inputs).
   - **They are still written.** `scripts/fill_missing.py` runs after every `run_canonical_load --slice` / `--all-slices` load unless `--no-fill` is passed, so a real load on live adds labelled rows. `scripts/build_synthetic_v2_clean_pool.py --write` and `scripts/apply_synth_v2_to_public.py` wrote the synthetic family. Nothing deletes them.
   - **Models and the LP: the `_Real` views** (six, each `WHERE is_demo = false`; rule 1). The forecast has a second guard, `router.assert_real_rows`; the LP and ABC have only the views.
   - **Marts: the `data_kind` label.** `mart.refresh` reads the base tables and carries each row as `real`, `filled` or `generated`. `backend/marts._kind_filter` is the one WHERE that every mart query goes through: real rows only, plus the `demo` back-cast in preview. `COUNT_FILLED_AND_GENERATED` in that file must stay off. Filled flow rows (never returns) may appear on a chart as estimates; filled and generated sales rows are retired for display.
   - **Direct readers.** `GET /inventory/receipt-signals` reads `derived_receipt_fact`, whose rows are all derived; it counts them and does not present them as observed.
   - **Views.** `public.product_demand_view` and `public.bo_monitoring_view` filter `is_demo = false` on both base tables since migration 0074 (applied to live 2026-11-04; `tests/test_views_real_rows_only.py`). A new view on a base table has no protection of its own.
   **Arrangement 3. Path 2, the practice month (decided by Kelvin, 2026-11-02; closes KNOWN_ISSUES M5).** The real batch (`scripts/run_month.py`: ABC, forecast, safety stock and target, LP, marts, review, close) runs on generated March 2026 sales, on one database: `ssm_practice` on `127.0.0.1:55432`. Its conditions, all of them enforced in code:
   - **Labelled rows, one tag.** `scripts/local_pipeline_qa.py synth` writes them `is_demo = true`, `_src_file = 'qa_synthetic_march'`, and refuses any other database. It first deletes the copy's retired `is_demo` backfill rows for that month.
   - **One view changed, in that copy only.** `scripts/local_pg.py practice` redefines `unilever_sku_demand_fact_real` there to admit that tag and no other `is_demo` row; `is_demo` stays a column of the view, so the label stays visible. It connects only to `127.0.0.1:55432`. Every other database keeps the view that excludes them.
   - **Every row written there says so.** `scripts/local_pg.py practice` also gives every table in that copy a `practice_run` column, NULL on the rows it started with, and a trigger that stamps every row inserted or updated afterwards. Only in that copy; never a migration.
   - **The marts count the generated month, in that copy only.** `scripts/local_pg.py practice` redefines `mart.data_kind` there so rows that are `is_demo` with no `fill_source` (what `synth` writes; 0 rows in `ssm_local`) read `real`. `source_tag` stays `demo_untagged` and `is_demo` stays on the fact row. Never a migration, and `backend/marts.py` holds no practice code: its SQL is the same on every database.
   - **The API answers from it only when the connection confirms it, and labels every answer (Kelvin, 2026-11-04).** `backend/practice_copy.confirmed()` uses the forecast's own test (`practice_switch.is_practice_database`), so `scripts/local_app.py` serves the Dashboard and Reorder pages from `ssm_practice` with an `X-Practice-Copy` header on every answer and a banner on every page. A URL that names the copy but is not confirmed still answers 409 `practice_copy_not_served` on everything but `/batch/*` and `/health`. A process whose URL names any other database never asks and never connects for this. **Inside a payload too (2026-11-04):** `backend/practice_copy.PracticeBodyLabel`, mounted only on that URL, rewrites every 2xx JSON answer: a `practice_copy` block (`not_a_result`, `generated_months`), `generated_sales_month` and `rests_on_generated_sales` on dated objects, and `data_kind`, `estimated`, `estimated_rows`, `synthetic_months` corrected. The queries beneath still read `real` there; the marts are unchanged.
   - **`python -m scripts.practice_artefacts` is the check.** It runs the month and fails on any file, row or route that does not carry its own marker (a route: the `X-Practice-Copy` header and the body label on a 200, no object dated the generated month reading as real, and a 422 fails because the route was not read). Run it after adding anything that a practice run writes.
   - **The forecast exception is derived from the connection.** `analytics/forecasting/practice_switch.py` is the only source of the forecast's permission. It reads no environment variable, flag, setting or file. The client (libpq's host, port, database) and the server (`inet_server_addr`, `inet_server_port`, `current_database`) must both say `127.0.0.1`, `55432`, `ssm_practice`, so a connection string or a tunnel cannot turn it on. Every run it permits logs the database and the row count. On any other database the guard (`router.assert_real_rows`) refuses labelled rows as before.
   - **The LP and the mart refresh have no such guard, so they have no exception.** The LP reads the demand view. `mart.refresh` reads the base table through the copy's own `mart.data_kind` above.
   - **No accuracy figure computed on generated rows is presented.** `scripts/cycle_feedback.py` withholds the forecast error (and the figures that could rebuild it, and its per-product file) when any `is_demo` row is in the sales the score reads, or in the history up to that month. A permitted forecast run prefixes every printed line with `[computed on generated sales]`. Those stored and file values still exist, in that copy and in the git-ignored `local/` folder: `Forecast_Result.mase`/`mape` there are computed partly on generated sales, each row carries `model_params.run.generated_sales_in_history`, and the LP's MASE < 1 entry test reads them. They are not quoted. The Data Management panel shows the withheld reason and the labelled log; the pages show the labelled plan and sales, and `backend/practice_copy.PracticeBodyLabel` withholds every accuracy figure dated on or after a generated month, in the answer itself, with the reason (2026-11-04). A month loaded through the panel's upload slot is withheld too, because nothing there can tell a real file from a made-up one. A range ending before such a month keeps its real figures.
   - **What it proves.** That the whole month runs on labelled generated data on a local copy. It does not prove a real new monthly file runs, because none has ever existed. Its plan is never a result.
   **Other uses of generated rows, none a path to a served figure on the real path.** `allow_placeholder=True` is passed literally only by `scripts/preview_router_synth.py` and `reports/simulation/synthetic_2026-10/run_simulation.py`: read-only what-ifs that write files, nothing to the database, and are never served. `scripts/rollover_scratch_test.py` is the one case of generated rows stored `is_demo = false`: tagged `rollover_test_synthetic`, in the scratch schema `ssm_rollover_test` only, with its isolation checks, for that test.
   **Preview files.** `scripts/build_preview_outputs.py` writes `reports/preview/app_*`; `backend/data_mode.preview_outputs` serves them to a preview request only when `app_meta.json` records `placeholder_source: demo`, so they belong to arrangement 1. Files built on `synthetic_v2` are refused.
3. **No fabricated metrics as fallback, ever.** If a real computation isn't possible (e.g. <12mo history, model exception), the correct value is a flagged "insufficient data" status — never a hardcoded number pretending to be measured.
4. **Hard gates**: M0, M2, M3 are human-review checkpoints. Don't cross a gate in one session — stop and report at gate boundaries.
6. **Verify before asserting.** Never state file counts, row counts, or test results without actually running something. Never describe planned/intended behavior as current state.
8. **The migration runner** is `scripts/run_canonical_load.py --schema public --target-public --schema-only` (the write rules are under DATABASE in Standing rules; a column can't be un-applied by deleting its migration file).
9. **Per-product sales, prices and costs stay out of git, and the repository does not fully meet this.** Read all three parts.
   - **The rule.** New per-product sales, prices or costs go in the git-ignored `local/` folder, never in a commit.
   - **The exception (agreed 2026-10-23).** Per-product figures the manuscript publishes may be committed in the file they trace to, and nothing it does not publish goes with them. `docs/MANUSCRIPT_WORKED_CALCULATIONS.md` holds two products on this basis, with the purchase price left out.
   - **What the repository holds anyway (`docs/DATA_GOVERNANCE.md` section 7, gap G14, open).** Per-SKU purchase costs are in history on all three remote branches, Main-BE, Main-Final and Main-FE: 8 CSV blobs, 73 rows each, with `cost_per_piece`. Commit 97e564d removed them from the current files of Main-BE and Main-FE, and Main-Final's current files still hold all 8. They cannot be removed without a history rewrite, which the standing rules forbid (Kelvin, 2026-11-03: history stays). The current tree also holds price values in `profiling/sheet_profiles` (375 values in 67 files, not tied to a product) and 26 CSV files with a product identifier beside a sales, stock, price or quantity column, among them `docs/published_snapshot_2026-10-24/` (header scan of 2026-11-03, not an audit). So this rule governs what is added. It does not describe what is there: never say the repository holds no per-product or price data. What happens to the repository is a handover decision (G13).

## Known open items (2026-09)
- Retired: scripts/run_sarima.py (dead code, not deployed; the deployed path is `analytics/forecasting/router.py`). Its docstring records the `fast_grid` override, the MAPE=15.0 fallbacks and the 5x overshoot guard as fixed in 2026-08, and scripts/generate_sarima_artifact.py now reads `forecast_value`. Corrected 2026-11-04 by reading both files; neither was run.
- Del Monte sell_out taxonomy break Jan 2025: **82** distinct `category_path` values with real rows before 2025 (2023-01..2024-02), **5** from 2025-03 (BEVERAGE, CULINARY, DAIRY, FRUITS, INNOVATION), 87 distinct in all — queried on `SellOut_Fact_Real` 2026-10-15. The earlier "94 pre-2025, 57 post-2025" (2026-08) counted distinct strings across the whole table, not real rows in the window; do not quote it. No mapping exists between the two sets and there are no real rows 2024-03..2025-02. Kept separate by team decision DEC-43 (2026-11-02); no adviser ruling.
- ssis_summary: no product/SKU grain anywhere in the family (95.6% of 1.95M rows are product-less outlet×day×invoice sales value); 0 real DB rows trace to it. `source_of_truth.yaml`'s `sales.unilever` entry removed 2026-09-09 (Phase 1) as a dead mapping — see reports/PROJECT_STATE_2026-09.md §8.
- **Calendar factor is LIVE, PER PRODUCT since 2026-11-13:** all 175 `ok` `Forecast_Result` rows for March 2026 carry each product's own `calendar_factor` (0.7103 to 1.2608; `analytics/forecasting/calendar.py` ProductCalendar, `analytics.params.CALENDAR_GRAIN = "product"`, December rule on). From 2026-10-19 to 2026-11-13 it was the company-total factor, 1.0762 on every row, which a few large products pointed against most products in 4 of 35 month-years (STATE.md, CALENDAR GRAIN). Adopted by the team as DEC-41 (2026-11-02); Sir Catubag has not signed it off. The runner's default stays OFF (`--calendar-factor` is opt-in) but every live write used it. The LP sensitivity of 2026-10-20 (424,127 with, 354,975 without, on the 107-row plan of its date) measured the company factor and was not repeated at product grain; `reports/diagnostics/calc_audit_2026-10-20/` is on branch `kelvin/calc-audit` and `newrepo/kelvin-backup-DO-NOT-MERGE`, not on Main-BE.
- Safety stock uses monthly σ for Unilever SKU grain (daily series impossible per DEC-03) — needs adviser ruling.
- LP cost inputs: procurement cost, storage cost, warehouse capacity and supplier ceilings are stated assumptions adopted by the team (DEC-44, 2026-11-02). SSM has not confirmed them.
- `scripts/clean_dead_skus.py` (gated 2026-10-21; NOT run): on 2026-10-20 it would have disabled 837 of 1,807 Unilever SKUs including 5 Tier A, with no gate. It is now a dry run by default (prints the count, the Tier A count and a sample, writes nothing) and writes only with `--approved-by NAME --expect-disable N` where N equals the dry-run count. Decided DEC-45 (2026-11-02): it stays gated and is not run before the defence. Nobody has approved disabling: the 837 is a measurement of a rule (no sale in 6 months), not a decision. Test: `tests/test_clean_dead_skus.py`.
- Reorder decisions (2026-10-21): a decided row (`accepted`/`dismissed`) is still the plan (`backend/lp_cycle.PLAN_STATUSES`); only open-action counts stay `pending`. A decision is made once, on a row of its principal's current cycle (409 otherwise). Reasons enter no computation. A decision changes neither the forecast nor the safety stock. An accepted order becomes an expected receipt (`backend/expected_receipts.py`, from `decided_q_i`, else `q_i`) and so part of the next cycle's opening stock (`stock_opening_v`), which the optimisation reads. Live holds no such receipt today (`expected_receipt` has 0 rows, checked 2026-11-02). `tests/backend/test_recommendation_decisions.py` fails if the forecast or the safety-stock calculation reads a decision.
- Destructive one-off scripts (2026-10-21): `scripts/delete_future_months.py` DELETED (22 module-level lines, no guard — importing it deleted `SellOut_Fact`/`Inventory_Fact` rows from 2026-07 and committed; recoverable from git history only). `scripts/map_dm_sales_to_skus.py` MOVED to `scripts/archive/` (assigned real Del Monte sell-out rows to random unseeded SKUs; already reverted by later migrations (see `scripts/archive/`); nothing calls it). `scripts/apply_real_recovery_to_public.py --restore` now refuses a backup whose manifest target is `public` unless `--confirm-restore-public <backup dir name>` is also given (it deletes across 10 tables incl. `schema_migrations`); `--rollback` is the targeted undo and is unchanged. Test: `tests/test_restore_public_guard.py`.
- Accuracy figures to quote: `docs/ACCURACY_AS_SERVED.md` (regenerate with `python -m scripts.accuracy_as_served --write`). Stored `mart.forecast_run` 5 and 7 predate c0b2727 and score only months with a sales row; do not quote them as served accuracy.
- Backend: the route count is pinned in `docs/CHAPTER4_CODE_FIGURES.json` (84 on 2026-11-04, in 24 router modules). The check that no route returned a mock or hardcoded value was made in 2026-08 on the 18 routes of that date and has not been repeated. Real Pydantic schema shapes: `backend/schemas/*.py` (10 modules plus `__init__.py`; the definitions themselves are the source of truth). `reports/BACKEND_HANDOFF.md` is not on Main-BE: its only copy is on the local branch `kelvin-etl-backup` (409814b, 2026-08), which STATE.md judges obsolete, so do not use it as the reference. `reports/API_CONTRACTS.md` is NOT a substitute — it is a Phase 0 *draft spec* of endpoints the mind map wanted, still says "Unilever-only", and pre-dates the principal param being restored 2026-09-17.
- Frontend: `frontend/src/components/Dashboard.jsx` calls `getDashboardData()` (`frontend/src/api/dashboard.js`) against live `GET /dashboard` — verified 2026-09-11 by reading the file directly (zero `MOCK_*` references, real `useEffect`/`useState` fetch). Corrected from an earlier claim that it was static mock data.
- **Frontend broken after a pull? Run `python scripts/smoke_api.py` first** (read-only, ~10s, issues 14 GETs over 8 routes against live, three of them with each principal scope; not every route the frontend uses). All PASS = the bug is in the frontend. Diagnosis, known-good null shapes for Del Monte, and the two gotchas (stale `starlette` pin; `--schema` now required on `orchestrate_abc.py`/`orchestrate_segment.py`) are in `reports/FRONTEND_HANDOFF_2026-09-20.md`. The last recorded all-pass in that report is 2026-09-20, on the route list of that date.

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
- NO REAL DATA BEFORE 2023-01, EITHER PRINCIPAL. SSM has no 2021-2022 data at all (confirmed with the team 2026-10-15): real Del Monte and Unilever sales both start 2023-01. The 2021-2022 range exists only as `origin: backcast` in the `demo` schema (flat at the series' own level, seeded jitter, no trend), served only when `DM_DEMO_ENABLED` is on (default off): `GET /demo/series`, `GET /demo/index`, and wired into `GET /forecast/{sku}?category=`, `GET /recommendations?principal=delmonte` and `GET /dashboard` (`demonstration` block), with `reason: no_data_recorded_before_2023`. Four origins, never mixed: `real_copy`, `interpolated`, `bridged` (reason `taxonomy_change_bridge`), `backcast`. The older `synthetic_v2` rows are retired for display (rule 2). **Del Monte demo totals are one canonical series per month (see STATE.md for the migration):** the pre-2025 paths through 2025-02, the five live categories from 2025-03. The pre-2025 paths and the 2025 categories are the same business in two vocabularies, so a back-cast row generated before its series' own first observation (`in_canonical_total = false`: the five live categories before 2025-03, and sub-categories first seen after 2023-01) is excluded from every aggregate and served only on its own series. Aggregate only through `demo.dm_monthly_total` / `GET /demo/totals`, in pesos; never sum `demo.dm_category_sales` yourself (before this rule a 2023-01 total was ₱15.1M against ₱6.13M real). `GET /demo/index` tags each series' taxonomy. **Del Monte's demo yields 5 category forecasts** (BEVERAGE, CULINARY, DAIRY, FRUITS, INNOVATION — all 5 live 2025 categories): a forecast needs a real month at 2025-12; 77 pre-2025 paths stay excluded on purpose (extending them would double-count against the 5 live categories, the same migration), and DAIRY — whose real data is thin and stops at 2025-06 — is carried forward flat (origin `forward_filled`, the forward-fill migration, Kelvin 2026-10-16) since it is not superseded by anything. **The demo order plan (2026-10-16):** Del Monte stock on hand is generated too (`demo.dm_category_stock`, origin `generated_months_of_cover`, no real anchor, a declared 45% spread independent of demand CV so a meaningful share lands below reorder point — see rule 2), and `run_lp --source demo --principal delmonte --write` plans all 5 forecastable categories (`demo.dm_category_lp`; 2 of 5 order >0), served at `order_plan.available`, `policy_comparison` and `dead_stock` on `/recommendations` and `/dashboard`. **Unilever's demo forecast is wired too** (`GET /forecast/{sku}?principal=unilever`, the demo migrations) and its own order plan (`run_lp --source demo --principal unilever --write`, demo forecast + REAL stock, `demo.unilever_sku_lp`) is served as `demo_unilever.order_plan` beside Unilever's real `/recommendations` items — never replacing them, since Unilever's real plan is good. Forecast accuracy (mape/mase/wape, a confidence band) is the one card that stays empty on purpose: rule 2's sanctioned exception forbids any accuracy metric in `demo.*`.
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
DEC-01 through DEC-46 live in ARCHITECTURE.md. Check there before assuming behavior on ambiguous points (grain, taxonomy, etc).

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

## Loading a month and rolling it back (2026-11-06, Kelvin's brief): how it works now
Runbook: `docs/MONTH_LOAD_RUNBOOK.md`. Supersedes the one-month demonstration of 2026-11-05 (its card, its `/live-demo` routes and `LIVE_DEMO_ENABLED` are gone).
- **One interface.** Data Management's Monthly Data Processing panel is the only way a month is loaded. `backend/routers/monthly_batch.py` is always mounted; `mode()` says "practice" (the flag on the local throwaway server, unchanged) or "live" (any other named database). Permissions decide who may use it: `upload.run` to load, the new admin-only `data.rollback` to roll back. No flag, no env var.
- **The file's month comes from the file** (`analytics/month_file.py`): a date or month column, or a month written above the table; never the name. Undatable, two months, ambiguous dates (`03/04/2026`) or a month that is not the next one: refused with the reason.
- **Load** (`scripts/demo_session.py load`): reads the file; saves a rollback point; optionally accepts the plan's waiting orders at the recommended quantity (Audrey's gate stays: the batch refuses while one waits); writes the rows `is_demo = true, _src_file = qa_synthetic_march`; runs `scripts.run_month`. March, then April on top.
- **Rollback** (`... rollback --month M`): restores the rollback point taken before M (so also removes later months), one transaction, rolled back unless EVERY table (copied or not), view and function equals the point's fingerprint; then plan and (back at the original state) the 51 pins. Two points are kept (~106 MB each on live, read 2026-11-05); a third load releases the oldest first.
- **The gate.** Any database but this machine's throwaway server needs `--target-public` AND `docs/MONTH_LOAD_REHEARSAL.json`: an attestation, committed, written only by `python -m scripts.month_load_rehearsal` after load, load, roll back, roll back (and the second round, the release of the oldest point) restored a restored copy EXACTLY at every step. It carries a hash of the files that load and roll back AND of what a load runs (ABC, forecast, LP, marts; 21 files since 2026-11-13); an edit to any invalidates it (`scripts/demo_rehearsal.FILES`).
- **Labels.** Every page carries the banner "Generated sales. Sales for March 2026 is generated: SSM has not sent that month…" (header `X-Generated-Sales`, set by `PracticeBodyLabel(data_keyed=True)` while the data holds labelled rows, cleared by the page when a JSON answer lacks it). Forecast error is not shown for a period resting on them; real months' rows of a range that reaches them stay (they carry the stock-out flags). Nothing on a page says practice, demonstration or test.
- **What the tests isolate.** `tests/backend/conftest.py` stubs `demo_labels` for every backend test: a machine whose `.env` names live, while live holds a loaded month, otherwise labels every TestClient answer.

Sign-in findings kept from 2026-11-05:
- **Sign-in findings (2026-11-05, from clean worktrees with no .env and only SUPABASE_DB_URL + JWT_SECRET_KEY set).** Password sign-in of the ADMIN account works against live on kelvin-be and on Main-Final's backend, locally and on the deployed Render API (`logincred.onrender.com`, 84 s on a cold start). The Vercel address in CORS, `ssm-dsd-six.vercel.app`, answers DEPLOYMENT_NOT_FOUND: the frontend is not served there. The STAFF account `guillermo@gmail.com` is not in `app.users` (five accounts, all admin); the app creates users only by invite (`/auth/register`), so none was made by hand. The leads in the brief did not reproduce: `practice_copy` answers 409 only when SUPABASE_DB_URL names ssm_practice; the API never reads SUPABASE_DIRECT_URL or SUPABASE_KEY. Login now says "the server is waking up" after 4 s.

## Checks
- Adding a real month: `docs/MONTHLY_LOAD_PROCEDURE.md` (the corrected commands; the older text in `git show 468c6d8:RUNNING.md` omits `--calendar-factor` and would move the plan).
- `scripts/check.sh --fast` (about 40 s: lint, the pinned-figure verification, the five cross-endpoint invariants in `tests/invariants/`) is what runs constantly; `--full` adds the whole pytest suite and the frontend build. It is read-only against the live database. **Skipped is not passed:** a check that cannot run fails the script and names the missing variable.
- `scripts/check.sh --optin` runs the 18 opt-in database tests (the 17 fill tests and the rollover test, marked in `scripts/known_opt_in_skips.txt`) on a disposable database on 127.0.0.1:55432 restored from a local backup, reports each, and tears it down. It never touches live, and those tests refuse anything else (`scripts/optin_guard.py`). A pass there says nothing about live, where they must never run.
- The Stop hook that runs `check.sh --fast` when a session ends its turn is **local and not pushed** (`.claude/hooks/stop-check.sh` + `.claude/settings.local.json`, both git-ignored). The shared thing is `scripts/check.sh`; run it by hand if you do not have the hook. The hook blocks the first failing stop and lets the second through with a warning, so a failure it cannot fix does not trap a session.

## Session report ending (required)
Every session report ends with these three headings, in this order, each under five lines and saying "none" when there is none. Everything else goes above them.
```
## Figures that moved
## Decisions needed
## Contradictions found
```

## Working style
- Plain language; spell out jargon and acronyms. Compact responses, no long prose recaps.
- Ask only if something fails or a decision isn't covered; otherwise follow the pre-approved thresholds in the prompt.
- Tests: run only the tests for code you touched; the full suite runs in a final QA session.
- After any code change: `git diff <file>` to verify it's a structural fix, not a string-prefix patch.
- Token-efficient: targeted edits over full-file rewrites.
