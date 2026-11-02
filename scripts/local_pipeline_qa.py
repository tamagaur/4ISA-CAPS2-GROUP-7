"""
scripts/local_pipeline_qa.py - run the Unilever monthly pipeline end to end, and break it on purpose, on the THROWAWAY
local database only (scripts/local_pg.py). Launch it through the guard so the child resolves to localhost:55432:

    python -m scripts.local_pg run -- python scripts/local_pipeline_qa.py happy
    python -m scripts.local_pg run -- python scripts/local_pipeline_qa.py step abc|forecast|lp|marts|close|synth
    python -m scripts.local_pg run --practice -- python scripts/local_pipeline_qa.py state

The month is March 2026: its per-SKU sales do not exist in the real sources, so `synth` generates them from each
product's own February (the same rule as scripts/rollover_scratch_test.py), tagged _src_file = 'qa_synthetic_march' and
is_demo = true.

`synth` runs only on ssm_practice, a copy of the local database that no page reads (python -m scripts.local_pg practice), so
the database behind the pages never holds one. Rows flagged is_demo never pass a _Real view (rollover_scratch_test.py says
the same), and the forecast refuses them even through a view (analytics/forecasting/router.assert_real_rows), so
scripts/run_month.py refuses a month that holds only these rows: they label the month, they do not drive it (KNOWN_ISSUES M5).
Everything else is the repo's own CLI, unmodified. Local timings say nothing about Render or Supabase.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
TAG = "qa_synthetic_march"
PRACTICE_DB = "ssm_practice"

STEPS = {
    "abc": [PY, "-m", "analytics.classification.orchestrate_abc", "--period", "2026-03", "--schema", "public",
            "--method", "t12m_new", "--principal", "unilever"],
    "forecast": [PY, "scripts/run_baseline_forecast.py", "--write", "--calendar-factor"],
    "lp": [PY, "scripts/run_lp.py", "--retire-stale-pending"],
    "close": [PY, "-m", "scripts.close_cycle", "--cycle", "2026-03", "--approved-by", "qa", "--expect-cycle", "2026-03", "--target-public"],
}


def guard() -> str:
    url = os.environ["SUPABASE_DB_URL"]
    u = urlparse(url)
    if (u.hostname, u.port) != ("127.0.0.1", 55432):
        sys.exit(f"REFUSED: not the throwaway database ({u.hostname}:{u.port})")
    return url


def connect():
    import psycopg2
    return psycopg2.connect(guard())


def practice_guard() -> None:
    url = guard()
    if urlparse(url).path.lstrip("/") != PRACTICE_DB:
        sys.exit(f"REFUSED: generated sales go only into {PRACTICE_DB}, never the database behind the pages")


def synth() -> None:
    practice_guard()
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM unilever_sku_demand_fact WHERE calendar_month = '2026-03' AND is_demo = false")
        if cur.fetchone()[0]:
            sys.exit("real March sales exist: refusing to write over them")
        cur.execute("DELETE FROM unilever_sku_demand_fact WHERE calendar_month = '2026-03' AND is_demo = true")
        cur.execute("""
            INSERT INTO unilever_sku_demand_fact (product_key, sku_code, calendar_month, region, quantity_sold, net_amount,
                                                  _src_file, _src_sheet, is_demo, gsv, fill_source)
            SELECT product_key, sku_code, '2026-03', region,
                   GREATEST(round(quantity_sold * (0.8 + 0.4 * ((abs(hashtext(sku_code || '2026-03')) %% 1000) / 1000.0))), 0),
                   net_amount * (0.8 + 0.4 * ((abs(hashtext(sku_code || '2026-03')) %% 1000) / 1000.0)),
                   %(tag)s, %(tag)s, true, gsv, NULL
            FROM unilever_sku_demand_fact WHERE calendar_month = '2026-02' AND is_demo = false AND quantity_sold > 0""", {"tag": TAG})
        print(f"synthetic March sales rows: {cur.rowcount}")


def marts() -> None:
    from analytics import marts as m
    out = m.refresh_marts(guard(), "qa_local")
    print("refresh_marts ->", out)


def state() -> dict:
    q = {
        "march_sales_real_rows": "select count(*) from unilever_sku_demand_fact_real where calendar_month='2026-03'",
        "abc_2026-03_t12m_new": "select count(*) from abc_classification where classification_period='2026-03' and method='t12m_new' and principal='unilever'",
        "forecast_rows_by_date": "select string_agg(forecast_date::text||':'||n, ' ') from (select forecast_date, count(*) n from forecast_result group by 1 order by 1 desc limit 3) x",
        "lp_runs": "select count(*) from lp_run",
        "lp_rows_cycle_2026-04": "select count(*) from lp_recommendation where planning_cycle_date='2026-04-01'",
        "lp_rows_cycle_2026-04_with_run": "select count(*) from lp_recommendation where planning_cycle_date='2026-04-01' and lp_run_key is not null",
        "lp_pieces_cycle_2026-04": "select coalesce(sum(q_i),0) from lp_recommendation where planning_cycle_date='2026-04-01' and lp_run_key is not null",
        "lp_rows_cycle_2026-03": "select count(*) from lp_recommendation where planning_cycle_date='2026-03-01'",
        "lp_rows_cycle_2026-03_closed": "select count(*) from lp_recommendation where planning_cycle_date='2026-03-01' and closed_at is not null",
        "planning_cycle": "select coalesce(string_agg(cycle::text||'='||state||'('||coalesce(array_to_string(steps_done,','),'')||')', ' '),'none') from planning_cycle",
        "expected_receipt_by_state": "select coalesce(string_agg(state||':'||n, ' '),'none') from (select state, count(*) n from expected_receipt group by 1) x",
        "fp_abc_2026-03": "select coalesce(sum(hashtext(product_key||':'||coalesce(tier,'')||':'||coalesce(revenue_share::text,''))),0) from abc_classification where classification_period='2026-03' and method='t12m_new' and principal='unilever'",
        "fp_forecast_2026-04": "select coalesce(sum(hashtext(product_key||':'||coalesce(forecast_value::text,''))),0) from forecast_result where forecast_date='2026-04-01'",
        "fp_lp_2026-04": "select coalesce(sum(hashtext(product_key||':'||q_i::text||':'||status)),0) from lp_recommendation where planning_cycle_date='2026-04-01'",
        "lp_run_keys_2026-04": "select coalesce(string_agg(run_key::text, ','),'none') from lp_run where planning_cycle_date='2026-04-01'",
        "mart_planning_rows": "select count(*) from mart.planning_mart",
        "mart_refresh_log": "select count(*) from mart.refresh_log",
    }
    out = {}
    with connect() as c, c.cursor() as cur:
        for k, sql in q.items():
            try:
                cur.execute(sql)
                out[k] = cur.fetchone()[0]
            except Exception as e:
                c.rollback()
                out[k] = f"ERR {type(e).__name__}"
    return out


def run_step(name: str) -> tuple[int, float, str]:
    t0 = time.time()
    p = subprocess.run(STEPS[name], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, time.time() - t0, (p.stdout + p.stderr)


def happy() -> None:
    timings = []
    t_all = time.time()
    t0 = time.time(); synth(); timings.append(("load (synthetic March)", time.time() - t0, 0))
    for name in ("abc", "forecast", "lp"):
        rc, dt, out = run_step(name)
        timings.append((name, dt, rc))
        if rc:
            print(out[-2500:])
            break
        print(f"--- {name} ok {dt:.1f}s; tail:\n{out[-600:]}")
    else:
        t0 = time.time(); marts(); timings.append(("marts", time.time() - t0, 0))
        rc, dt, out = run_step("close")
        timings.append(("close_cycle", dt, rc))
        print(out[-2500:])
    print("\nSTEP TIMINGS")
    for n, dt, rc in timings:
        print(f"  {n:28s} {dt:7.1f}s rc={rc}")
    print(f"  {'TOTAL':28s} {time.time() - t_all:7.1f}s")
    for k, v in state().items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    a = sys.argv[1:]
    guard()
    if a[0] == "happy":
        happy()
    elif a[0] == "synth":
        synth()
    elif a[0] == "marts":
        marts()
    elif a[0] == "sql":
        with connect() as c, c.cursor() as cur:
            cur.execute(a[1])
            if cur.description:
                print(cur.fetchall())
    elif a[0] == "state":
        for k, v in state().items():
            print(f"  {k}: {v}")
    elif a[0] == "step":
        rc, dt, out = run_step(a[1])
        print(out[-3000:])
        print(f"[{a[1]}] rc={rc} {dt:.1f}s")
