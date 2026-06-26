"""
analytics.etl.granularity — Granularity Resolver: monthly invoice totals → daily intervals.

Phase 3B (CLAUDE.md Step 7 — Checkpoint: no date gaps in output series; row counts plausible):
  Problem: Sales Register files are INVOICE-LEVEL only (no SKU breakdown).
  Solution: Disaggregate monthly totals into a daily time series.
    1. Distribute monthly invoice totals across business days in each month.
    2. Cross-reference UnileverLaUnionSalesperSKU2023to2026.xls for SKU-level
       estimates where available (Unilever La Union territory).
  Output: Reconstructed daily demand series per SKU, validated for continuity.

TODO: Implement resolve_granularity(monthly_df, sku_daily_df) -> pd.DataFrame.
      Validate: no date gaps, row counts plausible vs. source totals.
      Do NOT assume SKU-level data exists beyond the confirmed Unilever file.
"""
