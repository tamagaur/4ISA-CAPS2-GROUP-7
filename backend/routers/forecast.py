"""
backend.routers.forecast — GET /forecast/{sku_id}

Phase 6 (CLAUDE.md Step 23):
  Returns SARIMA forecast for a given SKU (Category A only).
  Reads pre-computed forecast values from Supabase. Requires auth.
  Returns 404 if sku_id does not exist or is not Category A.

TODO: Define APIRouter, implement endpoint.
      Schema: see backend/schemas/forecast.py.
"""
