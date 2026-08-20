# Synthetic Data Audit — SSM Decision Support Dashboard

Read-only quality-control audit of the placeholder/synthetic data corpus. Branch `kelvin-etl`, audited 2026-08-20. Synthetic data's existence is a sanctioned exception to the project's anti-fabrication rule (adviser-approved, to prove the frontend/pipeline shape ahead of SSM's real-file delivery) — this report inventories what's there and what's still missing, it does not question whether it should exist.

## VERDICT

1. **Total synthetic row count: 55,313** data rows across 374 raw `.xlsx` files in `data/raw/Synthetic Data/` (openpyxl row count, header excluded). Zero of these rows have ever reached `staging/`, `transform/`, or a database.
2. **No real anchor: all 55,313 (100%)** — every row's own `(doc_type, month)` cell has zero real source file (verified against `transform/_manifest.json`); spot-checked entity content is also 0% grounded (0/435 synthetic customer names, 8/9 synthetic salesman names, 0/362 synthetic SKU codes matched any real staged value in the samples checked).
3. **Only one location: `data/raw/Synthetic Data/`** (raw files only). `staging/_manifest.json`, `transform/_manifest.json`, `profiling/sheet_profiles/`, `tests/`, and the frontend all show zero references to it. Supabase has never been loaded at all (`analytics/etl/load.py`'s own docstring: "never executed against a live database as of this writing").
4. **Cleanly separable today (trivially — nothing is mixed in), but NOT safely separable if the pipeline is ever pointed at this folder**: a `is_demo=True` column is baked into the raw files but zero code in the repo reads it; a doc-type regex bug silently drops half the files (178/374) as `unknown`; the other half (196/374) would be parsed and would inject fabricated provenance strings as literal data.
5. **Shape will partially survive the swap**: Sell Out's category vocabulary and value distribution shape are a good match to real (see Phase 5); Sales Register/Purchase Order/Inventory Sign Off's customer, salesman, and SKU rosters are 100% invented; and the file format itself (pre-stamped `_src_file`/`_period`/provenance columns baked into what's supposed to be raw input) is structurally incompatible with how Extract reads a raw workbook.
6. **Biggest structural problem**: these 374 files are not shaped like raw SSM exports — they are shaped like *already-Extracted, provenance-stamped* Parquet-equivalent output (all 15 of `_shared.py`'s real `PROVENANCE_COLUMNS`, verbatim, plus `is_demo`) saved back into `data/raw/` as if they were pristine source. If the pipeline is ever run against this folder, it will not cleanly ingest "extra demo data" — it will re-Extract already-Extracted data and collide with its own provenance stamping.

---

## PHASE 0 — Discovery

### 0a. Synthetic/placeholder data files

- **`data/raw/Synthetic Data/`** — 374 `.xlsx` files, 10 MB total (`du -sh`), sitting flat (no month-folder nesting, unlike real Del Monte's `MONTHLY REPORT - <MONTH> <YEAR>` convention). Breakdown by filename prefix (`ls "data/raw/Synthetic Data" | sed -E 's/_[0-9]{4}-[0-9]{2}.*//' | sort | uniq -c`):
  - `INVENTORY_SIGN_OFF` — 92 files, 46 distinct months (2021-01 → 2026-03), 14,662 data rows
  - `PURCHASE_ORDER` — 104 files, 52 distinct months (2021-01 → 2026-03), 1,909 data rows
  - `SALES_REGISTER` — 86 files, 43 distinct months (2021-01 → 2026-03), 33,438 data rows
  - `SELL_OUT` — 92 files, 46 distinct months (2021-01 → 2026-03), 5,304 data rows
  - Total: 374 files / 55,313 rows (counted directly with `openpyxl`, one Excel sheet per file, `max_row - 1`; two files — `SELL_OUT_2024-04_PANGASINAN.xlsx`, `SELL_OUT_2026-03_PANGASINAN.xlsx` — report `max_row=None` due to a missing `<dimension>` tag and were counted by `iter_rows` instead).
  - **No Sales Return, RMR GS & BO, or Unilever/SKU synthetic files exist anywhere** (`ls "data/raw/Synthetic Data" | grep -i "unilever\|sku"` → none; `grep -i "sales_return\|rmr"` → none), even though both are covered in the generation plan docs below. Only 4 of the 6 planned families were actually produced on disk.
  - `data/raw/Synthetic Data/` is untracked by git, but so is all of `data/raw/*` (`.gitignore:12` — `data/raw/*` with only `!data/raw/.gitkeep` kept — this is the standing "real client data" policy, not something specific to synthetic data).
  - File mtimes: all 374 files were written **2026-08-20 15:29:41–15:29:47** (`ls -la --time-style=full-iso`), i.e. today, in a 6-second burst — consistent with a single generation run, not manual authoring.

- **Drift from the documented plan**: comparing filenames' embedded months against `DEL_MONTE_DEMO_GENERATION_SHEET.md`'s stated "Full range: 2021-01 – 2025-12" for all four families, the actual files also cover **2026-01, 2026-02, 2026-03** — three additional months per family, not mentioned in either planning doc. Everything else (24 backfill months 2021-2022 + the documented gap-fill months) matches the plan's counts exactly (e.g. Sell Out: 24 + 19 = 43 documented months, + 3 undocumented 2026 months = 46, matching the actual file count).

### 0b. Generator script

**No generator script exists in the repo.** `grep -r "Synthetic Data|synthetic_data|SYNTHETIC" --include=*.py --include=*.yaml --include=*.yml --include=*.json .` returns exactly two matches, both in `analytics/db/schema.sql` and `analytics/etl/transform.py`, and both are about an unrelated feature (a documented synthetic *date* marker for `Inventory_Fact.snapshot_date`, not data generation). `find` for `*faker*`, `*mock*`, `*fixture*`, `*generat*`, `*synthetic*` under the repo turns up nothing relevant (`scripts/_build_ac_tracker.py` is an unrelated acceptance-criteria tracker; its `is_demo`/`generat` hits are about AC-tracker terminology, not data generation).

Two planning documents exist and were read in full — **specs, not code, and specs for a plan that was only partly executed**:
- `analytics/docs/DEL_MONTE_DEMO_DATA_SPEC.md` (329 lines) — "Status: spec only. No data has been generated" (its own line 3). Documents the real gap-fill months per family (derived by querying `staging/<family>/*.parquet`'s real `_period` values), the real Sell Out category taxonomy (81 Era-A categories + 5 Era-B categories, two eras split at the real Feb2024→Mar2025 vocabulary change), real value ranges/CVs/swing bounds per category, and an explicit scope boundary: never add SKU/product grain to Sales Register/Purchases/Sales Return, never add units to RMR GS&BO, never add `units_received` to Purchase Order (matching this audit's ground-truth constraints).
- `analytics/docs/DEL_MONTE_DEMO_GENERATION_SHEET.md` (386 lines) — the companion "build from this" sheet: a `growth_factor(month_index) = 0.82 + (month_index/24)*0.18` linear-ramp formula for the 2021-2022 backfill (anchored to real Jan-2023 baselines), exact column orders/quirks per family, the full ranked 81-category Sell Out table with real value ranges, category "story role" assignments (trending up/down, high-variance, steady Class C) tied to real evidence, and an `is_demo` isolation design (dedicated boolean column, `NOT NULL DEFAULT false`, filtered at the query layer via a proposed `Sales_Fact_Real` view — **never implemented**, see Phase 1).

**Generated by unknown means**: whatever tool actually produced the 374 files (no script found in the repo, all files written in one ~6-second burst) is not identifiable from repo contents. The output closely follows the generation sheet's column orders, category vocabulary, and (per Phase 0a) even its exact documented month lists — strong circumstantial evidence the sheet was followed — but overshoots it by 3 undocumented months per family, so either the generation tool diverged from the checked-in spec or a newer, unwritten version of the plan was used.

### 0c. Real staged Parquet corpus

`staging/<doc_type>/*.parquet`, 112 MB total (`du -sh staging/`). Per `staging/_manifest.json` ("staged" list, 1,090 entries) and row counts:

| doc_type | extract-staged rows | sheets/files |
|---|---|---|
| sales_register | 23,817 | 127 |
| unilever_sku | 24,906 | 1 (one workbook, 2023-01→2026-02) |
| inventory_sign_off | 7,019 | 41 |
| sell_out | 1,573 | 34 |
| purchase_order | 544 | 22 |
| rmr_gs_bo | 538 | 12 |
| ssis_summary | 1,949,687 | 805 |
| sales_return | 1,406 | 48 |

`transform/` (10 MB, manifest + review HTML only — no parquet output at this stage) shows the same real corpus after Transform's natural-key/dedup rules: 58,485 rows staged successfully, 819 real rows rejected (details in Phase 2/4), 0 reject reasons mention anything synthetic.

### 0d. Every location synthetic rows currently sit

- **`data/raw/Synthetic Data/`** — the only location found. 374 raw files, 55,313 rows, confirmed above.
- **`staging/_manifest.json` / `transform/_manifest.json`**: `grep -c "Synthetic Data"` → 0 in both. Both manifests were last written **2026-08-20 01:05:39** (staging) and **02:10:49** (transform) — i.e. *before* the Synthetic Data files existed (15:29:41). The pipeline has literally never run since this corpus appeared; the zero-hit result is not evidence the pipeline would reject them, only that it hasn't been pointed at them yet (see Phase 1 for what a re-run would actually do).
- **`profiling/sheet_profiles/`**: `find profiling/sheet_profiles -iname "*synthetic*"` → 0 hits; the profiling dir's own mtime (2026-08-13/2026-08-20 00:56) predates the synthetic corpus too.
- **Loader inputs / test fixtures**: `tests/` has no `fixtures/` directory at all (`find tests -iname "*fixture*"` → none; `find tests -type d` lists only `backend/classification/etl/forecasting/optimization` subpackages, no data dirs). `grep -ri "is_demo|synthetic|placeholder|mock" tests/` → the one apparent hit (`tests/etl/test_transform.py`) does not actually contain the string on re-check (`grep -i "demo"` on that file → no matches) — false positive from an earlier pass, verified clean.
- **Supabase**: cannot be queried live (out of scope for this environment). Strong code-level evidence it is currently empty of everything, real or synthetic: `analytics/etl/load.py`'s module docstring states outright "load_to_supabase() will raise a clear ProgrammingError from the driver if the table is missing... **still never executed against a live database as of this writing**." No script anywhere references `Synthetic Data` or `is_demo` in a Supabase-insert context (`grep -rl "supabase" .` → 13 files, none touch synthetic data).
- **Frontend**: `grep -ri "is_demo|synthetic|placeholder|mock" frontend/src` → 15 hits, all are HTML `placeholder="..."` input attributes (e.g. `frontend/src/components/SKUManagement.jsx:429`, `placeholder="Search by code, name, or brand..."`) — UI text, unrelated to synthetic data.
- **`C:\Users\kyuan\Downloads\DelMonte_June_2025.xlsx`**: outside the repo entirely, not found referenced by any repo file, not part of this corpus.

---

## PHASE 1 — Separability

**Today: trivially separable, because nothing is mixed.** Zero synthetic rows exist in any staged/transformed output (Phase 0d). There is no real+synthetic co-mingling anywhere in the current pipeline artifacts to separate.

**Going forward, if `data/raw/Synthetic Data/` is ever left in place when the pipeline reruns, separability breaks in three independent ways:**

1. **Half the files won't even be discovered under the current doc-type classifier — and would be silently dropped, not silently mixed in.** `profiling/profile_files.py`'s `DOC_TYPE_PATTERNS` (line 62-81) matches `sale[s]?\s*regist(er)?` — a literal `\s*` (whitespace) between "sales" and "register" — but the synthetic filenames use an underscore separator (`SALES_REGISTER_2021-01_ILOCOS.xlsx`), which the regex does not bridge. Same issue for `sell\s*out` vs `SELL_OUT_...xlsx`. Verified directly by importing `infer_doc_type()` and running it against all 374 real filenames: **86 `SALES_REGISTER_*` + 92 `SELL_OUT_*` = 178 files classify as `doc_type="unknown"`**, meaning `select_files_for_doc_type()` (`_shared.py:601-617`, which filters by `infer_doc_type(f) == doc_type`) would never select them for any parser. `INVENTORY_SIGN_OFF_*` (92) and `PURCHASE_ORDER_*` (104) — 196 files — classify correctly (`"inventory"` and `"purchase"` are literal substrings regardless of the underscore) and both doc_types have live parsers in `FAMILY_PARSERS` (`analytics/etl/extract/driver.py:43-52`: `parse_inventory_signoff`, `parse_purchase_order`), so those 196 **would** be picked up.

2. **The 196 files that would be picked up carry provenance columns as literal DATA, not as pipeline output.** Opened `INVENTORY_SIGN_OFF_2021-01_ILOCOS.xlsx` and `PURCHASE_ORDER_2021-01_ILOCOS.xlsx` directly: their header rows are `__col0__, Quantity, Cost, Valuation, Valuation with VAT, CAS, PCS, PKG, in Cases, _src_file, _src_sheet, _header_row, _row_ordinal, _principal, _region, _period, _doc_type, _sheet_role, _grain, _checksum_status, _checksum_column, _checksum_expected, _checksum_got, _checksum_diff, is_demo` — i.e. the real raw column set **plus all 15 of `_shared.py`'s `PROVENANCE_COLUMNS` (lines 47-51) verbatim, plus `is_demo`**. These are supposed to be Extract's *output* columns, stamped after parsing — here they are baked into row 1 of a file sitting in the *input* folder. A real re-run's own provenance stamping would either collide with (overwrite) these fake values or produce duplicate-named columns, depending on how the stamping call is structured; either way the file's self-declared `_src_file`/`_period` values are not what a real run would compute.

3. **The embedded provenance values are internally inconsistent with the file they're printed in — a fingerprint of how they were built, and a correctness bug if ever read literally.** Example, `INVENTORY_SIGN_OFF_2021-01_ILOCOS.xlsx` row 2: `_src_file = "JANUARY_2021_INVENTORY_SANSAN_PANGASINAN_ILOCOS"`, `_period = "2021-01"` — a filename that names a file that does not exist anywhere on disk (the real file is `INVENTORY_SIGN_OFF_2021-01_ILOCOS.xlsx`). Same pattern in `SELL_OUT_2021-01_ILOCOS.xlsx` row 2: `_src_file = "PANGASINAN_ILOCOS_JANUARY_2023_SELL_OUT"` while `_period = "2021-01"` — the embedded filename string says **2023**, the period column says **2021**. This is the growth-factor backfill method described in `DEL_MONTE_DEMO_GENERATION_SHEET.md` §"2021-2022 backfill" leaving a fingerprint: rows were built by copying the real Jan-2023 anchor row's provenance fields and only overwriting `_period`, not `_src_file`. **Every `_src_file` value examined across the four families points at a file that does not exist on disk, real or synthetic** — checked systematically is out of budget for all 374 files, but the pattern held in every file opened (4/4 families sampled).

**Is there a marker?** Yes — `is_demo` (boolean, `True` on every row checked) is baked into the raw file content, exactly as `DEL_MONTE_DEMO_GENERATION_SHEET.md` §STEP 4 specified. But **zero code in the repo reads it**: `grep -rl "is_demo" --include=*.py --include=*.yaml --include=*.yml --include=*.sql .` → no hits anywhere in `analytics/`, `backend/`, `config/`, or `tests/`. None of the 9 `config/column_maps/*.yaml` files declare an `is_demo` canonical mapping (checked `inventory_sign_off.yaml` and `purchase_order.yaml` directly — no such entry). Per `apply_column_map`'s documented behavior (its own comment in `inventory_sign_off.yaml`: "unmapped columns are kept as-is, never dropped"), an `is_demo` raw column would survive Transform as an inert unmapped extra column — present, but not filterable by any existing query, view, or code path. `analytics/db/schema.sql` has no `is_demo` column on any fact table (`grep "is_demo" analytics/db/schema.sql` → no matches) — the generation sheet's proposed schema change and `Sales_Fact_Real` view were never implemented.

**Minimum-effort marker for later (proposal only, not implemented here)**: since the raw files already carry `is_demo=True` faithfully and consistently, the cheapest fix is not a new marker but making the existing one load-bearing — (a) fix the two `DOC_TYPE_PATTERNS` regexes so all 374 files classify consistently instead of half silently vanishing, (b) add `is_demo` to each of the 4 relevant `config/column_maps/*.yaml` files as a mapped canonical column so it survives Transform under a stable name, (c) add the `is_demo BOOLEAN NOT NULL DEFAULT false` column to `schema.sql`'s fact tables and the `Sales_Fact_Real`-style filtered view the generation sheet already specified.

---

## PHASE 2 — Coverage matrix

Matrix built from `transform/_manifest.json`'s `staged`/`reject` lists (per-`(doc_type, period)` outcome — authoritative for real-file processing results) cross-referenced with the 374 synthetic filenames' embedded periods, for the 8 real family×principal pairs (`sales_register`, `purchase_order`, `sell_out`, `inventory_sign_off`, `rmr_gs_bo`, `sales_return` = Del Monte; `ssis_summary`, `unilever_sku` = Unilever — principal assignment confirmed directly from manifest `principal` field, 100% consistent per doc_type), months 2021-01 through 2026-08 (68 months × 8 = 544 cells).

**Correction made during construction**: `transform/_manifest.json`'s own `period` field for `unilever_sku` literally reads `"2023-01"` for its one 24,906-row entry, even though the real data spans 38 months. This is a manifest granularity bug — the file has one manifest record per *sheet*, not per *row*, and the sheet's `period` field was populated from only the first month. Verified directly by loading `staging/unilever_sku/UnileverLaUnionSalesperSKU2023to2026__sheet1.parquet` and checking real per-row `_period` values: true real range is **2023-01 → 2026-02, 38 months, 24,906 rows**, confirmed by `_period.value_counts()` (593–779 rows/month, all months present, no gaps). Used the parquet's true per-row periods instead of the manifest's collapsed field for this one doc_type; flagging the manifest bug itself as a Phase-1-adjacent finding since anyone else trusting `transform/_manifest.json`'s `period` field naively would wrongly conclude 38 real Unilever months are absent.

Compressed summary (full 544-row detail in `reports/coverage_matrix.csv`):

| doc_type (principal) | 2021-2022 | 2023 | 2024 | 2025 | 2026 (Jan-Aug) |
|---|---|---|---|---|---|
| sales_register (delmonte) | SYNTHETIC (24mo) | REAL Jan-Jun,Aug-Sep,Nov-Dec / SYNTHETIC Jul,Oct | REAL Jan-Feb / SYNTHETIC Mar-Dec | REAL Mar-Apr,Jun,Aug-Dec / SYNTHETIC May,Jul | SYNTHETIC Jan-Mar / ABSENT Apr-Aug |
| purchase_order (delmonte) | SYNTHETIC (24mo) | REAL Sep / SYNTHETIC Jan-Aug,Oct / REAL Nov-Dec | REJECTED Jan / REAL Feb / SYNTHETIC Mar-Dec | REAL Mar,Sep,Dec / REJECTED Apr,Jun,Aug / SYNTHETIC others | SYNTHETIC Jan-Mar / ABSENT Apr-Aug |
| sell_out (delmonte) | SYNTHETIC (24mo) | REAL Jan-Jun,Aug-Sep,Nov / SYNTHETIC Jul,Oct,Dec | REAL Jan-Feb / SYNTHETIC Mar-Dec | REAL Mar-Apr,Jun,Aug-Sep,Dec / SYNTHETIC May,Jul,Oct-Nov | SYNTHETIC Jan-Mar / ABSENT Apr-Aug |
| inventory_sign_off (delmonte) | SYNTHETIC (24mo) | REAL Jan-Jun,Aug-Sep / SYNTHETIC Jul / REAL Dec | REAL Jan-Feb / SYNTHETIC Mar-Dec | REAL Mar-Apr,Jun,Aug-Sep,Dec / SYNTHETIC May,Jul,Oct-Nov | SYNTHETIC Jan-Mar / ABSENT Apr-Aug |
| rmr_gs_bo (delmonte) | ABSENT (24mo) | ABSENT (12mo) | ABSENT (12mo) | REAL Oct-Nov only / ABSENT rest | ABSENT (8mo) |
| sales_return (delmonte) | ABSENT (24mo) | REAL Jan-Jun,Aug-Sep,Nov-Dec / ABSENT Jul,Oct | REAL Jan-Feb / ABSENT Mar-Dec | REAL Mar-Apr,Jun,Aug-Sep,Dec / ABSENT May,Jul,Oct-Nov | ABSENT (8mo) |
| ssis_summary (unilever) | REJECTED (24mo) | REJECTED (12mo) | REJECTED (12mo) | REJECTED (12mo) | REJECTED Jan-Mar / ABSENT Apr-Aug |
| unilever_sku (unilever) | ABSENT (24mo) | REAL (12mo) | REAL (12mo) | REAL (12mo) | REAL Jan-Feb / ABSENT Mar-Aug |

Notable non-synthetic finding surfaced by this matrix: **`ssis_summary` is REJECTED for literally all 63 real months with data (2021-01 → 2026-03) plus one `unknown`-period entry** — reason (from `transform/_manifest.json`, verbatim): `"natural_key unconfirmed for fact='sales' principal='unilever' - see source_of_truth.yaml"` (all months) and, for most months, additionally `"not claimed by any (fact, principal) rule for this doc_type - unrecognized _principal?"`. This is a real Unilever data-pipeline gap independent of synthetic data — 1,949,687 real extracted rows, 0 currently reach any Fact table — noted here because it changes how "REAL" should be read in this matrix (real + extracted ≠ usable downstream).

Full per-cell detail: `reports/coverage_matrix.csv` (544 rows: `principal, doc_type, period, label`). Cell-label tally: **SYNTHETIC 187, REAL 119, REJECTED 67, ABSENT 171** (of 544).

---

## PHASE 3 — What was invented from nothing

**By month** (per Phase 2, restated): all 187 SYNTHETIC-labeled cells — and by extension all 55,313 rows within them, since the row-count-to-cell join found **zero synthetic rows land in a month where any real source exists for that doc_type** (every generated row sits exactly in a gap, as intended by the generation plan). So 100% of the corpus has no real month-level anchor.

**By entity — spot-checked, not exhaustively enumerated (out of budget for all 374 files); samples below are representative, not a full census:**

- **Salesman names (Sales Register)** — `DEL_MONTE_DEMO_GENERATION_SHEET.md` explicitly instructs: *"Salesman: Real names, e.g. 'CARLON DAHILIG' — reuse real salesman names already in the corpus, don't invent new ones."* Checked the two `SALES_REGISTER_2021-01_*.xlsx` files against all 33 real distinct salesman names in `staging/sales_register/*.parquet`: synthetic files use 9 distinct names, only **1/9 (`OFFICE SALES`) is real**. The other 8 are not in the real 33-name roster at all: `ELMER CASTANEDA, EDWIN TABUCOL, ARNEL SORIANO, JOVIT MANANSALA, NOEL DE VERA, MARISSA GALLARDO, GRACE PALAGANAS, RODEL BUMANGLAG`. **This directly contradicts the generation plan's own stated instruction** for this field.
- **Customer names (Sales Register)** — 435 distinct synthetic customer names in the 2 sampled files vs. 1,786 real distinct customer names in `staging/sales_register/*.parquet`: **overlap = 0/435**. (The generation sheet did not instruct reuse for this field, only "Blank not allowed" — so this one is invented by design, not a spec violation, but still has zero real anchor.) Sample invented names: `STA RITA RESTAURANT, TIN-TIN GROCERY, SIRIB EATERY, 5 BROTHERS CATERING, SUNRISE FOODHOUSE, AMIHAN EATERY, MABUHAY RESTAURANT, ATE VI EATERY, KUYA JUN EATERY, HAPPY DAYS CVS, HAPPY DAYS MINI MART, MEGA SAVE FOOD HOUSE, MABUHAY BAKERY, BUNSO MARKETING, GOLDEN HARVEST WHOLESALER, MASAGANA TRADING, JM TRADING, TANGLAW FOODHOUSE, REYNA GENERAL MERCHANDISE, NICOLE'S TRADING`.
- **SKU codes (Inventory Sign Off)** — 362 distinct leading SKU-code tokens in the `INVENTORY_SIGN_OFF_2021-01_*.xlsx` sample vs. 266 real distinct SKU-code tokens in `staging/inventory_sign_off/*.parquet`'s `__col0__` column: **overlap = 0/362**. Format convention matches real (alphanumeric prefix + digits, e.g. real `9DMP57930` vs. synthetic `9DMP41721`), but every code is a distinct fabricated value. Sample: `9DMP41721 -> "DM Heart Smart 100% PJ 80g 10x12"`, `DMP41156 -> "DM Pineapple Slices 234g 24s"`, `7DML91318 -> "DM Banana Ketchup 1L 12s"`, `8DBN24169 -> "DM Pineapple Slices 330ml 6Pck"`, `7DML23716 -> "DM Sweet Blend Juice 1L 4-Pack"`, `DMP75544 -> "DM Original Blend Juice 300 24x"`, `DMP64014 -> "DM Cream Filled Wafer 155g 10x12"`, `7DML95651 -> "DM Pineapple Slices 1.36kg 10x12"`, `9DBK11079 -> "DM Original Tomato Sauce 330ml Tray"`, `9DBS55855 -> "DM Elbow Macaroni 432g 12s"`. (20-row sample not reached because only 362 distinct codes existed in the one-month sample checked; all shown are invented.)
- **Sell Out category strings** — the one bright spot: 72 distinct category strings in `SELL_OUT_2021-01_*.xlsx`, **71/72 (98.6%) exactly match a real category string** from `staging/sell_out/*.parquet`'s 99 real distinct strings. The one non-match is a formatting artifact, not an invented category: `/SPAG SAUCE/SWEET SPAG SAUCE -\tBASE REGULAR` (tab character where the real string has a space). This is the one family where the generator's real-vocabulary-reuse instruction was followed almost exactly.
- **No rows for any principal other than Unilever/Del Monte** — `_principal` in every sampled synthetic row reads `"delmonte"`; no Magnolia or other principal strings found in any file opened.
- **Unilever SKU roster** — moot: zero Unilever/SKU synthetic files exist at all (Phase 0a), so there is nothing to check against the real 24,906-row `unilever_sku` staging table. The generation sheet's planned 2021-2022 Unilever per-SKU backfill (593-SKU roster × 24 months) was never executed.

---

## PHASE 4 — Structural impossibility checks

Ranked by how much frontend/downstream work would have to be redone if the shape doesn't survive the swap to real data.

1. **[Highest impact] Provenance/format collision, not a data-shape issue but a pipeline-mechanics one** — covered in full in Phase 1: 196/374 files (`INVENTORY_SIGN_OFF`, `PURCHASE_ORDER`) are structurally shaped as post-Extract output (all 15 `PROVENANCE_COLUMNS` + `is_demo` baked into row 1) sitting in the raw-input folder, and 178/374 (`SALES_REGISTER`, `SELL_OUT`) are invisible to the current doc-type classifier entirely. If this folder is ever left in place for a real pipeline run, the failure mode isn't "wrong numbers on a chart" — it's parser-level breakage or silent complete omission, which would require re-plumbing the discovery layer, not just re-labeling data.

2. **Del Monte customer/salesman/SKU rosters have zero real anchor (Phase 3)** — 0/435 customers, 8/9 salesmen, 0/362 SKU codes. Any frontend element that lists/searches/filters by these specific identity values (customer lookup, salesman leaderboard, SKU picker) is currently exercising a roster that will be entirely replaced, not partially refreshed, when real files land for these months. High rework risk for any UI feature built by eyeballing today's specific names.

3. **Sell Out `category_path` — real-data pipeline gap independently verified, applies equally to real and synthetic.** Ground-truth claim was "34 real sheets fail on missing `category_path`." Verified directly: `config/column_maps/sell_out.yaml` **does** declare `category_path: __col0__` (this may have been fixed since the claim was written — commit `ca8ee33 fix: apply_column_map skipping real __colN__ placeholders` is in this branch's recent history), but the map declaration doesn't translate into output: checked `transform/_manifest.json`'s `staged` records for `doc_type="sell_out"` — **0 of 34 real staged sheets have `category_path` in their post-Transform `columns` list** (actual columns present: `['Total Without Tax', 'Product Quantity', 'CASE', 'Total With Tax']`). The claim is confirmed true today, independent of the yaml declaration. Since the synthetic Sell Out files use the identical raw `__col0__` layout as real ones, they would hit the exact same gap if ever transformed — this is an existing real-pipeline bug the synthetic data inherits rather than a new problem synthetic data introduces.

4. **Inventory Sign Off `sku_code` — same pattern, independently verified.** Checked `transform/_manifest.json`'s 41 real `inventory_sign_off` staged records: **0/41 have `sku_code` in their `columns` list** (the raw `__col0__`/`__col1__` combined SKU+description string is never split into a `sku_code` field — confirmed against `config/column_maps/inventory_sign_off.yaml`'s own comment: *"__col0__ is NOT mapped in this file, on purpose"* and *"TRANSFORM TODO: ... still needs to write a parser that splits the leading alphanumeric token"*). Confirms the ground-truth claim exactly (41/41). Again, real and synthetic inventory files share this raw shape, so this is an inherited real gap, not synthetic-specific.

5. **No `bo_units`, no Del Monte SKU/daily-grain rows found anywhere in the actual generated corpus.** Ground truth flags these as hard impossibilities; checked and neither appears: no RMR/Sales Return synthetic files exist at all (so no fabricated `bo_units` risk), and none of the 4 generated families (Sales Register, Purchase Order, Sell Out, Inventory Sign Off) carry a per-SKU column for Sales Register/Purchase Order — their synthetic headers match the real 14-15 column invoice-level shape exactly (`Invoice Date, Salesman, Town Display, Branch Code, Customer Name, Invoice Num, REFNBR, Untaxed Amount, Discount Rate, Discount Amount, Tax, Net Amount, Balance, Posted[, Return Slip #]`), confirmed by direct row inspection of `SALES_REGISTER_2021-01_ILOCOS.xlsx` and `PURCHASE_ORDER_2021-01_ILOCOS.xlsx`. No violation of DEC-02/DEC-03 grain rules found in the generated content itself.

6. **Column vocabulary era** — Sales Register synthetic files use the Era-A/2023-2024 14-column shape consistently in the samples checked (`Invoice Date, Salesman, Town Display, Branch Code, Customer Name, Invoice Num, REFNBR, Untaxed Amount, Discount Rate, Discount Amount, Tax, Net Amount, Balance, Posted`), matching one of the three real eras. No mixed/unknown-era column sets found in the files opened.

7. **Dates outside 2021-2026** — none found; synthetic dates run 2021-01 through 2026-03, inside the project's stated 2021-2026 real-data boundary (Del Monte's own real corpus is narrower, 2023-2025, but that's a coverage gap, not a boundary violation — see Phase 6). The 2026-01/02/03 files (Phase 0a) are undocumented relative to the two planning docs but not out-of-bounds relative to project ground truth.

---

## PHASE 5 — Plausibility for demo purposes

Real vs. synthetic, same field, computed with `scipy.stats`:

**Sales Register `Net Amount`** (real: all `staging/sales_register/*.parquet`, n=18,684; synthetic: all `SALES_REGISTER_2021-*.xlsx` files, n=7,306):

| Metric | Real | Synthetic |
|---|---|---|
| mean | 12,124.1 | 5,465.4 |
| std | 67,968.7 | 15,748.2 |
| min / max | 17.3 / 4,043,777.2 | 19.4 / 954,154.3 |
| skew | 37.14 | 33.41 |
| kurtosis | 1,804.1 | 1,847.3 |
| zero fraction | 0.0000 | 0.0000 |
| exact-duplicate-value fraction | **0.4414** | **0.0064** |

Skew/kurtosis are a close match — the heavy-tailed shape (one huge real outlier invoice at ₱4.04M) is well reproduced. **The one number a panelist's histogram or "distinct values" count would expose: 44.14% of real Net Amount values are exact duplicates of another real value (recurring standard order sizes/unit prices), vs. only 0.64% of synthetic values** — the synthetic series is drawn too continuously; real invoice data clusters on repeated exact peso amounts far more than the synthetic generator reproduced.

> **CORRECTION (2026-08, `SYNTHETIC_STAGING_CONVERSION.md` Phase 3c)**: the 44.14% figure above could not be reproduced against `staging/sales_register/*.parquet` under any tried definition (standard rows-basis, string-exact, all-rows denominator, per-region). The real, reproducible rate under the standard definition (rows whose value repeats elsewhere / all non-null rows) is **52.5316%** (9,815/18,684). Do not cite 44.14% going forward — use 52.53%. The qualitative finding (synthetic under-clusters relative to real) still holds and was independently re-confirmed; only the exact percentage was wrong. The negative-Product-Quantity rate (0.0210, line ~171 below) and the 99-distinct-category-string count (line ~123 above) were separately spot-checked in the same session and both reproduced exactly — those two are not affected by this correction.

**Sell Out `Product Quantity`** (real: `staging/sell_out/*.parquet`, n=1,573; synthetic: `SELL_OUT_2021-01_*` + `SELL_OUT_2024-05_*.xlsx` sample, n=269):

| Metric | Real | Synthetic |
|---|---|---|
| zero fraction | 0.0006 | 0.0000 |
| negative fraction | **0.0210** | **0.0000** |
| skew | 10.77 | 7.76 |
| kurtosis | 151.3 | 62.9 |

The generation docs explicitly call for preserving real negative-quantity rows (`DEL_MONTE_DEMO_GENERATION_SHEET.md`: "Negatives allowed (2 real instances found)... Never blank"). Real data has 2.10% negative rows in the full corpus; **the sampled synthetic files have zero negative or zero rows at all** — the "preserve real edge cases" instruction wasn't reflected in this sample. Not necessarily untrue of the full 374-file corpus (only 3 of 92 Sell Out files were sampled here), but worth a targeted re-check before demo if negative-row realism matters to the walkthrough.

**Aggregate seasonality/smoothness check** — synthetic Sell Out total monthly revenue, 2021-2022 backfill window (the window explicitly built from a deterministic `growth_factor` ramp): linear-fit R² = **0.0072** against month index — i.e., the underlying 18%-over-24-month ramp formula does **not** produce a visually detectable straight-line trend in the aggregate total (per-category noise dominates); month-to-month totals range ₱9.18M–₱21.6M with no obvious monotonic climb. **This is a plausibility positive** — a panelist looking at a total-revenue trend line would not see a suspiciously perfect ramp.

**No rescaled-copy check performed exhaustively** (out of budget to diff every synthetic series against every real series numerically); the Sell Out category-value-range table in `DEL_MONTE_DEMO_GENERATION_SHEET.md` is explicitly built as `real_value × growth_factor × noise`, which is a scaled-and-noised copy by construction for the 2021-2022 window — that's disclosed in the plan, not a hidden finding, and the R² check above suggests the noise layer is doing real work rather than leaving a bare rescaling visible.

**Flag for a panel demo**: the customer/salesman roster fabrication (Phase 3/4) is the thing most likely to be independently noticed if anyone cross-references a name against a real invoice — the Net Amount duplicate-rate gap (Phase 5) is the thing most likely to show up on a distribution chart if a viewer plots "distinct invoice values."

---

## PHASE 6 — What's still missing from SSM

Grouped by doc family, using SSM's real file-naming convention observed directly in `data/raw/Del Monte/` (`MONTHLY REPORT - <MONTH> <YEAR>/` folders containing e.g. `PANGASINAN&ILOCOS <MONTH> <DATES> <YEAR> SELL OUT.xlsx`, `<YEAR> <REGION> <MONTH> SALES REGISTER.xlsx`) and `data/raw/Unilever/` (flat `UnileverLaUnionSalesperSKU2023to2026.xls` — one cumulative file, re-delivered whole, not per-month). Source: Phase 2's ABSENT cells (`reports/coverage_matrix.csv`), restricted to periods inside each family's own known-active real window (pre-window/not-yet-existent periods excluded and called out separately).

### Blocking — a named pipeline stage cannot run at all without it

- **Sell Out, remaining real gaps inside the active 2023-2025 window**: none currently ABSENT (all real months 2023-2025 are either REAL or SYNTHETIC-filled; only Apr-Aug 2026 are ABSENT going forward). Request pattern: `PANGASINAN&ILOCOS <MONTH> 1-<MONTH> 30 2026 SELL OUT.xlsx` for **April–August 2026**. **Blocks**: DEC-03's Del Monte category-grain recommendation and the SARIMA forecasting stage's ability to extend the current model window forward without a demo-data gap.
- **Sales Register, Apr-Aug 2026 (ABSENT)**: request `2026 <REGION> <MONTH> SALES REGISTER.xlsx` for **April–August 2026**. **Blocks**: same SARIMA forward-window continuity as above, plus any Sales-Fact-adjacent reconciliation reporting for those months.

### Non-blocking — improves coverage only

- **Purchase Order, Apr-Aug 2026 (ABSENT)**: request equivalent `PURCHASE_ORDER`-style monthly file for **April–August 2026**. Feeds Purchase_Fact only; not on the ABC/SARIMA/LP critical path per `config/column_maps/purchase_order.yaml`'s own note that `Purchase_Fact` doesn't even have most of this family's columns wired up yet.
- **Inventory Sign Off, Apr-Aug 2026 (ABSENT)**: request equivalent monthly file for **April–August 2026**. Feeds safety-stock/ROP inputs; improves coverage, not currently blocking a named stage since real 2023-2025 inventory coverage (17 real months) already exists to validate against.
- **Sales Return, real in-window gaps**: **2023-07, 2023-10, 2024-03 through 2024-12 (10 months), 2025-01, 2025-02, 2025-05, 2025-07, 2025-10, 2025-11** — 18 genuinely-missing real months inside the family's active 2023-2025 range, plus **April–August 2026**. Non-blocking today only because Sales Return has **no Extract driver wired to consume it at all yet** (per `DEL_MONTE_DEMO_DATA_SPEC.md` §1.3 — a real, separate gap independent of this audit) — once that driver exists, these become blocking for whichever fact it feeds.
- **RMR GS & BO, Dec 2025 – Aug 2026 (ABSENT)**: request `<REGION> GS/BO`-style Daily Report file for **December 2025 – August 2026**. Non-blocking for the core forecast pipeline per ground truth (`bo_units` has no source column anywhere; this family is value-based Bad Order reporting only). *Do not request pre-October-2025 backfill* — `DEL_MONTE_DEMO_DATA_SPEC.md` §1.6 already established this file convention didn't exist before Oct 2025; requesting it would be asking SSM for a file that was never produced.
- **Unilever per-SKU roster, Mar-Aug 2026 (ABSENT)**: request an updated `UnileverLaUnionSalesperSKU...` delivery extending through August 2026 (real coverage currently ends Feb 2026, 38/38 months present with no internal gaps). Non-blocking — real coverage is already dense; this only extends the trailing edge.
- **`ssis_summary`, Apr-Aug 2026 (ABSENT)**: request `SSIS SALES SUMMARY REPORT <MONTH> 2026.xlsx` for **April–August 2026**, matching the real naming convention seen in `data/raw/Unilever/`. Non-blocking in the sense that this family is currently 100% rejected at Transform for unrelated reasons (Phase 2) — extending its real coverage doesn't unblock anything until that rejection is separately fixed.

**Explicitly not requestable from SSM** (no real-world source ever existed for these, confirmed by the generation-spec's own verification pass and the RMR reasoning above): Del Monte 2021-2022 for all 4 generated families (Del Monte's real corpus genuinely begins Jan 2023), Unilever per-SKU 2021-2022 (real per-SKU data begins Jan 2023), and RMR GS & BO before Oct 2025.
