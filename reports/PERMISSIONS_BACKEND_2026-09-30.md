# Permissions: the backend half, for your review

- **From:** Audrey
- **To:** Kelvin
- **Date:** 2026-09-30
- **Branch:** `feat/permissions-backend` (from `UIFixes_Audrey` at `7760cca`). Not merged anywhere: `UIFixes_Audrey` deploys to Vercel and Render on push, so it waits for your review.
- **Database:** nothing written. Migration `0034_user_permissions.sql` is in the branch but not applied, for you to run with the runner after your 0032/0033 loader work. My side only ran read-only checks (section 3).

## 1. Your conditions

| You asked for | Where it is |
|---|---|
| Migration number 0034 or later | `analytics/db/migrations/0034_user_permissions.sql`. `analytics/db/schema.sql` is updated to match, per house convention. |
| No database writes from my side | Only `SELECT`s, inside `BEGIN READ ONLY`, rolled back (section 3). The tests use in-memory fakes. The one live render check used a read-only engine. |
| Checked against the database on every request | `require_permission()` in `backend/permissions.py` runs after `get_current_user`, which already re-reads the account and session each request (`backend/deps.py`). It then reads that user's overrides fresh, with no cache. Nothing about permissions is in the token, so an unticked box applies on the user's next request. |
| Any-of keys | Each endpoint lists every key that may open it; any one passes. For example, `GET /abc` takes `abc.view` OR `forecast.view`, because the SKU Forecast page calls it too. |
| LP fields removed on the server | `lp.view` covers LP figures on every page. Without it: `/dashboard` blanks its LP sections and sets `lp_hidden: true`, `/abc` sends `ON HAND` instead of the statuses that compare stock with the reorder point, and `/sku` sends `reorder_point: null` (section 5). |
| Page smoke test | `tests/backend/test_permissions.py`. For admin, manager and staff, first with nothing unticked and then with each one box unticked, it loads every endpoint of every page the user can see and checks there is no 401/403. Every endpoint used only by a hidden page must answer 403. It also runs a staff account with a single box ticked, once for each key. |
| Postman-style tests | Same file. Seven bad-token cases get 401 on six endpoints: no header, no `Bearer`, garbage, expired, tampered claims, signed with another key, and `alg: none`. Self-promotion is refused in every form I could find (section 4). |
| Unique index on `lower(email)`, after a read-only check for case duplicates | In 0034. The check found none (section 3). The API's duplicate checks now compare `lower(email)`, and `POST /auth/register` turns a unique-index race into a 409. |

## 2. Migration 0034

What it does. It is additive, safe to run twice, and wrapped in `BEGIN`/`COMMIT`, with unqualified names like 0031:

1. `user_permission_override (user_id, permission_key, granted, set_by, set_at)`:
   - primary key `(user_id, permission_key)`;
   - `user_id` references `users(user_id)` `ON DELETE CASCADE`;
   - `set_by` references `users(user_id)` `ON DELETE SET NULL`;
   - row-level security on, with no grants.

   A row exists only where a user differs from their role's preset. There is no CHECK on `permission_key`: the catalog lives in `backend/permissions.py`, and the PUT refuses unknown keys, so adding a permission needs no migration.
2. `users_role_check` is dropped and re-added as `role IN ('admin', 'manager', 'staff')`.
3. `CREATE UNIQUE INDEX users_email_lower_key ON users (lower(email))`.

To apply it, use your runner, after 0032/0033. The file has no `;` inside a string, and its rollback block is all comment lines, which `_strip_sql_file` drops.

To check it afterwards (read-only):

```sql
SELECT to_regclass('public.user_permission_override');                               -- not null
SELECT relrowsecurity FROM pg_class WHERE oid = 'public.user_permission_override'::regclass;  -- true
SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'users_role_check';     -- includes 'manager'
SELECT indexdef FROM pg_indexes WHERE indexname = 'users_email_lower_key';
```

Rollback: the commented block at the end of the file. It fails while any user is a manager. After a rollback, restart the backend, because it remembers "0034 is applied" until then.

## 3. Read-only checks on the live database (2026-09-30)

Every statement ran in a `READ ONLY` transaction (`SHOW transaction_read_only` = on), which was then rolled back. Only counts and DDL were printed, never an email or a hash.

| Check | Result |
|---|---|
| Users; distinct `email`; distinct `lower(email)`; distinct `lower(trim(email))` | 3; 3; 3; 3. There are no case duplicates, so the unique index can't fail on existing rows. |
| Unique IDs | `user_id bigint GENERATED ALWAYS AS IDENTITY`, primary key `users_pkey` |
| Passwords | 2 bcrypt (`$2b$`), 1 NULL (invite pending), 0 anything else |
| Roles | admin 1, staff 2 |
| Constraint names 0034 relies on | `users_role_check` = `CHECK (role = ANY (ARRAY['admin','staff']))`; `users_email_lower_key` is free |
| `user_permission_override` | Does not exist yet |
| Tables referencing `users(user_id)` | `auth_token` only |
| `schema_migrations` | Latest row: `0031_…` applied by `kyuan` on 2026-09-30. No rows numbered 0032 or higher. |

## 4. The API

### Endpoint → permission (any one listed key opens it)

| Endpoint | Keys |
|---|---|
| `GET /dashboard`, `GET /inventory/current`, `GET /inventory/movement` | `dashboard.view` |
| `GET /abc` | `abc.view`, `forecast.view` |
| `GET /fsn`, `GET /pareto` | `abc.view` |
| `GET /forecast/{sku_id}` | `forecast.view` |
| `GET /segment`, `GET /decomposition` | `forecast.view`, `lp.view` (the demand-pattern panel on SKU Forecast and in the Reorder modal) |
| `GET /category-trends` | `category_trends.view` |
| `GET /recommendations`, `GET /policy-comparison` | `lp.view` |
| `PATCH /recommendations/{key}` | `lp.decide` |
| `POST /sku`, `PATCH /sku/{key}` | `sku.edit` |
| `GET /audit-log`, `GET /audit-log/users` | `audit_log.view` |
| `/users` (all four routes), `POST /auth/register`, `/admin/...` (all three) | `users.manage` |
| `GET /sku`, `GET /data-mode`, `GET /auth/me`, heartbeat, logout | Sign-in only. `GET /sku` supplies product and brand names to the ABC, Reorder and SKU Forecast pages. |

`test_every_route_is_guarded` fails for any new route that neither declares its permission nor is added on purpose to the sign-in-only or public list. `deps.require_admin` is no longer used; I left it for you to delete or keep.

### New endpoints

- `GET /auth/me` → `{user_id, email, full_name, role, permissions: [sorted keys]}`.
- `GET /admin/permissions/catalog` → `{permissions: [{key, label, group, description}], roles: {admin: "all", manager: [...], staff: [...]}}`. These are the 11 keys and the presets from your Design table.
- `GET /admin/users/{id}/permissions` and `PUT` (body `{role, overrides}`, extra fields refused) → `{user_id, role, overrides, permissions}`:
  - only the overrides that differ from the preset are stored;
  - each save that changes something writes a "Change Access" audit entry, for example `staff → manager; overrides none → +audit_log.view, -sku.view`;
  - a role change signs that user out, the same as a role change from Edit User (`PATCH /users`). A change of boxes alone applies on their next request.

### Errors: `{"detail": sentence, "code": ...}` everywhere

| Status | `code` | When |
|---|---|---|
| 403 | `missing_permission` (+ `permission`: the first key the endpoint accepts) | Any guarded endpoint |
| 409 | `self_lockout` | Demoting yourself, or removing your own `users.manage` |
| 409 | `self_promotion` **(new)** | Any other change to your own access. Without it, someone given `users.manage` could make themselves an admin. |
| 409 | `last_admin` **(now also on `PATCH`/`DELETE /users`)** | Demoting or deleting the only admin. The admin rows are locked while counting, so two admins demoting each other at once can't both pass. |
| 422 | `unknown_permission` (+ `permission`) | An override names a key not in the catalog |
| 404 | `user_not_found` **(new)** | GET/PUT for a user ID that doesn't exist |
| 404 / 503 | `permissions_not_ready` **(new)** | Before 0034 (section 6) |

Self-promotion, as tested:
- **Staff:** `PUT` your own permissions, `PATCH /users/{you}` with `role: admin`, and inviting a new admin all get 403.
- **Given `users.manage`:** widening your own role or boxes gets 409 `self_promotion`; Edit User on your own role gets 400.
- **Tokens:** a token edited to say admin gets 401. A validly signed token that still says admin after a demotion gets the database's role, so staff access.

## 5. LP figures without `lp.view`

| Endpoint | What changes |
|---|---|
| `GET /dashboard` | These go to `null`: `reorder_preview`, `policy_comparison`, `lp`, `safety_stock_exposure`, `recommendations.{order_value, product_count}`, `kpis.safety_stock_rate` (with a reason) and `tier_stock[].pending_reorder_count`. `lp_hidden` becomes `true`; it is `false` otherwise. Sales, stock, allocation, ABC and forecast are untouched. |
| `GET /abc` | `stock_status` is `ON HAND` where it would have been `IN STOCK`, `LOW` or `NO ROP`, since above or below the reorder point reveals the LP's figure. `CRITICAL` and `NO DATA` stay. |
| `GET /sku` | `reorder_point: null`. Stock stays. |

The frontend already handles all of this. The two LP cards show "—" with "Needs the reorder-recommendation permission", the reorder and policy widgets aren't drawn, and ABC shows "Stock on hand". I checked this in a browser as a staff account with `lp.view` unticked, against the live data through a read-only backend: no errors.

## 6. Safe to deploy before 0034

This code can go live before the table exists without changing anyone's access. `permissions_ready()` looks the table up with `to_regclass`, which never errors. It keeps a "yes" until restart and re-checks a "no" after a minute. Until the table exists:

- **Enforcement:** the role presets, with no overrides. The staff preset is exactly what staff can open today; `test_the_staff_preset_opens_exactly_what_staff_could_open_before` checks this route by route. Admins keep everything.
- **`GET /auth/me`:** 404 `permissions_not_ready`. The frontend on `UIFixes_Audrey` already treats that as "keep today's access", which also hides Manager and the Permissions button.
- **Admin endpoints:** 503 `permissions_not_ready`. Choosing Manager in Add or Edit User also gets 503, instead of the old CHECK failing as a 500.
- **The override table:** never queried.

Once 0034 is applied, the app switches over within a minute, with no restart and no frontend deploy. The order doesn't matter, but the smoother one is: merge and deploy, then apply 0034.

## 7. Tests

- **`tests/backend/test_permissions.py`** (new, 112 tests):
  - the rule (preset + grants − removals; admin gets everything; deny by default);
  - the frontend's copies match the catalog and presets word for word;
  - every route is guarded;
  - the staff preset equals today's staff access;
  - the 403 shape and any-of keys;
  - the per-request check;
  - `/auth/me`;
  - all three admin endpoints (storage, audit, sign-out on a role change, 404/409/422);
  - the Postman-style token and self-promotion cases;
  - before-0034 behaviour and the readiness cache;
  - the page smoke test.
- **Updated:** `test_users.py`, `test_auth.py` and `test_accounts.py` (case-insensitive duplicates, last admin, the index-race 409), `test_admin_only_writes.py` (the contract's 403, and managers can write), and `test_dashboard.py`, `test_abc.py` and `test_sku.py` (LP figures with and without `lp.view`).
- **Full suite:** 836 passed, 8 skipped, 0 failed.
- **Frontend:** lint has 0 errors, the build passes, and no dev-mock code is in the production bundle.
- **Do the tests catch mistakes?** I broke the code six ways on purpose, and each break failed tests:
  - any-of changed to all-of: 6 failed;
  - the guard always passes: 24;
  - overrides ignored: 22;
  - the self-promotion check removed: 5;
  - the Dashboard strip removed: 1;
  - `/segment` narrowed to `lp.view`: 3.

## 8. For you to decide

1. **Who can create admins.** Only changes to your own access are blocked. Someone given `users.manage` can still invite a new admin or promote someone else. Should making an admin, or granting `users.manage`, need an admin?
2. **Sign-out on a role change from the Permissions screen.** Currently yes, matching Edit User; box changes alone don't sign anyone out. Keep it?
3. **Endpoints no page calls yet.** `/inventory/*` is on `dashboard.view` and `/policy-comparison` on `lp.view`. Are those right?
4. **Sign-in and email case.** Sign-in still matches the email exactly. With the new index, matching `lower(email)` there is now safe, but it's out of scope here.
5. **After 0034 is live:** frontend Phase 6 deletes the dev mock and the legacy fallback (`reports/PERMISSIONS_FRONTEND_2026-09-30.md`, section 5).
6. **Already out of date before this branch:** `schema.sql` doesn't reflect 0031 (`password_hash` nullable, `auth_token`, `'revoked'`). Only 0034 is added there.

## 9. Files

- **Backend (new):**
  - `backend/permissions.py` (the model, the dependency and the readiness check);
  - `backend/routers/permissions.py`;
  - `backend/schemas/permissions.py`;
  - `backend/api_errors.py` (the `{detail, code}` error type).
- **Backend (changed):**
  - `main.py`;
  - `audit.py` (docstring);
  - `routers/auth.py`: `/auth/me`, and register needs `users.manage` and checks email case-insensitively;
  - `routers/users.py`: `users.manage`, last admin, case-insensitive email;
  - `schemas/auth.py` and `schemas/users.py`: manager;
  - the guard on `abc`, `audit_log`, `category_trends`, `dashboard`, `decomposition`, `forecast`, `fsn`, `inventory`, `pareto`, `policy_comparison`, `recommendations`, `segment` and `sku`;
  - LP removal in `dashboard`, `abc` and `sku`.
- **Database:** `analytics/db/migrations/0034_user_permissions.sql` (new) and `analytics/db/schema.sql`.
- **Frontend:**
  - the Add User flow (name and email, then your permissions screen, then save with a check mark): `UserFormModal`, `PermissionsModal`, `UserManagement`;
  - the "—" and "Stock on hand" display: `Dashboard`, `ABCClassification`, `Charts`;
  - the new error codes: `PermissionsModal`, and the dev mock.
- **Tests:** as in section 7.
