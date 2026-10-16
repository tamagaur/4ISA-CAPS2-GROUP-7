"""
backend.routers.two_factor — a signed-in person's own two-step sign-in
(backend/mfa.py). Every route needs sign-in only: each acts on the caller's
own account.

  GET  /auth/mfa                 on or off, required or not, recovery codes left
  POST /auth/mfa/setup           a new secret for the QR code
  POST /auth/mfa/confirm         the first code turns it on -> recovery codes
  POST /auth/mfa/recovery-codes  a current code -> new recovery codes
  POST /auth/mfa/disable         a current code turns it off (not for a required role)

Turning it off and replacing recovery codes need a current code, so someone
using a browser left signed in can't quietly remove the second step. Wrong
codes there count toward the sign-in lock like wrong passwords. Wrong codes
answer 400, not 401: the frontend signs a person out on any 401.

An admin resets someone else's from User Management: POST
/users/{id}/mfa/reset (backend/routers/users.py).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend import audit, mfa
from backend.api_errors import ApiError
from backend.deps import TokenPayload, get_current_user, get_db
from backend.login_limiter import login_limiter
from backend.routers.auth import WRONG_CODE, _record_lockout, _too_many_attempts, wrong_code_message
from backend.schemas.auth import MfaCodeRequest, MfaSetupResponse, MfaStatus, RecoveryCodesResponse

router = APIRouter(prefix="/auth/mfa", tags=["auth"])

ALREADY_ON = "Two-step sign-in is already on for your account."
NOT_ON = "Two-step sign-in isn't on for your account."
REQUIRED = "Two-step sign-in is required for your role, so it can't be turned off. An admin can reset it."


def _require_available(db: Session) -> None:
    if not mfa.mfa_ready(db):
        raise ApiError(503, mfa.NOT_READY, code="mfa_not_ready")
    if not mfa.encryption_configured():
        raise ApiError(503, mfa.NOT_CONFIGURED, code="mfa_not_configured")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_code(db: Session, user: TokenPayload, code: str, client_ip: str) -> str:
    """A current app or recovery code for the caller, counted like a sign-in
    attempt. Returns 'app' or 'recovery'; raises 400 or 429 otherwise."""
    wait = login_limiter.retry_after(user.email, client_ip)
    if wait is not None:
        raise _too_many_attempts(wait)
    try:
        method = mfa.verify(db, user.user_id, code)
    except mfa.MfaUnavailable:
        db.rollback()
        raise ApiError(503, mfa.NOT_CONFIGURED, code="mfa_not_configured") from None
    if method is None:
        db.rollback()
        # A Lock (length + which limit tripped) since kelvin-etl's limiter change.
        lock = login_limiter.record_failure(user.email, client_ip)
        if lock is not None:
            _record_lockout(db, user.email, client_ip, lock)
            raise _too_many_attempts(lock.seconds)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=wrong_code_message(code))
    return method


@router.get("", response_model=MfaStatus)
def get_status(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> MfaStatus:
    available = mfa.mfa_ready(db) and mfa.encryption_configured()
    state = mfa.status(db, current_user.user_id) if available else {"enabled": False, "recovery_left": None}
    roles = sorted(mfa.required_roles()) if available else []
    return MfaStatus(
        available=available,
        enabled=state["enabled"],
        required=available and current_user.role in roles,
        required_roles=roles,
        recovery_codes_left=state["recovery_left"],
    )


@router.post("/setup", response_model=MfaSetupResponse)
def start_setup(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> MfaSetupResponse:
    _require_available(db)
    started = mfa.start_setup(db, current_user.user_id, current_user.email)
    if started is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ALREADY_ON)
    db.commit()
    secret, uri = started
    return MfaSetupResponse(secret=secret, otpauth_uri=uri)


@router.post("/confirm", response_model=RecoveryCodesResponse)
def confirm_setup(
    body: MfaCodeRequest,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> RecoveryCodesResponse:
    """Not counted toward the lock: a wrong code here can't get anyone into
    an account, it only leaves the setup unfinished."""
    _require_available(db)
    if mfa.is_enabled(db, current_user.user_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ALREADY_ON)
    codes = mfa.confirm_setup(db, current_user.user_id, body.code)
    if codes is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=WRONG_CODE)
    audit.record(db, "Two-Step Sign-In On", None, actor=current_user)
    db.commit()
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/recovery-codes", response_model=RecoveryCodesResponse)
def replace_recovery_codes(
    body: MfaCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> RecoveryCodesResponse:
    _require_available(db)
    if not mfa.is_enabled(db, current_user.user_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOT_ON)
    _check_code(db, current_user, body.code, _client_ip(request))
    codes = mfa.replace_recovery_codes(db, current_user.user_id)
    audit.record(db, "Recovery Codes Replaced", None, actor=current_user)
    db.commit()
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def disable(
    body: MfaCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    _require_available(db)
    if not mfa.is_enabled(db, current_user.user_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOT_ON)
    if mfa.is_required(current_user.role):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=REQUIRED)
    _check_code(db, current_user, body.code, _client_ip(request))
    mfa.remove(db, current_user.user_id)
    audit.record(db, "Two-Step Sign-In Off", None, actor=current_user)
    db.commit()
