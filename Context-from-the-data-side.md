Context from the data side (Yuan). Read-only check, no fixes yet.

abc_classification now stores TWO methods, 'single' and 't3m', plus a run_id column
(migration 0017). The cohort of record is method = 'single'. Any ABC query without that
filter returns roughly double — we saw 275 Tier A for 2026-02 instead of the correct 132.

Check every query and component that touches abc_classification: does it filter
method = 'single'? Cite file:line for any that doesn't.

Also, two blanks on the SKU Management page are expected, not bugs:
- CATEGORY is blank for most SKUs because ABC only covers Unilever SKUs with sales
  (710 of 17,407). The rest are Del Monte or have no sales.
- REORDER PT is mostly blank because it comes from the linear programming layer,
  which is on hold (Phase 4). Only pending LP recommendations have values.

Report what you find. Don't change anything yet.