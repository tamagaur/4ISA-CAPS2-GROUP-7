// frontend/src/permissions/keys.js — every permission key the frontend
// checks, and which page each one opens.
//
// Kelvin's permissions proposal (2026-09-30): the backend owns the catalog
// (GET /admin/permissions/catalog) and refuses any request a user lacks the
// permission for; the frontend only hides what they can't use. The admin
// permissions screen renders whatever the catalog returns, so adding a
// permission needs no change there. This file lists only the keys the UI
// itself checks, so renaming one is a change here and nowhere else.
//
// PROVISIONAL until Kelvin confirms: sku.view, sku.edit, trends.view and
// audit.view. The proposal's draft list has no row for SKU Management,
// Category Trends or the Audit Log.
export const P = {
  DASHBOARD_VIEW: 'dashboard.view',
  FORECAST_VIEW: 'forecast.view',
  TRENDS_VIEW: 'trends.view',
  SKU_VIEW: 'sku.view',
  SKU_EDIT: 'sku.edit',
  ABC_VIEW: 'abc.view',
  LP_VIEW: 'lp.view',
  LP_DECIDE: 'lp.decide',
  AUDIT_VIEW: 'audit.view',
  UPLOAD_RUN: 'upload.run',
  USERS_MANAGE: 'users.manage',
};

// The three roles are fixed by the proposal's design. What each one grants
// comes from the catalog, never from here.
export const ROLES = [
  { value: 'admin', label: 'Admin' },
  { value: 'manager', label: 'Manager' },
  { value: 'staff', label: 'Staff' },
];

// Each page and the permission that opens it, in sidebar order. The sidebar,
// the route guards and "the first page you can open" all read this, so a page
// can't be hidden in one place and still reachable in another.
export const PAGES = [
  { path: '/', label: 'Dashboard', permission: P.DASHBOARD_VIEW },
  { path: '/forecast', label: 'SKU Forecast', permission: P.FORECAST_VIEW },
  { path: '/category-trends', label: 'Category Trends', permission: P.TRENDS_VIEW },
  { path: '/sku-management', label: 'SKU Management', permission: P.SKU_VIEW },
  { path: '/abc', label: 'ABC Classification', permission: P.ABC_VIEW },
  { path: '/reorder', label: 'Reorder Recs', permission: P.LP_VIEW },
  { path: '/audit-log', label: 'Audit Log', permission: P.AUDIT_VIEW },
  { path: '/upload', label: 'Data Management', permission: P.UPLOAD_RUN },
  { path: '/users', label: 'User Management', permission: P.USERS_MANAGE },
];

export const permissionForPath = (path) => PAGES.find((page) => page.path === path)?.permission;

// TEMPORARY, until the backend has GET /auth/me (it returns 404 today): the
// access the app gave before this change, so deploying the frontend first
// changes nobody's access. An admin had everything; staff had every page
// except the Audit Log and User Management, and couldn't accept or dismiss
// recommendations or add or edit SKUs. PermissionsProvider uses this only
// when /auth/me is missing; delete it with the dev mock once the endpoint
// is live (Phase 6 in reports/PERMISSIONS_FRONTEND_2026-09-30.md).
export const LEGACY_STAFF_ACCESS = [
  P.DASHBOARD_VIEW, P.FORECAST_VIEW, P.TRENDS_VIEW, P.SKU_VIEW, P.ABC_VIEW, P.LP_VIEW, P.UPLOAD_RUN,
];

// What a 403 means, in words for the person who got it. A 403 carries the
// key it was missing; the raw code ("missing_permission") never reaches a page.
const DENIED_MESSAGES = {
  [P.LP_VIEW]: "You don't have access to reorder recommendations.",
  [P.LP_DECIDE]: "You don't have permission to accept or dismiss recommendations.",
  [P.SKU_EDIT]: "You don't have permission to add or edit SKUs.",
  [P.AUDIT_VIEW]: "You don't have access to the audit log.",
  [P.UPLOAD_RUN]: "You don't have permission to upload data.",
  [P.USERS_MANAGE]: "You don't have permission to manage users.",
};

export function deniedMessage(permission) {
  const reason = DENIED_MESSAGES[permission] || "You don't have permission to do that.";
  return `${reason} Ask an admin if you need it.`;
}
