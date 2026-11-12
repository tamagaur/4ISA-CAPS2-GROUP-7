"""The fake databases' answer to marts.accuracy_summary_query (they have no SQL engine)."""
from backend import marts


def accuracy_summary_rows(raw: list[dict]) -> list[dict]:
    """What marts.accuracy_summary_query returns for these scored rows: one row per month, one per
    product, one for the range (the fake database has no SQL engine, so it sums them here)."""
    agg = marts.accuracy_aggregates(raw)
    out = [{"kind": "month", "d": {**m, "sources": sorted(m["sources"])}} for m in agg["months"].values()]
    for key, p in agg["products"].items():
        out.append({"kind": "product", "d": {
            "product_key": key, "abs_miss": p["abs"], "abs_actual": p["act"], "priced": p["priced"],
            "rule_rows": p["rule_rows"], "stockout_rows": p["stockout_rows"], "ape_sum": p["ape_sum"], "ape_n": p["ape_n"],
            **{k: p["last"].get(k) for k in ("month", "direction", "run_length", "miss_pieces", "price_per_piece",
                                              "sku_code", "product_name", "possibly_stock_limited")}}})
    out.append({"kind": "total", "d": {
        "product_months": agg["product_months"], "sources": agg["sources"] or None, "run_labels": agg["run_labels"] or None,
        "possibly_stock_limited": agg["possibly_stock_limited"],
        "possibly_stock_limited_unknown": agg["possibly_stock_limited_unknown"]}})
    return out
