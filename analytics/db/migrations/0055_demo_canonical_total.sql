-- 0055_demo_canonical_total.sql — schema `demo`: one canonical Del Monte series per month.
--
-- Kelvin, 2026-10-15. The demonstration generates Del Monte under TWO vocabularies at once: the pre-2025 paths
-- (real 2023-01..2024-02, bridged through 2025-02) and the five 2025 categories (real from 2025-03, back-cast before
-- that). Over 2023-01..2025-02 a total across categories counted the same business twice, about 2x the real figure.
--
-- Rule, one canonical series per month: the old paths through 2025-02, the five live categories from 2025-03.
-- A back-cast row of a series generated BEFORE ITS OWN FIRST OBSERVATION (anchor_override: the five live categories,
-- and the sub-categories first seen after 2023-01) is excluded from every aggregate, and is served only when that
-- single series is charted on its own (GET /demo/series).
--
--   demo.dm_category_sales.in_canonical_total   generated column: NOT (origin = 'backcast' AND anchor_override)
--   demo.dm_monthly_total                        the only sanctioned aggregate: pesos per month, canonical rows only,
--                                                split by origin. Pesos (net_amount), never pieces: Del Monte's
--                                                quantity unit is unconfirmed (DEC-31).
--
-- Structure only, inside schema demo; no row is changed. Rollback: DROP VIEW demo.dm_monthly_total;
-- ALTER TABLE demo.dm_category_sales DROP COLUMN in_canonical_total;

ALTER TABLE demo.dm_category_sales
    ADD COLUMN IF NOT EXISTS in_canonical_total BOOLEAN
    GENERATED ALWAYS AS (NOT (origin = 'backcast' AND anchor_override)) STORED;

COMMENT ON COLUMN demo.dm_category_sales.in_canonical_total IS
    'false on a back-cast row generated before its series'' first real observation: excluded from every aggregate '
    '(it would count the same business twice under two taxonomies), served only on its own series. Migration 0055.';

CREATE OR REPLACE VIEW demo.dm_monthly_total AS
SELECT run_id,
       period,
       SUM(net_amount) FILTER (WHERE in_canonical_total)                                  AS pesos,
       SUM(net_amount) FILTER (WHERE in_canonical_total AND origin = 'real_copy')         AS real_pesos,
       SUM(net_amount) FILTER (WHERE in_canonical_total AND origin = 'interpolated')      AS interpolated_pesos,
       SUM(net_amount) FILTER (WHERE in_canonical_total AND origin = 'bridged')           AS bridged_pesos,
       SUM(net_amount) FILTER (WHERE in_canonical_total AND origin = 'backcast')          AS backcast_pesos,
       COUNT(*) FILTER (WHERE in_canonical_total)                                         AS series,
       COUNT(*) FILTER (WHERE NOT in_canonical_total)                                     AS series_left_out
FROM demo.dm_category_sales
GROUP BY run_id, period;

COMMENT ON VIEW demo.dm_monthly_total IS
    'Del Monte demonstration pesos per month, one canonical series (old paths through 2025-02, the five live '
    'categories from 2025-03). The only sanctioned aggregate over demo.dm_category_sales. Migration 0055.';
