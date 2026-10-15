"""
backend.demo_data — reads of schema `demo`, the single source of anything generated that is displayed
(CLAUDE.md hard rule 2; the older synthetic_v2 placeholders are retired for display, 2026-10-15).

Every function here is only reached behind backend.demo_flag.demo_enabled() (DM_DEMO_ENABLED, default off).
Every payload built here carries data_source "synthetic_demonstration", demonstration true and a note at the top, and
demonstration true + demonstration_note on every point and forecast row. No accuracy figure and no band exists in
schema demo, so none can be returned.

Origins (kept strictly apart): real_copy | interpolated | bridged | backcast. A Unilever month with no row between a
SKU's first and last real month is a real zero-sale month: quantity 0, origin null, reason no_sale, never generated.

Point reasons: interpolated -> interpolated; bridged -> taxonomy_change_bridge; backcast before 2023-01 ->
no_data_recorded_before_2023; backcast from 2023-01 (Del Monte series first seen later, anchor override) ->
no_observation_before_series_start. A backcast point of an anchor-overridden series also has
generated_before_first_observation: true.

TAXONOMIES DO NOT ADD UP. Del Monte's pre-2025 paths and its five 2025 categories describe the same business in two
vocabularies, and the demonstration generates both over 2023-01..2025-02. Summing categories across the two
double-counts; each index row says which taxonomy it belongs to.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.series_gaps import (
    REASON_BLANK_CAPTURE, REASON_BRIDGED, REASON_INTERPOLATED, REASON_NO_DATA_BEFORE_2023,
    REASON_NO_OBSERVATION_BEFORE_START, gap_note, unilever_points,
)

DATA_SOURCE = "synthetic_demonstration"
NOTE = ("Synthetic demonstration data (approved by Kelvin 2026-10-15): generated for visualisation only. "
        "It is not SSM data, not a forecast result and not an accuracy figure.")
POINT_NOTE = "synthetic demonstration"
ORIGINS = ("real_copy", "interpolated", "bridged", "backcast")


def label(payload: dict) -> dict:
    """Top-level demonstration labels on a payload."""
    return {**payload, "data_source": DATA_SOURCE, "demonstration": True, "demonstration_note": NOTE}


def _num(v):
    return None if v is None else float(v)


def point(period, quantity, net_amount, origin, reason, generated_before_first_observation=False) -> dict:
    return {"period": period, "quantity": quantity, "net_amount": net_amount, "origin": origin, "reason": reason,
            "generated_before_first_observation": generated_before_first_observation,
            "demonstration": True, "demonstration_note": POINT_NOTE}


def latest_run(db: Session, principal: str):
    return db.execute(
        text("SELECT run_id, seed, generator_version, window_end FROM demo.run WHERE principal = :p "
             "ORDER BY run_id DESC LIMIT 1"), {"p": principal},
    ).mappings().first()


def _dm_reason(origin, period, q):
    if origin == "interpolated":
        return REASON_INTERPOLATED
    if origin == "bridged":
        return REASON_BRIDGED
    if origin == "backcast":
        return REASON_NO_DATA_BEFORE_2023 if period < "2023-01" else REASON_NO_OBSERVATION_BEFORE_START
    return REASON_BLANK_CAPTURE if q is None else None


def series_points(db: Session, principal: str, key: str) -> dict | None:
    """One demonstration series with every point labelled, or None when the principal has no run / the key no rows."""
    run = latest_run(db, principal)
    if run is None:
        return None
    if principal == "unilever":
        rows = db.execute(
            text("SELECT period, quantity, net_amount, origin, false AS anchor_override FROM demo.unilever_sku_sales "
                 "WHERE run_id = :r AND sku_code = :k ORDER BY period"), {"r": run["run_id"], "k": key},
        ).mappings().all()
    else:
        rows = db.execute(
            text("SELECT period, quantity, net_amount, origin, anchor_override FROM demo.dm_category_sales "
                 "WHERE run_id = :r AND category_path = :k ORDER BY period"), {"r": run["run_id"], "k": key},
        ).mappings().all()
    if not rows:
        return None
    points: list[dict] = []
    if principal == "unilever":
        for r in rows:
            if r["origin"] == "backcast":
                points.append(point(r["period"], _num(r["quantity"]), _num(r["net_amount"]), "backcast",
                                    REASON_NO_DATA_BEFORE_2023))
        rest = [r for r in rows if r["origin"] != "backcast"]
        by_period = {r["period"]: _num(r["quantity"]) for r in rest}
        amount = {r["period"]: _num(r["net_amount"]) for r in rest}
        for pt in unilever_points(by_period):
            has_row = pt["period"] in by_period
            points.append(point(pt["period"], pt["quantity"], amount.get(pt["period"]),
                                "real_copy" if has_row else None, pt["reason"]))
    else:
        for r in rows:
            q = _num(r["quantity"])
            points.append(point(r["period"], q, _num(r["net_amount"]), r["origin"],
                                _dm_reason(r["origin"], r["period"], q),
                                bool(r["anchor_override"]) and r["origin"] == "backcast"))
    counts = {o: sum(1 for p in points if p["origin"] == o) for o in ORIGINS}
    return label({
        "principal": principal, "key": key,
        "run": {"run_id": run["run_id"], "seed": run["seed"], "generator_version": run["generator_version"],
                "window_end": run["window_end"]},
        "origin_counts": counts,
        "points": points,
        "gap_note": gap_note(p["reason"] for p in points if p["reason"]),
    })


def forecasts(db: Session) -> list[dict]:
    """The Del Monte demonstration forecasts (one-step MA3), every row labelled. No metric and no band."""
    run = latest_run(db, "delmonte")
    if run is None:
        return []
    rows = db.execute(
        text("SELECT category_path, forecast_period, forecast_quantity, method, history_months, interpolated_in_window "
             "FROM demo.dm_forecast WHERE run_id = :r ORDER BY category_path"), {"r": run["run_id"]},
    ).mappings().all()
    return [{
        "category": r["category_path"], "forecast_period": r["forecast_period"],
        "forecast_quantity": _num(r["forecast_quantity"]), "method": r["method"],
        "history_months": int(r["history_months"]), "generated_months_in_average": int(r["interpolated_in_window"]),
        "status": "ok", "demonstration": True, "demonstration_note": POINT_NOTE,
    } for r in rows]


def index(db: Session, principal: str) -> dict:
    """Every series in the principal's latest run with its origin counts (and, for Del Monte, its taxonomy)."""
    run = latest_run(db, principal)
    if run is None:
        return label({"principal": principal, "series": []})
    if principal == "unilever":
        rows = db.execute(text(
            "SELECT sku_code AS key, origin, COUNT(*) AS n FROM demo.unilever_sku_sales WHERE run_id = :r "
            "GROUP BY sku_code, origin ORDER BY sku_code"), {"r": run["run_id"]}).mappings().all()
        taxonomy = {}
    else:
        rows = db.execute(text(
            "SELECT category_path AS key, origin, COUNT(*) AS n FROM demo.dm_category_sales WHERE run_id = :r "
            "GROUP BY category_path, origin ORDER BY category_path"), {"r": run["run_id"]}).mappings().all()
        first = db.execute(text("SELECT category_path, first_real_period FROM demo.dm_category_param WHERE run_id = :r"),
                           {"r": run["run_id"]}).mappings().all()
        taxonomy = {r["category_path"]: ("2025" if r["first_real_period"] >= "2025-01" else "pre_2025") for r in first}
    series: dict[str, dict] = {}
    for r in rows:
        s = series.setdefault(r["key"], {"key": r["key"], "origin_counts": {o: 0 for o in ORIGINS}})
        if r["origin"] in s["origin_counts"]:
            s["origin_counts"][r["origin"]] = int(r["n"])
        if principal == "delmonte":
            s["taxonomy"] = taxonomy.get(r["key"])
    payload = {"principal": principal, "run_id": run["run_id"], "series": list(series.values())}
    if principal == "delmonte":
        payload["taxonomy_note"] = ("pre_2025 paths and the 2025 categories describe the same business in two "
                                    "vocabularies and both are generated over 2023-01..2025-02: do not sum across them.")
    return label(payload)
