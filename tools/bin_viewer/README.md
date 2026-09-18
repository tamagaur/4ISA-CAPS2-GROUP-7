# Bin Viewer

A dev tool for reviewing Phase 2 SKU binning (reports/BINNING_ROUND1_2026-09.md).
BINS ONLY — no forecasting model or accuracy number appears anywhere here;
that is Phase 3.

**Not the product dashboard.** This is a self-contained HTML file that reads
a frozen data snapshot — it does not talk to the backend or the live database.

## Use it

Open **`bin_viewer.html`** in any browser (double-click — no server, no
internet connection needed; everything is inline, system fonts only).

- The canvas shows one draggable card per bin (name, SKU count, rule).
  Drag a card anywhere — positions are saved in your browser's
  `localStorage` and restored next time you open the file. **Reset layout**
  puts the cards back at their default positions.
- **SKUs cannot be dragged between bins** — bin membership is rule-based
  (`sku_segment.bin_reason`), not manual. The canvas hint and each card's
  lock icon say so.
- Click a bin card to open the side panel: every SKU in that bin, with
  SKU code, product name, history months, trend, CV, stability group, and
  revenue share. Columns are sortable (click the header); the search box
  filters by SKU code or product name.
- Click a SKU row for its detail view: a sparkline of monthly
  `quantity_sold` over the full 2023-01–2026-02 window, every trait, and
  the exact `bin_reason` text stored for it.
- The scheme dropdown lists whatever schemes are in `bin_data.json`. Round
  1 ships only `length_v1`; Round 2 (`trend_v1`, `volatility_v1`,
  `newness_v1`, `combined_v1`) will populate it once those scheme rows exist
  in `sku_segment` — no rebuild of this page will be needed then, only a
  re-run of `build.py`.

## Rebuild it

```
python tools/bin_viewer/build.py --schema ssm_binning_phase2   # scratch, before the public write gate
python tools/bin_viewer/build.py                                # public, after Yuan runs the write commands
```

Optional flags: `--principal`, `--cohort-period`, `--abc-method`, `--scheme`
(defaults: `unilever`, `2026-02`, `single`, `length_v1`).

No DB credentials appear in `bin_data.json` or `bin_viewer.html` — the
script only ever reads already-computed `sku_traits`/`sku_segment` rows and
the demand series for the sparklines.

## Files

| file | |
|---|---|
| `bin_viewer.html` | **the tool** — self-contained, safe to commit as a snapshot |
| `template.html` | the page with a `__BIN_DATA__` placeholder; `build.py` fills it |
| `build.py` | regenerates the data + the built HTML |
| `bin_data.json` | the data payload (bins, SKUs, traits, monthly quantity) |

Data: bin/trait facts from `sku_traits`/`sku_segment` (migration 0018);
sparkline series from `Unilever_SKU_Demand_Fact_Real`; product names from
`Product_Dimension`.
