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
| DEC-02 | Product dimension does **not** conform across all facts → model as **two marts** | **PROPOSED** | Invoice-grain facts (Sales/Purchase/SalesReturn) have no SKU key. `Product_Dimension` joins only to Inventory/SellOut/Unilever-SKU. Call this a *transaction mart* + *product mart*, not one clean constellation. |
| DEC-03 | **Recommendation grain per principal** | **DECIDED (2025-07)** | **Unilever = SKU** (La Union per-SKU file has real SKU demand). **Del Monte = category/brand** (from Sell Out; invoice-level sales carry no SKU, and allocating would be fabrication). SKU-level Del Monte via inventory-delta proxy is a **deferred future upgrade** (Option B), not baseline. See §5.1. Defensible claim: *"we forecast at the grain each principal's data honestly supports."* |
| DEC-04 | **Source-of-truth per fact per principal** | **DECIDED (2025-07)** | One authoritative source per fact; overlapping views demoted to reconciliation cross-checks (never loaded). Prevents double/triple-counting. Full map in §5.2. Dedup natural key confirmed by a uniqueness test during Extract QC. |
| DEC-05 | Totals-row used as extraction **checksum** | **DECIDED** | Row-0 sums validate that extraction lost/added nothing. |
| DEC-06 | SCD strategy = Type 1 (overwrite) for dimensions | **PROPOSED** | Acceptable for demand forecasting (we care about the time series, not attribute history). Revisit if customer/salesman reassignment matters. |
| DEC-07 | Canonical `doc_type` vocabulary = Extract's staged `_doc_type` tags | **DECIDED (2026-07), applied (2026-07)** | Three vocabularies drifted apart (Extract tags vs `source_of_truth.yaml` labels vs `column_maps/*.yaml` filenames), breaking `load_column_map()` lookups. The staged tags win because they are already validated against the real corpus. `source_of_truth.yaml` and column-map filenames renamed to match (`purchases`→`purchase_order`, `inventory`→`inventory_sign_off`, `inventory_signoff.yaml`→`inventory_sign_off.yaml`); a `sales_unilever_sku_demand` fact entry was added (previously missing entirely). A second instance of the same bug class was found and fixed while applying this: `cross_check_roles` (a `_sheet_role` list) was being used to name *doc_types* (`ssis_summary`) — moved to a new `cross_check_doc_types` field, which also now documents `daily_sales_report` as a demoted duplicate of `sales_register` (both share `_sheet_role="data"`, so role alone can't distinguish them). `tests/test_transform_config.py` (new) asserts every staged `_doc_type` has a column map + source-of-truth entry, and the reverse — no config entry names a doc_type Extract never actually staged. |
| DEC-08 | EOQ inclusion in the prescriptive model | **OPEN — verify first** | EOQ does **not** appear in any of the three panel scribe's notes on record. Before adding: confirm the exact panel/adviser requirement (verbal comment? RRL conflation?). If confirmed, EOQ enters as a **benchmark/reference quantity** that the multi-objective LP refines under SSM's real constraints — never as a second, competing order-quantity decision alongside LP. Log framing + source here when resolved. |

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
    - (4) **Still open:** `transform.py` and `granularity.py` were written ahead of the Extract review checkpoint and require line-by-line reconciliation against §4 and §5.2 before first run — the doc_type-vocabulary fix above is necessary but not sufficient; the actual transform/dedup/grain logic itself is unreviewed.
  - **Transform QC gate (must pass before Load):** 0 config lookup errors; every staged sheet accounted for (promoted / demoted / rejected-with-reason — zero silent skips); dedup uniqueness tests pass; row counts reconcile to Extract QC totals; deterministic re-run.
- **Load / Warehouse:** Supabase/Postgres. Transaction mart (invoice grain) + product mart (SKU grain) per DEC-02. Idempotent upserts on natural keys; money `NUMERIC(14,2)`; codes TEXT.
  - **Gating rule:** Supabase project setup, DDL (`schema.sql`), and `Date_Dimension` seeding are **parallel-safe** and may proceed now — they depend only on the schema, not on Transform. The Load run itself is **hard-gated** on the Transform QC gate above; running Load first would crash on unmapped doc_types or persist misaligned data. Load evidence required: idempotency proof (second run inserts 0 rows), FK integrity, and a spot-check provenance walk-back curated → staging → source cell.
- **Analytics:** ABC/Pareto → SARIMA (statsmodels) → safety stock & ROP → LP optimization (PuLP, w₁=0.45, w₂=0.35, w₃=0.20). Results stored as `Forecast_Result`, `LP_Recommendation`.
- **Serving:** FastAPI backend, Next.js + Tailwind dashboard.

---

## 8. Status & change log

### Current status (2026-07)
- **Extract: DONE and verified (6 families) + T3 Option A added (7th family).** Full corpus staged (161 files / 72,046 rows across 6 document families), 49/49 tests, checksum-verified, byte-identical determinism, 0 unresolved rejects. QC artifacts: `staging/_extract_qc.md` + HTML review viewer. `ssis_summary` driver added (2026-07, T3); run against real data pending placement of the ~60 SSIS workbooks in `data/raw/`.
- **Transform: config vocabulary fixed (DEC-07); pipeline logic still NOT safe to run.** The doc_type naming mismatch, the two missing column maps, and the ssis_summary extractor gap (T3) are all closed (see §7). Still blocking: `transform.py`/`granularity.py` still need line-by-line reconciliation against §4/§5.2 before a first real run (T4).
- **Load: written, never run against a live DB.** Hard-gated on the Transform QC gate; Supabase setup itself is parallel-safe and proceeding.
- **Analytics / backend:** ABC, SARIMA, LP, and FastAPI scaffolding are code-complete-looking but **unverified end-to-end** — none has run against real staged/loaded data. Router files are stubs (no endpoint logic yet).
- **Process note:** Transform work proceeded past the Extract review checkpoint. Recorded here not to assign fault but because the doc_type drift it caused (DEC-07) is exactly the failure class the checkpoint exists to catch — checkpoints are reaffirmed as blocking for all future stage transitions.

### Change log
- **2026-07 (T3):** `ssis_summary` extractor built — Option A confirmed (DEC-04 unchanged). `analytics/etl/extract/ssis_summary.py` added as the 7th family driver; `driver.py` `FAMILY_PARSERS` updated; `__init__.py` documented. File-selection reuses the existing `ssis_summary` pattern in `DOC_TYPE_PATTERNS`; all Extract QC gates (header detection, sheet-role tagging, column coercion, provenance stamping, checksum) reuse `_shared.py` unchanged.
- **2026-07 (later):** DEC-07 applied — `source_of_truth.yaml` doc_type labels and `column_maps/*.yaml` filenames renamed to match Extract's real staged tags exactly; added the previously-missing `sales_unilever_sku_demand` fact entry; introduced `cross_check_doc_types` (fixes the same drift class for `daily_sales_report` and the `ssis_summary` cross-check references under Inventory/Sell Out); added `column_maps/daily_sales_report.yaml` and `column_maps/rmr_gs_bo.yaml`, both evidence-based from real staged output; added `tests/test_transform_config.py` as a permanent regression gate.
- **2026-07:** Added DEC-07 (canonical doc_type vocabulary — DECIDED) and DEC-08 (EOQ — OPEN pending verification of the actual panel requirement; not present in any scribe's notes on record). Expanded §7 Transform/Load placeholders with known gaps, Transform QC gate, and Load gating rule. Updated status to reflect Extract completion.
- **2025-07:** DEC-03 (grain) and DEC-04 (source-of-truth) closed — see §5.1 / §5.2.

### Still open
- **DEC-02** (two-marts model) and **DEC-06** (SCD Type 1): move PROPOSED → DECIDED as Transform/Load work formally begins.
- **DEC-08** (EOQ): verify the requirement's source before any model or manuscript change.
- ~~`ssis_summary` resolution~~ — **CLOSED (T3 Option A, 2026-07).** Extractor built; DEC-04 confirmed.
- `transform.py` / `granularity.py` line-by-line reconciliation against §4/§5.2 (checklist T4) — not yet done.
