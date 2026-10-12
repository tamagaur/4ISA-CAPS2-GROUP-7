"""scripts/rehearse_app_schema_fillskip.py — does rehearse_fills skip the 0048 compatibility views?

reports/SCHEMA_REORG_PLAN.md section 3c calls this the rehearsal leak, and it is the one
defect in the whole reorganisation that would be invisible: rehearse_fills clones public's
views into a scratch schema with pg_get_viewdef, and a compatibility view's body names
`app.audit_log` with its schema. Re-created in scratch, that clone is a WRITABLE WINDOW
ONTO THE LIVE TABLE — a fill rehearsal would write live audit rows, and the "outputs
unchanged" check would be comparing live with itself and could never fail. Commit 37233c8
added the skip (a view is cloned only if every relation it depends on, transitively, is in
public). Until 0048 there were no non-public-dependent views anywhere, so the skip had
never once executed.

It cannot be tested from the command line. `--build --dry-run` opens its own connection,
and the compatibility views only exist inside 0048's uncommitted transaction, which no
other connection can see. So this script does both halves on ONE connection:

  1. applies 0048 inside a transaction that is always rolled back, and
  2. calls rehearse_fills._plan() on that same connection — the function whose return value
     IS what `--build --dry-run` prints (rehearse_fills.py:80-89 formats exactly these four
     values and then returns) — so the decision under test is the real one, not a copy.

Then it asserts the three things that matter: all 6 views are skipped, each for depending on
`app`, and no clone list anywhere mentions them.

Part 2 follows the consequence. `audit_log` and `user_permission_override` are not credential
tables, so they ARE cloned into a scratch schema, and `fill_missing` and `load_slices` both
finish by writing an unqualified `INSERT INTO audit_log` (fill_missing.py:608,
load_slices.py:862) under a search_path set to the scratch schema and nothing else
(load_slices.py:595-600, deliberately: "a table missing from a scratch schema must fail,
never resolve to the live table of the same name"). The first run of this script showed that
after 0048 those two tables were in neither public nor the clone list, so that insert had
nowhere to resolve and every scratch fill run would fail - fail-closed, but broken. The fix
was to make rehearse_fills scan `app` as well as `public` (SOURCE_SCHEMAS), still cloning
every table under its bare name, so `audit_log` reappears in scratch. Part 2 now builds a
scratch clone for real, inside the rolled-back transaction, and runs the actual statement:
it must land in the scratch copy, and the live journal must not gain a row.

READ ONLY in effect: the only write is 0048 itself, inside a transaction rolled back in a
`finally`. Nothing is committed on any path.

    python -m scripts.rehearse_app_schema_fillskip
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from analytics.config import get_settings
from scripts.rehearse_fills import _plan
from scripts.run_canonical_load import _strip_sql_file

MIGRATION = Path(__file__).resolve().parents[1] / "analytics" / "db" / "migrations" / "0048_app_schema.sql"
MOVED = ["users", "user_session", "auth_token", "user_mfa", "user_permission_override", "audit_log"]


def main() -> int:
    engine = create_engine(get_settings().supabase_db_url)
    failures: list[str] = []
    conn = engine.connect()
    try:
        trans = conn.begin()
        try:
            conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            conn.execute(text("SET LOCAL statement_timeout = '30s'"))

            # --- before: the state the skip has never had anything to do in ----------
            tables_before, _, views_before, skipped_before = _plan(conn)
            print(f"[before 0048] {len(tables_before)} tables, {len(views_before)} views to clone, "
                  f"{len(skipped_before)} views skipped")
            for v, why in skipped_before.items():
                print(f"              SKIP view {v}: depends on {', '.join(why)}")

            # --- apply 0048, uncommitted --------------------------------------------
            conn.exec_driver_sql(_strip_sql_file(MIGRATION.read_text(encoding="utf-8")).replace("%", "%%"))
            print(f"[applied, uncommitted] {MIGRATION.name}")

            # --- after: the same decision function, now with 6 compat views ----------
            tables_after, skipped_tables, views_after, skipped_after = _plan(conn)
            print(f"[after 0048]  {len(tables_after)} tables, {len(views_after)} views to clone, "
                  f"{len(skipped_after)} views skipped")
            for v, why in sorted(skipped_after.items()):
                print(f"              SKIP view {v}: depends on {', '.join(why)}")

            clone_view_names = {v for v, _ in views_after}
            clone_table_names = {t for _, t in tables_after}
            for name in MOVED:
                if name not in skipped_after:
                    failures.append(f"{name}: compatibility view was NOT skipped")
                elif skipped_after[name] != ["app"]:
                    failures.append(f"{name}: skipped, but for {skipped_after[name]} rather than ['app']")
                if name in clone_view_names:
                    failures.append(f"{name}: present in the list of views to CLONE - this is the leak")
                if name in {t for src, t in tables_after if src == "public"}:
                    failures.append(f"{name}: still listed as a PUBLIC base table to clone")

            newly_skipped = set(skipped_after) - set(skipped_before)
            if newly_skipped != set(MOVED):
                failures.append(f"newly skipped views are {sorted(newly_skipped)}, expected the 6 moved names")

            # The credential rule and the skip are different mechanisms; after the move the
            # 6 are not in public at all, so the credential rule no longer sees them. Worth
            # printing, because "no credential table skipped" would look alarming otherwise.
            print(f"[credential rule] still skipping {len(skipped_tables)} public table(s): "
                  f"{', '.join(sorted(skipped_tables)) or 'none'}")
            for name in ("audit_log", "user_permission_override", "users", "user_mfa"):
                src_before = next((src for src, t in tables_before if t == name), None)
                src_after = next((src for src, t in tables_after if t == name), None)
                print(f"              {name}: cloned from {src_before or 'NOT CLONED'} before, "
                      f"{src_after or 'NOT CLONED'} after")
            for name in ("audit_log", "user_permission_override"):
                if name not in clone_table_names:
                    failures.append(f"{name}: not in the clone list after 0048 - a scratch fill run would "
                                    f"have nowhere to resolve its unqualified INSERT")

            # --- part 2: what a scratch fill run does now --------------------------
            # An empty schema stands in for a freshly cloned one that did not get
            # audit_log, with the same search_path load_slices._scope sets.
            src_audit = next((src for src, t in tables_after if t == "audit_log"), None)
            live_before = conn.exec_driver_sql("SELECT count(*) FROM app.audit_log").scalar()
            conn.exec_driver_sql("CREATE SCHEMA _0048_scratch_probe")
            # a savepoint, so a failure here leaves the transaction usable for the cleanup
            # and the rollback below instead of aborting everything after it
            probe = conn.begin_nested()
            try:
                # the clone, exactly as build() does it for every table
                conn.exec_driver_sql(
                    f"CREATE TABLE _0048_scratch_probe.audit_log (LIKE {src_audit}.audit_log "
                    f"INCLUDING DEFAULTS INCLUDING IDENTITY INCLUDING INDEXES INCLUDING CONSTRAINTS)")
                conn.exec_driver_sql(
                    f"INSERT INTO _0048_scratch_probe.audit_log OVERRIDING SYSTEM VALUE "
                    f"SELECT * FROM {src_audit}.audit_log")
                seq = conn.exec_driver_sql(
                    f"SELECT pg_get_serial_sequence('{src_audit}.audit_log', 'audit_log_key')").scalar()
                last, called = conn.exec_driver_sql(f"SELECT last_value, is_called FROM {seq}").one()
                conn.exec_driver_sql(
                    f"SELECT setval(pg_get_serial_sequence('_0048_scratch_probe.audit_log', 'audit_log_key'), "
                    f"{int(last)}, {bool(called)})")
                # the pipeline statement, under the search_path load_slices._scope sets
                conn.exec_driver_sql("SET LOCAL search_path TO _0048_scratch_probe")
                conn.exec_driver_sql(
                    "INSERT INTO audit_log (user_email, user_name, role, action, details) "
                    "VALUES ('0048-probe@invalid', '0048 probe', 'etl', 'data_fill', 'probe')")
                conn.exec_driver_sql("SET LOCAL search_path TO public")
                scratch_rows = conn.exec_driver_sql(
                    "SELECT count(*) FROM _0048_scratch_probe.audit_log WHERE user_email = "
                    "'0048-probe@invalid'").scalar()
                live_after = conn.exec_driver_sql("SELECT count(*) FROM app.audit_log").scalar()
                print(f"[part 2] cloned audit_log from {src_audit}; unqualified INSERT under the scratch "
                      f"search_path landed {scratch_rows} row(s) in scratch; app.audit_log {live_before} "
                      f"-> {live_after}")
                if scratch_rows != 1:
                    failures.append(f"part 2: the scratch copy got {scratch_rows} rows, expected 1")
                if live_after != live_before:
                    failures.append(
                        f"part 2: app.audit_log went {live_before} -> {live_after} - the scratch write "
                        f"reached the LIVE journal. This is the leak.")
                probe.close()
            except Exception as exc:  # noqa: BLE001 - the failure IS the result
                probe.rollback()
                failures.append(f"part 2 raised: {type(exc).__name__}: {str(exc).splitlines()[0]}")
                print(f"[part 2] raised: {str(exc).splitlines()[0]}")
            finally:
                conn.exec_driver_sql("SET LOCAL search_path TO public")
                conn.exec_driver_sql("DROP SCHEMA IF EXISTS _0048_scratch_probe CASCADE")
        finally:
            trans.rollback()
            print("[rollback] the transaction was rolled back; public is unchanged")
    finally:
        conn.close()

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nPASS: all {len(MOVED)} compatibility views are skipped, each for depending on app; "
          f"none appears in a clone list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
