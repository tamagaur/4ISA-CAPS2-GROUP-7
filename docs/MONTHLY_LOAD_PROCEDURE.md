# Monthly load procedure: the old steps, checked against the code

**Status 2026-11-04: not safe to follow end to end. Two steps are BLOCKED** (steps 3/5 for Del Monte returns, and step 9). See "What blocks this procedure" below. Unilever's own slices, ABC, forecast and the plan do run.

**What this is.** The "Adding a new month" section of `RUNNING.md`, recovered unchanged from `git show 468c6d8:RUNNING.md`. The grey quoted lines are the old text with nothing corrected. Each step is followed by a mark saying what the code does today.

**For the defence, the path shown is [LOCAL_DEMO_RUNBOOK.md](LOCAL_DEMO_RUNBOOK.md):** generated March sales on a local copy. It replaces steps 1 to 5 with generated rows, so it does not meet the blocker in those steps, and it does not prove them. **A real new monthly file has never been loaded.** No step below has run on one.

## How it was checked

Every command was typed as written, on the throwaway database (`127.0.0.1:55432`), on 2026-11-03/04 UTC, code base b209a9e plus migration 0074. Nothing here wrote to live (`etl_load_event` on live stayed at 191 rows).

| Tested on | What it can show | What it cannot show |
|---|---|---|
| `ssm_local`, restored from `full_backup_20261102T170343Z`, re-loading real files for existing months (Del Monte 2025-12, Unilever 2026-02) | Steps 0 and 2 to 5 and 10 run, what they write, and a repeat load | A month the database has not seen |
| `ssm_practice`, with the 709 generated March rows | Steps 6 to 8 on a new month | Anything scored against real sales; the practice figures are not results |

| Mark | Meaning |
|---|---|
| **MATCHES** | Ran as written and did what the text says |
| **DOES NOT MATCH** | Runs or could run, but the text is wrong in the way stated |
| **BLOCKED** | The code refuses the step and nothing has replaced it |
| **NOT RUN** | Read in the code only, or could not be run; says why |

## What blocks this procedure

| # | Step | What happens | Replaced by | What would settle it |
|---|---|---|---|---|
| 1 | 3 and 5, `delmonte:salesreturn_fact:YYYY-MM` | Refused for any month: `prepare failed: FileNotFoundError ... data\raw\PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN (1).xlsx`. `scripts/load_slices.py:544` looks for that file at the top of `data/raw`; it is in `data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/`. Since the layout guard (67d3443, 2026-10-02) that lookup opens the file. `tests/etl/test_load_slices.py` has no case that reaches it. The load events in the 2026-11-02 backup hold 20 loads of this table, all from one day (2026-10-03), and none refused or from a slice run after it | Nothing. `--all-slices` skips the lookup, but it rebuilds every month | A one-line change to find the file by search. Trial without editing the loader: a dry run of 2025-12 and 2023-04 gave 2 slices, 0 refused (103 and 37 rows) |
| 2 | 9, the accuracy backtest | Moving `WINDOW` and running the command as written exits 1 and writes nothing, and it no longer feeds the card by default. See step 9 | Partly: `scripts/accuracy_as_served.py`, which cannot store a new month without code edits and has never run on one | A decision on whether step 9 is part of the monthly procedure, then the edits it lists, tested on the first real month |

## Not in the old text

| What | Command | Mark |
|---|---|---|
| The whole month as one command, Unilever slices only | `python -m scripts.run_month --month YYYY-MM --calendar-factor on ...` (usage in `scripts/run_month.py`, `reports/MONTHLY_BATCH_REHEARSAL_2026-11-02.md`) | Runs load, ABC, forecast and LP, refreshes the marts, prints a review and stops. It does not do steps 2, 3, 4, 9 or 10, or the review flags. A real file still stops at the sign-off in step 4. The load inside it has never run as a write on real new data |
| Closing the month | The same command with `--close --expect-plan-pieces N`, or `scripts/close_cycle.py` | Rehearsed on the practice copy (`LOCAL_DEMO_RUNBOOK.md`). No live cycle has been closed |
| Review flags for the new cycle | `python -m scripts.compute_review_flags --calendar-factor --write` | Needed after every forecast run, by that script's own docstring. **Neither the old text nor `run_month` runs it.** On the practice copy it refuses generated rows (`demand frame contains is_demo=true rows`), so it has not been run on a new month |
| Feedback report | `python -m scripts.cycle_feedback --cycle YYYY-MM` | Read-only. Withholds the forecast error when generated rows are in what it scores |

## The old section, unchanged, with marks

> ## Adding a new month (live database)

> Written 2026-10-19 from the end-to-end ingestion audit. Steps 1-5 were run
> end to end on a scratch copy of public (`ssm_e2e_audit`) and loading the same
> month twice was shown to duplicate nothing. Steps 6-9 were run report-only
> against public (no `--write`); their write forms below are the documented
> ones, not exercised in that audit.

> **0. Migrations must be clear.** A public load refuses while any migration
> file is unapplied (`refusing: migrations pending on public`). Back up, then
> apply with `python -m scripts.run_canonical_load --schema public
> --target-public --schema-only`. As of 2026-10-19, 0059 and 0060 are pending
> on public, and 0060 drops `app.users.avatar_data_url`.

**Mark: MATCHES, except the last sentence.** The refusal printed exactly as quoted, naming the pending files, and `--schema-only` applied them. **DOES NOT MATCH:** "0059 and 0060 are pending" is out of date; both are applied. STATE.md holds the next free number.

> **1. Put the files in `data/raw/`.** The month comes from the file NAME
> (plus up to three parent folder names), never from a date typed inside the
> workbook. The Del Monte "Actual as of" cell is not read at all. Keep the
> existing naming:
>
> | Data | Where | Name must contain |
> |---|---|---|
> | Del Monte sales register, returns, sell-out, purchases, inventory sign-off | `data/raw/Del Monte/MONTHLY REPORT - <MONTH> <YEAR>/` | month name + 4-digit year |
> | Unilever stock (SSIS) | `data/raw/SSIS/<YEAR>/SSIS <MONTH> <YEAR>.xlsx` | month name + 4-digit year (`SSIS FEBRUARY 202.xlsx` only works because its folder is `2026/`) |
> | Unilever SKU sales | `data/raw/Unilever/UnileverLaUnionSalesperSKU2023to2026.xls` | this exact name: SSM's updated multi-year file replaces it |

**Mark: DOES NOT MATCH on how a file is read. NOT RUN on a new file.** Since 67d3443 (2026-10-02) a file's family is identified by its content, from its sheets and headers (`analytics/etl/extract/layout.py:270`), and a name that disagrees with the content is refused as `layout_changed`. The month comes from the path first. A sales-register or returns file with no month in its path takes the commonest month among its **invoice dates** (`layout.py:345-350`), so "never from a date typed inside the workbook" is no longer true for those. Unilever SKU rows carry their own month, and the slice takes only that month's rows. `--file PATH` now names a file directly. The exact-name line is not enforced by what I read, but no renamed file has been tried: keep the name. The folder table's other paths match what is on disk.

> **2. Back up the tables a load writes to** (read-only; verifies every file's row count):
>
> ```bash
> python -m scripts.backup_tables sales_fact purchase_fact salesreturn_fact sellout_fact inventory_fact unilever_sku_demand_fact derived_receipt_fact sku_demand_fill etl_quarantine etl_coverage etl_load_event product_dimension customer_dimension schema_migrations
> python -m scripts.backup_tables --schema app audit_log
> ```
>
> Restore: each `backups/tables_<time>/data/<table>.csv` is a `COPY ... WITH
> (FORMAT csv, HEADER)` export; `structure.json` has the columns, keys and
> indexes to recreate the table if needed.

**Mark: MATCHES.** Both commands ran, and every file's count was verified. The list covers everything the test load wrote in `public` and `app`. It also rewrites `mart.*`, which is rebuilt from those tables, so it is not in the list. The restore instructions were read, not run.

> **3. Dry run** (writes only `etl_load_event` rows marked `dry_run`). One
> `--slice principal:table:YYYY-MM` per table and month:
>
> ```bash
> python -m scripts.run_canonical_load --schema public --target-public --dry-run \
>   --slice delmonte:sales_fact:YYYY-MM --slice delmonte:salesreturn_fact:YYYY-MM \
>   --slice delmonte:sellout_fact:YYYY-MM --slice delmonte:purchase_fact:YYYY-MM \
>   --slice delmonte:inventory_fact:YYYY-MM \
>   --slice unilever:unilever_sku_demand_fact:YYYY-MM --slice unilever:inventory_fact:YYYY-MM
> ```
>
> Read the slice summary: `real A->B (-x/+y)` per slice, refusals, and any
> `validation_warning` (e.g. a peso total far outside earlier months).

**Mark: BLOCKED for `delmonte:salesreturn_fact` (blocker 1). The other six slices MATCH.** Only `etl_load_event` rows were written (+7 by the table statistics), and the slice summary and `validation_warning` lines printed as described. Any refused slice makes the command exit 1.

> **4. Sign off** - the one human step. The dry run prints the run key:
>
> ```bash
> python -m analytics.etl.transform_signoff --transform-dir transform/slices/<run key> --decision approved --by "<name>"
> ```

**Mark: MATCHES.** The dry run printed the run key and this command. Before signing, all 7 slices were refused as `fingerprint_unsigned`. The loader's other work still ran on that refused run: it refreshed the marts, and without `--no-fill` it would have run the fill step.

> **5. Load** - the step 3 command without `--dry-run`. It deletes and
> re-inserts each slice's real rows in one transaction (re-running the same
> month changes nothing, `-0/+0`), then runs the fill step and refreshes the
> marts.

**Mark: BLOCKED for `delmonte:salesreturn_fact` (blocker 1). DOES NOT MATCH on "changes nothing".** Real rows do hold: the plan stayed 435,988 pieces and every table's real count equalled live's, and a second load printed `-0/+0` on every slice that loaded. (On the first load, Unilever's stock slice printed `-812/+812` with the same 812 rows.) **Labelled rows do not hold.** Compared with live, the first load's fill step added 2,397 `synthetic_v2_gap` rows (`sales_fact` 1,124, `inventory_fact` 1,088, `salesreturn_fact` 127, `purchase_fact` 50, `sellout_fact` 8), and `data_kind = 'filled'` rows rose by 957 in `mart.inventory_mart` and by 4 in `mart.sales_mart`. A real load on live should be expected to add such rows (CLAUDE.md rule 2, arrangement 2). Whether charts that show estimates would change on live was not measured.

> **6. ABC** (Tier A basis: `analytics.params.TIER_A_BASIS`):
>
> ```bash
> python -m analytics.classification.orchestrate_abc --period YYYY-MM --schema public --method t12m_new --principal unilever
> python -m analytics.classification.orchestrate_abc --period YYYY-MM --schema public --method single --principal delmonte
> ```

**Mark: MATCHES.** Both ran on the practice month. Unilever wrote 1,083 rows, 191 of them Tier A on generated sales (not a result). With no Del Monte file for the month, the Del Monte command exits 0 and writes 0 rows, so a zero there says nothing was loaded, not that the step failed.

> **7. Forecast.** First move `EXPECTED_MONTHS` in
> `scripts/run_baseline_forecast.py` (hard-coded `2023-01..2026-02`) to end at the
> new month, or the missing-month check never looks at it. Then:
>
> ```bash
> python scripts/run_baseline_forecast.py            # report only
> python scripts/run_baseline_forecast.py --write    # upsert Forecast_Result, refresh marts
> ```

**Mark: DOES NOT MATCH, in two ways. The second one moves the plan.** (a) `EXPECTED_MONTHS` no longer exists: `expected_months()` (`scripts/run_baseline_forecast.py:82`) derives the range from the latest demand month, so there is nothing to edit. (b) **The `--write` line as written omits `--calendar-factor`,** which is off by default while the live forecast uses it (DEC-41). Typed as written it replaces the forecast without the factor. The form that ran is `python scripts/run_baseline_forecast.py --write --calendar-factor`. `scripts/run_month.py` makes this choice compulsory. New since the old text: the run exits 2 if the ABC period is older than the latest sales month, so step 6 must come first. The report-only form and the `--calendar-factor` write ran. The `--write` form without the factor was not run: (b) is from reading the code.

> **8. Safety stock, reorder point and the LP** (one script):
>
> ```bash
> python scripts/run_lp.py --dry-run
> python scripts/run_lp.py --retire-stale-pending
> ```

**Mark: MATCHES, with one addition.** Both ran on the practice month (2026-04: 121 rows, 1,213,168 pieces, practice only, and the same total as the runbook). New since the old text: a second real run on a planned cycle is refused with exit 2 unless `--replan` is given.

> **9. Accuracy backtest** (the dashboard's accuracy card). Move `WINDOW` in
> `scripts/backtest_forecast_run.py` (hard-coded to end 2026-02), then:
>
> ```bash
> python -m scripts.backtest_forecast_run --write --mart-schema mart --target-public --replace
> ```

**Mark: BLOCKED (blocker 2).** `WINDOW` is still hard-coded (`scripts/backtest_forecast_run.py:68`), but the command as written fails:
- **It stops before writing.** With `WINDOW` extended, the `tier_a_2026_02` run compares itself with a headline pinned to the old window and exits 1 (`headline differs from ...`). The run is on a fixed cohort, and it is part of the default command, so nothing is written. `--only at_the_time` or `--only at_the_time_calendar` gets past that, but the stored label still says `2023-10..2026-02` while `window_end` says `2026-03` (seen on run 15 in the test).
- **The card no longer reads these runs by default.** It reads `backend/marts.DEFAULT_BACKTEST_LABEL` (`backend/marts.py:984`), written by `scripts/accuracy_as_served.py --write-run`.
- **That replacement cannot store a new month as it stands.** With a new month loaded and `WINDOW` unmoved it fails (`latest demand month 2026-03 is not the window end 2026-02`, `accuracy_as_served.py:508`). With `WINDOW` moved, `--write-run` refuses a label that exists, and the labels are hard-coded (`accuracy_as_served.py:423-433`). New labels in turn need `DEFAULT_BACKTEST_LABEL` and `tests/backend/test_calendar_adjustment.py:66` changed.
- **NOT RUN: all of this on a real new month.** On the practice copy the backtests refuse generated rows (`history contains 1 placeholder (is_demo) months`), which is the guard working. By the code, without this step a new month falls back to the stored forecast (`backend/marts.py:1066-1069`). On the practice copy that month's 1,077 stored rows had no scorable actuals, so the fallback showed nothing.

> **10. Check the API:** `python scripts/smoke_api.py`.

**Mark: MATCHES.** All routes passed on `ssm_local` after the load. It issues 14 GETs over 8 routes, not every route the frontend uses.

> **Rehearsing on a scratch copy** (`python -m scripts.rehearse_fills --schema
> ssm_<name> --build`, then step 3-5 with `--schema ssm_<name>` and no
> `--target-public`): the build and every scratch load apply pending migrations
> to the scratch schema, but a migration that names `app.users` explicitly
> (0059, 0060) runs against the LIVE table. Do not build a scratch copy while
> such a migration is pending on public. The clone also copies no triggers;
> public has one (`trg_inventory_fact_count_month`, 0039). Drop the scratch
> schema afterwards.

**Mark: part MATCHES, part NOT RUN.** `rehearse_fills --build --dry-run` ran and wrote nothing. Steps 3 to 5 on a scratch schema, and the real `--build`, were not run: both write a scratch schema to the live database. "0059, 0060" is out of date. One trigger on `public` (`trg_inventory_fact_count_month`) is still correct.

> **The scratch build refuses, it does not warn (2026-10-24).** `rehearse_fills --build` and every scratch migration 
> read the migrations they would apply and REFUSE, before creating anything, if any names `app.`, `public.` or `mart.` explicitly: 
> those statements run against the live schemas whatever the scratch search_path says. Apply such a migration to public first 
> (after a backup), then build. `scripts/rollover_scratch_test.py` (`ROLLOVER_SCRATCH=1 pytest tests/etl/test_rollover_scratch.py`) 
> proves the receipt ledger, settlement, the opening-stock view and `close_cycle` on `ssm_rollover_test` with a synthetic March, 
> checks that public, mart and app are byte-for-byte unchanged, and drops the schema. Switch the planning mart OFF 
> (`planning_mart.use_schema(None)`) before calling any decision endpoint against a scratch copy: it writes `mart.planning_mart`, which is live.

**Mark: DOES NOT MATCH on the test command.** The refusal rule was read in `scripts/rehearse_fills.py` and not triggered. `python -m scripts.rollover_scratch_test` and the pytest form now refuse anything but `127.0.0.1:55432`, so they no longer build `ssm_rollover_test` beside live. The way to run them is `scripts/check.sh --optin`.
