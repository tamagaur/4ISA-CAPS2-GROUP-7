"""
backend.routers.inventory — GET /inventory/current

Phase 6 (CLAUDE.md Step 23):
  Returns current stock levels per SKU.
  Reads from Inventory_Fact via Supabase. Requires auth.

TODO (B1): Implement endpoint with get_db and get_current_user deps.
      Schema: see backend/schemas/inventory.py.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/current")
async def get_inventory_current():
    """Stub — returns empty list until Supabase is connected (S2)."""
    return []
