# Anomalies

Every entry cites `file :: sheet :: row/col` (or column name) evidence observed directly in profiling/sheet_profiles/*.json or profiling/file_inventory.csv. Nothing here is inferred beyond the cited cells.

## Header offset varies by file/sheet

Header row index is not fixed at row 0 across the corpus. Distribution:

- row index 0: 131 sheets, e.g. data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx :: ILOCOS BO; data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx :: ILOCOS GS ; data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx :: ILOCOS ONE PAGER
- row index 1: 418 sheets, e.g. data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY PURCHASES.xlsx :: ILOCOS PURCHASE; data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY PURCHASES.xlsx :: PANGASINAN PURCHASE; data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES REGISTER.xlsx :: ILOCOS SALES REGISTER
- row index 2: 170 sheets, e.g. data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SELL OUT.xlsx :: ILOCOS_SELL OUT; data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SELL OUT.xlsx :: PANG_SELL OUT; data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2024/2024 JANUARY INVENTORY SIGN OFF.xlsx :: ILOCOS  SIGN OFF INVENTORY
- row index 3: 1 sheets, e.g. data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY INVENTORY SIGN OFF.xlsx :: ILOCOS  SIGN OFF INVENTORY
- row index 4: 26 sheets, e.g. data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY INVENTORY SIGN OFF.xlsx :: PANGASINAN SIGN OFF INVENTORY; data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 04.2025/2025 APRIL INVENTORY.xlsx :: ILOCOS  SIGN OFF INVENTORY; data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 04.2025/2025 APRIL INVENTORY.xlsx :: PANGASINAN SIGN OFF INVENTORY
- row index 5: 61 sheets, e.g. data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 08.2025/2025 AUGUST INVENTORY.xlsx :: PANGASINAN SIGN OFF INVENTORY; data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 06.2025/2025 JUNE INVENTORY.xlsx :: ILOCOS  SIGN OFF INVENTORY; data/raw/SANSAN MARKETING_Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx :: INVENTORY
- row index 6: 1 sheets, e.g. data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 08.2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx :: ILO 090223
- row index 7: 1 sheets, e.g. data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 08.2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx :: ACTUAL 090423
- row index 8: 57 sheets, e.g. data/raw/SANSAN MARKETING_Unilever/SSIS DAILY SALES SUMMARY REPORT APRIL 2022.xlsx :: INVOICE REG(APRIL1-30,2022); data/raw/SANSAN MARKETING_Unilever/SSIS DAILY SALES SUMMARY REPORT FEBRUARY.2022.xlsx :: INVOICE REG(FEBRUARY 1-28,2022); data/raw/SANSAN MARKETING_Unilever/SSIS DAILY SALES SUMMARY REPORT JANUARY 1-28.2022.xlsx :: INVOICE REG(JANUARY 1-28,2022)
- row index 11: 1 sheets, e.g. data/raw/SANSAN MARKETING_Unilever/Unilever-La-Union-Sales-per-SKU-2023-to-2026.xls :: sheet1

**Proposed handling rule:** never assume header row 0; use the header-detection heuristic in `profiling/detect.py::detect_header` (label-density scoring over the first 15 rows) for every sheet in the parser pass.

## Phantom sheet dimensions (openpyxl over-reports max_column/max_row)

Confirmed directly: `SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 10.2025/2025 OCTOBER RMR GS & BO.xlsx :: PANG GS` reports `max_column=16384` against ~11 real data columns; row 0 contains a copy-pasted title string (`RMR GOODSTOCK & BADSTOCK OF APRIL 2025`) repeated at column offsets out to column index 16376 — stale copy-paste debris, not real data. Several "DAILY SALES REPORT" files (Del Monte) carry a `SCHEDULE` sheet whose declared `max_row` is 1,048,448+ (the Excel row ceiling) against ~10-20 real rows.

**Proposed handling rule:** never trust `ws.max_row`/`ws.max_column`. Probe a bounded window (first 200 rows / first 500 columns) for the true non-empty extent, and stream rows with an early-stop once a long run (500+) of fully-blank rows follows real data. Implemented in `profiling/reader.py::_find_real_extent` and `_stream_bounded_rows`.

## `Discount Rate` is a text label, not numeric

Observed distinct raw values across sheets (sample): `LESS 2%, LESS 3%, LESS 4%, LESS 4% LESS 1%, Less 2%, Public Pricelist`

Example locations:
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY PURCHASES.xlsx` :: `ILOCOS PURCHASE` :: column `Discount Rate` — samples: ['Public Pricelist']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY PURCHASES.xlsx` :: `PANGASINAN PURCHASE` :: column `Discount Rate` — samples: ['Public Pricelist']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES REGISTER.xlsx` :: `ILOCOS SALES REGISTER` :: column `Discount Rate` — samples: ['LESS 4%', 'LESS 3%', 'LESS 2%', 'Public Pricelist']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES REGISTER.xlsx` :: `PANGASINAN SALES REGISTER` :: column `Discount Rate` — samples: ['Less 2%', 'LESS 4%', 'LESS 3%', 'Public Pricelist']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES RETURN.xlsx` :: `ILOCOS SALES RETURN` :: column `Discount Rate` — samples: ['LESS 4%', 'Public Pricelist', 'LESS 2%']

**Proposed handling rule:** `config/alias_tables/discount_label.csv` normalizes casing/spacing variants (`Public Pricelist`, `LESS 2%`, `Less 2%`, `LESS 4% LESS 2%`, ...) to canonical labels for human review before any numeric discount-rate derivation.

## Codes carry leading zeros / mixed alphanumeric forms

- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY PURCHASES.xlsx` :: `ILOCOS PURCHASE` :: column `Branch Code` — samples: ['000013']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY PURCHASES.xlsx` :: `ILOCOS PURCHASE` :: column `REFNBR` — samples: ['PO00840', 'PO00836', 'PO00834', 'PO00845', 'PO00842']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY PURCHASES.xlsx` :: `PANGASINAN PURCHASE` :: column `Branch Code` — samples: ['000096', '96']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY PURCHASES.xlsx` :: `PANGASINAN PURCHASE` :: column `REFNBR` — samples: ['PO01742', 'PO01745', 'PO01733', 'PO01755', 'PO01748']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES REGISTER.xlsx` :: `ILOCOS SALES REGISTER` :: column `Branch Code` — samples: ['L12E-001009', 'L12E-001052', 'L12E-000936', 'L12E-000787', 'L12E-000657']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES REGISTER.xlsx` :: `ILOCOS SALES REGISTER` :: column `REFNBR` — samples: ['DMIS0060809', 'DMIS0060807', 'DMIS0060637', 'FG0060807', 'DMIS0060754']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES REGISTER.xlsx` :: `PANGASINAN SALES REGISTER` :: column `Branch Code` — samples: ['L12F-001818', 'L12F-002582', 'L12F-002583', 'L12C-9000881', 'L12C-9000235']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES REGISTER.xlsx` :: `PANGASINAN SALES REGISTER` :: column `REFNBR` — samples: ['DMP014188-2', 'O1541438', 'DMP014237-2', 'DMP014357', 'DMP014468']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES RETURN.xlsx` :: `ILOCOS SALES RETURN` :: column `Branch Code` — samples: ['L12E-000899', 'L12E-000734', 'L12E-0000457', 'L12E-000624', 'L12E-000868']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES RETURN.xlsx` :: `ILOCOS SALES RETURN` :: column `REFNBR` — samples: ['DMIS0060708', 'DMIS0060728', 'ODM002733-2', 'ODM002739', 'DMIS0060759']

**Proposed handling rule:** load these columns as `TEXT` end-to-end (never `INTEGER`/`NUMERIC`) to preserve leading zeros; enforced at the Supabase DDL layer per CLAUDE.md Part 2.

## Duplicate / near-duplicate files

- dedup key `pangasinan&ilocos april 1-april 30 2023 sale return`:
  - `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 04.2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN (1).xlsx`
  - `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 04.2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN.xlsx`
- dedup key `ssis sales summary report april`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT APRIL 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT APRIL 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT APRIL 2025.xlsx`
- dedup key `ssis sales summary report august`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT AUGUST 2022.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT AUGUST 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT AUGUST 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT AUGUST 2025.xlsx`
- dedup key `ssis sales summary report december`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2022.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT DECEMBER 2025.xlsx`
- dedup key `ssis sales summary report february`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT FEBRUARY 2025.xlsx`
- dedup key `ssis sales summary report january`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JANUARY 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JANUARY 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JANUARY 2025 (2).xlsx`
- dedup key `ssis sales summary report july`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JULY 2022.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JULY 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JULY 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JULY 2025.xlsx`
- dedup key `ssis sales summary report june`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JUNE 2022.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JUNE 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JUNE 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT JUNE 2025.xlsx`
- dedup key `ssis sales summary report march`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT MARCH 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT MARCH 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT MARCH 2025.xlsx`
- dedup key `ssis sales summary report may`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT MAY 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT MAY 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT MAY 2025.xlsx`
- dedup key `ssis sales summary report november`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2022.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT NOVEMBER 2025.xlsx`
- dedup key `ssis sales summary report october`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2022.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2024 (2).xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT OCTOBER 2025.xlsx`
- dedup key `ssis sales summary report september`:
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2022.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2023.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2024.xlsx`
  - `data/raw/SANSAN MARKETING_Unilever/SSIS SALES SUMMARY REPORT SEPTEMBER 2025.xlsx`

**Proposed handling rule:** file-level dedup grouping required before load; `config/column_maps` + loaders must accept a canonical file per dedup group, chosen by latest modification or explicit human pick — never both silently.

## Magnolia and ambiguous-principal files (human decision required)

Magnolia-flagged files: 0

Ambiguous-principal files: 0

## Excel lock files (not data — exclude from loaders)

- `data/raw/SANSAN MARKETING_Unilever/~$SSIS SALES SUMMARY REPORT MAY 2025.xlsx` — Excel `~$` lock/temp file, contains only the editing user's name, never a data source

## Files that failed to read cleanly

- `data/raw/SANSAN MARKETING_Del Monte (From Email)/PRICE LIST - 2023/Letter for LGU 2023.pdf` (real_format=pdf) — PDF is not a tabular source; not profiled
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/PRICE LIST - 2023/OCTOBER PRICELIST.pdf` (real_format=pdf) — PDF is not a tabular source; not profiled
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/PRICE LIST - 2023/OCTOBER_REGULAR PROMO_PRICELIST.pdf` (real_format=pdf) — PDF is not a tabular source; not profiled

## Duplicate column labels within a single header row

- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx` :: `ILOCOS BO` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx` :: `ILOCOS GS ` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx` :: `ILOCOS ONE PAGER` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx` :: `PANG BO` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx` :: `PANG GS` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx` :: `PANG ONE PAGER` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 10.2025/2025 OCTOBER RMR GS & BO.xlsx` :: `ILOCOS BO` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 10.2025/2025 OCTOBER RMR GS & BO.xlsx` :: `ILOCOS GS ` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 10.2025/2025 OCTOBER RMR GS & BO.xlsx` :: `ILOCOS ONE PAGER` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 10.2025/2025 OCTOBER RMR GS & BO.xlsx` :: `PANG BO` — repeated label(s): ['RMR GOODSTOCK & BADSTOCK OF APRIL 2025']

**Proposed handling rule:** disambiguate by column position (e.g. Unilever SKU file's first `Product` = code, second `Product` = name) — record the positional mapping in the family's column_map YAML rather than relying on label text alone.
