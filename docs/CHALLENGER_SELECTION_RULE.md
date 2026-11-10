# Challenger selection rule (committed 2026-11-10, before any comparison)

This rule decides, once a year, whether the challenger forecast should replace the served one. It was written and
committed **before** the two were compared on any month. The commit that adds this file is the proof: anything run
that compares the two must come from a later commit. Its only implementation is `analytics/forecasting/selection_rule.py`.

## What is compared

| | Served | Challenger (`damped_trend_v1`, `analytics/forecasting/challenger.py`) |
|---|---|---|
| Short history (3-11 sales months) | MA3 | MA3 (the same) |
| Medium (12-23) | TSB | damped-trend exponential smoothing |
| Long (24+) | (XGBoost + MA3) / 2 | damped-trend exponential smoothing |
| Guards, zero floor, calendar factor, dead-SKU rule | as served | the same, applied the same way |

Both are computed for every Unilever product the forecast run covers (Tier A the month before), every month, and stored
side by side. Why this challenger: see the module docstring. In short, the 2026-11-10 diagnosis named lag on a falling
level as the main reason the forecast ran high. A trend term addresses that; a median of 3 addresses a single spike,
which explained 4 of the 38 testable runs. Damped Holt was in the 2026-09 bake-off and was not better than MA3 there.

## When

**At the December/January turn, every year**: after December's real sales are loaded, before January's forecast run is
written. The first scheduled point is the 2026/2027 turn.

## On which months

- January to December of the year that is closing, only months with real sales loaded.
- **Never** 2025-09 to 2026-02. The diagnosis looked at those months, and the challenger was chosen on them.
- The rows are the stored pairs: the forecast made for that cycle where one was stored, otherwise the backtest pair
  computed with the same code as of that month.
- A product-month is scored only when the actual and both forecasts exist, so both are always scored on identical rows.
- The actual is the one the as-served accuracy uses (`scripts/accuracy_as_served.py`): a net-negative month counts as 0,
  a month with no row counts as 0, and a blank quantity is not scored.
- **Minimum: 6 evaluable months** (one half-year, the block of DEC-26's model tests). With fewer, the result is
  *insufficient* and the served model stays. At the 2026/2027 turn that means at least 6 of 2026-03 to 2026-12 must have
  real sales.

## The decision

Measure: pooled WAPE in pieces, sum |forecast - actual| / sum |actual|. This is the Dashboard's "typical product,
weighted by sales". Delta = WAPE(challenger) - WAPE(served).

The challenger is **recommended** only if all four hold:

1. Delta < 0 over the evaluation months.
2. Delta < 0 in the first half of those months (in month order; with an odd count, the second half has one more).
3. Delta < 0 in the second half.
4. The 95% interval of Delta lies entirely below 0. The interval comes from a bootstrap that resamples products with
   replacement (a product's months stay together), 2,000 draws, seed 20261110, percentile interval.

Otherwise the served model stays. Ties and doubtful results go to the served model.

Reported beside the verdict but never deciding it: median product WAPE, net bias, surplus share of the miss, and the
count of products 3 months in a row too high, for each.

## What the verdict does

Nothing automatically. It is a recommendation to the team. A switch is a decision recorded as a DEC entry in
ARCHITECTURE.md by the people who own the forecast, after they have seen the evidence. No code reads the verdict to change
what is served.

## Changing this rule

Not after a comparison has been seen. A changed rule (or a changed challenger) is committed before the next turn and
applies from it. A changed challenger also needs its stored history recomputed with the new code before it is compared.

## Comparisons run on past turns

These are reported as evidence, run after this commit, and switch nothing. The 2024/2025 turn compares 2024-01 to
2024-12. The 2025/2026 turn compares 2025-01 to 2025-12, which leaves 2025-01 to 2025-08 once the seen months are
removed. The 2023/2024 turn would have 2023-10 to 2023-12 only (the backtest starts 2023-10), so it is *insufficient*.
