import hashlib, json, os
from urllib.parse import quote
def sig(r): return hashlib.md5(r.content).hexdigest()[:12]
REAL = ["/dashboard?principal=unilever", "/dashboard?principal=delmonte", "/dashboard?principal=all", "/recommendations?principal=unilever",
        "/recommendations?principal=delmonte", "/policy-comparison?principal=unilever", "/pareto?principal=delmonte", "/pareto?principal=unilever",
        "/category-trends?principal=delmonte", "/abc?principal=delmonte", "/fsn?principal=delmonte", "/dashboard/class-changes?principal=delmonte",
        "/forecast/21015692?principal=unilever", "/sku?principal=delmonte", "/dashboard/accuracy?principal=unilever"]
def run(h):
    out = {u: (lambda r: f"{r.status_code}:{sig(r)}")(h.call("admin", "GET", u)) for u in REAL}
    print("SIGS", json.dumps(out))
    PV = {"X-Data-Mode": "preview"}
    r = h.call("admin", "GET", "/dashboard?principal=delmonte", headers=PV).json()
    print("PREVIEW-HEADER dashboard delmonte demonstration key present:", "demonstration" in r)
    r = h.call("admin", "GET", "/recommendations?principal=delmonte", headers=PV).json()
    op = r.get("order_plan") or {}
    print("PREVIEW-HEADER recs delmonte order_plan keys:", list(op)[:8], "items:", len(op.get("items") or []), "top-level items:", len(r.get("items") or []), "data_source:", r.get("data_source"))
    for it in (op.get("items") or [])[:1]:
        print("  item:", json.dumps(it)[:420])
    for u in ("/demo/index?principal=delmonte", "/demo/totals"):
        print("flag state endpoint", u, h.call("admin", "GET", u).status_code)
