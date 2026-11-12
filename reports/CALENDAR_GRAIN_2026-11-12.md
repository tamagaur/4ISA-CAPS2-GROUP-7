# The calendar factor computed at the grain it is applied at (2026-11-12)

For: the panel and the adviser, and whoever writes the chapter text. Status: built and rehearsed on a restored copy of live
(branch `kelvin/calendar-grain`); not on the live system until `python -m scripts.apply_calendar_grain --target-public` runs, and
that command refuses to finish unless live reproduces the rehearsal. Aggregates only.

## 1. The defect
The calendar factor (team decision DEC-41) multiplies each product's forecast by how that calendar month has sold against the
three months before it in earlier years. It was computed from the **company total** and applied to **every product**. The company
total is weighted by volume, so a few large products set it.

Evidence (`Unilever_SKU_Demand_Fact_Real`, 419-543 products per month-year, 35 month-years 2023-04 to 2026-02):
- In **4 month-years** the company ratio and the typical product moved in **opposite directions**: 2023-06, 2023-12, 2024-03, 2025-06.
- In **8 more** they agreed in direction but differed by over 10%.
- The company ratio equals the same products' volume-weighted ratio in those months: the cause is weighting by a few large products,
  not products entering or leaving.
- Live's March 2026 factor (1.0762, applied to all 175 forecasts) rests on March 2024 (company 1.136; typical product 0.906, with 61%
  of products below their prior three months) and March 2025 (1.169 against 1.033). At product grain the same formula gives 0.984.

## 2. How the fix was chosen (criteria fixed before any result)
- **Measure the system is built on:** pooled WAPE (the pieces the order plan gets wrong) and median MASE (the typical product, and
  the plan's entry test). MAPE is reported but not used to choose: it is undefined at zero and rewards forecasting low.
- **Bar** (unchanged since 2026-11-10): on identical product-months, pooled WAPE lower in both windows (Sep 2025-Feb 2026 and
  Jan 2024-Aug 2025), a 95% product-bootstrap interval below zero in at least one, median MASE not higher in either.
- **Candidates:** the typical product's ratio for every product; the typical ratio within the product's volume third; each product's
  own ratio pulled toward the typical product's (weight n / (n + 2) for n own years). All halfway to 1, as before.
- **All three passed.** The rule picked the lowest average WAPE: each product's own ratio pulled toward the typical (32.341% against
  32.343% for the plain typical ratio: a tie in practice).
- **Then each earlier idea was scored on top of it, same bar:** the December rule (last December's typical-product dip in full)
  **passed**: at product grain December 2023 was a dip too (median 0.950), so the rule now acts in December 2024 as well as 2025 and
  can be tested in both windows. The spike cap **failed** (no interval below zero). The blind seasonal rule **failed** (MASE higher in
  the earlier window).

## 3. Results (same products and months before and after)

| Measure | Window | Before | After | Products |
|---|---|---|---|---|
| Pooled WAPE (backtest), 95% interval of the change | Sep 2025-Feb 2026 | 38.07% | **36.33%** [-3.43, -0.19] | 208 |
| | Jan 2024-Aug 2025 | 27.86% | **27.24%** [-0.91, -0.34] | 270 |
| Median MASE, interval | Sep-Feb | 0.731 | **0.646** [-0.132, -0.019] | 192 |
| | Jan 2024-Aug 2025 | 0.901 | **0.869** [-0.080, +0.016] | 188 |
| Company-total WAPE (the card) | Sep-Feb / earlier | 13.30% / 10.23% | **7.22% / 9.07%** | 208 / 270 |
| Pooled product WAPE (the card) | Sep-Feb / earlier | 38.27% / 27.88% | **36.53% / 27.25%** | 208 / 270 |
| MAPE, median product (the card) | Sep-Feb / earlier | 41.0% / 34.6% | **35.2% / 32.8%** | 183 / 237 |
| Products under 20% / at 100%+ MAPE | Sep-Feb | 24 / 39 | **31 / 34** | 183 |
| Planned products' pooled WAPE | Sep-Feb / earlier | 32.63% / 28.47% | **31.07% / 27.82%** (intervals below 0 in both) | 107 / 90 |
| Products passing MASE < 1 (enter the plan) | March 2026 | 110 of 175 | **115 of 175** | |
| Order plan rows / pieces | cycle 2026-03 | 110 / 378,700 | **115 / 330,212** (-12.8%) | |
| March forecast, total pieces | | 1,952,313 | **1,837,121** (-5.9%) | 175 |

**What it costs.** The old factor raised every product by the company's volume-weighted rise; the new one does not, so forecasts are
lower for most products and more months run short. Over the 29 backtest months, Tier A product-months whose demand exceeded forecast
plus safety stock rise from **797 to 852** (+55), and the pesos beyond safety stock from **PHP 40.49M to PHP 43.77M** (+PHP 3.27M,
about PHP 113k a month). On the card, money lost to under-forecasting rises PHP 25.84M -> 28.29M (Sep-Feb) while money tied up by
over-forecasting falls PHP 35.34M -> 28.58M.

Every figure, including the plan by urgency and category and the Chapter 4 code figures: `docs/CHAPTER4_MOVED_FIGURES_2026-11-11.md`
section 9.

## 4. Were the spike cap, the December rule and the blind rule this defect in disguise?
- **December rule: yes, in part.** It could not be tested before because the company total rose in December 2023 while the typical
  product fell. At the right grain it is testable in both windows, and it passes.
- **Spike cap: it adds nothing that survives** once the grain is fixed (no interval below zero in either window).
- **Blind rule: it adds nothing** (the months it acted on are now carried by each product's own factor; MASE gets worse in the
  earlier window).

## 5. Limits to state
- 38 months of real data: each calendar month has two or three earlier occurrences at most.
- The December rule's cause (holiday break, new quota) is the team's reading; SSM has not confirmed it.
- The stock-out price above is a backtest of past months, at the current safety-stock service level (90%).
- DEC-41's description ("the company calendar factor", 1.0762) no longer describes the system once this is applied.

## 6. Checked and left alone
- Supplier allocation and warehouse capacity: aggregate limits by design, not a factor applied to products.
- Default procurement cost (PHP 33.48 per piece): an average applied to a product only when its own cost is missing; 0 of the 110
  planned products use it.
- Three non-serving scripts still use the company factor (the challenger experiment, the legacy run-7 recreation, a bias diagnosis).
