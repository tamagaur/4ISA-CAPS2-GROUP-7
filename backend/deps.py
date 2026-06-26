"""
backend.deps — FastAPI dependency injection: DB session, auth, pagination.

Phase 6 (CLAUDE.md Step 24):
  get_db()   → yields a SQLAlchemy session pointed at Supabase.
  get_current_user() → validates Supabase JWT or API key; raises 401 if invalid.
  No SSM client data is served without a valid auth token.

TODO: Implement get_db() using SQLAlchemy 2.0 async session.
      Implement get_current_user() — confirm auth method with Yuan first.
"""
