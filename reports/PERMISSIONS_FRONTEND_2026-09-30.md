# Permissions: what the frontend expects from the backend

- **From:** Audrey
- **To:** Kelvin (and Yuan)
- **Date:** 2026-09-30
- **Branch:** `feat/permissions-frontend`, merged into `UIFixes_Audrey` on 2026-09-30
- **Status:** frontend tasks 1–7 of your proposal are built, against a dev-only mock that follows your API contract. It is live, but dormant until your endpoints exist:
  - While `GET /auth/me` returns 404, the app keeps the access it gave before: the login token's role, with staff seeing every page except the Audit Log and User Management.
  - Until then, the Permissions button and the Manager role stay hidden.
  - Once `/auth/me` answers, the app switches to the new permissions by itself.

## 1. The shapes the frontend reads (please confirm or correct)

| Endpoint | What the frontend assumes |
|---|---|
| `GET /auth/me` | **A new endpoint.** There is no `/auth/me` today; the frontend used to read the role off the login token. It reads `role` and `permissions` (a list of keys). |
| `GET /admin/permissions/catalog` | As in your contract: `permissions: [{key, label, group, description}]` and `roles: {admin: "all", manager: [...], staff: [...]}`. The admin screen is built entirely from it. |
| `GET /admin/users/{id}/permissions` | `{role, overrides: {key: true/false}, permissions: [key, ...]}`. The contract doesn't name these fields, so these are the names I used. |
| `PUT /admin/users/{id}/permissions` | The body is `{role, overrides}`, with only the differences from the role's preset. The reply has the same shape as the GET. |
| 403 | `{"detail": "missing_permission", "permission": "<key>"}` with `permission` at the top level. `HTTPException` nests everything under `detail`, so this needs a custom exception handler. |
| 409 | `{"detail": "last_admin"}` or `{"detail": "self_lockout"}` |
| 422 | `{"detail": "unknown_permission", "permission": "<key>"}` |

## 2. The keys the frontend checks

| Key | Where | In your draft list? |
|---|---|---|
| `dashboard.view`, `forecast.view`, `abc.view` | Their pages | Yes |
| `lp.view` | Reorder Recs page | Yes |
| `lp.decide` | Accept, Dismiss, bulk Accept | Yes |
| `upload.run` | Data Management page (today a mock every user can see) | Yes |
| `users.manage` | User Management page, including the permissions screen | Yes |
| `sku.view` | SKU Management page | **No: provisional** |
| `sku.edit` | Add SKU and Edit SKU (`POST`/`PATCH /sku`, admin-only today) | **No: provisional** |
| `trends.view` | Category Trends page | **No: provisional** |
| `audit.view` | Audit Log page (admin-only today) | **No: provisional** |

In the mock, `sku.view` and `trends.view` go to every role, and `sku.edit` and `audit.view` to admins only, which keeps today's access. All keys live in `frontend/src/permissions/keys.js`, so a rename is a one-line change.

## 3. Questions

1. **Keys for the four pages above.** Are those names OK, and what presets should they have?
2. **Staff and `lp.view`.** Your matrix says Staff doesn't get it, and the mock follows that. I'd suggest read-only by default: LP numbers also appear on the Dashboard, ABC and SKU Management, so hiding only the tab doesn't hide them.
3. **`users.manage`.** Should it come only with the admin role, never through an override? And should nobody be able to edit their own permissions? Otherwise someone granted `users.manage` could give themselves more access, or demote the only admin.
4. **Where roles change.** Your doc keeps the role in both the Edit User form (`PATCH /users`) and the permissions screen (`PUT`). Is that OK, or should only the permissions screen change it?
5. **Manager.** It needs the `users.role` CHECK widened from `('admin', 'staff')`, plus the two `Literal["admin", "staff"]` schemas (`backend/schemas/auth.py:40`, `backend/schemas/users.py:33`). Until then, saving a Manager from the Add/Edit User form returns a 422.

## 4. When your endpoints go live (your step 4, my Phase 6)

1. Your endpoints are deployed. The app then leaves its fallback on its own: `/auth/me` no longer returns 404.
2. Test every role together: the tabs, typed URLs, buttons, an override taking effect on the next click, and last-admin and self-lockout changes being refused.
3. Remove what is no longer needed:
   - the mock: `frontend/src/api/mocks/permissionsMock.js`, `frontend/src/components/dev/`, and the `MOCK_PERMISSIONS` branches in `auth.js`, `api/permissions.js`, `utils/usersApi.js` and `DashboardLayout.jsx`;
   - the fallback: `LEGACY_STAFF_ACCESS` in `permissions/keys.js`, and the `legacy` flag in `PermissionsProvider.jsx`, `UserManagement.jsx` and `UserFormModal.jsx`.

To try it now: set `VITE_MOCK_PERMISSIONS=true` in `frontend/.env.local` and run the dev server. A "DEV" switch in the bottom-right corner lets you act as Admin, Manager or Staff.
