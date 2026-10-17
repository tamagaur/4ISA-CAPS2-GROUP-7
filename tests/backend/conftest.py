"""
tests/backend/conftest.py — shared by every backend test.

Since 2026-09-28 get_current_user checks the account and its session in the
database on every request (backend/deps.py:_load_active_principal). Each
test module fakes only the queries its own router issues, so by default that
check is replaced with "trust the signed token", which is what those tests
were written against. Tests of the check itself opt back in with
@pytest.mark.real_session_check (tests/backend/test_accounts.py).

Permissions (backend/permissions.py) default to the role presets with no
per-user overrides, as if migration 0034's table were there but empty, so no
module has to fake the override lookup. Tests of the lookup itself opt back in
with @pytest.mark.real_permission_store (tests/backend/test_permissions.py).

No test may send a real email: backend.mailer.send is replaced for every test
by the `outbox` list, which a test can ask for to see what would have gone out.
Email also counts as set up (mailer.is_configured), whatever this machine's
.env holds; tests of the no-email case switch it off themselves.

Two-step sign-in (backend/mfa.py) defaults to "migration 0035 not applied":
password-only sign-in, no user_mfa queries, so no module has to fake that
table. tests/backend/test_mfa.py opts back in with @pytest.mark.real_mfa.
"""
from __future__ import annotations

import os

import pytest

from backend import deps, mailer, mfa, permissions
from backend.login_limiter import failure_log_budget, login_limiter, reset_limiter


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_session_check: run get_current_user's database check instead of skipping it"
    )
    config.addinivalue_line(
        "markers", "real_permission_store: look permissions up in the database instead of presets only"
    )
    config.addinivalue_line(
        "markers", "real_mfa: two-step sign-in reads its table instead of acting as if 0035 weren't applied"
    )


@pytest.fixture(autouse=True)
def _trust_signed_tokens(request, monkeypatch):
    if request.node.get_closest_marker("real_session_check") is None:
        monkeypatch.setattr(deps, "_load_active_principal", lambda db, payload: payload)


@pytest.fixture(autouse=True)
def _presets_only(request, monkeypatch):
    if request.node.get_closest_marker("real_permission_store") is None:
        monkeypatch.setitem(permissions._ready_cache, "value", True)
        monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id: {})
    else:
        # Every such test starts as a fresh server would: nothing cached.
        monkeypatch.setitem(permissions._ready_cache, "value", False)
        monkeypatch.setitem(permissions._ready_cache, "checked_at", 0.0)


@pytest.fixture(autouse=True)
def _mfa_not_applied(request, monkeypatch):
    if request.node.get_closest_marker("real_mfa") is None:
        monkeypatch.setattr(mfa, "mfa_ready", lambda db: False)


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        mailer, "send",
        lambda to, subject, body, html=None, inline_images=None: sent.append(
            {"to": to, "subject": subject, "body": body, "html": html, "inline_images": inline_images}
        ),
    )
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    return sent


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """create_access_token/decode_access_token (backend/auth_utils.py) refuse
    to run with no JWT_SECRET_KEY set. Worktrees don't all carry a .env, so
    tests supply a throwaway secret rather than depending on one being
    present; a real .env's value (if loaded) is left alone."""
    if not os.environ.get("JWT_SECRET_KEY"):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-not-for-production")


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
