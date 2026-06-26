"""
analytics.etl.extract.sales_register — Sales Register parser.

Phase 3B (CLAUDE.md Step 6):
  Source: Sales Register xlsx files (2021–2025).
  Confirmed columns (CLAUDE.md Part 2):
    Invoice Date | Salesman | Town Display | Customer Name |
    Untaxed Amount | Discount Amount | Tax | Net Amount |
    Balance | Return Slip # | Return Type
  Granularity: INVOICE-LEVEL only — no SKU breakdown.

TODO: Implement parse_sales_register(filepath: Path) -> pd.DataFrame.
      Validate all expected columns are present before returning.
      Raise ValueError with descriptive message on schema mismatch.
"""
