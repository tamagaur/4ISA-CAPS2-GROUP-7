"""
backend.routers.inventory — GET /inventory/current

Phase 6 (CLAUDE.md Step 23 — Checkpoint: input/output schema defined before coding):
  Returns current stock levels per SKU.
  Reads from Inventory_Fact via Supabase. Requires auth.

TODO: Define APIRouter, implement endpoint with get_db and get_current_user deps.
      Schema: see backend/schemas/inventory.py.
"""
