# SSM Decision Support Dashboard — 3ISA Group 7

**Client:** San San Marketing (SSM), Urdaneta, Pangasinan  
**Principals in scope:** Unilever Philippines · Del Monte Philippines  
**Track:** IS-BA · UST CICS · Capstone 2025–2026

---

## What this system does

Replaces SSM's blanket 3-week safety stock rule with per-SKU, data-driven
replenishment recommendations surfaced through an interactive Decision Support
Dashboard (DSD).

**Pipeline:**

```
Raw Data (xlsx/csv)
  → ETL (extract → clean → granularity resolve → load to Supabase)
    → ABC/Pareto Classification
        A (0–80% revenue)  → SARIMA + LP + full processing
        B (80–95%)         → descriptive monitoring only
        C (95–100%)        → minimal monitoring
      → SARIMA Demand Forecasting (Category A only, MAPE < 20% gate)
        → Safety Stock: SS_i = Z × σ_di  (Z=1.28, 90% service level)
          → ROP: ROP_i = Ŷ_(t+1,i) + SS_i
            → LP Optimization: Minimize Z = w₁·TC − w₂·SL + w₃·SC
              → Decision Support Dashboard (Next.js)
```

---

## Repository layout

```
analytics/          Installable Python package — full ML pipeline
  db/               DDL, SQLAlchemy ORM models, date dimension seeder
  etl/              Extraction, granularity resolver, cleaning, loader
  classification/   ABC/Pareto classification
  forecasting/      SARIMA demand forecasting
  optimization/     LP replenishment optimization (PuLP/CBC)
  notebooks/        Exploratory notebooks (not part of pipeline)

backend/            FastAPI REST API — reads from Supabase only
  routers/          Endpoint modules (/inventory, /forecast, /recommendations, /abc, /bo-monitoring)
  schemas/          Pydantic request/response models

frontend/           Next.js dashboard (Phase 7 — not yet initialized)

tests/              pytest suite mirroring analytics/ structure

data/
  raw/              Source xlsx/csv files — NEVER committed (gitignored)
  interim/          Intermediate cleaned DataFrames
  processed/        Pipeline-ready outputs

docs/erd/           Entity-Relationship Diagram assets
```

---

## Architecture boundary

> **The `analytics` package does NOT get imported by `backend` at runtime.**
>
> `analytics` runs as a batch pipeline and writes outputs to Supabase.
> `backend` (FastAPI) reads those outputs from Supabase via SQL/SQLAlchemy.
> This keeps heavy ML dependencies (statsmodels, PuLP) out of the web process.

---

## Setup

```bash
# 1. Copy and fill environment variables
cp .env.example .env

# 2. Create virtual environment and install
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                 # installs analytics package in editable mode

# 3. Run tests
pytest

# 4. Start API (after Supabase schema is live)
uvicorn backend.main:app --reload
```

