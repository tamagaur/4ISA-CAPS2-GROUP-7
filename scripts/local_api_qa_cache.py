"""The response cache (backend/response_cache.py) across users, data changes and its 64-entry cap."""
import concurrent.futures as cf
import hashlib
import json
import os

import psycopg2

from backend import response_cache as rc


def sig(r):
    return hashlib.md5(r.content).hexdigest()[:10]


def sqlx(q, args=None):
    c = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); c.autocommit = True
    cur = c.cursor(); cur.execute(q, args)
    out = cur.fetchall() if cur.description else None
    c.close(); return out


CACHED = ["/abc?principal=unilever", "/category-trends?principal=unilever", "/dashboard?principal=unilever",
          "/dashboard/pareto?principal=unilever", "/dashboard/yoy?principal=unilever", "/dashboard/class-changes?principal=unilever",
          "/dashboard/accuracy?principal=unilever", "/dashboard/error-decomposition?principal=unilever",
          "/dashboard/error-decomposition/aggregate?principal=unilever", "/dashboard/error-decomposition/concentration?principal=unilever",
          "/dashboard/idle-stock?principal=unilever", "/dashboard/product-sales?principal=unilever", "/dashboard/forecast-runs",
          "/fsn?principal=unilever", "/pareto?principal=unilever", "/recommendations?principal=unilever", "/sku?principal=unilever"]


def run(h):
    print("## 1. does each cached route actually hit on a repeat (view_only)?")
    rc.invalidate()
    nohit = []
    for p in CACHED:
        h.call("view_only", "GET", p); s0 = rc.stats()["hits"]; h.call("view_only", "GET", p)
        if rc.stats()["hits"] == s0:
            nohit.append(p)
    print("   routes that did NOT hit on the repeat:", nohit or "none", "| entries", rc.stats()["entries"])

    print("## 2. same-permission users get identical bytes; warm == fresh (user-dependent content would differ)")
    # a second view_only identity
    from scripts.local_api_qa import QA_PASSWORD
    from backend.auth_utils import hash_password
    sqlx("delete from app.users where email='qa-view_two@qa-harness.org'")
    uid = sqlx("insert into app.users (email,password_hash,full_name,role) values ('qa-view_two@qa-harness.org',%s,'QA two','staff') returning user_id", (hash_password(QA_PASSWORD),))[0][0]
    h.tokens["view_two"] = h.client.post("/auth/login", json={"email": "qa-view_two@qa-harness.org", "password": QA_PASSWORD}).json()["access_token"]
    diffs = []
    for p in CACHED:
        rc.invalidate(); a = sig(h.call("view_only", "GET", p))
        rc.invalidate(); b = sig(h.call("view_two", "GET", p))
        rc.invalidate(); h.call("view_only", "GET", p); w = sig(h.call("view_two", "GET", p))   # view_two served view_only's cached entry
        if not (a == b == w):
            diffs.append((p, a, b, w))
    print("   differing:", diffs or "none")

    print("## 3. permission isolation, both orders, for every cached route: view_only(lp) vs no_lp vs decide_only")
    bad = []
    for first, second in (("view_only", "no_lp"), ("no_lp", "view_only"), ("decide_only", "no_lp"), ("no_lp", "decide_only")):
        for p in CACHED:
            rc.invalidate(); h.call(first, "GET", p); r2 = h.call(second, "GET", p)
            rc.invalidate(); r2f = h.call(second, "GET", p)
            if r2.status_code != r2f.status_code or sig(r2) != sig(r2f):
                bad.append((first, second, p, r2.status_code, r2f.status_code))
    print("   cross-user differences warm vs fresh:", bad or "none")

    print("## 4. staleness: does the data version move when data changes?")
    url = "/dashboard?principal=unilever"
    for _ in range(3):
        h.call("view_only", "GET", url)          # get past the cold-start (first requests are never cached)

    def served_from_cache(change):
        rc.invalidate(); h.call("view_only", "GET", url); h.call("view_only", "GET", url)
        before = rc.stats()["hits"]
        h.call("view_only", "GET", url)
        assert rc.stats()["hits"] == before + 1, "route did not cache"
        change()
        before = rc.stats()["hits"]
        h.call("view_only", "GET", url)
        return rc.stats()["hits"] == before + 1      # True = the old entry was served after the change
    ecols = [r[0] for r in sqlx("select column_name from information_schema.columns where table_name='etl_load_event' and is_identity='NO' and is_generated='NEVER' order by ordinal_position")]
    def ev_sql(tag, dry, rows):
        sel = ", ".join({"run_id": f"'qa-{tag}'", "finished_at": "now()", "started_at": "now()", "dry_run": dry,
                         "real_rows_added": str(rows), "real_rows_removed": "0", "fill_rows_added": "0", "fill_rows_removed": "0"}.get(c, c) for c in ecols)
        return (f"insert into etl_load_event ({', '.join(ecols)}) select {sel} from etl_load_event "
                "where not dry_run and slice is not null order by load_event_key desc limit 1")
    ev = lambda tag, dry, rows: ev_sql(tag, dry, rows)
    print("   (a) a real load event (real_rows_added=5)     served stale:", served_from_cache(lambda: sqlx(ev("a", "false", 5))))
    print("   (b) a dry-run load event                      served stale:", served_from_cache(lambda: sqlx(ev("b", "true", 5))), "(expected True: a dry run changes no data)")
    print("   (c) a load event that added/removed 0 rows    served stale:", served_from_cache(lambda: sqlx(ev("c", "false", 0))), "(expected True: no data changed)")
    # ABC re-run alone: abc_classification.computed_at moves, tier changes. View the latest period's t12m_new rows.
    def abc_url_sig():
        return sig(h.call("view_only", "GET", "/abc?principal=unilever"))
    def abc_change(tier):
        sqlx("update abc_classification set tier=%s, computed_at=now() where classification_key=(select classification_key from abc_classification "
             "where principal='unilever' and method='t12m_new' and classification_period=(select max(classification_period) from abc_classification where method='t12m_new') order by classification_key limit 1)", (tier,))
    for _ in range(3):
        h.call("view_only", "GET", "/abc?principal=unilever")
    for n, tier in ((1, "C"), (2, "B")):
        rc.invalidate(); h.call("view_only", "GET", "/abc?principal=unilever"); h.call("view_only", "GET", "/abc?principal=unilever")
        warm = abc_url_sig()
        abc_change(tier)
        served = abc_url_sig()
        rc.invalidate(); fresh = abc_url_sig()
        print(f"   (d{n}) ABC row changed to {tier} (computed_at=now): served-after-change == fresh? {served == fresh}  (changed from warm? {warm != fresh})")
    print("   mart.refresh_status stale flags:", sqlx("select stale, planning_stale from mart.refresh_status"))

    print("## 5. the 64-entry cap under concurrent load (8 threads, 90 distinct keys)")
    from fastapi.testclient import TestClient
    periods = [f"{y}-{m:02d}" for y in (2023, 2024, 2025) for m in range(1, 13)] + ["2026-01", "2026-02"]
    urls = [f"/dashboard/pareto?principal=unilever&period={p}" for p in periods] + [f"/dashboard/yoy?principal=unilever&period={p}" for p in periods]         + [f"/dashboard/product-sales?principal=unilever&period={p}" for p in periods[:20]]
    rc.invalidate()
    for _ in range(3):
        h.call("view_only", "GET", urls[0])
    truth = {}
    for u in urls:
        rc.invalidate(); truth[u] = sig(h.call("view_only", "GET", u))
    rc.invalidate()
    def worker(chunk):
        c = TestClient(h.app, raise_server_exceptions=False)
        out = []
        for u in chunk * 2:
            r = c.get(u, headers={"Authorization": "Bearer " + h.tokens["view_only"]})
            out.append((u, r.status_code, sig(r)))
        return out
    chunks = [urls[i::8] for i in range(8)]
    with cf.ThreadPoolExecutor(8) as ex:
        results = [x for part in ex.map(worker, chunks) for x in part]
    wrong = [(u, st) for u, st, sg in results if st != 200 or sg != truth[u]]
    st = rc.stats()
    print(f"   requests {len(results)}, wrong/non-200: {len(wrong)} {wrong[:3]}; cache entries after: {st['entries']} (cap {rc.MAX_ENTRIES}), hits {st['hits']}, misses {st['misses']}")
