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

Did not move: headline pooled WAPE 30.12%, MASE below 1 for 110 of 175 (median 0.823), over-forecast pieces, the card's
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
