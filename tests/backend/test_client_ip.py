"""
tests/backend/test_client_ip.py — backend/client_ip.py: on Render the request's
client address comes from Cloudflare's CF-Connecting-IP, never from
X-Forwarded-For; anywhere else nothing changes.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.client_ip import RealClientIPMiddleware
from backend.main import app as real_app


def make_client(enabled):
    app = FastAPI()

    @app.get("/ip")
    def ip(request: Request):
        return {"ip": request.client.host}

    app.add_middleware(RealClientIPMiddleware, enabled=enabled)
    return TestClient(app)


def test_on_render_the_cloudflare_address_wins_over_forwarded_for():
    res = make_client(True).get(
        "/ip", headers={"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "203.0.113.77"}
    )
    assert res.json() == {"ip": "198.51.100.7"}


def test_ipv6_addresses_are_accepted():
    res = make_client(True).get("/ip", headers={"CF-Connecting-IP": " 2001:db8::1 "})
    assert res.json() == {"ip": "2001:db8::1"}


def test_a_header_that_is_not_an_ip_is_ignored():
    res = make_client(True).get("/ip", headers={"CF-Connecting-IP": "203.0.113.77, 1.1.1.1"})
    assert res.json() == {"ip": "testclient"}


def test_without_the_header_the_address_is_unchanged():
    res = make_client(True).get("/ip", headers={"X-Forwarded-For": "203.0.113.77"})
    assert res.json() == {"ip": "testclient"}


def test_off_render_the_header_is_ignored():
    res = make_client(False).get("/ip", headers={"CF-Connecting-IP": "198.51.100.7"})
    assert res.json() == {"ip": "testclient"}


def test_turns_on_only_when_render_says_so(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    assert RealClientIPMiddleware(app=None).enabled is True
    monkeypatch.delenv("RENDER")
    assert RealClientIPMiddleware(app=None).enabled is False


def test_the_api_uses_it():
    assert any(m.cls is RealClientIPMiddleware for m in real_app.user_middleware)
