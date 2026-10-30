import json
def run(h):
    for who, url in (("admin", "/dashboard?principal=unilever&period=2026-02"), ("admin", "/dashboard?principal=unilever"), ("admin", "/dashboard?principal=both&period=2026-02")):
        r = h.call(who, "GET", url); j = r.json()
        print("##", url, r.status_code)
        k = j.get("kpis", {})
        print("  kpis.weeks_of_cover:", json.dumps(k.get("weeks_of_cover"))[:500])
        print("  kpis.weeks_of_cover_range_end:", json.dumps(k.get("weeks_of_cover_range_end"))[:200])
        inv = j.get("inventory", {})
        print("  inventory keys:", list(inv)[:12])
        print("  inventory.weeks_of_cover:", json.dumps(inv.get("weeks_of_cover"))[:200], "| cover_series[-2:]:", json.dumps((inv.get("cover_series") or [])[-2:])[:300])
        for key in j:
            if "cover" in key.lower():
                print("  top-level", key, json.dumps(j[key])[:200])
