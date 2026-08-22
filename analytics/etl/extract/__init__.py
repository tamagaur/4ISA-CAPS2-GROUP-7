"""
analytics.etl.extract — One parser module per source file type.

Phase 3B (CLAUDE.md Step 6 — Checkpoint: each parser returns clean DataFrame,
schema validated):
  sales_register.py    — Sales Register xlsx (invoice-level, 2021–2025)
  inventory_signoff.py — Inventory Sign-Off records
  bo_rmr_gs.py         — BO / RMR Good Stock records
  purchase_order.py    — Purchase Order files
  sell_out.py          — Sell-Out data
  unilever_sku.py      — UnileverLaUnionSalesperSKU2023to2026.xls (SKU-level source)
  ssis_summary.py      — SSIS Sales Summary Reports (~60 Unilever workbooks)
                         T3 Option A (CHECKLIST_BACKEND.md). System-of-record
                         for Unilever sales per DEC-04 (ARCHITECTURE.md).
                         raw_data sheets are the promoted fact; other sheet
                         roles (invoice_reg, per_customer_summary, scratch)
                         are staged for auditability only.

Step 5 checkpoint: File inventory documented and column schemas confirmed with
Yuan BEFORE any parser is written.
"""
