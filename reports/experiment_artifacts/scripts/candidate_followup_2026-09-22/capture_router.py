"""Run scripts/run_baseline_forecast.py main() down its --write path on a READ-ONLY session, capturing every
Forecast_Result upsert instead of executing it. Report CSV/MD writers are stubbed (no repo files touched).
Usage: python capture_router.py <out.json>"""
import json, os, sys
OUT, CAP = os.path.abspath(sys.argv[1]), []
import psycopg2
sys.path.insert(0, r"C:\Users\kyuan\Capstone-Project"); os.chdir(r"C:\Users\kyuan\Capstone-Project")
import scripts.run_baseline_forecast as rbf



class Cur:
    def __init__(self, cur, conn): self._c, self.connection = cur, conn
    def execute(self, sql, params=None):
        head = sql.lstrip().split(None, 1)[0].upper()
        if head in ("INSERT", "DELETE", "UPDATE", "TRUNCATE", "DROP", "ALTER", "CREATE"):
            if head == "INSERT": CAP.append([str(p) if i == 1 else p for i, p in enumerate(params)])
            else: raise RuntimeError(f"unexpected write intercepted: {head}")
            return
        return self._c.execute(sql, params)
    def __getattr__(self, k): return getattr(self._c, k)


class Conn:
    def __init__(self, conn): self._c = conn; self.autocommit = True
    def cursor(self): return Cur(self._c.cursor(), self)
    def commit(self): pass
    def rollback(self): pass
    def close(self): self._c.close()


def connect():
    rbf.load_dotenv(r"C:\Users\kyuan\Capstone-Project\.env", override=False)
    c = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); c.set_session(readonly=True, autocommit=True)
    return Conn(c)


rbf.connect = connect
_fd, _ft = rbf.fetch_demand, rbf.fetch_tier_a
def _dump_demand(cur):
    d = _fd(cur); d.to_pickle(OUT.replace(".json", "_demand.pkl")); return d
def _dump_tier(cur, period):
    t = _ft(cur, period); t.to_pickle(OUT.replace(".json", "_tier_a.pkl")); return t
rbf.fetch_demand, rbf.fetch_tier_a = _dump_demand, _dump_tier
rbf._write_csv = lambda *a, **k: None
rbf._write_md = lambda *a, **k: None
sys.argv = ["run_baseline_forecast.py", "--write"]
with open(os.devnull, "w") as dn:
    so = sys.stdout; sys.stdout = dn
    try: rbf.main()
    finally: sys.stdout = so
json.dump(CAP, open(OUT, "w"), default=str)
print("captured upserts:", len(CAP))
