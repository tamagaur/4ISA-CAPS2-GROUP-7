"""
analytics.classification.abc — ABC/Pareto SKU classification.

Phase 3C (CLAUDE.md Steps 10–11):
  Step 10:
    - Compute cumulative revenue per SKU from Sales_Fact
    - Sort descending by revenue contribution
    - Assign tiers: A = 0–80%, B = 80–95%, C = 95–100%
    Checkpoint: Pareto 80/20 plot generated and reviewed.
                Cumulative Revenue Coverage Ratio validated.
                Inventory Turnover Ratio computed.
  Step 11:
    - Write tier assignments to ABC_Classification table in Supabase.
    Checkpoint: All active SKUs have a tier; no nulls.

  Downstream: Category A SKUs only proceed to SARIMA forecasting (Phase 4).
              Category B → descriptive monitoring.
              Category C → minimal monitoring.

TODO: Implement classify_abc(sales_fact_df: pd.DataFrame) -> pd.DataFrame.
      Output columns: sku_id, total_revenue, revenue_share, cumulative_share, tier.
"""
