// frontend/src/api/permissions.js — the four calls in the "API contract"
// section of Kelvin's permissions proposal. Until the backend has them, a dev
// server with VITE_MOCK_PERMISSIONS=true answers from api/mocks instead,
// in the same shapes.
import { apiFetch, getCurrentUser } from '../auth';
import {
  MOCK_PERMISSIONS, mockCatalog, mockMe, mockSaveUserPermissions, mockUserPermissions, overlayMockRoles,
} from './mocks/permissionsMock';

const MOCK = import.meta.env.DEV && MOCK_PERMISSIONS;

// A refused call: `message` is the backend's sentence (`detail`), and
// `code` the proposal's machine code (missing_permission, last_admin,
// self_lockout, unknown_permission), which screens branch on.
export class PermissionApiError extends Error {
  constructor(message, { status, code = null, permission = null } = {}) {
    super(message);
    this.name = 'PermissionApiError';
    this.status = status;
    this.code = code;
    this.permission = permission;
  }
}

async function readJson(res, fallback) {
  const body = await res.json().catch(() => null);
  if (res.ok) return body;
  const detail = body?.detail;
  throw new PermissionApiError(typeof detail === 'string' ? detail : fallback, {
    status: res.status,
    code: body?.code ?? null,
    permission: body?.permission ?? null,
  });
}

// GET /auth/me -> { email, full_name, role, permissions: [key, ...] }
export async function getMe() {
  const res = MOCK ? mockMe(getCurrentUser()) : await apiFetch('/auth/me');
  return readJson(res, 'Could not load what your account can open.');
}

// GET /admin/permissions/catalog ->
//   { permissions: [{ key, label, group, description }], roles: { admin: 'all', manager: [...], staff: [...] } }
export async function getPermissionCatalog() {
  const res = MOCK ? mockCatalog() : await apiFetch('/admin/permissions/catalog');
  return readJson(res, 'Could not load the list of permissions.');
}

// GET /admin/users/{id}/permissions -> { role, overrides: { key: bool }, permissions: [key, ...] }.
// Takes the whole row from GET /users: the mock starts from its role.
export async function getUserPermissions(user) {
  const res = MOCK ? mockUserPermissions(user) : await apiFetch(`/admin/users/${user.user_id}/permissions`);
  return readJson(res, "Could not load this user's permissions.");
}

// PUT /admin/users/{id}/permissions with { role, overrides } (only what
// differs from the role's preset) -> the same shape as the GET.
export async function saveUserPermissions(user, { role, overrides }) {
  let res;
  if (MOCK) {
    const listed = await apiFetch('/users');
    const users = listed.ok ? overlayMockRoles(await listed.json()) : [];
    res = mockSaveUserPermissions(user, { role, overrides }, {
      isSelf: user.email === getCurrentUser()?.email,
      users,
    });
  } else {
    res = await apiFetch(`/admin/users/${user.user_id}/permissions`, {
      method: 'PUT',
      body: JSON.stringify({ role, overrides }),
    });
  }
  return readJson(res, 'Could not save the permissions.');
}
