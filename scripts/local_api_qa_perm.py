import json


def show(label, r, n=330):
    print(f"## {label}: {r.status_code} {r.text[:n]}")


def run(h):
    show("GET /users (admin)", h.call("admin", "GET", "/users"))
    for who in ("admin", "view_only", "decide_only", "no_lp", "bare"):
        r = h.call(who, "GET", "/auth/me")
        j = r.json() if r.status_code == 200 else {}
        print(f"## /auth/me {who}: {r.status_code} perms={sorted(j.get('permissions', []))}")
    uid = {}
    r = h.call("admin", "GET", "/users")
    for who in ("decide_only",):
        import psycopg2, os
        c = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); cur = c.cursor()
        cur.execute("select user_id from app.users where email=%s", (f"qa-{who}@qa-harness.org",)); uid[who] = cur.fetchone()[0]
    show("GET /admin/users/{decide_only}/permissions", h.call("admin", "GET", f"/admin/users/{uid['decide_only']}/permissions"), 700)
    # /abc stock_status for no_lp vs view_only
    a = h.call("no_lp", "GET", "/abc?principal=unilever").json()
    b = h.call("view_only", "GET", "/abc?principal=unilever").json()
    def first_with(o):
        items = o.get("items") or o.get("products") or []
        return [{k: v for k, v in i.items() if "stock" in k or "cover" in k or "reorder" in k} for i in items[:2]]
    print("## /abc no_lp   :", json.dumps(first_with(a))[:400])
    print("## /abc view_only:", json.dumps(first_with(b))[:400])
