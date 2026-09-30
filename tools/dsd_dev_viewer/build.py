"""
tools/dsd_dev_viewer/build.py - regenerate the DSD Dev Viewer (dev tool).

Replaces tools/bin_viewer (length_v1 bins only) and tools/routing_viewer
(combined_v1 per-bin refit, never the live router). One view of what is LIVE:

    Tier A (as of 2026-02, method 'single')
      -> combined_v1 bin (sku_segment)
      -> router bin      (forecast_result.model_params.bin, DEC-26 length_v2)
      -> served model    (model_params.method)
      -> backup          (model_params.backup_fired / backup_reason)

Nothing is refitted: every number is read from what the pipeline stored.
Read-only. One query per table, pulled once, embedded as JSON into
dsd_dev_viewer.html (self-contained, open by double-clicking).

Preview mode ("with 2021-22 placeholder") reads the output of
scripts/preview_router_synth.py: router_preview_synth.csv, series_synth.csv and
preview_summary.csv, copied into data/ at build time. The build stops if any is
missing. Placeholder months are never demand; the page labels them everywhere.

TWO THINGS ARE COMPUTED HERE RATHER THAN READ (both labelled as such on the
page, both checked against what the pipeline stored):
  - MA3's MASE on the served model's holdout months (ma3_same_holdout).
  - The confidence band over the HOLDOUT months (add_band_evidence). Only ONE
    band is stored per SKU, around the planning-month forecast; no per-month
    band exists anywhere. This re-runs the served model's rolling one-step
    holdout - DEC-25's own protocol - and applies the writer's rule to each
    month. Costs ~10s (one XGBoost booster per distinct holdout month, cached
    across SKUs); there is no cheaper way, because the numbers do not exist.

ETL and dashboard-API numbers on the Pipeline tab are NOT computed or queried:
every one is copied from a file under reports/ and carries its citation (see
ETL_NODES). Where no report states a number, the page prints "not on record".

Usage (from the repo root, .env holding SUPABASE_DIRECT_URL or SUPABASE_DB_URL):
    python tools/dsd_dev_viewer/build.py [--preview-src <folder>]
    python tools/dsd_dev_viewer/build.py --offline   # rebuild from data/db_snapshot.json
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time

import psycopg2
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

PRINCIPAL, ABC_PERIOD, ABC_METHOD = "unilever", "2026-02", "single"
REAL_START = "2023-01"
COMBINED_ORDER = ["insufficient", "short", "medium", "long_down", "long_flat", "long_up"]
ROUTER_ORDER = ["insufficient", "short", "medium", "long"]
BACKUP_ORDER = ["not fired", "not applicable", "fired"]
# analytics/forecasting/router.py LIVE_MODEL, plus the runner's provisional path
# for the insufficient bin (scripts/run_baseline_forecast.py _write_forecast_result).
# The note is a COHORT statement (half-year block tests) - the page shows it on
# model nodes and the banner only, never against a single SKU.
MODEL_LABEL = {
    "ma3": ("MA3", "benchmark"),
    "tsb": ("TSB", "cohort: ties MA3"),
    "xgb_ma3_avg": ("XGBoost + MA3 avg", "cohort: ties MA3"),
    "provisional": ("Provisional avg", "not scored"),
}
CHALLENGERS = {"tsb", "xgb_ma3_avg"}
# Expected counts for the traffic lights, as stated by Yuan on 2026-09-22 for the
# live 2026-03 forecast. A node with no entry here has no expected count on record.
EXPECTED = {
    "tier_a": 132,
    "combined": {"insufficient": 13, "short": 30, "medium": 17, "long_down": 22, "long_flat": 36, "long_up": 14},
    "router": {"insufficient": 13, "short": 30, "medium": 17, "long": 72},
    "model": {"ma3": 30, "tsb": 17, "xgb_ma3_avg": 72, "provisional": 13},
    "backup": {"not fired": 89, "not applicable": 43, "fired": 0},
    "forecast_result": 132,
}

# --------------------------------------------------------------------------- #
# The stored confidence band - what it actually is
# --------------------------------------------------------------------------- #
# Writer: scripts/run_baseline_forecast.py:825 (CONFIDENCE_Z) and :828
# (_confidence_band), called at :1034. Forecast_Result.confidence_lower/upper =
# forecast_value +/- 1.645 * the SERVED model's rolling one-step holdout RMSE,
# lower bound floored at 0, NULL/NULL when that RMSE is undefined. A symmetric
# normal-approximation interval around a point forecast - not a predictive
# interval from a fitted model.
#
# LEVEL: not decided anywhere. DEC-25 (ARCHITECTURE.md:95) states the RMSE basis
# and states no level. The only level claim in the repo is the writer's own
# comment (run_baseline_forecast.py:821-824): "~90% normal-approximation
# multiplier (not 95%'s 1.96)". 1.645 is the two-sided 90% normal quantile, so
# 90% is nominal and undocumented as a decision. Nothing in the repo measures
# whether it holds - which is what this page's coverage columns test.
CONFIDENCE_Z = 1.645
BAND_LEVEL_NOMINAL = 0.90
# The one phrase every level mention uses. There is no decided level to cite, so
# the multiplier and the absence of a DEC-25 statement travel with the number.
BAND_LEVEL_LABEL = ("nominal ~90% (level not documented in DEC-25; multiplier 1.645 "
                    "from the writer code)")
BAND_DEF = {
    "interval": "Symmetric normal-approximation interval around the point forecast: "
                "forecast ± 1.645 × RMSE, lower bound floored at 0. NULL/NULL when the RMSE is "
                "undefined (e.g. a 1-month holdout) - never a fabricated band.",
    "sigma": "The SERVED model's own rolling one-step holdout RMSE "
             "(model_params.holdout_metrics_served.rmse) - not MA3's, unless MA3 is what serves that "
             "SKU. Same holdout and same protocol as the stored mape / mase / wape (DEC-25).",
    "level": BAND_LEVEL_LABEL + ". 1.645 is the two-sided 90% normal quantile, and "
             "scripts/run_baseline_forecast.py:821-824 calls it a “~90% normal-approximation "
             "multiplier”. DEC-25 documents the RMSE basis and does NOT state a level, so there is "
             "no decided level to cite: the figure used as the comparison point below is that "
             "comment's nominal one and nothing stronger.",
    "stored": "ONE band per SKU, on the forecast_date row, around the PLANNING-month forecast. No "
              "per-holdout-month band is stored anywhere in the database.",
    "corridor": "The corridor on this page is computed at build time: the served model's rolling "
                "one-step holdout is re-run (DEC-25's protocol) and the writer's own rule is applied "
                "to each month's forecast, using that SKU's one holdout RMSE. The recomputation is "
                "checked against the stored mase / wape / rmse / holdout months.",
    "ma3": "No MA3 band is stored. model_params.holdout_metrics_all_methods.ma3.rmse exists but "
           "belongs to the RETIRED static 80/20 flat-line protocol - a different protocol from "
           "DEC-25's, so it is not this band. MA3's corridor here is computed from MA3's own rolling "
           "one-step RMSE on the same months, and is labelled computed everywhere it appears.",
    "z": CONFIDENCE_Z,
    "level_nominal": BAND_LEVEL_NOMINAL,
    "level_label": BAND_LEVEL_LABEL,
}

# --------------------------------------------------------------------------- #
# ETL and dashboard-API numbers - copied from reports/, never computed here
# --------------------------------------------------------------------------- #
# Rule for this block: a number appears only if a file under reports/ states it,
# and the citation travels with it. Where no report states one, the value is NOR
# and the page prints "not on record". The ETL stages are not re-run by this
# build, so nothing here is measured live.
NOR = "not on record"
ETL_NODES = {
    "raw": {
        "title": "Raw source files", "sub": "data/raw/ (read-only)",
        "source": "reports/FULL_DATA_AUDIT.md §A (generated 2026-08-25)",
        "io": ["in 569 files", "out 8 families"], "mline": "179 never classified",
        "columns": [["doc_type", 0], ["principal / corpus", 0], ["real?", 0], ["files", 1]],
        "rows": [
            ["inventory_sign_off", "delmonte", "real", 17],
            ["inventory_sign_off", "synthetic corpus", "synthetic", 92],
            ["purchase_order", "delmonte", "real", 11],
            ["purchase_order", "synthetic corpus", "synthetic", 104],
            ["rmr_gs_bo", "delmonte", "real", 2],
            ["sales_register", "delmonte", "real", 22],
            ["sales_return", "delmonte", "real", 19],
            ["sell_out", "delmonte", "real", 17],
            ["ssis_summary", "Unilever+SSIS folders", "real", 105],
            ["unilever_sku", "unilever", "real", 1],
            ["unknown (never classified)", "mixed", "mixed", 179],
        ],
        "checks": [
            {"ok": None, "text": "569 files on disk, and the 11 rows below sum to 569 exactly. No ROW count "
                                 "exists at this stage on record - Extract is the first stage that counts rows."},
            {"warn": True, "text": "179 files are never classified, so they have never been ingested under any "
                                   "doc_type: 178 synthetic SALES_REGISTER_*/SELL_OUT_* files plus one under "
                                   "data/raw/SSIS/. Root cause on record: profile_files.py's DOC_TYPE_PATTERNS "
                                   "matches whitespace where those filenames use an underscore."},
            {"ok": None, "text": "Formats: 567 .xlsx, 1 .xls (the La Union SKU file, MHTML-disguised), 1 file "
                                 "with no extension (.gitkeep)."},
        ],
    },
    "extract": {
        "title": "Extract", "sub": "extract/driver.py → staging/*.parquet",
        "source": "reports/PROJECT_STATE_2026-09.md §3 (staging/_manifest.json, 2026-08-20 20:44) + "
                  "reports/PHASE1_EXECUTION_PLAN_2026-09.md “Fresh manifest state” and §4",
        "io": ["in data/raw/ (569 files)", "out 1,590 sheets"], "mline": "2,089,347 rows · 0 reject",
        "columns": [["doc_type", 0], ["sheets staged", 1], ["rows staged", 1], ["rejects", 1]],
        "rows": [
            ["ALL (8 families)", 1590, 2089347, 0],
            ["ssis_summary", 805, 1949687, NOR],
            ["sales_return", 68, 1931, NOR],
            ["unilever_sku", 31, 44583, NOR],
            ["the other 5 families", NOR, NOR, NOR],
        ],
        "checks": [
            {"ok": None, "text": "8 families, 1,590 sheets, 2,089,347 rows staged, 0 rejects. No expected row "
                                 "count is on record to compare against."},
            {"warn": True, "text": "Per-family row counts are on record for 3 of the 8 families only; the other "
                                   "5 are not on record."},
            {"warn": True, "text": "unilever_sku's 31 sheets / 44,583 rows include ~30 non-La-Union sheets (SOH "
                                   "etc.), not just the one real SKU-demand file (1 file / 24,906 rows)."},
            {"ok": None, "text": "This manifest only ever tracked data/raw/. Synthetic files are written straight "
                                 "into staging/ by a separate step, never through extract.driver, so Transform "
                                 "sees more sheets than Extract staged - expected, not a defect (PHASE1 §4)."},
        ],
    },
    "transform": {
        "title": "Transform", "sub": "transform_driver.py → transform/_manifest.json",
        "source": "reports/PHASE1_EXECUTION_PLAN_2026-09.md “Fresh manifest state”, step 1, §1 "
                  "(purchase_order region fix), §2 (footer rows), §16 (sell_out relabel) + "
                  "reports/COLUMN_GAP_AUDIT_2026-09.md (inventory header artifacts)",
        "io": ["in staging/ glob", "out 720 promoted"], "mline": "902 demoted · 37 reject",
        "columns": [["manifest state", 0], ["promoted", 1], ["demoted", 1], ["reject (sheets)", 1], ["blocked", 1]],
        "rows": [
            ["2026-08-20 snapshot", 669, NOR, 921, 805],
            ["after Phase 1 step 1 (2026-09-09)", 720, 902, 86, 0],
            ["after the purchase_order region fix (2026-09-09)", NOR, NOR, 37, 0],
        ],
        "checks": [
            {"warn": True, "text": "37 sheets still reject, all genuine dedup conflicts: sales_return 14, "
                                   "inventory_sign_off 11, sell_out 7, sales_register 5, purchase_order 0 (was 49 "
                                   "before the region fix). 14 + 11 + 7 + 5 = 37."},
            {"ok": None, "text": "Rows dropped or rewritten BY RULE at Transform, where a report states the count: "
                                 "sales_register TOTAL/footer rows 181 raw / 177 post-mapping; inventory_sign_off "
                                 "7 section-header artifact rows; sell_out 1,023 source-defect 'False' category "
                                 "rows relabelled to UNCLASSIFIED and summed into 124 merged rows (22 real). "
                                 "Revenue preserved - relabelled and merged, not dropped."},
            {"ok": None, "text": "The 805 'blocked' sheets were ssis_summary against a null natural_key - a dead "
                                 "mapping, removed 2026-09-09. They reclassify as cleanly demoted, not lost data "
                                 "(no product grain, 0 real DB rows ever traced to them)."},
        ],
    },
    "load": {
        "title": "Load", "sub": "scripts/run_canonical_load.py",
        "source": "reports/PHASE1_EXECUTION_PLAN_2026-09.md §11 (full row accounting, 2026-09-14), §14 "
                  "(item 36), §16 (item 40a) + reports/PROJECT_STATE_2026-09.md §10 (frozen targets) and "
                  "§11 (cutover counts, 2026-09-16)",
        "io": ["in 135,007 rows", "out 157,923 loaded"], "mline": "912 quarantined (real)",
        "columns": [["fact table", 0], ["combined in", 1], ["quarantined (NOT NULL key)", 1],
                    ["dropped (NOT NULL other)", 1], ["dropped (conflict group)", 1],
                    ["after rule relabel / merge", 1], ["loaded", 1], ["frozen target", 1]],
        "rows": [
            ["unilever_sku_demand_fact", 44575, 0, 0, 0, "—", 44575, 44575],
            ["sales_fact", 53742, 432, 197, 4, "—", 53109, 53109],
            ["purchase_fact", 4594, 27, 13, 1792, "—", 2762, 2762],
            ["salesreturn_fact", 1900, 0, 0, 270, "—", 1630, 1630],
            ["sellout_fact", 8584, 0, 0, 26, 7686, 7660, 7660],
            ["inventory_fact (inventory_sign_off)", 21612, 453, 0, 254, "—", 20905, 20905],
            ["inventory_fact (ssis_soh / unilever)", NOR, NOR, NOR, NOR, "—", 27282, 27282],
        ],
        "checks": [
            {"ok": True, "text": "Every frozen target matched exactly at the 2026-09-16 cutover: sales 53,109 / "
                                 "purchase 2,762 / sales_return 1,630 / sell_out 7,660 / inventory 48,187 "
                                 "(20,905 DM + 27,282 UL) / demand 44,575."},
            {"warn": True, "text": "sell_out's relabel arithmetic does not close on record: PHASE1 §16 gives "
                                   "8,584 in, 1,023 removed, 124 added and states 7,686 - but 8,584 - 1,023 + 124 "
                                   "= 7,685. 7,686 is the MEASURED count and 7,686 - 26 = 7,660 matches the "
                                   "target, so one row is unexplained in the report, not in the data."},
            {"warn": True, "text": "inventory_sign_off is 20,905 in public. A later fix (7 section-header artifact "
                                   "rows excluded, COLUMN_GAP_AUDIT_2026-09.md) takes the code target to 20,898; "
                                   "no re-load into public is on record."},
            {"ok": None, "text": "'in 135,007 rows' is the sum of the six combined-in counts below. It "
                                 "excludes ssis_soh, whose input count is not on record - only its 27,282 "
                                 "loaded rows are."},
            {"ok": None, "text": "The quarantined and conflict columns are REAL-ONLY by design (FACT_PLAN's own "
                                 "comment): demo-data noise is counted and printed separately by the loader, never "
                                 "blended into a pass/fail target. 'combined in' and 'loaded' are real+demo."},
            {"ok": None, "text": "purchase_fact's conflict-group column is 1,792 (demo only) AFTER item 36's fix. "
                                 "Before it, 1,887 rows were dropped including 95 real ones and the loaded count "
                                 "was 2,667."},
            {"ok": None, "text": "salesreturn_fact was 0 rows in public before the cutover (the BO path was dead), "
                                 "so its 1,630 rows are a clean addition - nothing overwritten."},
        ],
    },
    "base": {
        "title": "Base fact tables", "sub": "public schema (Supabase)",
        "source": "reports/PROJECT_STATE_2026-09.md §11 “Final counts, 2026-09-16” "
                  "(post-cutover public)",
        "io": ["in the Load run above", "out 157,923 rows"], "mline": "6 fact tables",
        "columns": [["table", 0], ["rows in public", 1], ["real", 1], ["demo", 1]],
        "rows": [
            ["unilever_sku_demand_fact", 44575, 24906, 19669],
            ["sales_fact", 53109, NOR, NOR],
            ["purchase_fact", 2762, NOR, NOR],
            ["salesreturn_fact", 1630, NOR, NOR],
            ["sellout_fact", 7660, NOR, NOR],
            ["inventory_fact", 48187, NOR, NOR],
        ],
        "checks": [
            {"ok": None, "text": "This is the first node INSIDE Supabase. Everything to its left is Python "
                                 "reading files; everything from here on is a table or a view."},
            {"warn": True, "text": "The real / demo split post-cutover is on record for unilever_sku_demand_fact "
                                   "only. POST_LOAD_VERIFICATION.md has a full split but is a 2026-08-20 "
                                   "pre-cutover snapshot and its totals no longer match, so it is not quoted here."},
            {"ok": None, "text": "inventory_fact's 48,187 is 20,905 Del Monte (inventory_sign_off) + 27,282 "
                                 "Unilever (ssis_soh), two different doc_types in one table."},
            {"ok": None, "text": "Demo rows load into these base tables by design and are excluded downstream by "
                                 "the _Real views, never by a caller-supplied filter (CLAUDE.md rule 1)."},
        ],
    },
    "api": {
        "title": "Dashboard API", "sub": "GET /forecast/{sku_id} · GET /dashboard",
        "source": "reports/FRONTEND_HANDOFF_2026-09-20.md (verified 2026-09-20)",
        "io": ["in forecast_result", "out 17 routes"], "mline": "3 principal scopes",
        "columns": [["check", 0], ["result", 0]],
        "rows": [
            ["All 17 frontend-facing routes × 3 principal scopes", "200"],
            ["npm run build", "exit 0, 731 ms, 18 chunks, no warnings"],
            ["Backend importing anything from analytics/", "none - offline scripts cannot affect the API"],
            ["Test suite", "303 passed / 13 failed / 1 skipped (the 13 pre-existing)"],
        ],
        "checks": [
            {"ok": None, "text": "This is where the band leaves Supabase. backend/routers/forecast.py:75-87 passes "
                                 "confidence_lower/upper through per SKU; backend/routers/dashboard.py:996-1105 "
                                 "SUMS them across SKUs per period for the dashboard chart, so the dashboard's "
                                 "band is a sum of per-SKU bands."},
            {"warn": True, "text": "Verified 2026-09-20 by scripts/smoke_api.py, NOT by this build - this page "
                                   "never calls the API. Re-run that script before trusting the row above."},
        ],
    },
}

COHORT = """SELECT product_key FROM abc_classification
            WHERE principal = %(p)s AND classification_period = %(per)s AND tier = 'A' AND method = %(m)s"""

QUERIES = {
    "abc": """SELECT product_key, tier FROM abc_classification
              WHERE principal = %(p)s AND classification_period = %(per)s AND method = %(m)s""",
    "product": f"""SELECT product_key, sku_code, product_name FROM product_dimension
                   WHERE product_key IN ({COHORT})""",
    "segment": f"""SELECT product_key,
                          json_object_agg(scheme, json_build_object('bin', bin, 'reason', bin_reason))
                   FROM sku_segment
                   WHERE principal = %(p)s AND cohort_period = %(per)s AND abc_method = %(m)s
                     AND product_key IN ({COHORT})
                   GROUP BY product_key""",
    "traits": f"""SELECT product_key, history_months, first_sale_period, longest_run, trend, trend_slope,
                         trend_pvalue, cv, adi, restart_flag, stability_group, revenue_share_2026_02
                  FROM sku_traits
                  WHERE principal = %(p)s AND cohort_period = %(per)s AND abc_method = %(m)s
                    AND product_key IN ({COHORT})""",
    "forecast": f"""SELECT product_key, forecast_date::text, forecast_value, confidence_lower, confidence_upper,
                           mape, mase, status,
                           model_params->>'bin', model_params->>'method', model_params->>'ma3_value',
                           model_params->'holdout_metrics_served', model_params->>'backup_fired',
                           model_params->>'backup_reason', model_params->'components',
                           model_params->>'provisional', model_params->>'sales_months'
                    FROM forecast_result
                    WHERE forecast_date = (SELECT MAX(forecast_date) FROM forecast_result)
                      AND product_key IN ({COHORT})""",
    # One pass over the whole view: every SKU's row count (the Pipeline node's
    # rows in), and the monthly series for the Tier A cohort only.
    "demand": f"""SELECT product_key, SUM(n_rows)::int,
                         json_object_agg(calendar_month, qty) FILTER (
                             WHERE product_key IN ({COHORT}) AND calendar_month BETWEEN %(start)s AND %(per)s)
                  FROM (SELECT product_key, calendar_month, SUM(quantity_sold) AS qty, COUNT(*) AS n_rows
                        FROM unilever_sku_demand_fact_real
                        GROUP BY 1, 2) d
                  GROUP BY product_key""",
}


def _num(v, nd=4):
    return None if v is None else round(float(v), nd)


def _connect():
    """Read-only connection, SUPABASE_DIRECT_URL first then SUPABASE_DB_URL.

    It used to be `DIRECT or DB_URL`, which fails outright when only the direct
    host is unreachable (2026-09-23: its DNS name no longer resolves from this
    machine while the pooled host does). Both are tried, the one that connected
    is reported, and every failure is printed - a build must not be able to
    silently read a different database than the banner claims."""
    load_dotenv(os.path.join(REPO, ".env"))
    errors = []
    for name in ("SUPABASE_DIRECT_URL", "SUPABASE_DB_URL"):
        url = os.environ.get(name)
        if not url:
            errors.append(f"{name}: unset")
            continue
        try:
            conn = psycopg2.connect(url, connect_timeout=20)
        except psycopg2.OperationalError as exc:
            errors.append(f"{name}: {str(exc).strip().splitlines()[0]}")
            continue
        # Read-only is transaction-scoped (fetch()'s first statement), never
        # set_session: that sets default_transaction_read_only on the server
        # session, which through the :6543 pooler outlives this connection and
        # leaves the next client unable to write.
        return conn, name
    raise SystemExit("no database reachable:\n  " + "\n  ".join(errors)
                     + f"\nrebuild the page from the last snapshot with: --offline ({SNAPSHOT})")


def fetch() -> tuple[dict, dict, str]:
    conn, dsn = _connect()
    cur = conn.cursor()
    # One psycopg2-managed transaction (autocommit off: it opens with BEGIN),
    # made READ ONLY by its first statement. Nothing commits it; rollback()
    # ends it, and close() discards it on any error exit.
    cur.execute("SET TRANSACTION READ ONLY")
    params = {"p": PRINCIPAL, "per": ABC_PERIOD, "m": ABC_METHOD, "start": REAL_START}
    out, timing = {}, {}
    try:
        for name, sql in QUERIES.items():
            t = time.perf_counter()
            cur.execute(sql, params)
            out[name] = cur.fetchall()
            timing[name] = round(time.perf_counter() - t, 2)
        conn.rollback()
    finally:
        conn.close()
    return out, timing, dsn


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    res = []
    while (y, m) <= (ey, em):
        res.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return res


def recent_level_ratio(series: list[float]) -> float | None:
    """mean(last 3) / mean(last 12) of the SKU's modelling series. Display only,
    no threshold. None under 12 months or when the 12-month mean is not positive."""
    if len(series) < 12:
        return None
    m12 = sum(series[-12:]) / 12
    return None if m12 <= 0 else sum(series[-3:]) / 3 / m12


def model_series(monthly: list, periods: list[str]):
    """The modelling series: first row -> last row, gaps zero-filled. Exactly
    what scripts/run_baseline_forecast.build_series() hands the router, rebuilt
    from the monthly values this page already holds. None with no rows at all."""
    import pandas as pd
    present = [i for i, v in enumerate(monthly) if v is not None]
    if not present:
        return None
    a, b = present[0], present[-1]
    idx = pd.to_datetime([periods[i] + "-01" for i in range(a, b + 1)])
    return pd.Series([monthly[i] or 0.0 for i in range(a, b + 1)], index=idx, dtype=float)


def ma3_same_holdout(monthly: list, periods: list[str]) -> tuple[float | None, int]:
    """MA3's MASE on the same rolling one-step holdout the served model was
    scored on. Reuses the pipeline's own pieces, no reimplementation:
      series  first row -> last row, gaps zero-filled (run_baseline_forecast.build_series)
      split   analytics.forecasting.sarima.train_holdout_split (last 20%)
      MA3     analytics.forecasting.router.rolling_one_step, column "ma3"
              (router.ma3_value from the first sale, floored at zero)
      metric  diagnostic_metrics.mase with naive_scale(train)
    Pure computation on the rows already pulled; no DB access."""
    import numpy as np
    from analytics.forecasting.diagnostic_metrics import mase, naive_scale
    from analytics.forecasting.router import rolling_one_step
    from analytics.forecasting.sarima import HOLDOUT_FRACTION, train_holdout_split
    series = model_series(monthly, periods)
    if series is None:
        return None, 0
    train, holdout = train_holdout_split(series, holdout_fraction=HOLDOUT_FRACTION)
    scored = rolling_one_step(series, list(holdout.index), None, force_bin="short")
    m = mase(scored["actual"].to_numpy(), scored["ma3"].to_numpy(), naive_scale(train.to_numpy(dtype=float)))
    return (None if not np.isfinite(m) else m), len(scored)


def assemble(raw: dict) -> dict:
    tiers = {r[0]: r[1] for r in raw["abc"]}
    cohort = sorted(pk for pk, t in tiers.items() if t == "A")
    product = {r[0]: r[1:] for r in raw["product"]}
    segment = {r[0]: r[1] for r in raw["segment"]}
    traits = {r[0]: r[1:] for r in raw["traits"]}
    forecast = {r[0]: r[1:] for r in raw["forecast"]}
    view_rows = {r[0]: r[1] for r in raw["demand"]}
    demand = {r[0]: r[2] for r in raw["demand"] if r[2] is not None}
    periods = months(REAL_START, ABC_PERIOD)

    skus, problems = [], []
    for pk in cohort:
        code, name = product.get(pk, (None, None))
        seg = segment.get(pk, {})
        tr = traits.get(pk)
        fc = forecast.get(pk)
        if tr is None:
            problems.append(f"{pk}: no sku_traits row")
        if fc is None:
            problems.append(f"{pk}: no forecast_result row")
        (fdate, fval, lo, hi, mape, mase, status, rbin, method, ma3, served, fired, reason, comps, prov,
         smonths) = fc if fc else (None,) * 16
        if status == "insufficient_data":
            rbin, method = rbin or "insufficient", "provisional"
        served = served or {}
        dm = demand.get(pk, {})
        monthly = [None if dm.get(p) is None else _num(dm[p], 1) for p in periods]
        # a row whose quantity is NULL: the pipeline's fetch_demand fillna(0) counts it as 0
        null_months = [i for i, p in enumerate(periods) if p in dm and dm[p] is None]
        present = sorted({i for i, v in enumerate(monthly) if v is not None} | set(null_months))
        first_i, last_i = (present[0], present[-1]) if present else (None, None)
        # The modelling series: first row -> last row, gaps zero-filled
        # (scripts/run_baseline_forecast.py build_series). Its holdout is the last
        # holdout_months of that span (analytics/forecasting/sarima.py train_holdout_split).
        model_series = [monthly[i] or 0.0 for i in range(first_i, last_i + 1)] if present else []
        h = served.get("months")
        holdout = [last_i - h + 1, last_i] if h and present else None
        fval_n, ma3_n = _num(fval, 3), _num(ma3, 3)
        rlr = recent_level_ratio(model_series)
        ma3_mase, ma3_hmonths = ma3_same_holdout(monthly, periods) if status == "ok" else (None, 0)
        if status == "ok" and ma3_hmonths != h:
            problems.append(f"{pk}: MA3 holdout {ma3_hmonths} months vs served {h}")
        skus.append({
            "pk": pk, "code": code, "name": name,
            "combined": (seg.get("combined_v1") or {}).get("bin"),
            "bin_reason": (seg.get("combined_v1") or {}).get("reason"),
            "schemes": {k: v["bin"] for k, v in seg.items()},
            "router_bin": rbin, "method": method, "status": status,
            "forecast_date": fdate, "served": fval_n, "lo": _num(lo, 3), "hi": _num(hi, 3),
            "ma3": ma3_n, "components": comps,
            "gap": None if fval_n is None or not ma3_n else round((fval_n - ma3_n) / ma3_n, 4),
            "rlr": None if rlr is None else round(rlr, 3),
            # the RMSE the band was built from (model_params.holdout_metrics_served.rmse)
            "rmse": _num(served.get("rmse")),
            "mase": _num(mase), "ma3_mase": _num(ma3_mase), "mape": _num(mape), "wape": _num(served.get("wape")),
            "ma3_wape": _num(served.get("ma3_wape")), "holdout_months": h, "holdout": holdout,
            "backup": ("fired" if fired == "true" else "not fired") if method in CHALLENGERS else "not applicable",
            "backup_reason": reason,
            "provisional": prov == "true", "sales_months": int(smonths) if smonths else None,
            "view_rows": view_rows.get(pk, 0), "first_i": first_i, "last_i": last_i,
            "gap_months": sum(1 for i in range(first_i, last_i + 1) if monthly[i] is None and i not in null_months) if present else 0,
            "null_months": null_months,
            "neg_months": sum(1 for v in monthly if v is not None and v < 0),
            "traits": None if tr is None else {
                "history_months": tr[0], "first_sale": tr[1], "longest_run": tr[2], "trend": tr[3],
                "trend_slope": _num(tr[4]), "trend_pvalue": _num(tr[5]), "cv": _num(tr[6]), "adi": _num(tr[7]),
                "restart_flag": tr[8], "stability_group": tr[9], "revenue_share": _num(tr[10], 5)},
            "monthly": monthly,
        })

    def count(key, order):
        c = {k: 0 for k in order}
        for s in skus:
            c[s[key]] = c.get(s[key], 0) + 1
        return c

    edges = {}
    for s in skus:
        for a, b in ((("src", "Tier A"), ("combined", s["combined"])),
                     (("combined", s["combined"]), ("router", s["router_bin"])),
                     (("router", s["router_bin"]), ("model", s["method"])),
                     (("model", s["method"]), ("backup", s["backup"]))):
            k = f"{a[0]}:{a[1]}|{b[0]}:{b[1]}"
            edges[k] = edges.get(k, 0) + 1

    tier_counts = {}
    for t in tiers.values():
        tier_counts[t] = tier_counts.get(t, 0) + 1
    return {
        "meta": {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                 "cohort": f"Tier A as of {ABC_PERIOD}, method '{ABC_METHOD}'", "principal": PRINCIPAL,
                 "n": len(cohort), "forecast_date": next((s["forecast_date"] for s in skus if s["forecast_date"]), None),
                 "problems": problems,
                 "view_rows": sum(view_rows.values()), "view_skus": len(view_rows),
                 "abc_classified": len(tiers), "abc_tiers": tier_counts},
        "periods": periods, "combined_order": COMBINED_ORDER, "router_order": ROUTER_ORDER,
        "backup_order": BACKUP_ORDER, "model_label": MODEL_LABEL, "expected": EXPECTED,
        "counts": {"combined": count("combined", COMBINED_ORDER), "router": count("router_bin", ROUTER_ORDER),
                   "model": count("method", list(MODEL_LABEL)), "backup": count("backup", BACKUP_ORDER),
                   "status": count("status", [])},
        "edges": [{"from": k.split("|")[0], "to": k.split("|")[1], "n": v} for k, v in sorted(edges.items())],
        "skus": skus,
    }


# --------------------------------------------------------------------------- #
# The band over the holdout months, and its coverage
# --------------------------------------------------------------------------- #
def one_band(value, rmse):
    """scripts/run_baseline_forecast.py::_confidence_band, applied to one month.
    Same multiplier, same floor at zero, same None/None when rmse is undefined."""
    if rmse is None or value is None:
        return None, None
    return max(0.0, value - CONFIDENCE_Z * rmse), value + CONFIDENCE_Z * rmse


def add_band_evidence(payload: dict) -> dict:
    """Per-SKU band corridor across the holdout months, plus coverage.

    WHY THIS IS COMPUTED AND NOT READ: Forecast_Result stores one band per SKU,
    around the planning-month forecast. A corridor needs a forecast per holdout
    month, and nothing stores those. So the served model's rolling one-step
    holdout is re-run here - DEC-25's own protocol, the same one the stored
    mape/mase/wape/rmse come from - and the writer's rule (one_band) is applied
    to each month using that SKU's single holdout RMSE.

    THE RECOMPUTATION IS CHECKED, NOT TRUSTED: for every scored SKU the MASE,
    WAPE, RMSE and holdout-month count this produces are compared against what
    the pipeline stored, and main() prints how many of the 119 agree. If those
    counts are not 119/119 the corridor is not the served model's and the page
    says so rather than drawing it.

    Coverage = holdout months whose actual falls inside that month's band,
    over holdout months. Band width / forecast is taken from the STORED band
    (confidence_upper - confidence_lower) / forecast_value, i.e. the number the
    SKU panel already shows, floor included. MA3's corridor is computed the same
    way from MA3's own rolling one-step RMSE on the same months - no MA3 band is
    stored anywhere (BAND_DEF['ma3'])."""
    import statistics

    from analytics.forecasting.diagnostic_metrics import mase, naive_scale, rmse as rmse_metric, wape
    from analytics.forecasting.global_model import GlobalForecaster
    from analytics.forecasting.router import rolling_one_step
    from analytics.forecasting.sarima import HOLDOUT_FRACTION, train_holdout_split

    periods = payload["periods"]
    pool = {}
    for s in payload["skus"]:
        ser = model_series(s["monthly"], periods)
        if ser is not None:
            pool[s["pk"]] = ser
    # The same Tier A training pool served_forecasts() builds, so the global
    # model sees the same cross-SKU history it saw when the row was written.
    forecaster = GlobalForecaster(pool)
    agree = {"n": 0, "mase": 0, "wape": 0, "rmse": 0, "months": 0}
    derived, months_seen = 0, []

    for s in payload["skus"]:
        for k in ("hpath", "cov", "bw", "ma3_cov", "ma3_bw", "ma3_rmse", "outside"):
            s.setdefault(k, None)
        if s["status"] != "ok" or s["pk"] not in pool:
            continue
        series = pool[s["pk"]]
        train, holdout = train_holdout_split(series, holdout_fraction=HOLDOUT_FRACTION)
        scored = rolling_one_step(series, list(holdout.index), forecaster, force_bin=s["router_bin"])
        if scored.empty:
            continue
        a = scored["actual"].to_numpy(dtype=float)
        v = scored["value"].to_numpy(dtype=float)
        m3 = scored["ma3"].to_numpy(dtype=float)
        scale = naive_scale(train.to_numpy(dtype=float))

        # The band's own sigma. A snapshot cached before this build stored it has
        # to invert the stored band instead: confidence_upper is never floored,
        # so (hi - forecast) / Z recovers it to the band's 2-dp precision.
        r = s.get("rmse")
        if r is None and s.get("hi") is not None and s.get("served") is not None:
            r = round((s["hi"] - s["served"]) / CONFIDENCE_Z, 4)
            s["rmse"], s["rmse_derived"] = r, True
            derived += 1
        r3 = _num(rmse_metric(a, m3))

        rows = []
        for i, month in enumerate(scored["month"]):
            key = month.strftime("%Y-%m")
            lo, hi = one_band(float(v[i]), r)
            lo3, hi3 = one_band(float(m3[i]), r3)
            rows.append({
                "m": key, "i": periods.index(key) if key in periods else None,
                "a": _num(a[i], 1), "v": _num(v[i], 3), "lo": _num(lo, 3), "hi": _num(hi, 3),
                "m3": _num(m3[i], 3), "lo3": _num(lo3, 3), "hi3": _num(hi3, 3),
                "out": None if lo is None else not (lo <= a[i] <= hi),
                "out3": None if lo3 is None else not (lo3 <= a[i] <= hi3),
                "bu": bool(scored["backup_fired"].iloc[i]),
            })
        s["hpath"] = rows
        s["outside"] = [x["i"] for x in rows if x["out"]]
        tested = [x for x in rows if x["out"] is not None]
        tested3 = [x for x in rows if x["out3"] is not None]
        s["cov"] = None if not tested else round(sum(1 for x in tested if not x["out"]) / len(tested), 4)
        s["ma3_cov"] = None if not tested3 else round(sum(1 for x in tested3 if not x["out3"]) / len(tested3), 4)
        # width / forecast, from the stored band for the served model and from
        # the same rule applied to MA3's planning-month value for MA3
        if s.get("lo") is not None and s.get("hi") is not None and s.get("served"):
            s["bw"] = round((s["hi"] - s["lo"]) / s["served"], 4)
        lo3p, hi3p = one_band(s.get("ma3"), r3)
        if lo3p is not None and s.get("ma3"):
            s["ma3_bw"] = round((hi3p - lo3p) / s["ma3"], 4)
        s["ma3_rmse"] = r3

        agree["n"] += 1
        months_seen.append(len(rows))
        tol = 0.02 if s.get("rmse_derived") else 0.0006
        got_mase, got_wape = mase(a, v, scale), wape(a, v)
        if s["mase"] is not None and abs(got_mase - s["mase"]) <= 0.0006:
            agree["mase"] += 1
        if s["wape"] is not None and abs(got_wape - s["wape"]) <= 0.0006:
            agree["wape"] += 1
        if r is not None and abs(rmse_metric(a, v) - r) <= tol:
            agree["rmse"] += 1
        if len(rows) == s["holdout_months"]:
            agree["months"] += 1

    def block(rows):
        cov = [s["cov"] for s in rows if s["cov"] is not None]
        cov3 = [s["ma3_cov"] for s in rows if s["ma3_cov"] is not None]
        bw = [s["bw"] for s in rows if s["bw"] is not None]
        bw3 = [s["ma3_bw"] for s in rows if s["ma3_bw"] is not None]
        med = lambda xs: None if not xs else round(statistics.median(xs), 4)
        return {"n": len(rows), "scored": len(cov), "cov": med(cov), "bw": med(bw),
                "below": sum(1 for c in cov if c < BAND_LEVEL_NOMINAL),
                "cov3": med(cov3), "bw3": med(bw3),
                "below3": sum(1 for c in cov3 if c < BAND_LEVEL_NOMINAL)}

    scored_skus = [s for s in payload["skus"] if s["cov"] is not None]
    return {
        **BAND_DEF, "agree": agree, "derived_rmse": derived,
        "all": block(scored_skus),
        "by_model": {m: block([s for s in scored_skus if s["method"] == m])
                     for m in MODEL_LABEL if any(s["method"] == m for s in scored_skus)},
        "holdout_months": [min(months_seen), max(months_seen)] if months_seen else None,
        # 1-8 holdout months means coverage can only take values k/n: with 8
        # months the nearest step below 1.0 is 0.875, so no SKU can land between
        # 0.875 and 1.0. "Below 90%" therefore means "at least one month outside",
        # not "close to the nominal level" - stated here so the count is not read
        # as a near miss.
        "granularity": ("Coverage can only take values k/n with n = the SKU's holdout months "
                        "(1-8 here), so no SKU can score between 0.875 and 1.0. Below the "
                        + BAND_LEVEL_LABEL + " means at least one holdout month fell outside the band."),
    }


# --------------------------------------------------------------------------- #
# Fit review - is the served forecast fit to use on this SKU?
# --------------------------------------------------------------------------- #
FIT_REVIEW = os.path.join(REPO, "reports", "diagnostics", "fit_review_common_2026-09-23.csv")

# CAUSE GROUPS come from the CSV's own cause_group column, with every threshold
# recorded in reports/diagnostics/README.md. Nothing is derived here: the earlier
# volatility_v1 substitute and the "cause not on record" fallback are gone, and
# "none of the above" is the CSV's own label for a SKU where no rule fires - a
# real result, not a gap. The rules are not exclusive; cause_group is the FIRST
# match, so a SKU can carry other cause_is_* flags too, and the SKU note lists them.
CAUSE_ORDER = ["level shift", "spiky", "high volatility", "intermittent", "tiny scale",
               "trend reversal", "none of the above"]
CAUSE_FLAGS = {"cause_is_level_shift": "level shift", "cause_is_spiky": "spiky",
               "cause_is_high_volatility": "high volatility", "cause_is_intermittent": "intermittent",
               "cause_is_tiny_scale": "tiny scale", "cause_is_trend_reversal": "trend reversal"}
CAUSE_THRESHOLDS = [
    ("level shift", "mean(last 6) / mean(prior 12) outside 0.7-1.3; needs >=18 months"),
    ("spiky", ">=1 month more than 3 x MAD from the SKU's median (MAD raw/unscaled)"),
    ("high volatility", "CV(last 12) > cohort p75 = 0.4365 (measured over the 119 scored SKUs)"),
    ("intermittent", "zero-or-missing share >= 0.30 or longest zero run >= 3 months"),
    ("tiny scale", "median monthly units <= cohort lower quartile = 812.5 units (measured)"),
    ("trend reversal", "sign(Theil-Sen slope, last 12) != sign(Theil-Sen slope, full history)"),
]
VERDICT_ORDER = ["clean", "borderline", "not fit", "no verdict (never scored)"]
# The guardrail sentence every not-fit SKU carries, per Yuan 2026-09-23. The
# "0 of 51" is his figure, quoted as given; it is not recomputed here.
NO_BETTER_MODEL = ("51 candidate models were tested on these SKUs; none passed the test. "
                   "This is treated as a review flag, not a model problem.")


def _num(v, nd=4):
    return None if v is None else round(float(v), nd)


def _median(values):
    import statistics
    vals = [v for v in values if v is not None]
    return None if not vals else round(statistics.median(vals), 4)


def load_fit_review(payload: dict) -> dict:
    """reports/diagnostics/fit_review_common_2026-09-23.csv, merged per SKU.

    Hard-fails if the file is missing: a viewer that silently drops the fit
    verdicts would show every SKU as unlabelled and look like good news.

    Nothing is recomputed from it - the verdict, its flags, both scorings and
    MA3's are carried through as the CSV gives them. What IS checked: that the
    CSV covers the cohort exactly, and that its mase_pipeline and
    band_width_over_forecast_stored agree with what this build read from the
    database. A disagreement means the CSV and the DB are describing different
    runs, and main() prints it."""
    import csv

    if not os.path.isfile(FIT_REVIEW):
        raise SystemExit(f"fit review missing: {FIT_REVIEW}\n"
                         f"The Unfit view cannot be built without it and this build will not "
                         f"produce a page that quietly omits the verdicts.")
    with open(FIT_REVIEW, encoding="utf-8-sig", newline="") as fh:
        rows = {int(r["product_key"]): r for r in csv.DictReader(fh)}

    def num(v):
        try:
            return None if v in (None, "") else round(float(v), 4)
        except ValueError:
            return None

    cohort = {s_["pk"] for s_ in payload["skus"]}
    agree = {"n": 0, "mase": 0, "bw": 0}
    spike_check = {"n": 0, "ok": 0, "bad": []}
    level_check = {"n": 0, "ok": 0, "bad": []}
    counts = {"verdict": {}, "cause": {}, "cause_verdict": {}, "by_bin": {}}
    for sku in payload["skus"]:
        r = rows.get(sku["pk"])
        if r is None:
            sku.update(verdict="not in the fit review", cause="no verdict", assessable=None)
            continue
        scored = r["verdict"] in ("clean", "borderline", "not fit")
        cause = r["cause_group"]
        sku.update(
            causes_all=[label for col, label in CAUSE_FLAGS.items() if r.get(col) == "1"],
            cause_level_shift=num(r["cause_level_shift"]), cause_cv=num(r["cause_cv_last12"]),
            cause_median_units=num(r["cause_median_units"]), cause_spikes=num(r["cause_n_spikes"]),
            cause_mad=num(r["cause_mad"]),
            cause_zero_share=num(r["cause_zero_missing_share"]), cause_zero_run=num(r["cause_longest_zero_run"]),
            cause_n_months=num(r["cause_n_months"]), cause_is_level_shift=r["cause_is_level_shift"] == "1",
            sales_months_fit=num(r["sales_months"]),
            verdict=r["verdict"], cause=cause,
            assessable=r["assessable"] == "yes", assessable_reason=r["assessable_reason"],
            verdict_source=r["verdict_source"],
            mase_common=num(r["mase_common"]), mase_pipeline=num(r["mase_pipeline"]),
            ma3_mase_common=num(r["ma3_mase_common"]),
            ma3_fails=r["ma3_also_fails_common"] == "1",
            rlr_fit=num(r["recent_level_ratio"]),
            bw_csv=num(r["band_width_over_forecast_stored"]),
            flags=[k[5:].replace("_", " ") for k in
                   ("flag_mase_not_fit", "flag_mase_borderline", "flag_recent_level", "flag_diverges_from_ma3")
                   if r[k] == "1"],
        )
        counts["verdict"][r["verdict"]] = counts["verdict"].get(r["verdict"], 0) + 1
        counts["cause"][cause] = counts["cause"].get(cause, 0) + 1
        counts["cause_verdict"].setdefault(cause, {})
        counts["cause_verdict"][cause][r["verdict"]] = counts["cause_verdict"][cause].get(r["verdict"], 0) + 1
        counts["by_bin"].setdefault(sku["router_bin"], {})
        counts["by_bin"][sku["router_bin"]][r["verdict"]] = counts["by_bin"][sku["router_bin"]].get(r["verdict"], 0) + 1
        # ONE month record per SKU, on the same modelling series the chart draws
        # and the holdout path scores, dated by that series' own period index.
        # The banner, the series sentences and Band detail all read it; none of
        # them reads a month from the CSV. Each part is re-derived from the CSV's
        # parameters and must reproduce the CSV's number, or it is withheld.
        #   spike_months  |value - cause_median_units| > 3 x cause_mad, whole series;
        #                 the count must equal cause_n_spikes.
        #   lvl           README's level-shift rule, mean(last 6) / mean(prior 12),
        #                 with the two windows it was measured on; the ratio must
        #                 equal cause_level_shift. cause_largest_step_month is NOT
        #                 used: its producer is not in the repo and no definition
        #                 tried reproduces it (it dated 65004662's change to
        #                 2023-04 while the ratio beside it is measured on
        #                 2024-09..2026-02).
        med, mad = sku["cause_median_units"], sku["cause_mad"]
        months = payload["periods"]
        sku["spike_top"], sku["spike_months"], sku["lvl"] = None, None, None
        if med is not None and mad is not None and sku["first_i"] is not None:
            hits = [(months[i], sku["monthly"][i] or 0.0)
                    for i in range(sku["first_i"], sku["last_i"] + 1)
                    if abs((sku["monthly"][i] or 0.0) - med) > 3 * mad]
            spike_check["n"] += 1
            if len(hits) == int(sku["cause_spikes"] or 0):
                spike_check["ok"] += 1
                sku["spike_months"] = [m for m, _ in hits]
                if hits:
                    m, v = max(hits, key=lambda h: abs(h[1] - med))
                    sku["spike_top"] = {"m": m, "v": _num(v, 1)}
            else:
                spike_check["bad"].append(sku["code"])
        if sku["cause_level_shift"] is not None and sku["first_i"] is not None:
            a, b = sku["first_i"], sku["last_i"]
            series = [sku["monthly"][i] or 0.0 for i in range(a, b + 1)]
            level_check["n"] += 1
            prior = sum(series[-18:-6]) / 12 if len(series) >= 18 else 0.0
            ratio = None if prior <= 0 else sum(series[-6:]) / 6 / prior
            if ratio is not None and abs(round(ratio, 3) - sku["cause_level_shift"]) <= 0.0006:
                level_check["ok"] += 1
                sku["lvl"] = {"r": sku["cause_level_shift"],
                              "prior": [months[b - 17], months[b - 6]], "recent": [months[b - 5], months[b]]}
            else:
                level_check["bad"].append(sku["code"])
        if scored:
            agree["n"] += 1
            if sku["mase"] is not None and sku["mase_pipeline"] is not None and abs(sku["mase"] - sku["mase_pipeline"]) <= 0.0011:
                agree["mase"] += 1
            if sku["bw"] is not None and sku["bw_csv"] is not None and abs(sku["bw"] - sku["bw_csv"]) <= 0.0011:
                agree["bw"] += 1
    return {
        "file": os.path.relpath(FIT_REVIEW, REPO).replace("\\", "/"),
        "rows": len(rows), "missing": sorted(cohort - set(rows)), "extra": sorted(set(rows) - cohort),
        "agree": agree, "counts": counts, "spike_check": spike_check, "level_check": level_check,
        "verdict_order": VERDICT_ORDER, "cause_order": CAUSE_ORDER, "no_better_model": NO_BETTER_MODEL,
        "thresholds": CAUSE_THRESHOLDS,
        # The two gates are the README's measured figures, quoted, never recomputed.
        # The two medians ARE computed here, over the CSV rows that carry the column,
        # and the sentence that uses one says so.
        "gate_cv": 0.4365, "gate_units": 812.5,
        "median_cv": _median([num(r["cause_cv_last12"]) for r in rows.values()]),
        "median_cv_n": sum(1 for r in rows.values() if num(r["cause_cv_last12"]) is not None),
        "median_units": _median([num(r["cause_median_units"]) for r in rows.values()]),
        "median_units_n": sum(1 for r in rows.values() if num(r["cause_median_units"]) is not None),
        "cause_note": ("Cause group is the CSV's own cause_group column; every threshold is recorded in "
                       "reports/diagnostics/README.md. The rules are NOT exclusive - cause_group is the "
                       "first match, and a SKU's other fired rules are listed on its own page. "
                       "'none of the above' means no rule fired, which is a result, not a gap. "
                       "A CAUSE IS NOT A VERDICT: the same causes fire on clean SKUs too, and every "
                       "cause below carries its clean count next to its not-fit count."),
    }


# --------------------------------------------------------------------------- #
# Preview mode: "with 2021-22 placeholder" (what-if, never evidence)
# --------------------------------------------------------------------------- #
PREVIEW_FILES = ("router_preview_synth.csv", "series_synth.csv", "preview_summary.csv")
# scripts/preview_router_synth.py's output. Override with --preview-src or
# DSD_PREVIEW_SRC; the files are copied into data/ at build time.
DEFAULT_PREVIEW_SRC = os.environ.get("DSD_PREVIEW_SRC", os.path.join(REPO, "reports", "preview"))
DATA_DIR = os.path.join(HERE, "data")
# Every live build writes the assembled DB payload here so the page can be
# rebuilt when the database is unreachable (--offline). It is a snapshot of one
# read, not a substitute for one: the page banner and stdout both name its
# timestamp, and preview mode still reads reports/preview/ either way.
SNAPSHOT = os.path.join(DATA_DIR, "db_snapshot.json")
PREVIEW_START = "2021-01"
PREVIEW_METHOD = {"trailing_average": "provisional"}


def copy_preview_inputs(src: str) -> None:
    import shutil
    missing = [f for f in PREVIEW_FILES if not os.path.isfile(os.path.join(src, f))]
    if missing:
        sys.exit(f"BUILD FAILED: preview input(s) missing from {src}: {', '.join(missing)}. "
                 f"Run scripts/preview_router_synth.py or pass --preview-src.")
    os.makedirs(DATA_DIR, exist_ok=True)
    for f in PREVIEW_FILES:
        shutil.copyfile(os.path.join(src, f), os.path.join(DATA_DIR, f))


BACKUP_OPTIONS = os.path.join(REPO, "analytics", "forecasting", "backup_options.json")


def load_backup_options():
    """analytics/forecasting/backup_options.json - DEC-28's machine-readable copy.

    Hard-fails if the file is missing or if a router bin has no entry. A viewer
    that quietly printed "pending decision" over a decision that HAS been made
    would misreport the record, so the build stops instead. Nothing is computed
    or defaulted here: the served model, the ordered backup list and the long
    bin's watch list are carried through exactly as the file gives them."""
    if not os.path.isfile(BACKUP_OPTIONS):
        raise SystemExit(f"backup options missing: {BACKUP_OPTIONS}" + chr(10) +
                         f"DEC-28 (ARCHITECTURE.md) is the source; this build will not produce a page "
                         f"that shows the Backup options column as undecided.")
    with open(BACKUP_OPTIONS, encoding="utf-8") as fh:
        bo = json.load(fh)
    missing = [b for b in ROUTER_ORDER if b not in bo.get("bins", {})]
    if missing:
        raise SystemExit(f"BUILD FAILED: {BACKUP_OPTIONS} has no entry for router bin(s) {missing}")
    bo["file"] = os.path.relpath(BACKUP_OPTIONS, REPO).replace("\\", "/")
    return bo


def assemble_preview(skus: list[dict]) -> dict:
    """Per-SKU preview overrides, read as given from the copied files: bins, served
    forecast, served MASE / WAPE, and MA3's MASE / WAPE on the same holdout
    (ma3_holdout_mase / ma3_holdout_wape) all come from router_preview_synth.csv.
    Nothing is refitted or rescaled here. The only derived value is WHICH months
    are the holdout, for the chart shading: train_holdout_split on the file's own
    series, zero-filled first -> last row as the preview script does."""
    import numpy as np
    import pandas as pd
    from analytics.forecasting.sarima import HOLDOUT_FRACTION, train_holdout_split

    rp = pd.read_csv(os.path.join(DATA_DIR, "router_preview_synth.csv"))
    need = {"ma3_holdout_mase", "ma3_holdout_wape", "holdout_mase", "holdout_wape"}
    if need - set(rp.columns):
        sys.exit(f"BUILD FAILED: router_preview_synth.csv lacks {sorted(need - set(rp.columns))}")
    rp["backup_fired"] = rp["backup_fired"].astype(str).str.lower().eq("true")
    raw = pd.read_csv(os.path.join(DATA_DIR, "series_synth.csv"), dtype={"month": str})
    raw["is_placeholder"] = raw["is_placeholder"].astype(str).str.lower().eq("true")
    summary = pd.read_csv(os.path.join(DATA_DIR, "preview_summary.csv"))

    periods = months(PREVIEW_START, ABC_PERIOD)
    pidx = {p: i for i, p in enumerate(periods)}
    real = {s["pk"]: s for s in skus}
    if set(rp["product_key"]) != set(real):
        sys.exit("BUILD FAILED: router_preview_synth.csv product keys differ from the live Tier A cohort")

    def f(v, nd=4):
        return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), nd)

    out, checks = {}, {"ma3_equal": 0, "ma3_total": 0, "holdout_in_placeholder": 0}
    for r in rp.itertuples(index=False):
        pk = int(r.product_key)
        g = raw[raw["product_key"] == pk]
        monthly = [None] * len(periods)
        ph = [False] * len(periods)
        for m, q, isph in zip(g["month"], g["quantity"], g["is_placeholder"]):
            monthly[pidx[m]] = None if pd.isna(q) else round(float(q), 1)
            ph[pidx[m]] = bool(isph)
        # a real month whose quantity is NULL in the _Real view: the file carries the
        # pipeline's 0; the page marks it the same way in both modes
        off = len(periods) - len(real[pk]["monthly"])
        null_months = [i + off for i in real[pk]["null_months"]]
        for i in null_months:
            monthly[i] = None
        present = [i for i, v in enumerate(monthly) if v is not None or i in null_months]
        ph_idx = [i for i, x in enumerate(ph) if x]
        method = PREVIEW_METHOD.get(r.served_model, r.served_model)
        rec = {
            "monthly": monthly, "null_months": null_months, "ph": [ph_idx[0], ph_idx[-1]] if ph_idx else None,
            "ph_count": len(ph_idx),
            "first_i": present[0] if present else None, "last_i": present[-1] if present else None,
            "gap_months": sum(1 for i in range(present[0], present[-1] + 1)
                              if monthly[i] is None and i not in null_months) if present else 0,
            "neg_months": sum(1 for v in monthly if v is not None and v < 0),
            "view_rows": int(len(g)), "router_bin": r.bin, "real_bin": real[pk]["router_bin"], "method": method,
            "status": r.status, "served": f(r.forecast, 3), "ma3": f(r.ma3_forecast, 3), "lo": None, "hi": None,
            "components": None, "backup_reason": None, "provisional": r.status == "insufficient_data",
            "backup": ("fired" if r.backup_fired else "not fired") if method in CHALLENGERS else "not applicable",
            "mase": f(r.holdout_mase), "wape": f(r.holdout_wape),
            "ma3_mase": f(r.ma3_holdout_mase), "ma3_wape": f(r.ma3_holdout_wape),
            "holdout": None, "holdout_months": None,
        }
        zf = [0.0 if (monthly[i] is None) else monthly[i] for i in range(rec["first_i"], rec["last_i"] + 1)] if present else []
        rec["sales_months"] = sum(1 for v in zf if v > 0)
        rec["rlr"] = f(recent_level_ratio(zf), 3)
        rs = real[pk]["served"]
        rec["change"] = None if rec["served"] is None or not rs else round((rec["served"] - rs) / rs, 4)
        rec["gap"] = None if rec["served"] is None or not rec["ma3"] else round((rec["served"] - rec["ma3"]) / rec["ma3"], 4)
        if r.status == "ok" and present:
            series = pd.Series(zf, index=pd.to_datetime([periods[i] + "-01" for i in range(rec["first_i"], rec["last_i"] + 1)]))
            _, holdout = train_holdout_split(series, holdout_fraction=HOLDOUT_FRACTION)
            h0 = pidx[holdout.index[0].strftime("%Y-%m")]
            rec["holdout"], rec["holdout_months"] = [h0, h0 + len(holdout) - 1], int(len(holdout))
            if any(ph[i] for i in range(h0, h0 + len(holdout))):
                checks["holdout_in_placeholder"] += 1
            if method == "ma3":      # file consistency: MA3 served => served MASE == MA3 MASE
                checks["ma3_total"] += 1
                checks["ma3_equal"] += int(rec["ma3_mase"] is not None and rec["mase"] is not None
                                           and abs(rec["ma3_mase"] - rec["mase"]) < 1e-9)
        out[pk] = rec
    if checks["holdout_in_placeholder"]:
        sys.exit(f"BUILD FAILED: {checks['holdout_in_placeholder']} SKUs have a placeholder month in the preview holdout")

    def vc(col, mapping=None):
        s = rp[col].map(mapping).fillna(rp[col]) if mapping else rp[col]
        return {str(k): int(v) for k, v in s.value_counts().items()}
    served_m = rp["served_model"].map(PREVIEW_METHOD).fillna(rp["served_model"])
    backup_exp = {"not fired": int(((served_m.isin(CHALLENGERS)) & ~rp["backup_fired"]).sum()),
                  "not applicable": int((~served_m.isin(CHALLENGERS)).sum()),
                  "fired": int(((served_m.isin(CHALLENGERS)) & rp["backup_fired"]).sum())}
    blocks = summary[summary["table"] == "testable_blocks"]
    moves = summary[summary["table"] == "test_month_bin_moves"]
    return {
        "periods": periods, "skus": {str(k): v for k, v in out.items()},
        "expected": {"tier_a": int(len(rp)), "combined": EXPECTED["combined"], "router": vc("bin"),
                     "model": vc("served_model", PREVIEW_METHOD), "backup": backup_exp, "forecast_result": int(len(rp))},
        "file_rows": int(len(raw)), "placeholder_rows": int(raw["is_placeholder"].sum()),
        "placeholder_skus": int(raw.loc[raw["is_placeholder"], "product_key"].nunique()),
        "blocks": [{"arm": a, "bin": b, "value": int(v)} for a, b, v in zip(blocks["arm"], blocks["bin"], blocks["value"])],
        "moves": [{"real": a, "synth": b, "n": int(v)} for a, b, v in zip(moves["real_bin"], moves["synth_bin"], moves["value"])],
        "checks": checks,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preview-src", default=DEFAULT_PREVIEW_SRC,
                    help="folder holding the preview CSVs (default: $DSD_PREVIEW_SRC or the preview session's scratchpad)")
    ap.add_argument("--offline", action="store_true",
                    help=f"rebuild from the last live read ({SNAPSHOT}) instead of querying the database")
    args = ap.parse_args()
    t0 = time.perf_counter()
    copy_preview_inputs(args.preview_src)          # fails loudly before any DB work
    if args.offline:
        if not os.path.isfile(SNAPSHOT):
            raise SystemExit(f"--offline needs {SNAPSHOT}, written by a live build. Not present.")
        with open(SNAPSHOT, encoding="utf-8") as fh:
            payload = json.load(fh)
        timing, dsn, t_db = {}, f"snapshot {os.path.basename(SNAPSHOT)}", 0.0
        print(f"--offline: rebuilding from {SNAPSHOT} (read {payload['meta']['generated']}); no DB query")
    else:
        raw, timing, dsn = fetch()
        t_db = time.perf_counter() - t0
        payload = assemble(raw)
        with open(SNAPSHOT, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"), allow_nan=False, default=str)
    payload["meta"]["source"] = dsn
    payload["meta"]["offline"] = bool(args.offline)
    t_band = time.perf_counter()
    payload["band"] = add_band_evidence(payload)
    t_band = time.perf_counter() - t_band
    payload["fit"] = load_fit_review(payload)
    payload["etl"] = ETL_NODES
    payload["preview"] = assemble_preview(payload["skus"])
    payload["backup_options"] = load_backup_options()
    data = json.dumps(payload, separators=(",", ":"), allow_nan=False, default=str).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data)
    out = os.path.join(HERE, "dsd_dev_viewer.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    c, m = payload["counts"], payload["meta"]
    print(f"cohort={m['n']} forecast_rows={sum(1 for s in payload['skus'] if s['status'])} "
          f"forecast_date={m['forecast_date']} view_rows={m['view_rows']} view_skus={m['view_skus']} "
          f"abc_classified={m['abc_classified']}")
    print(f"combined_v1={c['combined']}")
    print(f"router={c['router']} model={c['model']} backup={c['backup']}")
    short = [s for s in payload["skus"] if s["method"] == "ma3"]
    same = sum(1 for s in short if s["mase"] is not None and s["ma3_mase"] is not None and abs(s["ma3_mase"] - s["mase"]) <= 0.00051)
    print(f"MA3-served SKUs whose recomputed MA3 MASE equals the stored served MASE (3 dp, as stored): {same} of {len(short)}")
    b, ag = payload["band"], payload["band"]["agree"]
    print(f"band = forecast +/- {CONFIDENCE_Z} * served holdout RMSE, lower floored at 0; "
          f"level {BAND_LEVEL_LABEL}")
    print(f"corridor recomputed for {ag['n']} scored SKUs; agrees with what was stored - "
          f"mase {ag['mase']}/{ag['n']}, wape {ag['wape']}/{ag['n']}, rmse {ag['rmse']}/{ag['n']}, "
          f"holdout months {ag['months']}/{ag['n']}"
          + (f" (rmse inverted from the stored band for {b['derived_rmse']} SKUs: the snapshot predates "
             f"model_params rmse being carried)" if b["derived_rmse"] else ""))
    a = b["all"]
    print(f"coverage (served): median {a['cov']}, {a['below']} of {a['scored']} below {BAND_LEVEL_LABEL}, "
          f"median band width / forecast {a['bw']}; holdout months {b['holdout_months']}")
    print(f"coverage (MA3, computed - no MA3 band is stored): median {a['cov3']}, "
          f"{a['below3']} of {a['scored']} below {BAND_LEVEL_LABEL}, median width / forecast {a['bw3']}")
    for meth, blk in b["by_model"].items():
        print(f"  {meth}: n={blk['n']} median coverage={blk['cov']} below={blk['below']} "
              f"median width/forecast={blk['bw']} | MA3 median coverage={blk['cov3']} below={blk['below3']}")
    f = payload["fit"]
    print(f"fit review: {f['file']} \u2014 {f['rows']} rows, "
          f"missing from CSV {len(f['missing'])}, not in cohort {len(f['extra'])}; "
          f"agrees with the DB read: mase_pipeline {f['agree']['mase']}/{f['agree']['n']}, "
          f"band width/forecast {f['agree']['bw']}/{f['agree']['n']}")
    sc = f["spike_check"]
    print(f"  spike months re-identified from cause_median_units +/- 3 x cause_mad match cause_n_spikes: "
          f"{sc['ok']}/{sc['n']}" + (f" MISMATCH {sc['bad']}" if sc["bad"] else ""))
    lc = f["level_check"]
    print(f"  level shift re-derived as mean(last 6) / mean(prior 12) matches cause_level_shift: "
          f"{lc['ok']}/{lc['n']}" + (f" MISMATCH {lc['bad']} (window withheld)" if lc["bad"] else ""))
    print(f"  verdict={f['counts']['verdict']}")
    print(f"  cause={f['counts']['cause']}")
    for cs in f["cause_order"]:
        cv = f["counts"]["cause_verdict"].get(cs)
        if cv:
            print(f"    {cs}: " + ", ".join(f"{k} {v}" for k, v in cv.items()))
    for bn in ("short", "medium", "long", "insufficient"):
        if bn in f["counts"]["by_bin"]:
            print(f"  {bn}: {f['counts']['by_bin'][bn]}")
    pv = payload["preview"]
    pvc = {}
    for s in pv["skus"].values():
        pvc[s["router_bin"]] = pvc.get(s["router_bin"], 0) + 1
    print(f"preview: bins={pvc} placeholder_skus={pv['placeholder_skus']} placeholder_rows={pv['placeholder_rows']} "
          f"file check, MA3-served SKUs with served MASE == ma3_holdout_mase: {pv['checks']['ma3_equal']} of {pv['checks']['ma3_total']} "
          f"backup_options={payload['backup_options']['file']} "
          f"({', '.join(b + ' ' + str(len(payload['backup_options']['bins'][b]['backups'])) for b in ROUTER_ORDER)} backups)")
    print(f"problems={m['problems'] or 'none'}")
    print(f"source={dsn}  query seconds={timing}  db total={t_db:.2f}s  band evidence={t_band:.2f}s  "
          f"build total={time.perf_counter() - t0:.2f}s  html={os.path.getsize(out) / 1024:.0f} KB")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DSD Dev Viewer</title>
<style>
:root{
  color-scheme:dark;
  --bg:#0f1117;--surface-1:#161a24;--surface-2:#1d2230;--surface-3:#252b3b;
  --ink:#eef0f6;--ink-2:#b9bfd0;--ink-3:#7d8499;--line:rgba(255,255,255,.07);--line-2:rgba(255,255,255,.14);
  --accent:#6ea8fe;
  --actual:#c3c2b7;
  --m-ma3:#199e70;--m-tsb:#9085e9;--m-xgb:#d95926;--m-prov:#8a8f9e;
  --ok:#2fb36d;--warn:#e0a526;--bad:#e5484d;--none:#5b6173;
  --flag-bg:rgba(224,165,38,.14);--flag-ink:#f1c35c;
  --ui:"Segoe UI",-apple-system,"Helvetica Neue",Arial,sans-serif;
  --mono:"Cascadia Mono","Cascadia Code",Consolas,"Courier New",monospace;
  --r:10px;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 var(--ui)}
button,input,select{font:inherit;color:inherit}

header{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:20px;padding:0 24px;height:56px;
  background:rgba(15,17,23,.94);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:baseline;gap:10px;white-space:nowrap}
.brand b{font-size:15px}
.brand span{color:var(--ink-3);font-size:12px}
nav{display:flex;gap:4px;margin-left:8px;height:100%}
nav button{background:none;border:0;padding:0 14px;color:var(--ink-3);cursor:pointer;border-bottom:2px solid transparent;font-weight:600}
nav button:hover{color:var(--ink-2)}
nav button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)}
.meta{margin-left:auto;color:var(--ink-3);font-size:12px;text-align:right;line-height:1.35}

.wrap{padding:18px 24px 32px;max-width:1800px;margin:0 auto}
.note{display:flex;gap:10px;align-items:flex-start;padding:10px 14px;border-radius:var(--r);background:var(--surface-1);
  border:1px solid var(--line);color:var(--ink-2);font-size:12px;margin-bottom:14px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600;
  background:var(--surface-3);color:var(--ink-2);white-space:nowrap}
.pill i{width:8px;height:8px;border-radius:50%;display:inline-block}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.kpi{background:var(--surface-1);border:1px solid var(--line);border-radius:var(--r);padding:12px 14px}
.kpi .v{font:600 24px/1.1 var(--ui);font-variant-numeric:tabular-nums}
.kpi .l{color:var(--ink-3);font-size:12px;margin-top:4px}
.card{background:var(--surface-1);border:1px solid var(--line);border-radius:var(--r);padding:16px;min-width:0}
.card h2{margin:0 0 2px;font-size:14px;font-weight:600}
.card .sub{color:var(--ink-3);font-size:12px;margin-bottom:12px}
.two{display:grid;grid-template-columns:minmax(0,1fr) 440px;gap:14px;align-items:start}
.stack{display:grid;gap:14px;min-width:0}
.sticky{position:sticky;top:70px;max-height:calc(100vh - 86px);overflow:auto}

/* flow (routing) */
.flowSvg svg{width:100%;height:auto;display:block}
.colh{fill:var(--ink-3);font-size:11px;font-weight:600;letter-spacing:.04em}
.node{cursor:pointer}
.node rect.box{fill:var(--surface-2);stroke:var(--line-2)}
.node:hover rect.box{fill:var(--surface-3)}
.node.sel rect.box{stroke:var(--accent);stroke-width:2}
.node.empty rect.box{fill:none;stroke-dasharray:4 3}
.node text{fill:var(--ink);font-size:12px;pointer-events:none}
.node text.n{fill:var(--ink-2);font-family:var(--mono)}
.node text.s{fill:var(--ink-3);font-size:11px}
.link{fill:none;stroke-opacity:.32;transition:stroke-opacity .12s}
.link.hi{stroke-opacity:.65}
.filtered .link:not(.hi){stroke-opacity:.12}

/* controls */
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.search{background:var(--surface-2);border:1px solid var(--line-2);border-radius:8px;padding:6px 10px;width:260px;outline:none}
.search:focus{border-color:var(--accent)}
.btn{background:var(--surface-2);border:1px solid var(--line-2);border-radius:8px;padding:6px 12px;cursor:pointer}
.btn:hover{background:var(--surface-3)}
.btn:disabled{opacity:.4;cursor:default}
.seg{display:inline-flex;background:var(--surface-2);border:1px solid var(--line-2);border-radius:8px;padding:2px;flex-wrap:wrap}
#causeSeg{flex-wrap:nowrap;overflow-x:auto;max-width:100%;scrollbar-width:thin}
#causeSeg button{white-space:nowrap}
.seg button{background:none;border:0;padding:4px 10px;border-radius:6px;cursor:pointer;color:var(--ink-2);display:inline-flex;align-items:center;gap:6px}
.seg button[aria-pressed="true"]{background:var(--surface-3);color:var(--ink)}
.seg i{width:8px;height:8px;border-radius:50%}
.count{color:var(--ink-3);font-size:12px;margin-left:auto}
.ac{position:relative}
.ac .search{width:340px}
.ac ul{position:absolute;top:100%;left:0;right:0;margin:4px 0 0;padding:4px;list-style:none;background:#0b0d13;border:1px solid var(--line-2);
  border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.5);z-index:40;max-height:320px;overflow:auto}
.ac li{padding:6px 8px;border-radius:6px;cursor:pointer;display:flex;gap:10px;align-items:baseline}
.ac li b{font-family:var(--mono);font-weight:600}
.ac li span{color:var(--ink-3);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ac li[aria-selected="true"],.ac li:hover{background:var(--surface-3)}

/* tables */
.tw{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}
td{white-space:nowrap}
th{position:sticky;top:0;background:var(--surface-2);color:var(--ink-3);font-weight:600;cursor:pointer;user-select:none;z-index:1;
  white-space:normal;vertical-align:bottom;line-height:1.25;min-width:56px}
th.num,td.num{text-align:right}
td.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--surface-2)}
tbody tr.sel{background:rgba(110,168,254,.10);box-shadow:inset 3px 0 0 var(--accent)}
td.name{max-width:220px;overflow:hidden;text-overflow:ellipsis}
td.flag{background:var(--flag-bg);color:var(--flag-ink);font-weight:600}
.muted{color:var(--ink-3)}
.ph{color:var(--ink-3);font-style:italic}

/* detail / focus */
.dhead{display:flex;flex-direction:column;gap:6px;margin-bottom:10px}
.dhead .code{font:600 18px/1.2 var(--mono)}
.dhead .nm{color:var(--ink-2)}
.tags{display:flex;gap:6px;flex-wrap:wrap}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px;margin:12px 0}
.stat{background:var(--surface-2);border-radius:8px;padding:8px 10px;min-width:0}
.stat .v{font:600 15px/1.2 var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat .l{color:var(--ink-3);font-size:11px;margin-top:2px}
.stat.flag{background:var(--flag-bg)}
.stat.flag .v{color:var(--flag-ink)}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--ink-2);font-size:11px;margin-top:6px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw-line{width:14px;height:2px;border-radius:1px;display:inline-block}
.sw-dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.sw-ring{width:9px;height:9px;border-radius:50%;display:inline-block;border:2px solid}
.sw-hollow{width:8px;height:8px;border-radius:50%;display:inline-block;border:1.5px solid var(--ink-3)}
.sw-band{width:9px;height:12px;border-radius:2px;display:inline-block;opacity:.3}
.sw-hold{width:12px;height:12px;border-radius:2px;display:inline-block;background:var(--accent);opacity:.18}
details{border-top:1px solid var(--line);padding:8px 0}
summary{cursor:pointer;color:var(--ink-2);font-weight:600;font-size:12px;padding:2px 0}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:8px 0 0;font-size:12px}
dl.kv dt{color:var(--ink-3)}
dl.kv dd{margin:0;font-family:var(--mono);word-break:break-word}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.xh{stroke:var(--ink-3);stroke-width:1;stroke-dasharray:3 3;pointer-events:none}
.focus{display:grid;grid-template-columns:minmax(0,1fr) 220px;gap:14px}
.focusnav{display:flex;align-items:center;gap:8px;margin-left:auto}
.backupbox{border:1px dashed var(--line-2);border-radius:8px;padding:12px;color:var(--ink-3);font-size:12px;align-self:start}
.backupbox b{display:block;color:var(--ink-2);margin-bottom:4px}
.spark svg{display:block}

/* grid view */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.fc{background:var(--surface-1);border:1px solid var(--line);border-radius:var(--r);padding:12px 12px 10px;cursor:pointer}
.fc:hover{border-color:var(--line-2)}
.fc.sel{border-color:var(--accent)}
.fc .top{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.fc .code{font:600 13px var(--mono)}
.fc .nm{color:var(--ink-3);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px}
.fc .foot{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:6px}
.fc .foot div{font-size:11px;color:var(--ink-3)}
.fc .foot b{display:block;font:600 12px var(--mono);color:var(--ink)}
.empty{padding:40px;text-align:center;color:var(--ink-3)}

/* pipeline */
.canvas{background:
  radial-gradient(circle, rgba(255,255,255,.05) 1px, transparent 1px) 0 0/18px 18px, var(--surface-1)}
.canvas svg{width:100%;height:auto;display:block}
.kn{cursor:pointer}
.kn .body{fill:var(--surface-2);stroke:var(--line-2);stroke-width:1}
.kn:hover .body{fill:var(--surface-3)}
.kn.sel .body{stroke:var(--accent);stroke-width:2}
.kn.path .body{stroke:var(--accent);stroke-width:2.5}
.kn.dim{opacity:.35}
.kn text{fill:var(--ink);font-size:12px;pointer-events:none}
.kn text.t{font-weight:600}
.kn text.io{fill:var(--ink-3);font-family:var(--mono);font-size:11px}
.kn text.st{fill:var(--ink-3);font-size:10.5px}
.wire{fill:none;stroke:var(--ink-3);stroke-width:1.5;opacity:.6}
.wire.path{stroke:var(--accent);opacity:1;stroke-width:2.5}
/* database boundary: the frame around what lives in Supabase, and the lane outside it */
.dbframe{fill:rgba(110,168,254,.05);stroke:var(--accent);stroke-width:1.5;stroke-dasharray:7 4}
.dbframe-l{fill:var(--accent);font-size:10.5px;font-weight:700;letter-spacing:.09em;opacity:.95}
.lane-l{fill:var(--ink-3);font-size:10.5px;font-weight:600;letter-spacing:.09em}
.xing circle{fill:var(--bg);stroke:var(--accent);stroke-width:1.6}
.xing text{fill:var(--accent);font-size:10px;font-weight:700;text-anchor:middle}
.xing text.w{fill:var(--ink-2);font-size:9.5px;font-weight:600;letter-spacing:.05em}
.wire.cross{stroke:var(--accent);opacity:.85;stroke-width:2}
.wire.wrap{stroke:var(--accent);opacity:.5;stroke-dasharray:6 4}
.kn text.tag{fill:var(--ink-3);font-size:9.5px;letter-spacing:.05em}
.srcline{font-size:11px;color:var(--ink-3);margin:-4px 0 8px}
.srcline b{color:var(--ink-2);font-weight:600}
/* band corridor */
.corr{stroke:none}
.outmark{stroke:var(--bad);fill:none;stroke-width:1.8}
.sw-corr{width:14px;height:10px;border-radius:2px;display:inline-block;opacity:.3}
.sw-out{width:10px;height:10px;border-radius:50%;display:inline-block;border:2px solid var(--bad)}
.sw-clip{width:14px;height:0;border-top:2px dotted var(--ink-2);display:inline-block}
.clipnote{fill:var(--ink-2);font-size:10px}
.bandregion{fill:var(--ink-3);font-size:10px;letter-spacing:.02em}
.widenote{border-left:3px solid var(--bad);background:rgba(229,72,77,.09);color:#f1a3a6;padding:8px 12px;
  border-radius:0 8px 8px 0;font-size:12px;margin:8px 0}
.unfitnote{border-left:3px solid var(--flag-ink);background:var(--flag-bg);color:var(--flag-ink);padding:8px 12px;
  border-radius:0 8px 8px 0;font-size:12px;margin:8px 0}
.unfitnote b{color:#ffd98a}
.v-clean{color:var(--ok)} .v-borderline{color:var(--warn)} .v-notfit{color:var(--bad);font-weight:600}
.explain{background:var(--surface-2);border:1px solid var(--line);border-radius:var(--r);padding:12px 14px;margin:10px 0}
.explain h4{margin:0 0 6px;font-size:12px;font-weight:600;color:var(--ink-2);letter-spacing:.02em}
.explain h4+h4{margin-top:12px}
.explain ul{margin:0;padding-left:18px;font-size:12.5px;line-height:1.65;color:var(--ink)}
.explain li{margin:0}
.explain s-[title]{}
.explain span[title]{border-bottom:1px dotted var(--line-2);cursor:help}
.explain .cl{color:var(--ink-2)}
.ret{color:var(--flag-ink);font-style:italic}
.verdictline{display:flex;gap:10px;align-items:flex-start;padding:11px 14px;border-radius:var(--r);margin:10px 0;
  font-size:13.5px;line-height:1.55;border:1px solid var(--line)}
.verdictline.notfit{background:rgba(229,72,77,.10);border-color:rgba(229,72,77,.35)}
.verdictline.borderline{background:var(--flag-bg);border-color:rgba(224,165,38,.35)}
.verdictline.clean{background:rgba(47,179,109,.08);border-color:rgba(47,179,109,.3)}
.verdictline b{white-space:nowrap}
details.sec{border:1px solid var(--line);border-radius:var(--r);padding:0;margin:8px 0;background:var(--surface-1)}
/* display:flex on a <summary> stops the engine treating it as the disclosure
   summary: the closed content keeps rendering. Measured in headless Edge
   2026-09-23 - every collapsed section was still fully visible. Keep summary at
   its default display, and hide the bodies explicitly as well. */
details.sec>summary{padding:9px 14px;font-weight:600;font-size:12.5px;color:var(--ink-2);list-style:none}
details.sec:not([open])>.secbody{display:none}
details.legendbox:not([open])>.legend{display:none}
details.sec>summary::before{content:"\25b8";color:var(--ink-3);transition:transform .12s}
details.sec[open]>summary::before{transform:rotate(90deg)}
details.sec>summary:hover{color:var(--ink)}
details.sec .secbody{padding:2px 14px 12px}
details.sec .explain{background:none;border:0;padding:0;margin:0}
details.legendbox{border:0;padding:0;margin:2px 0}
details.legendbox>summary{color:var(--ink-3);font-size:11.5px;font-weight:600;padding:2px 0}
.stats.four{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));max-width:760px}
.banddef dl.kv dt{min-width:118px}
.lightbox{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--ink-2)}
.lightbox span{display:inline-flex;gap:6px;align-items:center}
.lamp{width:10px;height:10px;border-radius:50%;display:inline-block}
.pnode{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.pnode h3{margin:0;font-size:14px}
.checks{font-size:12px;color:var(--ink-2);margin:0 0 10px;padding-left:18px}

#tip{position:fixed;z-index:50;pointer-events:none;background:#0b0d13;border:1px solid var(--line-2);border-radius:8px;
  padding:7px 10px;font-size:12px;box-shadow:0 8px 24px rgba(0,0,0,.45);display:none;min-width:140px}
#tip .h{color:var(--ink-3);font-size:11px;margin-bottom:3px}
#tip .r{display:flex;justify-content:space-between;gap:14px}
#tip .r b{font-family:var(--mono);font-weight:600}
[hidden]{display:none!important}
@media (max-width:1200px){.two{grid-template-columns:1fr}.sticky{position:static;max-height:none}.focus{grid-template-columns:1fr}}
/* preview mode */
:root{--ph:#c9a227}
.pvbanner{position:sticky;top:56px;z-index:25;display:flex;gap:10px;align-items:center;padding:9px 24px;
  background:repeating-linear-gradient(135deg,#3a2f0c 0 10px,#2e260b 10px 20px);border-bottom:1px solid #6b5716;color:#f3dd8a;font-size:12.5px}
.pvbanner b{color:#ffe9a3;letter-spacing:.03em}
.modeSeg button[data-v="preview"][aria-pressed="true"]{background:#5a4a14;color:#ffe9a3}
.sw-null{width:8px;height:8px;display:inline-block;border:1.5px solid var(--warn)}
.sw-ph{width:14px;height:0;border-top:2px dashed var(--ph);display:inline-block}
.sw-phbg{width:12px;height:12px;border-radius:2px;display:inline-block;background:repeating-linear-gradient(135deg,rgba(201,162,39,.35) 0 3px,transparent 3px 6px)}
.pvnote{border-left:3px solid var(--ph);background:rgba(201,162,39,.08);color:#e8d48f;padding:8px 12px;border-radius:0 8px 8px 0;font-size:12px;margin:8px 0}
.mini{border-collapse:collapse;font-size:12px;margin:6px 0 10px}
.mini th,.mini td{padding:4px 10px;border:1px solid var(--line);text-align:right;position:static;background:none;cursor:default}
.mini th{color:var(--ink-3);font-weight:600}
.mini td.l,.mini th.l{text-align:left}
.pvgrid{display:grid;grid-template-columns:auto auto 1fr;gap:18px;align-items:start}
@media (max-width:1200px){.pvgrid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <div class="brand"><b>DSD Dev Viewer</b><span>Unilever · Tier A</span></div>
  <nav role="tablist">
    <button role="tab" data-tab="forecasts" aria-selected="true">Forecasts</button>
    <button role="tab" data-tab="pipeline" aria-selected="false">Pipeline</button>
  </nav>
  <div class="seg modeSeg" id="modeSeg" role="group" aria-label="Data mode"></div>
  <div class="meta" id="meta"></div>
</header>
<div class="pvbanner" id="pvbanner" hidden role="status"><b>PREVIEW</b><span>— 2021–22 months are placeholder data, not SSM's.
  Shows how routing changes with more history. Accuracy numbers here are not evidence: the placeholder is smoother than real sales.</span></div>
<div class="wrap">
  <div class="note"><span class="pill">Frozen snapshot</span><div id="noteText"></div></div>
  <div class="kpis" id="kpis"></div>

  <section id="tab-forecasts">
    <div class="banddef" id="bandCard" style="margin-bottom:14px"></div>
    <div class="toolbar">
      <div class="ac" id="acF"></div>
      <div class="seg" id="binSeg"></div>
      <div class="seg" id="modelSeg"></div>
      <div class="seg" id="verdictSeg" title="Fit verdict, from the fit review CSV"></div>
      <div class="seg" id="causeSeg" title="Cause group, built only from signals already on record"></div>
      <div class="seg" id="viewSeg"></div>
      <button class="btn" id="colsBtn"></button>
      <span class="count" id="gcount"></span>
    </div>
    <div class="card" id="focus" style="margin-bottom:14px"></div>
    <div class="card" id="fTableCard">
      <div class="tw" style="max-height:640px"><table id="ftbl"><thead></thead><tbody></tbody></table></div>
    </div>
    <div class="grid" id="grid" hidden></div>
  </section>

  <section id="tab-pipeline" hidden>
    <div class="card" id="pvSummary" style="margin-bottom:14px" hidden></div>
    <div class="toolbar">
      <div class="ac" id="acP"></div>
      <button class="btn" id="pclr">Clear SKU</button>
      <div class="lightbox">
        <span><i class="lamp" style="background:var(--ok)"></i>matches expected count</span>
        <span><i class="lamp" style="background:var(--warn)"></i>warnings</span>
        <span><i class="lamp" style="background:var(--bad)"></i>count mismatch</span>
        <span><i class="lamp" style="background:var(--none)"></i>no expected count on record</span>
        <span style="margin-left:6px"><i class="lamp" style="background:none;border:1.5px dashed var(--accent);border-radius:2px"></i>inside Supabase</span>
        <span><i class="lamp" style="background:var(--ink-3);border-radius:2px"></i>ETL / API node &mdash; every number from a file under reports/</span>
      </div>
    </div>
    <div class="two" id="pgrid">
      <div class="stack">
        <div class="card canvas"><div id="pSvg"></div></div>
        <div class="card" id="pPanel"></div>
      </div>
      <aside class="card sticky" id="pDock" hidden></aside>
    </div>
  </section>
</div>
<div id="tip"></div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = (v, d=3) => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits:d});
const pct = v => v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
const COLOR = {ma3:'var(--m-ma3)', tsb:'var(--m-tsb)', xgb_ma3_avg:'var(--m-xgb)', provisional:'var(--m-prov)'};
const mlabel = m => (D.model_label[m] || [m])[0];
const mnote = m => (D.model_label[m] || [,''])[1];
const PROV = s => s.status === 'insufficient_data';
const NT = 'not testable (<3 months)';
const modelPill = m => `<span class="pill"><i style="background:${COLOR[m]}"></i>${esc(mlabel(m))}</span>`;
const fcMonth = D.meta.forecast_date ? D.meta.forecast_date.slice(0, 7) : 'next';
const B = D.band;
const pctv = (v, d=1) => v == null ? '\u2014' : (v * 100).toFixed(d) + '%';
const LVL = B.level_nominal, LVLL = B.level_label;
const hpoint = (s, i) => s.hpath ? s.hpath.find(p => p.i === i) : null;
const F = D.fit;
const VCLASS = {'clean':'v-clean', 'borderline':'v-borderline', 'not fit':'v-notfit'};
const vcell = v => `<span class="${VCLASS[v] || 'muted'}">${esc(v || '\u2014')}</span>`;
// A cause is not a verdict: the same rules fire on clean SKUs. Every place a
// cause appears shows its clean count beside its not-fit count.
const causeSplit = (rows, c) => ({
  unfit: rows.filter(s => s.cause === c && s.verdict === 'not fit').length,
  clean: rows.filter(s => s.cause === c && s.verdict === 'clean').length,
  n: rows.filter(s => s.cause === c).length,
});
const causeTag = (rows, c) => { const k = causeSplit(rows, c); return `${c} ${k.unfit} not fit / ${k.clean} clean`; };
const WIDE_BAND = 2;
// ---------------------------------------------------------------------------
// Plain-language explanation. FIXED sentence templates with stored numbers
// dropped in - no sentence is composed at run time, and every one carries the
// field it came from in its tooltip. Sources are the fit review CSV
// (reports/diagnostics/fit_review_common_2026-09-23.csv), its README's two
// measured gates, and the page's own stored band / recomputed holdout path.
// ---------------------------------------------------------------------------
const CSVSRC = 'fit_review_common_2026-09-23.csv';
// A negative actual is a returns-dominated month, not demand
// (analytics/forecasting/diagnostic_metrics.py:7-11: negatives are excluded
// from MAPE, kept in WAPE/sMAPE). Labelling only - no stored value changes.
const RETURNS = 'returns exceeded sales that month; not a demand reading';
const RETSRC = 'analytics/forecasting/diagnostic_metrics.py:7-11 \u2014 a negative actual is returns-dominated';
const retTag = v => v != null && v < 0 ? ` <span class="ret" title="${esc(RETSRC)}">(${RETURNS})</span>` : '';
const said = {mad: false};
const sent = (src, txt) => `<span title="${esc(src)}">${txt}</span>`;
const u = (v, d=0) => fmt(v, d);
const LVLSRC = `cause_level_shift (${CSVSRC}), re-derived on this series as mean(last 6) / mean(prior 12); the windows are the ones it was measured on`;
const SPKSRC = `cause_n_spikes, cause_mad, cause_median_units (${CSVSRC}); the months re-identified on this series`;
// Every month the banner, the series sentences, Band detail and the hover name
// comes from here: spike_months and lvl (build.py load_fit_review) and the
// recomputed holdout path, all dated on the series the chart draws. Nothing
// reads a month from the CSV.
function monthFacts(s){
  const scored = s.hpath ? s.hpath.map(p => p.m) : (s.holdout ? V.periods.slice(s.holdout[0], s.holdout[1] + 1) : []);
  const spikes = s.spike_months || null;
  return {scored, spikes, spikesScored: spikes && spikes.filter(m => scored.includes(m)),
          bandOut: s.hpath ? s.hpath.filter(p => p.out).map(p => p.m) : null,
          recentScored: s.lvl ? scored.filter(m => m >= s.lvl.recent[0] && m <= s.lvl.recent[1]) : null};
}
function seriesSentences(s){
  const out = [];
  out.push(sent(`sales_months (${CSVSRC}) \u00b7 model_params.bin`,
    `<b>${u(s.sales_months_fit != null ? s.sales_months_fit : s.sales_months)}</b> months with sales, routed to the <b>${esc(s.router_bin)}</b> bin.`));

  const rlr = s.rlr_fit != null ? s.rlr_fit : s.rlr;
  let lvl = rlr == null ? sent('recent_level_ratio (' + CSVSRC + ')', 'No recent-level ratio on record: fewer than 12 months.')
    : sent(`recent_level_ratio (${CSVSRC})`, `Recent 3 months are at <b>${(rlr * 100).toFixed(1)}%</b> of the 12-month level.`);
  if (s.cause_is_level_shift && s.lvl)
    lvl += ' ' + sent(LVLSRC,
      `The last 6 months (<b>${esc(s.lvl.recent[0])} \u2013 ${esc(s.lvl.recent[1])}</b>) average <b>${fmt(s.lvl.r, 2)}\u00d7</b> the 12 before (${esc(s.lvl.prior[0])} \u2013 ${esc(s.lvl.prior[1])}).`);
  out.push(lvl);

  const madName = said.mad ? '3 MAD' : '3 MAD (median absolute deviation)';
  said.mad = true;
  const sp = s.spike_months && s.spike_months.length, spk = s.spike_top;
  out.push(sent(`${SPKSRC}; the largest is the series month furthest from that median`,
    !s.spike_months ? 'Spike months could not be re-identified on this series.' : sp ? `<b>${u(sp)}</b> month${sp === 1 ? ' is' : 's are'} more than ${madName} from this SKU\u2019s own median of <b>${u(s.cause_median_units)}</b> units \u2014 largest deviation: <b>${u(spk && spk.v)}</b> units in <b>${esc(spk && spk.m)}</b>.`
       : `No month is more than ${madName} from this SKU\u2019s own median of <b>${u(s.cause_median_units)}</b> units.`));

  out.push(s.cause_cv == null
    ? sent(`cause_cv_last12 (${CSVSRC})`, 'No CV on record: fewer than 12 months.')
    : sent(`cause_cv_last12 (${CSVSRC}); the p75 gate ${F.gate_cv} is the README\u2019s measured figure; the cohort median is computed over the ${F.median_cv_n} rows that carry a CV`,
      `CV over the last 12 months is <b>${fmt(s.cause_cv)}</b>, against a cohort median of <b>${fmt(F.median_cv)}</b>; it <b>${s.cause_cv > F.gate_cv ? 'clears' : 'does not clear'}</b> the high-volatility gate of ${F.gate_cv}.`));

  out.push(sent(`cause_median_units (${CSVSRC}); the ${F.gate_units}-unit gate is the README\u2019s measured lower quartile; the cohort median is computed over ${F.median_units_n} rows`,
    `Median monthly units <b>${u(s.cause_median_units)}</b>, against a cohort median of <b>${u(F.median_units)}</b>; it <b>${s.cause_median_units <= F.gate_units ? 'sits in' : 'is above'}</b> the cohort\u2019s bottom quarter (gate ${F.gate_units} units).`));

  const zc = s.cause_zero_share == null ? null : Math.round(s.cause_zero_share * s.cause_n_months);
  out.push(sent(`cause_zero_missing_share \u00d7 cause_n_months, cause_longest_zero_run (${CSVSRC})`,
    zc ? `<b>${zc}</b> month${zc === 1 ? '' : 's'} are zero or missing, longest run <b>${u(s.cause_zero_run)}</b>.`
       : 'No zero or missing months.'));
  return out;
}
function outsideSentences(s){
  if (!s.hpath) return [];
  const half = s.rmse == null ? null : B.z * s.rmse;
  return s.hpath.filter(p => p.out).map(p => {
    const gap = half ? Math.abs(p.a - p.v) / half : null;
    const spike = !!(s.spike_months && s.spike_months.includes(p.m));
    const shifted = !!(s.cause_is_level_shift && s.lvl && p.m >= s.lvl.recent[0] && p.m <= s.lvl.recent[1]);
    const clause = spike ? sent(SPKSRC, 'It is a spike month.')
      : shifted ? sent(LVLSRC, 'It sits in the shifted last 6 months.')
      : sent(`${SPKSRC}; ${LVLSRC}`, 'It is neither, the miss is ordinary error.');
    return sent(`the month\u2019s actual and one-step forecast from the recomputed served holdout; the band from the stored \u03c3 (model_params.holdout_metrics_served.rmse)`,
      `<b>${esc(p.m)}</b>: actual <b>${u(p.a, 1)}</b>${retTag(p.a)} vs forecast <b>${u(p.v)}</b>; the band reaches <b>${u(p.lo)}\u2013${u(p.hi)}</b> (\u00b1${B.z} \u00d7 RMSE ${u(s.rmse)}). The gap is <b>${gap == null ? '\u2014' : fmt(gap, 2)}\u00d7</b> the band half-width.`)
      + ' <span class="cl">' + clause + '</span>';
  });
}
function honestySentences(s){
  const out = [];
  if (s.bw != null && s.bw > WIDE_BAND)
    out.push(['widenote', sent('(confidence_upper \u2212 confidence_lower) / forecast_value, as stored',
      `Band width / forecast is <b>${fmt(s.bw)}</b>: the band is wider than 2\u00d7 the forecast, so it is too wide to be informative here.`)]);
  if (s.verdict === 'not fit'){
    const bits = [sent(`verdict, cause_group (${CSVSRC})`,
      `<b>Not fit to use on this SKU.</b> Cause group: <b>${esc(s.cause)}</b>`
      + (s.cause === 'none of the above' ? ' (no cause rule fires on this SKU)' : '')
      + (s.causes_all && s.causes_all.length > 1 ? `, first match; also fired: ${esc(s.causes_all.filter(c => c !== s.cause).join(', '))}` : '') + '.')];
    bits.push(sent(`mase_common, flag_* columns (${CSVSRC}); the not-fit gate is MASE >= 1.1, reports/diagnostics/README.md`,
      `MASE is <b>${fmt(s.mase_common)}</b> on the common window`
      + (s.flags && s.flags.length ? `, flags: ${esc(s.flags.join(', '))}` : '') + '.'));
    if (s.ma3_fails) bits.push(sent(`ma3_also_fails_common, ma3_mase_common (${CSVSRC})`,
      `MA3 also fails the gate on this SKU (MA3 MASE ${fmt(s.ma3_mase_common)}).`));
    bits.push(sent('cause thresholds: reports/diagnostics/README.md; cohort split counted over the 132 rows',
      `<span class="muted">${esc(s.cause)}: ${esc((F.thresholds.find(t => t[0] === s.cause) || [, 'no rule fired'])[1])}`
      + ` · across the cohort ${causeTag(V.skus, s.cause)}.</span>`));
    bits.push(sent('Yuan, 2026-09-23 \u2014 fixed text, not recomputed here', esc(F.no_better_model)));
    out.push(['unfitnote', bits.join(' ')]);
  }
  return out;
}
// Collapsed-section state, remembered for the life of the page so moving
// between SKUs does not re-collapse what you opened. Nothing is removed by the
// collapse - every section is one click away and holds what it always held.
const openSec = {};
function sec(key, title, body, hint){
  if (!body) return '';
  return `<details class="sec" data-sec="${esc(key)}"${openSec[key] ? ' open' : ''}>`
    + `<summary>${esc(title)}${hint != null ? ` <span class="muted">${esc(hint)}</span>` : ''}</summary>`
    + `<div class="secbody">${body}</div></details>`;
}
function bindSecs(root){
  $$(root + ' details.sec').forEach(d => d.ontoggle = () => { openSec[d.dataset.sec] = d.open; });
}
// The verdict in plain words. One fixed sentence per verdict, plus one fixed
// clause per cause group - no sentence is composed at run time.
function verdictLine(s){
  const pctOf = v => v == null ? null : Math.round(v * 100) + '%';
  const rlr = s.rlr_fit != null ? s.rlr_fit : s.rlr;
  const mf = monthFacts(s), ns = mf.scored.length;
  const CAUSE = {
    'level shift': rlr == null || !s.lvl ? 'The selling level has shifted.'
      : `Recent sales are at ${pctOf(rlr)} of the usual level; the last 6 months (${s.lvl.recent[0]} \u2013 ${s.lvl.recent[1]}) `
        + `average ${fmt(s.lvl.r, 2)}\u00d7 the 12 before, and ${mf.recentScored.length} of the ${ns} months we score on fall inside those 6.`,
    'spiky': !mf.spikes ? 'Spike months could not be re-identified on this series.'
      : `${mf.spikes.length} month(s) of the whole series sit far outside this SKU\u2019s usual range; ${mf.spikesScored.length} of them fall in the ${ns} months we score on`
        + (mf.bandOut ? `, and ${mf.bandOut.length} of those ${ns} fell outside the band.` : '.')
        + ' A one-step forecast cannot follow them.',
    'high volatility': 'Month-to-month swings on this SKU are wider than most of the cohort.',
    'intermittent': 'Many months have no sales at all, so there is little to follow.',
    'tiny scale': 'This SKU sells in small volumes, so ordinary swings look large against them.',
    'trend reversal': 'The recent trend runs opposite to the longer-run trend.',
    'none of the above': 'No cause rule fires; the forecast simply misses by more than the gate allows.',
  };
  const tail = CAUSE[s.cause] || '';
  if (s.verdict === 'not fit') return ['notfit', `<b>Not fit to use.</b> ${tail}`];
  if (s.verdict === 'borderline') return ['borderline', `<b>Borderline.</b> It sits just inside the gate. ${tail}`];
  if (s.verdict === 'clean') return ['clean', `<b>Fit to use on the evidence tested.</b> ${tail}`];
  return ['', `<b>Not scored.</b> Under 3 months of sales, so there is nothing to measure yet.`];
}
function verdictBlock(s){
  const [cls, txt] = verdictLine(s);
  return `<div class="verdictline ${cls}" title="verdict, cause_group (${esc(CSVSRC)}); recent_level_ratio; spike months and level windows re-derived on this series">${txt}</div>`;
}
// The four that answer "what is the number and can I use it". MASE on the
// common window is the one the verdict is made on, so it carries the 1.1 gate.
function topTiles(s){
  const p = PROV(s);
  return `<div class="stats four">` + [
    [fmt(s.served), `Served forecast${s.provisional ? ' (provisional)' : ''}`, false],
    [fmt(s.ma3), 'MA3 forecast', false],
    [p ? NT : fmt(s.mase_common), 'MASE (common window)', !p && s.mase_common != null && s.mase_common >= 1.1],
    [fmt(s.rlr_fit != null ? s.rlr_fit : s.rlr), 'Recent level ratio (3 / 12 mo)', false],
  ].map(([v, l, f]) => `<div class="stat${f ? ' flag' : ''}" title="${esc(v)}"><div class="v">${esc(v)}</div><div class="l">${l}</div></div>`).join('') + `</div>`;
}
const legendBox = s => `<details class="legendbox"${openSec.legend ? ' open' : ''} data-sec="legend"><summary>legend</summary>${LEGEND(s)}</details>`;
// The four collapsed sections. Every block that used to sit open on the page is
// in exactly one of them; nothing was dropped.
function routingKv(s){
  return `<h4 style="margin:14px 0 4px;font-size:12px;color:var(--ink-2)">Routing</h4>` + kv([
      ['status', esc(s.status)],
      ['router bin', esc(s.router_bin) + (s.sales_months != null ? ` (${s.sales_months} sales months${V.pv ? ', incl. placeholder' : ''})` : '')],
      ['holdout months', s.holdout ? `${s.holdout_months} (${V.periods[s.holdout[0]]} – ${V.periods[s.holdout[1]]})` : '—'],
      ['components', esc(s.components ? JSON.stringify(s.components) : '—')],
      ['band (stored)', s.lo == null ? '\u2014 (no holdout RMSE)' : `${fmt(s.lo)} \u2013 ${fmt(s.hi)} = ${fmt(s.served)} \u00b1 ${B.z} \u00d7 ${fmt(s.rmse)}`
        + (s.rmse_derived ? ' <span class="muted">(\u03c3 inverted from the stored band)</span>' : '')],
      ['coverage', s.cov == null ? '\u2014' : `${pctv(s.cov)} of ${s.hpath.length} holdout months inside`
        + (s.outside && s.outside.length ? ` \u00b7 outside: ${s.outside.map(i => V.periods[i]).join(', ')}` : '')],
      ['MA3 backup', esc(s.backup) + (s.backup_reason ? ` — ${esc(s.backup_reason)}` : '')],
      ['backup options', backupOptions(s)],
      ['bin_reason', binReasonHTML(s)],
      ['other schemes', esc(Object.entries(s.schemes).filter(([k]) => k !== 'combined_v1').map(([k, v]) => `${k}=${v}`).join(', '))],
    ]);
}
function skuSections(s, W){
  said.mad = false;                       // spell out MAD once per render
  const outs = outsideSentences(s), hon = honestySentences(s), mf = monthFacts(s);
  const why = hon.map(([cls, t]) => cls === 'unfitnote' ? `<div class="${cls}">${t}</div>` : '').join('')
    || `<div class="explain"><ul><li>${verdictLine(s)[1].replace(/<\/?b>/g, '')}</li></ul></div>`;
  const bandBody = hon.filter(([cls]) => cls === 'widenote').map(([cls, t]) => `<div class="${cls}">${t}</div>`).join('')
    + (outs.length ? `<div class="explain"><h4>Why the actual fell outside the band</h4><ul>`
        + outs.map(x => `<li>${x}</li>`).join('') + `</ul></div>` : '')
    + kv([['band (stored)', s.lo == null ? '\u2014 (no holdout RMSE)'
            : `${fmt(s.lo)} \u2013 ${fmt(s.hi)} = ${fmt(s.served)} \u00b1 ${B.z} \u00d7 ${fmt(s.rmse)}`],
          ['band width / forecast', fmt(s.bw)],
          ['coverage', s.cov == null ? '\u2014' : `${pctv(s.cov)} of ${s.hpath.length} holdout months inside`
            + (s.outside && s.outside.length ? ` \u00b7 outside: ${s.outside.map(i => V.periods[i]).join(', ')}` : '')],
          ['MA3 band (computed)', s.ma3_bw == null ? '\u2014' : `width / forecast ${fmt(s.ma3_bw)} \u00b7 coverage ${pctv(s.ma3_cov)}`]]);
  return sec('why', 'Why this verdict', why)
    + sec('series', 'Series shape', `<div class="explain"><ul>` + seriesSentences(s).map(x => `<li>${x}</li>`).join('') + `</ul></div>`)
    + sec('band', 'Band detail', bandBody, mf.bandOut && mf.bandOut.length ? `${mf.bandOut.length} of ${mf.scored.length} scored month(s) outside the band` : '')
    + sec('all', 'All metrics', statTiles(s) + routingKv(s));
}

// the same summary, one line, for the sparkline column's hover
function oneLine(s){
  const rlr = s.rlr_fit != null ? s.rlr_fit : s.rlr;
  return [`${u(s.sales_months_fit != null ? s.sales_months_fit : s.sales_months)} months of sales, ${s.router_bin} bin`,
    rlr == null ? 'no recent-level ratio' : `recent 3 at ${(rlr * 100).toFixed(1)}% of the 12-month level`,
    `${s.spike_months ? s.spike_months.length : '\u2014'} spike month(s) beyond 3 MAD`,
    s.cause_cv == null ? 'no CV' : `CV ${fmt(s.cause_cv)} vs cohort median ${fmt(F.median_cv)}`,
    `median ${u(s.cause_median_units)} units`,
    (s.cause_zero_share ? `${Math.round(s.cause_zero_share * s.cause_n_months)} zero/missing months` : 'no zero or missing months'),
    (s.neg_months ? `${s.neg_months} negative month(s): ${RETURNS}` : null),
    `fit verdict: ${s.verdict}`].filter(Boolean).join(' \u00b7 ');
}
function drawBandCard(){
  const a = B.all, rows = Object.entries(B.by_model);
  $('#bandCard').innerHTML = `<details class="sec"${openSec.band_explainer ? ' open' : ''} data-sec="band_explainer">`
    + `<summary>The stored band is an error range, not a validated confidence interval \u2014 details</summary>`
    + `<div class="secbody">`
    + `<div class="sub">Read from <b>Forecast_Result.confidence_lower / confidence_upper</b>. Definition traced to `
    + `DEC-25 (ARCHITECTURE.md) and the writer, scripts/run_baseline_forecast.py:821\u2013840.</div>`
    + kv([
        ['interval', esc(B.interval)],
        ['\u03c3 used', esc(B.sigma)],
        ['level', `<b style="color:var(--flag-ink)">${esc(B.level)}</b>`],
        ['stored where', esc(B.stored)],
        ['corridor on this page', esc(B.corridor)],
        ['MA3 band', esc(B.ma3)],
        ['recomputation check', `${B.agree.mase}/${B.agree.n} MASE, ${B.agree.wape}/${B.agree.n} WAPE, `
          + `${B.agree.rmse}/${B.agree.n} RMSE, ${B.agree.months}/${B.agree.n} holdout-month counts match what the `
          + `pipeline stored` + (B.derived_rmse ? ` \u00b7 \u03c3 inverted from the stored band for ${B.derived_rmse} SKUs` : '')],
        ['coverage granularity', esc(B.granularity)],
        ['fit review', `<b>${esc(F.file)}</b> \u2014 verdict, cause group and both scorings are carried through as `
          + `the CSV gives them. ${esc(F.cause_note)}`],
        ['cause thresholds', F.thresholds.map(([c, t]) => `<b>${esc(c)}</b>: ${esc(t)}`).join('<br>')
          + `<br><span class="muted">recorded in reports/diagnostics/README.md</span>`],
      ])
    + (V.pv ? `<div class="pvnote">Preview mode carries no corridor: the preview file holds one forecast per SKU, not a `
      + `per-month path. Coverage columns read \u2014 here. Switch to <b>Real only</b> for them.</div>` : '')
    + `<table class="mini" style="margin-top:10px"><tr><th class="l">cohort</th><th>SKUs</th>`
    + `<th>median coverage</th><th title="${esc(LVLL)}">below ${esc(LVLL)}</th><th>median band width / forecast</th>`
    + `<th>MA3 median coverage (computed)</th><th title="${esc(LVLL)}">MA3 below ${esc(LVLL)}</th></tr>`
    + [['All scored', a], ...rows.map(([m, blk]) => [mlabel(m), blk])].map(([l, blk]) =>
        `<tr><td class="l">${esc(l)}</td><td>${blk.scored}</td><td>${pctv(blk.cov)}</td>`
        + `<td${blk.below ? ' style="color:var(--flag-ink);font-weight:600"' : ''}>${blk.below}</td>`
        + `<td>${fmt(blk.bw)}</td><td>${pctv(blk.cov3)}</td><td>${blk.below3}</td></tr>`).join('')
    + `</table><div class="muted" style="font-size:12px">Holdout length across the cohort: `
    + `${B.holdout_months ? B.holdout_months[0] + '\u2013' + B.holdout_months[1] + ' months' : '\u2014'}. `
    + `The 13 provisional SKUs have no holdout and no band.</div>`
    + `</div></details>`;
  bindSecs('#bandCard');
}
const absGap = s => s.gap == null ? null : Math.abs(s.gap);
const LONG_NOTE = 'All 72 long forecasts change in preview: the global XGBoost model learns across SKUs, so extra history for 40 SKUs shifts every long forecast.';
const MODEL_KEYS = Object.keys(D.model_label);

// ---------------- mode: every view reads V, never D.skus directly ----------------
let V;
function count(rows, key, order){ const c = {}; (order || []).forEach(k => c[k] = 0); rows.forEach(s => c[s[key]] = (c[s[key]] || 0) + 1); return c; }
function buildView(mode){
  const pv = mode === 'preview';
  // The corridor and its coverage are computed from the REAL served path. The
  // preview file has no per-month forecasts, so preview mode carries none rather
  // than showing a real corridor under preview numbers.
  const skus = pv ? D.skus.map(s => ({...s, real_served: s.served, ...D.preview.skus[s.pk], mode,
                                      hpath: null, cov: null, bw: null, ma3_cov: null, ma3_bw: null})) : D.skus.map(s => ({...s, real_bin: s.router_bin, ph: null, ph_count: 0, mode}));
  return {
    mode, pv, skus, byPk: new Map(skus.map(s => [s.pk, s])),
    periods: pv ? D.preview.periods : D.periods,
    expected: pv ? D.preview.expected : D.expected,
    counts: {combined: count(skus, 'combined', D.combined_order), router: count(skus, 'router_bin', D.router_order),
             real_router: count(skus, 'real_bin', D.router_order), model: count(skus, 'method', MODEL_KEYS),
             backup: count(skus, 'backup', D.backup_order)},
  };
}
function setMode(mode){
  V = buildView(mode);
  seg($('#modeSeg'), [['real', 'Real only'], ['preview', 'Preview: with 2021–22 placeholder']], () => V.mode, setMode, true);
  $('#pvbanner').hidden = !V.pv;
  document.body.dataset.mode = mode;
  $('#noteText').innerHTML = V.pv
    ? `Preview reads <b>router_preview_synth.csv</b>, <b>series_synth.csv</b> and <b>preview_summary.csv</b> (copied to tools/dsd_dev_viewer/data/). Bins, served forecasts, served MASE / WAPE and MA3's MASE / WAPE on the same holdout are shown exactly as the preview file gives them; nothing is refitted or rescaled here. <b>Cohort result (real data):</b> TSB and the XGBoost + MA3 average tie MA3.`
    : `Every number is read from what the pipeline stored (forecast_result, sku_segment, sku_traits, unilever_sku_demand_fact_real). Nothing is refitted. <b>Cohort result:</b> TSB and the XGBoost + MA3 average tie MA3 on real Tier A data (half-year block tests). They are served because they are trained models that use the full history, not because they are more accurate. MA3 is the benchmark and the fallback. Per-SKU pages show that SKU's own MASE and WAPE only.`;
  filter = null;
  buildPN();
  drawKpis(); initSegs(); drawBandCard();
  showTab(tab);
}
function drawKpis(){
  const scored = V.skus.filter(s => s.status === 'ok');
  $('#kpis').innerHTML = [
    [V.skus.length, 'Tier A SKUs (as of 2026-02)'],
    [scored.length, 'Routed to a model'],
    [V.counts.model.provisional, 'Provisional (<3 months)'],
    [V.counts.model.tsb + V.counts.model.xgb_ma3_avg, 'Served by a challenger'],
    [scored.filter(s => s.mase != null && s.mase >= 1).length, 'SKUs with MASE ≥ 1'],
    ...(V.pv ? [[V.skus.filter(s => s.ph_count > 0).length, 'SKUs with placeholder months']] : [[V.counts.backup.fired, 'MA3 backup fired']]),
  ].map(([v, l]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
}
$('#meta').innerHTML = `${esc(D.meta.cohort)}<br>forecast month ${esc(fcMonth)} · ${D.meta.offline ? 'snapshot read' : 'read live'} ${esc(D.meta.generated.replace('T', ' '))}`
  + (D.meta.offline ? ` · <b style="color:var(--flag-ink)">rebuilt offline from the last snapshot</b>` : '')
  + (D.meta.problems.length ? ` · <b>${D.meta.problems.length} data problems</b>` : '');

function metricCell(s, k){
  if (PROV(s)) return `<td class="num muted">${NT}</td>`;
  const v = s[k], f = (k === 'mase' || k === 'ma3_mase') && v != null && v >= 1;
  return `<td class="num${f ? ' flag' : ''}"${f ? ' title="MASE ≥ 1: worse than the in-sample naive scale on this holdout"' : ''}>${fmt(v)}</td>`;
}
// DEC-28, read from analytics/forecasting/backup_options.json. The bin is the
// LIVE router bin in real mode and the PREVIEW router bin in preview mode -
// s.router_bin is already whichever of the two the mode is showing, so the same
// lookup serves both. No fallback text: the build fails if a bin has no entry.
const BO = bin => D.backup_options.bins[bin] || null;
function backupOptions(s){
  const b = BO(s.router_bin);
  if (!b) return `<span class="ph">no entry for the ${esc(s.router_bin)} bin</span>`;
  if (!b.backups.length) return `<span class="ph">none</span> <span class="muted">(${esc(s.router_bin)} bin)</span>`;
  return `${esc(b.backups.join(' → '))} <span class="muted">(${esc(s.router_bin)} bin)</span>`;
}
// The per-SKU panel: ordered list, then the watch list where the bin has one.
function backupPanel(s){
  const b = BO(s.router_bin);
  if (!b) return `<div class="ph">no entry for the ${esc(s.router_bin)} bin</div>`;
  const ord = b.backups.length
    ? `<ol style="margin:4px 0 0;padding-left:18px">${b.backups.map(x => `<li>${esc(x)}</li>`).join('')}</ol>`
    : `<div class="ph">none</div>`;
  return `<div>served: <b style="color:var(--ink-2)">${esc(b.served)}</b></div>${ord}`
    + (b.note ? `<div class="muted" style="margin-top:5px">${esc(b.note)}</div>` : '')
    + (b.watch && b.watch.length
        ? `<div style="margin-top:8px"><b>Watch list</b><div style="font-family:var(--mono);font-size:11px;color:var(--ink-2);margin-top:3px">${esc(b.watch.join(', '))}</div>`
          + (b.watch_note ? `<div class="muted" style="margin-top:4px">${esc(b.watch_note)}</div>` : '') + `</div>`
        : '')
    + `<div class="muted" style="margin-top:8px">${esc(D.backup_options.decision)} · ${esc(D.backup_options.file)}</div>`;
}

// ---------------- chart ----------------
const GEOM = {};
function chart(s, W, H, mode){
  const P = V.periods.concat([fcMonth]), n = P.length, big = mode === 'big', spark = mode === 'spark';
  const corr = spark || !s.hpath ? [] : s.hpath.filter(p => p.i != null && p.lo != null);
  // The axis is capped at 1.5x the largest actual so a band several times the
  // forecast cannot flatten the series into a line at the bottom. The cap never
  // hides an actual or a point forecast - only band bounds are allowed to clip,
  // and every clipped bound is drawn as a clipped edge with its true value.
  const acts = s.monthly.filter(v => v != null);
  const pts = [s.served, s.ma3, ...corr.map(p => p.v)].filter(v => v != null);
  const bands = spark ? [] : [s.hi, s.lo, ...corr.flatMap(p => [p.hi, p.lo])].filter(v => v != null);
  const natural = Math.max(1, ...acts, ...pts, ...bands) * 1.08;
  const cap = Math.max((acts.length ? Math.max(...acts) : 0) * 1.5, Math.max(1, ...pts) * 1.08);
  const ymax = spark ? natural : Math.min(natural, cap);
  const ymin = Math.min(0, ...acts, ...pts);
  const clipTop = [];
  const L = big ? 56 : spark ? 2 : 6, R = spark ? 5 : big ? 18 : 12, T = spark ? 3 : 8, B = spark ? 3 : big ? 26 : 16;
  const X = i => L + i * (W - L - R) / (n - 1), Y = v => T + (H - T - B) * (1 - (v - ymin) / (ymax - ymin));
  const clip = v => { if (v > ymax){ clipTop.push(v); return ymax; } return v; };
  const Yc = v => Y(clip(v));
  const id = mode + s.pk + V.mode;
  GEOM[id] = {L, R, W, n};
  const isPh = i => s.ph && i >= s.ph[0] && i <= s.ph[1];
  let g = `<svg viewBox="0 0 ${W} ${H}" width="${spark ? W : ''}" height="${spark ? H : ''}" data-pk="${s.pk}" data-g="${id}" data-ph="${s.ph_count || 0}" role="img" aria-label="${esc(s.code)} monthly demand and forecast">`;
  if (s.ph) g += `<rect class="phband" x="${X(s.ph[0] - .5)}" y="${T}" width="${X(s.ph[1] + .5) - X(s.ph[0] - .5)}" height="${H - T - B}" fill="url(#phpat)"/>`
    + (big ? `<text x="${X(s.ph[0] - .5) + 4}" y="${T + 11}" fill="var(--ph)" font-size="10">placeholder (not SSM data)</text>` : '');
  if (!spark){
    if (big && s.holdout) g += `<rect x="${X(s.holdout[0] - .5)}" y="${T}" width="${X(s.holdout[1] + .5) - X(s.holdout[0] - .5)}" height="${H - T - B}" fill="var(--accent)" opacity=".10"/>`
      + `<text x="${X(s.holdout[0] - .5) + 4}" y="${T + 11}" fill="var(--accent)" font-size="10" opacity=".9">holdout</text>`;
    const ticks = big ? [0, 1, 2, 3, 4].map(t => ymin + (ymax - ymin) * t / 4) : [ymin, ymax / 1.08];
    ticks.forEach(v => {
      g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/>`;
      if (big) g += `<text x="${L - 6}" y="${Y(v) + 3}" text-anchor="end" fill="var(--ink-3)" font-size="10">${fmt(v, 0)}</text>`;
    });
    if (ymin < 0) g += `<line x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--line-2)"/>`;
    g += `<rect x="${X(n - 1.5)}" y="${T}" width="${X(n - 1) - X(n - 1.5) + R}" height="${H - T - B}" fill="var(--surface-3)" opacity=".45"/>`;
    const labels = big ? P.map((_, i) => i).filter(i => (i % 6 === 0 && i < n - 4) || i === n - 1) : [0, n - 1];
    labels.forEach(i => g += `<text x="${X(i)}" y="${H - (big ? 8 : 3)}" text-anchor="${big ? 'middle' : (i ? 'end' : 'start')}" fill="var(--ink-3)" font-size="${big ? 10 : 9}">${P[i]}</text>`);
  }
  // The band across the HOLDOUT months: a corridor around each month's own
  // one-step forecast, not a flat line around the final forecast. Computed at
  // build time (nothing stores a per-month band) - see D.band.corridor.
  if (corr.length){
    const up = corr.map(p => `${X(p.i).toFixed(1)},${Yc(p.hi).toFixed(1)}`);
    const dn = corr.map(p => `${X(p.i).toFixed(1)},${Y(Math.max(ymin, p.lo)).toFixed(1)}`);
    if (corr.length > 1){
      g += `<polygon class="corr" points="${up.concat(dn.slice().reverse()).join(' ')}" fill="${COLOR[s.method]}" opacity=".17"/>`
        + `<polyline points="${up.join(' ')}" fill="none" stroke="${COLOR[s.method]}" stroke-width="1.2" stroke-dasharray="4 3" opacity=".85"/>`
        + `<polyline points="${dn.join(' ')}" fill="none" stroke="${COLOR[s.method]}" stroke-width="1.2" stroke-dasharray="4 3" opacity=".85"/>`
        + `<polyline points="${corr.map(p => `${X(p.i).toFixed(1)},${Y(p.v).toFixed(1)}`).join(' ')}" fill="none" stroke="${COLOR[s.method]}" stroke-width="1.6"/>`;
    } else {
      const p = corr[0], w = big ? 9 : 6;
      g += `<rect x="${X(p.i) - w / 2}" y="${Yc(p.hi)}" width="${w}" height="${Math.max(1, Y(Math.max(ymin, p.lo)) - Yc(p.hi))}" rx="3" fill="${COLOR[s.method]}" opacity=".22"/>`
        + `<circle cx="${X(p.i)}" cy="${Y(p.v)}" r="${big ? 3 : 2}" fill="${COLOR[s.method]}"/>`;
    }
    // a clipped bound is a dotted edge at the cap, not a line pretending to be the top
    corr.filter(p => p.hi > ymax).forEach(p => {
      g += `<line x1="${X(p.i) - 6}" x2="${X(p.i) + 6}" y1="${Y(ymax)}" y2="${Y(ymax)}" stroke="${COLOR[s.method]}" stroke-width="2" stroke-dasharray="2 2"/>`
        + `<path d="M${X(p.i) - 4},${Y(ymax) + 5} l4,-5 l4,5" fill="none" stroke="${COLOR[s.method]}" stroke-width="1.4"/>`
        + `<title>${p.m}: band top ${fmt(p.hi, 0)}, above the axis cap</title>`;
    });
    corr.filter(p => p.out).forEach(p => {
      const r = big ? 5 : 3.5;
      g += `<circle class="outmark" cx="${X(p.i)}" cy="${Y(p.a)}" r="${r}"><title>${p.m}: actual ${fmt(p.a, 1)} outside the band ${fmt(p.lo, 0)}\u2013${fmt(p.hi, 0)}</title></circle>`;
    });
  }
  // actual: a segment only between two consecutive months that both have a row AND are the same kind
  // (real vs placeholder). Placeholder months are dashed in their own colour, never styled as demand.
  const paths = {real: '', ph: ''};
  s.monthly.forEach((v, i) => {
    if (v == null) return;
    const kind = isPh(i) ? 'ph' : 'real';
    const prev = i > 0 ? s.monthly[i - 1] : null, next = i < s.monthly.length - 1 ? s.monthly[i + 1] : null;
    const joined = prev != null && (isPh(i - 1) ? 'ph' : 'real') === kind;
    const joinsNext = next != null && (isPh(i + 1) ? 'ph' : 'real') === kind;
    paths[kind] += (joined ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1);
    if (!joined && !joinsNext && !spark) g += `<circle cx="${X(i)}" cy="${Y(v)}" r="2.5" fill="${kind === 'ph' ? 'none' : 'var(--actual)'}" stroke="${kind === 'ph' ? 'var(--ph)' : 'none'}"/>`;
  });
  if (paths.ph) g += `<path class="phline" d="${paths.ph}" fill="none" stroke="var(--ph)" stroke-width="${big ? 1.8 : 1.3}" stroke-dasharray="5 4" stroke-linejoin="round"/>`;
  g += `<path d="${paths.real}" fill="none" stroke="var(--actual)" stroke-width="${big ? 2 : 1.5}" stroke-linejoin="round" stroke-linecap="round"/>`;
  if (!spark && s.first_i != null) for (let i = s.first_i; i <= s.last_i; i++)
    if (s.monthly[i] == null){
      const nul = (s.null_months || []).includes(i), r = big ? 3.5 : 2.5, y0 = Y(Math.max(0, ymin));
      g += nul ? `<rect class="nullq" x="${X(i) - r}" y="${y0 - r}" width="${2 * r}" height="${2 * r}" fill="var(--surface-1)" stroke="var(--warn)" stroke-width="1.5"><title>${P[i]}: NULL quantity (pipeline counts it as 0)</title></rect>`
        : `<circle cx="${X(i)}" cy="${y0}" r="${r}" fill="var(--surface-1)" stroke="var(--ink-3)" stroke-width="1.5"><title>${P[i]}: no row</title></circle>`;
    }
  const fx = X(n - 1), c = COLOR[s.method];
  if (!spark && s.lo != null && s.hi != null){
    const top = Yc(s.hi);
    g += `<rect x="${fx - 4}" y="${top}" width="8" height="${Math.max(1, Y(Math.max(ymin, s.lo)) - top)}" rx="4" fill="${c}" opacity=".28"/>`;
    if (s.hi > ymax) g += `<line x1="${fx - 7}" x2="${fx + 7}" y1="${Y(ymax)}" y2="${Y(ymax)}" stroke="${c}" stroke-width="2.4" stroke-dasharray="2 2"/>`
      + `<path d="M${fx - 5},${Y(ymax) + 6} l5,-6 l5,6" fill="none" stroke="${c}" stroke-width="1.6"/>`;
  }
  const last = s.monthly[n - 2];
  if (s.served != null && last != null) g += `<line x1="${X(n - 2)}" y1="${Y(last)}" x2="${fx}" y2="${Y(s.served)}" stroke="${c}" stroke-width="1.5" stroke-dasharray="3 3"/>`;
  if (!spark && s.ma3 != null && s.method !== 'ma3') g += `<circle cx="${fx}" cy="${Y(s.ma3)}" r="${big ? 5.5 : 4}" fill="none" stroke="var(--m-ma3)" stroke-width="2"/>`;
  if (s.served != null) g += `<circle cx="${fx}" cy="${Y(s.served)}" r="${big ? 6 : spark ? 2.8 : 4}" fill="${c}" stroke="var(--surface-1)" stroke-width="${spark ? 1 : 2}"/>`;
  // the band region says what it is on the chart itself, not only in the legend
  if (big && (corr.length || s.lo != null)){
    const x0 = corr.length ? X(corr[0].i - .5) : X(n - 1.5);
    g += `<line x1="${x0}" x2="${X(n - 1) + R - 2}" y1="${T + 30}" y2="${T + 30}" stroke="${c}" stroke-width="1" opacity=".45"/>`
      + `<text class="bandregion" x="${x0 + 4}" y="${T + 26}" style="fill:${c};opacity:.95">band over holdout + forecast month</text>`;
  }
  if (!spark && clipTop.length){
    const top = Math.max(...clipTop);
    g += `<line x1="${L}" x2="${W - R}" y1="${Y(ymax)}" y2="${Y(ymax)}" stroke="var(--ink-2)" stroke-width="1" stroke-dasharray="2 3" opacity=".7"/>`
      + (big ? `<text class="clipnote" x="${W - R - 2}" y="${Y(ymax) - 5}" text-anchor="end">axis capped at 1.5\u00d7 max actual \u00b7 band reaches ${fmt(top, 0)}</text>` : '');
  }
  if (!spark) g += `<line class="xh" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/><rect x="${L}" y="0" width="${W - L}" height="${H}" fill="transparent"/>`;
  return g + '</svg>';
}
document.body.insertAdjacentHTML('beforeend', `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><pattern id="phpat" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="rgba(201,162,39,.06)"/><line x1="0" y1="0" x2="0" y2="6" stroke="rgba(201,162,39,.30)" stroke-width="2"/></pattern></defs></svg>`);
const tip = $('#tip');
document.addEventListener('mousemove', ev => {
  const svg = ev.target.closest && ev.target.closest('.chart svg');
  $$('.xh[visibility="visible"]').forEach(l => { if (!svg || !svg.contains(l)) l.setAttribute('visibility', 'hidden'); });
  if (!svg || !GEOM[svg.dataset.g]){ tip.style.display = 'none'; return; }
  const s = V.byPk.get(+svg.dataset.pk), gm = GEOM[svg.dataset.g];
  const box = svg.getBoundingClientRect(), vx = (ev.clientX - box.left) * gm.W / box.width;
  const step = (gm.W - gm.L - gm.R) / (gm.n - 1), i = Math.max(0, Math.min(gm.n - 1, Math.round((vx - gm.L) / step)));
  const xh = svg.querySelector('.xh'); xh.setAttribute('x1', gm.L + i * step); xh.setAttribute('x2', gm.L + i * step); xh.setAttribute('visibility', 'visible');
  let rows;
  if (i === gm.n - 1){
    rows = [[`Served · ${mlabel(s.method)}`, fmt(s.served)], ['MA3', fmt(s.ma3)]];
    if (s.lo != null) rows.push(['Band', `${fmt(s.lo, 0)} – ${fmt(s.hi, 0)}`]);
    if (V.pv) rows.push(['Change vs real', pct(s.change)]);
  } else {
    const v = s.monthly[i], ph = s.ph && i >= s.ph[0] && i <= s.ph[1];
    rows = [[ph ? 'Placeholder' : 'Actual', v == null ? ((s.null_months || []).includes(i) ? 'NULL quantity (pipeline counts it as 0)' : 'no row') : fmt(v, 1)]];
    if (v != null && v < 0) rows.push(['', RETURNS]);
    if (ph) rows.push(['', 'not SSM data']);
    if (s.holdout && i >= s.holdout[0] && i <= s.holdout[1]) rows.push(['', 'holdout month']);
    const hp = hpoint(s, i);
    if (hp){
      rows.push([`One-step \u00b7 ${mlabel(s.method)}`, fmt(hp.v)]);
      if (hp.lo != null) rows.push(['Band (computed)', `${fmt(hp.lo, 0)} \u2013 ${fmt(hp.hi, 0)}`]);
      rows.push(['Actual vs band', hp.out == null ? '\u2014' : hp.out ? 'OUTSIDE' : 'inside']);
      rows.push(['MA3 one-step', fmt(hp.m3)]);
      if (hp.bu) rows.push(['', 'MA3 backup fired this month']);
    }
  }
  tip.innerHTML = `<div class="h">${esc(s.code)} · ${i === gm.n - 1 ? fcMonth + ' (forecast)' : V.periods[i]}</div>`
    + rows.map(([k, v]) => `<div class="r"><span>${esc(k)}</span><b>${v}</b></div>`).join('');
  tip.style.display = 'block';
  tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 8, ev.clientX + 14) + 'px';
  tip.style.top = Math.max(8, ev.clientY - tip.offsetHeight - 12) + 'px';
});
const LEGEND = s => `<div class="legend"><span><i class="sw-line" style="background:var(--actual)"></i>Actual (real)</span>`
  + (s.ph ? `<span><i class="sw-ph"></i><i class="sw-phbg"></i>Placeholder months (not SSM data)</span>` : '')
  + `<span><i class="sw-hollow"></i>No row</span>`
  + ((s.null_months || []).length ? `<span><i class="sw-null"></i>NULL quantity (pipeline counts it as 0)</span>` : '')
  + `<span><i class="sw-dot" style="background:${COLOR[s.method]}"></i>Served · ${esc(mlabel(s.method))}</span>`
  + (s.method !== 'ma3' ? `<span><i class="sw-ring" style="border-color:var(--m-ma3)"></i>MA3</span>` : '')
  + (s.lo != null ? `<span><i class="sw-band" style="background:${COLOR[s.method]}"></i>Band (${esc(fcMonth)}, stored)</span>` : '')
  + (s.hpath && s.hpath.length ? `<span><i class="sw-corr" style="background:${COLOR[s.method]}"></i>Band over the holdout (computed)</span>`
    + `<span><i class="sw-out"></i>Actual outside the band</span>` : '')
  + `<span><i class="sw-clip"></i>Axis capped at 1.5\u00d7 max actual; a clipped band edge is dotted, true value labelled</span>`
  + (s.holdout ? `<span><i class="sw-hold"></i>Holdout months</span>` : '') + `</div>`;
function statTiles(s){
  const p = PROV(s);
  return `<div class="stats">` + [
    [fmt(s.served), `Served forecast${s.provisional ? ' (provisional)' : ''}`], [fmt(s.ma3), 'MA3 forecast'],
    [pct(s.gap), 'Served vs MA3'],
    // WAPE / MA3 WAPE, MA3 coverage, MA3 band width and the raw Band card were
    // dropped 2026-09-23: the band's bounds are already printed by the Routing
    // block below as 'band (stored)', and the MA3 mirrors of coverage and width
    // belong to the Band detail section, not to this summary.
    ...(V.pv ? [[pct(s.change), 'Served change vs real']] : []),
    [p ? NT : fmt(s.mase), 'MASE (served, holdout)', !p && s.mase >= 1],
    [p ? NT : fmt(s.ma3_mase), 'MA3 MASE (same holdout)', !p && s.ma3_mase >= 1],
    [p ? NT : pctv(s.cov), 'Coverage (holdout)', !p && s.cov != null && s.cov < LVL],
    [p ? NT : fmt(s.bw), 'Band width / forecast'],
    [fmt(s.rlr), 'Recent level ratio (3 / 12 mo)'],
  ].map(([v, l, f]) => `<div class="stat${f ? ' flag' : ''}" title="${esc(v)}"><div class="v">${esc(v)}</div><div class="l">${l}</div></div>`).join('') + `</div>`;
}
// bin_reason as sku_segment stored it, with one thing added and nothing changed:
// where the reason's own Mann-Kendall p is >= 0.05 the Theil-Sen slope it quotes
// is labelled NOT SIGNIFICANT, so a non-zero slope is not read as a trend. The p
// is taken from the reason string itself (falling back to sku_traits.trend_pvalue)
// so the label always describes the number printed beside it.
const MK_ALPHA = 0.05;
function binReasonHTML(s){
  const r = s.bin_reason;
  if (!r) return esc(r);
  const m = /Mann-Kendall p=([0-9.]+)/.exec(r);
  const pv = m ? parseFloat(m[1]) : (s.traits && s.traits.trend_pvalue);
  if (!/Theil-Sen slope/.test(r) || pv == null || !(pv >= MK_ALPHA)) return esc(r);
  return esc(r) + ` <span class="ret" title="Mann-Kendall p=${esc(pv)} >= ${MK_ALPHA}: the slope is not distinguishable from no trend">`
    + `— slope not statistically significant (p ≥ ${MK_ALPHA})</span>`;
}
const kv = o => '<dl class="kv">' + o.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('') + '</dl>';
const skuNotes = s => V.pv ? (s.ph_count ? `<div class="pvnote">${s.ph_count} placeholder months (2021–22) prepended. They are not SSM's sales.</div>` : '')
  + (s.router_bin === 'long' ? `<div class="pvnote">${esc(LONG_NOTE)} Served change vs real: <b>${pct(s.change)}</b>.</div>` : '') : '';
function detailHTML(s, W){
  if (!s) return '<div class="empty">Select a SKU.</div>';
  return `<div class="dhead"><div class="code">${esc(s.code)}</div><div class="nm">${esc(s.name)}</div>`
    + `<div class="tags">${modelPill(s.method)}<span class="pill">router: ${esc(s.router_bin)}</span>${V.pv ? `<span class="pill">real bin: ${esc(s.real_bin)}</span>` : ''}<span class="pill">combined_v1: ${esc(s.combined)}</span></div></div>`
    + skuNotes(s)
    + verdictBlock(s)
    + `<div class="chart">${chart(s, W || 420, 230, 'big')}</div>` + legendBox(s) + topTiles(s) + skuSections(s, W)

    + `<details><summary>Traits (sku_traits, 2026-02, real data)</summary>` + kv(Object.entries(s.traits || {}).map(([k, v]) => [k, esc(v == null ? '—' : v)])) + `</details>`;
}

// ---------------- sortable table helper ----------------
function sortRows(rows, key, dir){
  return rows.slice().sort((a, b) => {
    const x = typeof key === 'function' ? key(a) : a[key], y = typeof key === 'function' ? key(b) : b[key];
    if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
    return (x > y ? 1 : x < y ? -1 : 0) * dir;
  });
}
function renderTable(el, cols, rows, st, onRow, selected){
  const head = '<tr>' + cols.map(c => `<th data-k="${c.k}"${c.num ? ' class="num"' : ''}${c.tip ? ` title="${esc(c.tip)}"` : ''}>${c.l}${st.k === c.k ? (st.d > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('') + '</tr>';
  const col = cols.find(c => c.k === st.k);
  const sorted = col && col.sort !== false ? sortRows(rows, col.v || col.k, st.d) : rows;
  el.querySelector('thead').innerHTML = head;
  el.querySelector('tbody').innerHTML = sorted.map(s => `<tr data-pk="${s.pk}"${s.pk === selected ? ' class="sel"' : ''}>` + cols.map(c => c.r(s)).join('') + '</tr>').join('');
  el.querySelectorAll('th').forEach(th => th.onclick = () => {
    const c = cols.find(x => x.k === th.dataset.k); if (c.sort === false) return;
    st.d = st.k === c.k ? -st.d : (c.num ? -1 : 1); st.k = c.k; renderTable(el, cols, rows, st, onRow, selected);
  });
  // ETL rows are report rows, not SKUs: they pass no onRow and stay unclickable.
  if (onRow) el.querySelectorAll('tbody tr').forEach(tr => tr.onclick = () => onRow(+tr.dataset.pk));
  return sorted;
}
const C = {
  code: {k:'code', l:'SKU', r: s => `<td>${esc(s.code)}</td>`},
  name: {k:'name', l:'Product', r: s => `<td class="name" title="${esc(s.name)}">${esc(s.name)}</td>`},
  method: {k:'method', l:'Served model', r: s => `<td>${modelPill(s.method)}</td>`},
  served: {k:'served', l:'Served forecast', num:1, r: s => `<td class="num">${fmt(s.served)}</td>`},
  ma3: {k:'ma3', l:'MA3 forecast', num:1, r: s => `<td class="num">${fmt(s.ma3)}</td>`},
  gap: {k:'gap', l:'Served vs MA3', num:1, v: absGap, tip:'(served − MA3) / MA3; sorts on the absolute gap', r: s => `<td class="num">${pct(s.gap)}</td>`},
  change: {k:'change', l:'Change vs real', num:1, v: s => s.change == null ? null : Math.abs(s.change), tip:'(preview served − real served) / real served; sorts on the absolute change', r: s => `<td class="num">${pct(s.change)}</td>`},
  ph: {k:'ph_count', l:'Placeholder months', num:1, r: s => `<td class="num${s.ph_count ? ' flag' : ''}">${s.ph_count}</td>`},
  mase: {k:'mase', l:'MASE', num:1, r: s => metricCell(s, 'mase')},
  ma3_mase: {k:'ma3_mase', l:'MA3 MASE (same holdout)', num:1, tip:'MA3 scored on the same rolling one-step holdout months as the served model', r: s => metricCell(s, 'ma3_mase')},
  wape: {k:'wape', l:'WAPE', num:1, r: s => metricCell(s, 'wape')},
  ma3_wape: {k:'ma3_wape', l:'MA3 WAPE', num:1, r: s => metricCell(s, 'ma3_wape')},
  rlr: {k:'rlr', l:'Recent level ratio', num:1, tip:'mean(last 3 months) / mean(last 12 months) of the modelling series; display only, no threshold', r: s => `<td class="num">${fmt(s.rlr)}</td>`},
  spark: {k:'spark', l:'Monthly demand', sort:false, r: s => `<td class="spark" title="${esc(oneLine(s))}">${chart(s, 150, 30, 'spark')}</td>`},
  cov: {k:'cov', l:'Coverage (holdout)', num:1, tip:'Share of holdout months whose actual falls inside that month\u2019s band. Computed here - no per-month band is stored. Flagged below ' + LVLL + '.',
    r: s => PROV(s) ? `<td class="num muted">${NT}</td>`
      : `<td class="num${s.cov != null && s.cov < LVL ? ' flag' : ''}">${pctv(s.cov)}</td>`},
  bw: {k:'bw', l:'Band width / forecast', num:1, tip:'(confidence_upper - confidence_lower) / forecast_value, as stored on the forecast_date row',
    r: s => PROV(s) ? `<td class="num muted">${NT}</td>` : `<td class="num">${fmt(s.bw)}</td>`},
  ma3_cov: {k:'ma3_cov', l:'MA3 coverage (computed)', num:1, tip:'The same rule applied to MA3\u2019s own rolling one-step RMSE on the same months. No MA3 band is stored. Flagged below ' + LVLL + '.',
    r: s => PROV(s) ? `<td class="num muted">${NT}</td>`
      : `<td class="num${s.ma3_cov != null && s.ma3_cov < LVL ? ' flag' : ''}">${pctv(s.ma3_cov)}</td>`},
  ma3_bw: {k:'ma3_bw', l:'MA3 band width / forecast', num:1, r: s => PROV(s) ? `<td class="num muted">${NT}</td>` : `<td class="num">${fmt(s.ma3_bw)}</td>`},
  verdict: {k:'verdict', l:'Fit verdict', tip:'From ' + D.fit.file + ', carried through as given - not recomputed here',
    v: s => D.fit.verdict_order.indexOf(s.verdict), r: s => `<td>${vcell(s.verdict)}</td>`},
  cause: {k:'cause', l:'Cause group', tip:D.fit.cause_note,
    v: s => D.fit.cause_order.indexOf(s.cause), r: s => `<td class="${s.cause === 'none of the above' ? 'muted' : ''}">${esc(s.cause)}</td>`},
  mase_common: {k:'mase_common', l:'MASE (common window)', num:1, tip:'The fit review\u2019s common-window scoring, the one the verdict is made on',
    r: s => `<td class="num${s.mase_common >= 1 ? ' flag' : ''}">${fmt(s.mase_common)}</td>`},
  mase_pipeline: {k:'mase_pipeline', l:'MASE (pipeline 20%)', num:1, tip:'The stored pipeline scoring, for comparison with the common window',
    r: s => `<td class="num${s.mase_pipeline >= 1 ? ' flag' : ''}">${fmt(s.mase_pipeline)}</td>`},
  assessable: {k:'assessable', l:'Assessable', tip:'Whether the SKU has enough history to be judged at all',
    r: s => `<td class="${s.assessable ? '' : 'muted'}">${s.assessable == null ? '\u2014' : s.assessable ? 'yes' : 'no'}</td>`},
};

// ---------------- tabs ----------------
let tab = 'forecasts';
function showTab(t){
  tab = t;
  $$('nav button').forEach(x => x.setAttribute('aria-selected', x.dataset.tab === t));
  ['forecasts', 'pipeline'].forEach(k => $('#tab-' + k).hidden = k !== t);
  $('.kpis').hidden = t === 'pipeline';
  if (t === 'forecasts') drawForecasts();
  if (t === 'pipeline') drawPipeline();
}
$$('nav button').forEach(b => b.onclick = () => showTab(b.dataset.tab));

// ================= SANKEY (Pipeline panel of the combined_v1 / router nodes) =================
function sankeyCols(){
  return [
    {key:'src', title:'COHORT', items:['Tier A']},
    {key:'combined', title:'COMBINED_V1 BIN', items:D.combined_order},
    ...(V.pv ? [{key:'realrouter', title:'ROUTER BIN (REAL)', items:D.router_order}] : []),
    {key:'router', title:V.pv ? 'ROUTER BIN (PREVIEW)' : 'ROUTER BIN (LIVE)', items:D.router_order},
    {key:'model', title:'SERVED MODEL', items:MODEL_KEYS},
    {key:'backup', title:'MA3 BACKUP', items:D.backup_order},
  ];
}
const SKU_KEY = {combined:'combined', realrouter:'real_bin', router:'router_bin', model:'method', backup:'backup'};
let filter = null;
function drawFlow(){
  const COLS = sankeyCols();
  const val = (s, col) => col === 'src' ? 'Tier A' : s[SKU_KEY[col]];
  const edgesM = {};
  V.skus.forEach(s => { for (let i = 0; i < COLS.length - 1; i++){ const k = `${COLS[i].key}:${val(s, COLS[i].key)}|${COLS[i + 1].key}:${val(s, COLS[i + 1].key)}`; edgesM[k] = (edgesM[k] || 0) + 1; } });
  const edges = Object.entries(edgesM).map(([k, n]) => ({from:k.split('|')[0], to:k.split('|')[1], n}));
  const nodeCount = (col, item) => col === 'src' ? V.skus.length : V.skus.filter(s => s[SKU_KEY[col]] === item).length;
  const W = 1000, nodeW = V.pv ? 132 : 150, gap = 10, top = 28, H0 = 430, total = V.skus.length;
  const k = (H0 - gap * (Math.max(...COLS.map(c => c.items.length)) - 1)) / total;
  const x = i => i * ((W - nodeW) / (COLS.length - 1));
  const pos = {};
  COLS.forEach((c, i) => {
    let y = top;
    c.items.forEach(it => {
      const n = nodeCount(c.key, it);
      if (!n && c.key !== 'backup') return;
      const h = n ? n * k : 26;
      pos[`${c.key}:${it}`] = {x:x(i), y, h, n, col:c.key, item:it, outs:[], ins:[]};
      y += h + gap;
    });
  });
  edges.forEach(e => { const a = pos[e.from], b = pos[e.to]; if (a && b){ a.outs.push(e); b.ins.push(e); } });
  const off = {};
  Object.values(pos).forEach(p => {
    let o = 0; p.outs.sort((u, v) => pos[u.to].y - pos[v.to].y).forEach(e => { off['o' + e.from + e.to] = o; o += e.n * k; });
    let i = 0; p.ins.sort((u, v) => pos[u.from].y - pos[v.from].y).forEach(e => { off['i' + e.from + e.to] = i; i += e.n * k; });
  });
  const H = Math.max(...Object.values(pos).map(p => p.y + p.h)) + 6;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Tier A routing flow">`;
  COLS.forEach((c, i) => s += `<text class="colh" x="${x(i) + 2}" y="14">${c.title}</text>`);
  edges.forEach(e => {
    const a = pos[e.from], b = pos[e.to]; if (!a || !b) return;
    const w = e.n * k, y1 = a.y + off['o' + e.from + e.to] + w / 2, y2 = b.y + off['i' + e.from + e.to] + w / 2;
    const x1 = a.x + nodeW, x2 = b.x, mx = (x1 + x2) / 2;
    const moved = a.col === 'realrouter' && b.col === 'router' && a.item !== b.item;
    const col = moved ? 'var(--ph)' : b.col === 'model' ? COLOR[b.item] : a.col === 'model' ? COLOR[a.item] : 'var(--ink-3)';
    const hi = filter && (e.from === filter || e.to === filter) ? ' hi' : '';
    s += `<path class="link${hi}" stroke="${col}" stroke-width="${Math.max(w - 1, 1)}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"><title>${esc(e.from.split(':')[1])} → ${esc(e.to.split(':')[1])}: ${e.n} SKUs</title></path>`;
  });
  Object.entries(pos).forEach(([key, p]) => {
    const isModel = p.col === 'model', sub = isModel ? mnote(p.item) : '';
    s += `<g class="node${filter === key ? ' sel' : ''}${p.n ? '' : ' empty'}" data-k="${esc(key)}">`
      + `<rect class="box" x="${p.x}" y="${p.y}" width="${nodeW}" height="${p.h}" rx="6"/>`
      + (isModel ? `<rect x="${p.x}" y="${p.y}" width="4" height="${p.h}" rx="2" fill="${COLOR[p.item]}"/>` : '')
      + `<text x="${p.x + 12}" y="${p.y + 17}">${esc(isModel ? mlabel(p.item) : p.item)}</text>`
      + `<text class="n" x="${p.x + nodeW - 10}" y="${p.y + 17}" text-anchor="end">${p.n}</text>`
      + (sub && p.h > 34 ? `<text class="s" x="${p.x + 12}" y="${p.y + 32}">${esc(sub)}</text>` : '') + `</g>`;
  });
  $('#flowSvg').innerHTML = s + '</svg>';
  $('#flowSvg').classList.toggle('filtered', !!filter);
  $$('#flowSvg .node').forEach(g => g.onclick = () => { filter = filter === g.dataset.k ? null : g.dataset.k; drawPanel(); });
}
function binMoves(){
  const moved = V.skus.filter(s => s.real_bin !== s.router_bin), pref = V.skus.filter(s => s.ph_count > 0);
  const m = {}; moved.forEach(s => { const k = `${s.real_bin} → ${s.router_bin}`; m[k] = (m[k] || 0) + 1; });
  const allLong = pref.length && pref.every(s => s.router_bin === 'long' && s.real_bin === 'long');
  return {n: moved.length, pairs: m, text: `${moved.length} bin moves (REAL bin → preview bin)` + (Object.keys(m).length ? ': ' + Object.entries(m).map(([k, v]) => `${k} ${v}`).join(', ') : '')
    + (moved.length === 0 && allLong ? ` — all ${pref.length} prefixed SKUs are already long` : '')};
}
const R_COLS = () => [C.code, C.name,
  {k:'combined', l:'combined_v1', r: s => `<td>${esc(s.combined)}</td>`},
  ...(V.pv ? [{k:'real_bin', l:'Router bin (real)', r: s => `<td>${esc(s.real_bin)}</td>`}] : []),
  {k:'router_bin', l:V.pv ? 'Router bin (preview)' : 'Router bin', r: s => `<td>${esc(s.router_bin)}</td>`},
  C.method, C.served, ...(V.pv ? [C.change] : []), C.ma3, C.mase, C.ma3_mase, C.wape, C.ma3_wape,
  {k:'status', l:'Status', r: s => `<td>${esc(s.status)}</td>`},
  {k:'backup', l:'MA3 backup', r: s => `<td class="muted">${esc(s.backup)}</td>`},
  {k:'_bo', l:'Backup options', sort:false, r: s => `<td>${backupOptions(s)}</td>`}];
const textMatch = (s, q) => { q = (q || '').trim().toLowerCase(); return !q || String(s.code).toLowerCase().includes(q) || String(s.name).toLowerCase().includes(q); };
const sankeyMatch = s => { if (!filter) return true; const i = filter.indexOf(':'), col = filter.slice(0, i), item = filter.slice(i + 1); return !SKU_KEY[col] || s[SKU_KEY[col]] === item; };

// ================= AUTOCOMPLETE =================
function autocomplete(host, placeholder, onPick){
  host.innerHTML = `<input class="search" placeholder="${esc(placeholder)}" autocomplete="off" role="combobox" aria-expanded="false"><ul role="listbox" hidden></ul>`;
  const inp = host.querySelector('input'), ul = host.querySelector('ul');
  let items = [], idx = 0;
  const paint = () => {
    ul.innerHTML = items.map((s, i) => `<li role="option" data-pk="${s.pk}" aria-selected="${i === idx}"><b>${esc(s.code)}</b><span>${esc(s.name)}</span></li>`).join('');
    ul.hidden = !items.length; inp.setAttribute('aria-expanded', !!items.length);
    ul.querySelectorAll('li').forEach(li => li.onmousedown = e => { e.preventDefault(); pick(+li.dataset.pk); });
  };
  const pick = pk => { const s = V.byPk.get(pk); inp.value = `${s.code} · ${s.name}`; items = []; paint(); onPick(pk); };
  inp.oninput = () => {
    const q = inp.value.trim().toLowerCase(); idx = 0;
    items = q ? V.skus.filter(s => String(s.code).toLowerCase().includes(q) || String(s.name).toLowerCase().includes(q))
      .sort((a, b) => (String(b.code).startsWith(q) - String(a.code).startsWith(q))).slice(0, 12) : [];
    paint();
  };
  inp.onkeydown = e => {
    if (!items.length) return;
    if (e.key === 'ArrowDown'){ idx = (idx + 1) % items.length; paint(); e.preventDefault(); }
    else if (e.key === 'ArrowUp'){ idx = (idx - 1 + items.length) % items.length; paint(); e.preventDefault(); }
    else if (e.key === 'Enter'){ pick(items[idx].pk); e.preventDefault(); }
    else if (e.key === 'Escape'){ items = []; paint(); }
  };
  inp.onblur = () => setTimeout(() => { items = []; paint(); }, 100);
  return {input: inp, clear: () => { inp.value = ''; items = []; paint(); }};
}

// ================= FORECASTS =================
let gBin = 'all', gModel = 'all', gView = 'table', gVerdict = 'all', gCause = 'all';
const fState = {k:'gap', d:-1};
let fSel = null, fOrder = [];
function seg(el, opts, get, set, noRedraw){
  el.innerHTML = opts.map(([v, l, c]) => `<button data-v="${v}" aria-pressed="${get() === v}">${c ? `<i style="background:${c}"></i>` : ''}${esc(l)}</button>`).join('');
  el.querySelectorAll('button').forEach(b => b.onclick = () => { if (get() === b.dataset.v) return; set(b.dataset.v); if (!noRedraw){ seg(el, opts, get, set); drawForecasts(); } });
}
function initSegs(){
  seg($('#binSeg'), [['all', 'All bins'], ...D.router_order.map(b => [b, `${b} · ${V.counts.router[b]}`])], () => gBin, v => gBin = v);
  const vn = v => V.skus.filter(s => s.verdict === v).length;
  seg($('#verdictSeg'), [['all', 'All'], ...F.verdict_order.filter(vn).map(v => [v, `${v} · ${vn(v)}`])], () => gVerdict, v => gVerdict = v);
  const cn = c => V.skus.filter(s => s.cause === c).length;
  seg($('#causeSeg'), [['all', 'All causes'], ...F.cause_order.filter(cn).map(c => {
    const k = causeSplit(V.skus, c);
    return [c, `${c} · ${k.n} (${k.unfit} not fit / ${k.clean} clean)`];
  })], () => gCause, v => gCause = v);
  seg($('#modelSeg'), [['all', 'All models'], ...MODEL_KEYS.map(m => [m, mlabel(m), COLOR[m]])], () => gModel, v => gModel = v);
  seg($('#viewSeg'), [['table', 'Table view'], ['grid', 'Grid view']], () => gView, v => gView = v);
}
const acF = autocomplete($('#acF'), 'Find a SKU by code or product…', pk => { fSel = pk; drawForecasts(); });
// Nine columns answer the usual question; the other fourteen are one click
// away and every one of them stays sortable when shown.
let colsOpen = false;
const F_DEFAULT = () => [C.code, C.name, C.method, C.spark, C.served, C.ma3,
  ...(V.pv ? [C.change] : [C.mase_common, C.verdict]), C.rlr];
const F_MORE = () => [C.gap, ...(V.pv ? [C.ph] : [C.cause, C.assessable]), C.mase,
  ...(V.pv ? [] : [C.mase_pipeline]), C.ma3_mase, C.wape,
  ...(V.pv ? [] : [C.cov, C.bw, C.ma3_cov, C.ma3_bw])];
const F_COLS = () => colsOpen ? [...F_DEFAULT(), ...F_MORE()] : F_DEFAULT();
function drawFocus(){
  const s = V.byPk.get(fSel), i = fOrder.findIndex(x => x.pk === fSel);
  if (!s){ $('#focus').innerHTML = '<div class="empty">Select a SKU.</div>'; return; }
  $('#focus').innerHTML = `<div class="toolbar" style="margin-bottom:6px"><div class="dhead" style="margin:0"><div class="code">${esc(s.code)}</div><div class="nm">${esc(s.name)}</div></div>`
    + `<div class="tags" style="align-self:flex-start;margin-left:12px">${modelPill(s.method)}<span class="pill">router: ${esc(s.router_bin)}</span>${V.pv ? `<span class="pill">real bin: ${esc(s.real_bin)}</span>` : ''}<span class="pill">combined_v1: ${esc(s.combined)}</span><span class="pill">${esc(s.status)}</span></div>`
    + `<div class="focusnav"><span class="muted">${i >= 0 ? `${i + 1} of ${fOrder.length} in filter` : 'outside the current filter'}</span>`
    + `<button class="btn" id="fPrev" ${i <= 0 ? 'disabled' : ''}>← Prev</button><button class="btn" id="fNext" ${i < 0 || i >= fOrder.length - 1 ? 'disabled' : ''}>Next →</button></div></div>`
    + skuNotes(s)
    + verdictBlock(s)
    + topTiles(s)
    + `<div class="focus"><div><div class="chart">${chart(s, 1100, 300, 'big')}</div>${legendBox(s)}</div>`
    + `<div class="backupbox"><b>Backup options${V.pv ? ` · preview bin: ${esc(s.router_bin)}` : ` · ${esc(s.router_bin)} bin`}</b><div class="bo">${backupPanel(s)}</div><div style="margin-top:8px;border-top:1px solid var(--line);padding-top:6px">Live fallback today: MA3. MA3 backup: ${esc(s.backup)}.</div></div></div>`
    + skuSections(s);
  bindSecs('#focus');
  const lg = $('#focus details.legendbox');
  if (lg) lg.ontoggle = () => { openSec.legend = lg.open; };
  if (i > 0) $('#fPrev').onclick = () => { fSel = fOrder[i - 1].pk; drawForecasts(); };
  if (i >= 0 && i < fOrder.length - 1) $('#fNext').onclick = () => { fSel = fOrder[i + 1].pk; drawForecasts(); };
}
function drawForecasts(){
  if (fSel == null) fSel = (sortRows(V.skus.filter(s => s.gap != null), absGap, -1)[0] || V.skus[0]).pk;
  const rows = V.skus.filter(s => (gBin === 'all' || s.router_bin === gBin) && (gModel === 'all' || s.method === gModel)
    && (gVerdict === 'all' || s.verdict === gVerdict) && (gCause === 'all' || s.cause === gCause));
  $('#gcount').textContent = `${rows.length} of ${V.skus.length} SKUs`;
  const cb = $('#colsBtn');
  cb.textContent = colsOpen ? `Columns: all ${F_DEFAULT().length + F_MORE().length}` : `Columns: ${F_DEFAULT().length} of ${F_DEFAULT().length + F_MORE().length}`;
  cb.title = colsOpen ? 'Hide the extra columns' : 'Show every column \u2014 ' + F_MORE().map(c => c.l).join(', ');
  cb.onclick = () => { colsOpen = !colsOpen; drawForecasts(); };
  $('#fTableCard').hidden = gView !== 'table'; $('#grid').hidden = gView !== 'grid';
  const onRow = pk => { fSel = pk; drawForecasts(); };
  const cols = F_COLS();
  if (!cols.find(c => c.k === fState.k)) { fState.k = 'gap'; fState.d = -1; }
  if (gView === 'table') fOrder = renderTable($('#ftbl'), cols, rows, fState, onRow, fSel);
  else {
    fOrder = sortRows(rows, (cols.find(c => c.k === fState.k) || C.gap).v || fState.k, fState.d);
    const nt = '<span class="muted" style="font-weight:400">not testable</span>';
    $('#grid').innerHTML = fOrder.map(s => `<div class="fc${s.pk === fSel ? ' sel' : ''}" data-pk="${s.pk}">`
      + `<div class="top"><div><div class="code">${esc(s.code)}</div><div class="nm" title="${esc(s.name)}">${esc(s.name)}</div></div>${modelPill(s.method)}</div>`
      + `<div class="chart">${chart(s, 300, 110, 'card')}</div>`
      + `<div class="foot"><div>${V.pv ? 'Change vs real' : 'Served'}<b>${V.pv ? pct(s.change) : fmt(s.served, 0)}</b></div>`
      + `<div>MASE<b${!PROV(s) && s.mase >= 1 ? ' style="color:var(--flag-ink)"' : ''}>${PROV(s) ? nt : fmt(s.mase)}</b></div>`
      + `<div>MA3 MASE<b${!PROV(s) && s.ma3_mase >= 1 ? ' style="color:var(--flag-ink)"' : ''}>${PROV(s) ? nt : fmt(s.ma3_mase)}</b></div></div></div>`).join('') || '<div class="empty">No SKUs match.</div>';
    $$('#grid .fc').forEach(c => c.onclick = () => onRow(+c.dataset.pk));
  }
  drawFocus();
}

// ================= PIPELINE =================
const eqMap = (got, exp) => Object.keys(exp).every(k => (got[k] || 0) === exp[k]) && Object.keys(got).every(k => k in exp || !got[k]);
const maseHigh = rows => rows.filter(s => s.mase != null && s.mase >= 1);
const ma3High = rows => rows.filter(s => s.ma3_mase != null && s.ma3_mase >= 1);
const maseLine = rows => { const n = rows.filter(s => s.mase != null).length; return `${maseHigh(rows).length} of ${n} MASE ≥ 1 (MA3: ${ma3High(rows).length} of ${n})`; };
function light(checks){
  if (checks.some(c => c.ok === false)) return 'bad';
  if (checks.some(c => c.warn)) return 'warn';
  if (checks.some(c => c.ok === true)) return 'ok';
  return 'none';
}
let PN = [];
// Lane membership is the database boundary: 'db' = the object lives in Supabase,
// 'out' = Python or a file outside it. Every wire whose two ends sit in different
// lanes is a boundary crossing, and drawPipeline() marks each one.
const NOREC = 'not on record';
function etlNode(id, row, col, lane){
  const e = D.etl[id];
  const cols = e.columns.map((c, i) => ({k:'c' + i, l:c[0], num:c[1], v: r => r[i],
    r: r => `<td class="${c[1] ? 'num' : ''}${String(r[i]) === NOREC ? ' muted' : ''}">${esc(r[i])}</td>`}));
  return {id, row, col, lane, etl:true, title:e.title, sub:e.sub, source:e.source, io:e.io,
          mline:e.mline, checks:e.checks, tag:'reports/', rows: () => e.rows, has: () => true, cols};
}
const vcount = rows => {
  const c = {};
  F.verdict_order.forEach(v => c[v] = rows.filter(s => s.verdict === v).length);
  return c;
};
const causeLine = rows => {
  const fired = F.cause_order.filter(c => rows.some(s => s.cause === c && s.verdict === 'not fit'));
  if (!fired.length) return 'none';
  return fired.map(c => causeTag(rows, c)).join('; ')
    + ' \u2014 the clean counts are there because the same cause fires on SKUs the review passed.';
};
function buildPN(){
  const E = V.expected, S = V.skus, scored = S.filter(s => s.status === 'ok');
  const rowsOut = S.reduce((a, s) => a + s.view_rows, 0);
  const negSkus = S.filter(s => s.neg_months > 0), gapSkus = S.filter(s => s.gap_months > 0);
  const P = V.pv ? D.preview : null;
  const src = V.pv ? 'from preview file' : '';
  const covAll = B.all;
  PN = [
    // ---- row 0: files in, through ETL, across the write boundary, into the DB
    etlNode('raw', 0, 0, 'out'),
    etlNode('extract', 0, 1, 'out'),
    etlNode('transform', 0, 2, 'out'),
    etlNode('load', 0, 3, 'out'),
    etlNode('base', 0, 4, 'db'),
    {id:'real', row:0, col:5, lane:'db',
     title:V.pv ? 'Preview series' : '_Real views', sub:V.pv ? 'series_synth.csv' : 'unilever_sku_demand_fact_real',
     source:V.pv ? 'reports/preview/series_synth.csv (scripts/preview_router_synth.py output)'
                 : 'analytics/db/schema.sql:832-848 (the six CREATE VIEW ... WHERE is_demo = false) · row counts read live by this build',
     io:V.pv ? [`in ${fmt(P.file_rows, 0)} rows`, `${fmt(P.placeholder_rows, 0)} placeholder · ${P.placeholder_skus} SKUs`]
             : [`in ${fmt(D.meta.view_rows, 0)} rows`, `out ${fmt(rowsOut, 0)} Tier A rows`],
     checks:[{ok:null, text:V.pv ? `No expected row count on record (file: ${fmt(P.file_rows, 0)} rows)`
                                 : `No expected row count on record (view: ${fmt(D.meta.view_rows, 0)} rows, ${D.meta.view_skus} SKUs)`},
       ...(V.pv ? [{warn:true, text:`${fmt(P.placeholder_rows, 0)} placeholder rows (2021–22) across ${P.placeholder_skus} SKUs — not SSM data`}]
                : [{ok:null, text:'The views exclude is_demo = true structurally, so a real-vs-synthetic mix-up is a query-target mistake, not a filter a caller can forget. Every model reads these, never the base tables (enforced by tests/forecasting/test_real_view_reads.py).'}]),
       {warn:negSkus.length > 0, text:`${negSkus.length} Tier A SKUs have a negative month`},
       {warn:gapSkus.length > 0, text:`${gapSkus.length} Tier A SKUs have months with no row between their first and last row`}],
     rows:() => S, has:() => true,
     cols:[C.code, C.name, {k:'view_rows', l:V.pv ? 'Rows in file' : 'Rows in view', num:1, r:s => `<td class="num">${s.view_rows}</td>`}, ...(V.pv ? [C.ph] : []),
       {k:'first_i', l:'First row', r:s => `<td>${s.first_i == null ? '—' : V.periods[s.first_i]}</td>`},
       {k:'last_i', l:'Last row', r:s => `<td>${s.last_i == null ? '—' : V.periods[s.last_i]}</td>`},
       {k:'gap_months', l:'Months with no row', num:1, r:s => `<td class="num${s.gap_months ? ' flag' : ''}">${s.gap_months}</td>`},
       {k:'neg_months', l:'Negative months (returns)', num:1, tip:RETSRC,
        r:s => `<td class="num${s.neg_months ? ' flag' : ''}" title="${esc(s.neg_months ? RETURNS : '')}">${s.neg_months}</td>`}, C.spark]},
    // ---- row 1: classification and binning in the DB, models outside it, back in, then out to the API
    {id:'abc', row:1, col:0, lane:'db', title:'ABC Tier A', sub:'abc_classification · 2026-02 · single',
     source:'read live by this build; the 132 expected is Yuan’s 2026-09-22 figure for the live 2026-03 forecast',
     io:[`in ${D.meta.abc_classified} SKUs`, `out ${S.length} Tier A`],
     checks:[{ok:S.length === E.tier_a, text:`Tier A = ${S.length} (expected ${E.tier_a}${V.pv ? ', rows in preview file' : ''})`},
       {ok:null, text:`All tiers: ${Object.entries(D.meta.abc_tiers).map(([k, v]) => `${k}=${v}`).join(', ')}`}],
     rows:() => S, has:() => true,
     cols:[C.code, C.name, {k:'rev', l:'Revenue share 2026-02', num:1, v:s => s.traits && s.traits.revenue_share, r:s => `<td class="num">${fmt(s.traits && s.traits.revenue_share, 5)}</td>`}, C.spark]},
    {id:'combined', row:1, col:1, lane:'db', title:'combined_v1 bins', sub:'sku_segment' + (V.pv ? ' (real, not re-binned)' : ''),
     source:'read live by this build (sku_segment, scheme combined_v1)',
     io:[`in ${S.length}`, `out ${D.combined_order.map(b => V.counts.combined[b]).join('/')}`],
     checks:[{ok:eqMap(V.counts.combined, E.combined), text:`${D.combined_order.map(b => `${b} ${V.counts.combined[b]}`).join(', ')} (expected ${D.combined_order.map(b => E.combined[b]).join('/')})`},
       ...(V.pv ? [{ok:null, text:'combined_v1 is the real sku_segment scheme; the preview does not re-bin it.'}] : [])],
     rows:() => S, has:() => true, sankey:true,
     cols:() => { const r = R_COLS(); return [...r.slice(0, 3), {k:'bin_reason', l:'bin_reason', r:s => `<td class="name" style="max-width:320px" title="${esc(s.bin_reason)}">${binReasonHTML(s)}</td>`}, ...r.slice(3)]; }},
    {id:'router', row:1, col:2, lane:'db', title:V.pv ? 'Router bins (preview)' : 'Router bins (live)', sub:V.pv ? 'router_preview_synth.csv · bin' : 'model_params.bin · length_v2',
     source:V.pv ? 'reports/preview/router_preview_synth.csv' : 'read live by this build (forecast_result.model_params.bin, DEC-26 length_v2)',
     io:[`in ${S.length}`, `out ${D.router_order.map(b => V.counts.router[b]).join('/')}`],
     checks:[{ok:eqMap(V.counts.router, E.router), text:`${D.router_order.map(b => `${b} ${V.counts.router[b]}`).join(', ')} (expected ${D.router_order.map(b => E.router[b]).join('/')}${src ? ' ' + src : ''})`},
       ...(V.pv ? [{ok:null, text:binMoves().text}] : [])],
     rows:() => S, has:() => true, sankey:true,
     cols:() => { const r = R_COLS(); const i = V.pv ? 5 : 4; return [...r.slice(0, i), {k:'sales_months', l:'Sales months', num:1, r:s => `<td class="num">${fmt(s.sales_months, 0)}</td>`}, ...r.slice(i)]; }},
    ...MODEL_KEYS.map((m, i) => {
      const mine = S.filter(s => s.method === m), sc = mine.filter(s => s.mase != null), hi = maseHigh(sc);
      const bin = {ma3:'short', tsb:'medium', xgb_ma3_avg:'long', provisional:'insufficient'}[m];
      const blk = B.by_model[m];
      return {id:'model:' + m, row:1, col:3, mrow:i, lane:'out', model:m, title:mlabel(m), sub:mnote(m),
        source:'analytics/forecasting/router.py LIVE_MODEL (DEC-26); coverage computed by this build (D.band)',
        mline: (() => { const v = vcount(mine); return m === 'provisional' ? null
          : `${v['not fit']} not fit / ${v.borderline} borderline / ${v.clean} clean`; })(),
        io:[`in ${V.counts.router[bin]} (${bin})`, `out ${mine.length}`],
        checks:[{ok:mine.length === E.model[m], text:`${mine.length} SKUs (expected ${E.model[m]}${src ? ' ' + src : ''})`},
          ...(m === 'provisional' ? [{ok:null, text:`No holdout, no band, no coverage, and no fit verdict: under 3 sales months there is nothing to score. All ${mine.length} read "${F.verdict_order[3]}".`}]
            : [(() => { const v = vcount(mine); return {warn:v['not fit'] > 0,
                 text:`Fit review on this bin: ${v['not fit']} not fit / ${v.borderline} borderline / ${v.clean} clean `
                   + `(${bin} bin, ${mine.length} SKUs). Cause groups among the not-fit: ${causeLine(mine)}. `
                   + `The table below lists them - sort or filter on Fit verdict. ${F.no_better_model}`}; })(),
               {ok:null, text:F.cause_note},
               {warn:hi.length > 0, text:maseLine(mine)},
               ...(blk ? [{warn:blk.below > 0, text:`Band coverage on this cohort: median ${pctv(blk.cov)}, `
                   + `${blk.below} of ${blk.scored} below ${LVLL}, median band width / forecast ${fmt(blk.bw)}. `
                   + `MA3 on the same months (computed, no MA3 band is stored): median ${pctv(blk.cov3)}, ${blk.below3} below.`},
                  {ok:null, text:B.granularity}]
                 : [{ok:null, text:'Coverage is not available in preview mode.'}])]),
          ...(V.pv && m === 'xgb_ma3_avg' ? [{ok:null, text:`${LONG_NOTE} ${mine.filter(s => s.change != null && Math.abs(s.change) > 0).length} of ${mine.length} changed.`}] : [])],
        rows:() => mine, has:s => s.method === m, sortDefault:V.pv ? null : {k:'verdict', d:-1},
        cols:[C.code, C.name, ...(V.pv ? [] : [C.verdict, C.cause, C.assessable]), C.served,
          ...(V.pv ? [C.change] : []), C.ma3, C.gap, C.mase, ...(V.pv ? [] : [C.mase_common, C.mase_pipeline]),
          C.ma3_mase, C.wape, ...(V.pv ? [] : [C.cov, C.bw, C.ma3_cov, C.ma3_bw])]};
    }),
    {id:'holdout', row:1, col:4, lane:'out', title:'Holdout evaluation', sub:V.pv ? 'as given in the preview file' : 'rolling one-step, served model',
     source:'DEC-25 (ARCHITECTURE.md:95); metrics read live from model_params.holdout_metrics_served, coverage computed by this build',
     io:[`in ${scored.length} routed`, `out ${scored.filter(s => s.mase != null).length} scored`],
     checks:[{ok:scored.length === E.router.short + E.router.medium + E.router.long, text:`${scored.length} routed SKUs (expected ${E.router.short + E.router.medium + E.router.long} = short + medium + long)`},
       {ok:scored.every(s => s.mase != null), text:`${scored.filter(s => s.mase == null).length} routed SKUs without a MASE`},
       {warn:maseHigh(scored).length > 0, text:maseLine(scored)},
       (() => { const v = vcount(scored); return {warn:v['not fit'] > 0,
          text:`Fit review across all scored SKUs: ${v['not fit']} not fit / ${v.borderline} borderline / `
            + `${v.clean} clean. Cause groups among the not-fit: ${causeLine(scored)}.`}; })(),
       ...(V.pv ? [{ok:null, text:'Coverage is not available in preview mode — the preview file holds no per-month path.'}]
         : [{ok:B.agree.mase === B.agree.n && B.agree.wape === B.agree.n && B.agree.rmse === B.agree.n && B.agree.months === B.agree.n,
             text:`Recomputed holdout path agrees with what was stored: MASE ${B.agree.mase}/${B.agree.n}, WAPE ${B.agree.wape}/${B.agree.n}, `
               + `RMSE ${B.agree.rmse}/${B.agree.n}, holdout months ${B.agree.months}/${B.agree.n}. The corridor is only the served model’s if these match.`},
            {warn:covAll.below > 0, text:`Coverage across all ${covAll.scored} scored SKUs: median ${pctv(covAll.cov)}, `
               + `${covAll.below} below ${LVLL}, median band width / forecast ${fmt(covAll.bw)}.`},
            {ok:null, text:B.granularity}])],
     rows:() => scored, has:s => s.status === 'ok',
     cols:[C.code, C.name, C.method, {k:'holdout_months', l:'Holdout months', num:1, r:s => `<td class="num">${fmt(s.holdout_months, 0)}</td>`}, C.mase,
       C.ma3_mase, C.wape, C.ma3_wape, ...(V.pv ? [] : [C.verdict, C.cause, C.mase_common, C.mase_pipeline, C.cov, C.bw, C.ma3_cov, C.ma3_bw])]},
    {id:'fr', row:1, col:5, lane:'db', title:V.pv ? 'Preview forecasts' : 'forecast_result', sub:V.pv ? 'router_preview_synth.csv (not Forecast_Result)' : `forecast_date ${D.meta.forecast_date}`,
     source:V.pv ? 'reports/preview/router_preview_synth.csv' : 'read live by this build; band definition DEC-25 + scripts/run_baseline_forecast.py:821-840',
     io:[`in ${S.length}`, `out ${S.filter(s => s.status).length} rows`],
     checks:[{ok:S.filter(s => s.status).length === E.forecast_result, text:`${S.filter(s => s.status).length} rows (expected ${E.forecast_result}${src ? ' ' + src : ''})`},
       {ok:eqMap(V.counts.backup, E.backup), text:`MA3 backup: ${D.backup_order.map(b => `${b} ${V.counts.backup[b]}`).join(', ')} (expected ${D.backup_order.map(b => E.backup[b]).join('/')}${src ? ' ' + src : ''})`},
       {ok:null, text:`Band stored here, one per SKU: ${B.interval} σ = ${B.sigma}`},
       {warn:true, text:`Level: ${B.level}`},
       {ok:null, text:`${S.filter(s => s.lo != null).length} of ${S.length} rows carry a band; the rest are the ${V.counts.model.provisional} provisional SKUs (no holdout RMSE, so NULL/NULL, never a fabricated band).`}],
     rows:() => S, has:() => true,
     cols:[C.code, C.name, {k:'status', l:'Status', r:s => `<td>${esc(s.status)}</td>`}, C.method, C.served, ...(V.pv ? [C.change] : []),
       {k:'lo', l:'Band low', num:1, r:s => `<td class="num">${fmt(s.lo)}</td>`}, {k:'hi', l:'Band high', num:1, r:s => `<td class="num">${fmt(s.hi)}</td>`},
       ...(V.pv ? [] : [{k:'rmse', l:'Holdout RMSE (σ)', num:1, r:s => `<td class="num">${fmt(s.rmse)}</td>`}, C.bw, C.cov]),
       {k:'backup', l:'MA3 backup', r:s => `<td class="muted">${esc(s.backup)}</td>`}, {k:'_bo', l:'Backup options', sort:false, r:s => `<td>${backupOptions(s)}</td>`}],
    },
    etlNode('api', 1, 6, 'out'),
  ];
  PN.forEach(n => n.light = light(n.checks));
}
const LAMP = {ok:'var(--ok)', warn:'var(--warn)', bad:'var(--bad)', none:'var(--none)'};
let pSel = 'raw', pSku = null;
const pStates = {};
function drawSummary(){
  const el = $('#pvSummary');
  el.hidden = !V.pv;
  if (!V.pv) return;
  const P = D.preview, bins = [...new Set(P.blocks.map(b => b.bin))];
  const bv = (arm, bin) => (P.blocks.find(b => b.arm === arm && b.bin === bin) || {}).value;
  const rb = [...new Set(P.moves.map(m => m.real))], sb = [...new Set(P.moves.map(m => m.synth))];
  const mv = (r, s) => (P.moves.find(m => m.real === r && m.synth === s) || {}).n;
  const bm = binMoves();
  el.innerHTML = `<h2>Preview summary</h2><div class="sub">From preview_summary.csv. Placeholder-backed numbers show what more history would change; they are not accuracy evidence.</div>`
    + `<div class="pvgrid"><div><b style="font-size:12px">Testable blocks per bin</b><table class="mini"><tr><th class="l">bin</th><th>REAL</th><th>Preview</th></tr>`
    + bins.map(b => `<tr><td class="l">${esc(b)}</td><td>${bv('REAL', b)}</td><td>${bv('SYNTH', b)}</td></tr>`).join('') + `</table>`
    + `<div class="muted" style="font-size:12px">REAL ${bins.map(b => bv('REAL', b)).join('/')} vs preview ${bins.map(b => bv('SYNTH', b)).join('/')}</div></div>`
    + `<div><b style="font-size:12px">Test-month bin moves (rows = REAL bin, columns = preview bin)</b><table class="mini"><tr><th class="l">REAL \\ preview</th>${sb.map(b => `<th>${esc(b)}</th>`).join('')}</tr>`
    + rb.map(r => `<tr><td class="l">${esc(r)}</td>${sb.map(s => `<td${r !== s && mv(r, s) ? ' style="color:var(--ph);font-weight:600"' : ''}>${fmt(mv(r, s), 0)}</td>`).join('')}</tr>`).join('') + `</table></div>`
    + `<div><b style="font-size:12px">At ${esc(fcMonth)} (the served forecast)</b><div class="pvnote">${esc(bm.text)}.</div><div class="pvnote">${esc(LONG_NOTE)}</div></div></div>`;
}
function drawPipeline(){
  drawSummary();
  // Geometry: two rows, and within each row two lanes. The lower lane is inside
  // Supabase and gets a dashed frame; the upper lane is Python or files. A wire
  // between lanes is a database boundary crossing and gets a marker.
  const W = 1340, nw = 170, nh = 86, pad = 16;
  const step = (W - nw - 2 * pad) / 6, cx = c => pad + c * step;
  const MODELS = PN.filter(n => n.model);
  const mh = MODELS.length * (nh + 18) - 18;
  const Y = {r0out:52, r0db:52 + nh + 84, r1out:0, r1db:0};
  Y.r1out = Y.r0db + nh + 116;
  Y.r1db = Y.r1out + mh + 96;
  const H = Y.r1db + nh + 46;
  const wrapY = Y.r0db + nh + 36;                        // the row-0 -> row-1 hand-off
  const pos = {};
  PN.forEach(n => {
    const y = n.lane === 'db' ? (n.row ? Y.r1db : Y.r0db)
      : n.row === 0 ? Y.r0out
      : n.model ? Y.r1out + n.mrow * (nh + 18) : Y.r1out + (mh - nh) / 2;
    pos[n.id] = {x:cx(n.col), y, lane:n.lane, row:n.row};
  });
  const sku = pSku && V.byPk.get(pSku);
  const onPath = n => sku && n.has(sku);
  const at = id => PN.find(n => n.id === id);
  const prov = MODELS.find(n => n.model === 'provisional');
  const EDGES = [
    ['raw', 'extract'], ['extract', 'transform'], ['transform', 'load'],
    ['load', 'base', {xing:'①', label:'data ENTERS Supabase'}],
    ['base', 'real'],
    ['real', 'abc', {wrap:true}],
    ['abc', 'combined'], ['combined', 'router'],
    ...MODELS.map(m => ['router', m.id, {xing:'', label:'read'}]),
    ...MODELS.filter(m => m.model !== 'provisional').map(m => [m.id, 'holdout']),
    ['holdout', 'fr', {xing:'', label:'write'}],
    ...(prov ? [[prov.id, 'fr', {xing:'', label:'write'}]] : []),
    ['fr', 'api', {xing:'②', label:'data LEAVES Supabase'}],
  ];
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Pipeline node graph: raw files through ETL into Supabase, out to the models, back in, and out to the dashboard API">`;

  // the Supabase frames: one per contiguous run of db-lane nodes in a row
  [0, 1].forEach(row => {
    const cols = PN.filter(n => n.lane === 'db' && n.row === row).map(n => n.col).sort((a, b) => a - b);
    let run = [];
    const flush = () => {
      if (!run.length) return;
      const x0 = cx(run[0]) - 15, x1 = cx(run[run.length - 1]) + nw + 15;
      const y0 = (row ? Y.r1db : Y.r0db) - 52;
      s += `<rect class="dbframe" x="${x0}" y="${y0}" width="${x1 - x0}" height="${nh + 72}" rx="12"/>`
        + `<text class="dbframe-l" x="${x1 - 12}" y="${y0 + 17}" text-anchor="end">SUPABASE · POSTGRES — INSIDE THE DATABASE</text>`;
      run = [];
    };
    cols.forEach((c, i) => { if (i && c !== cols[i - 1] + 1) flush(); run.push(c); });
    flush();
    const yo = row ? Y.r1out : Y.r0out;
    s += `<text class="lane-l" x="${pad}" y="${yo - 30}">OUTSIDE THE DATABASE — PYTHON / FILES</text>`;
  });

  const marks = [];
  EDGES.forEach(([a, b, o]) => {
    const A = pos[a], Bp = pos[b], na = at(a), nb = at(b);
    if (!A || !Bp) return;
    const lit = sku && onPath(na) && onPath(nb) ? ' path' : '';
    if (o && o.wrap){
      // row 0 -> row 1: down out of the DB frame, left above the model fan, down again
      const x1 = A.x + nw / 2, x2 = Bp.x + nw / 2;
      s += `<path class="wire wrap${lit}" d="M${x1},${A.y + nh + 18} V${wrapY} H${x2} V${Bp.y - 1}"/>`
        + `<path d="M${x2 - 5},${Bp.y - 9} l5,8 l5,-8z" fill="var(--accent)" opacity=".7"/>`
        + `<text class="lane-l" x="${x2 + 14}" y="${wrapY - 6}" style="fill:var(--accent)">same database, next stage</text>`;
      return;
    }
    const x1 = A.x + nw + 5, y1 = A.y + nh / 2, x2 = Bp.x - 5, y2 = Bp.y + nh / 2, mx = (x1 + x2) / 2;
    const cross = A.lane !== Bp.lane;
    s += `<path class="wire${cross ? ' cross' : ''}${lit}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
    // One marker per crossing, not per wire: router -> the four model nodes is a
    // single read across the boundary, and stacking four pills on one another
    // just hid the nodes underneath.
    if (cross && o){
      const key = `${a}|${o.xing || o.label}`;
      const seen = marks.find(k => k.key === key);
      if (seen){ seen.xs.push((x1 + x2) / 2); seen.ys.push((y1 + y2) / 2); }
      else marks.push({key, xs:[(x1 + x2) / 2], ys:[(y1 + y2) / 2], ...o});
    }
  });

  PN.forEach(n => {
    const {x, y} = pos[n.id];
    const cls = ['kn', pSel === n.id ? 'sel' : '', sku ? (onPath(n) ? 'path' : 'dim') : ''].join(' ');
    const trunc = (t, k) => t.length > k ? t.slice(0, k - 1) + '…' : t;
    s += `<g class="${cls}" data-id="${esc(n.id)}" tabindex="0">`
      + `<text class="t" x="${x + nw / 2}" y="${y - 8}" text-anchor="middle">${esc(n.title)}</text>`
      + `<rect class="body" x="${x}" y="${y}" width="${nw}" height="${nh}" rx="8"/>`
      + `<rect x="${x}" y="${y}" width="${nw}" height="5" rx="2" fill="${n.model ? COLOR[n.model] : n.etl ? 'var(--ink-3)' : V.pv ? 'var(--ph)' : 'var(--accent)'}" opacity=".85"/>`
      + `<path d="M${x - 6},${y + nh / 2 - 5} l6,5 l-6,5z" fill="var(--ink-3)"/><path d="M${x + nw},${y + nh / 2 - 5} l6,5 l-6,5z" fill="var(--ink-3)"/>`
      + `<text class="st" x="${x + 10}" y="${y + 22}">${esc(trunc(n.sub, 28))}</text>`
      + `<text class="io" x="${x + 10}" y="${y + 40}">${esc(trunc(n.io[0], 23))}</text>`
      + `<text class="io" x="${x + 10}" y="${y + 56}">${esc(trunc(n.io[1], 23))}</text>`
      + (n.mline ? `<text class="io" x="${x + 10}" y="${y + 72}" style="fill:var(--ink-2);font-size:10.5px">${esc(trunc(n.mline, 26))}</text>` : '')

      + `<circle cx="${x + nw / 2}" cy="${y + nh + 12}" r="6" fill="${LAMP[n.light]}" stroke="var(--surface-1)" stroke-width="2"><title>${esc(n.light)}</title></circle>`
      + `<title>${esc(n.title)}: ${esc(n.io.join(' → '))}</title></g>`;
  });

  // boundary markers last, so they sit above the wires
  const mean = arr => arr.reduce((x, y) => x + y, 0) / arr.length;
  marks.forEach(k => {
    const x = mean(k.xs), y = mean(k.ys);
    s += `<g class="xing">`
      + (k.xing ? `<circle cx="${x}" cy="${y}" r="12"/><text x="${x}" y="${y + 4}">${k.xing}</text>`
                  + `<rect x="${x - 86}" y="${y - 40}" width="172" height="20" rx="10" fill="var(--bg)" stroke="var(--accent)" stroke-width="1.2"/>`
                  + `<text class="w" x="${x}" y="${y - 26}">${esc(k.xing + '  ' + k.label)}</text>`
                : `<rect x="${x - 50}" y="${y - 9}" width="44" height="18" rx="9" fill="var(--bg)" stroke="var(--accent)" stroke-width="1.2"/>`
                  + `<text class="w" x="${x - 28}" y="${y + 4}">${esc(k.label.toUpperCase())}</text>`)
      + `</g>`;
  });
  $('#pSvg').innerHTML = s + '</svg>';
  $$('#pSvg .kn').forEach(g => g.onclick = () => { pSel = g.dataset.id; drawPipeline(); });
  drawPanel(); drawDock();
}
function drawPanel(){
  const n = PN.find(x => x.id === pSel);
  const st = pStates[n.id] || (pStates[n.id] = n.sortDefault ? {...n.sortDefault} : {k:n.etl ? 'c0' : 'code', d:1});
  const cols = typeof n.cols === 'function' ? n.cols() : n.cols;
  if (!cols.find(c => c.k === st.k)) { st.k = cols[0].k; st.d = 1; }
  $('#pPanel').innerHTML = `<div class="pnode"><i class="lamp" style="background:${LAMP[n.light]}"></i><h3>${esc(n.title)}</h3>`
    + `<span class="pill">${n.lane === 'db' ? 'inside Supabase' : 'outside the database'}</span>`
    + `<span class="muted">${esc(n.sub)} · ${esc(n.io.join(' → '))}</span><span class="count" id="pcount"></span></div>`
    + (n.source ? `<div class="srcline"><b>${n.etl ? 'Numbers from' : 'Source'}:</b> ${esc(n.source)}</div>` : '')
    + `<ul class="checks">${n.checks.map(c => `<li>${c.ok === false ? '✗ ' : c.warn ? '⚠ ' : c.ok ? '✓ ' : ''}${esc(c.text)}</li>`).join('')}</ul>`
    + (n.sankey ? `<div style="color:var(--ink-3);font-size:12px;margin-bottom:6px">Tier A → combined_v1 bin → ${V.pv ? 'router bin (real) → router bin (preview)' : 'live router bin'} → served model → MA3 backup. Click a node to filter the table below.</div>`
      + (V.pv ? `<div class="pvnote" id="moveNote">${esc(binMoves().text)}</div>` : '')
      + `<div id="flowSvg" class="flowSvg" style="margin-bottom:12px;max-width:1000px"></div>`
      + `<div class="toolbar"><input class="search" id="q" placeholder="Search SKU code or product"><button class="btn" id="clr">Clear filter</button></div>` : '')
    + `<div class="tw" style="max-height:420px"><table id="ptbl"><thead></thead><tbody></tbody></table></div>`;
  const draw = () => {
    const rows = n.sankey ? n.rows().filter(s => sankeyMatch(s) && textMatch(s, $('#q').value)) : n.rows();
    // ETL rows are rows of a report, not SKUs - nothing to select from them.
    renderTable($('#ptbl'), cols, rows, st, n.etl ? null : pk => selectPipelineSku(pk), pSku);
    $('#pcount').textContent = `${rows.length} of ${n.rows().length} rows` + (n.sankey && filter ? ` · ${filter.replace(':', ' = ')}` : '');
  };
  if (n.sankey){
    drawFlow();
    $('#q').oninput = draw;
    $('#clr').onclick = () => { filter = null; $('#q').value = ''; drawPanel(); };
  }
  draw();
}
function drawDock(){
  const s = pSku && V.byPk.get(pSku);
  $('#pDock').hidden = !s;
  $('#pgrid').style.gridTemplateColumns = s ? '' : '1fr';
  if (s){ $('#pDock').innerHTML = detailHTML(s, 420); bindSecs('#pDock'); }
}
const acP = autocomplete($('#acP'), 'Find a SKU to trace its path…', pk => selectPipelineSku(pk));
function selectPipelineSku(pk){ pSku = pk; drawPipeline(); }
$('#pclr').onclick = () => { pSku = null; acP.clear(); drawPipeline(); };

setMode('real');
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
