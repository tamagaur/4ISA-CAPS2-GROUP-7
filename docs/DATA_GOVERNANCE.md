# SSM Decision Support Dashboard (DSD) — Data governance

Status: draft v1, 2026-11-02. Evidence for each control is a file in this repo (checked 2026-11-02) or marked
**UNVERIFIED** (lives in Supabase, Render, Vercel or on a laptop and must be confirmed there). Nothing here is a
legal opinion; the Data Privacy Act of 2012 (RA 10173) points are for the team and adviser to confirm.

## 1. Roles (until handover to SSM; section 10 says who replaces these names)

These are the team's own assignments, made 2026-11-02. Every role is held only until handover to SSM.

| Role | Meaning | Named person | Until |
|---|---|---|---|
| Data owner (SSM business data) | Decides who may see and use SSM's sales, stock and cost data | Sir Abe. **Has not acknowledged this role** | Handover to SSM |
| Data steward | Keeps the data correct and labelled: loads, fixes, pinned figures | Kelvin Yuan Guillermo | Handover to SSM |
| Data custodian | Runs the systems: database, hosting, backups, keys | Maika (holds Render, Vercel and Supabase access) | Handover to SSM |
| Privacy contact | Receives privacy questions and breach reports for user accounts | Kelvin Yuan Guillermo | Handover to SSM |

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
| Startup secret checks | The API refuses to start if `JWT_SECRET_KEY` is under 32 characters when `APP_ENV=production`, or if `MFA_ENCRYPTION_KEY` is set (or `MFA_ENABLED=true`) and is not a valid Fernet key. Neither fires in local development with the variable unset (G8, 2026-11-02) | `backend/startup_checks.py`, `tests/backend/test_startup_checks.py` |
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
| G4 | **Open.** Local backup folders hold real data on a laptop (74 folders on 2026-11-02; this file said 91, see the list below); disk encryption **UNVERIFIED** | Laptop loss exposes SSM data and user hashes | Turn on BitLocker; list who holds copies; delete the backups the list below marks "yes" (70 folders, 699.07 MB). **The list is evidence only: nothing has been deleted; the deletion is Kelvin's to run after reading it** | Custodian |
| G5 | ~~No retention or disposal schedule exists~~ | — | **Done 2026-11-02:** section 5 filled and adopted by the team. SSM has not confirmed it, and the data owner has not acknowledged the role | Team |
| G6 | ~~No privacy notice, breach procedure or named privacy contact~~ | — | **Done 2026-11-02:** notice wording written, Kelvin Yuan Guillermo named as privacy contact, no placeholder left in section 6. The 72-hour rule still needs confirming with the adviser or SSM's counsel | Team |
| G7 | ~~No access-review cadence~~ | — | **Done 2026-11-02 (as a policy; no review has been run yet).** Reviewed quarterly and on three events: a member leaving, any role change, and before handover to SSM. Method: list users, roles, permission boxes and direct-apply grants; remove what is not needed; keep the evidence from the audit log | Data steward |
| G8 | ~~`JWT_SECRET_KEY` and `MFA_ENCRYPTION_KEY` have no recorded rotation or minimum length~~ | — | **Done 2026-11-02:** startup checks in `backend/startup_checks.py` (4 tests in `tests/backend/test_startup_checks.py`) and the rotation policy in section 6 point 5. Takes effect when this branch is deployed to Render; the local `.env` still starts (checked) | Backend |
| G9 | Row-level security not confirmed on every table that holds user or audit data | Direct database access could bypass the API | Run a read-only check of `pg_class.relrowsecurity` per table | Yuan |
| G10 | Branch protection is not enforced on GitHub (private repo, free plan) | A direct push to an integration branch | Keep the pull-request convention; revisit if the plan changes | Team |
| G11 | Agreements with Supabase, Render, Vercel and the email provider, and their data regions, not recorded | Unknown transfer of personal data abroad | Record the plan, region and DPA status of each in section 7 | Custodian |
| G12 | Whether SSM's sales listing or outlet fields identify individuals is unknown | Personal data may be in the business tables | Check the raw outlet and invoice fields; if so, classify and minimise | Yuan |
| G13 | **Open.** No handover procedure to SSM | Student accounts, keys and backup copies stay with the team after the project | Section 10 lists what transfers, what is rotated, what is removed and what is deleted | Team, then SSM |

### G4 evidence: backup folders against the section 5 rule (2026-11-02)

Listed from `backups/`, read-only. **Nothing has been deleted.** The deletion is Kelvin's to run after reading this.
Rule applied (section 5): keep the 3 most recent, plus the latest folder of each of the 6 calendar months 2026-06 to
2026-11. Months with no folder (2026-06, -07, -08) keep nothing. Where a folder name has no timestamp
(`lp_rerun_2026-09-30`, `session5_wip_untracked`, `session5_wip2_untracked`) its file date is used. Sizes are the bytes
on disk, not compressed. Totals: 74 folders, 718.48 MB; 4 inside the rule (19.4 MB), **70 outside, 699.07 MB that would
be freed**.

Things to read before deleting:
- The count is **74 folders, not the 91** this file said earlier. `backups/` also holds 18 loose files (SQL, CSV, patches, JSON), which this list does not cover and the rule does not name. Where the 91 came from is unresolved.
- The September keeper (`lp_rerun_2026-09-30`) is an LP-rerun scratch folder, not a database backup, because the rule picks by date. The latest September database backup is `pm_cleanup_20260928T174927Z`.
- Five folders are empty or near-empty (0 bytes): `full_backup_20261007T170842Z`, `tables_20261020T174555Z` and three `real_recovery_rehearsal_` folders from 2026-09-23.
- Several are the only copy of a restore point cited in migrations or in `STATE.md` (for example `pre_0045_20261007`, the `real_recovery_` and `synth_v2_cutover_` folders). Whether any of them is still needed for a rollback is for Kelvin to decide, not this list.
- Copies on other laptops or drives are not counted.

| # | Date | Folder | Size (MB) | Against the rule | Delete? |
|---|---|---|---|---|---|
| 1 | 2026-11-02 | `full_backup_20261102T114428Z` | 19.09 | inside: 3 most recent; latest of 2026-11 | no |
| 2 | 2026-10-24 | `tables_20261024T110607Z` | 0.14 | inside: 3 most recent; latest of 2026-10 | no |
| 3 | 2026-10-24 | `tables_20261024T082629Z` | 0.13 | inside: 3 most recent | no |
| 4 | 2026-10-24 | `tables_20261024T075057Z` | 0.07 | outside: older than the 3 most recent and not the latest of its month | yes |
| 5 | 2026-10-23 | `tables_20261023T133928Z` | 0.06 | outside: older than the 3 most recent and not the latest of its month | yes |
| 6 | 2026-10-22 | `tables_20261022T142441Z` | 0.05 | outside: older than the 3 most recent and not the latest of its month | yes |
| 7 | 2026-10-22 | `tables_20261022T120255Z` | 0.11 | outside: older than the 3 most recent and not the latest of its month | yes |
| 8 | 2026-10-21 | `tables_20261021T175535Z` | 0.01 | outside: older than the 3 most recent and not the latest of its month | yes |
| 9 | 2026-10-21 | `tables_20261021T171309Z` | 0.01 | outside: older than the 3 most recent and not the latest of its month | yes |
| 10 | 2026-10-21 | `tables_20261021T171239Z` | 1.37 | outside: older than the 3 most recent and not the latest of its month | yes |
| 11 | 2026-10-20 | `tables_20261020T174604Z` | 0.03 | outside: older than the 3 most recent and not the latest of its month | yes |
| 12 | 2026-10-20 | `tables_20261020T174555Z` | 0.00 | outside: older than the 3 most recent and not the latest of its month | yes |
| 13 | 2026-10-20 | `tables_20261020T171149Z` | 17.65 | outside: older than the 3 most recent and not the latest of its month | yes |
| 14 | 2026-10-20 | `tables_20261020T163159Z` | 0.13 | outside: older than the 3 most recent and not the latest of its month | yes |
| 15 | 2026-10-20 | `tables_20261020T163154Z` | 0.46 | outside: older than the 3 most recent and not the latest of its month | yes |
| 16 | 2026-10-20 | `tables_20261020T135337Z` | 1.15 | outside: older than the 3 most recent and not the latest of its month | yes |
| 17 | 2026-10-20 | `tables_20261020T135322Z` | 17.57 | outside: older than the 3 most recent and not the latest of its month | yes |
| 18 | 2026-10-20 | `tables_20261020T135315Z` | 0.95 | outside: older than the 3 most recent and not the latest of its month | yes |
| 19 | 2026-10-20 | `tables_20261020T132130Z` | 0.03 | outside: older than the 3 most recent and not the latest of its month | yes |
| 20 | 2026-10-20 | `tables_20261020T112333Z` | 0.01 | outside: older than the 3 most recent and not the latest of its month | yes |
| 21 | 2026-10-19 | `tables_20261019T131316Z` | 0.48 | outside: older than the 3 most recent and not the latest of its month | yes |
| 22 | 2026-10-19 | `tables_20261019T100004Z` | 0.47 | outside: older than the 3 most recent and not the latest of its month | yes |
| 23 | 2026-10-19 | `tables_20261019T095959Z` | 0.39 | outside: older than the 3 most recent and not the latest of its month | yes |
| 24 | 2026-10-19 | `tables_20261019T090053Z` | 0.01 | outside: older than the 3 most recent and not the latest of its month | yes |
| 25 | 2026-10-19 | `tables_20261019T090050Z` | 0.01 | outside: older than the 3 most recent and not the latest of its month | yes |
| 26 | 2026-10-19 | `tables_20261019T073443Z` | 0.02 | outside: older than the 3 most recent and not the latest of its month | yes |
| 27 | 2026-10-19 | `tables_20261019T073423Z` | 44.98 | outside: older than the 3 most recent and not the latest of its month | yes |
| 28 | 2026-10-16 | `full_backup_20261016T070624Z` | 11.99 | outside: older than the 3 most recent and not the latest of its month | yes |
| 29 | 2026-10-16 | `full_backup_20261016T054130Z` | 11.88 | outside: older than the 3 most recent and not the latest of its month | yes |
| 30 | 2026-10-07 | `full_backup_20261007T171126Z` | 1.14 | outside: older than the 3 most recent and not the latest of its month | yes |
| 31 | 2026-10-07 | `full_backup_20261007T170842Z` | 0.00 | outside: older than the 3 most recent and not the latest of its month | yes |
| 32 | 2026-10-07 | `INCOMPLETE_full_backup_20261007T151146Z_ssl_drop` | 1.14 | outside: older than the 3 most recent and not the latest of its month | yes |
| 33 | 2026-10-07 | `pre_0045_20261007` | 0.11 | outside: older than the 3 most recent and not the latest of its month | yes |
| 34 | 2026-10-05 | `mart_backup_before_0046_20261005T080301Z` | 3.06 | outside: older than the 3 most recent and not the latest of its month | yes |
| 35 | 2026-10-05 | `full_backup_20261005T061733Z` | 10.63 | outside: older than the 3 most recent and not the latest of its month | yes |
| 36 | 2026-10-04 | `full_backup_20261004T143933Z` | 10.57 | outside: older than the 3 most recent and not the latest of its month | yes |
| 37 | 2026-10-04 | `full_backup_20261004T134329Z` | 13.55 | outside: older than the 3 most recent and not the latest of its month | yes |
| 38 | 2026-10-04 | `live_backup_20261004T134035Z` | 7.50 | outside: older than the 3 most recent and not the latest of its month | yes |
| 39 | 2026-10-04 | `full_backup_20261004T133536Z` | 10.56 | outside: older than the 3 most recent and not the latest of its month | yes |
| 40 | 2026-10-03 | `full_backup_20261003T095403Z` | 7.44 | outside: older than the 3 most recent and not the latest of its month | yes |
| 41 | 2026-10-03 | `full_backup_20261003T080251Z` | 7.41 | outside: older than the 3 most recent and not the latest of its month | yes |
| 42 | 2026-10-03 | `segmentation_2026-02_pre_recompute_20261003T063026Z` | 0.16 | outside: older than the 3 most recent and not the latest of its month | yes |
| 43 | 2026-10-02 | `full_backup_20261002T160122Z` | 13.62 | outside: older than the 3 most recent and not the latest of its month | yes |
| 44 | 2026-09-30 | `lp_rerun_2026-09-30` | 0.05 | inside: latest of 2026-09 | no |
| 45 | 2026-09-30 | `session5_wip2_untracked` | 0.39 | outside: older than the 3 most recent and not the latest of its month | yes |
| 46 | 2026-09-30 | `session5_wip_untracked` | 0.39 | outside: older than the 3 most recent and not the latest of its month | yes |
| 47 | 2026-09-28 | `pm_cleanup_20260928T174927Z` | 1.20 | outside: older than the 3 most recent and not the latest of its month | yes |
| 48 | 2026-09-28 | `pm_cleanup_rehearsal_20260928T174501Z` | 1.21 | outside: older than the 3 most recent and not the latest of its month | yes |
| 49 | 2026-09-28 | `synth_v2_cutover_20260928T151525Z` | 32.74 | outside: older than the 3 most recent and not the latest of its month | yes |
| 50 | 2026-09-28 | `synth_v2_cutover_rehearsal_20260928T144105Z` | 32.77 | outside: older than the 3 most recent and not the latest of its month | yes |
| 51 | 2026-09-28 | `dm_fixes_20260928T114435Z` | 58.10 | outside: older than the 3 most recent and not the latest of its month | yes |
| 52 | 2026-09-28 | `dm_fixes_rehearsal_20260928T114328Z` | 58.12 | outside: older than the 3 most recent and not the latest of its month | yes |
| 53 | 2026-09-23 | `real_recovery_20260923T022354Z` | 25.06 | outside: older than the 3 most recent and not the latest of its month | yes |
| 54 | 2026-09-23 | `real_recovery_rehearsal_20260923T022020Z` | 25.06 | outside: older than the 3 most recent and not the latest of its month | yes |
| 55 | 2026-09-23 | `real_recovery_rehearsal_20260923T021638Z` | 24.67 | outside: older than the 3 most recent and not the latest of its month | yes |
| 56 | 2026-09-23 | `real_recovery_rehearsal_20260923T020250Z` | 24.96 | outside: older than the 3 most recent and not the latest of its month | yes |
| 57 | 2026-09-23 | `real_recovery_rehearsal_20260923T015811Z` | 24.96 | outside: older than the 3 most recent and not the latest of its month | yes |
| 58 | 2026-09-23 | `real_recovery_rehearsal_20260923T011419Z` | 24.65 | outside: older than the 3 most recent and not the latest of its month | yes |
| 59 | 2026-09-23 | `real_recovery_rehearsal_20260923T011046Z` | 24.65 | outside: older than the 3 most recent and not the latest of its month | yes |
| 60 | 2026-09-23 | `real_recovery_rehearsal_20260923T010538Z` | 0.00 | outside: older than the 3 most recent and not the latest of its month | yes |
| 61 | 2026-09-23 | `real_recovery_rehearsal_20260923T005531Z` | 0.00 | outside: older than the 3 most recent and not the latest of its month | yes |
| 62 | 2026-09-22 | `real_recovery_rehearsal_20260922T150147Z` | 24.96 | outside: older than the 3 most recent and not the latest of its month | yes |
| 63 | 2026-09-22 | `real_recovery_rehearsal_20260922T144257Z` | 24.96 | outside: older than the 3 most recent and not the latest of its month | yes |
| 64 | 2026-09-22 | `real_recovery_rehearsal_20260922T132429Z` | 24.95 | outside: older than the 3 most recent and not the latest of its month | yes |
| 65 | 2026-09-21 | `staging_v2_sales_return_superseded_20260921T152509Z` | 0.41 | outside: older than the 3 most recent and not the latest of its month | yes |
| 66 | 2026-09-21 | `staging_real_region_fix_20260921T152230Z` | 0.03 | outside: older than the 3 most recent and not the latest of its month | yes |
| 67 | 2026-09-21 | `staging_v2a_superseded_20260921T142457Z` | 9.68 | outside: older than the 3 most recent and not the latest of its month | yes |
| 68 | 2026-09-21 | `staging_v1_20260921T140003Z` | 17.40 | outside: older than the 3 most recent and not the latest of its month | yes |
| 69 | 2026-09-17 | `live_backup_20260917T093732Z` | 6.37 | outside: older than the 3 most recent and not the latest of its month | yes |
| 70 | 2026-09-17 | `live_backup_20260917T093208Z` | 6.37 | outside: older than the 3 most recent and not the latest of its month | yes |
| 71 | 2026-09-16 | `live_backup_20260916T190021Z` | 6.37 | outside: older than the 3 most recent and not the latest of its month | yes |
| 72 | 2026-09-16 | `live_backup_20260916T185950Z` | 6.37 | outside: older than the 3 most recent and not the latest of its month | yes |
| 73 | 2026-09-16 | `live_backup_20260916T185626Z` | 6.37 | outside: older than the 3 most recent and not the latest of its month | yes |
| 74 | 2026-09-14 | `live_backup_20260914T151217Z` | 9.12 | outside: older than the 3 most recent and not the latest of its month | yes |

## 5. Retention and disposal (adopted by the team 2026-11-02; SSM has not confirmed it)

| Data | Keep | Then |
|---|---|---|
| Active user accounts | While the person has access | Disable on leaving; delete personal fields after 12 months, keep the audit entry with the user id |
| Sessions, invite and reset tokens | Until expiry | Prune expired rows |
| Audit trail | 3 years. Basis: covers at least two complete annual planning cycles plus a margin, and matches the longest sales history the system holds | Archive, then delete |
| Live-database backups | The 3 most recent, plus one per month for 6 months | Delete older, from disk and any copies. The current list is under G4 |
| Demonstration data | Until the capstone is archived | Drop the `demo` schema |
| SSM business data | Held only for the duration of the capstone; returned or deleted at project close; deleted on SSM's request at any time | Delete from the database, `backups/`, `local/` and every copy; confirm person by person (section 10) |

## 6. Privacy and incident handling (draft)

1. **Collect only what is needed**: name, work email, role. No government IDs, no phone numbers.
2. **Notice**: tell each user at account creation what is held, why, who can see it, and how long. Wording: "This system stores your name, work email and role so you can sign in and so your actions can be recorded in the audit log. Your decisions on reorder recommendations are recorded with your name and the time. Only administrators and you can see your account details. Data is held for the duration of the project. Questions or corrections: Kelvin Yuan Guillermo."
3. **Rights**: a user may ask what is held, correct it, or ask for deletion. Route to the privacy contact, Kelvin Yuan Guillermo.
4. **Breach**: anyone who suspects exposure reports to the custodian (Maika) and the privacy contact (Kelvin Yuan Guillermo) at once. Contain first: rotate `JWT_SECRET_KEY` (signs everyone out), reset affected passwords, revoke sessions. Record what, when, who, what data. Under RA 10173 and National Privacy Commission rules, a breach of personal data that creates real risk is reported to the Commission and affected people within 72 hours of knowledge; **confirm the current rule with the adviser or SSM's counsel**.
5. **Keys and rotation**: if `MFA_ENCRYPTION_KEY` is lost, authenticator secrets cannot be read and users must re-enrol (the code already refuses to enable MFA without it). At startup the API refuses to run in production with a `JWT_SECRET_KEY` under 32 characters, and refuses a `MFA_ENCRYPTION_KEY` that is not a valid Fernet key (G8). Rotation: `JWT_SECRET_KEY` on suspected exposure and at handover to SSM (everyone signs in again). `MFA_ENCRYPTION_KEY` **only on exposure**, because rotating it means re-encrypting every stored authenticator secret, and the fallback is that all users re-enrol.

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
| Render | `JWT_SECRET_KEY` a long random string (32+ characters), different from local | Signs every session; the example file holds a placeholder. With `APP_ENV=production` the API now refuses to start under 32 characters | `[ ]` |
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

Revisit this file each quarter, and whenever a new data source, a new role, or a new third party is added.
Last reviewed: 2026-11-02 by Kelvin Yuan Guillermo. Next review due by 2027-02-02 (three months), or sooner on any of the
three events in G7.

Gap state on 2026-11-02: **done** G2, G3, G5, G6, G7, G8 (G5, G6 and G7 are the team's own adoption, not confirmed by
SSM). **Open:** G1 (accepted for now), G4 (the backup list is attached, nothing deleted), G9, G10, G11, G12, G13.
This file records the team's decisions; it does not show that anyone outside the team has agreed to them.

## 10. Handover to SSM (gap G13, open)

Every role in section 1 ends at handover. Nothing below has been done; it is the list.

| Step | What | Who confirms |
|---|---|---|
| Transfers or is rebuilt | The Supabase project, the Render service and the Vercel project: either ownership moves to SSM or SSM rebuilds them from the repo. Choose one per service | Custodian and SSM |
| Rotated | Both secret keys: `JWT_SECRET_KEY` (everyone signs in again) and `MFA_ENCRYPTION_KEY` (every stored authenticator secret is re-encrypted, or all users re-enrol; section 6 point 5). Handover is a deliberate rotation, unlike the usual "only on exposure" rule for the MFA key | Custodian |
| Removed | Every student account on the live system, and the team's access to Supabase, Render, Vercel and GitHub | Data steward, from the audit log |
| Deleted, confirmed person by person | The `backups/` folders, `local/`, and any other copy of SSM data on a laptop, drive or cloud folder. Each member states in writing that theirs is deleted | Each member, collected by the privacy contact |
| SSM fills | SSM's own data owner, data custodian and privacy contact, replacing the names in section 1; the access review (G7) is run once before handover | SSM |

