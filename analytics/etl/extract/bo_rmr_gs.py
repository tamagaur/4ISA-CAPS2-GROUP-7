"""
analytics.etl.extract.bo_rmr_gs — BO / RMR Good Stock parser.

Phase 3B (CLAUDE.md Step 6):
  Source: BO/RMR GS files — Good Stock + Bad Order records.
  Same invoice-level structure as Sales Register (CLAUDE.md Part 2).
  Used downstream to compute: BO_rate = (BO units / units received) × 100

TODO: Implement parse_bo_rmr_gs(filepath: Path) -> pd.DataFrame.
      Separate Good Stock rows from Bad Order rows in output.
"""
