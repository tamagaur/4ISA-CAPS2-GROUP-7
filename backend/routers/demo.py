"""
backend.routers.demo — GET /demo/series: the labelled demonstration series (CLAUDE.md hard rule 2).

OFF BY DEFAULT. Governed by the DM_DEMO_ENABLED environment variable (backend/demo_flag.py); with it unset or
false every request is a plain 404, so a deployment that has not switched it on behaves exactly as before.

Reads only schema `demo` (migrations 0052, 0053), which nothing in the real path reads. One series per request:
  ?principal=unilever&key=<sku_code>        SKU grain (DEC-03)
  ?principal=delmonte&key=<category_path>   category grain

Every point carries its `origin` and, where it is not a plain real month, a `reason`:
  real_copy      a real month                                  reason: null (or blank_capture for a NULL quantity)
  interpolated   between two real months of the same series    reason: interpolated
  bridged        across the 2024-03..2025-02 taxonomy change   reason: bridged_taxonomy_change (not built)
  backcast       2021-01..2022-12, no real data either side    reason: no_data_recorded_before_2023
A Unilever month with no row between the first and last real month is a real zero-sale month: quantity 0,
origin null, reason no_sale (never generated). No accuracy figure and no band is returned.

Per point: demonstration: true and demonstration_note. Top level: data_source "synthetic_demonstration",
demonstration: true, demonstration_note, the run's seed and generator version, origin_counts (the four kinds,
separately) and gap_note.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.demo_flag import demo_enabled
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.series_gaps import (
    REASON_BLANK_CAPTURE, REASON_BRIDGED, REASON_INTERPOLATED, REASON_NO_DATA_BEFORE_2023, gap_note, unilever_points,
)

router = APIRouter(prefix="/demo", tags=["demo"])

DATA_SOURCE = "synthetic_demonstration"
NOTE = ("Synthetic demonstration data (approved by Kelvin 2026-10-15): generated for visualisation only. "
        "It is not SSM data, not a forecast result and not an accuracy figure.")
POINT_NOTE = "synthetic demonstration"
ORIGINS = ("real_copy", "interpolated", "bridged", "backcast")
_REASON_BY_ORIGIN = {"interpolated": REASON_INTERPOLATED, "bridged": REASON_BRIDGED, "backcast": REASON_NO_DATA_BEFORE_2023}


def _num(v):
    return None if v is None else float(v)


def _point(period, quantity, net_amount, origin, reason) -> dict:
    return {"period": period, "quantity": quantity, "net_amount": net_amount, "origin": origin, "reason": reason,
            "demonstration": True, "demonstration_note": POINT_NOTE}


@router.get("/series")
def get_demo_series(
    principal: str = Query(..., pattern="^(unilever|delmonte)$"),
    key: str = Query(..., description="sku_code (unilever) or category_path (delmonte)"),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("forecast.view")),
) -> dict:
    if not demo_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    run = db.execute(
        text("SELECT run_id, seed, generator_version, window_end FROM demo.run WHERE principal = :p "
             "ORDER BY run_id DESC LIMIT 1"), {"p": principal},
    ).mappings().first()
    if run is None:
        raise HTTPException(status_code=404, detail="No demonstration run for this principal")

    if principal == "unilever":
        rows = db.execute(
            text("SELECT period, quantity, net_amount, origin FROM demo.unilever_sku_sales "
                 "WHERE run_id = :r AND sku_code = :k ORDER BY period"), {"r": run["run_id"], "k": key},
        ).mappings().all()
    else:
        rows = db.execute(
            text("SELECT period, quantity, net_amount, origin FROM demo.dm_category_sales "
                 "WHERE run_id = :r AND category_path = :k ORDER BY period"), {"r": run["run_id"], "k": key},
        ).mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No demonstration series for {key!r}")

    points: list[dict] = []
    backcast = [r for r in rows if r["origin"] == "backcast"]
    rest = [r for r in rows if r["origin"] != "backcast"]
    for r in backcast:
        points.append(_point(r["period"], _num(r["quantity"]), _num(r["net_amount"]), "backcast", REASON_NO_DATA_BEFORE_2023))
    if principal == "unilever":
        by_period = {r["period"]: _num(r["quantity"]) for r in rest}
        amount = {r["period"]: _num(r["net_amount"]) for r in rest}
        for pt in unilever_points(by_period):
            has_row = pt["period"] in by_period
            points.append(_point(pt["period"], pt["quantity"], amount.get(pt["period"]),
                                 "real_copy" if has_row else None, pt["reason"]))
    else:
        for r in rest:
            q = _num(r["quantity"])
            reason = _REASON_BY_ORIGIN.get(r["origin"]) or (REASON_BLANK_CAPTURE if q is None else None)
            points.append(_point(r["period"], q, _num(r["net_amount"]), r["origin"], reason))

    counts = {o: sum(1 for p in points if p["origin"] == o) for o in ORIGINS}
    return {
        "principal": principal, "key": key,
        "data_source": DATA_SOURCE, "demonstration": True, "demonstration_note": NOTE,
        "run": {"run_id": run["run_id"], "seed": run["seed"], "generator_version": run["generator_version"],
                "window_end": run["window_end"]},
        "origin_counts": counts,
        "points": points,
        "gap_note": gap_note(p["reason"] for p in points if p["reason"]),
    }
