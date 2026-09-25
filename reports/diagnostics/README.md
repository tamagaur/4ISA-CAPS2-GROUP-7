# reports/diagnostics — fit review, cause groups and the thresholds on record

Read-only diagnostics on the Unilever **Tier A cohort as of 2026-02** (ABC method
`single`, 132 SKUs). Nothing here changes a rule, a bin or a served model.

## Files

| file | what it holds |
|---|---|
| `fit_review_2026-09-23.csv` | v1 scoring — each SKU's own last-20% holdout (`train_holdout_split`). Superseded for verdicts by the file below; kept so the two scorings can be compared. |
| `fit_review_common_2026-09-23.csv` | v2 — the **common holdout 2025-09…2026-02**, plus the stored pipeline metrics side by side, plus the Part A **cause group**. 132 rows. |
| `incident_check_2026-09-23.csv` | every flagged (spike / zero / absent) SKU-month on the 28 not-fit SKUs, traced to the fact row, the staged raw row and the source file. |

## Verdict vs assessability (independent columns)

- `verdict` — `clean` / `borderline` / `not fit`, from MASE. **Never overridden by
  holdout length.** `verdict_source` names which scoring produced it: `common`
  (107 SKUs) or `pipeline (20% split)` (12 short-bin SKUs the common window
  cannot score — 8 launched at or after 2025-09, 4 have an all-zero pre-window
  series so `naive_scale` is 0 and MASE has no denominator).
- `assessable` — `yes` for the 119 SKUs with ≥3 months of sales; `no` only for
  the 13 provisional SKUs. These are the only genuinely unassessable ones.

## Verdict thresholds (fixed before computing, 2026-09-23)

| flag | threshold |
|---|---|
| not fit | MASE ≥ **1.1** |
| borderline | **0.9** ≤ MASE < 1.1 |
| recent level | mean(last 3) / mean(last 12) outside **0.7–1.3** |
| diverges from MA3 | \|served − MA3\| / MA3 > **50%** on the planning-month forecast |
| band coverage | **no pass/fail.** DEC-25 states no coverage level; it only says the band is the served model's holdout RMSE. `CONFIDENCE_Z = 1.645` (`scripts/run_baseline_forecast.py`) is commented "~90%". Every coverage column is **in-sample** — the RMSE is fitted on the same residuals it is scored against (`coverage_basis` records this on each row). |

## Cause groups — rules, precedence and thresholds

One cause group per SKU: the **first** rule that fires in this precedence.

> `level shift` > `intermittent` > `high volatility` > `spiky` > `tiny scale` > `trend reversal` > `none of the above`

| rule | fires when | threshold | source of the threshold |
|---|---|---|---|
| level shift | mean(last 6) / mean(prior 12) outside 0.7–1.3 | **0.7 – 1.3** | the same band already used for `recent_level_ratio`; needs ≥18 months, else null |
| intermittent | zero-or-missing share ≥ 0.30 **or** longest zero run ≥ 3 | **0.30 / 3 months** | declared before computing; fires on **1** of 132 SKUs — intermittency is effectively absent from this cohort |
| high volatility | CV(last 12) > cohort p75 | **0.4365** | measured: 75th percentile of CV(last 12) across the 119 scored SKUs |
| spiky | ≥1 month more than 3 MAD from the SKU's median | **3 × MAD**, MAD raw/unscaled | declared before computing |
| tiny scale | median monthly units ≤ cohort lower quartile | **812.5 units** | measured: 25th percentile of median monthly units across the 119 scored SKUs |
| trend reversal | sign(Theil-Sen slope, last 12) ≠ sign(Theil-Sen slope, full history), neither zero | sign flip | declared before computing |

Both measured thresholds come from the **119 scored Tier A SKUs as of 2026-02**.
They are cohort-relative descriptors, not gates: recomputing them on a different
cohort or period will move them, so any re-run must state the cohort it used.

Columns carrying the numbers: `cause_group`, `cause_level_shift`,
`cause_largest_step_month`, `cause_cv_last12`, `cause_zero_missing_share`,
`cause_longest_zero_run`, `cause_n_spikes`, `cause_mad`, `cause_median_units`,
`cause_trend_reversal`, `cause_n_months`, and one `cause_is_<rule>` flag per rule
(the flags are **not** exclusive — `cause_group` is only the first match).

## Cause group × verdict (132 SKUs, 2026-09-23)

| cause group | clean | borderline | not fit | no verdict |
|---|---|---|---|---|
| spiky | 43 | 7 | 9 | 0 |
| level shift | 9 | 6 | 9 | 0 |
| high volatility | 4 | 1 | 5 | 0 |
| tiny scale | 3 | 0 | 3 | 1 |
| intermittent | 1 | 0 | 0 | 0 |
| none of the above | 14 | 3 | 2 | 12 |

**A cause is not a diagnosis.** Every cause group also contains SKUs that fit
well — 43 clean SKUs are "spiky", 9 clean SKUs show a level shift. Read the cause
as *what the series looks like*, never as *why this SKU is unfit*, and never as a
candidate bin: a bin defined by fit results would be circular.

## Standing caveats

- The 28 not-fit SKUs are **not a data problem**. `incident_check_2026-09-23.csv`
  traces all 59 flagged months: 58 spikes match the staged raw row exactly, 1 is a
  real zero, 0 are missing data, 0 were excluded by a loader rule. No period shows
  a cohort-wide drop (worst is 2 of 72 SKUs, 2.8%).
- `etl_quarantine` **exists in `public` and is empty** — migration
  `0024_etl_quarantine.sql` was applied in batch 1 of the recovery cutover
  (2026-09-23, see `reports/PROJECT_STATE_2026-09.md` §17.2). It holds 0 rows, so it
  can neither confirm nor contradict an exclusion. The "0 excluded by rule" result
  rests on the raw-vs-fact reconciliation, not on a quarantine lookup.
  *(Earlier revisions of this file said the table was absent from `public`; that was
  true when written, before batch 1 ran the same day.)*
- Anything selected *because* it scored badly (the 28) cannot be used to justify a
  model change on its own — a win on a selected subset is the selection problem,
  not evidence. Of the 50 candidate models scored on these 28, **none** passed the
  two-condition test (95% bootstrap interval on the median per-SKU WAPE difference
  clear of zero, seed 20260921, 1,000 resamples, **and** more SKUs improving).
