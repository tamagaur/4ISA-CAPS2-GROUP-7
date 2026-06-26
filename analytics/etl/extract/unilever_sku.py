"""
analytics.etl.extract.unilever_sku — Unilever SKU-level sales parser.

Phase 3B (CLAUDE.md Step 6):
  Source: UnileverLaUnionSalesperSKU2023to2026.xls
  This is the ONLY confirmed SKU-level data source (CLAUDE.md Part 2).
  Granularity: daily sales per SKU, Unilever La Union territory.
  Primary input for SARIMA per-SKU time series (Phase 4).

TODO: Implement parse_unilever_sku(filepath: Path) -> pd.DataFrame.
      Output must include: sku_id, date, quantity_sold, territory columns.
      Do NOT assume additional SKU-level sources exist without Yuan confirming.
"""
