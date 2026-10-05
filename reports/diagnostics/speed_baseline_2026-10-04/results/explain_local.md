# EXPLAIN (ANALYZE, BUFFERS) — top 12 slowest distinct statements (local)

Run inside BEGIN; SET TRANSACTION READ ONLY; ... ROLLBACK. `seen` = slowest time the statement took during the timing runs (includes the round trip).

## #1 — seen 660 ms — `/dashboard?period=2026-02&start_period=2026-02&principal=unilever`

```sql
SELECT MAX(calendar_month) AS p FROM Unilever_SKU_Demand_Fact_Real
```

```
Aggregate  (cost=1495.73..1495.74 rows=1 width=32) (actual time=8.741..8.742 rows=1 loops=1)
  Buffers: shared hit=1062
  ->  Seq Scan on unilever_sku_demand_fact  (cost=0.00..1433.49 rows=24896 width=8) (actual time=0.014..5.585 rows=24906 loops=1)
        Filter: (NOT is_demo)
        Rows Removed by Filter: 12243
        Buffers: shared hit=1062
Planning Time: 0.113 ms
Execution Time: 8.780 ms
```

## #2 — seen 612 ms — `/sku?principal=unilever`

```sql
SELECT
        pd.product_key,
        COALESCE(pd.sku_code, pd.category_path) AS sku_id,
        pd.product_name,
        pd.principal,
        pd.grain,
        pd.pack_size,
        pd.brand,
        pd.unit_price AS unit_price,
        pd.lead_time_days AS lead_time_days,
        pd.status AS status,
        pd.notes AS notes,
        inv.stock_pieces AS current_stock,
        inv.stock_cases AS current_stock_cases,
        rop.rop_i AS reorder_point,
        abc.tier AS tier,
        abc.classification_period AS tier_period
    FROM product_dimension pd
    LEFT JOIN (
    SELECT inv.product_key,
           
    CASE WHEN pd_pack.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd_pack.pack_size::numeric > 0
         THEN SUM(inv.quantity_on_hand) * pd_pack.pack_size::numeric
              + COALESCE(SUM(inv.quantity_pieces), 0)
    END
 AS stock_pieces,
           
    SUM(COALESCE(inv.valuation, inv.quantity_on_hand * inv.unit_cost_per_case))
  AS stock_value_pesos,
           SUM(inv.quantity_on_hand) AS stock_cases
    FROM inventory_fact_real inv
    JOIN product_dimension pd_pack ON pd_pack.product_key = inv.product_key
    JOIN (
        SELECT principal, MAX(_period) AS latest_period
        FROM inventory_fact_real
        GROUP BY principal
    ) latest_inv ON latest_inv.principal = inv.principal AND inv._period = latest_inv.latest_period
    GROUP BY inv.product_key, pd_pack.pack_size
) inv ON inv.product_key = pd.product_key
    LEFT JOIN (
        SELECT product_key, rop_i
        FROM lp_recommendation
        WHERE status = 'pending' AND planning_cycle_date = %(current_cycle)s
    ) rop ON rop.product_key = pd.product_key
    LEFT JOIN (
        SELECT DISTINCT ON (product_key)
               product_key, tier, classification_period
        FROM abc_classification
        WHERE method = 'single'
          AND (CAST(%(abc_period)s AS TEXT) IS NULL
               OR classification_period <= CAST(%(abc_period)s AS TEXT))
        ORDER BY product_key, classification_period DESC
    ) abc ON abc.product_key = pd.product_key
 WHERE 1=1 AND pd.principal = %(principal)s ORDER BY pd.product_name
```

```
Sort  (cost=11144.23..11149.48 rows=2098 width=210) (actual time=87.168..87.304 rows=2098 loops=1)
  Sort Key: pd.product_name
  Sort Method: quicksort  Memory: 347kB
  Buffers: shared hit=33750
  ->  Hash Left Join  (cost=7861.81..11028.48 rows=2098 width=210) (actual time=34.242..83.775 rows=2098 loops=1)
        Hash Cond: (pd.product_key = lp_recommendation.product_key)
        Buffers: shared hit=33750
        ->  Merge Left Join  (cost=7853.05..11014.20 rows=2098 width=193) (actual time=34.182..83.131 rows=2098 loops=1)
              Merge Cond: (pd.product_key = abc_classification.product_key)
              Buffers: shared hit=33745
              ->  Merge Left Join  (cost=7851.12..8296.58 rows=2098 width=183) (actual time=34.025..38.109 rows=2098 loops=1)
                    Merge Cond: (pd.product_key = inventory_fact.product_key)
                    Buffers: shared hit=10286
                    ->  Index Scan using product_dimension_pkey on product_dimension pd  (cost=0.28..407.27 rows=2098 width=119) (actual time=0.016..1.039 rows=2098 loops=1)
                          Filter: (principal = 'unilever'::text)
                          Rows Removed by Filter: 685
                          Buffers: shared hit=560
                    ->  Materialize  (cost=7850.84..7879.40 rows=476 width=72) (actual time=34.005..36.320 rows=994 loops=1)
                          Buffers: shared hit=9726
                          ->  GroupAggregate  (cost=7850.84..7873.45 rows=476 width=107) (actual time=34.002..36.016 rows=994 loops=1)
                                Group Key: inventory_fact.product_key, pd_pack.pack_size
                                Buffers: shared hit=9726
                                ->  Sort  (cost=7850.84..7852.03 rows=476 width=20) (actual time=33.979..34.126 rows=1122 loops=1)
                                      Sort Key: inventory_fact.product_key, pd_pack.pack_size
                                      Sort Method: quicksort  Memory: 95kB
                                      Buffers: shared hit=9726
                                      ->  Nested Loop  (cost=3836.18..7829.67 rows=476 width=20) (actual time=19.075..33.707 rows=1200 loops=1)
                                            Buffers: shared hit=9726
                                            ->  Hash Join  (cost=3835.89..7682.86 rows=476 width=17) (actual time=19.055..31.942 rows=1200 loops=1)
                                                  Hash Cond: ((inventory_fact.principal = inventory_fact_1.principal) AND (inventory_fact._period = (max(inventory_fact_1._period))))
                                                  Buffers: shared hit=6126
                                                  ->  Seq Scan on inventory_fact  (cost=0.00..3671.73 rows=32823 width=34) (actual time=0.691..9.391 rows=32823 loops=1)
                                                        Filter: (NOT is_demo)
                                                        Rows Removed by Filter: 28170
                                                        Buffers: shared hit=3063
                                                  ->  Hash  (cost=3835.86..3835.86 rows=2 width=41) (actual time=17.934..17.936 rows=2 loops=1)
                                                        Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                                        Buffers: shared hit=3063
                                                        ->  HashAggregate  (cost=3835.84..3835.86 rows=2 width=41) (actual time=17.926..17.927 rows=2 loops=1)
                                                              Group Key: inventory_fact_1.principal
                                                              Batches: 1  Memory Usage: 24kB
                                                              Buffers: shared hit=3063
                                                              ->  Seq Scan on inventory_fact inventory_fact_1  (cost=0.00..3671.73 rows=32823 width=17) (actual time=0.333..9.240 rows=32823 loops=1)
                                                                    Filter: (NOT is_demo)
                                                                    Rows Removed by Filter: 28170
                                                                    Buffers: shared hit=3063
                                            ->  Index Scan using product_dimension_pkey on product_dimension pd_pack  (cost=0.28..0.31 rows=1 width=11) (actual time=0.001..0.001 rows=1 loops=1200)
                                                  Index Cond: (product_key = inventory_fact.product_key)
                                                  Buffers: shared hit=3600
              ->  Unique  (cost=1.93..2682.25 rows=1522 width=18) (actual time=0.153..44.393 rows=1537 loops=1)
                    Buffers: shared hit=23459
                    ->  Incremental Sort  (cost=1.93..2623.54 rows=23485 width=18) (actual time=0.153..42.766 rows=23250 loops=1)
                          Sort Key: abc_classification.product_key, abc_classification.classification_period DESC
                          Presorted Key: abc_classification.product_key
                          Full-sort Groups: 583  Sort Method: quicksort  Average Memory: 26kB  Peak Memory: 26kB
                          Pre-sorted Groups: 7  Sort Method: quicksort  Average Memory: 26kB  Peak Memory: 26kB
                          Buffers: shared hit=23459
                          ->  Index Scan using abc_classification_product_key_period_method_key on abc_classification  (cost=0.41..1835.98 rows=23485 width=18) (actual time=0.065..20.690 rows=23277 loops=1)
                                Index Cond: ((classification_period <= '2026-02'::text) AND (method = 'single'::text))
                                Buffers: shared hit=23459
        ->  Hash  (cost=7.84..7.84 rows=74 width=15) (actual time=0.052..0.052 rows=73 loops=1)
              Buckets: 1024  Batches: 1  Memory Usage: 12kB
              Buffers: shared hit=5
              ->  Index Scan using ix_lp_recommendation_status on lp_recommendation  (cost=0.14..7.84 rows=74 width=15) (actual time=0.017..0.039 rows=73 loops=1)
                    Index Cond: ((status = 'pending'::text) AND (planning_cycle_date = '2026-03-01'::date))
                    Buffers: shared hit=5
Planning:
  Buffers: shared hit=23
Planning Time: 0.775 ms
Execution Time: 87.515 ms
```

## #3 — seen 606 ms — `/abc?classification_period=2026-02&view=last_known&principal=unilever`

```sql
WITH latest AS (
            SELECT DISTINCT ON (product_key)
                   product_key, principal, tier, revenue_share,
                   cumulative_share, boundary_flag, classification_period
            FROM abc_classification
            WHERE method = 'single' AND classification_period <= %(period)s AND principal = %(principal)s
            ORDER BY product_key, classification_period DESC
        )
        SELECT
            ac.product_key,
            COALESCE(pd.sku_code, pd.category_path, '') AS sku_id,
            pd.product_name,
            ac.principal,
            ac.tier,
            ac.classification_period AS tier_period,
            ac.revenue_share,
            ac.cumulative_share,
            ac.boundary_flag,
            inv.stock_pieces AS current_stock,
            inv.product_key IS NOT NULL AS has_stock_row,
            rop.rop_i AS reorder_point,
            rop.ss_i AS safety_stock,
            pool_run.p AS pool_period,
            pool.tier AS pool_tier,
            fc.status AS fc_status,
            fc.mase AS fc_mase
        FROM latest ac
        JOIN product_dimension pd ON pd.product_key = ac.product_key
        LEFT JOIN (
    SELECT inv.product_key,
           
    CASE WHEN pd_pack.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd_pack.pack_size::numeric > 0
         THEN SUM(inv.quantity_on_hand) * pd_pack.pack_size::numeric
              + COALESCE(SUM(inv.quantity_pieces), 0)
    END
 AS stock_pieces,
           
    SUM(COALESCE(inv.valuation, inv.quantity_on_hand * inv.unit_cost_per_case))
  AS stock_value_pesos,
           SUM(inv.quantity_on_hand) AS stock_cases
    FROM inventory_fact_real inv
    JOIN product_dimension pd_pack ON pd_pack.product_key = inv.product_key
    JOIN (
        SELECT principal, MAX(_period) AS latest_period
        FROM inventory_fact_real
        GROUP BY principal
    ) latest_inv ON latest_inv.principal = inv.principal AND inv._period = latest_inv.latest_period
    GROUP BY inv.product_key, pd_pack.pack_size
) inv ON inv.product_key = ac.product_key
        LEFT JOIN (
            SELECT product_key, rop_i, ss_i
            FROM lp_recommendation
            WHERE status = 'pending' AND planning_cycle_date = %(current_cycle)s
        ) rop ON rop.product_key = ac.product_key
        
        LEFT JOIN (
            SELECT m.principal, MAX(m.classification_period) AS p
            FROM abc_classification m
            WHERE m.method = 'single'
            GROUP BY m.principal
        ) pool_run ON pool_run.principal = ac.principal
        LEFT JOIN abc_classification pool
               ON pool.product_key = ac.product_key
              AND pool.classification_period = pool_run.p
              AND pool.method = 'single'
        LEFT JOIN (
            SELECT DISTINCT ON (f.product_key) f.product_key, f.status, f.mase
            FROM forecast_result f
            ORDER BY f.product_key, f.forecast_date DESC, f.generated_at DESC
        ) fc ON fc.product_key = ac.product_key
    
        ORDER BY ac.tier,
                 (ac.classification_period = %(period)s) DESC,
                 ac.classification_period DESC,
                 ac.revenue_share DESC NULLS LAST
```

```
Sort  (cost=14240.66..14244.47 rows=1522 width=196) (actual time=119.686..119.772 rows=1531 loops=1)
  Sort Key: abc_classification.tier, ((abc_classification.classification_period = '2026-02'::text)) DESC, abc_classification.classification_period DESC, abc_classification.revenue_share DESC NULLS LAST
  Sort Method: quicksort  Memory: 235kB
  Buffers: shared hit=35607
  ->  Hash Left Join  (cost=12590.70..14160.21 rows=1522 width=196) (actual time=109.656..114.619 rows=1531 loops=1)
        Hash Cond: (abc_classification.product_key = lp_recommendation.product_key)
        Buffers: shared hit=35607
        ->  Hash Join  (cost=12581.94..14143.64 rows=1522 width=178) (actual time=109.565..114.175 rows=1531 loops=1)
              Hash Cond: (abc_classification.product_key = pd.product_key)
              Buffers: shared hit=35602
              ->  Hash Right Join  (cost=12247.23..13804.92 rows=1522 width=120) (actual time=108.420..112.447 rows=1531 loops=1)
                    Hash Cond: ((pool.product_key = abc_classification.product_key) AND (pool.classification_period = pool_run.p))
                    Buffers: shared hit=35332
                    ->  Seq Scan on abc_classification pool  (cost=0.00..1375.38 rows=23485 width=18) (actual time=0.016..7.182 rows=23896 loops=1)
                          Filter: (method = 'single'::text)
                          Rows Removed by Filter: 25437
                          Buffers: shared hit=759
                    ->  Hash  (cost=12224.40..12224.40 rows=1522 width=118) (actual time=102.060..102.069 rows=1531 loops=1)
                          Buckets: 2048  Batches: 1  Memory Usage: 157kB
                          Buffers: shared hit=34573
                          ->  Merge Left Join  (cost=9401.57..12224.40 rows=1522 width=118) (actual time=46.083..101.340 rows=1531 loops=1)
                                Merge Cond: (abc_classification.product_key = f.product_key)
                                Buffers: shared hit=34573
                                ->  Nested Loop Left Join  (cost=9345.61..12160.99 rows=1522 width=109) (actual time=45.944..100.831 rows=1531 loops=1)
                                      Join Filter: (pool_run.principal = abc_classification.principal)
                                      Rows Removed by Join Filter: 1531
                                      Buffers: shared hit=34523
                                      ->  Merge Left Join  (cost=7852.81..10645.34 rows=1522 width=77) (actual time=33.525..87.706 rows=1531 loops=1)
                                            Merge Cond: (abc_classification.product_key = inventory_fact.product_key)
                                            Buffers: shared hit=33764
                                            ->  Unique  (cost=1.96..2740.97 rows=1522 width=37) (actual time=0.145..52.003 rows=1531 loops=1)
                                                  Buffers: shared hit=24038
                                                  ->  Incremental Sort  (cost=1.96..2682.25 rows=23485 width=37) (actual time=0.145..50.403 rows=23223 loops=1)
                                                        Sort Key: abc_classification.product_key, abc_classification.classification_period DESC
                                                        Presorted Key: abc_classification.product_key
                                                        Full-sort Groups: 582  Sort Method: quicksort  Average Memory: 26kB  Peak Memory: 26kB
                                                        Pre-sorted Groups: 7  Sort Method: quicksort  Average Memory: 26kB  Peak Memory: 26kB
                                                        Buffers: shared hit=24038
                                                        ->  Index Scan using abc_classification_product_key_period_method_key on abc_classification  (cost=0.41..1894.69 rows=23485 width=37) (actual time=0.047..22.011 rows=23223 loops=1)
                                                              Index Cond: ((classification_period <= '2026-02'::text) AND (method = 'single'::text))
                                                              Filter: (principal = 'unilever'::text)
                                                              Rows Removed by Filter: 673
                                                              Buffers: shared hit=24038
                                            ->  Materialize  (cost=7850.84..7879.40 rows=476 width=40) (actual time=33.376..35.175 rows=690 loops=1)
                                                  Buffers: shared hit=9726
                                                  ->  GroupAggregate  (cost=7850.84..7873.45 rows=476 width=107) (actual time=33.373..34.970 rows=690 loops=1)
                                                        Group Key: inventory_fact.product_key, pd_pack.pack_size
                                                        Buffers: shared hit=9726
                                                        ->  Sort  (cost=7850.84..7852.03 rows=476 width=20) (actual time=33.346..33.465 rows=692 loops=1)
                                                              Sort Key: inventory_fact.product_key, pd_pack.pack_size
                                                              Sort Method: quicksort  Memory: 95kB
                                                              Buffers: shared hit=9726
                                                              ->  Nested Loop  (cost=3836.18..7829.67 rows=476 width=20) (actual time=18.553..33.016 rows=1200 loops=1)
                                                                    Buffers: shared hit=9726
                                                                    ->  Hash Join  (cost=3835.89..7682.86 rows=476 width=17) (actual time=18.533..31.128 rows=1200 loops=1)
                                                                          Hash Cond: ((inventory_fact.principal = inventory_fact_1.principal) AND (inventory_fact._period = (max(inventory_fact_1._period))))
                                                                          Buffers: shared hit=6126
                                                                          ->  Seq Scan on inventory_fact  (cost=0.00..3671.73 rows=32823 width=34) (actual time=0.655..9.213 rows=32823 loops=1)
                                                                                Filter: (NOT is_demo)
                                                                                Rows Removed by Filter: 28170
                                                                                Buffers: shared hit=3063
                                                                          ->  Hash  (cost=3835.86..3835.86 rows=2 width=41) (actual time=17.425..17.426 rows=2 loops=1)
                                                                                Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                                                                Buffers: shared hit=3063
                                                                                ->  HashAggregate  (cost=3835.84..3835.86 rows=2 width=41) (actual time=17.416..17.418 rows=2 loops=1)
                                                                                      Group Key: inventory_fact_1.principal
                                                                                      Batches: 1  Memory Usage: 24kB
                                                                                      Buffers: shared hit=3063
                                                                                      ->  Seq Scan on inventory_fact inventory_fact_1  (cost=0.00..3671.73 rows=32823 width=17) (actual time=0.295..8.902 rows=32823 loops=1)
                                                                                            Filter: (NOT is_demo)
                                                                                            Rows Removed by Filter: 28170
                                                                                            Buffers: shared hit=3063
                                                                    ->  Index Scan using product_dimension_pkey on product_dimension pd_pack  (cost=0.28..0.31 rows=1 width=11) (actual time=0.001..0.001 rows=1 loops=1200)
                                                                          Index Cond: (product_key = inventory_fact.product_key)
                                                                          Buffers: shared hit=3600
                                      ->  Materialize  (cost=1492.80..1492.83 rows=1 width=41) (actual time=0.008..0.008 rows=2 loops=1531)
                                            Buffers: shared hit=759
                                            ->  Subquery Scan on pool_run  (cost=1492.80..1492.82 rows=1 width=41) (actual time=12.408..12.410 rows=2 loops=1)
                                                  Buffers: shared hit=759
                                                  ->  HashAggregate  (cost=1492.80..1492.81 rows=1 width=41) (actual time=12.408..12.409 rows=2 loops=1)
                                                        Group Key: m.principal
                                                        Batches: 1  Memory Usage: 24kB
                                                        Buffers: shared hit=759
                                                        ->  Seq Scan on abc_classification m  (cost=0.00..1375.38 rows=23485 width=17) (actual time=0.016..7.299 rows=23896 loops=1)
                                                              Filter: (method = 'single'::text)
                                                              Rows Removed by Filter: 25437
                                                              Buffers: shared hit=759
                                ->  Unique  (cost=55.97..56.63 rows=132 width=29) (actual time=0.135..0.181 rows=132 loops=1)
                                      Buffers: shared hit=50
                                      ->  Sort  (cost=55.97..56.30 rows=132 width=29) (actual time=0.134..0.152 rows=132 loops=1)
                                            Sort Key: f.product_key, f.forecast_date DESC, f.generated_at DESC
                                            Sort Method: quicksort  Memory: 31kB
                                            Buffers: shared hit=50
                                            ->  Seq Scan on forecast_result f  (cost=0.00..51.32 rows=132 width=29) (actual time=0.015..0.096 rows=132 loops=1)
                                                  Buffers: shared hit=50
              ->  Hash  (cost=298.76..298.76 rows=2876 width=66) (actual time=1.137..1.138 rows=2783 loops=1)
                    Buckets: 4096  Batches: 1  Memory Usage: 302kB
                    Buffers: shared hit=270
                    ->  Seq Scan on product_dimension pd  (cost=0.00..298.76 rows=2876 width=66) (actual time=0.016..0.566 rows=2783 loops=1)
                          Buffers: shared hit=270
        ->  Hash  (cost=7.84..7.84 rows=74 width=22) (actual time=0.060..0.061 rows=73 loops=1)
              Buckets: 1024  Batches: 1  Memory Usage: 13kB
              Buffers: shared hit=5
              ->  Index Scan using ix_lp_recommendation_status on lp_recommendation  (cost=0.14..7.84 rows=74 width=22) (actual time=0.022..0.045 rows=73 loops=1)
                    Index Cond: ((status = 'pending'::text) AND (planning_cycle_date = '2026-03-01'::date))
                    Buffers: shared hit=5
Planning:
  Buffers: shared hit=12
Planning Time: 1.672 ms
Execution Time: 120.192 ms
```

## #4 — seen 536 ms — `/fsn?principal=unilever&period=2026-02`

```sql
SELECT d.product_key, pd.sku_code AS sku_id, d.calendar_month AS period, SUM(d.quantity_sold) AS qty
        FROM Unilever_SKU_Demand_Fact_Real d
        JOIN Product_Dimension pd ON pd.product_key = d.product_key
        WHERE d.calendar_month = ANY(%(months)s)
        GROUP BY d.product_key, pd.sku_code, d.calendar_month
```

```
HashAggregate  (cost=1996.13..2069.18 rows=5844 width=56) (actual time=25.649..29.769 rows=8735 loops=1)
  Group Key: unilever_sku_demand_fact.product_key, pd.sku_code, unilever_sku_demand_fact.calendar_month
  Batches: 1  Memory Usage: 3857kB
  Buffers: shared hit=1414
  ->  Hash Join  (cost=335.12..1937.69 rows=5844 width=29) (actual time=1.185..20.637 rows=8735 loops=1)
        Hash Cond: (unilever_sku_demand_fact.product_key = pd.product_key)
        Buffers: shared hit=1414
        ->  Index Scan using unilever_sku_demand_fact_sku_code_calendar_month_key on unilever_sku_demand_fact  (cost=0.41..1587.62 rows=5844 width=21) (actual time=0.046..17.829 rows=8735 loops=1)
              Index Cond: (calendar_month = ANY ('{2025-03,2025-04,2025-05,2025-06,2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02}'::text[]))
              Filter: (NOT is_demo)
              Buffers: shared hit=1144
        ->  Hash  (cost=298.76..298.76 rows=2876 width=16) (actual time=1.127..1.129 rows=2783 loops=1)
              Buckets: 4096  Batches: 1  Memory Usage: 182kB
              Buffers: shared hit=270
              ->  Seq Scan on product_dimension pd  (cost=0.00..298.76 rows=2876 width=16) (actual time=0.010..0.629 rows=2783 loops=1)
                    Buffers: shared hit=270
Planning:
  Buffers: shared hit=13
Planning Time: 0.302 ms
Execution Time: 30.182 ms
```

## #5 — seen 528 ms — `/dashboard?period=2026-02&start_period=2025-03&principal=unilever`

```sql
SELECT _period AS period, SUM(receipt_value) AS total,
               COUNT(*) FILTER (WHERE flag = 'negative_balance') AS negative_skus, COUNT(*) AS skus
        FROM derived_receipt_fact
        WHERE principal = 'unilever' AND _period = ANY(%(periods)s)
        GROUP BY _period
```

```
GroupAggregate  (cost=0.29..783.91 rows=37 width=56) (actual time=0.605..6.486 rows=12 loops=1)
  Group Key: _period
  Buffers: shared hit=3822
  ->  Index Scan using ix_derived_receipt_fact_period on derived_receipt_fact  (cost=0.29..668.90 rows=9164 width=31) (actual time=0.027..3.612 rows=9164 loops=1)
        Index Cond: ((principal = 'unilever'::text) AND (_period = ANY ('{2025-03,2025-04,2025-05,2025-06,2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02}'::text[])))
        Buffers: shared hit=3822
Planning Time: 0.128 ms
Execution Time: 6.526 ms
```

## #6 — seen 460 ms — `/abc?principal=unilever`

```sql
SELECT
            ac.product_key,
            COALESCE(pd.sku_code, pd.category_path, '') AS sku_id,
            pd.product_name,
            ac.principal,
            ac.tier,
            ac.revenue_share,
            ac.cumulative_share,
            ac.boundary_flag,
            inv.stock_pieces AS current_stock,
            inv.product_key IS NOT NULL AS has_stock_row,
            rop.rop_i AS reorder_point,
            rop.ss_i AS safety_stock,
            pool_run.p AS pool_period,
            pool.tier AS pool_tier,
            fc.status AS fc_status,
            fc.mase AS fc_mase
        FROM abc_classification ac
        JOIN product_dimension pd ON pd.product_key = ac.product_key
        LEFT JOIN (
    SELECT inv.product_key,
           
    CASE WHEN pd_pack.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd_pack.pack_size::numeric > 0
         THEN SUM(inv.quantity_on_hand) * pd_pack.pack_size::numeric
              + COALESCE(SUM(inv.quantity_pieces), 0)
    END
 AS stock_pieces,
           
    SUM(COALESCE(inv.valuation, inv.quantity_on_hand * inv.unit_cost_per_case))
  AS stock_value_pesos,
           SUM(inv.quantity_on_hand) AS stock_cases
    FROM inventory_fact_real inv
    JOIN product_dimension pd_pack ON pd_pack.product_key = inv.product_key
    JOIN (
        SELECT principal, MAX(_period) AS latest_period
        FROM inventory_fact_real
        GROUP BY principal
    ) latest_inv ON latest_inv.principal = inv.principal AND inv._period = latest_inv.latest_period
    GROUP BY inv.product_key, pd_pack.pack_size
) inv ON inv.product_key = ac.product_key
        LEFT JOIN (
            SELECT product_key, rop_i, ss_i
            FROM lp_recommendation
            WHERE status = 'pending' AND planning_cycle_date = %(current_cycle)s
        ) rop ON rop.product_key = ac.product_key
        
        LEFT JOIN (
            SELECT m.principal, MAX(m.classification_period) AS p
            FROM abc_classification m
            WHERE m.method = 'single'
            GROUP BY m.principal
        ) pool_run ON pool_run.principal = ac.principal
        LEFT JOIN abc_classification pool
               ON pool.product_key = ac.product_key
              AND pool.classification_period = pool_run.p
              AND pool.method = 'single'
        LEFT JOIN (
            SELECT DISTINCT ON (f.product_key) f.product_key, f.status, f.mase
            FROM forecast_result f
            ORDER BY f.product_key, f.forecast_date DESC, f.generated_at DESC
        ) fc ON fc.product_key = ac.product_key
    
        WHERE ac.classification_period = %(period)s AND ac.method = 'single'
     AND ac.principal = %(principal)s ORDER BY ac.tier, ac.revenue_share DESC NULLS LAST
```

```
Sort  (cost=12777.01..12778.92 rows=766 width=187) (actual time=54.917..54.965 rows=710 loops=1)
  Sort Key: ac.tier, ac.revenue_share DESC NULLS LAST
  Sort Method: quicksort  Memory: 108kB
  Buffers: shared hit=14667
  ->  Hash Left Join  (cost=7916.69..12740.31 rows=766 width=187) (actual time=44.678..53.833 rows=710 loops=1)
        Hash Cond: (ac.product_key = lp_recommendation.product_key)
        Buffers: shared hit=14667
        ->  Merge Left Join  (cost=7907.93..12729.53 rows=766 width=170) (actual time=44.616..53.566 rows=710 loops=1)
              Merge Cond: (ac.product_key = f.product_key)
              Buffers: shared hit=14662
              ->  Merge Join  (cost=7851.96..12668.67 rows=766 width=161) (actual time=44.478..53.214 rows=710 loops=1)
                    Merge Cond: (ac.product_key = pd.product_key)
                    Buffers: shared hit=14612
                    ->  Merge Left Join  (cost=7851.68..12406.50 rows=766 width=103) (actual time=44.453..52.363 rows=710 loops=1)
                          Merge Cond: (ac.product_key = inventory_fact.product_key)
                          Buffers: shared hit=14184
                          ->  Nested Loop Left Join  (cost=0.84..4521.59 rows=766 width=63) (actual time=10.667..16.477 rows=710 loops=1)
                                Buffers: shared hit=4458
                                ->  Nested Loop Left Join  (cost=0.41..2903.57 rows=766 width=61) (actual time=10.632..13.957 rows=710 loops=1)
                                      Buffers: shared hit=1618
                                      ->  Index Scan using abc_classification_product_key_period_method_key on abc_classification ac  (cost=0.41..1336.61 rows=766 width=29) (actual time=0.043..3.052 rows=710 loops=1)
                                            Index Cond: ((classification_period = '2026-02'::text) AND (method = 'single'::text))
                                            Filter: (principal = 'unilever'::text)
                                            Buffers: shared hit=859
                                      ->  Materialize  (cost=0.00..1557.39 rows=1 width=41) (actual time=0.015..0.015 rows=1 loops=710)
                                            Buffers: shared hit=759
                                            ->  Subquery Scan on pool_run  (cost=0.00..1557.38 rows=1 width=41) (actual time=10.583..10.585 rows=1 loops=1)
                                                  Buffers: shared hit=759
                                                  ->  GroupAggregate  (cost=0.00..1557.37 rows=1 width=41) (actual time=10.582..10.583 rows=1 loops=1)
                                                        Buffers: shared hit=759
                                                        ->  Seq Scan on abc_classification m  (cost=0.00..1498.65 rows=23485 width=17) (actual time=0.015..8.464 rows=23223 loops=1)
                                                              Filter: ((method = 'single'::text) AND (principal = 'unilever'::text))
                                                              Rows Removed by Filter: 26110
                                                              Buffers: shared hit=759
                                ->  Memoize  (cost=0.42..2.65 rows=1 width=18) (actual time=0.003..0.003 rows=1 loops=710)
                                      Cache Key: ac.product_key, pool_run.p
                                      Cache Mode: logical
                                      Hits: 0  Misses: 710  Evictions: 0  Overflows: 0  Memory Usage: 95kB
                                      Buffers: shared hit=2840
                                      ->  Index Scan using abc_classification_product_key_period_method_key on abc_classification pool  (cost=0.41..2.64 rows=1 width=18) (actual time=0.002..0.002 rows=1 loops=710)
                                            Index Cond: ((product_key = ac.product_key) AND (classification_period = pool_run.p) AND (method = 'single'::text))
                                            Buffers: shared hit=2840
                          ->  Materialize  (cost=7850.84..7879.40 rows=476 width=40) (actual time=33.774..35.582 rows=690 loops=1)
                                Buffers: shared hit=9726
                                ->  GroupAggregate  (cost=7850.84..7873.45 rows=476 width=107) (actual time=33.770..35.372 rows=690 loops=1)
                                      Group Key: inventory_fact.product_key, pd_pack.pack_size
                                      Buffers: shared hit=9726
                                      ->  Sort  (cost=7850.84..7852.03 rows=476 width=20) (actual time=33.743..33.830 rows=692 loops=1)
                                            Sort Key: inventory_fact.product_key, pd_pack.pack_size
                                            Sort Method: quicksort  Memory: 95kB
                                            Buffers: shared hit=9726
                                            ->  Nested Loop  (cost=3836.18..7829.67 rows=476 width=20) (actual time=18.843..33.462 rows=1200 loops=1)
                                                  Buffers: shared hit=9726
                                                  ->  Hash Join  (cost=3835.89..7682.86 rows=476 width=17) (actual time=18.824..31.653 rows=1200 loops=1)
                                                        Hash Cond: ((inventory_fact.principal = inventory_fact_1.principal) AND (inventory_fact._period = (max(inventory_fact_1._period))))
                                                        Buffers: shared hit=6126
                                                        ->  Seq Scan on inventory_fact  (cost=0.00..3671.73 rows=32823 width=34) (actual time=0.712..9.443 rows=32823 loops=1)
                                                              Filter: (NOT is_demo)
                                                              Rows Removed by Filter: 28170
                                                              Buffers: shared hit=3063
                                                        ->  Hash  (cost=3835.86..3835.86 rows=2 width=41) (actual time=17.707..17.709 rows=2 loops=1)
                                                              Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                                              Buffers: shared hit=3063
                                                              ->  HashAggregate  (cost=3835.84..3835.86 rows=2 width=41) (actual time=17.698..17.700 rows=2 loops=1)
                                                                    Group Key: inventory_fact_1.principal
                                                                    Batches: 1  Memory Usage: 24kB
                                                                    Buffers: shared hit=3063
                                                                    ->  Seq Scan on inventory_fact inventory_fact_1  (cost=0.00..3671.73 rows=32823 width=17) (actual time=0.351..9.184 rows=32823 loops=1)
                                                                          Filter: (NOT is_demo)
                                                                          Rows Removed by Filter: 28170
                                                                          Buffers: shared hit=3063
                                                  ->  Index Scan using product_dimension_pkey on product_dimension pd_pack  (cost=0.28..0.31 rows=1 width=11) (actual time=0.001..0.001 rows=1 loops=1200)
                                                        Index Cond: (product_key = inventory_fact.product_key)
                                                        Buffers: shared hit=3600
                    ->  Index Scan using product_dimension_pkey on product_dimension pd  (cost=0.28..400.08 rows=2876 width=66) (actual time=0.018..0.465 rows=1807 loops=1)
                          Buffers: shared hit=428
              ->  Unique  (cost=55.97..56.63 rows=132 width=29) (actual time=0.134..0.180 rows=132 loops=1)
                    Buffers: shared hit=50
                    ->  Sort  (cost=55.97..56.30 rows=132 width=29) (actual time=0.134..0.150 rows=132 loops=1)
                          Sort Key: f.product_key, f.forecast_date DESC, f.generated_at DESC
                          Sort Method: quicksort  Memory: 31kB
                          Buffers: shared hit=50
                          ->  Seq Scan on forecast_result f  (cost=0.00..51.32 rows=132 width=29) (actual time=0.015..0.098 rows=132 loops=1)
                                Buffers: shared hit=50
        ->  Hash  (cost=7.84..7.84 rows=74 width=22) (actual time=0.053..0.054 rows=73 loops=1)
              Buckets: 1024  Batches: 1  Memory Usage: 13kB
              Buffers: shared hit=5
              ->  Index Scan using ix_lp_recommendation_status on lp_recommendation  (cost=0.14..7.84 rows=74 width=22) (actual time=0.016..0.039 rows=73 loops=1)
                    Index Cond: ((status = 'pending'::text) AND (planning_cycle_date = '2026-03-01'::date))
                    Buffers: shared hit=5
Planning:
  Buffers: shared hit=55
Planning Time: 2.033 ms
Execution Time: 55.192 ms
```

## #7 — seen 414 ms — `/dashboard?period=2026-02&start_period=2026-02&principal=unilever`

```sql
SELECT calendar_month AS period, SUM(net_amount) AS total
            FROM Unilever_SKU_Demand_Fact_Real
            WHERE calendar_month = ANY(%(periods)s)
            GROUP BY calendar_month
```

```
HashAggregate  (cost=1094.97..1095.82 rows=68 width=40) (actual time=7.529..7.530 rows=1 loops=1)
  Group Key: unilever_sku_demand_fact.calendar_month
  Batches: 1  Memory Usage: 24kB
  Buffers: shared hit=893
  ->  Index Scan using unilever_sku_demand_fact_sku_code_calendar_month_key on unilever_sku_demand_fact  (cost=0.41..1092.38 rows=519 width=16) (actual time=0.067..7.291 rows=779 loops=1)
        Index Cond: (calendar_month = ANY ('{2026-02}'::text[]))
        Filter: (NOT is_demo)
        Buffers: shared hit=893
Planning Time: 0.154 ms
Execution Time: 7.578 ms
```

## #8 — seen 255 ms — `/dashboard?period=2026-02&start_period=2026-02&principal=unilever`

```sql
SELECT DISTINCT _period AS p FROM SellOut_Fact_Real WHERE net_amount_tax_inclusive
```

```
Unique  (cost=384.65..384.79 rows=23 width=8) (actual time=0.940..0.959 rows=1 loops=1)
  Buffers: shared hit=324
  ->  Sort  (cost=384.65..384.72 rows=28 width=8) (actual time=0.939..0.946 rows=122 loops=1)
        Sort Key: sellout_fact._period
        Sort Method: quicksort  Memory: 25kB
        Buffers: shared hit=324
        ->  Seq Scan on sellout_fact  (cost=0.00..383.98 rows=28 width=8) (actual time=0.695..0.910 rows=122 loops=1)
              Filter: ((NOT is_demo) AND net_amount_tax_inclusive)
              Rows Removed by Filter: 5884
              Buffers: shared hit=324
Planning Time: 0.088 ms
Execution Time: 0.983 ms
```

## #9 — seen 252 ms — `/recommendations?status=pending&principal=unilever`

```sql
SELECT
        lr.recommendation_key,
        COALESCE(pd.sku_code, pd.category_path) AS sku_id,
        pd.product_name,
        pd.principal,
        CASE WHEN pd.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd.pack_size::numeric > 0 THEN pd.pack_size::numeric END AS pack_size,
        lr.planning_cycle_date,
        lr.q_i,
        lr.rop_i,
        lr.ss_i,
        lr.status,
        inv.stock_pieces AS current_stock,
        inv.stock_cases AS current_stock_cases,
        inv.stock_value_pesos AS stock_value_pesos,
        CASE WHEN inv.product_key IS NOT NULL THEN TRUE
             WHEN counted.principal IS NOT NULL THEN FALSE
        END AS in_stock_count,
        abc.revenue_share AS revenue_share,
        abc.tier AS tier,
        sales.avg_monthly_sales_pesos AS avg_monthly_sales_pesos,
        fr.forecast_value AS forecast_units
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    LEFT JOIN Forecast_Result fr
      ON fr.product_key = lr.product_key AND fr.forecast_date = lr.planning_cycle_date
    LEFT JOIN (
        
    SELECT inv.product_key,
           
    CASE WHEN pd_pack.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd_pack.pack_size::numeric > 0
         THEN SUM(inv.quantity_on_hand) * pd_pack.pack_size::numeric
              + COALESCE(SUM(inv.quantity_pieces), 0)
    END
 AS stock_pieces,
           
    SUM(COALESCE(inv.valuation, inv.quantity_on_hand * inv.unit_cost_per_case))
  AS stock_value_pesos,
           SUM(inv.quantity_on_hand) AS stock_cases
    FROM inventory_fact_real inv
    JOIN product_dimension pd_pack ON pd_pack.product_key = inv.product_key
    WHERE inv._period = %(inv_period)s
    GROUP BY inv.product_key, pd_pack.pack_size

    ) inv ON inv.product_key = lr.product_key
    LEFT JOIN (
        SELECT DISTINCT principal FROM inventory_fact_real WHERE _period = %(inv_period)s
    ) counted ON counted.principal = pd.principal
    LEFT JOIN (
        SELECT DISTINCT ON (product_key) product_key, revenue_share, tier
        FROM abc_classification
        WHERE method = 'single' AND classification_period = %(abc_period)s
        ORDER BY product_key, classification_period DESC
    ) abc ON abc.product_key = lr.product_key
    LEFT JOIN (
        SELECT recent.product_key, SUM(recent.month_total) / MAX(sales_window.months) AS avg_monthly_sales_pesos
        FROM (
            SELECT product_key, calendar_month, SUM(net_amount) AS month_total
            FROM unilever_sku_demand_fact_real
            WHERE calendar_month IN (
                SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
                WHERE calendar_month <= %(inv_period)s
                ORDER BY calendar_month DESC LIMIT 3
            )
            GROUP BY product_key, calendar_month
        ) recent
        CROSS JOIN (
            SELECT COUNT(*) AS months FROM (
                SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
                WHERE calendar_month <= %(inv_period)s
                ORDER BY calendar_month DESC LIMIT 3
            ) window_months
        ) sales_window
        GROUP BY recent.product_key
    ) sales ON sales.product_key = lr.product_key
 WHERE 1=1 AND pd.principal = %(principal)s AND lr.status = %(status)s AND lr.planning_cycle_date = %(current_cycle)s ORDER BY lr.rop_i DESC
```

```
Sort  (cost=10415.88..10416.20 rows=128 width=292) (actual time=52.479..52.497 rows=73 loops=1)
  Sort Key: lr.rop_i DESC
  Sort Method: quicksort  Memory: 36kB
  Buffers: shared hit=9154
  ->  Hash Left Join  (cost=10152.67..10411.40 rows=128 width=292) (actual time=49.815..52.429 rows=73 loops=1)
        Hash Cond: (lr.product_key = sales.product_key)
        Buffers: shared hit=9154
        ->  Merge Left Join  (cost=5421.94..5678.41 rows=128 width=245) (actual time=16.130..18.641 rows=73 loops=1)
              Merge Cond: (lr.product_key = inventory_fact_1.product_key)
              Buffers: shared hit=5968
              ->  Nested Loop Left Join  (cost=1233.94..1446.86 rows=54 width=141) (actual time=5.380..5.968 rows=73 loops=1)
                    Buffers: shared hit=2635
                    ->  Nested Loop Left Join  (cost=1233.94..1435.91 rows=54 width=132) (actual time=0.755..1.309 rows=73 loops=1)
                          Buffers: shared hit=445
                          ->  Nested Loop  (cost=1233.80..1390.34 rows=54 width=125) (actual time=0.749..1.181 rows=73 loops=1)
                                Buffers: shared hit=299
                                ->  Merge Left Join  (cost=1233.52..1246.03 rows=74 width=55) (actual time=0.741..0.990 rows=73 loops=1)
                                      Merge Cond: (lr.product_key = abc_classification.product_key)
                                      Buffers: shared hit=80
                                      ->  Sort  (cost=10.14..10.32 rows=74 width=49) (actual time=0.071..0.079 rows=73 loops=1)
                                            Sort Key: lr.product_key
                                            Sort Method: quicksort  Memory: 29kB
                                            Buffers: shared hit=5
                                            ->  Index Scan using ix_lp_recommendation_status on lp_recommendation lr  (cost=0.14..7.84 rows=74 width=49) (actual time=0.022..0.046 rows=73 loops=1)
                                                  Index Cond: ((status = 'pending'::text) AND (planning_cycle_date = '2026-03-01'::date))
                                                  Buffers: shared hit=5
                                      ->  Unique  (cost=1223.38..1227.21 rows=606 width=22) (actual time=0.661..0.833 rows=685 loops=1)
                                            Buffers: shared hit=75
                                            ->  Sort  (cost=1223.38..1225.30 rows=766 width=22) (actual time=0.661..0.732 rows=685 loops=1)
                                                  Sort Key: abc_classification.product_key
                                                  Sort Method: quicksort  Memory: 52kB
                                                  Buffers: shared hit=75
                                                  ->  Index Scan using ix_abc_classification_tier on abc_classification  (cost=0.29..1186.69 rows=766 width=22) (actual time=0.034..0.499 rows=710 loops=1)
                                                        Index Cond: (classification_period = '2026-02'::text)
                                                        Filter: (method = 'single'::text)
                                                        Rows Removed by Filter: 843
                                                        Buffers: shared hit=75
                                ->  Index Scan using product_dimension_pkey on product_dimension pd  (cost=0.28..1.95 rows=1 width=78) (actual time=0.002..0.002 rows=1 loops=73)
                                      Index Cond: (product_key = lr.product_key)
                                      Filter: (principal = 'unilever'::text)
                                      Buffers: shared hit=219
                          ->  Index Scan using ix_forecast_result_product on forecast_result fr  (cost=0.14..0.83 rows=1 width=19) (actual time=0.001..0.001 rows=1 loops=73)
                                Index Cond: (product_key = lr.product_key)
                                Filter: (forecast_date = '2026-03-01'::date)
                                Buffers: shared hit=146
                    ->  Materialize  (cost=0.00..10.28 rows=1 width=9) (actual time=0.063..0.063 rows=1 loops=73)
                          Buffers: shared hit=2190
                          ->  Limit  (cost=0.00..10.27 rows=1 width=9) (actual time=4.617..4.618 rows=1 loops=1)
                                Buffers: shared hit=2190
                                ->  Seq Scan on inventory_fact  (cost=0.00..3976.09 rows=387 width=9) (actual time=4.615..4.615 rows=1 loops=1)
                                      Filter: ((NOT is_demo) AND (_period = '2026-02'::text) AND (principal = 'unilever'::text))
                                      Rows Removed by Filter: 26899
                                      Buffers: shared hit=2190
              ->  Materialize  (cost=4188.00..4228.63 rows=602 width=104) (actual time=10.715..12.562 rows=715 loops=1)
                    Buffers: shared hit=3333
                    ->  GroupAggregate  (cost=4188.00..4221.11 rows=602 width=107) (actual time=10.711..12.343 rows=715 loops=1)
                          Group Key: inventory_fact_1.product_key, pd_pack.pack_size
                          Buffers: shared hit=3333
                          ->  Sort  (cost=4188.00..4189.50 rows=602 width=33) (actual time=10.685..10.764 rows=716 loops=1)
                                Sort Key: inventory_fact_1.product_key, pd_pack.pack_size
                                Sort Method: quicksort  Memory: 68kB
                                Buffers: shared hit=3333
                                ->  Hash Join  (cost=334.71..4160.20 rows=602 width=33) (actual time=5.455..10.483 rows=812 loops=1)
                                      Hash Cond: (inventory_fact_1.product_key = pd_pack.product_key)
                                      Buffers: shared hit=3333
                                      ->  Seq Scan on inventory_fact inventory_fact_1  (cost=0.00..3823.91 rows=602 width=30) (actual time=4.513..9.358 rows=812 loops=1)
                                            Filter: ((NOT is_demo) AND (_period = '2026-02'::text))
                                            Rows Removed by Filter: 60181
                                            Buffers: shared hit=3063
                                      ->  Hash  (cost=298.76..298.76 rows=2876 width=11) (actual time=0.923..0.924 rows=2783 loops=1)
                                            Buckets: 4096  Batches: 1  Memory Usage: 159kB
                                            Buffers: shared hit=270
                                            ->  Seq Scan on product_dimension pd_pack  (cost=0.00..298.76 rows=2876 width=11) (actual time=0.014..0.532 rows=2783 loops=1)
                                                  Buffers: shared hit=270
        ->  Hash  (cost=4728.23..4728.23 rows=200 width=40) (actual time=33.663..33.670 rows=904 loops=1)
              Buckets: 1024  Batches: 1  Memory Usage: 57kB
              Buffers: shared hit=3186
              ->  Subquery Scan on sales  (cost=4722.73..4728.23 rows=200 width=40) (actual time=33.039..33.537 rows=904 loops=1)
                    Buffers: shared hit=3186
                    ->  HashAggregate  (cost=4722.73..4726.23 rows=200 width=40) (actual time=33.037..33.455 rows=904 loops=1)
                          Group Key: unilever_sku_demand_fact_1.product_key
                          Batches: 1  Memory Usage: 441kB
                          Buffers: shared hit=3186
                          ->  Nested Loop  (cost=4678.80..4714.49 rows=1098 width=48) (actual time=31.330..32.416 rows=2236 loops=1)
                                Buffers: shared hit=3186
                                ->  Aggregate  (cost=1583.82..1583.83 rows=1 width=8) (actual time=11.429..11.431 rows=1 loops=1)
                                      Buffers: shared hit=1062
                                      ->  Limit  (cost=1583.78..1583.79 rows=3 width=8) (actual time=11.424..11.427 rows=3 loops=1)
                                            Buffers: shared hit=1062
                                            ->  Sort  (cost=1583.78..1583.95 rows=68 width=8) (actual time=11.423..11.424 rows=3 loops=1)
                                                  Sort Key: unilever_sku_demand_fact.calendar_month DESC
                                                  Sort Method: top-N heapsort  Memory: 24kB
                                                  Buffers: shared hit=1062
                                                  ->  HashAggregate  (cost=1582.22..1582.90 rows=68 width=8) (actual time=11.400..11.406 rows=38 loops=1)
                                                        Group Key: unilever_sku_demand_fact.calendar_month
                                                        Batches: 1  Memory Usage: 24kB
                                                        Buffers: shared hit=1062
                                                        ->  Seq Scan on unilever_sku_demand_fact  (cost=0.00..1526.36 rows=22343 width=8) (actual time=0.017..7.307 rows=24906 loops=1)
                                                              Filter: ((NOT is_demo) AND (calendar_month <= '2026-02'::text))
                                                              Rows Removed by Filter: 12243
                                                              Buffers: shared hit=1062
                                ->  HashAggregate  (cost=3094.97..3108.70 rows=1098 width=48) (actual time=19.897..20.770 rows=2236 loops=1)
                                      Group Key: unilever_sku_demand_fact_1.product_key, unilever_sku_demand_fact_1.calendar_month
                                      Batches: 1  Memory Usage: 1009kB
                                      Buffers: shared hit=2124
                                      ->  Hash Join  (cost=1583.82..3086.74 rows=1098 width=24) (actual time=11.339..18.872 rows=2236 loops=1)
                                            Hash Cond: (unilever_sku_demand_fact_1.calendar_month = unilever_sku_demand_fact_2.calendar_month)
                                            Buffers: shared hit=2124
                                            ->  Seq Scan on unilever_sku_demand_fact unilever_sku_demand_fact_1  (cost=0.00..1433.49 rows=24896 width=24) (actual time=0.015..5.052 rows=24906 loops=1)
                                                  Filter: (NOT is_demo)
                                                  Rows Removed by Filter: 12243
                                                  Buffers: shared hit=1062
                                            ->  Hash  (cost=1583.79..1583.79 rows=3 width=8) (actual time=11.296..11.298 rows=3 loops=1)
                                                  Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                                  Buffers: shared hit=1062
                                                  ->  Limit  (cost=1583.78..1583.79 rows=3 width=8) (actual time=11.289..11.291 rows=3 loops=1)
                                                        Buffers: shared hit=1062
                                                        ->  Sort  (cost=1583.78..1583.95 rows=68 width=8) (actual time=11.287..11.289 rows=3 loops=1)
                                                              Sort Key: unilever_sku_demand_fact_2.calendar_month DESC
                                                              Sort Method: top-N heapsort  Memory: 24kB
                                                              Buffers: shared hit=1062
                                                              ->  HashAggregate  (cost=1582.22..1582.90 rows=68 width=8) (actual time=11.258..11.264 rows=38 loops=1)
                                                                    Group Key: unilever_sku_demand_fact_2.calendar_month
                                                                    Batches: 1  Memory Usage: 24kB
                                                                    Buffers: shared hit=1062
                                                                    ->  Seq Scan on unilever_sku_demand_fact unilever_sku_demand_fact_2  (cost=0.00..1526.36 rows=22343 width=8) (actual time=0.006..7.236 rows=24906 loops=1)
                                                                          Filter: ((NOT is_demo) AND (calendar_month <= '2026-02'::text))
                                                                          Rows Removed by Filter: 12243
                                                                          Buffers: shared hit=1062
Planning:
  Buffers: shared hit=33
Planning Time: 1.685 ms
Execution Time: 52.739 ms
```

## #10 — seen 226 ms — `/dashboard?period=2026-02&start_period=2026-02&principal=unilever`

```sql
SELECT
                    ac.tier,
                    inv.any_active AS any_active,
                    inv.any_inactive AS any_inactive
                FROM ABC_Classification ac
                LEFT JOIN (
                    SELECT
                        product_key,
                        BOOL_OR(stock_status = 'Active') AS any_active,
                        BOOL_OR(stock_status = 'Inactive') AS any_inactive
                    FROM Inventory_Fact_Real
                    WHERE _period = %(inv_period)s
                    GROUP BY product_key
                ) inv ON inv.product_key = ac.product_key
                WHERE ac.classification_period = %(period)s AND ac.method = 'single' AND ac.principal = 'unilever'
```

```
Hash Left Join  (cost=3878.19..5070.63 rows=766 width=4) (actual time=11.055..11.680 rows=710 loops=1)
  Hash Cond: (ac.product_key = inv.product_key)
  Buffers: shared hit=3138
  ->  Index Scan using ix_abc_classification_tier on abc_classification ac  (cost=0.29..1190.71 rows=766 width=10) (actual time=0.042..0.545 rows=710 loops=1)
        Index Cond: (classification_period = '2026-02'::text)
        Filter: ((method = 'single'::text) AND (principal = 'unilever'::text))
        Rows Removed by Filter: 843
        Buffers: shared hit=75
  ->  Hash  (cost=3871.30..3871.30 rows=528 width=10) (actual time=10.293..10.294 rows=785 loops=1)
        Buckets: 1024  Batches: 1  Memory Usage: 45kB
        Buffers: shared hit=3063
        ->  Subquery Scan on inv  (cost=3851.71..3871.30 rows=528 width=10) (actual time=9.759..10.169 rows=785 loops=1)
              Buffers: shared hit=3063
              ->  GroupAggregate  (cost=3851.71..3866.02 rows=528 width=10) (actual time=9.758..10.095 rows=785 loops=1)
                    Group Key: inventory_fact.product_key
                    Buffers: shared hit=3063
                    ->  Sort  (cost=3851.71..3853.21 rows=602 width=15) (actual time=9.745..9.795 rows=785 loops=1)
                          Sort Key: inventory_fact.product_key
                          Sort Method: quicksort  Memory: 49kB
                          Buffers: shared hit=3063
                          ->  Seq Scan on inventory_fact  (cost=0.00..3823.91 rows=602 width=15) (actual time=5.411..9.597 rows=785 loops=1)
                                Filter: ((NOT is_demo) AND (_period = '2026-03'::text))
                                Rows Removed by Filter: 60208
                                Buffers: shared hit=3063
Planning Time: 0.213 ms
Execution Time: 11.758 ms
```

## #11 — seen 221 ms — `/category-trends?principal=unilever`

```sql
SELECT COALESCE(pd.category_path, 'UNCLASSIFIED') AS category, d.calendar_month AS period,
               SUM(d.net_amount) AS revenue
        FROM Unilever_SKU_Demand_Fact_Real d JOIN Product_Dimension pd ON pd.product_key = d.product_key
        WHERE d.net_amount > 0
        GROUP BY 1, 2
```

```
HashAggregate  (cost=2099.72..2268.02 rows=13464 width=72) (actual time=20.707..20.911 rows=532 loops=1)
  Group Key: COALESCE(pd.category_path, 'UNCLASSIFIED'::text), unilever_sku_demand_fact.calendar_month
  Batches: 1  Memory Usage: 657kB
  Buffers: shared hit=1332
  ->  Hash Join  (cost=334.71..1923.01 rows=23561 width=48) (actual time=1.012..12.721 rows=23223 loops=1)
        Hash Cond: (unilever_sku_demand_fact.product_key = pd.product_key)
        Buffers: shared hit=1332
        ->  Seq Scan on unilever_sku_demand_fact  (cost=0.00..1526.36 rows=23561 width=24) (actual time=0.017..7.436 rows=23223 loops=1)
              Filter: ((NOT is_demo) AND (net_amount > '0'::numeric))
              Rows Removed by Filter: 13926
              Buffers: shared hit=1062
        ->  Hash  (cost=298.76..298.76 rows=2876 width=22) (actual time=0.984..0.985 rows=2783 loops=1)
              Buckets: 4096  Batches: 1  Memory Usage: 179kB
              Buffers: shared hit=270
              ->  Seq Scan on product_dimension pd  (cost=0.00..298.76 rows=2876 width=22) (actual time=0.007..0.558 rows=2783 loops=1)
                    Buffers: shared hit=270
Planning:
  Buffers: shared hit=9
Planning Time: 0.270 ms
Execution Time: 21.033 ms
```

## #12 — seen 215 ms — `/forecast/69767334?principal=unilever`

```sql
SELECT u.email, u.full_name, u.role, s.session_id, s.ended_at,
           s.last_seen_at < now() - make_interval(mins => %(idle_minutes)s) AS idle
      FROM users u
      LEFT JOIN user_session s ON s.session_id = %(session_id)s AND s.user_id = u.user_id
     WHERE u.user_id = %(user_id)s
```

```
Nested Loop Left Join  (cost=0.14..3.42 rows=1 width=127) (actual time=0.015..0.016 rows=0 loops=1)
  Buffers: shared hit=1
  ->  Seq Scan on users u  (cost=0.00..1.04 rows=1 width=104) (actual time=0.015..0.015 rows=0 loops=1)
        Filter: (user_id = 0)
        Rows Removed by Filter: 3
        Buffers: shared hit=1
  ->  Index Scan using user_session_session_id_key on user_session s  (cost=0.14..2.36 rows=1 width=46) (never executed)
        Index Cond: (session_id = 'none'::text)
        Filter: (user_id = 0)
Planning Time: 0.164 ms
Execution Time: 0.045 ms
```

