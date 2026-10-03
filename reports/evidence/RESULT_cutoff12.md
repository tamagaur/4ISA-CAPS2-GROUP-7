# Result — long-bin cutoff 24 → 12

Pre-registration: `reports/evidence/PREREG_cutoff12.md` (commit 14657c2, before any computation).
Script: `reports/evidence/cutoff12_run.py`. Outputs: `cutoff12_checks.csv`, `cutoff12_results.csv`.

**Verdict: KEEP.** The challenger scores T on the full window (and T in all 4 testable blocks). Only the KEEP rule fires; SWITCH-CANDIDATE and INCONCLUSIVE do not. The long-bin cutoff stays at 24.

## Sources
- Forecasts: stored, `reports/experiment_artifacts/preds_plus.csv.gz` — columns `tsb`, `ma3`, `ens_xgb_ma3@A` (= 0.5 × `xgb_abs@A` + 0.5 × `ma3`; max deviation 8.7e-11).
- XGBoost refits: **0**. No medium-bin SKU-month lacked a stored challenger, so the refit reproducibility check had nothing to run on.
- Bins: DEC-26 length rule on sales months at forecast time. Five SKU-months that the bake-off labelled `intermittent` (12–15 sales months) fall in medium under that rule (still 89 SKUs); 15 fall in short.

## Checks (all pass)
| check | result |
|---|---|
| read-only transaction; is_demo rows in `_Real` view | on; 0 |
| Tier A 2026-02 single, from the DB / preds_plus SKUs inside it | 132 / 119 of 119 |
| stored sales months and actuals == recomputed from `Unilever_SKU_Demand_Fact_Real` | 2,711 / 2,711 each |
| TSB (`baseline.tsb_forecast`, 0.3/0.1) recomputed == stored, tolerance 1e-9 relative (fixed before the run) | 2,711 / 2,711; 2,306 bit-identical, max abs diff 8.7e-11 |
| medium SKU-months / missing challenger / missing TSB | 1,002 / 0 / 0 |

## Medium bin (12–23 months): XGBoost + MA3 average vs TSB — the verdict
Median per-SKU WAPE; interval = 95% bootstrap on (average − TSB); better/worse = SKUs.

| window | SKU-months | SKUs | average | TSB | 95% interval | better / worse | score |
|---|---|---|---|---|---|---|---|
| full 2023-10..2026-02 | 1,002 | 89 | 0.261 | 0.250 | [−0.011, +0.019] | 33 / 56 | T |
| 2023-10..2024-02 | 79 | 0 | – | – | – | – | NT (no SKU has ≥ 3 origins; medium starts 2024-01) |
| 2024-03..2024-08 | 297 | 49 | 0.163 | 0.156 | [−0.006, +0.020] | 16 / 33 | T |
| 2024-09..2025-02 | 305 | 65 | 0.304 | 0.298 | [−0.013, +0.036] | 22 / 43 | T |
| 2025-03..2025-08 | 174 | 28 | 0.281 | 0.285 | [−0.040, +0.022] | 15 / 13 | T |
| 2025-09..2026-02 | 147 | 25 | 0.332 | 0.350 | [−0.084, +0.062] | 15 / 10 | T |

MASE < 1 pass share (full window): TSB 76.4% (68/89), average 73.0% (65/89).

## Side result (not part of the verdict): short bin (3–11 months), average vs MA3
| window | SKU-months | SKUs | average | MA3 | 95% interval | better / worse | score |
|---|---|---|---|---|---|---|---|
| full | 691 | 114 | 0.284 | 0.273 | [−0.013, +0.028] | 45 / 69 | T |
| 2023-10..2024-02 | 226 | 61 | 0.216 | 0.194 | [−0.003, +0.052] | 14 / 47 | T |
| 2024-03..2024-08 | 122 | 23 | 0.302 | 0.347 | [−0.070, +0.052] | 12 / 11 | T |
| 2024-09..2025-02 | 128 | 22 | 0.380 | 0.354 | [−0.028, +0.060] | 11 / 11 | T |
| 2025-03..2025-08 | 76 | 17 | 0.192 | 0.202 | [−0.039, +0.024] | 10 / 7 | T |
| 2025-09..2026-02 | 139 | 25 | 0.405 | 0.472 | [−0.113, +0.007] | 17 / 8 | T |

MASE < 1 pass share (full window): MA3 67.5% (77/114), average 64.0% (73/114). Short-bin rows where the stored XGBoost has no value are excluded (SKU-months where both exist).

## Status
Exploratory: these months were also used to set the cutoffs. Under the pre-registered rule, KEEP settles the question. No production code or rule was changed.
