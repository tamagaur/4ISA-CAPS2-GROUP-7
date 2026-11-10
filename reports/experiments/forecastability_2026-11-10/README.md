# Forecastability classes, 2026-11-10 (backtest only)

Scripts: `checks.py` (the three checks) and `classify.py` (classes, treatments, scores). Both read only the throwaway copy
`ssm_challenger` (a restore of the 2026-11-04 backup) in one READ ONLY transaction. Aggregates are in `results_checks.json`,
`results_classes.json` and `results_classes.csv`. Per-product rows are in the git-ignored `local/` (hard rule 9). Nothing
served, planned or pinned changed. Live, the manuscript, Render and Vercel were not touched.

The rules and treatments in `classify.py` were committed (f3ffe47) before the first scoring run. Two items were added
after that run and are labelled post hoc everywhere: BURST2 and `system_nopromo` (below).

## Verdict

1. **The piece fall is mostly a shift in what customers buy, not less buying. The level correction was NOT built (gate).**
   Comparing the same six calendar months a year apart, pieces fell 23.5% while constant-price value fell 4.1%. About 85%
   of the piece decline is composition. A company-wide tracking signal on pieces would read that shift as falling demand
   and cut every forecast for a decline that, in value, mostly did not happen.
2. **Stock-outs explain at most about a tenth of the over-forecast.** 342 of the 673 "forecast too high" product-months
   carry the stock-limited flag. But the flag also fires on 43.5% of the "too low" months, so it does not separate
   censored months from the rest. Only 111 months closed at zero stock, carrying 9.7% of the excess pieces.
3. **Working days do not explain the Decembers.** Every December has 0.87 to 0.89 of the prior three months' working days.
   Per working day, the Decembers still disagree: 1.34, 0.77 and 0.72.
4. **Two classes have a rule and a treatment that hold in both windows: SUCCESSION (a re-coded product) and FADING (the
   collapse flag made to act).** Together they cut pooled WAPE for all products by 3.5 points in Sep 2025 - Feb 2026 and
   by 2.6 points in 2024-01 - 2025-08, with both 95% intervals below zero.
5. **Burst sellers: no treatment holds.** The pre-registered rule did not detect them. The post-hoc rule detects them
   only after the spikes start. The family split and plain smoothing are each better in one window only. The forecast-free
   stock-cover policy holds less stock in both windows but runs short two to three times as often: a trade-off, not a win.
6. **Promo, bundle and near-zero sellers: keep forecasting them with the served model, and report them as their own
   population.** The treatment is worse for the planned products in both windows.

## 1. The checks

### Pack mix (`checks.py`, every real Unilever row, all products)

Inside each SKU the peso per piece did not move: the matched-SKU price ratio is 1.005 (median 1.003, 5th-95th percentile
0.98-1.09). So the rise in pesos per piece, from about 12 to about 16, is entirely composition. Constant-price value
(each SKU's pieces x its own median peso per piece) is therefore a quantity index of what was bought.

| Comparison | Pieces | Pesos | Constant-price value | Share of the piece fall that is real (value) decline | Share that is composition |
|---|---|---|---|---|---|
| Same months a year apart: Sep 2024-Feb 2025 vs Sep 2025-Feb 2026 | -23.5% | -3.6% | -4.1% | 15.5% | **84.5%** |
| The step: Mar-Jun 2025 vs Jul 2025-Feb 2026 (seasons not matched) | -25.6% | -11.6% | -11.9% | 42.7% | 57.3% |
| FY2024 vs FY2025 | -12.6% | +1.6% | +1.3% | none (value rose) | all |

The step comparison puts July and December, both seasonal dips, on one side only. That is why it shows more real decline.
The year-over-year line is the fair one.

**Where the composition sits.** Shares are of the piece fall, year over year, measured in log points.

| Family key | Within family (moving between packs) | Between families (moving between products) |
|---|---|---|
| Coarse: brand x category (55 families) | 77.2% | 7.2% |
| Fine: brand x category x name family, sizes and pack words dropped (667, heuristic) | 39.8% | 44.6% |

**A "piece" is not one unit.** It is a sachet for one code, a 7-sachet bundle "(6+1)" for another and a 7 kg bag for a
third. In the 205 fine families whose pack sizes all parse to one unit (48% of pieces), content fell as much as pieces
(-14.9% against -14.0%) while value fell less (-8.8%). In those families customers did not move to bigger sachets. They
moved to higher-value pieces, and bundles are among them; the parser cannot read their content.

**The families the brief names (year over year):**

| Family | Pieces | Constant-price value | Content (parsed codes) | Reading |
|---|---|---|---|---|
| Knorr Sinigang 67749041 / 67749043 / 67749045 | +34.3% | +31.3% | +31.5% | No decline at all |
| Knorr cubes (14 codes selling) | -25.4% | -22.8% | -22.7% | A real decline, not mix |
| Surf powder (41 codes) | -42.2% | -12.5% | -44.4% | Mostly mix into codes whose content does not parse (bundles) |
| Surf fabcon Blossom Fresh (12 codes) | -25.2% | -29.2% | -29.3% | A real decline, plus re-codes |

The named products are not one product in different packs. 67749045 is Sinigang **na Gabi**, another flavour in the same
pack as 67749043. The "four Knorr cubes" are four flavours (chicken, pork, beef, shrimp) of one pack, 48X12X10G, and the
"four Surf powders" are four scents of one pack, 288X65G. Only 67749041 vs 67749043 is one product in two packs.

### Stock-outs (`mart.accuracy_mart` run 11, the as-served backtest)

| | Main 2025-09..2026-02, all | Main, planned | Earlier 2024-01..2025-08, all | Earlier, planned |
|---|---|---|---|---|
| Product-months "forecast too high" | 673 | 356 | 1,828 | 728 |
| ... flagged possibly stock-limited | 342 (50.8%) | 154 (43.3%) | 1,199 (65.6%) | 393 (54.0%) |
| ... closing count zero | 111 | 38 | 416 | 71 |
| Excess pieces, all over months | 3,026,994 | 1,335,353 | 9,236,379 | 4,693,676 |
| ... in flagged months | 1,118,929 | 606,627 | 5,857,584 | 2,562,840 |
| ... in closing-zero months | 294,763 | 135,750 | 1,263,438 | 111,820 |
| "Too low" months flagged, for comparison | 43.5% | 38.0% | 56.0% | 54.0% |

The flag (migration 0043: an opening or closing count of 0 or under one week of average sales) fires almost as often on
under-forecast months as on over-forecast ones, so it cannot say a month was censored. A closing count of zero is the
nearest sign. One caveat: the stock counts and the SKU sales may not be from the same branch (Ilocos Sur counts vs La Union
sales, UNVERIFIED).

### December working days (`holidays` 0.108, Philippine regular and special non-working days)

| | Dec 2023 | Dec 2024 | Dec 2025 |
|---|---|---|---|
| Working days, Dec / mean(Sep-Nov), Mon-Sat | 0.892 | 0.880 | 0.868 |
| Working days, Dec / mean(Sep-Nov), Mon-Fri | 0.885 | 0.844 | 0.844 |
| Pieces, Dec / mean(Sep-Nov) | 1.195 | 0.681 | 0.624 |
| Pieces per working day (Mon-Sat), Dec / mean(Sep-Nov) | **1.339** | **0.774** | **0.718** |

SSM's trading days are not on record, so both a Monday-Saturday and a Monday-Friday week are shown; they agree. The
holiday list is the library's. A proclamation the library lacks would move one December by a day, which is under 0.05
on these ratios. A selling-day adjustment would scale every December by about 0.87. That cannot turn a 1.20 into a 0.62.
The three Decembers disagree for some other reason.

## 2. The classes

Each product-month is classified at forecast time from its history before that month; the first rule that matches wins.

| Class | Detection rule (history before t only) | Treatment | Main window: products / product-months | Share of actual pieces | Share of served abs. error | Served net over-forecast, pieces |
|---|---|---|---|---|---|---|
| DEAD | the served dead-SKU rule already zeroes it | unchanged | 8 / 19 | 0.0% | 0.0% | 0 |
| PROMO/LOW | name has (n+m), +, PROMO, PRMO, PRM, DUO, DUA, or the last 6 months sum to < 500 pieces | min(served, last month): **not adopted** | 61 / 264 | 10.9% | 11.9% | 45,888 |
| SUCCESSION (found here) | last month < 0.5 x 12-month mean AND a code of the same brand x category, same content per piece (+-10%) or same name family, made its first sale in the 3 months before | last month (naive) | 25 / 59 | 1.9% | 8.7% | 387,922 |
| FADING | the live collapse rule (`review_flag.collapse_ratio` < 0.5) | min(served, mean of last 3 months) | 20 / 38 | 5.8% | 9.1% | 119,460 |
| NEW | under 6 months since first sale | served | 20 / 45 | 4.8% | 4.6% | 115,039 |
| BURST (pre-registered) | Syntetos-Boylan, last 12 months: CV^2 of non-zero months >= 0.49 | family split | 1 / 1 | 0.0% | 0.0% | (one product, not shown) |
| BURST2 (post hoc) | the served forecast's own errors over the last 6 months: MASE >= 1, errors two-sided | none holds | 38 / 90 | 21.3% | 16.2% | 264,611 |
| STABLE | the rest | served | 126 / 562 | 55.3% | 49.5% | 569,138 |

Earlier window, same order (products / product-months): DEAD 24/71, PROMO/LOW 97/698, SUCCESSION 43/93 (+1,045,200
pieces over-forecast), FADING 38/111 (+455,457), NEW 45/107, BURST 3/18, BURST2 80/330, STABLE 177/1,864.

**Scoring.** Pooled WAPE = sum |f - a| / sum |a|. MASE = median over products of mean |f - a| / one fixed scale per product,
mean |y_t - y_t-1| over 2023-01..2025-08 from its first sale. The scale is the same in both windows; 16 products lack two
months there and are left out of MASE. MAPE = median over products of mean |f - a| / a over months with a > 0. Its
denominator shrinks as sales fall, so it inflates on fading, low and December rows whatever the method. Brackets are 95%
product-bootstrap intervals of the WAPE difference against served, in points.

### Treatment scores, all months

| Class, treatment | Window | Set | Pooled WAPE served -> treatment | Difference [95%] | MASE | MAPE | Net over-forecast, pieces |
|---|---|---|---|---|---|---|---|
| SUCCESSION, last month | main | all | 187.8% -> 50.1% | -137.8 [-1619.6, -45.4] | 0.756 -> 0.118 | 299% -> 90% | 387,922 -> 43,661 |
| | earlier | all | 247.5% -> 40.7% | -206.9 [-548.5, -104.3] | 1.213 -> 0.073 | 94% -> 64% | 1,045,200 -> 11,263 |
| | main | planned | 112.7% -> 44.7% | -68.0 [-737.5, -17.0] | 0.730 -> 0.415 | 72% -> 65% | 227,341 -> 33,879 |
| | earlier | planned | 64.6% -> 31.0% | -33.5 [-71.3, +16.3] | **0.643 -> 1.036** | 22% -> 47% | 233,917 -> -18,205 |
| FADING, min(served, last 3 mean) | main | all | 65.1% -> 51.0% | -14.1 [-85.6, +2.8] | 0.330 -> 0.111 | 47% -> 33% | 119,460 -> -67,947 |
| | earlier | all | 1182.6% -> 152.2% | -1030.5 [-4289.2, -356.3] | 1.633 -> 0.225 | 100% -> 69% | 455,457 -> 21,194 |
| | main | planned | 60.5% -> 51.2% | -9.3 [-56.6, +7.1] | 0.383 -> 0.341 | 25% -> 32% | 79,439 -> -67,213 |
| | earlier | planned | 1 product-month: not testable | | | | |
| PROMO/LOW, min(served, last month) | main | all | 45.2% -> 45.8% | +0.5 [-5.8, +4.1] | 0.982 -> 0.823 | 70% -> 70% | |
| | earlier | all | 50.2% -> 43.3% | -6.9 [-19.8, -1.0] | 1.026 -> 0.811 | 112% -> 100% | |
| | main | planned | 32.9% -> 37.2% | **+4.3 [+0.2, +7.3]** | 0.683 -> 0.778 | 43% -> 50% | |
| | earlier | planned | 37.8% -> 41.7% | **+3.9 [+0.9, +6.9]** | 0.745 -> 0.807 | 124% -> 117% | |
| BURST2, family split (a) | main | all | 31.7% -> 32.2% | +0.5 [-2.6, +5.0] | 0.993 -> 1.063 | 28% -> 38% | |
| | earlier | all | 24.5% -> 23.7% | -0.8 [-2.2, +0.6] | 0.864 -> 0.860 | 30% -> 31% | |
| | main | planned | 33.5% -> 28.2% | -5.3 [-37.1, +6.5] | 0.295 -> 0.386 | 9% -> 15% | |
| | earlier | planned | 27.4% -> 25.9% | -1.6 [-4.8, +1.9] | 0.768 -> 0.740 | 31% -> 31% | |
| BURST2, own 12-month mean (control) | main / earlier | all | | +0.7 [-1.8, +7.0] / -1.9 [-4.2, -0.0] | 0.993 -> 1.192 / 0.864 -> 0.808 | | |
| STABLE, family split | main / earlier | all | | +1.5 [-1.2, +3.8] / +1.2 [+0.5, +1.9] | worse / equal | | |
| **SYSTEM without the promo treatment** | main | all | 41.5% -> 38.1% | **-3.5 [-7.3, -1.3]** | 0.776 -> 0.731 | 44.4% -> 44.0% | 1,502,371 -> 970,797 |
| | earlier | all | 30.5% -> 27.9% | **-2.6 [-4.4, -1.5]** | 0.888 -> 0.871 | 40.6% -> 40.2% | 3,223,097 -> 1,756,925 |
| | main | planned | 35.7% -> 32.3% | **-3.4 [-8.7, -0.2]** | 0.577 -> 0.585 | 33.4% -> 32.9% | 561,760 -> 221,646 |
| | earlier | planned | 29.0% -> 28.5% | -0.5 [-1.2, +0.2] | 0.772 -> 0.772 | 31.4% -> 32.0% | 1,443,070 -> 1,190,833 |
| SYSTEM as pre-registered (with promo) | main / earlier | all | 41.5% -> 38.1% / 30.5% -> 27.5% | -3.4 [-7.1, -1.2] / -3.0 [-4.9, -1.7] | 0.776 -> 0.692 / 0.888 -> 0.856 | | |
| | main / earlier | planned | 35.7% -> 33.0% / 29.0% -> 28.7% | -2.7 [-7.9, +0.6] / -0.3 [-1.0, +0.6] | 0.577 -> 0.598 / 0.772 -> 0.790 | | |

WAPE above 100% on SUCCESSION and FADING is the shrinking denominator: those rows sell almost nothing, so the
over-forecast pieces column is the plainer reading.

### December and January, the system without the promo treatment

| | Served pooled WAPE | System | Difference [95%] | MASE served -> system | MAPE served -> system |
|---|---|---|---|---|---|
| Dec 2025, all | 56.7% | 53.6% | -3.1 [-8.0, -0.5] | 0.809 -> 0.799 | 54.4% -> 53.3% |
| Dec 2024, all | 69.8% | 65.1% | -4.6 [-12.5, -0.5] | 1.357 -> 1.246 | 62.3% -> 62.3% |
| Jan 2026, all | 46.4% | 45.1% | -1.3 [-4.4, +0.9] | 0.707 -> 0.707 | 27.4% -> 28.3% |
| Jan 2024 + Jan 2025, all | 24.8% | 23.9% | -0.9 [-2.6, +0.4] | 0.940 -> 0.940 | 24.3% -> 25.0% |
| Dec 2025, planned | 56.6% | 52.2% | -4.4 [-13.5, -0.0] | 0.626 -> 0.590 | 47.4% -> 47.4% |
| Dec 2024, planned | 65.1% | 65.1% | 0.0 | 1.289 -> 1.289 | 62.1% -> 62.1% |
| Jan 2026, planned | 36.5% | 35.2% | -1.3 [-6.5, +2.0] | 0.569 -> 0.555 | 20.2% -> 20.2% |
| Jan 2024 + Jan 2025, planned | 20.6% | 21.1% | +0.5 [-0.0, +1.7] | 0.862 -> 0.872 | 23.4% -> 23.6% |

The system does not fix December. It removes the re-coded and fading rows from it, which is all the gain here.

### Which treatments hold out of window

| Treatment | All products | Planned products |
|---|---|---|
| SUCCESSION: last month | **Holds** (both windows, both intervals below 0, MASE lower) | Lower WAPE in both windows (interval below 0 in main only); MASE worse in the earlier window (10 products, 13 rows) |
| FADING: min(served, last 3 mean) | **Holds** (earlier interval below 0, MASE lower in both) | Main window lower, inside the noise; earlier window has 1 row, not testable |
| PROMO/LOW: min(served, last month) | Not holding (lower in the earlier window only; MASE lower in both) | **Worse in both windows** |
| BURST2: family split | Not holding | Lower in both, inside the noise; MASE worse in main |
| BURST2: own 12-month mean | Not holding | Not holding |
| STABLE: family split / 12-month mean | Worse in both | Worse in both |
| SYSTEM without promo | **Holds** | Lower in both (interval below 0 in main only); MASE +0.008 in main, equal in earlier |

## 3. Class by class

**SUCCESSION (a pattern the brief did not list).** When a code is re-coded (a new pack name, a size change of a few
grams, a new sachet strip), the old code stops selling, and the served forecast keeps forecasting it from its own past
for months. The detection needs no forecast: the old code's last month is under half its 12-month level while the same
brand and category starts a code with the same content per piece. About half the detected pairs are re-codes visible in
the name (SACHET -> STR SAC, LIQUID SEASONING -> TPR, 13ML -> 14ML, SOL -> STR); the rest are a collapse that coincides
with a launch. The treatment, following the old code down at once, is right in both cases. Untested: whether the new-code
condition adds anything over the last-month drop alone.

**FADING, and Surf Fabcon Blossom Fresh SOL 360X28ML.** Its sales fell to near zero in September 2025, the month a new code
(STR 360X28ML) took them over. That is a re-code, not a fade.

| Rule | First forecast month it acts on |
|---|---|
| SUCCESSION | September 2025 (the month of the fall) |
| Collapse flag (ratio 0.75 for September, 0.33 for October) | October 2025 |
| Served forecast | Never in the data. It was still forecasting the code for the March 2026 cycle, and the March plan ordered it. |

So the collapse flag, acting on the forecast, would have caught it for 6 forecasts (October 2025 through the March 2026
cycle) that the served system got wrong; the served system had still not caught it by March. The succession rule would
have caught it one month before the flag, for 7 forecasts. From October, the fading treatment's forecast for this code is a
fraction of the served one. It reaches 0 by January 2026 and is 0 for the March cycle. The plan was not re-run, so what
the LP would then have ordered is not measured.

**BURST sellers.** The pre-registered rule (Syntetos-Boylan CV^2 >= 0.49) found 1 product-month: Tier A demand is not
high-CV month to month. The Knorr items have CVs of 0.2-0.4 and are smooth series with sudden spikes. The post-hoc BURST2
rule (the LP's own MASE >= 1 entry test, applied month by month) catches them in 2 to 4 of their 6 main-window months,
after the spikes begin, never before. In the Knorr cube flavours, pork dropped and chicken rose in the same month with
stock on hand, a swap between flavours (correlation 0.03). The Sinigang and Surf powder flavours move together
(0.61-0.88), so a family total does not average their spikes out.

- (a) Family split, family MA3 x 12-month share: better in one window, worse in the other (all products). Dead end as a
  general fix.
- (b) No forecast, order up to the 95th percentile of the last 12 months (monthly review, zero lead time, lost sales).
  Against served + 1.645 sigma:

| BURST2 rows | Policy | Fill rate | Months short | Leftover, months of sales |
|---|---|---|---|---|
| Main, all (38 products) | served + safety | 98.9% | 5.6% | 0.666 |
| | cover target, no forecast | 97.4% | 10.0% | 0.564 |
| Earlier, all (80) | served + safety | 99.6% | 3.3% | 0.608 |
| | cover target, no forecast | 98.5% | 10.9% | 0.421 |

It is the same trade-off in both windows: 15% to 31% less leftover stock, two to three times the months short. Today the plan
excludes these products because their MASE is >= 1, so they get no recommendation at all. A cover target gives them one
that covers 97-98% of demand without a forecast. Whether that is wanted is a decision, below.

**PROMO, bundle and near-zero sellers.** As their own population, the served forecast scores pooled WAPE 45.2% (main) and
50.2% (earlier), MASE 0.98 and 1.03, MAPE 70% and 112%. They are 10.9% of main-window pieces. The treatment (never above
last month) is worse for the planned products in both windows, so they stay on the served forecast. Their accuracy should
be quoted on its own line, not pooled into a MAPE headline.

**NEW (under 6 months).** Bias +22.0% in the main window and -2.4% in the earlier one. Not consistent, so no treatment.

**STABLE.** The rest carries +569,138 pieces of over-forecast in the main window: the lag on a falling piece level. That
level is mostly mix (section 1). The mix-aware candidate, the family split, is worse in both windows.

## Dead ends, one line each

- Company-wide level correction: not built. The piece fall is about 85% composition (gate).
- Selling-day adjustment for December: the working-day ratio is about 0.87 every year; it cannot explain 1.20 vs 0.62.
- Stock-limited flag as a class: it fires on 44-56% of under-forecast months too, so it does not separate censored months.
- Syntetos-Boylan burst rule: it detects nothing in Tier A.
- Family split for STABLE products: worse in both windows (+1.5 and +1.2 points).
