"""ABC re-run alone vs the cache: start from freshly refreshed marts (stale flags false), change abc_classification twice."""
import hashlib, os
import psycopg2
from analytics import marts
from backend import response_cache as rc


def sig(r): return hashlib.md5(r.content).hexdigest()[:10]
def sqlx(q, a=None):
    c = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); c.autocommit = True; cur = c.cursor(); cur.execute(q, a)
    out = cur.fetchall() if cur.description else None; c.close(); return out


def run(h):
    marts.refresh_marts(os.environ["SUPABASE_DB_URL"], "qa_abc_probe")
    print("flags after refresh (stale, planning_stale):", sqlx("select stale, planning_stale from mart.refresh_status"))
    for _ in range(3): h.call("view_only", "GET", "/dashboard?principal=unilever")   # a mart reader probes the marts: only then do cached routes cache
    u = "/abc?principal=unilever"
    for _ in range(3): h.call("view_only", "GET", u)
    for n, tier in ((1, "C"), (2, "B"), (3, "A")):
        rc.invalidate(); h.call("view_only", "GET", u); w0 = rc.stats()["hits"]; h.call("view_only", "GET", u); warm_hit = rc.stats()["hits"] == w0 + 1
        sqlx("update abc_classification set tier=%s, computed_at=now() where classification_key=(select classification_key from abc_classification "
             "where principal='unilever' and method='t12m_new' and classification_period=(select max(classification_period) from abc_classification where method='t12m_new') order by classification_key limit 1)", (tier,))
        st0 = rc.stats()["hits"]
        served = sig(h.call("view_only", "GET", u)); was_hit = rc.stats()["hits"] == st0 + 1
        rc.invalidate(); fresh = sig(h.call("view_only", "GET", u))
        print(f"change {n} (tier->{tier}): flags now {sqlx('select stale, planning_stale from mart.refresh_status')[0]}; warm repeat was a hit: {warm_hit}; served == fresh? {served == fresh}; request after the change was a cache hit: {was_hit}")
