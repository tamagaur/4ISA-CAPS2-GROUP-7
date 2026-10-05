# Safety-stock source comparison (2026-10-05, read-only)

**Question.** The plan sizes each product's safety stock from how much its monthly **sales** move around. Would
sizing it from how far the **forecast** misses give a different amount of stock, in pesos, per class?

**Answer.** Hardly. On the 174 Unilever products that have both figures, the forecast-error method holds
**₱113,053 less (−1.4%)**: ₱7.90M against ₱8.01M. Class A (as of 2026-02) is 2.8% lower; Class B and C (as of
2026-02) are 3.5–5.8% higher on few products and few months. **The current method stays the default; nothing in the
plan, the database or the code was changed.**

Run by `run_comparison.py` on 2026-10-05 06:10 UTC, one read-only transaction against the live database.

## What was compared

Both methods use the plan's own formula (`scripts/run_lp.py`, `safety_stock_for`):

safety stock = Z × monthly spread ÷ √(average weekdays in a month) × √(review days + lead days)

| Input | Value | Source |
|---|---|---|
| Z | 1.28 (90% service level) | `analytics/params.py` `SERVICE_Z` (SSM) |
| Review + lead days | 5 + 3 business days | `analytics/params.py` `PLACEHOLDERS` (placeholders, not SSM's figures) |
| Minimum months for a spread | 2 | `scripts/run_lp.py` `_sigma_d_for_product` ("need >= 2") |
| Classes | stored ABC run, method `single`, period 2026-02 | `abc_classification` |
| Price per piece | last purchase price (stock file's unit cost per case ÷ pack size), no VAT, **pending SSM confirmation** | `backend/stock_units.py` `last_purchase_price_sql` |

They differ only in what the monthly spread (standard deviation) is taken of:

| Method | Monthly spread of | Months used |
|---|---|---|
| **Current (default)** | the product's sales, in pieces | all its months on file (`Unilever_SKU_Demand_Fact_Real`) |
| Forecast error | forecast minus actual sales, in pieces | the months the default backtest scored it (`mart.accuracy_mart`, "backtest 2023-10..2026-02, Tier A the month before each month") |
| Sales, same months (control) | the product's sales, in pieces | only the backtest's months, to separate the method from the window |

## Check: the current method here equals the stored plan

| Check | Result |
|---|---|
| Classified Unilever products (2026-02, `single`) | 710 |
| Pending plan rows for cycle 2026-03 among them | 73 |
| Their safety stock recomputed here | 73 of 73 |
| Largest difference from the stored `ss_i` | 0.005 piece (stored values are rounded to 2 places) |

## Coverage per class (classes as of 2026-02)

A product is comparable only when it has both spreads. The backtest forecasts a product only in months when it was
Class A the month before, so few Class B and C products have forecast errors at all.

| Class (as of 2026-02) | Products | With current safety stock | Also with forecast errors (comparable) | Median scored months |
|---|---|---|---|---|
| A | 132 | 128 | 111 | 19 |
| B | 194 | 188 | 53 | 7 |
| C | 384 | 364 | 10 | 7 |
| All | 710 | 680 | 174 | 14.5 |

All 174 comparable products have a price. 23 Class C products with a current safety stock have no price and are left
out of every peso figure (never given a default).

## Result: safety stock in pesos, comparable products only

Pesos at last purchase price, pending SSM confirmation.

| Class (as of 2026-02) | Products | Current method | Forecast-error method | Difference | Lower / higher under forecast error |
|---|---|---|---|---|---|
| A | 111 | ₱6,581,013 | ₱6,397,234 | −₱183,779 (−2.8%) | 56 / 55 |
| B | 53 | ₱905,152 | ₱957,621 | +₱52,469 (+5.8%) | 23 / 30 |
| C | 10 | ₱523,496 | ₱541,754 | +₱18,257 (+3.5%) | 6 / 4 |
| **All** | **174** | **₱8,009,662** | **₱7,896,609** | **−₱113,053 (−1.4%)** | 85 / 89 |

In pieces, all classes: 745,937 current against 710,342 forecast-error.

For context, the current method over every priced product in the class (not only the comparable ones):
A ₱7,196,280 (128 products), B ₱1,803,227 (188), C ₱1,563,437 (341), all ₱10,562,943 (657).

## Controls

| Class (as of 2026-02) | Sales spread, same months as the errors | Forecast error against that | Forecast error with the average miss kept in (root mean square) |
|---|---|---|---|
| A | ₱6,432,347 | −0.5% | ₱6,356,196 |
| B | ₱893,472 | +7.2% | ₱988,039 |
| C | ₱479,418 | +13.0% | ₱583,219 |
| All | ₱7,805,237 | +1.2% | ₱7,927,454 |

- Most of Class A's −2.8% is the window, not the method: on the same months the two differ by 0.5%.
- The root-mean-square version divides by the number of months, the spread by one less, so on short histories it can
  come out lower even though it keeps the average miss in.

## Reading

| Point | Evidence |
|---|---|
| The two sources give nearly the same stock | −1.4% overall; products split 85 lower / 89 higher |
| This fits the earlier finding that forecast errors are mostly noise the size of the sales swings | `reports/diagnostics/model_audit_2026-10-03/README.md` |
| Class B and C figures rest on little data | 53 and 10 products, median 7 scored months, all from months when they were Class A |
| No reason here to change the default | the difference is small and inside what the placeholder inputs (review and lead days) would move |

## Limits

- Unilever only. Del Monte has no product-level forecast.
- Forecast errors exist only for months a product was Class A the month before, so the forecast-error method cannot
  cover most Class B and C products today.
- Review and lead days are placeholders; the price is pending SSM confirmation. Both scale the two methods equally,
  so the percentages do not depend on them.
- Stock counts are Ilocos Sur and product sales are La Union (territory match unverified); this compares two sales-based
  figures, so it is not affected, but the peso level is.

## Files

| File | What |
|---|---|
| `run_comparison.py` | the read-only query and the arithmetic; rerun to refresh every figure here |
| `summary_by_class.csv` | every figure in the tables above |
| `checks.csv` | the reproduction check against the stored plan |
| `figures.json` | the same, with the run time and the inputs |
| `local/per_product.csv` | per-product table (git-ignored: per-product prices are never committed) |
