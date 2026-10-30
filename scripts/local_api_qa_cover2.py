import os, psycopg2
def run(h):
    items = h.call("admin", "GET", "/recommendations?principal=unilever").json()["items"]
    c = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); cur = c.cursor()
    from backend.routers.recommendations import AVG_DAYS_PER_MONTH, SKU_COVER_HISTORY_MONTHS
    cur.execute("select distinct calendar_month from unilever_sku_demand_fact_real where calendar_month<='2026-02' order by 1 desc limit %s", (SKU_COVER_HISTORY_MONTHS,))
    months = [r[0] for r in cur.fetchall()]
    print("window", months[-1], "..", months[0], "n=", len(months), "AVG_DAYS_PER_MONTH", AVG_DAYS_PER_MONTH)
    shown = 0
    for i in items:
        if i.get("days_of_cover") is None or i.get("current_stock") in (None, 0):
            continue
        cur.execute("select coalesce(sum(quantity_sold),0) from unilever_sku_demand_fact_real d join product_dimension pd using(product_key) where pd.sku_code=%s and calendar_month = any(%s)", (i["sku_id"], months))
        tot = float(cur.fetchone()[0]); avg = tot / len(months)
        hand = round(float(i["current_stock"]) / (avg / float(AVG_DAYS_PER_MONTH)), 1) if avg > 0 else None
        print(f"sku {i['sku_id']}: stock {i['current_stock']:.0f} pcs, 12-mo sales {tot:.0f} pcs -> avg {avg:.1f}/mo; hand {hand} days; API {i['days_of_cover']} days; match={hand == i['days_of_cover']}")
        shown += 1
        if shown == 3: break
    # also: any pesos-looking fields still on the item?
    print("item keys with 'peso'/'value'/'cost':", sorted(k for k in items[0] if any(t in k for t in ("peso", "value", "cost"))))
