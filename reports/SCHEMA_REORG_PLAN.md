# Schema reorganisation — plan and critique (2026-10-08)

**Status: PLAN ONLY.** No DDL, no migration file, no code edit, no schema created. Nothing here is decided.
The draft decision record (DEC-39) is the appendix; it is not in `ARCHITECTURE.md` yet.

Terms: RLS = row-level security. ACL = a table's grant list. "Compat view" = a view in `public` with a moved
table's old name, so old code keeps working. "Scratch" = a throwaway `ssm_*` schema used for rehearsals.
Pooler = Supabase's connection pooler on port 6543, which shares server sessions between clients.

---

## 0. Inputs, and two corrections to the brief

| Input | What was used |
|---|---|
| Schema audit 2026-10-08 | **The report is not in `reports/`.** Searched `reports/`, `reports/archive/`, `reports/diagnostics/`, every worktree (only one existed) and every file modified since 2026-10-07 under the user folder. Its raw inventory exists: `inv.py` + `inv.json` in session `03769d17…`'s scratchpad (2026-10-08 02:09). Used that; not redone. |
| Live read | One read-only transaction this session (`BEGIN; SET TRANSACTION READ ONLY; …; ROLLBACK`, port 6543, role `postgres`): role settings, schema privileges, default ACLs, function settings, owned sequences, audit-log actions, fill tags. |
| Code | `kelvin-etl` at 84a4c10. |

**Correction 1 — "one schema = one full copy of the stack" stopped being true on 2026-10-04 (migration 0041).**

| Evidence | Where |
|---|---|
| 0041 creates objects by fixed name: `CREATE SCHEMA IF NOT EXISTS mart`, then `CREATE TABLE mart.sales_mart` with no `IF NOT EXISTS` | `0041_data_marts.sql:48`, `:76` |
| The runner replays every migration into a new scratch schema with `search_path = <scratch>, public`, and has no notion of `mart` (0 hits) | `scripts/run_canonical_load.py:1549`, `:1572` |
| So a fresh `--schema ssm_x --schema-only` (and so `--all-slices` on a new schema) should fail at 0041: "relation sales_mart already exists". One transaction per file, so it rolls back cleanly. **UNVERIFIED by execution** (running it writes); by reading the two lines above. | — |
| Since then each mart migration got its own rehearsal script that swaps the schema name and reads live `public`; 0047 has none | `scripts/rehearse_marts.py:9-14`, `scripts/rehearse_planning_mart.py:12-14, 63` |
| ABC and segmentation already rehearse as "write to scratch, read live public" | `analytics/classification/orchestrate_abc.py:378-381`, `analytics/segmentation/orchestrate_segment.py:295-299` |
| Marts only ever summarise `public` | `analytics/marts.py:20-21` |

The rehearsal unit is already split by stage. The reorganisation should write that down, not rebuild the single-copy model.

**Correction 2 — `mart` has 6 functions, not 5**: `capture_forecast_result`, `data_kind`, `month_add`, `refresh`,
`refresh_planning`, `source_tag` (plus the trigger function `public.inventory_fact_count_month`). The other audit
figures match the inventory: `public` 31 tables / 9 views, `mart` 9 tables / 8 views, ledger 48 rows all
`target_schema = 'public'`, every table RLS on with 0 policies, 0 table grants to `anon`/`authenticated`.

---

## 1. Critique of the cut

### 1.1 Verdict per table (31 tables)

| Table | Proposed | Verdict | Why (evidence) |
|---|---|---|---|
| sales_fact, purchase_fact, salesreturn_fact, sellout_fact, inventory_fact, unilever_sku_demand_fact | public | Right | The loader's targets (`run_canonical_load.py:1616-1619`). They also hold estimate rows (§1.2.2). |
| derived_receipt_fact | public | **Right place, wrong reason** | Not a source fact: receipts = closing − opening + sold, computed by the fill step (`0038_data_fills.sql:8-10, 60-86`). Live: 28,245 rows, all `is_demo = true`, `fill_source = 'derived_stock_balance'`, 2 run ids. It belongs in `public` because the **loader deletes its rows inside the slice transaction** (`scripts/load_slices.py:122, 634-639`): it is part of the load unit. |
| customer_dimension, product_dimension, date_dimension, salesman_dimension, supplier_dimension | public | Right | `product_dimension` is also written by the app (SKU master, `backend/deps.py:316-317`; audit action `Edit SKU`). |
| schema_migrations | public | Right | §1.2.4. |
| abc_classification, sku_segment, sku_traits, forecast_result | analytics | Right | Written only by model stages. |
| review_flag | analytics | Right | Computed only; no human column (`0042:84-99`). |
| lp_run | analytics | Right | LP run record. |
| lp_recommendation | analytics | **Right schema, fails the stated test** | Carries the admin's Accept/Dismiss: `status`, `decided_at`, `decided_by` (`analytics/db/schema.sql:613, 621-624`). Re-running the LP does not regenerate a decision. Keep it here; fix the test (§1.3); don't split the table. |
| sku_demand_fill | analytics | **Wrong → public** | Twin of `derived_receipt_fact`: same migration (`0038:88-104`), same writer (`scripts/fill_missing.py:502-507`), same nature (live 3,130 rows, all `is_demo`, `synthetic_category_split`), tracked as a load-coverage table (`load_slices.py:118, 123`). In `analytics` it would sit beside the tables the next model stage reads — the wrong side of Hard Rule 2 — and the fill step would write two schemas in one transaction. |
| etl_quarantine, etl_coverage, etl_load_event, etl_cutover_ledger | etl | **Wrong → stay in public** | Written in the **same transaction** as the facts: delete/insert facts → quarantine → ledger check → `etl_coverage` → `etl_load_event` → `audit_log` (`run_canonical_load.py:31-37`). The loader isolates a scratch run with `SET LOCAL search_path TO <schema>` — one schema, no public fallback, on purpose (`load_slices.py:600`; `run_canonical_load.py:81-84`). A separate `etl` schema breaks that model for no reader benefit. `etl_cutover_ledger` (30 rows) is the one-off cutover record written by the `apply_*` scripts. |
| users, user_session, auth_token, user_mfa, user_permission_override | app | Right | Written only by the backend; every foreign key points at `users`; hold credentials (`user_mfa.secret_encrypted`, `recovery_hashes`, `0035_user_two_factor.sql:33-38`). |
| audit_log | app | **Right schema, but "standalone" is false** | §1.2.3. |

After corrections: **public 18, analytics 7, app 6**, mart unchanged.

### 1.2 The specific questions

**1.2.1 derived_receipt_fact** — a derived output that stays in `public` because of who deletes it (the loader). Rename not needed.

**1.2.2 sku_demand_fill** — with the facts in `public`. Not because it is a source: because the line between real
and estimated already runs **through rows, not tables**. Live 2026-10-08:

| Table | Real rows | Estimate rows by `fill_source` |
|---|---:|---|
| inventory_fact | 32,823 | synthetic_v2 24,144 · synthetic_v2_gap 3,906 · synthetic_branch_adjacent 120 |
| salesreturn_fact | 1,604 | synthetic_v2 2,222 · synthetic_v2_gap 1,667 · synthetic_rate_transfer 68 |

What enforces Hard Rule 2 is the `_Real` views (`is_demo = false`), which every model reads. A schema boundary
can't carry that line; moving one estimate table pretends it does.

**1.2.3 audit_log — both kinds of event.**

| Writer / reader | What | Where |
|---|---|---|
| Backend (writer) | 75 of 77 live rows: Login 57, user admin, Edit SKU 1, Reorder Recommendation Accepted 1, two-step, password | `backend/audit.py:25` |
| Loader (writer) | `data_load` (0 live rows today) | `scripts/load_slices.py:853-863` |
| Fill step (writer) | `data_fill` (2 live rows) | `scripts/fill_missing.py:608` |
| `mart.refresh_status` (reader) | latest `Edit SKU` → `planning_stale` | `0047_planning_stale_tier_basis.sql:15-45` |
| Backend cache key (reader) | latest `Add SKU`/`Edit SKU` | `backend/deps.py:224-228` |

Decision: `app` — its purpose is the admin's Audit Log page and it holds sign-in history (personal data).
Consequences: the dependency rule must allow pipeline → `audit_log` writes and mart → `audit_log` reads; and a
scratch loader/fill run must never write the live journal (§3c shows compat views make exactly that happen).
Data events are already recorded in structured form in `etl_load_event`, so the pipeline's audit write could later
become optional; not needed for this plan.

**1.2.4 schema_migrations — stays in the schema it describes.** The runner reads `"<schema>".schema_migrations` and
writes the ledger row in the same transaction as the migration (`run_canonical_load.py:1481-1493, 1569-1594`); a
scratch's ledger dies with `DROP SCHEMA`. A separate `ops` ledger would need a `(target_schema, filename)` key
(today `ON CONFLICT (filename)`, `:1590`), would make every scratch rehearsal write a live table (standing rule 7),
and would make rollback two steps (`DROP SCHEMA` + `DELETE`) where a missed `DELETE` leaves a phantom "applied"
row. With several schemas the ledger describes the stack; `public` is the stack's anchor.

**1.2.5 Five schemas, or fewer?** A schema earns its keep when it separates *writers* or *privileges*.

| Pair | Different writer? | Different privileges? | Reason to split |
|---|---|---|---|
| etl vs public | No — same transaction | No | None |
| analytics vs public | Yes (model stages) | No | Clarity only |
| app vs everything | Yes (backend only) | **Yes — credentials** | Hard reason |

| Option | Schemas | For | Against |
|---|---|---|---|
| A (proposal) | public, analytics, etl, app, mart | Every stage named | `etl` split breaks scratch isolation; 4 schemas in one load transaction; `sku_demand_fill` on the wrong side |
| **B (recommended target)** | public (load unit), analytics, app, mart | Every load-transaction table in one schema, so `public` stays the single cloned rehearsal unit; schemas match writers | `public` mixes source facts, estimates and bookkeeping — rows already mix |
| **C (recommended first step)** | public, app, mart | 6 tables, 0.4 MB; the only split with a security reason; foreign keys closed; no pipeline table moves | Layering only partly physical |
| D (status quo + documentation) | public, mart | No risk | Credentials stay in the API-exposed schema; the clone deny-list keeps drifting (§4) |

### 1.3 The two stated rules are false as written

**Membership test "regenerable from public by rerunning the pipeline"** fails three ways: `lp_recommendation`
holds human decisions; `public`'s facts hold regenerable fill rows (§1.2.2); `mart.forecast_run` /
`forecast_run_value` are never rebuilt (`0041:20-23`). Replace with a **writer test: a table belongs to the schema
of the stage that writes it**, stated per schema in DEC-39.

**Dependency rule "etl → public → analytics → mart, one direction; app standalone":**

| Edge that exists today | Evidence | Fits? |
|---|---|---|
| mart reads `etl_load_event` | `0047:15-45` | Skips a layer — fine as a one-way graph, not as a chain |
| mart reads `audit_log` | `0047:15-45` | mart → app: app is not standalone |
| Loader and fill step write `audit_log` | `load_slices.py:862`, `fill_missing.py:608` | pipeline → app |
| Backend writes `product_dimension` | `backend/deps.py:316-317` | app → public |
| Backend writes `lp_recommendation` decisions | `schema.sql:613` | app → analytics |
| Backend reads mart, `lp_recommendation`, `audit_log` on every read request | `backend/deps.py:224-228` | app reads all |
| Mart refresh reads public facts and analytics outputs | live function bodies (abc_classification, forecast_result, lp_run, lp_recommendation, review_flag) | Yes |
| Loader deletes `derived_receipt_fact` | `load_slices.py:634-639` | Yes, if it stays in public |

Rewrite: **pipeline data flows public → analytics → mart and never backwards; the app reads every schema through
the API and writes only `app.*`, product-master edits and the decision columns of `lp_recommendation`; pipeline
stages write `app.audit_log` only.**

---

## 2. The rehearsal problem

How each stage is rehearsed today (by reading):

| Stage | Today | Evidence |
|---|---|---|
| Migrations, public part | Replay or apply-pending into scratch, `search_path = <scratch>, public` | `run_canonical_load.py:1530-1595` |
| Migrations, mart part | Swap `mart` for a scratch name, read live public | `rehearse_marts.py:9-14`, `rehearse_planning_mart.py:63` |
| Loader | Scratch built by the runner; `SET LOCAL search_path TO <scratch>` | `load_slices.py:600` |
| Fill step | Clone of every public base table minus a name deny-list; public's views re-created in scratch | `scripts/rehearse_fills.py:24, 36-61` |
| ABC, segmentation | Write scratch, read live public | `orchestrate_abc.py:378-381` |
| Forecast | Scratch schema ahead of public, direct port 5432 only | `scripts/run_baseline_forecast.py:100-121` |
| Marts | Public only | `analytics/marts.py:20-21` |

### Options

| | R1 Prefixed schema set | **R2 Public is the only clone; derived stages rebuilt** | R3 Ledger pinned in `ops` | R4 Rehearse inside a rolled-back transaction on live |
|---|---|---|---|---|
| What a rehearsal is | `ssm_x`, `ssm_x__analytics`, `ssm_x__app`, `ssm_x__mart` cloned together | Clone `public` → `ssm_x` (load + fill run there); ABC / forecast / LP / mart write a scratch target while reading live public; app never copied | Any of the others, ledger rows kept centrally | `BEGIN; SET LOCAL lock_timeout …; apply; verify; ROLLBACK` |
| Change in `run_canonical_load.py` | `--schema` becomes a map `{public: ssm_x, analytics: ssm_x__analytics, …}`; migrations written with schema tokens and substituted; loader path = the set; every writer CLI takes the map | **None on the load path** (layout B keeps every load-transaction table in public). Add: refuse a fresh build with a clear message (it already fails at 0041); add the R4 mode for migrations that touch analytics/app/mart | Ledger read/write go to `ops.schema_migrations` keyed by target | New `--rehearse` flag |
| Rollback | `DROP SCHEMA ssm_x, ssm_x__analytics, ssm_x__app, ssm_x__mart CASCADE` (one statement) | `DROP SCHEMA ssm_x CASCADE` (unchanged) | `DROP SCHEMA` + `DELETE FROM ops.schema_migrations WHERE target = …` | Automatic |
| How it fails | Any qualified name outside the map escapes to live: 0041's `mart.` names, the 3 functions pinned to `search_path = mart, public`, `backend/permissions.py:109`'s `public.`. Regex substitution also rewrites comments and string literals (`'mart.refresh'`). Duplicate names across 4 path entries shadow silently. Cost ≈ option 3b. | No isolated end-to-end run (load → ABC → forecast → LP → mart): downstream stages read live public. A migration touching both a public and an analytics table needs two rehearsals. | Every scratch writes a live table; a missed `DELETE` leaves a phantom "applied" row. Answers "where is the ledger", not "where are the tables". | Holds exclusive locks on live tables while open. A dropped client leaves the transaction open up to the `postgres` role's `idle_in_transaction_session_timeout = 600s` (read 2026-10-08), with every dashboard query on those tables queued behind it. Can't rehearse multi-minute loads. One flag separates rehearse from apply. |

**Recommendation: R2 for the stack, R4 (with local `lock_timeout` and `statement_timeout`) for the reorganisation
migrations themselves** — both are catalog-only and take milliseconds.

R2 also needs `scripts/rehearse_fills.py` changed: clone base tables only, skip any view whose body names a schema
other than `public`, read the "outputs unchanged" check (`:116-120`) from `analytics`, drop the deny-list (`:24`).

**Strongest objection to R2:** it gives up any future isolated end-to-end rehearsal across stages. Answer: that
capability does not exist today — ABC, segmentation and marts already read live public — so nothing is lost. If it
is ever needed, it is R1, which is the full qualification project (3b).

---

## 3. How code finds the tables

`ALTER TABLE … SET SCHEMA` keeps each table's object ID, so foreign keys, views (`mart.refresh_status`), triggers,
identity sequences, RLS and grants follow. What breaks is anything that names a table as text.

**Counts** — text search over `.py`/`.sql` at 84a4c10, excluding tests, migrations, `schema.sql`, `frontend/`,
`local/`, `backups/`, `reports/`. "Reference" = the name after `FROM/JOIN/INTO/UPDATE/TABLE/EXISTS/ON/to_regclass(`.
Regex counts, not a parse.

| Group (as proposed) | Files | References | Test files |
|---|---:|---:|---:|
| analytics (8 tables) | 48 | 124 | 15 |
| etl (4) | 5 | 14 | 2 |
| app (6) | 15 | 47 | 7 |
| **All moved** | **60** (backend 23, scripts 27, analytics package 4, scratch/tools 6) | **185** | — |

Wider whole-word count (comments included): `product_dimension` appears in 44 scripts (matches the brief), 131 files in all.

**Text references that are not plain queries:**

| Item | Where | Breaks under | Effect |
|---|---|---|---|
| 3 functions pinned to `search_path = mart, public`, reading analytics tables unqualified | `mart.refresh`, `mart.refresh_planning`, `mart.capture_forecast_result` (`0041:328`, `0043:38`, `0046:125`; live `proconfig`) | a, b (not c) | Fail at the next refresh. `analytics/marts.py` reports instead of raising (DEC-36), so marts go stale quietly. |
| `to_regclass('public.user_permission_override')` | `backend/permissions.py:109` | a, b | **Fails open:** probe false → overrides `{}` (`:185-186`) → a revoked permission comes back. A server that already cached "present" instead returns 500 on every signed-in request (`deps.py:216-218`) until restarted. 0 override rows live today, so nobody is affected now. |
| `to_regclass('lp_run')` | `backend/lp_cycle.py:87`, `scripts/run_lp.py:196` | a (if off the path), b | Silent fallback to the pre-`lp_run` cycle logic. |
| `to_regclass('review_flag')` | `backend/routers/recommendations.py:328` | a, b | Review flags silently disappear. |
| `to_regclass('etl_load_event')` | `scripts/load_slices.py:872` | proposal only | "Event not recorded", no audit row. |
| Writer CLIs where `--schema public` means "live", via `MetaData(schema=…)` | `orchestrate_abc.py:386-387`, `orchestrate_segment.py:298-299`, `fill_missing.py:674` | b | Meaning of "live" changes per table. |
| ORM classes | `analytics/db/models.py:336, 374, 400` | b | Need a schema each. |
| Forecaster refuses any non-default schema on the path over port 6543 | `run_baseline_forecast.py:97-121` | a | Deployed forecaster stops. |

### 3a — connection-level `search_path` (public, analytics, etl, app)

Three ways to set it, and what each costs here:

| Mechanism | Verdict |
|---|---|
| Session `SET search_path` | Forbidden (Hard Rule 7: leaks through the pooler). |
| Startup option `options=-c search_path=…` | Whether the pooler's transaction mode honours it per client is **UNVERIFIED**; if not, it is silently ignored. |
| `ALTER ROLE postgres SET search_path` | The only one that works through the pooler — it is how the path is set today (`"\$user", public, extensions`, `pg_db_role_setting`). |

Costs of the role-level path:
- **Scope:** every `postgres` session — backend, every script, the runner, the Studio SQL editor.
- **Staggered take-up:** only new server sessions read it; pooled ones keep the old path until recycled, so for a
  while some transactions see it and some don't. (Unknown schemas on a path are ignored, so it can be set before a move.)
- **Forecaster stops** (`run_baseline_forecast.py:97-121`) until edited.
- **Shadowing:** first match wins; a same-named table later on the path is invisible; an experiment copy earlier on the path silently wins.
- **Doesn't fix:** the 3 pinned functions (their own setting overrides it) or any `public.<table>` literal, including the permission probe.
- **Scratch:** the loader's `SET LOCAL search_path TO <scratch>` still wins (good). `pg_dump`-style backups are unaffected (`backup_everything.py:652-654` empties the path).
- **Clarity:** `FROM forecast_result` no longer tells a reader which layer it hits; the dependency rule can't be checked from the code.

Not "near-zero change" in this codebase. **Reject.**

### 3b — qualify every reference

Scope: 60 files / 185 references for the proposal's moves (app alone: 15 / 47), 24 test files, 3 ORM classes, the
writer CLIs' meaning of `--schema`, the pinned functions. The hard part is not the edits: a hard-coded
`analytics.` escapes every scratch run (the 0041 lesson). Done properly it needs a schema map passed into every
stage; done naively it makes rehearsals write live. Do it per module, app first, behind compat views.

### 3c — compatibility views in public

**Covers every runtime statement found:** 0 `TRUNCATE` on any moved table in non-test code (the only hit is a grant
line in `scripts/sql/2026-09-28_lock_down_data_api_undo.sql:11-12`); 0 `ON CONFLICT ON CONSTRAINT`; 0 `COPY` into a
moved table (the 7 `COPY` sites target temporary `bk_*` tables or copy out); 0 runtime `ALTER`/`LOCK` on moved
tables. Probes, pinned functions, ORM, writer CLIs and the forecaster keep working unchanged.

**TRUNCATE:** no loader path uses it — the loader deletes by slice (`run_canonical_load.py:31-34`). The risk is future code only.

**What views cost or break:**

| Problem | Detail | Fix |
|---|---|---|
| Views run as their owner by default | Owner `postgres` bypasses RLS; a view granted to an API role would expose the table | `security_invoker = true` (Postgres 15+; live is 17.6); no grants. `postgres`'s default ACL in public gives `service_role` TRUNCATE/REFERENCES/TRIGGER/MAINTAIN on new relations — no read or write, revoke for tidiness. |
| **Rehearsal leak (new, serious)** | `rehearse_fills.py:36-61` deparses public's views and re-creates them in scratch. A compat view's body names `app.audit_log` / `analytics.x` with its schema, so the scratch copy is a **writable view onto the live table**: fill rehearsals write live audit rows; under the proposal (`sku_demand_fill` → analytics) they would delete and insert live estimate rows; the "outputs unchanged" check would compare live with itself and always pass. | Change `rehearse_fills.py` before the first compat view exists (§2). |
| Column drift | A view's column list is fixed at creation; a later `ADD COLUMN` is invisible through it | Re-create the view in the same migration as any column change. |
| Future migrations | Must alter the real table (`analytics.forecast_result`), which a public clone can't hold | R4 for those. |
| A bridge nobody removes | Permanent tax | Drop per group once qualified (§5 group 5). |

**ON CONFLICT through a view:** Postgres documents `INSERT … ON CONFLICT` on automatically updatable views as
supported; **UNVERIFIED on this code** — `orchestrate_segment`'s upsert must be proven in an R4 rehearsal first.

### Recommendation

**c then b, never a.** Sequence: fix `rehearse_fills.py` and the permission probe → migrate with compat views
(and re-pin the 3 mart functions in the analytics migration) → qualify module by module, app first (15 files) →
drop each group's views once a search finds 0 unqualified references outside migrations and
`python scripts/smoke_api.py` passes 17/17.

---

## 4. Supabase and security

Read 2026-10-08:

| Fact | Value |
|---|---|
| Backend / scripts connect as | `postgres` through the pooler (owner of every table) |
| `USAGE` on `public` | anon ✓, authenticated ✓, service_role ✓ |
| `USAGE` on `mart` | none of the three |
| Default ACLs for `postgres` | only in `public` and `storage`; none elsewhere |
| Table grants in `public` | anon/authenticated 0; service_role some privilege on all 40 relations |
| Data API exposed schemas | Not in the catalog (`authenticator` has no `pgrst.db_schemas`); it is the dashboard setting (Project Settings → Data API). Current value **UNVERIFIED**; Supabase's default is `public`, `graphql_public`. |

**What new schemas need:**

| Item | Need | Why |
|---|---|---|
| Grants to anon / authenticated / service_role | None. Explicit `REVOKE ALL ON SCHEMA` for the record | A schema created by `postgres` gives nothing to `PUBLIC` (unlike `public`); same as `mart` today |
| Exposed schemas setting | Do **not** add `analytics` or `app` | — |
| RLS | Nothing | RLS flag and policies are keyed by table object ID; `SET SCHEMA` keeps it, so "on, 0 policies" travels. Grants travel too. |
| Compat views | `security_invoker = true`; revoke from the three API roles | §3c |
| GraphQL | Nothing expected (it lists schemas a role can use) — **UNVERIFIED** | — |
| PostgREST schema cache | Reloads itself on DDL (event trigger `pgrst_ddl_watch` present) | — |

**Net: an improvement, with new traps.**

Improvements:
1. **Credential tables leave the only schema the API roles can use.** Today `users`, `auth_token`, `user_mfa` are
   protected by "no grants" + "RLS with no policies". One `GRANT … ON ALL TABLES IN SCHEMA public` — the repo ships
   one, `scripts/sql/2026-09-28_lock_down_data_api_undo.sql:11-12` — plus one permissive policy would expose
   password hashes and two-step secrets. After the move that grant misses them.
2. **Clone tools stop copying credentials by construction.** Today the deny-list has drifted:
   `rehearse_fills.py:24` omits `user_mfa` (encrypted secret + recovery-code hashes; 1 live row), so the next
   `--build` copies it into scratch, contrary to the script's own docstring (`:8-9`).

New ways to get it wrong:
- Compat views left as owner-rights views (§3c).
- Compat views cloned into scratch writing live (§3c).
- Someone "fixing" an API error by exposing `app` or granting `USAGE` on it.
- Supabase's "RLS disabled" advisor targets the exposed schema (exact scope **UNVERIFIED**), so a future table in
  `app`/`analytics` created without RLS may go unflagged — keep "RLS on" as a migration checklist line.
- The permission probe fails open when the public view is finally dropped, unless changed first (§3).

---

## 5. Migration plan (prose only — nothing written)

**Numbering:** next free is **0048** (0045 and 0047 are now used: commits f08cba1, 84a4c10; ledger max 0047).
`CLAUDE.md`'s "0045 is still free / next is 0047" line is stale.

**Prerequisites (code, before any migration):**

| # | Change | Why |
|---|---|---|
| P1 | `rehearse_fills.py`: clone base tables only, skip views that name a non-public schema, read outputs from `analytics`, drop the deny-list | §3c rehearsal leak; §4 drift |
| P2 | `backend/permissions.py`: probe the real table and fail closed (503), never return `{}` | Independent fail-open defect; the move triggers it |
| P3 | Runner: refuse a fresh build with a clear message; add the R4 rehearse-in-transaction mode | §0, §2 |
| P4 | Backup (Hard Rule 8). The last full `backup_everything` run lost its connection after 26 min; a scoped backup of the moved tables (app 0.4 MB, analytics 18 MB) is the realistic option | — |

### Group 1 — app (0048)

- **Contents:** set a local lock timeout (5 s) and statement timeout; create schema `app`; revoke all on it from
  anon, authenticated, service_role; move `users`, `user_session`, `auth_token`, `user_mfa`,
  `user_permission_override`, `audit_log`; in `public`, create one view per moved table with the same name and
  columns, `security_invoker` on, revoked from the three API roles; comment each table and view with DEC-39. No
  function changes (no function body names an app table; `mart.refresh_status` follows `audit_log` by object ID).
- **Touches:** 6 tables (0.4 MB), 4 identity sequences (move with their tables), 4 foreign keys (all inside `app`),
  1 dependent view (`mart.refresh_status`). Exclusive lock on 6 tables for milliseconds — but every request's session
  check reads `users`/`user_session`, so a lock wait stalls every request: hence the lock timeout.
- **Verify** (read before and after):
  1. Object IDs of the 6 tables unchanged; namespace = `app`.
  2. Row counts unchanged (2026-10-08 inventory: audit_log 77, users 3, user_session 101, auth_token 2, user_mfa 1, user_permission_override 0 — re-read immediately before).
  3. RLS on, 0 policies, on all 6.
  4. `has_schema_privilege` for the three API roles on `app` = false; 0 grant rows for them on `app.*` and on the 6 views.
  5. Each view: `security_invoker=true` in its options; `is_insertable_into = YES`.
  6. `to_regclass('public.user_permission_override')` not null.
  7. `mart.refresh_status` returns 1 row and depends on `app.audit_log`.
  8. `smoke_api.py` 17/17 × 3 scopes; one sign-in; `GET /audit-log` still returns the rows.
- **Rollback:** a forward migration that drops the 6 views, moves the tables back and drops `app` with `RESTRICT`
  (refuses if anything else landed there). One transaction; the ledger keeps both rows.
- **If it half-applies:** it can't inside the database — file and ledger row are one transaction
  (`run_canonical_load.py:1569-1594`). Outside it: nothing, with views in place. Without views: running servers
  return 500 on every signed-in request; restarted ones fail open on permissions.

### Group 2 — analytics (0049, optional, after group 1 has settled)

- **Contents:** timeouts; create schema `analytics`; revoke from the API roles; move `abc_classification`,
  `sku_segment`, `sku_traits`, `forecast_result`, `review_flag`, `lp_run`, `lp_recommendation`; compat views as in
  group 1; re-pin `mart.refresh`, `mart.refresh_planning`, `mart.capture_forecast_result` to
  `search_path = mart, analytics, public` (a one-line setting change per function, no body copy) so they read the
  tables directly and survive the views' removal.
- **Touches:** 7 tables (18 MB), 6 identity sequences, foreign keys to `product_dimension` and `lp_run` (cross-schema
  foreign keys are fine), `mart.refresh_status` (by object ID), 3 function settings. The lock on
  `lp_recommendation`/`forecast_result` stalls `/recommendations`, `/forecast` and dashboard reads while waiting.
- **Verify:** object IDs + counts (abc_classification 74,347; sku_segment 1,926; sku_traits 321; forecast_result 189;
  review_flag 189; lp_run 2; lp_recommendation 277 — re-read before); RLS and grants as group 1; the 3 functions'
  settings show `analytics`; `python -m scripts.rehearse_marts --check-only --schema mart` and
  `python -m scripts.rehearse_planning_mart --check-only` 0 differences (read-only); `smoke_api.py` 17/17;
  `to_regclass('lp_run')`, `('review_flag')` not null; the upsert-through-view test from §3c passed in R4 first.
- **Rollback:** forward un-move, restoring the pins to `mart, public`.
- **If it half-applies:** not inside the database. Without views: the 3 functions fail at the next refresh, marts go
  stale quietly, `/recommendations` falls back to joins on `planning_stale`.

### Group 3 — etl: no migration (layout B keeps it in `public`).

### Group 4 — public → core rename: no migration (§6).

### Group 5 — drop compat views (one later migration per group)

Only after the group's code is qualified (0 unqualified references outside migrations), P2 is done, and
`smoke_api.py` passes. Deploy the qualified code first (it works while the views exist), then drop. Rollback:
re-create the views.

**Cannot be done inside one transaction (all groups):** code deploys (Render backend, scripts on the team's
machines); the Data API exposed-schemas setting (must stay unchanged — check only); a role-level `search_path`
(rejected); running processes' cached probe results (`backend/permissions.py:110-111`, `backend/lp_cycle.py:86`).

---

## 6. What I would not do

| Part of the proposal | Don't, because | Instead |
|---|---|---|
| `etl` schema | Same writer, same transaction, same privileges as the facts; breaks single-schema scratch isolation | Keep in `public`; table comments name them the loader's bookkeeping |
| `sku_demand_fill` → analytics | Generated rows beside model inputs; fill step spans schemas; rehearsal leak | Keep with `derived_receipt_fact` in `public` |
| `schema_migrations` → ops | Scratch rehearsals write live; two-step rollback | Keep in `public` as the stack's ledger |
| `public` → `core` rename | Breaks Supabase defaults (the `postgres` role's path, the Data API default, Studio) and every reference to the 18 tables that stay (`product_dimension` alone: 131 files); gain is cosmetic | Never |
| Role-level `search_path` | Forecaster refuses to start; staggered take-up through the pooler; hides layers | Compat views → qualification |
| Order etl → analytics → app | Starts with the move that has no reason and the most transaction coupling | app → (optional) analytics |
| Qualifying all 185 references before the defense | Gain is clarity; risk lands in the last weeks | Qualify app (15 files); analytics behind views as time allows |
| Splitting `lp_recommendation` decisions into `app` | 1 accepted row; churn for purity | State the exception in the membership test |
| The analytics move at all, if time is short | Clarity-only reason | Do group 1; record layout B as the target in DEC-39 |

**Existing defects found along the way** (not caused by the proposal):

| # | Defect | Evidence |
|---|---|---|
| 1 | Fresh scratch build fails at 0041 (UNVERIFIED by execution) | `0041:76`, `run_canonical_load.py:1544-1595` |
| 2 | `rehearse_fills.py` would copy `user_mfa` secrets into scratch | `rehearse_fills.py:24` vs `0035:33-38` |
| 3 | Permission probe hard-codes `public.` and fails open | `backend/permissions.py:109, 185-186` |
| 4 | Mart functions pinned to `mart, public` — any future move of an analytics table breaks the refresh quietly | live `proconfig`; `0041:328`, `0043:38`, `0046:125` |

---

## Appendix — Draft DEC-39 (PROPOSED, not in ARCHITECTURE.md)

Paste-ready row for the decision table in `ARCHITECTURE.md`:

| DEC-39 | Database layout — **four schemas, each table in the schema of the pipeline stage that writes it: `public` = the load unit (source facts, the fill step's labelled estimates, dimensions, the loader's bookkeeping, the migration ledger); `analytics` = model outputs; `app` = the web application's accounts, sessions, secrets and audit log; `mart` = pre-summed read models (DEC-36)** | **PROPOSED (2026-10-08), pending Yuan; not applied** | **Membership (writer test):** `public` — written by the loader or the fill step, including `derived_receipt_fact`, `sku_demand_fill` and `etl_*`; real and estimated rows are told apart by `is_demo`/`fill_source` and the `_Real` views (Hard Rule 1), not by schema. `analytics` — written by a model stage from public's `_Real` views (ABC, segmentation, forecast, review flag, LP); regenerable by re-running that stage, except the user's decision columns on `lp_recommendation`. `app` — written only by the backend; never cloned into a scratch schema; never exposed through the Data API. `mart` — written only by `mart.refresh*`, `capture_forecast_result` and the backtest; rebuildable except the forecast history (`forecast_run`, `forecast_run_value`). **Dependency rule:** pipeline data flows public → analytics → mart, never backwards; the app reads every schema through the API and writes only `app.*`, product-master edits and recommendation decisions; pipeline stages write `app.audit_log` only. **Rehearsal:** `public` is the only schema cloned for a rehearsal (loader and fill step run there with the scratch schema alone on the path); analytics and mart stages are rehearsed by writing a scratch target while reading live `public`; `app` is never copied; a fresh replay of all migrations into an empty schema is not supported after 0041; catalog-only migrations are rehearsed inside a rolled-back transaction with a lock timeout. **Name resolution:** compatibility views in `public` (`security_invoker`, no grants) during the move, then schema-qualified names; no session-, connection- or role-level `search_path` change. **Security:** the new schemas grant nothing to `anon`, `authenticated` or `service_role` and are not added to the Data API's exposed schemas; RLS stays on every table. **Order:** `app` first; `analytics` optional; `etl` schema and a `public` rename rejected. Evidence: `reports/SCHEMA_REORG_PLAN.md`. |

**Methodology text** (for the manuscript — use only for what has been applied; if only `app` is moved, drop the
`analytics` sentence and say outputs remain in `public` alongside the source data):

> The DSD database (PostgreSQL 17, hosted on Supabase) is divided into four schemas according to the pipeline stage
> that writes each table. The `public` schema is the load unit: the six source fact tables, the five dimension
> tables, the two tables of labelled estimates produced by the fill step, the loader's bookkeeping (quarantined rows,
> coverage and load events) and the migration ledger. Every table written by a single data-load transaction lives
> here, so a load can be rehearsed on one copy of this schema before it reaches the live database. The `analytics`
> schema holds the outputs of the model stages — ABC classification, segmentation, forecasts, review flags, and
> linear-programming runs and recommendations — each computed from the real-data views of `public`. The `app` schema
> holds the web application's own tables: user accounts, sessions, sign-in tokens, two-step verification secrets,
> permission overrides and the audit log. The `mart` schema holds pre-summed tables that are rebuilt after every
> load, fill, forecast and optimisation run. Data flows in one direction, from `public` to `analytics` to `mart`; the
> application reads all schemas through its API and writes only its own tables, product-master edits and the user's
> decision on each recommendation. Real and estimated rows are distinguished by a provenance flag inside each table
> and by the real-data views that every model reads, so the rule that estimated data never feeds a KPI, forecast,
> classification or the optimisation is enforced by those views rather than by schema placement. Credential tables
> sit outside the schema exposed by Supabase's Data API, and none of the added schemas grants access to the API's
> public roles.
