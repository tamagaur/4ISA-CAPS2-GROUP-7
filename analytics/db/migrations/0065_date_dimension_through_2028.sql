-- 0065_date_dimension_through_2028.sql - extend date_dimension from 2027-01-01 through 2028-12-31.
--
-- WHY. The table ended 2026-12-31. A December 2026 stock sheet carries an early-January 2027 snapshot date
-- (the SSIS count is taken in the first days of the next month: the 2026-02 count is dated 2026-03-02), and
-- inventory_fact.snapshot_date is a foreign key to date_dimension, so the January 2027 load would fail on it.
--
-- SAME RULES AS analytics/db/seed_date_dim.py, checked against all 2,191 existing rows on 2026-10-22:
-- day_of_week ISO (1 = Monday .. 7 = Sunday), week_of_year ISO, English day/month names, quarter calendar,
-- is_weekend = Saturday or Sunday, fiscal_period NULL (SSM's fiscal calendar is not confirmed anywhere in the
-- source data; left null rather than guessed, ARCHITECTURE.md principle #1).
--
-- ADDITIVE ONLY. Every generated date is after the current maximum (2026-12-31) and ON CONFLICT DO NOTHING
-- guards the key, so no existing row can be inserted over or changed.
--
-- Expected on apply: 731 rows written (365 in 2027 + 366 in 2028); table 2,191 -> 2,922 rows; max date_key
-- 2028-12-31; the 2,191 earlier rows identical.
--
-- Rollback: DELETE FROM date_dimension WHERE date_key > DATE '2026-12-31' (only while no fact row references
-- one); DELETE FROM schema_migrations WHERE filename = '0065_date_dimension_through_2028.sql'.

INSERT INTO date_dimension (date_key, day_of_week, day_name, week_of_year, month, month_name,
                            quarter, year, is_weekend, fiscal_period)
SELECT d::date,
       EXTRACT(isodow FROM d)::smallint,
       trim(to_char(d, 'FMDay')),
       EXTRACT(week FROM d)::smallint,
       EXTRACT(month FROM d)::smallint,
       trim(to_char(d, 'FMMonth')),
       EXTRACT(quarter FROM d)::smallint,
       EXTRACT(year FROM d)::smallint,
       EXTRACT(isodow FROM d) >= 6,
       NULL
FROM generate_series(DATE '2027-01-01', DATE '2028-12-31', INTERVAL '1 day') AS g(d)
ON CONFLICT (date_key) DO NOTHING;
