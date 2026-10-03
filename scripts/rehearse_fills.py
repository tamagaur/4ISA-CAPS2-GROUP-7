"""scripts/rehearse_fills.py - rehearse the DEC-31 fill step on a scratch copy of public, and verify its guardrails.

  python -m scripts.rehearse_fills --schema ssm_fills --build     clone public (server side) + apply pending migrations
                                                                  through the ledger (0032, 0033, 0038 ...) + seed etl_coverage
  python -m scripts.fill_missing   --schema ssm_fills             the fill step itself (run it twice: the 2nd writes nothing)
  python -m scripts.rehearse_fills --schema ssm_fills --verify    guardrails, scratch vs public (public read-only)

The clone: every public base table except the auth tables and old backups (no credential is copied), LIKE ... INCLUDING
DEFAULTS/IDENTITY/INDEXES/CONSTRAINTS + INSERT ... SELECT, identity sequences mirrored to public's positions, and
public's views recreated against the clone (pg_get_viewdef). Foreign keys are not cloned. Public is only ever read, in
a BEGIN; SET TRANSACTION READ ONLY; ... ; ROLLBACK transaction - never a session-level setting (pooler leak).
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import Connection, create_engine, text

FACT_TABLES = ("sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact", "unilever_sku_demand_fact")
REAL_VIEWS = {"sales_fact_real": "sales_fact", "purchase_fact_real": "purchase_fact", "salesreturn_fact_real": "salesreturn_fact",
              "sellout_fact_real": "sellout_fact", "inventory_fact_real": "inventory_fact",
              "unilever_sku_demand_fact_real": "unilever_sku_demand_fact"}
NOT_CLONED = {"users", "user_session", "auth_token", "user_permission_override", "product_dimension_backup_20260918"}
OUTPUT_TABLES = ("forecast_result", "abc_classification", "lp_recommendation", "sku_traits", "sku_segment")  # models' outputs


def _read_only(conn: Connection) -> None:
    conn.execute(text("SET TRANSACTION READ ONLY"))


def build(engine, schema: str) -> None:
    from scripts.run_canonical_load import _require_scratch_schema, ensure_scratch_schema
    _require_scratch_schema(schema)
    with engine.connect() as conn:
        _read_only(conn)
        if conn.execute(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name = :s"), {"s": schema}).scalar():
            raise SystemExit(f"schema {schema} already exists - drop it first (this script never drops a schema)")
        tables = [r[0] for r in conn.execute(text("SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace "
                                                  "AND c.relkind = 'r' ORDER BY 1")) if r[0] not in NOT_CLONED]
        views = conn.execute(text("SELECT c.relname, pg_get_viewdef(c.oid, true) FROM pg_class c "
                                  "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'v' ORDER BY 1")).all()
        conn.rollback()
    print(f"[build] cloning {len(tables)} tables and {len(views)} views into {schema}")
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL statement_timeout = '15min'"))
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        for t in tables:
            conn.execute(text(f"CREATE TABLE {schema}.{t} (LIKE public.{t} INCLUDING DEFAULTS INCLUDING IDENTITY "
                              f"INCLUDING INDEXES INCLUDING CONSTRAINTS)"))
            n = conn.execute(text(f"INSERT INTO {schema}.{t} OVERRIDING SYSTEM VALUE SELECT * FROM public.{t}")).rowcount
            for (col,) in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
                                            "AND table_name = :t AND is_identity = 'YES'"), {"t": t}):
                seq = conn.execute(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": f"public.{t}", "c": col}).scalar()
                last, called = conn.execute(text(f"SELECT last_value, is_called FROM {seq}")).one()
                conn.execute(text("SELECT setval(pg_get_serial_sequence(:t, :c), :v, :called)"),
                             {"t": f"{schema}.{t}", "c": col, "v": last, "called": called})
            print(f"  {t}: {n} rows")
        conn.execute(text("SET LOCAL search_path TO :s").bindparams(s=schema))
        for name, body in views:
            conn.execute(text(f"CREATE VIEW {name} AS {body}"))
    ensure_scratch_schema(engine, schema, dry_run=False)
    from scripts import load_slices as ls
    with engine.begin() as conn:
        ls._scope(conn, schema)
        print(f"[build] etl_coverage seeded: {ls.refresh_all_coverage(conn)}")


def _fingerprint(conn: Connection, schema: str, table: str, where: str, cols: list[str]) -> tuple:
    row = "ROW(" + ", ".join(f'x."{c}"' for c in cols) + ")::text"
    return conn.execute(text(f"SELECT count(*), md5(COALESCE(string_agg(md5({row}), '' ORDER BY md5({row})), '')) "
                             f"FROM {schema}.{table} x WHERE {where}")).one()


def _cols(conn: Connection, schema: str, table: str) -> list[str]:
    return [r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema = :s "
                                            "AND table_name = :t ORDER BY ordinal_position"), {"s": schema, "t": table})]


def verify(engine, schema: str) -> int:
    """Each check: (name, got, want). A want of None = report only."""
    res = []
    with engine.connect() as conn:
        _read_only(conn)
        conn.execute(text("SET LOCAL statement_timeout = '10min'"))
        # 1. The _Real views: same definition text as public's, same rows, and no fill row in any of them.
        for v, t in REAL_VIEWS.items():
            d_pub = conn.execute(text("SELECT pg_get_viewdef(CAST(:v AS regclass), true)"), {"v": f"public.{v}"}).scalar()
            # deparsed outside the scratch search_path, the clone's table names come back schema-qualified
            d_scr = conn.execute(text("SELECT pg_get_viewdef(CAST(:v AS regclass), true)"),
                                 {"v": f"{schema}.{v}"}).scalar().replace(f"{schema}.", "")
            res.append((f"{v}: definition identical to public's", d_pub == d_scr, True))
            res.append((f"{v}: no fill_source column", "fill_source" in _cols(conn, schema, v), False))
            cols = _cols(conn, "public", t)
            res.append((f"{t}: real rows identical to public's (count, md5)", _fingerprint(conn, schema, t, "NOT x.is_demo", cols)
                        == _fingerprint(conn, "public", t, "NOT x.is_demo", cols), True))
            res.append((f"{v}: rows that are demo", conn.execute(text(f"SELECT count(*) FROM {schema}.{v} WHERE is_demo")).scalar(), 0))
        # 2. Every demo row carries a fill tag; no real row does.
        for t in FACT_TABLES:
            res.append((f"{t}: demo rows without fill_source", conn.execute(text(
                f"SELECT count(*) FROM {schema}.{t} WHERE is_demo AND fill_source IS NULL")).scalar(), 0))
            res.append((f"{t}: real rows with fill_source", conn.execute(text(
                f"SELECT count(*) FROM {schema}.{t} WHERE NOT is_demo AND fill_source IS NOT NULL")).scalar(), 0))
            mcol = "calendar_month" if t == "unilever_sku_demand_fact" else "_period"
            pcol = "'unilever'" if t == "unilever_sku_demand_fact" else "principal"
            res.append((f"{t}: demo rows in a cell that has real rows", conn.execute(text(
                f"SELECT count(*) FROM {schema}.{t} d WHERE d.is_demo AND EXISTS (SELECT 1 FROM {schema}.{t} r "
                f"WHERE NOT r.is_demo AND {pcol.replace('principal', 'r.principal')} = {pcol.replace('principal', 'd.principal')} "
                f"AND r.{mcol} = d.{mcol})")).scalar(), 0))
        # 3. Public's existing demo rows are all still there, unchanged but for the tag (the fill only adds to empty cells).
        for t in FACT_TABLES:
            cols = _cols(conn, "public", t)
            res.append((f"{t}: public's demo rows unchanged in scratch (count, md5)",
                        _fingerprint(conn, schema, t, "x.is_demo AND x.fill_source = 'synthetic_v2'", cols)
                        == _fingerprint(conn, "public", t, "x.is_demo", cols), True))
        # 4. The models' stored outputs are untouched.
        for t in OUTPUT_TABLES:
            cols = _cols(conn, "public", t)
            res.append((f"{t}: identical to public's", _fingerprint(conn, schema, t, "TRUE", cols)
                        == _fingerprint(conn, "public", t, "TRUE", cols), True))
        # 5. Del Monte split: totals equal the real sell-out totals; every row demo.
        res.append(("sku_demand_fill: months whose total differs from real sell-out (amount or quantity)", conn.execute(text(f"""
            SELECT count(*) FROM (SELECT _period, SUM(net_amount) a, SUM(quantity) q FROM {schema}.sellout_fact_real
                                  WHERE principal = 'delmonte' AND _period IN (SELECT _period FROM {schema}.sku_demand_fill) GROUP BY 1) t
            FULL JOIN (SELECT _period, SUM(net_amount) a, SUM(quantity) q FROM {schema}.sku_demand_fill GROUP BY 1) s USING (_period)
            WHERE (t.a, t.q) IS DISTINCT FROM (s.a, s.q)""")).scalar(), 0))
        res.append(("sku_demand_fill: real sell-out months with no split", conn.execute(text(f"""
            SELECT count(*) FROM (SELECT DISTINCT _period FROM {schema}.sellout_fact_real WHERE principal = 'delmonte'
                                  AND _period <= (SELECT max(_period) FROM {schema}.sku_demand_fill)) t
            WHERE _period NOT IN (SELECT _period FROM {schema}.sku_demand_fill)""")).scalar(), 0))
        # 6. Derived receipts: the stored identity holds on every row; flags match signs.
        res.append(("derived_receipt_fact: rows where balance != closing - opening + sold", conn.execute(text(
            f"SELECT count(*) FROM {schema}.derived_receipt_fact WHERE balance_pieces <> closing_pieces - opening_pieces + sold_pieces"
        )).scalar(), 0))
        res.append(("derived_receipt_fact: NaN in any numeric", conn.execute(text(
            f"SELECT count(*) FROM {schema}.derived_receipt_fact WHERE 'NaN' IN (opening_pieces, closing_pieces, sold_pieces, "
            f"balance_pieces, receipt_pieces) OR unit_cost_per_piece = 'NaN' OR receipt_value = 'NaN'")).scalar(), 0))
        # 7. Coverage: report the status grid of the new pairs.
        for p, t in (("unilever", "purchase_fact"), ("unilever", "salesreturn_fact"), ("delmonte", "sku_demand_fill"),
                     ("unilever", "inventory_fact"), ("unilever", "unilever_sku_demand_fact"), ("delmonte", "salesreturn_fact")):
            grid = dict(conn.execute(text(f"SELECT status, count(*) FROM {schema}.etl_coverage WHERE principal = :p AND table_name = :t "
                                          f"GROUP BY 1"), {"p": p, "t": t}).all())
            res.append((f"etl_coverage {p}.{t} status counts", grid, None))
        conn.rollback()
    failed = 0
    for name, got, want in res:
        ok = want is None or got == want
        failed += not ok
        print(f"  {'ok  ' if want is not None and ok else 'FAIL' if not ok else 'info'} {name}: {got}")
    print(f"\n{len(res)} checks, {failed} failed")
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schema", required=True)
    p.add_argument("--build", action="store_true")
    p.add_argument("--verify", action="store_true")
    args = p.parse_args()
    from analytics.config import get_settings
    engine = create_engine(get_settings().supabase_db_url)
    if args.build:
        build(engine, args.schema)
    if args.verify:
        return verify(engine, args.schema)
    return 0


if __name__ == "__main__":
    sys.exit(main())
