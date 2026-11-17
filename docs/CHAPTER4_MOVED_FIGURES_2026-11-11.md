# Chapter 4 figures that move with the final bundle (2026-11-11)

For: whoever rebuilds Chapter 4 after `python -m scripts.apply_final_bundle --target-public` has run on live.
Code freezes at the commit that adds this file. Every "after" value below was measured on the rehearsal copy
(`ssm_bundle`: a restore of live's backup `full_backup_20261111T103426Z`, plus the bundle), and the apply command
refuses to finish unless live reproduces it: same plan row for row, same error-decomposition rows
(`docs/FINAL_BUNDLE_REHEARSAL.json`). Take the chapter's figures from this commit only.

Three columns where they differ: what the chapter or its edit list prints now, what live shows today (lp_run 8),
and what live shows after the command (lp_run 9). A figure absent here did not move.

## 1. The plan (Tables 4.2.19, 4.2.20; plan totals quoted in the text)

What changed: two products whose forecast is 0 (no sale in their last three months, too short a history for the
dead-SKU rule) were ordering pure safety stock: 68212522 (1,104 pieces) and 64957377 (1,680). Their safety stock
now follows the level, as faded and re-coded products' already did, so it is 0 and they order nothing. Both were
Critical (absent from the stock count, read as 0) and both are Cooking Aids.

| Figure | lp_run 6 (chapter draft) | Live now: lp_run 8 | After: lp_run 9 |
|---|---|---|---|
| Rows in the plan | 109 | 110 | 110 |
| Rows ordering more than 0 | 73 | 69 | **67** |
| Order, pieces (Σ plan_q_i) | 435,988 | 381,484 | **378,700** |
| Order before case-pack rounding | 431,443.01 | (not measured) | **374,793.74** |
| Safety stock, pieces (Σ ss_i) | 557,611.70 | 462,133.41 | **459,359.47** |
| Target stock, pieces (Σ rop_i) | 1,005,660.91 | 897,922 | **895,147.89** |
| Forecast, pieces | 1,217,633.75 | 1,184,313 | 1,184,313 |
| Critical: products / ordering / pieces / safety stock | 18 / 18 / 118,644 / 53,537.52 | 16 / 16 / 65,388 / 24,747.12 | **14 / 14 / 62,604 / 21,973.18** |
| Urgent: products / ordering / pieces / safety stock | 5 / 5 / 67,276 / 18,649.23 | 6 / 6 / 67,300 / 18,652.56 | 6 / 6 / 67,300 / 18,652.56 |
| Planned: products / ordering / pieces | 86 / 50 / 250,068 | 88 / 47 / 248,796 | **90** / 47 / 248,796 |
| Cooking Aids: products / ordering / pieces | | 20 / 15 / 37,926 | 20 / **13** / **35,142** |

Table data, regenerated: `docs/MANUSCRIPT_TABLE_DATA_2026-10-30.md` (Tables 4.2.19, 4.2.20, 4.2.4).

## 2. Chapter 4 code figures (`docs/CHAPTER4_CODE_FIGURES.json`, re-pinned in this commit)

| id | Before | After |
|---|---|---|
| critical_absent_products (Critical, absent from the 2 March count) | 5 | **3** |
| critical_absent_order_pieces | 19,920 | **17,136** |
| critical_total_order_pieces | 65,388 | **62,604** |
| requirement_at_6apr_million_pieces | 1.48 | **1.47** |
| single_delivery_requirement_pieces (sensitivity, not adopted) | 243,020 | **240,236** |
| single_delivery_requirement_before_case_rounding_pieces | 240,134 | **237,360** |
| Test totals | see section 7 | |

Unchanged: critical_counted_products 11, critical_counted_stock_pieces 3,192, the dependence ratios 3.7 and 3.0,
requirement at the 3 February level 1.53, routes 95 / 85 / 70 / 15 / 10, seasonality, category sums.

## 3. Error decomposition (`docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json`, re-pinned in this commit)

What changed: the decomposition rebuilds safety stock for every scored product-month (all 21,250 rows: the backtest
ends 2026-02, the first stored plan is 2026-03) and did so at full sigma. Migration 0077 applies the plan's rule to it:
for a product-month whose forecast is 0 or was changed by succession or fading, the rebuilt safety stock follows the
level (4,200 of 21,250 rows). Less safety stock is credited, so more of the under-forecast reads as beyond it.

| Tier A (the served tier) | Before (live now) | After |
|---|---|---|
| Months demand beat safety stock | 762 | **797** |
| Exceedance rate | 17.44% | **18.24%** |
| Absorbed by safety stock, pieces | 4,966,558 | **4,860,408** |
| Beyond safety stock, pieces | 2,705,595 | **2,811,745** |
| Absorbed, PHP | 63,818,827 | **62,049,541** |
| Beyond safety stock, PHP | 38,724,995 | **40,494,280** |

| Tier B / C (counterfactual, never served) | Before | After |
|---|---|---|
| B: months beyond / rate | 883 / 17.01% | **902 / 17.37%** |
| B: absorbed / beyond pieces | 339,481 / 240,405 | **319,279 / 260,607** |
| C: months beyond / rate | 1,705 / 14.59% | **1,782 / 15.25%** |
| C: absorbed / beyond pieces | 167,047 / 154,277 | **153,426 / 167,898** |

Did not move: pooled WAPE 30.12% of the run WITHOUT the calendar factor (run 20; the published headline is the calendar-adjusted run's, 28.87% since 2026-11-12), MASE below 1 for 110 of 175 (median 0.823; 115 / 0.755 since 2026-11-13), over-forecast pieces, the card's
company-total and pooled WAPE (the forecasts are unchanged).

## 4. Charts 8, 9, 10 (`reports/evidence/ch08-10`, regenerated in this commit)

They were last drawn on 2026-09-29's 73-product plan with older placeholders (allocation 105%, cost 25, capacity 3.8M)
and had not run since: chart 10 imported a module removed on 2026-09-30, and the chart-8 harness left out case packs, so
its own check (G7) could not pass. Both fixed; G7 passes at 103 / 105 / 108%.

| Figure | Committed (2026-09-29) | Now (lp_run 9) |
|---|---|---|
| Chart 8 verdict | FLAWED | **CONFIRMS** |
| Chart 8, 103%: order / need / shortfall | 1,193,368 / 1,255,471 / 62,103 on 45 SKUs | **378,700 / 374,794 / 0 on 0** |
| Chart 8, 105%: month-end cover vs 3-week target | 3.00 weeks (just below) | **4.42 weeks (met)** |
| Chart 9 at the current weights: SKUs cut / order cost | 45 / PHP 14,007,120 | **0 / PHP 8,828,107** |
| Chart 9: grid points within ±0.10 changing the cut set | | 0 of 18 |
| Chart 10: safety stock at Z = 1.28 | 485,541 | **459,359** |
| Chart 10: at 85% / 95% / 99% | 393,149 / 623,940 / 882,451 | **371,950 / 590,296 / 834,867** |
| Chart 10: measured monthly exceedance (95% CI) | 8.4% (7.3-9.6) | **9.1% (7.9-10.5)** |

## 5. Manuscript figure checks (`python -m scripts.manuscript_figures`)

Each row is a printed chapter value that the data no longer gives. "Live now" shows which ones moved before this
bundle: h, i, j, k (the succession and fading treatments, served 2026-11-10), l (held since DEC-26: the data gives
0/2/0, the chapter 0/4/1) and o (the safety-stock change of 2026-11-10) were already wrong against the chapter. The
figures were redrawn from the rehearsal copy in this commit (`reports/figures/`).

| Figure | Item | Chapter basis | Printed | Live now (lp_run 8) | After the bundle (lp_run 9) |
|---|---|---|---|---|---|
| h | 2025-03 forecast | Table 4.2.18 | 2603372 | 2554925 | 2554925 |
| h | 2025-04 forecast | Table 4.2.18 | 2381632 | 2351536 | 2351536 |
| h | 2025-05 forecast | Table 4.2.18 | 2626451 | 2625601 | 2625601 |
| h | 2025-06 forecast | Table 4.2.18 | 2694583 | 2687976 | 2687976 |
| h | 2025-07 forecast | Table 4.2.18 | 2365326 | 2239579 | 2239579 |
| h | 2025-08 forecast | Table 4.2.18 | 2125154 | 1964264 | 1964264 |
| h | 2025-08 direction | Table 4.2.18 | 'over' | 'under' | 'under' |
| h | 2025-09 forecast | Table 4.2.18 | 2341533 | 2118181 | 2118181 |
| h | 2025-10 forecast | Table 4.2.18 | 1988739 | 1905395 | 1905395 |
| h | 2025-11 forecast | Table 4.2.18 | 2082199 | 1991783 | 1991783 |
| h | 2025-12 forecast | Table 4.2.18 | 1810379 | 1771172 | 1771172 |
| h | 2026-01 forecast | Table 4.2.18 | 2274480 | 2212229 | 2212229 |
| h | 2026-01 direction | Table 4.2.18 | 'over' | 'under' | 'under' |
| h | 2026-02 forecast | Table 4.2.18 | 1887478 | 1854382 | 1854382 |
| h | over-forecast months | edit list item 7 | 8 | 6 | 6 |
| i | 2025-03 WAPE (%) | Table 4.2.18 | 20.3 | 18.7 | 18.7 |
| i | 2025-04 WAPE (%) | Table 4.2.18 | 22.1 | 21.0 | 21.0 |
| i | 2025-07 WAPE (%) | Table 4.2.18 | 46.9 | 40.0 | 40.0 |
| i | 2025-08 WAPE (%) | Table 4.2.18 | 41.4 | 33.5 | 33.5 |
| i | 2025-09 WAPE (%) | Table 4.2.18 | 40.0 | 28.1 | 28.1 |
| i | 2025-10 WAPE (%) | Table 4.2.18 | 41.7 | 40.5 | 40.5 |
| i | 2025-11 WAPE (%) | Table 4.2.18 | 32.4 | 30.3 | 30.3 |
| i | 2025-12 WAPE (%) | Table 4.2.18 | 58.3 | 55.2 | 55.2 |
| i | 2026-01 WAPE (%) | Table 4.2.18 | 46.4 | 45.2 | 45.2 |
| i | 2026-02 WAPE (%) | Table 4.2.18 | 35.2 | 33.8 | 33.8 |
| j | 2025-03 surplus | Table 4.2.18 | 3376570 | 3036166 | 3036166 |
| j | 2025-03 shortage | Table 4.2.18 | 3851955 | 3862481 | 3862481 |
| j | 2025-04 surplus | Table 4.2.18 | 2486130 | 2304184 | 2304184 |
| j | 2025-04 shortage | Table 4.2.18 | 4944467 | 5096578 | 5096578 |
| j | 2025-05 surplus | Table 4.2.18 | 2911738 | 2907473 | 2907473 |
| j | 2025-06 surplus | Table 4.2.18 | 5365124 | 5328474 | 5328474 |
| j | 2025-06 shortage | Table 4.2.18 | 4403057 | 4494367 | 4494367 |
| j | 2025-07 surplus | Table 4.2.18 | 7375371 | 6471131 | 6471131 |
| j | 2025-08 surplus | Table 4.2.18 | 3848422 | 2828328 | 2828328 |
| j | 2025-08 shortage | Table 4.2.18 | 4247026 | 4296721 | 4296721 |
| j | 2025-09 surplus | Table 4.2.18 | 5252297 | 3864453 | 3864453 |
| j | 2025-09 shortage | Table 4.2.18 | 5056550 | 5092534 | 5092534 |
| j | 2025-10 surplus | Table 4.2.18 | 4291229 | 3903451 | 3903451 |
| j | 2025-10 shortage | Table 4.2.18 | 7385082 | 7564986 | 7564986 |
| j | 2025-11 surplus | Table 4.2.18 | 4944624 | 4459017 | 4459017 |
| j | 2025-11 shortage | Table 4.2.18 | 3907377 | 4089975 | 4089975 |
| j | 2025-12 surplus | Table 4.2.18 | 9967556 | 9707524 | 9707524 |
| j | 2026-01 surplus | Table 4.2.18 | 7527223 | 7232970 | 7232970 |
| j | 2026-01 shortage | Table 4.2.18 | 4485523 | 4624189 | 4624189 |
| j | 2026-02 surplus | Table 4.2.18 | 6421262 | 6174229 | 6174229 |
| j | 2026-02 shortage | Table 4.2.18 | 2481131 | 2537737 | 2537737 |
| k | MASE below 1 | Table 4.2.15 / pinned | 109 | 110 | 110 |
| k | median MASE | §4.2.2.1.3 / pinned | 0.827 | 0.823 | 0.823 |
| l | XGBoost + MA3 average (long, @A) W/T/L | §4.2.2.1.2 and Table 4.2.16: '0 wins, 4 ties, 1 loss' (DEC-26, 2026-09-21) | '0/4/1' | '0/2/0' | '0/2/0' |
| m | rows ordering > 0 | plan invariant | 69 | agrees (69) | 67 |
| m | order pieces | plan invariant | 381484 | agrees (381484) | 378700 |
| m | safety stock (pieces) | edit list item 9 | 462133 | agrees (462133) | 459359 |
| m | CRITICAL products | Tier B, B-a | 16 | agrees (16) | 14 |
| m | CRITICAL ordering | Tier B, B-a | 16 | agrees (16) | 14 |
| m | CRITICAL order pieces | Tier B, B-a | 65388 | agrees (65388) | 62604 |
| m | CRITICAL safety stock | Tier B, B-a | 24747.12 | agrees (24747.12) | 21973.18 |
| m | PLANNED products | Tier B, B-a | 88 | agrees (88) | 90 |
| o | target stock, plan (pieces) | Table 4.2.22 | 1005661 | 897922 | 895148 |
| o | target stock, rule (pieces) | Table 4.2.22 | 840092 | 817103 | 817103 |
| o | target vs rule (%) | Table 4.2.22 | 19.7 | 9.9 | 9.6 |
| o | average stock, plan (PHP) | rule_read_as_peak | 7496532 | 6903393 | 6714485 |
| o | average stock, rule (PHP) | rule_read_as_peak | 8066830 | 7932223 | 7932223 |
| o | average vs rule (%) | rule_read_as_peak | -7.1 | -13.0 | -15.4 |
| o | peak stock, plan (PHP) | rule_read_as_peak | 11045937 | 10393572 | 10204663 |
| o | peak stock, rule (PHP) | rule_read_as_peak | 9680196 | 9518668 | 9518668 |
| o | peak vs rule (%) | rule_read_as_peak | 14.1 | 9.2 | 7.2 |
| o | the other reading's average vs rule (%), source note only | rule_read_as_average | -22.6 | -27.5 | -29.5 |
| o | the other reading's peak vs rule (%), source note only | rule_read_as_average | -2.2 | -6.4 | -8.1 |
| o | products holding less than the rule | Table 4.2.22 | 56 | 58 | 58 |
| n | COOKING AIDS products / ordering / pieces | Tier B, B-b | (20, 15, 37926) | agrees | (20, 13, 35142) |
| p | over / absorbed / beyond, pieces, as published | PUBLISHED_FIGURES_SNAPSHOT | (12242746, 4847983, 2669295) | (10397753, 4966558, 2705595) | (10397753, 4860408, 2811745) |
| p | months beyond safety stock | STATE.md headline | 749 | 762 | 797 |
| p | pesos beyond safety stock | pinned | 38187551 | 38724995 | 40494280 |
| q | pesos beyond safety stock | pinned | 38187551 | 38724995 | 40494280 |

## 6. Worked calculations (`docs/MANUSCRIPT_WORKED_CALCULATIONS.md`, Tables 4.2.22 to 4.2.24)

The file is written on lp_run 6 throughout and was NOT rewritten in this commit (chapter work). What holds and what does not:

| Part | Status after the bundle |
|---|---|
| A. Product 62687212 (product_key 39): SS 1,822.16, T 3,976.53, plan_q_i 9,744 (9,723.32 before rounding) | **unchanged** in lp_run 9 |
| A. The warehouse line Σ(S_i + plan_q_i) = 2,232,506 + 435,988 | moves: the order total is 378,700 |
| B. Product 69668149 (product_key 853), ordered 0 | still 0 (SS 19,456.55, T 51,906.98, forecast 88,188.39 in lp_run 9) |
| C. Urgency subtotals 118,644 + 67,276 + 250,068 = 435,988 | moves: 62,604 + 67,300 + 248,796 = **378,700** (section 1) |
| Rounding added | 4,544.99 in lp_run 6; **3,906.26** in lp_run 9 (378,700 - 374,793.74) |

## 7. Test totals (Chapter 4's testing section, `docs/CHAPTER4_CODE_FIGURES.json`)

| Total | Before (pinned 2026-11-11 at 4c2c1d0) | After (this commit) | How |
|---|---|---|---|
| With data/raw: collected / passed / skipped / failed | 2,808 / 2,790 / 18 / 0 | **2,828 / 2,810 / 18 / 0** | MEASURED: `scripts/check.sh --full` on this tree against the rehearsal copy, GREEN, 429 s |
| Clean clone: collected / passed / skipped | 2,802 / 2,781 / 21 | **2,822 / 2,801 / 21** | pinned by arithmetic; the clean-clone measurement is in STATE.md |

+20 collected: 21 new tests (the bundle's attestation and guards, 0077's rule, the freshness flag, 0078, the zero-forecast
safety stock) and one deleted (`tests/test_transform_config.py`, `def test_dummy(): pass`).

## 8. Not moved by this bundle, still out of date in the chapter

- Routes 95 / 85 / 70 (the chapter prints 84 / 74 / 59 in places, STATE.md 2026-11-06).
- Table 4.2.18 (monthly forecast, WAPE, surplus and shortage), Table 4.2.15 / 4.2.16 and section 4.2.2.1.3 (rows h to l
  above): moved by the 2026-11-10 treatments, before this bundle.
- Tables 4.2.22 and 4.2.25 print the mixed policy pair (-22.6 / +14.1); the consistent pairs are in row o.

## 9. The calendar factor at product grain, LIVE 2026-11-13 (`scripts/apply_calendar_grain.py`, built 2026-11-12)

Supersedes nothing in sections 1-8 except the figures below; the spike cap (refused, rehearsal plan SPIKE-COPY) and the
forecastability gate (not adopted, rehearsal plan GATE-COPY) are on other branches and never reached live. Every "after" value was
measured on the rehearsal copy (`ssm_grain`: a restore of live's backup `full_backup_20261111T142748Z` plus the apply) and LIVE
REPRODUCES IT: applied 2026-11-13 08:05 UTC, every result key equal to the copy's when compared byte-ordered (the apply's own
comparison stopped on a collation artefact of its hash, STATE.md), and check.sh --fast GREEN against live. Every before/after is on
the same products and product-months.

December rule: included by the 2026-11-13 brief's rule. Pooled WAPE, 95% product bootstrap: grain alone vs company 38.07% -> 37.15%
[-1.57, -0.34] (Sep 2025-Feb 2026) and 27.86% -> 27.53% [-0.62, -0.05] (2024-01..2025-08), MASE 0.731 -> 0.674 and 0.901 -> 0.869;
grain + December 36.33% / 27.24% (below); December over grain alone [-2.37, +0.63] and [-0.38, -0.20].

What changed: the calendar factor (DEC-41) was the company total's month ratio, applied to every product. In 4 of 35 month-years it
pointed the opposite way to the typical product (March 2024: company 1.136, product median 0.906, 61% of products fell) and in 8
more it differed by over 10%: a few large products move the total. It is now computed per product: each product's own month
ratios, pulled toward the typical product's (weight n / (n + 2) for n own years), halfway to 1; December takes last December's
typical-product dip in full when it was a dip (at product grain December 2023 was a dip, 0.950, so the rule acts in December 2024
and 2025). Chosen on criteria fixed before the results (STATE.md).

| Figure | Before (live, lp_run 9) | After (lp_run 10) |
|---|---|---|
| Calendar factor for March 2026 | 1.0762, every product | per product, 0.7103 to 1.2608 |
| March forecast, 175 'ok' products | 1,952,313 | **1,837,121** (-5.9%) |
| MASE < 1 (Tier A as of 2026-02) / median | 110 of 175 / 0.823 | **115 of 175 / 0.755** |
| Review flags 2026-03 | 63 of 189 | **40 of 189** |
| Plan rows / ordering / pieces | 110 / 67 / 378,700 | **115 / 64 / 330,212** (-12.8%) |
| Safety stock / forecast over the plan rows | 459,359 / 1,184,313 | **466,159 / 1,146,783** |
| Critical / Urgent / Planned: products, ordering, pieces | 14/14/62,604; 6/6/67,300; 90/47/248,796 | **15/15/58,832; 5/5/33,328; 95/44/238,052** |
| Categories (products / ordering / pieces) | Hair 29/19/138,516; Fabric Cleaning 25/12/86,122; Deo 13/11/58,248; Fabric Enh 8/7/50,040; Cooking Aids 20/13/35,142; Condiments 7/3/9,288; Oral 4/1/912; Skin Cleansing 4/1/432 | **Hair 30/19/130,116; Fabric Cleaning 25/12/72,368; Deo 14/11/50,256; Fabric Enh 8/5/36,600; Cooking Aids 19/12/32,364; Condiments 11/3/7,296; Oral 4/1/876; Skin Cleansing 4/1/336** |
| Error card Sep 2025-Feb 2026 (208 products, 1,078 product-months): company-total / pooled product WAPE | 13.30% / 38.27% | **7.22% / 36.53%** |
| Error card Sep 2025-Feb 2026: MAPE, **Chapter 3 basis, no month set apart** (192 products) | 41.0% (basis not recorded; the earlier 183-product set had zero-count months set apart) | **40.7%** |
| Error card Sep 2025-Feb 2026: MAPE, **stock-limited months set apart** (months absent from the month-end count; 149 months, 189 products) | was printed 35.2% (183 products, under 20% 31, at 100%+ 34; set apart a zero OPENING or closing count, 2026-11-12 to 2026-11-15) | **39.8%** (the same months-apart set is now the closing count only) |
| Error card Sep 2025-Feb 2026: surplus / shortage pesos | PHP 35.34M / 25.84M | **PHP 28.58M / 28.29M** |
| Error card 2024-01..2025-08 (270 products, 3,292 product-months): company / pooled WAPE | 10.23% / 27.88% | **9.07% / 27.25%** |
| Error card 2024-01..2025-08: MAPE, **Chapter 3 basis, no month set apart** (255 products) | 34.6% (basis not recorded) | **37.9%** |
| Error card 2024-01..2025-08: MAPE, **stock-limited months set apart** (559 months, 242 products) | was printed 32.8% (237 products, under 20% 38, at 100%+ 42; zero opening or closing count set apart) | **33.6%** |
| Error card 2024-01..2025-08: surplus / shortage pesos | PHP 100.84M / 76.70M | **PHP 93.69M / 79.54M** |
| Error card Mar 2025-Feb 2026 (the card's default range; 233 products): company / pooled / **MAPE, Chapter 3 basis (218 products)** | 10.29% / 32.28% / 38.2% | **8.52% / 32.04% / 38.7%** |
| Error card Mar 2025-Feb 2026: MAPE, **stock-limited months set apart** (257 months, 217 products) | was printed 34.0% (210 products; zero opening or closing count set apart) | **36.7%** |
| Products at 50%+ MAPE (as-served frame, 183 / 237 products) | 73 / 76 | **63 / 74** |
| Backtest pooled WAPE (as-served frame), 95% interval of the change: Sep-Feb / earlier | 38.07% / 27.86% | **36.33% [-3.43, -0.19] / 27.24% [-0.91, -0.34]** |
| Backtest median MASE, interval: Sep-Feb / earlier | 0.731 / 0.901 | **0.646 [-0.132, -0.019] / 0.869 [-0.080, +0.016]** |
| Planned products (lp_run 9's 110): pooled WAPE Sep-Feb / earlier | 32.63% / 28.47% | **31.07% [-3.17, -0.10] / 27.82% [-0.91, -0.37]** |
| Headline, calendar-adjusted (whole window): median product WAPE / pooled / pesos | 37.88% / 29.69% / 10.77% | **36.37% / 28.87% / 8.70%** |
| Headline, no calendar factor | 38.55% / 30.12% / 10.02% | unchanged (that run has no calendar factor) |
| **Stock-out price: Tier A months beyond safety stock (26 months, 2024-01..2026-02; was printed "29 backtest months", the backtest's length, not the decomposition's)** | **797 (18.24%)** | **852 (19.50%)**, +55 |
| **Tier A pesos / pieces beyond safety stock** | **PHP 40.49M / 2,811,745** | **PHP 43.77M / 3,096,724** (+PHP 3.27M at sales value, about PHP 126k a month; was printed PHP 113k, over 29 months) |
| Tier A end-of-month stock the forecast leaves, max(0, F + SS - A), same 4,370 rows: piece-months / PHP at cost | 22,681,047 / 260.16M | **21,427,253 / 245.56M** (-1,253,794 / -PHP 14.60M) |
| The trade, 26 months: holding saved / stock-out margin lost / net (assumption ranges, STATE.md) | | **PHP 0.77M to 1.21M / 0.08M to 0.30M / +0.47M to +1.14M** (central +0.62M; turns negative only if a shortfall costs over 24-37% of its sales value; margin measured 9.21%) |
| March plan at cost (LP cost per piece) / safety stock at cost | PHP 8.83M / 5.13M | **PHP 7.57M / 5.20M** |
| Tier A absorbed by safety stock, pieces / PHP | 4,860,408 / 62,049,541 | 5,083,650 / 64,062,674 |
| Tier B / C months beyond safety stock (counterfactual tiers) | 902 / 1,782 | 952 / 1,807 |
| Chapter 4 code figures: critical counted products / stock / order | 11 / 3,192 / 45,468 | **12 / 3,198 / 42,272** |
| critical absent products / order; critical total order | 3 / 17,136; 62,604 | **3 / 16,560; 58,832** |
| count 2 Mar over 3 Feb / over 6 Apr; requirement at 3 Feb / 6 Apr (M pcs) | 3.7 / 3.0; 1.53 / 1.47 | **3.7 / 2.9; 1.47 / 1.40** |
| single delivery requirement (sensitivity) / before rounding | 240,236 / 237,360 | **213,062 / 210,825** |
| Chart 10: measured monthly exceedance at Z = 1.28 (95% CI) | 9.1% (7.9-10.5) | **9.0% (7.7-10.3)** |
| Tests collected / passed (with data/raw); clean clone | 2,828 / 2,810; 2,822 / 2,801 | **2,854 / 2,836; 2,848 / 2,827** (2026-11-15 after the near-zero flag; 2,853 / 2,835; 2,847 / 2,826 before it; 2,845 / 2,827; 2,839 / 2,818 on 2026-11-13, +1 test for the month-load gate; passed counts derived by chapter_figures --write) |

Manuscript figure checks: Tables 4.2.19 and 4.2.20 pass on the new plan; figures h-l and o-q stay "held" against older manuscript
values (chapter work), but NOT exactly as before: drawn from live on 2026-11-13 (163b42f's re-pin had not redrawn figures h-k, p and
q, which still showed lp_run 9's data), seven manuscript statements that agreed with lp_run 9's served backtest now disagree: Table 4.2.18's 2025-04 and 2025-12 over/under direction (figure 4.2.26), its 2025-05 and 2025-06 monthly WAPE (4.2.27), and its 2025-05, 2025-07 and 2025-12 shortage pesos (4.2.28).
The served forecast's backtest moved with the method, so no code change reconciles them; the chapter text is the author's. This is
the 2026-11-13 brief's second gate (STATE.md). DEC-41's text in ARCHITECTURE.md describes the per-product factor since
2026-11-13. Stored run descriptions of runs 21-23 corrected by migration 0079 (they said "x the company calendar factor").

### 9.1 The MAPE basis and the stock-limited label, applied 2026-11-15 (no database write)

Only the basis of the MAPE and the definition of the stock-limited label changed; WAPE (company 8.52% / 7.22% / 9.07%, pooled 32.04% / 36.53% / 27.25%), every plan figure, every breakdown and every other row above are the same on live (read through the card's own route, `scripts/score_stock_limited_rule.py`, 2026-11-15). **Since 2026-11-17 the pooled WAPE counts a net-negative month as 0 sold: 31.95% / 36.33% / 27.24% on the same three ranges** (the company totals did not move; the pinned set is `docs/EVALUATION_METRICS.md`).

| Figure (Tier A, Unilever; windows Mar 2025-Feb 2026 / Sep 2025-Feb 2026 / 2024-01..2025-08) | Before (card as deployed) | After |
|---|---|---|
| Card headline MAPE | 34.0% / 35.2% / 32.8% (set apart a zero opening OR closing count; labelled "as Chapter 3 defines it") | **38.7% / 40.7% / 37.9%** (Chapter 3's measure, nothing set apart) |
| MAPE beside it, stock-limited months set apart | none | **36.7% / 39.8% / 33.6%** (257 / 149 / 559 product-months) |
| Product-months labelled possibly stock-limited | 1,169 / 538 / 2,066 | **257 / 149 / 559** (absent from the month-end count) |
| Perfect-average floor, MAPE, Chapter 3 basis | not computed on this basis (the error hunt's floor was WAPE: 34.53% / 26.79%, main / earlier) | **37.4% / 36.5% / 36.9%** |
| Perfect-average floor, MAPE, stock-limited basis (level = all months / level = months that count) | n/a | **36.5% / 35.5%; 35.0% / 33.6%; 33.2% / 29.9%** |

The floor is `scripts/mape_floor.py`: every month of a product forecast with the product's own true mean over the window (an oracle, not a forecast), scored with the card's own MAPE function on the card's own rows. A mean is not the MAPE-optimal constant (MAPE rewards a lower level), so it is the floor for "a perfect average", not for every constant.

### 9.2 The near-zero flag and the worst 50 (2026-11-15; read-only on live, no forecast, order or plan changed)

**What drives the mean.** On the card's default range (Mar 2025-Feb 2026, 218 products with a sale) the mean of the product MAPEs is 1,057% and the median 38.7%. 46 product-months (2.5% of the 1,839 months a product sold) carry 94% of the sum of the percentage errors: months where a product sold under 5% of its usual level (its 12-month mean), against a forecast near that usual level (forecast 5,000, sold 2). 38 of the 46 are the first low month of a collapse that nothing computed from the earlier months can see. Of the 25 highest-MAPE products and the next 25 by contribution to the product-month mean (50 in all), the cause by data, one each: 12 promo-bundle waves or short-lived promo packs (months of a few pieces between waves of thousands), 17 run-outs of a code that was re-coded or replaced (the successor launches 0-3 months earlier; the old code's collapse month is the miss), 13 one-month gaps or dips where demand resumes the next month and the forecast is right (many with a zero or near-zero month-end count), 2 one-off bulk orders (the month after is forecast on the bulk), 6 ordinary over-forecasts of a soft month. The named list is in the git-ignored `local/WORST_50_2026-11-15.md` (hard rule 9).

**The flag** (`backend/marts.NEAR_ZERO_SHARE` = 5%): a product with any scored month where 0 < sold < 5% of its usual monthly level is labelled, counted, and scored on MAE and RMSE (pieces, over all its scored months) instead of a percentage. It is a measurement rule, not tuned: 2% and 10% are in the table. Forecasts, orders and stock-outs are untouched; the card shows the forecastable products' MAPE, the flagged count, and the flagged MAE and RMSE, and keeps the every-product MAPE in the tooltip.

| Window | Population | State | Products | Mean | Median | at 50%+ | at 100%+ | Flagged |
|---|---|---|---|---|---|---|---|---|
| 2025-03..2026-02 | all | before | 218 | 1057.1% | 38.7% | 75 | 53 | - |
| 2025-03..2026-02 | all | after, 2% | 190 | 94.7% | 34.1% | 47 | 26 | 28 flagged (264 months; MAE 4789, RMSE 12044 pieces) |
| 2025-03..2026-02 | all | after, 5% | 179 | 51.7% | 32.4% | 36 | 15 | 39 flagged (368 months; MAE 4280, RMSE 10696 pieces) |
| 2025-03..2026-02 | all | after, 10% | 173 | 42.3% | 31.7% | 30 | 10 | 45 flagged (427 months; MAE 4908, RMSE 13015 pieces) |
| 2025-03..2026-02 | planned | before | 114 | 821.3% | 29.9% | 21 | 14 | - |
| 2025-03..2026-02 | planned | after, 2% | 105 | 59.6% | 28.4% | 12 | 5 | 9 flagged (79 months; MAE 9514, RMSE 20147 pieces) |
| 2025-03..2026-02 | planned | after, 5% | 100 | 30.7% | 27.2% | 7 | 0 | 14 flagged (128 months; MAE 6870, RMSE 15994 pieces) |
| 2025-03..2026-02 | planned | after, 10% | 100 | 30.7% | 27.2% | 7 | 0 | 14 flagged (128 months; MAE 6870, RMSE 15994 pieces) |
| 2025-09..2026-02 | all | before | 192 | 938.1% | 40.7% | 77 | 46 | - |
| 2025-09..2026-02 | all | after, 2% | 175 | 108.7% | 35.6% | 60 | 29 | 17 flagged (85 months; MAE 4216, RMSE 8544 pieces) |
| 2025-09..2026-02 | all | after, 5% | 164 | 66.5% | 33.7% | 49 | 18 | 28 flagged (145 months; MAE 3745, RMSE 7848 pieces) |
| 2025-09..2026-02 | all | after, 10% | 158 | 51.0% | 32.7% | 43 | 12 | 34 flagged (177 months; MAE 4807, RMSE 13278 pieces) |
| 2025-09..2026-02 | planned | before | 112 | 383.5% | 29.0% | 27 | 15 | - |
| 2025-09..2026-02 | planned | after, 2% | 105 | 72.6% | 27.8% | 20 | 8 | 7 flagged (37 months; MAE 5995, RMSE 11307 pieces) |
| 2025-09..2026-02 | planned | after, 5% | 100 | 35.1% | 27.2% | 15 | 3 | 12 flagged (67 months; MAE 4429, RMSE 8767 pieces) |
| 2025-09..2026-02 | planned | after, 10% | 100 | 35.1% | 27.2% | 15 | 3 | 12 flagged (67 months; MAE 4429, RMSE 8767 pieces) |
| 2024-01..2025-08 | all | before | 255 | 1610.3% | 37.9% | 109 | 75 | - |
| 2024-01..2025-08 | all | after, 2% | 207 | 77.9% | 30.6% | 62 | 28 | 48 flagged (576 months; MAE 3345, RMSE 6278 pieces) |
| 2024-01..2025-08 | all | after, 5% | 201 | 70.5% | 29.9% | 56 | 23 | 54 flagged (639 months; MAE 3132, RMSE 5982 pieces) |
| 2024-01..2025-08 | all | after, 10% | 194 | 45.5% | 29.4% | 49 | 16 | 61 flagged (698 months; MAE 2916, RMSE 5733 pieces) |
| 2024-01..2025-08 | planned | before | 95 | 2074.8% | 29.9% | 23 | 12 | - |
| 2024-01..2025-08 | planned | after, 2% | 87 | 37.0% | 29.1% | 15 | 4 | 8 flagged (102 months; MAE 3489, RMSE 5215 pieces) |
| 2024-01..2025-08 | planned | after, 5% | 87 | 37.0% | 29.1% | 15 | 4 | 8 flagged (102 months; MAE 3489, RMSE 5215 pieces) |
| 2024-01..2025-08 | planned | after, 10% | 86 | 36.1% | 29.0% | 14 | 3 | 9 flagged (119 months; MAE 3019, RMSE 4829 pieces) |

Population "planned" = the 116 products with a row in the live cycle (115 plan rows and legacy row 4), as scored by the card.

**Tested and not holding (not applied; would move the plan):** a launch handover (halve a forecast for 3 months after a same brand x category, same-content or same-family code first sells, the existing succession context, `analytics/forecasting/treatments.build_contexts`), one rule fixed before scoring, on the card's rows: Mar 2025-Feb 2026 pooled WAPE 32.00% -> 32.26%, median MAPE 38.7% -> 40.6% (407 rows, 106 products moved); Sep-Feb 36.43% -> 38.17%; 2024-01..2025-08 27.25% -> 30.30%. It fires on far more products than die. The served succession and fading rules already act from the month after a collapse; only 2 product-months in the default range were scored after an already-low month with a forecast still above 20% of usual.

**Still above 100% among the forecastable products (15 on the default range):** each is one or two months at 5-25% of usual (December and January dips, promo-bundle waves, a soft month after a delivery), where the level forecast is right on average and wrong in that month; they are real errors, not hidden.
