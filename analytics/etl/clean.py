"""
analytics.etl.clean — Data cleaning and feature engineering.

Phase 3B (CLAUDE.md Step 8 — Checkpoint: outlier detection run; schema validation passed):
  Operations:
    - Remove duplicate invoices
    - Standardize product codes across principals
    - Fix unit measure inconsistencies
    - Compute holding cost features
    - Compute Bad Order rate per SKU: BO_rate = (BO units / units received) × 100
  Output: Cleaned DataFrame ready for load.py.

TODO: Implement clean_pipeline(raw_df: pd.DataFrame) -> pd.DataFrame.
      Run IQR-based outlier detection and flag (do NOT silently drop).
      Validate output schema before returning.
"""
