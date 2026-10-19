"""
backend.routers.users — user management (needs users.manage; see
backend/permissions.py).

  GET    /users                      every account, with its status and last sign-in
  PATCH  /users/{user_id}            name, email, role
  DELETE /users/{user_id}
  POST   /users/{user_id}/send-link  a new invite (invite pending) or a
                                     password reset link (active account)
  POST   /users/me/avatar            the signed-in user's own profile
                                     picture (any authenticated account, not
                                     just users.manage — see backend/avatar.py)
  POST   /users/{user_id}/mfa/reset  turns off someone's two-step sign-in
                                     (lost phone and recovery codes)

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

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import account_links, audit, avatar, mfa
from backend.api_errors import ApiError
from backend.deps import TokenPayload, get_current_user, get_db
from backend.permissions import LAST_ADMIN, admin_count, require_permission
from backend.schemas.auth import SendLinkResponse
from backend.schemas.users import UserOut, UserUpdate
from backend.sessions import revoke_user_sessions

router = APIRouter(prefix="/users", tags=["users"])

# last_sign_in_at (2026-10-02, for the security audit): the latest sign-in
# from user_session, which records every sign-in with its date and time
# (migration 0023; older sign-ins backfilled from the audit log with their
# user_id). Read there rather than copied onto users, so there is no second
# copy to keep in step and no migration. NULL = never signed in.
#
# invite_expires_at (2026-10-18, Audrey: show "Invite expired" in the table):
# when the account's newest invite link stops working, from auth_token
# (migration 0031). Only for an account still without a password; NULL for an
# active one, or an invited one that has no link on record. Issuing a new link
# retires the old ones, so the newest expiry is the one that counts.
USER_COLUMNS = (
    "user_id, email, full_name, role, created_at, avatar_path, "
    "CASE WHEN password_hash IS NULL THEN 'invited' ELSE 'active' END AS status, "
    "(SELECT max(s.started_at) FROM user_session s WHERE s.user_id = users.user_id) AS last_sign_in_at, "
    "CASE WHEN password_hash IS NULL THEN (SELECT max(t.expires_at) FROM auth_token t "
    "WHERE t.user_id = users.user_id AND t.purpose = 'invite') END AS invite_expires_at"
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
    with_mfa = mfa.enabled_user_ids(db)
    return [UserOut(**row, mfa_enabled=row["user_id"] in with_mfa) for row in rows]


@router.post("/me/avatar", response_model=UserOut)
def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> UserOut:
    """Sets the signed-in user's own profile picture. Never another user's —
    the target is always current_user.user_id from the auth dependency, not
    a value the request body could supply.

    Image bytes never reach Postgres: the upload is validated, re-encoded to
    a 128x128 WebP (which also strips any EXIF/GPS data) and put in the
    `avatars` Storage bucket (backend/avatar.py); only the resulting object
    path is written here.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length.isdigit() and int(content_length) > avatar.MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Image must be 2 MB or smaller.",
        )
    raw = avatar.read_capped(file.file)
    webp = avatar.to_avatar_webp(raw)
    object_name = avatar.new_object_name(current_user.user_id)
    avatar.upload(object_name, webp)

    old_avatar_path = db.execute(
        text("SELECT avatar_path FROM users WHERE user_id = :user_id"), {"user_id": current_user.user_id}
    ).scalar()
    row = db.execute(
        text(f"UPDATE users SET avatar_path = :avatar_path WHERE user_id = :user_id RETURNING {USER_COLUMNS}"),
        {"avatar_path": object_name, "user_id": current_user.user_id},
    ).mappings().first()
    db.commit()

    # Each upload gets a fresh random object name, so the old one is now an
    # orphan in Storage. Delete it only after the new path is durably
    # committed; a failed delete logs and continues (backend/avatar.py).
    if old_avatar_path:
        avatar.delete(old_avatar_path)

    return UserOut(**row)


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
    return UserOut(**row, mfa_enabled=mfa.is_enabled(db, user_id))


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
        purpose=purpose, email=user["email"], full_name=user["full_name"], token=token, minutes=minutes,
        expires_at=expires_at, invited_by=current_user.full_name, role=user["role"],
    )
    return SendLinkResponse(
        purpose=purpose,
        email_sent=problem is None,
        setup_link=account_links.link_url(token) if problem else None,
        expires_at=expires_at,
        email_problem=problem,
    )


@router.post("/{user_id}/mfa/reset", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def reset_mfa(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(manage_users),
) -> None:
    """For someone who lost their phone and their recovery codes: turns
    their two-step sign-in off and signs them out. If their role requires it
    (MFA_REQUIRED_ROLES), they set it up again at their next sign-in. Your
    own is turned off from your account, with a code, not from here."""
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't reset your own two-step sign-in here. Use Account security, or ask another admin.",
        )
    user = _get_user(db, user_id)
    if not mfa.mfa_ready(db) or not mfa.remove(db, user_id):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Two-step sign-in isn't on for {user['email']}.",
        )
    revoke_user_sessions(db, user_id)
    audit.record(db, "Two-Step Sign-In Reset", user["email"], actor=current_user)
    db.commit()
