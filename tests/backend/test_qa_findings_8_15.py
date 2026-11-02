"""QA 2026-10-24 findings 9-15 that were fixed (8 and 15 are decisions, reported not changed)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.routers import dashboard_range
from backend.routers import reorder_approval as ra
from backend.schemas.recommendations import QuantityChangeRequest, RecommendationDecision
from backend.schemas.sku import SKUCreate, SKUUpdate
from tests.backend.test_reorder_approval import ADMIN, _DB
from tests.backend.test_recommendations import FakeResult


class NoDatabase:
    info: dict = {}      # the response cache reads db.info before the route runs

    def __getattr__(self, name):
        raise AssertionError("reached the database")


@pytest.fixture
def admin():
    app.dependency_overrides[get_db] = lambda: NoDatabase()
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=2, email="admin@ssmcapstone.com", role="admin", full_name="Admin"))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


# 10 - SKU master text
@pytest.mark.parametrize("bad", ["", "   ", "x" * 201, pytest.param("x" * 5_000_000, id="5MB")])
def test_a_sku_name_must_be_present_and_bounded(bad):
    with pytest.raises(ValidationError):
        SKUCreate(sku_code="12345678", principal="unilever", product_name=bad)
    with pytest.raises(ValidationError):
        SKUUpdate(product_name=bad)


@pytest.mark.parametrize("bad", ["abc", "-5", "", "0", "12x24", "1e3", "٣٣"])
def test_a_pack_size_must_be_a_positive_number(bad):
    with pytest.raises(ValidationError):
        SKUUpdate(pack_size=bad)


def test_good_sku_text_passes_and_is_trimmed():
    u = SKUUpdate(product_name="  Dove 90g ", pack_size=" 144 ", brand="  ", notes="n")
    assert (u.product_name, u.pack_size, u.brand) == ("Dove 90g", "144", None)
    assert SKUUpdate(pack_size="24.5").pack_size == "24.5" and SKUUpdate().product_name is None


def test_a_long_brand_or_note_is_refused():
    with pytest.raises(ValidationError):
        SKUUpdate(brand="b" * 101)
    with pytest.raises(ValidationError):
        SKUUpdate(notes="n" * 2001)


def test_a_del_monte_category_row_cannot_be_renamed_by_hand(monkeypatch):
    from tests.backend.test_sku_writes import WritableSession  # noqa: F401  (same fake)
    from backend.routers import sku as sku_router

    class Session:
        writes = []
        rolled_back = False

        def execute(self, stmt, params=None):
            sql = str(stmt)
            if sql.lstrip().startswith("SELECT product_name, pack_size, brand, notes, grain"):
                return FakeResult([{"product_name": "ACE", "pack_size": None, "brand": None, "notes": None, "grain": "category"}])
            if sql.lstrip().startswith("UPDATE"):
                self.writes.append(sql)
            return FakeResult([])

        def rollback(self):
            self.rolled_back = True

    db = Session()
    with pytest.raises(HTTPException) as err:
        sku_router.update_sku(7, SKUUpdate(product_name="QA"), db=db, current_user=ADMIN)
    assert err.value.status_code == 400 and db.writes == []


# 11 / 13 - bounds and filters
def test_a_negative_audit_log_limit_is_a_422_not_a_503(admin):
    assert admin.get("/audit-log?limit=-1").status_code == 422


@pytest.mark.parametrize("q", ["from=abc&to=abc", "from=2026-01-01", "to=2026-01-31"])
def test_inventory_movement_dates_are_dates_and_come_as_a_pair(admin, q):
    assert admin.get(f"/inventory/movement?principal=delmonte&{q}").status_code == 422


@pytest.mark.parametrize("q", ["from=2026-01-01", "to=2026-01-31"])
def test_a_lone_recommendations_date_is_a_422(admin, q):
    resp = admin.get(f"/recommendations?principal=unilever&{q}")
    assert resp.status_code == 422 and "together" in resp.json()["detail"]


@pytest.mark.parametrize("run_id", ["99999999999999999999", "2147483648", "0"])
def test_a_run_id_outside_the_integer_range_is_a_422(admin, run_id):
    assert admin.get(f"/dashboard/accuracy?principal=unilever&run_id={run_id}").status_code == 422


# 9 - an inverted range
def test_a_start_after_the_end_is_refused_not_swapped():
    with pytest.raises(HTTPException) as err:
        dashboard_range.resolve_range(NoDatabase(), "2025-03", "2026-02", "unilever")
    assert err.value.status_code == 422 and "after" in err.value.detail


# 12 - grants
def _grant(body_granted, returning):
    class Db(_DB):
        def execute(self, stmt, params=None):
            sql = " ".join(str(stmt).split())
            if "lp_direct_apply_grant" in sql and ("INSERT" in sql or "DELETE" in sql):
                self.sql.append((sql, dict(params or {})))
                return FakeResult([{"user_id": 1}] if returning else [])
            return super().execute(stmt, params)

    db = Db(users={1: {"user_id": 1, "email": "planner@ssmcapstone.com", "role": "staff"}})
    ra.set_direct_apply_grant(1, ra.DirectApplyGrantBody(granted=body_granted), db=db, admin=ADMIN)
    return [a for a in db.audit if a["action"].startswith("Direct Apply")]


def test_a_real_grant_or_revoke_is_audited_once():
    assert [a["action"] for a in _grant(True, True)] == ["Direct Apply Granted"]
    assert [a["action"] for a in _grant(False, True)] == ["Direct Apply Revoked"]


def test_a_replayed_grant_or_a_revoke_with_nothing_to_revoke_writes_no_audit_entry():
    assert _grant(True, False) == []
    assert _grant(False, False) == []


# 14 - types
@pytest.mark.parametrize("bad", ["13824", True, False, None])
def test_a_quantity_must_be_a_json_number(bad):
    with pytest.raises(ValidationError):
        QuantityChangeRequest(quantity=bad)


def test_numbers_still_pass():
    assert QuantityChangeRequest(quantity=13824, reason="count is wrong").quantity == 13824.0
    assert QuantityChangeRequest(quantity=12.5, reason="count is wrong").quantity == 12.5


@pytest.mark.parametrize("bad", ["yes", 1, "true"])
def test_reviewed_must_be_a_real_boolean(bad):
    with pytest.raises(ValidationError):
        RecommendationDecision(status="accepted", reviewed=bad)
    with pytest.raises(ValidationError):
        QuantityChangeRequest(quantity=1, reviewed=bad)


def test_a_decided_quantity_given_as_text_is_refused_and_a_real_one_passes():
    with pytest.raises(ValidationError):
        RecommendationDecision(status="accepted", decided_quantity="390")
    assert RecommendationDecision(status="accepted", decided_quantity=390, reviewed=True).reviewed is True
