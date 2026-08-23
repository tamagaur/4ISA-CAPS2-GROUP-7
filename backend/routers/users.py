"""
backend.routers.users — GET /users, PATCH /users/{user_id}, DELETE /users/{user_id}.

Admin-only user management (list/update/delete). Creating a user still goes
through POST /auth/register (backend/routers/auth.py, Story #89) — that
endpoint already owns hashing + the admin-only + duplicate-email checks, so
this router isn't a second implementation of "create," only list/edit/remove.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth_utils import hash_password
from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.users import UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _require_admin(current_user: TokenPayload) -> None:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin may manage users.",
        )


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> list[UserOut]:
    _require_admin(current_user)
    rows = db.execute(
        text("SELECT user_id, email, full_name, role, created_at FROM users ORDER BY user_id")
    ).mappings().all()
    return [UserOut(**row) for row in rows]


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> UserOut:
    _require_admin(current_user)

    existing = db.execute(
        text("SELECT user_id FROM users WHERE user_id = :user_id"), {"user_id": user_id}
    ).first()
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if body.email is not None:
        dupe = db.execute(
            text("SELECT 1 FROM users WHERE email = :email AND user_id != :user_id"),
            {"email": body.email, "user_id": user_id},
        ).first()
        if dupe is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists.",
            )

    fields: dict[str, str] = {}
    if body.email is not None:
        fields["email"] = body.email
    if body.full_name is not None:
        fields["full_name"] = body.full_name
    if body.role is not None:
        fields["role"] = body.role
    if body.password is not None:
        fields["password_hash"] = hash_password(body.password)

    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update.",
        )

    set_clause = ", ".join(f"{col} = :{col}" for col in fields)
    row = db.execute(
        text(
            f"UPDATE users SET {set_clause} WHERE user_id = :user_id "
            "RETURNING user_id, email, full_name, role, created_at"
        ),
        {**fields, "user_id": user_id},
    ).mappings().first()
    db.commit()
    return UserOut(**row)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    _require_admin(current_user)

    # A self-delete would lock the admin out mid-session with no one left
    # to undo it from the UI — force that to happen from another admin account.
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )

    result = db.execute(text("DELETE FROM users WHERE user_id = :user_id"), {"user_id": user_id})
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
