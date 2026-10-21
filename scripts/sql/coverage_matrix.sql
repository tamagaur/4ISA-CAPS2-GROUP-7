-- Coverage matrix queries (docs/COVERAGE_MATRIX.md). Aggregate counts only, no per-product rows.
-- Run: PYTHONUTF8=1 python scripts/run_sql.py scripts/sql/coverage_matrix.sql   (BEGIN; SET TRANSACTION READ ONLY; ... ROLLBACK)
-- Pinned to: Tier A basis t12m_new at 2026-02 (analytics.params.TIER_A_BASIS), real forecast date 2026-03-01,
-- real lp_run 4, demo.run 12 (Unilever) and 7 (Del Monte). Re-pin these when a newer run exists
-- (latest = SELECT MAX(run_id) FROM demo.run WHERE principal = ...; MAX(run_key) FROM lp_run).
SELECT run_id, label, principal, window_end, forecast_target, created_at FROM demo.run ORDER BY run_id;
SELECT run_key, planning_cycle_date, principal_scope, created_at, code_version FROM lp_run ORDER BY run_key;
SELECT abc.principal, pd.grain, abc.method, abc.classification_period, abc.tier, COUNT(*) n FROM ABC_Classification abc JOIN Product_Dimension pd USING (product_key) WHERE abc.principal = 'delmonte' AND abc.classification_period IN ('2025-12', '2024-02') GROUP BY 1,2,3,4,5 ORDER BY 4 DESC,5;
SELECT abc.principal, pd.grain, abc.method, abc.classification_period, abc.tier, COUNT(*) n FROM ABC_Classification abc JOIN Product_Dimension pd USING (product_key) WHERE abc.principal = 'unilever' AND abc.classification_period = '2026-02' GROUP BY 1,2,3,4,5 ORDER BY 3,5;
SELECT 'uni_sales' t, run_id, COUNT(*) n, COUNT(DISTINCT product_key) d FROM demo.unilever_sku_sales GROUP BY run_id UNION ALL
SELECT 'uni_fc', run_id, COUNT(*), COUNT(DISTINCT product_key) FROM demo.unilever_sku_forecast GROUP BY run_id UNION ALL
SELECT 'uni_lp', run_id, COUNT(*), COUNT(DISTINCT product_key) FROM demo.unilever_sku_lp GROUP BY run_id UNION ALL
SELECT 'dm_sales', run_id, COUNT(*), COUNT(DISTINCT category_path) FROM demo.dm_category_sales GROUP BY run_id UNION ALL
SELECT 'dm_param', run_id, COUNT(*), COUNT(DISTINCT category_path) FROM demo.dm_category_param GROUP BY run_id UNION ALL
SELECT 'dm_fc', run_id, COUNT(*), COUNT(DISTINCT category_path) FROM demo.dm_forecast GROUP BY run_id UNION ALL
SELECT 'dm_lp', run_id, COUNT(*), COUNT(DISTINCT category_path) FROM demo.dm_category_lp GROUP BY run_id UNION ALL
SELECT 'dm_excl', run_id, COUNT(*), COUNT(DISTINCT category_path) FROM demo.dm_excluded GROUP BY run_id UNION ALL
SELECT 'bc_excl', run_id, COUNT(*), COUNT(DISTINCT series_key) FROM demo.backcast_excluded GROUP BY run_id ORDER BY 1,2;
SELECT pd.principal, lr.lp_run_key, lr.planning_cycle_date, COUNT(*) n, COUNT(*) FILTER (WHERE q_i > 0) pos, SUM(q_i) qty FROM lp_recommendation lr JOIN Product_Dimension pd USING (product_key) WHERE lr.planning_cycle_date = '2026-03-01' GROUP BY 1,2,3 ORDER BY 1,2;
SELECT model_params->>'method' m, status, COUNT(*) FROM Forecast_Result GROUP BY 1,2 ORDER BY 1,2;
SELECT model_params->>'abc_period_used' p, model_params->>'abc_method_used' m, model_params->>'run' r, COUNT(*) FROM Forecast_Result GROUP BY 1,2,3;
SELECT pd.principal, pd.grain, COUNT(*) FROM ABC_Classification abc JOIN Product_Dimension pd USING (product_key) GROUP BY 1,2 ORDER BY 1,2;
SELECT abc.principal, abc.method, COUNT(*) FROM ABC_Classification abc GROUP BY 1,2 ORDER BY 1,2;
SELECT pd.principal, pd.grain, COUNT(*) FROM Forecast_Result fr JOIN Product_Dimension pd USING (product_key) GROUP BY 1,2;
SELECT pd.principal, pd.grain, COUNT(*), MIN(planning_cycle_date), MAX(planning_cycle_date) FROM lp_recommendation lr JOIN Product_Dimension pd USING (product_key) GROUP BY 1,2;
SELECT reason, COUNT(*) FROM demo.dm_excluded WHERE run_id = 7 GROUP BY 1;
SELECT category_path, forecast_status FROM demo.dm_category_param WHERE run_id = 7 AND forecast_status <> 'ok' ORDER BY 1 LIMIT 0;
SELECT forecast_status, COUNT(*) FROM demo.dm_category_param WHERE run_id = 7 GROUP BY 1;
SELECT f.forecast_period, f.method, COUNT(*) n, COUNT(*) FILTER (WHERE forecast_quantity = 0) zero FROM demo.dm_forecast f WHERE run_id = 7 GROUP BY 1,2;
SELECT period, COUNT(*) n, COUNT(*) FILTER (WHERE order_qty > 0) pos, SUM(order_qty) qty, SUM(forecast_quantity) fc FROM demo.dm_category_lp WHERE run_id = 7 GROUP BY 1;
SELECT f.forecast_period, f.method, COUNT(*) n, COUNT(*) FILTER (WHERE forecast_quantity = 0) zero FROM demo.unilever_sku_forecast f WHERE run_id = 12 GROUP BY 1,2;
SELECT period, COUNT(*) n, COUNT(*) FILTER (WHERE order_qty > 0) pos, SUM(order_qty) qty, MIN(stock_source) s1, MAX(stock_source) s2 FROM demo.unilever_sku_lp WHERE run_id = 12 GROUP BY 1;
SELECT 'real_fc' k, COUNT(*) FROM Forecast_Result WHERE forecast_date = '2026-03-01';
SELECT 'real_fc_tierA', COUNT(*) FROM Forecast_Result fr JOIN ABC_Classification a ON a.product_key = fr.product_key AND a.method = 't12m_new' AND a.classification_period = '2026-02' AND a.tier = 'A';
SELECT 'real_fc_ok_pass' k, COUNT(*) FROM Forecast_Result WHERE status = 'ok' AND mase < 1.0;
SELECT 'real_fc_ok_fail' k, COUNT(*) FROM Forecast_Result WHERE status = 'ok' AND mase >= 1.0;
SELECT 'real_fc_ok_nullmase' k, COUNT(*) FROM Forecast_Result WHERE status = 'ok' AND mase IS NULL;
SELECT 'real_fc_zero_all' k, COUNT(*), COUNT(*) FILTER (WHERE status = 'ok') ok_zero FROM Forecast_Result WHERE forecast_value = 0;
SELECT model_params->>'method' m, status, COUNT(*) n, COUNT(*) FILTER (WHERE mase < 1.0) pass, COUNT(*) FILTER (WHERE mase >= 1.0) fail, COUNT(*) FILTER (WHERE forecast_value = 0) zero FROM Forecast_Result GROUP BY 1,2 ORDER BY 1,2;
SELECT 'S_demo_sales_in_TierA' k, COUNT(DISTINCT s.product_key) FROM demo.unilever_sku_sales s JOIN ABC_Classification a ON a.product_key = s.product_key AND a.method = 't12m_new' AND a.classification_period = '2026-02' AND a.tier = 'A' WHERE s.run_id = 12;
SELECT 'S_inter_realfc' k, COUNT(DISTINCT s.product_key) FROM demo.unilever_sku_sales s JOIN Forecast_Result fr ON fr.product_key = s.product_key WHERE s.run_id = 12;
SELECT 'F_inter_realfc' k, COUNT(*) FROM demo.unilever_sku_forecast d JOIN Forecast_Result fr ON fr.product_key = d.product_key WHERE d.run_id = 12;
SELECT 'F_in_TierA' k, COUNT(*) FROM demo.unilever_sku_forecast d JOIN ABC_Classification a ON a.product_key = d.product_key AND a.method = 't12m_new' AND a.classification_period = '2026-02' AND a.tier = 'A' WHERE d.run_id = 12;
SELECT 'L_in_TierA' k, COUNT(*) FROM demo.unilever_sku_lp d JOIN ABC_Classification a ON a.product_key = d.product_key AND a.method = 't12m_new' AND a.classification_period = '2026-02' AND a.tier = 'A' WHERE d.run_id = 12;
SELECT 'L_inter_realLP4' k, COUNT(*) FROM demo.unilever_sku_lp d JOIN lp_recommendation lr ON lr.product_key = d.product_key AND lr.lp_run_key = 4 WHERE d.run_id = 12;
SELECT 'realF_not_in_demoF' k, COUNT(*) FROM Forecast_Result fr WHERE NOT EXISTS (SELECT 1 FROM demo.unilever_sku_forecast d WHERE d.run_id = 12 AND d.product_key = fr.product_key);
SELECT 'realF_not_in_demoF_by_status' k, fr.status, COUNT(*) FROM Forecast_Result fr WHERE NOT EXISTS (SELECT 1 FROM demo.unilever_sku_forecast d WHERE d.run_id = 12 AND d.product_key = fr.product_key) GROUP BY 2;
SELECT 'demoF_not_in_realF' k, COUNT(*) FROM demo.unilever_sku_forecast d WHERE d.run_id = 12 AND NOT EXISTS (SELECT 1 FROM Forecast_Result fr WHERE fr.product_key = d.product_key);
SELECT 'realLP4_in_TierA' k, COUNT(*) FROM lp_recommendation lr JOIN ABC_Classification a ON a.product_key = lr.product_key AND a.method = 't12m_new' AND a.classification_period = '2026-02' AND a.tier = 'A' WHERE lr.lp_run_key = 4;
SELECT 'demo_tier_in_synthetic_v2_flag' k, COUNT(*) FROM ABC_Classification a JOIN Product_Dimension pd USING (product_key) WHERE pd.principal = 'delmonte' AND a.method <> 'single';
SELECT lp_run_key, status, COUNT(*) FROM lp_recommendation WHERE lp_run_key = 4 GROUP BY 1,2;
