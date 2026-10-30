import os, psycopg2


def s(r, n=200):
    return f"{r.status_code} {r.text[:n]}"


def run(h):
    c = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); cur = c.cursor()
    cur.execute("select user_id, email from app.users where email like 'qa-%@qa-harness.org'")
    uid = {e.split("@")[0][3:]: u for u, e in cur.fetchall()}
    items = h.call("admin", "GET", "/recommendations?principal=unilever").json()["items"]
    pend = [i["recommendation_key"] for i in items if i["status"] == "pending" and (i.get("plan_q_i") or 0) > 0]
    body = {"status": "accepted", "reviewed": True}
    # 1. admin ticks off lp.decide for decide_only (lp.view stays removed): next request
    print("PUT decide_only lp.decide off:", s(h.call("admin", "PUT", f"/admin/users/{uid['decide_only']}/permissions",
          {"role": "staff", "overrides": {"lp.view": False}})))
    print("  PATCH now :", s(h.call("decide_only", "PATCH", f"/recommendations/{pend[0]}", body), 120))
    print("  GET recs  :", s(h.call("decide_only", "GET", "/recommendations?principal=unilever"), 120))
    print("  GET /dashboard (cached entry from before?) LP keys:", "lp_safety_stock_units" in h.call("decide_only", "GET", "/dashboard?principal=unilever").text)
    # 2. grant lp.decide to a user with lp.view removed AND dashboard.view removed -> can they reach the dashboard LP?
    print("PUT bare: lp.decide only:", s(h.call("admin", "PUT", f"/admin/users/{uid['bare']}/permissions",
          {"role": "staff", "overrides": {k: False for k in ["dashboard.view","abc.view","forecast.view","category_trends.view","sku.view","lp.view"]} | {"lp.decide": True}})))
    for path in ("/auth/me", "/recommendations?principal=unilever", "/dashboard?principal=unilever", "/policy-comparison?principal=unilever",
                 "/inventory/current?principal=unilever", "/dashboard/error-decomposition?principal=unilever", "/sku?principal=unilever", "/abc?principal=unilever"):
        print(f"  bare(lp.decide only) GET {path}:", s(h.call("bare", "GET", path), 90))
    # 3. the PUT with lp.view=F, lp.decide=T: what is stored vs effective
    print("PUT no_lp lp.view=F,lp.decide=T:", s(h.call("admin", "PUT", f"/admin/users/{uid['no_lp']}/permissions",
          {"role": "staff", "overrides": {"lp.view": False, "lp.decide": True}}), 300))
    print("  GET perms:", s(h.call("admin", "GET", f"/admin/users/{uid['no_lp']}/permissions"), 400))
    print("  audit-log tail:", [ (a.get('action'), (a.get('details') or '')[:90]) for a in h.call("admin","GET","/audit-log?limit=3").json().get('items', h.call("admin","GET","/audit-log?limit=3").json())[:3]] if True else "")
