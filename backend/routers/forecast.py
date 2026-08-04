"""
backend.routers.forecast — GET /forecast/{sku_id}

Phase 6 (CLAUDE.md Step 23):
  Returns SARIMA forecast for a given SKU (Category A only).
  Reads pre-computed forecast values from Supabase. Requires auth.
  Returns 404 if sku_id does not exist or is not Category A.

TODO (B1): Implement endpoint.
      Schema: see backend/schemas/forecast.py.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/{sku_id}")
async def get_forecast(sku_id: str):
    """Stub — returns empty dict until Supabase is connected (S2)."""
    return {}
