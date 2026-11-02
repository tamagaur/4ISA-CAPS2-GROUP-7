"""G2 and G3 of docs/DATA_GOVERNANCE.md: the API's response headers and the append-only audit trail (static check)."""
import json
import pathlib
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.security_headers import HSTS, SecurityHeadersMiddleware

REPO = pathlib.Path(__file__).resolve().parents[2]


def _client(hsts: bool) -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)

    @app.get("/auth/me")
    def me():
        return {"ok": True}

    @app.get("/abc")
    def abc():
        return {"ok": True}

    @app.get("/own")
    def own():
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True}, headers={"X-Frame-Options": "SAMEORIGIN"})

    return TestClient(app)


def test_every_answer_carries_the_browser_headers():
    r = _client(False).get("/abc")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in r.headers      # development: no HTTPS to pin
    assert "cache-control" not in r.headers


def test_hsts_only_when_asked():
    assert _client(True).get("/abc").headers["strict-transport-security"] == HSTS


def test_account_routes_are_not_cached():
    assert _client(False).get("/auth/me").headers["cache-control"] == "no-store"


def test_a_header_the_route_set_is_left_alone():
    assert _client(False).get("/own").headers["x-frame-options"] == "SAMEORIGIN"


def test_the_real_app_sets_them(monkeypatch):
    from backend.main import app
    names = [m.cls.__name__ for m in app.user_middleware]
    assert "SecurityHeadersMiddleware" in names


def test_the_audit_log_migration_refuses_update_delete_and_truncate():
    sql = (REPO / "analytics/db/migrations/0072_audit_log_append_only.sql").read_text(encoding="utf-8")
    code = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "BEFORE UPDATE OR DELETE ON app.audit_log" in code and "BEFORE TRUNCATE ON app.audit_log" in code
    assert not re.search(r"\bDROP\s+TABLE\b|\bDELETE\s+FROM\b|\bTRUNCATE\s+TABLE\b", code, re.I)
    assert all(";" not in l for l in sql.splitlines() if l.strip().startswith("--")), "the runner splits on semicolons"


def test_vercel_keeps_its_security_headers():
    cfg = json.loads((REPO / "frontend/vercel.json").read_text(encoding="utf-8"))
    keys = {h["key"] for block in cfg["headers"] for h in block["headers"]}
    assert {"Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Strict-Transport-Security"} <= keys
