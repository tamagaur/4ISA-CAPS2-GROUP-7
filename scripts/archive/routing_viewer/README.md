# Routing Viewer

A dev tool for one question: **does routing the forecast model by
`combined_v1` bin beat always-MA3** on the Tier A (as of 2026-02, method
'single') Unilever cohort?

**Not the product dashboard.** Self-contained HTML reading a frozen snapshot —
no backend, no live DB. Diagnostic only; nothing here is adopted methodology.

## Use it

Open **`routing_viewer.html`** in any browser (double-click, no server).

- **Header toggle** — `Real only` vs the two synthetic-prefix arms. The
  synthetic arms are DIAGNOSTIC ONLY (is_demo rows are approved for frontend
  validation, never for reported results) and show a banner saying so.
- **Bins** — click a bin card to load its interval plot and table.
- **Interval plot** — median WAPE per model with a bootstrap 95% interval.
  The shaded band is MA3's interval: a model is DECISIVE only if its whisker
  clears that band entirely.
- **Routing value / Fittability / Stability / Per-SKU** — tables; the per-SKU
  table sorts on any header and filters by bin or search.

## Rebuild

From the repo root, `.env` holding `SUPABASE_DIRECT_URL` or `SUPABASE_DB_URL`.
Read-only against the DB; every model is refitted from the `_Real` view.

    python tools/routing_viewer/build.py                    # ~1 min, real only
    python tools/routing_viewer/build.py --with-synthetic   # ~3 min, adds arms A/B
    python tools/routing_viewer/build.py --inline           # re-inline JSON after a template edit

Method, split, seed and the synthetic-arm definitions are in `build.py`'s
docstring and repeated in the page footer.
