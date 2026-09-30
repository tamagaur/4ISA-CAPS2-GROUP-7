"""
tests/backend/conftest.py — shared by every backend test.

Since 2026-09-28 get_current_user checks the account and its session in the
database on every request (backend/deps.py:_load_active_principal). Each
test module fakes only the queries its own router issues, so by default that
check is replaced with "trust the signed token", which is what those tests
were written against. Tests of the check itself opt back in with
@pytest.mark.real_session_check (tests/backend/test_accounts.py).

No test may send a real email: backend.mailer.send is replaced for every test
by the `outbox` list, which a test can ask for to see what would have gone out.
Email also counts as set up (mailer.is_configured), whatever this machine's
.env holds; tests of the no-email case switch it off themselves.
"""
from __future__ import annotations

import pytest

from backend import deps, mailer
from backend.login_limiter import failure_log_budget, login_limiter, reset_limiter


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_session_check: run get_current_user's database check instead of skipping it"
    )


@pytest.fixture(autouse=True)
def _trust_signed_tokens(request, monkeypatch):
    if request.node.get_closest_marker("real_session_check") is None:
        monkeypatch.setattr(deps, "_load_active_principal", lambda db, payload: payload)


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        mailer, "send", lambda to, subject, body: sent.append({"to": to, "subject": subject, "body": body})
    )
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    return sent


@pytest.fixture(autouse=True)
def _fresh_limiters():
    # Every TestClient request comes from the same address, so counts would
    # otherwise carry from one test into the next.
    login_limiter.reset()
    reset_limiter.reset()
    failure_log_budget.reset()
    yield
    login_limiter.reset()
    reset_limiter.reset()
    failure_log_budget.reset()
