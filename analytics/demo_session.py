"""
analytics.demo_session - what a "demonstration session" on a real database is, and how a connection can tell (2026-11-05, Kelvin's brief).

A demonstration session lets labelled generated March sales (is_demo = true, _src_file = TAG) run through the real monthly batch on
the database behind the pages, and lets one button (scripts/demo_session.py undo) put every table and every definition back exactly as
it was. This module holds only what readers and guards need: the constants, the two definitions that change for the window, and the
questions "is a session open?" and "is the swap in force?". It writes nothing; scripts/demo_session.py does.

WHAT CHANGES FOR THE WINDOW, and nothing else:
  public.unilever_sku_demand_fact_real   the demand view also admits is_demo rows whose _src_file is TAG. Every other is_demo row stays out.
  mart.data_kind(boolean, text)          an is_demo row with no fill_source reads 'real', so the marts count the month (the retired
                                         synthetic_v2 family stays 'generated'). The label stays on the mart row (source_tag
                                         'demo_untagged') and on the fact row (is_demo).
Both are the practice copy's two definitions (scripts/local_pg.py PRACTICE_VIEW_SQL / PRACTICE_KIND_SQL), built here from the live
definitions themselves, so the column list cannot drift from the real view. Both are restored from text saved in the snapshot schema, and
the restore is checked by a fingerprint of EVERY view and function of app, public, mart and demo (definition and privileges).

WHY A WINDOW AND NOT A MIGRATION. A numbered migration would leave a dormant switch in the schema for good, but the runner applies every
pending migration in order and 0075 is pending and not to be applied, so no later migration can be applied alone. The window is
recorded in the database itself (the snapshot schema), opened only by the tool's gates (a passing revert proof, an explicit target flag)
and closed by the revert, which refuses to finish unless the definitions equal what was saved. Decision of 2026-11-05, recorded in STATE.md.

THE WITNESS. permits_labelled_rows() is what the forecast's guard asks (analytics/forecasting/practice_switch): True only when a session
is OPEN in this database and the swap is IN FORCE in it. Read from the connection's own database, never from an environment variable.
"""
from __future__ import annotations

SESSION_TAG = "live_demo"
SNAP_SCHEMA = f"demo_revert_{SESSION_TAG}"          # scripts/demo_revert.snap_schema(SESSION_TAG)
TAG = "qa_synthetic_march"                           # _src_file of the generated rows; backend/practice_copy.GENERATED_TAG reads it too
VIEW = "public.unilever_sku_demand_fact_real"
KIND_FN = "mart.data_kind(boolean, text)"
SCHEMAS = ("app", "public", "mart", "demo")
REAL_ONLY = "WHERE is_demo = false"                  # how the live view's definition ends (read 2026-11-05 on a restored copy of live)
ADMITTING = f"WHERE is_demo = false OR (is_demo = true AND _src_file = '{TAG}'::text)"
KIND_OLD = "WHEN p_fill_source IS NULL OR p_fill_source = 'synthetic_v2' THEN 'generated'"
KIND_NEW = "WHEN p_fill_source IS NULL THEN 'real' WHEN p_fill_source = 'synthetic_v2' THEN 'generated'"

# Every view and function of the four schemas, with its privileges: what "the schema is exactly as it was" means.
DEFINITIONS_FINGERPRINT_SQL = """
    SELECT md5(coalesce(string_agg(x, E'\\n' ORDER BY x), '')), count(*) FROM (
        SELECT 'v:' || n.nspname || '.' || c.relname || ':' || pg_get_viewdef(c.oid, true) || ':' || coalesce(c.relacl::text, '') || ':'
               || coalesce(c.reloptions::text, '') AS x
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('v', 'm') AND n.nspname = ANY(%(schemas)s)
        UNION ALL
        SELECT 'f:' || n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || '):' || pg_get_functiondef(p.oid)
               || ':' || coalesce(p.proacl::text, '')
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE p.prokind IN ('f', 'p') AND n.nspname = ANY(%(schemas)s)
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
    ) t
"""
SESSION_SQL = f"SELECT state, opened_at, opened_by, baseline_rows, baseline_pieces, baseline_cycle, defs_fingerprint FROM {SNAP_SCHEMA}._session"


def definitions_fingerprint(cur) -> tuple[str, int]:
    cur.execute(DEFINITIONS_FINGERPRINT_SQL, {"schemas": list(SCHEMAS)})
    digest, n = cur.fetchone()
    return digest, int(n)


def read_definitions(cur) -> dict:
    """The two live definitions as text, so the window can put them back byte for byte."""
    cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", (VIEW,))
    view = cur.fetchone()[0].strip().rstrip(";")
    cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (KIND_FN,))
    function = cur.fetchone()[0].strip()
    return {"view": view, "function": function}


def admitting_view_sql(original_view: str) -> str:
    """The view's own definition with its one WHERE clause widened. Refuses a definition it does not recognise rather than guess."""
    if original_view.count(REAL_ONLY) != 1:
        raise RuntimeError(f"{VIEW} does not end in {REAL_ONLY!r} exactly once: its definition is not the one this window knows how to widen")
    return f"CREATE OR REPLACE VIEW {VIEW} AS {original_view.replace(REAL_ONLY, ADMITTING)}"


def admitting_function_sql(original_function: str) -> str:
    flat = " ".join(original_function.split())
    if flat.count(KIND_OLD) != 1:
        raise RuntimeError("mart.data_kind is not the definition this window knows how to widen")
    return " ".join(flat.replace(KIND_OLD, KIND_NEW).split())


def restoring_view_sql(original_view: str) -> str:
    return f"CREATE OR REPLACE VIEW {VIEW} AS {original_view}"


def session_row(cur) -> dict | None:
    """The open or closing session recorded in this database, or None. Read-only."""
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{SNAP_SCHEMA}._session",))
    if not cur.fetchone()[0]:
        return None
    cur.execute(SESSION_SQL)
    row = cur.fetchone()
    if row is None:
        return None
    keys = ("state", "opened_at", "opened_by", "baseline_rows", "baseline_pieces", "baseline_cycle", "defs_fingerprint")
    return dict(zip(keys, row))


def is_open(cur) -> bool:
    row = session_row(cur)
    return bool(row and row["state"] == "open")


def swap_in_force(cur) -> bool:
    cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", (VIEW,))
    return f"_src_file = '{TAG}'" in cur.fetchone()[0]


def permits_labelled_rows(cur) -> bool:
    """True only while a session is open in this database AND the widened view is in force in it. What the forecast's guard asks."""
    return is_open(cur) and swap_in_force(cur)
