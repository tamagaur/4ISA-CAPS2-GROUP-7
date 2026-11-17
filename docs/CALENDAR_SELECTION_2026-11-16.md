# The calendar adjustment under an out-of-sample protocol (2026-11-16)

Protocol, fixed and committed before any candidate was scored: `docs/CALENDAR_SELECTION_PROTOCOL_2026-11-16.md` (sha256
`27ae3eef679ff95303b8162f6d98ee687d982ec8b6ac4e8bb124fdf48e3d4cb3`, commits 260c72a then a30cd1a; the second replaced one
mechanism before any scoring). Code: `scripts/calendar_selection.py` (grid, folds, bootstrap) and `scripts/calendar_selection_analysis_1..3.py`
(the tables below; run from the repo root with `PYTHONPATH=.`). Inputs: the as-served Tier A panel without the factor (4,370 product-months,
2024-01..2026-02) and the demand read once, read-only. No live write, nothing applied. Scores are pooled WAPE on identical product-months;
every factor reads only months before its target.

## Answer
**Nothing beats what is live under this protocol.** Choosing on past months and testing on the next, the whole procedure scores 31.85%
on 2025-03..2026-02 against 31.93% for the live settings in this panel (the panel applies the factor before succession and fading, so this is not the card's live 31.95%, docs/EVALUATION_METRICS.md) and 33.39% for no factor: a tie with live (0.08 points). The pick differs by fold
(T1 a median-grain setting 0.16 points worse than live; T2 and T3 a gated setting 0.41 and 0.19 points better, intervals include zero).
No build and no rehearsal: nothing survives to rehearse. The live plan (115 rows, 330,212 pieces) is unchanged.

## Folds (choose on past, test on next; 95% product bootstrap of the change, 2,000 draws, seed 20261116)
| Fold | Chosen on | Pick | Held-out WAPE: pick / live / none | Pick vs live | Pick vs none |
|---|---|---|---|---|---|
| T1 | 2024-04..2025-02 | median grain, s 0.7, Dec rule | 28.64 / 28.48 / 29.16 (2025-03..08) | [-0.51, +0.75] pts | [-1.30, +0.23] |
| T2 | 2024-04..2025-08 | own-weight 4, s 0.7, Dec rule, gate "company and product agree" | 36.01 / 36.42 / 38.89 (2025-09..2026-02) | [-0.89, +0.07] | [-5.38, -0.40] |
| T3 (reverse, secondary) | 2025-01..2026-02 | same as T2 | 27.99 / 28.18 / 29.51 (2024-04..12) | [-0.46, +0.10] | [-2.31, -0.72] |

The factor (live or any pick) beats no factor in T2 and T3; in T1 it cannot be told from none. The pick changes from fold to fold, which is what a flat surface looks like.

## 2. The shrink (out of sample; own weight 2, Dec rule on, log scale)
| s | WAPE T1 | T2 | T3 | Bias T1 | T2 | T3 |
|---|---|---|---|---|---|---|
| 0 | 29.16 | 37.23 | 28.92 | +3.3% | +1.8% | +13.0% |
| 0.3 | 28.64 | 36.70 | 28.33 | +0.9% | +2.2% | +11.1% |
| 0.5 | 28.48 | 36.53 | 28.13 | -0.5% | +2.7% | +9.9% |
| 0.6 | 28.46 | 36.51 | 28.13 | -1.1% | +3.0% | +9.3% |
| 0.7 | 28.53 | 36.49 | 28.17 | -1.8% | +3.4% | +8.7% |
| 1.0 | 28.97 | 36.65 | 28.52 | -3.6% | +4.5% | +7.2% |

The curve is flat between 0.4 and 0.8; its minimum is 0.5-0.6 in T1 and T3 and 0.7 in T2. **0.5 was a sound choice and survives out of sample.**
The full factor (s 1) costs 0.4-0.5 points of WAPE against 0.5-0.6 and overshoots in T1 (bias -3.6%).
Independent check: regressing a month's realised log ratio on last year's gives slope 0.95 over all 23 pairs (December carries it) and 0.51 excluding December (21 pairs).
Ceiling: a perfect month-level scalar (in-sample, unreachable) gives 26.83% over 2024-04..2026-02 against 31.13% none and 29.65% live, so live closes 34% of the gap.

## 3. Grain (no Dec rule, geometric mean; held-out WAPE)
| Grain, s | T1 | T2 | T3 |
|---|---|---|---|
| company, 0.5 | 27.56 | 38.16 | 30.13 |
| company, 1.0 | 27.25 | 38.17 | 32.90 |
| product median, 0.5 | 28.71 | 37.19 | 28.42 |
| product median, 1.0 | 28.65 | 36.45 | 28.05 |
| own-weighted 2, 0.5 (live shape) | 28.48 | 37.39 | 28.83 |

**No grain is right throughout. The right one does depend on the month, but not on anything known beforehand.** Company wins T1 (March 2025: 18.0% against
25.6% for the product median) and loses T2 and T3 (December 2024: 79.4% against 43.8%). In the 23 months where both have an earlier year the two disagree on direction in 7; there the company grain was better in 3 (2025-03, 2025-05, 2025-11), the product grain in 3 (2024-12, 2025-06, 2025-09) and 1 tied. The gate "do nothing when they
disagree" was chosen in T2 and T3 and gains 0.2-0.4 points over live there (not distinguishable from zero); T1 chose against it. **March is the open case:**
company ratio 1.136 / 1.169, product median 0.906 / 1.033 in 2024 / 2025, so the grains disagree on direction every March. The gated pick leaves March 2026 at 1.000;
live gives a median 0.986 (range 0.710-1.261).

## 4. Does it improve with history?
Weakly, and only for the simplest estimator. On the 11 months with two earlier years (2025-04..2026-02) the median-grain factor at s 1 gains 1.47 points of WAPE
over no factor with one year and 2.18 with two. The own-weighted factor gains nothing from the second year (33.67 against 33.71 at s 1) and per-month bias is mixed.
Last year's ratio explains 38% of this year's (corr 0.62, 23 pairs; 18% excluding December), so the ceiling is the year-to-year instability of the ratio (July product median
0.92, 0.85, 0.76; December 0.95, 0.65, 0.48), not the shrink. **March 2026 has two usable earlier years, not three:** March 2023 has no three prior months, so it yields no ratio.
For a system that runs for years the median across more years should steady the estimate; these 23 pairs suggest it but cannot say by how much.

## 5. The December rule
**It cannot be tested out of sample.** It was written after December 2024 and December 2025 were both seen, and those are its only two applications (December 2023's
product median 0.950 drives 2024, 0.651 drives 2025; for December 2026 it would apply 0.482 in full). December 2024 WAPE: 51.0% none, 52.4% factor without the rule, 43.8% with.
December 2025: 57.1%, 50.2%, 42.9%. Over 2024-04..2026-02 it takes WAPE from 30.13% to 29.66% (0.47 points), **31.8% of the whole factor's gain in pieces** (it adds exactly zero outside
the two Decembers), and December 2025's bias goes from +48% (no factor) to -4.7%. That is its in-sample gain. Its first honest test is December 2026, and applying last December in full is a real risk if the dip does not repeat.

## 6. Mechanism C (seasonal-naive blend)
Fails. At a = 0.1 held-out T1 / T2 / T3 are 28.82 / 38.64 / 29.65 against none 29.16 / 38.89 / 29.51; worse from a = 0.3, and 33.65 / 47.82 / 38.60 at a = 1. Defined on 62% of rows.

## March and July: does it correct them?
| Month | Bias, no factor | Live | Full factor (s 1, own 2) | Gated pick |
|---|---|---|---|---|
| March 2024 | -16.6% | -16.6% (no earlier year) | same | same |
| March 2025 | -13.9% | **-15.6% (worse)** | -17.3% | -13.9% (no adjustment) |
| July 2024 | +28.5% | +23.9% | +19.3% | +21.7% |
| July 2025 | +33.3% | +25.8% | +18.3% | +22.4% |

Live takes 4.6 and 7.5 points off July and moves March 2025 the wrong way. A full factor takes 9-15 points off July and makes March worse still. **No candidate corrects both**, because the
products' own March ratio and the company's point opposite ways.

## What I did not do, and the limits
- Item 6 (build, rehearse, stock-out price, March plan before and after): nothing survived, so none was built. The March 2026 plan stays 115 rows / 330,212 pieces (lp_run 10).
- The succession and fading treatments act after the factor in the router; the panel multiplies before them. The live factor reproduces to 1e-6 on every untreated row (4,219 of 4,370 exact), WAPE 28.88% against 28.87% stored.
- 26 target months and one to two earlier years: every fold has a few months, so intervals are wide. The T3 fold chooses on later years and is secondary.
