"""
scripts/local_api_qa.py - the real FastAPI app (backend.main.app, in process) with REAL users, sessions and sign-in, against the
THROWAWAY local database only (scripts/local_pg.py). Launch through the guard:

    python -m scripts.local_pg run -- python -m scripts.local_api_qa matrix      # permission walk, every GET route x 5 identities
    python -m scripts.local_pg run -- python -m scripts.local_api_qa cache      # the response cache across users and data changes

Identities (password QA_PASSWORD, all staff but `admin`):
    admin        everything
    view_only    the staff preset (lp.view, no lp.decide)
    decide_only  lp.view REMOVED, lp.decide GRANTED
    no_lp        lp.view removed, no lp.decide
    bare         every permission removed
Local timings and behaviour say nothing about Render or Supabase.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse

os.environ.setdefault("JWT_SECRET_KEY", "local-qa-only-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRY_HOURS", "8")
os.environ.setdefault("APP_ENV", "development")

QA_PASSWORD = "Qa-pass-123!"
IDENTITIES = {
    "admin": ("admin", {}),
    "view_only": ("staff", {}),
    "decide_only": ("staff", {"lp.view": False, "lp.decide": True}),
    "no_lp": ("staff", {"lp.view": False}),
    "bare": ("staff", None),     # None = every catalog key removed
}


def guard() -> str:
    url = os.environ["SUPABASE_DB_URL"]
    u = urlparse(url)
    if (u.hostname, u.port) != ("127.0.0.1", 55432):
        sys.exit(f"REFUSED: not the throwaway database ({u.hostname}:{u.port})")
    return url


def setup_users() -> None:
    import psycopg2
    from backend import permissions
    from backend.auth_utils import hash_password
    conn = psycopg2.connect(guard())
    cur = conn.cursor()
    for name, (role, overrides) in IDENTITIES.items():
        email = f"qa-{name}@qa-harness.org"
        cur.execute("DELETE FROM app.user_permission_override WHERE user_id IN (SELECT user_id FROM app.users WHERE email=%s)", (email,))
        cur.execute("DELETE FROM app.users WHERE email=%s", (email,))
        cur.execute("INSERT INTO app.users (email, password_hash, full_name, role) VALUES (%s,%s,%s,%s) RETURNING user_id",
                    (email, hash_password(QA_PASSWORD), f"QA {name}", role))
        uid = cur.fetchone()[0]
        if overrides is None:
            overrides = {k: False for k in permissions.ALL_KEYS}
        for key, granted in overrides.items():
            cur.execute("INSERT INTO app.user_permission_override (user_id, permission_key, granted) VALUES (%s,%s,%s)", (uid, key, granted))
    conn.commit()
    conn.close()


class Harness:
    def __init__(self):
        guard()
        setup_users()
        from fastapi.testclient import TestClient
        from backend.main import app
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)
        self.tokens = {}
        for name in IDENTITIES:
            r = self.client.post("/auth/login", json={"email": f"qa-{name}@qa-harness.org", "password": QA_PASSWORD})
            if r.status_code != 200:
                sys.exit(f"login failed for {name}: {r.status_code} {r.text[:200]}")
            self.tokens[name] = r.json()["access_token"]

    def call(self, who, method, path, json_body=None, headers=None, **kw):
        h = {"Authorization": "Bearer " + self.tokens[who]}
        h.update(headers or {})
        return self.client.request(method, path, json=json_body, headers=h, **kw)


def get_routes(app):
    out = []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if methods and hasattr(r, "path") and r.path.startswith("/") and "GET" in methods:
            out.append(r.path)
    return sorted(set(out))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    h = Harness()
    import importlib
    mod = importlib.import_module(f"scripts.local_api_qa_{cmd}")
    mod.run(h)
