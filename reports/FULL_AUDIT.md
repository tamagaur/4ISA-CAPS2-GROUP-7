# FULL DATA AUDIT — Raw Corpus + Live Database (READ-ONLY)

Generated 2026-08-26. SELECT-only queries against `SUPABASE_DB_URL`; read-only
scan of `data/raw/`. No code, config, or data changes were made. No pipeline
run was executed. Every fact below is either a quoted query result or quoted
file/code evidence — see Part A / Part B / Part C for full detail and
citations.

## Summary table (i) — raw corpus, by doc_type

`files` = total files classified into that doc_type by `infer_doc_type()`
(real + synthetic combined, matching the universe A2/A3 were computed over —
see Part C for the real-vs-synthetic split). `unread sheets` = A2 total
sheet-instance occurrences never reached by any YAML/source_of_truth role.
`unmapped columns` = A3 total (doc_type, sheet, header) rows present in a
*read* sheet but not mapped by that doc_type's YAML.

| doc_type | files | unread sheets | unmapped columns |
|---|---|---|---|
| ssis_summary | 105 | 700 | 5 |
| purchase_order | 115 | 0 | 28 |
| inventory_sign_off | 109 | 6 | 66 |
| sales_return | 19 | 24 | 7 |
| sales_register | 22 | 4 | 15 |
| sell_out | 17 | 0 | 2 |
| rmr_gs_bo | 2 | 4 | 0 |
| unilever_sku | 1 | 0 | 0 |
| unknown (unclassified) | 178 | 178 | — |
| **TOTAL** | **568** | **916** | **123** |

## Summary table (ii) — live database, by table

`real`/`demo` columns are blank ("—") where the table has no `is_demo`
column (not applicable, not zero). `dead cols` = count of 100%-NULL or
single-distinct-value columns (Part B, B3). `drift flags` = undocumented
live columns absent from `schema.sql` (Part B, B2).

| table | rows | real | demo | dead cols | drift flags |
|---|---|---|---|---|---|
| inventory_fact | 322,578 | 80,440 | 242,138 | 0 | 1 (`cost` undocumented) |
| product_dimension | 17,245 | — | — | 5 | 1 (`manual_reorder_point` undocumented, also 100% NULL) |
| sales_fact | 53,320 | 17,947 | 35,373 | 2 | 0 |
| unilever_sku_demand_fact | 44,575 | 24,906 | 19,669 | 2 | 0 |
| sellout_fact | 8,368 | 1,539 | 6,829 | 1 | 0 |
| purchase_fact | 2,110 | 353 | 1,757 | 3 | 0 |
| abc_classification | 63,745 | — | — | 0 | 0 |
| customer_dimension | 23,712 | — | — | 1 | 0 |
| lp_recommendation | 430 | 0† | 0† | 2 | 0 |
| forecast_result | 136 | — | — | 2 | 0 |
| date_dimension | 2,191 | — | — | 1 | 0 |
| salesman_dimension | 33 | — | — | 0 | 0 |
| audit_log | 21 | — | — | 0 | 0 |
| users | 2 | — | — | 0 | 0 |
| supplier_dimension | 2 | — | — | 0 | 0 |
| **salesreturn_fact** | **0** | **0** | **0** | **all (0-row)** | 0 |

†`lp_recommendation` has no `is_demo` column; shown 0/0 because every row is
`status='pending'` demo-adjacent test output generated before any live
`forecast_result` row existed (see Part B, B5) — not literally split by demo
flag, flagged here for visibility, not a real is_demo measurement.

Views (not counted above): `salesreturn_fact_real` is also a confirmed
0-row view (its base table is empty). All other `_Real` views are non-empty
and confirmed to genuinely filter `is_demo = false` (Part B, B7).

---

=== PART A — RAW CORPUS ===

# Part A — Raw-File Corpus Audit (data/raw/)

READ-ONLY audit. Scan performed by a standalone script
(`scratchpad/scan_raw.py`) that imports and reuses, unmodified, the repo's
own read-only discovery logic:

- `profiling/reader.py::read_workbook()` (magic-byte format sniffing —
  `PK\x03\x04` = xlsx, `\xD0\xCF\x11\xE0...` = legacy xls-BIFF,
  `MIME-Version:` / `From:` text preamble = MHTML, dispatched via
  `email.message_from_bytes` + `lxml.html`), called with `full_read=True`
  (same flag Extract's `_shared.py::process_file` uses) so every row is
  read, never the profiling pass's 20s-budget partial read.
- `profiling/detect.py::trim_grid()` / `detect_header()` — the same
  phantom-column-aware trimming and header-row scoring Extract/discovery
  use.
- `profiling/profile_files.py::DOC_TYPE_PATTERNS` / `infer_doc_type()` —
  the actual filename-regex dispatch table, used unmodified (not
  re-derived).

TRUE populated row/col extent (A1's `populated_rows`/`populated_cols`
columns) was computed by scanning every returned cell for non-blank content
and taking the max row/col index actually holding data — never
`worksheet.dimensions` or any stored XML dimension attribute.

Corpus size confirmed: **568 files** scanned (568
expected: 567 `.xlsx` + 1 `.xls`). Real format breakdown (magic-byte
sniffed, not by extension): {'xlsx': 567, 'mhtml': 1}.

doc_type classification distribution (via `infer_doc_type()`, the raw
filename-regex dispatch — before Extract's `_shared.py::refine_doc_type()`
daily-vs-monthly split, see A1 notes and A5):

```
{
  "sales_register": 22,
  "rmr_gs_bo": 2,
  "inventory_sign_off": 109,
  "sales_return": 19,
  "sell_out": 17,
  "purchase_order": 115,
  "ssis_summary": 105,
  "unknown": 178,
  "unilever_sku": 1
}
```

---

## A1. Sheet inventory

One row per (file, sheet) — every one of the 568 files
appears at least once; multi-sheet workbooks appear once per sheet. Columns:
`file, doc_type, sheet_name, populated_rows, populated_cols, truncated,
header_row_index, read_error`.

- `doc_type` = `infer_doc_type(path)` result: the first `DOC_TYPE_PATTERNS`
  regex (in `profiling/profile_files.py`) whose `.search()` matches the raw
  filename. `unknown` = no pattern matched.
- `populated_rows` / `populated_cols` = TRUE probed extent (see header note
  above), not the stored `dimensions` XML attribute.
- `truncated` = True only if the reader's internal blank-row-streak cutoff
  fired before EOF (should be False everywhere here since the scan used
  `full_read=True`, which disables the profiling-pass time budget — verify
  the column is all-False before trusting completeness elsewhere).
- `header_row_index` = 0-based row Extract/discovery's `detect_header()`
  picked as the header row, inside the trimmed grid (after leading
  fully-blank rows are dropped by `trim_grid()`).
- `read_error` populated only when the whole file failed to open (empty in
  every row below — see A5 "Classification failures" for the actual error
  count, which is zero).

NOTE on `sales_register` vs `daily_sales_report`: `infer_doc_type()` (used
for this table's `doc_type` column) tags both under `sales_register`.
Extract's own second-stage `_shared.py::refine_doc_type()` re-tags the 4
files under `data/raw/Del Monte/DAILY REPORT - .../` (whose filename
matches `DAILY_REPORT_RE`) to `daily_sales_report` — those 4 files are
listed here still as `sales_register` (matching `infer_doc_type()` output
literally, per the instruction to cite the actual classifying rule), with
this note as the disclosed caveat. See A5 for confirmation these are real,
correctly-routed files (not a classification failure).

```csv
file,doc_type,sheet_name,populated_rows,populated_cols,truncated,header_row_index,read_error
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,ONE PAGER,407,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1106,45,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1107,41,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1111,25,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1112,17,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1113,46,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1114,24,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1115-11117,29,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1118,42,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1119,29,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1120,31,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1122-1124,31,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1125,26,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1126,23,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1127,27,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1128,35,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx,sales_register,1129,47,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 NOVEMBER RMR GS & BO.xlsx,rmr_gs_bo,PANG ONE PAGER,74,497,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 NOVEMBER RMR GS & BO.xlsx,rmr_gs_bo,PANG GS,60,497,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 NOVEMBER RMR GS & BO.xlsx,rmr_gs_bo,PANG BO,24,497,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 NOVEMBER RMR GS & BO.xlsx,rmr_gs_bo,ILOCOS ONE PAGER,34,497,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 NOVEMBER RMR GS & BO.xlsx,rmr_gs_bo,ILOCOS GS ,29,497,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 NOVEMBER RMR GS & BO.xlsx,rmr_gs_bo,ILOCOS BO,14,497,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,ONE PAGER,691,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1106,95,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1107,39,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1111,39,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1112,27,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1113,24,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1114,38,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1115,33,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1117,30,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1118,48,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1119,29,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1120,41,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1121,63,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1122,45,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1124,59,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1125,79,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1126,64,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1127,77,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1128,31,9,False,1,
data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx,sales_register,1129,88,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1003,43,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1004,14,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1006,16,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1007,14,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1008,24,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1009,30,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1010,30,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1011-13,23,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1014,16,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1015,32,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1016,23,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1017,33,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1018,18,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1021,39,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1022,31,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1023,31,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1024,26,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1025,22,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,ONE PAGER,385,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1027,17,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1028,31,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1029-30,26,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx,sales_register,1031,28,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 OCTOBER RMR GS & BO.xlsx,rmr_gs_bo,PANG ONE PAGER,79,497,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 OCTOBER RMR GS & BO.xlsx,rmr_gs_bo,PANG GS,55,497,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 OCTOBER RMR GS & BO.xlsx,rmr_gs_bo,PANG BO,33,497,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 OCTOBER RMR GS & BO.xlsx,rmr_gs_bo,ILOCOS ONE PAGER,76,497,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 OCTOBER RMR GS & BO.xlsx,rmr_gs_bo,ILOCOS GS ,35,497,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 OCTOBER RMR GS & BO.xlsx,rmr_gs_bo,ILOCOS BO,49,497,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,ONE PAGER,749,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1003,43,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1004,37,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1006,32,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1007,27,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1008,41,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1009,36,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1010,33,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1011,22,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1013,36,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1015,44,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1016,36,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1017,31,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1018,58,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1020,40,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1021,39,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1022,40,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1023,35,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1024,46,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1025,21,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1027,31,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1028,42,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1029,42,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1030,42,9,False,1,
data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/2025 PANG. OCTOBER SALES REGISTER.xlsx,sales_register,1031,57,9,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/APRIL_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,148,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/APRIL_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,156,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE REGISTER.xlsx,sales_register,PANGSINAN SALES REGISTER,498,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,181,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN (1).xlsx,sales_return,ILOCOS SALES RETURN,15,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN (1).xlsx,sales_return,PANGASINAN SALE RETURN,26,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN.xlsx,sales_return,ILOCOS SALES RETURN,15,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN.xlsx,sales_return,PANGASINAN SALE RETURN,26,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SELL OUT.xlsx,sell_out,ILOCOS SELL OUT,71,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SELL OUT.xlsx,sell_out,PANGASINAN SELL OUT ,72,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,163,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,141,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL INVENTORY.xlsx,inventory_sign_off,Sheet1,243,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL PURCHASES.xlsx,purchase_order,PANGASINAN PURCHASE,52,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL PURCHASES.xlsx,purchase_order,ILOCOS PURCHASE,16,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER (2),580,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER,602,14,False,1,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL SALES REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,365,14,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL SALES RETURN.xlsx,sales_return,PANGASINAN GS,42,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL SALES RETURN.xlsx,sales_return,PANGASINAN BO,11,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL SALES RETURN.xlsx,sales_return,ILOCOS GS,14,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL SALES RETURN.xlsx,sales_return,ILOCOS BO,10,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL SELL OUT.xlsx,sell_out,PANG_SELL OUT,9,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,8,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,inventory_sign_off,PANGASINAN-ACTUAL,176,18,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,inventory_sign_off,ACTUAL 090423,213,17,False,7,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,inventory_sign_off,ILOCOS-ACTUAL ,158,18,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,inventory_sign_off,ILO 090223,213,14,False,6,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_SALES REGISTER_PANGASINAN & ILOCOS_AUGUST 2023.xlsx,sales_register,PANGASINAN,573,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_SALES REGISTER_PANGASINAN & ILOCOS_AUGUST 2023.xlsx,sales_register,ILOCOS,134,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_SALES RETURN_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,sales_return,PANGASINAN,53,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_SALES RETURN_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,sales_return,ILOCOS,17,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_SELL OUT_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,sell_out,PANGASINAN_SELL OUT,78,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_SELL OUT_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,sell_out,ILOCOS_SELL OUT,67,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,186,11,False,5,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,151,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST INVENTORY.xlsx,inventory_sign_off,Sheet1,243,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST PURCHASES.xlsx,purchase_order,PANGASINAN PURCHASE,49,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST PURCHASES.xlsx,purchase_order,ILOCOS PURCHASE,29,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER (2),580,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER,602,16,False,1,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST SALES REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,407,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST SALES RETURN.xlsx,sales_return,PANGASINAN GS,59,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST SALES RETURN.xlsx,sales_return,PANGASINAN BO,26,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST SALES RETURN.xlsx,sales_return,ILOCOS GS,36,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST SALES RETURN.xlsx,sales_return,ILOCOS BO,21,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST SELL OUT.xlsx,sell_out,PANG_SELL OUT,8,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,8,4,False,2,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023 SALES REGISTER.xlsx,sales_register,PANG_SALES REG,428,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023 SALES REGISTER.xlsx,sales_register,ILOCOS_SALES REG,287,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023 SALES RETURN.xlsx,sales_return,PANG_SALES RETURN,45,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023 SALES RETURN.xlsx,sales_return,ILOCOS_SALES RETURN,51,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023_PURCHASE ORDER.xlsx,purchase_order,PANG_PURCHASE,49,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023_PURCHASE ORDER.xlsx,purchase_order,ILOCOS_PURCHASE,12,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023_SIGN OFF INVENTORY.xlsx,inventory_sign_off,PANG - SIGN OFF,161,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023_SIGN OFF INVENTORY.xlsx,inventory_sign_off,ILOCOS - SIGN OFF,138,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,229,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,198,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER INVENTORY.xlsx,inventory_sign_off,Sheet1,243,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER (2),580,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER,631,18,False,1,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SALES REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,308,18,False,2,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SALES RETURN.xlsx,sales_return,PANGASINAN GS,65,18,False,4,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SALES RETURN.xlsx,sales_return,PANGASINAN BO,18,18,False,4,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SALES RETURN.xlsx,sales_return,ILOCOS GS,24,18,False,4,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SALES RETURN.xlsx,sales_return,ILOCOS BO,16,18,False,4,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SELL OUT.xlsx,sell_out,PANG_SELL OUT,8,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,8,4,False,2,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECMBER PURCHASES.xlsx,purchase_order,PANGASINAN PURCHASE,47,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECMBER PURCHASES.xlsx,purchase_order,ILOCOS PURCHASE,26,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2023/FEBRUARY_2023_INVENTORY_SANSAN_ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,204,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2023/PANGASINAN&ILOCOS FEBRUARY 1-FEBRUARY 28 2023 SALE REGISTER.xlsx,sales_register,PANGSINAN SALES REGISTER,622,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2023/PANGASINAN&ILOCOS FEBRUARY 1-FEBRUARY 28 2023 SALE REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,163,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2023/PANGASINAN&ILOCOS FEBRUARY 1-FEBRUARY 28 2023 SALE RETURN.xlsx,sales_return,ILOCOS SALES RETURN,19,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2023/PANGASINAN&ILOCOS FEBRUARY 1-FEBRUARY 28 2023 SALE RETURN.xlsx,sales_return,PANGASINAN SALE RETURN,32,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2023/PANGASINAN&ILOCOS FEBRUARY 1-FEBRUARY 28 2023 SELL OUT.xlsx,sell_out,ILOCOS SELL OUT,65,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2023/PANGASINAN&ILOCOS FEBRUARY 1-FEBRUARY 28 2023 SELL OUT.xlsx,sell_out,PANGASINAN SELL OUT ,71,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY INVENTORY SIGN OFF.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,169,10,False,4,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY INVENTORY SIGN OFF.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,150,10,False,3,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY PURCHASES.xlsx,purchase_order,PANGASINAN PURCHASE,23,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY PURCHASES.xlsx,purchase_order,ILOCOS PURCHASE,10,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER,609,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY SALES REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,224,14,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY SALES RETURN.xlsx,sales_return,PANGASINAN SALES RETURN,44,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY SALES RETURN.xlsx,sales_return,ILOCOS SALES RETURN,23,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY SELL OUT.xlsx,sell_out,PANG_SELL OUT,71,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,71,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/JANUARY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,124,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/JANUARY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,191,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/PANGASINAN&ILOCOS JANUARY 1-JANUARY 31 2023 SALE REGISTER.xlsx,sales_register,PANGSINAN SALES REGISTER,609,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/PANGASINAN&ILOCOS JANUARY 1-JANUARY 31 2023 SALE REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,176,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/PANGASINAN&ILOCOS JANUARY 1-JANUARY 31 2023 SALE RETURN.xlsx,sales_return,ILOCOS SALES RETURN,27,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/PANGASINAN&ILOCOS JANUARY 1-JANUARY 31 2023 SALE RETURN.xlsx,sales_return,PANGASINAN SALE RETURN,47,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/PANGASINAN&ILOCOS JANUARY 1-JANUARY 31 2023 SELL OUT.xlsx,sell_out,ILOCOS SELL OUT,67,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/PANGASINAN&ILOCOS JANUARY 1-JANUARY 31 2023 SELL OUT.xlsx,sell_out,PANGASINAN SELL OUT ,74,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY INVENTORY SIGN OFF.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,158,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY INVENTORY SIGN OFF.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,134,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY PURCHASES.xlsx,purchase_order,PANGASINAN PURCHASE,28,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY PURCHASES.xlsx,purchase_order,ILOCOS PURCHASE,13,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER,526,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY SALES REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,165,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY SALES RETURN.xlsx,sales_return,PANGASINAN SALES RETURN,37,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY SALES RETURN.xlsx,sales_return,ILOCOS SALES RETURN,62,15,False,1,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY SELL OUT.xlsx,sell_out,PANG_SELL OUT,80,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,72,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/JUNE_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,151,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/JUNE_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,150,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/PANGASINAN&ILOCOS JUNE 1-JUNE 30 2023 SALE REGISTER.xlsx,sales_register,PANGSINAN SALES REGISTER,578,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/PANGASINAN&ILOCOS JUNE 1-JUNE 30 2023 SALE REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,148,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/PANGASINAN&ILOCOS JUNE 1-JUNE 30 2023 SALE RETURN.xlsx,sales_return,ILOCOS SALES RETURN,29,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/PANGASINAN&ILOCOS JUNE 1-JUNE 30 2023 SALE RETURN.xlsx,sales_return,PANGASINAN SALE RETURN,46,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/PANGASINAN&ILOCOS JUNE 1-JUNE 30 2023 SELL OUT.xlsx,sell_out,ILOCOS SELL OUT,67,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/PANGASINAN&ILOCOS JUNE 1-JUNE 30 2023 SELL OUT.xlsx,sell_out,PANGASINAN SELL OUT ,74,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,167,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,150,11,False,5,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE INVENTORY.xlsx,inventory_sign_off,Sheet1,243,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE PURCHASES.xlsx,purchase_order,PANGASINAN PURCHASE,37,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE PURCHASES.xlsx,purchase_order,ILOCOS PURCHASE,25,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER (2),580,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER,853,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE SALES REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,383,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE SALES RETURN.xlsx,sales_return,PANGASINAN GS,72,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE SALES RETURN.xlsx,sales_return,PANGASINAN BO,19,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE SALES RETURN.xlsx,sales_return,ILOCOS GS,35,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE SALES RETURN.xlsx,sales_return,ILOCOS BO,14,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE SELL OUT.xlsx,sell_out,PANG_SELL OUT,9,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,8,4,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/MARCH_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,141,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/MARCH_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOF ,159,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/PANGASINAN&ILOCOS MARCH 1-MARCH 31 2023 SALE REGISTER.xlsx,sales_register,PANGSINAN SALES REGISTER,672,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/PANGASINAN&ILOCOS MARCH 1-MARCH 31 2023 SALE REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,204,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/PANGASINAN&ILOCOS MARCH 1-MARCH 31 2023 SALE RETURN.xlsx,sales_return,ILOCOS SALES RETURN,20,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/PANGASINAN&ILOCOS MARCH 1-MARCH 31 2023 SALE RETURN.xlsx,sales_return,PANGASINAN SALE RETURN,26,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/PANGASINAN&ILOCOS MARCH 1-MARCH 31 2023 SELL OUT.xlsx,sell_out,ILOCOS SELL OUT,69,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/PANGASINAN&ILOCOS MARCH 1-MARCH 31 2023 SELL OUT.xlsx,sell_out,PANGASINAN SELL OUT ,76,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,163,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,141,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH INVENTORY.xlsx,inventory_sign_off,Sheet1,243,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH PURCHASES.xlsx,purchase_order,PANGASINAN PURCHASE,24,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH PURCHASES.xlsx,purchase_order,ILOCOS PURCHASE,18,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER (2),580,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER,767,14,False,1,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH SALES REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,361,14,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH SALES RETURN.xlsx,sales_return,PANGASINAN GS,54,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH SALES RETURN.xlsx,sales_return,PANGASINAN BO,14,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH SALES RETURN.xlsx,sales_return,ILOCOS GS,17,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH SALES RETURN.xlsx,sales_return,ILOCOS BO,12,16,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH SELL OUT.xlsx,sell_out,PANG_SELL OUT,9,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,9,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/MAY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,152,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/MAY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,165,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/PANGASINAN&ILOCOS MAY 1-MAY 31 2023 SALE REGISTER.xlsx,sales_register,PANGSINAN SALES REGISTER,637,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/PANGASINAN&ILOCOS MAY 1-MAY 31 2023 SALE REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,229,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/PANGASINAN&ILOCOS MAY 1-MAY 31 2023 SALE RETURN.xlsx,sales_return,ILOCOS SALES RETURN,30,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/PANGASINAN&ILOCOS MAY 1-MAY 31 2023 SALE RETURN.xlsx,sales_return,PANGASINAN SALE RETURN,43,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/PANGASINAN&ILOCOS MAY 1-MAY 31 2023 SELL OUT.xlsx,sell_out,ILOCOS SELL OUT,69,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/PANGASINAN&ILOCOS MAY 1-MAY 31 2023 SELL OUT.xlsx,sell_out,PANGASINAN SELL OUT ,68,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - NOVEMBER 2023/NOVEMBER 2023 SALES REGISTER.xlsx,sales_register,PANG_SALES REG,519,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - NOVEMBER 2023/NOVEMBER 2023 SALES REGISTER.xlsx,sales_register,ILOCOS_SALES REG,204,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - NOVEMBER 2023/NOVEMBER 2023 SALES RETURN.xlsx,sales_return,PANG_SALES RETURN,17,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - NOVEMBER 2023/NOVEMBER 2023 SALES RETURN.xlsx,sales_return,ILOCOS_SALES RETURN,22,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - NOVEMBER 2023/NOVEMBER 2023_PURCHASE ORDER.xlsx,purchase_order,PANG_PURCHASE,18,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - NOVEMBER 2023/NOVEMBER 2023_PURCHASE ORDER.xlsx,purchase_order,ILOCOS_PURCHASE,25,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - NOVEMBER 2023/NOVEMBER 2023_SELL OUT.xlsx,sell_out,PANG_SELL OUT,75,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - NOVEMBER 2023/NOVEMBER 2023_SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,71,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023 SALES REGISTER.xlsx,sales_register,PANG_SALES REG,632,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023 SALES REGISTER.xlsx,sales_register,ILOCOS_SALES REG,165,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023 SALES RETURN.xlsx,sales_return,PANG_SALES RETURN,55,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023 SALES RETURN.xlsx,sales_return,ILOCOS_SALES RETURN,33,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023_PURCHASE ORDER.xlsx,purchase_order,PANG_PURCHASE,29,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023_PURCHASE ORDER.xlsx,purchase_order,ILOCOS_PURCHASE,9,13,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023_SELL OUT.xlsx,sell_out,PANG_SELL OUT,76,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023_SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,71,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023_SIGN OFF INVENTORY.xlsx,inventory_sign_off,PANG - SIGN OFF,164,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023_SIGN OFF INVENTORY.xlsx,inventory_sign_off,ILOCOS - SIGN OFF,155,10,False,2,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPT. PURCHASES.xlsx,purchase_order,PANGASINAN PURCHASE,20,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPT. PURCHASES.xlsx,purchase_order,ILOCOS PURCHASE,29,23,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,167,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,148,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER INVENTORY.xlsx,inventory_sign_off,Sheet1,243,11,False,4,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER (2),580,17,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER SALES REGISTER.xlsx,sales_register,PANGASINAN SALES REGISTER,588,18,False,1,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER SALES REGISTER.xlsx,sales_register,ILOCOS SALES REGISTER,371,18,False,2,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER SALES RETURN.xlsx,sales_return,PANGASINAN GS,73,18,False,4,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER SALES RETURN.xlsx,sales_return,PANGASINAN BO,33,18,False,4,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER SALES RETURN.xlsx,sales_return,ILOCOS GS,23,18,False,4,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER SALES RETURN.xlsx,sales_return,ILOCOS BO,15,18,False,4,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER SELL OUT.xlsx,sell_out,PANG_SELL OUT,8,3,False,2,
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER SELL OUT.xlsx,sell_out,ILOCOS_SELL OUT,8,4,False,2,
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,SALES PER CUSTOMER ,5130,13,False,2,
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,RAW DATA,5123,13,False,1,
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,B.O  SUMMARY,11,12,False,1,
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,INVOICE REG(NOVEMBER 1-29 2021),5130,13,False,8,
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,"SOH(DEC 1, 2021)",863,15,False,0,
"data/raw/SSIS/2021/SSIS DAILY OCTOBER 1-30, 2021.xlsx",ssis_summary,INVENTORY,11,5,False,5,
"data/raw/SSIS/2021/SSIS DAILY OCTOBER 1-30, 2021.xlsx",ssis_summary,SALES PER CUSTOMER ,5004,13,False,2,
"data/raw/SSIS/2021/SSIS DAILY OCTOBER 1-30, 2021.xlsx",ssis_summary,RAW DATA,4997,13,False,1,
"data/raw/SSIS/2021/SSIS DAILY OCTOBER 1-30, 2021.xlsx",ssis_summary,B.O  SUMMARY,7,12,False,1,
"data/raw/SSIS/2021/SSIS DAILY OCTOBER 1-30, 2021.xlsx",ssis_summary,INVOICE REG( October 1-30 2021),5004,13,False,8,
"data/raw/SSIS/2021/SSIS DAILY OCTOBER 1-30, 2021.xlsx",ssis_summary,"SOH(Oct. 30, 2021)",867,17,False,0,
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,SALES PER CUSTOMER ,5130,13,False,2,
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,RAW DATA,5123,13,False,1,
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,B.O  SUMMARY,9,12,False,1,
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,INVOICE REG(NOVEMBER 1-29 2021),5130,13,False,8,
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,"SOH(DEC 1, 2021)",863,15,False,0,
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,SALES PER CUSTOMER ,3402,13,False,2,
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,RAW DATA,3395,13,False,1,
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,B.O  SUMMARY,7,12,False,1,
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,"INVOICE REG(DECEMBER 1-30,2021)",3402,13,False,8,
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,"SOH(DEC 27, 2021)",858,17,False,0,
data/raw/SSIS/2021/SSIS MONTHLY AUGUST 2021.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2021/SSIS MONTHLY AUGUST 2021.xlsx,ssis_summary,SALES PER CUSTOMER ,4251,13,False,2,
data/raw/SSIS/2021/SSIS MONTHLY AUGUST 2021.xlsx,ssis_summary,RAW DATA,6066,13,False,1,
data/raw/SSIS/2021/SSIS MONTHLY AUGUST 2021.xlsx,ssis_summary,B.O (JAN.2021- AUGUST.2021),19,12,False,1,
data/raw/SSIS/2021/SSIS MONTHLY AUGUST 2021.xlsx,ssis_summary,INVOICE REG( AUGUST 2021),6073,13,False,8,
data/raw/SSIS/2021/SSIS MONTHLY AUGUST 2021.xlsx,ssis_summary,"SOH(AUGUST 31, 2021)",878,17,False,0,
data/raw/SSIS/2021/SSIS MONTHLY JANUARY-JUNE 2021.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2021/SSIS MONTHLY JANUARY-JUNE 2021.xlsx,ssis_summary,SALES PER CUSTOMER ,29688,13,False,2,
data/raw/SSIS/2021/SSIS MONTHLY JANUARY-JUNE 2021.xlsx,ssis_summary,RAW DATA,29681,13,False,1,
data/raw/SSIS/2021/SSIS MONTHLY JANUARY-JUNE 2021.xlsx,ssis_summary,B.O (NOV.2020- JUNE.2021),19,12,False,1,
data/raw/SSIS/2021/SSIS MONTHLY JANUARY-JUNE 2021.xlsx,ssis_summary,INVOICE REG( JANUARY-JUNE2021),29688,13,False,8,
data/raw/SSIS/2021/SSIS MONTHLY JANUARY-JUNE 2021.xlsx,ssis_summary,"SOH(JANUARY 30, 2021)",798,14,False,0,
data/raw/SSIS/2021/SSIS MONTHLY JULY 2021.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2021/SSIS MONTHLY JULY 2021.xlsx,ssis_summary,SALES PER CUSTOMER ,6308,13,False,2,
data/raw/SSIS/2021/SSIS MONTHLY JULY 2021.xlsx,ssis_summary,RAW DATA,6301,13,False,1,
data/raw/SSIS/2021/SSIS MONTHLY JULY 2021.xlsx,ssis_summary,B.O (JAN.2021- JULY.2021),18,12,False,1,
data/raw/SSIS/2021/SSIS MONTHLY JULY 2021.xlsx,ssis_summary,INVOICE REG( JULY2021),6308,13,False,8,
data/raw/SSIS/2021/SSIS MONTHLY JULY 2021.xlsx,ssis_summary,"SOH(JUNE 30, 2021)",905,14,False,0,
data/raw/SSIS/2021/SSIS MONTHLY JUNE 2021.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2021/SSIS MONTHLY JUNE 2021.xlsx,ssis_summary,SALES PER CUSTOMER ,6376,13,False,2,
data/raw/SSIS/2021/SSIS MONTHLY JUNE 2021.xlsx,ssis_summary,RAW DATA,6369,13,False,1,
data/raw/SSIS/2021/SSIS MONTHLY JUNE 2021.xlsx,ssis_summary,B.O (NOV.2020- JUNE.2021),22,12,False,1,
data/raw/SSIS/2021/SSIS MONTHLY JUNE 2021.xlsx,ssis_summary,"INVOICE REG( JUNE 1- 30,  2021)",6376,13,False,8,
data/raw/SSIS/2021/SSIS MONTHLY JUNE 2021.xlsx,ssis_summary,"SOH(JUNE 30, 2021)",953,15,False,0,
data/raw/SSIS/2021/SSIS MONTHLY MAY 2021.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2021/SSIS MONTHLY MAY 2021.xlsx,ssis_summary,SALES PER CUSTOMER ,5492,13,False,2,
data/raw/SSIS/2021/SSIS MONTHLY MAY 2021.xlsx,ssis_summary,RAW DATA,5490,13,False,1,
data/raw/SSIS/2021/SSIS MONTHLY MAY 2021.xlsx,ssis_summary,B.O (NOV.2020-MAY.2021),22,12,False,1,
data/raw/SSIS/2021/SSIS MONTHLY MAY 2021.xlsx,ssis_summary,"INVOICE REG( MAY 03-31, 2021)",5497,13,False,8,
data/raw/SSIS/2021/SSIS MONTHLY MAY 2021.xlsx,ssis_summary,"SOH(MAY 31, 2021)",965,14,False,0,
data/raw/SSIS/2021/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (2).xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2021/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (2).xlsx,ssis_summary,SALES PER CUSTOMER ,2978,13,False,2,
data/raw/SSIS/2021/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (2).xlsx,ssis_summary,RAW DATA,2971,13,False,1,
data/raw/SSIS/2021/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (2).xlsx,ssis_summary,B.O (JAN.2021- SEPTEMBER.2021),7,12,False,1,
data/raw/SSIS/2021/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (2).xlsx,ssis_summary,INVOICE REG( Sept. 1-25 2021),2978,13,False,8,
data/raw/SSIS/2021/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (2).xlsx,ssis_summary,"SOH(Sept. 30, 2021)",894,17,False,0,
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4222,13,False,2,
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,RAW DATA,4215,13,False,1,
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,B.O  SUMMARY,11,13,False,1,
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,"INVOICE REG(AUGUST, 2022)",4222,13,False,8,
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,"SOH(SEPTEMBER 1,2022)",831,17,False,0,
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,3394,13,False,2,
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,RAW DATA,3387,13,False,1,
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,19,14,False,1,
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,"INVOICE REG(DEC. 1-28, 2022)",3394,13,False,8,
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,"SOH(DECEMBER 29,2022)",762,17,False,0,
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4424,13,False,2,
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,RAW DATA,4417,13,False,1,
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,B.O  SUMMARY,9,12,False,1,
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,"INVOICE REG(FEBRUARY 1-28,2022)",4424,13,False,8,
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,"SOH(MARCH1,2022)",874,13,False,0,
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,SALES PER CUSTOMER ,5302,13,False,2,
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,RAW DATA,5295,13,False,1,
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,B.O  SUMMARY,8,12,False,1,
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,"INVOICE REG(JANUARY 1-31,2022)",5302,13,False,8,
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,"SOH(FEB.3,2022)",842,17,False,0,
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4153,13,False,2,
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,RAW DATA,4764,13,False,1,
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,"INVOICE REG(JULY, 2022)",4073,13,False,8,
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,"SOH(AUGUST 01, 2022)",838,15,False,0,
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4771,13,False,2,
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,RAW DATA,4764,13,False,1,
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,"INVOICE REG(JUNE,2022)",4771,13,False,8,
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,"SOH(JULY 1,2022)",806,15,False,0,
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,SALES PER CUSTOMER ,5349,13,False,2,
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,RAW DATA,5342,13,False,1,
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,B.O  SUMMARY,8,12,False,1,
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,"INVOICE REG(MARCH,2022)",5349,13,False,8,
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,"SOH(MARCH31,2022)",830,13,False,0,
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4277,13,False,2,
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,RAW DATA,4270,13,False,1,
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,"INVOICE REG(MAY1-31,2022)",4277,13,False,8,
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,"SOH(JUNE1,2022)",817,17,False,0,
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,5151,13,False,2,
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,RAW DATA,5144,13,False,1,
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,B.O  SUMMARY,17,13,False,1,
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,"INVOICE REG(OCTOBER, 2022)",5151,13,False,8,
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,"SOH(NOVEMBER 3,2022)",786,17,False,0,
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4154,13,False,2,
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,RAW DATA,4147,13,False,1,
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,B.O  SUMMARY,10,13,False,1,
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,"INVOICE REG(APRIL1-30,2022)",4154,13,False,8,
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,"SOH(APRIL30,2022)",791,14,False,0,
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,5937,13,False,2,
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,RAW DATA,5930,13,False,1,
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,11,13,False,1,
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,"INVOICE REG(SEPTEMBER, 2022)",5937,13,False,8,
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,"SOH(OCTOBER 1,2022)",841,17,False,0,
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,5445,15,False,2,
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,RAW DATA,5438,15,False,1,
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,Sheet4,25,2,False,0,
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,INVOICE REG(APRIL 2024),5446,17,False,8,
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,"SOH(MAY 2, 2024)",649,17,False,0,
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,7566,15,False,2,
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,RAW DATA,7559,15,False,1,
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,INVOICE REG(AUGUST 2024),7567,17,False,8,
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,"SOH(SEPTEMBER 1, 2024)",697,17,False,0,
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,2863,15,False,2,
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,RAW DATA,2856,15,False,1,
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,Sheet4,30,2,False,0,
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,INVOICE REG(DECEMBER 2024),2864,17,False,8,
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,"SOH(JANUARY 2, 2025)",661,14,False,0,
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,6941,15,False,2,
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,RAW DATA,6934,15,False,1,
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,INVOICE REG(JULY 2024),6942,17,False,8,
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,"SOH(AUGUST 1, 2024)",745,17,False,0,
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,5608,15,False,2,
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,RAW DATA,5601,15,False,1,
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,B.O  SUMMARY,9,12,False,1,
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,INVOICE REG(JUNE 2024),5609,17,False,8,
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,"SOH(JULY 1, 2024)",656,17,False,0,
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,6354,15,False,2,
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,RAW DATA,6347,15,False,1,
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,Sheet4,25,2,False,0,
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,B.O  SUMMARY,5,13,False,1,
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,INVOICE REG(MAY 2024),6355,17,False,8,
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,"SOH(JUNE 1, 2024)",692,17,False,0,
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,5975,15,False,2,
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,RAW DATA,5968,15,False,1,
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,Sheet4,30,2,False,0,
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,INVOICE REG(NOVEMBER 2024),5976,17,False,8,
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,"SOH(DECEMBER 2, 2024)",655,14,False,0,
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,5641,15,False,2,
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,RAW DATA,5634,15,False,1,
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,Sheet4,28,2,False,0,
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,B.O  SUMMARY,10,13,False,1,
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,INVOICE REG(OCTOBER 2024),5642,17,False,8,
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,"SOH(NOVEMBER 1, 2024)",623,17,False,0,
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,7054,15,False,2,
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,RAW DATA,7047,15,False,1,
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,Sheet4,27,2,False,0,
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,INVOICE REG(SEPTEMBER 2024),7055,17,False,8,
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,"SOH(OCTOBER 1, 2024)",762,17,False,0,
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,6724,15,False,2,
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,RAW DATA,6717,15,False,1,
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,Sheet4,27,2,False,0,
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,INVOICE REG(MARCH 2025),6725,17,False,8,
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,"SOH(MAY 2, 2025)",610,14,False,0,
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,6913,15,False,2,
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,RAW DATA,6906,15,False,1,
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,Sheet4,29,2,False,0,
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,INVOICE REG(JULY 2025),6914,17,False,8,
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,"SOH(SEPTEMBER 01, 2025)",695,14,False,0,
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,4148,15,False,2,
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,RAW DATA,7172,15,False,1,
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,Sheet4,33,2,False,0,
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,INVOICE REG(DECEMBER 2025),4149,17,False,8,
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,"SOH(JANUARY 05, 2025)",777,14,False,0,
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,6237,15,False,2,
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,RAW DATA,6230,15,False,1,
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,INVOICE REG(FEBRUARY 2025),6238,17,False,8,
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,"SOH(MARCH 01, 2025)",651,14,False,0,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7052,15,False,2,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,RAW DATA,7045,15,False,1,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,Sheet4,25,2,False,0,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,INVOICE REG(JANUARY 2025),7053,17,False,8,
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,"SOH(FEBRUARY 3, 2025)",643,14,False,0,
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7726,15,False,2,
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,RAW DATA,7719,15,False,1,
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,Sheet4,29,2,False,0,
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,INVOICE REG(JULY 2025),7727,17,False,8,
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,"SOH(AUGUST 01, 2025)",672,14,False,0,
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7575,15,False,2,
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,RAW DATA,7568,15,False,1,
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,Sheet4,29,2,False,0,
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,INVOICE REG(JUNE 2025),7576,17,False,8,
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,"SOH(JULY 01, 2025)",515,14,False,0,
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7889,15,False,2,
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,RAW DATA,7882,15,False,1,
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,INVOICE REG(MARCH 2025),7890,17,False,8,
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,"SOH(APRIL 1, 2025)",648,14,False,0,
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,8746,15,False,2,
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,RAW DATA,8739,15,False,1,
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,Sheet4,28,2,False,0,
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,INVOICE REG(MAY 2025),8747,17,False,8,
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,"SOH(JUNE 1, 2025)",406,14,False,0,
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7095,15,False,2,
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,RAW DATA,7172,15,False,1,
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,Sheet4,31,2,False,0,
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,INVOICE REG(NOVEMBER 2025),7096,17,False,8,
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,"SOH(DECEMBER 01, 2025)",782,14,False,0,
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,6886,15,False,2,
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,RAW DATA,7172,15,False,1,
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,Sheet4,30,2,False,0,
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,INVOICE REG(OCTOBER 2025),6887,17,False,8,
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,"SOH(NOVEMBER 03, 2025)",787,14,False,0,
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7179,15,False,2,
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,RAW DATA,7172,15,False,1,
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,Sheet4,30,2,False,0,
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,INVOICE REG(SEPTEMBER 2025),7180,17,False,8,
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,"SOH(OCTOBER 01, 2025)",717,14,False,0,
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,SALES PER CUSTOMER ,7926,15,False,2,
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,RAW DATA,7919,15,False,1,
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,B.O  SUMMARY,7,13,False,1,
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,Sheet4,33,2,False,0,
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,INVOICE REG(FEBRUARY 2026),7927,17,False,8,
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,"SOH(MARCH 02, 2026)",814,14,False,0,
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,SALES PER CUSTOMER ,8648,15,False,2,
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,RAW DATA,8641,15,False,1,
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,Sheet4,33,2,False,0,
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,INVOICE REG(JANUARY 2026),8649,17,False,8,
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,"SOH(FEBRUARY 03, 2026)",749,14,False,0,
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,SALES PER CUSTOMER ,8576,15,False,2,
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,RAW DATA,8569,15,False,1,
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,B.O  SUMMARY,7,13,False,1,
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,Sheet4,34,3,False,0,
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,INVOICE REG(MARCH 2026),8577,17,False,8,
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,"SOH(APRIL 06, 2026)",787,14,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-01_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,204,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-01_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,160,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-02_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,211,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-02_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,152,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-03_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,191,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-03_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-04_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,186,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-04_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-05_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,173,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-05_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,130,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-06_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,216,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-06_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,129,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,221,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-08_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,208,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-08_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,138,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-09_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,224,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-09_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,183,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,145,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,239,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,125,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-12_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,177,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-12_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-01_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,151,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-01_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-02_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,178,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-02_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,153,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-03_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,189,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-03_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-04_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,202,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-04_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-05_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,181,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-05_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,127,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-06_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,195,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-06_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,134,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,198,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,137,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-08_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,184,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-08_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,150,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-09_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,168,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-09_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,157,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,236,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,128,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-12_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,158,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-12_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,134,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,167,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,188,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,138,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,154,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,139,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-03_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,159,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-03_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,126,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-04_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,239,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-04_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-05_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,160,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-05_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-06_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-06_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,133,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,187,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-08_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,205,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-08_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-09_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,239,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-09_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,131,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,168,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,144,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,184,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-12_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,204,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-12_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,145,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-01_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,193,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-01_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,124,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-02_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,191,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-02_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-05_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,239,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-05_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,172,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,134,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,232,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,201,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,139,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-01_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,179,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-01_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-02_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,176,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-02_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-03_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,186,25,False,0,
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-03_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,122,25,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-01_ILOCOS.xlsx,purchase_order,Purchase Order,18,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-01_PANGASINAN.xlsx,purchase_order,Purchase Order,32,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-02_ILOCOS.xlsx,purchase_order,Purchase Order,16,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-02_PANGASINAN.xlsx,purchase_order,Purchase Order,12,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-03_ILOCOS.xlsx,purchase_order,Purchase Order,8,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-03_PANGASINAN.xlsx,purchase_order,Purchase Order,19,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-04_ILOCOS.xlsx,purchase_order,Purchase Order,16,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-04_PANGASINAN.xlsx,purchase_order,Purchase Order,22,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-05_ILOCOS.xlsx,purchase_order,Purchase Order,8,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-05_PANGASINAN.xlsx,purchase_order,Purchase Order,17,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-06_ILOCOS.xlsx,purchase_order,Purchase Order,17,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-06_PANGASINAN.xlsx,purchase_order,Purchase Order,32,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-07_ILOCOS.xlsx,purchase_order,Purchase Order,8,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-07_PANGASINAN.xlsx,purchase_order,Purchase Order,36,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-08_ILOCOS.xlsx,purchase_order,Purchase Order,8,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-08_PANGASINAN.xlsx,purchase_order,Purchase Order,26,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-09_ILOCOS.xlsx,purchase_order,Purchase Order,9,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-09_PANGASINAN.xlsx,purchase_order,Purchase Order,20,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-10_ILOCOS.xlsx,purchase_order,Purchase Order,8,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-10_PANGASINAN.xlsx,purchase_order,Purchase Order,33,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-11_ILOCOS.xlsx,purchase_order,Purchase Order,8,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-11_PANGASINAN.xlsx,purchase_order,Purchase Order,24,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-12_ILOCOS.xlsx,purchase_order,Purchase Order,13,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2021-12_PANGASINAN.xlsx,purchase_order,Purchase Order,24,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-01_ILOCOS.xlsx,purchase_order,Purchase Order,9,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-01_PANGASINAN.xlsx,purchase_order,Purchase Order,22,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-02_ILOCOS.xlsx,purchase_order,Purchase Order,12,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-02_PANGASINAN.xlsx,purchase_order,Purchase Order,23,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-03_ILOCOS.xlsx,purchase_order,Purchase Order,8,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-03_PANGASINAN.xlsx,purchase_order,Purchase Order,28,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-04_ILOCOS.xlsx,purchase_order,Purchase Order,15,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-04_PANGASINAN.xlsx,purchase_order,Purchase Order,14,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-05_ILOCOS.xlsx,purchase_order,Purchase Order,9,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-05_PANGASINAN.xlsx,purchase_order,Purchase Order,26,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-06_ILOCOS.xlsx,purchase_order,Purchase Order,14,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-06_PANGASINAN.xlsx,purchase_order,Purchase Order,18,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-07_ILOCOS.xlsx,purchase_order,Purchase Order,8,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-07_PANGASINAN.xlsx,purchase_order,Purchase Order,37,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-08_ILOCOS.xlsx,purchase_order,Purchase Order,15,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-08_PANGASINAN.xlsx,purchase_order,Purchase Order,20,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-09_ILOCOS.xlsx,purchase_order,Purchase Order,13,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-09_PANGASINAN.xlsx,purchase_order,Purchase Order,30,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-10_ILOCOS.xlsx,purchase_order,Purchase Order,14,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-10_PANGASINAN.xlsx,purchase_order,Purchase Order,33,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-11_ILOCOS.xlsx,purchase_order,Purchase Order,13,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-11_PANGASINAN.xlsx,purchase_order,Purchase Order,32,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-12_ILOCOS.xlsx,purchase_order,Purchase Order,10,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2022-12_PANGASINAN.xlsx,purchase_order,Purchase Order,30,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-01_ILOCOS.xlsx,purchase_order,Purchase Order,20,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-01_PANGASINAN.xlsx,purchase_order,Purchase Order,40,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-02_ILOCOS.xlsx,purchase_order,Purchase Order,11,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-02_PANGASINAN.xlsx,purchase_order,Purchase Order,29,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-03_ILOCOS.xlsx,purchase_order,Purchase Order,13,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-03_PANGASINAN.xlsx,purchase_order,Purchase Order,27,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-04_ILOCOS.xlsx,purchase_order,Purchase Order,13,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-04_PANGASINAN.xlsx,purchase_order,Purchase Order,22,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-05_ILOCOS.xlsx,purchase_order,Purchase Order,18,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-05_PANGASINAN.xlsx,purchase_order,Purchase Order,35,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-06_ILOCOS.xlsx,purchase_order,Purchase Order,9,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-06_PANGASINAN.xlsx,purchase_order,Purchase Order,25,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-07_ILOCOS.xlsx,purchase_order,Purchase Order,11,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-07_PANGASINAN.xlsx,purchase_order,Purchase Order,16,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-08_ILOCOS.xlsx,purchase_order,Purchase Order,20,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-08_PANGASINAN.xlsx,purchase_order,Purchase Order,27,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-10_ILOCOS.xlsx,purchase_order,Purchase Order,12,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2023-10_PANGASINAN.xlsx,purchase_order,Purchase Order,21,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-03_ILOCOS.xlsx,purchase_order,Purchase Order,9,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-03_PANGASINAN.xlsx,purchase_order,Purchase Order,29,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-04_ILOCOS.xlsx,purchase_order,Purchase Order,17,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-04_PANGASINAN.xlsx,purchase_order,Purchase Order,26,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-05_ILOCOS.xlsx,purchase_order,Purchase Order,14,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-05_PANGASINAN.xlsx,purchase_order,Purchase Order,14,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-06_ILOCOS.xlsx,purchase_order,Purchase Order,8,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-06_PANGASINAN.xlsx,purchase_order,Purchase Order,23,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-07_ILOCOS.xlsx,purchase_order,Purchase Order,13,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-07_PANGASINAN.xlsx,purchase_order,Purchase Order,22,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-08_ILOCOS.xlsx,purchase_order,Purchase Order,11,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-08_PANGASINAN.xlsx,purchase_order,Purchase Order,37,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-09_ILOCOS.xlsx,purchase_order,Purchase Order,13,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-09_PANGASINAN.xlsx,purchase_order,Purchase Order,38,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-10_ILOCOS.xlsx,purchase_order,Purchase Order,10,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-10_PANGASINAN.xlsx,purchase_order,Purchase Order,38,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-11_ILOCOS.xlsx,purchase_order,Purchase Order,12,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-11_PANGASINAN.xlsx,purchase_order,Purchase Order,27,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-12_ILOCOS.xlsx,purchase_order,Purchase Order,12,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2024-12_PANGASINAN.xlsx,purchase_order,Purchase Order,44,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-01_ILOCOS.xlsx,purchase_order,Purchase Order,11,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-01_PANGASINAN.xlsx,purchase_order,Purchase Order,17,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-02_ILOCOS.xlsx,purchase_order,Purchase Order,10,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-02_PANGASINAN.xlsx,purchase_order,Purchase Order,41,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-05_ILOCOS.xlsx,purchase_order,Purchase Order,12,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-05_PANGASINAN.xlsx,purchase_order,Purchase Order,44,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-07_ILOCOS.xlsx,purchase_order,Purchase Order,9,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-07_PANGASINAN.xlsx,purchase_order,Purchase Order,20,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-10_ILOCOS.xlsx,purchase_order,Purchase Order,12,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-10_PANGASINAN.xlsx,purchase_order,Purchase Order,20,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-11_ILOCOS.xlsx,purchase_order,Purchase Order,13,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2025-11_PANGASINAN.xlsx,purchase_order,Purchase Order,28,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2026-01_ILOCOS.xlsx,purchase_order,Purchase Order,11,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2026-01_PANGASINAN.xlsx,purchase_order,Purchase Order,21,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2026-02_ILOCOS.xlsx,purchase_order,Purchase Order,14,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2026-02_PANGASINAN.xlsx,purchase_order,Purchase Order,29,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2026-03_ILOCOS.xlsx,purchase_order,Purchase Order,9,31,False,0,
data/raw/Synthetic Data/PURCHASE_ORDER_2026-03_PANGASINAN.xlsx,purchase_order,Purchase Order,19,31,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-01_ILOCOS.xlsx,unknown,Sales Register,245,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-01_PANGASINAN.xlsx,unknown,Sales Register,297,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-02_ILOCOS.xlsx,unknown,Sales Register,156,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-02_PANGASINAN.xlsx,unknown,Sales Register,456,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-03_ILOCOS.xlsx,unknown,Sales Register,106,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-03_PANGASINAN.xlsx,unknown,Sales Register,787,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-04_ILOCOS.xlsx,unknown,Sales Register,180,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-04_PANGASINAN.xlsx,unknown,Sales Register,581,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-05_ILOCOS.xlsx,unknown,Sales Register,148,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-05_PANGASINAN.xlsx,unknown,Sales Register,438,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-06_ILOCOS.xlsx,unknown,Sales Register,141,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-06_PANGASINAN.xlsx,unknown,Sales Register,465,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-07_ILOCOS.xlsx,unknown,Sales Register,138,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-07_PANGASINAN.xlsx,unknown,Sales Register,528,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-08_ILOCOS.xlsx,unknown,Sales Register,107,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-08_PANGASINAN.xlsx,unknown,Sales Register,427,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-09_ILOCOS.xlsx,unknown,Sales Register,114,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-09_PANGASINAN.xlsx,unknown,Sales Register,401,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-10_ILOCOS.xlsx,unknown,Sales Register,116,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-10_PANGASINAN.xlsx,unknown,Sales Register,626,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-11_ILOCOS.xlsx,unknown,Sales Register,95,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-11_PANGASINAN.xlsx,unknown,Sales Register,314,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-12_ILOCOS.xlsx,unknown,Sales Register,91,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2021-12_PANGASINAN.xlsx,unknown,Sales Register,373,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-01_ILOCOS.xlsx,unknown,Sales Register,140,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-01_PANGASINAN.xlsx,unknown,Sales Register,588,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-02_ILOCOS.xlsx,unknown,Sales Register,165,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-02_PANGASINAN.xlsx,unknown,Sales Register,658,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-03_ILOCOS.xlsx,unknown,Sales Register,232,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-03_PANGASINAN.xlsx,unknown,Sales Register,799,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-04_ILOCOS.xlsx,unknown,Sales Register,207,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-04_PANGASINAN.xlsx,unknown,Sales Register,478,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-05_ILOCOS.xlsx,unknown,Sales Register,125,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-05_PANGASINAN.xlsx,unknown,Sales Register,851,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-06_ILOCOS.xlsx,unknown,Sales Register,311,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-06_PANGASINAN.xlsx,unknown,Sales Register,439,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-07_ILOCOS.xlsx,unknown,Sales Register,145,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-07_PANGASINAN.xlsx,unknown,Sales Register,663,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-08_ILOCOS.xlsx,unknown,Sales Register,129,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-08_PANGASINAN.xlsx,unknown,Sales Register,358,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-09_ILOCOS.xlsx,unknown,Sales Register,159,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-09_PANGASINAN.xlsx,unknown,Sales Register,631,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-10_ILOCOS.xlsx,unknown,Sales Register,226,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-10_PANGASINAN.xlsx,unknown,Sales Register,780,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-11_ILOCOS.xlsx,unknown,Sales Register,135,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-11_PANGASINAN.xlsx,unknown,Sales Register,658,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-12_ILOCOS.xlsx,unknown,Sales Register,216,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2022-12_PANGASINAN.xlsx,unknown,Sales Register,609,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2023-07_ILOCOS.xlsx,unknown,Sales Register,131,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2023-07_PANGASINAN.xlsx,unknown,Sales Register,851,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2023-10_ILOCOS.xlsx,unknown,Sales Register,187,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2023-10_PANGASINAN.xlsx,unknown,Sales Register,440,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-03_ILOCOS.xlsx,unknown,Sales Register,218,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-03_PANGASINAN.xlsx,unknown,Sales Register,777,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-04_ILOCOS.xlsx,unknown,Sales Register,104,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-04_PANGASINAN.xlsx,unknown,Sales Register,796,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-05_ILOCOS.xlsx,unknown,Sales Register,200,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-05_PANGASINAN.xlsx,unknown,Sales Register,588,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-06_ILOCOS.xlsx,unknown,Sales Register,156,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-06_PANGASINAN.xlsx,unknown,Sales Register,785,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-07_ILOCOS.xlsx,unknown,Sales Register,175,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-07_PANGASINAN.xlsx,unknown,Sales Register,746,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-08_ILOCOS.xlsx,unknown,Sales Register,264,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-08_PANGASINAN.xlsx,unknown,Sales Register,851,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-09_ILOCOS.xlsx,unknown,Sales Register,214,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-09_PANGASINAN.xlsx,unknown,Sales Register,498,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-10_ILOCOS.xlsx,unknown,Sales Register,124,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-10_PANGASINAN.xlsx,unknown,Sales Register,851,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-11_ILOCOS.xlsx,unknown,Sales Register,156,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-11_PANGASINAN.xlsx,unknown,Sales Register,626,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-12_ILOCOS.xlsx,unknown,Sales Register,156,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2024-12_PANGASINAN.xlsx,unknown,Sales Register,485,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2025-01_ILOCOS.xlsx,unknown,Sales Register,117,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2025-01_PANGASINAN.xlsx,unknown,Sales Register,717,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2025-02_ILOCOS.xlsx,unknown,Sales Register,194,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2025-02_PANGASINAN.xlsx,unknown,Sales Register,810,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2025-05_ILOCOS.xlsx,unknown,Sales Register,183,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2025-05_PANGASINAN.xlsx,unknown,Sales Register,593,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2025-07_ILOCOS.xlsx,unknown,Sales Register,247,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2025-07_PANGASINAN.xlsx,unknown,Sales Register,709,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2026-01_ILOCOS.xlsx,unknown,Sales Register,166,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2026-01_PANGASINAN.xlsx,unknown,Sales Register,498,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2026-02_ILOCOS.xlsx,unknown,Sales Register,252,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2026-02_PANGASINAN.xlsx,unknown,Sales Register,839,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2026-03_ILOCOS.xlsx,unknown,Sales Register,226,29,False,0,
data/raw/Synthetic Data/SALES_REGISTER_2026-03_PANGASINAN.xlsx,unknown,Sales Register,562,29,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-01_ILOCOS.xlsx,unknown,Sell Out,71,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-01_PANGASINAN.xlsx,unknown,Sell Out,63,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-02_ILOCOS.xlsx,unknown,Sell Out,74,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-02_PANGASINAN.xlsx,unknown,Sell Out,77,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-03_ILOCOS.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-03_PANGASINAN.xlsx,unknown,Sell Out,66,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-04_ILOCOS.xlsx,unknown,Sell Out,76,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-04_PANGASINAN.xlsx,unknown,Sell Out,70,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-05_ILOCOS.xlsx,unknown,Sell Out,77,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-05_PANGASINAN.xlsx,unknown,Sell Out,78,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-06_ILOCOS.xlsx,unknown,Sell Out,74,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-06_PANGASINAN.xlsx,unknown,Sell Out,73,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-07_ILOCOS.xlsx,unknown,Sell Out,62,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-07_PANGASINAN.xlsx,unknown,Sell Out,73,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-08_ILOCOS.xlsx,unknown,Sell Out,66,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-08_PANGASINAN.xlsx,unknown,Sell Out,65,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-09_ILOCOS.xlsx,unknown,Sell Out,70,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-09_PANGASINAN.xlsx,unknown,Sell Out,67,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-10_ILOCOS.xlsx,unknown,Sell Out,71,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-10_PANGASINAN.xlsx,unknown,Sell Out,72,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-11_ILOCOS.xlsx,unknown,Sell Out,66,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-11_PANGASINAN.xlsx,unknown,Sell Out,73,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-12_ILOCOS.xlsx,unknown,Sell Out,64,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2021-12_PANGASINAN.xlsx,unknown,Sell Out,74,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-01_ILOCOS.xlsx,unknown,Sell Out,68,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-01_PANGASINAN.xlsx,unknown,Sell Out,73,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-02_ILOCOS.xlsx,unknown,Sell Out,67,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-02_PANGASINAN.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-03_ILOCOS.xlsx,unknown,Sell Out,71,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-03_PANGASINAN.xlsx,unknown,Sell Out,74,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-04_ILOCOS.xlsx,unknown,Sell Out,64,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-04_PANGASINAN.xlsx,unknown,Sell Out,65,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-05_ILOCOS.xlsx,unknown,Sell Out,74,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-05_PANGASINAN.xlsx,unknown,Sell Out,74,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-06_ILOCOS.xlsx,unknown,Sell Out,72,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-06_PANGASINAN.xlsx,unknown,Sell Out,76,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-07_ILOCOS.xlsx,unknown,Sell Out,67,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-07_PANGASINAN.xlsx,unknown,Sell Out,73,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-08_ILOCOS.xlsx,unknown,Sell Out,73,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-08_PANGASINAN.xlsx,unknown,Sell Out,75,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-09_ILOCOS.xlsx,unknown,Sell Out,72,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-09_PANGASINAN.xlsx,unknown,Sell Out,73,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-10_ILOCOS.xlsx,unknown,Sell Out,73,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-10_PANGASINAN.xlsx,unknown,Sell Out,71,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-11_ILOCOS.xlsx,unknown,Sell Out,67,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-11_PANGASINAN.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-12_ILOCOS.xlsx,unknown,Sell Out,75,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2022-12_PANGASINAN.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2023-07_ILOCOS.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2023-07_PANGASINAN.xlsx,unknown,Sell Out,74,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2023-10_ILOCOS.xlsx,unknown,Sell Out,70,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2023-10_PANGASINAN.xlsx,unknown,Sell Out,72,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2023-12_ILOCOS.xlsx,unknown,Sell Out,66,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2023-12_PANGASINAN.xlsx,unknown,Sell Out,72,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-03_ILOCOS.xlsx,unknown,Sell Out,70,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-03_PANGASINAN.xlsx,unknown,Sell Out,66,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-04_ILOCOS.xlsx,unknown,Sell Out,61,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-04_PANGASINAN.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-05_ILOCOS.xlsx,unknown,Sell Out,70,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-05_PANGASINAN.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-06_ILOCOS.xlsx,unknown,Sell Out,77,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-06_PANGASINAN.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-07_ILOCOS.xlsx,unknown,Sell Out,75,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-07_PANGASINAN.xlsx,unknown,Sell Out,71,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-08_ILOCOS.xlsx,unknown,Sell Out,70,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-08_PANGASINAN.xlsx,unknown,Sell Out,70,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-09_ILOCOS.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-09_PANGASINAN.xlsx,unknown,Sell Out,75,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-10_ILOCOS.xlsx,unknown,Sell Out,63,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-10_PANGASINAN.xlsx,unknown,Sell Out,72,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-11_ILOCOS.xlsx,unknown,Sell Out,67,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-11_PANGASINAN.xlsx,unknown,Sell Out,70,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-12_ILOCOS.xlsx,unknown,Sell Out,77,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2024-12_PANGASINAN.xlsx,unknown,Sell Out,69,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-01_ILOCOS.xlsx,unknown,Sell Out,15,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-01_PANGASINAN.xlsx,unknown,Sell Out,13,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-02_ILOCOS.xlsx,unknown,Sell Out,13,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-02_PANGASINAN.xlsx,unknown,Sell Out,14,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-05_ILOCOS.xlsx,unknown,Sell Out,16,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-05_PANGASINAN.xlsx,unknown,Sell Out,14,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-07_ILOCOS.xlsx,unknown,Sell Out,13,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-07_PANGASINAN.xlsx,unknown,Sell Out,15,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-10_ILOCOS.xlsx,unknown,Sell Out,16,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-10_PANGASINAN.xlsx,unknown,Sell Out,15,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-11_ILOCOS.xlsx,unknown,Sell Out,15,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2025-11_PANGASINAN.xlsx,unknown,Sell Out,15,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2026-01_ILOCOS.xlsx,unknown,Sell Out,13,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2026-01_PANGASINAN.xlsx,unknown,Sell Out,15,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2026-02_ILOCOS.xlsx,unknown,Sell Out,15,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2026-02_PANGASINAN.xlsx,unknown,Sell Out,16,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2026-03_ILOCOS.xlsx,unknown,Sell Out,13,19,False,0,
data/raw/Synthetic Data/SELL_OUT_2026-03_PANGASINAN.xlsx,unknown,Sell Out,15,19,False,0,
"data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT (OCTOBER 1-30, 2021).xlsx",ssis_summary,INVENTORY,11,5,False,5,
"data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT (OCTOBER 1-30, 2021).xlsx",ssis_summary,SALES PER CUSTOMER ,5004,13,False,2,
"data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT (OCTOBER 1-30, 2021).xlsx",ssis_summary,RAW DATA,4997,13,False,1,
"data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT (OCTOBER 1-30, 2021).xlsx",ssis_summary,B.O  SUMMARY,7,12,False,1,
"data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT (OCTOBER 1-30, 2021).xlsx",ssis_summary,INVOICE REG( October 1-30 2021),5004,13,False,8,
"data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT (OCTOBER 1-30, 2021).xlsx",ssis_summary,"SOH(Oct. 30, 2021)",867,17,False,0,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4154,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,RAW DATA,4147,13,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,B.O  SUMMARY,10,13,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,"INVOICE REG(APRIL1-30,2022)",4154,13,False,8,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,"SOH(APRIL30,2022)",791,14,False,0,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4424,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,RAW DATA,4417,13,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,B.O  SUMMARY,9,12,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,"INVOICE REG(FEBRUARY 1-28,2022)",4424,13,False,8,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,"SOH(MARCH1,2022)",874,13,False,0,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4694,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,RAW DATA,4687,13,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,B.O  SUMMARY,7,12,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,"INVOICE REG(JANUARY 1-28,2022)",4694,13,False,8,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,"SOH(JANUARY 29,2022)",828,17,False,0,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,SALES PER CUSTOMER ,5349,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,RAW DATA,5342,13,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,B.O  SUMMARY,8,12,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,"INVOICE REG(MARCH,2022)",5349,13,False,8,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,"SOH(MARCH31,2022)",830,13,False,0,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4277,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,RAW DATA,4270,13,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,"INVOICE REG(MAY1-31,2022)",4277,13,False,8,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,"SOH(JUNE1,2022)",817,17,False,0,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,SALES PER CUSTOMER ,5130,13,False,2,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,RAW DATA,5123,13,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,B.O  SUMMARY,9,12,False,1,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,INVOICE REG(NOVEMBER 1-29 2021),5130,13,False,8,
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,"SOH(DEC 1, 2021)",863,15,False,0,
"data/raw/Unilever/SSIS MONTHLY SALES REPORT (FEB. 01-28, 2021).xlsx",ssis_summary,INVENTORY,11,5,False,5,
"data/raw/Unilever/SSIS MONTHLY SALES REPORT (FEB. 01-28, 2021).xlsx",ssis_summary,SALES PER CUSTOMER,4190,13,False,2,
"data/raw/Unilever/SSIS MONTHLY SALES REPORT (FEB. 01-28, 2021).xlsx",ssis_summary,RAW DATA,4182,13,False,2,
"data/raw/Unilever/SSIS MONTHLY SALES REPORT (FEB. 01-28, 2021).xlsx",ssis_summary,BO INVENTORY (NOV2020-FEB2021,1915,10,False,0,
"data/raw/Unilever/SSIS MONTHLY SALES REPORT (FEB. 01-28, 2021).xlsx",ssis_summary,"STOCK CARD(FEB. 28,2021",829,14,False,0,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (APRIL,2021).xlsx",ssis_summary,INVENTORY,11,5,False,5,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (APRIL,2021).xlsx",ssis_summary,SALES PER CUSTOMER,4083,13,False,2,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (APRIL,2021).xlsx",ssis_summary,RAW DATA,4077,13,False,2,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (APRIL,2021).xlsx",ssis_summary,"B.O (NOV.2020-APRIL 30,2021)",22,12,False,1,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (APRIL,2021).xlsx",ssis_summary,"INVOICE REG( APRIL 5-30, 2021)",4083,17,False,8,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (APRIL,2021).xlsx",ssis_summary,"SOH(APRIL 30, 2021)",933,14,False,0,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (AUGUST 2021).xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (AUGUST 2021).xlsx,ssis_summary,SALES PER CUSTOMER ,4251,13,False,2,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (AUGUST 2021).xlsx,ssis_summary,RAW DATA,6066,13,False,1,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (AUGUST 2021).xlsx,ssis_summary,B.O (JAN.2021- AUGUST.2021),19,12,False,1,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (AUGUST 2021).xlsx,ssis_summary,INVOICE REG( AUGUST 2021),6073,13,False,8,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (AUGUST 2021).xlsx,ssis_summary,"SOH(AUGUST 31, 2021)",878,17,False,0,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JAN. 01-31, 2021).xlsx",ssis_summary,SALES PER CUSTOMER,4620,13,False,2,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JAN. 01-31, 2021).xlsx",ssis_summary,INVENTORY,10,5,False,4,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JAN. 01-31, 2021).xlsx",ssis_summary,RAW DATA,4614,13,False,2,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JULY 2021).xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JULY 2021).xlsx,ssis_summary,SALES PER CUSTOMER ,6308,13,False,2,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JULY 2021).xlsx,ssis_summary,RAW DATA,6301,13,False,1,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JULY 2021).xlsx,ssis_summary,B.O (JAN.2021- JULY.2021),18,12,False,1,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JULY 2021).xlsx,ssis_summary,INVOICE REG( JULY2021),6308,13,False,8,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JULY 2021).xlsx,ssis_summary,"SOH(JUNE 30, 2021)",905,14,False,0,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JUNE,2021).xlsx",ssis_summary,INVENTORY,11,5,False,5,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JUNE,2021).xlsx",ssis_summary,SALES PER CUSTOMER ,6376,13,False,2,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JUNE,2021).xlsx",ssis_summary,RAW DATA,6369,13,False,1,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JUNE,2021).xlsx",ssis_summary,B.O (NOV.2020- JUNE.2021),22,12,False,1,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JUNE,2021).xlsx",ssis_summary,"INVOICE REG( JUNE 1- 30,  2021)",6376,13,False,8,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JUNE,2021).xlsx",ssis_summary,"SOH(JUNE 30, 2021)",953,15,False,0,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MARCH 01-31,2021).xlsx",ssis_summary,INVENTORY,11,5,False,5,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MARCH 01-31,2021).xlsx",ssis_summary,SALES PER CUSTOMER,4971,14,False,2,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MARCH 01-31,2021).xlsx",ssis_summary,RAW DATA,4963,14,False,2,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MARCH 01-31,2021).xlsx",ssis_summary,BO INVENTORY (NOV2020-MARCH31),2151,10,False,0,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MARCH 01-31,2021).xlsx",ssis_summary,"STOCK CARD(APRIL 05,,2021)",854,14,False,0,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MAY,2021).xlsx",ssis_summary,INVENTORY,11,5,False,5,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MAY,2021).xlsx",ssis_summary,SALES PER CUSTOMER ,5492,13,False,2,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MAY,2021).xlsx",ssis_summary,RAW DATA,5490,13,False,1,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MAY,2021).xlsx",ssis_summary,B.O (NOV.2020-MAY.2021),22,12,False,1,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MAY,2021).xlsx",ssis_summary,"INVOICE REG( MAY 03-31, 2021)",5497,13,False,8,
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MAY,2021).xlsx",ssis_summary,"SOH(MAY 31, 2021)",965,14,False,0,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (1).xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (1).xlsx,ssis_summary,SALES PER CUSTOMER ,2978,13,False,2,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (1).xlsx,ssis_summary,RAW DATA,2971,13,False,1,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (1).xlsx,ssis_summary,B.O (JAN.2021- SEPTEMBER.2021),7,12,False,1,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (1).xlsx,ssis_summary,INVOICE REG( Sept. 1-25 2021),2978,13,False,8,
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (1).xlsx,ssis_summary,"SOH(Sept. 30, 2021)",894,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,4366,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,RAW DATA,4359,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,B.O  SUMMARY,11,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,INVOICE REG(MARCH 2023),4366,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,"SOH(MAY 2, 2023)",747,20,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,5445,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,RAW DATA,5438,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,Sheet4,25,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,INVOICE REG(APRIL 2024),5446,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,"SOH(MAY 2, 2024)",649,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,6724,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,RAW DATA,6717,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,Sheet4,27,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,INVOICE REG(MARCH 2025),6725,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,"SOH(MAY 2, 2025)",610,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4222,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,RAW DATA,4215,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,B.O  SUMMARY,11,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,"INVOICE REG(AUGUST, 2022)",4222,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,"SOH(SEPTEMBER 1,2022)",831,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,5713,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,RAW DATA,5706,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,Sheet4,16,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,B.O  SUMMARY,7,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,INVOICE REG(AUGUST 2023),5714,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,"SOH(SEPTEMBER 1, 2023)",759,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,7566,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,RAW DATA,7559,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,INVOICE REG(AUGUST 2024),7567,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,"SOH(SEPTEMBER 1, 2024)",697,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,6913,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,RAW DATA,6906,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,Sheet4,29,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,INVOICE REG(JULY 2025),6914,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,"SOH(SEPTEMBER 01, 2025)",695,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,SALES PER CUSTOMER ,3402,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,RAW DATA,3395,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,B.O  SUMMARY,5,12,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,"INVOICE REG(DECEMBER 1-30,2021)",3402,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,"SOH(DEC 27, 2021)",858,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,3394,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,RAW DATA,3387,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,19,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,"INVOICE REG(DEC. 1-28, 2022)",3394,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,"SOH(DECEMBER 29,2022)",762,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,2878,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,RAW DATA,2871,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,Sheet4,23,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,B.O  SUMMARY,9,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,INVOICE REG(DECEMBER 2023),2879,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,"SOH(JANUARY 2, 2024)",665,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,2863,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,RAW DATA,2856,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,Sheet4,30,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,INVOICE REG(DECEMBER 2024),2864,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,"SOH(JANUARY 2, 2025)",661,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,4148,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,RAW DATA,7172,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,Sheet4,33,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,INVOICE REG(DECEMBER 2025),4149,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,"SOH(JANUARY 05, 2025)",777,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,4997,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,RAW DATA,4990,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,B.O  SUMMARY,24,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,INVOICE REG(FEBRUARY 2023),4997,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,"SOH(MARCH 01, 2023)",753,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,4991,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,RAW DATA,4984,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,Sheet4,23,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,INVOICE REG(FEBRUARY 2024),4992,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,"SOH(MARCH 1, 2024)",673,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,6237,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,RAW DATA,6230,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,INVOICE REG(FEBRUARY 2025),6238,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,"SOH(MARCH 01, 2025)",651,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,4316,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,RAW DATA,4309,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,B.O  SUMMARY,22,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,INVOICE REG(JANUARY 2023),4316,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,"SOH(FEBRUARY 01, 2023)",773,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,4957,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,RAW DATA,4950,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,Sheet4,23,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,INVOICE REG(JANUARY 2024),4958,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,"SOH(FEBRUARY 1, 2024)",697,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,SALES PER CUSTOMER ,7052,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,RAW DATA,7045,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,Sheet4,25,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,INVOICE REG(JANUARY 2025),7053,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,"SOH(FEBRUARY 3, 2025)",643,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4153,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,RAW DATA,4764,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,"INVOICE REG(JULY, 2022)",4073,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,"SOH(AUGUST 01, 2022)",838,15,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,4541,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,RAW DATA,4534,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,Sheet4,16,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,B.O  SUMMARY,12,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,INVOICE REG(JULY 2023),4542,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,"SOH(AUGUST 1, 2023)",787,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,6941,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,RAW DATA,6934,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,INVOICE REG(JULY 2024),6942,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,"SOH(AUGUST 1, 2024)",745,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7726,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,RAW DATA,7719,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,Sheet4,29,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,INVOICE REG(JULY 2025),7727,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,"SOH(AUGUST 01, 2025)",672,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4771,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,RAW DATA,4764,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,"INVOICE REG(JUNE,2022)",4771,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,"SOH(JULY 1,2022)",806,15,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,5275,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,RAW DATA,5268,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,Sheet4,15,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,B.O  SUMMARY,12,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,INVOICE REG(JUNE 2023),5276,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,"SOH(JULY 3, 2023)",795,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,5608,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,RAW DATA,5601,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,B.O  SUMMARY,9,12,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,INVOICE REG(JUNE 2024),5609,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,"SOH(JULY 1, 2024)",656,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7575,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,RAW DATA,7568,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,Sheet4,29,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,INVOICE REG(JUNE 2025),7576,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,"SOH(JULY 01, 2025)",515,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,6635,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,RAW DATA,6628,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,B.O  SUMMARY,24,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,INVOICE REG(MARCH 2023),6635,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,"SOH(APRIL 1, 2023)",754,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,5193,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,RAW DATA,5186,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,Sheet4,24,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,INVOICE REG(MARCH 2024),5194,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,"SOH(APRIL 1, 2024)",667,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7889,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,RAW DATA,7882,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,Sheet4,26,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,INVOICE REG(MARCH 2025),7890,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,"SOH(APRIL 1, 2025)",648,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,6524,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,RAW DATA,6517,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,Sheet4,15,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,B.O  SUMMARY,13,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,INVOICE REG(MAY 2023),6525,15,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,"SOH(JUNE 1, 2023)",774,20,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,6354,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,RAW DATA,6347,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,Sheet4,25,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,B.O  SUMMARY,5,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,INVOICE REG(MAY 2024),6355,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,"SOH(JUNE 1, 2024)",692,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,8746,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,RAW DATA,8739,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,Sheet4,28,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,INVOICE REG(MAY 2025),8747,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,"SOH(JUNE 1, 2025)",406,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,4560,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,RAW DATA,5144,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,17,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,"INVOICE REG(NOVEMBER, 2022)",4560,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,"SOH(DECEMBER 01,2022)",739,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,4749,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,RAW DATA,4742,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,Sheet4,22,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,B.O  SUMMARY,9,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,INVOICE REG(NOVEMBER 2023),4750,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,"SOH(DECEMBER 1, 2023)",713,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,5975,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,RAW DATA,5968,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,Sheet4,30,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,INVOICE REG(NOVEMBER 2024),5976,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,"SOH(DECEMBER 2, 2024)",655,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7095,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,RAW DATA,7172,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,Sheet4,31,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,INVOICE REG(NOVEMBER 2025),7096,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,"SOH(DECEMBER 01, 2025)",782,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,5151,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,RAW DATA,5144,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,B.O  SUMMARY,17,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,"INVOICE REG(OCTOBER, 2022)",5151,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,"SOH(NOVEMBER 3,2022)",786,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,5568,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,RAW DATA,5561,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,Sheet4,20,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,B.O  SUMMARY,9,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,INVOICE REG(OCTOBER 2023),5569,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,"SOH(NOVEMBER 3, 2023)",689,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,SALES PER CUSTOMER ,5641,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,RAW DATA,5634,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,Sheet4,28,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,B.O  SUMMARY,10,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,INVOICE REG(OCTOBER 2024),5642,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,"SOH(NOVEMBER 1, 2024)",623,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,6886,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,RAW DATA,7172,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,Sheet4,30,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,INVOICE REG(OCTOBER 2025),6887,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,"SOH(NOVEMBER 03, 2025)",787,14,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,SALES PER CUSTOMER ,5937,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,RAW DATA,5930,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,11,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,"INVOICE REG(SEPTEMBER, 2022)",5937,13,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,"SOH(OCTOBER 1,2022)",841,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,SALES PER CUSTOMER  (2),505,13,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,SALES PER CUSTOMER ,5667,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,RAW DATA,5660,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,Sheet4,19,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,B.O  SUMMARY,8,14,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,INVOICE REG(SEPTEMBER 2023),5668,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,"SOH(OCTOBER 2, 2023)",721,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,SALES PER CUSTOMER ,7054,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,RAW DATA,7047,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,Sheet4,27,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,8,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,INVOICE REG(SEPTEMBER 2024),7055,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,"SOH(OCTOBER 1, 2024)",762,17,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,INVENTORY,11,5,False,5,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,SALES PER CUSTOMER ,7179,15,False,2,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,RAW DATA,7172,15,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,Sheet4,30,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,Sheet2,13,2,False,0,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,Sheet1,15,2,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,9,13,False,1,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,INVOICE REG(SEPTEMBER 2025),7180,17,False,8,
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,"SOH(OCTOBER 01, 2025)",717,14,False,0,
data/raw/Unilever/UnileverLaUnionSalesperSKU2023to2026.xls,unilever_sku,sheet1,24918,8,False,11,
```

---

## A2. Coverage diff — sheets present but never read by the pipeline

"Never read" here means: the sheet's `_sheet_role` (computed by
`analytics/etl/extract/_shared.py::infer_sheet_role()`, reproduced
verbatim in the scan script) is never in that doc_type's
`system_of_record_role` per `config/source_of_truth.yaml` — i.e. even
though Extract stages it (all sheets get staged, tagged, checksummed),
Transform's `source_of_truth.yaml` gate means it never reaches a fact
table. `daily_sales_report` is included in full (it has a column_map YAML
for tagging purposes only, per that YAML's own docstring, but
`source_of_truth.yaml` never lists it as any principal's system of
record — see `cross_check_doc_types` entries — so every one of its sheets
counts as unread here).

**Total unread-sheet occurrences (row count below, i.e. sheet-instances
across all files): 916**
**Distinct (doc_type, sheet_name, sheet_role) groups: 148**

### CRITICAL — the SSIS "INVENTORY" sheet

Verified directly (not merely asserted): searching every `ssis_summary`
file's real sheet names (case-insensitive substring `inventory`) found the
literal sheet name **`"INVENTORY"`** present in **105 of
105 ssis_summary files** scanned (`_sheet_role` = `data` per
`infer_sheet_role()`, since "INVENTORY" doesn't match any of the
raw_data/per_customer/invoice_reg/one_pager/schedule/gs/bo name patterns —
it falls through to the generic `"data"` role).

- `config/column_maps/ssis_summary.yaml` maps ONLY the `RAW DATA` sheet's
  column vocabulary (Salesman, CALENDAR DAY, REASON CODE, OUTLET, OUTLET
  NAME, GSV, TPR + UW/DT Discount, Sale After TPR & UW, VAT, Total Sales
  Amt Inc. Tax, REMARKS) — it has no entry for an "INVENTORY" sheet at all.
- `config/source_of_truth.yaml`'s `sales.unilever` entry sets
  `system_of_record_role: raw_data` and `cross_check_roles: [invoice_reg,
  per_customer_summary]` — "INVENTORY" (role `data`) is in neither list.
  It is not cross-checked, not loaded, not mentioned anywhere in
  `source_of_truth.yaml`.

So: a sheet literally named `INVENTORY`, present in 105/105
real Unilever SSIS files, is staged by Extract (everything is) but has zero
column mapping and zero source-of-truth role — it is silently dropped at
the Transform boundary with no YAML that would need to cover it. (Note:
the CLAUDE.md context text says "confirmed present in all 59 SSIS files" —
this scan found 105 ssis_summary-classified files total, of which 105 carry
an INVENTORY-named sheet; the discrepancy between "59" and this count is
flagged as-is, not reconciled, since reconciling doc_type counts against
DB state is Part B's job, not this read-only file audit's.)

Two related literal sheet-name variants also found and grouped separately
below: `"BO INVENTORY (NOV2020-FEB2021"` and
`"BO INVENTORY (NOV2020-MARCH31)"` (both role `data`, same unmapped
situation).

### Full A2 grouped table (doc_type, sheet_name, sheet_role, file_count, yaml_exists_for_doctype)

Sorted by file_count descending.

```csv
doc_type,sheet_name,sheet_role,file_count,yaml_exists_for_doctype
ssis_summary,INVENTORY,data,105,True
ssis_summary,SALES PER CUSTOMER ,per_customer_summary,101,True
unknown,Sell Out,data,92,False
ssis_summary,B.O  SUMMARY,data,90,True
unknown,Sales Register,data,86,False
ssis_summary,Sheet4,scratch,56,True
ssis_summary,SALES PER CUSTOMER  (2),per_customer_summary,45,True
ssis_summary,Sheet1,scratch,40,True
ssis_summary,Sheet2,scratch,39,True
inventory_sign_off,Sheet1,scratch,6,True
sales_return,PANGASINAN GS,gs,6,True
sales_return,PANGASINAN BO,bo,6,True
sales_return,ILOCOS GS,gs,6,True
sales_return,ILOCOS BO,bo,6,True
sales_register,ONE PAGER,one_pager,4,True
ssis_summary,"SOH(JUNE 30, 2021)",data,4,True
ssis_summary,INVOICE REG(MARCH 2025),invoice_reg,4,True
ssis_summary,INVOICE REG(JULY 2025),invoice_reg,4,True
ssis_summary,SALES PER CUSTOMER,per_customer_summary,4,True
ssis_summary,INVOICE REG(NOVEMBER 1-29 2021),invoice_reg,3,True
ssis_summary,"SOH(DEC 1, 2021)",data,3,True
ssis_summary,B.O (NOV.2020- JUNE.2021),data,3,True
rmr_gs_bo,PANG ONE PAGER,one_pager,2,True
rmr_gs_bo,ILOCOS ONE PAGER,one_pager,2,True
ssis_summary,INVOICE REG( October 1-30 2021),invoice_reg,2,True
ssis_summary,"SOH(Oct. 30, 2021)",data,2,True
ssis_summary,"INVOICE REG(DECEMBER 1-30,2021)",invoice_reg,2,True
ssis_summary,"SOH(DEC 27, 2021)",data,2,True
ssis_summary,B.O (JAN.2021- AUGUST.2021),data,2,True
ssis_summary,INVOICE REG( AUGUST 2021),invoice_reg,2,True
ssis_summary,"SOH(AUGUST 31, 2021)",data,2,True
ssis_summary,B.O (JAN.2021- JULY.2021),data,2,True
ssis_summary,INVOICE REG( JULY2021),invoice_reg,2,True
ssis_summary,"INVOICE REG( JUNE 1- 30,  2021)",invoice_reg,2,True
ssis_summary,B.O (NOV.2020-MAY.2021),data,2,True
ssis_summary,"INVOICE REG( MAY 03-31, 2021)",invoice_reg,2,True
ssis_summary,"SOH(MAY 31, 2021)",data,2,True
ssis_summary,B.O (JAN.2021- SEPTEMBER.2021),data,2,True
ssis_summary,INVOICE REG( Sept. 1-25 2021),invoice_reg,2,True
ssis_summary,"SOH(Sept. 30, 2021)",data,2,True
ssis_summary,"INVOICE REG(AUGUST, 2022)",invoice_reg,2,True
ssis_summary,"SOH(SEPTEMBER 1,2022)",data,2,True
ssis_summary,"INVOICE REG(DEC. 1-28, 2022)",invoice_reg,2,True
ssis_summary,"SOH(DECEMBER 29,2022)",data,2,True
ssis_summary,"INVOICE REG(FEBRUARY 1-28,2022)",invoice_reg,2,True
ssis_summary,"SOH(MARCH1,2022)",data,2,True
ssis_summary,"INVOICE REG(JULY, 2022)",invoice_reg,2,True
ssis_summary,"SOH(AUGUST 01, 2022)",data,2,True
ssis_summary,"INVOICE REG(JUNE,2022)",invoice_reg,2,True
ssis_summary,"SOH(JULY 1,2022)",data,2,True
ssis_summary,"INVOICE REG(MARCH,2022)",invoice_reg,2,True
ssis_summary,"SOH(MARCH31,2022)",data,2,True
ssis_summary,"INVOICE REG(MAY1-31,2022)",invoice_reg,2,True
ssis_summary,"SOH(JUNE1,2022)",data,2,True
ssis_summary,"INVOICE REG(OCTOBER, 2022)",invoice_reg,2,True
ssis_summary,"SOH(NOVEMBER 3,2022)",data,2,True
ssis_summary,"INVOICE REG(APRIL1-30,2022)",invoice_reg,2,True
ssis_summary,"SOH(APRIL30,2022)",data,2,True
ssis_summary,"INVOICE REG(SEPTEMBER, 2022)",invoice_reg,2,True
ssis_summary,"SOH(OCTOBER 1,2022)",data,2,True
ssis_summary,INVOICE REG(APRIL 2024),invoice_reg,2,True
ssis_summary,"SOH(MAY 2, 2024)",data,2,True
ssis_summary,INVOICE REG(AUGUST 2024),invoice_reg,2,True
ssis_summary,"SOH(SEPTEMBER 1, 2024)",data,2,True
ssis_summary,INVOICE REG(DECEMBER 2024),invoice_reg,2,True
ssis_summary,"SOH(JANUARY 2, 2025)",data,2,True
ssis_summary,INVOICE REG(JULY 2024),invoice_reg,2,True
ssis_summary,"SOH(AUGUST 1, 2024)",data,2,True
ssis_summary,INVOICE REG(JUNE 2024),invoice_reg,2,True
ssis_summary,"SOH(JULY 1, 2024)",data,2,True
ssis_summary,INVOICE REG(MAY 2024),invoice_reg,2,True
ssis_summary,"SOH(JUNE 1, 2024)",data,2,True
ssis_summary,INVOICE REG(NOVEMBER 2024),invoice_reg,2,True
ssis_summary,"SOH(DECEMBER 2, 2024)",data,2,True
ssis_summary,INVOICE REG(OCTOBER 2024),invoice_reg,2,True
ssis_summary,"SOH(NOVEMBER 1, 2024)",data,2,True
ssis_summary,INVOICE REG(SEPTEMBER 2024),invoice_reg,2,True
ssis_summary,"SOH(OCTOBER 1, 2024)",data,2,True
ssis_summary,"SOH(MAY 2, 2025)",data,2,True
ssis_summary,"SOH(SEPTEMBER 01, 2025)",data,2,True
ssis_summary,INVOICE REG(DECEMBER 2025),invoice_reg,2,True
ssis_summary,"SOH(JANUARY 05, 2025)",data,2,True
ssis_summary,INVOICE REG(FEBRUARY 2025),invoice_reg,2,True
ssis_summary,"SOH(MARCH 01, 2025)",data,2,True
ssis_summary,INVOICE REG(JANUARY 2025),invoice_reg,2,True
ssis_summary,"SOH(FEBRUARY 3, 2025)",data,2,True
ssis_summary,"SOH(AUGUST 01, 2025)",data,2,True
ssis_summary,INVOICE REG(JUNE 2025),invoice_reg,2,True
ssis_summary,"SOH(JULY 01, 2025)",data,2,True
ssis_summary,"SOH(APRIL 1, 2025)",data,2,True
ssis_summary,INVOICE REG(MAY 2025),invoice_reg,2,True
ssis_summary,"SOH(JUNE 1, 2025)",data,2,True
ssis_summary,INVOICE REG(NOVEMBER 2025),invoice_reg,2,True
ssis_summary,"SOH(DECEMBER 01, 2025)",data,2,True
ssis_summary,INVOICE REG(OCTOBER 2025),invoice_reg,2,True
ssis_summary,"SOH(NOVEMBER 03, 2025)",data,2,True
ssis_summary,INVOICE REG(SEPTEMBER 2025),invoice_reg,2,True
ssis_summary,"SOH(OCTOBER 01, 2025)",data,2,True
ssis_summary,INVOICE REG(MARCH 2023),invoice_reg,2,True
ssis_summary,INVOICE REG( JANUARY-JUNE2021),invoice_reg,1,True
ssis_summary,"SOH(JANUARY 30, 2021)",data,1,True
ssis_summary,"INVOICE REG(JANUARY 1-31,2022)",invoice_reg,1,True
ssis_summary,"SOH(FEB.3,2022)",data,1,True
ssis_summary,INVOICE REG(FEBRUARY 2026),invoice_reg,1,True
ssis_summary,"SOH(MARCH 02, 2026)",data,1,True
ssis_summary,INVOICE REG(JANUARY 2026),invoice_reg,1,True
ssis_summary,"SOH(FEBRUARY 03, 2026)",data,1,True
ssis_summary,INVOICE REG(MARCH 2026),invoice_reg,1,True
ssis_summary,"SOH(APRIL 06, 2026)",data,1,True
ssis_summary,"INVOICE REG(JANUARY 1-28,2022)",invoice_reg,1,True
ssis_summary,"SOH(JANUARY 29,2022)",data,1,True
ssis_summary,BO INVENTORY (NOV2020-FEB2021,bo,1,True
ssis_summary,"STOCK CARD(FEB. 28,2021",data,1,True
ssis_summary,"B.O (NOV.2020-APRIL 30,2021)",data,1,True
ssis_summary,"INVOICE REG( APRIL 5-30, 2021)",invoice_reg,1,True
ssis_summary,"SOH(APRIL 30, 2021)",data,1,True
ssis_summary,BO INVENTORY (NOV2020-MARCH31),bo,1,True
ssis_summary,"STOCK CARD(APRIL 05,,2021)",data,1,True
ssis_summary,"SOH(MAY 2, 2023)",data,1,True
ssis_summary,INVOICE REG(AUGUST 2023),invoice_reg,1,True
ssis_summary,"SOH(SEPTEMBER 1, 2023)",data,1,True
ssis_summary,INVOICE REG(DECEMBER 2023),invoice_reg,1,True
ssis_summary,"SOH(JANUARY 2, 2024)",data,1,True
ssis_summary,INVOICE REG(FEBRUARY 2023),invoice_reg,1,True
ssis_summary,"SOH(MARCH 01, 2023)",data,1,True
ssis_summary,INVOICE REG(FEBRUARY 2024),invoice_reg,1,True
ssis_summary,"SOH(MARCH 1, 2024)",data,1,True
ssis_summary,INVOICE REG(JANUARY 2023),invoice_reg,1,True
ssis_summary,"SOH(FEBRUARY 01, 2023)",data,1,True
ssis_summary,INVOICE REG(JANUARY 2024),invoice_reg,1,True
ssis_summary,"SOH(FEBRUARY 1, 2024)",data,1,True
ssis_summary,INVOICE REG(JULY 2023),invoice_reg,1,True
ssis_summary,"SOH(AUGUST 1, 2023)",data,1,True
ssis_summary,INVOICE REG(JUNE 2023),invoice_reg,1,True
ssis_summary,"SOH(JULY 3, 2023)",data,1,True
ssis_summary,"SOH(APRIL 1, 2023)",data,1,True
ssis_summary,INVOICE REG(MARCH 2024),invoice_reg,1,True
ssis_summary,"SOH(APRIL 1, 2024)",data,1,True
ssis_summary,INVOICE REG(MAY 2023),invoice_reg,1,True
ssis_summary,"SOH(JUNE 1, 2023)",data,1,True
ssis_summary,"INVOICE REG(NOVEMBER, 2022)",invoice_reg,1,True
ssis_summary,"SOH(DECEMBER 01,2022)",data,1,True
ssis_summary,INVOICE REG(NOVEMBER 2023),invoice_reg,1,True
ssis_summary,"SOH(DECEMBER 1, 2023)",data,1,True
ssis_summary,INVOICE REG(OCTOBER 2023),invoice_reg,1,True
ssis_summary,"SOH(NOVEMBER 3, 2023)",data,1,True
ssis_summary,INVOICE REG(SEPTEMBER 2023),invoice_reg,1,True
ssis_summary,"SOH(OCTOBER 2, 2023)",data,1,True
```

---

## A3. Column diff — sheets the pipeline DOES read, headers it doesn't map

Only computed for doc_types with a `config/column_maps/*.yaml` (all 9 do)
and only for sheets whose `_sheet_role` IS in that doc_type's
system-of-record role set (i.e. sheets actually eligible to reach
Transform's `apply_column_map()` — checking column coverage on a sheet A2
already flagged as unread would double-count the same gap two ways).
Matching mirrors `transform.py`'s case-insensitive/whitespace-normalized
comparison. `__colN__` placeholders (Extract's name for a header-less
column, position N) are included when not explicitly referenced by the
YAML — several YAMLs (`sell_out.yaml`, `unilever_sku.yaml`,
`inventory_sign_off.yaml`) deliberately map specific `__colN__` positions,
so a different `__colN__` showing up here means a real, currently-unmapped
positional column, not a detection artifact.

**Total unique (doc_type, sheet_name, unmapped_header) rows:
123**

Notable / verbatim findings:

- `inventory_sign_off`, sheet `"ACTUAL 090423"` (2023-era 17/18-column
  layout, `data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/...xlsx`):
  headers `"ITEM CODE"`, `"ITEM DESCRIPTION"`, `"PRICE/PCS"`, `"PRICE/CS"`,
  `"case"`, `"TOTAL PCS"`, `"CASE"`, `"NEAR EXPIRY/ EXPIRED"`, `"DAMAGED"`,
  `"VARIANCE"`, `"AMOUNT"`, and placeholder `__col15__` — none of these
  are in `inventory_sign_off.yaml` (which only maps `__col1__`, Quantity,
  Cost, Valuation, Valuation with VAT, CAS, PCS, PKG, in PCS, in Cases).
  This is a genuinely different column vocabulary from the YAML's assumed
  2023/2025 templates — a third real shape.
- `inventory_sign_off`, sheet `"Inventory Sign Off"` (Synthetic Data
  files, 192 occurrences — see A5 anomaly note
  below): unmapped headers literally include `_src_file`, `_src_sheet`,
  `_header_row`, `_row_ordinal`, `_principal`, `_region`, and `__col0__` —
  i.e. Extract's own internal provenance-column NAMES appear as raw
  SOURCE headers in these synthetic files (verbatim, confirmed in the scan
  output), not as pipeline-added columns.
- Full itemization below (doc_type, sheet_name, unmapped_header,
  file_count).

```csv
doc_type,sheet_name,unmapped_header,file_count
inventory_sign_off,ACTUAL 090423,ITEM CODE,1
inventory_sign_off,ACTUAL 090423,ITEM DESCRIPTION,1
inventory_sign_off,ACTUAL 090423,PRICE/PCS,1
inventory_sign_off,ACTUAL 090423,PRICE/CS,1
inventory_sign_off,ACTUAL 090423,case,1
inventory_sign_off,ACTUAL 090423,TOTAL PCS,1
inventory_sign_off,ACTUAL 090423,CASE,1
inventory_sign_off,ACTUAL 090423,NEAR EXPIRY/ EXPIRED,1
inventory_sign_off,ACTUAL 090423,DAMAGED,1
inventory_sign_off,ACTUAL 090423,VARIANCE,1
inventory_sign_off,ACTUAL 090423,__col15__,1
inventory_sign_off,ACTUAL 090423,AMOUNT,1
inventory_sign_off,ILO 090223,ITEM CODE,1
inventory_sign_off,ILO 090223,ITEM DESCRIPTION,1
inventory_sign_off,ILO 090223,PRICE/PCS,1
inventory_sign_off,ILO 090223,PRICE/CS,1
inventory_sign_off,ILO 090223,case,1
inventory_sign_off,ILO 090223,TOTAL PCS,1
inventory_sign_off,ILO 090223,CASE,1
inventory_sign_off,ILO 090223,WH-BO (FEB-AUG24),1
inventory_sign_off,ILO 090223,OLD VARIANCE,1
inventory_sign_off,ILO 090223,VARIANCE,1
inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,__col0__,8
inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,__col8__,6
inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,__col9__,6
inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,__col10__,6
inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,68649,1
inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,2902.0827777777777,1
inventory_sign_off,ILOCOS - SIGN OFF,__col0__,2
inventory_sign_off,ILOCOS INVENTORY SIGNOF ,__col0__,1
inventory_sign_off,ILOCOS INVENTORY SIGNOFF,__col0__,5
inventory_sign_off,ILOCOS-ACTUAL ,__col0__,1
inventory_sign_off,ILOCOS-ACTUAL ,__col2__,1
inventory_sign_off,ILOCOS-ACTUAL ,__col5__,1
inventory_sign_off,ILOCOS-ACTUAL ,__col6__,1
inventory_sign_off,ILOCOS-ACTUAL ,__col7__,1
inventory_sign_off,ILOCOS-ACTUAL ,__col8__,1
inventory_sign_off,Inventory Sign Off,__col0__,92
inventory_sign_off,Inventory Sign Off,_src_file,92
inventory_sign_off,Inventory Sign Off,_src_sheet,92
inventory_sign_off,Inventory Sign Off,_header_row,92
inventory_sign_off,Inventory Sign Off,_row_ordinal,92
inventory_sign_off,Inventory Sign Off,_principal,92
inventory_sign_off,Inventory Sign Off,_region,92
inventory_sign_off,Inventory Sign Off,_period,92
inventory_sign_off,Inventory Sign Off,_doc_type,92
inventory_sign_off,Inventory Sign Off,_sheet_role,92
inventory_sign_off,Inventory Sign Off,_grain,92
inventory_sign_off,Inventory Sign Off,_checksum_status,92
inventory_sign_off,Inventory Sign Off,_checksum_column,92
inventory_sign_off,Inventory Sign Off,_checksum_expected,92
inventory_sign_off,Inventory Sign Off,_checksum_got,92
inventory_sign_off,Inventory Sign Off,_checksum_diff,92
inventory_sign_off,PANG - SIGN OFF,__col0__,2
inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,__col0__,5
inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,__col0__,8
inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,__col8__,7
inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,__col9__,7
inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,__col10__,6
inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,__col7__,1
inventory_sign_off,PANGASINAN-ACTUAL,__col0__,1
inventory_sign_off,PANGASINAN-ACTUAL,__col2__,1
inventory_sign_off,PANGASINAN-ACTUAL,__col5__,1
inventory_sign_off,PANGASINAN-ACTUAL,__col6__,1
inventory_sign_off,PANGASINAN-ACTUAL,__col7__,1
inventory_sign_off,PANGASINAN-ACTUAL,__col8__,1
purchase_order,ILOCOS PURCHASE,Posted,8
purchase_order,ILOCOS PURCHASE,Net Amount ( Actual Invoice),6
purchase_order,ILOCOS PURCHASE,__col17__,1
purchase_order,ILOCOS PURCHASE,__col18__,1
purchase_order,ILOCOS PURCHASE,__col19__,1
purchase_order,ILOCOS PURCHASE,__col20__,1
purchase_order,ILOCOS PURCHASE,__col21__,1
purchase_order,ILOCOS PURCHASE,__col22__,1
purchase_order,ILOCOS_PURCHASE,Posted,3
purchase_order,PANGASINAN PURCHASE,Posted,8
purchase_order,PANGASINAN PURCHASE,Net Amount ( Actual Invoice),6
purchase_order,PANG_PURCHASE,Posted,3
purchase_order,Purchase Order,Posted,104
purchase_order,Purchase Order,_src_file,104
purchase_order,Purchase Order,_src_sheet,104
purchase_order,Purchase Order,_header_row,104
purchase_order,Purchase Order,_row_ordinal,104
purchase_order,Purchase Order,_principal,104
purchase_order,Purchase Order,_region,104
purchase_order,Purchase Order,_period,104
purchase_order,Purchase Order,_doc_type,104
purchase_order,Purchase Order,_sheet_role,104
purchase_order,Purchase Order,_grain,104
purchase_order,Purchase Order,_checksum_status,104
purchase_order,Purchase Order,_checksum_column,104
purchase_order,Purchase Order,_checksum_expected,104
purchase_order,Purchase Order,_checksum_got,104
purchase_order,Purchase Order,_checksum_diff,104
sales_register,ILOCOS,Posted,1
sales_register,ILOCOS SALES REGISTER,Posted,14
sales_register,ILOCOS SALES REGISTER,Total CAS,2
sales_register,ILOCOS SALES REGISTER,Total PCS,2
sales_register,ILOCOS_SALES REG,Posted,3
sales_register,PANGASINAN,Posted,1
sales_register,PANGASINAN SALES REGISTER,Posted,6
sales_register,PANGASINAN SALES REGISTER,__col13__,2
sales_register,PANGASINAN SALES REGISTER,Total CAS,2
sales_register,PANGASINAN SALES REGISTER,Total PCS,2
sales_register,PANGASINAN SALES REGISTER (2),Posted,6
sales_register,PANGASINAN SALES REGISTER (2),__col15__,6
sales_register,PANGASINAN SALES REGISTER (2),REMARKS,6
sales_register,PANGSINAN SALES REGISTER,Posted,6
sales_register,PANG_SALES REG,Posted,3
sales_return,ILOCOS,Posted,1
sales_return,ILOCOS SALES RETURN,Posted,9
sales_return,ILOCOS_SALES RETURN,Posted,3
sales_return,PANGASINAN,Posted,1
sales_return,PANGASINAN SALE RETURN,Posted,7
sales_return,PANGASINAN SALES RETURN,Posted,2
sales_return,PANG_SALES RETURN,Posted,3
sell_out,ILOCOS_SELL OUT,Total With Tax,1
sell_out,PANGASINAN_SELL OUT,Total With Tax,1
ssis_summary,RAW DATA,__col1__,105
ssis_summary,RAW DATA,NIV,105
ssis_summary,RAW DATA,UL GSV,56
ssis_summary,RAW DATA,Mark-up/Mark-down Value in %,56
ssis_summary,RAW DATA,INVOICE NO.,1
```

---

## A4. Non-sales content flag

Case-insensitive substring match on every header cell (read + unread
sheets alike) against: `inventory, stock, on-hand/on hand, cost,
valuation, price, capacity, warehouse, category, brand, supplier`.

**Sheets with at least one flagged header: 446**

Full itemization (file, doc_type, sheet_name, flagged_headers — semicolon
separated, verbatim):

```csv
file,doc_type,sheet_name,flagged_headers
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/APRIL_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/APRIL_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - APRIL 2025/2025 APRIL INVENTORY.xlsx,inventory_sign_off,Sheet1,CATEGORY; PRODUCT LIST PRICE (VAT-EX) CASE; PRODUCT LIST PRICE (VAT-INC) CASE
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,inventory_sign_off,PANGASINAN-ACTUAL,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,inventory_sign_off,ACTUAL 090423,PRICE/PCS; PRICE/CS
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,inventory_sign_off,ILOCOS-ACTUAL ,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx,inventory_sign_off,ILO 090223,PRICE/PCS; PRICE/CS
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - AUGUST 2025/2025 AUGUST INVENTORY.xlsx,inventory_sign_off,Sheet1,CATEGORY; PRODUCT LIST PRICE (VAT-EX) CASE; PRODUCT LIST PRICE (VAT-INC) CASE
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023_SIGN OFF INVENTORY.xlsx,inventory_sign_off,PANG - SIGN OFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2023/DECEMBER 2023_SIGN OFF INVENTORY.xlsx,inventory_sign_off,ILOCOS - SIGN OFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER INVENTORY.xlsx,inventory_sign_off,Sheet1,CATEGORY; PRODUCT LIST PRICE (VAT-EX) CASE; PRODUCT LIST PRICE (VAT-INC) CASE
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2023/FEBRUARY_2023_INVENTORY_SANSAN_ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY INVENTORY SIGN OFF.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY INVENTORY SIGN OFF.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/JANUARY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2023/JANUARY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY INVENTORY SIGN OFF.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY INVENTORY SIGN OFF.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/JUNE_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - JUNE 2023/JUNE_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - JUNE 2025/2025 JUNE INVENTORY.xlsx,inventory_sign_off,Sheet1,CATEGORY; PRODUCT LIST PRICE (VAT-EX) CASE; PRODUCT LIST PRICE (VAT-INC) CASE
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/MARCH_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - MARCH 2023/MARCH_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOF ,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - MARCH 2025/2025 MARCH INVENTORY.xlsx,inventory_sign_off,Sheet1,CATEGORY; PRODUCT LIST PRICE (VAT-EX) CASE; PRODUCT LIST PRICE (VAT-INC) CASE
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/MAY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,PANGASINAN INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - MAY 2023/MAY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx,inventory_sign_off,ILOCOS INVENTORY SIGNOFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023_SIGN OFF INVENTORY.xlsx,inventory_sign_off,PANG - SIGN OFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2023/SEPTEMBER 2023_SIGN OFF INVENTORY.xlsx,inventory_sign_off,ILOCOS - SIGN OFF,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER INVENTORY.xlsx,inventory_sign_off,PANGASINAN SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER INVENTORY.xlsx,inventory_sign_off,ILOCOS  SIGN OFF INVENTORY,Cost; Valuation; Valuation with VAT
data/raw/Del Monte/MONTHLY REPORT - SEPTEMBER 2025/2025 SEPTEMBER INVENTORY.xlsx,inventory_sign_off,Sheet1,CATEGORY; PRODUCT LIST PRICE (VAT-EX) CASE; PRODUCT LIST PRICE (VAT-INC) CASE
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2021/SSIS DAILY NOVEMBER 1 - 29.xlsx,ssis_summary,"SOH(DEC 1, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
"data/raw/SSIS/2021/SSIS DAILY OCTOBER 1-30, 2021.xlsx",ssis_summary,INVENTORY,AT COST
"data/raw/SSIS/2021/SSIS DAILY OCTOBER 1-30, 2021.xlsx",ssis_summary,B.O  SUMMARY,CATEGORY
"data/raw/SSIS/2021/SSIS DAILY OCTOBER 1-30, 2021.xlsx",ssis_summary,"SOH(Oct. 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2021/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (3).xlsx,ssis_summary,"SOH(DEC 1, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2021/SSIS DECEMBER 2021.xlsx,ssis_summary,"SOH(DEC 27, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2021/SSIS MONTHLY AUGUST 2021.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2021/SSIS MONTHLY AUGUST 2021.xlsx,ssis_summary,B.O (JAN.2021- AUGUST.2021),CATEGORY
data/raw/SSIS/2021/SSIS MONTHLY AUGUST 2021.xlsx,ssis_summary,"SOH(AUGUST 31, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2021/SSIS MONTHLY JANUARY-JUNE 2021.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2021/SSIS MONTHLY JANUARY-JUNE 2021.xlsx,ssis_summary,B.O (NOV.2020- JUNE.2021),CATEGORY
data/raw/SSIS/2021/SSIS MONTHLY JANUARY-JUNE 2021.xlsx,ssis_summary,"SOH(JANUARY 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2021/SSIS MONTHLY JULY 2021.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2021/SSIS MONTHLY JULY 2021.xlsx,ssis_summary,B.O (JAN.2021- JULY.2021),CATEGORY
data/raw/SSIS/2021/SSIS MONTHLY JULY 2021.xlsx,ssis_summary,"SOH(JUNE 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2021/SSIS MONTHLY JUNE 2021.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2021/SSIS MONTHLY JUNE 2021.xlsx,ssis_summary,B.O (NOV.2020- JUNE.2021),CATEGORY
data/raw/SSIS/2021/SSIS MONTHLY JUNE 2021.xlsx,ssis_summary,"SOH(JUNE 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2021/SSIS MONTHLY MAY 2021.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2021/SSIS MONTHLY MAY 2021.xlsx,ssis_summary,B.O (NOV.2020-MAY.2021),CATEGORY
data/raw/SSIS/2021/SSIS MONTHLY MAY 2021.xlsx,ssis_summary,"SOH(MAY 31, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2021/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (2).xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2021/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (2).xlsx,ssis_summary,B.O (JAN.2021- SEPTEMBER.2021),CATEGORY
data/raw/SSIS/2021/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (2).xlsx,ssis_summary,"SOH(Sept. 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS AUGUST 2022.xlsx,ssis_summary,"SOH(SEPTEMBER 1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS DECEMBER 2022.xlsx,ssis_summary,"SOH(DECEMBER 29,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS FEBRUARY.2022.xlsx,ssis_summary,"SOH(MARCH1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS JANUARY.2022.xlsx,ssis_summary,"SOH(FEB.3,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS JULY 2022.xlsx,ssis_summary,"SOH(AUGUST 01, 2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS JUNE 2022.xlsx,ssis_summary,"SOH(JULY 1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS MARCH.2022.xlsx,ssis_summary,"SOH(MARCH31,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS MAY 2022.xlsx,ssis_summary,"SOH(JUNE1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS OCTOBER 2022.xlsx,ssis_summary,"SOH(NOVEMBER 3,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS REPORT APRIL 2022.xlsx,ssis_summary,"SOH(APRIL30,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2022/SSIS SEPTEMBER 2022.xlsx,ssis_summary,"SOH(OCTOBER 1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2024/SSIS APRIL 2024.xlsx,ssis_summary,"SOH(MAY 2, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2024/SSIS AUGUST 2024.xlsx,ssis_summary,"SOH(SEPTEMBER 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2024/SSIS DECEMBER 2024.xlsx,ssis_summary,"SOH(JANUARY 2, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2024/SSIS JULY 2024.xlsx,ssis_summary,"SOH(AUGUST 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2024/SSIS JUNE 2024.xlsx,ssis_summary,"SOH(JULY 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2024/SSIS MAY 2024.xlsx,ssis_summary,"SOH(JUNE 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2024/SSIS NOVEMBER 2024.xlsx,ssis_summary,"SOH(DECEMBER 2, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2024/SSIS OCTOBER 2024.xlsx,ssis_summary,"SOH(NOVEMBER 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2024/SSIS SEPTEMBER 2024.xlsx,ssis_summary,"SOH(OCTOBER 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS APRIL 2025.xlsx,ssis_summary,"SOH(MAY 2, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS AUGUST 2025.xlsx,ssis_summary,"SOH(SEPTEMBER 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS DECEMBER 2025.xlsx,ssis_summary,"SOH(JANUARY 05, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS FEBRUARY 2025.xlsx,ssis_summary,"SOH(MARCH 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS JANUARY 2025.xlsx,ssis_summary,"SOH(FEBRUARY 3, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS JULY 2025.xlsx,ssis_summary,"SOH(AUGUST 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS JUNE 2025.xlsx,ssis_summary,"SOH(JULY 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS MARCH 2025.xlsx,ssis_summary,"SOH(APRIL 1, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS MAY 2025.xlsx,ssis_summary,"SOH(JUNE 1, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS NOVEMBER 2025.xlsx,ssis_summary,"SOH(DECEMBER 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS OCTOBER 2025.xlsx,ssis_summary,"SOH(NOVEMBER 03, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2025/SSIS SEPTEMBER 2025.xlsx,ssis_summary,"SOH(OCTOBER 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2026/SSIS FEBRUARY 202.xlsx,ssis_summary,"SOH(MARCH 02, 2026)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2026/SSIS JANUARY 2026.xlsx,ssis_summary,"SOH(FEBRUARY 03, 2026)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/SSIS/2026/SSIS MARCH 2026.xlsx,ssis_summary,"SOH(APRIL 06, 2026)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-01_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-01_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-02_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-02_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-03_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-03_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-04_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-04_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-05_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-05_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-06_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-06_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-08_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-08_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-09_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-09_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-12_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2021-12_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-01_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-01_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-02_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-02_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-03_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-03_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-04_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-04_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-05_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-05_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-06_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-06_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-08_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-08_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-09_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-09_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-12_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2022-12_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2023-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-03_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-03_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-04_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-04_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-05_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-05_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-06_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-06_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-08_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-08_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-09_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-09_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-12_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2024-12_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-01_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-01_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-02_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-02_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-05_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-05_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-07_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-07_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-10_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-10_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-11_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2025-11_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-01_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-01_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-02_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-02_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-03_ILOCOS.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
data/raw/Synthetic Data/INVENTORY_SIGN_OFF_2026-03_PANGASINAN.xlsx,inventory_sign_off,Inventory Sign Off,Cost; Valuation; Valuation with VAT
"data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT (OCTOBER 1-30, 2021).xlsx",ssis_summary,INVENTORY,AT COST
"data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT (OCTOBER 1-30, 2021).xlsx",ssis_summary,B.O  SUMMARY,CATEGORY
"data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT (OCTOBER 1-30, 2021).xlsx",ssis_summary,"SOH(Oct. 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx,ssis_summary,"SOH(APRIL30,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx,ssis_summary,"SOH(MARCH1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx,ssis_summary,"SOH(JANUARY 29,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MARCH.2022.xlsx,ssis_summary,"SOH(MARCH31,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT MAY 2022.xlsx,ssis_summary,"SOH(JUNE1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS DAILY SALES SUMMARY REPORT NOVEMBER 1 - 29 (1).xlsx,ssis_summary,"SOH(DEC 1, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
"data/raw/Unilever/SSIS MONTHLY SALES REPORT (FEB. 01-28, 2021).xlsx",ssis_summary,INVENTORY,AT COST
"data/raw/Unilever/SSIS MONTHLY SALES REPORT (FEB. 01-28, 2021).xlsx",ssis_summary,BO INVENTORY (NOV2020-FEB2021,Item category; Stock Type
"data/raw/Unilever/SSIS MONTHLY SALES REPORT (FEB. 01-28, 2021).xlsx",ssis_summary,"STOCK CARD(FEB. 28,2021",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (APRIL,2021).xlsx",ssis_summary,INVENTORY,AT COST
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (APRIL,2021).xlsx",ssis_summary,"B.O (NOV.2020-APRIL 30,2021)",CATEGORY
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (APRIL,2021).xlsx",ssis_summary,"SOH(APRIL 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (AUGUST 2021).xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (AUGUST 2021).xlsx,ssis_summary,B.O (JAN.2021- AUGUST.2021),CATEGORY
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (AUGUST 2021).xlsx,ssis_summary,"SOH(AUGUST 31, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JAN. 01-31, 2021).xlsx",ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JULY 2021).xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JULY 2021).xlsx,ssis_summary,B.O (JAN.2021- JULY.2021),CATEGORY
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JULY 2021).xlsx,ssis_summary,"SOH(JUNE 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JUNE,2021).xlsx",ssis_summary,INVENTORY,AT COST
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JUNE,2021).xlsx",ssis_summary,B.O (NOV.2020- JUNE.2021),CATEGORY
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (JUNE,2021).xlsx",ssis_summary,"SOH(JUNE 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MARCH 01-31,2021).xlsx",ssis_summary,INVENTORY,AT COST
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MARCH 01-31,2021).xlsx",ssis_summary,BO INVENTORY (NOV2020-MARCH31),Item category; Stock Type
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MARCH 01-31,2021).xlsx",ssis_summary,"STOCK CARD(APRIL 05,,2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MAY,2021).xlsx",ssis_summary,INVENTORY,AT COST
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MAY,2021).xlsx",ssis_summary,B.O (NOV.2020-MAY.2021),CATEGORY
"data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (MAY,2021).xlsx",ssis_summary,"SOH(MAY 31, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (1).xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (1).xlsx,ssis_summary,B.O (JAN.2021- SEPTEMBER.2021),CATEGORY
data/raw/Unilever/SSIS MONTHLY SALES SUMMARY REPORT (SEPTEMBER 2021) (1).xlsx,ssis_summary,"SOH(Sept. 30, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx,ssis_summary,"SOH(MAY 2, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx,ssis_summary,"SOH(MAY 2, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx,ssis_summary,"SOH(MAY 2, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx,ssis_summary,"SOH(SEPTEMBER 1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx,ssis_summary,"SOH(SEPTEMBER 1, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx,ssis_summary,"SOH(SEPTEMBER 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx,ssis_summary,"SOH(SEPTEMBER 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2021. (1).xlsx,ssis_summary,"SOH(DEC 27, 2021)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx,ssis_summary,"SOH(DECEMBER 29,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx,ssis_summary,"SOH(JANUARY 2, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx,ssis_summary,"SOH(JANUARY 2, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx,ssis_summary,"SOH(JANUARY 05, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx,ssis_summary,"SOH(MARCH 01, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx,ssis_summary,"SOH(MARCH 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx,ssis_summary,"SOH(MARCH 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx,ssis_summary,"SOH(FEBRUARY 01, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx,ssis_summary,"SOH(FEBRUARY 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx,ssis_summary,"SOH(FEBRUARY 3, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx,ssis_summary,"SOH(AUGUST 01, 2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx,ssis_summary,"SOH(AUGUST 1, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx,ssis_summary,"SOH(AUGUST 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx,ssis_summary,"SOH(AUGUST 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx,ssis_summary,"SOH(JULY 1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx,ssis_summary,"SOH(JULY 3, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx,ssis_summary,"SOH(JULY 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx,ssis_summary,"SOH(JULY 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx,ssis_summary,"SOH(APRIL 1, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx,ssis_summary,"SOH(APRIL 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx,ssis_summary,"SOH(APRIL 1, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx,ssis_summary,"SOH(JUNE 1, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx,ssis_summary,"SOH(JUNE 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx,ssis_summary,"SOH(JUNE 1, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx,ssis_summary,"SOH(DECEMBER 01,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx,ssis_summary,"SOH(DECEMBER 1, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx,ssis_summary,"SOH(DECEMBER 2, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx,ssis_summary,"SOH(DECEMBER 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx,ssis_summary,"SOH(NOVEMBER 3,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx,ssis_summary,"SOH(NOVEMBER 3, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx,ssis_summary,"SOH(NOVEMBER 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx,ssis_summary,"SOH(NOVEMBER 03, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx,ssis_summary,"SOH(OCTOBER 1,2022)",Stock Quantity (CS/PC); Stock Value; MOVING AVERAGE PRICE(CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx,ssis_summary,"SOH(OCTOBER 2, 2023)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx,ssis_summary,"SOH(OCTOBER 1, 2024)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,INVENTORY,AT COST
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,B.O  SUMMARY,CATEGORY
data/raw/Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx,ssis_summary,"SOH(OCTOBER 01, 2025)",Stock Quantity (CS/PC); Stock Value; Last Purchase Price(GSV/CS); CATEGORY DESC; Blocked Stock(CS/PC)
```

---

## A5. Classification failures

### `infer_doc_type()` produces no match ("unknown")

**178 files.** All 178 are under
`data/raw/Synthetic Data/` and split into two filename families:
**86 `SALES_REGISTER_*`** and **92 `SELL_OUT_*`**. Root cause (verified
against `profiling/profile_files.py::DOC_TYPE_PATTERNS`, quoted verbatim):

- `sales_register` pattern: `r"sale[s]?\s*regist(er)?|daily\s*sales\s*report"`
  — requires `\s*` (whitespace, zero-or-more) between "sale(s)" and
  "regist(er)". The real filenames use an underscore
  (`SALES_REGISTER_2022-08_ILOCOS.xlsx`), which `\s` does NOT match, so
  every one of the 86 files falls through to `unknown`.
- `sell_out` pattern: `r"sell\s*out"` — same problem:
  `SELL_OUT_2021-01_ILOCOS.xlsx` has an underscore between "SELL" and
  "OUT", not whitespace, so all 92 files fall through to `unknown`.

This is the identical bug class the repo's own code comments already
document as fixed elsewhere for `unilever_sku`/`la_union`
(`la[\s_]*union`, explicitly extended to `[\s_]*` after a documented
"UnileverLaUnion..." near-miss) and for the `pangasinan` region pattern
(`pang(?![a-z])`) — but `sales_register` and `sell_out` were never given
the same `[\s_]*` treatment, so they still miss every underscore-separated
filename. (By contrast, `purchase_order`'s pattern — `r"purchase|_po\b|\bpo\b"`
— matches because "purchase" appears as one unbroken substring in
`PURCHASE_ORDER_...xlsx` with no required separator, and `inventory_sign_off`'s
`r"inventory|sign\s*off"` matches on the standalone word "inventory" the
same way — so `PURCHASE_ORDER_*` and `INVENTORY_SIGN_OFF_*` synthetic
files DO classify correctly; only the two patterns above are affected.)

Full list of the 178 unclassified files:

<details>
<summary>178 unknown-doc_type files (click to expand)</summary>

- data/raw/Synthetic Data/SALES_REGISTER_2021-01_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-01_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-02_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-02_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-03_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-03_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-04_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-04_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-05_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-05_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-06_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-06_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-08_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-08_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-09_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-09_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-10_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-10_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-11_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-11_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-12_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2021-12_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-01_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-01_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-02_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-02_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-03_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-03_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-04_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-04_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-05_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-05_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-06_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-06_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-08_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-08_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-09_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-09_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-10_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-10_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-11_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-11_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-12_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2022-12_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2023-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2023-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2023-10_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2023-10_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-03_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-03_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-04_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-04_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-05_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-05_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-06_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-06_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-08_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-08_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-09_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-09_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-10_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-10_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-11_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-11_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-12_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2024-12_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2025-01_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2025-01_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2025-02_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2025-02_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2025-05_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2025-05_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2025-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2025-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2026-01_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2026-01_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2026-02_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2026-02_PANGASINAN.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2026-03_ILOCOS.xlsx
- data/raw/Synthetic Data/SALES_REGISTER_2026-03_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-01_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-01_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-02_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-02_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-03_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-03_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-04_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-04_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-05_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-05_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-06_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-06_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-08_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-08_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-09_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-09_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-10_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-10_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-11_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-11_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-12_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2021-12_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-01_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-01_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-02_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-02_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-03_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-03_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-04_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-04_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-05_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-05_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-06_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-06_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-08_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-08_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-09_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-09_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-10_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-10_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-11_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-11_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-12_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2022-12_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2023-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2023-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2023-10_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2023-10_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2023-12_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2023-12_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-03_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-03_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-04_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-04_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-05_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-05_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-06_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-06_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-08_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-08_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-09_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-09_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-10_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-10_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-11_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-11_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-12_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2024-12_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-01_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-01_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-02_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-02_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-05_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-05_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-07_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-07_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-10_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-10_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-11_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2025-11_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2026-01_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2026-01_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2026-02_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2026-02_PANGASINAN.xlsx
- data/raw/Synthetic Data/SELL_OUT_2026-03_ILOCOS.xlsx
- data/raw/Synthetic Data/SELL_OUT_2026-03_PANGASINAN.xlsx

</details>

### doc_type routed to a doc_type whose expected sheet name never appears (misrouted)

Checked for `rmr_gs_bo` (expects a sheet name containing "gs", "bo", or
"one pager") and `ssis_summary` (expects a sheet name containing
"raw data") — the only two doc_types with a documented, specific expected
sheet-name convention in the extractor docstrings/`source_of_truth.yaml`.

None found by the automated sheet-name-hint check (see caveat below).

Caveat: this is a narrow, code-documented-convention check, not an
exhaustive misrouting audit — doc_types without a stated "must contain
sheet X" convention (sales_register, purchase_order, inventory_sign_off,
sell_out, sales_return) were not checked this way since there is no
single documented expected sheet name to test against; their file-level
routing was instead spot-checked via the doc_type distribution in A1 and
found consistent with each family's extractor docstring (e.g. `rmr_gs_bo`
= exactly 2 real files, matching `bo_rmr_gs.py`'s "October, November 2025"
docstring claim; `sales_return` = 19 files matching `sales_return.py`'s
"19 real files" claim before its 1 known-duplicate exclusion).

### File-open / read errors

None found.

### Related anomaly (not a misroute, but a real classification-adjacent finding)

92 `data/raw/Synthetic Data/INVENTORY_SIGN_OFF_*.xlsx` files classify
correctly as `inventory_sign_off` (see above) and their single sheet is
literally named `"Inventory Sign Off"`, but that sheet's own header row
contains Extract's internal provenance column names as raw source
headers: `__col0__, Quantity, Cost, Valuation, Valuation with VAT, CAS,
PCS, PKG, in Cases, _src_file, _src_sheet, _header_row, _row_ordinal,
_principal, _region` (verbatim, confirmed by direct read). This means the
synthetic-data generator baked pipeline-provenance-shaped column names
into the "raw" file itself, which is a data-generation anomaly worth
flagging to whoever owns `data/raw/Synthetic Data/` generation — these are
`is_demo` synthetic files per CLAUDE.md's sanctioned exception, not real
source data, but the shape is unusual enough to record here.

---

## Summary numbers

| Metric | Value |
|---|---|
| Total files scanned | 568 |
| Real format (magic-byte) | {'xlsx': 567, 'mhtml': 1} |
| doc_type distribution | see JSON block near top |
| A2 total unread-sheet occurrences | 916 |
| A2 distinct (doc_type,sheet,role) unread groups | 148 |
| A3 total unique unmapped (doc_type,sheet,header) rows | 123 |
| A4 sheets with flagged (inventory/cost/price/etc.) headers | 446 |
| A5 unknown-doc_type files | 178 |
| A5 file read errors | 0 |
| SSIS files with an INVENTORY-named sheet | 105 / 105 ssis_summary files |

---

=== PART B — LIVE DATABASE ===

# Part B — Live Database Audit (READ-ONLY)

Method: all facts below come from live SELECT queries against Supabase Postgres
(via `SUPABASE_DB_URL` / psycopg2, session set `readonly=true`). No INSERT/UPDATE/DELETE/DDL
was run. `analytics/db/schema.sql` and `analytics/db/migrations/0001`–`0008` were read first
for reference, then every claim below was independently verified against the live DB.

---

## B1. Table census

`information_schema.tables where table_schema='public'` returns **24 objects**: 16 base tables, 8 views.

### Base tables (16)

| table | rows | split |
|---|---|---|
| abc_classification | 63,745 | principal: delmonte 19,817 / unilever 43,928 (no is_demo column) |
| audit_log | 21 | no is_demo/principal column |
| customer_dimension | 23,712 | principal: delmonte 23,712 (single value — see B3) |
| date_dimension | 2,191 | no is_demo/principal column |
| forecast_result | 136 | no is_demo/principal column; status: ok 89 / insufficient_data 37 / dead_sku 10 |
| inventory_fact | 322,578 | delmonte/false 5,171; delmonte/true 75,269; unilever/true 242,138; **unilever/false = 0 rows (0-row cell)** |
| lp_recommendation | 430 | no is_demo/principal column directly; via product_dimension join: 100% unilever (430/430) |
| product_dimension | 17,245 | delmonte 15,438 / unilever 1,807 |
| purchase_fact | 2,110 | delmonte/false 353; delmonte/true 1,757; **no unilever rows at all (0-row cell)** |
| sales_fact | 53,320 | delmonte/false 17,947; delmonte/true 35,373; **no unilever rows (schema CHECK principal='delmonte' only — by design)** |
| salesman_dimension | 33 | no is_demo/principal column |
| **salesreturn_fact** | **0** | **0-ROW TABLE** (every column reads 0 non-null, 0 distinct) |
| sellout_fact | 8,368 | delmonte/false 1,539; delmonte/true 6,829 (Del Monte only by CHECK constraint, by design) |
| supplier_dimension | 2 | delmonte 1 / unilever 1 |
| unilever_sku_demand_fact | 44,575 | is_demo false 24,906 / true 19,669 (no principal column — Unilever-only table by design) |
| users | 2 | no is_demo/principal column |

### Views (8)

| view | rows |
|---|---|
| bo_monitoring_view | 217 (all principal=delmonte — no unilever rows ever reach it, see B7) |
| inventory_fact_real | 5,171 |
| product_demand_view | 52,943 (unilever 44,575 + delmonte 8,368) |
| purchase_fact_real | 353 |
| sales_fact_real | 17,947 |
| **salesreturn_fact_real** | **0-ROW VIEW** (base table is 0 rows) |
| sellout_fact_real | 1,539 |
| unilever_sku_demand_fact_real | 24,906 |

**Every 0-row object found:** `salesreturn_fact` (base table) and `salesreturn_fact_real` (view). Also flag the **0-row cells** inside otherwise-populated tables: `inventory_fact` has zero `unilever, is_demo=false` rows (no real Unilever inventory data has ever been loaded), and `purchase_fact` has zero `unilever` rows of any is_demo value (schema allows unilever principal there but nothing was ever loaded).

---

## B2. Schema drift, both directions

### (a) Columns live but NOT in schema.sql's CREATE TABLE text

- **`inventory_fact.cost`** (numeric) — live, populated with real data (see B4), but does not appear in schema.sql's `CREATE TABLE Inventory_Fact` block (lines 284-315) nor in any migration file 0001–0008. This is undocumented drift — no tracked migration ever added it.
- **`product_dimension.manual_reorder_point`** (numeric) — live, but not in schema.sql's `CREATE TABLE Product_Dimension` (lines 102-119) nor in migration 0002_add_sku_management_fields.sql (which adds unit_price/lead_time_days/status/notes but not this). Undocumented drift, currently 100% NULL (see B3).

### (b) Columns in schema.sql's CREATE TABLE text but absent live

None found. Every column schema.sql declares for every table was confirmed present live via `information_schema.columns`.

### (c) Tables/views present in one but not the other

None found — all 16 base tables and all 8 views schema.sql declares (6 `_Real` views + `bo_monitoring_view` + `product_demand_view`) exist live, and no live table/view is absent from schema.sql.

### Migration-by-migration applied-vs-committed status (method: check live DB for the specific column/table/data each migration claims to add)

| migration | claims | live verification | verdict |
|---|---|---|---|
| 0001_add_is_demo.sql | adds is_demo to 6 fact tables + 6 `_Real` views + Inventory_Fact._period/quantity_pieces + Supplier_Dimension seed | is_demo column confirmed present on all 6 fact tables; all 6 `_Real` views exist; inventory_fact has _period and quantity_pieces; supplier_dimension has exactly 2 rows (delmonte, unilever) | **APPLIED** (matches file's own "APPLIED" note) |
| 0002_add_boundary_flag.sql | adds ABC_Classification.boundary_flag | column confirmed present (`cols_abc_classification` includes boundary_flag) | **APPLIED** |
| 0002_add_sku_management_fields.sql | adds unit_price, lead_time_days, status, notes to Product_Dimension | all 4 columns confirmed present live | **APPLIED** — contradicts the file's own header comment "NOT YET APPLIED to Supabase — run this by hand"; the comment is stale, the migration is in fact live |
| 0003_add_audit_log.sql | creates Audit_Log table | table exists live, 21 rows | **APPLIED** — also contradicts its own "NOT YET APPLIED" header comment |
| 0004_add_valuation.sql | adds Inventory_Fact.valuation, recreates Inventory_Fact_Real | valuation column confirmed present and populated; view confirmed selects it | **APPLIED** |
| 0005_fix_real_views.sql | restores all 6 `_Real` views to strict `is_demo = false` (no OR clauses) | live `pg_get_viewdef()` for all 6 views confirmed strict `WHERE is_demo = false`, no OR-clause leak present | **APPLIED** (matches file's own "ALREADY APPLIED" note) |
| 0006_revert_sellout_category_attribution.sql | reverts SellOut_Fact.product_key random SKU reassignment back to category grain | queried sellout_fact/product_dimension join: 0 orphans, and product_dimension confirms 15,029 of 15,438 delmonte rows have NULL category_path (i.e. grain='sku'-shaped rows exist separately from the 8,368 sellout rows) — consistent with the revert having run; row count of sellout_fact is exactly 8,368 as the migration's comment states | **APPLIED** (matches file's own "ALREADY APPLIED" note) |
| 0007_null_phantom_category_sku_codes.sql | nulls sku_code on 99 phantom category rows; reverts product_key 50133's unit_price/status edit | live: `product_dimension` delmonte rows with grain='category' and non-null sku_code = 0 (confirmed via B6 product_dimension_nulls query showing null_sku_code=99 out of 15,438 delmonte rows, i.e. exactly 99 rows are still NULL-sku_code category rows as expected post-fix, 0 remaining phantom codes) | **APPLIED** (matches file's own "ALREADY APPLIED" note) |
| 0008_add_forecast_result_status.sql | adds Forecast_Result.status | column confirmed present live, populated (89 ok / 37 insufficient_data / 10 dead_sku, 0 NULL) | **APPLIED** — also contradicts its own "NOT YET APPLIED" header comment |

**Note:** three migration files (0002_add_sku_management_fields.sql, 0003_add_audit_log.sql, 0008_add_forecast_result_status.sql) carry header comments claiming "NOT YET APPLIED" that are now stale/incorrect — all three are in fact live. This is a documentation-vs-reality drift inside the migrations directory itself, not a schema drift.

No migrations beyond 0008 exist in `analytics/db/migrations/`.

---

## B3. Dead columns (100% NULL or exactly 1 distinct non-null value)

Computed via one batched `SELECT count(col), count(DISTINCT col) ...` per table (not per-column queries).

**100% NULL columns:**
- `date_dimension.fiscal_period` — 0/2,191 non-null
- `forecast_result.confidence_lower` — 0/136 non-null
- `forecast_result.confidence_upper` — 0/136 non-null
- `product_dimension.unit_price` — 0/17,245 non-null
- `product_dimension.lead_time_days` — 0/17,245 non-null
- `product_dimension.manual_reorder_point` — 0/17,245 non-null (also the undocumented-drift column from B2a)
- `purchase_fact.units_received` — 0/2,110 non-null
- `salesreturn_fact.*` — every column is 0/0 (table itself is empty, see B1)

**Exactly 1 distinct non-null value (no informational variance):**
- `customer_dimension.principal` — 23,712/23,712 all = 'delmonte'
- `lp_recommendation.decided_at` — 1/430 non-null, that 1 value is the sole distinct value (429 rows still 'pending')
- `lp_recommendation.decided_by` — same, 1/430 non-null (1 accepted row, decided_by='mikhaellaaudrey@gmail.com')
- `product_dimension.status` — 17,245/17,245 all = 'ACTIVE' (DISABLED never used live)
- `product_dimension.notes` — 1/17,245 non-null, single distinct value
- `purchase_fact.principal` — 2,110/2,110 all = 'delmonte' (no unilever purchase rows ever loaded)
- `purchase_fact.supplier_key` — 2,110/2,110 all the same key (single Del Monte supplier)
- `sales_fact.principal` — 53,320/53,320 all = 'delmonte' (schema CHECK enforces this — by design)
- `sales_fact._outlier_flag` — 53,320/53,320 all the same boolean value (no row ever flagged an outlier)
- `sellout_fact.principal` — 8,368/8,368 all = 'delmonte' (schema CHECK enforces this — by design)
- `unilever_sku_demand_fact.region` — 44,575/44,575 all = 'la_union' (matches CLAUDE.md: only confirmed Unilever SKU-level source is La Union)
- `unilever_sku_demand_fact._src_sheet` — 44,575/44,575 all the same sheet name

All other tables/columns not listed above showed non-zero non-null AND >1 distinct value.

---

## B4. Valuation — Inventory_Fact.valuation / .cost

Split by (principal, is_demo):

| principal | is_demo | valuation nonnull | valuation distinct | cost nonnull | cost distinct | rows |
|---|---|---|---|---|---|---|
| delmonte | **false (REAL)** | 5,171 | 4,911 | 5,171 | 4,889 | 5,171 |
| delmonte | true | 45,569 | 29,905 | 15,313 | 14,795 | 75,269 |
| unilever | true | 3,614 | 1,807 | 0 | 0 | 242,138 |

**Data-quality flag found while computing this**: 210 of the real (is_demo=false) rows store the literal Postgres numeric value `'NaN'` in both `valuation` and `cost` (same 210 rows for both columns) — not NULL, an actual stored NaN. This silently poisons any `AVG()`/`MAX()` computed directly over the column (confirmed: `MAX(valuation)` for that slice returns `NaN` until NaN rows are excluded). Excluding those 210 NaN rows, the real (is_demo=false) delmonte range is: valuation min -29,451.23 / max 1,759,818.77 / mean 8,235.42; cost min -14,678.24 / max 2,156,208.39 / mean 5,719.99.

**Explicit answer to the question posed**: **YES** — there are 5,171 rows with `is_demo=false` where both `valuation` and `cost` are non-null (Del Monte only; zero real Unilever inventory rows exist at all, see B1). So SOH Value CAN today be computed from real data, but only for Del Monte, and only after excluding/handling the 210 NaN-valued rows, which is not currently done anywhere confirmed.

---

## B5. LP integrity — LP_Recommendation (430 rows) vs Forecast_Result (136 rows)

Join key verified live: both tables carry `product_key BIGINT NOT NULL REFERENCES Product_Dimension(product_key)` — this is the only viable join path (no other shared key exists).

Join `lp_recommendation.product_key = forecast_result.product_key`:

| forecast_result.status matched | LP rows |
|---|---|
| ok | 89 |
| insufficient_data | 37 |
| dead_sku | 10 |
| **no matching Forecast_Result row at all (NULL)** | **294** |

294 of 430 LP_Recommendation rows (68%) join to **zero** Forecast_Result rows for their product_key — not even a non-'ok' one. Re-running the join keyed on "best available status per product_key" (in case of duplicate forecast rows per product across dates) returns the identical breakdown — confirming this isn't a forecast_date multiplicity artifact.

For the 294 unmatched rows: sampled 20 directly (see raw data in `out5.json`). They carry real-looking `q_i`/`rop_i`/`ss_i` numeric values (e.g. product_key 39: q_i=236,513.07, rop_i=236,513.07, ss_i=1,004.84) with **no Forecast_Result row of any status ever existing for that product_key** — meaning these demand-input-derived numbers cannot trace back to any live Forecast_Result row. Where they came from is **NOT DETERMINABLE** from the live DB alone (LP_Recommendation carries no source/provenance column). Notably many rows show **q_i == rop_i** exactly (e.g. product_key 1, 4, 5, 6, 8, 18, 29...), and `ss_i = 1.28` appears repeatedly as a floor value across unrelated products — patterns consistent with a fallback/default computation path rather than a real per-SKU LP solve, but this cannot be confirmed from DB data alone (would require reading the LP script, out of scope for this read-only DB audit).

**generated_at timestamps — explicit before/after answer:**
- `lp_recommendation.generated_at`: min 2026-08-23 08:43:53 UTC, max 2026-08-24 07:12:56 UTC
- `forecast_result.generated_at`: min 2026-08-25 13:13:48 UTC, max 2026-08-25 14:55:16 UTC

**LP_Recommendation was generated entirely BEFORE any row in the current Forecast_Result table existed** — the latest LP row (2026-08-24 07:12) predates the earliest Forecast_Result row (2026-08-25 13:13) by more than a day. This means **none** of the 430 LP rows — including the 136 that happen to join to a product_key that now has a Forecast_Result row — could have been computed from the Forecast_Result data currently live in the DB. The 89/37/10 "matches" in the table above are coincidental product_key overlaps, not a demonstrated causal/temporal dependency.

`lp_recommendation.status`: pending 429, accepted 1 (decided_by mikhaellaaudrey@gmail.com). `lp_recommendation` joined to product_dimension: 100% principal=unilever (430/430) — no Del Monte LP rows exist at all, consistent with DEC-03 (LP/forecast only runs where per-SKU demand exists).

---

## B6. Referential integrity

FK constraints declared live (`information_schema.table_constraints` / `key_column_usage` / `constraint_column_usage`):

- abc_classification.product_key → product_dimension.product_key
- forecast_result.product_key → product_dimension.product_key
- inventory_fact.snapshot_date → date_dimension.date_key
- inventory_fact.product_key → product_dimension.product_key
- lp_recommendation.product_key → product_dimension.product_key
- purchase_fact.invoice_date → date_dimension.date_key
- purchase_fact.supplier_key → supplier_dimension.supplier_key
- sales_fact.invoice_date → date_dimension.date_key
- sales_fact.salesman_key → salesman_dimension.salesman_key
- sales_fact.customer_key → customer_dimension.customer_key
- salesreturn_fact.return_date → date_dimension.date_key
- sellout_fact.product_key → product_dimension.product_key
- unilever_sku_demand_fact.product_key → product_dimension.product_key

All of these are enforced by real Postgres FK constraints (not just informal). Anti-join orphan checks against every one of the above (including inventory_fact/sellout_fact/unilever_sku_demand_fact/abc_classification/forecast_result/lp_recommendation product_key; sales_fact customer_key/salesman_key/invoice_date; purchase_fact supplier_key/invoice_date; inventory_fact snapshot_date) all returned **0 orphaned rows** — referential integrity is 100% intact live. (This is expected given Postgres enforces the declared FKs, but was verified via SELECT anti-joins as instructed, not assumed from the constraint list alone.)

**Product_Dimension nulls, by principal:**

| principal | total | NULL sku_code | NULL category_path |
|---|---|---|---|
| delmonte | 15,438 | 99 | 15,029 |
| unilever | 1,807 | 0 | 1,807 |

(Consistent with DEC-03: Unilever rows are always grain='sku' → category_path always NULL, sku_code always populated; Del Monte rows are mostly grain='category' → sku_code NULL only for true category rows — 99 is the exact count 0007 migration nulled and left nulled, zero re-drift.)

---

## B7. Views — live definitions via `pg_get_viewdef()`

All 6 `_Real` family views, confirmed live (not from schema.sql):

- `Sales_Fact_Real`: `SELECT ... FROM sales_fact WHERE is_demo = false` — strict, no OR-leak.
- `Purchase_Fact_Real`: `SELECT ... FROM purchase_fact WHERE is_demo = false` — strict.
- `Inventory_Fact_Real`: `SELECT ... FROM inventory_fact WHERE is_demo = false` — strict (includes valuation, cost, quantity_pieces columns).
- `SellOut_Fact_Real`: `SELECT ... FROM sellout_fact WHERE is_demo = false` — strict.
- `Unilever_SKU_Demand_Fact_Real`: `SELECT ... FROM unilever_sku_demand_fact WHERE is_demo = false` — strict.
- `SalesReturn_Fact_Real`: `SELECT ... FROM salesreturn_fact WHERE is_demo = false` — strict (base table is 0 rows, so view is 0 rows).

**Confirmed: every `_Real` view reads its expected single base table and the `is_demo = false` predicate is genuinely present in the live WHERE clause for all six** — no drift, no OR-leak (matches migration 0005's fix).

Row counts, view vs base:

| view | view rows | base table rows |
|---|---|---|
| sales_fact_real | 17,947 | 53,320 |
| purchase_fact_real | 353 | 2,110 |
| inventory_fact_real | 5,171 | 322,578 |
| sellout_fact_real | 1,539 | 8,368 |
| unilever_sku_demand_fact_real | 24,906 | 44,575 |
| salesreturn_fact_real | 0 | 0 |

Other views found:
- `bo_monitoring_view`: live definition matches schema.sql's Section 5 exactly (aggregate-then-join CTEs, no fan-out); reads purchase_fact + salesreturn_fact directly (NOT is_demo-filtered — reads the raw base tables, including demo rows). 217 rows, all principal=delmonte (matches purchase_fact's delmonte-only real+demo population; salesreturn_fact is 0 rows so bo_net_amount is NULL for every row via the LEFT JOIN).
- `product_demand_view`: live definition matches schema.sql's Section 7 exactly (UNION ALL of unilever_sku_demand_fact JOIN product_dimension, and sellout_fact LEFT JOIN product_dimension). Also **not** is_demo-filtered — reads raw base tables including demo rows. 52,943 rows = 44,575 (unilever) + 8,368 (delmonte), i.e. exactly the full base-table union, confirming no demo filter is applied here.

**Flag**: `bo_monitoring_view` and `product_demand_view` are NOT part of the `_Real` family and do NOT filter is_demo — any caller of these two views that needs demo-excluded data must filter is_demo itself; neither view does it for you (documented behavior per schema.sql's own comments, confirmed live).

---

## B8. Temporal coverage

Real-only (is_demo=false) data, gap lists computed by enumerating every calendar month in [min,max] and checking absence — not just "gaps exist":

**sales_fact (delmonte, real)** — range 2023-01 to 2025-12 (36 months), 20 present, **16 missing**:
`2023-07, 2023-10, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-05, 2025-07`

**purchase_fact (delmonte, real)** — range 2023-09 to 2025-12 (28 months), 10 present, **18 missing**:
`2023-10, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-05, 2025-07, 2025-09, 2025-10, 2025-11`

**inventory_fact (delmonte, real)** — range 2023-01 to 2025-12 (36 months), 17 present, **19 missing**:
`2023-07, 2023-10, 2023-11, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-05, 2025-07, 2025-10, 2025-11`

**sellout_fact (delmonte, real)** — range 2023-01 to 2025-12 (36 months), 17 present, **19 missing**:
`2023-07, 2023-10, 2023-12, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-05, 2025-07, 2025-10, 2025-11`

**unilever_sku_demand_fact (real, region always la_union)** — range 2023-01 to 2026-02 (38 months), **38 present, 0 missing** — fully continuous, matches CLAUDE.md's stated "Unilever per-SKU data: Jan 2023–Feb 2026" claim exactly.

**salesreturn_fact (real)**: NOT DETERMINABLE — table has 0 rows, no date range exists.

**forecast_result** (no is_demo/principal column; all product_keys resolve to unilever per B5) — forecast_date range 2023-06 to 2026-03 (34 months), 22 present, **12 missing**:
`2023-07, 2023-08, 2023-09, 2023-10, 2023-11, 2024-03, 2024-04, 2024-05, 2024-12, 2025-03, 2025-04, 2025-05`

**lp_recommendation** — planning_cycle_date range 2023-05 to 2026-03 (35 months), 34 present, **1 missing**: `2024-04`

---

## Cross-cutting notes for the caller

- Del Monte's real Sales/Purchase/Inventory/SellOut facts all cluster around the same ragged set of ~17-20 present months out of 28-36 possible — this is one underlying source-file coverage gap reflected consistently across four independently-loaded tables, not four separate problems.
- `inventory_fact.cost` and `product_dimension.manual_reorder_point` are live columns nobody's migration file accounts for (see B2a) — worth a decision on whether to backfill a migration file documenting them.
- Three migration files' own header comments ("NOT YET APPLIED") are stale relative to the live DB (see B2 table) — a documentation hazard for anyone trusting the migrations directory over live inspection.

---

## PART C — CROSS-CHECK (raw corpus vs. live DB)

Method: doc_type → fact-table mapping taken from `config/source_of_truth.yaml`
(read directly, quoted verbatim below), file counts from Part A, row counts
from Part B. Real (non-synthetic) file counts were separated from synthetic
ones by filesystem location (`data/raw/Synthetic Data/` vs. everywhere else)
via a direct `find` count — not inferred from Part A's doc_type distribution,
which mixes real and synthetic files under one classification.

Verified split: 568 total files = 374 synthetic (`data/raw/Synthetic Data/`:
92 `INVENTORY_SIGN_OFF_*`, 104 `PURCHASE_ORDER_*`, 86 `SALES_REGISTER_*`, 92
`SELL_OUT_*`) + 194 real (88 under `data/raw/Del Monte/`, 45 under
`data/raw/SSIS/`, 61 under `data/raw/Unilever/`).

Real-file doc_type counts (total A1 classification count minus the synthetic
files known to land in that bucket — synthetic `INVENTORY_SIGN_OFF_*` and
`PURCHASE_ORDER_*` classify correctly per Part A's A5; synthetic
`SALES_REGISTER_*`/`SELL_OUT_*` both misclassify to `unknown`, per A5):

| doc_type | real files | synthetic files (same bucket) | total (A1) |
|---|---|---|---|
| sales_register | 22 | 0 (synthetic ones land in `unknown`) | 22 |
| rmr_gs_bo | 2 | 0 | 2 |
| inventory_sign_off | 17 | 92 | 109 |
| sales_return | 19 | 0 | 19 |
| sell_out | 17 | 0 (synthetic ones land in `unknown`) | 17 |
| purchase_order | 11 | 104 | 115 |
| ssis_summary | 105 | 0 | 105 |
| unilever_sku | 1 | 0 | 1 |
| unknown | 0 | 178 (86 SALES_REGISTER + 92 SELL_OUT) | 178 |
| **total** | **194** | **374** | **568** |

### C1. doc_type → fact table reconciliation

`config/source_of_truth.yaml` (read directly) is the authoritative doc_type→fact
mapping — quoted verbatim per entry below.

| doc_type (real files) | source_of_truth.yaml mapping | real (is_demo=false) DB rows | Verdict |
|---|---|---|---|
| `sales_register` (22, delmonte) | `sales.delmonte: doc_type=sales_register, system_of_record_role=data, natural_key=[invoice_num, principal, region]` (source_of_truth.yaml:57-75) | `sales_fact` delmonte real = **17,947** | Reconciles — ~816 rows/file, plausible for daily invoice-level register data. |
| `ssis_summary` (105, unilever) | `sales.unilever: doc_type=ssis_summary, system_of_record_role=raw_data, natural_key=null` — comment states "**stages ~805 real sheets every run**" but is explicitly `# BLOCKED, do not "fix" this without new evidence` because RAW DATA has no invoice/reference column, so `natural_key` is `null` and `transform_fact() raises loudly if this is used` (source_of_truth.yaml:32-56) | **0** — no live Sales_Fact row is attributable to Unilever (`sales_fact` schema CHECK restricts it to `principal='delmonte'` only, confirmed in Part B's B1/B3) | **FLAG — raw rows exist and are staged every run (per the file's own comment), but zero ever reach any live fact table.** This is a Transform-stage block (unconfirmed natural key), not a missing-source problem — the 105 real files' RAW DATA sheets are read but structurally cannot be loaded under current config. |
| `unilever_sku` (1, La Union MHTML) | `sales_unilever_sku_demand.unilever: doc_type=unilever_sku, system_of_record_role=data, natural_key=[sku_code, calendar_month]` — "Sole source for this fact ... no other sheet/doc_type competes" (source_of_truth.yaml:77-86) | `unilever_sku_demand_fact` real = **24,906**, `region` column is 100%-single-value `'la_union'` (confirmed Part B, B3) | Reconciles — matches "sole source" claim exactly; every real row traces to this one file. |
| `rmr_gs_bo` (2, both principals, GS+BO sheets) | `sales_return.both: doc_type=rmr_gs_bo, system_of_record_role=[gs,bo], natural_key=[return_slip_num, principal, region, return_type]` — comment states this key was "Confirmed against real rmr_gs_bo data" and references **"0/538 real rows"** having invoice_num, implying **538 real rows were staged** in a past run (source_of_truth.yaml:88-110) | `salesreturn_fact` = **0 rows total** (not just real=0 — the entire table is empty, per Part B B1) | **FLAG — config says this doc_type is wired and was staging real rows (538, per its own comment), but the live table has never received a single row, real or demo.** This is a Load-stage failure, not a config or Extract/Transform gap. |
| `sales_return` (19, delmonte, filename contains "SALE RETURN") | **Not referenced anywhere in `source_of_truth.yaml`** — the file's own header note (line 88 onward) shows `sales_return` fact's system of record is the *different* doc_type `rmr_gs_bo`, not the `sales_return`-classified files | N/A — these 19 files are not wired to any fact table under current config | These 19 real files appear to be orphaned relative to the current pipeline design: a differently-named doc_type (`sales_return`, from filenames literally containing "SALE RETURN") exists and is classified, has its own YAML (`config/column_maps/sales_return.yaml`, confirmed in Part A), but `source_of_truth.yaml` never designates it as any fact's system of record — `rmr_gs_bo` (2 files) is the designated source instead. Whether these 19 files' data (Del Monte sales returns) duplicates, supersedes, or is unrelated to `rmr_gs_bo`'s GS/BO sheets is **NOT DETERMINABLE** from this read-only audit. |
| `purchase_order` (11, delmonte only) | `purchase.both: doc_type=purchase_order, system_of_record_role=data, natural_key=[invoice_num, principal, region]` (source_of_truth.yaml:129-140) | `purchase_fact` delmonte real = **353**; unilever real = **0** | Delmonte reconciles (~32 rows/file). Unilever: 0 real raw `purchase_order` files exist for Unilever (confirmed — all 11 real files are under `data/raw/Del Monte/`) and 0 real DB rows — consistent absence, not a pipeline gap. |
| `inventory_sign_off` (17, delmonte only) | `inventory.both: doc_type=inventory_sign_off, system_of_record_role=data, natural_key=[sku_code, snapshot_date, region]` (source_of_truth.yaml:142-172) | `inventory_fact` delmonte real = **5,171**; unilever real = **0** | Delmonte reconciles (~304 rows/file). Unilever: 0 real raw `inventory_sign_off` files exist for Unilever — but see C2 below, a *different* real Unilever inventory source (the SSIS `INVENTORY` sheet) does exist and is simply never wired into this or any doc_type's config. |
| `sell_out` (17, delmonte) | `sell_out.both: doc_type=sell_out, natural_key=[category_path, region, _period]` (source_of_truth.yaml:176-191) | `sellout_fact` delmonte real = **1,539** | Reconciles (~90 rows/file), with the pre-existing caveat (CLAUDE.md, not re-litigated here) about the Del Monte category taxonomy break. |

### C2. Tables whose real source data exists in `data/raw/` but is unextracted — the actionable list

1. **`inventory_fact`, Unilever slice** — 242,138 `is_demo=true` rows, **0**
   `is_demo=false` rows (Part B, B1). A real, unextracted Unilever inventory
   source *does* exist: the `INVENTORY` sheet, confirmed present in **105 of
   105** real `ssis_summary` files (Part A, A2 CRITICAL finding) — headers
   not yet inspected for exact valuation columns by this audit's A2 pass
   (A2 only established sheet-level unread status; column-level headers for
   *unread* sheets were out of A3's scope, which covers only sheets the
   pipeline already reads). This sheet has **zero** YAML column map and is
   **absent from `source_of_truth.yaml`** entirely — not blocked like
   `ssis_summary`'s RAW DATA (which at least has a `null`-natural_key
   placeholder), simply never referenced. **This is the single largest,
   cleanest actionable gap found across both parts of this audit**: a
   100%-synthetic fact-table slice with a confirmed, monthly, multi-year
   real source sitting unused in the same 105 files already being read for
   other sheets.

2. **`salesreturn_fact`, both principals** — 0 rows total, not
   "100%-synthetic" in the strict sense (there is no demo data for this
   table either — see Part B, B1). Real source data for this table's
   designated doc_type (`rmr_gs_bo`, 2 files) has, per that config file's
   own comment, already been staged as 538 real rows in a past run, yet
   never reached the live table (see C1 above). Distinct failure mode from
   #1: the source is wired and was extracted at least once — this is a
   Load-stage gap, not an unwired-source gap. Flagged here because it's
   the same underlying symptom (real data available, live table empty).

No other table was found to be 100% `is_demo=true` with a confirmed,
unextracted real raw source — `purchase_fact`'s Unilever slice is 0 rows
of any kind, but no raw `purchase_order` (or equivalent) files exist for
Unilever anywhere in `data/raw/`, so there is no unextracted source to
name for it.

---

### Cross-cutting synthesis (A + B combined)

- The context's framing — "assume more is being silently dropped, in the
  files and in the DB alike" — is confirmed on both sides independently:
  Part A found 916 unread-sheet occurrences and 123 unmapped columns in the
  raw corpus; Part B independently found (without reference to Part A) that
  `salesreturn_fact` is entirely empty and that 68% of `LP_Recommendation`
  rows trace to no forecast at all. These are separate failure classes
  (extraction-time drop vs. load-time drop vs. downstream integrity), not
  one bug.
- The originally-reported "INVENTORY sheet in all 59 SSIS files" claim
  (from the task's own context) does not match this audit's file count —
  Part A found 105 real `ssis_summary`-classified files, all 105 carrying
  the sheet. Flagged as a discrepancy in Part A already; restated here
  because it's load-bearing for C2 finding #1's file count.
