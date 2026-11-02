# SSM Decision Support Dashboard (DSD) — Data governance

Status: draft v1, 2026-11-02. Evidence for each control is a file in this repo (checked 2026-11-02) or marked
**UNVERIFIED** (lives in Supabase, Render, Vercel or on a laptop and must be confirmed there). Nothing here is a
legal opinion; the Data Privacy Act of 2012 (RA 10173) points are for the team and adviser to confirm.

## 1. Roles (placeholders, to be filled)

| Role | Meaning | Named person |
|---|---|---|
| Data owner (business data) | Decides who may see and use SSM's sales, stock and cost data | `[TBD — SSM contact]` |
| Data steward | Keeps the data correct and labelled: loads, fixes, pinned figures | `[TBD — Yuan proposed]` |
| Data custodian | Runs the systems: database, hosting, backups, keys | `[TBD]` |
| Privacy contact | Receives privacy questions and breach reports for user accounts | `[TBD]` |
| Adviser | Technical sign-off | Sir Catubag |

## 2. Data inventory and classification

| Data | Class | Location | Personal data? |
|---|---|---|---|
| User accounts: name, email, password hash, MFA secret, recovery-code hashes, avatar path | Restricted | `app.users`, `app.user_mfa`, Supabase Storage | **Yes** |
| Sessions, sign-in tokens, invite and reset tokens | Restricted | `app.user_session`, `app.auth_token` | Indirectly |
| Audit trail | Restricted, integrity-critical | `app.audit_log` | Yes (actor email) |
| SSM sales, stock, prices, costs, supplier ceilings | Confidential | `public`, `mart` | Not by design; outlet fields **UNVERIFIED** |
| Forecasts, ABC classes, LP plan and decisions | Confidential | `public`, `mart`, `lp_*` | No |
| Demonstration data (`is_demo = true`, `demo` schema) | Internal, labelled synthetic | `demo` | No |
| Live-database backups | Same as the data they copy | `backups/` (git-ignored), 91 folders | Yes |
| Per-product sales extracts | Confidential | `local/` (git-ignored; hard rule 9) | No |

## 3. Controls: what the repo shows

| Area | Control seen | Evidence |
|---|---|---|
| Password storage | bcrypt hashes; a constant-time dummy check on sign-in | `backend/auth_utils.py:29`, `:55` |
| Session tokens | JWT, HS256, expiry from `JWT_EXPIRY_HOURS`, default 8 | `backend/auth_utils.py:31`, `:32`, `:39` |
| Sign-in brute force | 5 failures per email and 20 per IP per 15 min, then a 15-minute lockout, logged | `backend/login_limiter.py:38-41` |
| Two-step sign-in | Authenticator secret encrypted with a Fernet key (`MFA_ENCRYPTION_KEY`); recovery codes stored as sha256 only | `backend/mfa.py:23-25`, `:149` |
| Transport to database | `sslmode=require` | `backend/deps.py:71` |
| Access control | Role presets plus per-user permission boxes; admin-only keys (`lp.decide`) cannot be granted to staff | `backend/permissions.py:96`, `:204` |
| Approval workflow | Staff quantity changes and dismissals are held for an admin; every decision is recorded | `backend/routers/reorder_approval.py`, `reorder_requests.py` |
| Audit trail | Written by the server in the same transaction as the change; the browser cannot post entries; no code path updates or deletes audit rows | `backend/audit.py`, grep of `backend/ analytics/ scripts/` |
| Audit table privileges | `anon`, `authenticated` and `service_role` privileges revoked | `0048_app_schema.sql:180` |
| Row-level security | Enabled on `auth_token`, `etl_load_event`, `etl_coverage`, `user_permission_override`; full coverage **UNVERIFIED** | migrations 0031, 0033, 0034 |
| Input safety | NUL and NaN/Infinity refused before the database; validation errors and request bodies are never logged (test enforces it) | `backend/input_guard.py`, `tests/backend/test_secret_redaction.py` |
| API docs hidden in production | `/docs`, `/redoc`, `/openapi.json` off when `APP_ENV=production` | `backend/main.py:85` |
| CORS | Allow-list of origins | `backend/main.py:98` |
| Frontend headers | Content-Security-Policy (`script-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, Referrer-Policy, Permissions-Policy, and HSTS (added 2026-11-02) | `frontend/vercel.json` |
| API headers | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, HSTS in production, `Cache-Control: no-store` on `/auth`, `/users`, `/admin`, `/audit-log` (added 2026-11-02, G2) | `backend/security_headers.py`, `tests/backend/test_security_headers.py` |
| Audit immutability | Database triggers refuse UPDATE, DELETE and TRUNCATE on `app.audit_log` (G3). **Applied to live 2026-11-02**; UPDATE, DELETE and TRUNCATE each confirmed refused (rolled back), 120 rows unchanged | `analytics/db/migrations/0072_audit_log_append_only.sql` |
| Secrets in git | `.env`, `local/` and `backups/` are git-ignored | `.gitignore:6`, `:99`, `:132` |
| Change control | Numbered migrations only; applied ones never edited; no force pushes or history rewrites; read-only access uses a transaction-scoped READ ONLY | CLAUDE.md, DATABASE rule |
| Data integrity | Models read only `_Real` views; demo data is labelled and kept apart; 51 pinned figures and 12 cross-endpoint invariants run in `scripts/check.sh --fast` | CLAUDE.md rules 1-3; check run 2026-11-02 |
| Destructive scripts | Dry run by default and approval flags (`clean_dead_skus.py`, `apply_real_recovery_to_public.py --restore`) | CLAUDE.md, 2026-10-21 |

## 4. Gaps and what closes them

| # | Gap | Risk | Fix | Who |
|---|---|---|---|---|
| G1 | The sign-in token is kept in `localStorage` (`frontend/src/auth.js:89`) | Any script injected into the page can read it | **Accepted for now.** The Vercel CSP already limits scripts to the app's own origin. A cookie would be cross-site between `*.vercel.app` and `*.onrender.com`, and browsers restrict those. The proper fix is a Vercel rewrite that proxies `/api/*` to Render, then an httpOnly cookie. Only if SSM or the panel needs it | Maika / Audrey |
| G2 | ~~The API set no security headers of its own~~ | — | **Done 2026-11-02** (`backend/security_headers.py`, 7 tests). Takes effect when this branch is deployed to Render | Backend |
| G3 | Audit rows are append-only by convention and by revoked grants | A superuser or a bad script could still alter them | **Done and applied 2026-11-02:** migration 0072. A retention purge must disable the trigger deliberately (see the migration header) | Yuan |
| G4 | 91 local backup folders hold real data on a laptop; disk encryption **UNVERIFIED** | Laptop loss exposes SSM data and user hashes | Turn on BitLocker; list who holds copies; delete backups past the retention period in section 5 | Custodian |
| G5 | No retention or disposal schedule exists | Data and backups kept indefinitely | Adopt section 5 and confirm with SSM | Data owner |
| G6 | No privacy notice, breach procedure or named privacy contact | RA 10173 expectations unmet | Section 6 is the draft; fill the placeholders | Team |
| G7 | No access-review cadence | Stale admin or staff accounts | Quarterly: list users, roles, permission boxes and direct-apply grants; remove what is not needed. The audit log supports this | Data owner |
| G8 | `JWT_SECRET_KEY` and `MFA_ENCRYPTION_KEY` have no recorded rotation or minimum length | A weak or old key outlives its use | Set a minimum length check at startup; write a rotation step (rotating the MFA key needs re-encryption) | Backend |
| G9 | Row-level security not confirmed on every table that holds user or audit data | Direct database access could bypass the API | Run a read-only check of `pg_class.relrowsecurity` per table | Yuan |
| G10 | Branch protection is not enforced on GitHub (private repo, free plan) | A direct push to an integration branch | Keep the pull-request convention; revisit if the plan changes | Team |
| G11 | Agreements with Supabase, Render, Vercel and the email provider, and their data regions, not recorded | Unknown transfer of personal data abroad | Record the plan, region and DPA status of each in section 7 | Custodian |
| G12 | Whether SSM's sales listing or outlet fields identify individuals is unknown | Personal data may be in the business tables | Check the raw outlet and invoice fields; if so, classify and minimise | Yuan |

## 5. Retention and disposal (proposal, needs the data owner's approval)

| Data | Keep | Then |
|---|---|---|
| Active user accounts | While the person has access | Disable on leaving; delete personal fields after 12 months, keep the audit entry with the user id |
| Sessions, invite and reset tokens | Until expiry | Prune expired rows |
| Audit trail | 3 years `[TBD with SSM]` | Archive, then delete |
| Live-database backups | The 3 most recent, plus one per month for 6 months `[TBD]` | Delete older, from disk and any copies |
| Demonstration data | Until the capstone is archived | Drop the `demo` schema |
| SSM business data | Per SSM's own records policy `[TBD]` | Hand back or delete when the engagement ends |

## 6. Privacy and incident handling (draft)

1. **Collect only what is needed**: name, work email, role. No government IDs, no phone numbers.
2. **Notice**: tell each user at account creation what is held, why, who can see it, and how long. `[TBD: wording and link]`
3. **Rights**: a user may ask what is held, correct it, or ask for deletion. Route to the privacy contact `[TBD]`.
4. **Breach**: anyone who suspects exposure reports to the custodian and privacy contact at once. Contain first: rotate `JWT_SECRET_KEY` (signs everyone out), reset affected passwords, revoke sessions. Record what, when, who, what data. Under RA 10173 and National Privacy Commission rules, a breach of personal data that creates real risk is reported to the Commission and affected people within 72 hours of knowledge; **confirm the current rule with the adviser or SSM's counsel**.
5. **Keys**: if `MFA_ENCRYPTION_KEY` is lost, authenticator secrets cannot be read and users must re-enrol (the code already refuses to enable MFA without it).

## 7. Third parties to record

| Service | Holds | Plan and region | Agreement |
|---|---|---|---|
| Supabase (Postgres, Storage) | All data | **UNVERIFIED** | **UNVERIFIED** |
| Render (backend) | In-memory data, logs, environment secrets | **UNVERIFIED** | **UNVERIFIED** |
| Vercel (frontend) | Static app, no stored data | **UNVERIFIED** | **UNVERIFIED** |
| Email provider (invites, resets) | Recipient address, message body | **UNVERIFIED** | **UNVERIFIED** |
| GitHub (private repo) | Code, no data by rule 9 | Private | — |

## 8. Platform checklist (tick in the dashboards; none of these could be checked from the repo)

Any group member who has access to that dashboard can do these; it does not have to be one person. Write your initials and the date in the last column, and note any value you changed. Never paste a secret into this file.

| Where | Setting | Why | Done by / date |
|---|---|---|---|
| Render | `APP_ENV=production` | Turns on HSTS and hides `/docs`, `/redoc`, `/openapi.json` | `[ ]` |
| Render | `CORS_ALLOWED_ORIGINS` = the Vercel production URL only (no localhost) | The default allows localhost | `[ ]` |
| Render | `FRONTEND_URL` = the Vercel URL | Invite and reset links; the app builds none without it in production | `[ ]` |
| Render | `JWT_SECRET_KEY` a long random string (32+ characters), different from local | Signs every session; the example file holds a placeholder | `[ ]` |
| Render | `MFA_ENCRYPTION_KEY` set and backed up apart from the database, before `MFA_ENABLED=true` | Without it authenticator secrets cannot be read | `[ ]` |
| Render | Secrets set as environment variables in the dashboard, not in the repo | `.env` is git-ignored but a render.yaml would not be | `[ ]` |
| Vercel | `VITE_API_URL` = the Render URL (https) | Build-time; the CSP allows any https connection | `[ ]` |
| Vercel | Production deploys from `Main-Final` or `Main-FE` only, preview deploys without production secrets | Previews are public URLs | `[ ]` |
| Supabase | Backups: plan, retention, and whether point-in-time recovery is on | Section 5 | `[ ]` |
| Supabase | Network restrictions and SSL enforcement on | The code already requires SSL | `[ ]` |
| Supabase | Region, and who holds dashboard access with MFA on their own accounts | Section 7 | `[ ]` |
| Supabase | Service-role and database passwords rotated when a person leaves | Access review (G7) | `[ ]` |
| GitHub | Repo stays private; 2FA on every member | Branch protection is not available on the free plan | `[ ]` |

## 9. Review

Revisit this file each quarter, and whenever a new data source, a new role, or a new third party is added. Record
the date and the reviewer here: `[TBD]`.
