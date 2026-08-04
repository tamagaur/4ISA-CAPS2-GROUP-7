"""
backend.routers.abc — GET /abc

Phase 6 (CLAUDE.md Step 23):
  Returns ABC tier assignments for all active SKUs.
  Reads from ABC_Classification table in Supabase. Requires auth.

TODO (B1): Implement endpoint.
      Schema: see backend/schemas/abc.py.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/abc", tags=["abc"])


@router.get("")
async def get_abc():
    """Stub — returns empty list until Supabase is connected (S2)."""
    return []
