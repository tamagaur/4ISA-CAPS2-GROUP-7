"""
scripts/snapshot_published_figures.py — pin the accuracy figures the manuscript quotes, so they can be
reproduced after new actuals land (2026-10-24).

`mart.accuracy_mart` and `mart.error_decomposition` read real sales at every mart refresh, so loading March
2026 moves every figure computed from them. This freezes the figures and the rows behind them.

    python -m scripts.snapshot_published_figures --write          # read-only on the DB; writes the files below
    python -m scripts.snapshot_published_figures --verify         # recompute from the frozen rows, no DB write
    python -m scripts.snapshot_published_figures --march-impact   # what loading March 2026 would move (loads nothing)

Writes
  docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json   aggregates only (tracked): every figure, the actuals version
                                                      (analytics/actuals_version.py), the sha256 of every input
  docs/published_snapshot_2026-10-24/*.csv          the per-product rows the figures were computed from (tracked,
                                                      hard rule 9's exception of 2026-10-23: the figures are published),
                                                      trimmed to KEEP_COLUMNS: frozen as-served rows, demand money,
                                                      stored MASE rows, error-decomposition rows

--verify recomputes the headline WAPE, the MASE pass rate and median, the error-decomposition split, the
17.14% exceedance and the peso figure from the FROZEN rows (not the live database), checks the input hashes,
and compares with the JSON. It also reads the live actuals version and says whether the data has moved since;
a moved version never fails the figures (they are pinned to the frozen rows), it only says they are no longer
what a fresh computation would give.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts.report_target import report_path  # noqa: E402

SNAP_DATE = "2026-10-24"
SNAP_DIR = REPO / "docs" / f"published_snapshot_{SNAP_DATE}"
SNAP_JSON = REPO / "docs" / f"PUBLISHED_FIGURES_SNAPSHOT_{SNAP_DATE}.json"
DOC = REPO / "docs" / "ACCURACY_AS_SERVED.md"
FROZEN = {  # frozen file -> where it is read from (local/, git-ignored), then trimmed
    "accuracy_as_served_rows.csv": REPO / "local" / "accuracy_as_served_rows.csv",
    "demand_money.csv": REPO / "local" / "error_direction_money.csv",
}
FIGURE_TOLERANCE = 1e-9
# The only columns of each frozen file that --verify, --march-impact, scripts/manuscript_figures.py or a test reads. Anything
# else the source carries (prices, safety-stock values, run ids, model bins) is not committed.
KEEP_COLUMNS = {
    "accuracy_as_served_rows.csv": ["product_key", "month", "actual", "value", "ma3", "run"],
    "demand_money.csv": ["product_key", "month", "net_amount", "quantity_raw"],
    "mase_rows.csv": ["product_key", "status", "mase"],
    "error_decomposition_row.csv": ["tier", "product_key", "month", "forecast_pieces", "actual_pieces", "over_pieces",
                                    "under_pieces", "absorbed_pieces", "beyond_pieces", "exceeds_safety_stock",
                                    "over_pesos", "absorbed_pesos", "beyond_pesos"],
}


def write_frozen(name: str, df: pd.DataFrame, folder: Path = SNAP_DIR) -> None:
    """Write one frozen file with only its KEEP_COLUMNS, in that order."""
    folder.mkdir(parents=True, exist_ok=True)
    df[KEEP_COLUMNS[name]].to_csv(folder / name, index=False)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_sections(text: str, headings: tuple[str, ...]) -> dict[str, str]:
    """The published markdown of the named `## ` sections of docs/ACCURACY_AS_SERVED.md, verbatim."""
    out, cur, buf = {}, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur in headings:
                out[cur] = "\n".join(buf).strip()
            cur, buf = line[3:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur in headings:
        out[cur] = "\n".join(buf).strip()
    return out


def headline_figures(rows: pd.DataFrame, money: pd.DataFrame) -> dict:
    from scripts.accuracy_as_served import metrics
    out = {}
    for run in ("as_served", "as_served_calendar"):
        bt = rows[rows.run == run].reset_index(drop=True)
        m = metrics(bt, money)
        out[run] = {k: m[k] for k in ("median_product_wape_served", "pooled_wape_pcs_served", "total_wape_pesos_served",
                                      "surplus_share_of_miss_pesos", "surplus_share_of_miss_pieces", "products",
                                      "product_months")}
    return out


def mase_figures(mase: pd.DataFrame) -> dict:
    ok = mase[(mase.status == "ok") & mase.mase.notna()]
    return {"products_scored": int(len(ok)), "mase_below_1": int((ok.mase < 1).sum()),
            "pass_rate": float((ok.mase < 1).mean()), "median_mase": float(ok.mase.median())}


def decomposition_figures(dec: pd.DataFrame) -> dict:
    out = {}
    for tier, d in dec.groupby("tier"):
        n = len(d)
        err_p = d.over_pieces.sum() + d.absorbed_pieces.fillna(0).sum() + d.beyond_pieces.fillna(0).sum()
        under_no_ss = (d.under_pieces - d.absorbed_pieces.fillna(0) - d.beyond_pieces.fillna(0)).sum()
        out[tier] = {
            "product_months": int(n),
            "over_pieces": float(d.over_pieces.sum()), "absorbed_pieces": float(d.absorbed_pieces.sum()),
            "beyond_pieces": float(d.beyond_pieces.sum()), "under_without_safety_stock_pieces": float(under_no_ss),
            "total_error_pieces": float(err_p + under_no_ss),
            "over_pesos": float(d.over_pesos.sum()), "absorbed_pesos": float(d.absorbed_pesos.sum()),
            "beyond_pesos": float(d.beyond_pesos.sum()),
            "exceeds_safety_stock_months": int(d.exceeds_safety_stock.fillna(False).sum()),
            "exceedance_rate": float(d.exceeds_safety_stock.fillna(False).sum() / n),
        }
    return out


def compute(rows, money, mase, dec) -> dict:
    return {"headline_wape": headline_figures(rows, money), "mase": mase_figures(mase),
            "error_decomposition": decomposition_figures(dec)}


def flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


def read_frozen(folder: Path = SNAP_DIR):
    rows = pd.read_csv(folder / "accuracy_as_served_rows.csv")
    money = pd.read_csv(folder / "demand_money.csv")
    mase = pd.read_csv(folder / "mase_rows.csv")
    dec = pd.read_csv(folder / "error_decomposition_row.csv")
    return rows, money, mase, dec


def connect():
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute("BEGIN")
    cur.execute("SET TRANSACTION READ ONLY")      # transaction-scoped, never session-level (hard rule 7)
    return conn, cur


def cmd_write() -> int:
    from analytics import actuals_version
    # The frozen rows are tracked files too: through report_path like the JSON (until 2026-11-11 only the JSON was, so a run
    # against the local Postgres overwrote docs/published_snapshot_*/ with a copy's rows while its JSON went to local/).
    folder = report_path(SNAP_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    for name, src in FROZEN.items():
        write_frozen(name, pd.read_csv(src), folder)
    conn, cur = connect()
    try:
        stamp = actuals_version.read(cur)
        cur.execute("""SELECT product_key, forecast_date, status, mase, model_params ->> 'method' AS method
                       FROM forecast_result WHERE forecast_date = (SELECT MAX(forecast_date) FROM forecast_result)""")
        mase = pd.DataFrame(cur.fetchall(), columns=["product_key", "forecast_date", "status", "mase", "method"])
        cur.execute("SELECT * FROM mart.error_decomposition_row")
        dec = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
        cur.execute("SELECT refresh_id, refreshed_at, trigger FROM mart.refresh_log ORDER BY refresh_id DESC LIMIT 1")
        refresh = cur.fetchone()
    finally:
        conn.rollback()
        conn.close()
    for c in ("mase",):
        mase[c] = mase[c].astype(float)
    for c in dec.columns:
        if dec[c].dtype == object and c not in ("principal", "tier", "month", "forecast_source", "ss_method"):
            dec[c] = pd.to_numeric(dec[c], errors="coerce")
    write_frozen("mase_rows.csv", mase, folder)
    write_frozen("error_decomposition_row.csv", dec, folder)
    rows, money, mase_f, dec_f = read_frozen(folder)
    figures = compute(rows, money, mase_f, dec_f)
    published = doc_sections(DOC.read_text(encoding="utf-8"), ("Headline (quote these)", "MASE pass rate (quote this one number)",
                                                               "Per route (stored MASE definition)"))
    out = {
        "snapshot_date": SNAP_DATE,
        "purpose": "Pin the figures the manuscript quotes; --verify recomputes them from the frozen rows.",
        "actuals_version": stamp,
        "mart_refresh": {"refresh_id": refresh[0], "refreshed_at": refresh[1].isoformat(), "trigger": refresh[2]},
        "forecast_result_date": str(mase.forecast_date.iloc[0]),
        "inputs_sha256": {p.name: sha256(p) for p in sorted(folder.glob("*.csv"))},
        "figures": figures,
        "published_doc_sections_verbatim": {"source": "docs/ACCURACY_AS_SERVED.md", "doc_sha256": sha256(DOC), **published},
    }
    report_path(SNAP_JSON).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    t = figures["error_decomposition"]["A"]
    print(f"wrote {report_path(SNAP_JSON).relative_to(REPO)} ; inputs in {folder.relative_to(REPO)}")
    print(f"actuals version {stamp['key']}")
    print(f"MASE {figures['mase']['mase_below_1']} of {figures['mase']['products_scored']}, median {figures['mase']['median_mase']:.3f}")
    print(f"as served pooled WAPE {figures['headline_wape']['as_served']['pooled_wape_pcs_served']:.4%}, "
          f"exceedance A {t['exceedance_rate']:.4%}, beyond pesos A {t['beyond_pesos']:,.0f}")
    return 0


def cmd_verify() -> int:
    from analytics import actuals_version
    snap = json.loads(SNAP_JSON.read_text(encoding="utf-8"))
    bad = []
    for name, want in snap["inputs_sha256"].items():
        got = sha256(SNAP_DIR / name) if (SNAP_DIR / name).exists() else None
        if got != want:
            bad.append(f"input {name}: hash {'missing' if got is None else 'differs'}")
    if not bad:
        now = dict(flatten(compute(*read_frozen())))
        was = dict(flatten(snap["figures"]))
        for k, v in was.items():
            if k not in now or not np.isclose(now[k], v, rtol=FIGURE_TOLERANCE, atol=FIGURE_TOLERANCE):
                bad.append(f"figure {k}: snapshot {v!r}, recomputed {now.get(k)!r}")
    for b in bad:
        print("FAIL", b)
    if bad:
        return 1
    print(f"OK: {len(was)} figures reproduced from the frozen rows ({snap['actuals_version']['key']})")
    try:
        conn, cur = connect()
        try:
            live = actuals_version.read(cur)
        finally:
            conn.rollback()
            conn.close()
        if live["key"] == snap["actuals_version"]["key"]:
            print("live actuals are unchanged since the snapshot")
        else:
            print(f"live actuals have MOVED: snapshot {snap['actuals_version']['key']}, now {live['key']} "
                  "(a fresh computation would differ; the pinned figures do not)")
    except Exception as exc:  # no database: the figures were still verified
        print(f"live actuals version not read: {exc}")
    return 0


def cmd_march_impact() -> int:
    """What loading March 2026 sales would change in the stored figures. Loads nothing; the March actual is
    unknown, so the effect is bracketed by the range of the same quantity over the months already scored."""
    rows, money, mase, dec = read_frozen()
    snap = json.loads(SNAP_JSON.read_text(encoding="utf-8"))
    conn, cur = connect()
    try:
        cur.execute("""SELECT COUNT(*) FILTER (WHERE status = 'ok'), SUM(forecast_value) FILTER (WHERE status = 'ok')
                       FROM forecast_result WHERE forecast_date = '2026-03-01'""")
        n_ok, f_ok = cur.fetchone()
        cur.execute("""SELECT COUNT(*) FROM forecast_result fr JOIN abc_classification a ON a.product_key = fr.product_key
                       WHERE fr.forecast_date = '2026-03-01' AND fr.status = 'ok' AND a.principal = 'unilever'
                         AND a.classification_period = '2026-02' AND a.method = 't12m_new' AND a.tier = 'A'""")
        n_tier_a = cur.fetchone()[0]
    finally:
        conn.rollback()
        conn.close()
    a = dec[dec.tier == "A"].copy()
    nA = len(a)
    monthly = a.groupby("month").agg(n=("product_key", "size"), exc=("exceeds_safety_stock", "sum"),
                                     beyond=("beyond_pesos", "sum"), over=("over_pieces", "sum"),
                                     under=("under_pieces", "sum"), act=("actual_pieces", "sum"),
                                     fc=("forecast_pieces", "sum"))
    monthly["exc_rate"] = monthly.exc / monthly.n
    monthly["wape"] = (monthly.over + monthly.under) / monthly.act
    exc0, beyond0 = int(a.exceeds_safety_stock.sum()), float(a.beyond_pesos.sum())
    e0, act0 = float(a.over_pieces.sum() + a.under_pieces.sum()), float(a.actual_pieces.sum())
    n_new = int(n_ok)
    f_new = float(f_ok)

    def bracket(rate_lo, rate_hi, base_num, base_den, add_den):
        return ((base_num + rate_lo * add_den) / (base_den + add_den), (base_num + rate_hi * add_den) / (base_den + add_den))

    lo_e, hi_e = monthly.exc_rate.min(), monthly.exc_rate.max()
    exc_rng = bracket(lo_e, hi_e, exc0, nA, n_new)
    lo_w, hi_w = monthly.wape.min(), monthly.wape.max()
    wape_rng = bracket(lo_w, hi_w, e0, act0, f_new)       # March actual unknown: its forecast total stands in for scale
    beyond_rng = (beyond0 + float(monthly.beyond.min()), beyond0 + float(monthly.beyond.max()))

    # re-pricing: price = SUM(net)/SUM(qty) over the product's scored months, so a new scored month moves every
    # product's price, and so every peso figure of every old month. Measured the other way round: drop the newest
    # scored month (2026-02) from the price base and see how far the peso figure moves.
    def price(df):
        t = df[["product_key", "month"]].drop_duplicates().merge(money, on=["product_key", "month"], how="left")
        g = t.groupby("product_key")[["quantity_raw", "net_amount"]].sum()
        return (g.net_amount / g.quantity_raw).where((g.quantity_raw > 0) & (g.net_amount > 0))
    p_full, p_drop = price(a), price(a[a.month != a.month.max()])
    both = pd.concat([p_full.rename("full"), p_drop.rename("drop")], axis=1).dropna()
    px_shift = (both["drop"] / both["full"] - 1).abs()
    b_full = float((a.beyond_pieces.fillna(0) * a.product_key.map(p_full)).sum())
    b_drop = float((a.beyond_pieces.fillna(0) * a.product_key.map(p_drop)).sum())

    print("MARCH 2026 IMPACT (nothing loaded)")
    print(f"March forecasts waiting for an actual: {n_new} ok rows ({n_tier_a} Tier A as of 2026-02), forecast total {f_new:,.0f} pieces")
    print(f"scored Tier A product-months now {nA:,}; March would add ~{n_new} ({n_new / nA:.1%})")
    print(f"exceedance rate {exc0 / nA:.2%} -> {exc_rng[0]:.2%} .. {exc_rng[1]:.2%} (March at the best / worst monthly rate so far, {lo_e:.1%} / {hi_e:.1%})")
    print(f"pooled WAPE Tier A {e0 / act0:.2%} -> {wape_rng[0]:.2%} .. {wape_rng[1]:.2%} (monthly {lo_w:.1%} .. {hi_w:.1%})")
    print(f"beyond-safety-stock pesos {beyond0:,.0f} -> {beyond_rng[0]:,.0f} .. {beyond_rng[1]:,.0f} (before re-pricing)")
    print(f"re-pricing: dropping one month from the price base moves the median product price {px_shift.median():.2%}, "
          f"max {px_shift.max():.2%}; the beyond-pesos total {b_full:,.0f} -> {b_drop:,.0f} ({b_drop / b_full - 1:+.2%})")
    print("MASE 109 of 175: stored on Forecast_Result for 2026-03; unchanged by a sales load, changes only when the runner is rerun")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--march-impact", action="store_true")
    args = ap.parse_args()
    return cmd_write() if args.write else cmd_verify() if args.verify else cmd_march_impact()


if __name__ == "__main__":
    sys.exit(main())
