"""
backend.main — FastAPI application entry point.

Phase 6 (CLAUDE.md Steps 22–25):
  Mounts routers for all five endpoint groups.
  All endpoints require authentication before serving data (Step 24).
  Architecture boundary: this process reads from Supabase only.
    It does NOT import the analytics package.

Mounts routers for all five endpoint groups.
All endpoints require authentication before serving data (Step 24) — each
router declares dependencies=[Depends(get_current_user)] itself (see
backend/deps.py), so this file just includes them.
Architecture boundary: this process reads from Supabase only.
  It does NOT import the analytics package.

Auth: X-API-Key header, checked against BACKEND_API_KEY. See
backend/deps.py's module docstring for why this was chosen over Supabase
JWT (flagged deviation from the original "confirm with Yuan" TODO).
"""
from __future__ import annotations

from fastapi import FastAPI

from backend.routers import abc, bo_monitoring, forecast, inventory, recommendations

app = FastAPI(
    title="SSM Decision Support Dashboard API",
    description="Read-only API over Supabase-stored ETL/ABC/SARIMA/LP pipeline outputs.",
    version="0.1.0",
)

app.include_router(inventory.router)
app.include_router(forecast.router)
app.include_router(recommendations.router)
app.include_router(abc.router)
app.include_router(bo_monitoring.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Unauthenticated liveness check — deliberately outside every
    router's get_current_user dependency so uptime monitoring doesn't
    need an API key."""
    return {"status": "ok"}
