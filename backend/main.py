"""
backend.main — FastAPI application entry point.

Phase 6 (CLAUDE.md Steps 22–25):
  Mounts routers for all five endpoint groups.
  All endpoints require authentication before serving data (Step 24).
  Architecture boundary: this process reads from Supabase only.
    It does NOT import the analytics package.

TODO: Instantiate FastAPI app, include all routers, add auth middleware.
      Confirm auth strategy with Yuan (Supabase JWT vs. API key).
"""
