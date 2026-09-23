# Why some SKUs are unfit

*Unilever Tier A cohort as of 2026-02 · written 2026-09-23 · all numbers cite the file they come from*

## Summary (read this alone if you read nothing else)

Twenty-eight of our 132 top Unilever SKUs fail the forecast accuracy gate. We checked
whether that was a data problem: it is not — every unusual month traces back to the
source file exactly, with nothing missing and nothing dropped by the loader. It is real
demand. The reason those SKUs score badly is timing: for 20 of the 27 SKUs we could
measure, the big change in their sales level happens *inside* the six months we score
them on, and eight of those changes land in December 2025. A forecast made before a
change cannot know about it. We then tested 51 alternative forecasting models on exactly
these 28 SKUs, and none of them passed our test for being measurably better — including
every kind of smoothing. So we are not changing the model. We flag these SKUs for human
review, we keep their wide uncertainty ranges visible rather than hiding them, and we
leave stock buffering to the ordering side of the system. We also have one question for
SSM: what happened around December 2025?

---

## 1. The question

28 of our 132 Tier A SKUs fail the accuracy gate (`fit_review_common_2026-09-23.csv`,
`verdict` column). Why, and what did we do about it?

## 2. What "unfit" means here

We score every SKU on the **same six months — September 2025 to February 2026** — so no
SKU gets an easier test than another. The score is **MASE (Mean Absolute Scaled Error)**.
It compares our forecast error against the error you would get from the simplest possible
guess: *next month will be the same as this month*. MASE of 1.0 means we did exactly as
well as that naive guess. Below 1.0 means we did better. **We call a SKU "unfit" at MASE
1.1 or above** — meaning our forecast was at least 10% worse than just repeating last
month. That threshold was fixed in writing before anything was computed
(`reports/diagnostics/README.md`).

Two other terms used below: **MA3** is the 3-month moving average, the model we serve for
short-history SKUs and use as the benchmark for every SKU. **TSB** is a trained
statistical model we serve for medium-history SKUs. Where they have been compared on real
Tier A data, TSB and our other trained model **tie** with MA3 — they are served because
they are trained models that use a SKU's full history, not because they are more accurate
(DEC-26).

## 3. Finding 1 — the data is correct

We traced every unusual month on all 28 SKUs back through the pipeline to the raw file
(`incident_check_2026-09-23.csv`, 59 flagged SKU-months):

| what we found | count |
|---|---|
| spikes that match the raw source file **exactly** | 58 |
| genuine zero (no sale that month, file present and normal) | 1 |
| missing data | 0 |
| rows dropped by a loader rule | 0 |

No month is missing. No period of the source file is short — rows per month range 560 to
779 against a median of 654, and none falls below our low-water mark. No period shows an
unusual number of SKUs dropping together; the worst is 2 SKUs out of 72 (2.8%).

**So this is real demand behaviour, not a pipeline defect.** That is the single most
important sentence in this document.

## 4. Finding 2 — it is a timing problem

For **20 of the 27** SKUs where we could measure it, the largest change in sales level
happens *inside* the six months we score them on, and **8 of those land in December 2025**
(`fit_review_common_2026-09-23.csv`, `cause_largest_step_month`).

Why that matters: a forecast for October is made using data up to September. If a SKU's
demand permanently halves in October, the October forecast was built from a world where it
had not halved yet. No model can forecast a change it has not seen. It can only react
*after* the change shows up — which is what MA3 does, and why it takes about three months
to catch up. Scoring a SKU on precisely the months when it changed is close to the hardest
possible test.

**Worked example — SKU 64784425** (medium history, served by TSB):

- Its recent level fell to **0.60** of its 12-month level — it was selling about 40% less
  than it used to (`fit_review_common_2026-09-23.csv`, `recent_level_ratio`).
- TSB forecast **14,845** units for the planning month; MA3 said **9,862** — TSB is 51%
  higher, because TSB is still weighted toward the SKU's older, larger history
  (same file, `forecast_value` / `ma3_value`).
- On the shorter original test window it scored MASE **2.32**, and MA3 on the same months
  scored **2.55** (`fit_review_2026-09-23.csv`). On our common six-month window it scores
  **1.69**, and MA3 **1.82** (`fit_review_common_2026-09-23.csv`).

Read that last line carefully: **both models fail, and they fail together.** This is not
TSB being a poor choice. It is a SKU whose demand moved and neither model was told.

## 5. Finding 3 — no model fixes it

We took 51 candidate forecasting models whose predictions were already stored from the
earlier bake-off (`reports/experiment_artifacts/preds_plus.csv.gz`) and scored every one
of them on **only these 28 SKUs**.

Our rule for saying one model is measurably better than another has two conditions, both
required: the statistical confidence interval on the difference must be entirely on one
side of zero, **and** more SKUs must improve than get worse (`analytics/forecasting/switching.py`).

- **0 of 51 passed.** Every one came out a tie.
- Across 51 models × 5 half-year test blocks: **2 wins, 241 ties, 7 losses.**
- Those 2 wins are one block each, out of five, with no overall result clearing the bar.
  They are what two equally-good models produce by coincidence, not evidence.
- There is a second reason to discount them: **these 28 SKUs were chosen because they
  scored badly.** Anything that looks good on a group picked for looking bad needs to
  prove itself on a fresh, untouched period before it means anything.
- **MA3 also fails on all 25** of the not-fit SKUs where we can compare it
  (`fit_review_common_2026-09-23.csv`, `ma3_also_fails_common`). The benchmark fails too.

## 6. Why smoothing cannot be the answer

The instinct is "smooth out the bumps." But MA3 — what we already run — *is* smoothing.
And the problem is that these 28 SKUs have **two opposite problems mixed together**:

- **A one-off spike** (a promo month, a bulk order) wants **more** smoothing, so one odd
  month doesn't drag the forecast. Models covering this that we tested: MA6, MA12, med_3
  and median3 (median-based, deliberately resistant to outliers), SES (exponential
  smoothing) and damped Holt.
- **A permanent level change** wants **less** smoothing, so the forecast catches up fast.
  Models covering this that we tested: naive (just repeat last month), MA2, drift and Holt.

Turn one dial and you fix one group while making the other worse. That is exactly why all
51 came out flat. **CV** below means *coefficient of variation* — the standard deviation
divided by the average, a plain measure of how much a SKU bounces around month to month.

## 7. Finding 4 — a cause is a description, not a diagnosis

We group each SKU by what its sales history *looks like* — spiky, level shift, high
volatility (high CV), tiny scale, intermittent, trend reversal — using thresholds fixed in
advance and recorded in `reports/diagnostics/README.md`.

But the same shapes appear in SKUs that forecast perfectly well
(`fit_review_common_2026-09-23.csv`, `cause_group` × `verdict`):

| cause group | clean SKUs | not-fit SKUs |
|---|---|---|
| spiky | **43** | 9 |
| level shift | **9** | 9 |
| high volatility | 4 | 5 |

Forty-three SKUs are spiky and forecast fine. So "spiky" does not explain why a SKU is
unfit — it only describes the series. We publish causes as description, and we do not use
them to diagnose or to define a new SKU grouping.

## 8. What we do instead

1. **Flag these 28 for human review on the dashboard.** Show the planner the plain fact —
   "this SKU's recent sales are 60% of its usual level, check before ordering." A person
   who knows whether a customer was delisted can settle that; a model cannot. This follows
   a decision already on record for one SKU (DEC-26, product 674) — we are extending it.
2. **Keep the uncertainty range visible and honest.** The typical range on these SKUs is
   about **1.2× the forecast value** — roughly plus or minus 60%
   (`fit_review_common_2026-09-23.csv`, `band_width_over_forecast_stored`). Be precise
   about what that range is: it is an **error range built from the model's own past errors
   on the same months it is measured on** (in-sample), and **no confidence level for it is
   documented in our decision record** (DEC-25 states the method, not a level). It is a
   useful "how wrong have we been on this SKU" indicator. It is **not** a validated
   statistical confidence interval and must not be presented as one.
3. **Leave stock buffering to the ordering side.** Extra safety stock on unpredictable
   SKUs is the right answer, but that is a prescriptive decision under hold, so it waits.

## 9. What we did not do, and why

- **We did not edit the spikes out of the data.** They are what SSM reported. Smoothing
  them away in the stored history would make our numbers look better by changing the
  client's records — the exact thing our anti-fabrication rule forbids.
- **We did not swap models per SKU.** Picking whichever of the 51 happened to score best
  on each SKU is choosing with hindsight. We measured it: it is a ceiling, not a strategy.
- **We did not create a bin or rule defined by fit results.** Grouping SKUs by "these ones
  forecast badly" and then reporting that the group forecasts badly is circular.
- **We did not relax the test rule** to let a candidate through. The two-condition test is
  the same one used everywhere else in this project.

## 10. Open question for SSM

**What happened around December 2025?** Eight of these SKUs have their largest level
change in that single month, and more sit in the surrounding window. A delisting, a
promotion ending, a supply interruption or a competitor entering would explain several at
once — and it is a business fact no model can recover from the numbers alone. An answer
here would tell us whether these are temporary dips to ride out or permanent declines to
plan around. That distinction changes the order quantity; it does not change the model.

---

**Caveat on sourcing.** One set of numbers in section 5 — the 51-candidate table, the
0-of-51 pass count and the 2/241/7 block record — was computed in analysis over
`preds_plus.csv.gz` and is **not currently written to a file in this repository**. Every
other number cites a committed file. If that table needs to be auditable, it should be
exported before it is quoted in the manuscript.
