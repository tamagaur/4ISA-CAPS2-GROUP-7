# Chapter 4–5 Draft v2: Corrected Edit List

Against `4ISA_GROUP7_Ch4-5_Draft_v2.pdf` (65 pages). Supersedes `Downloads/CH4-5_EDITS_2026-10-22.md`. Verified 22–23 October 2026 against the live database and the repo at `c70c88d`.

**One rule governs every wording change below.** State a value's basis without waiting language ("pending", "placeholder", "awaiting") and without claiming a confirmation that does not exist. The model sentence is: *"Set from SSM's stock file; SSM has not confirmed it."* Nothing here says anything was approved, ruled on, confirmed or conducted unless it was. No adviser ruling, SSM confirmation or user acceptance testing is on record; the text says so plainly where it matters.

**What changed from the first list**

| First-list item | Now |
|---|---|
| Conventions 1 and 2 | Dropped. Replaced by the rule above. |
| 1 | Re-derived: 389 files / 280.21 MB included 196 synthetic files. Real SSM files are 193 staged. |
| 3, 11, 12 | Rewritten under the rule. The storage-cost derivation was wrong (2% of ₱33.48 is ₱0.67, not ₱0.50). |
| 4 | Whole column replaced, not two cells. |
| 7 | **Retracted objection: item 7 was right.** See below. |
| 8 | Draft sentence is accurate and stays. The calendar factor is applied live and has no sign-off. |
| 9 | Forecast cell is 1,217,634, not "unchanged". |
| 13 | Settled: the −33.6% does not survive. It is removed in four places. |
| 18 | The 83.6 s figure has no source and is dropped. The concurrent-users sentence is restored. |
| 20 | "Has not yet been conducted" stays. |
| 22 | SO3 stays "Partly achieved". SO5 keeps "UAT not yet conducted". |
| 23, 25 | Rewritten under the rule. The tolerance paragraph is corrected. |
| Section F | F2, F3, F7, F12, F13 corrected; F1, F9, F10, F11 refined; all traced or flagged below. |

**Retraction (item 7).** In my review I said the draft's Table 4.2.18 shows 7 Over and 5 Under. That came from a layout-mangled text extraction. Re-read in raw order, the table shows Over for June, July, August, September, November, December, January and February (8) and Under for March, April, May and October (4). The `direction` column is in pieces (`backend/marts.py:1147`, `forecast_pieces > actual_pieces`). Item 7 is correct as first written and needs no further change.

Legend: 🔴 blocking · 🟡 replace · 🔵 transcribe from `docs/CH4-5_EDITS_2026-10-22.md` (Tier B) · 🟣 wording

---

## 🔴 1 · p.2, §4.1.1: Source of Raw Data

The paragraph counts 161 files, 867 worksheets and about 203.8 MB. None of these can be reproduced. They come from an earlier corpus whose folders no longer exist.

Re-derive from `staging/_manifest.json` (built 2026-09-14) and `data/raw`, **counting real SSM files only**. The manifest also stages 196 generated files (16,571 rows); they are not SSM source files and belong in a separate sentence.

| Figure | Draft | Measured |
|---|---|---|
| SSM source files on disk | 161 | **194** (Del Monte 88, Unilever 61, SSIS summary reports 45) |
| Files staged by the manifest | n/a | **193** (one Del Monte file, `…APRIL 1-APRIL 30 2023 SALE RETURN (1).xlsx`, is not staged; reason not checked) |
| Worksheets staged from those files | 867 | **1,090** (Del Monte 284, Unilever 467, SSIS 339) |
| Size | about 203.8 MB | **276.89 MB on disk (264.06 MiB; 276,889,653 bytes); 276.87 MB for the 193 staged** |
| Formats (193 staged real files) | 156 .xlsx, 3 PDF, 1 lock file, 1 .xls | **192 genuine .xlsx and 1 .xls** (the MHTML file `UnileverLaUnionSalesperSKU2023to2026.xls`). "Genuine" = starts with the zip signature and contains `xl/workbook.xml`; all 192 do. On disk (194 files) the count is 193 .xlsx and 1 .xls, because the one unstaged Del Monte file is also .xlsx. No PDF or lock file is in `data/raw`. |
| Del Monte / Unilever split (193 staged) | 99 / 61 | **87 Del Monte / 61 Unilever / 45 SSIS summary reports** (the SSIS folder is Unilever's system; its sheets carry principal "ambiguous" or "unilever"). Counted either way it is 87 / 106 or 87 / 61 / 45; **99 is not reproduced** (the Del Monte folder holds 88 files on disk, 87 staged). Keep "61" only if the sentence is about the Unilever sales folder. |
| Header layouts | 107 | **121 distinct header-row layouts** across the 1,090 real staged sheets (the exact tuple of column labels in each sheet's `columns` field of `staging/_manifest.json`); **120** once case and repeated spaces are ignored. 93 of the 120 are SSIS summary reports; the other families have 10 (inventory sign-off), 8 (sales register), 5 (purchase order), 4 (sales return), 3 (sell-out), 1 (RMR) and 1 (SKU file). "Layout" is defined by the label tuple; a different definition gives a different count, so state the definition or drop the number. The draft's 107 is not reproduced. |
| Generated demonstration files (separate sentence) | n/a | 196 files, 196 sheets, 16,571 rows, staged but never used by a forecast, classification or the order plan |

Keep the qualitative claims: the disguised MHTML file, no prior cleaning, and that no single parsing rule read the whole corpus. Re-read Table 4.1.1 against the same manifest.

Measured by: file sizes on disk and the `src_file` / `row_count` fields of `staging/_manifest.json`.

---

## 🟡 2 · p.7, §4.1.2: staged rows and the rejection claim

Replace "1,991,339 staged rows … with no rejected record" with:

> The Extract stage produced 2,009,490 staged rows from real source files across all document families, with no record rejected at extraction. A further 16,571 rows belong to the labelled demonstration dataset, giving 2,026,061 staged rows in total. Validation found six worksheets whose own total cells disagree with the rows beneath them; the rows were loaded unchanged. The six are Del Monte purchase, sales-register and sales-return workbooks.

Basis: `staging/_manifest.json` (2,026,061 rows, 1,286 sheets, 0 rejected; 2,009,490 excluding `Synthetic Data`; 6 sheets with `checksum_status` = mismatch).
**Cause of each mismatch (now checked, 23 October 2026, by opening the six workbooks).** In every case the sheet's "total" is a formula in row 1 and the fault is in that formula, not in the rows. The check compares that cell with the sum of the sheet's rows; the rows were loaded unchanged.

| # | Workbook / sheet | Cell | What the formula does | Check |
|---|---|---|---|---|
| 1 | 2025 March sales register, Pangasinan | `L1` (Net Amount) | `=SUM(L4:L2083)`: starts at row 4, so the first data row (row 3) is left out | The skipped row is ₱8,224.23; the difference is ₱8,224.23 |
| 2 | November 2023 sales register, Ilocos | `J1` (Net Amount) | `=SUM(J23:J150)`: adds 128 of the 202 rows; rows 3–22 and 151–204 are outside the range | Outside rows total ₱44,679.33 + ₱461,324.63 = ₱506,003.96; the difference is ₱506,003.96 |
| 3 | December 2025 purchases, Pangasinan | `H1` (Untaxed Amount) | `=SUM(H7:H99)`: starts at row 7, leaving out rows 3–6 | Rows 3–6 total ₱2,867,226.84; the difference is ₱2,867,226.84 |
| 4 | December 2025 purchases, Ilocos | `H1` (Untaxed Amount) | `=SUM(H7:H122)`: same, leaving out rows 3–6 | Rows 3–6 total ₱63,905.10; the difference is ₱63,905.10 |
| 5 | February 2024 sales return, Pangasinan | `L1` (Net Amount) | `=SUM(H3:H100)`: the Net Amount total adds column **H, Untaxed Amount**, not column L | Column H sums to ₱143,371.74 = the cell; column L sums to ₱160,576.38 = the value read from the rows |
| 6 | January 2024 sales return, Pangasinan | `L1` (Net Amount) | `=SUM(H3:H100)`: same fault | Column H ₱149,664.37 = the cell; column L ₱167,624.08 = the rows |

Four are a range that stops short at the top or middle (1–4), two are a total pointing at the wrong column (5–6). Each is exact to the centavo, so the rows themselves are consistent with the cause.

**Does any of the six feed a forecast, an accuracy figure or the order plan? No.** Basis, from the code:
- The loader reads the rows, never the summary cell, so none of the six cell values enters any table.
- The three document families are Del Monte's sales register, purchase and sales-return workbooks. The sales register goes to `Sales_Fact`, which the ABC classification deliberately does not read (`analytics/classification/orchestrate_abc.py:10-11`; Del Monte ABC reads `SellOut_Fact`). Forecasting reads `Unilever_SKU_Demand_Fact_Real` (`analytics/forecasting`, `scripts/run_baseline_forecast.py`), the accuracy mart is built from those forecasts, and the order plan (`lp_run` 6) holds 109 Unilever products and no Del Monte product. A grep of `analytics/forecasting`, `analytics/classification`, `analytics/optimization`, `scripts/run_lp.py`, `scripts/run_baseline_forecast.py` and `scripts/accuracy_as_served.py` finds no read of the purchase, sales-return or Sales_Fact tables.
- The purchase and sales-return rows do reach one place: the Del Monte "purchases" and "returns" lines of the dashboard's flow chart (`mart.flow_month`, `analytics/db/migrations/0041_data_marts.sql`, lines 436–456). They enter as the row values, which are correct.

Sentences that can be added to §4.1.2: *"Of the six, four have a total cell whose formula omits some rows and two have a Net Amount total that adds the Untaxed Amount column; in all six the rows were loaded unchanged."* and *"None of the six workbooks feeds a forecast, an accuracy figure or the order plan."*

---

## 🟡🟣 3 · pp.10–11, §4.1.3 and Table 4.1.9: cost and capacity inputs

| Input | Draft | Replace with | Basis (Table 4.1.9, Basis column) |
|---|---|---|---|
| Procurement cost per piece | ₱25.00 | **₱33.48** | Median cost per piece of the 101 planned products in the February 2026 stock count; used only for a product the stock file gives no cost, which is **no product this cycle** (all 109 have a stock-file price). SSM has not confirmed it. |
| Storage cost per piece per month | ₱0.50 (2% of ₱25) | **₱0.50, unchanged** | 2% of the earlier ₱25 default, kept rather than re-derived (2% of ₱33.48 would be ₱0.67). A team choice; SSM has not confirmed it. |
| Warehouse capacity | 3,800,000 pieces | **3,816,842 pieces** | The most stock Unilever's warehouse held in one count (3 February 2025). A floor on true capacity, not a measured limit; it does not bind this cycle. SSM has not confirmed it. |
| Allocation | 103% | **103%, unchanged** | Lowest of the three bands SSM's manager stated (103, 105, 108%); SSM has not said which applies. |

§4.1.3 prose: replace "Three cost inputs are placeholders until SSM supplies its figures: …" with

> Three model inputs are set from SSM's own records, not from SSM's cost accounts: a warehouse capacity of 3,816,842 pieces (the most stock the warehouse held in one count, February 2025), a procurement cost of ₱33.48 per piece for any product the stock file gives no cost (the median of the planned products; no product needed it this cycle), and a storage cost of ₱0.50 per piece per month (2% of the earlier ₱25 default). SSM has not confirmed any of the three, and the plan's quantities would change if its figures differ.

Sources: `analytics/params.py` (`PLACEHOLDERS`), whose own comments give the derivations above.

---

## 🔴 4 · pp.14–15, Table 4.2.4 and the prose beneath

The Year-over-year column is on the all-products basis. The draft's own note says "the same products", so the whole column moves to the matched basis. **Replace the full column**, not two cells:

| Category | Draft | Matched products |
|---|---|---|
| Cooking Aids | +22.1% | **+1.5%** |
| Hair Care | −0.9% | **−9.4%** |
| Fabric Cleaning | −8.3% | **−10.6%** |
| Condiments | +13.5% | **+7.6%** |
| Deodorants & Fragrances | −4.2% | **+4.2%** |
| Fabric Enhancers | −4.5% | **−55.1%** |
| Skin Care | +9.7% | **+11.6%** |
| Oral Care | −6.2% | **−19.6%** |
| Skin Cleansing | +16.2% | **+12.1%** |
| Home & Hygiene | +0.4% | **−3.6%** |
| Other Foods | +25.8% | +25.8% |
| Unclassified | −25.3% | **−23.0%** |
| Mini Meals | +339.6% | +339.6% |
| Scratch Cooking Aids | −100% | **−100.6%** (see below) |
| Dressings | −100% | not in the matched list; recompute |

Source: `docs/MANUSCRIPT_CORRECTIONS_2026-10-22.md` §2 (Unilever net pesos, 2025-03..2026-02 against 2024-03..2025-02; matched = products with a sales row in both years). A matched change of −100.6% is possible when returns exceed sales in the later year; give such a row as "−100% or worse" or drop it. Recompute Dressings; it is not in that table.

Replace the prose "Cooking Aids is the only large category with a significant upward trend (+22.1% on the year) … Fabric Cleaning … (−8.3%)" with:

> On the 24-month Theil-Sen test, Cooking Aids is the only large category with a significant upward trend and Fabric Cleaning the only large one with a significant downward trend. Measured instead as a like-for-like change against the twelve months before, on products present in both years, Cooking Aids is essentially flat (+1.5%) while Fabric Cleaning falls 10.6%. The two columns answer different questions: the trend test uses the full 24-month shape, while the year-over-year column compares only products present in both ranges.

---

## 🟡 5 · p.27, §4.2.2.1.2: candidate count

"a stricter test of 35 candidates" → **36** (36 candidate models in each of three history bins, `reports/experiment_artifacts/cells_all.csv`; `reports/CLAIM_CHECK_2026-10-22.md` row 4). Also p.58 (Table 4.4.2, SO2).

## 🟡 6 · p.29, §4.2.2.3.3: code version

"code version 63542e2" → **`8ddf82d`**, citing `docs/ACCURACY_AS_SERVED.md`. (That document states it was computed from `3cfee40` with uncommitted changes; cite `8ddf82d` as the committed equivalent, per `docs/MANUSCRIPT_CORRECTIONS_2026-10-22.md` row 17.)

## 🔴 7 · p.31: over-forecast month count (unchanged from the first list)

"In 9 of the 12 months the forecast was too high" → **8 of the 12.** Table 4.2.18, read in order, is Over for June, July, August, September, November, December, January, February (8) and Under for March, April, May, October (4). The Direction column is in pieces.

## 🟣 8 · p.28, §4.2.2.1.4: Calendar Adjustment

**No wording change; the draft sentence is accurate.** The factor is applied to the live forecasts (the stored March 2026 forecast rows carry `calendar_factor_on: true`, factor 1.0762, 175 of 189 forecast rows), and `analytics/params.py` records it as approved for build and dry run only, with no adviser sign-off. Keep "this factor has not yet been signed off by the adviser", and keep the sentence that §4.2.2.3.3 shows it did not improve backtest accuracy. Add the measured effect once, in §4.2.2.3.3: the median product error is 40.22% without the factor and 42.56% with it (`docs/ACCURACY_AS_SERVED.md`, 310 products, 4,370 product-months). Add the factor formula here (F7).

---

## 🟡🔵 9 · p.33, Table 4.2.19: Order Plan by Urgency

| Measure | Draft | Replace with |
|---|---|---|
| Rows in cycle | 110 | **109** |
| Ordering more than 0 | 74 | **73** |
| Order (pieces) | 432,774 | **435,988** |
| Safety stock (pieces) | 557,617 | **557,612** |
| Forecast (pieces) | 1,217,633 | **1,217,634** (live 1,217,633.75; the draft's p.28 already says 1,217,634) |
| Critical | 19 | **18** |

Per-urgency rows are in Tier B, B-a of `docs/CH4-5_EDITS_2026-10-22.md` (Critical 18/18/118,644; Urgent 5/5/67,276; Planned 86/50/250,068). Rewrite the prose from them. Add: *"Order quantities are rounded to whole case packs within the allocation ceiling, so every non-zero order is a whole number of packs."*

## 🟡🔵 10 · p.34, Table 4.2.20: Order Plan by Category

Eight categories, not nine (Skin Care came only from a row with no LP run). Transcribe the eight rows from Tier B, B-b. Totals **109 / 73 / 435,988**.

## 🟡🔵🟣 11 · p.34, Table 4.2.21: Order Plan Summary (rename "…and Pending Inputs" to "…and Inputs Used")

| Item | Draft | Replace with |
|---|---|---|
| Products in the plan | 110 (109 pending, 1 accepted) | **109** (all pending; none decided) |
| Ordering more than 0 | 74 | **73** |
| Total order quantity | 431,480 pieces | **435,988 pieces** (whole case packs) |
| Procurement cost | 25.00, placeholder | **33.48, median cost per piece from the stock file; used for no product this cycle; not confirmed by SSM** |
| Storage cost | 0.50, placeholder | **0.50, 2% of the earlier ₱25 default; not confirmed by SSM** |
| Warehouse capacity | 3,800,000, placeholder | **3,816,842, most stock held in one count; not confirmed by SSM** |
| Stock count of 2 March 2026 | 46.6 million, accepted for planning pending SSM | **₱46.6 million, flagged by the system as unusually high; accepted for planning by the team; SSM has not confirmed it** |

Stale rows: 0. Decided rows in the plan: 0 of 109 (Tier B, B-c). The planner-review count is still to transcribe from the live plan.

## 🟡🟣 12 · p.35: the allocation sentence and the section's closing sentence

"about 0.43 million pieces" → **about 0.44 million pieces** (435,988). "About a third of the 1.26 million ceiling" still holds (34.5%). The three category figures come from the regenerated Table 4.2.20.

Replace the closing sentence ("Because the cost inputs are placeholders, the plan is a demonstration of the method …") with:

> The plan is computed on real demand and real stock. Its cost and capacity inputs are set from SSM's stock file and recorded stock levels (Section 4.1.3), not from SSM's cost accounts, and SSM has not confirmed them, so the quantities are a planning estimate that would change with SSM's own figures.

---

## 🔴 13 · p.36, Table 4.2.22 and everywhere "−33.6%" appears

**Settled: `lp_vs_rule_pct` did not compare like with like, and the −33.6% does not survive.**

What it computed: `(rule_total − lp_safety_stock) / rule_total`, i.e. (840,092 − 557,612) / 840,092 = 33.6%. The 840,092 is **the rule's entire three weeks of sales**, the whole stock the rule holds. The code even sets the rule's "safety stock" equal to that whole figure (`rule_safety_stock_units = rule_total`, `backend/routers/policy_comparison.py`). The rule has no separate safety stock, so the plan's safety stock (a buffer) was set against the rule's total stock (buffer plus cycle stock). The like-for-like comparison of the rule's whole stock is the plan's **target stock** (+19.7%), which is the figure the same table carries one row above. Commit `3cfee40` removed the field for this reason.

**How far it reaches in the draft (searched the full PDF text for "33.6"; three hits, plus one conclusion that depends on it):**

| Location | Text | Action |
|---|---|---|
| Table 4.2.22, Safety stock row (p.36) | 557,612 \| 840,092 \| −33.6% | Keep 557,612. Set the rule column and difference to "n/a: the rule has no separate safety stock". |
| §4.2.3.1.4 prose (p.36) | "The safety stock alone is 557,612 pieces, 33.6% less than the rule." | Replace with: "The plan's safety stock is 557,612 pieces; the 3-week rule has no separate safety stock, so it is compared on target stock (above) and on average and peak stock (below)." |
| §4.4.1 (p.57–58) | "it holds 33.6% less safety stock and 22.6% less average stock, but 14.1% more at its peak" | Replace "33.6% less safety stock" with "19.7% more target stock in pieces"; keep "22.6% less average stock (in pesos)" and "14.1% more at its peak". |
| §5.2.4 (Chapter 5, p.63) | "a per-product policy holds less safety stock overall but places it unevenly" | This conclusion rested on −33.6% and has no like-for-like support. Replace with: "…benchmarked against the 3-week rule, showing that a per-product policy holds more stock at its peak (19.7% more target stock in pieces, 14.1% more in pesos) and less on average (22.6% less in pesos), and places it unevenly across products (56 hold less, 53 hold more)." |

**What survives (checked live, 2026-10-22):** target stock 1,005,661 vs 840,092 (+19.7%); average stock ₱7,496,532 vs ₱9,680,196 (−22.6%); peak ₱11,045,937 (+14.1%); 56 / 53; 3.59 weeks at target. Add one caveat for the average: it compares the plan's average with the rule held flat. If SSM's 3 weeks is itself the rule's peak, the rule's average is lower (₱8,066,830) and the plan's average is **7.1% less**, not 22.6% (`/policy-comparison`, `pesos.rule_average_if_three_weeks_is_a_peak`). Prices are the last purchase price per piece from the stock file, which SSM has not confirmed as its purchase cost; say that in place of "(pending SSM confirmation)".

Replace the closing sentence of §4.2.3.1.4 ("The dashboard therefore makes no claim of capital freed until SSM confirms its prices …") with:

> Whether the redistribution frees capital depends on whether SSM's three weeks is an average or a peak, and SSM has not said which; the comparison therefore reports both and makes no claim of capital freed.

---

## 🟡🔵 14 · p.41 §4.2.3.3 and p.42, Table 4.2.23

"1 of 110 rows has been decided" → **0 of 109 rows** (all 109 pending; the one accepted row has no LP run and is not in the plan). Same denominator in the Freshness row (0 stale rows).

Table 4.2.23, one row changes: **Cost inputs**, "Not yet validated: four parameters pending SSM" → "Set from SSM's stock file and recorded stock levels, not confirmed by SSM (Section 4.1.3); supplier ceilings are 103% of last year's sales". **Purchasing team review: no change** ("Part of user acceptance testing", which has not been conducted). The Forecast quality row (109 of 175) is correct.

## 🟡 15 · p.51, §4.3.4.1: Reference Guide

"the 29 terms and figures" → **25 terms**, in five sections (Main-FE `d9ddf0d`, `DataDictionary.jsx`). 30 only if the five section headings are counted.

## 🟡 16 · p.55, Table 4.3.8: Automated Test Results

| Check | Draft | Replace with |
|---|---|---|
| Python test suite | 1,723 passed, 3 failed, 28 skipped (5 min 25 s) | **1,738 passed, 0 failed, 18 skipped (8 min 52 s)**, run 2026-10-22 at `c70c88d` |

Delete the paragraph about the three failing tests and the matching clause on p.61.

## 🟡 17 · p.56, §4.3.6.2: Functional Testing

"21 requests… more than 260 calls" → the saved speed log records **318 requests, 257 returned 200** (21 returned 404, 20 returned 422, 20 returned 400): `reports/diagnostics/speed_baseline_2026-10-04/results/requests_local.jsonl`. **Change the date too:** that log is from **4 October 2026**, not 22 October as the draft says. Neither 21 nor 260 traces to an artifact.

## 🟡🟣 18 · p.56, §4.3.6.3: Performance Testing

Replace "took 64.1 seconds on 4 October 2026 and 53.4 seconds in a later check … Response times on a paid plan and for concurrent users were not measured." with:

> The first response after a sleep took 64.1 seconds on 4 October 2026 (one measurement, after 16 idle minutes); later requests are fast, and ten read routes use a server-side cache. Response times on a paid plan and for concurrent users were not measured.

The 53.4 s has no evidence, and the 83.6 s in the first list has none either; neither is used. Chapter 5's "about one minute" stays (64.1 s, one measurement). Ten cached routes counted from `@cached(` in `backend/routers/`.

## 🟡 19 · p.56, Table 4.3.9: Security Test Results

| Test | Draft | Replace with |
|---|---|---|
| Invalid sign-in tokens | 9 of 9 refused | **42 of 42 refused** (7 kinds of invalid token, 6 endpoints, all HTTP 401) |
| Routes that require sign-in | 50 of 60; the 10 public routes | **49 of 59 require sign-in; 10 are public** |

Add a row: privilege escalation by a non-admin. *A user holding user-management permission without the Admin role cannot create, promote, modify or delete an Admin account.* (Admin-escalation block, commit `c475654`, tested in `tests/backend/test_permissions.py`.)

## 🟣 20 · p.57, §4.3.7: User Acceptance Testing

**No change to the opening.** "User acceptance testing has not yet been conducted" is true and stays, with the 5-point scale and the scenarios. Remove only the drafting note ("Replace this paragraph and fill the tables after testing") when real results exist. §4.3.7's three result tables stay empty until then.

## 🟡 21 · p.57, §4.4.1: Key Analytical Findings

Repeats the Cooking Aids claim from item 4: apply the same two-measure wording. Also repeats the "33.6% less safety stock" claim: see item 13.

## 🟡🟣 22 · p.58, Table 4.4.2: Objectives and Results

| Row | Draft | Replace with |
|---|---|---|
| SO2 | "35 candidates" | **36 candidates** |
| SO3 | "Partly achieved … cost inputs are placeholders; spoilage term replaced by storage cost" | **Status stays "Partly achieved".** Result: "Staged LP with weights 0.45 / 0.35 / 0.20 produces a plan each cycle on real demand and stock, in whole case packs; cost and capacity inputs are set from SSM's records and not confirmed by SSM; spoilage term replaced by storage cost" |
| SO5 | "11 pages … UAT pending" | **10 pages, plus a profile page**; keep "UAT not yet conducted" |

SO5: the side navigation holds ten pages (Table 4.3.2); the profile page sits outside it (and an admin-only card-preview page exists, `App.jsx`: 12 pages in the dashboard layout in all). Main-FE `d9ddf0d`.

## 🟣 23 · p.60, §4.4.4: Limitations and Deviations

**Keep the draft's pending-ruling sentence in substance; it is true.** No adviser ruling exists on the calendar factor or on the monthly-to-daily scaling, and SSM has confirmed none of the four LP inputs. Adjust only for what changed:

> The calendar factor and the scaling of monthly variability to days for safety stock have not been ruled on by the adviser. Four LP inputs (procurement cost, storage cost, warehouse capacity and supplier ceilings) are set from SSM's stock file, its recorded stock levels and the team's choices, and SSM has not confirmed them, so the order plan is a planning estimate on real demand and stock rather than a purchasing figure.

**Add a paragraph on the optimisation tolerance (corrected):**

> The linear program is solved in stages, each held at its optimum before the next. With no tolerance the cycle of March 2026 has no solution: the binding constraint is the hold on the safety-stock stage, not the warehouse or allocation ceilings, and the solver's own round-off puts that stage's optimum just outside its own bound. The hold is therefore relaxed by a relative 1e-7. That value solved the live cycle and five other cycles tried (June, September and November 2025, January and February 2026, on backtest forecasts); a smaller value, 1e-8, was found sufficient for March 2026 only. Its effect is that two products were solved 0.033 and 0.009 pieces below their computed need; case-pack rounding then raised both above need (to 390 and 204 pieces, from 384.80 and 202.52 before rounding).

(Sources: `analytics/optimization/lp.py` `HOLD_SLACK_REL`; `docs/LIMITATIONS.md` item 12; live `lp_recommendation`.)

**Does case-pack rounding absorb the 0.042-piece shortfall? Yes (checked 23 October 2026).** Arithmetic, from a read-only dry run of `scripts/run_lp.py --dry-run` on the live cycle 2026-03 with the committed 1e-7 slack (nothing written; 109 rows, plan total 435,988):

| Product | Pack | Need | Order solved | Short of need | Rounded to | Above need |
|---|---|---|---|---|---|---|
| 64985759 | 6 | 384.83 | 384.80 | 0.03 | 390 (65 packs) | +5.17 |
| 68395711 | 6 | 202.53 | 202.52 | 0.01 | 204 (34 packs) | +1.47 |

Each order lies strictly between two whole packs (384.80 / 6 = 64.13; 202.52 / 6 = 33.75), so rounding up moves it to the next pack, which is more than the shortfall. Rounding up is blocked only by a warehouse or allocation ceiling, and neither binds (about 1.15M and 829,000 pieces of room). Across all 109 rows, the number below need after rounding is **0** (largest shortfall 0.00). The table shows two-decimal values from the dry-run file, so 0.03 and 0.01 are the 0.033 and 0.009 of item 12 rounded; the sum of need less solved order over the 109 rows is 0.04.
**One qualification:** the plan stored in the database (`lp_run` 6, written 22 October at code version 3bd3201) was solved before the slack was lowered to 1e-7, so its pre-rounding orders are the 1e-6 ones (for these two products 384.49 and 202.45). Its post-rounding total is the same 435,988. A shortfall would survive rounding only if the solved order already sat within solver noise of a whole pack; that is not the case for either product here. Every figure that cites "from 384.49 and 202.45" belongs to the stored 1e-6 run; every figure that cites 0.042 belongs to the 1e-7 setting.

**Add a row to Table 4.4.3:** Planned: order quantities in individual pieces. Actual: rounded to whole case packs, inside the warehouse and allocation ceilings. Reason: stock is bought and delivered by the case.

## 🟡 24 · §4.2.3.1.3: add case-pack rounding

After the three solution stages:

> Finally, each product's quantity is rounded to a whole case pack. A product with no recorded pack size, or a pack size of 1, is unchanged. Every other order is raised to the next whole pack unless that would take the warehouse or the principal's allocation over its ceiling, in which case it is lowered to the pack below. Products are tried in descending order of revenue weight, so the result does not depend on input order.

Add formula F11. Source: `analytics/optimization/lp.py` `round_to_case_packs`.

## 🟣 25 · Chapter 5 sweep

| Location | Draft | Replace with |
|---|---|---|
| §5.2.3 | "cannot be treated as final until SSM provides its procurement cost, storage cost, warehouse capacity and supplier ceilings" | "runs on real demand and stock; its cost and capacity inputs are set from SSM's records, not confirmed by SSM, so its quantities are a planning estimate that changes with SSM's figures" |
| §5.2.4 | "holds less safety stock overall" | See item 13. |
| §5.2.5 | acceptance "remains to be confirmed through user acceptance testing" | **No change.** It has not been conducted. |
| §5.3.1 | "Provide the four missing LP inputs…" | **No change.** |
| §5.3.2 | "Obtain the adviser's ruling on the calendar factor and on the safety-stock scaling assumption before relying on either" | **No change.** Add: "and report the measured effect of each as further months are collected." |

Add to §5.2.3: *"The model is solved with a small numerical tolerance on the safety-stock constraint (1e-7), and its quantities are whole case packs."*

---

# Section F: Formulas to add (each traced to code, or flagged)

| # | Where | Formula and corrections | Traced to |
|---|---|---|---|
| F1 | §4.2.2.3.1 | `WAPE = Σ\|A−F\| / Σ\|A\|` over scored product-months (negatives included). Drop the "WAPE and WMAPE are the same" sentence: not in the code. | `analytics/forecasting/diagnostic_metrics.py` `wape` |
| F2 | same | `MASE = mean\|A−F\| / s`, where **s = the mean absolute month-to-month change of the product's real training months before the first test month** (fixed per product). Below 1 beats repeating last month. The first list defined the denominator over the scored months; that was wrong. | `diagnostic_metrics.py` `mase`, `naive_scale` |
| F3 | same | `MAPE = (100/n) × Σ \|A−F\| / A`, over months with **A > 0** (zero and negative months are dropped). **The first list's 459.55% / 29.35% are UNVERIFIED and withdrawn**: no query reproduces them. Measured instead on `mart.accuracy_mart`, 4,370 scored product-months: as served (run 10) pooled WAPE **32.94%**, pooled MAPE **1,054.98%**; calendar-adjusted (run 11) **32.49%** and **1,078.89%**; worst single month 7,091% and 8,292%. Cite those, with "run 10 / run 11". | `diagnostic_metrics.py` `mape`; SQL on `mart.accuracy_mart` |
| F4 | same | `sMAPE = (100/n) × Σ 2\|A−F\| / (\|A\|+\|F\|)`; a month where both are 0 is skipped; bounded 0–200%. | `diagnostic_metrics.py` `smape` |
| F5 | §4.2.2.1.2 | `F(t+1) = (D(t) + D(t−1) + D(t−2)) / 3` | stored `ma_window: 3` in `Forecast_Result.model_params` |
| F6 | same | `F_served = (F_XGBoost + F_MA3) / 2` for the long-history bin. **Boundary confirmed against the code:** long = **24 or more months with a sale** in the history known at forecast time (`LENGTH_V2_SEASONAL = 24`, `analytics/segmentation/bins.py:35`; `length_v2`, `bins.py:43-50`; `bin_at`, `analytics/forecasting/router.py:53-57`). Run on 2, 3, 11, 12, 23, 24, 25 it gives insufficient, short, short, medium, medium, long, long. The count is **months with a sale (quantity > 0)**, not calendar months, so write "24 or more months with sales". Short (3–11) is served MA3, medium (12–23) TSB (`LIVE_MODEL`, `router.py:40`). | `model_params.method = xgb_ma3_avg`, `components`; `bins.py`; `router.py` |
| F7 | §4.2.2.1.4 | **Corrected.** For target month *m*, for each earlier year *y*: `r_y = sales(m, y) / mean(sales of the 3 months before m, y)`. Then `full = exp(mean(ln r_y))` (**geometric mean**, not arithmetic) and `factor = 1 + 0.5 × (full − 1)`. Company-level totals; only months before the target are read. March 2026: 1.0762 from 2 earlier years. | `analytics/forecasting/calendar.py` `calendar_factor`; stored `calendar_factor`, `calendar_years` |
| F8 | §4.2.1.1.6 | `ADI = observed months since the first sale in the window / months with a sale`. Fast: ADI < 1.32 and at least 3 months with a sale, over the last 12 observed months. Non-moving: no sale in the last 6 calendar months. Slow: everything else that sold. 1.32 is the Syntetos-Boylan-Croston cut-off. | `analytics/classification/fsn.py`; `analytics/params.py` |
| F9 | §4.2.1.1.4 | `cumulative share_k = Σ(i≤k) revenue_i / Σ revenue`, products ranked by descending revenue. **A** while ≤ 0.80, **B** while ≤ 0.95, else **C**. | `analytics/classification/abc.py:181-183` |
| F10 | same | `Pareto share = revenue of the top ⌈0.20 × n⌉ products / total`; passes in 0.75–0.85; run only with at least 10 ranked items. | `abc.py` `pareto_check`; `backend/routers/abc.py:163` `PARETO_MIN_ITEMS` |
| F11 | §4.2.3.1.3 | `Q = pack × ⌈q/pack⌉` if the warehouse and allocation ceilings still hold; else `pack × ⌊q/pack⌋`; `Q = q` if pack is unknown or ≤ 1; rows tried in descending revenue weight. | `lp.py` `round_to_case_packs` |
| F12 | §4.2.1.1.1 | **Corrected to pieces over pieces (Unilever), 2026-10-28; the earlier "corrected to pesos" was wrong.** `weeks of cover = stock on hand (pieces) / weekly demand (pieces)`, where weekly demand = average monthly pieces sold over the 12 months ending at the stock count / 4.348 and 4.348 = 365.25 / 12 / 7. Published Table 4.2.1 value 7.06 = 3,800,930 pieces (2026-02 count) / (2,340,123.33 pieces a month / 4.348), sales window 2025-03 to 2026-02. The pesos version (stock at purchase cost over sales at selling price, ₱46,576,778.51 over ₱32,592,761.60 a month) gives 6.21 and is not the published figure: it divides cost by price, so it understates cover by the margin. Del Monte has no pack size, so its cover stays in pesos and its card says so. | `backend/marts.py` `pieces_by_period` (sales) and `stock_pieces_at` (stock), combined in `backend/routers/dashboard.py` `cover_at` and `_weeks_of_cover`; `analytics/params.py` `WEEKS_PER_MONTH`; pinned by `tests/invariants/test_b_cover_agreement.py` |
| F13 | §4.2.2.3.3 | `surplus = max(F−A, 0) × p`, `shortage = max(A−F, 0) × p`, where **p is the product's average realised price per piece** (Σ sales pesos / Σ pieces over its scored months), **not a purchase price**. | `analytics/db/migrations/0043_mart_stock_limited_rule.sql` (`miss_pieces = forecast − actual`; `price_per_piece`) |
| F14 | §4.2.3.1.1 | `Z = 1.28`, the one-sided normal quantile for 90% service. | `analytics/params.py` `SERVICE_Z` |

**Not traced to a query:** only the F3 figures from the first list, now replaced by measured ones. The F6 boundary and the six mismatched workbooks (item 2) were traced on 23 October 2026 (see above).

---

## Running order

1. Item 1 first (re-derive §4.1.1). 2. Items 2–8 and 21. 3. Items 9–14 with `docs/CH4-5_EDITS_2026-10-22.md` (Tier B) open. 4. Items 15–25. 5. Section F last. 6. Final pass: search the draft for "pending", "placeholder", "awaiting", "not yet" and "remains to be" **and confirm each remaining one states something true** (several should stay: UAT, the adviser's rulings, SSM's confirmation). Also search for "33.6" and "110".

## ✅ Verified correct: do not touch

- 109 products passing the MASE gate, median MASE 0.827 (p.28)
- 1,217,634 pieces forecast for March 2026; 1,131,373 before the calendar factor
- Safety stock 557,612 pieces (pp.32, 36)
- Table 4.2.22 except the Safety stock row (item 13)
- "no candidate beat MA3 at p < 0.05" and "equal in accuracy to MA3 within the margin of error, not more accurate" (pp.25–26)
- 19 of 36 Del Monte months missing (pp.22, 57)
- 189 Tier A products, 81.0% of revenue, 80/20 check at 84.4% (p.16)
- Tables 4.1.7, 4.1.8, 4.2.15
- Forecast quality row of Table 4.2.23 (109 of 175)
- Table 4.2.18 as drawn: 8 Over and 4 Under (item 7)
