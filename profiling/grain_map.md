# Grain Map

Which files feed which fact/dim grain, derived from `profiling/sheet_profiles/*.json` `grain` field (regex/column-presence inference — see `profiling/detect.py::infer_grain`).

## Grain: `summary` (492 sheets, 75 files)
**Target:** SSIS mixed summary — needs per-sheet sub-classification, not a single grain

- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 10.2025/2025 OCTOBER RMR GS & BO.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 NOVEMBER RMR GS & BO.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 03.2025/2025 MARCH INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 04.2025/2025 APRIL INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 06.2025/2025 JUNE INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 08.2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 08.2025/2025 AUGUST INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 09.2025/2025 SEPTEMBER INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 12.2025/2025 DECEMBER INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte/Copy of DAILY SALES REPORT 07.31.2025.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte/DAILY SALES REPORT  09.30.2025.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte/DAILY SALES REPORT  10.31.2025 (1).xlsx`
- `data/raw/SANSAN MARKETING_Del Monte/DAILY SALES REPORT 08.30.2025.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte/DAILY SALES REPORT 11.17-20.2025.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte/MONTHLY SALES REGISTER 06.30.2025.xlsx`
- ... and 60 more files

## Grain: `invoice` (307 sheets, 60 files)
**Target:** Sales_Fact / Purchase_Fact / SalesReturn_Fact (invoice-level, NO SKU)

- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 10.2025/2025 ILOCOS OCTOBER SALES REGISTER.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 10.2025/2025 PANG. OCTOBER SALES REGISTER.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 ILOCOS NOVEMBER SALES REGISTER.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - 11.2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2023/PANGASINAN&ILOCOS JANUARY 1-JANUARY 31 2023 SALE REGISTER.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2023/PANGASINAN&ILOCOS JANUARY 1-JANUARY 31 2023 SALE RETURN.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2024/2024 JANUARY PURCHASES.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2024/2024 JANUARY SALES REGISTER.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2024/2024 JANUARY SALES RETURN.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2023/PANGASINAN&ILOCOS FEBRUARY 1-FEBRUARY 28 2023 SALE REGISTER.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2023/PANGASINAN&ILOCOS FEBRUARY 1-FEBRUARY 28 2023 SALE RETURN.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY PURCHASES.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES REGISTER.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SALES RETURN.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 03.2023/PANGASINAN&ILOCOS MARCH 1-MARCH 31 2023 SALE REGISTER.xlsx`
- ... and 45 more files

## Grain: `category` (34 sheets, 17 files)
**Target:** SellOut_Fact (category/brand hierarchy grain)

- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2023/PANGASINAN&ILOCOS JANUARY 1-JANUARY 31 2023 SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2024/2024 JANUARY SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2023/PANGASINAN&ILOCOS FEBRUARY 1-FEBRUARY 28 2023 SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 03.2023/PANGASINAN&ILOCOS MARCH 1-MARCH 31 2023 SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 03.2025/2025 MARCH SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 04.2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 04.2025/2025 APRIL SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 05.2023/PANGASINAN&ILOCOS MAY 1-MAY 31 2023 SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 06.2023/PANGASINAN&ILOCOS JUNE 1-JUNE 30 2023 SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 06.2025/2025 JUNE SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 08.2023/DELMONTE_SELL OUT_PANGASINAN & ILOCOS _AUGUST 2023.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 08.2025/2025 AUGUST SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 09.2023/SEPTEMBER 2023_SELL OUT.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 09.2025/2025 SEPTEMBER SELL OUT.xlsx`
- ... and 2 more files

## Grain: `sku` (19 sheets, 10 files)
**Target:** Inventory_Fact (SKU-level)

- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2023/JANUARY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 01.2024/2024 JANUARY INVENTORY SIGN OFF.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2023/FEBRUARY_2023_INVENTORY_SANSAN_ILOCOS.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 02.2025/2024 FEBRUARY INVENTORY SIGN OFF.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 03.2023/MARCH_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 04.2023/APRIL_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 05.2023/MAY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 06.2023/JUNE_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 09.2023/SEPTEMBER 2023_SIGN OFF INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 12.2023/DECEMBER 2023_SIGN OFF INVENTORY.xlsx`

## Grain: `inventory` (14 sheets, 7 files)
**Target:** Inventory_Fact

- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 03.2025/2025 MARCH INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 04.2025/2025 APRIL INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 06.2025/2025 JUNE INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 08.2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 08.2025/2025 AUGUST INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 09.2025/2025 SEPTEMBER INVENTORY.xlsx`
- `data/raw/SANSAN MARKETING_Del Monte (From Email)/MONTHLY REPORT - 12.2025/2025 DECEMBER INVENTORY.xlsx`

## Grain: `monthly-sku` (1 sheets, 1 files)
**Target:** SARIMA input — the ONLY confirmed SKU-level sales source (Unilever La Union)

- `data/raw/SANSAN MARKETING_Unilever/Unilever-La-Union-Sales-per-SKU-2023-to-2026.xls`

## The granularity gap

Sales Register / Purchases / Sales Return files are **invoice-level only** — no SKU column exists anywhere in that family (confirmed: header sets for these families contain `Invoice Date, Salesman, Town Display, Branch Code, Customer Name, Invoice Num, REFNBR, Untaxed Amount, ...` with no product/SKU field). Per-SKU demand series required for SARIMA (CLAUDE.md Phase 4) cannot be derived from these files directly.

The **Unilever La Union per-SKU file** (`SANSAN MARKETING_Unilever/Unilever-La-Union-Sales-per-SKU-2023-to-2026.xls`, actually an MHTML web archive) is the **sole confirmed SKU-level sales source** — grain `Calendar Month x Product x Pack Size`, Unilever La Union territory only. This is the Granularity Resolver's dependency per CLAUDE.md Part 2.

Sell Out files carry a **category/brand hierarchy grain** (leading-slash / indented paths like `/ACE/BASE`), not SKU — a second SKU-*ish* anchor but not a substitute for true SKU grain.

Inventory Sign-Off files carry genuine **SKU-level** stock snapshots (first-column SKU codes like `9DBL58403 DM ...`) — the third SKU-ish anchor, usable for point-in-time stock but not demand history.
