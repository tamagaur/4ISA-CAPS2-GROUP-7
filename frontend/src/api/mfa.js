// frontend/src/api/mfa.js — the signed-in person's own two-step sign-in
// (backend/routers/two_factor.py). Signing in with it is in auth.js
// (verifyLoginCode and the setup-at-sign-in pair).
import { apiFetch } from '../auth';

async function call(path, options, fallback) {
  const res = await apiFetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    const err = new Error(typeof detail === 'string' ? detail : fallback);
    err.status = res.status;
    err.code = body?.code;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

const post = (path, payload, fallback) =>
  call(path, { method: 'POST', body: payload ? JSON.stringify(payload) : undefined }, fallback);

// { available, enabled, required, required_roles, recovery_codes_left }.
// available is false until the server has migration 0035 and its key.
export const getMfaStatus = () => call('/auth/mfa', {}, 'Could not load two-step sign-in.');

// Raised on window, with the status as `detail`, whenever the Account
// security dialog loads one, so the sidebar's line and the My profile
// page follow a change made from either place.
export const MFA_STATUS_EVENT = 'san2:mfa-status';

// -> { secret, otpauth_uri } for the QR code.
export const startMfaSetup = () => post('/auth/mfa/setup', null, 'Could not start the setup.');

// The first code from the app turns it on -> { recovery_codes }.
export const confirmMfaSetup = (code) =>
  post('/auth/mfa/confirm', { code }, 'Could not check the code.');

// A current code -> { recovery_codes }; the old ones stop working.
export const replaceRecoveryCodes = (code) =>
  post('/auth/mfa/recovery-codes', { code }, 'Could not make new recovery codes.');

export const disableMfa = (code) =>
  post('/auth/mfa/disable', { code }, 'Could not turn off two-step sign-in.');
