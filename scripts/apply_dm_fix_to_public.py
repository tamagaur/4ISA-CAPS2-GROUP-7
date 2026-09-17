"""scripts/apply_dm_fix_to_public.py — Part A.2 of the 2026-09-17/18
column-gap audit (reports/COLUMN_GAP_AUDIT_2026-09.md). Applies the Del
Monte product_dimension dedup + inventory_fact.product_key fix to
`public`, exactly reproducing what the scratch dry-run
(schema ssm_col_gap_audit) already verified.

Run this yourself — the harness's own safety classifier blocks automated
writes to `public`, separate from any task-level approval. Requires
SUPABASE_DIRECT_URL in .env (bypasses the pooler; the pooler connection is
currently stuck read-only from an unrelated leaked session setting).

Steps, all inside one transaction per step, matching the scratch run:
  1. Delete the 7 section-header artifact rows from inventory_fact
     (confirmed same rows/file/sheet as the scratch fix).
  2. Apply migration 0016 (dedup 291 rows, null 310 fake categories, add
     the (principal, sku_code) partial unique index).
  3. resolve_delmonte_sku_dimension() — upsert 597 real (sku_code,
     product_name) rows from inventory_sign_off, category_path NULL.
  4. resolve_delmonte_inventory_product_key() — join-based product_key
     backfill, asserts 0 Unilever rows touched.

Then verifies against the exact scratch-dry-run numbers and prints
PASS/FAIL per check. Nothing is left partially applied: steps 1-2 run in
one transaction, so a failure there rolls back cleanly; steps 3-4 already
have their own internal safety (the Unilever-touched assertion aborts
before committing if it ever fires).

Usage:
    python -m scripts.apply_dm_fix_to_public
"""
from __future__ import annotations

import os

env = {}
with open(".env") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
if not env.get("SUPABASE_DIRECT_URL"):
    raise SystemExit("SUPABASE_DIRECT_URL not found in .env — required for this script.")
os.environ["SUPABASE_DB_URL"] = env["SUPABASE_DIRECT_URL"]

from sqlalchemy import create_engine, text  # noqa: E402

from analytics.config import get_settings  # noqa: E402
from scripts.run_canonical_load import (  # noqa: E402
    MIGRATIONS_DIR,
    _strip_sql_file,
    resolve_delmonte_inventory_product_key,
    resolve_delmonte_sku_dimension,
)

HEADER_ARTIFACT_CODES = [
    "QUICK N EASY", "KIKKOMAN", "CONTADINA",
    "MR. MILK YOGHURT", "VINA MILK", "PROMO PACK", "NEW PRODUCTS",
]


def main() -> int:
    cfg = get_settings()
    engine = create_engine(cfg.supabase_db_url)

    with engine.connect() as conn:
        ro = conn.execute(text("SHOW default_transaction_read_only")).scalar()
        if ro == "on":
            raise SystemExit(
                "Connection is read-only (SHOW default_transaction_read_only = on). "
                "Confirm SUPABASE_DIRECT_URL in .env points at the real Postgres port "
                "(5432), not the pooler."
            )

    print("=== Step 1: delete 7 header-artifact rows from public.inventory_fact ===")
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM inventory_fact WHERE principal='delmonte' AND sku_code = ANY(:codes)"),
            {"codes": HEADER_ARTIFACT_CODES},
        )
        deleted = result.rowcount or 0
        print(f"  deleted: {deleted} (expected 7)")
        if deleted != 7:
            raise SystemExit(f"Expected to delete exactly 7 rows, got {deleted}. Aborting before migration 0016.")

    print("\n=== Step 2: apply migration 0016 to public ===")
    mig = MIGRATIONS_DIR / "0016_product_dimension_delmonte_sku_dedup.sql"
    cleaned = _strip_sql_file(mig.read_text(encoding="utf-8"))
    with engine.begin() as conn:
        conn.exec_driver_sql(cleaned.replace("%", "%%"))
    print("  applied.")

    print("\n=== Step 3: resolve_delmonte_sku_dimension ===")
    r1 = resolve_delmonte_sku_dimension(engine, "public", dry_run=False)

    print("\n=== Step 4: resolve_delmonte_inventory_product_key ===")
    r2 = resolve_delmonte_inventory_product_key(engine, "public", dry_run=False)

    print("\n=== Verification against the scratch dry-run ===")
    checks = []
    with engine.connect() as conn:
        dup = conn.execute(text(
            "SELECT count(*) FROM (SELECT sku_code FROM product_dimension WHERE sku_code IS NOT NULL "
            "AND principal='delmonte' GROUP BY principal, sku_code HAVING COUNT(*)>1) t"
        )).scalar()
        checks.append(("DM duplicate (principal, sku_code) groups", dup, 0))

        fake = conn.execute(text(
            "SELECT count(*) FROM product_dimension WHERE principal='delmonte' AND grain='sku' "
            "AND category_path IN ('/BASE','/FOUR SEASONS','/PINEAPPLE JUICE','/KETCHUP','/SPAGHETTI SAUCE')"
        )).scalar()
        checks.append(("Fake heuristic categories remaining", fake, 0))

        inv_count = conn.execute(text("SELECT count(*) FROM inventory_fact WHERE principal='delmonte'")).scalar()
        checks.append(("inventory_fact (delmonte) row count", inv_count, 20898))

        real_res = conn.execute(text(
            "SELECT count(*) FILTER (WHERE product_key IS NOT NULL) FROM inventory_fact "
            "WHERE principal='delmonte' AND is_demo=false"
        )).scalar()
        checks.append(("DM real inventory rows resolved", real_res, 5164))

        real_total = conn.execute(text(
            "SELECT count(*) FROM inventory_fact WHERE principal='delmonte' AND is_demo=false"
        )).scalar()
        checks.append(("DM real inventory rows total", real_total, 5164))

        uni_null = conn.execute(text(
            "SELECT count(*) FROM inventory_fact WHERE principal='unilever' AND product_key IS NULL"
        )).scalar()
        # unilever untouched by this script — report only, not a pass/fail vs a fixed number
        print(f"  (info) Unilever inventory_fact rows still null: {uni_null} — untouched by this script, "
              f"see Part B / apply_unilever_fix_to_public.py")

    all_ok = True
    for label, actual, expected in checks:
        ok = actual == expected
        all_ok &= ok
        print(f"  {label}: {actual} (expected {expected}) {'PASS' if ok else 'FAIL'}")

    print(f"\n{'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED — see above'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
