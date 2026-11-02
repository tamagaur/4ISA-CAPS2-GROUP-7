"""
backend.routers.data_mode — GET /data-mode

What the requested data mode means for this database right now
(backend/data_mode.py): the placeholder window preview adds, and whether the
file-backed what-if forecasts and LP results exist — built by
scripts/build_preview_outputs.py — so the UI can say on every page what its
predictive and prescriptive figures are, before any page payload arrives.
In real mode there is nothing to describe beyond the mode itself.

Both modes also carry `coverage` (2026-10-20): each principal's first and
latest month of real sales (backend/marts.real_coverage). The layout asks
this on every page anyway, so it is where the date filter learns what "now"
is — the latest month with data, per principal — instead of a hand-edited
constant in the frontend.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend import marts
from backend.data_mode import PREVIEW, REAL, get_data_mode, preview_block
from backend.deps import TokenPayload, get_current_user, get_db

router = APIRouter(prefix="/data-mode", tags=["data-mode"])


@router.get("")
def get_data_mode_info(
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> dict:
    coverage = {"coverage": marts.real_coverage(db)}
    if mode != PREVIEW:
        return {"mode": REAL, **coverage}
    return {**preview_block(db), **coverage}
