"""A password, token, secret or key never appears in a response body or a log line (QA 2026-10-24, finding 16)."""
from __future__ import annotations

import logging
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.error_redaction import clean_error
from backend.main import app

SECRET = "Hunter2-secret-VALUE"
REPO = pathlib.Path(__file__).resolve().parents[2]


class NoDatabase:
    def __getattr__(self, name):
        raise AssertionError("reached the database")


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: NoDatabase()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _admin():
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=2, email="admin@ssmcapstone.com", role="admin", full_name="Admin"))


CASES = [
    ("/auth/login", {"password": SECRET}),                                          # email missing: the reported case
    ("/auth/login", {"email": "not-an-email", "password": SECRET}),
    ("/auth/login", {"email": "a@ssmcapstone.com", "password": SECRET * 100}),      # too long: used to echo it all
    ("/auth/login", {"email": "a@ssmcapstone.com", "password": 12345, "extra": SECRET}),
    ("/auth/login/verify", {"code": SECRET, "mfa_token": SECRET}),                   # the code and the step token
    ("/auth/login/setup/confirm", {"code": SECRET, "mfa_token": SECRET}),
    ("/auth/mfa/confirm", {"code": SECRET}),
    ("/auth/mfa/disable", {"code": SECRET, "password": SECRET}),
    ("/auth/set-password", {"token": SECRET, "password": SECRET}),
    ("/auth/link-info", {"token": SECRET}),
    ("/auth/register", {"email": "new@ssmcapstone.com", "full_name": "N", "password": SECRET}),   # extra=forbid
]


@pytest.mark.parametrize("path,body", CASES)
def test_a_422_never_echoes_a_secret(client, path, body):
    _admin()
    resp = client.post(path, json=body)
    assert resp.status_code != 404, path        # a path that does not exist proves nothing
    assert SECRET not in resp.text, resp.text


def test_the_reported_case_is_a_422_that_names_the_missing_field_only(client):
    resp = client.post("/auth/login", json={"password": SECRET})
    assert resp.status_code == 422
    assert SECRET not in resp.text
    assert any(e["loc"][-1] == "email" for e in resp.json()["detail"])      # the useful part is kept


def test_a_body_that_is_not_json_does_not_come_back(client):
    resp = client.post("/auth/login", content=b'{"password": "' + SECRET.encode() + b'" oops',
                       headers={"content-type": "application/json"})
    assert resp.status_code == 422 and SECRET not in resp.text


def test_a_plain_text_body_does_not_come_back(client):
    resp = client.post("/auth/login", content=SECRET.encode(), headers={"content-type": "text/plain"})
    assert resp.status_code == 422 and SECRET not in resp.text


def test_nothing_is_logged_with_the_secret(client, caplog):
    caplog.set_level(logging.DEBUG)
    for path, body in CASES:
        client.post(path, json=body)
    client.post("/auth/login", content=SECRET.encode(), headers={"content-type": "text/plain"})
    assert SECRET not in caplog.text


def test_a_secret_nested_in_a_larger_input_is_hidden_but_its_siblings_are_not():
    error = {"type": "x", "loc": ["body", "profile"], "msg": "bad",
             "input": {"name": "Ana", "password": SECRET, "nested": [{"api_key": SECRET, "n": 1}]}}
    out = clean_error(error)
    assert SECRET not in str(out) and out["input"]["name"] == "Ana" and out["input"]["nested"][0]["n"] == 1


def test_an_ordinary_field_keeps_its_input():
    out = clean_error({"type": "int_parsing", "loc": ["query", "run_id"], "msg": "m", "input": "abc"})
    assert out["input"] == "abc"


def test_the_server_never_logs_a_request_or_a_validation_error():
    """The logger calls in backend/ name an object or an address; none passes a request, a body or a validation error."""
    offenders = []
    for path in (REPO / "backend").rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\blogger\.\w+\(", line) and re.search(r"\b(body|payload|request(?=[.,)])|exc\.errors|\.errors\(\)|password|token|secret)\b", line, re.I):
                offenders.append(f"{path.relative_to(REPO).as_posix()}:{n}")
    assert offenders == []
