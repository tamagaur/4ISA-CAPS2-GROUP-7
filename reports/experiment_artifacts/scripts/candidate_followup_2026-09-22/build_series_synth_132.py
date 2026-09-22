"""series_synth.csv for all 132 Tier A (2026-02) SKUs, as consumed by scripts/preview_router_synth.py: real rows exactly
as the live runner read them (cap_after_demand.pkl; the 13 from q13.pkl, identical) + v2 pre-2023 placeholder rows."""
import glob, pandas as pd
t = pd.read_pickle("cap_after_tier_a.pkl"); keys = set(int(k) for k in t.product_key)
D = pd.read_pickle("cap_after_demand.pkl"); D = D[D.product_key.isin(keys) & ~D.product_key.isin(pd.read_pickle("q13.pkl").product_key)]
real = pd.concat([D, pd.read_pickle("q13.pkl")])[["product_key", "sku_code", "calendar_month", "quantity"]]
V = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(r"C:\Users\kyuan\Capstone-Project\staging_synthetic\unilever_sku\*.parquet"))])
V = V[V._period < "2023-01"]; u = real.drop_duplicates("product_key")
code2pk = u.set_index(u.sku_code.astype(str).str.strip()).product_key.to_dict()
V["product_key"] = V.Product.astype(str).str.strip().map(code2pk); V = V[V.product_key.notna()]
ph = pd.DataFrame({"product_key": V.product_key.astype(int), "month": V._period,
                   "quantity": pd.to_numeric(V["Sale Quantity in\r\n  Aggr.PC"]), "is_placeholder": True})
out = pd.concat([ph, real.rename(columns={"calendar_month": "month"})[["product_key", "month", "quantity"]].assign(is_placeholder=False)])
out = out.sort_values(["product_key", "month"])
assert not out.duplicated(["product_key", "month"]).any()
out.to_csv("series_synth.csv", index=False)
