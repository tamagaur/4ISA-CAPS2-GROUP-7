-- 0080_run_label_calendar_factor_not_applied.sql - the product-calendar backtest run that applies no calendar factor says so, and the
-- accuracy rows carry their runs' current labels and descriptions. 2026-11-13.
--
-- WHY. scripts/accuracy_as_served.py wrote run 20 as "..., succession + fading, product calendar": the twin of the error card's default
-- run 21 with no calendar factor. Without a factor the factor's grain changes nothing, so run 20 holds exactly run 15's forecasts
-- (read on live 2026-11-13: every stored check figure equal, 4,370 product-months each), and a label naming "product calendar" reads as if
-- a factor were applied. The label now ends ", calendar factor not applied" (backend/marts.CALENDAR_OFF_SUFFIX). The code that finds
-- the card's "before the adjustment" twin (backend/marts.unadjusted_twin_query, scripts/forecast_bias_diagnosis.run_ids) prefers that
-- label and falls back to the bare one, so run 16 still finds run 15. scripts/accuracy_as_served.py writes the new label from now on.
-- Also: mart.accuracy_mart keeps its own copy of each run's label and description (run_label, cohort). Migration 0079 corrected
-- mart.forecast_run.cohort of runs 21-23 ("x each product's own calendar factor") and left accuracy_mart's copy saying "x the company
-- calendar factor" (21,250 rows, read on live 2026-11-13), which GET /dashboard/accuracy returns in its rows. Both copies are set from
-- mart.forecast_run for the product-calendar runs, run 20's new label included.
--
-- WHAT CHANGES. mart.forecast_run: the one run labelled exactly as below (run 20 on live), its label and cohort (appended). Keyed by
-- label, not run_id (a restored copy numbers runs differently). mart.accuracy_mart: run_label and cohort on the rows of the runs whose
-- label contains ", product calendar" where they differ from mart.forecast_run. The views mart.accuracy_category_month and
-- mart.accuracy_total_month read accuracy_mart and follow. No figure, forecast, plan or other table changes.
--
-- Expected on apply (live, read 2026-11-13): forecast_run 1 row (run 20). accuracy_mart 25,620 rows: run 20's 4,370 (label and
-- cohort) and runs 21, 22, 23's 4,370 + 5,192 + 11,688 (cohort). Touches no app.users column, so public.users is not re-created.
-- Rollback: UPDATE mart.forecast_run SET label = left(label, length(label) - 29), cohort = split_part(cohort, '. No calendar factor', 1)
--           WHERE label LIKE '%, product calendar, calendar factor not applied', then the accuracy_mart UPDATE below again, then
--           DELETE FROM schema_migrations WHERE filename = '0080_run_label_calendar_factor_not_applied.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)
UPDATE mart.forecast_run
   SET label  = label || ', calendar factor not applied',
       cohort = cohort || '. No calendar factor: the same forecasts as the run labelled without '', product calendar'''
 WHERE label = 'as-served backtest 2023-10..2026-02, Tier A the month before each month, succession + fading, product calendar'
   AND kind = 'backtest_recreated';

UPDATE mart.accuracy_mart a
   SET run_label = r.label,
       cohort    = r.cohort
  FROM mart.forecast_run r
 WHERE r.run_id = a.run_id
   AND r.label LIKE '%, product calendar%'
   AND (a.run_label IS DISTINCT FROM r.label OR a.cohort IS DISTINCT FROM r.cohort);
