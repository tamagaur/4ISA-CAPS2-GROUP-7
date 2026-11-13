-- 0079_product_calendar_run_descriptions.sql - the stored descriptions of the product-calendar backtest runs say which factor
-- they carry. 2026-11-13.
--
-- WHY. scripts/accuracy_as_served.py wrote the three calendar-adjusted ", product calendar" runs of 2026-11-13 (the error
-- card's default and the Tier B / C counterfactuals, scripts/apply_calendar_grain.py) with the description of the runs before
-- them: "served value x the company calendar factor". Those runs carry each product's own factor (analytics/forecasting/
-- calendar.py ProductCalendar), and GET /dashboard/accuracy/runs serves the description (backend/marts.accuracy_runs, cohort).
-- The script's text is corrected in the same commit, so a later write gives the same words.
--
-- WHAT CHANGES. mart.forecast_run.cohort on the runs whose label ends ", product calendar, calendar-adjusted" (3 on live,
-- read 2026-11-13: run_id 21, 22, 23). The phrase "served value x the company calendar factor" becomes "served value x each
-- product's own calendar factor". Keyed by label, not run_id (a restored copy numbers its runs differently). No other column,
-- row or table. Nothing reads cohort to compute anything: forecasts, safety stock, the plan and the marts are unchanged.
--
-- Expected on apply: 3 rows updated on live. Touches no app.users column, so public.users is not re-created.
-- Rollback: the same UPDATE with the two phrases swapped, then
--           DELETE FROM schema_migrations WHERE filename = '0079_product_calendar_run_descriptions.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)
UPDATE mart.forecast_run
   SET cohort = replace(cohort, 'served value x the company calendar factor', 'served value x each product''s own calendar factor')
 WHERE label LIKE '%, product calendar, calendar-adjusted'
   AND cohort LIKE '%served value x the company calendar factor%';
