"""
backend.routers.users — user management (needs users.manage; see
backend/permissions.py).

  GET    /users                      every account, with its status
  PATCH  /users/{user_id}            name, email, role
  DELETE /users/{user_id}
  POST   /users/{user_id}/send-link  a new invite (invite pending) or a
                                     password reset link (active account)

Creating an account goes through POST /auth/register (backend/routers/auth.py),
which owns the permission and duplicate-email checks for create.

Since 2026-09-28 admins never set passwords: the account's owner sets one
through an emailed link (backend/account_links.py). A role or email change,
and deletion, end that user's open sessions (backend/sessions.py), so the
change applies on their next click. Every change is written to the audit log
(backend/audit.py).

Nobody can change their own role or delete their own account. Since
users.manage can be given to someone who isn't an admin, demoting or deleting
the last admin is refused explicitly (409 last_admin).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import account_links, audit
from backend.api_errors import ApiError
from backend.deps import TokenPayload, get_db
from backend.permissions import LAST_ADMIN, admin_count, require_permission, require_role_available
from backend.schemas.auth import SendLinkResponse
from backend.schemas.users import UserOut, UserUpdate
from backend.sessions import revoke_user_sessions

router = APIRouter(prefix="/users", tags=["users"])

USER_COLUMNS = (
    "user_id, email, full_name, role, created_at, "
    "CASE WHEN password_hash IS NULL THEN 'invited' ELSE 'active' END AS status"
)
_FIELD_LABELS = {"email": "email", "full_name": "name", "role": "role"}


# Every route here needs users.manage (Yuan's permissions proposal), checked
# per request against the database like every other permission.
manage_users = require_permission("users.manage")


def _get_user(db: Session, user_id: int):
    row = db.execute(
        text(f"SELECT {USER_COLUMNS} FROM users WHERE user_id = :user_id"), {"user_id": user_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return row


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(manage_users),
) -> list[UserOut]:
    rows = db.execute(text(f"SELECT {USER_COLUMNS} FROM users ORDER BY user_id")).mappings().all()
    return [UserOut(**row) for row in rows]


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(manage_users),
) -> UserOut:
    existing = _get_user(db, user_id)

    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update.",
        )
    if user_id == current_user.user_id and fields.get("role", existing["role"]) != existing["role"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't change your own role. Ask another admin to do it.",
        )
    if "role" in fields:
        require_role_available(db, fields["role"])
    if existing["role"] == "admin" and fields.get("role", "admin") != "admin" and admin_count(db) <= 1:
        raise ApiError(409, LAST_ADMIN, code="last_admin")
    if "email" in fields:
        dupe = db.execute(
            text("SELECT 1 FROM users WHERE lower(email) = lower(:email) AND user_id != :user_id"),
            {"email": fields["email"], "user_id": user_id},
        ).first()
        if dupe is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists.",
            )

    set_clause = ", ".join(f"{col} = :{col}" for col in fields)
    row = db.execute(
        text(f"UPDATE users SET {set_clause} WHERE user_id = :user_id RETURNING {USER_COLUMNS}"),
        {**fields, "user_id": user_id},
    ).mappings().first()

    changed = {col: value for col, value in fields.items() if existing[col] != value}
    # A new role or sign-in email must not ride on a session started before it.
    if changed.keys() & {"role", "email"}:
        revoke_user_sessions(db, user_id)
    if changed:
        details = "; ".join(f"{_FIELD_LABELS[col]}: {existing[col]} → {value}" for col, value in changed.items())
        audit.record(db, "Edit User", f"{existing['email']}: {details}", actor=current_user)
    db.commit()
    return UserOut(**row)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(manage_users),
) -> None:
    # A self-delete would lock the admin out mid-session with no one left
    # to undo it from the UI — force that to happen from another admin account.
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )
    existing = _get_user(db, user_id)
    if existing["role"] == "admin" and admin_count(db) <= 1:
        raise ApiError(409, LAST_ADMIN, code="last_admin")
    revoke_user_sessions(db, user_id)
    db.execute(text("DELETE FROM users WHERE user_id = :user_id"), {"user_id": user_id})
    audit.record(db, "Delete User", f"Removed {existing['email']} ({existing['role']})", actor=current_user)
    db.commit()


@router.post("/{user_id}/send-link", response_model=SendLinkResponse)
def send_link(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(manage_users),
) -> SendLinkResponse:
    """A fresh link for one account: a new invite while its invite is still
    pending, otherwise a password reset. Retires the account's older links."""
    user = _get_user(db, user_id)
    invited = user["status"] == "invited"
    purpose = "invite" if invited else "reset"
    minutes = account_links.INVITE_MINUTES if invited else account_links.ADMIN_RESET_MINUTES
    token, expires_at = account_links.issue(
        db, user_id=user_id, purpose=purpose, minutes=minutes, created_by=current_user.user_id
    )
    audit.record(db, "Invite Resent" if invited else "Reset Link Sent", user["email"], actor=current_user)
    db.commit()

    problem = account_links.send_link_email(
        purpose=purpose, email=user["email"], full_name=user["full_name"], token=token, minutes=minutes
    )
    return SendLinkResponse(
        purpose=purpose,
        email_sent=problem is None,
        setup_link=account_links.link_url(token) if problem else None,
        expires_at=expires_at,
        email_problem=problem,
    )
