# The six sheets that fail their checksum (2026-10-22)

Source: `staging/_manifest.json` (git-ignored, built 14 Sep 2026): 1,286 staged sheets, 6 with `checksum_status = "mismatch"`, 1,113 rows between them. Staging was not re-run and the manifest was not modified. The raw workbooks under `data/raw/Del Monte/` were opened read-only (openpyxl, formulas and cached values), and the staged parquet files were read, to explain each mismatch.

## What a "checksum" is here

The manifest's `checksum_expected` is the cached value of a totals cell in row 1 of the source sheet itself (a spreadsheet `SUM(...)` formula). `checksum_got` is the sum of the checked column over the rows the extractor staged. There is no independent control total. The manifest does not store an expected row count, so a row-count mismatch cannot be shown from it; the row counts were compared directly instead (below).

## Per file

| # | Source file, sheet | Period | Family | Checked column | Expected (sheet's totals cell) | Staged sum | Difference | Staged rows (manifest = parquet = raw data rows) | Mismatch type | Rows in the staged set? | Why they differ | Reaches a real result? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `2025 MARCH SALES REGISTER.xlsx`, PANGASINAN SALES REGISTER | 2025-03 | sales_register | Net Amount | 6,136,297.81 (`L1 =SUM(L4:L2083)`) | 6,144,522.04 | 8,224.23 | 765 = 765 = 765 | Content (amount sum). Row count agrees. | Yes, all 765 | Formula starts at row 4 and skips the first data row (row 3). | **No** (see below) |
| 2 | `NOVEMBER 2023 SALES REGISTER.xlsx`, ILOCOS_SALES REG | 2023-11 | sales_register | Net Amount | 1,343,306.55 (`J1 =SUM(J23:J150)`) | 1,849,310.51 | 506,003.96 | 202 = 202 = 202 | Content (amount sum). Row count agrees. | Yes, all 202 | Formula covers rows 23 to 150 of a sheet whose data runs to row 204. | **No** |
| 3 | `2025 DECMBER PURCHASES.xlsx`, PANGASINAN PURCHASE | 2025-12 | purchase_order | Untaxed Amount | 14,417,647.57 (`H1 =SUM(H7:H99)`) | 17,284,874.41 | 2,867,226.84 | 45 = 45 = 45 | Content (amount sum). Row count agrees. | Yes, all 45 | Formula starts at row 7; data rows 3 to 6 (the newest bills) are outside it. | **No** |
| 4 | `2025 DECMBER PURCHASES.xlsx`, ILOCOS PURCHASE | 2025-12 | purchase_order | Untaxed Amount | 3,192,762.95 (`H1 =SUM(H7:H122)`) | 3,256,668.05 | 63,905.10 | 24 = 24 = 24 | Content (amount sum). Row count agrees. | Yes, all 24 | Same: rows 3 to 6 outside the formula. | **No** |
| 5 | `2024 FEBRUARY SALES RETURN.xlsx`, PANGASINAN SALES RETURN | 2024-02 | sales_return | Net Amount | 143,371.74 (`L1 =SUM(H3:H100)`) | 160,576.38 | 17,204.64 | 42 = 42 = 42 | Content (amount sum). Row count agrees. | Yes, all 42 | The totals cell sitting above Net Amount (column L) sums column H (Untaxed Amount). It equals the staged Untaxed Amount sum exactly (143,371.74). | **No** |
| 6 | `2024 JANUARY SALES RETURN.xlsx`, PANGASINAN SALES RETURN | 2024-01 | sales_return | Net Amount | 149,664.37 (`L1 =SUM(H3:H100)`) | 167,624.08 | 17,959.71 | 35 = 35 = 35 | Content (amount sum). Row count agrees. | Yes, all 35 | Same as row 5; staged Untaxed Amount sum is 149,664.37. | **No** |

Rows: 765 + 202 + 45 + 24 + 42 + 35 = 1,113, the figure in the manifest. For all six, re-summing the checked column straight from the raw workbook's data rows gives exactly the staged sum, and the formula range re-computed from the raw cells gives exactly the "expected" figure. So the extractor dropped nothing and altered nothing; the six totals cells are wrong, not the staged data. The same finding is on record in `config/checksum_allowlist.yaml` (2026-09-30 sweep of all 54 checksummed real files: these 6 and no others; each is allow-listed by file hash and sheet).

## Does any of it reach a real result?

Everything here is Del Monte invoice grain (no product key). Checked by reading the code, not by running the pipeline:

| Result | Reads these rows? | Evidence |
|---|---|---|
| Forecasts (Unilever per-SKU; Del Monte category) | No | The forecast runner and `analytics/forecasting` do not reference `sales_fact`, `purchase_fact` or `salesreturn_fact`. Unilever reads `Unilever_SKU_Demand_Fact_Real`; Del Monte reads `SellOut_Fact_Real` (`backend/routers/dashboard.py:630-631` says Sales_Fact is deliberately not used). |
| Accuracy metrics, `docs/ACCURACY_AS_SERVED.md` | No | Every figure there is Unilever per-SKU; the file has no Del Monte figure. `mart.accuracy_mart` is built from `forecast_result`. |
| LP plan (`lp_run`) | No | The LP is Unilever-only on real stock; its inputs are forecast, inventory and params. |
| Dashboard flow lines | Yes, as displayed amounts | `mart.flow_month` takes `purchase_fact` (rows 3, 4) and `salesreturn_fact` (rows 5, 6) (`analytics/db/migrations/0041_data_marts.sql:430-456`). Rows 1 and 2 (`sales_fact`) are not in `mart.sales_mart`; they surface only in `/inventory/movement` (newest 50 invoices; `backend/routers/inventory.py:123-140`). These are the figures the sheet reports, correctly summed, not the wrong totals-cell values. |

Per file, "reaches accuracy / forecasts / LP / ACCURACY_AS_SERVED.md": **no** for all six. "Reaches a displayed flow or movement figure": rows 1, 2 via `/inventory/movement`; rows 3, 4 via purchases flow and `/inventory/movement`; rows 5, 6 via returns flow. In every case the loaded value is the sum of the real data rows.

## Live presence (read-only query, 2026-10-22)

All 1,113 rows are in the live database, with the same row counts and the same sums as the staged files (checked with `BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK` on the `_real` views, by period and source sheet):

| Sheet | Live table | Rows | Sum of Net Amount (live) |
|---|---|---|---|
| Sales register 2025-03 Pangasinan | sales_fact_real | 765 | 6,144,522.04 |
| Sales register 2023-11 Ilocos | sales_fact_real | 202 | 1,849,310.51 |
| Purchases 2025-12 Pangasinan | purchase_fact_real | 45 | 19,359,059.30 |
| Purchases 2025-12 Ilocos | purchase_fact_real | 24 | 3,647,468.21 |
| Sales return 2024-02 Pangasinan | salesreturn_fact_real | 42 | 160,576.38 |
| Sales return 2024-01 Pangasinan | salesreturn_fact_real | 35 | 167,624.08 |

(`purchase_fact_real` has no Untaxed Amount column, so the purchase rows are compared on Net Amount; the staged Net Amount sums are the same figures.)

## Not determined

* Staged parquet files are dated 21 Sep 2026, the manifest 14 Sep 2026, and the files on disk are not the same set as the manifest (for instance 544 real purchase_order rows on disk against 2,453 in the manifest, which counted the synthetic files then). For the six sheets above the parquet row counts and sums match the manifest exactly, so the findings hold for them; the totals elsewhere were not compared.
