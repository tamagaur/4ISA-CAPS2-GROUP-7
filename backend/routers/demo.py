"""
backend.routers.demo — the labelled demonstration series (CLAUDE.md hard rule 2).

OFF BY DEFAULT. Governed by the DM_DEMO_ENABLED environment variable (backend/demo_flag.py); with it unset or
false every request is a plain 404, so a deployment that has not switched it on behaves exactly as before.

  GET /demo/series?principal=unilever&key=<sku_code>        one series, SKU grain (DEC-03)
  GET /demo/series?principal=delmonte&key=<category_path>   one series, category grain
  GET /demo/index?principal=...                             every series with its origin counts (and taxonomy)

The payload rules, origins and reasons live in backend/demo_data.py. Reads only schema `demo`, which nothing in the
real path reads. The same payloads are wired into GET /forecast/{sku_id}, GET /recommendations and GET /dashboard
(behind the same switch).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend import demo_data
from backend.demo_flag import demo_enabled
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission

router = APIRouter(prefix="/demo", tags=["demo"])

# Re-exported for the callers and tests that named them here first.
DATA_SOURCE = demo_data.DATA_SOURCE
NOTE = demo_data.NOTE


@router.get("/series")
def get_demo_series(
    principal: str = Query(..., pattern="^(unilever|delmonte)$"),
    key: str = Query(..., description="sku_code (unilever) or category_path (delmonte)"),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("forecast.view")),
) -> dict:
    if not demo_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    payload = demo_data.series_points(db, principal, key)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No demonstration series for {key!r}")
    return payload


@router.get("/index")
def get_demo_index(
    principal: str = Query(..., pattern="^(unilever|delmonte)$"),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("forecast.view")),
) -> dict:
    if not demo_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    return demo_data.index(db, principal)


@router.get("/totals")
def get_demo_totals(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("forecast.view")),
) -> dict:
    """Del Monte demonstration pesos per month: the one canonical series (see demo_data.monthly_totals)."""
    if not demo_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    return demo_data.monthly_totals(db)
