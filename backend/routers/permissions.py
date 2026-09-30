"""
backend.routers.permissions — the admin side of Yuan's permissions
proposal: the catalog, and one user's role + overrides (read and save).

    GET /admin/permissions/catalog        users.manage
    GET /admin/users/{user_id}/permissions users.manage
    PUT /admin/users/{user_id}/permissions users.manage

GUARDRAILS on PUT (the proposal's "no lockout", plus self-promotion):
  - 409 self_lockout: you can't demote yourself or take away your own
    users.manage.
  - 409 self_promotion: nobody changes their own access in any other way
    either. Someone given users.manage without being an admin could
    otherwise make themselves an admin.
  - 409 last_admin: a change that would leave no admin is refused.
  - 422 unknown_permission: an override names a key not in the catalog.
Every saved change writes an audit_log entry: who, for whom, old -> new.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import audit
from backend.api_errors import ApiError
from backend.deps import TokenPayload, get_db
from backend.permissions import (
    ALL_KEYS, CATALOG, LAST_ADMIN, PRESETS, admin_count, effective, load_overrides, normalize,
    require_permission, require_ready,
)
from backend.schemas.permissions import CatalogResponse, UserPermissions, UserPermissionsUpdate
from backend.sessions import revoke_user_sessions

router = APIRouter(prefix="/admin", tags=["permissions"])

manage_users = require_permission("users.manage")


def _get_user(db: Session, user_id: int):
    row = db.execute(
        text("SELECT user_id, email, role FROM users WHERE user_id = :user_id"), {"user_id": user_id}
    ).mappings().first()
    if row is None:
        raise ApiError(404, "User not found.", code="user_not_found")
    return row


def _out(user_id: int, role: str, overrides: dict[str, bool]) -> UserPermissions:
    stored = normalize(role, overrides)
    return UserPermissions(
        user_id=user_id, role=role, overrides=stored, permissions=sorted(effective(role, stored)),
    )


def _describe(overrides: dict[str, bool]) -> str:
    if not overrides:
        return "none"
    return ", ".join(f"{'+' if granted else '-'}{key}" for key, granted in sorted(overrides.items()))


@router.get("/permissions/catalog", response_model=CatalogResponse)
def get_catalog(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(manage_users),
) -> CatalogResponse:
    require_ready(db)
    return CatalogResponse(
        permissions=CATALOG,
        roles={"admin": "all", **{role: list(keys) for role, keys in PRESETS.items()}},
    )


@router.get("/users/{user_id}/permissions", response_model=UserPermissions)
def get_user_permissions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(manage_users),
) -> UserPermissions:
    require_ready(db)
    user = _get_user(db, user_id)
    return _out(user["user_id"], user["role"], load_overrides(db, user_id))


@router.put("/users/{user_id}/permissions", response_model=UserPermissions)
def put_user_permissions(
    user_id: int,
    body: UserPermissionsUpdate,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(manage_users),
) -> UserPermissions:
    require_ready(db)
    unknown = sorted(key for key in body.overrides if key not in ALL_KEYS)
    if unknown:
        raise ApiError(422, "Unknown permission.", code="unknown_permission", permission=unknown[0])

    user = _get_user(db, user_id)
    old_role = user["role"]
    old_overrides = normalize(old_role, load_overrides(db, user_id))
    new_role = body.role
    new_overrides = normalize(new_role, body.overrides)
    old_keys = effective(old_role, old_overrides)
    new_keys = effective(new_role, new_overrides)

    if user_id == current_user.user_id and (new_role != old_role or new_overrides != old_overrides):
        losing = (old_role == "admin" and new_role != "admin") or (
            "users.manage" in old_keys and "users.manage" not in new_keys
        )
        if losing:
            raise ApiError(409, "You can't remove your own admin access.", code="self_lockout")
        raise ApiError(409, "You can't change your own access. Ask another admin.", code="self_promotion")

    if old_role == "admin" and new_role != "admin" and admin_count(db) <= 1:
        raise ApiError(409, LAST_ADMIN, code="last_admin")

    if new_role != old_role:
        db.execute(text("UPDATE users SET role = :role WHERE user_id = :user_id"),
                   {"role": new_role, "user_id": user_id})
        # Same as a role change from the Edit User form (PATCH /users):
        # that user signs in again and gets the new role's pages. A change
        # of ticks alone needs no sign-out; it applies on their next request.
        revoke_user_sessions(db, user_id)
    db.execute(text("DELETE FROM user_permission_override WHERE user_id = :user_id"), {"user_id": user_id})
    for key, granted in sorted(new_overrides.items()):
        db.execute(
            text("INSERT INTO user_permission_override (user_id, permission_key, granted, set_by, set_at) "
                 "VALUES (:user_id, :key, :granted, :set_by, now())"),
            {"user_id": user_id, "key": key, "granted": granted, "set_by": current_user.user_id},
        )
    if new_role != old_role or new_overrides != old_overrides:
        audit.record(
            db, "Change Access",
            f"{user['email']}: role {old_role} → {new_role}; "
            f"overrides {_describe(old_overrides)} → {_describe(new_overrides)}",
            actor=current_user,
        )
    db.commit()
    return _out(user_id, new_role, new_overrides)
