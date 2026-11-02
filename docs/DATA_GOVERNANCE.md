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
| SSM sales, stock, prices, costs, supplier ceilings | Confidential | `public`, `mart` | No |
| Customer and outlet names: `customer_dimension.customer_name` (2,841 distinct), `salesreturn_fact.customer_name` (180), and the raw sheets' Customer Name, Outlet Name and Account Name columns | Confidential, **personal data in part** | `public`, `data/raw/`, `backups/` | **Yes, in part.** Free-text store names; many are a person's name (a sole proprietor's store named for them). A script cannot say how many |
| Salesman names: `salesman_dimension.salesman_name` (33 distinct), the raw Salesman column | Restricted | `public`, `data/raw/`, `backups/` | **Yes: 30 of the 33 are individuals' names**; 3 are labels (`ENCODER`, `OFFICE SALES`, a route code beginning `DSP7-`) |
| Rejected source rows: `etl_quarantine.raw_values` (8,224 rows; about 5,900 carry a raw customer or salesman name) | Restricted | `public`, `backups/` | **Yes, the same names as the two rows above**, held again as the file had them |
| Invoice numbers: `invoice_num` on `sales_fact` (59,699 distinct), `salesreturn_fact` (5,287), `purchase_fact` (2,148) | Confidential | `public`, `data/raw/` | **No.** Document numbers with prefixes such as `GEN`, `INV`, `DMP`, `BILL`; none has a phone or email shape |
| Forecasts, ABC classes, LP plan and decisions | Confidential | `public`, `mart`, `lp_*` | No |
| Demonstration data (`is_demo = true`, `demo` schema) | Internal, labelled synthetic | `demo` | No |
| Live-database backups | Same as the data they copy | `backups/` (git-ignored), 74 folders | Yes |
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
| G4 | **Open.** Local backup folders hold real data on a laptop (74 folders on 2026-11-02; this file said 91); disk encryption **UNVERIFIED** | Laptop loss exposes SSM data and user hashes | Turn on BitLocker; list who holds copies; delete the folders the table below marks DELETE (58 folders, 653.81 MB). **The table is evidence only: nothing has been deleted; the deletion is Kelvin's to run after reading it** | Custodian |
| G5 | ~~No retention or disposal schedule exists~~ | — | **Done 2026-11-02:** section 5 filled and adopted by the team. SSM has not confirmed it, and the data owner has not acknowledged the role | Team |
| G6 | ~~No privacy notice, breach procedure or named privacy contact~~ | — | **Done 2026-11-02:** notice wording written, Kelvin Yuan Guillermo named as privacy contact, no placeholder left in section 6. The 72-hour rule still needs confirming with the adviser or SSM's counsel | Team |
| G7 | ~~No access-review cadence~~ | — | **Done 2026-11-02: the policy, and the first review run the same day (evidence below; 2 accounts flagged to confirm, none removed).** Reviewed quarterly and on three events: a member leaving, any role change, and before handover to SSM. Method: list users, roles, permission boxes and direct-apply grants; remove what is not needed; keep the evidence from the audit log | Data steward |
| G8 | ~~`JWT_SECRET_KEY` and `MFA_ENCRYPTION_KEY` have no recorded rotation or minimum length~~ | — | **Done 2026-11-02:** startup checks in `backend/startup_checks.py` (4 tests in `tests/backend/test_startup_checks.py`) and the rotation policy in section 6 point 5. Takes effect when this branch is deployed to Render; the local `.env` still starts (checked) | Backend |
| G9 | Row-level security not confirmed on every table that holds user or audit data | Direct database access could bypass the API | Run a read-only check of `pg_class.relrowsecurity` per table | Yuan |
| G10 | Branch protection is not enforced on GitHub (private repo, free plan) | A direct push to an integration branch | Keep the pull-request convention; revisit if the plan changes | Team |
| G11 | Agreements with Supabase, Render, Vercel and the email provider, and their data regions, not recorded | Unknown transfer of personal data abroad | Record the plan, region and DPA status of each in section 7 | Custodian |
| G12 | **Answered 2026-11-02: yes, personal data is present; kept open for minimisation.** Customer and outlet names (2,841 in `customer_dimension`, 180 in `salesreturn_fact`) are free-text store names, many a person's name; 30 of the 33 salesman values are individuals' names (the other 3 are labels). `etl_quarantine.raw_values` holds the same names again, as the files had them (about 5,900 of its 8,224 rows). Invoice numbers are document numbers (prefixes `GEN`, `INV`, `DMP`, `BILL`), not people. **No phone, address, contact, email or TIN field exists**: not in any `public`, `mart` or `lp_*` table (a column-name scan), and not in the header rows of any of the 567 `.xlsx` files in `data/raw/` (the first 8 rows of every sheet; headers seen: Salesman, Customer Name, Outlet Name, Account Name, plus province, city and municipality names, which are places, not street addresses). The cells were then read too (2026-11-02): the customer, outlet, account, invoice and salesman columns of all 567 `.xlsx` files, about 2.3 million cells, hold **0 phone-shaped and 0 email-shaped values**; so do the same columns in `public` and `etl_quarantine`. 2,436 raw cells contain a street-style word (`st.`, `brgy`, `purok` and the like): the ones sampled are store names beginning `ST.`, but they were not read one by one, so a street address among them is not ruled out. The one `.xls` (the Unilever La Union file) has no customer column; its header names a person in its Current User field (`JOL***** G*****`), and it has 0 phone or email shapes. Masked examples: `*SUSAN E***** & B********`, `JEM'S C******`, `R***** M********`, `J*** J*** M*****` (a salesman) | Names of private people and of SSM's staff sit in the database, in the raw files and in every backup. **No backend route and no frontend file reads these columns** (searched `backend/` and `frontend/src/`), so the dashboard does not display them | Classify as in section 2 (done). Keep the columns out of any export, extract or report. Remove them at handover and delete the backup copies (section 10). Consider replacing salesman names with codes if a name is ever needed in a screen | Data steward |
| G13 | **Open.** No handover procedure to SSM | Student accounts, keys and backup copies stay with the team after the project | Section 10 lists what transfers, what is rotated, what is removed and what is deleted | Team, then SSM |

### G7 evidence: first access review (2026-11-02)

Run read-only against the live database (transaction-scoped READ ONLY) on 2026-11-02. Queries were run by Claude Code at
Kelvin Yuan Guillermo's request; **reviewer of record: Kelvin Yuan Guillermo (data steward)**, who decides every removal.
**Nothing was removed.** Emails are masked here. Sources: `app.users`, `app.user_permission_override`, `app.user_session`,
`app.audit_log`.

Method (G7): list users, roles, permission boxes and direct-apply grants; remove what is not needed; evidence from the audit log.
Result: **5 accounts, all `admin`. 0 permission-box overrides and 0 direct-apply grants exist** (an admin always has every
permission and overrides do not apply to one, `backend/permissions.py:14`).

| id | Name | Email | Role | Created | Boxes / direct-apply | Sign-ins (last) | Audit entries | Still needed? | Flag |
|---|---|---|---|---|---|---|---|---|---|
| 3 | Mikhaella Audrey Bugayong | mi\*\*\*\*@gmail.com | admin | 2026-08-19 | none | 134 (2026-11-02) | 101 | Yes: the most active account, a team member | None |
| 11 | Kelvin Yuan Guillermo | ky\*\*\*\*@gmail.com | admin | 2026-10-16 | none | none recorded | 0 | Yes: data steward and privacy contact | No sign-in is recorded for this account in `app.user_session` |
| 12 | Jamaica Valdez | va\*\*\*\*@gmail.com | admin | 2026-10-16 | none | 21 (2026-11-02) | 2 | **Unconfirmed**: the name is not in the team list in `CLAUDE.md`, but the account signs in today | **Confirm who this is before the next review** |
| 14 | Mikhaella Audrey Bugayong | ta\*\*\*\*@gmail.com | admin | 2026-10-16 | none | none recorded | 4 (as staff, then admin) | **Unconfirmed**: same full name as account 3, different email | **Candidate for removal if it duplicates account 3** |
| 15 | Thea Faith Cabrera | tf\*\*\*\*@gmail.com | admin | 2026-10-18 | none | 17 (2026-11-02) | 1 | Yes: a team member | None |

Findings:
- **All five accounts are `admin`.** Role is the only access control in use. Where a person does not need user management, audit-log access or `lp.decide`, a `staff` role would do. Whether each person needs admin is for Kelvin to say.
- Two accounts share a full name (ids 3 and 14).
- Sign-in history exists for accounts 4 and 5 (3 sessions from 2026-08-24, and 2 on 2026-09-28) but those accounts no longer exist, so nothing needs removing for them.
- The audit log also holds entries for `guillermo@gmail.com` (staff, 3 entries, 2026-08/09), `nobody_probe@example.com` (a probe, 2026-09-30) and `system:etl_loader`: none has an account today.
- Not checked: whether two-step sign-in is on for each account.

### G4 evidence: the backup folders against the section 5 rule (corrected 2026-11-02)

Listed from `backups/`, read-only. **Nothing has been deleted. The deletion is Kelvin's to run after reading this table.**

The rule (section 5): keep the 3 most recent **database backups**, plus the latest database backup of each of the 6 calendar
months 2026-06 to 2026-11, plus any folder an applied migration cites as a rollback point (kept regardless, hard rule 8).
A **database backup** is a non-empty folder written before a change that holds table dumps of the live database; its name
starts with `full_backup_`, `live_backup_`, `tables_`, `mart_backup_`, `dm_fixes_`, `synth_v2_cutover_`, `pm_cleanup_` or
`real_recovery_` (the `real_recovery_rehearsal_` folders dump the same tables). An empty folder or an `INCOMPLETE_` one is
not a backup. Anything else is a table export, a staging copy, a code patch or a loose file: the rule does not delete it, and it is marked LEAVE.
The date is the timestamp in the name; three folders have none and use their file date. Months with no database backup
(2026-06, -07, -08) keep nothing.

| | Items | Size (MB) |
|---|---|---|
| In `backups/` | 74 folders + 18 loose files | 720.55 |
| **KEEP** | 7 | 36.06 |
| **DELETE** | 58 | **653.81 (reclaimable)** |
| **LEAVE** (not database backups; do not delete in this pass) | 9 folders + 18 loose files | 30.69 |

What the correction changed: the earlier list picked `lp_rerun_2026-09-30` as September's keeper because it was the latest
folder by date. It is not a database backup: it holds a CSV and a parquet export of one table, `lp_recommendation`. The
September keeper is now `pm_cleanup_20260928T174927Z`.

**To act on this table:** delete every DELETE row, keep every KEEP row, do not touch a LEAVE row. Nothing else is needed. For information: `full_backup_` folders hold the whole database; the `tables_` and pre-apply folders hold only the tables they were about to change, so after the deletion **one complete full backup remains** (`full_backup_20261102T114428Z`).

**Counts.** `backups/` holds 74 folders and 18 loose files; the "91 folders" this file gave earlier does not match the directory and its source is unresolved. **Empty folders: 4** (an earlier note said 5; a fifth is not on disk; each has no file at any depth): `tables_20261020T174555Z`, `full_backup_20261007T170842Z`, `real_recovery_rehearsal_20260923T010538Z`, `real_recovery_rehearsal_20260923T005531Z`. **Cited as a rollback point by an applied migration: 3**, all KEEP: `live_backup_20260914T151217Z` (0014), `live_backup_20260916T190021Z` (0016), `tables_20261021T175535Z` (0064). No loose file is cited.

| # | Date | Folder or file | Size (MB) | What it is | Action | Why |
|---|---|---|---|---|---|---|
| 1 | 2026-11-02 | `full_backup_20261102T114428Z` | 19.09 | database backup | **KEEP** | 3 most recent; latest database backup of 2026-11 |
| 2 | 2026-10-24 | `tables_20261024T110607Z` | 0.14 | database backup | **KEEP** | 3 most recent; latest database backup of 2026-10 |
| 3 | 2026-10-24 | `tables_20261024T082629Z` | 0.13 | database backup | **KEEP** | 3 most recent |
| 4 | 2026-10-24 | `tables_20261024T075057Z` | 0.07 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 5 | 2026-10-23 | `tables_20261023T133928Z` | 0.06 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 6 | 2026-10-22 | `tables_20261022T142441Z` | 0.05 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 7 | 2026-10-22 | `tables_20261022T120255Z` | 0.11 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 8 | 2026-10-21 | `tables_20261021T175535Z` | 0.01 | database backup | **KEEP** | cited by applied migration 0064 (rule 8, kept regardless) |
| 9 | 2026-10-21 | `tables_20261021T171309Z` | 0.01 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 10 | 2026-10-21 | `tables_20261021T171239Z` | 1.37 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 11 | 2026-10-20 | `tables_20261020T174604Z` | 0.03 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 12 | 2026-10-20 | `tables_20261020T174555Z` | 0.00 | empty folder (no files) | **DELETE** | contains no files |
| 13 | 2026-10-20 | `tables_20261020T171149Z` | 17.65 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 14 | 2026-10-20 | `tables_20261020T163159Z` | 0.13 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 15 | 2026-10-20 | `tables_20261020T163154Z` | 0.46 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 16 | 2026-10-20 | `tables_20261020T135337Z` | 1.15 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 17 | 2026-10-20 | `tables_20261020T135322Z` | 17.57 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 18 | 2026-10-20 | `tables_20261020T135315Z` | 0.95 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 19 | 2026-10-20 | `tables_20261020T132130Z` | 0.03 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 20 | 2026-10-20 | `tables_20261020T112333Z` | 0.01 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 21 | 2026-10-19 | `tables_20261019T131316Z` | 0.48 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 22 | 2026-10-19 | `tables_20261019T100004Z` | 0.47 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 23 | 2026-10-19 | `tables_20261019T095959Z` | 0.39 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 24 | 2026-10-19 | `tables_20261019T090053Z` | 0.01 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 25 | 2026-10-19 | `tables_20261019T090050Z` | 0.01 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 26 | 2026-10-19 | `tables_20261019T073443Z` | 0.02 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 27 | 2026-10-19 | `tables_20261019T073423Z` | 44.98 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 28 | 2026-10-16 | `full_backup_20261016T070624Z` | 11.99 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 29 | 2026-10-16 | `full_backup_20261016T054130Z` | 11.88 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 30 | 2026-10-07 | `full_backup_20261007T171126Z` | 1.14 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 31 | 2026-10-07 | `full_backup_20261007T170842Z` | 0.00 | empty folder (no files) | **DELETE** | contains no files |
| 32 | 2026-10-07 | `INCOMPLETE_full_backup_20261007T151146Z_ssl_drop` | 1.14 | incomplete backup (SSL dropped mid-run) | **DELETE** | an incomplete backup is not a restore point |
| 33 | 2026-10-07 | `pre_0045_20261007` | 0.11 | not a database backup (table export, staging copy or code patch) | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 34 | 2026-10-05 | `mart_backup_before_0046_20261005T080301Z` | 3.06 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 35 | 2026-10-05 | `full_backup_20261005T061733Z` | 10.63 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 36 | 2026-10-04 | `full_backup_20261004T143933Z` | 10.57 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 37 | 2026-10-04 | `full_backup_20261004T134329Z` | 13.55 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 38 | 2026-10-04 | `live_backup_20261004T134035Z` | 7.50 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 39 | 2026-10-04 | `full_backup_20261004T133536Z` | 10.56 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 40 | 2026-10-03 | `full_backup_20261003T095403Z` | 7.44 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 41 | 2026-10-03 | `full_backup_20261003T080251Z` | 7.41 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 42 | 2026-10-03 | `segmentation_2026-02_pre_recompute_20261003T063026Z` | 0.16 | not a database backup (table export, staging copy or code patch) | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 43 | 2026-10-02 | `full_backup_20261002T160122Z` | 13.62 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 44 | 2026-09-30 | `lp_rerun_2026-09-30` | 0.05 | not a database backup (table export, staging copy or code patch) | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 45 | 2026-09-30 | `session5_wip2_untracked` | 0.39 | not a database backup (table export, staging copy or code patch) | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 46 | 2026-09-30 | `session5_wip_untracked` | 0.39 | not a database backup (table export, staging copy or code patch) | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 47 | 2026-09-28 | `pm_cleanup_20260928T174927Z` | 1.20 | database backup | **KEEP** | latest database backup of 2026-09 |
| 48 | 2026-09-28 | `pm_cleanup_rehearsal_20260928T174501Z` | 1.21 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 49 | 2026-09-28 | `synth_v2_cutover_20260928T151525Z` | 32.74 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 50 | 2026-09-28 | `synth_v2_cutover_rehearsal_20260928T144105Z` | 32.77 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 51 | 2026-09-28 | `dm_fixes_20260928T114435Z` | 58.10 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 52 | 2026-09-28 | `dm_fixes_rehearsal_20260928T114328Z` | 58.12 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 53 | 2026-09-23 | `real_recovery_20260923T022354Z` | 25.06 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 54 | 2026-09-23 | `real_recovery_rehearsal_20260923T022020Z` | 25.06 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 55 | 2026-09-23 | `real_recovery_rehearsal_20260923T021638Z` | 24.67 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 56 | 2026-09-23 | `real_recovery_rehearsal_20260923T020250Z` | 24.96 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 57 | 2026-09-23 | `real_recovery_rehearsal_20260923T015811Z` | 24.96 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 58 | 2026-09-23 | `real_recovery_rehearsal_20260923T011419Z` | 24.65 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 59 | 2026-09-23 | `real_recovery_rehearsal_20260923T011046Z` | 24.65 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 60 | 2026-09-23 | `real_recovery_rehearsal_20260923T010538Z` | 0.00 | empty folder (no files) | **DELETE** | contains no files |
| 61 | 2026-09-23 | `real_recovery_rehearsal_20260923T005531Z` | 0.00 | empty folder (no files) | **DELETE** | contains no files |
| 62 | 2026-09-22 | `real_recovery_rehearsal_20260922T150147Z` | 24.96 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 63 | 2026-09-22 | `real_recovery_rehearsal_20260922T144257Z` | 24.96 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 64 | 2026-09-22 | `real_recovery_rehearsal_20260922T132429Z` | 24.95 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 65 | 2026-09-21 | `staging_v2_sales_return_superseded_20260921T152509Z` | 0.41 | not a database backup (table export, staging copy or code patch) | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 66 | 2026-09-21 | `staging_real_region_fix_20260921T152230Z` | 0.03 | not a database backup (table export, staging copy or code patch) | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 67 | 2026-09-21 | `staging_v2a_superseded_20260921T142457Z` | 9.68 | not a database backup (table export, staging copy or code patch) | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 68 | 2026-09-21 | `staging_v1_20260921T140003Z` | 17.40 | not a database backup (table export, staging copy or code patch) | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 69 | 2026-09-17 | `live_backup_20260917T093732Z` | 6.37 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 70 | 2026-09-17 | `live_backup_20260917T093208Z` | 6.37 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 71 | 2026-09-16 | `live_backup_20260916T190021Z` | 6.37 | database backup | **KEEP** | cited by applied migration 0016 (rule 8, kept regardless) |
| 72 | 2026-09-16 | `live_backup_20260916T185950Z` | 6.37 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 73 | 2026-09-16 | `live_backup_20260916T185626Z` | 6.37 | database backup | **DELETE** | older than the 3 most recent, not the latest of its month, not cited by a migration |
| 74 | 2026-09-14 | `live_backup_20260914T151217Z` | 9.12 | database backup | **KEEP** | cited by applied migration 0014 (rule 8, kept regardless) |
| 75 | 2026-10-20 | `RESTORE_freeze_2026-10-20.sql` | 0.00 | loose file: restore script for the 2026-10-20 freeze | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 76 | 2026-10-04 | `claude_md_local_before_root_20261004.md` | 0.01 | loose file: copy of the old local CLAUDE.md before it moved to the repo root | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 77 | 2026-09-21 | `delmonte_abc_held.patch` | 0.01 | loose file: held Del Monte ABC code patch | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 78 | 2026-09-21 | `forecast_result_pre_router_20260921T100759Z.csv` | 0.16 | loose file: Forecast_Result rows before the 2026-09-21 router change (data); holds SSM data | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 79 | 2026-09-29 | `pm_cleanup_baseline_public_20260928T174908Z.json` | 0.03 | loose file: baseline counts for the 2026-09-28 product-master cleanup; row counts only | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 80 | 2026-10-08 | `pre_0047_viewdef_20261007T172944Z.sql` | 0.00 | loose file: view definitions saved before migration 0047 | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 81 | 2026-10-20 | `pre_0061_viewdef_20261020T1355Z.sql` | 0.00 | loose file: view definitions saved before migration 0061 | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 82 | 2026-10-02 | `product_dimension_backup_20260918.csv` | 1.45 | loose file: product_dimension rows, 2026-09-18 (data); holds SSM data | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 83 | 2026-09-21 | `rollback_forecast_result_20260921T100759Z.py` | 0.00 | loose file: rollback script for the forecast-result CSV above | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 84 | 2026-09-30 | `session5_build_preview_outputs_3way.py` | 0.01 | loose file: scratch script from session 5 | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 85 | 2026-09-30 | `session5_wip.patch` | 0.17 | loose file: session 5 work-in-progress patch | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 86 | 2026-09-30 | `session5_wip2.patch` | 0.18 | loose file: session 5 work-in-progress patch, second | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 87 | 2026-09-30 | `session5_wip2_filelist.txt` | 0.00 | loose file: file list for the second session 5 patch | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 88 | 2026-09-30 | `session5_wip2_untracked.sha256` | 0.00 | loose file: checksums for the second session 5 untracked copy | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 89 | 2026-09-30 | `session5_wip_filelist.txt` | 0.00 | loose file: file list for the first session 5 patch | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 90 | 2026-09-30 | `session5_wip_untracked.sha256` | 0.00 | loose file: checksums for the first session 5 untracked copy | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 91 | 2026-09-20 | `sku_traits_pre_0022_20260920T151450Z.csv` | 0.02 | loose file: SKU traits before migration 0022 (data); holds SSM data | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |
| 92 | 2026-09-28 | `synth_v2_cutover_baseline_public_20260928T151324Z.json` | 0.02 | loose file: baseline counts for the 2026-09-28 synthetic-v2 cutover; row counts only | **LEAVE** | not a database backup, so the rule does not delete it; not cited by a migration |

Copies on other laptops or drives are not counted here. Disk encryption (BitLocker) is **UNVERIFIED**.

## 5. Retention and disposal (adopted by the team 2026-11-02; SSM has not confirmed it)

| Data | Keep | Then |
|---|---|---|
| Active user accounts | While the person has access | Disable on leaving; delete personal fields after 12 months, keep the audit entry with the user id |
| Sessions, invite and reset tokens | Until expiry | Prune expired rows |
| Audit trail | 3 years. Basis: covers at least two complete annual planning cycles plus a margin, and matches the longest sales history the system holds | Archive, then delete |
| Live-database backups | The 3 most recent database backups, plus the latest **database backup** (not the latest folder) of each of the last 6 calendar months, plus any folder an applied migration cites as a rollback point (hard rule 8) | Delete older, from disk and any copies. The current list is under G4 |
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
Last reviewed: 2026-11-02, reviewer of record Kelvin Yuan Guillermo. Next review due by 2027-02-02 (three months), or sooner on any of the
three events in G7.

Gap state on 2026-11-02: **done** G2, G3, G5, G6, G7, G8 (G5, G6 and G7 are the team's own adoption, not confirmed by
SSM). **Open:** G1 (accepted for now), G4 (the corrected table is attached, nothing deleted), G9, G10, G11, G12 (answered: personal data is present; minimisation left), G13. G7's first review was run 2026-11-02.
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

