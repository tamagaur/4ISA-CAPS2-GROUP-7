# Deploying the SSM DSD and testing it in a browser (2026-11-13)

For: whoever sets up the Render backend and the Vercel frontend, and whoever tests the site after. Every variable below was read
from the code on branch `kelvin-be` (file and line given), not from older notes. No secret value appears here. Supersedes section 3
of `docs/RENDER_SETUP.md`, which predates three of these findings (SUPABASE_KEY, SUPABASE_DIRECT_URL, the VITE_API_URL build check).

## 1. What is deployed now (probed 2026-11-13, no sign-in)

| Thing | Finding |
|---|---|
| Backend `https://fourisa-caps2-group-7.onrender.com` | Up (`/health` 200). Serves 84 routes; the repo has 95. The 11 missing are all of `/batch/*`, so **Data Management cannot load or roll back a month on it**. Its route list matches neither `abc-tab-edits` (8010f11) nor Main-BE (4f12e24) exactly. `/docs` is open, so `APP_ENV` is not `production`. CORS already allows `https://ssm-dsd.vercel.app`. Email is off there (`GET /auth/forgot-password` says `email_enabled: false`). |
| Which branch Render deploys | **Not readable from the repo**: there is no `render.yaml`. The service's Settings tab shows it. Whatever it watches, it is not running any team branch's current tip: `thea-dashboardedits` and `kelvin-be` both have `/batch/*`. |
| Frontend `https://ssm-dsd.vercel.app` | Up (200). Its bundle calls the backend above. `ssm-dsd-six.vercel.app` (the local `.env`'s FRONTEND_URL) answers 404. |
| Unauthenticated access | Every data route answers 401. Only `/health`, `/status` and `GET /auth/forgot-password` answer without a sign-in. |

**What has to happen.** Point both Render and Vercel at branch `kelvin-be` on `https://github.com/tamagaur/4ISA-CAPS2-GROUP-7`
and deploy. No merge is needed: `kelvin-be` already contains `thea-dashboardedits` (afc4d7e) and `abc-tab-edits` (8010f11). The
month-load attestation (`docs/MONTH_LOAD_REHEARSAL.json`) matches this code, so a load on live is allowed from it.

## 2. Settings sheet

### Render (backend web service)

| Setting | Value |
|---|---|
| Repository / branch | `https://github.com/tamagaur/4ISA-CAPS2-GROUP-7`, branch `kelvin-be` |
| Root directory | empty (the repository root: the API imports `analytics/` and starts `scripts/` as subprocesses) |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/health` |
| Python | 3.13 (`.python-version`; if the build rejects it, set `PYTHON_VERSION` to a full version such as `3.13.5`) |

| Variable | Value | Needed | What breaks without it (code) |
|---|---|---|---|
| `SUPABASE_DB_URL` | Supabase > Connect > **Transaction pooler**: `postgresql://postgres.dsdxemtmbbmdtccwxzyk:<password>@aws-0-ap-south-1.pooler.supabase.com:6543/postgres` | Yes | The server refuses to start (`backend/main.py` lifespan, `backend/deps.py:83`). Never `db.<ref>.supabase.co`: IPv6 only. |
| `SUPABASE_DIRECT_URL` | The same string with port **5432** (the session pooler) | Yes, for loading a month | The order plan's long reads use it (`analytics/config.long_read_db_url`, `scripts/run_lp.py`); without it they go through the 6543 pooler, which has dropped long queries before. The API itself never reads it. |
| `JWT_SECRET_KEY` | A new random string of at least 32 characters: `python -c "import secrets; print(secrets.token_urlsafe(64))"` | Yes | With `APP_ENV=production` and under 32 characters the server refuses to start (`backend/startup_checks.py`). Unset: every sign-in fails ("JWT_SECRET_KEY is not set", `backend/auth_utils.py:74`). Changing it only signs everyone out. |
| `CORS_ALLOWED_ORIGINS` | `https://ssm-dsd.vercel.app` | Yes | The browser blocks every call from the site. The name is exactly this (`backend/main.py:57`); unset, only `http://localhost:5173` is allowed. No trailing slash; several origins separated by commas. |
| `FRONTEND_URL` | `https://ssm-dsd.vercel.app` | Yes | Invite and password-reset links: with `APP_ENV=production` none is built (`backend/mailer.py`). |
| `APP_ENV` | `production` | Yes | Hides `/docs` and `/openapi.json`, turns on HSTS, enforces the 32-character secret. |
| `MFA_ENCRYPTION_KEY` | **Copy from the existing Render service's Environment tab.** One account has two-step sign-in set up under it (`app.user_mfa`, read 2026-11-13). | If two-step stays on | Malformed: the server refuses to start. A different key: that account cannot pass the second step until an admin resets it. |
| `MFA_ENABLED` | Copy from the existing service (`true` or unset) | Optional | Unset: two-step is paused and sign-in skips the code (`backend/mfa.py`). |
| `MFA_REQUIRED_ROLES` | Copy, or leave unset | Optional | Unset: two-step is optional for everyone. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | `smtp.gmail.com`, `587`, the sending Gmail address, its 16-letter app password, `"SSM Dashboard <address>"` | Optional (all five or none) | The admin gets a copyable link instead of an email. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | `https://dsdxemtmbbmdtccwxzyk.supabase.co`; Supabase > Project Settings > API > service_role | Optional | Profile-picture upload fails (`backend/avatar.py`). **The Supabase project has no Storage bucket at all** (`storage.buckets` 0 rows, 2026-11-13), so upload fails even with both set until an `avatars` bucket is created in the Supabase dashboard. |
| `JWT_ALGORITHM`, `JWT_EXPIRY_HOURS` | `HS256`, `8` | Optional | Code defaults are the same. |
| Do **not** set | `DM_DEMO_ENABLED` (turns on the synthetic demonstration data), `MONTHLY_BATCH_ENABLED` (practice server only), `SUPABASE_KEY` (read by nothing; no longer required since 2026-11-13), `RENDER` (Render sets it) | | |

### Vercel (frontend project)

| Setting | Value |
|---|---|
| Repository / branch | `https://github.com/tamagaur/4ISA-CAPS2-GROUP-7`, branch `kelvin-be` |
| Root directory | `frontend` |
| Framework / build / output | Vite / `npm run build` / `dist` |
| `VITE_API_URL` | `https://fourisa-caps2-group-7.onrender.com` (the backend's address, **no trailing slash**) |

`VITE_API_URL` is read when the site is BUILT, not when it runs, so redeploy after changing it. Until 2026-11-13 a build without it
succeeded and the site sent every request to `http://localhost:8000` (`src/auth.js:16`'s development fallback), behind a
Content-Security-Policy allowing only that address (`vite.config.js`): every call failed as a network error and nothing warned. Since
2026-11-13 the build refuses to finish without it, or with a trailing slash, and says why. If the backend moves, change it here AND
`CORS_ALLOWED_ORIGINS` on Render if the frontend moves.

## 3. Browser checklist

Sign in at `https://ssm-dsd.vercel.app/login` with an admin account that does not have two-step sign-in (four of the five accounts;
the fifth needs its authenticator app while `MFA_ENABLED` is on). The first request after the backend has slept takes about a minute
(84 s measured 2026-11-05); the login page says "the server is waking up" after 4 s. Every figure below was read from the API on
2026-11-13: "now" from live, "after March" from a restored copy of live with the March file loaded (section 4).

| # | Do | Expect now | Expect after loading March |
|---|---|---|---|
| 1 | Sign in | The Dashboard. If the server is cold, "Reading which months have data…" first; on a failure a message and Try again, never a page on a guessed month (new 2026-11-13). | Same |
| 2 | Top bar | No banner. Range Mar 2025 – Feb 2026. | Banner on every page: "Sales for March 2026 is generated: SSM has not sent that month…". Range Apr 2025 – Mar 2026. |
| 3 | Dashboard, Unilever: sales | Latest month Feb 2026 ₱27,914,343.91; 12 months ₱391,113,139.25 (28,081,480 pcs) | Mar 2026 ₱27,509,282.50; 12 months ₱384,708,516.42; March marked generated |
| 4 | Stock card | Feb 2026, counted 2 Mar 2026: ₱46,576,778.51, flagged "unusually high … pending SSM confirmation"; weeks of cover 7.06 | Mar 2026, counted 6 Apr 2026 (a real count): ₱22,700,825.83; weeks of cover 3.28 |
| 5 | Forecast card | "The Mar 2026 forecast is 1,146,783 pieces — 17.2% above the 978,202 pieces sold in Feb 2026"; calendar adjustment ×0.8739 to ×1.2413 over 115 products | "The Apr 2026 forecast is 1,082,882 pieces — 8.6% above the 997,511 pieces sold in Mar 2026"; ×0.7501 to ×1.0990 |
| 6 | Forecast error card | Company total 8.5%, typical product (weighted) 32.0%, MAPE 34.0% | "Forecast error withheld: sales for March 2026 is generated… A date range ending before March 2026 shows the real months' error." Pick Mar 2025 – Feb 2026: 8.5% / 32.0% / 34.0% again (MAPE was blank there before a fix of 2026-11-13) |
| 7 | Reorder preview | 115 products, 330,212 pcs; act now 20, review later 44, no order 51 | 131 products, 1,016,754 pcs; act now 88, review later 11, no order 32 |
| 8 | Reorder page | Cycle Mar 2026; 115 rows, 64 with an order, 330,212 pcs; weights "Purchase cost 45%, Need met (by sales value) 35%, Storage 20%"; opening stock = the count of 2 Mar 2026 | Cycle Apr 2026; 131 rows, 99 with an order, 1,016,754 pcs; opening stock = the count of 6 Apr 2026 |
| 9 | Open one row's review drawer | Same three weight labels; the 90% service level appears with the safety stock, not with a weight | Same |
| 10 | ABC page, Unilever | Feb 2026: A 189, B 230, C 672 | Mar 2026: A 191, B 232, C 660 |
| 11 | ABC page, Del Monte | Note reads "82 sub-categories became 5 categories" | Same |
| 12 | SKU Forecast > a product > Show details | Time of year: "…for this product (its own years, leaning on the typical product where it has few)" | Same |
| 13 | Reference Guide > Reorder Planning > Order weights | "Purchase cost 45%, need met 35% … storage 20%, as stored with the current plan" (read from the plan, not typed in) | Same |
| 14 | Leave a page open past the session expiry (8 h), or sign out in another tab, then click anything | Sent to the login page with "session expired"; after signing in, back on the page you were on (new 2026-11-13) | Same |
| 15 | Data Management > upload a file after the session expired | Sent to the login page, not a silent failure (new 2026-11-13) | Same |

Why the plan triples after March: the March plan is small because it opens on the count of 2 Mar 2026, ₱46.6M, about twice the
counts before and after it (accepted for planning, pending SSM). April opens on the real count of 6 Apr 2026, ₱22.7M, so it needs
more. Not caused by the generated sales.

## 4. Loading March in front of an audience

- Needs the backend redeployed from `kelvin-be` (section 1): the deployed one has no `/batch/*`.
- Data Management > Monthly Data Processing: upload `local/demo/demo_march_sales.csv` (git-ignored, on the machine that made it:
  `python -m scripts.make_demo_sales_file --month 2026-03`; the same file as the rehearsal's), choose calendar factor **On**, and accept
  the waiting orders when asked. Another file, factor Off, or not accepting gives other numbers than section 3.
- The load took 170 s on a local copy. On Render it has not been timed, and the free instance's memory has not been measured
  against the forecast and the plan; a dry run there (load, then Roll back) before the audience settles both.
- Roll back (admin only) returns live to 115 rows / 330,212 pieces and the Feb 2026 range, proven on the copy 2026-11-13.
