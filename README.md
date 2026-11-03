# SSM Decision Support Dashboard (DSD)

## What it does

The DSD produces a distributor's monthly order plan from its own sales and stock records. The distributor is San San Marketing (SSM), an FMCG wholesaler in Urdaneta, Pangasinan, which holds about three weeks of safety stock on every product regardless of how fast it sells. The system ranks products by revenue, forecasts next month's demand for the ones that matter, works out each product's own safety stock and target stock, and solves for how much to order. A web dashboard shows the result, and a person accepts or dismisses each line. It covers two principals, and they differ: Unilever has sales per product and gets the whole pipeline; Del Monte has sales per category only, so it is ranked and charted but gets no real order plan.

Before you run anything, read [What the data is](#what-the-data-is-and-is-not) below.

## The pipeline

| Stage | What happens | Where |
|---|---|---|
| 1. Extract and load | Parse the client's files, clean them, load them into Postgres | `analytics/etl/`, `scripts/run_canonical_load.py` |
| 2. Classify | ABC/Pareto ranking; the top class is what gets forecast | `analytics/classification/` |
| 3. Forecast | One method per product, chosen by how much history it has | `analytics/forecasting/router.py`, `scripts/run_baseline_forecast.py` |
| 4. Safety stock and target stock | Per product, from its own forecast and variability | `analytics/optimization/lp.py`, `scripts/run_lp.py` |
| 5. Optimise | Multi-objective linear program (PuLP); settings in `analytics/params.py` | `analytics/optimization/lp.py`, `scripts/run_lp.py` |
| 6. Present | Marts, then a FastAPI backend, then a React + Vite frontend | `analytics/marts.py`, `backend/`, `frontend/` |

`python -m scripts.run_month` chains the monthly steps, and it is a dry run unless told otherwise. Schema changes go only through the numbered files in `analytics/db/migrations/`.

## Running it locally

There are two ways, and they use different databases.

**The app, against the shared Supabase database.** You need its credentials from the team. This is the real database: read [`CLAUDE.md`](CLAUDE.md) before running anything that writes.

```bash
pip install -r requirements.txt            # Python version: .python-version
cd frontend && npm ci && cd ..
cp .env.example .env                       # each setting is explained in the file

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev -- --port 5173  # in a second terminal; open http://localhost:5173
```

`python scripts/smoke_api.py` is a quick read-only call of every route the frontend uses. If it passes and a page is broken, the fault is in the frontend.

The API refuses to start on a weak or malformed secret: a short `JWT_SECRET_KEY` in production, or a `MFA_ENCRYPTION_KEY` that is not a valid key. The rules are in `backend/startup_checks.py`, and the message names the variable.

**The practice month, on a throwaway local database.** This runs the real monthly batch from the browser and cannot touch the shared database. Follow [`docs/LOCAL_DEMO_RUNBOOK.md`](docs/LOCAL_DEMO_RUNBOOK.md). It needs PostgreSQL on your machine (`scripts/local_pg.py` looks in the default Windows folder, or set `PG_BIN`) and a full backup folder, which is git-ignored, so a fresh clone does not have one. Ask the repo owner for a copy, or make one with `scripts/backup_everything.py` if you have database access.

The client's source files are also git-ignored and are never committed. They go in `data/raw/`, and you need them only to re-extract or to run the tests that read them.

## The checks

`scripts/check.sh` is the one check command. Run it from Git Bash on Windows. `--fast` and `--full` need `SUPABASE_DB_URL` and `frontend/node_modules`, and only ever read the live database.

| Command | Covers | Takes |
|---|---|---|
| `--fast` | Database reachable, backend and frontend lint, pinned figures reproduce, the cross-endpoint invariants in `tests/invariants/` | under a minute; run it constantly |
| `--full` | All of `--fast`, the whole pytest suite and its pinned totals, the frontend production build | about 10 min |
| `--optin` | Only the database tests that are too destructive for anywhere else, on a disposable local database it creates and drops. Needs the local PostgreSQL and a backup folder | about 3 min |

**A red run** ends with a table naming each failed step; every step still runs, so the table shows all the failures at once. Read a red run by step:

- **Skipped counts as failed.** A check that could not run (variable unset, database unreachable, a test skipping itself) fails and says why. That means "not verified", which is not the same as "broken". Some networks block port 6543, for example.
- **The only allowed skips** are the opt-in tests listed in `scripts/known_opt_in_skips.txt`. `--full` reports them as NOT RUN, never as passed.
- **A pinned figure failing means a number moved.** Figures quoted in the manuscript are frozen in [`docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json`](docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json), and those printed from the code or the live system are in [`docs/CHAPTER4_CODE_FIGURES.json`](docs/CHAPTER4_CODE_FIGURES.json), each with the command that measures it. Pinning means the check fails if the value drifts. Find out why it moved. Re-pin (`python -m scripts.chapter_figures --write`) only on purpose, in the commit that changes the code.

One check sits outside `check.sh`: `python -m scripts.practice_artefacts` runs a practice month and fails on any file, row or route that does not say it came from one. It takes about 5 minutes on the local database. Run it after adding anything a practice run writes.

## Where things are written down

| File | What it is for |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | The rules: repo and branch conventions, database writes, hard rules on generated data, why data is missing, the team |
| [`STATE.md`](STATE.md) | Current state only: the plan, the next migration number, what is blocked and on whom. Any current number you need is here or in a file it names |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Stage contracts and the decision register (section 5, DEC-01 onward), including which team decisions no one outside the team has confirmed |
| [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) | Open defects and the written limitations, each with its owner and reason |
| [`docs/DATA_GOVERNANCE.md`](docs/DATA_GOVERNANCE.md) | Roles, data inventory, controls, retention, privacy, and what is still needed for handover to the client |
| [`docs/LOCAL_DEMO_RUNBOOK.md`](docs/LOCAL_DEMO_RUNBOOK.md) | Step-by-step practice month in the browser, with what you should see and what to do if it goes wrong |
| [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md) | Test items, pass/fail criteria, results by round, and integration coverage |
| [`docs/DEMO_DATA.md`](docs/DEMO_DATA.md) | The labelled demonstration data in schema `demo`: how each kind is generated and served |

Other Markdown files at the repo root (`RUNNING.md`, `BACKEND_GUIDE.md`, `ROADMAP.md` and others) and everything under `reports/` are dated records, not maintained guides. `RUNNING.md` in particular still names a retired branch. If one of them disagrees with the code or with the files above, trust the code and those files.

## What is deliberately not finished

Open defects and limitations are in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md), and whatever waits on someone outside the team is under "Blocked" in [`STATE.md`](STATE.md). Check both before you fix something that looks broken, because some of it is a recorded decision or an unanswered client question rather than unfinished work. Del Monte's empty per-product cards are empty on purpose: `CLAUDE.md`, "Why data is missing", explains why.

## What the data is, and is not

The system is built on one distributor's real records. Generated data also exists, always labelled. It sits in three places, and they are not the same thing:

| Where | What it is | What keeps it apart |
|---|---|---|
| The **practice copy**: local database `ssm_practice` on `127.0.0.1:55432` | Generated sales for one month, `is_demo = true`, so the real monthly batch has something to run on | It cannot reach live: the scripts refuse any other server, the forecast's permission comes from the connection itself, and the API answers 409 from this copy on everything but the batch panel and `/health` |
| Schema **`demo`** on the shared database | Labelled demonstration series and order plans | Served only when `DM_DEMO_ENABLED` is on (default off) and the request asks for it; it holds no accuracy metrics |
| **Base fact tables** on the shared database | Older backfill rows, `is_demo = true`, kept and not deleted | Model code reads the `_Real` views, which exclude them. Never read a base fact table for anything that feeds a figure |

No figure computed on generated data is presented as a result. A plan from the practice month is never a result, and the system withholds forecast error whenever generated rows are in what it would score. The practice month shows that the steps run; it does not show that a real new monthly file runs, because none has ever existed.

The conditions behind each of these are hard rule 2 in `CLAUDE.md`. A gap in a chart means different things for each principal, so read "Why data is missing" in the same file before you investigate one.
