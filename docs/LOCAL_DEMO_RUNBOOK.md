# Local demo runbook: close a practice month from the browser

**What this shows:** the real monthly steps running on labelled generated sales, on a copy on this laptop, and the Dashboard and Reorder pages following them. **What to say about it:** the April plan it produces is practice, not a result. It does not show the deployed service, which has not been redeployed, and it does not show a real new monthly file running, because none has ever existed.

Walked through in Chrome on 2026-11-04, from the branch `kelvin/practice-pages`, on this laptop. It has not been walked on any other machine. Takes about 5 minutes from the first command to a closed month.

**Before you start:**

- PowerShell open in the repo folder (`C:\Users\kyuan\Capstone-Project`), on the branch `kelvin/practice-pages`. `Main-BE` does not have this behaviour until that branch is merged.
- The folder `backups\full_backup_20261102T170343Z` on this machine. It is git-ignored, so another machine will not have it.
- Already installed: the Python packages in `.venv`, the frontend packages (`npm install` in `frontend`), PostgreSQL 17 in `C:\Program Files\PostgreSQL\17\bin` (or set `PG_BIN` to its folder), Chrome. The very first `local_pg start` on a machine also needs `openssl` on the PATH.

## 1. Start everything

Terminal 1. This one stays open and keeps printing.

```powershell
.venv\Scripts\python.exe -m scripts.local_pg start
.venv\Scripts\python.exe -m scripts.local_app --reset backups\full_backup_20261102T170343Z
```

Lines appear in this order, except the last few, where the frontend and the backend start side by side and may interleave. Ready is about a minute after the first command.

| You should see | Meaning |
|---|---|
| `up on 127.0.0.1:55432` | The throwaway database server is running. Printed by the first command, which then returns |
| `structure loaded, 0 errors` | The restore has started. **Nothing more prints for about 30 s. This is not a stall** |
| `restored 62 tables, 547,433 rows in ...s` | The backup loaded |
| A red `NOTICE: schema "public" already exists, skipping` | Harmless |
| `=== run_canonical_load: schema='public'  dry_run=False  target_public=True ===`, then `[schema] ensuring 'public' is migrated` | The migration runner, on the throwaway database. `target_public` means that database's own `public` schema, not live |
| About 70 lines of `skipped analytics\db\...sql — already in ...` | Migrations the backup already holds |
| `applied ...0073_decision_column_comments.sql`, then `applied ...0074_views_real_rows_only.sql` | The two migrations newer than the backup |
| `--schema-only: 'public' is migrated. No loads. Exiting.` | The runner has finished, as it should |
| `ssm_practice is a fresh copy of ssm_local; ...` | The copy the panel and the pages work on is ready |
| `LOCAL APP on the throwaway database, signed in as ...  Not live.` then a long `localStorage.setItem(...)` line | **Copy that long line** |
| `> vite --port 5173 --strictPort`, `VITE ... ready in ... ms`, `Local: http://localhost:5173/`, `Network: use --host to expose` | The frontend is up |
| `INFO: Started server process`, `FRONTEND_URL is not set: email links will point at http://localhost:5173 ...` | The backend is starting. The FRONTEND_URL line is harmless here: this app sends no email in the demo |
| `Uvicorn running on http://127.0.0.1:8000` | The backend is ready |

## 2. Bring the review flags up to live's count

Terminal 2. The backup was taken before the flags were last written, so it holds 25 flagged of the 109 planned. Live holds 27. Skip this only if the flag count will not be shown.

```powershell
$py = (Resolve-Path .venv\Scripts\python.exe).Path
& $py -m scripts.local_pg run --practice -- $py -m scripts.compute_review_flags --calendar-factor --write
```

The first line reads `[PRACTICE RUN ON GENERATED SALES, NOT A RESULT] on ssm_practice: everything below runs on the practice copy`. It prints on anything run on this copy, and at this point no generated sales are in it yet. Further down come `"needs_review": 64` and a table of the flagged products. It ends with `wrote 189 review_flag rows for 2026-03-01 (replaced 189)` and `[marts] planning mart refreshed ...`. The plan does not read the flags, so it stays 109 rows and 435,988 pieces. Keep the full `$py` path after `--`: a bare `python` there starts the system Python, which crashes on `Router.__init__() got an unexpected keyword argument 'on_startup'`.

This runs on the practice copy, the database behind the pages. The panel does not show flags.

## 3. Sign in

1. In Chrome open **http://localhost:5173**. Use the word `localhost`: `127.0.0.1:5173` is refused.
2. Press F12, open **Console**, paste the long line and press Enter. If Chrome refuses the paste, type `allow pasting`, press Enter, and paste again.

You land on **Data management**, signed in without a password as the first admin account on the copy (the sidebar shows that person's name). A yellow **Practice copy** note is at the top of this and every page, and below it a blue note reads **Local practice database**.

Open the **Reorder** page in a second tab now if you want the before and after. It shows the Mar 2026 plan: "0 accepted, 0 dismissed, 109 not decided" and 435,988 pieces. The Dashboard shows Mar 2025 to Feb 2026.

## 4. The four steps

Do not reload the panel after step 4 until you have finished talking about the plan (see "After the close").

| Do this | Screen shows | Wait |
|---|---|---|
| **Step 1:** click **No file? Generate practice sales** | Step 1 changes to "2026-03 sales are in the database." The blue note gains: **"709 sales rows this month are generated practice data, so nothing here is a real result."** The two file slots disappear | 3 s |
| **Step 2:** choose **On (as the live forecast)**. **Run 2026-03** stays disabled until you choose | The button becomes clickable | |
| Click **Run 2026-03** | "Running, this takes a few minutes" and a live log (see below). A reload here is safe: it comes back still running | 2 to 3.5 min |
| **Step 3:** read the table | See below. The blue note still carries the 709 label | |
| **Step 4:** tick **I have read the plan above (1,213,168 pieces)**. **Close 2026-03** stays disabled until you tick | The button becomes clickable | |
| Click **Close 2026-03** | "2026-03 is closed." | 3 s |

**The log during the Run.** Normal lines, none of them a failure:

| Line | Meaning |
|---|---|
| `[abc] running`, `[forecast] running`, `[lp] running` | The step that has started |
| `[computed on generated sales] ...` | The forecast's own marker on every line it prints on this copy |
| `INFO: sigma_d derived from monthly sigma ...`, more than a hundred of them | The safety stock calculation, one per product |
| `WARNING: <product> (unilever): not in the opening stock count (2026-03) ... counted as 0 on hand` | A planned product missing from the stock count. It is reported, and the plan treats it as stated |
| `WARNING: ... stock counts are from the Ilocos Sur warehouse workbook; per-product sales are La Union only ...` | A recorded limitation, on every run |

A failure reads differently: the panel changes to **"The last step stopped (exit N)"**.

**The review screen should read:**

| Plan | Products | Ordering | Pieces | Note |
|---|---|---|---|---|
| 2026-03 | 109 | 73 | 435,988 | Last month's plan, not closed yet |
| 2026-04 | 121 | 110 | 1,213,168 | On the Reorder page now, not closed. 2.78x the 2026-03 plan |

Below it: "stock count 2026-03 (taken 2026-04-06): 1,685,621 pieces, 0.70x the median of the 6 before it". A moment later: "forecast error withheld: 709 generated or uploaded practice sales rows are in this cycle..." and "0 accepted, 0 dismissed, 109 not decided. 0 quantity changes (+0 pieces)."

The panel is closing March while the Reorder page already shows April's plan: the page moves at Run, the panel's month at Close. Both screens now say so, and the Reorder page's line ends "This plan (2026-04) is run, not closed. 2026-03 is run, not closed."

1,213,168 is a practice number, never quote it as a plan. Every page withholds the forecast error on purpose: see the next section.

## After the close

- **The pages have moved, and have said so all along.** Reorder shows the Apr 2026 plan: 121 products, 1,213,168 pieces, "0 accepted, 0 dismissed, 121 not decided". Dashboard shows Apr 2025 to Mar 2026, latest month Mar 2026 ₱27.5M. They move at **Run**, when the April plan is written.
- **The Close changes neither page.** Their text and `GET /recommendations` are the same before and after it, and nothing on the Reorder page says whether a plan has been run or closed. Do not point at the page to show the close: point at the panel's "2026-03 is closed."
- **The forecast error is withheld.** The Dashboard's "How close the forecasts were" card, the product's reliability and past misses, and the likely range say "Forecast error withheld..." instead of a number, because March is generated (hard rule 2). A date range ending Feb 2026 still shows the real 10% and 35%. The same happens after a sales file is uploaded, with its own reason: nothing on the copy can tell a real file from a made-up one.
- **Every answer labels itself.** Besides the yellow note, each answer's body says it is practice: a `practice_copy` block with `"not_a_result": true` and `"generated_months": ["2026-03"]`. Anything dated March carries `"generated_sales_month": true`, its `data_kind` reads `generated_practice`, and anything dated later carries `"rests_on_generated_sales": true`. To see it: F12, **Network**, click a request, **Response**.
- **A reload moves the panel on.** It then reads "Monthly batch for 2026-04" with empty steps, and the plan table and the 709 label are gone from the screen. Nothing is lost.
- **To show that the rows stay labelled** (should print `709|709`):

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h 127.0.0.1 -p 55432 -U postgres -d ssm_practice -At -c "select count(*), count(*) filter (where is_demo and _src_file='qa_synthetic_march') from unilever_sku_demand_fact where calendar_month::text like '2026-03%'"
```

## Trying a stock count file (optional, not part of the 5 minutes)

The **Stock count** slot in step 1 loads the workbook you give it. Use it **before** clicking Generate: once the month's sales are in, the slots disappear. Choose the file, then Generate, then Run as above.

- **It is checked at once**, against what the loader needs (`docs/RAW_FILE_REQUIREMENTS.md`), and refused with what is missing. A file named for another month is refused, for example: "SSIS FEBRUARY 2026.xlsx says it is 2026-02, and this is the 2026-03 batch."
- **The name matters.** The month comes from the file name: `SSIS MARCH 2026.xlsx`. The sheet must be named `SOH(<date>)`.
- **It replaces that month's count, on this copy only.** The workbook in `data/raw/` for that month is left out of the run, and `data/raw/` itself is not touched.
- **The Run takes much longer.** Measured with one count, in Chrome: 466 s, about 8 minutes, against about 2 minutes with no file (763 s before 2026-11-04, when a dry run read every SSIS workbook first). The load reads every SSIS workbook once, because the manifest covers them all, and that read is about 4 minutes. A sales file alone took 200 s. Do not do this in front of an audience.
- **The log gains** `[practice load] Run pressed by <you>. The system signs the manifest; nobody reviews it.`, `[manifest] run key ...` and `[practice load] sign-off recorded by system: auto-signed on the practice copy, no review`. The manifest was read by nobody, and the record says so: `_signoff_practice_auto.json` in that run's folder under `transform/slices/`, and `system: auto-signed...` as the name on the `audit_log` and `etl_load_event` rows.
- **To confirm it read your file** (should print the upload's path and the row count):

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h 127.0.0.1 -p 55432 -U postgres -d ssm_practice -At -c "select _src_file, count(*) from inventory_fact where _period='2026-03' and principal='unilever' and not is_demo group by 1"
```

The March workbook from `data/raw/SSIS/2026/` uploaded unchanged gave 785 rows from the upload's path and the same 1,213,168.

## If it goes wrong

**1. You end up on the login page, or the panel is missing.**
The sign-in line only works for the app run that printed it. A restart, or a second start of the app, makes a new one. Paste the **newest** line from Terminal 1. Never type a password here.
If the page reads "Ingestion is not connected yet", the backend was not started by `scripts.local_app`. Stop it and go back to section 1.

**2. Starting the app fails with `Port 5173 is already in use` or `[Errno 10048] ... 127.0.0.1, 8000`.**
An earlier app is still running. Stop it, then repeat section 1. This prints which of the two happened, and neither is an error:

```powershell
$found = Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue
if ($found) { $found | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }; "Stopped the running app." } else { "Nothing is running on 8000 or 5173." }
```

**3. A step says "The last step stopped (exit N)", or you need to start again.**
Open the log under the panel and read its last lines: the reason is there. Clicking Run again skips the finished steps. To go back to the start, including after a close, stop the app (item 2), repeat section 1 with `--reset` and then sections 2 and 3. It takes about a minute, it also clears any uploaded files, and it can only touch the throwaway server. If you hit this in front of the panel and do not have 5 minutes, say what stopped and move on: do not improvise a command.

## When you finish

Press Ctrl+C in Terminal 1, or use the command in item 2, then:

```powershell
.venv\Scripts\python.exe -m scripts.local_pg stop
```

It prints `waiting for server to shut down.... done` and `server stopped`.

Nothing above writes to live. `scripts.local_app` refuses any database but `127.0.0.1:55432`, the batch routes do not exist on the deployed service, and a Run with a file refuses any database but the practice copy.
