# Creating the Supabase database

This walks through standing up the actual Supabase project this codebase
has been designed against but never yet run — `analytics/db/schema.sql`
has never been executed on a live database. This needs a human with
Supabase dashboard access; nothing here can be automated by a coding
assistant.

## What you'll end up with

14 tables (5 dimensions, 3 transaction-mart facts, 3 product-mart facts,
3 analytics-output tables) + 1 view, in one `public` schema — no
microservices/domain separation, no RLS-per-domain. This is one client
with 1-2 users and one linear pipeline, not a multi-tenant platform, so
that complexity doesn't apply here (see `ARCHITECTURE.md` if you want the
full reasoning).

## 1. Create the project

1. Go to [supabase.com](https://supabase.com), sign in or create an
   account.
2. Create a new organization if you don't have one, then **New Project**.
3. Pick a name (e.g. `ssm-dsd`), a database password (save it somewhere —
   you'll need it in the connection string, and Supabase won't show it
   again), and a region (closest to where the dashboard will actually be
   used).
4. Wait for provisioning — takes a minute or two. You'll land on the
   project dashboard when it's ready.

## 2. Get the connection string

1. In the project dashboard: **Project Settings → Database**.
2. Under **Connection string**, copy the **URI** format (starts with
   `postgresql://postgres:...`). Use the **Session pooler** or **direct
   connection** string, not the transaction pooler — this project uses
   plain SQLAlchemy/psycopg2, not a serverless connection pattern that
   needs pooling.
3. Replace the `[YOUR-PASSWORD]` placeholder in that string with the
   real database password from step 1.3.
4. Also grab the **anon public** key from **Project Settings → API** —
   this fills `SUPABASE_KEY`, even though nothing in the codebase
   currently calls it directly (confirmed via grep — all real DB access
   goes through the plain Postgres connection string, not Supabase's
   client SDK). Worth having set anyway since `.env.example` expects it
   and it costs nothing to fill in.

## 3. Set up your local `.env`

```bash
cp .env.example .env
```

Edit `.env` and fill in the two values from step 2:

```
SUPABASE_DB_URL=postgresql://postgres:your-real-password@...
SUPABASE_KEY=your-real-anon-key
```

`.env` is gitignored — this stays on your machine only.

## 4. Run `schema.sql`

Two ways to do this — pick whichever's easier:

**Option A — Supabase SQL Editor (no local Postgres client needed):**
1. In the dashboard: **SQL Editor → New query**.
2. Open `analytics/db/schema.sql` in this repo, copy its entire contents,
   paste into the editor.
3. Run it.

**Option B — `psql`, if you have it installed:**
```bash
psql "$SUPABASE_DB_URL" -f analytics/db/schema.sql
```

**What success looks like:** no errors, and either the SQL Editor's
results pane or `psql`'s output shows a series of `CREATE TABLE` /
`CREATE INDEX` confirmations ending with one `CREATE VIEW`. If you re-run
it, it should succeed silently the second time too — every statement
uses `IF NOT EXISTS` / `CREATE OR REPLACE`, so this is safe to re-run.

**Verify the table count** — in the SQL Editor or via `psql`:
```sql
SELECT count(*) FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
-- expect 14
SELECT count(*) FROM information_schema.views WHERE table_schema = 'public';
-- expect 1 (bo_monitoring_view)
```

## 5. Seed the date dimension

```bash
python -m analytics.db.seed_date_dim
```

This populates `date_dimension` with one row per calendar day, 2021-01-01
through 2026-12-31 (covers the full real data corpus plus SARIMA forecast
horizon). Takes a few seconds.

**What success looks like:**
```
Generated 2191 calendar days (2021-01-01 .. 2026-12-31).
Upserted 2191/2191 rows into date_dimension.
```

**Verify:**
```sql
SELECT count(*) FROM date_dimension;
-- expect 2191
SELECT min(date_key), max(date_key) FROM date_dimension;
-- expect 2021-01-01, 2026-12-31
```

Safe to re-run later with a different `--end` to extend the range
further — it upserts, never duplicates or destroys existing rows.

## 6. What's NOT done yet after this

Creating the database is a different milestone from actually loading real
data into it. As of 2026-08:
- `analytics/etl/transform/driver.py` doesn't exist yet — nothing
  currently runs Transform automatically over the full staged corpus.
  Individual pieces (`transform_fact()`, the granularity resolvers) are
  tested and verified against real data in isolation, but nothing wires
  them together yet.
- `load_to_supabase()` doesn't yet resolve dimension foreign keys
  (`product_key`, `customer_key`, etc.) automatically — that's tracked
  separately as a follow-up (DEC-09's resolution: load-time
  lookup-or-insert).
- Two known, permanent data gaps are already baked into the schema
  (see the comments in `schema.sql` directly above each): `Sales_Fact`
  is Del Monte-only (Unilever's real sales data has no invoice grain to
  put there), and `SalesReturn_Fact.bo_units` will always be NULL (no
  source column exists for Bad Order *quantity*, only peso value via
  `BO_Monitoring_View`'s value-based `bo_rate`).

So: once you finish steps 1-5, you have a real, empty (except
`date_dimension`) Supabase database matching the current schema design
exactly. Loading real fact rows into it is separate, later work.
