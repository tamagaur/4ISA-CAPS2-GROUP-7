# SSM DSD — Project Architecture

> **Living document.** This is the shared source of truth for how the system is built. It will grow stage by stage. **Current focus: the Extract stage.** Downstream sections are intentionally light placeholders to be expanded later.
>
> Decision status legend: **DECIDED** (locked) · **PROPOSED** (recommended, awaiting sign-off) · **OPEN** (must be resolved before it blocks work).

---

## 1. Purpose & scope

The **Decision Support Dashboard (DSD)** — always "DSD", never "DSS" — replaces San San Marketing's (SSM) blanket three-week safety-stock rule with data-driven replenishment recommendations for an FMCG distributor in Urdaneta, Pangasinan.

- **In scope:** Unilever Philippines and Del Monte Philippines only.
- **Out of scope (permanent):** Magnolia. Any Magnolia record found in the raw data is quarantined and flagged, never loaded.
- **Analytical goal:** ETL → ABC/Pareto classification → SARIMA demand forecasting → safety stock & reorder point → multi-objective LP optimization → dashboard.

---

## 2. Architectural principles

1. **Anti-fabrication is absolute.** Every stored value traces to a real source cell (`file :: sheet :: row/col`) or is a deterministic derivation of real cells. Nothing is synthesized, imputed, interpolated, or back-filled. Missing data is reported as a gap, never filled.
2. **Config-driven, not code-per-file.** File/format handling is governed by a schema registry (`config/column_maps/*.yaml`, `config/alias_tables/*.csv`), not bespoke logic per file.
3. **Layered and traceable.** Data moves through explicit zones (raw → staging → curated). Every curated row can be walked back to a staged row and then to a source cell — this is what makes the anti-fabrication rule auditable.
4. **Idempotent & deterministic.** Re-running any stage on the same input produces byte-identical output. Loads are idempotent upserts on natural keys.
5. **Evidence over assumption.** When the data is ambiguous, the pipeline records `unknown` / routes to a reject queue — it never guesses.

---

## 3. High-level layers

```
  SOURCES              RAW ZONE           STAGING ZONE            CURATED (WAREHOUSE)        ANALYTICS            SERVING
  ────────             ────────           ────────────            ──────────────────         ─────────            ───────
  SSM Excel   ──►   data/raw/         ──► staging/            ──► Supabase / Postgres    ──► ABC / Pareto    ──► FastAPI
  exports          (immutable,           (1 typed table          - transaction mart          SARIMA              │
  (.xlsx/.xls-     as-received)          per source-sheet,       - product mart              LP (PuLP)           ▼
   as-MHTML)                             + provenance)           (see §5, DEC-02)        ──► Forecast_Result   Next.js
                                                                                             LP_Recommendation   dashboard
        │                 │                    │                        │
     EXTRACT ────────────────────────────────►│                        │
     (faithful read + typing + provenance)     │                        │
                                          TRANSFORM ────────────────────►│
                                          (rename/map vocab, dedup,       │
                                           source-of-truth, conform)   LOAD (idempotent upsert)
```

---

## 4. ETL stage boundaries (who owns what)

| Concern | Extract | Transform | Load |
|---|:---:|:---:|:---:|
| Open any format (xlsx / real-xls / MHTML / csv) | ✅ | | |
| Locate header row, drop junk/scratch sheets | ✅ | | |
| **Type fidelity** (codes→TEXT, money→decimal, dates→date) | ✅ | | |
| Attach provenance + sheet-role + detected-grain tags | ✅ | | |
| Totals-row checksum + reject log | ✅ | | |
| **Rename / map** vocab A/B/C → canonical fields | | ✅ | |
| Dedup + choose **source-of-truth** per fact | | ✅ | |
| Conform to dimensions, resolve grain per principal | | ✅ | |
| Upsert into facts/dims on natural keys | | | ✅ |

**One-line rule:** *Extract detects and tags; Transform decides and standardizes; Load persists.*

---

## 5. Architecture decision register

| ID | Decision | Status | Notes |
|---|---|---|---|
| DEC-01 | Explicit raw → staging → curated layering | **DECIDED** | Staging = typed, per-source-sheet, provenance-carrying; it is the audit trail. |
| DEC-02 | Product dimension does **not** conform across all facts → model as **two marts** | **PROPOSED** | Invoice-grain facts (Sales/Purchase/SalesReturn) have no SKU key. `Product_Dimension` joins only to Inventory/SellOut/Unilever-SKU. Call this a *transaction mart* + *product mart*, not one clean constellation. See DEC-11: `Product_Demand_View` resolves the *consumption* side of this tension (one read shape for downstream models) without deciding the *storage* question here — this row stays PROPOSED until the team decides it explicitly. |
| DEC-03 | **Recommendation grain per principal** | **DECIDED (2025-07)** | **Unilever = SKU** (La Union per-SKU file has real SKU demand). **Del Monte = category/brand** (from Sell Out; invoice-level sales carry no SKU, and allocating would be fabrication). SKU-level Del Monte via inventory-delta proxy is a **deferred future upgrade** (Option B), not baseline. See §5.1. Defensible claim: *"we forecast at the grain each principal's data honestly supports."* |
| DEC-04 | **Source-of-truth per fact per principal** | **DECIDED (2025-07)** | One authoritative source per fact; overlapping views demoted to reconciliation cross-checks (never loaded). Prevents double/triple-counting. Full map in §5.2. Dedup natural key confirmed by a uniqueness test during Extract QC. |
| DEC-05 | Totals-row used as extraction **checksum** | **DECIDED** | Row-0 sums validate that extraction lost/added nothing. |
| DEC-06 | SCD strategy = Type 1 (overwrite) for dimensions | **PROPOSED** | Acceptable for demand forecasting (we care about the time series, not attribute history). Revisit if customer/salesman reassignment matters. |
| DEC-07 | Canonical `doc_type` vocabulary = Extract's staged `_doc_type` tags | **DECIDED (2026-07), applied (2026-07)** | Three vocabularies drifted apart (Extract tags vs `source_of_truth.yaml` labels vs `column_maps/*.yaml` filenames), breaking `load_column_map()` lookups. The staged tags win because they are already validated against the real corpus. `source_of_truth.yaml` and column-map filenames renamed to match (`purchases`→`purchase_order`, `inventory`→`inventory_sign_off`, `inventory_signoff.yaml`→`inventory_sign_off.yaml`); a `sales_unilever_sku_demand` fact entry was added (previously missing entirely). A second instance of the same bug class was found and fixed while applying this: `cross_check_roles` (a `_sheet_role` list) was being used to name *doc_types* (`ssis_summary`) — moved to a new `cross_check_doc_types` field, which also now documents `daily_sales_report` as a demoted duplicate of `sales_register` (both share `_sheet_role="data"`, so role alone can't distinguish them). `tests/test_transform_config.py` (new) asserts every staged `_doc_type` has a column map + source-of-truth entry, and the reverse — no config entry names a doc_type Extract never actually staged. |
| DEC-08 | EOQ inclusion in the prescriptive model | **OPEN — verify first** | EOQ does **not** appear in any of the three panel scribe's notes on record. Before adding: confirm the exact panel/adviser requirement (verbal comment? RRL conflation?). If confirmed, EOQ enters as a **benchmark/reference quantity** that the multi-objective LP refines under SSM's real constraints — never as a second, competing order-quantity decision alongside LP. Log framing + source here when resolved. |
| DEC-09 | Dimension FK resolution timing — Transform-time vs Load-time | **DECIDED (2026-08): Load-time, lookup-or-insert** | `load_to_supabase()` resolves/creates the dimension row and gets its surrogate key immediately before upserting the fact row that needs it — Transform stays DB-free, but resolution happens inline in Load rather than a separate backfill pass. Required by 4 tables (`Unilever_SKU_Demand_Fact`, `ABC_Classification`, `Forecast_Result`, `LP_Recommendation`) which declare `product_key NOT NULL`, so deferred backfill is physically impossible for them. |
| DEC-10 | `Sales_Fact` scope — Del Monte only, not both principals | **DECIDED (2026-08)** | Unilever's real Sales system-of-record (SSIS `RAW_DATA`) has no invoice/reference column at all — confirmed against real staged headers, true grain is closer to outlet+calendar_day than invoice. `Sales_Fact.principal` CHECK restricted to `'delmonte'`. Confirmed via exhaustive grep that nothing in `analytics/`/`backend/` depends on this table holding Unilever rows. **Direct consequence: `ssis_summary` (1,949,687 real staged rows — the single largest source in the entire corpus) now has no fact-table destination at all.** Quantified 2026-08: giving it one (a new outlet+day-grain fact table) would add **~694 MB** to the database — versus **~16 MB** for literally everything else combined — which would push the project off Supabase's free tier (500 MB) by ~42%. Not built in this pass. If Unilever sales are ever needed as a fact (not just SKU demand via `Unilever_SKU_Demand_Fact`), revisit this as an explicit cost/scope decision, not a default "add the table" move. |
| DEC-11 | Unit-of-measure normalization — canonical comparable unit = **pieces** | **DECIDED (2026-08)** | Unilever: `Unilever_SKU_Demand_Fact.quantity_sold` is set from the source's reported `sale_quantity_pieces` column directly (`transform.normalize_quantities()`), never derived from `sale_quantity_cases × pack_size` — confirmed against real data that the two agree only ~84% of the time, so the derivation is a QC cross-check (flagged on disagreement), not the value of record. Del Monte: `Inventory_Fact.quantity_pieces` (new column) is set from the reported `PCS` column directly; `CAS`/`PKG` are **not** converted — no confirmed `pack_size` exists anywhere in Del Monte's files, so a conversion would be fabricated, not derived. Del Monte Sell Out (`SellOut_Fact.quantity`/`quantity_cases`) is explicitly **out of scope**: no unit is documented and no pack_size exists to reconcile against either. See `config/column_maps/unilever_sku.yaml`, `inventory_sign_off.yaml`, `sell_out.yaml` for the per-field notes. |
| DEC-12 | Period-key normalization — canonical value format **'YYYY-MM'** across every fact needing cross-grain joins; no forced cross-table rename | **DECIDED (2026-08)** | Closes three bugs found reconciling `transform.py`/`granularity.py` against real data (§7 gap 4): (1) `Unilever_SKU_Demand_Fact.calendar_month` was never reformatted from its raw `"MM.YYYY"` shape — `transform.reformat_calendar_month()` now does this (reuses Extract's own `MM_YYYY_RE`), wired into `transform_fact()` for `unilever_sku`. (2) `granularity.py::resolve_unilever_sku_grain()` required `{"sku_id", "date", "quantity_sold"}` — `sku_id`/day-level `"date"` are the *analytics*-layer contract (`COALESCE(sku_code, category_path)`, post-Load), not this pre-Load stage's real fields; fixed to require `{"sku_code", "calendar_month", "quantity_sold"}` with a monthly (not daily) continuity check, consistent with the confirmed monthly-only Unilever source and `sarima.py`'s own monthly seasonality assumption. (3) `Inventory_Fact.snapshot_date` (`DATE NOT NULL`) was being assigned a raw `'YYYY-MM'` string — invalid. `Inventory_Fact` gains a real `_period TEXT` column (mirrors `Sales_Fact`/`Purchase_Fact`/`SalesReturn_Fact`/`SellOut_Fact`'s existing pattern) as the actual join key; `snapshot_date` is now an explicitly documented **synthetic** first-of-`_period` marker, not a reported date. Naming: each fact keeps its natural period column (`_period` vs. `calendar_month`) — "single period key" means one consistent format/semantics, not one literal column name project-wide. |
| DEC-13 | Unified product-demand **read shape** — `Product_Demand_View`, storage stays grain-honest | **DECIDED (2026-08)** | Answers this session's "single staging schema" story without contradicting DEC-02 (still PROPOSED) or DEC-03 (DECIDED, grain differs per principal): `Unilever_SKU_Demand_Fact` and `SellOut_Fact` are unchanged — a new `schema.sql` §6 view (`Product_Demand_View`) `UNION ALL`s both through `Product_Dimension`'s already-shared `product_key`, giving downstream models (ABC/SARIMA/LP) one shape to read. Depends on DEC-11/DEC-12 landing first: `quantity_unit` ('pieces' for Unilever vs 'unconfirmed' for Del Monte — DEC-11 never confirmed a Del Monte pack_size) stops a caller from silently treating the two `quantity` columns as comparable; `period` is reliably `'YYYY-MM'` on both sides thanks to DEC-12. `net_amount` is NULL for Unilever rows (that source has no revenue field — not fabricated). `LEFT JOIN`+`COALESCE` on the Del Monte side so an unresolved `product_key` (nullable on `SellOut_Fact`, unlike Unilever's `NOT NULL` FK) still surfaces rather than being silently dropped. Deliberately not ORM-mapped in `models.py`, same precedent as `BO_Monitoring_View` — no real consumer reads it yet. Unverified against a live Postgres instance (Load has never run against one). |
| DEC-14 | Reject-rate validation gate blocks Load — threshold = **2%** | **DECIDED (2026-08) — team default, not a sourced business requirement** | No panel/adviser note or manuscript section specifies a reject-rate threshold anywhere (checked — the manuscript's only comparable gate is the unrelated MAPE < 20% forecast-accuracy check, §3.4.2.2). 2% was chosen by the team as a circuit breaker, not a tolerance expected to be approached: the real corpus already runs at 0% rejects (161 files, 6 families — see status below). `load.py::check_reject_rate_gate()` reads `staging/_manifest.json`'s `staged`/`reject` counts (Extract's sheet/file-level rejects only — unreadable, no header/data, Magnolia-quarantined) and raises before any DB write if crossed; `load_to_supabase()` takes an optional `manifest_path` to enforce this. Checksum mismatches are deliberately excluded from the reject-rate count — `extract/_qc.py` already documents those as informational, never a staging/Load gate, and this story doesn't reopen that decision. **Revisit this number if the adviser/panel later specifies a different one** — it is not defended as evidence-based the way DEC-03/DEC-04 are. |
| DEC-15 | Zero/negative/outlier quantities are **flagged, never dropped or clamped** | **DECIDED (2026-08)** | Extends this project's existing anti-fabrication stance on quantities (already documented per-fact — e.g. `SellOut_Fact.quantity`/`SalesReturnFact.bo_units`'s "negatives are real, do not clamp to zero" comments) into an actual visibility mechanism: nothing was flagging them before, they just passed through silently. `clean.py::flag_quantity_issues()` (new) reports zero/negative/IQR-outlier counts and rows per quantity column — reuses `flag_iqr_outliers()` for the outlier half rather than duplicating the IQR math, and never mutates or returns a modified DataFrame (a value can land in more than one bucket, e.g. negative *and* an outlier — buckets aren't mutually exclusive). Surfaced through the same M2 QC tooling this session already built, not a new mechanism or a schema change: `transform_driver.py`'s manifest gains a top-level `quantity_issues` section (per `fact/principal`, using `QUANTITY_COLS_BY_FACT` — `quantity_sold`, `bo_units`, `units_received`, `quantity`, and both `quantity_pieces`/`quantity_on_hand` for inventory), and `transform_signoff.py`'s checklist prints it for the human sign-off decision. Deliberately **not** persisted as schema.sql columns (unlike `Sales_Fact._outlier_flag`, which already exists but is itself unpopulated since nothing calls `clean_pipeline()` yet) — team chose to route this through the now-enforced M2 review/sign-off gate instead of a 5-table schema change; revisit if the eventual dashboard needs to query flagged rows directly. |
| DEC-16 | Unilever SOH scope — **2023-01 onward only** | **DECIDED (2026-08)** | Three independent signals all break at the same boundary in `reports/SOH_PROFILE.md`'s discovery pass: Article No join rate against the real Unilever SKU universe jumps from ~53% (2021) to ~96% (2025); the price column changes from `MOVING AVERAGE PRICE(CS)` (2021-2022) to `Last Purchase Price(GSV/CS)` (2023+) — a different pricing methodology, not a rename (see DEC-19); and the snapshot-date convention shifts from mixed/inconsistent labeling pre-2023 to uniformly early-next-month (1-5 days after period end) from 2023 on. Pre-2023 SOH data is out of scope for the `ssis_soh` doc_type until a fresh ruling extends it. |
| DEC-17 | Unilever SOH dedupe — **sheet-name snapshot date, first file wins** | **DECIDED (2026-08)** | `data/raw/SSIS/` and `data/raw/Unilever/` hold the same 37 months twice (byte-identical row counts and Article No sets, confirmed in `reports/SOH_PROFILE.md`). Dedup key is the snapshot date parsed from the `SOH(<date>)` sheet name (after the DEC-18 date-guard correction), not the file path; ties resolve to whichever file `analytics/etl/extract/_shared.select_source_files()`'s deterministic sort visits first (alphabetical — `SSIS/` sorts before `Unilever/`). Every skipped duplicate is logged with both paths, not silently dropped. |
| DEC-18 | Unilever SOH — **2021-06-30 rejected explicitly** | **DECIDED (2026-08)** | `SSIS MONTHLY JULY 2021.xlsx`'s SOH sheet carries a snapshot literally labeled `SOH(JUNE 30, 2021)` — colliding with `SSIS MONTHLY JUNE 2021.xlsx`'s own, different-payload snapshot also labeled June 30, 2021 (904 vs 952 rows, disjoint Article No sets). Two genuinely different exports sharing one date label; neither can be picked as canonical without a source-side answer neither file provides, so both are rejected for that date rather than one being guessed. Moot under DEC-16's 2023+ scope (both files are 2021), kept as an explicit guard in `analytics/etl/extract/ssis_soh.py` (R3) so a future scope change can't silently let it back in unnoticed. |
| DEC-19 | `last_purchase_price_gsv_per_cs` is **NOT** mapped to `Inventory_Fact.cost` | **DECIDED (2026-08)** | Verified unit mismatch, not a naming preference: Del Monte's `cost` is an extended peso total, confirmed equal to `valuation` on real data (584 rows `Cost == Valuation` in the 2025 layout, plus the totals row reconciling the same way). Unilever's `last_purchase_price_gsv_per_cs` is a per-CASE unit price (the source header says so directly — "GSV/CS"). Coalescing the two under one column name would silently mix a total and a unit price. `Inventory_Fact.unit_cost_per_case` (migration 0009) is the separate, correctly-scoped column instead; Del Monte rows leave it NULL, Unilever rows leave `cost` NULL. |
| DEC-20 | Unilever SOH — **`_period` is the join key; `snapshot_date` is provenance only** | **DECIDED (2026-08)** | Unlike Del Monte's `inventory_sign_off` (whose `snapshot_date` is a documented SYNTHETIC first-of-`_period` marker, DEC-12), Unilever SOH's `snapshot_date` is a REAL reported date — but it still isn't the join key: it lands mostly 1-5 days into the month *after* `_period`, with one confirmed exception (verified live: `migrations/0010_gsv_and_guards.sql`'s `days_offset` backfill, 27,282/27,282 rows populated — 17,338 at 1 day, 5,506 at 2, 3,653 at 3, and 785 rows all from the single 2026-03 period/file (`SSIS MARCH 2026.xlsx`, snapshot 2026-04-06) at **6 days**, flagged not corrected), so joining on it directly would silently misalign against every other fact's `_period`-keyed convention. `Inventory_Fact.demand_period` (migration 0010) precomputes `_period`'s successor month for exactly this join; `Unilever_Inventory_Monthly` (same migration) exposes both `_period` and `demand_period` together so a consumer doesn't have to re-derive the relationship. |
| DEC-21 | Unilever SOH — **116 SKUs reclassified in a Feb-2025 taxonomy tidy-up; latest snapshot wins** | **DECIDED (2026-08)** | `reports/ADVISER_EVIDENCE.md`'s R9 pass found 116 SKUs whose `CATEGORY DESC` changes at least once across their snapshot history (e.g. `DRESSINGS`→`CONDIMENTS`, `SCRATCH COOKING AIDS`→`COOKING AIDS`), concentrated around Feb-2025 — a real reclassification wave, not vocabulary drift. Per R13/DEC-04-style convention, each SKU's `category_path` (`Product_Dimension`) takes its MOST RECENT snapshot's value. Explicitly **not** the same problem as Del Monte's sell_out taxonomy break (DEC-03/open items — 94 vs 57 category sets, adviser ruling still needed there): this is a bounded, identified set of individual SKUs moving between an otherwise-stable 17-20-value vocabulary, not a wholesale vocabulary replacement. |
| DEC-22 | `Product_Dimension` Unilever population — **1,807 → 2,098** | **DECIDED (2026-08)** | 291 real, non-joining Article Nos found in the Unilever SOH source (confirmed real SKUs per R8, not data errors) were inserted as new `grain='sku', principal='unilever'` rows. **`ABC_Classification`'s denominator has changed** (was computed against 1,807) **and ABC has NOT been recomputed** as of this entry — the 291 new rows have no sales history in `Unilever_SKU_Demand_Fact` and were never classified, so they sit outside both `ABC_Classification` and `Forecast_Result`'s Tier-A gate for now. Revisit before treating any Tier-A percentage/count as current if ABC is re-run against the new 2,098 population. |
| DEC-23 | SARIMA seasonal fit — **no annual seasonality found; model replacement pending adviser review** | **OPEN — evidence gathered, no model change made** | `reports/SEASONALITY_AND_BASELINES.md` + `reports/ADVISER_EVIDENCE.md` (2026-08, Unilever-only diagnosis, no refit performed): isolated lag-12 ACF significant in only 5.1% of Tier-A SKUs with ≥24 months — statistically indistinguishable from the 5% false-positive rate at α=0.05; 0/16 aggregate series (portfolio + 15 categories) show significant lag-12 ACF either; the one real quarterly (lag-3) signal found in 5 categories did not survive re-testing at quarterly resolution (0/5 significant, swallowed by the wider bound at n=11-13 quarters). Backtest (6-month walk-forward holdout, 89 SARIMA-comparable Tier-A SKUs): SARIMA is the worst of 6 methods tested (mean MASE 4.72, median 1.29, only 37.1% of SKUs beat naive-seasonal's MASE<1 bar) — a 3-month moving average alone wins outright on 31/89 SKUs vs SARIMA's 15/89. Diagnosis only; no model code changed, no refit run, nothing written to `Forecast_Result`. Decision on whether/how to replace SARIMA is the adviser's, not made here. |
| DEC-24 | ABC classification — **negative-revenue-only SKUs excluded as inactive-for-period, not Tier C** | **DECIDED (2026-09-18)** | SKUs whose only 2026-02 activity was returns (negative revenue, no gross sales) are excluded from ABC as inactive-for-period, not assigned Tier C. 69 SKUs in 2026-02. Confirmed by design, not a bug: `analytics/classification/orchestrate_abc.py`'s `_split_negative_revenue()` (169-183) clamps negative `total_revenue` to 0.0 and reports the excluded `sku_id`s; `_split_zero_revenue()` (186-199, 2026-09-17 ruling) then drops zero-revenue rows (including these clamped negatives) from `classify_abc()`'s input entirely rather than fabricating a tier. No run log survives in the repo to confirm the 69 were actually printed in `excluded_negative_revenue` on the last live run — re-run with `--quiet` off and archive the log before trusting that count operationally. |

### 5.1 Grain map (DEC-03)

| Principal | Forecasting / recommendation grain | Demand source | Why |
|---|---|---|---|
| **Unilever** | **SKU** (Product × Pack Size × Month) | `UnileverLaUnionSalesperSKU…` (MHTML) | Real per-SKU demand exists in the source. |
| **Del Monte** | **Category / brand segment** | Sell Out files (`/ACE/BASE`, `/TETRA/BASE`, …) | Sales/returns/purchases are invoice-level with **no SKU**; category is the honest supported grain. |
| Del Monte (deferred) | SKU | Inventory Sign-Off month-deltas + Purchases | *Future upgrade only.* Real derivation (`opening + purchases − closing`) under a stated assumption; limited to periods with inventory files. **Not baseline; never invoice allocation.** |

### 5.2 Source-of-truth map (DEC-04)

| Fact | Principal | **System of record (loaded)** | Demoted to cross-check (not loaded) | Dedup natural key* |
|---|---|---|---|---|
| Sales | Unilever | SSIS `RAW DATA` sheet | `INVOICE REG`, `SALES PER CUSTOMER` (same txns, other views) | invoice/reference (confirm) |
| Sales | Del Monte | Monthly Sales Register (vocab A/B/C) | Daily reports (`daily_sales_report` — different `_doc_type`, same `_sheet_role`, see DEC-07), summary echoes | `Invoice Num` (+ principal, region) |
| Sales Return | both | Sales Return files; RMR **`GS` + `BO` split** | RMR **`ONE PAGER`** (= GS ∪ BO) | `Return Slip #` / `Invoice Num` |
| Purchase | both | Purchases / Purchase Order files | — | `Invoice Num` (`BILL/…`) / PO ref |
| Inventory | both | Inventory Sign-Off | SSIS `INVENTORY` / `SOH` echoes | SKU code + snapshot date |
| Sell Out | Del Monte | Sell Out files | SSIS `SALES PER CUSTOMER` (different view) | category + period |
| Unilever SKU Demand | Unilever | `UnileverLaUnionSalesperSKU…` (sole source) | — | `sku_code` + `calendar_month` |

\* Extract QC runs a uniqueness test to confirm the true key; default to the composite shown until proven otherwise. Note the key's *column name* drifts by layout (`Invoice Num` vs `REFERENCE #` vs `REFNBR`) — canonicalized in Transform, not Extract.

**Cross-principal note:** Unilever sales live in SSIS workbooks; Del Monte sales live in Sales Register files — so there is **no cross-principal overlap**. The double-count risk is *within* a Unilever workbook (multiple sheet views) and *within* the Del Monte export set (daily vs monthly), plus the RMR one-pager trap. Extract stages all of them and tags `_sheet_role`; Transform applies this map to promote only the system-of-record.

---

## 6. Extract stage — current focus

### 6.1 Responsibility
Faithfully pull every data sheet from every raw file into a typed staging table, preserving source truth and attaching enough metadata for Transform to do its job. **Extract never changes meaning.**

### 6.2 Inputs
`data/raw/` — immutable, as-received SSM exports (~161 files, ~5-year span). Extract treats this zone as read-only.

### 6.3 Known source realities Extract must handle
(Confirmed against the actual files — verify these hold, don't assume.)

- **Format is disguised.** Sniff by magic bytes, not extension: `PK…` = xlsx; `\xD0\xCF…` = real xls (BIFF); `MIME-Ver…` = **MHTML web archive** (the Unilever La Union SKU file — quoted-printable, parse via `email` → `read_html`). CSV where present.
- **Header is not always row 1.** Observed at rows **0, 1, and 2**. Detect it (first row with ≥5 label-like cells); keep rows above it as `junk_range`.
- **≥3 column vocabularies for the same Del Monte sales register** — Extract must pull all as raw tables (renaming is Transform's job):
  - **A:** `Town Display / REFNBR / Untaxed Amount / Net Amount / Balance` (2023–2024 bulk)
  - **B:** `AREA / REFERENCE # / NET VALUE / DISCOUNT AMNT. / TAX AMNT. / AMOUNT` (2025 files, ~23 code-named sheets each)
  - **C:** `Customers / Area / Net Value / Tax amount / Amount` (2025 monthly)
  - plus minor drift: `Dscount Amount` typo, `Total Discount to be claim`, `Return Type`, `Total CAS/PCS`.
- **Multi-sheet, variable count.** Some files split by region (`PANGASINAN`/`ILOCOS`), others into ~20+ code-named sheets. **Iterate every sheet**; region comes from filename when sheet names don't carry it.
- **Redundant & scratch sheets.** SSIS workbooks hold multiple views of the same transactions (`SALES PER CUSTOMER`, `INVOICE REG`, `RAW DATA`) plus scratch (`Sheet1/2/4`). Extract pulls data sheets and **tags their role**; it does not pick which is authoritative (that's DEC-04 / Transform).
- **Type traps.** `Branch Code`/`Outlet` carry **leading zeros** (632 confirmed) → TEXT. Money fields are decimal (~99.9% conformant). `Discount Rate` is a **text label** (`Public Pricelist`, `LESS 2%`, `Less 2%`, `LESS 4% LESS 2%`), not numeric.
- **Lock files.** Skip anything starting with `~$`.

### 6.4 Processing rules
1. **Select files:** all `.xlsx/.xls/.csv` under `data/raw/`, **excluding** `~$*` and non-data files.
2. **Sniff format** by magic bytes; dispatch to the right reader.
3. **Iterate all sheets;** for each, run header detection; a sheet with no detectable data header is skipped and logged (scratch).
4. **Coerce with fidelity:** codes/identifiers → TEXT (preserve leading zeros), money → decimal, dates → date. Never let numeric coercion strip a code.
5. **Consume the totals row** as a checksum, not a data row.
6. **Emit one staging table per (file, sheet)** with the provenance contract below.
7. **Reject, don't drop:** unreadable files/sheets and checksum failures go to `staging/_rejects/` with reason + evidence.

### 6.5 Output contract (staging)
Each staged table keeps **raw column names** (no renaming) plus these provenance columns:

| Column | Meaning |
|---|---|
| `_src_file` | source filename |
| `_src_sheet` | source sheet name |
| `_header_row` | detected header row index |
| `_row_ordinal` | original row position (traceability) |
| `_principal` | `unilever` / `delmonte` / `ambiguous` (from filename + REFNBR/REFERENCE # prefix) |
| `_region` | `pangasinan` / `ilocos` / `la_union` (from filename/sheet tokens) |
| `_period` | `YYYY-MM` |
| `_doc_type` | `sales_register` / `daily_sales_report` / `purchase_order` / `sales_return` / `sell_out` / `inventory_sign_off` / `rmr_gs_bo` / `ssis_summary` / `unilever_sku` — canonical per DEC-07 |
| `_sheet_role` | `data` / `raw_data` / `per_customer_summary` / `invoice_reg` / `one_pager` / `scratch` |
| `_grain` | detected: `invoice` / `sku` / `category` / `summary` |

### 6.6 Extract QC gates (must pass to hand off)
- **Sheet accountability:** every data sheet in the file inventory is either staged or explicitly logged as skipped — zero unaccounted.
- **Type conformance:** money columns ~100% parse as decimal; no code column loses leading zeros.
- **Checksum:** per-sheet extracted `Net Amount` sum reconciles to the totals row (within tolerance) or is flagged.
- **Reject log reviewed:** every reject has a reason and evidence.
- **Determinism:** a second run is byte-identical.

### 6.7 Extract explicitly does NOT
Rename/map columns · resolve vocab A/B/C to canonical fields · dedup or choose source-of-truth · conform to dimensions · allocate SKUs or resolve grain · compute any analytics. All of that is Transform or later.

---

## 7. Downstream (placeholders — expand later)

- **Transform:** apply `column_maps`/`alias_tables` to map A/B/C → canonical schema; dedup and apply DEC-04 source-of-truth; resolve DEC-03 grain per principal; conform to dimensions; standardize discount labels, regions, doc-type prefixes.
  - **Remaining gaps blocking a safe run (2026-07):**
    - ~~(1) `doc_type` naming mismatch across config layers~~ — **CLOSED.** DEC-07 applied: `source_of_truth.yaml` and `column_maps/*.yaml` now use Extract's real staged `_doc_type` values exactly; `tests/test_transform_config.py` gates against regressions in either direction.
    - ~~(2) no column maps for `daily_sales_report` / `rmr_gs_bo`~~ — **CLOSED.** Both written from real `staging/_manifest.json` evidence. `daily_sales_report` turned out to have two distinct sheet shapes (per-day transactional, leaner than Sales Register vocab A; one SCHEDULE rollup/workbook) — documented in the map file itself.
    - ~~(3) no Extract driver for `ssis_summary`~~ — **CLOSED (2026-07, T3 Option A).** Decision: build the extractor (confirms DEC-04). `analytics/etl/extract/ssis_summary.py` added as the 7th family driver. `driver.py` updated to include `parse_ssis_summary` in `FAMILY_PARSERS`. `RAW DATA` sheets → `sheet_role=raw_data` (the promoted fact); `Invoice Reg`, `Per Customer Summary`, scratch tabs staged for auditability only; Transform/DEC-04 decides which roles are loaded.
    - (4) **Partially CLOSED (2026-08, story #16 Steps 0-4; further closed same day by DEC-11/DEC-12).** The Load-blocking correctness gaps are fixed: `transform.backfill_provenance_fields()` now populates bare `principal`/`region` from Extract's `_principal`/`_region` provenance (previously neither existed as real columns, so every fact's `NOT NULL principal` would have failed at Load); `filter_source_of_truth()` now actually enforces `cross_check_doc_types` (previously parsed but never applied); `config/source_of_truth.yaml`'s natural keys for inventory/sell_out/purchase/sales_return now match `schema.sql`'s literal `UNIQUE` constraints (previously missing `region`/`principal` columns, which would have silently collapsed real cross-region rows); `granularity.resolve_unilever_sku_grain()` now matches Transform's actual output schema (`sku_code`/`calendar_month`, was `sku_id`/`date`) with a month-grain continuity check (was day-grain, itself a fabricated assumption against a monthly source); `granularity.resolve_delmonte_category_grain()` now rejects wrong-`_doc_type` input per DEC-03. `analytics/etl/_coerce.py` (new) shares numeric-coercion logic between Extract and Transform rather than risking a second DEC-07-class drift. See tests/etl/test_transform.py, tests/etl/test_granularity.py.
      - **Dimension conformance timing — DECIDED (2026-08), see DEC-09.** `product_key`/`date_key` resolution happens in Load (lookup-or-insert), not Transform — Transform stays DB-free.
      - **`unilever_sku` source file delivered and verified (2026-08, later same day).** `UnileverLaUnionSalesperSKU2023to2026.xls` was found and placed in `data/raw/Unilever/` — the real Extract run now stages 1 file / 24,906 rows / 0 rejects for this doc_type (was 0 rows). Two bugs blocked this until fixed: (1) `lxml` was never in `requirements.txt` despite being required for `pandas.read_html` to parse the MHTML content — added. (2) `profiling/profile_files.py`'s `DOC_TYPE_PATTERNS`/`REGION_PATTERNS` `la.union` regex required a separator character between "La" and "Union" that the real filename doesn't have (`UnileverLaUnionSalesperSKU...`) — the file was silently never selected for processing at all (0 files matched, 0 rejects, nothing attempted). Widened to `la[\s_]*union` in both places. These patterns are marked "frozen, already reviewed" elsewhere in the codebase — that review predates ever having the real file to test against, so the freeze was based on an untested assumption, not a lock on model output others need to fix.
        - `transform_fact()` runs end-to-end cleanly against the real data: 24,906 in, 24,906 out, 0 duplicate groups, 0 numeric-coercion failures.
        - **`quantity_sold` mapping — CLOSED, see DEC-11.** Both `sale_quantity_cases` (58/24,906 null) and `sale_quantity_pieces` (71/24,906 null) are populated; `pack_size` has 0 nulls. `cases × pack_size ≈ pieces` matches within 0.5 units for **84.1%** of rows (20,897/24,835) — real but imperfect, not clean enough to treat `cases × pack_size` as the value of record. `transform.normalize_quantities()` now sets `quantity_sold` from `sale_quantity_pieces` directly; the cases×pack_size comparison is kept as a QC cross-check, not the source of truth.
        - `resolve_unilever_sku_grain()` runs without error against the real transformed output and correctly reports `ok=False` with **4,473 SKU-months with a gap** in an otherwise-continuous run — a real characteristic of the data (SKUs introduced/discontinued mid-period), not a bug; relevant input for E07's "exclude SKUs with insufficient history" story (#50) once that's built.
      - **New findings from attempting real-data verification (2026-08), not yet fixed, out of scope for story #16 Steps 0-4:**
        - `transform.apply_column_map()` produces **duplicate column labels** (breaking `dedup_facts()`'s `groupby`) when handed a batch spanning more than one Sales Register vocabulary era at once (e.g. `Invoice Num`/`REFNBR`/`REFERENCE #` all present simultaneously after concatenating 2023+2024+2025 staged sheets — all three rename to `invoice_num`, same for `region`/`untaxed_amount`/`discount_amount`/`tax_amount`/`net_amount`). This directly contradicts backlog story #11's "Check" status ("three Sales Register column vocabularies resolved by year") — confirmed via `staging/sales_register/*.parquet` that they are not safely resolved when combined into one real batch, only when handled one file/sheet at a time.
        - **CLOSED, confirmed stale (2026-09-11, Phase 1 step 2c).** `inventory_sign_off`'s named-column shape (`PRODUCT/ SKU CODE`, `DESCRIPTION`, `ITEM CODE`, `ITEM DESCRIPTION`, `CATEGORY`) IS covered — not by `column_maps/inventory_sign_off.yaml` (still true that file never references them), but by `transform.route_inventory_sku_shapes()`/`_classify_inventory_sku_shape()` (shape "C": `ITEM CODE`→`sku_code`, `ITEM DESCRIPTION`→`product_name` direct copy, `transform.py:784-798`), built after this note was written. Verified against real data: 5,591 real rows split `matched` 4,961 / `direct` (shape C) 411 / `source_gap` (shape D, genuinely no SKU in source) 173 / `unmatched` 46 — 99.2% accounted for. Of the 46, **29** are `sku_description_raw == "Total"` (a per-sheet TOTAL/footer row) and **2** are `"#REF!"` (a broken Excel formula reference, zero real data) — the same TOTAL-row defect class already fixed in `sales_register`/`sales_return`/`sell_out`, now fixed here too via the shared `analytics.etl.transform.exclude_footer_rows()` (`reports/PHASE1_EXECUTION_PLAN_2026-09.md`, step 2e). **The remaining 15 are NOT the same thing** — checked before excluding anything further: every one carries real `quantity_on_hand`/`cost`/`valuation` data (12 with `sku_description_raw=NULL`, 1 `"DESCRIPTION"` — large magnitude, ~2,535 cases/₱2.6M, looks like a section subtotal not a footer — and 2 `"WH/Stock"`/`"IS-WH/Stock"`, similarly large). Excluding these without understanding what they are would risk dropping real inventory data — left as `sku_code_status='unmatched'`, flagged, not guessed at, not fixed.
        - **CLOSED, confirmed stale (2026-09-09, Phase 1 step 1).** `sell_out`'s `category_path` DOES map from `__col0__` and matches real staged data — 129 real sell_out sheets promote cleanly with no unmapped-canonical block; live `sellout_fact_real` has `category_path` populated for all 98 real categories. See `reports/PROJECT_STATE_2026-09.md` §8.
        - **SUPERSEDED (2026-09-11, Phase 1 step 2b) — this is now fixed, not left as-is.** The `region == "False"` `purchase_order` defect was traced further: it's not just informational — it silently blocked the real `_region` provenance from ever filling `region` (`backfill_provenance_fields` only fills true nulls, and the literal string `"False"`/bool `False` is not null), and the same defect was already present in **223/353 live real `purchase_fact` rows** before this fix. `region: ["Town Display"]` removed from `column_maps/purchase_order.yaml`; `region` now populates cleanly from `_region` (100%, zero `'False'`) for all future transform runs. The 223 already-live rows are unchanged (no DB writes in Phase 1) — tracked as `PROJECT_STATE_2026-09.md` §6 decision item 19 for the Phase 1d cutover diff.
    - (5) **CLOSED (2026-08, pre-Supabase-creation review).** `schema.sql`/`models.py` reviewed against real data before first-ever execution against a live database (never run before this). Four fixes, all mirrored in both files (a bare drift-in-sync bug was also found and fixed: `models.py` had two stacked module docstrings before `from __future__ import annotations`, an actual `SyntaxError` — this file had never been successfully imported by anyone before now):
      - `Sales_Fact` restricted to Del Monte only — see DEC-10 for the full rationale and the `ssis_summary`-orphaning consequence (quantified: ~694 MB if ever given a destination table, vs ~16 MB for everything else combined).
      - `SalesReturn_Fact` dropped `invoice_num` from its `UNIQUE` constraint (confirmed 0/538 real rows ever populate it — Postgres `UNIQUE` treats `NULL <> NULL`, so it was a silent no-op, not real protection). **`config/source_of_truth.yaml`'s `sales_return.both.natural_key` updated to match** — this is exactly the "config says one key, DDL says another" drift class DEC-07 was about; caught only because the size-estimation work below happened to re-run `transform_fact()` for `sales_return` and it crashed.
      - `Unilever_SKU_Demand_Fact` gained a `net_amount` column — `classify_abc()` requires `total_revenue` per SKU and this is the only Unilever SKU-grain fact table; it had no revenue field at all before this. Confirmed via grep this table is otherwise untouched, safe to add. Note recorded: Unilever's `ABC_Classification` rows will be SKU-grain, Del Monte's category-grain — both legitimately coexist via `Product_Dimension.grain`, expected DEC-03 behavior, not a bug.
      - `BO_Monitoring_View` redefined value-based (`SUM(SalesReturn_Fact.net_amount WHERE return_type='BO') / SUM(Purchase_Fact.net_amount)`) instead of unit-based — `bo_units` has no source column anywhere in real RMR data and never will (confirmed, same file family as the `invoice_num` finding above), so the old unit-based `bo_rate` was permanently unrecoverable, not a temporary gap. Also noted: `analytics/optimization/lp.py`'s `w3` objective term is implemented as generic `storage_cost_i * Q_i`, not spoilage/BO-linked at all, despite the manuscript calling it "spoilage cost" — no BO term exists anywhere in the LP objective at any grain. Fixed again same day: `BO_Monitoring_View` had a fan-out bug (Purchase_Fact/SalesReturn_Fact joined many-to-many before aggregating) — rewritten with each side pre-aggregated in its own CTE before the join.
      - **Database size estimated before creation (2026-08):** ~15.3 MB for the real current schema (6 fact tables + 5 dimensions; `Inventory_Fact`/`SellOut_Fact` sized from raw staged counts as an upper bound since their real Transform output is still blocked — see item (4)'s findings above, not yet fixed). Comfortably within Supabase free tier (500 MB, ~3% used). `ssis_summary`'s hypothetical table would alone be ~694 MB — see DEC-10.
    - (6) **PARTIALLY CLOSED (2026-08):** there was no way for a human to actually *see* Transform's output before Load — Extract had `driver.py` + `staging/_manifest.json` + `staging/_review.html`, Transform had only bare functions. `analytics/etl/transform_driver.py` (new) closes the reviewability half: it runs `transform_fact()` for every `(fact, principal)` `source_of_truth.yaml` declares, classifies every staged sheet as promoted/demoted/conflict/blocked (zero silent skips, matching the QC gate bullet below exactly), and writes `transform/_manifest.json` in the same shape `extract/_shared.py::build_manifest()` uses — so `analytics.etl._review.render_review("transform")` renders it with the same viewer Extract already has (`_review.py`'s `STATUS_LABELS` makes the viewer itself stage-aware, since Transform's `promoted`/`demoted` vocabulary isn't Extract's `pass`/`mismatch`/`unverified`). **Unverified against the real corpus** at the time this was written — tested against small synthetic staged parquet fixtures only (`tests/etl/test_transform_driver.py`); real-corpus verification is still owed once this lands on a branch with `data/raw/` present. Reviewability alone isn't a gate, though — nothing stopped Load from running whether or not anyone actually looked. `analytics/etl/transform_signoff.py` (new) closes that half: it builds a checklist from `transform/_manifest.json` (zero-silent-skips, promoted/demoted/conflict/blocked counts, row-count reconciliation against `staging/_manifest.json`, conflicts and blocked items listed for review — blocked items split into *expected*, e.g. `ssis_summary`'s known `natural_key: null` gap, vs *unexpected*, anything else) and only writes `transform/_signoff.json` when a person runs it with an explicit `--decision {approved,rejected} --by "<name>"` — there is no default/auto-approve path, and a bare run only previews the checklist. `load.py::check_signoff_gate()` (new; `load_to_supabase()` gains an optional `transform_dir` param, opt-in like DEC-14's `manifest_path`) blocks Load unless an `"approved"` sign-off exists whose `manifest_fingerprint` matches the *current* manifest — a stale sign-off from before a Transform re-run doesn't count, and a `"rejected"` decision blocks just as hard as no decision at all. Field naming (`decision`/`decided_by`/`decided_at`) mirrors `schema.sql`'s existing `LP_Recommendation.status`/`decided_at`/`decided_by` pattern rather than inventing a new shape. Same real-data caveat — unverified end-to-end, synthetic fixtures only (`tests/etl/test_transform_signoff.py`).
  - **Transform QC gate (must pass before Load):** 0 config lookup errors; every staged sheet accounted for (promoted / demoted / rejected-with-reason — zero silent skips); dedup uniqueness tests pass; row counts reconcile to Extract QC totals; deterministic re-run. As of 2026-08 this is backed by real code (`transform_driver.py`, see (6) above) rather than only a documented checklist.
- **Load / Warehouse:** Supabase/Postgres. Transaction mart (invoice grain) + product mart (SKU grain) per DEC-02. Idempotent upserts on natural keys; money `NUMERIC(14,2)`; codes TEXT.
  - **Gating rule:** Supabase project setup, DDL (`schema.sql`), and `Date_Dimension` seeding are **parallel-safe** and may proceed now — they depend only on the schema, not on Transform. The Load run itself is **hard-gated** on the Transform QC gate above; running Load first would crash on unmapped doc_types or persist misaligned data. Load evidence required: idempotency proof (second run inserts 0 rows), FK integrity, and a spot-check provenance walk-back curated → staging → source cell.
- **Analytics:** ABC/Pareto → SARIMA (statsmodels) → safety stock & ROP → LP optimization (PuLP, w₁=0.45, w₂=0.35, w₃=0.20). Results stored as `Forecast_Result`, `LP_Recommendation`.
- **Serving:** FastAPI backend, Next.js + Tailwind dashboard.

---

## 8. Status & change log

### Current status (2026-08)
- **Extract: DONE and verified, all 7 families including `ssis_summary`.** Full corpus staged and re-verified 2026-08 with the real event log (`analytics/etl/events.py`, `DSD_EVENTS=1`): `sales_register` 23,817 rows, `unilever_sku` 24,906, `inventory_sign_off` 7,019, `sell_out` 1,573, `purchase_order` 544, `rmr_gs_bo` 538, `ssis_summary` 1,949,687 — 2,008,084 rows total, 0 rejects across all 7 families. `tests/etl/test_extract.py` is 46/46 (not 49 — corrected here after checking directly; don't recite the old number). QC artifacts: `staging/_extract_qc.md`, `staging/_review.html`, and (opt-in, `DSD_EVENTS=1`) `staging/_events.jsonl` + `staging/_timeline.html` for a live/replay view of a run.
- **Transform: DEC-07 vocabulary fixed; §16 Steps 0-4 correctness/wiring gaps closed; DEC-11/DEC-12 (unit + period normalization) landed; a real driver exists (`transform_driver.py`, §7 item 6) but has not yet been run against this branch's real corpus.** `backfill_provenance_fields`, natural-key fixes, `cross_check_doc_types` enforcement, and the `granularity.py` schema bridge are all done and tested (see §7 item 4). `transform_driver.py`/`transform_signoff.py` (merged from `thea/updates`, 2026-08) close the reviewability/sign-off gap but were built and tested against synthetic fixtures only, in an environment with no `data/raw/` — real-corpus verification on this branch is still owed, not assumed done just because the code merged cleanly. Real-data verification (this branch) also surfaced three `apply_column_map()`/column-map gaps still unfixed (multi-vocab column collision in `sales_register`, incomplete `inventory_sign_off` header coverage, unmatched `sell_out` category_path) — `purchase_order` verified cleanly end-to-end against real staged data (544 rows in, 427 after dedup, 92 duplicate groups collapsed, 0 conflicts).
- **Load: written, never run against a live DB.** `schema.sql`/`models.py` reviewed and fixed against real data (2026-08, see §7 item 5) but still never executed against an actual database — Supabase project creation is the next concrete step, guided by `SUPABASE_SETUP.md`. Hard-gated on the Transform QC gate for real fact loads; DDL creation and `Date_Dimension` seeding remain parallel-safe.
- **Analytics / backend:** ABC, SARIMA, LP, and FastAPI scaffolding are code-complete-looking but **unverified end-to-end** — none has run against real staged/loaded data. Router files are stubs (no endpoint logic yet).
- **Process note:** Transform work proceeded past the Extract review checkpoint. Recorded here not to assign fault but because the doc_type drift it caused (DEC-07) is exactly the failure class the checkpoint exists to catch — checkpoints are reaffirmed as blocking for all future stage transitions.

### Change log
- **2026-08 (merge, AUDREY-TRY-MERGE + thea/updates):** Both branches independently added decisions numbered DEC-09/DEC-10 for unrelated things. Kept this branch's DEC-09 (dimension FK timing) and DEC-10 (`Sales_Fact` scope) as-is since other files already cite them by number; renumbered `thea/updates`'s five new decisions to DEC-11 through DEC-15 (unit normalization, period normalization, `Product_Demand_View`, reject-rate gate, quantity flagging) and fixed their internal cross-references to match. §7's gap list item (5) also collided (schema.sql review vs. Transform reviewability tooling, two unrelated things) — kept schema.sql review as (5), Transform driver/sign-off tooling renumbered to (6).
- **2026-08 (pre-Supabase-creation schema review, same day as story #9/#16 work):** `schema.sql`/`models.py` fixed against real data before ever being run — see §7 item 5 for full detail. DEC-09 decided (load-time lookup-or-insert), DEC-10 added (`Sales_Fact` Del Monte-only, `ssis_summary` orphaned, quantified at ~694 MB if ever given a destination). Fixed a real, previously-undiscovered bug: `models.py` could not be imported at all (stacked docstrings before `from __future__ import annotations`). `SUPABASE_SETUP.md` added (project creation walkthrough). Database size estimated (~15.3 MB current schema, comfortably within free tier) before creating the actual project. Manuscript errata logged separately below.
- **2026-08 (story #9, same day as Steps 0-4):** `UnileverLaUnionSalesperSKU2023to2026.xls` delivered and placed in `data/raw/Unilever/`. Fixed two bugs blocking it from staging: missing `lxml` dependency (added to `requirements.txt`), and a `la.union` regex in `profiling/profile_files.py` (`DOC_TYPE_PATTERNS` + `REGION_PATTERNS`) that didn't match the real filename's no-separator "LaUnion" — widened to `la[\s_]*union`. Real Extract re-run now stages 24,906 rows / 0 rejects for `unilever_sku` (was 0). Removed the now-resolved temporary exemption in `tests/test_transform_config.py`. Verified `transform_fact()` and `resolve_unilever_sku_grain()` end-to-end against the real data — see §7 item 4's unilever_sku sub-bullet for the cases-vs-pieces evidence gathered (closed by DEC-11) and the 4,473 real month-gaps found.
- **2026-08 (story #16, Steps 0-4):** Closed the Load-blocking correctness gaps in `transform.py`/`granularity.py`: `backfill_provenance_fields()` (new), `filter_source_of_truth()` now enforces `cross_check_doc_types`, 4 natural-key fixes in `source_of_truth.yaml` (inventory/sell_out/purchase gained missing `region`/`principal`; sales_return now matches `schema.sql`'s literal 5-tuple), `resolve_unilever_sku_grain()`/`resolve_delmonte_category_grain()` schema/guard fixes. New shared `analytics/etl/_coerce.py`. `unilever_sku` numeric coercion + calendar_month reformat implemented but fixture-tested only — the La Union SKU source file is confirmed not yet delivered, so unverified against real data; its quantity_sold mapping (cases vs pieces) is left an explicit unresolved TODO per `UNILEVER_QUANTITY_FIELD_CANDIDATES`. Added DEC-09 (dimension FK timing, deferred). `tests/test_transform_config.py`'s exemption list corrected: `daily_sales_report` permanent (confirmed no matching files in corpus), `unilever_sku` temporary/pending-data (not naming drift), stale `ssis_summary` exemption removed (T3 now stages real rows, exemption was a no-op). Real-data verification against `staging/*.parquet` surfaced 3 new pre-existing gaps out of scope for this change — see §7 item 4's "New findings" — most notably that backlog story #11's "three vocabularies resolved" Check status doesn't hold when files from different eras are combined in one batch, only file-by-file.
- **2026-08 (DEC-15):** `clean.py::flag_quantity_issues()` added — zero,
  negative, and IQR-outlier quantities are flagged (never dropped or
  clamped) per fact's real quantity column(s). Wired into
  `transform_driver.py`'s manifest (`quantity_issues` section) and
  `transform_signoff.py`'s sign-off checklist, not persisted to
  `schema.sql` — routed through the M2 QC/sign-off tooling already built
  this session rather than a new schema change.
- **2026-08 (§7 gap 6, sign-off):** `analytics/etl/transform_signoff.py`
  added — an M2 sign-off checklist requiring an explicit, named human
  decision (`approved`/`rejected`) before Load will run, not just an
  inspectable artifact. Recorded decisions are tied to a manifest
  fingerprint so a stale approval from before a Transform re-run is never
  silently accepted. `load.py::check_signoff_gate()` enforces it via
  `load_to_supabase()`'s new optional `transform_dir` parameter, alongside
  DEC-14's existing reject-rate gate.
- **2026-08 (§7 gap 6):** `analytics/etl/transform_driver.py` added — a
  Transform-stage QC driver (the "M2 gate") mirroring `extract/driver.py`:
  runs `transform_fact()` per `(fact, principal)`, classifies every staged
  sheet as promoted/demoted/conflict/blocked, writes
  `transform/_manifest.json`. `transform_fact()`'s report dict gained a
  `mapped_df` key (pre-dedup, post-column-map, provenance intact) so the
  driver can trace a dedup conflict back to its source sheet(s) without
  reimplementing the pipeline. `_review.py::render_review()` generalized
  (`STATUS_LABELS`) so the same HTML viewer renders Transform's
  promoted/demoted vocabulary honestly instead of mislabeling it as
  Extract's checksum pass/mismatch/unverified. Unverified against the real
  corpus at the time this was written — no source data available in that
  environment; real-corpus verification still owed.
- **2026-08 (DEC-14):** Reject-rate validation gate added —
  `load.py::check_reject_rate_gate()` / `compute_reject_rate()` block Load
  when Extract's reject rate (sheet/file-level only, from
  `staging/_manifest.json`) crosses 2%, a team-chosen default with no
  panel/adviser source (manuscript checked — only comparable gate is the
  unrelated MAPE < 20% forecast check). `load_to_supabase()` gains an
  optional `manifest_path` to enforce it before any DB write.
- **2026-08 (DEC-13):** `Product_Demand_View` added (`schema.sql` §6) —
  unifies `Unilever_SKU_Demand_Fact` and `SellOut_Fact` into one read
  shape for downstream models via `Product_Dimension.product_key`,
  without physically merging storage (DEC-02 unchanged, still PROPOSED).
  Carries an explicit `quantity_unit` column so callers can't silently
  treat Unilever's confirmed-pieces `quantity` as comparable to Del
  Monte's unconfirmed-unit one. Not ORM-mapped, same as `BO_Monitoring_View`.
- **2026-08 (DEC-12):** Period-key normalization — `transform.reformat_calendar_month()`
  fixes `Unilever_SKU_Demand_Fact.calendar_month`'s raw `"MM.YYYY"` shape;
  `granularity.py::resolve_unilever_sku_grain()`'s required columns/gap-
  check fixed to match real Transform output and monthly grain (was
  `{"sku_id", "date", ...}`, an analytics-layer/daily-grain mismatch);
  `Inventory_Fact` gains a real `_period` column as its join key, and
  `snapshot_date` is now an explicitly synthetic first-of-`_period`
  marker (`schema.sql`/`models.py` updated) instead of an invalid raw
  `'YYYY-MM'` string. See DEC-12 above.
- **2026-08 (DEC-11):** Unit-of-measure normalization added —
  `transform.normalize_quantities()` sets `Unilever_SKU_Demand_Fact.quantity_sold`
  from reported `sale_quantity_pieces` (cases×pack_size kept as a QC
  cross-check only, ~84% agreement) and adds
  `Inventory_Fact.quantity_pieces` from Del Monte's `PCS` column
  (`schema.sql`/`models.py` updated); `cases`/`packages` conversion and
  Sell Out's `quantity`/`quantity_cases` are explicitly left unconverted
  pending pack_size evidence — see DEC-11 above and the per-field notes in
  the relevant `column_maps/*.yaml`.
- **2026-07 (T3):** `ssis_summary` extractor built — Option A confirmed (DEC-04 unchanged). `analytics/etl/extract/ssis_summary.py` added as the 7th family driver; `driver.py` `FAMILY_PARSERS` updated; `__init__.py` documented. File-selection reuses the existing `ssis_summary` pattern in `DOC_TYPE_PATTERNS`; all Extract QC gates (header detection, sheet-role tagging, column coercion, provenance stamping, checksum) reuse `_shared.py` unchanged.
- **2026-07 (later):** DEC-07 applied — `source_of_truth.yaml` doc_type labels and `column_maps/*.yaml` filenames renamed to match Extract's real staged tags exactly; added the previously-missing `sales_unilever_sku_demand` fact entry; introduced `cross_check_doc_types` (fixes the same drift class for `daily_sales_report` and the `ssis_summary` cross-check references under Inventory/Sell Out); added `column_maps/daily_sales_report.yaml` and `column_maps/rmr_gs_bo.yaml`, both evidence-based from real staged output; added `tests/test_transform_config.py` as a permanent regression gate.
- **2026-07:** Added DEC-07 (canonical doc_type vocabulary — DECIDED) and DEC-08 (EOQ — OPEN pending verification of the actual panel requirement; not present in any scribe's notes on record). Expanded §7 Transform/Load placeholders with known gaps, Transform QC gate, and Load gating rule. Updated status to reflect Extract completion.
- **2025-07:** DEC-03 (grain) and DEC-04 (source-of-truth) closed — see §5.1 / §5.2.

### Still open
- **DEC-02** (two-marts model) and **DEC-06** (SCD Type 1): move PROPOSED → DECIDED as Transform/Load work formally begins.
- **DEC-08** (EOQ): verify the requirement's source before any model or manuscript change.
- **DEC-10's `ssis_summary` question**: does Unilever sales ever need to be a fact table (not just SKU demand)? Costs ~694 MB if yes — an explicit scope/budget decision, not a default build.
- `Unilever_SKU_Demand_Fact.quantity_sold` mapping (cases vs pieces) — evidence gathered (§7 item 4), not yet decided.
- ~~DEC-09~~ — **CLOSED (2026-08).** Load-time lookup-or-insert.
- ~~`ssis_summary` extraction~~ — **CLOSED (T3 Option A, 2026-07).** Extractor built; DEC-04 confirmed. (Its *load destination* is the still-open DEC-10 question above — extraction and destination are separate questions.)
- `transform.py` / `granularity.py` line-by-line reconciliation against §4/§5.2 (checklist T4) — largely done (§7 item 4); the Transform driver itself (wiring it all together) is not yet built.
- `inventory_sign_off` / `sell_out` column-map gaps (§7 item 4's "New findings") — block real Transform output for those two facts; `Inventory_Fact`/`SellOut_Fact` sizing above used raw staged counts as an upper bound because of this.

### Manuscript errata (logged 2026-08, not yet corrected in the manuscript itself)
- Sec 3.4.1.1 states "five (5) years... spanning 2020 to 2025." Real data confirmed this session runs 2021 through 2026 — 2020 does not exist anywhere in the corpus, and the corpus extends a year past the manuscript's stated end date.
- Table 3.3.1 (Fact Tables) lists 5 tables and omits `Unilever_SKU_Demand_Fact` entirely, despite it being DEC-03-required and already built (a 6th real fact table). `Forecast_Result` and `LP_Recommendation` also aren't listed as tables anywhere in §3.3, though they're discussed narratively elsewhere and exist in `schema.sql`.
- `CAPSTONE 3ISA GROUP 7 DOCUMENTS.pdf` §3.2.3 describes `SellOut_Fact`'s FKs as connecting to `Date_Dimension` and a `Product_Category_Dimension`. That table doesn't exist and was never built — DEC-03 replaced the idea of a separate category dimension with one `Product_Dimension` distinguished by its own `grain` column (`'sku'` vs `'category'`), so `SellOut_Fact.product_key` points at a `grain='category'` row in the same table Unilever's SKU rows live in, not a second dimension table.
