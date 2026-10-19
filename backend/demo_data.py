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

from analytics.params import POLICY_COVER_WEEKS as POLICY_WEEKS
from analytics.params import WEEKS_PER_MONTH as AVG_WEEKS_PER_MONTH
from backend.series_gaps import (
    REASON_BLANK_CAPTURE, REASON_BRIDGED, REASON_FORWARD_FILLED, REASON_INTERPOLATED, REASON_NO_DATA_BEFORE_2023,
    REASON_NO_OBSERVATION_BEFORE_START, gap_note, unilever_points,
)

DATA_SOURCE = "synthetic_demonstration"
NOTE = ("Synthetic demonstration data (approved by Kelvin 2026-10-15): generated for visualisation only. "
        "It is not SSM data, not a forecast result and not an accuracy figure.")
POINT_NOTE = "synthetic demonstration"
ORIGINS = ("real_copy", "interpolated", "bridged", "backcast", "forward_filled")


def label(payload: dict) -> dict:
    """Top-level demonstration labels on a payload."""
    return {**payload, "data_source": DATA_SOURCE, "demonstration": True, "demonstration_note": NOTE}


def _num(v):
    return None if v is None else float(v)


def point(period, quantity, net_amount, origin, reason, generated_before_first_observation=False,
          in_canonical_total=True) -> dict:
    return {"period": period, "quantity": quantity, "net_amount": net_amount, "origin": origin, "reason": reason,
            "generated_before_first_observation": generated_before_first_observation,
            "in_canonical_total": in_canonical_total,
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
    if origin == "forward_filled":
        return REASON_FORWARD_FILLED
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
            text("SELECT period, quantity, net_amount, origin, anchor_override, in_canonical_total "
                 "FROM demo.dm_category_sales "
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
                                bool(r["anchor_override"]) and r["origin"] == "backcast",
                                bool(r.get("in_canonical_total", True))))
    counts = {o: sum(1 for p in points if p["origin"] == o) for o in ORIGINS}
    return label({
        "principal": principal, "key": key,
        "run": {"run_id": run["run_id"], "seed": run["seed"], "generator_version": run["generator_version"],
                "window_end": run["window_end"]},
        "origin_counts": counts,
        "points": points,
        "gap_note": gap_note(p["reason"] for p in points if p["reason"]),
    })


def monthly_totals(db: Session) -> dict:
    """The Del Monte demonstration pesos per month: ONE canonical series (old paths through 2025-02, the five live
    categories from 2025-03; demo.dm_monthly_total, migration 0055). Each month splits by origin so a reader can see how
    much of it is generated. The only sanctioned aggregate: never sum demo.dm_category_sales across categories."""
    run = latest_run(db, "delmonte")
    if run is None:
        return label({"principal": "delmonte", "months": []})
    rows = db.execute(
        text("SELECT period, pesos, real_pesos, interpolated_pesos, bridged_pesos, backcast_pesos, series, series_left_out "
             "FROM demo.dm_monthly_total WHERE run_id = :r ORDER BY period"), {"r": run["run_id"]},
    ).mappings().all()
    return label({
        "principal": "delmonte", "run_id": run["run_id"], "basis": "pesos (net_amount), ex-VAT as recorded",
        "rule": ("one canonical series per month: the pre-2025 paths through 2025-02, the five live 2025 categories "
                 "from 2025-03; rows generated before a series' own first observation are left out of every total"),
        "months": [{
            "period": r["period"], "pesos": _num(r["pesos"]), "real": _num(r["real_pesos"]),
            "interpolated": _num(r["interpolated_pesos"]), "bridged": _num(r["bridged_pesos"]),
            "backcast": _num(r["backcast_pesos"]), "series": int(r["series"]), "series_left_out": int(r["series_left_out"]),
            "demonstration": True, "demonstration_note": POINT_NOTE,
        } for r in rows],
    })


def stock(db: Session) -> list[dict]:
    """The Del Monte demonstration stock on hand, every row labelled. There is no real anchor at this grain
    (migration 0056): Inventory_Fact_Real is SKU grain only and carries no category_path, so every row's origin
    is 'generated_months_of_cover' — a seeded draw against the category's own demonstration demand, never a copy
    of anything real."""
    run = latest_run(db, "delmonte")
    if run is None:
        return []
    rows = db.execute(
        text("SELECT category_path, period, quantity_on_hand, months_of_cover FROM demo.dm_category_stock "
             "WHERE run_id = :r ORDER BY category_path, period"), {"r": run["run_id"]},
    ).mappings().all()
    return [{
        "category": r["category_path"], "period": r["period"], "quantity_on_hand": _num(r["quantity_on_hand"]),
        "months_of_cover": _num(r["months_of_cover"]), "origin": "generated_months_of_cover",
        "demonstration": True, "demonstration_note": POINT_NOTE,
    } for r in rows]


ORDER_PLAN_NOTE = (
    "Order-plan rows rest on generated demand AND generated stock — two layers deep. Del Monte has no "
    "SSM-confirmed warehouse capacity or supplier allocation (unlike the real Unilever LP), so this is a plain "
    "order-up-to (safety stock + target stock, no allocation/warehouse ceiling)."
)


def order_plan(db: Session) -> dict:
    """The Del Monte demonstration order plan: analytics/demo/prescriptive.py's safety stock, target stock and
    order quantity. 'available' is False until scripts.run_lp --source demo --principal delmonte --write has run
    for the current demonstration build."""
    run = latest_run(db, "delmonte")
    if run is None:
        return {"available": False, "reason": "no Del Monte demonstration run exists"}
    rows = db.execute(
        text("SELECT category_path, period, forecast_quantity, stock_on_hand, sigma_d, safety_stock, target_stock, "
             "order_qty FROM demo.dm_category_lp WHERE run_id = :r ORDER BY category_path"), {"r": run["run_id"]},
    ).mappings().all()
    if not rows:
        return {"available": False, "reason": "the demonstration order plan has not been run yet "
                                               "(scripts.run_lp --source demo --principal delmonte --write)"}
    return {
        "available": True, "demonstration_note": ORDER_PLAN_NOTE,
        "items": [{
            "category": r["category_path"], "period": r["period"],
            "forecast_quantity": _num(r["forecast_quantity"]), "stock_on_hand": _num(r["stock_on_hand"]),
            "sigma_d": _num(r["sigma_d"]), "safety_stock": _num(r["safety_stock"]),
            "target_stock": _num(r["target_stock"]), "order_qty": _num(r["order_qty"]),
            "demonstration": True, "demonstration_note": POINT_NOTE,
        } for r in rows],
    }


UNILEVER_ORDER_PLAN_NOTE = (
    "Demo forecast, REAL stock: this plan's demand side comes from the demonstration (the MA3 forecast, and a "
    "sigma computed over the demonstration's full history including the 2021-22 back-cast), but stock on hand "
    "and cost per piece are Unilever's REAL count and REAL cost — real inventory exists and is good, so none of "
    "it is generated. That is a different confidence than Del Monte's plan, which rests on generated demand AND "
    "generated stock. Not Unilever's real LP: the real LP_Recommendation is unaffected."
)


def unilever_order_plan(db: Session) -> dict:
    """The Unilever demonstration order plan: scripts/run_lp.py's --source demo --principal unilever
    (demo.unilever_sku_lp, migration 0057). 'available' is False until that run has been written."""
    run = latest_run(db, "unilever")
    if run is None:
        return {"available": False, "reason": "no Unilever demonstration run exists"}
    rows = db.execute(
        text("SELECT sku_code, period, forecast_quantity, stock_on_hand, sigma_d, safety_stock, target_stock, "
             "order_qty FROM demo.unilever_sku_lp WHERE run_id = :r ORDER BY sku_code"), {"r": run["run_id"]},
    ).mappings().all()
    if not rows:
        return {"available": False, "reason": "the demonstration order plan has not been run yet "
                                               "(scripts.run_lp --source demo --principal unilever --write)"}
    return {
        "available": True, "demonstration_note": UNILEVER_ORDER_PLAN_NOTE, "stock_source": "real",
        "sku_count": len(rows),
        "items": [{
            "sku_id": r["sku_code"], "period": r["period"],
            "forecast_quantity": _num(r["forecast_quantity"]), "stock_on_hand": _num(r["stock_on_hand"]),
            "sigma_d": _num(r["sigma_d"]), "safety_stock": _num(r["safety_stock"]),
            "target_stock": _num(r["target_stock"]), "order_qty": _num(r["order_qty"]),
            "demonstration": True, "demonstration_note": POINT_NOTE,
        } for r in rows],
    }


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


def unilever_forecast(db: Session, sku_code: str) -> dict | None:
    """The demonstration's one-step MA3 forecast for one Unilever SKU (migration 0056), or None when this SKU
    has no demo forecast (fewer than 3 real months, or more than one blank-capture month in its MA3 window —
    scripts/build_unilever_demo.py). Not Unilever's real forecast: this table is never read by the real path."""
    run = latest_run(db, "unilever")
    if run is None:
        return None
    r = db.execute(
        text("SELECT forecast_period, forecast_quantity, method, history_months, blank_capture_filled "
             "FROM demo.unilever_sku_forecast WHERE run_id = :r AND sku_code = :k"), {"r": run["run_id"], "k": sku_code},
    ).mappings().first()
    if r is None:
        return None
    return {
        "forecast_period": r["forecast_period"], "forecast_quantity": _num(r["forecast_quantity"]),
        "method": r["method"], "history_months": int(r["history_months"]),
        "blank_capture_filled": bool(r["blank_capture_filled"]),
        "status": "ok", "demonstration": True, "demonstration_note": POINT_NOTE,
    }


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
                                    "vocabularies and both are generated over 2023-01..2025-02: do not sum across them. "
                                    "GET /demo/totals is the one canonical total (rows generated before a series' own "
                                    "first observation are left out of it).")
    return label(payload)


TARGET_VS_RULE_BLOCKED_REASON = (
    "Del Monte's demonstration target stock (analytics/demo/prescriptive.py) has no allocation or warehouse "
    "ceiling to pull it below SSM's 3-week rule (DEC-31: no confirmed Del Monte allocation/warehouse data), so "
    "it floors at the SAME 3-week constant the rule itself uses (analytics.params.POLICY_COVER_WEEKS) and can "
    "only ever read equal to or above the rule, never below it -- it cannot show the one thing this comparison "
    "exists to show (stock the rule traps that the LP would free). A genuinely different target would need "
    "the ceiling data SSM has not given us. Reading 0% here would misstate that as a real finding rather than "
    "a structural gap, so this comparison is withheld; safety_stock_vs_rule_pct below is NOT floor-bound (it is "
    "driven only by each category's own demand variability) and is the genuine comparison this card can make."
)


def policy_comparison(db: Session) -> dict:
    """The Del Monte demonstration version of GET /policy-comparison / dashboard.py's policy_comparison band:
    the demo order plan's target/safety stock (demo.dm_category_lp) against SSM's own 3-week rule, in units.
    target_vs_rule_pct is withheld (TARGET_VS_RULE_BLOCKED_REASON, Kelvin 2026-10-16): target_stock floors at
    the same 3-week constant the rule uses, so it always compares the rule against itself. safety_stock_vs_rule_pct
    takes its place as the headline: safety stock is never floor-bound, so it is a genuinely independent number
    (the same split the real card makes between its floor-bound 'peak' and its safety-stock-based 'average',
    backend/routers/policy_comparison.py). Pesos are left out: the demo order plan's categories have no
    confirmed quantity unit either (DEC-31)."""
    run = latest_run(db, "delmonte")
    if run is None:
        return {"available": False, "reason": "no Del Monte demonstration run exists"}
    rows = db.execute(
        text("SELECT forecast_quantity, safety_stock, target_stock FROM demo.dm_category_lp WHERE run_id = :r"),
        {"r": run["run_id"]},
    ).mappings().all()
    if not rows:
        return {"available": False, "reason": "the demonstration order plan has not been run yet "
                                               "(scripts.run_lp --source demo --principal delmonte --write)"}
    lp_units = sum(float(r["safety_stock"]) for r in rows)
    target_units = sum(float(r["target_stock"]) for r in rows)
    forecast_units = sum(float(r["forecast_quantity"]) for r in rows)
    rule_units = POLICY_WEEKS * forecast_units / AVG_WEEKS_PER_MONTH
    return {
        "available": True, "demonstration": True, "demonstration_note": ORDER_PLAN_NOTE,
        "category_count": len(rows),
        "lp_target_stock_units": round(target_units, 2), "lp_safety_stock_units": round(lp_units, 2),
        "rule_stock_units": round(rule_units, 2),
        "target_vs_rule_pct": None,
        "target_vs_rule_blocked_reason": TARGET_VS_RULE_BLOCKED_REASON,
        "safety_stock_vs_rule_pct": round((rule_units - lp_units) / rule_units * 100, 1) if rule_units > 0 else None,
        "categories_above_rule": sum(1 for r in rows if float(r["target_stock"]) >
                                     POLICY_WEEKS * float(r["forecast_quantity"]) / AVG_WEEKS_PER_MONTH),
        "rule_weeks": POLICY_WEEKS,
    }


DEAD_STOCK_NOTE = (
    "A demonstration-only heuristic (Kelvin, 2026-10-16), not the real dashboard's tier_stock bucket: Del Monte "
    "has no ABC tier (it is not in the ABC cohort) and no stock_status flag, so this classes each category by "
    "its generated months_of_cover against the SAME policy centre the stock draw and the order plan both use "
    "(analytics.demo.stock.CENTER_MONTHS_OF_COVER): dead_stock > 2x centre, critical < 0.5x centre, else in_stock."
)


def dead_stock(db: Session) -> dict:
    """Del Monte demonstration dead-stock classification, every one of the 82 generated categories (not only the
    5 with a forecast — this needs only stock + demand, which all 82 have). See DEAD_STOCK_NOTE for the rule."""
    from analytics.demo.stock import CENTER_MONTHS_OF_COVER

    run = latest_run(db, "delmonte")
    if run is None:
        return {"available": False, "reason": "no Del Monte demonstration run exists"}
    rows = db.execute(
        text("SELECT DISTINCT ON (category_path) category_path, period, months_of_cover "
             "FROM demo.dm_category_stock WHERE run_id = :r ORDER BY category_path, period DESC"),
        {"r": run["run_id"]},
    ).mappings().all()
    if not rows:
        return {"available": False, "reason": "no demonstration stock exists for this run"}
    items = []
    for r in rows:
        cover = float(r["months_of_cover"])
        label_ = ("dead_stock" if cover > 2 * CENTER_MONTHS_OF_COVER
                 else "critical" if cover < 0.5 * CENTER_MONTHS_OF_COVER else "in_stock")
        items.append({"category": r["category_path"], "period": r["period"], "months_of_cover": round(cover, 4),
                      "status": label_, "demonstration": True, "demonstration_note": POINT_NOTE})
    counts = {k: sum(1 for i in items if i["status"] == k) for k in ("dead_stock", "critical", "in_stock")}
    return {"available": True, "demonstration_note": DEAD_STOCK_NOTE, "counts": counts, "items": items}
