-- 0076_forecast_challenger.sql - the challenger forecast stored beside the served one, every product every month.
-- 2026-11-10.
--
-- One row per product, target month, kind and challenger: the served forecast and the challenger's, side by side,
-- written together by scripts/challenger_forecast.py. Never read by the forecast runner, the LP or any API route,
-- so nothing served changes when it is written. docs/CHALLENGER_SELECTION_RULE.md compares the two once a year
-- (analytics/forecasting/selection_rule.py) and its verdict switches nothing.
--   kind               cycle     the forecast written for that planning cycle (served_value = Forecast_Result's value)
--                      backtest  the same code replayed as of that month (served_value = the as-served backtest)
--   challenger         the challenger's id (analytics/forecasting/challenger.CHALLENGER_ID, now damped_trend_v1)
--   served_value       served forecast in pieces, as served (calendar factor and dead-SKU rule included)
--   challenger_value   challenger forecast in pieces, the same guards, calendar factor and dead-SKU rule applied
--   cohort_period      the ABC period whose Tier A the product belonged to (the month before month)
--   calendar_factor    the factor both values carry (1 when none)
-- Actuals are NOT stored: they are read when scoring, so a late or corrected sales row scores both the same way.
--
-- Additive only. Expected on apply: 0 rows written, no existing row changed. Touches no app.users column, so
-- public.users is not re-created. Row-level security on, no policy: only the owner role reads or writes it.
--
-- Rollback: DROP TABLE IF EXISTS forecast_challenger.
--           DELETE FROM schema_migrations WHERE filename = '0076_forecast_challenger.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)
CREATE TABLE IF NOT EXISTS forecast_challenger (
    product_key        BIGINT  NOT NULL REFERENCES product_dimension (product_key),
    month              DATE    NOT NULL CHECK (EXTRACT(DAY FROM month) = 1),
    kind               TEXT    NOT NULL CHECK (kind IN ('cycle', 'backtest')),
    challenger         TEXT    NOT NULL CHECK (length(btrim(challenger)) > 0),
    served_value       NUMERIC(14, 4) NOT NULL CHECK (served_value >= 0),
    challenger_value   NUMERIC(14, 4) NOT NULL CHECK (challenger_value >= 0),
    served_method      TEXT    NOT NULL,
    challenger_method  TEXT    NOT NULL,
    bin                TEXT    NOT NULL CHECK (bin IN ('short', 'medium', 'long')),
    dead_sku           BOOLEAN NOT NULL,
    calendar_factor    NUMERIC(8, 6) NOT NULL,
    challenger_backup_reason TEXT,
    cohort_period      TEXT    NOT NULL,
    code_version       TEXT    NOT NULL,
    generated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_key, month, kind, challenger)
);
CREATE INDEX IF NOT EXISTS ix_forecast_challenger_month ON forecast_challenger (challenger, kind, month);
ALTER TABLE forecast_challenger ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE forecast_challenger IS
    'Challenger forecast beside the served one, per product and month (scripts/challenger_forecast.py). Never served: no runner, LP or route reads it. Compared once a year by docs/CHALLENGER_SELECTION_RULE.md.';
