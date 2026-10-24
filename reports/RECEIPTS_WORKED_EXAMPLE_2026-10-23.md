# Worked example: derived February 2026 receipts (Unilever)

> Published figures: its two products appear in the manuscript with their arithmetic, so these figures are published and the purpose of hard rule 9 (confidentiality of unpublished per-product data) does not apply to this file.

Written for: the manuscript, as two single-product illustrations of the derived-receipts calculation. Source discussion: `reports/FOLLOWUP_2026-10-23.md` §3c. All figures queried read-only on 2026-10-24 and cross-checked against `local/stock_reconciliation_per_product_2026-10-23.csv`.

## The rule

SSM has no Unilever delivery records, so receipts are derived: **receipts = closing count − opening count + pieces sold in between.** Counts are in pieces (cases × pack size + loose pieces). Because the figure is defined by this identity, it always balances; what can be tested is whether the result is possible (not negative) and ordinary.

Two date points before the examples:

- The "February" opening count is the file month 2026-01, taken **3 February 2026** (not 2 February). The closing count is file month 2026-02, taken **2 March 2026**.
- Stock tables hold cases plus loose pieces; pieces = `quantity_on_hand` × `product_dimension.pack_size` + `quantity_pieces` (`backend/stock_units.py:69-74`).

## Example 1: a large receipt (neither a negative-receipt product nor a stock-fall-beyond-best-month product)

| | Figure | Source (table.column) |
|---|---|---|
| a. Product | **69668149 — SURF POWDER SUN FRESH L 288X65G** (pack size 288) | `product_dimension.sku_code`, `product_name`, `pack_size` |
| b. Opening count, snapshot 3 Feb 2026 | **15,944 pieces** = 55 cases × 288 + 104 loose | `inventory_fact_real` (`_period` 2026-01, `snapshot_date` 2026-02-03): `quantity_on_hand` 55, `quantity_pieces` 104; equals `derived_receipt_fact.opening_pieces` |
| c. Closing count, snapshot 2 Mar 2026 | **235,487 pieces** = 817 cases × 288 + 191 loose | `inventory_fact_real` (`_period` 2026-02, `snapshot_date` 2026-03-02): `quantity_on_hand` 817, `quantity_pieces` 191; equals `derived_receipt_fact.closing_pieces` |
| d. Pieces sold, February 2026 | **62,753** | `unilever_sku_demand_fact_real.quantity_sold`, `calendar_month` = '2026-02'; equals `derived_receipt_fact.sold_pieces` |
| e. Derived receipts | 235,487 − 15,944 + 62,753 = 219,543 + 62,753 = **282,296 pieces** | matches `derived_receipt_fact.receipt_pieces` (282,296; `balance_pieces` 282,296; `flag` empty) |
| f. Highest monthly sales, preceding 36 months | **141,290 pieces, January 2024** (next: 132,900 in March 2024) | `unilever_sku_demand_fact_real.quantity_sold`, `calendar_month` '2023-03'..'2026-02' (window including February 2026) and '2023-02'..'2026-01' (the 36 months before it) give the same answer. The product has 32 months of sales in the window (first sale 2023-07). |
| g. In the 146 / the 189? | **Neither.** Receipts are positive. The 2 Mar → 6 Apr fall is 235,487 → 110,431 = 125,056 pieces, below its best month of 141,290 (`fall_beyond_best_month` = 0). | `local/stock_reconciliation_per_product_2026-10-23.csv` (`implied_receipts_feb`, `fall_beyond_best_month`); 6 Apr count from `inventory_fact_real` `_period` 2026-03 |

Reading it: the 282,296 pieces received equal 4.5 times that month's sales of 62,753, and stock was 14.8 times the January level. One month of stock cover moved from about a quarter of a month to nearly four months. Stock fell back to 110,431 by 6 April. The count is not shown to be wrong, but nobody holds the delivery records to confirm the receipt.

## Example 2: an impossible receipt (one of the 146 negative-receipt products)

| | Figure | Source (table.column) |
|---|---|---|
| a. Product | **68438411 — KNORR BN CUBES CHICKEN PANTRY 72X60G** (pack size 72) | `product_dimension.sku_code`, `product_name`, `pack_size` |
| b. Opening count, snapshot 3 Feb 2026 | **3,505 pieces** = 48 cases × 72 + 49 loose | `inventory_fact_real` (`_period` 2026-01, `snapshot_date` 2026-02-03): `quantity_on_hand` 48, `quantity_pieces` 49; equals `derived_receipt_fact.opening_pieces` |
| c. Closing count, snapshot 2 Mar 2026 | **464 pieces** = 6 cases × 72 + 32 loose | `inventory_fact_real` (`_period` 2026-02, `snapshot_date` 2026-03-02): `quantity_on_hand` 6, `quantity_pieces` 32; equals `derived_receipt_fact.closing_pieces` |
| d. Pieces sold, February 2026 | **659** | `unilever_sku_demand_fact_real.quantity_sold`, `calendar_month` = '2026-02'; equals `derived_receipt_fact.sold_pieces` |
| e. Derived receipts | 464 − 3,505 + 659 = −3,041 + 659 = **−2,382 pieces** | `derived_receipt_fact.balance_pieces` = −2,382; `flag` = `negative_balance`; stored `receipt_pieces` is **0** (negative balances are held at zero, not stored as negative) |
| f. Highest monthly sales, preceding 36 months | **3,076 pieces, February 2024** (next: 2,392 in May 2023) | `unilever_sku_demand_fact_real.quantity_sold`, `calendar_month` '2023-03'..'2026-02' and '2023-02'..'2026-01' give the same answer; 36 of 36 months present |
| g. In the 146 / the 189? | **One of the 146** (negative receipt). **Not one of the 189**: 6 Apr count is 1,912, above 464 (`fall_beyond_best_month` = 0). | `local/stock_reconciliation_per_product_2026-10-23.csv` (`implied_receipts_feb` = −2,382, `fall_beyond_best_month` = 0) |

Reading it: the warehouse held 3,505 pieces on 3 February and sold 659 in February, so at most 2,846 pieces should remain with no receipts at all. The 2 March count found 464, which is 2,382 pieces fewer than selling alone explains. Receipts cannot be negative, so the count, the sales figure (La Union only, UNVERIFIED against the Ilocos Sur warehouse), or stock leaving by another route is wrong or incomplete. The data cannot say which.

## Portfolio ratio

| Measure | Figure | Source |
|---|---|---|
| Net derived receipts, February 2026 | 3,827,499 pieces | `derived_receipt_fact` where `_period` = '2026-02': sum of `balance_pieces` (852 products); the sum of stored `receipt_pieces` is 3,865,916 and the 175 negative balances total −38,417 |
| Pieces sold, February 2026 | **1,766,710** | `unilever_sku_demand_fact_real.quantity_sold` where `calendar_month` = '2026-02' (779 rows, 2 of them blank captures) |
| Ratio | 3,827,499 / 1,766,710 = **2.166, i.e. about 2.17** | |

The ratio is stable against which sales total is used. Dividing by the 1,762,107 that `derived_receipt_fact.sold_pieces` carries (the 852 products with a count, which is what `FOLLOWUP_2026-10-23.md` §3c divides by) gives 2.172. Dividing the stored non-negative `receipt_pieces` (3,865,916) by 1,766,710 gives 2.19.

## Counts that differ between sources (for the manuscript's footnotes)

| Item | Figure | Why |
|---|---|---|
| Products with negative derived receipts, February 2026 | **175 of 852 products, −38,417 pieces** (publish this one; same 852 products as the 3,827,499 net receipts above). Of the 175: 146 had a count on record in both January and February; 29 rest on a February closing stock assumed 0 (in the January count, absent from February's; `closing_flag`), −2,980 pieces. | `derived_receipt_fact` holds one row per product that has a February count (812) plus the 40 products counted in January but absent from February's count, closed at an assumed 0 (Unilever files omit zero rows): 812 + 40 = 852. The per-product file keeps only the 812 in the February count, so it shows 146 and −35,437. 146 is also not "146 of 812": 106 of the 812 had no January count (opening assumed 0) and cannot go negative, so the 146 sit among 706 products with both counts. The Example 2 product is in the 146 and in the 175. Checked read-only 2026-10-24. |
| Sales total used | 1,766,710 (demand view) vs 1,762,107 (`derived_receipt_fact`) vs 1,756,297 (per-product CSV `sold_feb`) | 1,766,710 is every February sales row (779 products). 1,762,107 leaves out the 107 products that sold in February (4,603 pieces) but are in neither the January nor the February count. 1,756,297 further leaves out the 40 closed-at-zero products (5,810 pieces), keeping only products in the February count. 1,766,710 − 4,603 = 1,762,107; 1,762,107 − 5,810 = 1,756,297. |
| Negative February sales | 68 demand rows total −4,534 pieces (26 of them in the per-product file, 29 in `derived_receipt_fact`, −3,676); largest is SKU 64315841 (DOVE S-CON CERAMIDE INTENSE REP 288X12ML), **−1,619** | Reaches every published sales total above, as a net figure (gross positive sales are 1,771,244 against 1,766,710), and it lowers that product's derived receipt: closing − opening + (negative sales). It reaches the 175: 21 of the 29 negative-sales products are negative-balance products; 9 of the 175 would not be negative if negative sales were counted as 0 (166 would), which is the rule the Pareto and class-change figures and the forecast runner already use (a net-negative month is 0); the receipts total would be 3,866,705. The 2.17 ratio would move to 2.19. Not changed: the published figures are as stored; the rule for derived receipts is for Yuan to decide. |
| Opening count date | 3 Feb 2026 | File month 2026-01; not 2 Feb. |
