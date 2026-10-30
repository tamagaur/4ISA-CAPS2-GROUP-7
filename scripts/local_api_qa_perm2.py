import json, os, psycopg2


def s(r, n=260):
    return f"{r.status_code} {r.text[:n]}"


def run(h):
    c = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); cur = c.cursor()
    cur.execute("select user_id, email from app.users where email like 'qa-%@qa-harness.org'")
    uid = {e.split("@")[0][3:]: u for u, e in cur.fetchall()}
    items = h.call("admin", "GET", "/recommendations?principal=unilever").json()["items"]
    pend = [i for i in items if i["status"] == "pending" and (i.get("plan_q_i") or 0) > 0]
    print("pending positive rows:", len(pend), "first keys", [i["recommendation_key"] for i in pend[:6]])
    k = [i["recommendation_key"] for i in pend[:6]]
    body = {"status": "accepted", "reviewed": True}
    print("## users with 0 decisions yet, hitting PATCH accept:")
    for who, key in (("bare", k[0]), ("no_lp", k[0]), ("view_only", k[0])):
        print(f"  {who:12s} PATCH {key}: ", s(h.call(who, "PATCH", f"/recommendations/{key}", body)))
    r = h.call("decide_only", "PATCH", f"/recommendations/{k[0]}", body)
    print(f"  decide_only  PATCH {k[0]}: ", s(r, 400))
    r2 = h.call("view_only", "GET", f"/recommendations/changes")
    print("  view_only GET /recommendations/changes:", s(r2, 120))
    print("  decide_only GET /recommendations/changes:", s(h.call("decide_only", "GET", "/recommendations/changes"), 120))
    print("  decide_only GET /recommendations (sees its own decision?):",
          [ (i["recommendation_key"], i["status"]) for i in h.call("decide_only","GET","/recommendations?principal=unilever").json()["items"] if i["recommendation_key"]==k[0]])
    print("  decide_only reverse (admin-only):", s(h.call("decide_only", "POST", f"/recommendations/{k[0]}/reverse", {"reason": "qa"}), 160))
    # quantity change by decide_only on another row
    pack = [i for i in pend if i["recommendation_key"] == k[1]][0]
    print("  decide_only quantity-change:", s(h.call("decide_only", "POST", f"/recommendations/{k[1]}/quantity-change", {"quantity": float(pack["plan_q_i"]) , "reviewed": True}), 300))
    # revoke: admin unticks lp.decide for decide_only (keeps lp.view removed)
    pr = h.call("admin", "PUT", f"/admin/users/{uid['decide_only']}/permissions", {"overrides": {"lp.view": False, "lp.decide": False}})
    print("## admin PUT overrides lp.view=F lp.decide=F:", s(pr, 300))
    print("  decide_only now PATCH:", s(h.call("decide_only", "PATCH", f"/recommendations/{k[2]}", body), 160))
    print("  decide_only now GET /recommendations:", s(h.call("decide_only", "GET", "/recommendations?principal=unilever"), 160))
    # the odd override: lp.decide granted, lp.view removed — what does the admin screen store?
    pr = h.call("admin", "PUT", f"/admin/users/{uid['no_lp']}/permissions", {"overrides": {"lp.view": False, "lp.decide": True}})
    print("## admin PUT overrides lp.view=F lp.decide=T on no_lp:", s(pr, 400))
    print("   GET after:", s(h.call("admin", "GET", f"/admin/users/{uid['no_lp']}/permissions"), 400))
    # audit entry for decide_only's decision: who is recorded
