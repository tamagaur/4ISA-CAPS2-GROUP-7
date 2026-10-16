// frontend/src/auth.js — token storage + authenticated fetch helper
// (Story #89: login; Story #91: session expiry).
//
// The JWT is kept in localStorage (not a cookie) because the backend is a
// separate origin in dev (Vite on :5173, FastAPI on :8000) and this app has
// no server-side rendering step that would benefit from httpOnly cookies.
// Tradeoff: localStorage is readable by any JS on the page, so it's only as
// safe as this app's exposure to XSS — acceptable for an internal staff
// tool, worth revisiting if the dashboard ever embeds third-party scripts.

import { invalidateCache } from './api/cache';
import { MOCK_PERMISSIONS, mockDeniedPermission } from './api/mocks/permissionsMock';
import { dataModeHeaders } from './dataMode';

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const TOKEN_KEY = 'dsd_access_token';
const ROLE_KEY = 'dsd_role';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRole() {
  return localStorage.getItem(ROLE_KEY);
}

// Decodes a JWT's payload without verifying its signature — client-side
// code has no way to check the signature (that needs JWT_SECRET_KEY, which
// never reaches the browser), so this is only ever used to read the `exp`
// claim for a UX-level expiry check. The backend is the actual authority:
// every real API call is still verified server-side by deps.get_current_user.
function decodeTokenPayload(token) {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
    const json = decodeURIComponent(
      atob(padded)
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join('')
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}

// True if the token is missing, malformed, or its `exp` claim has passed.
export function isTokenExpired(token) {
  const payload = decodeTokenPayload(token);
  if (!payload || typeof payload.exp !== 'number') return true;
  return Date.now() >= payload.exp * 1000;
}

export function isAuthenticated() {
  const token = getToken();
  return Boolean(token) && !isTokenExpired(token);
}

// Reads { email, role, fullName } off the current session's JWT for display
// purposes (e.g. the Sidebar's signed-in-as line, attributing a reorder
// override to the user who made it — Story #93). Not for authorization
// decisions — the signature isn't verified client-side.
export function getCurrentUser() {
  const token = getToken();
  if (!token) return null;
  const payload = decodeTokenPayload(token);
  if (!payload) return null;
  return { email: payload.email, role: payload.role, fullName: payload.full_name || '' };
}

// Set just before an involuntary redirect to /login so the login page can
// explain WHY the user landed there. Without this the redirect fires before
// any component can render the "Session expired" error apiFetch throws, so
// the user was simply bounced mid-action with no explanation.
export const SESSION_EXPIRED_KEY = 'san2_session_expired';

function redirectToLogin() {
  if (typeof window !== 'undefined') {
    try {
      sessionStorage.setItem(SESSION_EXPIRED_KEY, '1');
    } catch { /* private mode / storage disabled — the redirect still works */ }
    window.location.href = '/login';
  }
}

export function setSession(accessToken, role) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(ROLE_KEY, role);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
  // Cached API responses belong to the session that fetched them — the next
  // account to sign in on this tab must not be served them.
  invalidateCache();
}

// FastAPI's `detail` is a plain string for our own HTTPExceptions (401 wrong
// password, etc.) but a LIST of Pydantic error objects for 422 validation
// failures (e.g. an empty/malformed email) — `new Error(detail)` on that
// array stringifies to the unreadable "[object Object]". Normalize both
// shapes to one readable string.
function extractErrorMessage(body, fallback) {
  const detail = body?.detail;
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((e) => e.msg || JSON.stringify(e)).join(' ');
  }
  return fallback;
}

// ── "Remember me" on the code step (backend/mfa.py, REMEMBER_DAYS) ────────
// Ticking it at the code step makes the backend hand this browser a
// remember_token. Sent with the next sign-ins, it skips the code (never the
// password) for 7 days; the backend checks it and ignores a stale one. One
// token per email, so two people sharing a computer don't replace each
// other's. Kept through sign-out on purpose: that is the point of it. It
// goes when it expires, or when that person next passes the code step with
// the box unticked.
const REMEMBER_KEY = 'dsd_remembered_devices';
export const REMEMBER_DAYS = 7;

function readRemembered() {
  try {
    const stored = JSON.parse(localStorage.getItem(REMEMBER_KEY) || '{}');
    return stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {};
  } catch {
    return {};
  }
}

function writeRemembered(emailKey, token) {
  try {
    const stored = readRemembered();
    if (token) stored[emailKey] = token;
    else delete stored[emailKey];
    localStorage.setItem(REMEMBER_KEY, JSON.stringify(stored));
  } catch { /* storage unavailable: the code is simply asked next time */ }
}

const rememberKeyFor = (email) => String(email || '').trim().toLowerCase();

function getRememberToken(email) {
  const key = rememberKeyFor(email);
  const token = readRemembered()[key];
  if (!token) return null;
  if (isTokenExpired(token)) {
    writeRemembered(key, null);
    return null;
  }
  return token;
}

// Whether this browser is remembered for `email` (the sign-in page ticks
// "Remember me" for it).
export const isDeviceRemembered = (email) => Boolean(getRememberToken(email));

// `remember` is the sign-in page's "Remember me" box (2026-10-16: it moved
// there from the code step). Unticked, this browser forgets `email` and the
// code is asked again; ticked, a remembered browser skips the code.
export async function login(email, password, { remember = true } = {}) {
  if (!remember) writeRemembered(rememberKeyFor(email), null);
  const rememberToken = remember ? getRememberToken(email) : null;
  const res = await fetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, ...(rememberToken ? { remember_token: rememberToken } : {}) }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(extractErrorMessage(body, 'Login failed. Check your email and password.'));
  }

  // The backend records the sign-in itself (a user_session row, see
  // backend/routers/auth.py) — the Audit Log page counts sign-ins from
  // there, so nothing is posted to /audit-log from here.
  const data = await res.json();
  // Two-step sign-in (backend/mfa.py): a right password for an account with
  // an authenticator app answers { mfa_step: 'verify' | 'setup', mfa_token }
  // instead of a session. The login page takes it from there.
  if (data.mfa_step) return data;
  setSession(data.access_token, data.role);
  return data;
}

// ── Password links (invites and "Forgot password?") ──────────────────────
// Public endpoints: the person using them has no session. Plain fetch, not
// apiFetch — its 401 handling would bounce them to /login mid-flow. Errors
// carry the HTTP status so a page can tell "this link is dead" (400) from
// "the server couldn't be reached".
async function postPublic(path, payload, fallbackError) {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const err = new Error(extractErrorMessage(body, fallbackError));
    err.status = res.status;
    err.code = body?.code;
    throw err;
  }
  return res;
}

// ── Two-step sign-in, the step after the password ─────────────────────────
// Public like the password links: no session exists yet, only the 5-minute
// mfa_token login() returned. A thrown error with err.code 'mfa_expired'
// means that token ran out: back to the password.

// The 6-digit code from the app, or a recovery code. Signs in. With
// `remember`, this browser isn't asked for `email`'s code for REMEMBER_DAYS;
// without it, anything remembered for that email here is dropped.
export async function verifyLoginCode(mfaToken, code, { email, remember = false } = {}) {
  const res = await postPublic(
    '/auth/login/verify',
    { mfa_token: mfaToken, code, remember_device: remember },
    'Could not check the code. Please try again.'
  );
  const data = await res.json();
  if (email) writeRemembered(rememberKeyFor(email), remember ? data.remember_token : null);
  setSession(data.access_token, data.role);
  return data;
}

// A role that must use two-step sign-in, setting it up at sign-in:
// -> { secret, otpauth_uri } for the QR code.
export async function startLoginMfaSetup(mfaToken) {
  const res = await postPublic(
    '/auth/login/setup',
    { mfa_token: mfaToken },
    'Could not start setting up two-step sign-in. Please try again.'
  );
  return res.json();
}

// Its first code turns it on and signs in: -> { recovery_codes, access_token, ... }.
// The session starts now; the page shows the recovery codes before going on.
export async function confirmLoginMfaSetup(mfaToken, code) {
  const res = await postPublic(
    '/auth/login/setup/confirm',
    { mfa_token: mfaToken, code },
    'Could not check the code. Please try again.'
  );
  const data = await res.json();
  setSession(data.access_token, data.role);
  return data;
}

// Resolves to the server's "we've sent a link" message. Throws with
// err.status 404 when no account uses the email (err.message is the server's
// sentence saying so), 422 when it isn't an email at all, 429 after too many
// requests.
export async function requestPasswordReset(email) {
  const res = await postPublic(
    '/auth/forgot-password',
    { email },
    'Could not send the reset link. Please try again.'
  );
  const body = await res.json().catch(() => null);
  return body?.detail || `We've sent a link to ${email} to set a new password.`;
}

// { email_enabled, detail }: whether "Forgot password?" can email a link at
// all. The live server has no email set up; then `detail` says to ask an admin.
export async function getPasswordResetInfo() {
  const res = await fetch(`${API_URL}/auth/forgot-password`);
  if (!res.ok) throw new Error('Could not check how to reset a password.');
  return res.json();
}

// { purpose: 'invite' | 'reset', email, full_name, expires_at }
export async function getLinkInfo(token) {
  const res = await postPublic(
    '/auth/link-info',
    { token },
    'This link has expired or has already been used.'
  );
  return res.json();
}

export async function setPasswordWithLink(token, password) {
  await postPublic(
    '/auth/set-password',
    { token, password },
    'Could not set your password. Please try again.'
  );
}

export function logout() {
  // Fired before clearSession() so it still carries this session's token;
  // keepalive lets it finish while the page navigates to /login.
  apiFetch('/auth/logout', { method: 'POST', keepalive: true }).catch(() => {});
  clearSession();
}

// Tells the backend the signed-in user is still here, which is what a
// session's length on the Audit Log page is measured from. Beats every
// minute and when the tab becomes visible again; a hidden tab stays quiet,
// and after 30 idle minutes the backend closes the session. Returns the
// cleanup for a useEffect.
const HEARTBEAT_INTERVAL_MS = 60 * 1000;

export function startSessionHeartbeat() {
  const beat = () => {
    if (document.visibilityState !== 'visible' || !isAuthenticated()) return;
    apiFetch('/auth/heartbeat', { method: 'POST' }).catch(() => {});
  };
  beat();
  const timer = setInterval(beat, HEARTBEAT_INTERVAL_MS);
  document.addEventListener('visibilitychange', beat);
  return () => {
    clearInterval(timer);
    document.removeEventListener('visibilitychange', beat);
  };
}

// Merges Authorization: Bearer <token> into whatever headers the caller
// already wants, for use by every other API module in this app.
export function authHeaders(extraHeaders = {}) {
  const token = getToken();
  return token
    ? { ...extraHeaders, Authorization: `Bearer ${token}` }
    : extraHeaders;
}

// Fired when the backend refuses a request for a missing permission, so
// PermissionsProvider reloads /auth/me: an admin may just have changed this
// person's access (Yuan's permissions proposal).
export const PERMISSION_DENIED_EVENT = 'dsd:permission-denied';

// The proposal's 403 body is {"detail": "<a sentence>", "code":
// "missing_permission", "permission": key}. Every api/*.js wrapper already
// shows `detail` as its error text, so the response passes through as it is;
// this only tells PermissionsProvider, going by `code` (never by detail).
function notifyPermissionDenied(permission) {
  window.dispatchEvent(new CustomEvent(PERMISSION_DENIED_EVENT, { detail: { permission } }));
}

// Thin fetch wrapper so future API calls don't each have to remember
// authHeaders() themselves. Story #91: checks expiry *before* firing the
// request — no point round-tripping to the API with a token that's already
// stale — and redirects to /login in both the pre-check and the 401 cases
// (401 also covers e.g. the server clock disagreeing with the client's).
export async function apiFetch(path, options = {}) {
  const token = getToken();
  if (token && isTokenExpired(token)) {
    clearSession();
    redirectToLogin();
    throw new Error('Session expired. Please log in again.');
  }

  // Dev mock only (api/mocks/permissionsMock.js): refuse what the backend
  // will refuse, so the 403 path can be tried before the backend has it.
  if (import.meta.env.DEV && MOCK_PERMISSIONS) {
    const missing = mockDeniedPermission(options.method, path, getCurrentUser()?.role);
    if (missing) {
      notifyPermissionDenied(missing);
      return new Response(
        JSON.stringify({ detail: "You don't have access to this. Ask an admin.", code: 'missing_permission', permission: missing }),
        { status: 403, headers: { 'Content-Type': 'application/json' } },
      );
    }
  }

  // Preview mode rides on every read as X-Data-Mode (src/dataMode.js), so
  // no api/*.js wrapper has to remember it.
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: authHeaders({
      'Content-Type': 'application/json',
      ...dataModeHeaders(options.method),
      ...options.headers,
    }),
  });
  if (res.status === 401) {
    clearSession();
    redirectToLogin();
  }
  if (res.status === 403) {
    const body = await res.clone().json().catch(() => null);
    if (body?.code === 'missing_permission') notifyPermissionDenied(body.permission);
  }
  return res;
}
