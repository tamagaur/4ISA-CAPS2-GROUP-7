"""
backend.routers.auth — POST /auth/login, POST /auth/register.

Story #89: login with hashed credentials.

POST /auth/login is public (no Depends(get_current_user) — that would be
circular: you need a token to get a token).
POST /auth/register requires an existing admin token (Depends(get_current_user)
+ a role check) — there is deliberately no public self-registration route,
per the story's "admin-only" requirement. The very first admin account is
seeded once, outside the API (see backend/scripts/seed_admin.py), not
created through this endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth_utils import create_access_token, hash_password, verify_password
from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.auth import LoginRequest, LoginResponse, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    row = db.execute(
        text("SELECT user_id, password_hash, role, full_name FROM Users WHERE email = :email"),
        {"email": body.email},
    ).mappings().first()

    # Same error for "no such user" and "wrong password" — do not reveal
    # which one it was; that would let an attacker enumerate valid emails.
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password.",
    )
    if row is None:
        raise invalid_credentials
    if not verify_password(body.password, row["password_hash"]):
        raise invalid_credentials

    token = create_access_token(
        user_id=row["user_id"], email=body.email, role=row["role"], full_name=row["full_name"]
    )
    return LoginResponse(access_token=token, role=row["role"], full_name=row["full_name"])


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> LoginResponse:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin may register new users.",
        )

    existing = db.execute(
        text("SELECT 1 FROM Users WHERE email = :email"), {"email": body.email}
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    password_hash = hash_password(body.password)
    row = db.execute(
        text(
            "INSERT INTO Users (email, password_hash, full_name, role) "
            "VALUES (:email, :password_hash, :full_name, :role) "
            "RETURNING user_id, role, full_name"
        ),
        {"email": body.email, "password_hash": password_hash, "full_name": body.full_name, "role": body.role},
    ).mappings().first()
    db.commit()

    token = create_access_token(
        user_id=row["user_id"], email=body.email, role=row["role"], full_name=row["full_name"]
    )
    return LoginResponse(access_token=token, role=row["role"], full_name=row["full_name"])
