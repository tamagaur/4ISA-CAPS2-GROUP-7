// frontend/src/api/mocks/permissionsMock.js — a DEV-ONLY stand-in for the
// permission endpoints in Kelvin's permissions proposal, until the backend
// has them. Delete this file, and the MOCK_PERMISSIONS branches that call it,
// once the real endpoints are live (Phase 6 of the frontend plan).
//
// Off unless VITE_MOCK_PERMISSIONS=true on a dev server: import.meta.env.DEV
// is false in `vite build`, so none of this reaches a production bundle.
//
// Every response has the shape of the proposal's API contract, returned as a
// real Response so callers handle it exactly like the backend's. State lives
// in localStorage so a reload keeps it:
//   dsd_mock_me     { role, overrides }: who the signed-in person acts as
//   dsd_mock_users  { [user_id]: { role, overrides } }: saved on the admin screen
import { effectiveKeys, normalizeOverrides } from '../../permissions/rules';

export const MOCK_PERMISSIONS = import.meta.env.DEV && import.meta.env.VITE_MOCK_PERMISSIONS === 'true';

const ME_KEY = 'dsd_mock_me';
const USERS_KEY = 'dsd_mock_users';

// The proposal's draft catalog and presets, plus the provisional keys in
// permissions/keys.js, whose presets keep today's access for those pages.
export const MOCK_CATALOG = {
  permissions: [
    { key: 'dashboard.view', label: 'Dashboard', group: 'Analytics', description: 'Open the dashboard.' },
    { key: 'forecast.view', label: 'SKU Forecast', group: 'Analytics', description: 'Open the forecasts page.' },
    { key: 'trends.view', label: 'Category Trends', group: 'Analytics', description: 'Open category trends. Provisional key.' },
    { key: 'abc.view', label: 'ABC Classification', group: 'Management', description: 'Open the ABC classification page.' },
    { key: 'sku.view', label: 'SKU Management', group: 'Management', description: 'See the product list. Provisional key.' },
    { key: 'sku.edit', label: 'Add or edit SKUs', group: 'Management', description: 'Changes the product master. Provisional key.' },
    { key: 'lp.view', label: 'Reorder recommendations', group: 'LP / Reorder', description: 'See the recommended orders.' },
    { key: 'lp.decide', label: 'Accept or dismiss recommendations', group: 'LP / Reorder', description: 'Changes what SSM orders.' },
    { key: 'audit.view', label: 'Audit Log', group: 'Admin', description: 'See who changed what, and when. Provisional key.' },
    { key: 'upload.run', label: 'Data Management (upload)', group: 'Admin', description: 'Reserved for Module 07.' },
    { key: 'users.manage', label: 'Manage users', group: 'Admin', description: 'Invite users, set roles and permissions.' },
  ],
  roles: {
    admin: 'all',
    manager: ['dashboard.view', 'forecast.view', 'trends.view', 'abc.view', 'sku.view', 'lp.view', 'lp.decide'],
    staff: ['dashboard.view', 'forecast.view', 'trends.view', 'abc.view', 'sku.view'],
  },
};

const respond = (status, body) => new Response(JSON.stringify(body), {
  status,
  headers: { 'Content-Type': 'application/json' },
});

function read(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch { /* storage off: the mock just doesn't survive a reload */ }
}

const effective = (role, overrides) => [...effectiveKeys(MOCK_CATALOG, role, overrides)];

// ── The signed-in person, as the dev panel sets them ──────────────────────
// Starts as the role on their login token, so an admin stays an admin.
export function getMockMe(tokenRole) {
  const saved = read(ME_KEY, null);
  return { role: saved?.role || tokenRole || 'staff', overrides: saved?.overrides || {} };
}

export function setMockMe({ role, overrides }) {
  write(ME_KEY, { role, overrides: normalizeOverrides(MOCK_CATALOG, role, overrides) });
}

export function resetMock() {
  try {
    localStorage.removeItem(ME_KEY);
    localStorage.removeItem(USERS_KEY);
  } catch { /* nothing stored */ }
}

// GET /auth/me. `user` is auth.getCurrentUser().
export function mockMe(user) {
  const me = getMockMe(user?.role);
  return respond(200, {
    email: user?.email ?? null,
    full_name: user?.fullName ?? '',
    role: me.role,
    permissions: effective(me.role, me.overrides),
  });
}

// GET /admin/permissions/catalog
export const mockCatalog = () => respond(200, MOCK_CATALOG);

// ── Other people, as the admin screen saves them ───────────────────────────
// `user` is a row from GET /users; its role is the start until one is saved.
function savedAccess(user) {
  const saved = read(USERS_KEY, {})[user.user_id];
  return { role: saved?.role || user.role, overrides: saved?.overrides || {} };
}

// GET /admin/users/{id}/permissions
export function mockUserPermissions(user) {
  const { role, overrides } = savedAccess(user);
  return respond(200, { user_id: user.user_id, role, overrides, permissions: effective(role, overrides) });
}

// PUT /admin/users/{id}/permissions, with the proposal's refusals: 422 for a
// key the catalog doesn't have, 409 for a change that leaves no admin or
// takes away the saver's own access. `users` is GET /users with mock roles.
export function mockSaveUserPermissions(user, { role, overrides = {} }, { isSelf, users }) {
  const known = new Set(MOCK_CATALOG.permissions.map((permission) => permission.key));
  const unknown = Object.keys(overrides).find((key) => !known.has(key));
  if (unknown) return respond(422, { detail: 'unknown_permission', permission: unknown });

  const before = savedAccess(user);
  const next = { role, overrides: normalizeOverrides(MOCK_CATALOG, role, overrides) };
  const couldManage = effective(before.role, before.overrides).includes('users.manage');
  const canManage = effective(next.role, next.overrides).includes('users.manage');
  if (isSelf && ((before.role === 'admin' && role !== 'admin') || (couldManage && !canManage))) {
    return respond(409, { detail: 'self_lockout' });
  }
  const admins = users.filter((row) => row.role === 'admin').length;
  if (before.role === 'admin' && role !== 'admin' && admins <= 1) {
    return respond(409, { detail: 'last_admin' });
  }

  write(USERS_KEY, { ...read(USERS_KEY, {}), [user.user_id]: next });
  return respond(200, { user_id: user.user_id, ...next, permissions: effective(next.role, next.overrides) });
}

// GET /users shows each account's role; with the mock, show the saved one.
export function overlayMockRoles(users) {
  const saved = read(USERS_KEY, {});
  return users.map((row) => (saved[row.user_id]?.role ? { ...row, role: saved[row.user_id].role } : row));
}

// ── Refusing requests, as the backend will ────────────────────────────────
// Only the endpoints the UI gates an action or a page's data on: enough to
// try the 403 path before the backend exists. The backend will check them all.
const MOCK_RULES = [
  { methods: ['PATCH'], pattern: /^\/recommendations\/[^/?]+/, permission: 'lp.decide' },
  { methods: ['GET'], pattern: /^\/recommendations(\?|$)/, permission: 'lp.view' },
  { methods: ['POST'], pattern: /^\/sku(\?|$)/, permission: 'sku.edit' },
  { methods: ['PATCH'], pattern: /^\/sku\/[^/?]+/, permission: 'sku.edit' },
  { methods: ['GET'], pattern: /^\/audit-log/, permission: 'audit.view' },
  { methods: ['GET', 'POST', 'PATCH', 'DELETE'], pattern: /^\/users(\/|\?|$)/, permission: 'users.manage' },
  { methods: ['POST'], pattern: /^\/auth\/register$/, permission: 'users.manage' },
];

// The key a request lacks, or null when the mock lets it through.
export function mockDeniedPermission(method, path, tokenRole) {
  const verb = (method || 'GET').toUpperCase();
  const rule = MOCK_RULES.find((r) => r.methods.includes(verb) && r.pattern.test(path));
  if (!rule) return null;
  const me = getMockMe(tokenRole);
  return effective(me.role, me.overrides).includes(rule.permission) ? null : rule.permission;
}
