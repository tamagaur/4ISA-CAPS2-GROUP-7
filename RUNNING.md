# Running this project

This is the same "Getting Started" + "Troubleshooting" content from
`README.md`, pulled out on its own for quick reference. If the two ever
drift apart, `README.md` is the source of truth — update this file to
match, not the other way around.

## Prerequisites

- Python 3.12+ (developed and tested on 3.13). The pinned `xgboost==3.4.1`
  requires 3.12 or newer. On Python 3.11, install `xgboost==3.2.0` instead —
  the newest release that still supports 3.11.
- No system-level dependencies beyond Python and pip

## 1. Clone and check out the real trunk

```bash
git clone <repo-url>
cd Capstone-Project
git checkout group7/kelvin-etl
```

`master` is a stub trunk — none of the real ETL, Transform, or backend
work has been merged into it yet. Work off `group7/kelvin-etl`, which is
where all real work actually lives.

**Corrected 2026-09-20.** This used to say `AUDREY-TRY-MERGE`. That branch
still exists but was last updated 2026-08-17 and is **197 commits behind**
`kelvin-etl`, with nothing unique to it (`git rev-list --left-right --count
AUDREY-TRY-MERGE...kelvin-etl` returns `0  197`). Checking it out put you a
month back. Everything it had is already in `kelvin-etl`.

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

`lxml` was added 2026-08 — required to parse the Unilever La Union file,
which is actually an MHTML web archive despite its `.xls` extension. If
you installed before this date, re-run the command above even if you
think you're already set up.

`xgboost` became a pipeline dependency on 2026-09-21 — the long-history
forecasts (`analytics/forecasting/global_model.py`) use it. If you set up
before then, re-run the install; without it the forecasting tests and
`scripts/run_baseline_forecast.py` fail with `No module named 'xgboost'`.

## 3. Get the source data in place

`data/raw/` and `staging/` are both gitignored — neither client files nor
Extract's output are ever committed. Everyone on the team has the same
shared "SAN SAN Marketing" folder; copy it in, keeping the subfolder
structure:

```bash
cp -r "SAN SAN Marketing/Del Monte" "data/raw/Del Monte"
cp -r "SAN SAN Marketing/SSIS" "data/raw/SSIS"
cp -r "SAN SAN Marketing/Unilever" "data/raw/Unilever"
```

`UnileverLaUnionSalesperSKU2023to2026.xls` must end up inside
`data/raw/Unilever/` specifically. Without it, the `unilever_sku` family
stages 0 rows and looks broken even though the code is fine — it's a
missing-file problem, not a bug, but it's easy to mistake for one.

## 4. Run Extract

```bash
python -m analytics.etl.extract.driver
```

Takes a few minutes — the real corpus is 1,000+ sheets across 194 files.
You'll know it worked when the output ends with something like:

```
Staged 1042 sheet(s) across 7 families to .../staging
Sheets scanned: 1042
Staged: 1042
Rejected: 0
```

This writes `staging/_manifest.json`, `staging/_extract_qc.md`, and one
Parquet file per staged sheet.

## 5. Run the tests

```bash
pytest tests/ -v
```

Expected as of 2026-09-23: **554 passed / 8 skipped / 0 failed** (with
`xgboost` installed and `.env` pointing at the live database). The old
`Users` vs `users` casing failures are fixed. Any failure now means
something is wrong — see Troubleshooting.

(Was 495 on 2026-09-21. The merge of `kelvin-etl` added the ETL recovery
and real-view suites; 2026-09-23's unit/LP-cycle fixes added 12 more.)

If you see tests skipping that you expected to run, it almost always means
step 3 or step 4 wasn't done yet — several tests are gated on `data/raw/`
or `staging/` actually existing. (This step previously said "109 passed",
which pre-dated the backend and analytics suites.)

## Adding a new month (live database)

Written 2026-10-19 from the end-to-end ingestion audit. Steps 1-5 were run
end to end on a scratch copy of public (`ssm_e2e_audit`) and loading the same
month twice was shown to duplicate nothing. Steps 6-9 were run report-only
against public (no `--write`); their write forms below are the documented
ones, not exercised in that audit.

**0. Migrations must be clear.** A public load refuses while any migration
file is unapplied (`refusing: migrations pending on public`). Back up, then
apply with `python -m scripts.run_canonical_load --schema public
--target-public --schema-only`. As of 2026-10-19, 0059 and 0060 are pending
on public, and 0060 drops `app.users.avatar_data_url`.

**1. Put the files in `data/raw/`.** The month comes from the file NAME
(plus up to three parent folder names), never from a date typed inside the
workbook. The Del Monte "Actual as of" cell is not read at all. Keep the
existing naming:

| Data | Where | Name must contain |
|---|---|---|
| Del Monte sales register, returns, sell-out, purchases, inventory sign-off | `data/raw/Del Monte/MONTHLY REPORT - <MONTH> <YEAR>/` | month name + 4-digit year |
| Unilever stock (SSIS) | `data/raw/SSIS/<YEAR>/SSIS <MONTH> <YEAR>.xlsx` | month name + 4-digit year (`SSIS FEBRUARY 202.xlsx` only works because its folder is `2026/`) |
| Unilever SKU sales | `data/raw/Unilever/UnileverLaUnionSalesperSKU2023to2026.xls` | this exact name: SSM's updated multi-year file replaces it |

**2. Back up the tables a load writes to** (read-only; verifies every file's row count):

```bash
python -m scripts.backup_tables sales_fact purchase_fact salesreturn_fact sellout_fact inventory_fact unilever_sku_demand_fact derived_receipt_fact sku_demand_fill etl_quarantine etl_coverage etl_load_event product_dimension customer_dimension schema_migrations
python -m scripts.backup_tables --schema app audit_log
```

Restore: each `backups/tables_<time>/data/<table>.csv` is a `COPY ... WITH
(FORMAT csv, HEADER)` export; `structure.json` has the columns, keys and
indexes to recreate the table if needed.

**3. Dry run** (writes only `etl_load_event` rows marked `dry_run`). One
`--slice principal:table:YYYY-MM` per table and month:

```bash
python -m scripts.run_canonical_load --schema public --target-public --dry-run \
  --slice delmonte:sales_fact:YYYY-MM --slice delmonte:salesreturn_fact:YYYY-MM \
  --slice delmonte:sellout_fact:YYYY-MM --slice delmonte:purchase_fact:YYYY-MM \
  --slice delmonte:inventory_fact:YYYY-MM \
  --slice unilever:unilever_sku_demand_fact:YYYY-MM --slice unilever:inventory_fact:YYYY-MM
```

Read the slice summary: `real A->B (-x/+y)` per slice, refusals, and any
`validation_warning` (e.g. a peso total far outside earlier months).

**4. Sign off** - the one human step. The dry run prints the run key:

```bash
python -m analytics.etl.transform_signoff --transform-dir transform/slices/<run key> --decision approved --by "<name>"
```

**5. Load** - the step 3 command without `--dry-run`. It deletes and
re-inserts each slice's real rows in one transaction (re-running the same
month changes nothing, `-0/+0`), then runs the fill step and refreshes the
marts.

**6. ABC** (Tier A basis: `analytics.params.TIER_A_BASIS`):

```bash
python -m analytics.classification.orchestrate_abc --period YYYY-MM --schema public --method t12m_new --principal unilever
python -m analytics.classification.orchestrate_abc --period YYYY-MM --schema public --method single --principal delmonte
```

**7. Forecast.** First move `EXPECTED_MONTHS` in
`scripts/run_baseline_forecast.py` (hard-coded `2023-01..2026-02`) to end at the
new month, or the missing-month check never looks at it. Then:

```bash
python scripts/run_baseline_forecast.py            # report only
python scripts/run_baseline_forecast.py --write    # upsert Forecast_Result, refresh marts
```

**8. Safety stock, reorder point and the LP** (one script):

```bash
python scripts/run_lp.py --dry-run
python scripts/run_lp.py --retire-stale-pending
```

**9. Accuracy backtest** (the dashboard's accuracy card). Move `WINDOW` in
`scripts/backtest_forecast_run.py` (hard-coded to end 2026-02), then:

```bash
python -m scripts.backtest_forecast_run --write --mart-schema mart --target-public --replace
```

**10. Check the API:** `python scripts/smoke_api.py`.

**Rehearsing on a scratch copy** (`python -m scripts.rehearse_fills --schema
ssm_<name> --build`, then step 3-5 with `--schema ssm_<name>` and no
`--target-public`): the build and every scratch load apply pending migrations
to the scratch schema, but a migration that names `app.users` explicitly
(0059, 0060) runs against the LIVE table. Do not build a scratch copy while
such a migration is pending on public. The clone also copies no triggers;
public has one (`trg_inventory_fact_count_month`, 0039). Drop the scratch
schema afterwards.

**The scratch build refuses, it does not warn (2026-10-24).** `rehearse_fills --build` and every scratch migration 
read the migrations they would apply and REFUSE, before creating anything, if any names `app.`, `public.` or `mart.` explicitly: 
those statements run against the live schemas whatever the scratch search_path says. Apply such a migration to public first 
(after a backup), then build. `scripts/rollover_scratch_test.py` (`ROLLOVER_SCRATCH=1 pytest tests/etl/test_rollover_scratch.py`) 
proves the receipt ledger, settlement, the opening-stock view and `close_cycle` on `ssm_rollover_test` with a synthetic March, 
checks that public, mart and app are byte-for-byte unchanged, and drops the schema. Switch the planning mart OFF 
(`planning_mart.use_schema(None)`) before calling any decision endpoint against a scratch copy: it writes `mart.planning_mart`, which is live.

## Troubleshooting

**The dashboard breaks after you pull.** Run this first — read-only, about ten
seconds, writes nothing:

```bash
python scripts/smoke_api.py
```

It drives all 17 frontend-facing routes against the live database and tells you
which side the fault is on. All PASS means the bug is in the frontend. Full
diagnosis, the Del Monte null shapes the frontend must tolerate, and the two
known gotchas (a stale `starlette` pin; `--schema` is now required on
`orchestrate_abc.py` and `orchestrate_segment.py`) are in
[reports/FRONTEND_HANDOFF_2026-09-20.md](reports/FRONTEND_HANDOFF_2026-09-20.md).

**Forecasting tests fail to import (`No module named 'xgboost'`).** Re-run
`pip install -r requirements.txt` — see step 2 for the Python 3.11 case.

**`test_abc_schema_contract` lists key columns several times.** Fixed
2026-09-21: the live database also holds experiment schemas
(`ssm_abc_repro`, `ssm_synth_v2`, `ssm_abc_phase2`) with copies of the
tables, and the test now reads only `public`.

**A family stages 0 rows.** Check two things: the file is under the
subfolder its principal implies (Del Monte / SSIS / Unilever), and its
filename matches what the driver looks for. `unilever_sku` in particular
needs the exact file `UnileverLaUnionSalesperSKU2023to2026.xls` inside
`data/raw/Unilever/` — see step 3 above.

**`daily_sales_report` always stages 0 rows.** This is expected, not a
bug. No files in the current corpus match the real daily-report naming
convention ("DAILY SALES REPORT MM.DD.YYYY.xlsx") — the folders named
"DAILY REPORT - ..." under `data/raw/Del Monte/` are actually ordinary
monthly Sales Register files under a misleading folder name.

**Tests skip unexpectedly.** `data/raw/` or `staging/` isn't populated —
redo steps 3 and 4 before assuming something's broken.

**`ModuleNotFoundError: No module named 'lxml'` when parsing the
Unilever file.** You installed dependencies before 2026-08 — re-run
`pip install -r requirements.txt`.
