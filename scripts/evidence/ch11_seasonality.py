"""
Chart 11 - month-of-year index per year, Del Monte vs Unilever, real net pesos.
Index = the month's net pesos / the mean month of that calendar year.

Sources (inputs/, one READ ONLY extract of the _Real views):
  Del Monte  Sales_Fact_Real net_amount by region x invoice month. There is no branch
             field: branch_code is outlet-level; region holds the branch (pangasinan /
             ilocos) in 2023 rows only, and a town name from 2024. The branch split is
             therefore shown for 2023 only; towns are not mapped to branches (no
             documented mapping exists).
  Unilever   Unilever_SKU_Demand_Fact_Real net_amount by month (La Union source).

Decision under test: no seasonal model (seasonality not detectable at SKU level in 38
months). Pre-registered flag: 'aggregate caveat needed' if the monthly index correlates
positively (Spearman, p < 0.05) in EVERY pair of full years 2023-2025 for a principal.
It cannot overturn the SKU-level decision.
"""
import _common as C
import os
from itertools import combinations

import pandas as pd
from scipy.stats import spearmanr

YEARS = (2023, 2024, 2025)
BRANCHES = ("pangasinan", "ilocos")


def index_frame(df, principal, series):
    d = df.copy()
    d["year"] = d.month.str[:4].astype(int)
    d["moy"] = d.month.str[5:7].astype(int)
    d = d[d.year.isin(YEARS)]
    d["index"] = d.net_amount / d.groupby("year").net_amount.transform("mean")
    d["months_in_year"] = d.groupby("year").month.transform("size")
    d["partial_year"] = d.months_in_year < 12
    return d.assign(principal=principal, series=series)


def main():
    dm = pd.read_csv(os.path.join(C.INPUTS, "delmonte_sales_region_month.csv"))
    ul = pd.read_csv(os.path.join(C.INPUTS, "unilever_sales_month.csv"))

    dm_tot = dm.groupby("month", as_index=False).agg(net_amount=("net_amount", "sum"), rows=("invoices", "sum"))
    ul_tot = ul.rename(columns={"rows": "rows"})[["month", "net_amount", "rows"]]
    frames = [index_frame(dm_tot, "delmonte", "total"), index_frame(ul_tot, "unilever", "total")]
    y23 = dm[dm.month.str.startswith("2023")]
    branch_share = y23[y23.region.isin(BRANCHES)].invoices.sum() / y23.invoices.sum()
    for b in BRANCHES:
        g = y23[y23.region == b].groupby("month", as_index=False).agg(net_amount=("net_amount", "sum"), rows=("invoices", "sum"))
        frames.append(index_frame(g, "delmonte", f"branch {b} (2023 only)"))
    I = pd.concat(frames, ignore_index=True)

    # The criterion is defined on FULL years: a pair is tested only when both years have 12 months.
    months_in = I[I.series == "total"].groupby(["principal", "year"]).month.size()
    pairs, flags, testable = [], {}, {}
    for p in ("delmonte", "unilever"):
        t = I[(I.principal == p) & (I.series == "total")]
        all_hit, all_testable = True, True
        for a, b in combinations(YEARS, 2):
            na, nb_ = int(months_in.get((p, a), 0)), int(months_in.get((p, b), 0))
            if na == 12 and nb_ == 12:
                m = t[t.year == a].set_index("moy")["index"].to_frame("a").join(t[t.year == b].set_index("moy")["index"].to_frame("b"))
                rho, pv = spearmanr(m.a, m.b)
                hit, reason = bool(rho > 0 and pv < 0.05), ""
            else:
                rho, pv, hit = float("nan"), float("nan"), False
                reason = f"not testable: {a} has {na} of 12 months, {b} has {nb_}"
                all_testable = False
            all_hit &= hit
            pairs.append(dict(principal=p, years=f"{a}-{b}", months_a=na, months_b=nb_, rho=rho, p_value=pv,
                              positive_significant=hit, note=reason))
        flags[p], testable[p] = all_hit, all_testable
    Pr = pd.DataFrame(pairs)
    flagged = [p for p, f in flags.items() if f]
    untestable = [p for p, t_ in testable.items() if not t_]
    name = {"delmonte": "Del Monte", "unilever": "Unilever"}
    parts = []
    for p in flags:
        parts.append(f"{name[p]}: " + ("CAVEAT NEEDED" if flags[p] else "NOT TESTABLE" if not testable[p] and
                                      Pr[(Pr.principal == p) & (Pr.note == "")].empty else
                                      "no flag" + (" (some pairs not testable)" if not testable[p] else "")))
    verdict = ("CAVEAT NEEDED" if flagged else "CONFIRMS") if not untestable else " / ".join(parts)
    pair_txt = lambda r: (f"{r.years} rho {r.rho:+.2f} (p {r.p_value:.3f})" if r.note == "" else f"{r.years} {r.note}")  # noqa: E731
    detail = "; ".join(f"{name[p]}: " + ", ".join(pair_txt(r) for r in Pr[Pr.principal == p].itertuples()) for p in flags)

    rows_year = I[I.series == "total"].groupby(["principal", "year"]).agg(rows=("rows", "sum"), months=("month", "size"),
                                                                         pesos=("net_amount", "sum")).reset_index()
    dmr = rows_year[rows_year.principal == "delmonte"].set_index("year")
    ul_null = int((ul.rows - ul.rows_with_amount).sum())
    peak = I[I.series == "total"].loc[lambda d: d.groupby(["principal", "year"])["index"].transform("max") == d["index"]]
    caption = (
        f"Month-of-year index (month's real net pesos / that year's mean month), {YEARS[0]}-{YEARS[-1]}. Spearman correlation of "
        f"the index between years - "
        + "; ".join(f"{name[p]}: " + ", ".join(pair_txt(r) for r in Pr[Pr.principal == p].itertuples()) for p in flags)
        + ". " + (f"Every pair is positive and significant for {', '.join(name[p] for p in flagged)}: an aggregate seasonal pattern "
                  f"the paper should mention; it does not overturn the SKU-level finding. " if flagged
                  else "No principal has every pair of full years positive and significant. ")
        + ("".join(f"{name[p]} has no full year in {YEARS[0]}-{YEARS[-1]} ("
                   + ", ".join(f"{y}: {int(months_in.get((p, y), 0))} of 12 months" for y in YEARS)
                   + f"), so the pre-registered test cannot be run for it and its curves are partial years. " for p in untestable
                   if Pr[(Pr.principal == p) & (Pr.note == "")].empty))
        + "Peak month by year: " + "; ".join(f"{'DM' if r.principal == 'delmonte' else 'UL'} {r.year} {r.month[5:]} ({r.index:.2f})"
                                               for r in peak.sort_values(["principal", "year"]).itertuples())
        + f". Del Monte volume differs sharply by year: " + ", ".join(f"{y} {int(dmr.loc[y, 'rows']):,} invoice rows / PHP "
                                                                    f"{dmr.loc[y, 'pesos'] / 1e6:,.1f}M" for y in YEARS)
        + f"; {min(YEARS, key=lambda y: dmr.loc[y, 'rows'])} has the fewest rows, so its index rests on the least data. The branch split "
          f"exists for 2023 only ({branch_share:.0%} of 2023 invoice rows carry a branch; later rows carry a town)."
    )
    notes = [f"Del Monte has no branch field: branch_code is outlet-level (config/column_maps/sales_register.yaml:89-91); region "
             f"holds the branch in 2023 rows and a town from 2024. Towns are not mapped to branches (no documented mapping).",
             f"Unilever: {ul_null} demand rows have no net_amount and are left out of the monthly sums (La Union source only).",
             "Nominal pesos; the index divides within each year, so price level cancels."]
    C.write_result(11, "seasonality", "Month-of-year index", {"index": I, "pairs": Pr, "rows_by_year": rows_year}, caption,
                   verdict, detail, [], "ch11_seasonality.py", extra=dict(data_notes=notes, years=list(YEARS)))


if __name__ == "__main__":
    main()
