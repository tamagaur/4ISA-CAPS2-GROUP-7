# Files the system needs each month

**For SSM.** Please send these files each month. Column headings may differ in capitals and spacing and still be read; any other spelling is not recognised unless the "also accepted" spelling below is used. Extra columns are fine and are ignored.

Excel workbooks (.xlsx, .xls) work for every file. CSV works only for the Unilever sales file, because the others are found by their sheet name and a CSV has no sheets.

## Unilever

| File | How to name it | Must contain | Useful if present | If something is missing today |
|---|---|---|---|---|
| **Sales per SKU** (one sheet, any number of months) | **La Union** in the file name, e.g. `UnileverLaUnionSalesperSKU2023to2026.xls` | Calendar Month · Product · the product name in the third column, with no heading · Pack Size · Sale Quantity in Aggr.CS · Sale Quantity in Aggr.PC · GSV · Total Sales Amt Inc. Tax | Nothing else is read | A column: the file is refused and nothing loads. "La Union" not in the name: every row is left out |
| **Stock count (SSIS workbook)**, sheet named `SOH(<date of the count>)` | The month and year in the file name, e.g. `SSIS MARCH 2026.xlsx` | Article No · Article Description · PACK SIZE · Stock Quantity (CS/PC) · Stock Value · PO Qty · Open SO Quantity · Balance Quantity · Status · CATEGORY DESC | Last Purchase Price(GSV/CS) · Blocked Stock(CS/PC) · Batch | A column: the file is refused and nothing loads. No SOH sheet, or no month in the name: the workbook is skipped, and no stock count loads for that month. Last Purchase Price missing: stock for that month has no peso value at purchase price |

## Del Monte

Put each month's files in a folder named `MONTHLY REPORT - <MONTH> <YEAR>`. Each sheet or file name should also say the branch (**Pangasinan** or **Ilocos**).

| File | Sheet name contains | Must contain | Useful if present | If something is missing today |
|---|---|---|---|---|
| **Sales register** | `SALES REG`, or a sheet named by number such as `2026` | Invoice Date · Invoice Num (also REFNBR, REFERENCE #) · Customer Name (also Customers) · Salesman · Untaxed Amount (also NET VALUE) · Tax (also TAX AMNT.) · Net Amount (also AMOUNT) | Town Display (also AREA) · Discount Amount · Balance · Return Slip # · Return Type · Discount Rate · Total Discount to be claim · Total CAS/PCS · Total CAS · Total PCS · Branch Code (also Outlet) | A required column: refused, nothing loads. An optional one: loads, that field blank |
| **Purchases** | `PURCHASE` | Invoice Date · Invoice Num · Customer Name (the supplier) · Untaxed Amount · Tax · Net Amount | Salesman · Branch Code · REFNBR · Discount Rate · Discount Amount · Balance · Return Slip # · Return Type | Same |
| **Sales returns** | `SALES RETURN`, `GS` or `BO` | Invoice Num · Return Slip # · Net Amount | Return Type · Total CAS · Total PCS | Same. A row with no slip number is set aside, not loaded |
| **Sell-out** | `SELL OUT` | The category in the first column, with no heading · Total Without Tax (also Total With Tax) · Product Quantity | CASE | Same |
| **Inventory sign-off** | `SIGN OFF`, `ACTUAL` or `ILO` + number | Either Quantity, Cost and Valuation; or ITEM CODE, ITEM DESCRIPTION and PCS | Valuation with VAT · CAS · PKG · in PCS · in Cases | Same |
| **RMR GS/BO** (used for 2025-10 and 2025-11 only) | `ONE PAGER` | Invoice Date · Customer Name · Salesman · Untaxed Amount · Net Amount · Return Slip # · Return Type | Town Display · Discount Amount · Tax · Balance | Same |

## In every file

A row whose key field is blank is set aside rather than loaded, and is kept on record: invoice number for sales and purchases; product code and month for Unilever sales; product code for stock. A month with no file is reported as missing. It is never filled in by the real path.

## For the team (not for SSM)

- Source: `required:` and `sheet_names:` in `config/column_maps/<kind>.yaml`, read by `analytics/etl/extract/layout.py`; row keys in `config/source_of_truth.yaml`. Those files win over this table.
- Refusal codes: `unknown_layout`, `layout_changed`, `month_unknown`, `missing_file` (`scripts/load_slices.py`), each with an `etl_load_event` row. A header no map knows is loaded around and warned as `unmapped_column`.
- **Run on a real file:** Unilever sales only, 2026-11-04, dry run on the throwaway database: same month as .xls and as .csv with La Union in the name, 779 rows prepared; without it, 779 excluded and the slice refused by the shrink guard. A new month has nothing for that guard to protect (not run). **Read from code, not run:** the Del Monte "if missing" column and the stock count's optional columns.
- Not needed: `ssis_summary` (RAW DATA sheet, no product grain, DEC-04) and `daily_sales_report`.
