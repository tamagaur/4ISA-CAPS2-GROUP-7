# Loading a month, and rolling any loaded month back (Data Management)

Written 2026-11-06. Replaces the one-month demonstration runbook of 2026-11-05. Everything here was rehearsed through the real page (headless Chromium) on `ssm_ui`, a
restore of `backups/full_backup_20261104T175951Z`, and through the command line by `python -m scripts.month_load_rehearsal` (the gate). The live walk is recorded in STATE.md.

## What it is
One interface: **Data Management → Monthly Data Processing** on the real database. Nothing else loads a month.

1. **Upload monthly data.** Choose the sales file for the processing month (`.csv`, `.xlsx`, `.xls`; any name). The month is read from INSIDE the file (a month or date
   column, or a month written above the table: `analytics/month_file.py`), never from its name. A file that cannot be dated, is dated in two months, has a date that could be
   two things (`03/04/2026`), or is for a month other than the next one is refused on the spot with the reason, and the slot is left as it was.
2. **Validate.** Reads the file again and checks it against the system and the Reorder page's decisions. Loads nothing.
3. **Run the month.** Confirm. If orders of the current plan still wait for a decision, the dialog offers to accept them at the recommended quantity (the next plan cannot be
   made while one waits: Audrey's gate, unchanged). Then, in one job: save a **rollback point**, write the file's rows labelled `is_demo = true`, run ABC, the forecast, safety
   stock, the order plan and the marts. The step shows elapsed time while it runs and the total when it ends.
4. **Loaded months.** Each month loaded, the plan it produced, and (admin only) **Roll back <month>**.

The sales of a month loaded this way are GENERATED when SSM has not sent the file, and every page says so (banner: "Generated sales. Sales for March 2026 is generated: SSM
has not sent that month…"). Forecast error is not shown for a period that rests on them (hard rule 2), and the product page says why where its likely range is missing.

## Rollback
- A **rollback point** is taken before each month loads: a copy of every table the load can change, a fingerprint of EVERY table, view and function, and the text of the
  two definitions that change while labelled rows are loaded (`analytics/demo_session.py`). It is a schema `demo_revert_m<YYYYMM>` in the database itself, so a restart,
  another browser or another server sees the same history. **Two** are kept (a checkpoint is ~106 MB on the live database, read 2026-11-05); loading a third releases the oldest
  first, and that month can then no longer be rolled back (the page says so).
- **Roll back March** restores the state before March was loaded, and removes April if it was loaded after (the dialog says so). One transaction; it rolls back unless every
  table, view and function equals the checkpoint's. Afterwards it reads the plan (must equal what it was, no later plan may exist) and, when this returns to the original state,
  runs the 51 pinned figures. Anything saved after the checkpoint, decisions on the Reorder page included, is put back too. Not put back, by design: `app.audit_log`
  (append-only), `app.user_session`, `app.auth_token`.
- **Who.** Rollback is the admin-only permission `data.rollback`; a staff account never sees the control, whatever overrides it holds. No environment variable or startup flag
  decides it: once the API is on Render there is no terminal.
- **The gate.** On a database that is not this machine's throwaway server, load and rollback run only when `docs/MONTH_LOAD_REHEARSAL.json` is an attestation of THIS code (it holds a
  hash of the files that load and roll back; any edit invalidates it until `python -m scripts.month_load_rehearsal --backup <dir>` passes again on a restored copy). It is committed,
  so the hosted API has it. Without it the page says loading is switched off and why.

## From a terminal (same code, same gate)
    python -m scripts.demo_session status
    python -m scripts.demo_session check-file --file F
    python -m scripts.demo_session load --file F --by NAME --accept-waiting --target-public
    python -m scripts.demo_session rollback --month 2026-03 --by NAME --yes --target-public
    python -m scripts.data_management_app --rehearsal --restore backups/full_backup_<stamp> --db ssm_ui    # the app on a restored copy, no password
    python -m scripts.data_management_app --live                                                           # the app on .env's database, your own password
    python -m scripts.make_demo_sales_file --month 2026-03        # a generated file (writes local/demo/, git-ignored: hard rule 9)

## What is not proven
Render and Vercel were not touched and were not run: whether the hosted API has what the child processes need (ABC, the forecast and the LP import the analytics packages) is
unverified. The hosted site shows a loaded month to everyone reading the same database, labelled, until it is rolled back.
