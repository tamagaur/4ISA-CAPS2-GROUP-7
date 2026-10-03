"""
Charts 8, 9, 10 - the LP (scripts/run_lp.py, reworked 2026-09-29). PLACEHOLDER inputs
(analytics/optimization/lp_inputs.PLACEHOLDERS: allocation %, review/lead days, target
weeks, warehouse capacity, costs) - realistic values, NOT SSM's figures.
Candidate pool: Category A, Forecast_Result status 'ok' and MASE < 1.0 (the pipeline
gate, run_lp.py:113; not changed here).

  8  allocation 103 / 105 / 108 %: `python -m scripts.run_lp --dry-run --csv` three
     times (run_lp's own READ ONLY transaction), plus the plan totals from plan_cycle().
  9  LP weights: every (w1 cost, w2 service, w3 storage) on a 0.05 grid summing to 1
     (231 points), allocation 103 %, plan_cycle() with lp.build_lp_model's `weights`
     argument bound (lp.py and run_lp.py are not edited).
 10  service level 85..99 %: total safety stock held, model-implied stockout months,
     and the measured monthly exceedance at the current Z.

run_lp's inputs are fetched ONCE here with its own queries and helpers, in one READ
ONLY transaction (BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK).

Check G7 (pre-registered; extended here to all three allocations, which is stricter):
the harness at the default weights equals run_lp --dry-run row for row (order, short).
"""
import _common as C
import argparse
import functools
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

sys.path.insert(0, C.REPO)
PCTS = (103.0, 105.0, 108.0)
SCRATCH = os.environ.get("DSD_EVIDENCE_LOGS", os.path.join(__import__("tempfile").gettempdir(), "dsd_evidence_logs"))
STEP = 0.05
DEFAULT_W = (0.45, 0.35, 0.20)


def R():
    import scripts.run_lp as run_lp
    logging.getLogger(run_lp.__name__).setLevel(logging.ERROR)
    for h in logging.getLogger().handlers:
        h.setLevel(logging.ERROR)
    return run_lp


def fetch_products():
    """run_lp.main() Steps A-C, verbatim in substance, inside one read-only transaction."""
    r = R()
    with C.read_only() as (cur, via):
        cur.execute(r.CANDIDATE_QUERY, (r.MASE_GATE,))
        cand = pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_id", "principal", "forecast_date", "forecast_value", "mase"])
        pks = [int(k) for k in cand.product_key.unique()]
        demand = r.fetch_demand_history(cur, pks)
        stock = r.fetch_stock_and_cost(cur, pks)
    by_cycle, gated = {}, {}
    for row in cand.itertuples():
        d = demand[demand.product_key == row.product_key]
        if d.empty:
            gated["no demand history at all"] = gated.get("no demand history at all", 0) + 1
            continue
        sigma_d, reason = r._sigma_d_for_product(d, row.principal)
        if sigma_d is None:
            gated[reason] = gated.get(reason, 0) + 1
            continue
        p, reason = r.product_input(row.product_key, row.sku_id, row.principal, float(row.forecast_value), sigma_d,
                                    stock, demand, prior_year=row.forecast_date.year - 1)
        if p is None:
            gated[reason] = gated.get(reason, 0) + 1
            continue
        by_cycle.setdefault(row.forecast_date, []).append(p)
    return cand, demand, by_cycle, gated, via


def args_for(pct):
    return R().build_parser().parse_args(["--dry-run", "--allocation-pct", f"{pct:g}"])


def solve(job):
    """One plan_cycle() with the LP weights bound. Returns totals + per-SKU orders."""
    products, pct, w = job
    r = R()
    from analytics.optimization.lp import build_lp_model
    r.build_lp_model = functools.partial(build_lp_model, weights=w)
    plan = r.plan_cycle(products, args_for(pct))
    s = plan.summary()
    orders = plan.orders or {}
    cost = sum(orders.get(k.sku_id, 0.0) * k.procurement_cost_per_unit for k in plan.skus)
    return dict(w1=w[0], w2=w[1], w3=w[2], pct=pct, feasible=plan.orders is not None, need=s["need"], ordered=s["ordered"],
                shortfall=s["shortfall"], short_skus=";".join(s["short_skus"]), n_short=len(s["short_skus"]),
                order_cost=cost, month_end_cover_weeks=s["month_end_cover_weeks"],
                month_end_stock_value=s["month_end_stock_value"], cover_required_value=s["cover_required_value"],
                allocation_binds=all(s["allocation_binds"].values()),
                orders={k.sku_id: orders.get(k.sku_id) for k in plan.skus})


def grid():
    n = int(round(1 / STEP))
    return [(round(i * STEP, 2), round(j * STEP, 2), round((n - i - j) * STEP, 2)) for i in range(n + 1) for j in range(n + 1 - i)]


def run_cli(pct):
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(C.EVID, f"ch08_cli_plan_{pct:g}.csv")
    log = os.path.join(SCRATCH, f"run_lp_dry_{pct:g}.log")
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run([sys.executable, "-m", "scripts.run_lp", "--dry-run", "--allocation-pct", f"{pct:g}", "--csv", out],
                            cwd=C.REPO, stdout=fh, stderr=subprocess.STDOUT, env=os.environ.copy()).returncode
    if rc != 0:
        C.fail("G7", f"run_lp --dry-run --allocation-pct {pct:g} exited {rc}; log {log}")
    return pd.read_csv(out, dtype={"sku_id": str})


def main():
    t0 = time.time()
    C.export_env_to_process()
    cand, demand, by_cycle, gated, via = fetch_products()
    if len(by_cycle) != 1:
        C.fail("G7", f"expected one planning cycle, found {len(by_cycle)}")
    cycle, products = next(iter(by_cycle.items()))
    print(f"fetched via {via}: {len(cand)} candidates, {len(products)} planned, gated out {gated}, cycle {cycle} [{time.time() - t0:.0f}s]", flush=True)
    cli = {pct: run_cli(pct) for pct in PCTS}
    print(f"3 CLI dry runs done [{time.time() - t0:.0f}s]", flush=True)

    jobs = [(products, pct, DEFAULT_W) for pct in PCTS] + [(products, 103.0, w) for w in grid()]
    with ProcessPoolExecutor(max_workers=C.MAX_WORKERS) as ex:
        res = list(ex.map(solve, jobs, chunksize=4))
    print(f"{len(jobs)} solves done [{time.time() - t0:.0f}s]", flush=True)
    base = {r_["pct"]: r_ for r_ in res[:3]}

    # ---- G7: harness == CLI, row for row -------------------------------------
    bad = []
    for pct in PCTS:
        c = cli[pct]
        h = pd.Series(base[pct]["orders"]).round(2)
        m = c.set_index("sku_id").order.round(2)
        if set(h.index) != set(m.index) or (h.reindex(m.index) - m).abs().max() > 0.01:
            bad.append(pct)
    g7 = dict(id="G7", **{"pass": not bad},
              detail=f"harness at weights {DEFAULT_W} equals run_lp --dry-run order for order at "
                     f"{', '.join(f'{p:g}%' for p in PCTS if p not in bad)} ({len(products)} products each)"
                     + (f"; DIFFERS at {bad}" if bad else ""))
    if bad:
        C.fail("G7", g7["detail"])

    notes = C.null_notes(p.product_key for p in products)
    ph = R().PLACEHOLDERS
    ph_note = ("LP inputs are PLACEHOLDERS (analytics/optimization/lp_inputs.py), realistic values the team chose, not SSM's "
               "figures: " + ", ".join(f"{k} {v:g}" if isinstance(v, (int, float)) else f"{k} {v}" for k, v in ph.items()) + ".")
    pool_note = f"Pool: Category A with a stored forecast of status 'ok' and MASE < {C.MASE_GATE_PIPELINE:g} (pipeline gate)."

    chart8(cli, base, products, cycle, g7, notes + [ph_note, pool_note])
    chart9(res[3:], base[103.0], products, g7, notes + [ph_note, pool_note])
    chart10(products, demand, notes + [ph_note, pool_note])
    print(f"total {time.time() - t0:.0f}s")


RUN_LP_TOLERANCE_PHP = 1.0   # run_lp.py:556 - its log calls cover met when stock >= required - PHP 1


def boundary_note(cover_105: float, gap_105: float) -> str:
    """The sentence chart 8 carries in its caption and data notes (Yuan, 2026-09-30).
    Only meaningful when 105% misses the strict test by less than run_lp's own tolerance."""
    return (f"Boundary result — at 105% month-end cover = {cover_105:.9f} weeks (₱{-gap_105:.2f} short); "
            f"run_lp's own tolerance is ₱{RUN_LP_TOLERANCE_PHP:g} (run_lp.py:556).")


def chart8(cli, base, products, cycle, g7, notes):
    rows = []
    for pct in PCTS:
        b = base[pct]
        rows.append(dict(allocation_pct=pct, products=len(products), need=b["need"], ordered=b["ordered"], shortfall=b["shortfall"],
                         n_short=b["n_short"], short_skus=b["short_skus"], month_end_cover_weeks=b["month_end_cover_weeks"],
                         cover_gap_php=b["month_end_stock_value"] - b["cover_required_value"],
                         run_lp_says_met=b["month_end_stock_value"] >= b["cover_required_value"] - 1.0,
                         order_cost=b["order_cost"], allocation_binds=b["allocation_binds"]))
    A = pd.DataFrame(rows)
    old = []
    for pct in PCTS:
        prev = pd.read_csv(os.path.join(C.REPO, "reports", "lp_dry_run_2026-09-29", f"plan_aggregate_{pct:g}.csv"), dtype={"sku_id": str})
        j = prev.merge(cli[pct], on="sku_id", how="outer", suffixes=("_0929", "_now"), indicator=True)
        both = j[j._merge == "both"]
        old.append(dict(allocation_pct=pct, skus_0929=len(prev), skus_now=len(cli[pct]), only_0929=int((j._merge == "left_only").sum()),
                        only_now=int((j._merge == "right_only").sum()),
                        order_changed=int(((both.order_0929 - both.order_now).abs() > 0.5).sum()),
                        forecast_changed=int(((both.forecast_0929 - both.forecast_now).abs() > 0.5).sum())))
    D = pd.DataFrame(old)
    tw = R().PLACEHOLDERS["target_weeks"]
    r105, r108 = A.set_index("allocation_pct").loc[105.0], A.set_index("allocation_pct").loc[108.0]
    low_cover = r105.month_end_cover_weeks is not None and r105.month_end_cover_weeks < tw
    cleared = r105.n_short > 0 and r108.n_short == 0
    verdict = "FLAWED" if (low_cover or cleared) else "CONFIRMS"
    detail = (f"105%: month-end cover {r105.month_end_cover_weeks:.9f} weeks vs target {tw:g} ({'BELOW' if low_cover else 'met'}; "
              f"PHP {r105.cover_gap_php:+,.6f} against the requirement; run_lp's own log rule, stock >= required - PHP 1 "
              f"(run_lp.py:556), calls it {'met' if r105.run_lp_says_met else 'short'}); "
              f"short SKUs {int(r105.n_short)} at 105% vs {int(r108.n_short)} at 108% ({'108% CLEARS it' if cleared else 'not cleared by 108%'})")
    caption = (
        f"Supplier allocation at Sir Abe's three levels (last year's sales x 103 / 105 / 108 % / 12), planning cycle {cycle}, "
        f"{len(products)} products, run_lp --dry-run with every other input at its placeholder default. "
        + "; ".join(f"{r.allocation_pct:g}%: order {r.ordered:,.0f} of need {r.need:,.0f} pieces, shortfall {r.shortfall:,.0f} on "
                    f"{r.n_short} SKUs, month-end cover {r.month_end_cover_weeks:.6f} weeks (PHP {r.cover_gap_php:+,.2f} against "
                    f"the {R().PLACEHOLDERS['target_weeks']:g}-week requirement)" for r in A.itertuples())
        + f". The pre-registered test is strict (cover below {tw:g} weeks), so 105% "
        + ("FAILS it" if low_cover else "passes it")
        + (f" by PHP {-r105.cover_gap_php:,.6f}; run_lp's own log counts cover within PHP 1 as met (run_lp.py:556), so it "
           f"reports 105% as met" if low_cover and r105.run_lp_says_met else "")
        + f". Target cover {tw:g} weeks (placeholder). Against the 2026-09-29 dry run: "
        + "; ".join(f"{r.allocation_pct:g}% {r.order_changed} of {r.skus_now} orders changed" for r in D.itertuples())
        + ". Inputs are placeholders, not SSM's figures."
    )
    if low_cover and -r105.cover_gap_php < RUN_LP_TOLERANCE_PHP:
        bn = boundary_note(r105.month_end_cover_weeks, r105.cover_gap_php)
        caption, notes = caption + " " + bn, notes + [bn]
    C.write_result(8, "allocation", "Allocation 103/105/108", {"totals": A, "diff_vs_0929": D}, caption, verdict, detail, [g7],
                   "lp_charts.py", extra=dict(data_notes=notes, cli_csvs=[f"reports/evidence/ch08_cli_plan_{p:g}.csv" for p in PCTS]))


def chart9(res, default, products, g7, notes):
    G = pd.DataFrame([{k: v for k, v in r_.items() if k != "orders"} for r_ in res])
    G["is_default"] = (G[["w1", "w2", "w3"]] - np.array(DEFAULT_W)).abs().max(axis=1) < 1e-9
    G["neighbour"] = (G[["w1", "w2", "w3"]] - np.array(DEFAULT_W)).abs().max(axis=1) <= 0.10 + 1e-9
    base_set = set(filter(None, default["short_skus"].split(";")))
    G["cut_set_differs"] = [set(filter(None, s.split(";"))) != base_set for s in G.short_skus]
    nb = G[G.neighbour & ~G.is_default]
    diff = nb[nb.cut_set_differs]
    verdict = "FLAWED" if len(diff) else "CONFIRMS"
    detail = (f"{len(diff)} of {len(nb)} grid points within +/-0.10 of {DEFAULT_W} change the cut-SKU set"
              + (f" (e.g. {diff.iloc[0][['w1', 'w2', 'w3']].tolist()})" if len(diff) else ""))
    anyd = G[G.cut_set_differs & ~G.is_default]
    caption = (
        f"LP weights (cost w1, service w2, storage w3) on a {STEP:g} grid summing to 1 ({len(G)} points), allocation 103 %, "
        f"{len(products)} products, placeholder inputs. At the current weights {DEFAULT_W}: {default['n_short']} SKUs cut "
        f"(order below need), shortfall {default['shortfall']:,.0f} pieces, order cost PHP {default['order_cost']:,.0f}. "
        f"Within +/-0.10 of the current weights on every weight ({len(nb)} other points) the cut set changes at {len(diff)}; "
        f"across the whole grid at {len(anyd)} of {len(G) - 1}. Shortfall across the grid "
        f"{G.shortfall.min():,.0f}-{G.shortfall.max():,.0f} pieces; order cost PHP {G.order_cost.min():,.0f}-{G.order_cost.max():,.0f}."
    )
    C.write_result(9, "weights", "LP weights", {"grid": G}, caption, verdict, detail, [g7], "lp_charts.py",
                   extra=dict(data_notes=notes, default=list(DEFAULT_W), step=STEP))


def chart10(products, demand, notes):
    from scipy.stats import norm
    r = R()
    from analytics.optimization.lp import Z_SCORE
    from analytics.optimization.lp_inputs import BUSINESS_DAYS_PER_WEEK, WEEKS_PER_MONTH
    ph = r.PLACEHOLDERS
    window = ph["review_days"] + ph["lead_days"]
    cycles = WEEKS_PER_MONTH * BUSINESS_DAYS_PER_WEEK / ph["review_days"]
    cost = {p.sku_id: (p.cost_per_piece if p.cost_per_piece is not None else ph["default_procurement_cost_per_unit"]) for p in products}
    ss_now = sum(r.safety_stock_for(p.sigma_d, window) for p in products)
    ss_check = abs(ss_now - sum(Z_SCORE * p.sigma_d * np.sqrt(window) for p in products)) < 1e-6

    # measured: monthly exceedance of forecast + Z x sigma_monthly on the stored rolling one-step holdout
    A = C.load_preds()
    served = np.select([A.sales < 12, A.sales < 24], [A.ma3, A.tsb], A["ens_xgb_ma3@A"])
    A = A.assign(served=served)
    A = C.in_window(A, *C.FULL)
    # sigma_monthly exactly as the LP derives sigma_d from it (run_lp._sigma_d_for_product, Unilever branch):
    # sigma_d = sigma_monthly / sqrt(avg business days per month)  =>  sigma_monthly = sigma_d * sqrt(avg bdays)
    pool = {p.product_key for p in products if p.principal == "unilever"}
    sig = {}
    for p in products:
        if p.product_key in pool:
            ms = demand[demand.product_key == p.product_key].period.astype(str).unique()
            avg_bdays = sum(len(r.business_days_in_month(m)) for m in ms) / len(ms)
            sig[p.product_key] = p.sigma_d * np.sqrt(avg_bdays)
    E = A[A.pk.isin(pool) & A.served.notna()].copy()
    E["sigma_monthly"] = E.pk.map(sig)
    rows, emp = [], []
    rng = np.random.default_rng(C.SEED)
    skus = E.pk.unique()
    idx = rng.integers(0, len(skus), (C.NBOOT, len(skus)))
    for sl in range(85, 100):
        z = float(norm.ppf(sl / 100))
        ss = sum(z * p.sigma_d * np.sqrt(window) for p in products)
        ss_val = sum(z * p.sigma_d * np.sqrt(window) * cost[p.sku_id] for p in products)
        ex = (E.actual > E.served + z * E.sigma_monthly).astype(int)
        per = pd.DataFrame({"pk": E.pk, "x": ex}).groupby("pk").x.agg(["sum", "size"]).reindex(skus)
        boot = per["sum"].to_numpy()[idx].sum(1) / per["size"].to_numpy()[idx].sum(1)
        rows.append(dict(service_level=sl / 100, z=z, total_safety_stock_pieces=ss, total_safety_stock_php=ss_val,
                         model_stockout_sku_months_per_year=len(products) * 12 * (1 - (sl / 100) ** cycles),
                         measured_exceedance=ex.mean(), measured_ci_lo=np.percentile(boot, 2.5), measured_ci_hi=np.percentile(boot, 97.5),
                         nominal_exceedance=1 - sl / 100))
    Tb = pd.DataFrame(rows)
    ex_now = (E.actual > E.served + Z_SCORE * E.sigma_monthly).astype(int)
    per = pd.DataFrame({"pk": E.pk, "x": ex_now}).groupby("pk").x.agg(["sum", "size"]).reindex(skus)
    boot = per["sum"].to_numpy()[idx].sum(1) / per["size"].to_numpy()[idx].sum(1)
    lo, hi, rate = np.percentile(boot, 2.5), np.percentile(boot, 97.5), ex_now.mean()
    flawed = lo > 0.10
    verdict = "FLAWED" if flawed else "CONFIRMS"
    detail = f"measured monthly exceedance at Z={Z_SCORE}: {rate:.1%} (95% CI {lo:.1%}-{hi:.1%}, SKU bootstrap) vs nominal 10%"
    checks = [dict(id="SS", **{"pass": ss_check}, detail=f"run_lp.safety_stock_for at Z={Z_SCORE} equals Z x sigma_d x sqrt({window:g}) summed: {ss_check}")]
    if not ss_check:
        C.fail("SS", checks[0]["detail"])
    caption = (
        f"Service level 85-99 %: total safety stock the LP would hold ({len(products)} products, SS = Z x sigma_d x sqrt({window:g} "
        f"business days), placeholder review/lead days) against expected stockouts. Current Z = {Z_SCORE} (lp.py, 90 %): "
        f"{ss_now:,.0f} pieces. At 85 % / 95 % / 99 %: "
        + " / ".join(f"{Tb.loc[Tb.service_level.round(2) == s, 'total_safety_stock_pieces'].iloc[0]:,.0f}" for s in (0.85, 0.95, 0.99))
        + f" pieces. Model-implied SKU-months with a stockout per year (normal demand, {cycles:.2f} independent weekly cycles a "
          f"month) fall from {Tb.model_stockout_sku_months_per_year.iloc[0]:,.0f} at 85 % to "
          f"{Tb.model_stockout_sku_months_per_year.iloc[-1]:,.0f} at 99 %. Measured on the stored rolling one-step holdout "
          f"({E.pk.nunique()} of the products, {len(E)} SKU-months, {C.FULL[0]}..{C.FULL[1]}, served model by history length): "
          f"actual demand exceeded forecast + {Z_SCORE} x monthly sigma in {rate:.1%} of months (95 % CI {lo:.1%}-{hi:.1%}, "
          f"bootstrap over SKUs) against the nominal 10 %. Sigma is the LP's own: the SKU's monthly demand standard deviation over "
          f"its whole history (holdout months included), recovered as sigma_d x sqrt(average business days a month)."
    )
    C.write_result(10, "service", "Service level", {"curve": Tb}, caption, verdict, detail, checks, "lp_charts.py",
                   extra=dict(data_notes=notes + ["The model-implied stockout months are a formula (normal demand, independent weekly "
                                                  "cycles), not a measurement; the measured exceedance is at monthly grain."],
                              z_current=Z_SCORE, measured_rate=rate, measured_ci=[lo, hi]))


if __name__ == "__main__":
    main()
