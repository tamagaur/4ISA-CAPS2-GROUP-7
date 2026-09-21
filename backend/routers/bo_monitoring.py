from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.deps import TokenPayload, get_current_user, get_db
from backend.principals import PrincipalQuery, principal_clause

router = APIRouter(prefix="/bo-monitoring", tags=["bo-monitoring"])

_WEEKDAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}

# Both principals again (2026-09-17): the per-request scope comes from
# ?principal= (backend/principals.py) instead of a module-level literal.
#
# What the data holds (checked 2026-09-21): salesreturn_fact_real is Del
# Monte only. return_type = 'BO' rows run 2025-03..2025-12; before 2025 the
# source doesn't distinguish BO from good-stock returns (return_type NULL,
# schema.sql), so those can't be counted here. purchase_fact_real — the
# rate's denominator — is Del Monte only too. No Unilever returns are
# loaded, so a Unilever scope is empty, not zero.
#
# The rate is value-based: BO net_amount / purchase net_amount, in percent,
# per schema.sql's BO_Monitoring_View note — bo_units has no source column
# (always NULL), so there is no unit-based rate or units-lost figure.
# SalesReturn_Fact_Real has no sku / brand / reason / qty column either, so
# those incident fields are null rather than filled with placeholders.


@router.get("")
def get_bo_monitoring(
    from_date: str = Query(None, alias="from"),
    to_date: str = Query(None, alias="to"),
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    principal_filter, params = principal_clause(principal, "principal")
    params = dict(params)

    period_filter = ""
    if from_date and to_date:
        from_period = from_date[:7]
        to_period = to_date[:7]
        period_filter = "AND _period >= :from_period AND _period <= :to_period"
        params["from_period"] = from_period
        params["to_period"] = to_period

    incidents_query = text(f"""
        SELECT
            return_slip_num as id,
            principal,
            region,
            _period as period,
            return_date as date,
            net_amount as value
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
        ORDER BY _period DESC, net_amount DESC
    """)
    rows = db.execute(incidents_query, params).mappings().all()

    # sku / brand / product / qty / reason: no such column upstream (see the
    # module note) — null, never a stand-in like "Unilever" or 0.
    incidents = []
    for r in rows:
        incidents.append({
            "id": r["id"] or None,
            "principal": r["principal"],
            "region": r["region"],
            "period": r["period"],
            "sku": None,
            "brand": None,
            "product": None,
            "qty": None,
            "reason": None,
            "value": float(r["value"] or 0),
            "date": str(r["date"]) if r["date"] is not None else None,
        })

    # Coverage first. A month only has BO data when the source typed its
    # returns (return_type IS NOT NULL) — Del Monte's returns files are
    # missing for some months entirely, and untyped pre-2025 returns can't be
    # split into BO vs good stock. So "no row" means no data, not zero, and
    # the trend keeps those months as explicit gaps.
    returns_query = text(f"""
        SELECT principal, _period,
               COUNT(*) FILTER (WHERE return_type = 'BO') AS bo_count,
               COALESCE(SUM(net_amount) FILTER (WHERE return_type = 'BO'), 0) AS bo_value
        FROM salesreturn_fact_real
        WHERE return_type IS NOT NULL {principal_filter} {period_filter}
        GROUP BY principal, _period
    """)
    purchases_query = text(f"""
        SELECT principal, _period, COALESCE(SUM(net_amount), 0) AS purchase_value
        FROM purchase_fact_real
        WHERE 1=1 {principal_filter} {period_filter}
        GROUP BY principal, _period
    """)
    covered = {
        (r["principal"], r["_period"]): (int(r["bo_count"]), float(r["bo_value"]))
        for r in db.execute(returns_query, params).mappings().all()
    }
    purchases = {
        (r["principal"], r["_period"]): float(r["purchase_value"] or 0)
        for r in db.execute(purchases_query, params).mappings().all()
    }

    def _rate(pairs) -> tuple[float | None, list[str]]:
        """Value-based BO rate (percent) over (principal, period) pairs that
        have BOTH typed returns and purchases — never BO from one set of
        months over purchases from another."""
        matched = [k for k in pairs if purchases.get(k, 0) > 0]
        bo_value = sum(covered[k][1] for k in matched)
        purchase_value = sum(purchases[k] for k in matched)
        rate = round(bo_value / purchase_value * 100, 2) if purchase_value > 0 else None
        return rate, sorted({k[1] for k in matched})

    # BO value/count per month for the requested scope, with gaps kept.
    covered_periods = sorted({period for (_, period) in covered})
    trend = []
    if covered_periods:
        y, m = map(int, covered_periods[0].split("-"))
        last = covered_periods[-1]
        while f"{y:04d}-{m:02d}" <= last:
            period = f"{y:04d}-{m:02d}"
            keys = [k for k in covered if k[1] == period]
            if not keys:
                trend.append({"period": period, "has_data": False, "incident_count": None,
                              "value_lost": None, "purchase_value": None, "bo_rate": None})
            else:
                rate, _ = _rate(keys)
                purchase_value = sum(purchases.get(k, 0) for k in keys)
                trend.append({
                    "period": period,
                    "has_data": True,
                    "incident_count": sum(covered[k][0] for k in keys),
                    "value_lost": round(sum(covered[k][1] for k in keys), 2),
                    "purchase_value": purchase_value if purchase_value > 0 else None,
                    "bo_rate": rate,
                })
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    incidents_count = sum(v[0] for v in covered.values())
    value_lost = round(sum(v[1] for v in covered.values()), 2)
    bo_rate_pct, rate_periods = _rate(list(covered))

    # How the loss varies across principals (the mapping's D5).
    principal_breakdown = []
    for principal_key in sorted({k[0] for k in covered}):
        keys = [k for k in covered if k[0] == principal_key]
        rate, periods = _rate(keys)
        principal_breakdown.append({
            "principal": principal_key,
            "incidents": sum(covered[k][0] for k in keys),
            "value_lost": round(sum(covered[k][1] for k in keys), 2),
            "months_with_data": len(keys),
            "bo_rate": rate,
            "rate_periods": periods,
        })
    principal_breakdown.sort(key=lambda r: r["value_lost"], reverse=True)

    # Region is the one finer dimension the source has (no SKU or brand).
    region_query = text(f"""
        SELECT region, COUNT(*) AS incident_count, COALESCE(SUM(net_amount), 0) AS bo_value
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
        GROUP BY region
        ORDER BY bo_value DESC
    """)
    region_breakdown = [
        {"region": r["region"], "incidents": int(r["incident_count"]), "value_lost": float(r["bo_value"])}
        for r in db.execute(region_query, params).mappings().all()
    ]

    # Day-of-week needs a return date; the source often has none (all 151
    # Del Monte BO rows as of 2026-09-21), so report how many are dated and
    # leave the breakdown empty rather than a row of zeros.
    weekday_query = text(f"""
        SELECT EXTRACT(ISODOW FROM return_date)::int AS dow, COUNT(*) AS count
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' AND return_date IS NOT NULL {principal_filter} {period_filter}
        GROUP BY dow
        ORDER BY dow
    """)
    weekday_counts = {
        _WEEKDAY_NAMES[r["dow"]]: int(r["count"])
        for r in db.execute(weekday_query, params).mappings().all() if r["dow"] in _WEEKDAY_NAMES
    }
    dated_incidents = sum(weekday_counts.values())
    weekday_breakdown = (
        [{"day": day, "count": weekday_counts.get(day, 0)} for day in _WEEKDAY_NAMES.values()]
        if dated_incidents else []
    )

    return {
        "incidents": incidents,
        "kpis": {
            "incidents": incidents_count,
            "unitsLost": None,  # bo_units has no source column — see the module note
            "valueLost": value_lost,
            "ratePct": bo_rate_pct,
            "rate": f"{bo_rate_pct}%" if bo_rate_pct is not None else "N/A",
            "rate_periods": rate_periods,
            "months_with_data": len(covered_periods),
            "months_missing": [t["period"] for t in trend if not t["has_data"]],
            "dated_incidents": dated_incidents,
        },
        "trend": trend,
        "weekday_breakdown": weekday_breakdown,
        "principal_breakdown": principal_breakdown,
        "region_breakdown": region_breakdown,
    }
