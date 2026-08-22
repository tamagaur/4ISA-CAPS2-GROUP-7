# Data Dictionary — the 7 real document families

~175 real source files, but only 7 real shapes. This is one section per family, ordered by how much the DSD actually depends on it — not alphabetically.

Every column table below was read from the real staged `.parquet` files and the real `config/column_maps/*.yaml` files just now, not from `ARCHITECTURE.md` or memory. **"Verified"** means the meaning is provable from the data itself or an existing code comment that was checked against real samples. **"Inferred"** means it's a reasonable guess from the column name alone, nothing more — if a row says inferred, treat it as a guess, not a fact.

---

## 1. Unilever SKU file — the only per-SKU demand source we have

**What it is:** A monthly export of Unilever's own sales-tracking system, one row per SKU per month. This is the only file in the entire corpus where a row represents a single product's performance, not an invoice or a category rollup — which is exactly why Unilever is the only principal we can forecast at SKU level.

**Representative files:** Only one file exists for this whole family — `UnileverLaUnionSalesperSKU2023to2026.xls` — covering January 2023 through February 2026 in one sheet. No eras to compare; it's a single, single-template export.

**Column table** (7 real columns, from `staging/unilever_sku/*.parquet`):

| Raw header | Meaning | Used? | Verified/Inferred |
|---|---|---|---|
| `Calendar\r\n  Month` | The month this row covers, raw format `MM.YYYY` | USED → `calendar_month` | Verified — confirmed by direct inspection of real values, e.g. `01.2023` |
| `Product` | **Misleading name — this is the SKU code, not a product name**, e.g. `20292808` | USED → `sku_code` | Verified — code comment confirms this was checked against real source samples |
| *(blank — no header text)* | The actual product name/description, e.g. `MASTER CLEANSER OIL CONTROL 144X70ML` | USED → `product_name` | Verified — real sample text confirms |
| `Pack Size` | A small integer, e.g. `144` | USED, but only as a cross-check calculation, never stored | Inferred — the column map admits it's "not confirmed whether this means units-per-pack or something else" |
| `Sale Quantity in\r\n  Aggr.CS` | Quantity sold, in cases | USED, but only as a cross-check — does **not** feed the real quantity figure | Verified — confirmed only ~84% consistent with the pieces column below, so it's not trusted as the source of record |
| `Sale Quantity in\r\n  Aggr.PC` | Quantity sold, in pieces | **USED — this is the real, trusted quantity figure** | Verified — this is what `quantity_sold` is actually set from |
| `GSV` | Gross Sales Value | Renamed to a canonical field, but **not currently loaded into any database column** | Inferred — the column map itself says "not yet confirmed which fact field this should feed" |
| `Total Sales Amt\r\n  Inc. Tax` | Total sale amount including tax | Renamed to a canonical field, but whether it actually reaches the database's `net_amount` column is **not confirmed in code** | Inferred — plausible connection, not verified as wired up |

**Why we need it:** This is the direct input to `Unilever_SKU_Demand_Fact`, which is the one and only source of real per-SKU demand data in the whole project. Without this file, Unilever couldn't be forecast at all — not "less accurately," genuinely not at all, since no other file has a SKU column for Unilever.

**Current status:** Flowing through Transform successfully. **1 sheet, 1 promoted, 0 rejected** in the last real run.

---

## 2. Del Monte Sell Out — the Del Monte demand source

**What it is:** A monthly rollup of what Del Monte's products actually sold through to end customers, grouped by category/brand — not by individual SKU. One row is one category's totals for the month (e.g. all of "FRUITS" sold in a region that month), not a single sale.

**Representative files:** `PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SELL OUT.xlsx` (2023, richer category-path style) and `2025 AUGUST SELL OUT.xlsx` (2025, flatter category style) — both real, both currently staged.

**Column table** — two real shapes exist, both real and currently staged:

*2023-era files* (`staging/sell_out/PANGASINAN_ILOCOS_APRIL_1-APRIL_30_2023_SELL_OUT__...parquet`):

| Raw header | Meaning | Used? | Verified/Inferred |
|---|---|---|---|
| *(blank — leading, unlabeled column)* | Category/brand path, e.g. `/ACE/BASE`, `/DISPENSER JUICE/DISPENSER JUICE - BASE REGULAR` | USED → `category_path` | Verified — confirmed genuinely blank in source, not a detection failure |
| `Total Without Tax` | Peso revenue for that category that month | USED → `net_amount` | Verified — header is self-explanatory and matches the raw value pattern |
| `Product Quantity` | Units sold for that category | USED → `quantity`, but **the actual unit (pieces? cases?) is not confirmed anywhere** | Inferred — the column map explicitly says no unit was ever confirmed for this field |

*2025-era files add one column* (`staging/sell_out/...SELL_OUT.parquet`, August 2025 on):

| Raw header | Meaning | Used? | Verified/Inferred |
|---|---|---|---|
| `CASE` | Same category, in case units — only appears from 2025 onward | USED → `quantity_cases`, same "unit not confirmed" caveat | Inferred |

**Why we need it:** This feeds `SellOut_Fact`, and via the newly-merged `Product_Demand_View`, is what Del Monte's forecasting is meant to read — at category grain, because that's the finest grain this file (or any Del Monte file) actually supports. There is no SKU column anywhere in this family — confirmed by direct inspection, not assumed.

**Current status: NOT flowing through Transform right now.** All 34 real staged sheets are **blocked**, every single one with the same reason: `category_path` is missing from the DataFrame at the point Transform needs it — the real column map's `__col0__` placeholder mapping isn't matching cleanly against every real file. This is a known, already-flagged gap, not something new. **0 of 34 sheets promoted.**

---

## 3. Del Monte Sales Register — the transaction record (and the reason Del Monte can't go SKU-level)

**What it is:** Del Monte's invoice log. One row is one invoice's grand total — who bought, when, how much — never a line-item breakdown of what was actually in that invoice.

**Representative files, 2 confirmed real eras** (a possible third "vocab C" spelling is documented in the column map but I could not find a real currently-staged file matching it distinctly — noting that honestly rather than forcing an example):

*Vocab A* — `2025 APRIL SALES REGISTER.xlsx` (also used in 2023/2024 files):

| Raw header | Meaning | Used? | Verified/Inferred |
|---|---|---|---|
| `Invoice Date` | Date of the invoice | USED → `invoice_date` | Verified |
| `Salesman` | Salesperson credited | USED → `salesman` | Verified |
| `Town Display` | Region/town | USED → `region` | Verified — confirmed blank on ~38% of real rows (a real source-data gap, not a code bug) |
| `Branch Code` | SSM branch identifier, e.g. `L12E-000624` | USED → `branch_code` | Verified |
| `Customer Name` | Buyer's business name | USED → `customer_name` | Verified |
| `Invoice Num` | Invoice number, e.g. `INV/2025/1650` | USED → `invoice_num` | Verified |
| `REFNBR` | A second reference number, e.g. `ODM0028805` | USED → `invoice_num` (same canonical field as above) | Verified as mapped — but a real, unresolved question: real data shows `Invoice Num` and `REFNBR` disagree on ~86% of overlapping rows, meaning they may not actually be the same thing despite sharing a destination field |
| `Untaxed Amount` | Pre-tax invoice amount | USED → `untaxed_amount` | Verified |
| `Discount Rate` | Text label, e.g. `"LESS 4%"`, `"Public Pricelist"` — **not a number** | USED → `discount_rate_label` | Verified |
| `Dscount Amount` *(sic — real typo in source)* | Discount amount in pesos | USED → `discount_amount` | Verified |
| `Tax` | Tax amount | USED → `tax_amount` | Verified |
| `Net Amount` | Final invoice total | USED → `net_amount` | Verified |
| `Balance` | Outstanding balance | USED → `balance` | Verified |
| `Posted` | Workflow flag (Yes/No) | **UNUSED — deliberately not mapped**, no destination in the schema | Verified — this is a documented, deliberate exclusion |

*Vocab B* — a differently-named header set covering ~85 real staged files, e.g. `2025 ILOCOS NOVEMBER SALES REGISTER.xlsx` (files this vocabulary appears in are the ones stored under "DAILY REPORT" folders, despite being ordinary monthly-shaped Sales Register data):

| Raw header | Same meaning as vocab A | Used? | Verified/Inferred |
|---|---|---|---|
| `AREA` | = `Town Display` | USED → `region` | Verified |
| `REFERENCE #` | = `Invoice Num`/`REFNBR` | USED → `invoice_num` | Verified |
| `NET VALUE` | = `Untaxed Amount` | USED → `untaxed_amount` | Verified |
| `DISCOUNT AMNT.` | = `Discount Amount` | USED → `discount_amount` | Verified |
| `TAX AMNT.` | = `Tax` | USED → `tax_amount` | Verified |
| `AMOUNT` | = `Net Amount` | USED → `net_amount` | Verified |

**No column in either vocabulary carries a product code, product name, or any product reference of any kind.** Confirmed directly by reading real rows — every field is identity (who/when/where) or money.

**Why we need it:** Feeds `Sales_Fact`, Del Monte's half of the transaction mart. Just as important as a *negative* finding: this file is the direct, visual proof behind the decision that Del Monte can never be forecast at SKU level — there's no line-item data to lose a SKU column from, the file never itemized by product in the first place.

**Current status:** Flowing through Transform, mostly cleanly. **127 sheets: 120 promoted, 4 demoted (correctly excluded cross-check sheets), 3 conflict** (real rows sharing an invoice/region/principal key but disagreeing on amount — flagged for a human, not resolved automatically).

---

## 4. Del Monte Inventory Sign-Off — current stock levels

**What it is:** A monthly stock count. One row is one SKU's on-hand quantity at that snapshot date. Unlike Sales Register, this file family **does** carry a real product identifier — just not cleanly, and not the same way across years.

**Representative files, 3 real distinct shapes found:**

*2023-era* (e.g. `DELMONTE_INVENTORY SIGN OFF_...AUGUST 2023.xlsx`):

| Raw header | Meaning | Used? | Verified/Inferred |
|---|---|---|---|
| *(blank, leading column)* | Combined "SKU code + product name" in one cell, e.g. `9DMR56831 DM QUICK N EASY MECHADO SAUCE (Royce)` | **UNUSED — not mapped for this era** | Verified — the column map deliberately does not map this position for 2023-era files, since the same position means something different in 2025 files (see below) |
| `Quantity` | Units on hand | USED → `quantity_on_hand` | Verified |
| `Cost` | Per-unit or total cost | UNUSED — not mapped | — |
| `Valuation` | Total inventory value | UNUSED — not mapped | — |
| `Valuation with VAT` | Total inventory value incl. tax | UNUSED — not mapped | — |
| `CAS` | Cases | USED → `cases` | Verified |
| `PCS` | Pieces | USED → `pieces` | Verified |
| `PKG`, `in PCS`, `in Cases` (when present) | Packages / breakdown figures | USED, but **inferred by column position, not by matching header text** — these columns have no header at all in most real files | Inferred — the column map's own comment calls this "reasonable evidence, not a confirmed match," and flags it for a human to spot-check |

*2025-era, cleanly labeled* (e.g. `2025 APRIL INVENTORY.xlsx`):

| Raw header | Meaning | Used? | Verified/Inferred |
|---|---|---|---|
| `CATEGORY` | Product category | UNUSED — not mapped in the current column map | — |
| `PRODUCT/ SKU CODE` | Real, clean SKU code | **UNUSED — not mapped in the current column map**, despite being a clean real header | Verified this column exists with real values; verified it is genuinely not in the map |
| `DESCRIPTION` | Product name | UNUSED — not mapped | — |
| Other columns (`BASE UNIT`, `CASE PACK`, `SKU BARCODE`, price fields) | Product master-data fields | UNUSED — not mapped | — |

This 2025-era shape is a genuinely different, cleaner report layout than the 2023-era one, and the current column map was built for the 2023-era shape — it does not cover this one at all yet. This matches the already-known gap: "a third real file layout the column map doesn't cover."

**Why we need it:** Feeds `Inventory_Fact` — current stock on hand, needed for reorder-point and safety-stock decisions. It's also the *only* Del Monte file with a real product identifier at all, which matters if anyone ever wants to sanity-check Del Monte category assignments against real SKUs.

**Current status: NOT flowing through Transform right now.** All 41 real staged sheets are **blocked**, all with the same reason: `sku_code` is missing from the DataFrame — a direct consequence of the 2025-era layout gap above (and the 2023-era layout never having its SKU column mapped either). **0 of 41 sheets promoted.**

---

## 5. Del Monte Purchase Order — incoming stock from the supplier

**What it is:** Del Monte's purchase log — what SSM bought *from* Del Monte (the supplier), as opposed to what SSM sold *to* its own customers. One row is one purchase invoice. Same POS export tool as Sales Register, but a different relationship: "Customer Name" in this file is actually the supplier's name (`DMPI` — Del Monte Philippines Inc.), not a customer.

**Representative files:** `2025 APRIL PURCHASES.xlsx` (2025 era) and `DECEMBER 2023_PURCHASE ORDER.xlsx` (2023 era, slightly narrower column set — no `Returns`/`Net Amount (Actual Invoice)` columns).

**Column table** (2025-era shape, `staging/purchase_order/2025_APRIL_PURCHASES__PANGASINAN_PURCHASE.parquet`):

| Raw header | Meaning | Used? | Verified/Inferred |
|---|---|---|---|
| `Invoice Date` | Purchase invoice date | USED → `invoice_date` | Verified |
| `Salesman` | Actually a site/branch label here, not a person, e.g. `PANGASINAN SITE` | USED → `salesman`, kept as-is | Verified — real sample confirms it's not a person's name |
| `Town Display` | Region — real data shows this is sometimes the literal boolean `False`, a genuine source quirk | USED → `region` | Verified |
| `Branch Code` | SSM branch code | USED → `branch_code` | Verified |
| `Customer Name` | **Misleading — this is the supplier's name (`DMPI`)**, not a customer | USED → `supplier_name` | Verified |
| `Invoice Num` | Purchase invoice number, e.g. `BILL/2025/0120` | USED → `invoice_num` | Verified |
| `REFNBR` | A PO reference, e.g. `PO02502` — **means something different here than in Sales Register** | USED → `po_reference` (a separate field, not merged into `invoice_num`) | Verified |
| `Untaxed Amount` | Pre-tax amount | USED → `untaxed_amount` | Verified |
| `Discount Rate` | Text label | USED → `discount_rate_label` | Verified |
| `Discount Amount` | Discount in pesos | USED → `discount_amount` | Verified |
| `Tax` | Tax amount | USED → `tax_amount` | Verified |
| `Net Amount` | Total invoice amount | USED → `net_amount` | Verified |
| `Balance` | Outstanding balance | USED → `balance` | Verified |
| `Posted` | Workflow flag | UNUSED — deliberately not mapped | Verified |
| `Return Slip #` | Return reference, when present | USED → `return_slip_num` | Verified |
| `Returns` | Return flag/marker | USED → `return_type` (also matches `Return Type` spelling in other files) | Verified |
| `Net Amount ( Actual Invoice)` | A second net-amount figure, sits next to `Net Amount` | **UNUSED — deliberately not mapped**, likely a cross-check echo column, not confirmed as authoritative | Inferred — flagged explicitly in the column map as an open question, not decided |

**No quantity/units column exists anywhere in this file family** — confirmed directly. `Purchase_Fact.units_received` (used for the Bad-Order-rate calculation) has no real source column here at all.

**Why we need it:** Feeds `Purchase_Fact` — the denominator side of the Bad Order rate (`bo_net_amount / purchase_net_amount`), and general procurement tracking.

**Current status:** Flowing through Transform, but with real friction. **22 sheets: 11 promoted, 11 conflict** — exactly half hit a dedup conflict on `(invoice_num, principal, region)`, flagged for a human, not yet diagnosed further than that in this pass.

---

## 6. RMR GS & BO — returns and bad orders

**What it is:** Del Monte's returns log, split into two real categories: GS (Good Stock returns) and BO (Bad Order — damaged/expired stock). One row is one return transaction. Each workbook also has a third "ONE PAGER" sheet per region that's just GS and BO added together — a duplicate view, never loaded.

**Representative files:** `2025 OCTOBER RMR GS & BO.xlsx` and `2025 NOVEMBER RMR GS & BO.xlsx` — the only two real files in this family, and they share one identical column shape (confirmed, no drift).

**Column table** (`staging/rmr_gs_bo/2025_OCTOBER_RMR_GS_BO__ILOCOS_BO.parquet`):

| Raw header | Meaning | Used? | Verified/Inferred |
|---|---|---|---|
| `Invoice Date` | Date of the return | USED → `invoice_date` | Verified |
| `Salesman` | Salesperson | USED → `salesman` | Verified |
| `Town Display` | Region | USED → `region` | Verified |
| `Customer Name` | Store/customer name | USED → `customer_name` | Verified |
| `Untaxed Amount` | Pre-tax return value | USED → `untaxed_amount` | Verified |
| `Discount Amount` | Discount portion | USED → `discount_amount` | Verified |
| `Tax` | Tax portion | USED → `tax_amount` | Verified |
| `Net Amount` | Total return value | USED → `net_amount` | Verified |
| `Balance` | Balance figure | USED → `balance` | Verified |
| `Return Slip #` | Return reference, e.g. `RMR39342` | USED → `return_slip_num` | Verified |
| `Return Type` | `GS` or `BO`, confirmed real values | USED → `return_type` | Verified |

**No quantity, units, or SKU column exists anywhere in this file family** — confirmed directly by reading real rows. This is the entire reason the Bad Order rate is calculated in pesos, not units — there was never a units figure to calculate it from.

**Why we need it:** Feeds `SalesReturn_Fact` — the numerator side of the Bad Order rate, and the only real returns data in the corpus. `bo_units` will permanently be `NULL` for every row; that's a fact about the source, not a bug.

**Current status:** Flowing through Transform cleanly. **12 sheets: 8 promoted (the real GS/BO split), 4 demoted (the 4 "ONE PAGER" cross-check sheets, correctly excluded per DEC-04) — 0 rejected.**

---

## 7. SSIS Summary — Unilever's real sales system, currently orphaned

**What it is:** ~60 monthly exports directly from Unilever's own SSIS sales-tracking system. Each workbook has multiple tabs with different purposes — the real sales data (`RAW DATA`), invoice-style cross-checks (`Invoice Reg`), inventory snapshots, return logs, and several genuinely blank/scratch tabs. This is the single largest source in the whole corpus by row count.

**Representative files:** `SSIS APRIL 2024.xlsx` and `SSIS AUGUST 2022.xlsx` — two real eras with a small but real header difference (see below).

**Column table** — the `RAW DATA` sheet, the one that actually matters (`staging/ssis_summary/*RAW_DATA.parquet`):

| Raw header | Meaning | Used? | Verified/Inferred |
|---|---|---|---|
| `Salesman` | Salesperson | USED → `salesman` | Verified |
| `CALENDAR DAY` | The specific day of the transaction | USED → `calendar_day` | Verified |
| `REASON CODE` | A code explaining the transaction type | USED → `reason_code` | Verified |
| `OUTLET` | Outlet identifier, numeric-looking but kept as text (leading zeros are real) | USED → `outlet_code` | Verified |
| `OUTLET NAME` | Outlet name | USED → `outlet_name` | Verified |
| `GSV` | Gross Sales Value | USED → `gsv` | Verified |
| `TPR + UW/DT Discount` | Combined discount figure | USED → `discount_amount` | Verified |
| `Sale After TPR & UW` | Net sale after discount | USED → `net_amount` | Verified — chosen over the near-identical `NIV` column below because only one can map to avoid ambiguity |
| `NIV` | A near-duplicate of `Sale After TPR & UW` — confirmed identical in every sampled row | **UNUSED — deliberately not mapped**, to avoid two raw columns claiming the same canonical field | Verified |
| `VAT` | Value-added tax | USED → `vat` | Verified |
| `Total Sales Amt Inc. Tax` | Total including tax | USED → `net_amount_inc_tax` | Verified |
| `REMARKS` | Free-text notes | USED → `remarks` | Verified |
| `UL GSV`, `Mark-up/Mark-down Value in %` | Only appear in some files (e.g. April 2024, not August 2022) | **UNUSED — not mapped, real header drift between eras** | Verified as present/absent by direct comparison of the two files |

**Critically: no invoice number, reference number, or transaction ID column of any kind exists on this sheet** — confirmed against real headers, not assumed. The real grain looks like outlet + calendar day (+ reason code), not invoice.

**Why we need it:** This is genuinely complicated right now. It was originally meant to feed `Sales_Fact` for Unilever. Two things now stand in the way: (1) there's no real transaction key to dedup on, so `transform_fact()` refuses to run rather than invent one; (2) even if a key were found, `Sales_Fact` was later restricted to Del Monte only (a separate, later decision), so this data would need an entirely new destination table to go anywhere. **As things stand today, this family feeds nothing** — it's the largest real source in the corpus and currently has no destination at all. Not inventing a purpose it doesn't have.

**Current status: NOT flowing through Transform.** All 805 real staged sheets are **blocked** — 661 because the natural key is genuinely unconfirmed (see above), and 144 because they're auxiliary tabs (`INVENTORY`, `B.O SUMMARY`, blank scratch sheets) that neither of our two principal-detection methods can identify as Unilever or Del Monte, so they can't be claimed by any rule at all. **0 of 805 sheets promoted.**

---

## Quick-reference summary

| # | Family | Feeds | Sheets promoted / total (last real run) |
|---|---|---|---|
| 1 | Unilever SKU | `Unilever_SKU_Demand_Fact` | 1 / 1 |
| 2 | Del Monte Sell Out | `SellOut_Fact` | 0 / 34 |
| 3 | Del Monte Sales Register | `Sales_Fact` | 120 / 127 |
| 4 | Del Monte Inventory Sign-Off | `Inventory_Fact` | 0 / 41 |
| 5 | Del Monte Purchase Order | `Purchase_Fact` | 11 / 22 |
| 6 | RMR GS & BO | `SalesReturn_Fact` | 8 / 12 |
| 7 | SSIS Summary | nothing today | 0 / 805 |
