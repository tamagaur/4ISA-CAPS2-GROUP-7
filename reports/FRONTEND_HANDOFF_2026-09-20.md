# Frontend handoff — after the 2026-09-20 push

**For Audrey, Maika, Kelvin, or whoever pulls next.** If the dashboard breaks
after you pull, start here. Written 2026-09-20.

## First: run this

```bash
python scripts/smoke_api.py
```

Read-only, about ten seconds, writes nothing. It drives every route the frontend
calls against the live database and tells you which side the problem is on:

- **All PASS but the dashboard looks wrong** → the bug is in the frontend. Jump to
  "If it's the frontend" below.
- **Any FAIL** → the backend or the database. The route name and status code point
  at the router.
- **IMPORT FAILED** → your dependencies are stale. `pip install -r requirements.txt`.

## What was already verified on 2026-09-20

Don't re-do this work; it was checked before the push.

| Check | Result |
|---|---|
| All 17 frontend-facing routes, ×3 principal scopes | 200 |
| `npm run build` | exit 0, 731ms, 18 chunks, no warnings |
| `frontend/` source changes in this push | **zero files** |
| Backend importing anything from `analytics/` | none — offline scripts cannot affect the API |
| Test suite | 303 passed / 13 failed / 1 skipped (the 13 are pre-existing, see below) |

## The three most likely things to bite you

### 1. Stale dependencies → the whole backend suite fails to collect

`requirements.txt` now pins `starlette==0.41.3`. FastAPI 0.115.5 needs
`starlette<0.42`, and an unrelated global Streamlit install pulls 1.6.0, which
dropped `Router(on_startup=...)`. Symptom is collection errors across all of
`tests/backend/`, not a single test failure.

```bash
pip install -r requirements.txt
```

### 2. Two scripts now require `--schema`

`orchestrate_abc.py` and `orchestrate_segment.py` used to write `public` when you
gave them no schema. They now refuse to run without one:

```
error: the following arguments are required: --schema
```

That is intentional — a rehearsal used to take an extra flag while a live write
took none. Pass `--schema public` if you really mean production, or a scratch
schema name to rehearse. Nothing in the app calls these, so this only affects you
if you run them by hand.

### 3. The 13 failing tests are NOT from this push

`tests/backend/test_auth.py` and `test_users.py` fail on `Users` vs `users` table
casing. They pre-date this work and were deliberately left alone. Baseline is
**303 passed / 13 failed / 1 skipped**. If you see exactly 13 failures, nothing
is wrong. If you see more, something is.

## If it's the frontend

### Del Monte returns empty/null on purpose

Del Monte has no `abc_classification` rows and is not in the segmentation cohort.
These are correct responses, not bugs:

| Route | Returns |
|---|---|
| `/abc?principal=delmonte` | `count: 0`, `classification_period: null`, `tier_summary: []` |
| `/segment/summary?principal=delmonte` | `cohort_period: null`, plus a `blocked_reason` string |
| `/sku?principal=delmonte` | 15,308 items, `tier: null` on every one |

The guards that handle these already exist — `{sku.cat \|\| '—'}` with a `default:`
badge class in `SKUManagement.jsx:300-305,401`, the `hasData` →
`blocked_reason` branch in `Charts.jsx:1171`, and `formatMonth(null) → '—'` in
`utils/formatDate.js:30-34`. **If you add a new panel, copy that pattern.** Do not
render `null` tiers as "C" or a missing cohort as today's date — an invented value
is worse than a dash.

### Known rough edge: the Del Monte SKU payload is 4.0 MB

`/sku?principal=delmonte` returns 15,308 items but only **260** carry a real
`current_stock`; the rest are null on both stock and tier, because Del Monte's
product dimension is category-grain. Unilever's equivalent is 0.6 MB for 2,098
items — about 7× smaller for the same screen.

It works and the table paginates client-side, but it is slow on a poor
connection, which matters for the defense. The fix is server-side (filter or
paginate in `backend/routers/sku.py`), not a frontend change. **Not done** — it
predates this push and nobody has approved the endpoint change.

## Database note

The database is shared, so two migrations are **already live** for everyone,
independent of whether you have pulled:

- **0019** — `schema_migrations` ledger table
- **0020** — `sku_traits.abc_method`, plus its unique key widened to
  `(product_key, cohort_period, abc_method)`

Both are additive. The backend selects explicit columns from `sku_traits`
(`segment.py:95-97`, `:215-217`) and there is no `SELECT *` anywhere that touches
it, so neither can break a response. **0021 is not applied** — it only corrects a
column comment, so nothing depends on it.

## Who to ask

Yuan owns all pipeline and database decisions. Anything touching
`abc_classification`, `sku_segment`, `sku_traits`, or the migrations above goes
through him first — do not apply a migration to `public` on your own initiative.
