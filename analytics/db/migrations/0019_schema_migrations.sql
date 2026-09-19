-- 0019_schema_migrations.sql — a ledger of which migrations have been applied.
--
-- Until now there was none: ensure_scratch_schema() (scripts/run_canonical_load.py:1349)
-- globs every 0*.sql and re-applies ALL of them on every invocation, so safety
-- rested entirely on each file's own IF NOT EXISTS guards. Four files are not
-- idempotent in form (0006, 0007, 0016, 0017); all four have converged today,
-- but 0016's bare DELETE FROM Product_Dimension becomes destructive the moment
-- the ETL re-introduces Del Monte duplicate sku_codes.
--
-- KEYED BY FILENAME, NOT NUMBER. Two files share the number 0002
-- (0002_add_boundary_flag.sql and 0002_add_sku_management_fields.sql); both
-- are applied and neither was applied twice. A number-keyed ledger could not
-- represent that. Filename is the natural key here.
--
-- BACKFILL, NOT RE-APPLY. The 19 pre-existing files are seeded with
-- applied_at = NULL, which reads as "believed applied, never observed by the
-- ledger" — deliberately distinguishable from a row the loader writes itself,
-- which carries a real timestamp. Nothing in this file re-runs any migration.
--
-- Checksums are the sha256 of each file's bytes as of 2026-09-20. They were
-- not observed at the original application either; their purpose is forward
-- detection of a file edited AFTER it was applied.
--
-- This file does NOT seed a row for itself: its own checksum cannot include
-- itself. The ledger-aware loader records 0019 when it applies it, with a real
-- applied_at — so 0019 is the first migration whose application is observed
-- rather than assumed. Backfilled rows number exactly 19.

BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename      TEXT PRIMARY KEY,
    checksum      TEXT,
    applied_at    TIMESTAMPTZ,
    applied_by    TEXT,
    target_schema TEXT
);

COMMENT ON TABLE schema_migrations IS
    'One row per applied migration file, keyed by filename (numbers collide - see the two 0002 files). applied_at NULL means the row was backfilled by 0019 and the application was never observed; a real timestamp means this loader applied it. See scripts/run_canonical_load.py ensure_scratch_schema().';

COMMENT ON COLUMN schema_migrations.checksum IS
    'sha256 of the file bytes when the row was written. A mismatch at load time means the file was edited after it was applied.';

INSERT INTO schema_migrations (filename, checksum, applied_at, applied_by, target_schema)
SELECT v.filename, v.checksum, NULL, 'backfilled_pre_ledger', current_schema()
FROM (VALUES
    ('0001_add_is_demo.sql', 'cb9c23982cccb635456dc8ed429f8d6d9eb1982e9e8e6c20e9263078afeeb73a'),
    ('0002_add_boundary_flag.sql', '68dd8c7f4f86ea39a935d42cf77ea0806f41c735fe785c47fb95057e6b359a40'),
    ('0002_add_sku_management_fields.sql', '271575446e82ec6f831399de9d0741b3c67c79394ff6c760c3c00d651e849ec2'),
    ('0003_add_audit_log.sql', 'bdeecf26922ca65364ee3af8beb308d41c61b6035e734dfb10e7d96af129dd6b'),
    ('0004_add_valuation.sql', 'e562cbda0957430e3f35982222adbe06ea856d94f3a53ac40d4f1ae75559c949'),
    ('0005_fix_real_views.sql', 'c947c51b3e9932e32a014cdc07f25c203e473d9791bc54608143f4c2b181d94a'),
    ('0006_revert_sellout_category_attribution.sql', '079084be573bb0e42a97ba4c6d3cf717b22b63623de8f8ad38fc2047ae315c44'),
    ('0007_null_phantom_category_sku_codes.sql', 'a91ac869c5c8f36a2d327425dc355decd981ec3cd4e2d7d5633e0a8931c860eb'),
    ('0008_add_forecast_result_status.sql', '96fa08c6ff031cc627ad307a70211181e1296bccd543684810fc961070837aa2'),
    ('0009_add_soh_columns.sql', '5bfd9a017377d313538a750168da998413aa4d9f91df5739727bd6c9e71ad45d'),
    ('0010_gsv_and_guards.sql', '81d280b08bc97ae01046ed3882bbd4d13d089d63f8d1a825383ec23533692994'),
    ('0011_sales_return_key_and_category_brand.sql', '41825c5e52c263fb7041fa439f4f697dd8d747dc590f60bfdffeec4b90e85c24'),
    ('0012_sellout_source_defect_category.sql', 'a03ef4a8b87ea3766cc0b0f2706924acbd99e192ea7110cc3de6dd232cc605dc'),
    ('0013_product_dimension_nulls_not_distinct.sql', '1136a25e2d6fc53c14719dfac5bcf8f196177eb01f05a12ff32b28a0634ba30c'),
    ('0014_product_dimension_unilever_sku_partial_key.sql', '4613499dcf4118ecddbb7db09c1b40f56cab1ac95b7ba6acffa53a23367141e7'),
    ('0015_salesreturn_fact_return_type_drift_fix.sql', '1ff2c94999da47790ccc4778b1ee9eccad7e2f8279550ca77dd609656aac9c13'),
    ('0016_product_dimension_delmonte_sku_dedup.sql', '32b7a9be33d9fc36d9feaa9c2417de9c2955862dcfcf06f00d6419ff7224822a'),
    ('0017_abc_classification_method_run_id.sql', '8cb2ac1885dcb794f4183903d1e83c1dfdd5e057e9cf8543f565b93d054851be'),
    ('0018_sku_segment_and_traits.sql', '8cc34ee54d4fb2d7f00de0d099ba268ea6c61d2a77278359340d7c89b92d4ca1')
) AS v(filename, checksum)
ON CONFLICT (filename) DO NOTHING;

COMMIT;

-- Down (manual, not run by the loader):
-- DROP TABLE IF EXISTS schema_migrations;
