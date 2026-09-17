-- analytics/db/migrations/0018_sku_segment_and_traits.sql
--
-- Phase 2 binning, Round 1 (reports/BINNING_ROUND1_2026-09.md). BINS ONLY —
-- no model runs, no MASE, no assignment; that is Phase 3.
--
-- sku_traits: one row per (product_key, cohort_period) — the trait facts a
-- binning scheme reads from. Computed once for the full 132-SKU cohort so
-- Round 2 schemes (trend_v1, volatility_v1, newness_v1, combined_v1) need
-- only new sku_segment rows, no further schema change.
--
-- sku_segment: one row per (product_key, cohort_period, abc_method, scheme)
-- — the bin assignment itself, plus a human-readable bin_reason so a bin
-- can be audited without recomputing the traits.
--
-- Both tables carry run_id (audit tag, not part of the natural key, same
-- convention as ABC_Classification's run_id from migration 0017).

BEGIN;

CREATE TABLE IF NOT EXISTS sku_traits (
    trait_key               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                   TEXT NOT NULL,
    principal                 TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    product_key                BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    cohort_period                TEXT NOT NULL,   -- 'YYYY-MM', the ABC period this cohort was drawn from
    history_months                INT NOT NULL,   -- months with quantity_sold > 0
    first_sale_period               TEXT,          -- NULL if never sold in the observed window
    longest_run                      INT NOT NULL, -- longest unbroken run of quantity_sold > 0 months
    trend                              TEXT NOT NULL CHECK (trend IN ('up', 'down', 'none')),  -- Mann-Kendall, p < 0.05
    cv                                  NUMERIC,     -- coefficient of variation of monthly quantity, full series
    restart_flag                        BOOLEAN NOT NULL DEFAULT FALSE,  -- 3+ consecutive zero months after first sale, then sold again
    stability_group                      TEXT NOT NULL CHECK (stability_group IN ('all_38', 'at_least_30', 'churn')),
    revenue_share_2026_02                 NUMERIC(7,4),  -- ABC_Classification.revenue_share for this product at the 2026-02 single-period run
    computed_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_key, cohort_period)
);

CREATE TABLE IF NOT EXISTS sku_segment (
    segment_key              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                     TEXT NOT NULL,
    principal                   TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    product_key                  BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    sku_code                       TEXT,
    cohort_period                    TEXT NOT NULL,
    abc_method                        TEXT NOT NULL DEFAULT 'single' CHECK (abc_method IN ('single', 't3m')),
    scheme                              TEXT NOT NULL,   -- 'length_v1', 'trend_v1', 'volatility_v1', 'newness_v1', 'combined_v1', ...
    bin                                  TEXT NOT NULL,
    bin_reason                            TEXT NOT NULL,  -- human-readable, e.g. "25 months with sales >= 12"
    computed_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_key, cohort_period, abc_method, scheme)
);

CREATE INDEX IF NOT EXISTS ix_sku_segment_scheme_bin ON sku_segment (scheme, bin);
CREATE INDEX IF NOT EXISTS ix_sku_traits_cohort ON sku_traits (cohort_period, principal);

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP TABLE IF EXISTS sku_segment;
-- DROP TABLE IF EXISTS sku_traits;
-- COMMIT;
