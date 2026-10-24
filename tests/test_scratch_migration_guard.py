"""The scratch build refuses, as a hard guard, any pending migration that names app., public. or mart. (2026-10-24).

Applied "to a scratch schema" such a statement runs against the LIVE table or schema (0059 and 0060 altered the live
app.users). A pre-flight check protects only when someone remembers to look, so the build itself stops."""
from __future__ import annotations

import pytest

from scripts import rehearse_fills
from scripts import run_canonical_load as rcl


def _migration(tmp_path, name, sql):
    f = tmp_path / name
    f.write_text(sql, encoding="utf-8")
    return f


def test_a_migration_naming_app_or_public_or_mart_is_found(tmp_path):
    f = _migration(tmp_path, "0999_x.sql", "-- touches app.users in a comment only\nALTER TABLE app.users ADD COLUMN x TEXT;\n"
                                           "CREATE OR REPLACE VIEW public.users AS SELECT 1;\nSELECT mart.refresh();\n")
    refs = rcl.live_schema_references([f])
    assert ("0999_x.sql", "app.users") in refs and ("0999_x.sql", "public.users") in refs
    assert ("0999_x.sql", "mart.refresh") in refs


def test_the_scratch_build_refuses_and_names_the_file_and_the_reference(tmp_path):
    f = _migration(tmp_path, "0999_x.sql", "ALTER TABLE app.users ADD COLUMN x TEXT;\n")
    with pytest.raises(SystemExit) as exc:
        rcl.assert_scratch_migrations_safe([f], "ssm_rollover_test")
    msg = str(exc.value)
    assert "REFUSED" in msg and "0999_x.sql" in msg and "app.users" in msg and "Nothing was applied" in msg


def test_unqualified_migrations_and_comments_pass(tmp_path):
    ok = _migration(tmp_path, "0998_y.sql", "-- public.users and app.users are only named here, in a comment\n"
                                            "CREATE TABLE IF NOT EXISTS thing (a int);\nALTER TABLE thing ADD COLUMN b int;\n")
    rcl.assert_scratch_migrations_safe([ok], "ssm_rollover_test")
    assert rcl.live_schema_references([ok]) == []


def test_an_empty_pending_list_passes():
    rcl.assert_scratch_migrations_safe([], "ssm_rollover_test")


def test_the_known_hazards_are_caught_in_the_real_migration_files():
    names = {n for n, _ in rcl.live_schema_references(sorted(rcl.MIGRATIONS_DIR.glob("0*.sql")))}
    assert {"0048_app_schema.sql", "0059_user_avatar_path.sql", "0060_retire_avatar_data_url.sql"} <= names
    assert "0069_rollover_ledger.sql" not in names           # the new migration is scratch-safe


def test_it_runs_in_both_places_a_scratch_schema_is_built_and_before_anything_is_created():
    import inspect
    ensure = inspect.getsource(rcl.ensure_scratch_schema)
    assert ensure.index("assert_scratch_migrations_safe") < ensure.index("CREATE SCHEMA IF NOT EXISTS")
    assert "if not allow_public" in ensure                      # a live apply is the sanctioned path and is not blocked
    build = inspect.getsource(rehearse_fills.build)
    assert build.index("assert_scratch_migrations_safe") < build.index("CREATE SCHEMA")
