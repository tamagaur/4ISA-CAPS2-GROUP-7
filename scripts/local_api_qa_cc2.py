import json
def run(h):
    for q in ("period=2023-12&compare_period=2022-12", "period=2025-06&compare_period=2024-06"):
        j = h.call("admin", "GET", f"/dashboard/class-changes?principal=delmonte&{q}").json()["principals"][0]
        print("##", q, "keys:", [k for k in j if not isinstance(j[k], list)][:30])
        for k, v in j.items():
            if isinstance(v, list):
                print(f"  {k}: n={len(v)}")
                for it in v[:2]:
                    print("     ", json.dumps(it)[:430])
        for k in ("entered_revenue", "left_revenue", "note", "message", "reason", "compare_reason", "blocked_reason"):
            if k in j: print("  ", k, "=", str(j[k])[:300])
