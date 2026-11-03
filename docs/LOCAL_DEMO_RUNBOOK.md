# Local demo runbook: close a practice month from the browser

**What this shows:** the real monthly steps running on labelled generated sales, on a copy on this laptop. **What to say about it:** the April plan it produces is practice, not a result. It does not show the deployed service, which has not been redeployed, and it does not show a real new monthly file running, because none has ever existed.

Walked through in a browser on 2026-11-03, from `Main-BE`, with the commands below typed into PowerShell. Takes about 5 minutes from the first command to a closed month.

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
| `applied ...0073_decision_column_comments.sql` | The one migration newer than the backup |
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

## 4. The four steps

Do not reload after step 4 until you have finished talking about the plan (see "After the close").

| Do this | Screen shows | Wait |
|---|---|---|
| **Step 1:** click **No file? Generate practice sales** | Step 1 changes to "2026-03 sales are in the database." The blue note gains: **"709 sales rows this month are generated practice data, so nothing here is a real result."** | 3 s |
| **Step 2:** choose **On (as the live forecast)**. **Run 2026-03** stays disabled until you choose | The button becomes clickable | |
| Click **Run 2026-03** | "Running, this takes a few minutes" and a live log. A reload here is safe: it comes back still running | 2 to 3.5 min |
| **Step 3:** read the table | See below. The blue note still carries the 709 label | |
| **Step 4:** tick **I have read the plan above (1,213,168 pieces)**. **Close 2026-03** stays disabled until you tick | The button becomes clickable | |
| Click **Close 2026-03** | "2026-03 is closed." | 3 s |

**The review screen should read:**

| Plan | Products | Ordering | Pieces | Note |
|---|---|---|---|---|
| 2026-03 | 109 | 73 | 435,988 | Current |
| 2026-04 | 121 | 110 | 1,213,168 | 2.78x the current plan |

Below it: "stock count 2026-03 (taken 2026-04-06): 1,685,621 pieces, 0.70x the median of the 6 before it"; "forecast error withheld: 709 generated sales rows are in this cycle..."; "0 accepted, 0 dismissed, 109 not decided."

The 2026-03 row is the only place the panel shows 109 and 435,988, and it appears only from this step on. The withheld error is deliberate: no accuracy figure is shown on generated sales. 1,213,168 is a practice number, never quote it as a plan.

## After the close

- **The Reorder page is unchanged**, on purpose: it still shows March 2026 with 109 pending and 435,988 pieces, because the pages do not read the practice copy.
- **A reload moves the panel on.** It then reads "Monthly batch for 2026-04" with empty steps, and the plan table and the 709 label are gone from the screen. Nothing is lost.
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

**3. A step says "The last step stopped (exit N)", or you need to start again.**
Open the log under the panel and read its last lines: the reason is there. Clicking Run again skips the finished steps. To go back to the start, including after a close, repeat section 1 with `--reset` and then sections 2 and 3. It takes about 45 s, and it can only touch the throwaway server. If you hit this in front of the panel and do not have 5 minutes, say what stopped and move on: do not improvise a command.

## When you finish

Press Ctrl+C in Terminal 1, or use the command in item 2, then:

```powershell
.venv\Scripts\python.exe -m scripts.local_pg stop
```

Nothing above writes to live. `scripts.local_app` refuses any database but `127.0.0.1:55432`, and the batch routes do not exist on the deployed service.
