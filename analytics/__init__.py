"""
analytics — SSM Capstone ML pipeline package.

Phase 3A–5 (CLAUDE.md Part 4):
  db/           → Phase 3A: Supabase schema, ORM models, date dimension seed
  etl/          → Phase 3B: Extract, granularity resolve, clean, load
  classification/ → Phase 3C: ABC/Pareto classification
  forecasting/  → Phase 4:  SARIMA demand forecasting (Category A)
  optimization/ → Phase 5:  Safety stock, ROP, LP optimization (PuLP)

Architecture boundary: this package is a batch pipeline.
The FastAPI backend (backend/) does NOT import this package at runtime.
"""
