# Del Monte Demo Data — Generation Sheet

Companion to `DEL_MONTE_DEMO_DATA_SPEC.md`. Open decisions skipped — wipe-and-reload plan, isolation design not load-bearing. This sheet is the thing to build from.

## Pre-check: does real Sell Out data already mix Era A / Era B category strings in one column?

**Yes — confirmed live, in the real Extract-staged output**, not just a spec-time risk. Queried `staging/sell_out/*.parquet`'s real `__col0__` column (the raw category cell) across all 17 real files: **1,293 real rows use Era A fine-grained strings (81 distinct), 52 real rows use Era B coarse strings (5 distinct: FRUITS/CULINARY/BEVERAGE/INNOVATION/DAIRY) — same column, same field, already in the real pipeline's staged output.** Split cleanly by period (fine = 2023-01→2024-02, coarse = 2025-03→2025-12), so it hasn't caused a visible collision yet only because nobody has queried the full 17-month range as one series. It will the moment anyone does a category-level rollup across the whole corpus. Worth a real ticket independent of this demo-data work.

---

## Decision: 2021-2022 backfill (both principals)

**Generating Jan 2021 – Dec 2022 for Real Del Monte families listed below despite zero real Del Monte data existing before Jan 2023, and for Unilever's per-SKU file despite its real data starting Jan 2023. Decision made, not re-argued here.**

**Shared growth assumption, applies to every family/SKU below unless a family section overrides it:** modest linear ramp, **18% cumulative growth over the 24 generated months**, anchored so the last generated month (Dec 2022) sits just under the real Jan 2023 baseline and the first generated month (Jan 2021) sits at 82% of that baseline.

```
growth_factor(month_index) = 0.82 + (month_index / 24) * 0.18
  month_index: Jan 2021 = 0 ... Dec 2022 = 23 (factor ≈ 0.995)
  Jan 2023 (real, unchanged) picks up at factor 1.00, continuous with Dec 2022
generated_value(month) = real_Jan2023_baseline_value * growth_factor(month_index) * noise_factor
```

`noise_factor` = same real per-category/per-family swing bounds already documented in each section below (e.g. Sell Out's 130–530% real range) — apply on top of the ramp so months don't look artificially smooth. **No boom, no collapse, no COVID shape** — this is organic-growth-only, chosen because it's the least invented curve available and stays inside real Del Monte's own observed 2023-2024 volatility once noise is layered on.

**Named assumption:** the real Jan 2023 baseline (or, for Unilever, the real Jan 2023 SKU roster/values) is the only real anchor available pre-2023 — there is no real evidence of what the actual 2021-2022 values or SKU roster were. Using a flat 18%/24mo ramp from that single anchor, rather than inventing a more complex shape, is the deliberate choice.

---

## Sell Out

**Months to generate — 43 total (19 gap-fill + 24 backfill):**
- 2021-2022 backfill (24, new): 2021-01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 2022-01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12
- 2023-2025 gap-fill (19, unchanged from before): 2023-07, 2023-10, 2023-12, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-05, 2025-07, 2025-10, 2025-11

**2021-2022 uses the same Era A 81-category vocabulary as the 2023-2024 generated months — one taxonomy across the entire 2021-2025 generated+real range, no exceptions.** Per-category values for 2021-2022 = the real ranges in the table below × `growth_factor(month_index)` from the shared assumption above.

**Columns, in order:**
| # | Column | Type | Quirks |
|---|---|---|---|
| 1 | category_path (raw: no header text, leftmost column) | string | Leading 5 spaces before every value (`"     /TOM PASTE/BASE"`). No blank allowed — every row must have a category. |
| 2 | Total Without Tax | decimal(2) | Negatives allowed (2 real instances found). Never blank. |
| 3 | Product Quantity | decimal(4+) | Negatives allowed, paired with negative revenue rows. Fractional (real values carry many decimal places — averaged/weighted case quantities). |
| 4 | is_demo | boolean | Always `true` on generated rows. |

**Rows per sheet:** min 5, median 65.5, max 77 (region=ilocos: min 5/median 64/max 69; region=pangasinan: min 65/median 71/max 75 — use pangasinan's real range for generated months, since the abbreviated `PANG_SELL OUT` sheets from Nov 2023 onward that under-count are a real tagging bug, not a real volume drop, see spec §1.1).

**3 real example rows (Pangasinan, April 2023, verbatim formatting):**
```
     /TOM PASTE/BASE                208629.6    158.3333
     /FILIPINO TOMATO SAUCE/BASE    67520.54    93.70833
     /ORIGINAL TOMATO SAUCE/BASE    552931.8    541.5417
```

### Category list — Era A only, 81 categories, one vocabulary

**Chosen because:** Era A is the only real taxonomy with enough distinct categories to produce a genuine Pareto spread (81 real names vs. Era B's 4-5) and to fill every requested story role without reuse. **Era B is not used anywhere below — no mixing.**

Full 81, ranked by real total revenue (Jan2023–Feb2024, both regions, ₱77.00M grand total), with real net_amount range / real quantity range / real implied unit price:

| # | category_path | net_amount range (₱) | quantity range | unit price (₱) | months present |
|---|---|---|---|---|---|
| 1 | /TIDBITS/BASE | 778,693 – 1,501,233 | 493.5 – 901.6 | 1,583 | 11/11 |
| 2 | /SWEET SPAG SAUCE/PROMO | 13,252 – 4,390,411 | 13.9 – 5,021.5 | 888 | 11/11 |
| 3 | /ORIGINAL TOMATO SAUCE/BASE | 528,511 – 987,271 | 531.1 – 983.4 | 1,020 | 11/11 |
| 4 | /TOTAL 100% JUICES/ACE - BASE REGULAR | 522,756 – 953,641 | 857.0 – 1,597.8 | 605 | 11/11 |
| 5 | /TODAY'S/BASE | 255,052 – 1,009,557 | 188.8 – 721.0 | 1,384 | 11/11 |
| 6 | /TOM PASTE/BASE | 155,261 – 441,952 | 102.4 – 286.7 | 1,443 | 11/11 |
| 7 | /KETCHUPS/OTHER SAUCES - BASE | 137,971 – 284,795 | 133.5 – 275.8 | 1,061 | 11/11 |
| 8 | /TOM SAUCE/ORIGINAL TOMATO SAUCE - BASE REGULAR | 143,849 – 290,189 | 160.1 – 321.4 | 917 | 11/11 |
| 9 | /ACE/BASE | 98,974 – 424,516 | 100.3 – 614.4 | 903 | 11/11 |
| 10 | /CRUSHED/BASE | 81,347 – 218,035 | 88.5 – 211.8 | 1,052 | 11/11 |
| 11 | /ORIGINAL BLEND/BASE | 75,930 – 207,204 | 230.1 – 553.7 | 333 | 11/11 |
| 12 | /CHUNKS/BASE | 70,424 – 134,045 | 54.6 – 138.0 | 1,087 | 11/11 |
| 13 | /SLICED/BASE | 56,568 – 165,941 | 48.6 – 104.9 | 1,249 | 11/11 |
| 14 | /TOTAL 100% JUICES/FIBER - BASE REGULAR | 32,724 – 129,549 | 49.7 – 196.5 | 664 | 11/11 |
| 15 | /TOTAL 100% JUICES/FIBER - PROMO REGULAR | 31,174 – 177,557 | 50.5 – 294.0 | 613 | 10/11 |
| 16 | /OTHER SAUCES/NPI | 55,483 – 108,694 | 237.0 – 464.0 | 237 | 11/11 |
| 17 | /TOTAL 100% JUICES/HEARTSMART - BASE REGULAR | 43,915 – 120,873 | 59.4 – 184.9 | 664 | 11/11 |
| 18 | /TETRA/BASE | 11,801 – 171,615 | 12.8 – 197.3 | 883 | 11/11 |
| 19 | /STANDARD GRADE SOY SOUCE/BASE | 27,088 – 131,548 | 13.4 – 52.5 | 2,431 | 11/11 |
| 20 | /TOTAL 100% JUICES/HEARTSMART - PROMO REGULAR | 35,899 – 150,342 | 57.8 – 249.0 | 613 | 10/11 |
| 21 | /FILIPINO SPAG SAUCE/PROMO | 3,841 – 151,860 | 4.0 – 163.6 | 935 | 11/11 |
| 22 | /SPAG SAUCE/FILIPINO SPAG SAUCE - BASE | 23,913 – 102,021 | 26.3 – 111.4 | 930 | 11/11 |
| 23 | /MACARONI/BASE | 14,766 – 155,150 | 13.3 – 117.6 | 1,146 | 11/11 |
| 24 | /GRO/FS/DAIRY | 32,417 – 85,336 | 42.0 – 92.4 | 844 | 11/11 |
| 25 | /FILIPINO TOMATO SAUCE/BASE | 24,894 – 103,830 | 41.7 – 156.3 | 667 | 11/11 |
| 26 | /FIESTA/BASE | 3,231 – 114,559 | 1.0 – 83.3 | 1,414 | 11/11 |
| 27 | /TOM SAUCE/FILIPINO TOMATO SAUCE - BASE REGULAR | 26,884 – 75,199 | 33.3 – 94.2 | 819 | 11/11 |
| 28 | /ACE/NPI | 21,514 – 76,552 | 22.7 – 81.9 | 945 | 11/11 |
| 29 | /RECIPE MIX/BASE | 19,018 – 100,507 | 23.2 – 121.7 | 834 | 11/11 |
| 30 | /PASTA/SPAGHETTI PASTA - BASE | 5,373 – 105,403 | 4.5 – 89.8 | 1,215 | 11/11 |
| 31 | /MR MILK/NPI | 11,227 – 49,949 | 16.9 – 64.6 | 721 | 11/11 |
| 32 | /SPAG SAUCE/ITALIAN SPAG SAUCE - BASE REGULAR | 8,505 – 72,701 | 8.7 – 74.8 | 985 | 11/11 |
| 33 | /SPAGHETTI PASTA/BASE | 362 – 65,879 | 0.8 – 36.0 | 1,748 | 11/11 |
| 34 | /VINEGAR/BASE | 12,680 – 42,711 | 12.2 – 40.2 | 1,052 | 11/11 |
| 35 | /FIBER/NPI | 16,174 – 47,430 | 16.2 – 42.2 | 1,043 | 11/11 |
| 36 | /HEARTSMART/NPI | 7,874 – 45,165 | 7.0 – 40.8 | 1,124 | 11/11 |
| 37 | /ACE/PROMO | 1,012 – 187,684 | 1.8 – 345.0 | 547 | 7/11 |
| 38 | /SPAG SAUCE/SWEET SPAG SAUCE - BASE REGULAR (tab variant) | 60,069 – 77,676 | 55.0 – 80.4 | 1,002 | 4/11 |
| 39 | /SPAG SAUCE/SWEET SPAG SAUCE - BASE REGULAR | 24,668 – 51,567 | 25.3 – 51.9 | 974 | 7/11 |
| 40 | /SPAG SAUCE/GOURMET SPAG SAUCE - BASE REGULAR | 10,629 – 32,355 | 11.5 – 34.6 | 946 | 11/11 |
| 41 | /DISPENSER JUICE/DISPENSER JUICE | 432 – 83,013 | 1.0 – 216.0 | 385 | 5/11 |
| 42 | /TIPCO/BASE | 13,031 – 33,002 | 9.7 – 24.7 | 1,343 | 11/11 |
| 43 | /SPAG SAUCE/FILIPINO SPAG SAUCE | 102,793 – 108,713 | 105.0 – 110.0 | 984 | 2/11 |
| 44 | /SWEET SPAG SAUCE/BASE | 6,753 – 60,623 | 5.0 – 48.3 | 1,264 | 11/11 |
| 45 | /TERIYAKI MARINADE/BASE | 4,719 – 48,163 | 3.0 – 22.5 | 1,788 | 11/11 |
| 46 | /DISPENSER JUICE/DISPENSER JUICE - BASE REGULAR | 1,057 – 29,896 | 1.0 – 30.0 | 1,046 | 11/11 |
| 47 | /SWEET BLEND/BASE | 6,275 – 34,957 | 7.8 – 41.3 | 819 | 11/11 |
| 48 | /FILIPINO SPAG SAUCE/BASE | −1,297 – 47,905 | −1.1 – 36.6 | 1,261 | 11/11 |
| 49 | /CHUNKS/NPI | 4,073 – 21,430 | 7.4 – 35.4 | 554 | 11/11 |
| 50 | /TOTAL 100% JUICES/BONESMART - BASE REGULAR | 5,213 – 17,493 | 8.2 – 28.0 | 631 | 11/11 |
| 51 | /BEVERAGE/READY-TO-DRINK | 3,451 – 17,154 | 4.4 – 26.1 | 709 | 11/11 |
| 52 | /SWEET SPICY/BASE | 5,390 – 20,996 | 5.7 – 25.2 | 851 | 11/11 |
| 53 | /GOURMET SPAG SAUCE/BASE | 586 – 27,836 | 0.4 – 22.0 | 1,293 | 11/11 |
| 54 | /SWEET SPICY/NPI | 2,422 – 18,403 | 2.0 – 17.0 | 1,078 | 11/11 |
| 55 | /CANNED/BASE | −77 – 43,380 | −0.1 – 42.9 | 933 | 11/11 |
| 56 | /SPAG SAUCE/SWEET SPAG SAUCE - PROMO REGULAR | −627 – 58,800 | −1.0 – 77.4 | 777 | 10/11 |
| 57 | /FIBER/BASE | −2,649 – 35,856 | −2.5 – 51.3 | 884 | 11/11 |
| 58 | /ITALIAN SPAG SAUCE/BASE | 1,459 – 12,394 | 1.4 – 12.2 | 1,231 | 11/11 |
| 59 | /OTHER SOY SOUCE/BASE | 994 – 19,931 | 0.4 – 7.2 | 2,619 | 10/11 |
| 60 | /SPAG SAUCE/GOURMET SPAG SAUCE - PROMO REGULAR | 248 – 42,879 | 0.2 – 43.0 | 997 | 9/11 |
| 61 | /TOTAL 100% JUICES/ACE - PROMO CANNED | 42,847 (single month) | 79.0 | 542 | 1/11 |
| 62 | /HEARTSMART/PROMO | −151 – 24,290 | −0.2 – 39.5 | 613 | 4/11 |
| 63 | /HEARTSMART/BASE | −21 – 31,583 | −0.0 – 49.0 | 651 | 4/11 |
| 64 | /ORIGINAL TOMATO SAUCE/PROMO | 9,779 – 19,557 | 15.0 – 30.0 | 652 | 2/11 |
| 65 | /BISCUIT AND WAFERS/CREAM FILLED | 948 – 9,257 | 1.3 – 13.1 | 720 | 7/11 |
| 66 | /MARINADE/BASE | −54 – 20,990 | −0.1 – 33.5 | 629 | 10/11 |
| 67 | /CHICKEN COMPLIMENTS/BASE | 105 – 9,452 | 0.2 – 16.4 | 585 | 11/11 |
| 68 | /FANCY GRADE SOY SOUCE/BASE | 308 – 7,119 | 0.1 – 2.0 | 3,610 | 4/11 |
| 69 | /OLIVE OIL/NPI | 820 – 4,027 | 0.2 – 1.2 | 3,516 | 6/11 |
| 70 | /FIT N RIGHT/FNR 330 ML | 1,477 – 3,939 | 2.4 – 5.9 | 607 | 4/11 |
| 71 | /BANANA/BASE | 73 – 2,827 | 0.1 – 3.3 | 861 | 11/11 |
| 72 | /PIZZA SAUCE/BASE | 631 – 1,394 | 1.0 – 2.0 | 653 | 4/11 |
| 73 | /FIBER/PROMO | 3,601 (single month) | 6.0 | 600 | 1/11 |
| 74 | /CULINARY/KIKKOMAN | 175 – 1,339 | 0.4 – 3.1 | 433 | 5/11 |
| 75 | /DISPENSER JUICE/BASE | −529 – 2,643 | −0.5 – 2.5 | 951 | 3/11 |
| 76 | /FIT N RIGHT/FNR 1L | 89 – 778 | 0.2 – 1.1 | 709 | 5/11 |
| 77 | /BONESMART/BASE | −29 – 1,315 | −0.0 – 2.1 | 630 | 2/11 |
| 78 | /SPAG SAUCE/FILIPINO SPAG SAUCE - PROMO | 344 – 551 | 0.4 – 0.7 | 827 | 2/11 |
| 79 | /OYSTER SAUCE/BASE | 266 (single month) | 0.3 | 798 | 1/11 |
| 80 | /GOURMET SPAG SAUCE/PROMO | −121 (single month) | −0.1 | 966 | 1/11 |
| 81 | /MIXED FRUITS/TODAY'S | −841 (single month) | −1.0 | 841 | 1/11 |

**Plus:** blank/unlabeled rows (`False`, `False (2)`…`False (12)`) — real, keep, don't name them. Real total across these: ~₱13.4M pooled (largest single blank bucket alone is 5.47% of era revenue) — generate 6–12 such rows per sheet, matching real per-sheet counts.

### Category role assignment

| Role | category_path | Real evidence | Dashboard panel | Narrative |
|---|---|---|---|---|
| **Trending up** | `/TODAY'S/BASE` (#5, 5.7% share) | Real Jan23→Nov23 rise 255K→1,010K (+296%) | Monthly trend line (visible upward slope, high enough revenue to read clearly); Reorder Alerts | "Demand grew, the current stock rule leaves us short" |
| **Trending up** | `/STANDARD GRADE SOY SOUCE/BASE` (#19) | Real rise 52K(Jan23)→132K(Jan24), +154% | Monthly trend line (secondary riser); Reorder Alerts | Same, smaller scale — shows the pattern isn't a one-off |
| **Trending down** | `/TOTAL 100% JUICES/ACE - BASE REGULAR` (#4, 8.7% share) | Real decline from 954K peak (Mar23) to 523-527K (Jan/Feb24) | Monthly trend line (big-revenue category visibly falling); Inventory/KPI "capital tied up" card | "Still holding three weeks of this, trapped capital" — high-visibility because it's a top-5 category |
| **Trending down** | `/ACE/BASE` (#9) | Real decline 425K(Jan23)→~100-167K(late) | Monthly trend line; Reorder Alerts (flag: reduce) | Same story, second example |
| **Trending down** | `/TETRA/BASE` (#18) | Real collapse from 172K (Sept23 peak) to 12-14K (Jan/Feb24) | Monthly trend line (sharpest visible drop) | Sharpest "trapped capital" visual |
| **High-variance** | `/SWEET SPAG SAUCE/PROMO` (#2, 10.9% share) | Real 526% swing — near-zero most months, real ₱4.39M spike Jan24 | ABC donut (Class A, flagged distinct from stable Class A peers); Reorder Alerts (higher safety stock, not lower) | "Unpredictable, needs more safety stock, not less" — chosen because it's the 2nd-biggest revenue category, so the volatility is impossible to miss on the dashboard |
| **Steady Class C** | `/VINEGAR/BASE`, `/SPAG SAUCE/GOURMET SPAG SAUCE - BASE REGULAR`, `/CHUNKS/NPI`, `/SWEET SPICY/BASE`, `/BANANA/BASE` | All real, 11/11 real months present, real swing under ~200%, all under 0.35% revenue share individually | ABC donut (Class C wedge); Reorder Alerts (flag: no reorder needed / reduce) | "Class C, we are overstocking this for no reason" |

**KPI cards, suggested real-grounded figures:** total Sell Out revenue (sum of the table above, ₱77.00M/11mo real baseline to extrapolate from), count of Class A/B/C SKUs from the table, count of "reorder-critical" flagged categories (the 2 trending-up), count of "overstocked" flagged categories (the 3 trending-down).

**Bridging the 2024 gap:** per spec §2.5 — generate Mar–Dec 2024 in Era-A vocabulary (not the coarse one) so the 7 role-assigned categories above stay continuous through the gap; only the 2025 real months (already real, Era B) sit outside this category set, disclosed separately, not forced into the narrative (see spec §2.5 for the rejected alternative and why).

**Constraint respected:** no generated slope exceeds `/TODAY'S/BASE`'s real +296% (the steepest real gradual rise found); no generated swing exceeds `/SWEET SPAG SAUCE/PROMO`'s real 526%; no COVID-shaped shock anywhere — Del Monte's real range starts 2023, post-COVID, only real growth/decline/flat patterns above.

---

## Sales Register

**Months to generate — 40 total (16 gap-fill + 24 backfill):**
- 2021-2022 backfill (24, new): 2021-01 through 2021-12, 2022-01 through 2022-12
- 2023-2025 gap-fill (16, unchanged): 2023-07, 2023-10, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-05, 2025-07

**2021-2022 values** = the real Net Amount median (₱2,594.80) and range (₱17.29–4,043,777.20) × `growth_factor(month_index)`, same Discount Rate/Branch Code/day-of-week rules as documented above, unchanged.

**Columns, in order:**
| # | Column | Type | Quirks |
|---|---|---|---|
| 1 | Invoice Date | date | Mon–Sat only, never Sunday. Sat = ~12.5% of volume, not token. |
| 2 | Salesman | string | Real names, e.g. "CARLON DAHILIG" — reuse real salesman names already in the corpus, don't invent new ones. |
| 3 | Town Display | string | Real Pangasinan/Ilocos town names. |
| 4 | Branch Code | string | Format `L12E-######` / `L12F-######` (letter-prefixed, 6 digits) — not zero-padded numeric. |
| 5 | Customer Name | string | Blank not allowed. |
| 6 | Invoice Num | string | Format `INV/YYYY/####`. |
| 7 | REFNBR | string | Format `DMP######` / `DMIS######` / `TDM######` — mixed prefixes, real. |
| 8 | Untaxed Amount | decimal(2) | No negatives found. |
| 9 | Discount Rate | string (not numeric) | Closed real set: `Public Pricelist` (83%), `Less 2%`, `LESS 4%`, `LESS 3%`, `LESS 2%`, `LESS 4% LESS 1%`, `LESS 4% LESS 2%`, `LESS 4% LESS 4%`, `Less 3% (PHP)`. |
| 10 | Discount Amount | decimal(2) | Often 0.00, never blank. |
| 11 | Tax | decimal(2) | |
| 12 | Net Amount | decimal(2) | Range 17.29 – 4,043,777.20, median 2,594.80. No negatives. |
| 13 | Balance | decimal(2) | Usually equals Net Amount (unpaid) or 0 (paid). |
| 14 | Posted | string | `Yes` / `No`. |
| 15 | is_demo | boolean | Always `true`. |

**Rows per sheet:** overall min 12, median 41, max 850. Ilocos: min 12/median 30.5/max 405. Pangasinan: min 19/median 45/max 850.

**3 real example rows (Ilocos, April 2025, verbatim formatting):**
```
2025-04-30  ADMIN SALES      LAOAG CITY (Capital)  L12E-000624  BUNSO CONSUMER GOODS WHOLESALING       INV/2025/1650  ODM0028805    370378.52  LESS 4%            15432.44  44445.42  414823.94  414823.94  No
2025-04-30  CARLON DAHILIG   BACARRA                L12E-000816  NICOLE'S WINE CONVENIENCE STORE        INV/2025/1649  DMIS0064406     1302.72  Public Pricelist        0.00    156.33    1459.05    1459.05  No
2025-04-30  CARLON DAHILIG   BACARRA                L12E-000773  PRINCESS DREAM CONVENIENCE STORE       INV/2025/1648  DMIS0064405     4429.72  Public Pricelist        0.00    531.57    4961.29    4961.29  No
```

---

## Purchase Order

**Months to generate — 49 total (25 gap-fill + 24 backfill):**
- 2021-2022 backfill (24, new): 2021-01 through 2021-12, 2022-01 through 2022-12
- 2023-2025 gap-fill (25, unchanged): 2023-01, 2023-02, 2023-03, 2023-04, 2023-05, 2023-06, 2023-07, 2023-08, 2023-10, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-05, 2025-07, 2025-10, 2025-11

**2021-2022 values** = real Net Amount median (₱102,791.73) × `growth_factor(month_index)`, flat-with-noise as already specified (this family has too thin a real base — 11 real months, no two consecutive before 2024 — to support a directional trend even under the shared ramp; apply the ramp to the median anchor only, not a slope on top of it).

**Columns, in order:** identical to Sales Register (14 columns), same names, same order, plus `is_demo`. **Do not add `units_received`** — not a real column anywhere in this family.

**Format difference from Sales Register:** `Customer Name` is almost always `DMPI` (Del Monte Philippines Inc. — the manufacturer, since this is what SSM buys, not sells); `Invoice Num` format is `BILL/YYYY/####` (not `INV/…`); `REFNBR` format is `PO#####` (not `DMP…`); `Town Display` is real-quirk `False` (literal boolean-as-text) on some real rows — reproduce this quirk, don't "fix" it if replicating edge cases.

**Rows per sheet:** overall min 7, median 23, max 50. Ilocos: min 7/median 16/max 27. Pangasinan: min 18/median 30.5/max 50.

**3 real example rows (verbatim formatting, Feb 2024):**
```
2024-01-31  PANGASINAN SITE  False  96  DMPI  BILL/2024/0026  PO01731   34187.10  Public Pricelist   0.00   4102.45    38289.55   38289.55  No
2024-01-29  PANGASINAN SITE  False  96  DMPI  BILL/2024/0025  PO01730  301531.50  Public Pricelist   0.00  36183.78   337715.30  337715.30  No
2024-01-29  PANGASINAN SITE  False  96  DMPI  BILL/2024/0024  PO01726  402042.00  Public Pricelist   0.00  48245.04   450287.00  450287.00  No
```

**Given only 11 real months as a base and no two consecutive real months before 2024**, generate this family flat-with-noise around the real median (₱102,791.73), not a trending series — insufficient real evidence for a trend shape here.

---

## Sales Return

**Blocker, state before generating: no Extract driver exists for this family yet — flag to whoever owns it before investing here.**

**Months to generate — 42 total (18 gap-fill + 24 backfill):**
- 2021-2022 backfill (24, new): 2021-01 through 2021-12, 2022-01 through 2022-12 — use the **2023-era column shape** (13 columns, no `Return Type`), since the 2025-era GS/BO split didn't exist yet.
- 2023-2025 gap-fill (18, unchanged): 2023-07, 2023-10, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-05, 2025-07, 2025-10, 2025-11

**2021-2022 values** = real Net Amount range (0–233,658.68) × `growth_factor(month_index)`, same 13-column shape shown below.

**Columns, in order — 2023/2024 shape (use for 2023–2024 generated months):**
| # | Column | Type | Quirks |
|---|---|---|---|
| 1 | Invoice Date | date | |
| 2 | Invoice Num | string | `INV/YYYY/####` |
| 3 | REFNBR | string | |
| 4 | Customer Name | string | |
| 5 | Salesman | string | |
| 6 | Untaxed Amount | decimal(2) | |
| 7 | Discount Rate | string | Same closed set as Sales Register |
| 8 | Discount Amount | decimal(2) | |
| 9 | Tax | decimal(2) | |
| 10 | Net Amount | decimal(2) | Range 0 – 233,658.68. Zero allowed, no negatives found. |
| 11 | Balance | decimal(2) | |
| 12 | Posted | string | `Yes`/`No` |
| 13 | Return Slip # | string | May be blank |
| 14 | is_demo | boolean | Always `true` |

**Columns, in order — 2025 shape (use for 2025 generated months):** all 14 above, plus `Return Type` (`GS` or `BO`) at the end — 15 columns total, sheets split by region **and** by GS/BO (4 sheets per file instead of 2).

**Rows per sheet:** min 14, median 45, max 573.

**3 real example rows (2023-era shape, Ilocos, April 2023):**
```
2023-04-27  INV/2023/0781  DM004453     MAPPLES AND MUMBLES BAKERY   GHIMBOY TAAN   255.32   Public Pricelist   0.00   30.64   ...
2023-04-27  INV/2023/0780  DMIS005071   FOOD CARTEL (LAOAG)          GHIMBOY TAAN  1245.00   Public Pricelist   0.00  149.40   ...
2023-04-13  INV/2023/0689  DMIS009222   24/7 FARINA'S CONVENIENCE STORE  GHIMBOY TAAN  770.36  Public Pricelist  0.00  92.44   ...
```

---

## Inventory Sign Off

**Months to generate — 43 total (19 gap-fill + 24 backfill):**
- 2021-2022 backfill (24, new): 2021-01 through 2021-12, 2022-01 through 2022-12
- 2023-2025 gap-fill (19, unchanged): 2023-07, 2023-10, 2023-11, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-05, 2025-07, 2025-10, 2025-11

**2021-2022 values** = real Quantity/PCS ranges × `growth_factor(month_index)`, same combined `__col0__` SKU+description string format, same real-negative-allowed rule.

**Columns, in order:**
| # | Column | Type | Quirks |
|---|---|---|---|
| 1 | __col0__ (SKU code + description, one combined cell, no header text) | string | Format `"<9-char alphanumeric code> <free-text description>"`, e.g. `"9DBL58403 DM 100% PA Juice w/ Vit ACE 202 6-Pack"`. Not two fields — one string. |
| 2 | Quantity | decimal | Range −137.33 – 18,340.82. **Negatives real** (adjustments), don't clamp. |
| 3 | CAS | integer | |
| 4 | PCS | integer | Range −18 – 199,988. Negatives real. |
| 5 | PKG | decimal | May be blank (`NaN` in real data). |
| 6 | is_demo | boolean | Always `true` |

**Note:** a real 3rd header shape exists (named columns `PRODUCT/ SKU CODE`, `DESCRIPTION`, `ITEM CODE`, `ITEM DESCRIPTION`, `CATEGORY` instead of the combined `__col0__`) in some real 2025 files, and the column map doesn't cover it yet (spec §1.4). Generate using the combined `__col0__` shape above — it's the one the pipeline currently handles.

**Rows per sheet:** overall min 121, median 158, max 238. Ilocos: min 131/median 148/max 201. Pangasinan: min 121/median 159.5/max 224.

**3 real example rows (verbatim formatting):**
```
9DBL58403 DM 100% PA Juice w/ Vit ACE 202 6-Pack     10466.39   9536900.00   9536900.00   10681328.00   10394   1846   NaN
9DBL58404 DM Fiber Enriched 100% PJ 202 6Pck            231.50    133855.60    133855.60     149918.30     231      2    4.0
9DBL58405 DM Heart Smart 100% PJ 202 6Pack              115.00     73537.90     73537.90      82362.45     115      0    4.0
```
*(columns shown: description, Quantity, Cost, Valuation, Valuation with VAT, CAS, PCS, PKG — only `__col0__`/Quantity/CAS/PCS/PKG are pipeline-consumed per the table above; Cost/Valuation columns shown here only because they're in the same real row, not required in generated output)*

---

## RMR GS & BO — nothing to generate

Real coverage (2025-10, 2025-11) is already 100% of this family's real existence window — it's a Daily-Report-convention file that didn't exist before Oct 2025. Backfilling earlier months would invent a file convention Del Monte didn't use yet (see spec §1.6). **0 months, 0 rows, skip.**

---

## Unilever SSIS family — generate nothing, real data only, unchanged

Real Unilever SSIS range: Jan 2021 – Mar 2026, fully real, covers COVID. No generation — instruction #1 does not name this family, and it has no gap.

## Unilever per-SKU (`Unilever_SKU_Demand_Fact`) — 24 months generated, 2021-01 to 2022-12

**Real per-SKU data starts Jan 2023** (`UnileverLaUnionSalesperSKU2023to2026.xls`, 24,906 real rows, 38 real months, 1,807 distinct real SKUs across the full real range). Generating Jan 2021–Dec 2022 here specifically, per instruction #4 — this is the one exception to "Unilever: do not touch" from the original spec, scoped narrowly to this one file/fact.

**Columns, in order** (pipeline-consumed, per `config/column_maps/unilever_sku.yaml`):
| # | Column (raw header) | Type | Quirks |
|---|---|---|---|
| 1 | `Calendar\r\n  Month` | string | Raw format `MM.YYYY` (e.g. `"01.2021"`), NOT `YYYY-MM` — real quirk, `transform.reformat_calendar_month()` converts it downstream, generate in the raw `MM.YYYY` shape. |
| 2 | `Product` (real header text, actual content = SKU code, not a product name — real mismatch, don't fix) | string | Numeric-looking code, e.g. `"20292808"`. |
| 3 | `__col2__` (no real header text) | string | Brand + description, embedded `\r\n`, e.g. `"MASTER\r\n  CLEANSER OIL CONTROL 144X70ML"`. |
| 4 | `Pack Size` | integer (as text) | Real values are small integers: 4, 6, 12, 16, 24, 36, 48, 50, 72, 96, 108, 144, 288, 360, 576. |
| 5 | `Sale Quantity in\r\n  Aggr.CS` | decimal | QC cross-check field only, not the value of record. |
| 6 | `Sale Quantity in\r\n  Aggr.PC` | decimal | **This is the real quantity_sold source** (DEC-11) — comma-formatted in real files (e.g. `"1,234.00"`), generate the same way. |
| 7 | `GSV` | decimal | Comma-formatted text in real files, negatives real. |
| 8 | `Total Sales Amt\r\n  Inc. Tax` | decimal | Comma-formatted text, negatives real. |
| 9 | is_demo | boolean | Always `true`. |

**Real Jan 2023 anchor (earliest real month — the backfill basis):** 593 real rows (one row per active SKU that month). Real `Sale Quantity in Aggr.PC` range: −111 to 192,242 pieces, median 172.5. Real `GSV` range: −17,364.98 to 1,013,216.92, median 12,501.24. Real `Total Sales Amt Inc. Tax` range: −19,448.78 to 1,112,113.84, median 13,707.70.

**SKU roster for 2021-2022:** reuse the **real Jan 2023 593-SKU roster** verbatim (same `Product` codes, same `__col2__` descriptions, same `Pack Size`) for every one of the 24 generated months — do not invent new SKU codes, do not shrink or grow the roster month to month. **Named assumption:** there is no real evidence of which SKUs actually existed in 2021-2022 (some real Jan-2023 SKUs may be post-2021 launches, some 2021-era SKUs may have been discontinued by 2023) — holding the roster constant is the least-invented option available, not a claim that the real 2021 roster was identical.

**Per-row generated value** = real Jan 2023 value for that SKU × `growth_factor(month_index)` × noise (use a per-SKU noise band of ±15-20%, since real per-SKU month-to-month variation at this grain is tighter than Del Monte's category-level swings — no real per-SKU CV was computed for this exception, so this is a stated, conservative estimate, not a derived one).

**Rows per generated month:** 593 (matching the real Jan 2023 anchor exactly, per the fixed-roster assumption above) — real per-month counts elsewhere in the corpus range 560-779, so 593 sits inside the real observed band.

**3 real example rows (Jan 2023, the anchor month — generate 2021-2022 rows in this exact shape, values scaled by growth_factor):**
```
01.2023  20292808  MASTER\r\n  CLEANSER OIL CONTROL 144X70ML  144   1.08     154.0     6619.86     7334.33
01.2023  20292809  MASTER\r\n  CLEANSER OIL CONTROL 72X135ML   72   1.66     119.0     7755.10     8567.75
01.2023  20292810  MASTER\r\n  CLEANSER OIL CONTROL 72X225ML   72   0.96      69.0     6266.93     6906.21
```
For 2021-01 (month_index=0, growth_factor≈0.82), the first row generates as: `01.2021  20292808  MASTER\r\n  CLEANSER OIL CONTROL 144X70ML  144  [0.886]  [126.3]  [5428.29]  [6014.15]` (quantities/amounts × 0.82, before noise).

**COVID-era movement — real, verified, from `SOH` (Stock On Hand) sheets in the real 2021 SSIS files** (Jan 30, 2021 snapshot vs. Dec 27, 2021 snapshot, 510 common real SKUs). This is stock-value movement, not sales-quantity movement — no real per-SKU sales series exists for 2021 (`UnileverLaUnionSalesperSKU...` only starts Jan 2023). Use these for the walkthrough as inventory-swing evidence, not demand evidence:

**Strongest real gainers (stock value, Jan→Dec 2021):**
| Article No | Description | Jan 2021 value | Dec 2021 value | Real % change |
|---|---|---|---|---|
| 65004555 | LADY'S CHOICE RGLR MYNS DOY 24X220ML | 83,063 | 1,559,425 | +1,777% |
| 67462921 | CREAM SILK TRI-KERATIN STRAIGHT 288X10ML | 2,868 | 157,248 | +5,382% |
| 67462919 | CREAM SILK TRI-KRATIN REP SHINE 288X10ML | 9,117 | 174,960 | +1,819% |
| 65004662 | BESTFOODS RGLR MYNS MAYOMAGICDOY24X220ML | 160,143 | 1,537,302 | +860% |

**Strongest real decliners (stock value, Jan→Dec 2021):**
| Article No | Description | Jan 2021 value | Dec 2021 value | Real % change |
|---|---|---|---|---|
| 67438364 | SUNSILK SH SMOOTH & MNGBLE 288X13ML | 1,326,990 | 11,419 | −99.1% |
| 67655820 | SUNSILK SH STRONG&LONG 288X13ML | 599,581 | 6,324 | −98.9% |
| 67749041 | KNORR SINIGANG SAM ORIG 12X12X22G | 587,349 | 207,975 | −64.6% |
| 67749045 | KNORR SINIGANG NA GABI 24X12X11G | 415,528 | 71,426 | −82.8% |

Real, usable in a walkthrough as "here's what COVID actually did to stock levels" — clearly label as stock-on-hand, not sales, if presented.

---

## New totals per family

| Family | Real months | Generated months | Total months | Full range |
|---|---|---|---|---|
| Sell Out | 17 | 43 (19 gap-fill + 24 backfill) | 60 | 2021-01 – 2025-12 |
| Sales Register | 20 | 40 (16 gap-fill + 24 backfill) | 60 | 2021-01 – 2025-12 |
| Purchase Order | 11 | 49 (25 gap-fill + 24 backfill) | 60 | 2021-01 – 2025-12 |
| Sales Return | 18 | 42 (18 gap-fill + 24 backfill) | 60 | 2021-01 – 2025-12 |
| Inventory Sign Off | 17 | 43 (19 gap-fill + 24 backfill) | 60 | 2021-01 – 2025-12 |
| RMR GS & BO | 2 | 0 (unchanged — not extended) | 2 | 2025-10 – 2025-11 only |
| Unilever per-SKU (`Unilever_SKU_Demand_Fact`) | 38 | 24 (backfill only) | 62 | 2021-01 – 2026-02 |
| Unilever SSIS family | 63 (full real range) | 0 (untouched) | 63 | 2021-01 – 2026-03 |

---

## Manuscript disclosure paragraph — updated

> To demonstrate the dashboard's full year-over-year view during development, historical records outside the periods actually delivered by SSM were synthetically generated for both principals. **Del Monte data delivered by SSM covers January 2023 – December 2025; January 2021 – December 2022 is fully generated, with no source data existing for that period.** **Unilever per-SKU demand data delivered by SSM covers January 2023 – March 2026; January 2021 – December 2022 is fully generated for this specific series, with no source data existing for that period** (Unilever's aggregate SSIS-family sales data does independently cover January 2021 onward and is real, unmodified, and unrelated to this generation exercise). Generated periods for both principals were produced by anchoring to the earliest real data available for that series (Del Monte: January 2023 category/family baselines; Unilever: the January 2023 per-SKU roster and values) and applying a flat 18%-over-24-month linear growth ramp back to January 2021, with random noise bounded by the real month-to-month volatility observed in each principal's own delivered data — no larger swing, steeper trend, or shock (including no COVID-era shape) was introduced than what the real delivered data itself exhibits. All generated rows are flagged `is_demo = true` in the database and are excluded from every analytical result (ABC classification, SARIMA forecasts, LP recommendations) presented in this manuscript; they are used for dashboard demonstration purposes only. [Insert exact row counts once generation actually runs.]
