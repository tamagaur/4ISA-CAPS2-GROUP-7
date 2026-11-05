"""
analytics.demo_session - how a loaded month is recorded, and how a connection can tell (2026-11-06; first written 2026-11-05).

A month of sales that did not come from SSM (the file is generated; SSM has not sent it) is loaded through Data Management with every row labelled
is_demo = true and _src_file = TAG. The labelled rows run through the real monthly batch on the database the pages read, and each load can be rolled
back. This module holds what readers and guards need: the constants, the two definitions that change while labelled rows are loaded, the CHECKPOINT
registry, and the questions "is the labelled-row window in force?" and "which months are loaded?". It writes nothing; scripts/demo_session.py does.

CHECKPOINTS (the history that makes a rollback possible). Before a month loads, one checkpoint is taken: a schema `demo_revert_m<YYYYMM>` holding a copy of
every table the load can change (scripts/demo_revert.UNCOPIED lists the few large tables a sales month never touches, which are fingerprinted but not
copied), a fingerprint of EVERY table, the text of the two definitions below, and a `_session` row. The checkpoint for a month is "the system as it was
before that month". Rolling a month back restores that checkpoint and, with it, removes every later month, because they were loaded on top. Up to
MAX_CHECKPOINTS stay; once one more month has loaded successfully the oldest is dropped (never before: a month that fails must not cost the oldest point), and its month can then no longer be rolled back (the page says so). The registry IS the
schemas: nothing is kept in an environment variable, a file or a process, so a restart, another browser or another server sees the same history.

WHAT CHANGES WHILE LABELLED ROWS ARE LOADED, and nothing else:
  public.unilever_sku_demand_fact_real   the demand view also admits is_demo rows whose _src_file is TAG. Every other is_demo row stays out.
  mart.data_kind(boolean, text)          an is_demo row with no fill_source reads 'real', so the marts count the month (the retired
                                         synthetic_v2 family stays 'generated'). The label stays on the mart row (source_tag
                                         'demo_untagged') and on the fact row (is_demo).
Both are the practice copy's two definitions (scripts/local_pg.py PRACTICE_VIEW_SQL / PRACTICE_KIND_SQL), built here from the live definitions
themselves, so the column list cannot drift from the real view. Each checkpoint keeps the definitions as they were when it was taken; a rollback puts
them back and checks the restore by a fingerprint of EVERY view and function of app, public, mart and demo (definition and privileges).

WHY A WINDOW AND NOT A MIGRATION. A numbered migration would leave a dormant switch in the schema for good, but the runner applies every pending
migration in order and 0075 is pending and not to be applied, so no later migration can be applied alone. Decision of 2026-11-05, recorded in STATE.md.

THE WITNESS. permits_labelled_rows() is what the forecast's guard asks (analytics/forecasting/practice_switch): True only while the widened view is in
force in THIS database. Read from the connection's own database, never from an environment variable.
"""
from __future__ import annotations

TAG = "qa_synthetic_march"                           # _src_file of the generated rows; backend/practice_copy.GENERATED_TAG reads it too
VIEW = "public.unilever_sku_demand_fact_real"
KIND_FN = "mart.data_kind(boolean, text)"
SCHEMAS = ("app", "public", "mart", "demo")
REAL_ONLY = "WHERE is_demo = false"                  # how the live view's definition ends (read 2026-11-05 on a restored copy of live)
ADMITTING = f"WHERE is_demo = false OR (is_demo = true AND _src_file = '{TAG}'::text)"
KIND_OLD = "WHEN p_fill_source IS NULL OR p_fill_source = 'synthetic_v2' THEN 'generated'"
KIND_NEW = "WHEN p_fill_source IS NULL THEN 'real' WHEN p_fill_source = 'synthetic_v2' THEN 'generated'"

CHECKPOINT_PREFIX = "demo_revert_m"
MAX_CHECKPOINTS = 2                                  # loaded months that can still be rolled back (a checkpoint is ~106 MB on the live database: 383 MB read 2026-11-05, with the older session's copy inside it)
CHECKPOINTS_SQL = "SELECT nspname FROM pg_namespace WHERE nspname ~ %s ORDER BY nspname"
SESSION_COLUMNS = ("state", "month", "taken_at", "taken_by", "baseline_cycle", "baseline_rows", "baseline_pieces", "defs_fingerprint",
                   "loaded_at", "loaded_by", "file_name", "file_basis", "sales_rows", "plan_cycle", "plan_rows", "plan_pieces", "note")

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


def month_tag(month: str) -> str:
    """'2026-03' -> 'm202603': the tag scripts/demo_revert names a snapshot by."""
    if not (isinstance(month, str) and len(month) == 7 and month[4] == "-" and month[:4].isdigit() and month[5:].isdigit() and 1 <= int(month[5:]) <= 12):
        raise ValueError(f"not a month: {month!r}")
    return "m" + month.replace("-", "")


def checkpoint_schema(month: str) -> str:
    return f"demo_revert_{month_tag(month)}"


def next_month(month: str) -> str:
    year, num = int(month[:4]), int(month[5:7])
    return f"{year + (num == 12)}-{num % 12 + 1:02d}"


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


def swap_in_force(cur) -> bool:
    cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", (VIEW,))
    view = cur.fetchone()[0]
    return isinstance(view, str) and f"_src_file = '{TAG}'" in view


def permits_labelled_rows(cur) -> bool:
    """True only while the widened view is in force in this database. What the forecast's guard asks."""
    return swap_in_force(cur)


def checkpoints(cur) -> list[dict]:
    """The checkpoints held in this database, oldest month first. Read-only. A schema without a readable `_session` row is reported with state
    'unreadable' so it is never silently ignored."""
    cur.execute(CHECKPOINTS_SQL, (f"^{CHECKPOINT_PREFIX}[0-9]{{6}}$",))
    out = []
    for (schema,) in cur.fetchall():
        digits = schema[len(CHECKPOINT_PREFIX):]
        month = f"{digits[:4]}-{digits[4:]}"
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f'"{schema}"._session',))
        row = None
        if cur.fetchone()[0]:
            cur.execute(f'SELECT {", ".join(SESSION_COLUMNS)} FROM "{schema}"._session')
            found = cur.fetchone()
            row = dict(zip(SESSION_COLUMNS, found)) if found else None
        out.append({**(row or {"state": "unreadable"}), "month": month, "schema": schema})
    return sorted(out, key=lambda c: c["month"])


def loaded_months(cur) -> list[dict]:
    """The months whose rows are in the sales table with the label, with their row counts: the data's own record, independent of any checkpoint."""
    cur.execute("SELECT calendar_month, count(*) FROM unilever_sku_demand_fact WHERE is_demo AND _src_file = %s GROUP BY 1 ORDER BY 1", (TAG,))
    return [{"month": str(m)[:7], "rows": int(n)} for m, n in cur.fetchall()]
