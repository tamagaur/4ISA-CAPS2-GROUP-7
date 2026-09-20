# Running this project

This is the same "Getting Started" + "Troubleshooting" content from
`README.md`, pulled out on its own for quick reference. If the two ever
drift apart, `README.md` is the source of truth — update this file to
match, not the other way around.

## Prerequisites

- Python 3.11+ (developed and tested on 3.13)
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

Expected as of 2026-09-20: **303 passed / 13 failed / 1 skipped**. The 13
failures are pre-existing (`Users` vs `users` table casing in
`tests/backend/test_auth.py` and `test_users.py`) and are not your fault —
see Troubleshooting. More than 13 means something is wrong.

If you see tests skipping that you expected to run, it almost always means
step 3 or step 4 wasn't done yet — several tests are gated on `data/raw/`
or `staging/` actually existing. (This step previously said "109 passed",
which pre-dated the backend and analytics suites.)

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

**13 backend tests fail and you didn't touch them.** That is the baseline —
`tests/backend/test_auth.py` and `test_users.py` fail on `Users` vs `users`
table casing, and pre-date the 2026-09-20 push. Expect exactly
**303 passed / 13 failed / 1 skipped**. More than 13 means something is wrong.

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
