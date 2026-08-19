// frontend/src/auth.js — token storage + authenticated fetch helper
// (Story #89: login; Story #91: session expiry).
//
// The JWT is kept in localStorage (not a cookie) because the backend is a
// separate origin in dev (Vite on :5173, FastAPI on :8000) and this app has
// no server-side rendering step that would benefit from httpOnly cookies.
// Tradeoff: localStorage is readable by any JS on the page, so it's only as
// safe as this app's exposure to XSS — acceptable for an internal staff
// tool, worth revisiting if the dashboard ever embeds third-party scripts.

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
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

function redirectToLogin() {
  if (typeof window !== 'undefined') {
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

export async function login(email, password) {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(extractErrorMessage(body, 'Login failed. Check your email and password.'));
  }

  const data = await res.json();
  setSession(data.access_token, data.role);
  return data;
}

export function logout() {
  clearSession();
}

// Merges Authorization: Bearer <token> into whatever headers the caller
// already wants, for use by every other API module in this app.
export function authHeaders(extraHeaders = {}) {
  const token = getToken();
  return token
    ? { ...extraHeaders, Authorization: `Bearer ${token}` }
    : extraHeaders;
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

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: authHeaders({ 'Content-Type': 'application/json', ...options.headers }),
  });
  if (res.status === 401) {
    clearSession();
    redirectToLogin();
  }
  return res;
}
