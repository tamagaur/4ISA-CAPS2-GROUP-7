# Two-step sign-in (authenticator app): 2026-10-02

Branch `feat/2fa`. After the password, sign-in asks for the 6-digit code from Google Authenticator or Microsoft Authenticator (the TOTP standard).

**Nothing in the warehouse is touched:** sales, inventory, ABC, forecasts and the LP are unchanged. The only database change is one new table, `user_mfa` (migration 0035).

## What people see

| Where | What |
|---|---|
| **Sidebar → your name ("Account security")** | Turn it on: scan a QR code (or type the key), then enter one code. You get 10 one-time recovery codes, shown once, to copy or download. Once on, you can make new recovery codes or turn it off. Both need a current code. |
| **Sign-in** | Password, then the 6-digit code. "Lost your phone? Use a recovery code" takes a recovery code instead. |
| **Sign-in, for a role that requires it** | If the account hasn't set it up yet, it's done right there (QR → code → recovery codes) before the dashboard opens. |
| **User Management** | A **Two-step** column: On, Off, or Setup due (the role requires it and the person hasn't set it up). An admin can **reset** someone else's: for a lost phone *and* lost recovery codes. It signs them out and is written to the Audit Log. |

## Turning it on: order of steps

1. **Merge and deploy the code.** This is safe before the migration: until `user_mfa` exists, sign-in is password-only exactly as now, and Account security says it isn't available yet.
2. **Make an encryption key**, once:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - Put it in Render as `MFA_ENCRYPTION_KEY`, and in your local `.env`.
   - Keep it safe and never change it. A new key makes every set-up authenticator stop working, and those people would need an admin reset.
3. **Apply migration 0035 on its own.** Don't use `run_canonical_load.py --schema-only`: that would also apply Kelvin's pending 0032/0033.
   - `python scripts/apply_migration_0035.py`: check only (read-only).
   - `python scripts/apply_migration_0035.py --apply`: creates the table and its `schema_migrations` row in one transaction, with before/after checks.
   - Add `--port 5432` if 6543 times out.
4. **Each admin turns it on for themselves** under Account security.
5. **Optional: make it required.** Set `MFA_REQUIRED_ROLES` on Render to `admin` (or `admin,staff`), and restart the service.
   - Do this only after step 4, so at least one admin already has it set up.
   - Unset means optional for everyone.

## How it is protected

- **Wrong codes count toward the existing sign-in lock** (5 per email or 20 per network address in 15 minutes → locked for 15 minutes).
  - The email's count is cleared only when the whole sign-in succeeds. If a right password cleared it, someone who knew the password could guess codes forever, 4 at a time.
- **A code works once.** The last used 30-second step is stored. A phone clock about 30 s off still works.
- **Between password and code**, the browser holds only a 5-minute token. It is signed with a different key from the sign-in token, so it can't open any page.
- **Stored data:**
  - The authenticator secret is encrypted (`MFA_ENCRYPTION_KEY`, Fernet).
  - Recovery codes are kept as sha256 hashes only, and a used one is removed.
  - The table has row-level security on and no API grants, like every table since the 2026-09-28 lock-down.
- **If the key is missing on the server:**
  - Nobody can set it up.
  - An account that already has it gets 503 instead of skipping the code.
  - A required role is not enforced, so one missing setting can't lock every admin out. The server logs a warning.
- **A required role can't turn it off.** An admin can reset it, and the person then sets it up again at their next sign-in.
- **The Audit Log records:**
  - Two-Step Sign-In On / Off / Reset
  - Recovery Codes Replaced
  - Recovery Code Used (with how many are left)
  - Sign-in Locked

## API

| Route | Who | Does |
|---|---|---|
| `POST /auth/login` | public | Unchanged for accounts without it. With it: `{mfa_step: "verify" \| "setup", mfa_token}` instead of a token |
| `POST /auth/login/verify` | public (mfa_token) | App or recovery code → sign-in token |
| `POST /auth/login/setup`, `/setup/confirm` | public (mfa_token) | Set up at sign-in → recovery codes + sign-in token |
| `GET /auth/mfa` | sign-in | `{available, enabled, required, required_roles, recovery_codes_left}` |
| `POST /auth/mfa/setup`, `/confirm`, `/recovery-codes`, `/disable` | sign-in | Your own |
| `POST /users/{id}/mfa/reset` | users.manage | Someone else's (not your own) |

`GET /users` rows gain `mfa_enabled`.

No new Python package is needed: the codes use the standard library, and Fernet comes with `python-jose[cryptography]`. The frontend adds `qrcode.react` 4.2.0 (no dependencies of its own).

## Checks

- **Tests:** `tests/backend/test_mfa.py` has 33 tests.
  - The code maths against RFC 6238's own test vectors, and clock drift.
  - Lockout, including "a right password doesn't reset the wrong-code count".
  - One-time use, recovery codes, the pending token not opening pages.
  - Required roles with and without the key, your own on/off/new codes, the admin reset, and "before 0035 nothing changes".
  - Full suite: 951 passed, 8 skipped.
- **Browser walkthrough** (fake in-memory database, headless Chrome), every step passed:
  - Turn on from Account security.
  - Wrong code, then right code.
  - Recovery-code sign-in.
  - A required role setting it up at sign-in.
  - The admin reset changing the row to "Setup due".
- **The SQL array expressions** were checked read-only against Postgres. `user_mfa` does not exist on the live database yet.

## Undo

1. Run the commented rollback at the end of `0035_user_two_factor.sql`.
2. Run `DELETE FROM schema_migrations WHERE filename = '0035_user_two_factor.sql'`.
3. Restart the backend.

Everyone is back to password-only sign-in.
