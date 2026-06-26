"""
backend.routers.bo_monitoring — GET /bo-monitoring

Phase 6 (CLAUDE.md Step 23):
  Returns Bad Order rates per SKU over time.
  BO_rate = (BO units / units received) × 100
  Reads from derived BO rate data in Supabase. Requires auth.

TODO: Define APIRouter, implement endpoint.
      Schema: see backend/schemas/bo_monitoring.py.
"""
