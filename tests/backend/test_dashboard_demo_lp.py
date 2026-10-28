"""GET /dashboard's demonstration block and lp.view (audit BE-13, 2026-10-28).

The block was added after _strip_lp_fields ran, so the demonstration order plan and policy comparison (LP-derived,
demo.dm_category_lp) reached users without lp.view. They are now left out for such a user; the rest of the block
(forecasts, stock, dead stock) is not LP and stays."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import demo_data, permissions, response_cache
from backend.auth_utils import TokenPayload, create_access_token
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.routers import dashboard
from tests.backend.test_dashboard import FakeSession

URL = "/dashboard?period=2026-02&start_period=2025-03&principal=delmonte"


@pytest.fixture(autouse=True)
def _demo_on(monkeypatch):
    response_cache.invalidate()
    monkeypatch.setattr(dashboard, "demo_data_enabled", lambda mode: True)
    monkeypatch.setattr(demo_data, "index", lambda db, principal: {"series": []})
    monkeypatch.setattr(demo_data, "monthly_totals", lambda db: {"months": []})
    monkeypatch.setattr(demo_data, "forecasts", lambda db: [])
    monkeypatch.setattr(demo_data, "stock", lambda db: [])
    monkeypatch.setattr(demo_data, "order_plan", lambda db: {"available": True, "items": [{"category": "DAIRY"}]})
    monkeypatch.setattr(demo_data, "policy_comparison", lambda db: {"available": True})
    monkeypatch.setattr(demo_data, "dead_stock", lambda db: {"items": []})
    yield
    response_cache.invalidate()


def _get(user: TokenPayload) -> dict:
    app.dependency_overrides[get_db] = lambda: FakeSession(recommendation_count=7)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as c:
            headers = {"Authorization": f"Bearer {create_access_token(user_id=1, email='a@x', role='admin', full_name='A')}"}
            return c.get(URL, headers=headers).json()
    finally:
        app.dependency_overrides.clear()


def test_demonstration_order_plan_and_policy_comparison_need_lp_view():
    staff = frozenset(permissions.PRESETS["staff"]) - {"lp.view"}
    hidden = _get(TokenPayload(2, "s@x", "staff", "S", permissions=staff))["demonstration"]
    assert hidden["order_plan"] is None and hidden["policy_comparison"] is None
    assert hidden["dead_stock"] == {"items": []}, "the non-LP parts of the block stay"
    shown = _get(TokenPayload(1, "a@x", "admin", "A", permissions=frozenset(permissions.ALL_KEYS)))["demonstration"]
    assert shown["order_plan"]["items"] == [{"category": "DAIRY"}] and shown["policy_comparison"] == {"available": True}
