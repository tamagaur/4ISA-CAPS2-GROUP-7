# Monthly batch and feedback loop: how to run it, and the rehearsal of 2026-11-02

Written for: the team members who will run the month, or defend it.

**Nothing here is a result.** The rehearsal ran on the throwaway local database (a copy of the 16 Oct backup, migrated to 0069) with generated March sales, so its plan is not the live plan and its accuracy figures are not accuracy. Nothing was written to live.

## Changed later on 2026-11-02: read this first

Generated sales are now `is_demo = true` and exist only in `ssm_practice`, a local copy. When this was written no page read it except the batch panel; since 2026-11-04 `scripts.local_app` serves every page from it, each answer labelled (`backend/practice_copy.py`), with forecast error withheld on the generated month. Everything below that ran on generated sales ran with them stored `is_demo = false`, on the 16 Oct backup. The current run is this one.

**The practice month, labelled, end to end (run across midnight 2026-11-02/03).** Rule 2, path 2 in `CLAUDE.md`. Nothing here is a result.

| Step | Outcome |
|---|---|
| Start | `backups/full_backup_20261102T114428Z`: 109 rows, 435,988 pieces |
| Load | 709 generated rows, `is_demo = true`, tagged `qa_synthetic_march` (they replace that copy's 644 retired backfill rows for March) |
| ABC, forecast, LP, marts | Exit 0 in 2 min 9 s. 185 `ok` forecasts, each marked `generated_sales_in_history`; the forecast logged the switch with database and row count |
| Review | April plan: 121 rows, 110 ordering, 1,213,168 pieces. Forecast error withheld |
| Close | 2026-03 `closed` by the practice approver; 110 plan rows closed |
| After | 709 rows still `is_demo = true`, 0 with the tag and not labelled, 0 other `is_demo` rows through the view, 0 real March rows; `mart.sales_mart` holds the 709 as `generated` |

It proves the month runs on labelled generated data on a local copy. It does not prove a real new monthly file runs: none has ever existed.

## Everything a practice month writes, and how each says so (2026-11-03)

Measured, not read from the code: `python -m scripts.practice_artefacts` fingerprints every repo file and table, runs the month, and diffs; it calls every GET route on the practice copy; it exits 1 on anything unlabelled. Run from `backups/full_backup_20261102T170343Z`: 3 files, 14 tables, 51 GET routes, 0 unlabelled. April plan unchanged by the labels: 121 rows, 110 ordering, 1,213,168 pieces. A row deliberately inserted with the trigger off was caught. "Before" is the same measurement on e93bcea.

**Files** (marker text `PRACTICE RUN ON GENERATED SALES, NOT A RESULT`)

| File | Before | Marker now |
|---|---|---|
| `local/nonlive_reports/reports/BASELINE_FORECAST_RUN.md` | None | First line |
| `local/cycle_feedback/feedback_<cycle>_nonlive.txt` | Yes, only if generated rows were in that month itself | First line, also when they are only in the history |
| `local/cycle_feedback/feedback_<cycle>_nonlive.csv` | None (a bare header) | First line, a `#` comment |
| `local/baseline_forecast_per_sku.csv` | Not written by a practice run (fixed earlier) | Not written |
| `local/baseline_forecast_per_sku.GENERATED_SALES_practice_2026-11-03.csv`, leftover from before that fix | Its file name only | First line, a `#` comment |
| `reports/lp_runs/retired_*.csv`. Did not fire in this run; written when a rerun retires rows | None, and in a folder for live's files | Moved to `local/nonlive_reports/`, `practice_marker` column; its own test |
| `run_lp --csv PATH`. `run_month` does not pass it | None | `practice_marker` column; its own test |
| `local/monthly_batch/uploads/`. The page's upload; a person's input file, not an output | Not generated data | None needed |

**Tables.** Every row written carries `practice_run`, stamped by a trigger in that copy only. Rows are written, then counted against `ssm_local`. "Updated" rows count as written, and the older version of each as deleted.

| Table | Written | Deleted | Other marker it already had |
|---|---|---|---|
| `public.unilever_sku_demand_fact` | 709 | 644 (the copy's retired backfill) | `is_demo`, `_src_file` |
| `public.abc_classification` | 1,083 | 0 | None |
| `public.forecast_result` | 191 | 0 | `model_params.run.generated_sales_in_history` |
| `public.lp_run` | 1 | 0 | None |
| `public.lp_recommendation` | 231 (121 new, 110 closed) | 110 | None |
| `public.planning_cycle` | 1 | 0 | None |
| `mart.sales_mart` | 709 | 644 | `data_kind = 'generated'` |
| `mart.sales_month` | 1 | 1 | `data_kind = 'generated'` |
| `mart.planning_mart` | 410 | 289 | None |
| `mart.forecast_run` | 1 | 0 | None |
| `mart.forecast_run_value` | 380 | 0 | None |
| `mart.accuracy_mart` | 380 | 0 | None |
| `mart.error_decomposition` | 104 | 104 (`refreshed_at` only) | None |
| `mart.refresh_log` | 6 | 0 | None |

A mart rebuild stamps rows of real months too: the label says the row was written on the practice copy, not that its own month is generated.

**API**

| Answer | Before | Now |
|---|---|---|
| The other 47 GET routes, on a process connected to `ssm_practice` | Answered with no marker; `/abc`, `/category-trends`, `/dashboard`, `/dashboard/forecast-runs`, `/forecast/{sku}`, `/fsn`, `/inventory/current`, `/policy-comparison`, `/recommendations` and `/sku` visibly differed from `ssm_local` | 409 `practice_copy_not_served` (`/status` included) |
| `GET /batch/status` | `synthetic_rows`, for the month in play only | `practice_note`, `generated_rows` |
| `GET /batch/feedback` | `synthetic_rows`, withheld reason | `practice_note`, `generated_rows` |
| `GET /batch/job` | The log; the forecast's lines prefixed | `practice_note` (the log can lose its first lines to its 400-line limit), and `run_month` opens with the marker |
| `GET /health` | Holds no figure | Unchanged |
| `POST /batch/*` | Answer a job name or a file name; no figure | Unchanged |

Printed output: the forecast's lines stay prefixed `[computed on generated sales]`, `run_month` prints the marker first, and `local_pg run --practice` prints it before the child starts.

Not looked at, because the run never reaches it: the loader's transform folder and layout cache, written only when a real file is uploaded and loaded.

## What the loop is

| Signal | Reaches the next plan? | How |
|---|---|---|
| Actual sales | Yes | The next forecast reads them |
| Stock count | Yes | Opening stock (`stock_opening_v`) |
| Accepted orders | Yes | `expected_receipt`, added to opening stock until a count covers them |
| Forecast error | Yes | MASE below 1 decides which products enter the plan |
| Quantity overrides, dismissal reasons | **No, by design** | Shown in the feedback report only. "Truck is full" says nothing about demand. A test fails if forecasting or the LP reads them. |

It runs as one batch a month because the data arrives monthly. There is no scheduler, because a close needs a named person.

## How to run a month

```
# 1. Dry run: reads, prints, writes nothing
python -m scripts.run_month --month 2026-03 --calendar-factor on

# 2. Load, ABC, forecast, plan, refresh marts; prints the review and stops
python -m scripts.run_month --month 2026-03 --calendar-factor on \
    --slice unilever:unilever_sku_demand_fact:2026-03 --slice unilever:inventory_fact:2026-03 \
    --approved-by NAME --expect-month 2026-03 --target-public

# 3. After a person has read the review: settles receipts and closes the month
python -m scripts.run_month --month 2026-03 --calendar-factor on --close --expect-plan-pieces N \
    --approved-by NAME --expect-month 2026-03 --target-public
```

Take a backup before step 2 on live. If a step fails, fix it and run the same command again; finished steps are skipped. The review alone: `python -m scripts.cycle_feedback --cycle 2026-03` (per-product file in `local/cycle_feedback/`, git-ignored).

To rehearse locally, prefix each command with `python -m scripts.local_pg run --practice --` and leave out `--target-public`. `scripts/local_pipeline_qa.py synth` generates labelled rows there, which this copy's demand view admits and the forecast accepts because of the connection (`analytics/forecasting/practice_switch.py`). Anywhere else they are refused.

## From the Data Management page (local only)

```
python -m scripts.local_pg start
python -m scripts.local_app --reset backups/full_backup_20261102T114428Z    # a clean copy; leave out --reset to keep the current one
```

It prints one line to paste into the browser console at http://localhost:5173, which signs you in without a password. Data Management then shows four steps: add the month's data, run it, review the new plan, close it.

**The shortcut cannot work on live.** No login code changed, so the deployed app has no bypass. The token is signed with a secret made up on each run, and `local_app` refuses any database but 127.0.0.1:55432. The batch routes also refuse any other database and never pass `--target-public`. With the batch off, the page shows its original banner and dropzone, and no panel.

Clicked through in a real browser (Chrome, driven by Playwright) on a clean copy: generated practice sales, run (104 s), review, close. No browser errors, and no sideways scroll at phone width.

**Known limits of the page:**

| Limit | Effect |
|---|---|
| A real new file stops at the loader's sign-off (`fingerprint_unsigned`) | Since 2026-11-04 the panel has an **Approve the file** action that runs the same `transform_signoff` command (docs/MONTHLY_BATCH_REVIEW.md). Tested with stand-ins only, because there is no real new file to test it with. |
| `LATEST_DATA_PERIOD` in `frontend/src/dataCoverage.js` is hand-set | After a run, the Dashboard's default range stays at Feb 2026 and it shows a banner saying so. The frontend's own file, left alone. |
| ~~The Dashboard and Reorder pages never show the batch~~ (no longer true since 2026-11-04) | Under `scripts.local_app` the pages read `ssm_practice`, labelled; they move at Run, not at Close (STATE.md). On any other server they show nothing of the batch, which never runs there. |
| A second month can't be practised | `local_pipeline_qa synth` only generates 2026-03. |
| The job log is held in memory | A backend restart forgets the log, not the work. |

## Rehearsal results

| # | What was done | Expected | Happened |
|---|---|---|---|
| R3 | Dry run with no March sales | Refuse | Exit 2, names the month |
| R4 | Approval naming a different month | Refuse | Exit 2, nothing written |
| R6 | Dry run with sales present | List the steps, write nothing | Exit 0, listed abc, forecast, lp |
| R7 | Write run with a forced forecast failure | Stop at the forecast; LP does not run | Exit 1. ABC 1,083 rows, 0 forecast rows, 0 plan rows for 2026-04 |
| R8 | Same command after the fault was removed | ABC skipped, the rest run, review printed | Exit 0, as expected |
| R9 | Same command again | Nothing changes | Every step skipped; plan fingerprint identical, `lp_run` count unchanged |
| R10 | Close with the wrong plan total | Refuse | Exit 2, nothing closed |
| R11 | Close with no plan total | Refuse | Exit 2 |
| R12 | Close with the printed total | Close | Exit 0. 98 plan rows closed, decisions kept |
| R13 | Close again | Nothing changes | "already closed", exit 0 |
| R14 | Run an earlier month | Refuse | Exit 2 |
| Receipts | One order delivered, one short, one later than the count | One of each state | `arrived_in_count` 1; `arrived_in_count` with `not_visible_in_count` 1; `expected` 1 |
| API | `scripts/smoke_api.py` on the rehearsed database | All pass | All routes PASS |

**Not rehearsed:** the load step as a real write, because no March raw files exist. `run_canonical_load --dry-run` accepted both slice specs on existing files (2 slices, 0 refused). Local timings say nothing about Render or Supabase.

## What the review shows, and why it matters

Plan pieces follow the stock count closely, and the counts swing. Generated-sales run, counts are real:

| Count (file month) | Taken | Pieces |
|---|---|---|
| 2026-03 | 2026-04-06 | 1,685,621 |
| 2026-02 | 2026-03-02 | 3,800,930 |
| 2026-01 | 2026-02-03 | 1,735,540 |
| 2025-12 | 2026-01-01 | 3,542,859 |
| 2025-11 | 2025-12-01 | 2,610,841 |
| 2025-10 | 2025-11-03 | 1,688,898 |
| 2025-09 | 2025-10-01 | 2,173,972 |

The rehearsed April plan is 1,213,146 pieces against March's 356,254 (3.41x). In the same run the forecast went from 1,892,200 to 1,654,892 pieces while the opening count fell by 2,115,309, so the count is the likely driver. That is an inference from these totals, not a tested cause. Nobody can check a count with SSM, so the batch shows it to the person approving and corrects nothing. There is no "too large" threshold because none is on record.

## Working without SSM

The answers are not coming (team, 2026-11-02). Each one is a written limitation in `KNOWN_ISSUES.md` (L1-L8), not pending work.

| Question for SSM | What we do instead |
|---|---|
| New sales files | The batch refuses until they exist, and the live plan stays at 2026-03. The loop is shown with this rehearsal, labelled synthetic. |
| Is a strange count right? | Accepted as recorded; shown at the review; not corrected |
| Ilocos Sur stock vs La Union sales | Treated as one stock position, stated as an assumption |
| Are zero-sale months omitted? | Treated as zero, on the evidence in `CLAUDE.md` ("Why data is missing") |
| Costs, capacity, ceilings, PO Qty, deliveries, promotions | L1-L4, already written |

Synthetic data stays in the local database or the `demo` schema, labelled. The batch refuses to start on live if the rehearsal's generated sales are in the month.

## Changed after this rehearsal (2026-11-04)

The rehearsal above ran with nothing decided, and its April plan (121 rows, 110 ordering, 1,213,168 pieces) stands as what that run produced. `scripts.run_month` now refuses that sequence, so it cannot be repeated as written. The panel now has five steps, `GET /batch/job` returns the stages reached rather than the raw log, and each job's full output is saved under `local/monthly_batch/logs`. What changed, what is provisional and what has not been run: [docs/MONTHLY_BATCH_REVIEW.md](../docs/MONTHLY_BATCH_REVIEW.md).
