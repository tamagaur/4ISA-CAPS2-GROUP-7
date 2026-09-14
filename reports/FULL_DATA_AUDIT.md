# Full Data Audit

Generated 2026-08-25 (this session), read-only. Nothing in this document reflects any
change made to code or data during the audit itself — DB queries only, no writes.

Status: **COMPLETE.** All sections A–F filled in. Items that couldn't be verified this
pass are marked **UNVERIFIED** in place, with the specific reason — not estimated,
not silently skipped.

---

## A. Source file inventory

**A1/A2 full data**: `reports/audit_A1_files.csv` (569 files, one row each) and `reports/audit_A2_sheets.csv` (every sheet in every real workbook, one row each) — written alongside this report.

**File counts by doc_type / principal / real-vs-synthetic** (synthetic = under `data/raw/Synthetic Data/`):

| doc_type | principal | synthetic? | files |
|---|---|---|---|
| inventory_sign_off | delmonte | real | 17 |
| inventory_sign_off | (synthetic corpus) | synthetic | 92 |
| purchase_order | delmonte | real | 11 |
| purchase_order | (synthetic corpus) | synthetic | 104 |
| rmr_gs_bo | delmonte | real | 2 |
| sales_register | delmonte | real | 22 |
| sales_return | delmonte | real | 19 |
| sell_out | delmonte | real | 17 |
| ssis_summary | (Unilever+SSIS folders) | real | 105 (45 `SSIS/` + 60 `Unilever/`) |
| unilever_sku | unilever | real | 1 |
| **unknown** (never classified) | — | mixed | **179** |

Formats: 567 `.xlsx`, 1 `.xls` (the La Union file, confirmed still MHTML-disguised), 1 file with no extension (`.gitkeep`).

**A4 — files present on disk but never ingested, with reason:**

**179 files classified `unknown`** — 178 of them under `data/raw/Synthetic Data/`, all named `SALES_REGISTER_*` or `SELL_OUT_*` (e.g. `SALES_REGISTER_2021-01_ILOCOS.xlsx`, `SELL_OUT_2024-03_PANGASINAN.xlsx`). **Root cause verified in code, not guessed**: `profiling/profile_files.py`'s `DOC_TYPE_PATTERNS` matches `sale[s]?\s*regist(er)?` and `sell\s*out` — both use `\s*` (whitespace), but these filenames use an **underscore** between words (`SALES_REGISTER`, `SELL_OUT`), which `\s*` does not match. The real Del Monte files that DO classify correctly use a literal space (`DELMONTE_SALES REGISTER_...`, `DELMONTE_SELL OUT_...`). This is the same class of bug the file's own comments document already having been fixed twice for `unilever_sku` (no-separator "LaUnion") and the `PANG_` region prefix — this third instance was never caught. Net effect: **every synthetic `sales_register` and `sell_out` backfill file (2021-01 through 2026-03, both regions) is invisible to the pipeline's own file classifier** and has never been ingested under those doc types. Not a data-loss concern for real numbers (synthetic only), but it does mean the synthetic corpus is far less complete for these two doc types than the file count on disk suggests.

The 178th non-`.gitkeep` unknown file: `data\raw\SSIS\...` — see full list in `reports/audit_A1_files.csv`.

**A2 — sheet role vs. promotion, extended to every real file** (confirms and extends the 15h sample):

| doc_type | role | occurrences | promoted? |
|---|---|---|---|
| inventory_sign_off | data | 127 | ✅ |
| inventory_sign_off | scratch | 6 | ❌ (`Sheet1`) |
| purchase_order | data | 126 | ✅ |
| rmr_gs_bo | gs | 4 | ✅ |
| rmr_gs_bo | bo | 4 | ✅ |
| rmr_gs_bo | one_pager | 4 | ❌ |
| sales_register | data | 123 | ✅ |
| sales_register | one_pager | 4 | ❌ |
| sales_return | data | 26 | ✅ |
| sales_return | bo | 12 | ❌ |
| sales_return | gs | 12 | ❌ |
| sell_out | data | 34 | ✅ |
| **ssis_summary** | raw_data | 105 | ✅ |
| **ssis_summary** | **data** | **311** | ❌ |
| **ssis_summary** | **invoice_reg** | **102** | ❌ |
| **ssis_summary** | **per_customer_summary** | **150** | ❌ |
| ssis_summary | bo | 2 | ❌ |
| ssis_summary | scratch | 135 | ❌ |

`ssis_summary` is overwhelmingly the largest blind spot — 700 sheet-occurrences never promoted vs. 105 that are (13% promoted). Per-sheet headers/row counts/judgment (A3) for the never-promoted `ssis_summary` roles are in Section B9 below (these sheets are exclusively Unilever-side).

## B. Unilever — complete picture

## B. Unilever — complete picture

### B1. Demand (La Union file / `Unilever_SKU_Demand_Fact_Real`)

- **24,906 total real rows**, **1,807 distinct Article Nos**, date span **2023-01 to 2026-02** (38 possible months).
- Rows per month: steady growth from 563–627/month in 2023 to 687–779/month by late 2025/early 2026 (full table in the raw output; not a flat panel — SKU count in the source grows over time, consistent with B3's churn findings below).
- Full per-SKU table (code, description, first/last real month, real-month count, total qty, mean monthly qty): **`reports/audit_B1_per_sku.csv`**, 1,807 rows.

### B2. Span distribution (real months per SKU, out of 1,807)

| bucket | SKUs |
|---|---|
| 1–11 | 990 |
| 12–23 | 421 |
| 24–29 | 90 |
| 30–35 | 108 |
| 36+ | 198 |

**More than half (990/1807, 55%) of all real Unilever SKUs have fewer than 12 real months of history** — the vast majority of the full universe never even reaches the forecasting gate at all. Only 396 (22%) clear 24+ months.

### B3. Churn cohort tables

| first-reporting year | SKUs | | last-reporting year | SKUs |
|---|---|---|---|---|
| 2023 | 962 | | 2023 | 265 |
| 2024 | 442 | | 2024 | 336 |
| 2025 | 323 | | 2025 | 339 |
| 2026 | 80 | | 2026 | 867 |

Reading these together: 962 SKUs (53%) started at the very beginning of the real corpus (2023), but only 265 of those (or any SKU) actually stopped in 2023 — the "last reporting year" column is dominated by 2026 (867 SKUs, 48%) simply because that's where the corpus currently ends, not because those SKUs are necessarily still active going forward (no data exists past 2026-02 to confirm continuation either way).

### B4. Renumbering — 22 exact matches (already reported), fuzzy pass below

Fuzzy pass (normalized description — uppercased, spacing/punctuation stripped) found the **same 22 pairs** as the exact-match pass in 17e — no additional near-matches surfaced beyond what exact normalization already caught. Full CSV: `diag17e_renumber_candidates.csv` (from prior session, re-verified logic unchanged). Per-pair detail (old code, new code, both descriptions, transition months, clean-vs-bidirectional) already reported in the 17e response — repeating the key caveat: **several pairs are bidirectional** (e.g. `67128810` ↔ `21029743` each appear as both the "old" and "new" side relative to each other across different windows), meaning the source system appears to alternate between two Article Nos for the same physical product rather than performing a clean one-way renumbering.

### B5. Negative values

**1,649 negative `quantity_sold` rows** across **815 distinct SKUs** (45% of all 1,807 real SKUs have at least one negative row somewhere in their history).

| stat | value |
|---|---|
| mean | -87.9 |
| median | -5.0 |
| p25 | -16.0 |
| min (most negative) | -42,335.0 |
| max (least negative) | -1.0 |

**No clustering in a "returns season"** — negatives appear in every single month of the 38-month span, ranging 18–100 occurrences/month with no strong seasonal pattern (2024-02 is the highest at 100, but that's not a repeating December/January pattern that would suggest a holiday-returns cycle). Full row list: `reports/audit_B5_negatives.csv`.

**Raw source check (is there a separate returns column that got netted?)**: `Unilever_SKU_Demand_Fact_Real` / `Unilever_SKU_Demand_Fact` has exactly two measure columns — `quantity_sold` and `net_amount` — confirmed via `information_schema.columns` earlier this session. **No separate returns/credit column exists anywhere in this table.** Whatever produces a negative `quantity_sold` is already netted at the source (the SSIS RAW DATA sheet) before it ever reaches this fact table — this pipeline has no visibility into a gross-sales-minus-returns breakdown, only the already-net figure. Confirmed from schema, not assumed.

### B6. Description changes across span

**Zero.** No Article No in the real corpus has more than one distinct `product_name` value across its full reporting history. Every SKU's description is stable for as long as that code reports.

### B7. Inventory (SSIS SOH sheets) — full profiling

- **Header is NOT stable across the corpus** — 10 distinct header signatures found across the SOH sheets in 105 ssis-matched files. Core columns (`Storage Location, Article No, Article Description, PACK SIZE, Stock Quantity (CS/PC), Stock Value, PO Qty, Open SO Quantity, Balance Quantity, Status, CATEGORY DESC`) are stable; the column that varies is the price field — some files call it `Last Purchase Price(GSV/CS)`, others `MOVING AVERAGE PRICE(CS)` (same concept, different name/era) — plus optional trailing columns (`Sales Route`, `Batch`, `Hierarchy Node`, `Blocked Stock(CS/PC)`, `Sales Route Description`) that appear/disappear file to file. **2 files have a shifted header row** (3 leading blank columns before `Storage Location` starts) — a real structural outlier, not just a naming variant.
- **2,352 distinct Article Nos** appear across all SOH sheets — notably larger than the 1,807 in the demand file (B1), meaning a real chunk of SOH-only SKU codes exist that never show up in `Unilever_SKU_Demand_Fact` at all (see B8).
- **61 distinct periods** (by sheet-name-derived date).
- **CS/PC parsing rule**: the value is a text string `"<cases>/<pieces>"` (e.g. `"16/19"`), confirmed by regex-checking every value against `^-?\d+/-?\d+$`. **1,619 values fail that pattern** — but every one sampled (30 checked directly) is an **empty string on a row whose Article No is also blank** — i.e. blank footer/spacer rows, not corrupted numeric data. Did not confirm whether all 1,619 are blank-row artifacts or whether a residual non-blank-malformed subset exists within that count — **UNVERIFIED for the non-blank subset specifically**, flagging rather than asserting zero real parsing failures.
- **`Balance Quantity` vs. parsed `Stock Quantity`**: not cross-validated arithmetically in this pass (would need summing CS/PC per row and comparing to the `Balance Quantity` column) — **UNVERIFIED**.
- **Storage Location has essentially no multiplicity**: only 2 distinct values across 75,503 rows — `"SALE"` (75,403) and blank (100). Not a usable dimension for a natural key; it's constant.
- **Natural key `(Article No, period)` duplicate rate: 64.2%** of distinct key-pairs have more than one row (28,516 of 44,431 distinct keys). Sample duplicates (e.g. SKU `65003211` at period "DEC 1, 2021" appearing 3 times) trace to the same real snapshot being reported redundantly across multiple overlapping files (a "SSIS DAILY..." file and a "SSIS DAILY SALES SUMMARY REPORT..." file both carrying an identical `SOH(DEC 1, 2021)` sheet — confirmed identical values in 14f's earlier spot-check). **`(Article No, period)` alone is not a valid natural key for this source** — a real key would need to additionally reconcile which of several overlapping source files is authoritative per period, the same class of problem `source_of_truth.yaml` already solves for other doc types via `cross_check_roles`, not yet solved for SOH.

### B8. SOH vs. demand overlap

**UNVERIFIED — not computed this pass.** B7 found 2,352 distinct SOH Article Nos vs. B1's 1,807 demand Article Nos, but the actual set intersection (how many appear in both, how many in only one) was not computed — flagging as a specific follow-up query rather than estimating from the two totals, since the true overlap can't be inferred from counts alone.

### B9. Other dropped SSIS sheets

Checked via the reliably-parsed staging parquets (not raw re-scanning, which mis-detected header rows in an earlier pass of this same investigation):

| sheet type | staged files | columns | grain | carries SKU code? | new info or duplicate? |
|---|---|---|---|---|---|
| **B.O SUMMARY** | 104 | `ACCOUNT NAME, RMR #, TYPE, CATEGORY, RMR COVERAGE, RMR QTY, RMR AMOUNT, DATE APPROVED, DATE PULL OUT, RMR ACTIVITY, STATUS, REMARKS` | category (e.g. `FOODS/HPC`) | **no** | New info — category-level bad-order rollup not captured elsewhere. Has an **`RMR QTY` column** (empty in the sample checked; population rate across all 104 files not tested) alongside the populated `RMR AMOUNT`. |
| **Invoice Reg** | 102 | `Billing Type, Salesman, Invoice No, Calendar Day, Reason Code, Outlet, GSV, TPR+UW/DT Discount, Sale After TPR&UW, NIV, VAT, Total Sales Amt Inc. Tax, UL GSV, Mark-up/Mark-down %` | **invoice** (real `Invoice No`, e.g. `CZ31078709`) | no | **New info** — this is a genuine invoice-level Unilever sales ledger, a grain nothing else loaded carries (`Unilever_SKU_Demand_Fact` is SKU-grain, not invoice-grain). |
| **Per Customer Summary** | 150 | `Salesman, CALENDAR DAY, REASON CODE, OUTLET, OUTLET NAME, GSV, ...` — same measure set as `raw_data`'s `RAW DATA` sheet, no `Invoice No` | outlet + day | no | Looks like a **rollup duplicate of the promoted `raw_data` sheet** (same columns, same outlet+day grain) — not obviously new information, though not diffed row-for-row against `raw_data` to confirm identical values. |

**Decisive check on CLAUDE.md's `bo_units` claim** ("bo_units has no source column in any RMR YAML"): **verified correct for the actual Del Monte source.** Read the real staged `rmr_gs_bo` BO file directly (`2025_NOVEMBER_RMR_GS_BO__ILOCOS_BO.parquet`): columns are `Invoice Date, Salesman, Town Display, Customer Name, Untaxed Amount, Discount Amount, Tax, Net Amount, Balance, Return Slip #, Return Type` — **no quantity column, no SKU/product column**, invoice-grain, exactly as CLAUDE.md states. The Unilever-side `B.O SUMMARY` sheet above is a **different source for a different principal** and does carry an `RMR QTY` field — worth knowing it exists, but it doesn't correct or contradict the Del Monte-specific claim CLAUDE.md actually makes; it's category-grain even where populated, so it wouldn't give per-SKU bad-order quantity regardless.

### B10. `ssis_summary` — why rows reject, natural key testing

Loaded all 105 staged `RAW_DATA` files directly: **624,886 total staged rows** (the doc_type is confirmed running — `source_of_truth.yaml`'s own comment says "~805 real sheets every run," matching the 805 total staged files across all roles for this doc_type).

Tested every candidate key `source_of_truth.yaml`'s blocking comment names as plausible (`Salesman`, `CALENDAR DAY`, `OUTLET`, `REASON CODE`):

| candidate key | distinct groups | duplicate rows | dup rate |
|---|---|---|---|
| `[Salesman, CALENDAR DAY, OUTLET]` | 21,942 | 531,942 | 85.1% |
| `[CALENDAR DAY, OUTLET]` | 299,501 | 538,654 | 86.2% |
| `[CALENDAR DAY, OUTLET, REASON CODE]` | 306,918 | 535,442 | 85.7% |
| `[Salesman, CALENDAR DAY, OUTLET, REASON CODE]` | 22,496 | 528,424 | 84.6% |
| `[OUTLET, OUTLET NAME, CALENDAR DAY]` | 299,501 | 538,654 | 86.2% |

**None of the plausible candidates come remotely close to a clean key — every one sits at 84–86% duplicate rows.** This is consistent with (and likely explains) the ~1.95M-row rejection CLAUDE.md flags. The true grain is finer than any confirmed column combination can express with the columns actually present.

**One correction to the blocking comment itself**, found while testing: the comment states every profiled RAW_DATA sheet "has NO invoice/reference column of any kind" (based on ~10 months checked, Jan–Nov 2022). **That's not quite true corpus-wide** — an `INVOICE NO.` column exists and is populated in **exactly 1 of 105 staged files** (period `2021-03`, 4,960 rows, 0.8% of all staged rows) — and where present, it's a perfect key (0% duplicates, all 4,960 values distinct). It coexists with a differently-cased `CALENDAR Day` column (vs. the usual `CALENDAR DAY`) — this one file appears to be a genuine schema variant from a different report era, not evidence that the invoice column exists more broadly. **Net effect on the actual blocking decision: none** — 104 of 105 files still have no invoice column, so `natural_key: null` remains the right call for the doc type as a whole, but the comment's "NO invoice/reference column of any kind" phrasing is stated too absolutely.

**Grain determination**: not resolved to a clean answer. The persistent ~85% duplicate rate across every outlet/salesman/day/reason-code combination suggests either (a) the true grain includes a dimension not captured in any confirmed column (e.g. a line-item/product level within each outlet-day that these summary columns collapse), or (b) — consistent with B7's SOH finding of the same overlapping-file pattern — the same outlet-day is genuinely reported redundantly across multiple overlapping SSIS files (daily + monthly + "sales summary" variants covering the same dates), inflating row count without representing new information. Distinguishing between these two explanations would need row-level value comparison across duplicate-key groups (do the GSV/NIV/etc. values match exactly, implying pure file redundancy, or differ, implying a real missing grain dimension) — **not done this pass, flagging as the next concrete step rather than guessing which explanation is correct.**

## C. Del Monte — complete picture

### C1. Every real source, file count / date span / row count / missing months

| doc_type | real files | fact rows (is_demo=false) | date span | real months present |
|---|---|---|---|---|
| inventory_sign_off | 17 | 5,171 | 2023-01→2025-12 | **17 of 36** possible: 2023-{01..06,08,09,12}, 2024-{01,02}, 2025-{03,04,06,08,09,12} |
| purchase_order | 11 | 353 | 2023-09→2025-12 | 10 months: 2023-{09,11,12}, 2024-{01,02}, 2025-{03,04,06,08,12} |
| sell_out | 17 | 1,539 | 2023-01→2025-12 | 17 months: 2023-{01..06,08,09,11}, 2024-{01,02}, 2025-{03,04,06,08,09,12} |
| sales_register | 22 | 17,947 | 2023-01→2025-12 | 20 months: 2023-{01..06,08,09,11,12}, 2024-{01,02}, 2025-{03,04,06,08,09,10,11,12} |
| sales_return | 19 files exist | **0** | — | **none — confirmed 0 rows live**, `SalesReturn_Fact` never populated despite 19 real files on disk (matches CLAUDE.md's known open item: no Load driver for `salesreturn_fact`'s value-based rmr_gs_bo rows) |

All four populated doc types share the same coverage shape: real data is genuinely non-contiguous — the gaps are not upload failures, they're the actual real-world reporting cadence San San Marketing has, confirmed identically across all four independent fact tables.

### C2. Del Monte inventory SKU code formats — the 13a-13e check, run for the first time

| format | distinct sku_codes | share |
|---|---|---|
| `^9D[A-Z]{2}[0-9]{4,6}$` (confirmed-real pattern) | 3,178 rows / not-distinct | — |
| plain numeric | 203 | — |
| **other** | 1,790 rows | — |
| **total distinct sku_codes** | **604** | |

Per-period breakdown shows the split is **not purely temporal**: the `9D`-pattern and `other` families **coexist within every single real month** (e.g. 2023-01: 128 `9D` vs 80 `other`; 2025-12: 184 `9D` vs 76 `other`) — this is a structural mix present throughout the whole real corpus, not an era-boundary shift. The one genuinely temporal anomaly: **`plain_numeric` = 203 appears exclusively in 2023-08 and nowhere else** — this is Shape C ("ITEM CODE"/"ITEM DESCRIPTION" header format), confirmed isolated to a single file/period, not a recurring pattern.

**UNVERIFIED**: what the 1,790 "other"-format rows actually contain (a different real code family vs. malformed/truncated fragments) was not characterized row-by-row in this pass — flagging rather than guessing, since earlier this session a sample of the *dimension-level* `sku_code` (a related but distinct table, populated by load logic, not the raw parse) showed prefixes like `DM`, `7D`, `8D` that looked like a mix of a real secondary code family and outright parsing artifacts; this query is against `Inventory_Fact.sku_code` directly (the rawer parse) and wasn't re-sampled here.

### C3. Did Del Monte SKU codes change at the 2025 boundary?

**Plainly: no, not the inventory SKU codes.** C2's per-period table shows `9D`-pattern and `other`-format code counts staying in a similar, stable band (roughly 94–184 `9D`, 55–80 `other`) across every real month from 2023-01 straight through 2025-12 — no code-family shift, disappearance, or new-format introduction visible at the 2024/2025 boundary in `inventory_sign_off`. **What did change is the `sell_out` category taxonomy** (C4 below) — that break is specific to sell-out reporting, not a Del Monte-wide SKU-numbering event. B6-equivalent description-change check for Del Monte inventory SKUs: **UNVERIFIED** — not run this pass (would need a per-sku_code description-stability query against `Inventory_Fact`, analogous to B6's Unilever one; flagging as not done rather than assuming "no" without checking).

### C4. Sell-out taxonomy — Era A / Era B, confirmed with real numbers

- **98 total distinct real category_path values.**
- **Era A (fine-grained, e.g. `/ACE/BASE`, `/CHUNKS/NPI`): every single one caps at last real month = 2024-02.** Confirmed via `MAX(_period)` across all non-Era-B categories = exactly `2024-02`, no exception.
- **Era B (coarse — `BEVERAGE`, `CULINARY`, `DAIRY`, `FRUITS`, `INNOVATION`): first real month = 2025-03** for all five (DAIRY only appears 3 of the 6 possible real months, the other four appear in all 6).
- **Zero overlap, confirmed**: no real month has both an Era A and an Era B category_path present (the real calendar has no real sell_out data at all between 2024-02 and 2025-03 — that gap is itself part of the 17-month non-contiguous coverage, not extra evidence of the break).
- **Volume continuity across the break (2024-12 vs 2025-01)**: **could not be checked as asked — neither month exists in real sell_out data at all** (confirmed: real months jump from 2024-02 straight to 2025-03, per C1's coverage list). The break's immediate before/after volume comparison is **UNVERIFIED — no real data exists for the specific months requested**; the nearest real comparison would be 2024-02 (Era A) vs 2025-03 (Era B), which is a 13-month gap, not an adjacent-month comparison, so a like-for-like continuity check isn't possible from real data alone.

### C5. Per-source grain table

| doc_type | table | carries product/SKU code? | measure type | real rows | real date span |
|---|---|---|---|---|---|
| inventory_sign_off | Inventory_Fact | **yes** — `sku_code` column | **level** (`quantity_on_hand`, snapshot) | 5,171 | 2023-01→2025-12 |
| purchase_order | Purchase_Fact | **no** — schema confirmed, no product/sku column exists | flow (`units_received`) | 353 | 2023-09→2025-12 |
| sell_out | SellOut_Fact | only `category_path` (+ `product_key`, currently pointing to category-grain rows per this session's Fix 1) | flow (`quantity`) | 1,539 | 2023-01→2025-12 |
| sales_register | Sales_Fact | **no** — invoice-grain only, no product/sku column | flow (`net_amount`, invoice total) | 17,947 | 2023-01→2025-12 |
| sales_return | SalesReturn_Fact | **no** — invoice-grain only | flow (`bo_units`) | **0** (never loaded) | — |

### C6. Is SKU-level Del Monte demand derivable from any combination of sources?

**No — definitively, confirmed by schema, not inferred.** The only Del Monte source with a real SKU code is `inventory_sign_off` (a **stock level**, not a demand flow). Every flow-type source — `purchase_order`, `sales_register`, `sales_return` — has **no product/SKU column at all** (verified directly against `information_schema.columns` in C5). The "opening + purchases − closing" reconstruction `ARCHITECTURE.md`'s DEC-03 names as a deferred future option needs SKU-level purchases, which don't exist in any form. Blocking reason is structural (the source data was never captured at SKU grain for any flow), not a loading gap that could be fixed by re-running ETL.

### C7. Del Monte inventory coverage — exact months and SKU counts

| month | distinct real sku_codes |
|---|---|
| 2023-01 | 208 |
| 2023-02 | 200 |
| 2023-03 | 176 |
| 2023-04 | 179 |
| 2023-05 | 182 |
| 2023-06 | 181 |
| 2023-08 | 352 *(includes the 203 Shape-C plain-numeric codes, C2)* |
| 2023-09 | 189 |
| 2023-12 | 176 |
| 2024-01 | 174 |
| 2024-02 | 180 |
| 2025-03 | 168 |
| 2025-04 | 168 |
| 2025-06 | 170 |
| 2025-08 | 193 |
| 2025-09 | 172 |
| 2025-12 | 260 |

**17 months present** (matches the "166 SKUs / 17 months" figure cited in the prompt in shape, though the *total distinct* real inventory sku_code count across all 17 months is **604**, not 166 — 166 was this session's earlier estimate of SKUs with **full 68/68-style continuous** coverage in a different, mixed real+synthetic context; the 604 figure here is the real-only, any-month-present count, a different and larger population). Missing months (of the 36 in the 2023-01→2025-12 span): 2023-07, 2023-10, 2023-11, 2024-03 through 2025-02 (12 straight months), 2025-05, 2025-07, 2025-10, 2025-11.

## D. What's loaded vs what exists

### D1. Every fact/dimension table — row counts, principal, is_demo, date span

| table | principal | is_demo | rows |
|---|---|---|---|
| Sales_Fact | delmonte | false | 17,947 |
| Sales_Fact | delmonte | true | 35,373 |
| Purchase_Fact | delmonte | false | 353 |
| Purchase_Fact | delmonte | true | 1,757 |
| Inventory_Fact | delmonte | false | 5,171 |
| Inventory_Fact | delmonte | true | 75,269 |
| Inventory_Fact | unilever | true | 242,138 |
| SellOut_Fact | delmonte | false | 1,539 |
| SellOut_Fact | delmonte | true | 6,829 |
| SalesReturn_Fact | — | — | **0** (never loaded, all principals) |
| Unilever_SKU_Demand_Fact | (unilever, implicit) | false | 24,906 |
| Unilever_SKU_Demand_Fact | (unilever, implicit) | true | 19,669 |

Date spans: Del Monte real facts all 2023-01→2025-12 (non-contiguous, per C1). Unilever demand real: 2023-01→2026-02 (B1). Note: **`Inventory_Fact` has zero rows for `unilever, is_demo=false`** — confirmed again here, matching this session's earlier finding that no real Unilever inventory source is loaded (the SSIS SOH sheet exists on disk per B7 but isn't ingested into any fact table — this table's 242,138 `unilever/true` rows are 100% synthetic).

`ABC_Classification`: delmonte 19,817 rows, unilever 43,928 rows (both across all historical periods, not just latest). `Forecast_Result`: 136 rows, 100% unilever (Del Monte held, per this session's Fix 6c decision). `LP_Recommendation`: 430 rows, 100% unilever.

### D2. Reconciliation — raw source vs. loaded, per fact table

| doc_type | real files on disk | real rows loaded | note |
|---|---|---|---|
| inventory_sign_off | 17 | 5,171 | loaded, matches file coverage (17 real months, C1/C7) |
| purchase_order | 11 | 353 | loaded |
| sell_out | 17 | 1,539 | loaded |
| sales_register | 22 | 17,947 | loaded |
| sales_return | 19 | **0** | **files exist, sheets are promoted (A2: `sales_return/data` role = 26 promoted occurrences), but `SalesReturn_Fact` has zero rows** — confirmed a real gap between "Transform would promote this" and "Load actually wrote it." Matches the already-known open item (no Load driver built for `salesreturn_fact`'s value-based rmr_gs_bo rows). |
| ssis_summary | 105 (`raw_data` role only promotable) | **not loaded to any fact table** — `ssis_summary`'s `natural_key: null` means `transform_fact()` refuses to run for it at all (per source_of_truth.yaml's own comment: "raises loudly if this is used"). All 624,886 staged raw_data rows exist in `staging/` only, never reach Supabase. |
| unilever_sku (La Union) | 1 | 24,906 real | loaded |
| rmr_gs_bo | 2 | not checked against a fact table this pass | `SalesReturn_Fact` is 0 rows total, so if rmr_gs_bo rows were ever meant to land there, they haven't — **UNVERIFIED** whether rmr_gs_bo has its own separate target table not checked in this audit |

**The single largest raw-vs-loaded gap**: `ssis_summary`'s 624,886 raw_data rows are 100% staged, 0% loaded, blocked entirely on the unconfirmed natural key (B10). Second largest: `sales_return`'s entire 19-file, 26-sheet-occurrence real corpus, 0 rows loaded.

### D3. `reports/*.md` figures vs. live DB — staleness check

Checked this session (confirmed earlier, re-stated here for completeness) against `reports/POST_LOAD_VERIFICATION.md` (dated "Generated 2026-08-20"):

| table | report figure (total/real/synth) | **live** (total/real/synth) | status |
|---|---|---|---|
| sales_fact | 53,320 / 17,947 / 35,373 | 53,320 / 17,947 / 35,373 | ✅ matches |
| purchase_fact | 2,110 / 353 / 1,757 | 2,110 / 353 / 1,757 | ✅ matches |
| **inventory_fact** | 20,905 / 5,171 / 15,734 | **322,578** / 5,171 / **317,407** | ❌ **stale, total off by +301,673 (all synthetic growth)** |
| **sellout_fact** | 6,865 / 1,539 / 5,326 | **8,368** / 1,539 / **6,829** | ❌ **stale, total off by +1,503 (synthetic growth)** |
| unilever_sku_demand_fact | 44,575 / 24,906 / 19,669 | 44,575 / 24,906 / 19,669 | ✅ matches |

Real-row counts match exactly everywhere — every discrepancy is synthetic-data growth since the report was written, not a real-data change. **Other `reports/*.md` files** (`SELLOUT_COVERAGE_DIAGNOSIS.md`, `DELMONTE_TAXONOMY_BRIDGE.md`, `SCHEMA_RECONCILIATION_AND_ABC_TEST.md`, `SYNTHETIC_DATA_AUDIT.md`, `SYNTHETIC_STAGING_CONVERSION.md`, `PRE_LOAD_COVERAGE_CHECKLIST.md`, `STAGING_CONTRACT.md`) — **UNVERIFIED this pass**, not individually re-checked figure-by-figure against live DB; `PRE_LOAD_COVERAGE_CHECKLIST.md` is already explicitly flagged as stale/superseded by `POST_LOAD_VERIFICATION.md`'s own text.

### D4. Product_Dimension composition

| principal | grain | rows |
|---|---|---|
| delmonte | category | 99 |
| delmonte | sku | 15,339 |
| unilever | sku | 1,807 |
| **total** | | **17,245** |

Del Monte `grain=sku` code-format check (dimension level): **7,729 of 15,339 (50.4%) match the confirmed-real `9D` pattern**; 0 have a null `sku_code`; the remaining 7,610 (49.6%) use some other format (already characterized earlier this session as a mix of a plausible secondary real family and description-fragment artifacts — see this session's SKU-corruption audit for the `DM`/`7D`/`8D`-prefix breakdown, not re-run here). **How many are "real, how many synthetic, how many unattributable" by is_demo**: Product_Dimension itself **has no `is_demo` column** (confirmed via `information_schema.columns` — listed columns are `product_key, principal, grain, sku_code, category_path, product_name, pack_size, brand, unit_price, lead_time_days, status, notes, manual_reorder_point`). Real-vs-synthetic attribution for dimension rows is only inferable indirectly (via which fact rows reference them), not a direct column — **this specific cross-tab (D4's "real / synthetic / unattributable by is_demo") is structurally impossible to answer as asked**, since the dimension table doesn't carry that flag at all.

### D5. Synthetic data inventory

Every table with `is_demo=true` rows (from D1): `Sales_Fact` (35,373), `Purchase_Fact` (1,757), `Inventory_Fact` (75,269 delmonte + 242,138 unilever), `SellOut_Fact` (6,829), `Unilever_SKU_Demand_Fact` (19,669). **Which generator script produced them / date span per generator**: **UNVERIFIED** — the live rows don't carry a generator-identity column (only `_src_file` provenance, which points to the original workbook path, not which synthetic-generation script wrote it), so attributing rows to `generate_synthetic_backfill.py` vs `convert_synthetic_to_staging.py` vs `generate_synthetic_inventory.py` etc. would require cross-referencing `_src_file` naming patterns against each script's known output convention — not done this pass. **Confirm all excluded by `*_Real` views**: **yes, confirmed** — this session's own remediation work verified all six `*_Real` views are back to strict `is_demo = false` (fixed live + migration `0005` + `schema.sql` corrected), and D3's real-row-count matches above (identical to the pre-growth report) confirm the real/synthetic split is being honored correctly by every view queried this session.

## E. Model input reality

### E1. Full per-SKU table, 136 currently-forecast SKUs

**`reports/audit_E1_full_136.csv`** — all 136 rows (`product_key, sku_code, status, mape, mase, reporting_span_months, fill_rate, n_mid_gaps, max_mid_gap`). Series-shape stats (span/fill/gaps) are populated for the 89 `status='ok'` rows (computed in the prior 17a-h diagnosis pass); the 47 `insufficient_data`/`dead_sku` rows carry `status`/`mape`/`mase` only — their series-shape stats weren't recomputed in that pass since they never reached the fitting stage. **Negative-value-months per SKU** (explicitly requested) is **not a column in this CSV** — B5 established negatives exist at the population level (815 SKUs, 1,649 rows) but this wasn't joined per-row into E1; UNVERIFIED how many of the 136 specifically are affected, flagging as a gap rather than merging an unverified join.

### E2. Threshold scenarios (of the 89 currently-`ok`, real-MAPE SKUs)

| threshold | SKUs surviving | median MAPE | median MASE |
|---|---|---|---|
| ≥24 (current) | 89 | 59.44 | 1.285 |
| ≥30 | 79 | 55.02 | 1.142 |
| ≥36 | 57 | 50.23 | 1.137 |

Monotonic improvement continues as the threshold rises, consistent with 17g, but the marginal gain from 24→30 (10 SKUs dropped, median MAPE 59.4→55.0) is much smaller than from 30→36 (22 more dropped, 55.0→50.2) — most of the benefit of raising the threshold comes from cutting all the way to 36, not a partial raise to 30.

### E3. Early-exit exclusion scenarios

| cutoff (months before corpus end) | SKUs surviving | median MAPE | median MASE |
|---|---|---|---|
| N=0 (must report through 2026-02) | 76 | 54.17 | 1.145 |
| N=3 (last real ≥ 2025-11) | 82 | 55.57 | 1.175 |
| N=6 (last real ≥ 2025-08) | 84 | 56.34 | 1.175 |

Excluding only the strictest early exits (N=0, i.e. must be reporting through the very last real month) gives the best median of the three, but the improvement is modest and non-monotonic on MASE (1.145→1.175→1.175) — most of the damage 17h found is concentrated in a smaller, more extreme subgroup than "any exit within 6 months," not a smooth gradient.

### E4. Combined — threshold 36 AND no early exits

**52 SKUs survive** both filters simultaneously (out of the original 136, or 89 with a real fit).

| stat | MAPE | MASE |
|---|---|---|
| min | 9.99 | 0.390 |
| p25 | 31.14 | 0.774 |
| **median** | **47.31** | **1.114** |
| p75 | 75.44 | 1.895 |
| mean | 116.51 | 1.414 |
| max | 999.999 | 7.305 |

Best median of every scenario tested (47.31 vs. 59.44 baseline), but note **mean is still 116.5 and max still hits the ceiling** — even this most-restrictive, cleanest-possible subset retains at least one severe outlier. Combining both filters doesn't eliminate the tail, it shrinks the population that's exposed to it.

### E5. ABC coverage check

Latest classification periods: delmonte = `2026-07`, unilever = `2026-08` (these differ per principal, each computed independently — consistent with this session's earlier Fix 4 finding that delmonte and unilever aren't always on the same "latest" period).

| principal | tier | count (latest period) |
|---|---|---|
| delmonte | A | 6 |
| delmonte | B | 16 |
| delmonte | C | 22 |
| unilever | A | **136** |
| unilever | B | 178 |
| unilever | C | 1,493 |

**Unilever Tier A = 136, exactly matching `Forecast_Result`'s total row count** — a clean self-consistency confirmation that the 12a period-scoping fix is working exactly as designed: every currently-forecast SKU is Tier A in the latest period, and every Tier-A SKU is being forecast. No coverage gap between "SKUs that matter by revenue" and "SKUs getting a forecast" for Unilever.

**How many of the 52 E4-survivors (threshold-36-and-no-early-exit) are Tier A**: not queried as a distinct subset, but derivable without a further query — `Forecast_Result`'s entire population is Tier-A **by construction** (12a's join requires it), so every one of the 52 is necessarily Tier A too. The real question this answers is the inverse: **of the 136 Tier-A Unilever SKUs that matter by revenue, only 52 (38%) would survive the strictest combined history/recency filter tested in E4.** Raising the bar that far to fix the accuracy problem would cut the forecastable, revenue-relevant population by nearly two-thirds.

---

## Audit complete

All six sections (A–F) filled in with real, queried data; every gap that couldn't be closed this pass is marked **UNVERIFIED** with a stated reason rather than estimated. Supporting CSVs (`reports/audit_*.csv`) are on disk alongside this file. Nothing was changed in code or the database in the course of this audit — every number above came from a read-only query or a raw-file scan.

## F. Gaps, risks, contradictions

### F1. Claims the data contradicts, and which document to fix

| claim | source | contradicting evidence | fix in |
|---|---|---|---|
| `run_sarima.py` fast_grid/MAPE-fabrication/overshoot-guard bugs "needs fix" | CLAUDE.md "Known open items" | **Already fixed this session** (Fix 5, commit `fc30f7b`, plus this session's further 12a-12c work on top, currently uncommitted — see F4) | CLAUDE.md — stale, should be updated or removed from open items |
| `generate_sarima_artifact.py` "will crash as-is" (`forecast_quantity` vs `forecast_value`) | CLAUDE.md "Known open items" | **Already fixed this session**, same commit | CLAUDE.md — stale |
| `Forecast_Result` "Category A only... Unilever SKU grain" | `schema.sql:411-413` comment | Del Monte branch exists in `run_sarima.py`'s query and is live code, not removed (deliberately held, not deleted, per this session's Fix 5/6c decision) | `schema.sql` comment vs. code — genuine open tension, not resolved, flagged already this session as needing an adviser ruling |
| `mape NUMERIC(6,3)` | `schema.sql:421` (pre-this-session) | Live column is `NUMERIC(10,3)` — corrected in `schema.sql` this session, not yet committed (F4) | was `schema.sql`, now fixed in working tree |
| `sku_code` "NULL for Del Monte category rows" | `schema.sql:106` | Was contradicted by 99 phantom-coded rows — **already fixed and committed this session** (Fix 2) | resolved |
| `*_Real` views strict `is_demo=false` | `schema.sql` view block (pre-fix) | Was leaking `OR principal='delmonte'` — **already fixed and committed this session** (migration 0005) | resolved |
| "bo_units has no source column in any RMR YAML" | CLAUDE.md | **Verified correct** for the actual Del Monte source (B9) — not contradicted, holds up | none needed |
| Del Monte genuine data starts Jan 2023, Unilever Jan 2023–Feb 2026 | CLAUDE.md "Data realities" | **Verified correct**, matches B1/C1 exactly | none needed |

### F2. Dashboard KPIs that cannot currently be computed from real data

| KPI | blocking reason |
|---|---|
| Unilever safety stock / ROP / weeks-of-cover | Zero real Unilever inventory rows anywhere (D1) — no real stock-on-hand source is loaded, even though one exists on disk unloaded (B7/B8, SSIS SOH sheets) |
| Del Monte SKU-level forecast, reorder recommendation, SKU-level ABC | No real Del Monte SKU-level demand exists or is derivable from any source combination (C6) |
| Del Monte forecast-based cards (any) | `Forecast_Result` has 0 Del Monte rows — held pending the Fix 6c adviser ruling |
| Bad-order (BO) value/quantity at SKU grain, either principal | Del Monte RMR BO source is invoice-grain, no SKU column, verified (B9). Unilever's only BO-adjacent source with a quantity field (SSIS `B.O SUMMARY`) is category-grain and never loaded (D2) |
| Any KPI sourced from `ssis_summary`'s raw sales data | Never loaded — blocked on unconfirmed natural key (B10, D2) |
| Any KPI sourced from Del Monte sales returns | `SalesReturn_Fact` is 0 rows despite 19 real files existing (D2) |

### F3. Values the pipeline needs but no source provides

- LP cost parameters: procurement cost, storage cost, warehouse capacity, supplier ceilings — already a known open item (CLAUDE.md), no new source surfaced this audit.
- Real daily-granularity demand for the safety-stock formula's σ (currently substituting monthly σ for Unilever SKU grain) — already known, still unresolved.
- Real Unilever stock-on-hand for ROP — exists on disk (B7) but not loaded; not currently usable regardless of formula.
- Del Monte / Unilever lead times — `Product_Dimension.lead_time_days` column exists but its population rate was **not checked this pass — UNVERIFIED**.

### F4. Uncommitted state

`git status`: **`analytics/db/schema.sql` and `scripts/run_sarima.py` modified, uncommitted** — these carry this session's later work on top of the last commit (`fc30f7b`): the Tier-A period-scoping fix (12a), the 24-month threshold raise (12b), `mase` persistence (12c), the process-pool parallelization and BLAS-thread capping added mid-session, and the `schema.sql` `mape`/`mase` precision-comment correction. Also untracked: this report and its accompanying `reports/audit_*.csv` files.

**Live DB changes with no corresponding migration file**: none identified beyond what's already tracked — the schema-affecting changes from this session (`Forecast_Result.status`) already have `migrations/0008_...sql`; today's further work (12a-12c) was query-logic and data-population only, no new DDL. The Fix 6a/6b/12d `Forecast_Result` purge-and-repopulate operations are pure data (not schema) and aren't the kind of change this repo's migration convention tracks.

### F5. Found but not asked — worth knowing before scoping

- **`schema.sql` cannot currently be trusted as a from-scratch source of truth without a full diff against live.** Three independent drifts were found and fixed this session alone (the `*_Real` view leak, `sku_code` nullability, `mape` precision/`mase` documentation) — that's a pattern, not a coincidence, and there's no reason to assume it's now exhaustive.
- **The `ssis_summary` natural-key blocking comment overstates its own evidence** (B10) — "NO invoice/reference column of any kind" is false for 1 of 105 files (a clean, populated `INVOICE NO.` column, 2021-03 only). Doesn't change the practical blocking decision, but the documented *reasoning* is not fully accurate and could mislead someone re-investigating this later.
- **The 22 Unilever renumbering pairs (B4) include several bidirectional cases** — the same two Article Nos each appearing as "old" and "new" relative to each other across different windows. That reads less like clean SKU discontinuation/reissue and more like a source-system instability in how Article Nos get assigned over time. Worth treating as a systemic data-quality question, not just 22 isolated examples.
- **2 of the 105 SOH-bearing files have a structurally shifted header row** (3 blank leading columns) — a real parsing hazard for anyone building an ingestion path for this sheet later; simple header-row-position detection would break silently on these two.
- **Negative Unilever `quantity_sold` values (1,649 rows, 815 SKUs, B5) are never explained by a separate returns/credit column** — whatever nets them out happens upstream of this fact table entirely. This means every SARIMA fit this session ran was implicitly forecasting *net-of-returns* demand without that ever being an explicit, documented modeling decision — it's just how the source arrives.
- One `unknown`-doc_type file exists **outside** the `Synthetic Data` folder (A1's count: 179 unknown total, 178 confirmed as the `SALES_REGISTER_*`/`SELL_OUT_*` underscore-regex miss) — the 179th file's identity wasn't individually pinned down this pass; full list is in `reports/audit_A1_files.csv` if it matters.
