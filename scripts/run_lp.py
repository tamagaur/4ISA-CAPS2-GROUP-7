"""
scripts.run_lp — Phase 5: Run safety stock / ROP / LP replenishment
optimization for Category A products and save to LP_Recommendation.

Mirrors scripts/run_sarima.py's structure (argparse -> load_dotenv ->
psycopg2 connect -> one fetch query -> a per-item loop with an immediate
upsert -> a closing summary) — see that file for the pattern this one
follows. Difference in shape: SARIMA fits ONE SKU at a time independently;
this LP is a single shared optimization PER PLANNING CYCLE (build_lp_model
takes the whole SKU list for that cycle at once, per analytics/optimization/
lp.py's own design — the constraints are portfolio-wide, not per-SKU), so
the outer loop here is over planning cycles, not over SKUs.

Candidate pool (task spec): Category A products (latest ABC_Classification
classification_period) with a Forecast_Result row at the latest
forecast_date where status='ok' AND mape < MAPE_GATE. The
latest-classification_period join is REQUIRED, not optional — ABC_
Classification keeps one row per (product, classification_period), so
joining on product_key alone fans a single Forecast_Result row out across
every historical period that product was ever tier A in (confirmed
empirically while building this script: an unfiltered join produced 80+
duplicate rows for a single product_key). Forecast_Result.forecast_date
is confirmed (scripts/run_sarima.py) to differ per product — each SKU's
own latest actual period + 1 month, not one shared date for the whole
run — so "the latest forecast_date" below means the single global
MAX(forecast_date) across the table, matching backend/routers/dashboard.py's
portfolio_forecast gating, not a per-product latest.

THREE inputs this LP needs have NO real data source anywhere in the schema
or Product_Dimension as of this writing — confirmed against a live query,
not assumed. Silently defaulting any of them would fabricate a number and
attribute it to SSM/Unilever/Del Monte. All three are REQUIRED CLI
arguments with NO default value (argparse errors out with no run at all if
one is missing) and are printed loudly at startup so a reader of this
script's output can never mistake them for a figure that came from real
data:

  1. Supplier ceiling A_i (--supplier-ceiling PRINCIPAL=VALUE, repeatable).
     No allocation table exists anywhere in analytics/db/schema.sql — see
     backend/routers/dashboard.py's kpis.fixed_point_ratio, which is
     permanently null for the exact same reason.
  2. Warehouse capacity (--warehouse-capacity). No warehouse-capacity
     table or config value exists anywhere either — this is SSM's own
     physical constraint, which whoever runs this script is expected to
     supply as a known operational fact, not a figure this script could
     look up.
  3. Storage cost per unit (--storage-cost-per-unit). No storage-cost
     column exists on any table.

A FOURTH gap, found while building this script rather than specified up
front, gets the same treatment: Product_Dimension.unit_price (the only
per-unit price column that exists anywhere) is confirmed 0/17,536
populated on the live database — SKU Management has never been used to
fill it in. build_lp_model()'s SKUInput requires a
procurement_cost_per_unit per product, so this script reads unit_price
where it exists (future-proofing — SKU Management could populate it any
time) and otherwise requires --default-procurement-cost-per-unit (also no
default) as an explicit, logged fallback. The summary at the end reports
how many products used the real column vs. the operator-supplied fallback,
so that split is never hidden.

Per planning cycle (one LP solve per distinct forecast_date present in the
gated pool — see above): if solve_lp() returns None (INFEASIBLE), this
script does NOT retry with a relaxed constraint. It computes and logs
exactly which bound was violated (sum(ROP_i) vs. warehouse_capacity, and
per-principal sum(ROP_i) vs. that principal's ceiling — provably the only
two ways this particular LP shape can be infeasible, since Q_i's only
lower bound is ROP_i itself, which is always individually satisfiable) and
writes nothing for that cycle.
"""
from __future__ import annotations

import argparse
import logging
import math
import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.etl.granularity import business_days_in_month, resolve_delmonte_category_grain, resolve_unilever_sku_grain
from analytics.optimization.lp import SKUInput, build_lp_model, compute_rop, compute_safety_stock, solve_lp

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MAPE_GATE = 20.0  # percent — task spec: "mape < 20", same scale/threshold backend/routers/dashboard.py uses.
LOUD_RULE = "=" * 78


def _parse_ceiling(raw: str) -> tuple[str, float]:
    """'unilever=50000' -> ('unilever', 50000.0). Raises via argparse.ArgumentTypeError
    on anything else — a malformed --supplier-ceiling should stop the run,
    not be silently skipped."""
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"--supplier-ceiling must be 'PRINCIPAL=VALUE', got {raw!r}")
    principal, _, value = raw.partition("=")
    principal = principal.strip().lower()
    if principal not in ("unilever", "delmonte"):
        raise argparse.ArgumentTypeError(f"--supplier-ceiling principal must be 'unilever' or 'delmonte', got {principal!r}")
    try:
        return principal, float(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--supplier-ceiling value must be numeric: {raw!r}") from e


def _sigma_d_for_product(demand_df: pd.DataFrame, principal: str) -> tuple[float | None, str | None]:
    """Reconstructs this product's demand series via analytics.etl.granularity
    (per DEC-03: Unilever real SKU-grain passthrough+validate, Del Monte
    category-grain even business-day distribution) and returns
    (sigma_d, None) or (None, reason) if it cannot be honestly computed.

    Del Monte: resolve_delmonte_category_grain() genuinely produces one row
    per business day, so its std is a real per-day figure — with a caveat
    (documented, not hidden): even distribution makes every day WITHIN a
    month identical, so all of this sigma's variance comes from month-to-
    month differences in the monthly total, not real day-to-day demand
    swings. It is a real number, just not a richer daily signal than the
    source data actually contains.

    Unilever: resolve_unilever_sku_grain() is confirmed (its own docstring)
    to NOT disaggregate — Unilever's only real demand source is monthly.
    There is no real daily Unilever series to take a std of. Rather than
    either (a) feeding compute_safety_stock() a monthly-scale sigma
    mislabeled as daily — which would overstate SS_i, since monthly
    variance is numerically much larger than daily — or (b) refusing to
    compute Unilever safety stock at all, this applies the standard i.i.d.
    scaling identity Var(monthly) = n * Var(daily) => sigma_daily =
    sigma_monthly / sqrt(avg business days per month). This is a disclosed
    STATISTICAL TRANSFORMATION of real, measured data (the same kind of
    documented-assumption move granularity.business_days_in_month() itself
    makes for "business day" = weekday), not a fabricated number — but it
    IS an assumption, so it is logged per-product, not silently applied.
    """
    if principal == "delmonte":
        monthly_df = demand_df.rename(columns={"period": "_period", "total_quantity": "quantity"})[["_period", "quantity"]]
        if len(monthly_df) < 2:
            return None, f"insufficient demand history ({len(monthly_df)} period(s), need >= 2)"
        daily_df, validation = resolve_delmonte_category_grain(monthly_df, amount_col="quantity")
        if daily_df.empty:
            return None, "granularity reconstruction produced no daily rows"
        if not validation.ok:
            logger.warning(f"    granularity validation flagged gaps/mismatch for this product: {validation.date_gaps[:3]}{'...' if len(validation.date_gaps) > 3 else ''}, total_mismatch={validation.total_mismatch}")
        sigma = float(daily_df["quantity"].std(ddof=1))
        return sigma, None

    if principal == "unilever":
        sku_daily_df = demand_df.rename(columns={"period": "calendar_month", "total_quantity": "quantity_sold"})
        sku_daily_df = sku_daily_df[["sku_code", "calendar_month", "quantity_sold"]]
        if len(sku_daily_df) < 2:
            return None, f"insufficient demand history ({len(sku_daily_df)} period(s), need >= 2)"
        passthrough_df, validation = resolve_unilever_sku_grain(sku_daily_df)
        if not validation.ok:
            logger.warning(f"    Unilever continuity check flagged gaps for this product: {validation.date_gaps[:3]}{'...' if len(validation.date_gaps) > 3 else ''}")
        sigma_monthly = float(passthrough_df["quantity_sold"].std(ddof=1))
        avg_bdays = sum(len(business_days_in_month(p)) for p in passthrough_df["calendar_month"].unique()) / passthrough_df["calendar_month"].nunique()
        if avg_bdays <= 0:
            return None, "could not compute an average business-day count for this product's periods"
        sigma_d = sigma_monthly / math.sqrt(avg_bdays)
        logger.info(f"    sigma_d derived from monthly sigma {sigma_monthly:.3f} / sqrt({avg_bdays:.1f} avg business days) = {sigma_d:.3f} (no real daily Unilever series exists — see module docstring)")
        return sigma_d, None

    return None, f"unknown principal {principal!r}"


def _diagnose_infeasibility(skus: list[SKUInput], warehouse_capacity: float, supplier_ceilings: dict[str, float]) -> list[str]:
    """This LP's only lower bound on Q_i is ROP_i itself (always
    individually satisfiable), so it is infeasible if and only if some
    aggregate constraint's own bound is smaller than the sum of ROP_i it
    covers. That makes this an exact diagnosis, not a guess."""
    reasons = []
    total_rop = sum(s.rop for s in skus)
    if total_rop > warehouse_capacity:
        reasons.append(f"warehouse_capacity ({warehouse_capacity:,.2f}) < sum(ROP_i) across all SKUs ({total_rop:,.2f})")
    by_principal: dict[str, float] = {}
    for s in skus:
        by_principal[s.principal] = by_principal.get(s.principal, 0.0) + s.rop
    for principal, rop_sum in by_principal.items():
        ceiling = supplier_ceilings.get(principal)
        if ceiling is not None and rop_sum > ceiling:
            reasons.append(f"supplier_ceiling[{principal}] ({ceiling:,.2f}) < sum(ROP_i) for {principal} ({rop_sum:,.2f})")
    return reasons or ["no bound identified — unexpected; check build_lp_model's constraints directly"]


def main():
    parser = argparse.ArgumentParser(
        description="Run safety stock / ROP / LP replenishment optimization for gated Category A products.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--supplier-ceiling", action="append", type=_parse_ceiling, dest="supplier_ceilings", required=True,
        metavar="PRINCIPAL=VALUE",
        help="Supplier ceiling A_i for one principal, e.g. 'unilever=50000'. Repeatable. "
             "REQUIRED, no default — no allocation table exists anywhere in the schema, "
             "so this number can only come from whoever runs this script, never from SSM data.",
    )
    parser.add_argument(
        "--warehouse-capacity", type=float, required=True,
        help="Total warehouse capacity across all SKUs this cycle. REQUIRED, no default — "
             "no warehouse-capacity source exists in the schema either.",
    )
    parser.add_argument(
        "--storage-cost-per-unit", type=float, required=True,
        help="Flat storage cost per unit, applied to every SKU. REQUIRED, no default — "
             "no storage-cost column exists on any table.",
    )
    parser.add_argument(
        "--default-procurement-cost-per-unit", type=float, required=True,
        help="Fallback procurement cost per unit for products where Product_Dimension.unit_price "
             "is NULL (currently 0/17,536 populated on the live database, i.e. this fallback is "
             "used for practically everything today). REQUIRED, no default. Real unit_price is "
             "used instead wherever it is actually populated.",
    )
    parser.add_argument(
        "--principal", choices=["both", "unilever", "delmonte"], default="both",
        help="Scope this run to one principal, filtered in Python after the gating query, "
             "same convention as scripts/run_sarima.py's --principal.",
    )
    args = parser.parse_args()

    supplier_ceilings = dict(args.supplier_ceilings)  # last one wins if a principal is repeated

    logger.warning(LOUD_RULE)
    logger.warning("OPERATOR-SUPPLIED INPUTS — NONE OF THE FOLLOWING COME FROM SSM, UNILEVER, OR")
    logger.warning("DEL MONTE DATA. They exist because analytics/optimization/lp.py's LP requires")
    logger.warning("them and no real source for any of them exists anywhere in this schema.")
    for principal, value in supplier_ceilings.items():
        logger.warning(f"  supplier_ceiling[{principal}]              = {value:,.2f} units")
    logger.warning(f"  warehouse_capacity                       = {args.warehouse_capacity:,.2f} units")
    logger.warning(f"  storage_cost_per_unit                    = {args.storage_cost_per_unit:,.4f} per unit")
    logger.warning(f"  default_procurement_cost_per_unit (fallback only) = {args.default_procurement_cost_per_unit:,.4f} per unit")
    logger.warning(LOUD_RULE)

    load_dotenv(override=False)
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.error("SUPABASE_DB_URL not set in .env")
        return

    conn = psycopg2.connect(db_url)
    conn.autocommit = True  # each cycle's upserts commit immediately, mirrors run_sarima.py's save_result
    cur = conn.cursor()

    UPSERT_QUERY = """
        INSERT INTO LP_Recommendation
        (product_key, planning_cycle_date, q_i, rop_i, ss_i, status)
        VALUES (%s, %s, %s, %s, %s, 'pending')
        ON CONFLICT (product_key, planning_cycle_date)
        DO UPDATE SET
            q_i = EXCLUDED.q_i,
            rop_i = EXCLUDED.rop_i,
            ss_i = EXCLUDED.ss_i,
            status = 'pending'
    """

    def save_result(product_key, planning_cycle_date, q_i, rop_i, ss_i):
        cur.execute(UPSERT_QUERY, (int(product_key), planning_cycle_date, float(q_i), float(rop_i), float(ss_i)))

    # ---- Step A: gated candidate pool -----------------------------------
    # Category A (latest classification_period) with a Forecast_Result row
    # at the latest forecast_date, status='ok', mape < MAPE_GATE. Both
    # "latest" joins are load-bearing — see module docstring's fan-out note.
    logger.info("Fetching gated Category A candidate pool...")
    cur.execute(
        """
        WITH latest_forecast AS (SELECT MAX(forecast_date) AS d FROM Forecast_Result),
             latest_abc AS (SELECT MAX(classification_period) AS p FROM ABC_Classification)
        SELECT pd.product_key, COALESCE(pd.sku_code, pd.category_path) AS sku_id, pd.principal,
               pd.unit_price, fr.forecast_date, fr.forecast_value, fr.mape
        FROM Forecast_Result fr
        JOIN Product_Dimension pd ON pd.product_key = fr.product_key
        JOIN ABC_Classification ac ON ac.product_key = fr.product_key
        JOIN latest_forecast lf ON fr.forecast_date = lf.d
        JOIN latest_abc la ON ac.classification_period = la.p
        WHERE fr.status = 'ok' AND fr.mape < %s
        """,
        (MAPE_GATE,),
    )
    candidates = cur.fetchall()
    columns = ["product_key", "sku_id", "principal", "unit_price", "forecast_date", "forecast_value", "mape"]
    candidates_df = pd.DataFrame(candidates, columns=columns)

    considered = len(candidates_df)
    logger.info(f"{considered} product(s) considered (Category A, status='ok', mape < {MAPE_GATE}, at the latest forecast_date).")

    if args.principal != "both":
        before = len(candidates_df)
        candidates_df = candidates_df[candidates_df["principal"] == args.principal]
        logger.info(f"--principal={args.principal}: scoped from {before} to {len(candidates_df)} product(s).")

    if candidates_df.empty:
        logger.warning("No candidates after gating. Nothing to do.")
        conn.close()
        return

    # ---- Step B: historical demand for the candidate pool, for sigma_d --
    product_keys = [int(k) for k in candidates_df["product_key"].unique()]
    cur.execute(
        """
        SELECT pd.product_key, pd.sku_code, pd.principal, d.period, SUM(d.quantity) AS total_quantity
        FROM (
            SELECT sf.product_key, sf._period AS period, sf.quantity
            FROM SellOut_Fact_Real sf
            JOIN Product_Dimension p ON sf.product_key = p.product_key
            WHERE p.principal = 'delmonte'

            UNION ALL

            SELECT product_key, calendar_month AS period, quantity_sold AS quantity
            FROM Unilever_SKU_Demand_Fact_Real
        ) d
        JOIN Product_Dimension pd ON d.product_key = pd.product_key
        WHERE pd.product_key = ANY(%s)
        GROUP BY pd.product_key, pd.sku_code, pd.principal, d.period
        ORDER BY pd.product_key, d.period ASC
        """,
        (product_keys,),
    )
    demand_rows = cur.fetchall()
    demand_df = pd.DataFrame(demand_rows, columns=["product_key", "sku_code", "principal", "period", "total_quantity"])
    demand_df["total_quantity"] = pd.to_numeric(demand_df["total_quantity"], errors="coerce").fillna(0)

    # ---- Step C: per-product gating (unit_price fallback, sigma_d) -----
    gated_out: dict[str, int] = {}
    real_unit_price_count = 0
    fallback_unit_price_count = 0
    sku_inputs_by_cycle: dict = {}  # planning_cycle_date -> list[SKUInput]
    lookup: dict[str, dict] = {}  # sku_id -> {product_key, planning_cycle_date, ss_i, rop_i}

    for row in candidates_df.itertuples():
        sku_id = row.sku_id
        product_key = row.product_key
        principal = row.principal

        product_demand = demand_df[demand_df["product_key"] == product_key]
        if product_demand.empty:
            gated_out["no demand history at all"] = gated_out.get("no demand history at all", 0) + 1
            logger.warning(f"  {sku_id} ({principal}): gated out — no demand history at all.")
            continue

        sigma_d, reason = _sigma_d_for_product(product_demand, principal)
        if sigma_d is None:
            gated_out[reason] = gated_out.get(reason, 0) + 1
            logger.warning(f"  {sku_id} ({principal}): gated out — {reason}.")
            continue

        if row.unit_price is not None:
            procurement_cost = float(row.unit_price)
            real_unit_price_count += 1
        else:
            procurement_cost = args.default_procurement_cost_per_unit
            fallback_unit_price_count += 1

        ss_i = compute_safety_stock(sigma_d)
        rop_i = compute_rop(forecast=float(row.forecast_value), safety_stock=ss_i)
        planning_cycle_date = row.forecast_date

        sku_input = SKUInput(
            sku_id=str(sku_id),
            principal=principal,
            rop=rop_i,
            procurement_cost_per_unit=procurement_cost,
            storage_cost_per_unit=args.storage_cost_per_unit,
        )
        sku_inputs_by_cycle.setdefault(planning_cycle_date, []).append(sku_input)
        lookup[str(sku_id)] = {
            "product_key": product_key, "planning_cycle_date": planning_cycle_date,
            "ss_i": ss_i, "rop_i": rop_i,
        }
        logger.info(f"  {sku_id} ({principal}): sigma_d={sigma_d:.3f} SS_i={ss_i:.2f} ROP_i={rop_i:.2f} "
                    f"procurement_cost={'real unit_price' if row.unit_price is not None else 'fallback'} "
                    f"cycle={planning_cycle_date}")

    # ---- Step D: validate ceilings cover every principal that survived --
    principals_present = {s.principal for skus in sku_inputs_by_cycle.values() for s in skus}
    missing = principals_present - set(supplier_ceilings)
    if missing:
        logger.error(
            f"--supplier-ceiling was not supplied for principal(s) {sorted(missing)}, but gated "
            f"product(s) for that principal survived every other gate. Refusing to guess an "
            f"unconstrained ceiling — supply --supplier-ceiling for every principal present and rerun."
        )
        conn.close()
        return

    # ---- Step E: one LP solve per planning cycle -------------------------
    rows_written = 0
    infeasible_cycles: list[tuple] = []

    for planning_cycle_date, skus in sorted(sku_inputs_by_cycle.items()):
        logger.info(f"Solving LP for planning cycle {planning_cycle_date} ({len(skus)} product(s))...")
        model = build_lp_model(skus, warehouse_capacity=args.warehouse_capacity, supplier_ceilings=supplier_ceilings)
        result = solve_lp(model)

        if result is None:
            reasons = _diagnose_infeasibility(skus, args.warehouse_capacity, supplier_ceilings)
            for reason in reasons:
                logger.error(f"  INFEASIBLE cycle {planning_cycle_date}: {reason}")
            infeasible_cycles.append((planning_cycle_date, reasons))
            logger.error(f"  Writing NOTHING for cycle {planning_cycle_date} — no constraint was relaxed to force a solution.")
            continue

        for sku_id, q_i in result.items():
            info = lookup[sku_id]
            save_result(info["product_key"], info["planning_cycle_date"], q_i, info["rop_i"], info["ss_i"])
            rows_written += 1
        logger.info(f"  Cycle {planning_cycle_date}: {len(result)} row(s) upserted into LP_Recommendation (status='pending').")

    conn.close()

    # ---- Summary -----------------------------------------------------
    logger.info(LOUD_RULE)
    logger.info("RUN SUMMARY")
    logger.info(f"  Products considered:        {considered}")
    logger.info(f"  Products gated out:          {sum(gated_out.values())}")
    for reason, count in sorted(gated_out.items()):
        logger.info(f"    - {reason}: {count}")
    logger.info(f"  Procurement cost source:     {real_unit_price_count} real (Product_Dimension.unit_price), "
                f"{fallback_unit_price_count} fallback (--default-procurement-cost-per-unit)")
    logger.info(f"  Planning cycles attempted:   {len(sku_inputs_by_cycle)}")
    logger.info(f"  Infeasible cycles:           {len(infeasible_cycles)}")
    for cycle_date, reasons in infeasible_cycles:
        logger.info(f"    - {cycle_date}: {'; '.join(reasons)}")
    logger.info(f"  Rows written to LP_Recommendation: {rows_written}")
    logger.info(LOUD_RULE)


if __name__ == "__main__":
    main()
