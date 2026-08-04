"""
backend.routers.recommendations — GET /recommendations

Phase 6 (CLAUDE.md Step 23):
  Returns LP-derived replenishment quantities Q_i per SKU (paginated).
  Reads from LP output table in Supabase. Requires auth.
  Includes Q_i, ROP_i, SS_i, planning_cycle_date per SKU.
  Supports Accept/Dismiss flag write-back (Step 28, Phase 7 interactivity).

TODO (B1): Implement paginated GET.
      Schema: see backend/schemas/recommendations.py.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("")
async def get_recommendations():
    """Stub — returns empty list until Supabase is connected (S2)."""
    return []
