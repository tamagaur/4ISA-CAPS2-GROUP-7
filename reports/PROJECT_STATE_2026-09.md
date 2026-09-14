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
