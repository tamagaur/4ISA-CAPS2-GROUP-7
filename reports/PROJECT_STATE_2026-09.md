# Project state — 2026-09-09  (Phase 0 baseline)

**The standing source of truth for the re-check.** Every number here is from a
live query or a committed file, dated. No fabrication.

**Report convention (2026-09-09):** this file is the durable baseline. Each phase
has **one live report** (`PHASE<N>_*_2026-09.md`); when a phase closes, its
conclusions are folded into this file and the phase report moves to
`reports/archive/`. Phase 0's follow-up analyses (`PHASE0_FOLLOWUP_CHECKS.md`,
`TIERA_STABILITY_2026-09.md`) are folded into §8–§9 below and archived.

---

## 1. Live database state

### 1a. Row counts (real vs demo)

| Table | Total | Real | Demo | Notes |
|---|---|---|---|---|
| `unilever_sku_demand_fact` | 44,575 | **24,906** | 19,669 | 1,807 SKUs, monthly 2023-01 → 2026-02 (38 months) |
| `inventory_fact` | 349,860 | **32,453** | 317,407 | UL 27,282 / DM 5,171 |
| `sellout_fact` | 8,368 | **1,539** | 6,829 | Del Monte category grain, 17 months |
| `sales_fact` | 53,320 | **17,947** | 35,373 | Del Monte invoice grain, no product column |
| `purchase_fact` | 2,110 | **353** | 1,757 | Del Monte only, 10 months, `units_received` **0/353** |
| `salesreturn_fact` | **0** | 0 | 0 | BO path dead |
| `abc_classification` | 23,223 | — | — | 38 monthly periods, **Unilever only** |
| `forecast_result` | 132 | — | — | 119 `ok` (MA3) + 13 `insufficient_data` (trailing avg), 0 Del Monte |
| `lp_recommendation` | 430 | — | — | **stale** — 34 cycles 2023-05→2026-03, generated 2026-08-23/24 |
| `product_dimension` | 17,536 | — | — | UL sku 2,098 · DM sku 15,339 · DM category 99 |
| `customer_dimension` | 23,712 | — | — | all Del Monte |
| `supplier_dimension` | 2 | — | — | |

Views: `*_real` (6, strict `WHERE is_demo = false`), `bo_monitoring_view`,
`product_demand_view`, `unilever_inventory_monthly`.

### 1b. Coverage detail

- **Unilever demand** — 24,906 real rows, **1,807 SKUs**, contiguous 2023-01 → 2026-02.
- **Unilever inventory (SOH)** — 27,282 real rows, 1,718 SKUs, 2023-01 → 2026-03,
  `quantity_on_hand` in **cases**, `unit_cost_per_case` populated. Loaded via
  `scratch/run_ssis_soh_load.py`, not canonical Load.
- **Del Monte sell-out** — 1,539 real rows, **17 non-contiguous months**. Taxonomy
  break is stark: 2023-01…2024-02 months carry **74–80 categories**; 2025-03…2025-12
  carry **4–5**. Missing 2023-07, -10, -12; all of 2024 after Feb; most of 2025.
- **Purchase** — Del Monte only, 10 months, `units_received` never populated. **No
  Unilever purchase data at all.**

### 1c. `product_dimension` field population

| principal / grain | rows | category_path | brand | pack_size | unit_price | lead_time_days | manual_reorder_point |
|---|---|---|---|---|---|---|---|
| unilever / sku | 2,098 | 291 | **1,807** | 1,807 | 0 | 0 | 0 |
| delmonte / sku | 15,339 | 310 | 0 | 0 | 0 | 0 | 0 |
| delmonte / category | 99 | 99 | 99 | 0 | 0 | 0 | 0 |

- **`category_path` is NULL for all 1,807 Unilever demand SKUs** (the 291 non-null
  are SOH-only SKUs with no demand — DEC-22).
- `brand` populated for all 1,807 demand SKUs — but **no code writes it**
  (ad-hoc). `unit_price`, `lead_time_days`, `manual_reorder_point` — 100% NULL,
  no code reads or writes them.

---

## 2. is_demo contamination check — VERDICT: **not contaminated**

The `orchestrate_abc.py::_fetch_unilever_sku_revenue` bug (reads the base table,
no `is_demo` filter) is a **latent code defect, not an active contamination**:

| Check | Result |
|---|---|
| Real vs demo months | Real 2023-01→2026-02; demo 2021-01→2022-12 **and** 2026-03→2026-08. **Zero month overlap.** |
| Demo rows in period 2026-02 | **0** |
| Recompute ABC Tier A for 2026-02 — base table vs `_Real` view | **Identical** — symmetric difference 0 |
| Same for 2025-12, 2024-01, 2023-06 | Identical (symdiff 0) each |
| Stored `abc_classification` 2026-02 Tier A vs fresh recompute | **Exact match** (132 SKUs) |
| `forecast_result` product_keys vs stored Tier A | **Exact match** — `fr == stored_A`, both 132 |

**So the cohort of 132 Tier-A SKUs is real.** Phase 3's clustering test and Phase
4's candidate set are aimed at the right SKUs. The `is_demo` fix stays a Phase 2
code-hygiene task; it is **not a blocking prerequisite**.

Why it's still safe today: every stored ABC period is a real month, no real month
has demo rows, and `run_baseline_forecast.py::resolve_abc_period` guards against
`MAX(classification_period)` landing on a synthetic period.

Also verified clean: the `scratch/fix_db.py` fabrication (`mape=15.0`,
`forecast_value=58995.66` on SKU 68438413) was **overwritten** by the 2026-09-01
`run_baseline_forecast.py --write` rebuild. **0 rows** now carry that value.
Migration 0007's phantom-sku-code null is holding (0 Del Monte category rows with
a non-null `sku_code`).

---

## 3. Manifest reconciliation — three snapshots, none authoritative for the live DB

| Source | Date | Content |
|---|---|---|
| `staging/_manifest.json` | 2026-08-20 20:44 | **8 families**, 1,590 sheets, 0 rejects, **2,089,347 rows** staged. `unilever_sku` shows 31 sheets / 44,583 rows — picks up ~30 non-La-Union sheets (SOH etc.), not just the 1 file / 24,906 rows. `sales_return` 68 sheets / 1,931 rows. `ssis_summary` 805 / 1,949,687. |
| `transform/_manifest.json` | 2026-08-20 21:40 | 669 staged / 921 rejected. `ssis_summary` **805 all blocked** (natural_key null). `rmr_gs_bo` **44 rejected / 4 staged** (dedup conflict). `purchase_order` 49 rejected. `sales_return` 68 in the `staged` list but has no `source_of_truth.yaml` entry → no fact destination. `sell_out` 129 staged. |
| `transform/_signoff.json` | — | **MISSING.** The Load sign-off gate has never passed. |
| `ARCHITECTURE.md:217` status | (older) | "7 families … 2,008,084 rows" — **STALE**, predates the `sales_return` 8th family and the fuller `ssis_summary`. |
| **Live Supabase DB** | 2026-08 → 2026-09 (scratch + migrations) | Populated **after** both manifests, by `scratch/` scripts + hand-applied migrations. Canonical `analytics/etl/load.py` **never ran**; neither QC gate exercised. |

**A controlled canonical Extract → Transform → sign-off → Load re-run is Phase 1
(into a scratch schema, diffed against live).** Not done in Phase 0 — re-running
Extract would clobber the committed manifests, which are the evidence.

---

## 4. Provenance map — how the live DB was actually populated

Canonical `analytics/etl/load.py` was never run. Every fact/dim in the live DB got
there via one of:

| Table / data | Loaded by | Notes |
|---|---|---|
| `unilever_sku_demand_fact`, `sellout_fact`, `sales_fact`, `purchase_fact` (real rows) | **UNVERIFIED mechanism** — no committed canonical loader; likely `scratch/execute_sql.py` / `scratch/fix_db.py` / ad-hoc, pre-2026-08 | The row counts match `transform/_manifest.json` staged totals for these facts, so a Transform→DB step happened, but not through `load.py`. |
| `inventory_fact` Unilever SOH (27,282) | `scratch/run_ssis_soh_extract.py` → `run_ssis_soh_transform.py` → `run_ssis_soh_load.py` → `run_ssis_soh_post_load_verify.py` | Bypasses `load.py` entirely; raw `fact_table.insert()` batches. The `ssis_soh` family is **not in `FAMILY_PARSERS`**. |
| `inventory_fact` `valuation` / `cost` columns | migration `0004` (`valuation`), then ad-hoc for `cost` (documented later by `0009`) | `0004` header: "Add missing valuation column … for dashboard KPI calculations" |
| `inventory_fact` `unit_cost_per_case`, `quantity_pieces`, `blocked_qty_*`, `stock_status` | migration `0009` | R11/R12 |
| `inventory_fact` `days_offset`, `demand_period`; `unilever_sku_demand_fact.gsv` | migration `0010` + `scratch/backfill_0010.py` | `0010` = DDL only; the backfill script does the per-row work |
| `product_dimension` +291 Unilever SOH-only SKUs | ad-hoc `INSERT` (`scratch/execute_sql.py` / `append_sql.py`) — **exact script not committed** | DEC-22; `transform_ssis_soh.write_outputs` only emits `product_dimension_candidates_r8.csv` |
| `product_dimension` Del Monte 15,339 sku rows + `sellout_fact.product_key` random reassignment | `scripts/map_dm_sales_to_skus.py` (`random.choice()`) | **Reverted** by migration `0006` (product_key → category) + `0007` (99 phantom sku_codes nulled) — but the 15,339 dim rows remain |
| `product_dimension.product_name` fixes | `scratch/append_sql.py` (5 hardcoded `UPDATE`s) + `scratch/update_products.sql` | |
| `product_dimension.brand` (1,807) | **UNVERIFIED — no code found.** Ad-hoc. | Must be made reproducible in Phase 1c. |
| `is_demo` column + `_Real` views | migrations `0001`, `0005` (`0005` fixes an `OR principal='delmonte'` that made the filter always-true) | |
| `abc_classification` (real periods) | `scripts/restore_abc_purge.py` after commit `0737434` purged Del Monte + Unilever synthetic periods; then presumably `orchestrate_abc` recompute | Backup at `reports/abc_purge_backup_2026-08.json` |
| `forecast_result` (132) | `scripts/run_baseline_forecast.py --write`, 2026-09-01 | Deletes orphan SARIMA rows in the same txn; dumps to `reports/orphaned_sarima_rows_*.json` |
| `lp_recommendation` (430) | `scripts/run_lp.py`, 2026-08-23/24 | **Stale** — pre-dates the MA3 forecast rebuild; SARIMA-era per-SKU-date cycles |
| `forecast_result` fabrication on 68438413 | `scratch/fix_db.py` (`mape=15.0`) | **Overwritten** by the 2026-09-01 rebuild; 0 rows carry it now |
| `synthetic` demo rows (all facts) | `scripts/generate_synthetic_*.py`, `scripts/convert_synthetic_to_staging.py`, `scripts/generate_synthetic_dm.py` | `is_demo=true`, excluded by `_Real` views |
| `audit_log`, `users` | migration `0003` + backend | |

**Migrations 0001–0010:** each header says "ALREADY APPLIED live". They were
hand-applied, not run through a migration tool. Note the **duplicate 0002**
(`0002_add_boundary_flag.sql` and `0002_add_sku_management_fields.sql`).

---

## 5. Stale-report register

| Report / section | Says | Reality | Correction |
|---|---|---|---|
| `FULL_DATA_AUDIT.md` §B7-B8, §D1 | "Zero real Unilever inventory rows — `Inventory_Fact` 100% synthetic" | Live: **32,453 real** (27,282 UL SOH + 5,171 DM) | SOH loaded via `scratch/run_ssis_soh_load.py` **after** that audit. §B7-B8 obsolete. |
| `DASHBOARD_RECON.md` §6 | "`Dashboard.jsx` is pure mock — `MOCK_*` constants, demo badge, 4 hardcoded KPIs" | `Dashboard.jsx` now calls `getDashboardData()` → `GET /dashboard`, no mock constants, no badge | Rewired since the recon. Every other DASHBOARD_RECON claim (backend all DB-backed) still holds. |
| `CLAUDE.md` — pipeline line | "SARIMA forecasting" | Deployed = **MA3 one-step** (`run_baseline_forecast.py:748`) | See `MA3_METRIC_RECONCILIATION.md`. |
| `CLAUDE.md` — known open items | lists `run_sarima.py` bugs (`fast_grid` override, fabricated MAPE=15.0, 5× guard) + `generate_sarima_artifact.py` `forecast_quantity` crash | `run_sarima.py` is dead code, not deployed; its output rows are deleted as orphans. `generate_sarima_artifact.py` + `scripts/plot_forecast.py:27` still reference `forecast_quantity` but are off the live path. | Move to "retired / dead code". |
| `CLAUDE.md` — "Dashboard runs on hardcoded mock data" | | `Dashboard.jsx` is live; backend has been DB-backed | Correct. |
| `ARCHITECTURE.md` §7 "Still open" | "the Transform driver itself … is not yet built" | `transform_driver.py` **exists**, ran 2026-08-20 | Stale. |
| `ARCHITECTURE.md` §7 "Still open" | `quantity_sold` cases-vs-pieces "not yet decided" | DEC-11 resolved it (pieces) | Stale line. |
| `ARCHITECTURE.md:217` status | "7 families … 2,008,084 rows" | 8 families, 2,089,347 rows staged | Stale. |
| `SEASONALITY_AND_BASELINES.md`, `ADVISER_EVIDENCE.md` — MA3 numbers | MA3 median MASE 0.795 / 0.838; wins 31/89 | Superseded — pre-purge 136-set, seasonal-12 MASE scale | Cite `MODEL_BAKEOFF_UNILEVER.md` / `MA3_METRIC_RECONCILIATION.md` instead. |
| `FULL_DATA_AUDIT.md` §E2/E3 threshold tables | median MAPE 59.4, MASE 1.285 | Those are **SARIMA** numbers, not MA3 | Relabel if they migrate toward a results section. |

---

## 6. Decision inventory — every OPEN item needing a human

Full text + evidence + recommendation in `reports/ADVISER_QUESTIONS_SIRCG.md`
(adviser) and `reports/CLIENT_QUESTIONS_SSM.md` (client). Summary:

**Provisional decisions logged 2026-09-09** (Yuan's ruling so Phase 1–3 don't
stall; revisit when the real answers return):
- **P-A — ABC period basis:** Phase 2 computes **both** single-period and
  trailing-3-month; **single-period is the default cohort of record** until Q8 is
  ruled. → item 17.
- **P-B — forecast gate:** **MASE < 1.0** provisionally (item 5).
- **P-C — D5 bad-order metric:** **value/count trend, not a rate — FINAL, not
  pending.** No Unilever purchase data exists; `Purchase_Fact.units_received` is
  0/353. This is a data fact, written into `API_CONTRACTS.md` as final. → item 18.
- **Parked, no Phase 1–3 impact:** σ form (item 2-adj), weights + provenance
  (items 7, 9), EOQ/DEC-08 (item 8), `BOUNDARY_MARGIN` (item 10).

| # | Item | Owner | Status | Blocks |
|---|---|---|---|---|
| 1 | Replenishment horizon — review cadence R + lead time L | **Client** (SSM via Thea) | OPEN | Phase 4b (ROP→S) entirely; σ sizing |
| 2 | Storage / holding-cost rate `h` | Client | OPEN | LP objective's cost term |
| 3 | Warehouse capacity `W` | Client | OPEN | LP constraint 1 |
| 4 | Supplier 52-week allocation `A` | Client | OPEN | LP constraint 2 (proxy available) |
| 5 | MAPE < 0.20 → MASE < 1.0 gate | **Adviser (Sir CG)** | **PROVISIONAL → MASE < 1.0** | Phase 4 SKU coverage (19 vs 67) |
| 6 | ROP → Order-Up-To-Level (S) model change | Adviser | OPEN (parked, no Phase 1–3 impact) | Phase 4b |
| 7 | LP restructure — service level as a constraint; what happens to weights 0.45/0.35/0.20 | Adviser | OPEN (parked) | Phase 4c |
| 8 | EOQ / DEC-08 — was it ever actually required? | Adviser + panel | OPEN (parked) | Manuscript §3.4.3 |
| 9 | LP weights provenance — 0.45/0.35/0.20 in no scribe note | Adviser | OPEN (parked) | Defensibility |
| 10 | `BOUNDARY_MARGIN = 0.02` — source vs manuscript §3.6 | Adviser | OPEN (parked) | ABC boundary flag |
| 11 | DEC-02 (two-marts), DEC-06 (SCD Type 1) — PROPOSED → DECIDED | Team | OPEN | Formalize |
| 12 | DEC-14 (2% reject-rate gate) — not a sourced number | Team / adviser | OPEN | Load gate |
| 13 | DEC-22 — recompute ABC vs 2,098 denominator | Team (Phase 2) | OPEN | ABC currency |
| 14 | DEC-23 — SARIMA replacement (evidence gathered, no decision) | Adviser | OPEN | Superseded by the map's method choice; confirm |
| 15 | Per-cluster / multi-model direction | **Prof** (after seeing the Phase 3 clustering test) | OPEN | Phase 3a |
| 16 | Del Monte taxonomy break (Jan-2025, 74→5 categories) — bridge or era-split? | Adviser + client | OPEN | Del Monte category analysis |
| 17 | ABC period basis — single-period vs trailing-3-month (Q8) | **Adviser (Sir CG)** | **PROVISIONAL → both computed, single-period default** | Phase 3 cohort, Phase 4 coverage |
| 18 | D5 bad-order metric — rate vs trend | — | **FINAL: value/count trend** (no UL purchase data; not a decision) | — |
| 19 | `purchase_fact.region` — 223/353 live real rows carry `'False'` (fixed forward in `purchase_order.yaml` 2026-09-11; live rows untouched — no DB writes in Phase 1) | Team (Phase 1d cutover) | Scratch-vs-live diff must show this delta explicitly, not silently overwrite it |
| 20 | `SalesReturn_Fact` UNIQUE constraint mismatch — **RESOLVED 2026-09-11**: migration `0011` drops `return_type`, adds `invoice_num` to the constraint. Drafted, not applied (no DB writes). | — | Migration `0011` ready for Yuan's apply-decision |
| 21 | `sales_return` `return_type` in the key — **RESOLVED 2026-09-11**: tested drop vs COALESCE against real data, identical results (1 group/3 rows either way, both false — see item 22). **Approved: drop `return_type`.** In migration `0011`. | — | Closed |
| 22 | `sales_return`'s 3 fully-blank rows — **RESOLVED 2026-09-11**: filtered at transform (`exclude_sales_return_header_rows`, 3rd check). Verified: excluded exactly 3, real dedup input 1,383→1,380, quarantine 776→773, conflicts stay 0. | — | Closed |
| 23 | `sales_register`'s 1 remaining real conflict (`INV/2024/0542`) — **shown in full 2026-09-11** (two different transactions, different date/customer/salesman/branch/amount, same invoice number). Not fixed — Yuan said "show me," not "fix it"; not in migration `0011`'s scope. | Team | Open — same-shape fix (`invoice_date` in the key) available if wanted |
| 24 | `inventory_sign_off` "3rd header shape" (`ARCHITECTURE.md:196`) — **VERIFIED MOOT 2026-09-11**, note closed. **RESOLVED 2026-09-12**: 31/46 real unmatched rows (29 `"Total"` + 2 `"#REF!"`) now excluded via the consolidated `exclude_footer_rows`. **NOT resolved, deliberately**: the remaining 15 (12 null, 1 `"DESCRIPTION"`, 2 `"WH/Stock"` variants) all carry real quantity/cost/valuation data — excluding them risked dropping real inventory data, so they're left flagged, `sku_code_status='unmatched'`. | Team | Minor — 15 real rows, needs source-sheet inspection before any rule |
| 25 | "22 conflicts" in the manifest vs "0 real conflicts" claimed — **RECONCILED 2026-09-11/12, not a discrepancy**: 22 = real+demo combined conflict sheets (133 underlying groups: 114 inventory + 16 sell_out + 2 sales_register, all demo except 1 real sales_register group already known). The loader processes real+demo together (demo data is approved, per CLAUDE.md rule 1) and will encounter these ~132 demo-driven conflicts with the same "keep all, flag" treatment as real ones — no special-casing. "0 real conflicts" premise unchanged and confirmed. | — | Closed — reporting convention fixed: state real vs demo vs combined always |
| 26 | Footer-row exclusion consolidated into one shared `exclude_footer_rows()` (was 3 separate near-identical functions) — **DONE 2026-09-12**. | — | Closed |
| 27 | `scripts/run_canonical_load.py` — **WRITTEN 2026-09-12** per the approved design + Yuan's 3 requirements (transactional gate-failure rollback, expected-vs-actual per table, per-SKU backfill logging) + `--dry-run` added to `load.py`. Syntax/import-verified, `FACT_PLAN` cross-checked against `source_of_truth.yaml`; DB-touching logic itself is UNVERIFIED (no DB writes this session). Two bugs caught before reporting done: a schema-scoping bug in the raw backfill SQL (would have silently hit `public`), and the validated keyword-rule fallback has no description source to apply to in production (`category_path_source` will only ever show `direct_soh_match`/`unclassified`, not `keyword_rule`, until a second Unilever description source is found). | Yuan | Needs: migration 0011 applied, `config/alias_tables/unilever_brand.csv` built, then a `--dry-run` invocation, then a real scratch run |
| 28 | `inventory_sign_off`'s 15 real `unmatched` rows — **LOGGED 2026-09-12** with full traceable identifiers (file/sheet/row_ordinal, no `sku_code` exists for these), `PHASE1_EXECUTION_PLAN_2026-09.md` decision item 28. Pattern A: 13 rows, one file/sheet (`AUGUST 2023...ILOCOS-ACTUAL`), row 0 = `"DESCRIPTION"` (large, 2,598 cases) + rows 143–154 contiguous, small real per-line quantities, `sku_description_raw=NULL`. Pattern B: 2 rows, each row 0 of a different sheet, large warehouse-scale magnitude (`"WH/Stock"`/`"IS-WH/Stock"`) — read as possible warehouse subtotals, not confirmed. | Team | Needs the 3 source workbooks opened at the cited rows — not resolvable from staged parquet alone |
| 29 | Plan doc's `category_path` verification target — **CORRECTED 2026-09-12**: was "direct ≥79% + fallback (reported separately) + UNCLASSIFIED", now "79.0% direct + 21.0% UNCLASSIFIED, full stop — no fallback tier in production" (the keyword rule is built/validated but inert, item 27). | — | Closed |
| 30 | **is_demo stored as literal string `"True"` (not boolean)** for ~half of `purchase_order`'s and `inventory_sign_off`'s synthetic rows — **FOUND AND FIXED 2026-09-14**, `analytics/etl/transform.py::coerce_is_demo_column()`, wired into `transform_fact()`. Silently misclassified 1,909 + 14,662 synthetic rows as real in every `is_demo != True` filter used this whole session until now. Re-verified: real-only counts for both families come back to exactly the numbers already computed earlier in Phase 1 — that work was correct, just computed against a `staging/` snapshot that hadn't staged the buggy files yet. 128/128 tests pass. | — | Closed |
| 31 | `staging/_manifest.json` row-count mismatch vs `transform/` — **RESOLVED 2026-09-14, expected by design**: Extract's manifest only tracks `data/raw/`-sourced files; `data/raw/Synthetic Data/*` is injected directly into `staging/` out-of-band and was never reflected there. `transform_driver` globs `staging/` directly so it legitimately sees more. Not a bug — documented in the sign-off notes. | — | Closed |
| 32 | Migration 0011 — **APPLIED to the scratch schema `ssm_canonical` 2026-09-14** (`--schema-only`), verified via direct read-only query: 25 tables, `category_path_source`/`brand_source` columns exist, `salesreturn_fact`'s new 4-column UNIQUE constraint exists, `inventory_fact.quantity_on_hand`'s comment is set. Three real execution bugs found and fixed en route (SQLAlchemy `text()` misreading literal `%` as a psycopg2 placeholder; a chunk-based SQL splitter silently discarding whole statements glued to a leading comment line — `0004_add_valuation.sql` reduced to zero statements; a second, trailing-inline-comment `%` in `schema.sql` itself) — see `PHASE1_EXECUTION_PLAN_2026-09.md` step 5c for the full sequence. **Cosmetic, not fixed**: `salesreturn_fact` now carries two identical UNIQUE constraints (schema.sql already had the new definition baked in from documenting migration 0011 in place; migration 0011's DROP+ADD adds a second, differently-named one on a from-scratch build). | Team | Minor cleanup — drop the duplicate constraint |
| 33 | `scripts/run_canonical_load.py` — **`--dry-run` executed for real 2026-09-14** against the scratch schema. Two more real bugs found and fixed first: (a) no column projection before `load_to_supabase()` — added `_project_to_table_columns()` + a small `load.py` fix excluding dimension-FK source columns from its unknown-columns check; (b) `FACT_PLAN`'s targets were real-only but the loader correctly loads real+demo combined — targets corrected to combined row totals, conflicts/quarantined stay real-only (demo noise reported separately, never blended into pass/fail). **Final result: all 6 fact tables + ssis_soh match their targets exactly, zero mismatches.** Confirmed via direct read-only query: scratch schema has 0 rows in every table (dry-run wrote nothing). | Yuan | Awaiting go for the real (non-dry-run) load |
| 34 | `config/alias_tables/unilever_brand.csv` — **BUILT 2026-09-14**, 9 entries, every one backed by a real description sample (see the CSV's own `evidence` column). 3 tokens explicitly checked and NOT merged (MASTER: no target found; BABY: "Baby Dove" is a real sub-line, not a spelling variant of DOVE — a taxonomy decision, not a typo fix; BF: 1 row, unconfirmed). | — | Closed |
| 35 | M2 transform sign-off — **RECORDED 2026-09-14**, `transform/_signoff.json`, decision=approved, by="Yuan Kyle" (Yuan's explicit answer to who the name should be). Re-recorded as the manifest changed under the is_demo fix, with full notes each time. | — | Closed |
| 36 | **`purchase_fact` — 95 real rows wrongly excluded by conflict-group dropping, 2 real months 100% missing.** The real load (2026-09-14) surfaced this: `_drop_conflicting_group_rows()` treats every row in a same-key conflicting group uniformly, regardless of `is_demo` — but `data/raw/Synthetic Data/PURCHASE_ORDER_2024-*_*.xlsx`/`2025-*_*.xlsx` (22 files, a different, older synthetic dataset than `generate_synthetic_backfill.py`) reused the **real** `BILL/YYYY/NNNN` invoice-number scheme with low sequential numbers, directly colliding with genuine invoices. Result: **January 2024 (37/37 real rows) and February 2024 (29/29 real rows) are 100% excluded from the load**; March 2025 loses 16/38 (42%), April 2025 loses 13/64 (20%) — 95 real rows total, 18% of the 526-row real population. This is real data suppressed by demo-data collision, the opposite of CLAUDE.md rule 2 ("synthetic data never compromises real reported results"). **Not fixed** — flagged for Yuan before touching the exclusion logic again. Proposed fix (not applied): within a conflicting group, if ≥1 row is real, drop only the demo rows and keep the real row(s); a real-vs-real conflict (like `sales_fact`'s 1) still gets flagged for human review as today. | Yuan | Blocks trusting `purchase_fact`'s Jan/Feb 2024 figures in any diff or report until fixed |
| 37 | **`inventory_fact` (ssis_soh/Unilever) — re-run idempotency gap, not a data bug.** Its `ON CONFLICT (sku_code, snapshot_date, region)` target matches `Inventory_Fact`'s plain `UNIQUE(sku_code, snapshot_date, region)` constraint — but Unilever's `region` is always `NULL`, and `NULL <> NULL` under plain UNIQUE semantics, so that constraint never actually fires: every insert is a bare INSERT, not a real upsert. The constraint that DOES fire is migration 0010's partial expression index `uq_inventory_unilever_soh` (`sku_code, snapshot_date, COALESCE(region,''), is_demo` WHERE `principal='unilever'`), which `load_to_supabase()`'s plain `index_elements` can't target (would need SQLAlchemy `index_where` + a matching `COALESCE` expression, not implemented). **Harmless for a one-time load** (confirmed: the data itself has zero duplicate `(sku_code, snapshot_date)` pairs, so a load into an empty schema always succeeds) — **but a second load against a schema that already has this data will hit a `UniqueViolation` and roll back the whole scratch schema.** Reproduced 2× this session from repeated re-runs while debugging. **Not fixed.** | Team | Will bite the next person who re-runs `run_canonical_load.py` against a populated `ssm_canonical` without dropping it first |
| 38 | **Two new commits on `group7/kelvin-etl`, both scoped to `analytics/optimization/lp.py`/`scripts/run_lp.py`** (`bf8a3a3` "Change gating criteria from MAPE to MASE", `344fcc3` "Revise reorder point calculation and documentation") — confirmed via `git diff --stat 85a8ebf group7/kelvin-etl`, zero overlap with schema/migrations/backend/config (item context: Phase 1d pre-load remote check). Someone (Audrey, per LP ownership) is actively working the LP while Phase 4 (which owns the LP restructure) is on hold pending Sir CG's ruling on service-level-as-constraint (item 7) and the MAPE→MASE gate (item 5, already provisionally decided the same direction as `bf8a3a3`'s title suggests). **Phase 4 will need to reconcile these changes against the restructure**, not just merge them blind. Yuan messaging Audrey directly. | Yuan / Audrey | Phase 4c (LP restructure) — reconcile before Phase 4 starts, not after |

---

## 7. Phase 0 verification

- `PROJECT_STATE_2026-09.md` numbers reproduce on a second query run ✅
- is_demo diff has a clear verdict: **not contaminated, cohort of 132 is real** ✅
- `reports/ADVISER_QUESTIONS_SIRCG.md` + `reports/CLIENT_QUESTIONS_SSM.md` ready to send ✅
- `reports/API_CONTRACTS.md` drafted ✅

**Nothing was written to the database.** Extract/Transform were not re-run
(deferred to Phase 1 to preserve the committed manifests as evidence).

---

## 8. Phase 0 follow-up conclusions  *(folded from `PHASE0_FOLLOWUP_CHECKS.md`, archived 2026-09-09)*

1. **`check_reject_rate_gate` measures Extract file/sheet rejects only** —
   `staging/_manifest.json`'s `reject` list (unreadable / no-header / Magnolia).
   That list is **empty** → the gate passes trivially at 0%. It does **not** see
   the 805 `ssis_summary` blocks or the 921 transform-stage rejects (those are in
   `transform/_manifest.json`, never read by the gate). Passing it is **not**
   evidence of transform quality.
2. **`ssis_summary` has no product grain, no fact destination, no real rows.**
   Column map has no SKU/article/item column. 95.6% of its 1.95M rows are
   product-less outlet×day×invoice sales value. `source_of_truth.yaml`'s
   `sales.unilever → ssis_summary (natural_key: null)` is a **dead declaration**
   (`Sales_Fact` has `CHECK(principal='delmonte')`). 0 real DB rows trace to it.
   → Phase 1 step 1: replace with an explicit "excluded, no fact destination"
   marker.
3. **`purchase_order` reaches `Purchase_Fact`** — all 353 real rows from Del Monte
   monthly PURCHASE ORDER sheets, 10 months. `units_received` 0/353 (→ D5 is a
   trend, not a rate — item 18, FINAL).
4. **`category_path` direct-match ceiling = 79.0%** (1,427 of 1,807 UL demand SKUs
   have a SOH row with `category_desc`; 380 have no SOH row; 0 have a null
   category). Verification bar reported as three separate numbers: direct 79.0% /
   keyword fallback (measured) / `UNCLASSIFIED` bucket. **The 380 no-SOH SKUs are
   0.2% of all-time and 2026-02 revenue, 0 Tier A** → `UNCLASSIFIED` is immaterial,
   the earlier `<8%` target is dropped as moot.
5. **brand→category is NOT 1:1** — 9 of 35 derived brands span >1 category,
   including SURF and KNORR (the two biggest). A flat brand→category fallback is
   not defensible. Fallback = **description-keyword rule**, validated out-of-sample
   at **94.6%** accuracy (97.4% at confidence ≥0.6, 89% coverage; 70/30 split, fit
   on train only). Rule: direct SOH match → keyword at conf ≥0.6 → `UNCLASSIFIED`.
   `brand` itself needs a committed first-token + alias-table rule (LADYS/LADY'S/
   LADY?S mojibake) — `config/alias_tables/unilever_brand.csv`.
6. **`unilever_sku` staging = 31 sheets** = 1 real (`UnileverLaUnion…xls`, 24,906
   rows, 2023-01→2026-02) + 30 `GENERATED_BACKFILL_*` synthetic (19,677 rows,
   2021-01→2022-12 and 2026-03→2026-08). 8-row staging→load attrition. Same origin
   as the purged demo ABC periods.
7. **ABC = 38 periods** (2023-01→2026-02), not 36. Plan doc corrected.

---

## 9. Tier-A stability  *(folded from `TIERA_STABILITY_2026-09.md`, archived 2026-09-09)*

Cohort convention: **every reference states its period** — "Tier A as of 2026-02"
(= 132), never bare "Tier A".

**Verdict: a small stable core with a churning boundary — not real instability.**

- **Stable core ~49 SKUs**: 21 Tier A in all 38 periods, 28 more in ≥30. All ≥36
  months history, all smooth (ADI ≈ 1.00, CV² 0.08). This is the real Category A.
- **Churn pool ~366 SKUs**: Tier A in a median of 7/38 periods; 40% have <12
  months history; mostly intermittent/lumpy. 415 SKUs ever Tier A.
- **Hypothesis holds** — always-Tier-A = long-history + smooth; occasional =
  short-history + intermittent. Confirmed on the two cluster axes.
- **Monthly count (89→149→132) is driven by revenue concentration, not level**:
  corr(A count, total revenue) = +0.31; corr(A count, monthly HHI) = **−0.74**;
  corr(A count, n SKUs selling) = **+0.70**. When a few large orders land, fewer
  SKUs clear the 80% cutoff.
- **2025-12 (A=89) is a documented anomaly**: lowest revenue month of 38, most
  concentrated, fewest SKUs selling, negative-revenue spike (90 SKUs). Do not
  anchor any decision on it.
- **`_split_negative_revenue` clamp**: ~1 boundary SKU/month in normal months, 8
  in 2025-12. Minor contributor, still a Phase 2 fix (comment/behavior mismatch).

**Downstream implication:** Phase 2 computes both single-period and trailing-3-month
ABC + a `tier_a_period_count` per SKU; Phase 3 clustering starts from the core/pool
split as stored data. Cohort of record for forecasting/LP is Sir CG's call
(adviser Q8; provisional = single-period).

---

## 10. Phase 1 gate close (2026-09-14)

**Full detail:** `reports/PHASE1_EXECUTION_PLAN_2026-09.md` (all steps, every
bug found/fixed, full row accounting). This is the gate deliverable — what
changed across the phase, the final frozen row targets, every open item
carried into Phase 2, and the cutover recommendation. **Phase 1 substance is
complete; the cutover itself is Yuan's decision, reviewed separately from
this close.**

### What changed, across the whole phase

The canonical `analytics/etl/` pipeline (Extract → Transform → sign-off →
Load) now runs end-to-end for real, into a scratch schema (`ssm_canonical`),
reproducing the DB from code for the first time this project has had that.
Both QC gates pass for real. `config/alias_tables/unilever_brand.csv` and
`Product_Dimension.category_path`/`brand` backfill are real and reproducible
for the first time (previously ad hoc, written by no code). A scratch-vs-live
diff script (`scripts/diff_scratch_vs_live.py`) exists, was run multiple
times, and is now the standing tool for any future re-check.

**14 real, distinct bugs were found and fixed via actual execution (not
review) across the phase**: the `is_demo` string/bool bug; 3 footer/junk-row
exclusion gaps; a stale sign-off/manifest wiring gap; 2 migration-application
bugs; 2 column-projection/target-basis bugs in the loader; 3 NOT-NULL/
conflict-group exclusion bugs found during the first real load; item 36
(real rows lost to demo-invoice-number collisions in `purchase_fact`); item
39 (`load.py`'s NaN-vs-NULL root cause); item 40a (`sellout_fact`'s
source-file-defect categories) and 40b (a null-masking defensive fix). A
full 8-class, every-table sweep (§13 of the Phase 1 report) confirmed
nothing else of these shapes remains in the pipeline.

### Frozen row targets — final (real load, `ssm_canonical`, 2026-09-14)

| table | rows (real+demo) | conflicts (real-only) | quarantined (real-only) |
|---|---|---|---|
| `unilever_sku_demand_fact` | 44,575 | 0 | 0 |
| `sales_fact` | 53,109 | 1 | 432 |
| `purchase_fact` | **2,762** (was 2,667 before item 36's fix) | 0 | 27 |
| `salesreturn_fact` | 1,630 | 0 | 8 |
| `sellout_fact` | **7,660** (was 8,545 before item 40a's fix) | 0 | 0 |
| `inventory_fact` (inventory_sign_off) | 20,905 | 0 | 188 |
| `inventory_fact` (ssis_soh/unilever) | 27,282 | — | — |

`category_path_source` split: `direct_soh_match` 1,427 (79.0%), `unclassified`
380 (21.0%, Unilever grain=sku), `source_file_defect` 1 (Del Monte
grain=category — item 40a, consolidates what were 12 separate fake category
rows into one honest `UNCLASSIFIED` dimension member), `keyword_rule` 0
(inert, no description source — item 27).

### Scratch-vs-live diff — real rows agree exactly on 4 of 5 comparable tables

`sales_fact`, `sellout_fact`, `inventory_fact`, and `unilever_sku_demand_fact`
all match live's real-row count exactly, with **zero value disagreements** on
every matching key across all six tables. `salesreturn_fact` is a clean
addition (live has 0 rows — the BO path was dead; nothing is overwritten).
`purchase_fact` has 51 more real rows in scratch than live (404 vs 353) —
**verified, not re-staged duplicates**: of the 353 live real rows, 130 carry
over unchanged (0 value mismatches) and 180 are the *same* invoices
re-keyed correctly after item 19's region fix (not new data). The remaining
43 of live's original rows are gone — casualties of item 36's conflict-group
bug (Jan 2024: 7, Feb 2024: 21, Mar 2025: 8, Apr 2025: 7 — a subset of that
item's 95 total). Real growth (2025-04/06/08/12, +85 combined) outweighs
those losses, netting to +51. Full per-month table and methodology:
`PHASE1_EXECUTION_PLAN_2026-09.md` §12.

### Open items carried forward (not fixed this phase, tracked for later)

| item | what | scope | risk if left open |
|---|---|---|---|
| 19 | `purchase_fact.region = 'False'` on 223/353 **live** real rows (fixed forward in `purchase_order.yaml`, live untouched) | Live DB only; scratch is clean | None today — no live endpoint filters/groups on `purchase_fact.region` (checked: `bo_monitoring.py`, `dashboard.py` don't select it). Resolves automatically if/when cutover happens. |
| 24 | 15 `inventory_sign_off` rows with ambiguous `sku_code_status='unmatched'` (real quantity/cost/valuation data, no confirmed SKU identity) | Scratch only, ~15 rows | Needs the 3 source workbooks opened at cited rows — not resolvable from staged parquet alone |
| 36 | **RESOLVED 2026-09-14** — `purchase_fact`: 95 real rows wrongly excluded by `_drop_conflicting_group_rows()` dropping a real row whenever it collided with a badly-numbered demo invoice. **Fixed**: within a mixed (real+demo) conflicting group, only the demo rows are now dropped; a real-vs-real group (sales_fact's 1 case) keeps the original behavior. Re-run confirmed exactly as expected: `purchase_fact` real rows 404→499 (+95). Re-diffed: **scratch now dominates live in every month** (9/9), 0 value mismatches on 130 matching keys, and **all 223 of live's `region='False'` real invoices are now recoverable under their corrected region in scratch — 0 real rows truly lost** (was 43). | Scratch `purchase_fact` load logic | Closed — gate condition met |
| 37 | `inventory_fact` (ssis_soh/Unilever) upsert re-run idempotency gap — `ON CONFLICT` target doesn't match the real partial-expression DB constraint | `run_canonical_load.py`, load-time only | Harmless for a single load (verified: 0 duplicate keys in today's data); breaks on a second run against an already-populated scratch schema |
| **NEW — live NaN defect** | 137 `sellout_fact.net_amount` + 210 `inventory_fact.quantity_on_hand` **real** rows on **live** store literal `NaN` (not `NULL`) — both scoped to Del Monte, 2023-08 only (`sellout_fact`: both regions, 76 categories incl. junk `'False'`-labeled ones; `inventory_fact`: Pangasinan only, 210 SKUs). Root cause: an old ad-hoc load script, not the canonical pipeline (scratch is clean for this exact period). **Scoped 2026-09-14, not user-visible today**: every live endpoint that aggregates `quantity_on_hand` either hard-filters `principal='unilever'` (`inventory.py`, `dashboard.py`'s SOH/safety-stock functions) or filters `_period = MAX(_period)` (`sku.py`, `recommendations.py`, `abc.py`, `dashboard.py`'s safety-stock comparison) — both exclude the affected Del Monte/2023-08 rows structurally. The one code path that reads `sellout_fact.net_amount` (`orchestrate_abc.py::_fetch_delmonte_category_revenue`, Del Monte category ABC) is dormant — Del Monte rows are purged from `abc_classification` today, no endpoint serves it — and even if re-run, pandas' `.sum()` defaults to skipping `NaN` (silently undercounts the affected 2023-08 categories) rather than propagating it the way a raw SQL `SUM` would. **Not fixed** — pre-existing live defect, independent of any cutover decision; flagging for whoever owns the dashboard/live DB directly, per Yuan's instruction. **Still a real defect despite being latent today** — the moment anyone builds real Del Monte category analysis (D1, Phase 2) against live, they hit it. `ssm_canonical` is already clean for this exact period (August 2023, both facts) — **this is one point in favor of cutting over once `purchase_fact` is sorted (item 36)**, not just neutral to the decision. | Live DB only | Latent today; will corrupt Del Monte category ABC results (as `NaN`, if via raw SQL, or a silent undercount, if via the current pandas path) the moment that computation is re-run for real |
| 6 (recap) | LP restructure vs 2 remote commits (`bf8a3a3`/`344fcc3`) on `group7/kelvin-etl` | Phase 4 | Needs reconciliation before Phase 4 starts, not blocking Phase 1 |
| **39** | **`load.py`'s null-cleaning (`.where(pd.notnull(...), None)`) is a no-op on any `float64`-dtype column** — root cause of the live NaN defect above AND an active defect in the current canonical load (`unilever_sku_demand_fact.quantity_sold`, 71 real rows). **FIXED 2026-09-14**: cast to `object` before `.where()`. Verified exactly as predicted: 126 `NaN` (71 real/55 demo) → 0 `NaN`, 126 proper `NULL`. | `analytics/etl/load.py`, every table | Closed — but note this only fixes rows that flow through `load_to_supabase()` going forward; it does not retroactively fix live's existing NaN rows (those need a separate live remediation or the cutover). |
| 40 | **RESOLVED 2026-09-14** — full 8-class sweep found 2 more real issues beyond A/F: (a) `sellout_fact.category_path` held the literal text `"False"`/`"False (N)"` for 194 real rows — confirmed via raw Excel inspection (`2024 FEBRUARY SELL OUT.xlsx`, `ILOCOS_SELL OUT` sheet, rows 64+) genuinely baked into SSM's own Sell Out template (a broken formula/lookup), not a pipeline bug. **Fixed per Yuan's ruling**: same treatment as Unilever's 380 no-SOH-match SKUs — `category_path` → the literal string `'UNCLASSIFIED'`, revenue preserved (summed per `(region, _period, is_demo)`, real and demo kept separate — `analytics/etl/transform.py::relabel_sellout_source_defect_categories()`), never dropped. 194 real rows → 22 merged `UNCLASSIFIED` rows, real revenue confirmed preserved exactly (₱13,909,661.72 total, verified via direct query). `Product_Dimension.category_path_source` gets a **new** distinct value, `source_file_defect` (migration `0012`, widens the CHECK constraint) — deliberately not folded into `'unclassified'`, which means something different (no SOH match exists) and doesn't even apply to Del Monte's category grain; collapsing them would hide that this is a confirmed source defect, not an absence of data, from anyone querying the column later. The 12 former fake category rows in `Product_Dimension` collapse to 1 real dimension member (`grain='category'` is SCD Type 1 — many fact rows correctly share one dimension row). Caught and fixed one bug in the merge code itself before it shipped: `net_amount` is a genuinely mixed float/str/Decimal column, and pandas' groupby-`sum()` on the string values did text concatenation, not addition (`"15871.97"+"36578.41"` → `"15871.9736578.41"`) — failed loudly at INSERT (a Postgres numeric-parse error), not silently; fixed with explicit `pd.to_numeric()` coercion before summing, re-verified. Client informed: new section added to `CLIENT_QUESTIONS_SSM.md` asking SSM to check their Sell Out template. (b) `_load_soh_snapshot()`'s `.astype(str)` masked null `sku_code` as the literal string `"nan"` before grouping — same shape as the already-fixed `dropna=False` bug. Fixed defensively (confirmed harmless in practice either way, since the fake row never matched a real join). Everything else in the sweep (real-vs-demo collisions in every other family, footer rows in remaining families, null-key grouping elsewhere, column-mapping domain mismatches, silent no-ops, schema/key mismatches) checked clean or already logged — see `PHASE1_EXECUTION_PLAN_2026-09.md` §13 for the full 8-class table. | `sellout_fact`/`product_dimension`/`run_canonical_load.py` | Closed — gate condition met, client question sent |

### Cutover recommendation — stated plainly

**Cut live over to canonical.** Every real-data question this phase
surfaced is now resolved or explained, and on every table `ssm_canonical`
is either an exact match to live or strictly better:

- `sales_fact`, `sellout_fact` (post-item-40a), `inventory_fact`,
  `unilever_sku_demand_fact`: **exact real-row matches**, zero value
  disagreements on every key checked.
- `purchase_fact`: **strictly dominates live** — every one of live's real
  rows is present in scratch (223 previously-mistagged `region='False'`
  rows recoverable under their correct region, 130 unchanged), plus 95 real
  rows live never had at all (item 36) and further real growth from a
  fuller current corpus. Zero real rows lost.
- `salesreturn_fact`: a clean, non-destructive addition — live has 0 rows
  today (the BO path was dead), scratch has 1,630.
- The live NaN defect (137 `sellout_fact` + 210 `inventory_fact` real rows)
  and the 12-fake-category `sellout_fact` defect (item 40a) both **only
  exist on live** — `ssm_canonical` is clean for both, by construction, not
  by a separate remediation step. Cutover fixes them as a side effect.

Nothing in this phase's evidence points the other way. The two remaining
open items (37: SOH upsert idempotency; 19: `purchase_fact.region`'s stale
tag, self-resolving on cutover) are load-mechanics and live-only cosmetics,
not reasons to hold data back from being reproducible-from-code.

**If Yuan prefers not to cut over now** — e.g. to let the adviser/client
question packets land first, or simply to sit with the decision — the
fallback is: keep live as-is, with this report as the standing provenance
note (`ssm_canonical` stays available for comparison, not deleted), and
revisit after Phase 2 needs the category data this phase built. Either
choice is defensible from the evidence; the recommendation above is the
one this session's numbers support.

**Not yet done, either way:** item 37 (SOH upsert idempotency) should be
fixed before `run_canonical_load.py` is ever run again as a *repeatable*
job (it's fine for the one-time load this phase produced). That's Phase 2
housekeeping, not a cutover blocker.

This is a recommendation, not an action — no cutover, no live write, has
been made or will be made without Yuan's explicit go.

### Open items carried into Phase 2

- Item 24 — 15 `inventory_sign_off` rows with ambiguous SKU identity (needs
  source workbooks opened by hand).
- Item 37 — SOH upsert idempotency gap (fix before repeatable re-runs).
- Item 19 — `purchase_fact.region='False'` on live only (self-resolves on
  cutover; harmless either way, confirmed no live consumer reads it).
- Item 6/38 — LP restructure vs. the 2 remote commits on `group7/kelvin-etl`
  (Phase 4, needs reconciliation before that phase starts).
- `CLIENT_QUESTIONS_SSM.md` now carries the Sell Out template defect
  question (194 rows, item 40a) alongside the original 6 operational-facts
  questions — awaiting SSM's response via Thea.
- Phase 2 (ABC + D1–D4) can now build on real, reproducible category data
  for the first time — `Product_Dimension.category_path`/`brand` and their
  `*_source` columns are load-bearing and queryable, not ad hoc.

## 11. Cutover incident, 2026-09-15/16 — CLOSED, cutover complete

**Status: cutover is complete.** `public` is live on the canonical
`run_canonical_load.py` load, all 6 fact tables at full volume, all
frozen 2026-09-11/14 targets matched exactly. `run_canonical_load.py`
against `public` is safe to run again (it's the reproducible pipeline
now, not a one-off).

### Final counts, 2026-09-16

| Table | Actual | Target | Status |
|---|---|---|---|
| `sales_fact` | 53,109 | 53,109 | ✅ |
| `purchase_fact` | 2,762 | 2,762 | ✅ |
| `salesreturn_fact` | 1,630 | 1,630 | ✅ (see below — was 865 mid-run, now fixed) |
| `sellout_fact` | 7,660 | 7,660 | ✅ |
| `inventory_fact` | 48,187 (20,905 DM + 27,282 UL) | 48,187 | ✅ |
| `unilever_sku_demand_fact` | 44,575 | 44,575 | ✅ |
| `product_dimension` | 17,619 | no fixed target | 0 duplicate-key groups (4-col and 3-col) |
| `customer_dimension` / `salesman_dimension` / `supplier_dimension` | 23,712 / 33 / 2 | unchanged | untouched throughout |
| `abc_classification` / `forecast_result` / `lp_recommendation` / `users` / `audit_log` | 23,223 / 132 / 430 / 2 / 46 | unchanged | untouched throughout |

### `salesreturn_fact`'s MISMATCH — root cause, fix, and correction to the earlier estimate

The full load initially landed 865 rows against an expected 1,630. Diagnosed
(single-query breakdown of the 789 excluded rows' NULLs, no Python loops):
all 789 (771 real, 18 demo) were excluded for exactly one reason —
`return_type` was the only null column in every one of them.

**Root cause: live-only schema drift, not a data or transform problem.**
`public.SalesReturn_Fact.return_type` carried a `NOT NULL` constraint that
neither `schema.sql` (line 278, declared nullable by design) nor any
migration (0011 included) ever added — leftover from the table's original
ad-hoc creation, masked forever after by `CREATE TABLE IF NOT EXISTS`
never touching an already-existing table's column constraints.

**Fixed** — migration `0015`
(`analytics/db/migrations/0015_salesreturn_fact_return_type_drift_fix.sql`):
`ALTER TABLE SalesReturn_Fact ALTER COLUMN return_type DROP NOT NULL`.
Applied to `public`, verified via `information_schema.columns`.

**Reloaded `salesreturn_fact` only** (not the full pipeline) after the fix:
**actual = 1,630, exact match against the existing frozen target.** No
target correction was needed — **this corrects an estimate made earlier in
this same session**, which predicted 1,654 (1,900 transform rows − 246
conflicting-group rows) using the conflicting-group count measured *before*
the fix, on the smaller NOT-NULL-filtered set. Once the 789 previously-
excluded rows re-entered the pipeline, they changed which rows collide:
the real post-fix conflicting-group exclusion is 270 rows / 135 groups —
matching the number already on record in migration 0011's own docstring
(2026-09-11) — not 246. `1,900 − 270 = 1,630`, exactly the original
target. The **1,630 target in `FACT_PLAN` (`scripts/run_canonical_load.py`)
was correct all along** and needs no code change either.

### Schema-drift sweep (one query — fresh `schema.sql`+migrations build vs.
`public`'s live `information_schema.columns`, comparing `is_nullable` for
every matching table/column)

Found exactly 2 instances of this drift class, nothing else hiding:

| Table.column | `public` | canonical (`schema.sql`+migrations) | Status |
|---|---|---|---|
| `salesreturn_fact.return_type` | was `NOT NULL` | nullable | **Fixed** — migration 0015 |
| `product_dimension.manual_reorder_point` | exists, nullable | **not declared at all** | **Open** — live-only column, no `schema.sql` entry. Low priority (nothing currently reads/writes it outside ad-hoc use); needs a decision (add to `schema.sql`, or drop if truly unused) before it's closed. |

### Bug tally, final

| # | Bug | Status |
|---|---|---|
| 1 | Desynced identity sequences (9 tables) | Fixed, verified |
| 2 | `Product_Dimension` `UNIQUE` constraint inert on NULL columns | Fixed — migration 0013 |
| 3/4 | `_product_fk_spec("sku")`'s natural key included a column `run_category_brand_backfill()` mutates post-load | Fixed — migration 0014 + narrowed key + `conflict_index_where` |
| 5 | `salesreturn_fact.return_type` live-only `NOT NULL` drift | Fixed — migration 0015 |

### Visible changes (dashboard/backend-facing)

| Change | Before | After |
|---|---|---|
| `salesreturn_fact` | 0 (pre-incident live) | 1,630 |
| `bo_monitoring_view` | 0 | 136 rows |
| `sellout_fact` / `inventory_fact` NaN defects | present (137 + 210 real rows, per §10) | 0 |
| `product_dimension` fake `'False'`-category rows | — | **12 still present** (`product_key` 50186–50201, `category_path_source=NULL`) — pre-existing residue from before the item-40a fix existed; `product_dimension` is never reset by a load, so nothing in this cutover touches already-loaded rows. Open item, not regressed by this work. |
| Backend `/dashboard`, `/recommendations` | — | **Not verified** — `backend/main.py` fails to import locally (`TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'`, a FastAPI/Starlette version mismatch in this dev environment, unrelated to any DB work this phase). Needs checking in an environment with matching dependency versions, or a version pin fix — separate from this phase's scope. |

### Remaining open items

- `product_dimension.manual_reorder_point` — undeclared live-only column (schema-drift sweep above). Needs a decision, not urgent.
- 12 leftover `'False'`-category `product_dimension` rows (pre-existing, item 40a predates them).
- Backend local dev environment can't import `backend/main.py` (FastAPI/Starlette version mismatch) — `/dashboard`/`/recommendations` unverified against the fresh cutover data.
- Item 37 (SOH upsert idempotency) and item 19 (already self-resolved by this cutover) — carried from §10, item 37 still open for a *repeatable* re-run scenario, not blocking.
- `broken_state_20260914/` evidence dump and `ssm_precutover_diag`/`ssm_canonical` scratch schemas can be cleaned up now that the incident is fully closed — not yet done.
- Phase 2 (ABC + D1–D4) can now build on the fresh, fully-loaded, reproducible cutover data.

**Re-verified 2026-09-16 (session resumed after a spend-limit pause):**
state is unchanged from the table below — no writes happened in between.

| Check | Result |
|---|---|
| 6 fact tables (`sales_fact`, `purchase_fact`, `salesreturn_fact`, `sellout_fact`, `inventory_fact`, `unilever_sku_demand_fact`) | Still at the step-2 truncated sample (200/200/42/200/400/200) — **not** the canonical full load, **not** the old pre-incident live data either |
| `product_dimension.category_path`, Unilever SKU-grain rows | 2,098/2,098 populated (0 NULL) — backfill ran to completion in step 2 |
| `product_dimension` duplicate-key groups | 0 |
| Migration 0014 partial index (`product_dimension_unilever_sku_key_idx`) | Present |
| `product_dimension` unique constraint | `UNIQUE NULLS NOT DISTINCT (principal, grain, sku_code, category_path)` — migration 0013 in place |
| Idle-in-transaction sessions on `public` | None (the stray scratch-only connection from last session is gone) |
| Scratch schemas present | `ssm_step3_verify` (empty — the seed attempt never completed), `ssm_precutover_diag`, `ssm_canonical` |
| Git: local vs `group7/kelvin-etl` | Local `e2b2e1a` is 1 commit ahead, clean fast-forward, nothing uncommitted except pre-existing unrelated `tools/forecast_viewer/*` edits and the untracked `broken_state_20260914/` evidence dump — **not pushed yet** |

**Conclusion: cutover has NOT completed.** It partially ran (step 2 of the
verification plan only) and then paused for bug-fixing. Bugs #1–#4 are
fixed in code and applied to `public`'s schema/constraints; the actual
full-volume load has not been re-run since the fixes landed.

### What happened, in order

1. First cutover attempt (approved plan: delete 6 fact tables' rows,
   re-run the loader against `public`, backfill in place) crashed and
   created 1,807 duplicate `Product_Dimension` rows before raising a hard
   `UniqueViolation`. Stopped immediately, no further live writes, reported
   to Yuan without diagnosing against live.
2. Per Yuan's incident instructions: dumped the broken state to
   `broken_state_20260914/` (evidence, outside `backups/`), verified
   `backups/live_backup_20260914T151217Z/` restores cleanly into a scratch
   schema (counts + checksums matched), then restored `public` from it —
   surgically for `Product_Dimension` (deleted only the 1,895 rows not in
   the original backup, left the original 17,536 + everything referencing
   them untouched), fully for the 6 fact tables.
3. Diagnosed two independent root causes, both against `public` inside
   rolled-back transactions before any live write:
   - **Root cause #1 — desynced identity sequences.** All 9 relevant
     tables' sequences were stuck at `last_value=1` regardless of actual
     `max(pk)` (explicit-value inserts during the original ad-hoc load
     never advanced them). **FIXED** — `setval()`'d via
     `pg_get_serial_sequence()` for all 9, verified `nextval() > max(pk)`
     for each.
   - **Root cause #2 — inert `ON CONFLICT`.** `Product_Dimension`'s
     `UNIQUE (principal, grain, sku_code, category_path)` never actually
     enforced uniqueness for either grain's real rows, because standard
     SQL `NULL <> NULL` — `sku_code IS NULL` for every category-grain row,
     `category_path IS NULL` for every fresh Unilever SKU-grain row.
     **FIXED** — migration `0013`, constraint rebuilt as
     `UNIQUE NULLS NOT DISTINCT (...)` (PG17.6 confirmed, PG15+ feature).
     Applied to `public`, verified via `pg_get_constraintdef()`.
4. Re-ran the user's verification sequence. Step 1 (preflight dimension
   identity check) passed. Step 2 (`--limit-rows 200` real run against
   `public`) completed clean, 0 duplicates. Step 3 (re-run the same
   1,807-SKU merge, expect 0 new inserts) **failed** — 1,807 rows were
   still accepted as new.
5. Diagnosed **root cause #3/#4 — a design flaw, not the same bug**:
   `run_category_brand_backfill()` (runs as step 8 of every real load, not
   row-limited) unconditionally mutates every existing Unilever SKU-grain
   row's `category_path` from `NULL` to a real value (confirmed: step 2's
   run already flipped all 2,098 existing Unilever SKU rows to non-NULL).
   But `_product_fk_spec("sku")` hardcoded `category_path=None` as part of
   its matching key for every resolution attempt — so after the backfill
   has run once, that key can never match an existing row again, and every
   later resolution (re-running the loader, a future incremental load)
   silently re-inserts it as "new". This is why step 3 failed even with
   root causes #1 and #2 fixed — a real fourth bug, distinct from both.
6. Swept the same class codebase-wide (only 4 `DimensionFKSpec`s exist,
   all in `scripts/run_canonical_load.py`) — this is the only natural key
   with a member mutated post-load. Customer/salesman specs are clean; the
   Del Monte category-grain product spec is clean (its `category_path` is
   set once at insert time and never touched again).
7. **Fixed**, per Yuan's direction (option b — drop the mutable column
   from the key rather than re-look-up the current value):
   - `_product_fk_spec("sku")` narrowed to
     `dimension_natural_key=["principal", "grain", "sku_code"]` —
     scoped to this ONE `FactPlanItem`
     (`sales_unilever_sku_demand`/`unilever`), the only caller.
   - **Checked before applying** (this mattered): Del Monte also has
     `grain='sku'` rows in `Product_Dimension` (15,339 of them, loaded
     pre-canonical-load era, outside this codepath) — and 252 Del Monte
     `sku_code`s legitimately span multiple `category_path` values. A
     3-column key would be actively wrong if ever reused for Del Monte.
     Confirmed `_product_fk_spec("sku")` is Unilever-only via `FACT_PLAN`,
     so this is safe as scoped.
   - New migration `0014`: partial unique index
     `product_dimension_unilever_sku_key_idx` on
     `(principal, grain, sku_code)` `WHERE principal='unilever' AND grain='sku'`
     — **applied to `public`, verified via `pg_indexes`.**
   - `DimensionFKSpec` gained a `conflict_index_where` field
     (`analytics/etl/load.py`) so `resolve_dimension_fk()`'s
     `ON CONFLICT` can infer a partial index, not just a table-wide one.
   - `schema.sql` and its `Product_Dimension` comment updated to match
     (including correcting a previously-wrong comment that claimed
     `category_path IS NULL` for every SKU-grain row table-wide — false
     for Del Monte, true only for Unilever).
8. **Re-verification of step 3 was IN PROGRESS, not completed**, when this
   session paused. Built a full scratch-schema copy (`ssm_step3_verify`,
   built from `schema.sql` + all migrations incl. 0014) to safely re-run
   the real (committing) `resolve_dimension_fk()` path against a seeded
   copy of `public`'s current `Product_Dimension` without touching live —
   the seed insert kept failing on scaffolding issues (a stray
   `manual_reorder_point` column live has that `schema.sql` doesn't, an
   identity-column override, background-command wiring) and was not yet
   completed successfully. **No conclusion reached** on whether the fix
   actually produces 0 new inserts on re-test — code is fixed and applied
   to `public`, but not yet re-proven.

### Exact state of `public` right now (verified 2026-09-15, end of session)

Everything below is real, checked directly, not inferred:

| Table | Current `public` state | Backup target (`live_backup_20260914T151217Z`) |
|---|---|---|
| `product_dimension` | **17,602** rows, **0 duplicate-key groups**, all 2,098 Unilever SKU rows have non-NULL `category_path` (backfilled) | 17,536 (before the +66 legit new rows from step 2's 200-row sample) |
| `customer_dimension` | 23,712 — unchanged | 23,712 (matches exactly) |
| `salesman_dimension` | 33 — unchanged | 33 (matches exactly) |
| `supplier_dimension` | untouched | untouched |
| `sales_fact` | **200** (truncated sample, step 2) | 53,320 |
| `purchase_fact` | **200** (truncated sample, step 2) | 2,110 |
| `salesreturn_fact` | **42** (truncated sample, step 2) | 0 |
| `sellout_fact` | **200** (truncated sample, step 2) | 8,368 |
| `inventory_fact` | **400** (truncated sample, step 2) | 349,860 |
| `unilever_sku_demand_fact` | **200** (truncated sample, step 2) | 44,575 |
| `abc_classification`, `forecast_result`, `lp_recommendation` | untouched | untouched |

Sequences: all 9 relevant identity sequences fixed/synced (root cause #1).
Migration `0013` (NULLS NOT DISTINCT) applied. Migration `0014` (partial
Unilever-sku index) applied.

**Confirmed consistent, end of session:** no open/idle-in-transaction
session touching any `public` table; `product_dimension` duplicate check
= 0; the 6 fact tables' row counts above are stable, deliberate,
intermediate values from step 2's `--limit-rows 200` run, not partial
writes. One stray leaked connection (pid 3205147, `idle in transaction`)
is sitting against the **scratch** schema `ssm_step3_verify` only (from a
failed local seeding attempt) — does not touch `public`, holds no lock any
`public` operation needs, safe to ignore or let Postgres reap; an attempt
to terminate it was blocked by this session's own auto-mode tool
classifier, not a data-safety concern.

### Bug tally

| # | Bug | Status |
|---|---|---|
| 1 | Desynced identity sequences (9 tables) | **Fixed**, applied to `public`, verified |
| 2 | `Product_Dimension` `UNIQUE` constraint inert on NULL columns | **Fixed** — migration 0013, applied to `public`, verified |
| 3/4 | `_product_fk_spec("sku")`'s natural key includes `category_path`, which `run_category_brand_backfill()` mutates post-load — stale-key false "new" inserts | **Code fixed** (migration 0014 + `conflict_index_where` + narrowed key) and applied to `public` — **re-verification not yet completed** |

### Next action (when resumed)

1. Finish the scratch-schema re-verification of step 3 (`ssm_step3_verify`
   — currently empty/abandoned, safe to drop and redo, or redo from
   scratch): seed `product_dimension` from `public`'s current state
   (exclude `manual_reorder_point` — it's a live-only column `schema.sql`
   doesn't define, a separate small drift worth a one-line fix later),
   then run `resolve_dimension_fk()` for real against it with the full
   Unilever SKU population and confirm **0 rows treated as new**.
2. Only after that passes: re-run step 3 for real against `public` itself
   (still just the merge/resolve step, not a full load) to close out the
   user's original stop condition, per "Stop and report after step 3 if
   the duplicate count isn't exactly zero."
3. Only after step 3 passes cleanly: step 4 — full, non-limited load
   against `public`, all 7 tables checked against the backup's target
   counts (this restores the 6 fact tables from their current truncated
   200-row sample state to full volume).
4. Then the original cutover plan's deferred steps 3–4 (post-cutover
   verification, flag visible changes) still need to happen.
5. `ssm_step3_verify` scratch schema and `broken_state_20260914/` evidence
   dump can be cleaned up once the incident is fully closed and folded
   into this report — not yet, kept for now.

## 12. Column-gap audit — CLOSED (2026-09-17/18); scratch cleanup DONE (2026-09-18)

`ssm_precutover_diag`, `ssm_col_gap_audit`, `ssm_canonical`,
`ssm_sku_brand_fix`, `ssm_binning_phase2` dropped after verified public
apply — DB 548MB → 140MB. **Correction (2026-09-18 verification):
`ssm_abc_phase2` was NOT dropped** — it still exists (64MB, 4 tables)
and still holds `abc_classification_backup_20260917`, the
pre-migration-0017 backup, intact.

Commits `cccd038` (Del Monte product_dimension dedup + inventory
product_key fix), `196e01d` (Unilever SOH `unit_cost_per_case`/
`stock_status` mapping fix). Pushed to `group7/kelvin-etl`,
`e2710c4..c8a6c4c`. Full findings, per-column classification, and
evidence: `reports/COLUMN_GAP_AUDIT_2026-09.md`.

## 13. ABC Phase 2 — CLOSED (2026-09-18)

Commit `d3eb3ec`. Tier A as of 2026-02: **132 single-period**, **143
trailing-3-month**, **119 overlap** between the two bases.

## 14. Open items carried forward (logged only, not worked)

1. Demo DM inventory now references legacy synthetic DM product rows —
   don't delete those rows unless the demo rows go too.
2. Del Monte has no SKU-level sales source (sell-out is category-grain
   only; sales register/return carry no SKU column) — adviser ruling
   needed on the ABC basis for Del Monte.
3. Verify `transform_ssis_soh`'s `unit_cost_per_case`/`stock_status`
   output (commit `196e01d`) matches `public`'s existing values — not yet
   diffed.
4. ~~Pre-existing `tests/forecasting/test_sarima.py` collection error~~
   — **CLOSED 2026-09-18**: now passes 6/6. `tests/backend/*` collection
   errors (FastAPI/Starlette version mismatch) remain, pre-existing,
   unrelated to this work.
5. Duplicate migration `0002` (`0002_add_boundary_flag.sql` and
   `0002_add_sku_management_fields.sql`) — cosmetic, not yet resolved.
6. `net_amount` is gross, not net of returns — a manuscript limitation,
   not a pipeline defect.
7. `tools/forecast_viewer/*` has uncommitted changes from 2026-09-16,
   owner unknown, unrelated to Phase 1–2 work.
8. `CLAUDE.md`'s data-interface rule cites `schema.sql:698-714` for the
   `_Real` views. Stale: the six `CREATE OR REPLACE VIEW … _Real` statements
   are at `analytics/db/schema.sql:832-848` (and the file is at
   `analytics/db/schema.sql`, not the repo root). Found 2026-09-23 while
   sourcing the dev viewer's `_Real` node. **Logged only, not fixed** — the
   rule itself is unchanged and correct.
9. §16's `sell_out` relabel arithmetic does not close: 8,584 combined in,
   1,023 removed, 124 added is 7,685, but the report states — and measured —
   7,686, and 7,686 − 26 = 7,660 matches the frozen target. One row is
   unexplained in the write-up, not in the data (the loaded count is right
   either way). Found 2026-09-23. **Logged only, not fixed** — needs someone
   to re-derive the relabel counts, not a number changed in the report.

## 15. SKU Management / ABC page recon — 2026-09-18 (Audrey)

Brand dropdown junk + missing ABC categories traced. See DEC-24
(`ARCHITECTURE.md`) for the negative-revenue-exclusion ruling. ABC
negative-revenue exclusion: SKUs whose only 2026-02 activity was returns
(negative revenue, no gross sales) are excluded from ABC as
inactive-for-period, not assigned Tier C. 69 SKUs in 2026-02. No run log
survives in the repo to confirm those 69 were actually printed in
`orchestrate_abc.py`'s `excluded_negative_revenue` (330-331) on the last
live run — can't verify the report vs. silent drop either way; re-run
without `--quiet` and archive the log next time.

Brand/category fixes (product_key 50186 'False' row, Del Monte's 99
fake "brands", alias-table reapply without `COALESCE`, SOH mojibake
normalization) — applied to `public` and verified 2026-09-18. See chat
log 2026-09-18 for the full recon tables.

Audrey's original "12 'False' rows" claim — **CLOSED**: actual live
count was 1 (product_key 50186), deleted 2026-09-18, verified 0
remaining.

### Open items carried forward (this section)
~~7. `abc.py:94`, `dashboard.py:438,457-458` MAX(classification_period)
without a `method` filter~~ — **CLOSED 2026-09-18**: verified all
`MAX(classification_period)` lookups (`abc.py:114`,
`dashboard.py:595,619-620`) now filter `method = 'single'`, fixed
upstream before this check.

## 16. `ssis_summary` — CLOSED as deliberately demoted (2026-09-19)

Recurring audit noise, settled here so it stops being re-raised as an
orphaned-data finding.

`staging/ssis_summary/` holds **805 parquet files / 1,949,687 rows** and
reaches **no fact table**. This is correct and intentional, not a gap.
All 805 sheets are classified `demoted` by `transform_driver.py`, with
the reason string the manifest emits verbatim:

> `doc_type='ssis_summary' is never a fact's primary source (cross-check
> only, if referenced at all)`

Measured from `transform/_manifest.json` (2026-09-14 run): 805 of 805
sheets demoted, 0 promoted, 0 conflict, 0 blocked.

This follows the Phase 1 removal of `source_of_truth.yaml`'s
`sales.unilever` entry as a dead mapping (2026-09-09, §8) — with no
owning fact, the family has nothing to be promoted into. It is consistent
with the family's known grain problem: 95.6% of rows are product-less
outlet×day×invoice sales value, so there is no SKU grain to load.

**Disposition:** extraction stays on (auditability — `extract/driver.py`
keeps it as the 7th family per DEC-04). Demotion stays. Do not treat the
1.95M staged rows as an unloaded backlog.

Re-opening this requires a grain decision first, not a loader.

## 17. Real-row recovery + Yuan's 2026-09-22 rulings — scratch rebuilt, cutover rehearsed, NOT applied to public

Source of truth for this phase's working detail: the Phase E handoff (2026-09-21/22). Scratch `ssm_synth_v2` = ONE canonical rebuild, 2026-09-22 20:09→20:39 (29 min 55 s). Loader exit 1 = frozen-v1-target MISMATCH banners only.

| Ruling / fix | What changed | Count (verified, scratch vs public E3) |
|---|---|---|
| L1 | Unilever demand `net_amount_inc_tax` → `net_amount` | real demand rows identical to public |
| F3 | sheet "ILO 090223" is Ilocos (region pattern) | +193 inventory rows, 6 re-tagged |
| F4 | ONE PAGER-only invoices kept | +57 sales, 559,369.32 |
| H1 | FAKE BOOKING invoices on "PANGASINAN SALES REGISTER (2)" quarantined; F5 exempt for that sheet | −14 sales, 2,903,959.74; other 564 stay 2025-04, **pending SSM** |
| D12 | 18 Sept-2025 purchases (stale Tax/Net cells) quarantined, "Net Amount ( Actual Invoice)" kept in raw_values | 0 inserted; 14 real 2024-01 rows failing untaxed+tax=net CLOSED as rounding (max 0.50) |
| X2 | sell-out "Total With Tax" → net_amount, `net_amount_tax_inclusive` (0027) | 122 amounts (120 NULL + 2 merged 0.00); flag 122 TRUE / 5,876 FALSE / 0 NULL |
| X3 / X4 | "Total CAS"/"Total PCS" → `quantity_cases`/`quantity_pieces` (0027); `bo_units` stays NULL | sales 1,888; returns 227 (62 BO) |
| X1 / D11 | SOH pack_size on SOH-only SKUs; brand_source 'demand_first_token_rule' (0026) | pack 291 (0 overwritten); brand_source 380; brand 1 (BF→BESTFOODS) |
| sum fix | defect-category merge: all-missing group → NULL, not 0 | 114 `quantity_cases` (not a loaded column) |
| name fix | demand product names get the SOH apostrophe normalization | 2 LADY'S CHOICE names |
| X5 | DROPPED — PKG is pieces-per-case only in 2023-09/2024-02 (809/2,739 rows) | → product master cleanup (price-list case pack; PKG cross-check only) |
| X6 | SOH "Hierarchy Node" not extracted: no destination, no consumer, meaning UNVERIFIED | — |
| P2 | loader failure path keeps the scratch schema | — |

Cutover: `scripts/apply_real_recovery_to_public.py` rehearsed on a copy of public (`ssm_recovery_rehearsal`): 42/42 checks; real-row diff before = E3, after = 0 on all six facts; synthetic rows, other products, forecast_result, sku_segment, sku_traits, ABC (per method) unchanged; 1 customer row added for F4.

Provenance / open items (logged, not worked):
| Item | Status |
|---|---|
| P3 | public Unilever demand `net_amount` has no committed writer |
| 38 Unilever SKUs labelled SOH-sourced in public | no source in loaded SOH (2023+); 14 trace to unloaded 2021-22 SOH sheets (existence-only, D5); 24 not found in staged SOH, not searched further; brand values unchanged, only brand_source changes |
| 5 Del Monte category product_name values in public | writer UNVERIFIED |
| `product_dimension.manual_reorder_point` | public only, 0/17,406 populated, no migration, no code — **ask Audrey** |
| Product master cleanup queue | DM pack size from the price list; 2021-22 SOH for product details only (never quantities) |

### 17.1 Connection route for the recovery cutover — documented deviation (2026-09-23)

The standing rule is "direct URL, port 5432, never the pooler on 6543". Measured from Yuan's machine on
2026-09-23, the direct URL is not usable at all:

| route | host | DNS | connects | mode |
|---|---|---|---|---|
| direct 5432 | `db.dsdxemtmbbmdtccwxzyk.supabase.co` | AAAA only, **no A record** | **no** — `getaddrinfo failed` | session |
| session pooler 5432 | `aws-0-ap-south-1.pooler.supabase.com` | IPv4 | yes | session |
| transaction pooler 6543 | `aws-0-ap-south-1.pooler.supabase.com` | IPv4 | yes | transaction |

The machine has no global IPv6 address and no route to the direct host's AAAA address, so the direct URL fails at
name resolution before any connection is attempted. **Decision: run the recovery cutover over the SESSION pooler on
5432.** It preserves everything the "never 6543" rule exists to protect — one long-lived transaction per batch,
session GUCs, `CREATE TEMP TABLE ... ON COMMIT DROP` (used by `restore_from`), and `COPY ... TO STDOUT` (used by
every backup). Transaction mode on 6543 preserves none of them reliably and is still excluded.

Accepted trade-off: the pooled hop can drop mid-statement — it did twice on 2026-09-23, both times during a
~6-minute `COPY` while the link was degraded (~60 KB/s; the same backup later ran in 43 s). Batch mode is the
mitigation: a dropped connection costs one batch, not the run, and the ledger makes the resume exact.

Two pooler behaviours found and handled, both in `scripts/apply_real_recovery_to_public.py`:

1. Supavisor **drops the libpq startup `options`**, so `connect()`'s `statement_timeout=0` never arrived and the
   session kept the database default of `2min`. This killed migration 0027 mid-batch. Verified: startup options
   reported `2min` on both pooler ports; an explicit `SET` reported `0`. A local `connect()` wrapper now issues
   `SET statement_timeout = 0`, `SET idle_in_transaction_session_timeout = 0` and `SET lock_timeout = '30s'` on
   every session instead of trusting the handshake. This is correct on the direct connection too.
2. A whole-database `pg_total_relation_size()` scan ran for **18 minutes without completing** and had to be
   killed. It was not slow — it was **blocked**, and the pile-up is the real lesson. When the pooled client
   connection died mid-`COPY`, the *server* session survived as `idle in transaction` holding `AccessShareLock` on
   `ssm_recovery_oneshot.sales_fact` (pid 4000995, 50 min). Migration 0027's `ALTER TABLE Sales_Fact ADD COLUMN`
   from the next run then queued for `AccessExclusiveLock` behind it (pid 4001068, 42 min), and the size scan
   queued behind *that* (pid 4002426, 28 min) — and a later `DROP SCHEMA` behind all three. Three
   `pg_terminate_backend` calls cleared all 80 locks at once.
   Two rules from this: after any failed pooled run, **check `pg_stat_activity` for an orphaned `idle in
   transaction` backend before starting the next one** — the client exiting does not end the server session; and
   read schema sizes from `pg_class.relpages` (sub-second, lock-free), only at the start and end of a run, never
   mid-cutover. `connect()` now also sets `lock_timeout = '30s'`, so a blocked statement fails fast and names its
   blocker instead of hanging.

Scratch cleanup the same day: dropped `ssm_recovery_rehearsal`, `ssm_recovery_original`, `ssm_abc_phase2`,
`ssm_abc_repro`. Database went 417.2 MB -> 200.5 MB (relpages basis) against the 500 MB cap. Each `DROP SCHEMA
CASCADE` took under a second; the earlier 18-minute hang was the size query, not the drops.

### 17.2 COMPLETE — recovery cutover to `public` is fully applied (2026-09-23)

**All 12 batches are applied to `public` and committed. 42/42 checks passed.** The ledger, not this file, is the
source of truth. Nothing is left to resume; the next action on this run would be an undo, not a continuation.

| item | value |
|---|---|
| run id / ledger | `real_recovery_20260923T022354Z`, in `public.etl_cutover_ledger` |
| backup | `backups/real_recovery_20260923T022354Z/` — 9 tables + `etl_quarantine` recorded absent, **10/10 manifest md5 verified**, identity sequences captured |
| ledger rows | batch 0 `baseline`; 1 `done` 4/4, 2 `done` 14/14, 3 `done` 18/18, 4 `done` 7,773/7,773, 5 `done` 57/57, 6 `done` 1,888/1,888, 7 `done` 227/227, 8 `done` 122/122, 9 `done` 199/199, 10 `done` 291/291, 11 `done` 381/381, 12 `done` (reads only, 22 checks) |
| applied | migrations 0024–0027, all four recorded against `public`: `etl_quarantine` created, `sales_fact.quantity_cases/quantity_pieces`, `sellout_fact.net_amount_tax_inclusive`, purchase unique key rebuilt to include `invoice_date` |
| sales restated | real `sales_fact` **17,933 rows / ₱208,794,370.90** — batch 2 removed the 14 FAKE BOOKING invoices (−₱2,903,959.74). Every live figure quoted before 2026-09-23 sits on the old ₱211,698,330.64 basis. |
| quarantine | `public.etl_quarantine` **7,805 rows** = 14 (b2) + 18 (b3) + 7,773 (b4); batch 4's F1 check passed against the source's full real set |
| unchanged after batch 4 | `inventory_fact` 32,446, `unilever_sku_demand_fact` 24,906, `product_dimension` 17,406, real `purchase_fact` 499 |
| remaining | none |

Nothing to resume. `--status` prints the ledger. To undo:

    python -m scripts.apply_real_recovery_to_public --rollback backups/real_recovery_20260923T022354Z --i-have-approval
    python -m scripts.apply_real_recovery_to_public --restore  backups/real_recovery_20260923T022354Z --i-have-approval

`--rollback` walks the change log; `--restore` puts every backed-up table back row for row. Both re-hash against
the backup's md5, reset the identity sequences and clear this run's ledger rows.

**Final figures on `public` after batch 12** — real rows unless noted:

| table | before the cutover | after | what moved |
|---|---|---|---|
| `sales_fact` | 17,947 / ₱211,698,330.64 | **17,990 / ₱209,353,740.22** | −14 FAKE BOOKING (−₱2,903,959.74), +57 ONE PAGER (+₱559,369.32); 1,888 rows given `quantity_cases`/`quantity_pieces` |
| `inventory_fact` | 32,446 | **32,639** | +193 Ilocos stock lines, 6 region re-tags (`ILO 090223`) |
| `etl_quarantine` | absent → 0 | **7,805** | 14 + 18 + 7,773 |
| `salesreturn_fact` | — | 227 rows given quantities | `bo_units` still NULL |
| `sellout_fact` | — | 122 `net_amount` set | 122 TRUE / 1,245 FALSE on `net_amount_tax_inclusive` |
| `product_dimension` | 17,406 | **17,406** | Unilever SKU only: 291 `pack_size`, 380 `brand_source`, 1 `brand`; 0 rows added |
| `purchase_fact` | 499 | **499** | the 18 Sept-2025 lines were quarantined, not inserted (D12) |
| `unilever_sku_demand_fact` | 24,906 | **24,906** | unchanged |
| `forecast_result` / `sku_segment` / `sku_traits` | 132 / 792 / 132 | unchanged | md5 identical |
| `abc_classification` | 23,896 `single` + 25,437 other | unchanged | fingerprinted per method, never as one union |

Batch 12 also confirmed **0 differences in both directions** between the real rows of all six fact tables and the
scratch build, on every column including the new ones, and that the synthetic rows of every fact table are
byte-identical to their pre-migration fingerprints.

Per-schema size after the run: `public` 97 MB, `ssm_synth_v2` 86 MB (`pg_total_relation_size` summed per schema —
the whole-DB scan is the query that hung for 18 minutes on 2026-09-23, do not run it).

**DONE 2026-09-23 — batch 2 ran with Yuan's explicit go.** Batch 2 deleted the 14 FAKE BOOKING invoices from
`sales_fact` and moved them to `etl_quarantine`: **−₱2,903,959.74**, taking real sales from ₱211,698,330.64 to
₱208,794,370.90 (verified on `public` after the commit). It is the **first batch that changed any reported sales
total**, and every figure already quoted from the live DB — manuscript, dashboard screenshots, defense slides —
is now on the old basis. Nobody should re-run a number across that boundary without knowing which side of it
they are on.

Note on numbering: in Yuan's original ten-item list the 57 ONE PAGER invoices were "batch 4"; in the implemented
twelve-batch list they are **batch 5**, and batch 4 is the 7,773-row quarantine remainder. Batches 3 and 4 are
quarantine-only and change no fact-table total, but **they cannot run before batch 2** — corrected 2026-09-23,
an earlier note here claimed they could. Two independent reasons, both in the implemented script:
`apply_real_recovery_to_public.py:880-882` refuses any batch whose predecessors are not `done` (on `--batch N` as
well as `--from N`), and batch 4's F1 check (`:558-559`) compares `public.etl_quarantine` against the source's
**full** real quarantine set of 7,805 rows — without batch 2's 14 rows it sees 7,791 and rolls batch 4 back.
Batch order is strict: 2 → 3 → 4.

Pre-run hygiene that must be repeated before each resume: check `pg_stat_activity` for an orphaned
`idle in transaction` backend and terminate it (see 17.1) — a dead pooled client leaves its server session, and
its locks, behind.

### 17.3 Product master cleanup queue — QUEUED, do not act now (2026-09-23)

Recon only; nothing below has been applied. Evidence: `reports/diagnostics/` (fit review, incident check) and
the exhaustive staged-file scan described in step 3.

**Finding.** `product_dimension` has **7 Del Monte rows whose `sku_code` is a source section heading**, not a
code: `CONTADINA`, `KIKKOMAN`, `MR. MILK YOGHURT`, `NEW PRODUCTS`, `PROMO PACK`, `QUICK N EASY`, `VINA MILK`
(product_keys 18554, 18540, 18560, 18583, 18576, 18526, 18565). All 7 come from one workbook —
`data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx`,
`_period` 2023-08, header row 7 — staged as two sheets, `ACTUAL 090423` (205 rows) and `ILO 090223` (206 rows),
each carrying all 7 banners at identical row ordinals (110, 124, 138, 144, 149, 160, 167) = **14 source rows**.
Raw shape is uniform: `ITEM CODE` = the brand name, `ITEM DESCRIPTION` NULL, every price/quantity column NULL or
0, and the row immediately below begins that brand's product block (ordinal 124 `KIKKOMAN` → ordinal 125
`11858 KIKKOMAN FANCY GRD SOY SAUCE 12/600ML`).

**Zero facts attach.** Checked by `product_key` across `inventory_fact`, `sellout_fact`, `sku_segment`,
`abc_classification`, `forecast_result`, `sku_traits`, `unilever_sku_demand_fact`, `unilever_inventory_monthly`,
and again by `sku_code` across every table that has one: **0 rows everywhere** except the 7 dimension rows
themselves. **No fact reassignment is required** — this is a dimension-only cleanup with no restatement.

**Confinement verified, not assumed.** An exhaustive scan of every staged parquet across all 10 families
(`inventory_sign_off`, `sell_out`, `sales_register`, `sales_return`, `purchase_order`, `rmr_gs_bo`, `ssis_soh`,
`ssis_soh_inventory_fact`, `ssis_summary`, `unilever_sku`) finds those 7 strings **only** in the two August 2023
sign-off sheets — 7 labels × 2 sheets = 14 rows, nothing anywhere else.

#### The queue

| # | action | detail |
|---|---|---|
| 1 | **Quarantine the 7 dimension rows** | rule `banner_row_no_item_description`; record all **14** source rows in `raw_values` with `_src_file`/`_src_sheet`/`_row_ordinal`. 0 facts attach, no reassignment. Delete is wrong (destroys the evidence); correct-from-source is wrong (a banner has no code to correct *to* — inventing one is fabrication). |
| 2 | **Then add the `sku_code` format CHECKs** | Unilever **strictly** `^[0-9]{8}$` — 2,098 of 2,098 pass, 0 rejects, the format is uniform. Del Monte **deliberately loose**: reject only what is clearly not a code — contains whitespace, **or** contains no digit at all. A tight pattern fitted to today's observed shapes (`9AAA99999`, `AAA99999`, `999`–`99999`, `AAAA9999`, `9AAA9999`) would fail a rebuild the first time Del Monte issues a genuinely new code family. **This, not a template rule, is the durable guard.** Must run **after** item 1 or the constraint will not create. |
| 3 | **Note only — do not build** | A Transform banner rule for the sign-off template (`ITEM CODE` has no digit **AND** `ITEM DESCRIPTION` is NULL) would catch this class at load time. **One occurrence in 52 staged files does not justify building it.** Revisit only if the pattern recurs in a later delivery. |
| 4 | **Provenance gap — list with the others** | The 7 rows carry `product_name` values that **cannot** come from their source rows, because `ITEM DESCRIPTION` is NULL there — e.g. `KIKKOMAN` → "Del Monte Tomato Paste 240ml", `PROMO PACK` → "Del Monte Mango Juice 1kg". Some later backfill wrote them and the values look unrelated to the banner. Same class as **P3** (public Unilever demand `net_amount` has no committed writer) and the **38 Unilever SKUs labelled SOH-sourced in public** with no source in loaded SOH — all three are values in `public` with no identifiable writer. Trace them together, not one at a time. |

**Item 1 closed without action (2026-09-29).** The 14 banner source rows are already in `public.etl_quarantine` (keys 7553–7566, rule `exclude_footer_rows[inventory_sign_off]`) and the loader's Transform drops all 14 before any SKU is built; the 7 banner products (18526, 18540, 18554, 18560, 18565, 18576, 18583) were removed by the synth v2 cutover's batch 7 on 2026-09-28 as unreferenced Del Monte SKU rows (kept in that batch's backup CSV). No `banner_row_no_item_description` records are written.

**State note (2026-09-23).** `public.etl_quarantine` **now exists and is empty** (0 rows) — batch 1 of the
recovery cutover created it (§17.2, migrations 0024–0027). Item 1 is therefore no longer blocked on that
migration. Earlier notes in `reports/diagnostics/README.md` and `WHY_SOME_SKUS_ARE_UNFIT.md` state that
`etl_quarantine` is absent from `public`; that was true when written, earlier the same day, and is now stale —
those two files need the line corrected.

**Correction (2026-09-23, recon session).** Three lines in this section need fixing, all verified read-only
against `public` over the session pooler on 5432:

- The **"56 numeric codes with exactly one prefixed match"** rule **does not reproduce**. The count 56 is real
  but it is only `203 numeric codes − 147 rows in reports/dm_code_review_2026-09-21.csv`; it is not a
  match-count result. Matching a numeric code to prefixed codes by trailing digits gives, within those 56:
  **44 with one candidate, 10 with two, 2 with three** — and **19 of the 147 review rows also have exactly
  one**. Whatever rule produced the split was not written down, so "exactly one prefixed match" is a
  **reconstruction, not a recorded definition**. Treat the 56 as an unexplained residual until the rule is
  restated.
- The **"14 SKUs with 2021-22 SOH but no 2023+ SOH row"** figure is **126**, not 14, under the only definition
  that can be reconstructed: `unilever_inventory_monthly` holds 2023-01…2026-03 for 1,718 SKUs, so all 2021-22
  SOH is staged-only (102 staged `ssis_summary` SOH sheets; 2021-22 = 1,402 distinct 8-digit articles); of
  those, 126 exist in `product_dimension` with no 2023+ SOH row. Also a **reconstruction** — the original
  definition is not on record. Those sheets can supply `Article Description` (name), `CATEGORY DESC`
  (category) and `PACK SIZE`; **brand is not a column** and would still come from the first-token rule
  (migration 0026). All 126 currently sit at `category_path = 'UNCLASSIFIED'`.
- The State note above says `public.etl_quarantine` holds **0 rows**. That was true after batch 1; batches 2–4
  have since landed and it holds **7,805** (§17.2).

## 18. DEC-31 data fills — BUILT on `feat/data-fills`, rehearsed in `ssm_fills`, LIVE on `public` since 2026-10-02 (§18.4)

Yuan's decision 2026-10-02 (overrides DEC-29's "never fill"): fill every missing dataset for both principals, permanently, as one step
after every load; real data always replaces a fill. Rule and details: ARCHITECTURE.md DEC-31. Code: `scripts/fill_missing.py`, hooks in
`scripts/load_slices.py` (end of every non-dry-run load; `--no-fill` to skip) and `scripts/build_synthetic_v2_clean_pool.py` (after `--write`),
migration `0038_data_fills.sql`, rehearsal `scripts/rehearse_fills.py`.

### 18.1 Rows the fill step wrote in the rehearsal (scratch `ssm_fills` = copy of public 2026-10-02, window 2021-01..2026-09)

| fill | where | months | rows |
|---|---|---|---|
| 1 `derived_stock_balance` | `derived_receipt_fact` (Unilever) | 2023-02..2026-02 (37) | 23,100 (5,392 flagged `negative_balance`; 26 SKU-months skipped: NULL `quantity_sold`) |
| 2 `synthetic_rate_transfer` | `salesreturn_fact` (Unilever, is_demo) | 2021-01..2026-08 (68) | 68 (20 own Del Monte rate, 48 nearest month-of-year) |
| 3 `synthetic_category_split` | `sku_demand_fill` (Del Monte, is_demo) | 17 real sell-out months | 3,130 (374 SKUs; 20 SKUs excluded: average stock value <= 0); principal level 17/17 |
| 4 `synthetic_v2_gap` | Del Monte `salesreturn_fact` | 19 DEC-29 months + 2026-09 | 1,667 |
| | Del Monte `purchase_fact` | 2025-09, 2026-09 | 68 |
| | Del Monte `sales_fact` / `sellout_fact` / `inventory_fact` | 2026-09 | 954 / 8 / 303 |
| | Unilever `inventory_fact` | 2026-04..09 | 3,603 |
| — | `etl_load_event` (source `fill_missing`) | | 153 cells |

Second run: 0 rows, 0 events, 0 coverage rows (idempotent). Coverage after: Unilever purchases 37 derived / 33 missing; Unilever returns 68
synthetic / 2 missing; Del Monte product sales 17 synthetic / 53 missing; Unilever demand 2026-09 missing (D4: no DB generator).

### 18.2 Guardrails (all pass)

| check | result |
|---|---|
| `rehearse_fills --verify` (scratch vs public, public read-only): `_Real` view definitions, real rows (count + md5) of all 6 fact tables, no demo row in any `_Real` view, every demo row tagged / no real row tagged, no demo row in a real cell, public's demo rows unchanged, `forecast_result` / `abc_classification` / `lp_recommendation` / `sku_traits` / `sku_segment` identical, split totals, derived identity, NaN | 63/63 |
| `tests/etl/test_fills_db.py` on `ssm_fills` (each test rolled back): idempotence; real rows replace a fill (loader predicate + `remove_derived`) and the cell is never refilled; sweep; a once-real cell stays empty; a new real sales month gives new derived receipts; split totals = real totals (17 months, shares sum to 1); `assert_real_rows` on all 6 `_Real` views; the estimated series reads only the derived table | 8/8 |
| `tests/etl/test_fills.py` (no DB) | 16/16 |

### 18.3 Data flags found while building

- **Del Monte stock 2025-03 = 2025-04**, row for row (292 rows, 0 differences in SKU, site, quantities, valuation) although they come from two
  workbooks (`2025 MARCH INVENTORY.xlsx`, `2025 APRIL INVENTORY.xlsx`). Possible duplicate snapshot in SSM's files — ask SSM. It double-weights
  that snapshot in item 3's stock shares.
- **Unilever derived receipts swing in high/low pairs** (2024-07 2.36x sales then 2024-08 0.56x; 2026-01 0.57x then 2026-02 2.20x). The SOH is
  dated the 1st-6th of the next month, so a delivery can land on the other side of a snapshot (UNVERIFIED cause). Not smoothed.
- Both earlier `reports/unilever_derived_receipts*` files were wrong: v1 used only the loose-piece remainder (received = sold every month within
  0.1%), the untracked v2 dropped the remainder. No producer script for either was in the repo; `fill_missing.py` replaces them.
- Del Monte purchases 2025-09 is now synthetic next to its 18 real lines held in `etl_quarantine` (D12).

### 18.4 Applied to `public` (2026-10-02 / 2026-10-03)

Order: 0032 -> 0033 -> 0036 -> 0037 -> 0038 (`python -m scripts.run_canonical_load --schema public --target-public --schema-only`), then
`--refresh-coverage`, then `python -m scripts.fill_missing --schema public --target-public --dry-run`, then without `--dry-run`.

| step | when (UTC) | result (source) |
|---|---|---|
| Backup | 2026-10-02 16:01 | `backups/full_backup_20261002T160122Z` (gitignored): `public` 24 tables / 255,748 rows + `ssm_fills`; every file re-opened 2026-10-03 and matches its manifest's row counts and checksums |
| 0032, 0033, 0036, 0037, 0038 | 2026-10-02 16:06–16:08 | `public.schema_migrations`, applied_by kyuan; Audrey's `0035_user_two_factor.sql` was already there (13:10) |
| `--refresh-coverage` | 2026-10-02 16:09 | `etl_coverage.refreshed_at` |
| fill step | 2026-10-02 16:10 | run `fill-20261002T161030Z-5a18377c`: 153 cells, 32,901 rows = exactly the 18.1 counts (`etl_load_event`, `audit_log`); 0038 tagged 89,304 existing demo rows `synthetic_v2` |
| fill dry rerun | 2026-10-03 | 0 added, 0 removed, 0 gap cells (idempotent) |
| 2026-02 segmentation recompute | 2026-10-03 | Tier A as of 2026-02, method single: run `segment_unilever_2026-02_2d2dd97c` (132 traits, 660 segment rows; `length_v1` untouched). Exactly the 8 products with a negative month changed `cv` (19, 174, 345, 644, 666, 674, 832, 1037); 644 and 1037 also `trend_pvalue` (0.0098 -> 0.0119, 0.0092 -> 0.0112), still under alpha 0.05, so no bin moved. Pre-write rows: `backups/segmentation_2026-02_pre_recompute_20261003T063026Z/` |
| scratch | 2026-10-03 | `ssm_fills` and `ssm_seg_negkept` dropped; no `ssm_*` schema left; database 252 MB -> 137 MB (`pg_database_size`) |
| H2 / H3 holes (coverage check) | 2026-10-03 / 04 | rehearsed on scratch `ssm_fills_h2h3b` with 0039's trigger added there only (17/17 DB tests; dropped); backup `full_backup_20261003T095403Z`; 0040 applied 2026-10-03 10:02:54; fill run `fill-20261004T120358Z-a00f9489` 2026-10-04 12:03:58: +120 Del Monte Pangasinan stock 2023-02 rows (copy of 2023-01, `synthetic_branch_adjacent`), +2,592 Unilever receipts with opening assumed 0 (11 negative; 192 after the possibly partial 2025-05 count, pending SSM), +2,553 with closing assumed 0 (1,365 negative). Details: `reports/diagnostics/coverage_check_2026-10-03.md` |

**Rule breach on record:** the 2026-10-02 session applied 0037 and 0038 from uncommitted files (0037 = `0035_lp_run.sql` renumbered, because
public already held `0035_user_two_factor.sql`). They were committed afterwards in ef08b70; the committed files hash to the checksums
`schema_migrations` recorded. 0039 (stock-timing fix) and 0040 (fill holes) are live; reserved: **0041 = data marts, 0042 = in-transit stock**; anything else starts at 0043.

### 18.5 Del Monte preview pipeline (ABC SKU level, forecast router, LP) — NOT built; what is left

1. **Decision: the quantity unit.** `sku_demand_fill.quantity` inherits sell-out's quantity, which `Product_Demand_View` labels
   `'unconfirmed'` (schema.sql:802). Pesos per unit run about 830-910 (cases? UNVERIFIED). The LP plans in pieces, and 0 of the 374 split SKUs
   carry `pack_size`, `lead_time_days` or `unit_price` in `product_dimension`.
2. **ABC (SKU level, preview):** on-request preview ABC is Unilever-only (backend/data_mode.py `abc_single` / `abc_relation`, the Unilever
   relation at :364); extend it to rank `sku_demand_fill.net_amount` and lift the principal gate in backend/routers/abc.py.
3. **Forecast router:** scripts/build_preview_outputs.py is Unilever-only — Tier A pool (:65), `build_series` (:73), and its acceptance check
   `verify_against_live` (:94) needs a live `Forecast_Result` to reproduce, which Del Monte does not have: a Del Monte acceptance rule is a
   decision. The series is 17 of 36 months (gapped); how the router treats gap months on this branch is UNVERIFIED (the params branch's
   "gap months not zeros for ADI" is unmerged).
4. **LP:** `run_lp.py`'s Del Monte path is category grain (`resolve_delmonte_category_grain`, :103 / :299) and `CANDIDATE_QUERY` (:143) needs
   a `Forecast_Result` row; `build_preview_outputs.lp_rows` (:152) needs Del Monte SKU stock/cost (latest real snapshot 2025-12) and lead times.
5. **Backend/frontend gates:** `run_baseline_forecast.py --principal` accepts only `unilever` (:280); `/forecast/{sku}` actuals read the
   Unilever relation (backend/routers/forecast.py:95); `DEL_MONTE_NO_FORECAST` (frontend/src/components/SKUForecast.jsx:42); dashboard
   "The LP does not plan Del Monte" (backend/routers/dashboard.py:1161).

### 18.6 Frontend changes for Audrey (API live on this branch; frontend not changed)

| where | change |
|---|---|
| `GET /dashboard` -> `sales_vs_stock[]` | new keys per point: `received_estimated` (pesos at cost; Unilever scope only; null under `all` / `delmonte` and before 0038), `received_estimated_negative_skus`, and `provenance: {sales, stock_on_hand, received, received_estimated}`, each `real` / `derived` / `synthetic` / null |
| SalesVsStockWidget (Charts.jsx) | draw `received_estimated` as its own series, legend **"Estimated from stock and sales"**; tooltip "N SKUs had a negative stock balance (counted as 0)". The existing `received` line is already dashed (Charts.jsx:556, meaning *allocation proxy*), so the estimate needs a distinct style |
| any synthetic point (`provenance.* == 'synthetic'`) | legend **"Synthetic — SSM data not received"** |
| Del Monte | forecasts and LP in PREVIEW only, labelled preview-only (once 18.5 is built); product-level sales label **"Demo: Del Monte product sales estimated from total sales × stock share — SSM has no product-level sales"** |
| returns | no endpoint reads `salesreturn_fact` yet; Unilever returns are preview-only data with no chart |
| coverage | `etl_coverage` now says real / derived / synthetic / partial / missing per principal × table × month; no endpoint serves it yet (`GET /admin/data-loads` still planned, DEC-30) |


---

## 19. Data marts + range-based dashboard (DEC-36) — LIVE on `public` 2026-10-04

Branch `kelvin/data-marts` (off `kelvin-etl` 1edf5cf). Schema `mart`, migration **0041**, applied 2026-10-04 13:37:42 UTC
through the runner after backup `backups/full_backup_20261004T133536Z` (PASS). Pre-approved apply conditions (prompt
2026-10-04): mart size under 60 MB and a scratch rehearsal matching source totals exactly — both met (§19.2).

### 19.1 What is in `mart`

| object | grain | rows (live, 2026-10-04) | source |
|---|---|---|---|
| `sales_mart` (+ `_real`, `sales_month`, `sales_category_month`) | product (DM: category) × month × source tag | 43,528 | `unilever_sku_demand_fact`, `sellout_fact`, `sku_demand_fill` (DM split, level `product`, never in a total) |
| `flow_month` | principal × month × flow × source tag | 243 | purchases (`purchase_fact`, DM ex-VAT), estimated receipts (`derived_receipt_fact`), returns (`salesreturn_fact`) |
| `inventory_mart` (+ `_real`, `inventory_count`) | product × count × source tag | 52,387 | `inventory_fact`: cases, loose, pieces (UL cases × pack + loose; DM `no_pack_size`), pesos at last purchase price, previous count |
| `idle_stock` | product × real UL count | 3,857 | products in the count with no piece sold in the 6 (`DEAD_SKU_MONTHS`) real sales months up to it |
| `forecast_run` / `forecast_run_value` | run × product × month | 3 runs / 6,054 | history, never rebuilt: run 1 = `forecast_result` (stored_run), runs 2-3 = recreated backtests |
| `accuracy_mart` (+ category / total views) | run × product × month | 6,054 | forecast vs real actual, signed miss (pieces, pesos), direction, run length, possibly_stock_limited |
| `refresh_log`, `refresh_status` | — | — | each refresh's trigger, time, row counts; whether a source changed since |

Every row: `data_kind` = `real` (`is_demo = false`, the `_Real` views' rule) / `generated` (`synthetic_v2`) / `filled` (every
other `fill_source`). KPIs, Pareto and accuracy read real rows only. `mart.refresh()` rebuilds every derived table in one
transaction (~6 s server side); called after every slice load (after its fill step), `fill_missing` run alone,
`run_baseline_forecast --write` (which first keeps the run in the history), `run_lp`, and `backtest_forecast_run`; a failure
is reported, never raised (`python -m analytics.marts --refresh`).

### 19.2 Verification

| check | result |
|---|---|
| scratch rehearsal (`scripts/rehearse_marts.py`, built from the committed file into `ssm_mart_rehearsal`, dropped) | 12 exact comparisons: 0 differences; NaN 0 |
| same checks on live `mart` after the apply (`--check-only --schema mart`, `tests/test_marts.py`) | 0 differences; 9/9 tests pass |
| idle stock, Unilever count 2026-03 (counted 2026-04-06), no piece sold 2025-09..2026-02 | **108 products, ₱1,689,351.75** — the figure quoted to the team; no committed file or branch states it, so it is reproduced here from `inventory_fact_real` + `unilever_sku_demand_fact_real`. 101 of the 108 never sold at all in the La Union sales file: the Ilocos Sur stock vs La Union sales question, UNVERIFIED with SSM |
| range Pareto over one month vs every stored ABC `single` run | 54 of 54 runs: same products, same tiers; shares within the stored 4-decimal rounding |
| backtest regenerated (`scripts/backtest_forecast_run.py`, production router) vs the reports' own rows | at-the-time cohort 3,503 rows / 337 products, max \|diff\| 2.9e-11; fixed-107 cohort 2,419 / 107, max 5.0e-05 (4-dp CSV); every headline metric = `headline_two_cohorts.csv` |
| accuracy mart headline (29 months) | at-the-time: median product WAPE **34.56%** (report 34.79%), pooled 29.63% (29.56%), total pesos 9.82% (9.87%), surplus share 55.8% (55.9%). Differs only by 3 product-months whose quantity is blank: the reports counted them as 0 sold, the mart as missing (2026-10-03 blank-quantity decision); all other rows identical |
| size | live rows ~21 MB; on disk 41.6 MB including the space the next refresh reuses (steady-state peak); limit 60 MB |
| `GET /dashboard`, default range, from this machine (median of 3) | Unilever 4.40 s → **3.68 s**, Del Monte 3.72 → **2.74**, all 4.64 → **3.88**; 53 → 29 queries (each costs ~0.12 s round trip); the month-level marts are one read per request |
| backend tests touched (`tests/backend`, `test_marts`, `test_params`, LP script, fills, loader) | 691 passed, 1 skipped; `scripts/smoke_api.py` 13/13 PASS; `npm run build` exit 0 |

### 19.3 What the dashboard now answers for the selected range

| card | before | now |
|---|---|---|
| Sales | end-month snapshot only | `kpis.sales_cumulative` (range total, months with data, missing months, label) + `kpis.sales_snapshot` (= `kpis.sales`) |
| Inventory value | latest count (2026-03) | **count at the range's end** (default range: 2026-02, counted 2026-03-02, ₱46,576,778.51 — the count flagged unusual); `weeks_of_cover` keeps the latest count, `weeks_of_cover_range_end` added |
| Below safety stock | latest count (35 of 70) | range-end count (default **6 of 72**, = the 2 Mar figure on record); refused for a count before the plan's opening count |
| ABC ring + dead stock | stored single-month run | ranked on the range (default UL: A 174 / B 242 / C 666, Pareto check passes at 84.3%) |
| Forecast error (new) | — | `forecast_accuracy`: at-the-time backtest for months it covers, stored runs after; default range 248 products, pooled 33.4%, 56.7% of the peso miss is surplus, 59 products over-forecast 3+ months in a row (DEC-33's over-run rule on the range; the plan's own flag is `review_flag`, 15 products for cycle 2026-03) |
| Idle stock (new) | — | `idle_stock` at the range-end count (default 2026-02: 83 products, ₱1,417,263.94); full list `GET /dashboard/idle-stock` |
| Sales vs stock chart | real rows only (H1) | `*_estimated` points from filled rows (generated too in preview); `returns` / `returns_estimated` (H4) |

New routes (`dashboard.view`): `/dashboard/pareto`, `/yoy`, `/accuracy`, `/idle-stock`, `/product-sales` (serves the DM product
split, H4), `/forecast-runs`. `GET /pareto` reads the mart too.

### 19.4 Decisions (Yuan, 2026-10-04) and what is still open

| # | item | outcome |
|---|---|---|
| 1 | Range-end stock card on a flagged count | **Kept.** `kpis.soh_count_note` (and `soh_snapshot.note`): "Counted 2 Mar 2026: unusually high (₱46.6M), accepted pending SSM confirmation" for an accepted flagged count; a flagged count with no ruling gives its reviewed reason (`backend/data_notes.flagged_count_note`) |
| 2 | Which count weeks of cover reads | **The card's own (range-end) count**; the 2026-09-29 latest-count rule is superseded (DEC-36). `kpis.weeks_of_cover` is that figure (`weeks_of_cover_range_end` the same object); `caveat` "stock = Ilocos Sur warehouse; sales = La Union only; territory match unverified" for Unilever |
| 3 | `possibly_stock_limited` | **Replaced** by 3226cc4 README Part 0.1 (migration 0043): opening or closing count 0, or below 1 week of average sales (12 months before, from first sale, ≥ 3 months, week = mean × 12 ÷ 52), any direction; 2025-05 missing = 0 and flagged `count_possibly_partial`. Reproduces Part 0's **1,142 of 2,419** on the fixed-107 backtest (1,277 not) |
| 4 | H1 in real mode | Del Monte's empty months are generated (synthetic_v2), not filled: still gaps outside preview, as designed (DEC-29) |
| 5 | Under `all`, the range total covers only months both principals have | labelled (`months_with_data`, `missing_months`) |
| 6 | Audrey's `Charts.jsx:1133` "Ranked on <month> sales (single month)" | frontend: use `abc_revenue.label` (done on kelvin-etl's own `Charts.jsx`) |

---

## 20. Final QA — 2026-10-04 (branch `kelvin/final-qa`, off kelvin-etl 668b78e)

### 20.1 State of `public` and the app today

| area | state (source) |
|---|---|
| Migrations | Live `public.schema_migrations` = 44 rows: committed files 0001–0043 (43 files, every checksum matches) **plus `0035_user_two_factor.sql`**, which is still **not on kelvin-etl**. The file exists only on `group7/UIFixes_Audrey` (5633063, with the MFA backend). Its checksum matches the live row (`4d2dd018…`). Next free number: **0044** |
| Data marts (0041, 0043, DEC-36) | Schema `mart`. Live row counts by kind: sales_mart 25,658 real / 3,134 filled / 14,736 generated; inventory_mart 30,656 / 3,895 / 17,836; flow_month 30 / 127 / 86. Refreshed after every load, fill, forecast `--write`, LP run and backtest (§19) |
| Review flag + in-transit (0042, DEC-33/34) | `review_flag` 2026-03-01: 15 flagged of 132 assessed; 7 of the flagged are in the current plan's 74 rows. PO Qty is shown and never subtracted |
| Dashboard speed + cache (668b78e) | GET /dashboard: 4 statements cold, 1 cached (was 30 + pre-ping + BEGIN). Reads are batched (`backend/batch.py`), GETs use an autocommit pool, and the response cache is keyed on endpoint + params + permission set and cleared when the data version moves (`backend/response_cache.py`). Report: `reports/diagnostics/speed_cache_2026-10-04/README.md`. Render not re-timed |
| Coverage | `etl_coverage` recomputed read-only: 700 rows, **0 differences** from stored. Gaps (2021-01..2026-09) are the ones §18.1 records: Unilever purchases 32 missing (37 derived), Unilever returns 2026-09, Unilever demand 2026-09 (D4), Del Monte product sales 52 missing. Del Monte stock 2023-02 `partial` (Pangasinan = the H2 adjacent copy, demo) |
| Real vs filled | Six `_Real` views: 0 demo rows, every definition filters `is_demo = false`. 0 real rows carry a `fill_source`. KPI / Pareto / accuracy read `data_kind = 'real'` only (tests: `test_abc_ranking_reads_real_rows_only`, `test_chart_draws_filled_months_as_estimates_never_as_sales`, `test_real_kind_is_exactly_is_demo_false`, live `test_every_mart_total_equals_its_source`) |

### 20.2 End-to-end spot checks (database → mart → endpoint, read only)

| check | database | mart | endpoint |
|---|---|---|---|
| March plan | `lp_recommendation` 2026-03-01, lp_run 1: 73 pending, 325,467.96 pcs (+1 accepted, 1,331.24) | — | GET /recommendations: same 73 + 1, `lp_model.run.run_key` 1 |
| Idle stock | 108 products in the 2026-03 count with no piece sold 2025-09..2026-02 | `idle_stock`: 108, ₱1,689,351.75, counted 2026-04-06, 101 never sold | GET /dashboard/idle-stock?period=2026-03: same. **Default period** (range end 2026-02) reads the 2026-02 count instead: 83 products, ₱1,417,263.94 |
| Range Pareto, product 138 (REX WMN DLN POWDER DRY + BRGHT 360X3ML) | 2024 ₱467,464.84 / 3 months; 2025 ₱2,798,496.67 / 12 months | same | 2024: class B (rank 165, cumulative 0.805); 2025: class A (rank 31) |
| Stock at range end | Unilever 2026-02: ₱46,576,778.51, 812 rows, counted 2026-03-02 | same | `kpis.soh_value` same, `soh_count_date` 2026-03-02, `soh_count_note` "Counted 2 Mar 2026: unusually high (₱46.6M), accepted pending SSM confirmation" |
| needs_review | `review_flag` product 613 (69668140 SURF POWDER CHERRY BLOSSOM), 2026-03-01: collapse, ratio 0.1796 | — | the /recommendations row: `needs_review` true, `review_reasons` ['collapse'], 0.1796 |
| Accuracy, at-the-time cohort (run 2, 2023-10..2026-02) | — | 337 products, 3,500 scored product-months (3 blank actuals) | `wape_pieces` 0.296344, `median_product_wape` 0.345610 (SQL recompute on the mart gives the same) |

### 20.3 QA fixes (minimal, no feature change)

| fix | files |
|---|---|
| GET /forecast for Del Monte (scope `delmonte`, or a code that resolves to a Del Monte product) is now 200 with `forecast: []` and `blocked_reason` "No product-level forecast for Del Monte: its sales files have no product detail." instead of 404. Unknown codes elsewhere are still 404. The SKU Forecast page shows `blocked_reason` when it is present | `backend/routers/forecast.py`, `backend/schemas/forecast.py`, `tests/backend/test_forecast.py`, `frontend/src/components/SKUForecast.jsx` |
| `scripts/backup_live_db.py` **retired as a command**: its restore check fails on JSON columns because the command dumps them without `json_as_text`. It now prints a pointer to `python -m scripts.backup_everything` and exits 2. `create_backup()` stays (backup_everything calls it with `json_as_text=True`) | `scripts/backup_live_db.py` |

Suite before the fixes: 1,324 passed, 26 skipped (raw files not in the worktree; `FILLS_SCRATCH_SCHEMA` unset). Touched tests after: 29/29. `npm run build` exit 0. `scripts/smoke_api.py` 13/13 PASS.

### 20.4 Open items

| item | owner / waiting on |
|---|---|
| Merge Audrey's `UIFixes_Audrey` (22 commits not on kelvin-etl, including the 0035 file and MFA backend) so the repo matches the live ledger | Audrey |
| LP cost inputs (procurement cost, storage cost, warehouse capacity, supplier ceilings) | SSM |
| 2026-02 count (₱46.6M) accepted pending SSM confirmation; PO Qty meaning; stock (Ilocos Sur) vs sales (La Union) territory match | SSM |
| Forecast model sign-off (DEC-25/26) | Sir Catubag |
| Render not re-timed after the cache; /recommendations still 7–11 statements cold; the preview dashboard is never cached | next speed pass |
| Del Monte preview pipeline (§18.5) not built | Yuan |

## 21. Remaining endpoints + housekeeping — 2026-10-05 (branch `kelvin/endpoints-housekeeping`)

No migration, no database write, no forecast, segmentation or LP run. Everything below was read from live in
read-only transactions on 2026-10-05.

### 21.1 Report branches merged (kelvin-etl 6cd014c, pushed)

| Branch | Merged as | Note |
|---|---|---|
| `kelvin/tier-a-basis` | `kelvin/tier-a-basis-clean` de93b6e | 7 tables: per-product revenue, price and peso columns moved to git-ignored `local/` |
| `kelvin/lp-logic-check` | `kelvin/lp-logic-check-clean` 5964deb | 2 tables: per-product price and peso columns moved to `local/` (hard rule 9) |
| `kelvin/forecast-error-business` | b4f6b77 | as is |
| `kelvin/surplus-bias-experiment` | 3226cc4 | as is |
| `kelvin/model-audit` | 36a5548 | as is |

The two original branches still hold the per-product columns in their history: keep them local, never push them.

### 21.2 Endpoints (for the frontend)

| Endpoint | What changed | Live check |
|---|---|---|
| `GET /policy-comparison` | new `pesos` block, `status: "pending_ssm_confirmation"`: per-product targets against the 3-week rule at last purchase price; headline `average`, `peak` alongside; per-item peso fields | cycle 2026-03, 73 products: rule ₱8,211,106.33; average ₱5,906,831.95 (−28.1%); peak ₱8,917,570.23 (+₱706,463.89, +8.6%) = `lp_logic_check_2026-10-03` §4 |
| `GET /dashboard/class-changes` (new) | products that entered or left Class A between two ranges, with both ranges' revenue, class and rank | 2025 against 2024, Unilever: 44 entered (₱8.59M → ₱39.62M), 38 left (₱38.03M → ₱4.71M), 123 stayed = `tier_a_basis_2026-10-03` §4 |
| `GET /dashboard/accuracy`, `GET /dashboard` `forecast_accuracy` | two labelled figures, always both: `company_total` and `typical_product_weighted`; `level=summary` replaces `level=total` (still accepted) | default backtest 2023-10..2026-02, 337 products: company total 9.8% (0.098194), typical product weighted 29.6% (0.296344) |

Decisions made here (Yuan ruled on the first two the same day, see the rows):

| Item | What was done | Why |
|---|---|---|
| Class-changes revenue rule | a month where returns exceeded sales counts as 0 (the ABC runner's rule for several months, `analytics/classification/orchestrate_abc.py:208`) | it is the rule the tier-a-basis report used. **Yuan, 2026-10-05: one revenue rule everywhere** — `GET /dashboard/pareto` and the dashboard's ABC ring now use it too (they netted returns over the range before and gave 43 / 37 on the same years); live check after the change in §21.5. |
| Company total reads 9.8%, not 9.9% | reported as measured | traced: 3 product-months whose quantity is blank. The model audit counted them as 0 sold (9.87%); the mart counts them as missing (9.82%). Same forecasts, same price basis (§19). |
| A product with no last purchase price | left out of the peso sums and counted (`skus_without_price`) | hard rule 3: the plan's ₱25 placeholder is never shown as a measured price. Cycle 2026-03 has none. |

### 21.3 Recorded and reported

| Item | Where |
|---|---|
| DEC-37: PO Qty is not treated as in-transit stock (scale check), information only, pending SSM | `ARCHITECTURE.md`; no code change |
| Safety-stock source comparison: current method ₱8.01M against forecast-error ₱7.90M (−1.4%) on 174 comparable products; Class A as of 2026-02 −2.8%, B +5.8%, C +3.5%; current stays the default | `reports/diagnostics/safety_stock_source_2026-10-05/README.md` |

### 21.4 Tests

`tests/backend/test_policy_comparison.py`, `tests/backend/test_dashboard_range.py`, `tests/backend/test_dashboard.py`,
`tests/test_marts.py`, `tests/test_dec_references.py`, `tests/backend/test_stock_timing.py`: 158 passed, 3 skipped (the live-database tests in `test_marts.py`,
which need `SUPABASE_DB_URL`). The full suite was not run.


### 21.5 Follow-up decisions (Yuan, 2026-10-05)

| Decision | Done | Check |
|---|---|---|
| Delete the original `kelvin/tier-a-basis` and `kelvin/lp-logic-check` | both local branches and their worktrees removed; neither was ever on `group7` | `git ls-remote --heads group7`: 0 matches; the LP check's offline pull kept in git-ignored `scratch/lp_logic_check_2026-10-03/` |
| One revenue rule everywhere | `backend/marts.PARETO_SQL` counts a month where returns exceeded sales as 0 (`analytics/classification/orchestrate_abc.py:208`); `GET /dashboard/pareto`, the dashboard ABC ring and `GET /dashboard/class-changes` all rank with it | live, read-only: reproduces every stored `single` ABC run (`tests/test_marts.py`, 1 passed); Unilever 2025 against 2024: Class A 167 and 161, 44 entered, 38 left |
| Company-total gap traced | one line in `reports/diagnostics/model_audit_2026-10-03/README.md` | 3 blank-quantity product-months: 0 sold in the audit (9.87%), missing in the mart (9.82%) |

Tests after the change: `tests/backend/test_dashboard_range.py`, `tests/backend/test_dashboard.py`, `tests/test_marts.py`,
`tests/test_dec_references.py`: 132 passed, 3 skipped (live tests), plus the live ABC reproduction test run on its own.

## 22. Tier A on the 12-month basis + full refresh — LIVE on `public` 2026-10-05 (DEC-38, PENDING TA CONFIRMATION)

Full write-up: `reports/diagnostics/tier_a_refresh_2026-10-05/README.md`. Branch `kelvin/tier-a-12m` (also merges `kelvin/blank-qty-fix` e78748c). Backup `full_backup_20261005T061733Z`. Migration 0044.

| item | before | after |
|---|---|---|
| Unilever Tier A as of 2026-02 | 132 (Feb 2026 alone, `single`) | **189** (12 months + new, `t12m_new`: 175 + 14); setting `analytics.params.TIER_A_BASIS` |
| Revenue covered, Mar 2025 – Feb 2026 | 67.7% | 81.0% |
| Forecasts, cycle 2026-03 | run 1: 119 ok / 13 insufficient | run 4: 175 ok / 9 insufficient / 5 dead; run 1 kept |
| Segmentation cohort 2026-02 | 132 (`single`, kept) | 189 (`t12m_new`) |
| March plan at 103% | `lp_run` 1: 73 products, 325,468 pcs, ₱6,964,217 at cost, 0 short | `lp_run` 2: 97 products, 356,254 pcs, ₱7,017,551 at cost, 0 short |
| Review flags, cycle 2026-03 | 15 flagged of 132 | 51 flagged of 189 (17 in the plan) |
| At-the-time accuracy, Jan 2024 – Feb 2026 | old list: median product WAPE 36.3%, company total 9.5% (pesos) | new list: 39.0%, 10.7% |

Open: TA confirmation; forecast runs 2-3 (stored backtests, read by the accuracy card) are still on the single-month list and pre-date the blank-quantity fix; `stability_v1` reads "churn" for all 189 (cut-offs count out of 38 monthly runs, the new basis has 27). Next free migration: 0045 (0046 is taken by the planning-mart session).

## 23. Planning mart — LIVE on `public` 2026-10-05 (migration 0046, part of DEC-36; branch `kelvin/planning-mart`)

`mart.planning_mart`: one row per product x LP cycle with everything the Reorder page shows already joined. `GET /recommendations`
reads it in one statement; the response fields are unchanged. Applied after Claude Code 1's push (kelvin-etl 87edd5e, `lp_run` 2).

| item | value | source |
|---|---|---|
| Rows | 277 = `lp_recommendation` rows (34 cycles; 97 pending of `lp_run` 2 + 1 accepted in cycle 2026-03) | `scripts/rehearse_planning_mart.py --check-only` |
| Size | 176 kB (table + indexes + TOAST) | same |
| Same answer as the joins | 0 differences in 17 scope x cycle x status cases: all 277 rows, all 97 rows of `lp_run` 2, every field, plus freshness, LP model and stock counts. Checked on a scratch build before the apply and on live after it | same |
| Stored `stock_status` / `urgency` against the endpoint's | 0 of 277 differ; 0 NaN | same |
| Refresh | `mart.refresh_planning()`: 1.2 s at 253 rows, 2.8 s at 277 (scratch builds) | `refresh_log.duration_ms` |
| Backup before the apply | `backups/mart_backup_before_0046_20261005T080301Z`: the `mart` schema only (8 tables, 112,511 rows, structure SQL; re-read and checked). The full backup was started first and lost its connection after 26 minutes; 0046 writes nothing outside `mart` | scratch log |

**What each row holds.** Product name + SKU, principal, pack size; tier, revenue share, its basis (`t12m_new` for Unilever, `single` for
Del Monte) and month; the cycle's forecast in pieces with its range and the `mart.forecast_run` that keeps it; safety stock; target stock;
the opening count's stock (pieces, cases, pesos) and count date; `on_order` (PO Qty: information only, never subtracted, DEC-34/37);
the order in pieces and in pesos at the last purchase price (unit cost per case of the product's latest real count on or before the
opening count / pack size; in the mart only, not in the response); status (IN STOCK / LOW / CRITICAL / NO DATA; NO ROP cannot occur on a
planned row) and urgency; `needs_review` + reasons; `lp_run_key` and its allocation %; decision status (pending / accepted / dismissed).

**Kept in step.**

| change | what refreshes the mart |
|---|---|
| Data load, fill, forecast run, LP run, backtest | every full `mart.refresh()` now also runs the planning refresh, same transaction (`analytics/marts.refresh_marts_cursor`) |
| Review-flag write | `scripts/compute_review_flags.py --write` runs the planning refresh after its commit |
| Reorder decision | `PATCH /recommendations/{id}` updates the mart's own row in the decision's transaction |
| Product edited through the app | `PATCH /sku` runs the planning refresh in its transaction (about 1-3 s added to the edit) |
| ABC run on its own | NOT wired. The mart then reads as stale and the endpoint uses the joins until the next forecast or LP run refreshes it |

**Never served out of step.** `mart.refresh_status` gained `planning_refreshed_at` and `planning_stale` (a source changed after the last
planning refresh); `refreshed_at` / `stale` still mean the last FULL refresh. The endpoint falls back to the per-request joins when the
mart is missing, `planning_stale`, or its row count / pending count / latest decision differ from `lp_recommendation`'s, and in preview
mode. The response cache needs no change: its data version already reads `refresh_status`, so a planning refresh clears it.

**Queries per request** (`reports/diagnostics/speed_cache_2026-10-04/results/planning_mart_statements_per_request.txt`; session check included):

| request | before (87edd5e) | after, cache cold | after, cache warm |
|---|---:|---:|---:|
| `/recommendations?status=pending&principal=unilever` | 11 | **2** | **1** |
| `/recommendations?status=pending&principal=delmonte` | 7 | **2** | **1** |
| `/sku` (the Reorder page's other call, not changed) | 4 | 4 | 1 |

On the database the mart statement runs in about 25 ms (EXPLAIN ANALYZE: head 22 ms, rows 2 ms). It returns 26 kB for the 97 pending
Unilever rows (rows sent as JSON arrays; 78 kB as objects before that change) against about 16 kB of values for the joins' row query.

**Timings: NOT a clean measurement.** Local server on a laptop against live, 2026-10-05. The laptop's link to Supabase was unstable all
session: a bare 78 kB value took 0.3-0.9 s at its best and 5-15 s at its worst, a full backup lost its connection, and one `/sku` call
failed on a dropped connection. Time followed bytes, not statements, so the page's wall clock is mostly `/sku` (about 0.8 MB).

| measure (cold, interleaved before/after passes, link at 5-7 s per 78 kB) | before | after |
|---|---:|---:|
| `/recommendations` Unilever, server time, median | 4,433 ms (n=6) | 2,910 ms (n=6) |
| `/recommendations` Del Monte, server time, median | 883 ms (n=6) | 655 ms (n=3) |
| Reorder page Unilever (both calls), wall clock, 3 runs | 45.6 / 28.2 / 26.8 s | 40.9 / 38.5 / 27.5 s |
| Reorder page Del Monte, wall clock, 3 runs | 15.9 / 16.0 / 7.0 s | 6.4 / 9.1 / 7.4 s |
| Warm (cached), either endpoint, server time, median | 190-200 ms | 190-200 ms |

One earlier pass on a better link gave the unchanged page 2.1 / 3.6 / 1.5 / 2.6 / 2.2 s cold (Unilever); the mart's pass that followed
ran after the link had dropped again, so there is no matching "after" for it. Re-time on a stable connection before quoting a speed-up.
Render was not timed.

Tests (touched files only): `tests/test_planning_mart.py`, `tests/backend/test_recommendations.py`, `test_lp_cycle.py`, `test_sku.py`,
`test_response_cache.py`, `test_stock_timing.py`. Open: the ABC run's refresh hook; a clean re-timing; the full backup to rerun on a stable link.
