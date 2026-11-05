# Monthly batch safeguard: review notes

**Status, 2026-11-04.** Built by Audrey with Claude Code, on `thea-dashboardedits`, pushed to tamagaur/4ISA-CAPS2-GROUP-7 only, not the canonical repo: it has not reached `Main-BE` or any other branch of the group's repo. **Provisional: neither Yuan nor Kelvin has reviewed or verified any of it.** **No part has run against a PostgreSQL database end to end**, because the machine it was built on has no PostgreSQL, no `backups/` folder and an empty `data/raw`. The new read-only SQL did run against live.

## What changed

The Data Management panel now goes: upload, validate, run, review, close.

1. **Validate** carries the Reorder page's decisions onto the practice copy, and checks any waiting file with the loader's own dry run. It loads nothing.
2. **The checklist** (`GET /batch/checklist`) shows nine checks from what the scripts report.
3. **Approve the file**, for a real file, records the signed-in person with the loader's own sign-off command.
4. **Run the Month** is available only when nothing blocks. `POST /batch/run` asks every check again, and `scripts.run_month` applies its own refusals when it starts.
5. **Review and Close** are as they were.

## Implementation Decisions for Yuan's Review

### 1. Local-only ETL execution

| | |
|---|---|
| **Implemented** | Nothing about where `/batch` runs changed. The routes mount only with `MONTHLY_BATCH_ENABLED` on and the database at `127.0.0.1:55432`, and the three new routes sit behind the same check |
| **Why** | A run on live replaces the 109-row plan. Uploaded files have nowhere to live on the deployed server, and no real new month exists |
| **Files** | `backend/routers/monthly_batch.py` |
| **Limitations** | The deployed Data Management page still says ingestion is not connected. Jobs are held in one process's memory |
| **Verify** | The deployed API stays at 84 routes (`check.sh --fast` pins it). Decide whether and when this should reach the deployed service |
| **Revisable?** | Enabling is a separate project: file storage, a lock that survives a restart, and the plan-moving decision. The checks themselves would not need rewriting |

### 2. Replaying reorder decisions to the practice database

| | |
|---|---|
| **Implemented** | `scripts/replay_practice_decisions.py` reads the cycle's rows from both databases and carries the page's decisions over through `recommendations.decide_row`, with the original person, time, reason and quantity. A decision undone on the page is undone through `reorder_approval.reverse_decision`. Validate and Run both call it |
| **Why** | The pages use `ssm_local` and the batch uses `ssm_practice`, and no page may read the practice copy (CLAUDE.md rule 2, arrangement 3). Without this, a decision on the Reorder page never reached the plan, and the safeguard could never clear. The alternatives were weaker: re-copying the database needs its source idle and wipes generated sales, and checking `ssm_local` alone would let the plan ignore the decisions |
| **Files** | `scripts/replay_practice_decisions.py`, `scripts/batch_status.py`, `backend/routers/monthly_batch.py`, `tests/test_replay_practice_decisions.py` |
| **Limitations** | Staff requests are not copied: they are read from the pages' database, and the route refuses on them. The copy's audit log gets one replay entry per decision. **The real writes have not run** |
| **Verify** | See "Priority review items" below |
| **Revisable?** | Yes, easily. It is one script and two calls, and it has no part to play on a single database such as live |

Each row is handled like this:

| Page says | Practice copy says | Action |
|---|---|---|
| Accepted or dismissed | Pending | Applied through `decide_row` |
| Same decision | Same decision | Left alone, so nothing is applied twice |
| Pending | Pending | Left alone, and the safeguard keeps counting it |
| Pending | Accepted or dismissed | Reversed through the real reversal |
| A different decision or quantity | Accepted or dismissed | Reversed, then applied |
| Row differs (product, cycle or `q_i`) | | Reported, not touched, and the check fails |
| On one side only | | Reported, not touched, and the check fails |
| Next plan already on the copy | | Nothing replayed: those rows can no longer be decided |

### 3. Frontend file sign-off

| | |
|---|---|
| **Implemented** | `POST /batch/signoff` and an **Approve the file** action run `analytics.etl.transform_signoff` with the signed-in user as `--by`, on the manifest the dry run wrote. Requires `upload.run` |
| **Why** | Without it a real file could not get past `fingerprint_unsigned` from the page: the person would need a command line |
| **Files** | `backend/routers/monthly_batch.py`, `scripts/batch_status.py`, `frontend/src/components/MonthlyBatchDialogs.jsx` |
| **Limitations** | Refused for a file that was not checked, changed since, or had a refused slice. The sign-off is meant to be a person reading the manifest, and the dialog shows only the file names and row counts, not the full checklist the CLI prints. **Tested with stand-ins only: no real new file exists** |
| **Verify** | That row counts are enough for a person to approve on, or whether the dialog should show the manifest's checklist. Whether `upload.run` is the right permission for this |
| **Revisable?** | Yes. Removing the route and the action leaves the CLI path unchanged. The loader still checks every approval against the file |

### 4. Blocking unresolved decisions in practice runs

| | |
|---|---|
| **Implemented** | `run_month.preflight_refusals` refuses while this month's plan has a row someone can decide, or an open staff request. It applies to the panel and the command line, on every database. No override |
| **Why** | Once the next plan exists these rows can no longer be decided (`recommendations.py`, the current-cycle rule), and accepted orders count as stock on the way in that plan (`stock_opening_v`) |
| **Files** | `scripts/run_month.py`, `scripts/practice_artefacts.py`, `docs/LOCAL_DEMO_RUNBOOK.md`, `tests/test_run_month.py` |
| **Limitations** | `scripts/run_lp.py` run by hand is not gated, because the LP was out of scope; the load procedure says so. The gate stops at the moment a run starts, so an admin reversing a decision during a run is not caught. The defence demo now needs real decisions first (below) |
| **Verify** | The boundary table below. Whether `run_lp.py` should refuse too |
| **Revisable?** | Yes. It is one function, `decisions_refusal`, and its tests |

| Rows | Live, 2026-11-04 (read-only; a baseline, not a constant) | Blocks? | Why |
|---|---|---|---|
| This month's plan, pending, `q_i` above 0 | 73 (19 flagged) | **Yes** | The Reorder page offers Accept and Dismiss |
| Open `lp_quantity_change` and `lp_dismissal_request` on this month's rows | 0 | **Yes** | An admin must settle them first |
| This month's plan, pending, `q_i` of 0 | 36 | No | The page offers no buttons |
| Pending rows of earlier cycles | 179, in 33 cycles | No | The backend refuses a decision on them |
| This month's rows already decided | 1 | No | Done |
| Pending rows of a later plan | 0 | No | Next month's to settle |

Once the next plan exists the gate lifts, for a rerun and for a close, because a refusal there could never clear.

### 5. PostgreSQL and backup requirements for end-to-end testing

| | |
|---|---|
| **Implemented** | Nothing was installed or restored. Everything that could run without a database did. See "Test status" |
| **Why** | Audrey did not authorise an install, and Kelvin's backup is git-ignored and not on this machine |
| **Needs** | PostgreSQL 17 (`scripts/local_pg.py` expects `C:\Program Files\PostgreSQL\17\bin`, or set `PG_BIN`), and `backups/full_backup_20261102T170343Z` |
| **Verify** | Run the list under "What to run", on a machine that has both |
| **Revisable?** | Not applicable: this is a test environment, not a design choice |

## Priority review items

**1. Do decisions really reach the practice copy?** The pages use `ssm_local` and the batch uses `ssm_practice`. Check that accepted, dismissed and quantity-adjusted rows all arrive before a plan is made: `status`, `decided_q_i`, `decided_by`, `decided_at` and a live `expected_receipt` row with the same `expected_on`. Check that a reversal arrives too. Only the logic that decides what to do has been tested, not the writes.

**2. What the safeguard does to the demo.** The old April plan (121 rows, 110 ordering, 1,213,168 pieces) was made with nothing decided. With the 73 decisions made, accepted orders count as stock on the way, so it will change. **The new figure has not been measured.** Validate it rather than forcing the old one back.

There is one thing to judge when reading it. `stock_opening_v` counts a receipt whose `expected_on` falls after the count date. On the practice copy decisions are dated today, months after the 2026-04-06 count, so every accepted order counts as on the way. A real month's timing would not do that, so the demo may show a bigger drop than a real month would.

## Note for Kelvin

**The ETL checklist.** Your checks are all still there and still the rule. `close_cycle.CHECKS` is unchanged, and the panel shows those five flags as progress, because before a normal run three of them are false by design. `preflight_refusals` keeps its signature and sentences; it now calls `preflight_items`, which adds a code to each, and it has one new refusal. `facts` now needs a `decisions` key.

| Check on the page | Comes from | Blocks? |
|---|---|---|
| Sales available | `checks.sales_loaded` or an uploaded file | Yes |
| Latest processing month | `preflight_items`: `not_latest_month` | Yes |
| Monthly run not already completed | `checks.lp_next`, `cycle_state`, `already_ran` | Yes |
| Reorder decisions settled | `run_month.read_decisions` (new) | Yes |
| Files valid | Loader dry run, `etl_load_event` | If refused; otherwise a warning |
| File approved | `load_slices.unsigned_reason` | Yes |
| No other job running | The job | Yes |
| Stock count present | `checks.count_loaded` or an uploaded file | No: a warning. Close still refuses |
| Generated sales present | `synthetic_rows`; `synthetic_on_live` blocks | No: a warning |

**The practice workflow.**

- `run_month --check-files` runs your loader's dry run and writes a JSON report.
- `practice_artefacts` now settles the plan's decisions through `decide_row` before the month (`--settle-decisions`, practice copy only). It has **not been run**. Please run it: it is the check that everything a practice run writes carries its marker.
- `GET /batch/job` no longer returns the raw log, because it can carry internals. It returns the stages reached, and the full output goes to `local/monthly_batch/logs`.
- `_plan` adds `run_key`, read from `lp_run`. `batch_status` takes `--slice` and `--run-key`, and adds `decisions`, `preflight`, `close_missing`, `signoff` and `replay`.

**The demonstration sequence.** `docs/LOCAL_DEMO_RUNBOOK.md` is rewritten: settle the March plan on the Reorder page first (19 flagged rows on live need individual confirmation), then generate, validate, run, review and close. It has **not been walked through**, and its April figure is marked not measured. Please walk it before the defence, and write in the figure.

**Pinned figures.** This adds 174 tests, so the pytest totals in `docs/CHAPTER4_CODE_FIGURES.json` will drift and `check.sh --full` will fail until they are re-pinned on a machine with `data/raw`. They were not re-pinned here because this machine cannot produce them. The manuscript's quoted test totals will move with them.

**Two of your guard tests were widened, on purpose. Please check these.**

| Guard | Why it fired | What changed |
|---|---|---|
| `test_no_forecasting_safety_stock_or_lp_code_reads_the_capture_columns` | The replay script names `decided_q_i` and `decision_reason` to carry a decision across unchanged through `decide_row` | That script and its test join `ALLOWED`, by exact name. It computes nothing from them, and a test pins that it has no SQL write |
| `test_nothing_in_the_plan_reads_the_new_tables` | `run_month` counts open `lp_dismissal_request` rows for the gate | The check now expects exactly `["scripts/run_month.py"]`. A new test pins that it only counts open requests, never reads `lp_stock_observation`, and that `run_lp.py` and `lp.py` read neither table |

So a decision now does decide whether a run starts, though not what the plan contains. If you would rather keep those guards as they were, the gate belongs somewhere else, which is a design change for you and Yuan.

**Not touched:** forecast, ABC, safety stock, target stock, the LP, migrations, permissions, the Reorder page and the Dashboard.

## Test status

| Scenario | What ran | End to end |
|---|---|---|
| A. No pending decisions, all checks pass | Run route and checklist with stand-in status, completion logic, browser flow with stubbed answers | **Not Executed — Environment Dependency** |
| B. Pending decisions | Counts against live (read-only), refusal in `run_month` on live as a dry run, route 409, dialog and navigation in a browser with stubbed answers | **Not Executed — Environment Dependency** |
| C. Missing monthly data | Checklist and route tests, `run_month` refusal | **Not Executed — Environment Dependency** |
| D. Invalid upload | Reason mapping, detail cleaning, approval refused, with stand-in loader events. The loader's dry run itself did not run | **Not Executed — Environment Dependency** |
| E. Data changes after validation | Route tests: changed file, reversed decision. Stubbed browser flow: 409 opens the dialog | **Not Executed — Environment Dependency** |
| F. Processing failure | Real child processes in job tests: exit code, stages, saved log, redaction. Failure text for every stage | **Not Executed — Environment Dependency** |
| G. Duplicate run | Job lock, 409 while running, 409 once the plan exists, repeated clicks send one request | **Not Executed — Environment Dependency** |
| H. No permission | API tests on every new route; hidden Review button for a staff stand-in | Passed; no database needed |
| I. Responsive layout | 12 states at 1440, 820 and 390px with made-up figures: no page overflow, dialogs fit the screen. The plan table scrolls inside its own box at 390 | Passed as a layout check only |

The stubbed browser flows use made-up figures through the real checklist builder. They are not end-to-end verification.

**Whole suites on the machine this was built on, 2026-11-04:** backend 2,554 passed, 21 skipped (the allowed opt-in list), 0 failed; frontend 214 of 214; build passed; `check.sh --fast` GREEN, including the live plan check. `check.sh --full` was not run: this machine has no `data/raw`, and it would fail on the pinned totals until they are re-pinned.

**What to run** on a machine with PostgreSQL 17 and the backup:

```powershell
python -m scripts.local_pg start
python -m scripts.local_app --reset backups\full_backup_20261102T170343Z
python -m scripts.practice_artefacts          # in a second terminal
scripts\check.sh --full                       # then re-pin: python -m scripts.chapter_figures --write
```

Then walk `docs/LOCAL_DEMO_RUNBOOK.md`, upload a file from `tests/fixtures/extract_raw` for scenario D, and undo a decision after validating for scenario E.

## Known limits

- **A real new monthly file has never been loaded**, so a real file's path through validation, approval and load is untested anywhere.
- **The job lock is in memory.** A restart forgets a running job, so a second run could then start beside it. After a restart a finished run shows **Plan ready for review**, not **Monthly Processing Complete**, because the job's exit code is gone.
- **`run_month` still does not compute review flags** (already recorded in STATE.md). The checklist does not cover them.
- **A dry run keeps no row-level detail**, so file errors show the file, the table and the reason, not a row number.
