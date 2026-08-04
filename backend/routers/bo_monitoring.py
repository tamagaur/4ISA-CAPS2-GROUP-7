"""
backend.routers.bo_monitoring — GET /bo-monitoring

Phase 6 (CLAUDE.md Step 23):
  Returns Bad Order rates per SKU over time.
  BO_rate = (BO units / units received) * 100
  Reads from derived BO rate data in Supabase. Requires auth.

TODO (B1): Implement endpoint.
      Schema: see backend/schemas/bo_monitoring.py.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/bo-monitoring", tags=["bo-monitoring"])


@router.get("")
async def get_bo_monitoring():
    """Stub — returns empty list until Supabase is connected (S2)."""
    return []
