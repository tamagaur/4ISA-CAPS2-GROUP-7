"""speed_baseline.py — rerunnable dashboard speed baseline. READ-ONLY.

Copied from kelvin/speed-baseline (reports/diagnostics/speed_baseline_2026-10-04/,
later merged into kelvin-etl at 5f635a7) on 2026-10-04 and adapted for the round-trip + cache work:
  - `serve` runs the backend's REAL session-check statement (deps._principal_sql:
    session + permission overrides + data version, one round trip) for an existing
    admin account, read-only, so the response cache works exactly as in production.
    The minted token names no session, so the check's verdict is not applied.
  - `serve` counts statements on both pools (transactional and the GET read pool),
    and adds POST /__speed/invalidate (this harness only) to empty the cache.
  - `cache` times each page cold (cache emptied first) and warm (straight after).
    `--page reorder` (2026-10-05, planning mart) times one page only.

Nothing here writes to the database: every request is a GET, the local
server's auth check runs the same SELECT the real one does but never opens or
closes a session row, and EXPLAIN ANALYZE runs inside
BEGIN; SET TRANSACTION READ ONLY; ... ROLLBACK (never set_session(readonly):
that leaks through the :6543 pooler, see memory pooler-readonly-leak).

Subcommands (run from the repo root, .venv active):

  serve    Local FastAPI on this checkout against the live DB, instrumented:
           every request's SQL statements, their times and the pool's
           pre-ping go to out/requests_<label>.jsonl.
             python reports/diagnostics/speed_baseline_2026-10-04/speed_baseline.py serve --port 8077

  time     Drive every frontend call (ENDPOINTS below, taken from
           frontend/src) N times, sequentially, and write a CSV.
             ... time --base http://127.0.0.1:8077 --label local
             ... time --base https://logincred.onrender.com --label render --token-env DSD_TOKEN
           Local mints its own JWT (serve trusts it). Render needs a real
           signed-in token in the named env var (copy it from the browser).

  pages    Fire each page's calls the way the browser does (parallel, with
           the ABC page's /fsn waiting on /abc) and time the wall clock.

  render   No token needed: warm /health, the 401 path before and after the
           DB session check, and the Oregon -> Mumbai round trip derived from
           them. --cold for one cold-start probe after 15+ min idle.

  select1  20 x SELECT 1 round trips to Supabase: raw psycopg2 on one open
           connection, plus the per-request extras the backend pays
           (pool pre-ping, BEGIN, ROLLBACK) and a fresh connection.

  explain  EXPLAIN (ANALYZE, BUFFERS) the slowest distinct statements seen by
           `serve`, inside a read-only transaction.

  profile  cProfile one run of each endpoint in-process (TestClient) and
           split the time into DB wait, pandas/numpy, pydantic/serialisation
           and the rest.

  summary  Turn the CSV + JSONL into the tables in README.md.
"""
from __future__ import annotations

import argparse
import base64
import contextvars
import csv
import json
import os
import pickle
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "out"
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

# ── What the frontend calls ─────────────────────────────────────────────────
# Source: frontend/src/api/*.js + the call sites listed in README.md §1.
# LATEST = frontend/src/dataCoverage.js LATEST_DATA_PERIOD (Feb 2026); the
# default range is LATEST minus DEFAULT_MONTHS_BACK=11 (DashboardLayout.jsx:82).
LATEST = "2026-02"
START_12 = "2025-03"
PRINCIPALS = ("unilever", "delmonte")  # SHOW_ALL_PRINCIPALS = false (principals.js:20)

# {sku_<p>} is filled at run time from the first item of /abc?principal=<p>,
# the same list the SKU Forecast page picks from.
ENDPOINTS: list[tuple[str, str, str]] = [
    # (page, range, path)  range: '1m' | '12m' | '-' (range doesn't apply)
    ("layout", "-", "/auth/me"),
    ("layout", "-", "/status"),
]
for p in PRINCIPALS:
    ENDPOINTS += [
        ("dashboard", "1m", f"/dashboard?period={LATEST}&start_period={LATEST}&principal={p}"),
        ("dashboard", "12m", f"/dashboard?period={LATEST}&start_period={START_12}&principal={p}"),
        ("sku-management", "-", f"/sku?principal={p}"),
        ("abc", "-", f"/abc?classification_period={LATEST}&view=last_known&principal={p}"),
        ("abc", "-", f"/fsn?principal={p}&period={LATEST}"),
        ("abc", "1m", f"/pareto?grain={'category' if p == 'delmonte' else 'brand'}&months=1&principal={p}&period={LATEST}"),
        ("abc", "12m", f"/pareto?grain={'category' if p == 'delmonte' else 'brand'}&months=12&principal={p}&period={LATEST}"),
        ("forecast", "-", f"/abc?principal={p}"),
        ("forecast", "-", f"/forecast/{{sku_{p}}}?principal={p}"),
        ("forecast", "-", f"/segment?sku={{sku_{p}}}&principal={p}"),
        ("forecast", "-", f"/decomposition?sku={{sku_{p}}}&principal={p}"),
        ("reorder", "-", f"/recommendations?status=pending&principal={p}"),
        ("category-trends", "-", f"/category-trends?principal={p}"),
    ]
ENDPOINTS += [
    ("audit-log", "-", "/audit-log/users"),
    ("audit-log", "-", "/audit-log?exclude_action=Login&exclude_action=Logout&limit=10"),
    ("users", "-", "/users"),
    ("users", "-", "/admin/permissions/catalog"),
]

# Each page's calls as the browser issues them: a list of waves; calls in a
# wave run in parallel, the next wave starts when the previous one is done.
# /auth/me is the layout's (PermissionsProvider), issued once per sign-in /
# reload, so it is left out of the per-page numbers.
def page_waves(p: str, sku: str) -> dict[str, list[list[str]]]:
    grain = "category" if p == "delmonte" else "brand"
    return {
        "dashboard (12m default)": [[f"/dashboard?period={LATEST}&start_period={START_12}&principal={p}"]],
        "sku-management": [[f"/sku?principal={p}"]],
        "abc": [
            [f"/abc?classification_period={LATEST}&view=last_known&principal={p}",
             f"/sku?principal={p}"],
            # ABCClassification.jsx:420-427: /fsn and the Pareto card wait for
            # the ABC response's classification_period.
            [f"/fsn?principal={p}&period={LATEST}",
             f"/pareto?grain={grain}&months=1&principal={p}&period={LATEST}"],
        ],
        "forecast": [
            [f"/abc?principal={p}", f"/sku?principal={p}"],
            [f"/forecast/{sku}?principal={p}", f"/segment?sku={sku}&principal={p}",
             f"/decomposition?sku={sku}&principal={p}"],
        ],
        "reorder": [[f"/recommendations?status=pending&principal={p}", f"/sku?principal={p}"]],
        "category-trends": [[f"/category-trends?principal={p}"]],
    }


# ── serve: instrumented local server ────────────────────────────────────────
_REQ: contextvars.ContextVar[dict | None] = contextvars.ContextVar("speed_req", default=None)


def _jsonable(v):
    try:
        json.dumps(v)
        return v
    except TypeError:
        return repr(v)


def serve(args) -> None:
    import uvicorn
    from fastapi import Depends
    from sqlalchemy import event, text
    from sqlalchemy.orm import Session

    from backend import deps, response_cache
    from backend.main import app
    from backend.sessions import SESSION_IDLE_MINUTES

    OUT.mkdir(exist_ok=True)
    log_path = OUT / f"requests_{args.label}.jsonl"
    lock = threading.Lock()

    # Auth: the backend's own session-check statement, one round trip, for a
    # real admin account (read once at start). The minted token names no
    # session, so its verdict is not applied; everything it reads alongside
    # (permissions, data version) is, through deps._principal_from_row.
    with Session(deps._get_engine()) as s0:
        admin_id = s0.execute(text("SELECT MIN(user_id) FROM users WHERE role = 'admin'")).scalar()
        s0.rollback()

    def current_user_readonly(
        payload=Depends(deps.get_token_payload), db: Session = Depends(deps.get_db)
    ):
        row = db.execute(text(deps._principal_sql(db)), {
            "user_id": admin_id, "session_id": payload.session_id or "none",
            "idle_minutes": SESSION_IDLE_MINUTES,
        }).mappings().first()
        return deps._principal_from_row(db, payload, row)

    app.dependency_overrides[deps.get_current_user] = current_user_readonly

    @app.post("/__speed/invalidate")
    def _invalidate():
        response_cache.invalidate()
        return response_cache.stats()

    engine = deps._get_engine()

    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("speed_t0", []).append(time.perf_counter())

    def _after(conn, cursor, statement, parameters, context, executemany):
        t0 = conn.info["speed_t0"].pop()
        rec = _REQ.get()
        if rec is None:
            return
        rec["queries"].append({
            "ms": round((time.perf_counter() - t0) * 1000, 2),
            "rows": cursor.rowcount,
            "sql": statement,
            "params": {k: _jsonable(v) for k, v in (parameters or {}).items()} if isinstance(parameters, dict) else _jsonable(parameters),
            "pickle": base64.b64encode(pickle.dumps((statement, parameters))).decode(),
        })

    for eng in (engine, deps._get_read_engine()):
        event.listen(eng, "before_cursor_execute", _before)
        event.listen(eng, "after_cursor_execute", _after)

    # pool_pre_ping: one extra round trip per connection checkout (none since
    # 2026-10-04; kept so a pre-ping coming back would show up).
    dialect = engine.dialect
    real_ping = dialect.do_ping

    def timed_ping(dbapi_connection):
        t0 = time.perf_counter()
        try:
            return real_ping(dbapi_connection)
        finally:
            rec = _REQ.get()
            if rec is not None:
                rec["pings_ms"].append(round((time.perf_counter() - t0) * 1000, 2))

    dialect.do_ping = timed_ping

    class Instrument:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.inner(scope, receive, send)
            headers = dict(scope.get("headers") or [])
            rec = {
                "tag": headers.get(b"x-speed-tag", b"").decode(),
                "path": scope["path"], "query": scope["query_string"].decode(),
                "queries": [], "pings_ms": [], "status": None, "bytes": 0,
            }
            token = _REQ.set(rec)
            t0 = time.perf_counter()

            async def send_wrap(msg):
                if msg["type"] == "http.response.start":
                    rec["status"] = msg["status"]
                elif msg["type"] == "http.response.body":
                    rec["bytes"] += len(msg.get("body", b""))
                await send(msg)

            try:
                await self.inner(scope, receive, send_wrap)
            finally:
                rec["server_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                rec["db_ms"] = round(sum(q["ms"] for q in rec["queries"]) + sum(rec["pings_ms"]), 2)
                rec["n_queries"] = len(rec["queries"])
                _REQ.reset(token)
                with lock, open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")

    print(f"serve: logging to {log_path}")
    uvicorn.run(Instrument(app), host="127.0.0.1", port=args.port, log_level="warning")


# ── time: sequential runs ───────────────────────────────────────────────────
def _local_token() -> str:
    from backend.auth_utils import create_access_token

    return create_access_token(user_id=0, email="speed@local", role="admin", full_name="Speed Baseline")


def _client(args):
    import httpx

    token = os.environ.get(args.token_env) if args.token_env else _local_token()
    if not token:
        sys.exit(f"--token-env {args.token_env} is empty")
    return httpx.Client(base_url=args.base, headers={"Authorization": f"Bearer {token}"}, timeout=300)


def _resolve_skus(client) -> dict[str, str]:
    skus = {}
    for p in PRINCIPALS:
        r = client.get(f"/abc?principal={p}", headers={"x-speed-tag": "resolve"})
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items:
            sys.exit(f"/abc?principal={p} returned no items; cannot pick a SKU")
        skus[p] = items[0]["sku_id"]
    return skus


def _fill(path: str, skus: dict[str, str]) -> str:
    from urllib.parse import quote

    for p, s in skus.items():
        path = path.replace(f"{{sku_{p}}}", quote(s, safe=""))
    return path


def time_cmd(args) -> None:
    OUT.mkdir(exist_ok=True)
    client = _client(args)
    # Warm-up: the first request after boot opens pool connections; it is
    # recorded separately, not in the 3 runs.
    t0 = time.perf_counter()
    r = client.get("/auth/me", headers={"x-speed-tag": f"{args.label}|warmup"})
    print(f"warm-up /auth/me {r.status_code} {1000 * (time.perf_counter() - t0):.0f} ms")
    skus = _resolve_skus(client)
    print("sample SKUs:", skus)
    # --only reruns a subset (e.g. --only /dashboard) into its own CSV so the
    # full pass isn't overwritten.
    out = OUT / (f"timings_{args.label}.csv" if not args.only else f"timings_{args.label}_rerun.csv")
    rows = []
    for page, rng, raw in ENDPOINTS:
        path = _fill(raw, skus)
        if args.only and args.only not in path:
            continue
        for run in range(1, args.runs + 1):
            t0 = time.perf_counter()
            tag = f"{args.label}-rerun" if args.only else args.label
            r = client.get(path, headers={"x-speed-tag": f"{tag}|{run}"})
            ms = 1000 * (time.perf_counter() - t0)
            rows.append({"label": args.label, "page": page, "range": rng, "path": path, "run": run,
                         "status": r.status_code, "ms": round(ms, 1), "bytes": len(r.content),
                         "at": time.strftime("%H:%M:%S")})
            print(f"{page:16s} {rng:4s} {r.status_code} {ms:8.0f} ms  {len(r.content):>8d} B  {path}")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")


def pages_cmd(args) -> None:
    OUT.mkdir(exist_ok=True)
    client = _client(args)
    client.get("/auth/me")
    skus = _resolve_skus(client)
    rows = []

    def get(url, run):
        r = client.get(url, headers={"x-speed-tag": f"{args.label}-page|{run}"})
        # 404 is a normal answer the frontend maps to null (api/forecast.js,
        # segment.js, analytics.js); anything else non-2xx is a failure.
        if r.status_code != 404:
            r.raise_for_status()

    with ThreadPoolExecutor(max_workers=8) as pool:
        for p in PRINCIPALS:
            for page, waves in page_waves(p, _fill(f"{{sku_{p}}}", skus)).items():
                for run in range(1, args.runs + 1):
                    t0 = time.perf_counter()
                    for wave in waves:
                        list(pool.map(lambda u: get(u, run), wave))
                    ms = 1000 * (time.perf_counter() - t0)
                    rows.append({"label": args.label, "principal": p, "page": page, "run": run,
                                 "calls": sum(len(w) for w in waves), "waves": len(waves), "ms": round(ms, 1)})
                    print(f"{p:9s} {page:24s} run{run} {ms:8.0f} ms")
    out = OUT / f"pages_{args.label}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")


# ── cache: each page cold (cache emptied) and warm (repeated straight after) ──
def cache_cmd(args) -> None:
    """Per page, per principal, `runs` times: POST /__speed/invalidate (serve's
    harness-only route), load the page's waves (cold), then load them again
    (warm). The first cold load of the run is also the server's first request
    when this is started right after `serve`."""
    OUT.mkdir(exist_ok=True)
    client = _client(args)
    rows = []

    def get(url, tag):
        r = client.get(url, headers={"x-speed-tag": tag})
        if r.status_code != 404:
            r.raise_for_status()

    t0 = time.perf_counter()
    get(f"/dashboard?period={LATEST}&start_period={START_12}&principal=unilever", f"{args.label}-first|0")
    first_ms = 1000 * (time.perf_counter() - t0)
    print(f"first request after start (dashboard 12m unilever): {first_ms:.0f} ms")
    rows.append({"label": args.label, "principal": "unilever", "page": "dashboard (12m default)",
                 "state": "first request", "run": 0, "calls": 1, "waves": 1, "ms": round(first_ms, 1)})
    skus = _resolve_skus(client)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for p in PRINCIPALS:
            for page, waves in page_waves(p, _fill(f"{{sku_{p}}}", skus)).items():
                if args.page and args.page != page:
                    continue
                for run in range(1, args.runs + 1):
                    client.post("/__speed/invalidate")
                    for state in ("cold", "warm"):
                        t0 = time.perf_counter()
                        for wave in waves:
                            list(pool.map(lambda u: get(u, f"{args.label}-{state}|{run}"), wave))
                        ms = 1000 * (time.perf_counter() - t0)
                        rows.append({"label": args.label, "principal": p, "page": page, "state": state, "run": run,
                                     "calls": sum(len(w) for w in waves), "waves": len(waves), "ms": round(ms, 1)})
                        print(f"{p:9s} {page:24s} {state:4s} run{run} {ms:8.0f} ms")
    out = OUT / f"cache_{args.label}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")


# ── render: what can be measured without a signed-in token ──────────────────
# The backend's fixed floor before a route's first query is 4 round trips to
# the DB (pre-ping 2, BEGIN 1, session check 1 — see README §3a). A token
# signed with this checkout's JWT_SECRET_KEY but naming no session reaches that
# session check on Render and is refused AFTER it (deps._load_active_principal:
# no row -> 401, no write; user_id 0 has no row, so the idle-close UPDATE can't
# run). A garbage token is refused BEFORE any DB work. The difference between
# the two is those 4 round trips, Oregon -> Mumbai.
def render_cmd(args) -> None:
    import httpx

    OUT.mkdir(exist_ok=True)
    if args.cold:
        # One cold-start probe: keep asking until the service answers.
        t0 = time.perf_counter()
        attempts = []
        while True:
            a0 = time.perf_counter()
            try:
                r = httpx.get(f"{args.base}/health", timeout=args.cold_timeout)
                attempts.append({"status": r.status_code, "s": round(time.perf_counter() - a0, 1)})
                if r.status_code == 200:
                    break
            except httpx.HTTPError as exc:
                attempts.append({"status": type(exc).__name__, "s": round(time.perf_counter() - a0, 1)})
            if time.perf_counter() - t0 > 900:
                break
        res = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "total_s": round(time.perf_counter() - t0, 1),
               "attempts": attempts}
        print(json.dumps(res))
        with open(OUT / "render_cold.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(res) + "\n")
        return

    from backend.auth_utils import create_access_token

    signed = create_access_token(user_id=0, email="speed@probe", role="staff",
                                 full_name="Speed probe", session_id="speed-probe-no-session")
    cases = [
        ("health (no auth, no DB)", "/health", None),
        ("401 no token (no DB)", "/auth/me", None),
        ("401 bad signature (no DB)", "/auth/me", "Bearer not-a-jwt"),
        ("401 signed, no session (session-check SELECT)", "/auth/me", f"Bearer {signed}"),
    ]
    rows, details = [], {}
    with httpx.Client(base_url=args.base, timeout=120) as client:
        client.get("/health")  # wake + open the keep-alive connection
        for name, path, auth in cases:
            headers = {"Authorization": auth} if auth else {}
            for run in range(1, args.runs + 1):
                t0 = time.perf_counter()
                r = client.get(path, headers=headers)
                ms = 1000 * (time.perf_counter() - t0)
                details[name] = (r.status_code, r.text[:80])
                rows.append({"case": name, "run": run, "status": r.status_code, "ms": round(ms, 1),
                             "at": time.strftime("%H:%M:%S")})
    with open(OUT / "render_probe.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    med = {}
    for name, *_ in cases:
        xs = [r["ms"] for r in rows if r["case"] == name]
        med[name] = statistics.median(xs)
        print(f"{name:48s} status {details[name][0]}  median {statistics.median(xs):7.1f}  "
              f"min {min(xs):7.1f}  max {max(xs):7.1f}  ({details[name][1]!r})")
    db = med[cases[3][0]] - med[cases[2][0]]
    reached_db = "session has ended" in details[cases[3][0]][1]
    print(f"\nsession-check path reached the DB: {reached_db}")
    if reached_db:
        print(f"4-round-trip floor on Render = {db:.0f} ms -> Render->Supabase RTT ~ {db / 4:.0f} ms")
    (OUT / "render_probe_summary.json").write_text(json.dumps({
        "medians_ms": med, "reached_db": reached_db,
        "floor_4rt_ms": round(db, 1), "rtt_estimate_ms": round(db / 4, 1) if reached_db else None,
        "at": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2))


# ── select1 ─────────────────────────────────────────────────────────────────
def _connect():
    import psycopg2

    return psycopg2.connect(os.environ["SUPABASE_DB_URL"], sslmode="require", connect_timeout=10)


def select1_cmd(args) -> None:
    from sqlalchemy import text

    from backend import deps

    res = {}
    t0 = time.perf_counter()
    conn = _connect()
    res["connect_ms"] = round(1000 * (time.perf_counter() - t0), 1)
    conn.autocommit = True  # one round trip per statement, no BEGIN
    cur = conn.cursor()
    rt = []
    for _ in range(args.n):
        t0 = time.perf_counter()
        cur.execute("SELECT 1")
        cur.fetchone()
        rt.append(1000 * (time.perf_counter() - t0))
    conn.close()
    res["select1_autocommit_ms"] = rt

    # The backend's per-request extras, through its own engines: checkout +
    # SELECT 1 + commit + return to the pool. Transactional pool: psycopg2 sends
    # BEGIN READ WRITE and COMMIT as round trips of their own. Read pool (GET
    # requests): autocommit, the statement alone.
    from sqlalchemy.orm import Session

    for name, engine in (("engine_checkout_select1_return_ms", deps._get_engine()),
                         ("read_engine_checkout_select1_return_ms", deps._get_read_engine())):
        with engine.connect() as c:  # warm one pooled connection
            c.execute(text("SELECT 1"))
        full = []
        for _ in range(args.n):
            t0 = time.perf_counter()
            with Session(engine) as db:
                db.execute(text("SELECT 1")).scalar()
                db.commit()
            full.append(1000 * (time.perf_counter() - t0))
        res[name] = full

    def stats(xs):
        s = sorted(xs)
        return {"n": len(s), "median": round(statistics.median(s), 1), "min": round(s[0], 1),
                "p90": round(s[int(0.9 * (len(s) - 1))], 1), "max": round(s[-1], 1)}

    summary = {"connect_ms": res["connect_ms"],
               "select1_autocommit": stats(res["select1_autocommit_ms"]),
               "engine_checkout_select1_return": stats(res["engine_checkout_select1_return_ms"]),
               "read_engine_checkout_select1_return": stats(res["read_engine_checkout_select1_return_ms"]),
               "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    print(json.dumps(summary, indent=2))
    OUT.mkdir(exist_ok=True)
    (OUT / "select1.json").write_text(json.dumps({"summary": summary, "raw": res}, indent=2))


# ── explain ─────────────────────────────────────────────────────────────────
def _load_requests(label: str) -> list[dict]:
    path = OUT / f"requests_{label}.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def explain_cmd(args) -> None:
    reqs = [r for r in _load_requests(args.label) if r["tag"].startswith(f"{args.label}|") and not r["tag"].endswith("|warmup")]
    worst: dict[str, dict] = {}
    for r in reqs:
        for q in r["queries"]:
            key = " ".join(q["sql"].split())
            cur = worst.get(key)
            if cur is None or q["ms"] > cur["ms"]:
                worst[key] = {**q, "endpoint": r["path"] + ("?" + r["query"] if r["query"] else "")}
    top = sorted(worst.values(), key=lambda q: -q["ms"])[: args.top]
    conn = _connect()
    conn.autocommit = True  # explicit BEGIN/ROLLBACK below
    cur = conn.cursor()
    results = []
    for i, q in enumerate(top, 1):
        statement, params = pickle.loads(base64.b64decode(q["pickle"]))
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL statement_timeout = '120s'")
        try:
            cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + statement, params)
            plan = "\n".join(row[0] for row in cur.fetchall())
        except Exception as exc:  # noqa: BLE001 — report, don't stop
            plan = f"EXPLAIN FAILED: {type(exc).__name__}: {exc}"
        finally:
            cur.execute("ROLLBACK")
        results.append({"rank": i, "seen_ms": q["ms"], "endpoint": q["endpoint"], "sql": statement, "plan": plan})
        last = [l for l in plan.splitlines() if "Execution Time" in l]
        print(f"#{i} seen {q['ms']:.0f} ms  {last[0].strip() if last else plan[:80]}  <- {q['endpoint']}")
    conn.close()
    out = OUT / f"explain_{args.label}.md"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(f"# EXPLAIN (ANALYZE, BUFFERS) — top {len(results)} slowest distinct statements ({args.label})\n\n")
        fh.write("Run inside BEGIN; SET TRANSACTION READ ONLY; ... ROLLBACK. `seen` = slowest time the statement took during the timing runs (includes the round trip).\n\n")
        for r in results:
            fh.write(f"## #{r['rank']} — seen {r['seen_ms']:.0f} ms — `{r['endpoint']}`\n\n```sql\n{r['sql'].strip()}\n```\n\n```\n{r['plan']}\n```\n\n")
    print(f"wrote {out}")


# ── profile ─────────────────────────────────────────────────────────────────
def profile_cmd(args) -> None:
    import cProfile
    import pstats

    from fastapi.testclient import TestClient

    from backend.deps import get_current_user, get_token_payload
    from backend.main import app

    app.dependency_overrides[get_current_user] = get_token_payload
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {_local_token()}"
    client.get("/status")
    skus = _resolve_skus(client)
    rows = []
    seen = set()
    for page, rng, raw in ENDPOINTS:
        path = _fill(raw, skus)
        if path in seen or path == "/status":
            continue
        seen.add(path)
        client.get(path)  # warm
        prof = cProfile.Profile()
        t0 = time.perf_counter()
        prof.enable()
        r = client.get(path)
        prof.disable()
        wall = 1000 * (time.perf_counter() - t0)
        st = pstats.Stats(prof)
        buckets = {"db_wait": 0.0, "pandas_numpy": 0.0, "pydantic_json": 0.0}
        for (fname, _line, func), (_cc, _nc, tt, _ct, _callers) in st.stats.items():
            f = fname.replace("\\", "/")
            if "psycopg2" in f or func in ("<method 'execute' of 'psycopg2.extensions.cursor' objects>",
                                           "<method 'fetchall' of 'psycopg2.extensions.cursor' objects>"):
                buckets["db_wait"] += tt
            elif "/pandas/" in f or "/numpy/" in f:
                buckets["pandas_numpy"] += tt
            elif "/pydantic" in f or "/json/" in f or "jsonable_encoder" in func:
                buckets["pydantic_json"] += tt
        b = {k: round(v * 1000, 1) for k, v in buckets.items()}
        rows.append({"path": path, "status": r.status_code, "wall_ms": round(wall, 1), **b,
                     "other_ms": round(wall - sum(b.values()), 1)})
        print(rows[-1])
    out = OUT / "profile_inprocess.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")


# ── summary ─────────────────────────────────────────────────────────────────
def summary_cmd(args) -> None:
    def med_max(xs):
        return statistics.median(xs), max(xs)

    for label in args.labels:
        path = OUT / f"timings_{label}.csv"
        if not path.exists():
            continue
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        reqs = {}
        if (OUT / f"requests_{label}.jsonl").exists():
            for r in _load_requests(label):
                if r["tag"].startswith(f"{label}|") and not r["tag"].endswith("|warmup"):
                    key = r["path"] + ("?" + r["query"] if r["query"] else "")
                    reqs.setdefault(key, []).append(r)
        print(f"\n### {label}\n")
        print("| page | range | endpoint | status | median ms | slowest ms | KB | queries | DB ms (median) | non-DB ms (median) |")
        print("|---|---|---|---|---:|---:|---:|---:|---:|---:|")
        by = {}
        for r in rows:
            by.setdefault((r["page"], r["range"], r["path"]), []).append(r)
        for (page, rng, p), rs in by.items():
            md, mx = med_max([float(r["ms"]) for r in rs])
            kb = int(rs[0]["bytes"]) / 1024
            rq = reqs.get(p, [])
            nq = dbm = nondb = ""
            if rq:
                nq = statistics.median([x["n_queries"] for x in rq])
                dbm = round(statistics.median([x["db_ms"] for x in rq]))
                nondb = round(statistics.median([x["server_ms"] - x["db_ms"] for x in rq]))
                nq = int(nq) if nq == int(nq) else nq
            print(f"| {page} | {rng} | `{p}` | {rs[0]['status']} | {md:.0f} | {mx:.0f} | {kb:.0f} | {nq} | {dbm} | {nondb} |")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8077); s.add_argument("--label", default="local")
    for name in ("time", "pages", "cache"):
        t = sub.add_parser(name)
        t.add_argument("--base", default="http://127.0.0.1:8077")
        t.add_argument("--label", default="local")
        t.add_argument("--token-env", default=None, help="env var holding a real bearer token (Render)")
        t.add_argument("--runs", type=int, default=3)
        t.add_argument("--only", default=None, help="time: only paths containing this substring")
        t.add_argument("--page", default=None, help="cache: only this page (a page_waves name, e.g. reorder)")
    rd = sub.add_parser("render", help="token-free Render probes")
    rd.add_argument("--base", default="https://logincred.onrender.com")
    rd.add_argument("--runs", type=int, default=10)
    rd.add_argument("--cold", action="store_true", help="one cold-start probe (run after 15+ min idle)")
    rd.add_argument("--cold-timeout", type=float, default=300)
    s1 = sub.add_parser("select1"); s1.add_argument("--n", type=int, default=20)
    e = sub.add_parser("explain"); e.add_argument("--label", default="local"); e.add_argument("--top", type=int, default=12)
    sub.add_parser("profile")
    sm = sub.add_parser("summary"); sm.add_argument("labels", nargs="*", default=["local", "render"])
    args = ap.parse_args()
    {"serve": serve, "render": render_cmd, "time": time_cmd, "pages": pages_cmd, "cache": cache_cmd,
     "select1": select1_cmd,
     "explain": explain_cmd, "profile": profile_cmd, "summary": summary_cmd}[args.cmd](args)


if __name__ == "__main__":
    main()
