# Permissions: what the frontend expects from the backend

- **From:** Audrey
- **To:** Yuan (and Kelvin)
- **Date:** 2026-09-30, updated for the revised proposal the same day
- **Branch:** `feat/permissions-frontend`, merged into `UIFixes_Audrey` on 2026-09-30. The Add User flow below and the backend half are on `feat/permissions-backend`, for your review (see `reports/PERMISSIONS_BACKEND_2026-09-30.md`).
- **Status:** the frontend tasks of your revised proposal are built, against a dev-only mock that follows your API contract. It is live, but dormant until your endpoints exist:
  - While `GET /auth/me` returns 404, the app keeps today's access: the login token's role, with staff seeing every page except the Audit Log, User Management and (your step 0) Data Management.
  - Until then, the Permissions button on each user row and the Manager role stay hidden. Add User still opens the permissions screen, but it offers Admin and Staff only and shows each role's pages read-only.
  - Once `/auth/me` answers, the app switches to the new permissions by itself.

## 1. The shapes the frontend reads (from your contract)

| Endpoint | What the frontend reads |
|---|---|
| `GET /auth/me` | `role` and `permissions` (a list of keys). |
| `GET /admin/permissions/catalog` | `permissions: [{key, label, group, description}]` and `roles: {admin: "all", manager: [...], staff: [...]}`. The permissions screen is built entirely from it, one box per permission, grouped by `group`. |
| `GET /admin/users/{id}/permissions` | `{role, overrides: {key: true/false}, permissions: [key, ...]}`. The contract doesn't name these fields; the backend on `feat/permissions-backend` uses these names. |
| `PUT /admin/users/{id}/permissions` | The body is `{role, overrides}`, with only the differences from the role's preset. The reply has the same shape as the GET. |
| Errors (403, 404, 409, 422) | `detail` is shown as it is; the frontend branches only on `code` (`missing_permission`, `last_admin`, `self_lockout`, `self_promotion`, `unknown_permission`, `user_not_found`). A `missing_permission` 403 also reloads `/auth/me`. |
| `GET /dashboard` without `lp.view` | `lp_hidden: true`: the two LP cards show "—" with the reason, and the reorder and policy widgets aren't drawn. |
| `GET /abc` without `lp.view` | Stock status `ON HAND` ("Stock on hand") instead of the three statuses that compare stock with the reorder point. |

## 2. The keys the frontend checks

All are the names in your Design table, in `frontend/src/permissions/keys.js`.

| Key | Where the frontend checks it |
|---|---|
| `dashboard.view`, `abc.view`, `forecast.view`, `category_trends.view`, `sku.view` | The tab and the page |
| `sku.edit` | Add SKU and Edit SKU |
| `lp.view` | The Reorder Recs tab and page |
| `lp.decide` | Accept, Dismiss, bulk Accept |
| `audit_log.view`, `upload.run` | The Audit Log and Data Management tabs and pages |
| `users.manage` | User Management, including Add User and the permissions screen |

## 3. How Add User works now

1. **Add User:** full name and email, then **Next**.
2. **The permissions screen** (your design: role dropdown, boxes grouped by page from the catalog, boxes that differ from the role's preset marked, "Reset to role defaults"), for the new person, with a **Back** button.
3. **Save:** `POST /auth/register` with the role, then `PUT /admin/users/{id}/permissions` with the overrides, if any. A green check mark shows, and the window closes. If the second call fails, the account still exists, so the check mark's message says their page choices didn't save and to use the Permissions button on their row.

## 4. Still open (from your list)

1. Are Admin / Manager / Staff the right three roles for SSM, or should Manager be split?
2. ~~Manager needs the `users.role` CHECK widened and the two role schemas.~~ Done on `feat/permissions-backend`: migration 0034 widens the CHECK, and both schemas accept `manager`.

Your step 5 is done too: the Dashboard, ABC and SKU Management show "—" (or "Stock on hand") where the response leaves an LP figure out.

## 5. When your endpoints go live (your step 4, my Phase 6)

1. Your endpoints are deployed. The app then leaves its fallback on its own: `/auth/me` no longer returns 404.
2. Test every role together: the tabs, typed URLs, buttons, Add User, an override taking effect on the next click, and last-admin and self-lockout changes being refused.
3. Remove what is no longer needed:
   - the mock: `frontend/src/api/mocks/permissionsMock.js`, `frontend/src/components/dev/`, and the `MOCK_PERMISSIONS` branches in `auth.js`, `api/permissions.js`, `utils/usersApi.js` and `DashboardLayout.jsx`;
   - the fallback: `LEGACY_STAFF_ACCESS` and `LEGACY_CATALOG` in `permissions/keys.js`, and the `legacy` flag in `PermissionsProvider.jsx`, `PermissionsModal.jsx`, `UserManagement.jsx` and `UserFormModal.jsx`.

To try it now: set `VITE_MOCK_PERMISSIONS=true` in `frontend/.env.local` and run the dev server. A "DEV" switch in the bottom-right corner lets you act as Admin, Manager or Staff.
