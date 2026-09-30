// frontend/src/permissions/keys.js — every permission key the frontend
// checks, and which page each one opens.
//
// Yuan's permissions proposal (revised 2026-09-30 after Audrey's review):
// the backend owns the catalog (GET /admin/permissions/catalog) and refuses
// any request a user lacks the permission for; the frontend only hides what
// they can't use. The admin permissions screen renders whatever the catalog
// returns, so adding a permission needs no change there. This file lists
// only the keys the UI itself checks, named as in the proposal's table, so
// renaming one is a change here and nowhere else.
export const P = {
  DASHBOARD_VIEW: 'dashboard.view',
  ABC_VIEW: 'abc.view',
  FORECAST_VIEW: 'forecast.view',
  CATEGORY_TRENDS_VIEW: 'category_trends.view',
  SKU_VIEW: 'sku.view',
  SKU_EDIT: 'sku.edit',
  LP_VIEW: 'lp.view',
  LP_DECIDE: 'lp.decide',
  AUDIT_LOG_VIEW: 'audit_log.view',
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

export const roleLabel = (role) => ROLES.find((r) => r.value === role)?.label || role;

// Each page and the permission that opens it, in sidebar order. The sidebar,
// the route guards and "the first page you can open" all read this, so a page
// can't be hidden in one place and still reachable in another.
export const PAGES = [
  { path: '/', label: 'Dashboard', permission: P.DASHBOARD_VIEW },
  { path: '/forecast', label: 'SKU Forecast', permission: P.FORECAST_VIEW },
  { path: '/category-trends', label: 'Category Trends', permission: P.CATEGORY_TRENDS_VIEW },
  { path: '/sku-management', label: 'SKU Management', permission: P.SKU_VIEW },
  { path: '/abc', label: 'ABC Classification', permission: P.ABC_VIEW },
  { path: '/reorder', label: 'Reorder Recs', permission: P.LP_VIEW },
  { path: '/audit-log', label: 'Audit Log', permission: P.AUDIT_LOG_VIEW },
  { path: '/upload', label: 'Data Management', permission: P.UPLOAD_RUN },
  { path: '/users', label: 'User Management', permission: P.USERS_MANAGE },
];

export const permissionForPath = (path) => PAGES.find((page) => page.path === path)?.permission;

// TEMPORARY, until the backend has GET /auth/me (it returns 404 today): the
// access staff had before this change, so deploying the frontend first
// changes nobody's access. An admin has everything; staff get every page
// except the Audit Log and User Management, and can't accept or dismiss
// recommendations or add or edit SKUs. Data Management is admins-only now
// too: the proposal's frontend step 0, since it is a non-working mock.
// PermissionsProvider uses this only when /auth/me is missing; delete it
// with the dev mock once the endpoint is live (Phase 6 in
// reports/PERMISSIONS_FRONTEND_2026-09-30.md).
export const LEGACY_STAFF_ACCESS = [
  P.DASHBOARD_VIEW, P.FORECAST_VIEW, P.CATEGORY_TRENDS_VIEW, P.SKU_VIEW, P.ABC_VIEW, P.LP_VIEW,
];

// TEMPORARY, same lifetime as LEGACY_STAFF_ACCESS: the permission list in
// Yuan's proposal (its Design table), grouped by page, standing in for GET
// /admin/permissions/catalog until the backend has it. The Permissions
// modal shows it read-only with each role's access today, so it already
// looks like the real screen; the dev mock uses the same list.
export const LEGACY_CATALOG = {
  permissions: [
    { key: P.DASHBOARD_VIEW, label: 'View the dashboard', group: 'Dashboard', description: 'Sales, stock and forecast overview.' },
    { key: P.ABC_VIEW, label: 'View ABC classification', group: 'ABC classification', description: 'Which products are tier A, B or C.' },
    { key: P.FORECAST_VIEW, label: 'View forecasts', group: 'Predictive / SKU Forecast', description: 'Each product’s forecast.' },
    { key: P.CATEGORY_TRENDS_VIEW, label: 'View category trends', group: 'Category Trends', description: 'How each category is moving.' },
    { key: P.SKU_VIEW, label: 'View SKU Management', group: 'SKU Management', description: 'The product list.' },
    { key: P.SKU_EDIT, label: 'Add or edit SKUs', group: 'SKU Management', description: 'Changes the product master.' },
    { key: P.LP_VIEW, label: 'View reorder recommendations', group: 'LP / Reorder', description: 'Also the LP figures shown on other pages.' },
    { key: P.LP_DECIDE, label: 'Accept or dismiss recommendations', group: 'LP / Reorder', description: 'Changes what SSM orders.' },
    { key: P.AUDIT_LOG_VIEW, label: 'View the audit log', group: 'Audit Log', description: 'Who changed what, and when.' },
    { key: P.UPLOAD_RUN, label: 'Use Data Management', group: 'Data Management', description: 'Uploads (Module 07); a mock page for now.' },
    { key: P.USERS_MANAGE, label: 'Manage users', group: 'User Management', description: 'Invite users, set roles and permissions.' },
  ],
  roles: { admin: 'all', staff: LEGACY_STAFF_ACCESS },
};
