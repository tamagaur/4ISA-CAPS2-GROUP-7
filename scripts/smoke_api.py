"""scripts/smoke_api.py — read-only smoke test of every API route the frontend uses.

Run this FIRST when the dashboard misbehaves after a pull. It tells you in about
ten seconds whether the problem is the backend, the database, or the frontend,
which is usually the part that takes longest to work out by hand.

    python scripts/smoke_api.py

What it does: mints a local JWT (never touches the users table), drives the real
FastAPI app in-process with TestClient against the live database, and issues GETs
only. It writes nothing, anywhere. Safe to run any time, including from a laptop
that is not the one that deployed.

Reading the result:
  * All PASS, dashboard still broken     -> the bug is in the frontend. See
                                            reports/FRONTEND_HANDOFF_2026-09-20.md.
  * 401/403 everywhere                   -> JWT_SECRET_KEY missing or changed in .env
  * 500 on one route                     -> that router; the traceback prints below it
  * ImportError / collection failure     -> dependencies, run: pip install -r requirements.txt
  * Cannot connect                       -> SUPABASE_DB_URL in .env, or the pooler is down

Del Monte deliberately returns empty/null on the ABC and segmentation routes --
it has no abc_classification rows and is not in the segmentation cohort. That is
correct behaviour, not a failure, and this script asserts it stays that way.
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO, ".env"))

# Routes the frontend actually calls, per frontend/src/api/*.js.
# (path, min_items) -- min_items None means "don't check a count".
ROUTES: list[tuple[str, int | None]] = [
    ("/dashboard", None),
    ("/dashboard?principal=unilever", None),
    ("/dashboard?principal=delmonte", None),
    ("/abc", 1),
    ("/abc?principal=unilever", 1),
    ("/abc?principal=delmonte", 0),          # correctly empty -- no Del Monte ABC rows
    ("/sku", 1),
    ("/sku?principal=unilever", 1),
    ("/sku?principal=delmonte", 1),
    ("/recommendations", None),
    ("/inventory/current", 1),
    ("/inventory/movement", 1),
    ("/inventory/receipt-signals", None),
    ("/audit-log", None),
]


def main() -> int:
    try:
        from fastapi.testclient import TestClient

        from analytics.config import long_read_db_url
        from backend import deps
        from backend.auth_utils import create_access_token
        from backend.deps import get_current_user, get_token_payload
        from backend.main import app
    except Exception as exc:
        print(f"IMPORT FAILED: {type(exc).__name__}: {exc}")
        print("\n-> Most likely your dependencies are stale. Run:")
        print("     pip install -r requirements.txt")
        print("   (requirements.txt pins starlette==0.41.3; a newer one breaks FastAPI 0.115.5)")
        return 2

    # This script's own GETs land as one combined multi-statement read per route
    # (backend/batch.py's prefetch), long enough that the :6543 pooler SUPABASE_DB_URL
    # normally serves requests through has dropped it mid-query ("SSL SYSCALL error: EOF
    # detected", three smoke runs in a row, 2026-10-16 -- a different route each time).
    # analytics.config.long_read_db_url() exists for exactly this; point this process's
    # engines at it (SUPABASE_DIRECT_URL, falling back to the pooler when unset) before
    # the first request creates them. Scoped to this script only -- backend/deps.py's own
    # default (the pooler, for every normal request) is unchanged.
    deps._db_url = long_read_db_url

    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=1, email="smoke@local", role="admin", full_name="Smoke Test")
    }
    # The minted token has no sign-in session behind it (opening one would be
    # a write), so skip the per-request session check and trust the signature
    # alone. The routes are what this script tests; tests/backend covers auth.
    app.dependency_overrides[get_current_user] = get_token_payload
    client = TestClient(app)

    print(f"{'route':42s} {'code':>5s} {'items':>7s}  result")
    print("-" * 74)
    failures = 0
    for path, min_items in ROUTES:
        try:
            resp = client.get(path, headers=headers)
        except Exception as exc:
            print(f"{path:42s} {'EXC':>5s} {'':>7s}  {type(exc).__name__}: {exc}")
            failures += 1
            continue

        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        items = body.get("items") if isinstance(body, dict) else None
        n = len(items) if isinstance(items, list) else None

        problems = []
        if resp.status_code != 200:
            problems.append(f"HTTP {resp.status_code}")
        if min_items is not None and n is not None and n < min_items:
            problems.append(f"expected >={min_items} items, got {n}")

        verdict = "PASS" if not problems else "FAIL: " + "; ".join(problems)
        failures += bool(problems)
        print(f"{path:42s} {resp.status_code:>5d} {('' if n is None else n):>7}  {verdict}")

    # The Del Monte shape the frontend has to tolerate. If it ever changes,
    # the "no data" copy on the ABC page is now wrong.
    print()
    abc_dm = client.get("/abc?principal=delmonte", headers=headers).json()
    print(f"Del Monte ABC        : count={abc_dm.get('count')}, "
          f"classification_period={abc_dm.get('classification_period')!r}  (category-grain rows expected since the 2026-09-21 Del Monte ABC run; empty/None = a regression)")

    print()
    if failures:
        print(f"{failures} route(s) FAILED -- the backend is the problem, not the frontend.")
        return 1
    print("All routes PASS. If the dashboard still looks wrong, the bug is in the frontend --")
    print("see reports/FRONTEND_HANDOFF_2026-09-20.md for the known cases and fixes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
