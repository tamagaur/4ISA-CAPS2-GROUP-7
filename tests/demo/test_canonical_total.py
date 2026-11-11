"""One canonical Del Monte series per month (migration 0055; Kelvin 2026-10-15).

The demonstration generates Del Monte under two vocabularies over 2023-01..2025-02 (the old paths: real, interpolated,
bridged; and the five 2025 categories: back-cast). A total across categories must count the business once. The live
test fails if a monthly total in that window exceeds the real total of the same series by more than the interpolated
plus bridged contribution.
"""
import os

import pytest

from analytics.demo.dm_interpolate import in_canonical_total
from scripts.build_dm_demo import assert_not_inflated, canonical_totals


def row(cat, period, amount, origin, override=False):
    return (cat, 1, period, 1.0, amount, origin, override)


def test_the_rule_leaves_out_only_back_cast_generated_before_a_series_first_observation():
    assert in_canonical_total("real_copy", False) and in_canonical_total("interpolated", False)
    assert in_canonical_total("bridged", False) and in_canonical_total("backcast", False)
    assert not in_canonical_total("backcast", True)


def test_a_live_category_back_cast_is_not_added_to_the_old_paths_total():
    series = [row("/OLD", "2024-06", 100.0, "bridged"),
              row("BEVERAGE", "2024-06", 100.0, "backcast", True),   # the same business, second vocabulary
              row("/OLD", "2025-03", 0.0, "real_copy")]
    assert canonical_totals(series)["2024-06"]["bridged"] == 100.0
    assert sum(canonical_totals(series)["2024-06"].values()) == 100.0, "doubled: 200 would be the old behaviour"


def test_the_build_fails_if_a_month_exceeds_real_plus_interpolated_plus_bridged():
    sales = [("/A", 1, "2023-05", 1.0, 100.0)]
    ok = [row("/A", "2023-05", 100.0, "real_copy"), row("/A", "2023-06", 7.0, "interpolated")]
    assert assert_not_inflated(ok, sales)["2023-05"] == 100.0
    inflated = ok + [row("/B", "2023-05", 90.0, "backcast", False)]  # an un-flagged back-cast dated inside the window
    with pytest.raises(SystemExit):
        assert_not_inflated(inflated, sales)
    # the same row, flagged (generated before its series' first observation), is left out and the build passes
    assert assert_not_inflated(ok + [row("/B", "2023-05", 90.0, "backcast", True)], sales)["2023-05"] == 100.0


def _live_conn():
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv()
    from analytics.config import long_read_db_url
    url = long_read_db_url() if os.environ.get("SUPABASE_DB_URL") else None  # analytics.config.long_read_db_url: SUPABASE_DIRECT_URL only when it is the same database (2026-11-11)
    if not url:
        pytest.skip("no database URL")
    try:
        return psycopg2.connect(url, connect_timeout=15)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"database not reachable: {str(e)[:60]}")


def test_live_monthly_total_2023_01_to_2025_02_does_not_exceed_real_plus_interpolated_plus_bridged():
    conn = _live_conn()
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT to_regclass('demo.dm_monthly_total')")
        if cur.fetchone()[0] is None:
            pytest.skip("migration 0055 not applied here")
        cur.execute("""
            WITH run AS (SELECT MAX(run_id) AS id FROM demo.run WHERE principal = 'delmonte'),
            covered AS (SELECT DISTINCT category_path FROM demo.dm_category_sales WHERE run_id = (SELECT id FROM run)),
            real AS (SELECT s._period AS period, SUM(s.net_amount) AS pesos
                     FROM SellOut_Fact_Real s WHERE s.category_path IN (SELECT category_path FROM covered)
                     GROUP BY 1)
            SELECT t.period, t.pesos, COALESCE(r.pesos, 0), COALESCE(t.interpolated_pesos, 0), COALESCE(t.bridged_pesos, 0),
                   t.real_pesos
            FROM demo.dm_monthly_total t LEFT JOIN real r USING (period)
            WHERE t.run_id = (SELECT id FROM run) AND t.period BETWEEN '2023-01' AND '2025-02'
            ORDER BY t.period""")
        rows = cur.fetchall()
        cur.execute("ROLLBACK")
    finally:
        conn.close()
    assert len(rows) == 26
    for period, total, real, interp, bridged, real_copy in rows:
        assert float(total) <= float(real) + float(interp) + float(bridged) + 0.01, (period, total, real, interp, bridged)
        assert abs(float(real_copy or 0) - float(real)) < 0.01, f"real_copy differs from the real view in {period}"
