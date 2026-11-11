# Monthly load procedure

**Follow the commands as written.** They are the corrected ones. The older text in `git show 468c6d8:RUNNING.md` holds a forecast command that moves the plan: do not copy from it.

**A real new monthly file has never been loaded.** Every command below has run on the throwaway database (`127.0.0.1:55432`, 2026-11-04), on real files re-loaded for existing months or on generated March sales. None has run on a real new month, and none of steps 5 to 9 has run on live this way.

**For the defence, the path shown is [LOCAL_DEMO_RUNBOOK.md](LOCAL_DEMO_RUNBOOK.md):** generated March sales on a local copy. It replaces steps 1 to 5 with generated rows, so it does not prove them.

**On live this moves things on purpose.** A real month moves the live marts and creates a new plan for the month after, so the plan in STATE.md's `plan:` line stops being the current plan. Update STATE.md in the same commit. The 51 pinned figures read frozen rows and do not move.

## Before anything: this month's reorder decisions

**`scripts.run_month` and the Data Management panel refuse to run while this month's plan has an order nobody has decided, or a staff request an admin has not settled** (2026-11-04, provisional, for Yuan's review: [MONTHLY_BATCH_REVIEW.md](MONTHLY_BATCH_REVIEW.md)). Once the next plan exists those rows can no longer be decided, and accepted orders count as stock on the way in it. Rows ordering nothing and pending rows of older plans do not count. There is no override.

**The steps below run by hand are not gated.** `scripts/run_lp.py` does not make this check. Before step 9, see where the month stands, read-only:

```bash
python -m scripts.batch_status
```

## Steps

### 0. Migrations must be clear

A public load refuses while any migration file is unapplied (`refusing: migrations pending on public`). Back up, then apply:

```bash
python -m scripts.run_canonical_load --schema public --target-public --schema-only
```

STATE.md holds the latest applied number.

### 1. Put the files in `data/raw/`

| Data | Where | Keep this name |
|---|---|---|
| Del Monte sales register, returns, sell-out, purchases, inventory sign-off | `data/raw/Del Monte/MONTHLY REPORT - <MONTH> <YEAR>/` | Month name + 4-digit year |
| Unilever stock (SSIS) | `data/raw/SSIS/<YEAR>/SSIS <MONTH> <YEAR>.xlsx` | Month name + 4-digit year |
| Unilever SKU sales | `data/raw/Unilever/UnileverLaUnionSalesperSKU2023to2026.xls` | This exact name: SSM's updated multi-year file replaces it |

How a file is read:
- **Family:** from its sheets and headers. A name that disagrees with the content is refused as `layout_changed` (`analytics/etl/extract/layout.py:270`).
- **Month:** from the path. A sales register or returns file with no month in its path takes the commonest month among its invoice dates. Unilever SKU rows carry their own month, and a slice takes only that month's rows.
- **Not read at all:** the Del Monte "Actual as of" cell.

`--file PATH` on steps 3 and 5 names a file directly. No renamed file has been tried, so keep the names.

### 2. Back up the tables a load writes to

Read-only. It verifies every file's row count.

```bash
python -m scripts.backup_tables sales_fact purchase_fact salesreturn_fact sellout_fact inventory_fact unilever_sku_demand_fact derived_receipt_fact sku_demand_fill etl_quarantine etl_coverage etl_load_event product_dimension customer_dimension schema_migrations
python -m scripts.backup_tables --schema app audit_log
```

To restore: each `backups/tables_<time>/data/<table>.csv` is a `COPY ... WITH (FORMAT csv, HEADER)` export, and `structure.json` has the columns, keys and indexes. The restore itself has not been run. `mart.*` is not in the list because it is rebuilt from these tables.

### 3. Dry run

Writes only `etl_load_event` rows marked `dry_run`. Use one `--slice principal:table:YYYY-MM` per table and month:

```bash
python -m scripts.run_canonical_load --schema public --target-public --dry-run \
  --slice delmonte:sales_fact:YYYY-MM --slice delmonte:salesreturn_fact:YYYY-MM \
  --slice delmonte:sellout_fact:YYYY-MM --slice delmonte:purchase_fact:YYYY-MM \
  --slice delmonte:inventory_fact:YYYY-MM \
  --slice unilever:unilever_sku_demand_fact:YYYY-MM --slice unilever:inventory_fact:YYYY-MM
```

Read the slice summary: `real A->B (-x/+y)` per slice, refusals, and any `validation_warning` (for example a peso total far outside earlier months). Any refused slice makes the command exit 1. A month with no file for a table is refused as `missing_file`, so leave that slice out: 20 of the 38 months to 2026-02 have no Del Monte returns file.

### 4. Sign off

The one human step. The dry run prints the run key:

```bash
python -m analytics.etl.transform_signoff --transform-dir transform/slices/<run key> --decision approved --by "<name>"
```

Without it every slice is refused as `fingerprint_unsigned`. A refused run still refreshes the marts and runs the fill step, so run step 5 only after signing.

### 5. Load

The step 3 command without `--dry-run`. Each slice's real rows are deleted and re-inserted in one transaction. Then the fill step runs and the marts refresh.

- **Real rows:** re-loading the same month holds them. A second load printed `-0/+0` on every slice but the stock slice, whose `-812/+812` held the same 812 rows.
- **Labelled rows do grow.** On the test load the fill step added 2,397 `synthetic_v2_gap` rows compared with live, and `data_kind = 'filled'` rows rose by 957 in `mart.inventory_mart` and 4 in `mart.sales_mart`. That moved neither the plan nor any pinned figure (CLAUDE.md rule 2, arrangement 2). Charts that show estimates may change.

### 6. ABC

Tier A basis: `analytics.params.TIER_A_BASIS`.

```bash
python -m analytics.classification.orchestrate_abc --period YYYY-MM --schema public --method t12m_new --principal unilever
python -m analytics.classification.orchestrate_abc --period YYYY-MM --schema public --method single --principal delmonte
```

With no Del Monte file for the month, the second command exits 0 and writes 0 rows. That means nothing was loaded, not that it passed. Re-running either for an existing period left its rows unchanged.

### 7. Forecast

```bash
python scripts/run_baseline_forecast.py --calendar-factor            # report only
python scripts/run_baseline_forecast.py --write --calendar-factor    # upsert Forecast_Result, refresh marts
```

**Never drop `--calendar-factor`.** The runner's default is off, and the live forecast uses it (DEC-41). Measured on the copy, without it: total forecast 2,054,193.51 falls to 1,911,263.18, and the plan's dry run falls from 109 rows and 435,988 pieces to 100 rows and 324,826 pieces. `scripts.chapter_figures --verify` also fails. With it, all three return to the same values.

The run exits 2 if the ABC period is older than the latest sales month, so step 6 comes first. The range of expected months is derived from the latest sales month: there is nothing to edit. The report-only form rewrites the tracked `reports/BASELINE_FORECAST_RUN.md` when run on live.

### 8. Review flags

Directly after every forecast write, and before the plan.

```bash
python -m scripts.compute_review_flags --calendar-factor --write
```

GET /recommendations serves these flags, and a person must confirm a flagged row before accepting it. The flags are tied to the forecast they scored, so a forecast rerun leaves them stale (`planning_stale`, migration 0061) until this runs. The plan does not read them, so the order against step 9 does not change any quantity.

- `--calendar-factor` must match step 7. Without it the script stops at its reproduce check and writes nothing.
- **`scripts/run_month.py` does not run this step.** Run it by hand after that command's plan stage, before anyone reads the review.
- On the practice copy it refuses generated sales (`demand frame contains is_demo=true rows`), so the local demo does not run it for the new month.
- Run here on the existing 2026-03 cycle: 64 of 189 flagged, as on live. Not yet run on a new month.

### 9. Safety stock, reorder point and the plan

One script:

```bash
python scripts/run_lp.py --dry-run
python scripts/run_lp.py --retire-stale-pending
```

The second command plans a new cycle. On a cycle already planned it is refused with exit 2 and nothing is written. Passing `--replan` overrides that and moves a reviewed plan: do not add it without a decision on record.

### 10. Check the API

```bash
python scripts/smoke_api.py
```

Read-only. It issues 14 GETs over 8 routes, which is not every route the frontend uses.

## Removed on purpose: the accuracy backtest (old step 9)

**Do not put this step back before the defence, and do not move `WINDOW` in `scripts/backtest_forecast_run.py`.** The accuracy window is frozen at 2023-10..2026-02 deliberately: moving it moves published figures (KNOWN_ISSUES.md M1).

The old step also no longer worked. As written it exited 1 and wrote nothing, because one of its runs is pinned to the old window. The Dashboard's forecast-error card reads a different run by default, written by `scripts/accuracy_as_served.py --write-run`. That script stops when the latest sales month is not the window's end, and it refuses a label that already exists.

**What to expect meanwhile.** `python -m scripts.cycle_feedback --cycle YYYY-MM` scores the new month. By the code, the card falls back to the stored forecast for a month past the window (`backend/marts.py:1066-1069`); that has not been seen on real sales.

**It returns after the defence, as a decision on M1.** Rolling it forward means moving `WINDOW`, the hard-coded labels in `scripts/accuracy_as_served.py:423-433`, `backend/marts.DEFAULT_BACKTEST_LABEL` and the test that pins that label, and accepting that the quoted accuracy figures change.

## Also needed each month

| What | Command | Status |
|---|---|---|
| Closing the month, after a person has read the plan | `python -m scripts.close_cycle --cycle YYYY-MM --approved-by NAME --expect-cycle YYYY-MM --target-public` | Rehearsed on the practice copy only. No live cycle has been closed |
| Feedback report | `python -m scripts.cycle_feedback --cycle YYYY-MM` | Read-only. Withholds the forecast error when generated rows are in what it scores |
| Load, ABC, forecast and plan as one command (Unilever slices only) | `python -m scripts.run_month --month YYYY-MM --calendar-factor on ...` (usage in that file) | Refuses while this month's decisions are open. Leaves out steps 2, 3, 4, 8 and 10. A real file still stops at the sign-off in step 4. Its load has never run as a write on real new data |
| Check files without loading them (step 3 through the same command) | `python -m scripts.run_month --month YYYY-MM --calendar-factor on --check-files --slice ... --file ...` | The loader's own dry run. Writes only `etl_load_event` rows marked `dry_run` and working files in git-ignored folders. On live it also needs `--target-public`. Not yet run against a database |
| Decisions onto the practice copy (local setup only) | `python -m scripts.replay_practice_decisions --cycle YYYY-MM --write --json` | Replays through `decide_row`. The panel's Validate and Run do this. It refuses anything but two databases on the throwaway server. Not yet run against a database |

## Rehearsing on a scratch copy

Not run in this check, because a scratch build writes a schema to the live database.

```bash
python -m scripts.rehearse_fills --schema ssm_<name> --build
```

Then steps 3 to 5 with `--schema ssm_<name>` and no `--target-public`. Drop the scratch schema afterwards. The build reads the migrations it would apply and refuses, before creating anything, if any names `app.`, `public.` or `mart.` explicitly, because those would run against the live schemas: apply such a migration to public first. The clone copies no triggers, and public has one (`trg_inventory_fact_count_month`). Switch the planning mart off (`planning_mart.use_schema(None)`) before calling a decision endpoint against a scratch copy.

The rollover test runs through `scripts/check.sh --optin`, on the local database only.

## What changed from the old text

| Old step | Change | Why |
|---|---|---|
| 1 | Rewritten | Files are identified by content since 67d3443, and some take their month from invoice dates |
| 3, 5 | The commands are the same; the code is fixed | Every `delmonte:salesreturn_fact` slice was refused from 67d3443. Fixed 2026-11-04: all 18 months with a returns file now load. The two RMR months (2025-10, 2025-11) load through a separate slice, which by the code does not reach that line |
| 5 | Text corrected | "Changes nothing" held for real rows only |
| 7 | **Command corrected** | It omitted `--calendar-factor`. It also told the reader to edit `EXPECTED_MONTHS`, which no longer exists |
| New 8 | Added | Review flags were not in the old text |
| 8 | Renumbered 9 | `--replan` refusal added |
| 9 | **Removed** | See above |
| Rehearsal notes | Rollover command replaced | The old form now refuses anything but the local database |
