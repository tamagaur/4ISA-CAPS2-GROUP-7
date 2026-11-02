# Monthly batch and feedback loop: how to run it, and the rehearsal of 2026-11-02

Written for: the team members who will run the month, or defend it.

**Nothing here is a result.** The rehearsal ran on the throwaway local database (a copy of the 16 Oct backup, migrated to 0069) with generated March sales, so its plan is not the live plan and its accuracy figures are not accuracy. Nothing was written to live.

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

To rehearse locally, prefix each command with `python -m scripts.local_pg run --`, generate the month with `scripts/local_pipeline_qa.py synth`, and leave out `--target-public`.

## From the Data Management page (local only)

```
python -m scripts.local_pg start
python -m scripts.local_app --reset backups/full_backup_20261016T070624Z    # a clean copy; leave out --reset to keep the current one
```

It prints one line to paste into the browser console at http://localhost:5173, which signs you in without a password. Data Management then shows four steps: add the month's data, run it, review the new plan, close it.

**The shortcut cannot work on live.** No login code changed, so the deployed app has no bypass. The token is signed with a secret made up on each run, and `local_app` refuses any database but 127.0.0.1:55432. The batch routes also refuse any other database and never pass `--target-public`. With the batch off, the page shows its original banner and dropzone, and no panel.

Clicked through in a real browser (Chrome, driven by Playwright) on a clean copy: generated practice sales, run (104 s), review, close. No browser errors, and no sideways scroll at phone width.

**Known limits of the page:**

| Limit | Effect |
|---|---|
| A real new file stops at the loader's sign-off (`fingerprint_unsigned`) | The page has no sign-off button: run the `transform_signoff` command the log prints. Not built because there is no real new file to test it with. |
| `LATEST_DATA_PERIOD` in `frontend/src/dataCoverage.js` is hand-set | After a run, the Dashboard's default range stays at Feb 2026 and it shows a banner saying so. The frontend's own file, left alone. |
| The Dashboard and Reorder pages do not label practice sales | On the local copy they look real once practice sales are in. Only the Data Management panel says they are generated. Do not screenshot them as results. |
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
