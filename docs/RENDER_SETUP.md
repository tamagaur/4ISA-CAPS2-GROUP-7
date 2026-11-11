# Render setup: a new web service for the SSM DSD backend

Written 2026-11-06 from the repo at `ead658a` (branch `kelvin-be`) and from probes of the live service. Nothing here was run
against Render's dashboard (no access); anything that needs the dashboard is marked **DASHBOARD**. No secret values appear in this file.

## 1. What is deployed now (`https://fourisa-caps2-group-7.onrender.com`, probed 2026-11-06)

`logincred.onrender.com` is the old service in STATE.md and is not the one the frontend uses; it was not probed here.

| Probe (no sign-in) | Answer |
|---|---|
| `GET /health` | 200 |
| `GET /docs`, `GET /openapi.json` | 200 (so `APP_ENV` is **not** `production` on that service: production hides both pages and turns on HSTS) |
| `GET /batch/status` | **404** (a service running `6b7197e` answers 401) |
| `GET /dashboard`, `/auth/me`, `/forecast/x`, `/demo/series` | 401 (mounted, need a token) |
| `GET /auth/login` | 405 (exists, POST only) |

Route table: `/openapi.json` of the deployed service lists **84** method+path pairs. The same listing from this repo
(`app.openapi()` at `ead658a`) lists **95**. The deployed set is a strict subset: nothing is deployed that the repo lacks.
The 11 missing routes are all of `/batch/*`: `GET /batch/checklist`, `/batch/feedback`, `/batch/job`, `/batch/status`;
`POST /batch/close`, `/batch/files`, `/batch/practice-month`, `/batch/rollback`, `/batch/run`, `/batch/signoff`, `/batch/validate`.

What that says: the running build is older than `36f0b90` (2026-11-06, "Load a month and roll any loaded month back"), the commit that made
`monthly_batch.router` always mounted. Before it (`git show 36f0b90^:backend/main.py`, line 158, and at `7b91936`, line 151) the router was mounted only
when `MONTHLY_BATCH_ENABLED` is true and the database is the local throwaway server, which a Render service never is. So 84 is also exactly the
figure pinned in `docs/CHAPTER4_CODE_FIGURES.json` on 2026-11-04. **What the probe cannot tell**: which commit between `4f12e24`/`7b91936`
and `36f0b90^` it is. Every one of them has 84 routes. The `/health` and `/openapi.json` bodies carry no commit id. **DASHBOARD**: the service's
Events/Deploys tab shows the commit. STATE.md says `thea-dashboardedits` (now `6b7197e`) was pushed to `team` for Render to deploy; it did not
deploy that, or this service is not watching that branch.

## 2. Service settings

| Setting | Value | Why |
|---|---|---|
| Type | Web Service | |
| Repo | `https://github.com/tamagaur/4ISA-CAPS2-GROUP-7` (public; no GitHub login needed to connect it, a Render GitHub link is still the simplest) | |
| Branch | `thea-dashboardedits` (it is at `6b7197e`, contains everything in `kelvin-be` today). `kelvin-be` on `team` is still at `36f0b90`, missing the top-bar commit | The branch the group chose to deploy (STATE.md) |
| Region | Any. Supabase is `aws-0-ap-south-1` (Mumbai); Singapore is the nearest Render region and keeps the database round trips short (the app is round-trip bound, STATE/speed notes). Choosing it is a judgement, not a repo fact | |
| Root Directory | **leave empty (repository root)** | The backend imports `analytics/`, `config/`, `scripts/` and starts `scripts.*` as subprocesses from the repo root (`backend/routers/monthly_batch.py` runs `python -m scripts...` with `cwd=REPO`). A root of `backend/` would break all of that. The frontend is in `frontend/` and is deployed on Vercel, not here; with the root empty Render ignores it because the build only installs Python |
| Runtime | Python 3 | |
| Python version | `.python-version` at the repo root (tracked) says `3.13`. Render reads that file. If the build rejects it, set env var `PYTHON_VERSION` to a full version such as `3.13.5`. UNVERIFIED against Render: **DASHBOARD** shows the build log | `requirements.txt` pins (numpy 2.1.3, xgboost 3.4.1, fastapi 0.141.1) were installed on 3.13 locally |
| Build command | `pip install -r requirements.txt` | Heavy (pandas, statsmodels, xgboost, scipy, pulp): expect a slow first build. The API itself needs fewer, but the month load needs all of them, so do not trim |
| Start command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` | `README.md:33` runs it with `python -m uvicorn`; Render supplies `$PORT`. One worker: the login limiter and response cache are in-process |
| Health check path | `/health` (returns `{"status":"ok"}`, no auth, does not touch the database; `backend/main.py:175` names Render's health check) | |
| Instance type | The free tier sleeps after idle and cold-starts in about 60 s (64.1 s measured 2026-10-04; 84 s seen 2026-11-05). Login says "the server is waking up" after 4 s. A month load runs forecasting and the LP in subprocesses: **memory needed is not measured anywhere in the repo**, so the free 512 MB instance may not hold it. **DASHBOARD** to decide | |
| Auto-deploy | On commit to the branch (your choice) | |

There is no `render.yaml`, `Procfile` or Dockerfile in the repo, so every setting above is typed into the dashboard by hand.

## 3. Environment variables

Local `.env` holds these keys (names read, values not printed): `SUPABASE_DB_URL`, `SUPABASE_DIRECT_URL`, `SUPABASE_KEY`, `JWT_SECRET_KEY`,
`JWT_ALGORITHM`, `JWT_EXPIRY_HOURS`, `CORS_ALLOWED_ORIGINS`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`. It does **not** hold
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `FRONTEND_URL`, `APP_ENV`, `MFA_*` or `DM_DEMO_ENABLED`: those come from the Supabase dashboard,
or from the existing Render service's Environment tab (**DASHBOARD**).

### Needed to boot and sign in

| Variable | Used for (file) | Where the value comes from |
|---|---|---|
| `SUPABASE_DB_URL` | The only database connection the API reads (`backend/deps.py` and every router). Boot fails if missing/unreachable (`lifespan`, `backend/main.py`) | Local `.env` key `SUPABASE_DB_URL` (transaction pooler, port 6543), or Supabase > Connect > Transaction pooler. **Must be the pooler string** `postgresql://postgres.<ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:6543/postgres`. Not `db.<ref>.supabase.co`: that host is IPv6-only and Render's outbound has no IPv6 (`.env.example` comment) |
| `JWT_SECRET_KEY` | Signs every session token (`backend/deps.py`) | **Generate fresh**: `python -c "import secrets; print(secrets.token_urlsafe(64))"`. With `APP_ENV=production` the server refuses to start under 32 characters (`backend/startup_checks.py`). Different from local. A new value only signs everyone out |
| `CORS_ALLOWED_ORIGINS` | Browsers allowed to call the API (`backend/main.py:57`, comma-separated, exact match). **The name is `CORS_ALLOWED_ORIGINS`. There is no `ALLOWED_ORIGINS` in the code**; a variable of that name is ignored and the API then allows only `localhost:5173` | Set to `https://ssm-dsd.vercel.app` exactly: scheme included, **no trailing slash**, no path. Add other origins after commas if needed (e.g. `,http://localhost:5173` for local testing). STATE.md (2026-11-05) says the Vercel address `ssm-dsd-six.vercel.app` answered DEPLOYMENT_NOT_FOUND; if the frontend lives at another address, use that one |
| `FRONTEND_URL` | Where invite and password-reset links point (`backend/mailer.py`). Unset in production = no link is built | `https://ssm-dsd.vercel.app` (no trailing slash; it is stripped anyway) |
| `APP_ENV` | `production` hides `/docs`, `/redoc`, `/openapi.json`, turns on HSTS, enforces the 32-character JWT rule | `production`. The currently deployed service has docs open, so it is not set there |

### Needed for features, not for boot

| Variable | Used for | Where from |
|---|---|---|
| `SUPABASE_URL` | Builds profile-picture URLs and talks to Storage (`backend/avatar.py`) | `https://dsdxemtmbbmdtccwxzyk.supabase.co` (from `.env.example`; Supabase > Project Settings > API) |
| `SUPABASE_SERVICE_ROLE_KEY` | Uploading avatars (bypasses Storage RLS; the anon key will not work) | Supabase > Project Settings > API > `service_role`. Not in local `.env`. Without it, avatar upload fails with a clear message; nothing else breaks |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Invite and reset emails (`backend/mailer.py`). Unset = the admin gets a copyable link instead | Copy the five same-named keys from local `.env` (Gmail app password) |
| `JWT_ALGORITHM` (`HS256`), `JWT_EXPIRY_HOURS` (`8`) | Token settings; both have code defaults | Copy local values, or leave unset |
| `DM_DEMO_ENABLED` | Serves the labelled synthetic demonstration data behind the top bar's switch (CLAUDE.md rule 2). Off by default | Leave unset unless the group wants it on |
| `MFA_ENABLED`, `MFA_ENCRYPTION_KEY`, `MFA_REQUIRED_ROLES` | Two-step sign-in (`backend/mfa.py`, `backend/startup_checks.py`) | See next section |

Not needed on Render: `SUPABASE_DIRECT_URL` (read only by scripts and backups, never by the API), `SUPABASE_KEY` (nothing in `backend/` reads it),
`MONTHLY_BATCH_ENABLED` and `LOCAL_PG_URL` (local throwaway server only; setting `MONTHLY_BATCH_ENABLED` on Render does nothing because the
URL is not `127.0.0.1:55432`). `RENDER` is set by Render itself and switches on real-client-IP handling (`backend/client_ip.py`); do not set it.

### Fresh, or must match

| Variable | Rule | What breaks |
|---|---|---|
| `JWT_SECRET_KEY` | **Free to generate.** | Nothing stored depends on it. Everyone signs in again |
| `MFA_ENCRYPTION_KEY` | **Must equal the key used when authenticators were set up.** Only free to generate if no one has set up an authenticator, or you accept admin resets | A different key makes every stored authenticator secret unreadable: those people cannot sign in until an admin resets their two-step setup (`.env.example`). It must also parse as a Fernet key whenever it is set or `MFA_ENABLED` is true, or the server refuses to start |
| `MFA_ENABLED` | Two-step sign-in is **paused unless `true`** | If the old service has it `true` and the new one does not, sign-in silently skips the second step |

The repo cannot say which of these the existing service uses, and local `.env` has no `MFA_*` keys. **DASHBOARD**: read them from the existing
service's Environment tab, and copy them verbatim. A read-only check on the database of how many accounts have the second step on can be run by Yuan
(the column is named in migration 0035); that query was not run here.

## 4. Will not work (or works only partly) on Render

The brief expected the rollback points to be under `local/`. **They are not: they are copies inside the database** (a `checkpoint` schema per month,
`scripts/demo_session.py` `take_checkpoint`, about 106 MB each on live; the 2 newest are kept). So rollback survives a Render restart. What lives under `local/`
(git-ignored, so absent from every fresh Render build, and wiped on every deploy and restart because Render's disk is ephemeral):

| Path (under the repo root) | Holds | Consequence on Render |
|---|---|---|
| `local/monthly_batch/uploads` | The raw file a user uploads | Lost on restart; a load started from an upload that then restarts mid-way has no file |
| `local/monthly_batch/validation` | What the last validation of each month found (`/batch/validate`, `/batch/checklist`) | The checklist/sign-off view forgets validations after a restart; re-validate |
| `local/monthly_batch/logs` | Whole output of each job (`/batch/job`) | Job log vanishes after a restart; a restart during a job kills the job (subprocess of the web process) |
| `local/month_rollback_last.json` | Last rollback result | Lost; cosmetic |

Other things that need attention before trusting a load on the new service:

1. **The gate.** On any database but the local throwaway one, load and rollback are refused (409 `batch_not_rehearsed`) unless
   `docs/MONTH_LOAD_REHEARSAL.json` is committed and its hash matches the 9 files in `scripts/demo_rehearsal.FILES`. It is committed and was made for the
   `kelvin-be` code; deploying exactly that code satisfies it, any edit to those 9 files does not.
2. **Routes need the full repo and its subprocess runtime**: loads call `python -m scripts.run_month` and others, with a 120 s step timeout, on whatever instance
   size you pick. Not measured on Render; do not promise it works until one load has been run there. The only rehearsal was on a local restored copy.
3. **Request time.** A load is a background job (`/batch/job`), but Render's free instance also sleeps when idle, killing it.
4. **A load writes to the live database.** Pointing a *second* Render service at the same `SUPABASE_DB_URL` makes it a second writer to live: the
   plan in STATE.md's `plan:` line moves when a month loads (CLAUDE.md numeric gate). Do not load a month from the new service until the group decides to.
   Rolling back needs the admin-only `data.rollback` permission.
5. The practice-month routes (`/batch/practice-month`, practice sign-in) exist only against the local throwaway server and answer
   `batch_not_available` on Render.

## 5. Copy-paste checklist

1. Render > New > Web Service > connect `tamagaur/4ISA-CAPS2-GROUP-7`, branch `thea-dashboardedits`, Root Directory empty.
2. Build `pip install -r requirements.txt`; Start `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`; Health Check Path `/health`.
3. Environment: `SUPABASE_DB_URL`, `JWT_SECRET_KEY` (new), `CORS_ALLOWED_ORIGINS=https://ssm-dsd.vercel.app`, `FRONTEND_URL=https://ssm-dsd.vercel.app`, `APP_ENV=production`, then the SMTP five, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and the `MFA_*` values copied from the old service.
4. After deploy: `GET <new-url>/health` is 200; `GET <new-url>/docs` is **404** (production); `GET <new-url>/batch/status` is **401** (proves the new code is running; 404 means an old commit).
5. Sign in on the new URL as the admin. Point the frontend at it: Vercel env `VITE_API_URL=<new-url>` (build-time; a redeploy of the frontend is needed). **DASHBOARD** (Vercel).
6. Add the new URL's origin only if the frontend is served from somewhere not yet in `CORS_ALLOWED_ORIGINS`.

## 6. Not determinable from the repo

| Item | Settle it by |
|---|---|
| Which commit the old service runs | Render dashboard, Deploys tab |
| Whether `PYTHON_VERSION` is needed beside `.python-version` | First build log |
| Instance size that holds a month load | Try on a paid instance; no measurement exists |
| The existing `MFA_ENCRYPTION_KEY` / `MFA_ENABLED` / `MFA_REQUIRED_ROLES` values | Old service's Environment tab |
| Whether the Vercel frontend address is `ssm-dsd.vercel.app` | Vercel dashboard (STATE.md recorded `ssm-dsd-six.vercel.app` as not served) |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase dashboard |
