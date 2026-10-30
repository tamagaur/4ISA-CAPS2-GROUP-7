"""Every GET route x 5 identities: status, and whether LP figures (safety stock, reorder point, order quantity, target) are present."""
import json
import re

import psycopg2
import os

LP_KEY = re.compile(r"(safety_stock|reorder_point|^ss_i$|^rop_i$|^q_i$|plan_q_i|target_stock|order_qty|total_order|recommended_q|order_plan|days_of_cover|stock_status)", re.I)
WHO = ["admin", "view_only", "decide_only", "no_lp", "bare"]


def keys_in(obj, found, depth=0):
    if depth > 12:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if LP_KEY.search(k) and v not in (None, [], {}, 0):
                found.add(k)
            keys_in(v, found, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:50]:
            keys_in(v, found, depth + 1)


def run(h):
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); cur = conn.cursor()
    cur.execute("select sku_code from product_dimension pd join forecast_result fr using(product_key) where principal='unilever' and fr.forecast_date='2026-03-01' limit 1")
    sku = cur.fetchone()[0]
    sample = {"sku_id": sku, "sku_code": sku}
    o = h.app.openapi()
    rows = []
    for path, m in sorted(o["paths"].items()):
        if "get" not in m or path in ("/health", "/status") or path.startswith("/auth"):
            continue
        params = {p["name"] for p in m["get"].get("parameters", [])}
        url = path
        for k, v in sample.items():
            url = url.replace("{" + k + "}", v)
        if "{" in url:
            url = re.sub(r"\{[^}]+\}", "1", url)
        q = "?principal=unilever" if "principal" in params else ""
        if path == "/demo/series":
            q = "?principal=unilever&key=" + sku
        cells = []
        for who in WHO:
            r = h.call(who, "GET", url + q)
            tag = str(r.status_code)
            if r.status_code == 200:
                found = set()
                try:
                    keys_in(r.json(), found)
                except Exception:
                    pass
                tag += " LP:" + ("Y(" + ",".join(sorted(found))[:48] + ")" if found else "-")
            elif r.status_code == 403:
                try:
                    tag += " " + r.json().get("permission", "")
                except Exception:
                    pass
            cells.append(tag)
        rows.append((url + q, cells))
    print("| route | " + " | ".join(WHO) + " |")
    for url, cells in rows:
        print("| " + url + " | " + " | ".join(cells) + " |")
