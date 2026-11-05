# Live demonstration: March sales through Data Management, the pages become April, Undo puts it back

Written 2026-11-05. Everything here was rehearsed through the real page (headless Chromium) on `ssm_rehearsal`, a restore of
`backups/full_backup_20261104T175951Z`. It has NOT been run on the real database: that is your click.

## What it does
- **Open** copies every table of `app`, `public`, `mart`, `demo` into a snapshot schema `demo_revert_live_demo` (about 12 s on the local copy; longer
  over the pooler) and opens a window in which the demand view and `mart.data_kind` also admit rows with `is_demo = true` and `_src_file =
  qa_synthetic_march` (and nothing else). The window is recorded in that schema, not in an environment variable.
- **Upload** takes a CSV (`sku_code, quantity_sold, net_amount`, optional `calendar_month, gsv, region`). It writes nothing until Run.
- **Accept the N orders** (or decide them on the Reorder page): `run_month` refuses to plan April while a March order waits (Audrey's gate, unchanged).
  The button accepts them through `decide_row`, the Reorder page's own writer, labelled "demonstration".
- **Run** loads the 709 rows (`is_demo = true`, 644 retired `synthetic_v2` March rows are set aside for the window), then ABC, forecast
  (calendar factor on, as live), plan, marts. Rehearsal: plan 2026-04 = 121 rows, 93 ordering, 920,486 pieces; plan 2026-03 stays 109 / 435,988.
- **Undo** puts back every table (all rows that differ), the view and the function, in ONE transaction that rolls back unless every table, view
  and function fingerprint equals the snapshot's; then re-reads the definitions, the plan (must equal the baseline) and the 51 pinned figures; the
  snapshot is dropped only if all pass. A failure keeps the snapshot and says so.
- Not put back, by design: `app.audit_log` (append-only), `app.user_session`, `app.auth_token`.

## Before you start
1. `local/demo_revert_proof.json` says `passed: true` and `local/demo_session_rehearsal.json` exists (both git-ignored, this machine). The rehearsal
   record carries a hash of the 8 files that make the demonstration; **editing any of them invalidates it** and `--live` refuses until it is rehearsed again.
2. Generate the file: `python -m scripts.make_demo_sales_file` (read-only; writes `local/demo/demo_march_sales.csv`, 709 rows, git-ignored: rule 9).
3. While the window is open, anyone reading the same database (the hosted site included) reads March as generated demonstration data, and anything
   saved meanwhile is undone by Undo. Do it when nobody else is working, and undo before you leave.

## The clicks (real database)
1. `python -m scripts.live_demo_app --live` (backend :8000, frontend :5173, this machine only; nothing deployed). Sign in with your admin password.
2. Data Management. Note the plan: 109 rows, 435,988 pieces. Look at the Dashboard and Reorder pages (you will compare).
3. **Open the demonstration.** Wait for "Window open, no file yet".
4. **Choose file**: `local/demo/demo_march_sales.csv`. "File ready".
5. **Accept the 73 orders for the demonstration** (or accept them on Reorder). Wait until step 3 says none waits.
6. **Run** (about 2 minutes). "April plan is on the pages". Dashboard and Reorder now show April, with the demonstration banner; forecast error is withheld.
7. **Undo the demonstration**, then **Yes, put everything back**. Wait for "Undone and proven: 109 rows, 435,988 pieces". Pages read as at step 2.
If any step fails, Undo is still there: it works from the snapshot, not from how far the run got (rehearsed: an interrupted session was undone from the page).

## What was NOT rehearsed
The Supabase pooler (:6543). The rehearsal is a direct local Postgres. The first live step, Open, is the test of that path (a failed Open drops its own
snapshot and changes nothing else). Render and Vercel were not touched.
