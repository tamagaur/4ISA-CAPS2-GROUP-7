"""Del Monte: where do category_absent / not_collected points appear, and what value do they carry? Zero would be a fabricated value."""
import json
from collections import Counter

REASONS = ("category_absent", "not_collected")


def walk(o, path, hits, zeros):
    if isinstance(o, dict):
        r = o.get("reason") or o.get("gap_reason")
        if r in REASONS:
            nums = {k: v for k, v in o.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
            hits.append((path, r, nums))
            if any(v == 0 for v in nums.values()):
                zeros.append((path, r, nums))
        for k, v in o.items():
            walk(v, path + "/" + k, hits, zeros)
    elif isinstance(o, list):
        for i, v in enumerate(o[:5000]):
            walk(v, path + "[]", hits, zeros)


def run(h):
    urls = ["/category-trends?principal=delmonte", "/dashboard?principal=delmonte", "/dashboard/pareto?principal=delmonte",
            "/dashboard/yoy?principal=delmonte", "/dashboard/class-changes?principal=delmonte", "/dashboard/product-sales?principal=delmonte",
            "/dashboard/idle-stock?principal=delmonte", "/pareto?principal=delmonte", "/pareto?principal=delmonte&grain=category",
            "/dashboard?principal=delmonte&period=2025-12&start_period=2025-01", "/dashboard/class-changes?principal=delmonte&period=2025-12&compare_period=2023-12",
            "/dashboard/class-changes?principal=delmonte&period=2025-12&start_period=2025-01&compare_period=2024-12&compare_start_period=2024-01",
            "/dashboard?principal=both", "/category-trends?principal=both", "/dashboard/pareto?principal=both"]
    for u in urls:
        r = h.call("admin", "GET", u)
        if r.status_code != 200:
            print(f"{u}: {r.status_code} {r.text[:110]}"); continue
        hits, zeros = [], []
        walk(r.json(), "", hits, zeros)
        c = Counter((p, rs) for p, rs, _ in hits)
        print(f"{u}: 200; reason-bearing points {len(hits)}; with a numeric 0: {len(zeros)}")
        for (p, rs), n in list(c.items())[:4]:
            ex = next(nums for pp, r2, nums in hits if pp == p and r2 == rs)
            print(f"    {p} [{rs}] x{n}  e.g. numeric fields {ex}")
        for z in zeros[:2]:
            print("    ZERO ->", z)
