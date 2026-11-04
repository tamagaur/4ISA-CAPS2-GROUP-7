# Local demo runbook: close a practice month from the browser

**What this shows:** the real monthly steps running on labelled generated sales, on a copy on this laptop. **What to say about it:** the April plan it produces is practice, not a result. It does not show the deployed service, which has not been redeployed, and it does not show a real new monthly file running, because none has ever existed.

Walked through in a browser on 2026-11-03, from `Main-BE`, with the commands below typed into PowerShell, and it took about 5 minutes then. **Sections 4 and 5 changed on 2026-11-04 and have not been walked through since**: the plan's decisions now come first, so expect it to take longer.

**Before you start:** PowerShell open in the repo folder (`C:\Users\kyuan\Capstone-Project`), and the folder `backups\full_backup_20261102T170343Z` on this machine. It is git-ignored, so another machine will not have it.

## 1. Start everything

Terminal 1. This one stays open and keeps printing.

```powershell
.venv\Scripts\python.exe -m scripts.local_pg start
.venv\Scripts\python.exe -m scripts.local_app --reset backups\full_backup_20261102T170343Z
```

| You should see | Meaning |
|---|---|
| `up on 127.0.0.1:55432` | The throwaway database server is running |
| `restored 62 tables, 547,433 rows` | The backup loaded (about 30 s) |
| `applied ...0073_decision_column_comments.sql`, then `applied ...0074_views_real_rows_only.sql` | The two migrations newer than the backup |
| `ssm_practice is a fresh copy of ssm_local` | The copy the panel works on is ready |
| `LOCAL APP on the throwaway database, signed in as ...  Not live.` then a long `localStorage.setItem(...)` line | **Copy that long line** |
| `Uvicorn running on http://127.0.0.1:8000` | Ready, about 45 s after the first command |

A red `NOTICE: schema "public" already exists, skipping` is harmless.

## 2. Bring the review flags up to live's count

Terminal 2. The backup was taken before the flags were last written, so it holds 25 flagged of the 109 planned. Live holds 27. Skip this only if the flag count will not be shown.

```powershell
$py = (Resolve-Path .venv\Scripts\python.exe).Path
& $py -m scripts.local_pg run -- $py -m scripts.compute_review_flags --calendar-factor --write
```

It should end with `"needs_review": 64`, `wrote 189 review_flag rows for 2026-03-01`, `planning mart refreshed`. The plan does not read the flags, so it stays 109 rows and 435,988 pieces. Keep the full `$py` path after `--`: a bare `python` there starts the system Python, which crashes on `Router.__init__() got an unexpected keyword argument 'on_startup'`.

This changes the database behind the pages only. The practice copy keeps 25, and the panel does not show flags.

## 3. Sign in

1. In Chrome open **http://localhost:5173**. Use the word `localhost`: `127.0.0.1:5173` is refused.
2. Press F12, open **Console**, paste the long line and press Enter. If Chrome refuses the paste, type `allow pasting`, press Enter, and paste again.

You land on **Data management**, signed in without a password as the first admin account on the copy (the sidebar shows that person's name). A blue note at the top reads **Local practice database**.

## 4. Settle the March plan first

**Changed 2026-11-04, and not yet walked through in a browser.** `scripts.run_month` now refuses to run while this month's plan has an order nobody has decided, so the demo goes through the real approval. Details and limits: [MONTHLY_BATCH_REVIEW.md](MONTHLY_BATCH_REVIEW.md).

| Do this | Screen shows |
|---|---|
| Open **Reorder Recommendations** in the sidebar | The March 2026 plan |
| Use **Accept all** on the rows it offers | Those rows are accepted |
| Decide each remaining ordering row on its own, accepting or dismissing it | Flagged rows ask for their own confirmation, so Accept all leaves them out |
| Settle any staff request on the **Requests** tab | Nothing left awaiting an admin |

On live on 2026-11-04 the plan had 73 rows ordering something, 19 of them flagged, and the 36 rows ordering nothing have no buttons and do not count. Those are a baseline, not constants: the page reads the current rows. These decisions are written to `ssm_local`, the pages' database, and stay there until the next `--reset`. Not yet timed.

## 5. The five steps

Back on **Data Management**.

| Do this | Screen shows | Wait |
|---|---|---|
| **Step 1:** click **No file? Generate practice sales** | Step 1 changes to "2026-03 sales are in the database." The blue note gains: **"709 sales rows this month are generated practice data, so nothing here is a real result."** | About 10 s |
| **Step 2:** click **Run Validation** | The Reorder page's decisions are carried onto the practice copy through `decide_row`. The checklist reads **All required checks passed**, with a warning for the generated sales. If orders are still undecided, the **Pending Reorder Decisions** dialog opens and **Review Recommendations** takes you back to section 4 | A few seconds |
| **Step 3:** choose **On (as the live forecast)**. **Run the Month** stays disabled until you choose | The button becomes clickable | |
| Click **Run the Month**, then **Confirm and Run** | **Processing 2026-03** and the stages it has reached. A reload here is safe: it comes back still running | 2 to 3.5 min when last timed, with nothing decided |
| **Step 4:** read **Monthly Processing Complete** and the table | See below. The blue note still carries the 709 label | |
| **Step 5:** tick **I have read the plan above**. **Close 2026-03** stays disabled until you tick | The button becomes clickable | |
| Click **Close 2026-03** | "2026-03 is closed." | 3 s |

**The review screen should read:**

| Plan | Products | Ordering | Pieces | Note |
|---|---|---|---|---|
| 2026-03 | 109 | 73 | 435,988 | Current |
| 2026-04 | **not yet measured** | | | |

**The April row will change, and that is correct.** It read 121, 110 and 1,213,168 pieces when nothing was decided. Accepted orders now count as stock on the way (`stock_opening_v`: a receipt due after the count date), so expect a different figure, probably a smaller one. Do not force the old total. Write the measured figure here after the first walkthrough. On this copy the decisions are dated today, months after the 2026-04-06 count, so every accepted order counts as still on the way, which a real month's timing would not do.

Below it: "stock count 2026-03 (taken 2026-04-06): 1,685,621 pieces, 0.70x the median of the 6 before it"; "forecast error withheld: 709 generated sales rows are in this cycle..."; the decisions you made, with the rows that order nothing shown as not decided.

The 2026-03 row is the only place the panel shows 109 and 435,988, and it appears only from this step on. The withheld error is deliberate: no accuracy figure is shown on generated sales. The April figure is a practice number, never quote it as a plan.

## After the close

- **The Reorder page still shows March 2026**, with the decisions you made in section 4, because the pages do not read the practice copy. A decision travels one way, from the page to the copy.
- **A reload moves the panel on.** Its processing month then reads 2026-04 with empty steps, and the plan table and the 709 label are gone from the screen. Nothing is lost.
- **To show that the rows stay labelled** (should print `709 | 709`):

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h 127.0.0.1 -p 55432 -U postgres -d ssm_practice -At -c "select count(*), count(*) filter (where is_demo and _src_file='qa_synthetic_march') from unilever_sku_demand_fact where calendar_month::text like '2026-03%'"
```

## If it goes wrong

**1. You end up on the login page, or the panel is missing.**
The sign-in line only works for the app run that printed it. A restart, or a second start of the app, makes a new one. Paste the **newest** line from Terminal 1. Never type a password here.
If the page reads "Ingestion is not connected yet", the backend was not started by `scripts.local_app`. Stop it and go back to section 1.

**2. Starting the app fails with `Port 5173 is already in use` or `[Errno 10048] ... 127.0.0.1, 8000`.**
An earlier app is still running. Stop it, then repeat section 1:

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

**3. The panel says "Monthly Processing Failed", or you need to start again.**
It names the stage that stopped and what to do. The whole output is in `local/monthly_batch/logs`, in the file named by the job number under **Review available details**. Running again skips the finished steps. To go back to the start, including after a close, repeat section 1 with `--reset` and then sections 2, 3 and 4: the reset also undoes the decisions. It takes about 45 s, and it can only touch the throwaway server. If you hit this in front of the panel and do not have 5 minutes, say what stopped and move on: do not improvise a command.

## When you finish

Press Ctrl+C in Terminal 1, or use the command in item 2, then:

```powershell
.venv\Scripts\python.exe -m scripts.local_pg stop
```

Nothing above writes to live. `scripts.local_app` refuses any database but `127.0.0.1:55432`, and the batch routes do not exist on the deployed service.
