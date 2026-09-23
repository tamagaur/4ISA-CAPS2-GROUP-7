"""
backend.routers.data_mode — GET /data-mode

What the requested data mode means for this database right now
(backend/data_mode.py): the placeholder window preview adds, and whether the
file-backed what-if forecasts and LP results exist — built by
scripts/build_preview_outputs.py — so the UI can say on every page what its
predictive and prescriptive figures are, before any page payload arrives.
In real mode there is nothing to describe beyond the mode itself.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.data_mode import PREVIEW, REAL, get_data_mode, preview_block
from backend.deps import TokenPayload, get_current_user, get_db

router = APIRouter(prefix="/data-mode", tags=["data-mode"])


@router.get("")
def get_data_mode_info(
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> dict:
    if mode != PREVIEW:
        return {"mode": REAL}
    return preview_block(db)
