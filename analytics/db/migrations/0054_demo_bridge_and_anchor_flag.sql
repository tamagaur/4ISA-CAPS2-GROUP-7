-- 0054_demo_bridge_and_anchor_flag.sql — schema `demo`: flag for back-cast before a series' first observation.
--
-- Kelvin, 2026-10-15 (decision recorded in CLAUDE.md rule 2 and "Why data is missing"):
--   * Del Monte only: the anchor rule is overridden. The 5 live 2025 categories (BEVERAGE, CULINARY, DAIRY, FRUITS,
--     INNOVATION) and the sub-categories first seen after 2023-01 are back-cast to 2021-01 although their first real
--     month is later (a relabelling of a business that existed in 2021, not new products). Origin stays 'backcast';
--     this column marks those rows so the distinction survives.
--   * origin 'bridged' (already allowed by 0053) is now populated: Del Monte's pre-2025 paths are extended from their
--     last real month through 2025-02 across the taxonomy change. That is extrapolation, by decision.
--
-- Unilever is unaffected: its back-cast keeps the first-real-month = 2023-01 rule and gets no override.
-- Structure only, inside schema demo. Expected: one column added, existing rows false.
-- Rollback: ALTER TABLE demo.dm_category_sales DROP COLUMN anchor_override;

ALTER TABLE demo.dm_category_sales
    ADD COLUMN IF NOT EXISTS anchor_override BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN demo.dm_category_sales.anchor_override IS
    'true on a back-cast month of a series whose first real month is later than 2023-01: generated before its first '
    'real observation (Del Monte only, decision 2026-10-15). Migration 0054.';
