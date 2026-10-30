"""The demonstration path through the API with DM_DEMO_ENABLED on: labels, forbidden accuracy fields, permission gating, and isolation from real answers."""
import hashlib, json, os, re

ACCURACY = re.compile(r"(^|_)(mape|mase|wape|confidence|conf_lower|conf_upper|lower_bound|upper_bound|ci_)", re.I)
ORIGINS_OK = {"real_copy", "interpolated", "bridged", "backcast", "forward_filled", "generated_months_of_cover"}


def scan(o, path, bad, origins, flags):
    if isinstance(o, dict):
        for k, v in o.items():
            if ACCURACY.search(k) and v not in (None, [], {}):
                bad.append((path + "/" + k, str(v)[:40]))
            if k == "origin" and isinstance(v, str):
                origins.add(v)
            if k in ("demonstration", "data_source"):
                flags.add(f"{k}={v}")
            scan(v, path + "/" + k, bad, origins, flags)
    elif isinstance(o, list):
        for v in o[:3000]:
            scan(v, path + "[]", bad, origins, flags)


def sig(r): return hashlib.md5(r.content).hexdigest()[:10]


def run(h):
    print("DM_DEMO_ENABLED =", os.environ.get("DM_DEMO_ENABLED"))
    idx = h.call("admin", "GET", "/demo/index?principal=delmonte")
    print("## /demo/index delmonte:", idx.status_code, idx.text[:200])
    ij = idx.json() if idx.status_code == 200 else {}
    series = ij.get("series") or ij.get("items") or []
    key = (series[0].get("key") or series[0].get("category_path")) if series else None
    print("   n series:", len(series), "first key:", key)
    for u in ["/demo/index?principal=delmonte", "/demo/index?principal=unilever", f"/demo/series?principal=delmonte&key={key}", "/demo/totals",
              "/dashboard?principal=delmonte", "/recommendations?principal=delmonte", "/policy-comparison?principal=delmonte",
              f"/forecast/{key}?principal=delmonte&category={key}", "/category-trends?principal=delmonte", "/dashboard?principal=unilever",
              "/recommendations?principal=unilever"]:
        for who in ("admin", "no_lp"):
            r = h.call(who, "GET", u)
            bad, origins, flags = [], set(), set()
            if r.status_code == 200:
                scan(r.json(), "", bad, origins, flags)
            print(f"## {who:7s} {u[:70]:70s} {r.status_code} flags={sorted(flags)[:3]} origins={sorted(origins)} {'ACCURACY FIELDS: ' + str(bad[:3]) if bad else ''} {'unknown origin ' + str(origins - ORIGINS_OK) if origins - ORIGINS_OK else ''}")
    from urllib.parse import quote
    PV = {"X-Data-Mode": "preview"}
    cat = "BEVERAGE"
    print("## --- with the preview opt-in (flag on):")
    for who in ("admin", "view_only", "no_lp"):
        for u in ("/dashboard?principal=delmonte", "/recommendations?principal=delmonte", "/policy-comparison?principal=delmonte",
                  f"/forecast/{quote(cat, safe='')}?principal=delmonte&category={quote(cat, safe='')}", "/category-trends?principal=delmonte", "/pareto?principal=delmonte"):
            r = h.call(who, "GET", u, headers=PV)
            bad, origins, flags = [], set(), set()
            body = r.json() if r.status_code == 200 else {}
            if r.status_code == 200:
                scan(body, "", bad, origins, flags)
            dm = body.get("demonstration") if isinstance(body, dict) else None
            extra = ""
            if u.startswith("/dashboard") and isinstance(dm, dict):
                op = dm.get("order_plan") or {}
                extra = f" demonstration keys={list(dm)[:8]} order_plan.available={op.get('available')} items={len(op.get('items') or [])} policy_comparison={'yes' if dm.get('policy_comparison') else 'no'}"
            if u.startswith("/recommendations") and isinstance(body, dict):
                extra = f" available={(body.get('order_plan') or {}).get('available')} items={len(body.get('items') or [])} demonstration={body.get('demonstration')} data_source={body.get('data_source')}"
            print(f"## {who:9s} {u[:62]:62s} {r.status_code} flags={sorted(flags)[:2]} origins={sorted(origins)}{extra}")
            acc = [b for b in bad if not any(t in b[0] for t in ("mase_gate", "slope_confidence"))]
            if acc and r.status_code == 200 and "demonstration" in str(flags):
                print("     ACCURACY-LIKE FIELDS IN A DEMONSTRATION RESPONSE:", acc[:4])
    # real figures must not move with the flag
    r = h.call("admin", "GET", "/dashboard?principal=unilever").json()
    print("## unilever weeks_of_cover with the flag on:", (r.get("kpis", {}).get("weeks_of_cover") or {}).get("value"))
    for u in ("/dashboard?principal=unilever", "/forecast/21015692?principal=unilever", "/pareto?principal=unilever"):
        a = h.call("admin", "GET", u); b = h.call("admin", "GET", u, headers=PV)
        print(f"## preview vs real {u}: real {sig(a)} preview {sig(b)} differ={sig(a) != sig(b)}")
