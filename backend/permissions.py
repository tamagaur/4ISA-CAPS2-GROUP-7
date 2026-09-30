"""
backend.permissions — who may open and do what (Yuan's permissions
proposal, revised 2026-09-30 after Audrey's review).

THE MODEL
---------
Each user has one role (users.role: admin | manager | staff), which gives a
preset. An admin can then add or remove single permissions for one user
(user_permission_override, migration 0034):

    effective = role preset + per-user grants - per-user removals

An admin always has everything, and overrides don't apply to them.

CHECKED ON EVERY REQUEST
------------------------
require_permission(*keys) is a FastAPI dependency. It runs after
get_current_user, which already re-reads the account and its session from
the database on every request (backend/deps.py), and reads the user's
overrides on every request too. Nothing about permissions is in the token,
so unticking a box takes effect on the user's next request, not when the
8-hour token expires.

ANY OF SEVERAL KEYS
-------------------
Permissions attach to data, not pages. An endpoint accepts any of the keys
it is declared with: GET /abc takes abc.view OR forecast.view, because the
SKU Forecast page calls it too. So unticking one page never breaks another
page the user can still see (tests/backend/test_permissions.py's page smoke
test checks every preset with every one box unticked). Reading the product
catalog (GET /sku) needs sign-in only: the ABC, Reorder and SKU Forecast
pages all read product and brand names from it.

BEFORE MIGRATION 0034 IS APPLIED
--------------------------------
This code can be deployed before the table exists without changing anyone's
access. permissions_ready() looks the table up (to_regclass, which never
errors); until it exists:
  - enforcement uses the role presets with no overrides. The staff preset is
    today's staff access, and admins keep everything;
  - GET /auth/me answers 404 permissions_not_ready, which the frontend
    already treats as "keep today's behaviour" (its `legacy` mode, which
    also hides the Manager role and the Permissions screen);
  - the /admin/... permission endpoints answer 503 permissions_not_ready.
Once Kelvin applies 0034 through the runner, it switches over within a
minute, with no restart.
"""
from __future__ import annotations

import time

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api_errors import ApiError
from backend.deps import TokenPayload, get_current_user, get_db

ROLES = ("admin", "manager", "staff")

# The catalog: one entry per permission, grouped by page as the admin screen
# shows them. The frontend never hard-codes this; it reads it from
# GET /admin/permissions/catalog. A new key is off for Manager and Staff
# until someone adds it to their preset below (deny by default).
CATALOG = [
    {"key": "dashboard.view", "label": "View the dashboard", "group": "Dashboard",
     "description": "Sales, stock and forecast overview."},
    {"key": "abc.view", "label": "View ABC classification", "group": "ABC classification",
     "description": "Which products are tier A, B or C."},
    {"key": "forecast.view", "label": "View forecasts", "group": "Predictive / SKU Forecast",
     "description": "Each product’s forecast."},
    {"key": "category_trends.view", "label": "View category trends", "group": "Category Trends",
     "description": "How each category is moving."},
    {"key": "sku.view", "label": "View SKU Management", "group": "SKU Management",
     "description": "The product list."},
    {"key": "sku.edit", "label": "Add or edit SKUs", "group": "SKU Management",
     "description": "Changes the product master."},
    {"key": "lp.view", "label": "View reorder recommendations", "group": "LP / Reorder",
     "description": "Also the LP figures shown on other pages."},
    {"key": "lp.decide", "label": "Accept or dismiss recommendations", "group": "LP / Reorder",
     "description": "Changes what SSM orders."},
    {"key": "audit_log.view", "label": "View the audit log", "group": "Audit Log",
     "description": "Who changed what, and when."},
    {"key": "upload.run", "label": "Use Data Management", "group": "Data Management",
     "description": "Uploads (Module 07); a mock page for now."},
    {"key": "users.manage", "label": "Manage users", "group": "User Management",
     "description": "Invite users, set roles and permissions."},
]
ALL_KEYS = tuple(entry["key"] for entry in CATALOG)

# The proposal's Design table. Staff's preset is also today's staff access,
# which is why this code changes nobody's access before 0034 is applied.
PRESETS = {
    "manager": ("dashboard.view", "abc.view", "forecast.view", "category_trends.view",
                "sku.view", "sku.edit", "lp.view", "lp.decide"),
    "staff": ("dashboard.view", "abc.view", "forecast.view", "category_trends.view",
              "sku.view", "lp.view"),
}

MISSING_PERMISSION = "You don't have access to this. Ask an admin."
NOT_READY = ("Per-user permissions aren't set up on this server yet "
             "(migration 0034_user_permissions.sql isn't applied).")


# ── Is the table there yet? ───────────────────────────────────────────────
# Cached: True for good once seen; a False is re-checked after a minute, so
# applying the migration takes effect without restarting the server.
_READY_RECHECK_SECONDS = 60
_ready_cache = {"value": False, "checked_at": 0.0}


def permissions_ready(db: Session) -> bool:
    if _ready_cache["value"]:
        return True
    now = time.monotonic()
    if now - _ready_cache["checked_at"] < _READY_RECHECK_SECONDS and _ready_cache["checked_at"]:
        return False
    found = db.execute(text("SELECT to_regclass('public.user_permission_override') IS NOT NULL")).scalar()
    _ready_cache.update(value=bool(found), checked_at=now)
    return bool(found)


def require_ready(db: Session) -> None:
    if not permissions_ready(db):
        raise ApiError(503, NOT_READY, code="permissions_not_ready")


def require_role_available(db: Session, role: str) -> None:
    """Manager exists once 0034 widens users.role's CHECK. Before that, say
    so instead of letting the constraint fail as a 500. (The frontend already
    hides Manager until GET /auth/me answers.)"""
    if role == "manager" and not permissions_ready(db):
        raise ApiError(503, NOT_READY, code="permissions_not_ready")


# ── At least one admin ─────────────────────────────────────────────────────
# users.manage can be given to someone who isn't an admin, so "only admins
# change roles" no longer guarantees an admin remains: every demotion or
# deletion of an admin checks it (PATCH/DELETE /users, PUT permissions).
LAST_ADMIN = "There must be at least one admin."


def admin_count(db: Session) -> int:
    """How many admins there are, with their rows locked until the caller
    commits, so two admins demoting each other at the same moment can't both
    pass the check."""
    return int(db.execute(text(
        "SELECT COUNT(*) FROM (SELECT user_id FROM users WHERE role = 'admin' FOR UPDATE) AS admins"
    )).scalar() or 0)


# ── The rule ───────────────────────────────────────────────────────────────
def preset(role: str) -> set[str]:
    if role == "admin":
        return set(ALL_KEYS)
    return set(PRESETS.get(role, ()))


def effective(role: str, overrides: dict[str, bool]) -> set[str]:
    """role preset + grants - removals; an admin has everything."""
    keys = preset(role)
    if role == "admin":
        return keys
    for key, granted in overrides.items():
        if key not in ALL_KEYS:
            continue
        if granted:
            keys.add(key)
        else:
            keys.discard(key)
    return keys


def normalize(role: str, overrides: dict[str, bool]) -> dict[str, bool]:
    """Only the overrides that differ from the role's preset (none for an
    admin): what is stored, and what the PUT body is meant to carry."""
    if role == "admin":
        return {}
    base = preset(role)
    return {key: bool(granted) for key, granted in overrides.items() if (key in base) != bool(granted)}


def load_overrides(db: Session, user_id: int) -> dict[str, bool]:
    """The user's stored overrides, read fresh (no cache: see CHECKED ON
    EVERY REQUEST). Empty until migration 0034 is applied."""
    if not permissions_ready(db):
        return {}
    rows = db.execute(
        text("SELECT permission_key, granted FROM user_permission_override WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).all()
    return {key: bool(granted) for key, granted in rows}


def permissions_for(db: Session, user: TokenPayload) -> set[str]:
    if user.role == "admin":
        return set(ALL_KEYS)
    return effective(user.role, load_overrides(db, user.user_id))


# ── The dependency ─────────────────────────────────────────────────────────
def require_permission(*keys: str):
    """A dependency that passes a signed-in user holding ANY of `keys`, and
    otherwise raises the contract's 403:
        {"detail": "...", "code": "missing_permission", "permission": keys[0]}
    Returns the TokenPayload, like get_current_user, so routers keep their
    `current_user` parameter."""
    unknown = [key for key in keys if key not in ALL_KEYS]
    if not keys or unknown:
        raise ValueError(f"require_permission needs catalog keys; got {keys!r}")

    def dependency(
        current_user: TokenPayload = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> TokenPayload:
        if permissions_for(db, current_user) & set(keys):
            return current_user
        raise ApiError(403, MISSING_PERMISSION, code="missing_permission", permission=keys[0])

    # Read by tests/backend/test_permissions.py's guard and page smoke tests.
    dependency.permission_keys = keys
    return dependency


def can_see_lp(db: Session, user: TokenPayload) -> bool:
    """lp.view also covers the LP figures on other pages: the Dashboard,
    ABC and SKU Management leave them out for a user without it, rather
    than relying on the Reorder tab being hidden."""
    return "lp.view" in permissions_for(db, user)
