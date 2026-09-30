# Pre-registration — long-bin cutoff 24 → 12

- Population: Unilever Tier A products (ABC 2026-02, single) in the medium bin (12–23 sales months at forecast time, DEC-26 length rule), same rolling one-step protocol, 5 half-year blocks 2023-10 → 2026-02, same two-condition WAPE test as the bake-off (95% bootstrap over SKUs, 1,000 resamples, seed 20260921), a block testable when ≥ 5 SKUs have ≥ 3 origins.
- Challenger: XGBoost + MA3 average (w = 0.5) vs incumbent TSB (α 0.3 / β 0.1), per SKU-month where both exist.
- Verdicts: SWITCH-CANDIDATE if the challenger scores W on the full window AND W in a majority of testable blocks AND L in none; KEEP if it scores T or L on the full window, or L in any block; INCONCLUSIVE if fewer than 3 testable blocks.
- Status: exploratory — these months were used to set the cutoffs, so SWITCH-CANDIDATE is a lead to confirm on SSM's 2026 months before any change to the live rule; KEEP settles it.
- Also report (not part of the verdict): same comparison for 3–11-month products (XGBoost + average vs 3-month average), and MASE < 1 pass share per model.
