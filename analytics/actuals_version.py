"""The version of the actuals a published accuracy figure was computed on (2026-10-24).

`mart.accuracy_mart` and `mart.error_decomposition` read real sales at every mart refresh, so loading a month
(or correcting one) moves published figures with no trace. This stamps a figure with a key for the data behind it.

Unilever per-SKU sales have no `etl_load_event` rows (only inventory, returns and derived receipts do), so the
key is a content fingerprint of `Unilever_SKU_Demand_Fact_Real`: the md5 of one `month:rows:pieces:pesos` line
per calendar month. A new month, a corrected month or a changed row changes it; nothing else does.
`mart_refresh_id` and `mart_refreshed_at` say which mart refresh the figure came from, `latest_load_event_key`
the newest loader event of any table, for context.

    key = "actuals-<latest_actual_month>-<first 12 hex of the fingerprint>"
"""
from __future__ import annotations

ACTUALS_VERSION_SQL = """
    SELECT (SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real) AS latest_actual_month,
           (SELECT COUNT(*) FROM Unilever_SKU_Demand_Fact_Real) AS demand_rows,
           (SELECT SUM(quantity_sold) FROM Unilever_SKU_Demand_Fact_Real) AS demand_pieces,
           (SELECT md5(string_agg(calendar_month || ':' || n || ':' || COALESCE(q, 0) || ':' || COALESCE(a, 0), ';'
                                  ORDER BY calendar_month))
            FROM (SELECT calendar_month, COUNT(*) AS n, SUM(quantity_sold) AS q, SUM(net_amount) AS a
                  FROM Unilever_SKU_Demand_Fact_Real GROUP BY calendar_month) m) AS fingerprint,
           (SELECT MAX(load_event_key) FROM etl_load_event WHERE NOT dry_run) AS latest_load_event_key,
           (SELECT refresh_id FROM mart.refresh_log ORDER BY refresh_id DESC LIMIT 1) AS mart_refresh_id,
           (SELECT refreshed_at FROM mart.refresh_log ORDER BY refresh_id DESC LIMIT 1) AS mart_refreshed_at
"""

COLUMNS = ("latest_actual_month", "demand_rows", "demand_pieces", "fingerprint", "latest_load_event_key",
           "mart_refresh_id", "mart_refreshed_at")


def from_row(row) -> dict:
    """ACTUALS_VERSION_SQL's one row (a tuple, or a mapping) -> the stamp. JSON-safe."""
    d = dict(row) if hasattr(row, "keys") else dict(zip(COLUMNS, row))
    fp = d["fingerprint"]
    out = {"key": f"actuals-{d['latest_actual_month']}-{fp[:12]}" if fp else None,
           "latest_actual_month": d["latest_actual_month"],
           "demand_rows": int(d["demand_rows"]) if d["demand_rows"] is not None else None,
           "demand_pieces": float(d["demand_pieces"]) if d["demand_pieces"] is not None else None,
           "fingerprint": fp,
           "latest_load_event_key": d["latest_load_event_key"],
           "mart_refresh_id": d["mart_refresh_id"],
           "mart_refreshed_at": (d["mart_refreshed_at"].isoformat() if hasattr(d["mart_refreshed_at"], "isoformat")
                                 else d["mart_refreshed_at"])}
    return out


def read(cur) -> dict:
    """The stamp, from a psycopg2 cursor (scripts)."""
    cur.execute(ACTUALS_VERSION_SQL)
    return from_row(cur.fetchone())
