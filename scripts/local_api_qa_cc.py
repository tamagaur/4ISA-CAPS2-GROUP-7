import json
def run(h):
    for q in ("period=2025-12&compare_period=2024-12", "period=2025-12&start_period=2025-01&compare_period=2024-12&compare_start_period=2024-01",
              "period=2025-12&compare_period=2023-12", "period=2023-12&compare_period=2022-12", "period=2024-06&compare_period=2023-06", "period=2025-06&compare_period=2024-06"):
        r = h.call("admin", "GET", f"/dashboard/class-changes?principal=delmonte&{q}")
        j = r.json()
        print("##", q, r.status_code, "top keys:", list(j)[:14])
        for k, v in j.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                print(f"   {k}: n={len(v)} sample={json.dumps(v[0])[:330]}")
            elif not isinstance(v, (list, dict)):
                print(f"   {k}: {str(v)[:160]}")
