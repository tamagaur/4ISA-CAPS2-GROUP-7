# Chart design improvement plan — 2026-09

**Goal:** make every chart in the dashboard clearer and more polished, one batch at a
time, so each change can be checked before the next one starts.

**Source of the recommendations:** a review of all 12 charts against data-visualization
design rules, with colour-blind safety measured by a palette validator (not judged by
eye). The measured results are in the appendix.

---

## How we work through this

1. You say which batch to do (e.g. *"do Batch 1"*). You can change or drop any item
   first.
2. I implement only that batch.
3. I check it before handing it back: lint, build, tests (when backend code changes),
   browser screenshots at laptop (1440 px) and phone (390 px) width, and 0 console errors.
4. I report what changed, where to look, and the files touched.
5. You review it on http://localhost:5173 and give feedback. Nothing is committed until
   you say so.

**Rules for every batch**
- **Nothing hard-coded.** Any number, date or data statement on a chart comes from the
  backend. Labels such as a chart title can stay as UI text.
- **Colours are validated** with the palette checker before they ship.
- **Dashboard first (optional).** Any batch can be applied to the Dashboard first, like
  the zoom slider was, and rolled out to the other pages after you approve the look.

---

## Status

| Batch | What it covers | Size | Backend? | Status |
|---|---|---|---|---|
| 1 | Colour fixes | Small | No | ☑ Done 2026-09-26 |
| 2 | Lines, dots and gridlines | Medium | No | ☑ Done 2026-09-26 |
| 3 | Bars | Medium | No | ☑ Done 2026-09-26 |
| 4 | Labels and legends | Medium | No | ☑ Done 2026-09-26 |
| 5 | Story layer: insights, highlights, reference lines | Large | Yes | ☑ Done 2026-09-26 |
| 6 | KPI cards: change vs last month + sparklines | Medium | Yes | ☑ Done 2026-09-26 (Sales + Stock value cards) |
| 7 | Chart-specific upgrades | Large | Some | ☑ Done 2026-09-26 (one item skipped, see decisions) |
| 8 | Accessibility and trust | Medium | No | ☑ Done 2026-09-26 |

All eight batches are implemented and live on http://localhost:5173, uncommitted,
awaiting your review. The decisions each batch left open were made as recorded in
**Decisions made** below — change any of them and I'll adjust.

---

## Decisions made while implementing (2026-09-26)

Each of these is reversible on its own; say the word and I change it back.

1. **Straight line segments** (Batch 2 decision 1): every line chart now draws
   straight segments between months instead of smoothed curves. These are monthly
   totals — a curve implies values between the months that don't exist.
2. **Dots on every month, thinning under zoom** (Batch 2 decision 2): dots stay on
   every real observation (8 px with a 2 px white ring), but when the zoom window
   packs points tighter than ~14 px the per-month dots drop out automatically and
   only the latest and isolated points keep theirs.
3. **Insight sentences on the two Dashboard charts** (Batch 5 decision 1): Sales vs
   Stock and the Portfolio forecast get backend-written sentences. SKU Forecast and
   Category Trends already lead with their own backend-driven stat rows, so a second
   sentence there would restate what the page already says.
4. **Plain, factual tone** (Batch 5 decision 2), e.g. *"Sales fell 25.3% from ₱37.3M
   in Jan 2026 to ₱27.9M in Feb 2026; stock on hand stood at ₱46.6M in Feb 2026."*
5. **Sparklines on Sales and Stock value only** (Batch 6 decision 1): they are the
   two cards with monthly history in the payload. Below safety stock and Pending
   actions have no stored monthly history — nothing honest to draw yet.
6. **Delta colour by direction** (Batch 6 decision 2 — changed at your request,
   2026-09-26): the change vs last month is a shaded pill on both value cards —
   green with ↑ when the figure rose, red with ↓ when it fell, gray when flat. The
   Sales card's accent (top bar + icon) is green. (First shipped neutral; you chose
   the direction colours after review.)
7. **LP-vs-3-week gap label skipped** (Batch 7): the 71% headline already states the
   gap, and it leans on the LP's 1-business-day protection period — an open planning
   decision the card itself flags. Labelling the same number twice would harden it.
8. **Texture opt-in trigger**: the "out of stock" hatch returns automatically for
   readers whose OS asks for high contrast (`prefers-contrast: more`) or forced
   colors — no in-app setting to maintain.
9. **One indigo for the LP weight bars**: cost / service level / storage all wear
   the model-output indigo (they're three weights of one solver objective, not three
   categories); the labels carry identity. Their "Placeholder:" tooltip blurbs were
   replaced with the real objective terms from `analytics/optimization/lp.py`.
10. **"View as table" on the five data-dense charts** (Sales vs Stock, Portfolio
    forecast, SKU Forecast, Category Trends, brand/category Pareto). The ABC page's
    Cover-vs-reorder chart already has its drill-down table beside it, and the
    plain-CSS bars (tier stock, policy, weights) state their numbers in text.
11. **Keyboard tooltips came free**: Recharts 3's accessibility layer (on by
    default) focuses each chart with Tab and walks months with the arrow keys,
    showing the same tooltip as hover — verified in the browser pass.

---

## The charts this plan covers

| Page | Chart | Code |
|---|---|---|
| Dashboard | Sales vs Stock on Hand | `frontend/src/components/Charts.jsx` — `SalesVsStockWidget` |
| Dashboard | ABC classification (donut) | `Charts.jsx` — `ABCDonutWidget` |
| Dashboard | Active / dead stock by ABC tier | `Charts.jsx` — `CategoryStockBarWidget` |
| Dashboard | Portfolio-level aggregate forecast | `Charts.jsx` — `PortfolioForecastWidget` |
| Dashboard | Reorder recommendations (weights bars) | `Charts.jsx` — `ReorderRecommendationWidget` |
| Dashboard | Safety stock: LP policy vs 3-week rule | `Charts.jsx` — `PolicyComparisonWidget` |
| ABC Classification | Cover vs reorder point, by class | `ABCClassification.jsx` |
| ABC Classification | What drives revenue — by brand (Pareto) | `AbcBreakdowns.jsx` — `ParetoCard` |
| ABC Classification | Movement × value (ABC × FSN) | `AbcBreakdowns.jsx` — `AbcFsnMatrix` |
| SKU Forecast | Forecast chart + headline numbers | `SKUForecast.jsx` |
| SKU Forecast | Demand pattern tiles | `SkuDemandPatternPanel.jsx` |
| Category Trends | Category revenue + trend projection | `CategoryTrends.jsx` — `CategoryChart` |

Shared pieces: `ChartZoom.jsx` (dots, area fills, zoom slider) and `theme/colors.js`
(all chart colours).

---

## Batch 1 — Colour fixes

**What it does:** fixes the colours that measured as hard to tell apart or too faint.
This is the smallest batch with the most visible payoff.

**Changes**
- **SKU Forecast:** draw the *actual demand* line in **teal**, matching the Dashboard's
  forecast card. Today it's indigo next to a violet forecast line, which red-blind users
  see as the same colour (ΔE 1.9, where ≥ 8 is the target) and which is hard to separate
  even with normal vision.
- **Tier C plum:** `#EBC9E1` → `#D6A0C8`. The old colour has 1.5:1 contrast on the white
  card, so Tier C barely shows.
- **Teal:** `#14919B` → `#0E96A1` for every sales/actual line. The old teal sits just below
  the saturation floor and reads slightly gray.
- **LP weight bars** (Cost / Service level / Storage): use **one neutral colour** for all
  three. They're the same kind of value, and "Storage" currently uses slate, which already
  means "no data" in your colour rules.
- **New colour rule** written into `colors.js`: blue, indigo and violet never appear in
  the same chart (they collapse into one colour for red-blind viewers).

**Where to see it:** SKU Forecast (pick any SKU) · Dashboard → ABC donut (Tier C slice) ·
Dashboard → Sales vs Stock (teal line) · Dashboard → Reorder card → "How this was optimized".

**Files:** `theme/colors.js`, `SKUForecast.jsx`, `Charts.jsx`

**Decision for you:** none.

---

## Batch 2 — Lines, dots and gridlines

**What it does:** gives the line charts a quieter, more polished look and makes
"dashed = future" mean something.

**Changes**
- **Solid, hairline gridlines** in all 8 charts that use a grid. Today they're dashed,
  the same as your forecast and trend lines, so the projections don't stand out.
- **One soft area fill (~10%) per chart.** On Sales vs Stock, the two overlapping
  gradients turn muddy where the lines cross, so keep the fill under *Stock* only.
- **Dots:** 8 px with a 2 px white ring, so they stay readable where lines cross. Today
  they're 6 px with no ring.
- **Lines:** a consistent 2 px width with round ends.

**Where to see it:** Sales vs Stock, Portfolio forecast, SKU Forecast chart, Category
Trends chart, Brand Pareto, Cover vs reorder point.

**Files:** `ChartZoom.jsx` (`seriesDot`, `SeriesFill`), `Charts.jsx`, `SKUForecast.jsx`,
`CategoryTrends.jsx`, `AbcBreakdowns.jsx`, `ABCClassification.jsx`

**Decisions for you**
1. **Curve shape:** keep the smooth curves, or switch to straight segments between
   months? Smooth curves suggest values between months that don't exist; straight lines
   are more literal.
2. **Dots:** on every month (current) or only on the latest month plus on hover?

---

## Batch 3 — Bars

**What it does:** replaces heavy blocks with slimmer, softer bars — the "premium
dashboard" look.

**Changes**
- **Thinner bars:** about 24–32 px. The Cover vs reorder point bars are 54 px today.
- **4 px rounded ends**, square at the baseline.
- **2 px white gaps** between stacked segments, instead of segments touching.
- **"Out of stock" stripes off by default.** The colour + gap + legend carry it; the
  stripes come back as an accessibility option in Batch 8.

**Where to see it:** ABC → Cover vs reorder point · Dashboard → Active / dead stock ·
Dashboard → LP vs 3-week rule · Dashboard → Reorder weights · ABC → Brand Pareto.

**Files:** `ABCClassification.jsx`, `Charts.jsx`, `AbcBreakdowns.jsx` and their CSS

**Decision for you:** none.

---

## Batch 4 — Labels and legends

**What it does:** puts the information where the eye already is, instead of making the
reader look down at a legend.

**Changes**
- **Legend under the chart title**, not below the zoom slider.
- **Labels at the end of each line** — the series name and its latest value, e.g.
  "Stock ₱46.6M" — on charts with up to 4 lines. Values come from the chart's data.
- **Numbers in normal (dark) text** with a small colour swatch beside them. SKU Forecast
  currently colours its headline numbers purple to match the line.
- **Values at the tips of bars** where they fit; otherwise the tooltip carries them
  (never clipped).

**Where to see it:** every line chart; SKU Forecast headline numbers; bar charts.

**Files:** `Charts.jsx`, `SKUForecast.jsx`, `SKUForecast.css`, `CategoryTrends.jsx`,
`AbcBreakdowns.jsx`

**Decision for you:** none.

---

## Batch 5 — Story layer (backend + frontend)

**What it does:** the biggest "not plain" upgrade. Each chart tells the reader what to
notice, using sentences and highlights generated from the data.

**Changes**
- **Insight subtitle** under the title, written by the backend from the data, e.g.
  *"Stock on hand rose to ₱46.6M in Feb 2026 while sales fell to ₱27.9M."*
- **Highs and lows labelled:** the backend marks the peak and lowest month; the chart
  puts a small label there (e.g. the Dec 2025 sales dip).
- **Reference lines:** a thin "Forecast starts" divider on forecast charts, and an
  average or target line where the project defines one.
- **Hover focus:** hovering one line or tier dims the others.

**Where to see it:** Sales vs Stock, Portfolio forecast, SKU Forecast, Category Trends.

**Files:** `backend/routers/dashboard.py`, `backend/routers/forecast.py`,
`backend/routers/category_trends.py` (insight text + highlight points); `Charts.jsx`,
`SKUForecast.jsx`, `CategoryTrends.jsx` (display)

**Decisions for you**
1. Which charts get an insight sentence (all four, or start with Sales vs Stock).
2. The tone of the sentences (plain and factual is recommended).

---

## Batch 6 — KPI cards

**What it does:** makes the four headline cards show direction, not just a number.

**Changes**
- **Change vs last month** under each value, e.g. "▼ 25% vs Jan 2026", with an arrow. The
  backend computes it.
- **A small 7-month sparkline** in each card. The data is already in the Dashboard's API
  response.
- The colour of the change follows whether up is good or bad for that card.

**Where to see it:** Dashboard → the four KPI cards.

**Files:** `backend/routers/dashboard.py` (deltas), `KPICard.jsx`, `Dashboard.jsx`

**Decisions for you**
1. Which cards get a sparkline (Sales and Stock value have monthly history; Below safety
   stock and Pending actions don't yet).
2. Is a *higher* stock-on-hand value good or bad? (Higher can mean more trapped capital.)

---

## Batch 7 — Chart-specific upgrades

**What it does:** targeted improvements where a chart's current form doesn't fit its data.

**Changes**
- **Active / dead stock by tier:** dead stock is 0 in every tier, so the bars only say
  "everything is active". Show a clear "No dead stock flagged in Mar 2026" message with
  the counts, in compact rows. The month comes from the backend.
- **Brand Pareto:** colour only the Tier A brands, mute B and C, and mark where the
  cumulative line crosses 80%.
- **Movement × value matrix:** shade each cell by its count in one colour, like a heatmap.
- **Category Trends:** shade the projection's likely range. The backend already computes
  the slope bounds; it would also send the low/high lines. Label the last actual month
  and the projected end.
- **Portfolio forecast:** label the forecast value at the end of the line.
- **LP vs 3-week rule:** label the gap between the two bars directly.

**Files:** `Charts.jsx`, `AbcBreakdowns.jsx`, `CategoryTrends.jsx`,
`analytics/forecasting/category_trend.py` + `backend/routers/category_trends.py`
(projection range), `backend/routers/dashboard.py` (month for the dead-stock message)

**Decision for you:** you can pick a subset — each item is independent.

---

## Batch 8 — Accessibility and trust

**What it does:** lets anyone, including your panel, check every number, and makes
nothing depend on colour alone.

**Changes**
- **"View as table"** toggle on every chart, showing the same numbers as a table.
- **Keyboard focus shows the tooltip**, the same as hover.
- **Stripes/texture as an opt-in accessibility setting** (for colour-blind users and
  printing).
- A final check of every chart at phone width.

**Files:** a shared `ChartTable` component plus each chart component

**Decision for you:** none.

---

## What stays as it is

These already work well and are kept:
- The one-meaning-per-colour rules in `theme/colors.js` (green = healthy, amber = watch,
  red = act now, slate = no data, indigo = recommendation).
- Tooltips, skeleton loaders, the dimmed "updating" state on refetch.
- Entrance animations (they already respect the reduced-motion setting).
- Peso formatting (₱27.9M) and the zoom slider.

---

## Appendix — colour check results

Measured with the data-visualization palette validator on the white card surface.
Targets: colour-blind separation ΔE ≥ 8; normal-vision separation ΔE ≥ 15;
saturation ≥ 0.10; the lightest tier colour ≥ 2:1 contrast.

| Pair / ramp | Today | After Batch 1 |
|---|---|---|
| SKU Forecast: actual vs forecast | Indigo `#5B5FEF` vs violet `#A855F7`: **fails** (ΔE 1.9 colour-blind, 12.4 normal) | Teal `#0E96A1` vs violet `#A855F7`: **passes** (ΔE 14.7 / 27.0) — shipped |
| Sales vs Stock | Teal `#14919B` vs blue `#2563EB`: separation passes, teal **just under** the saturation floor (0.099) | Teal `#0E96A1` vs blue `#2563EB`: **all checks pass** — shipped |
| ABC tiers (plum ramp) | Tier C `#EBC9E1`: **fails** (1.5:1 contrast) | Tier C `#D6A0C8`: **passes** (2.16:1) — shipped |
| LP weight bars | Slate `#475569` reads as gray and means "no data" | All three bars now the model-output indigo (`SEMANTIC.recommendation`) — shipped |
| Blue / indigo / violet | Near-identical for red-blind viewers (ΔE 2.6) | Rule written into `theme/colors.js` — shipped |
| Pareto muted B/C grays (new in Batch 7) | — | `#8E99A9` / `#ACB5C3`: one hue, visible step, light end 2.07:1 — **passes** |

---

## Hard-coded copy found along the way (not in this plan's scope)

Fixed while passing through, because the backend already had (or now sends) the number:
- "Gated SKUs (MAPE < 20%)" and "Beat naive (MASE < 1)" — the gates now arrive as
  `portfolio_forecast.mape_gate` / `forecast.mase_gate` and the labels read them.
- The Pareto chart's 80/95% reference lines — now drawn from GET /pareto's own
  `cutoffs`, not literals.
- The FSN note's fallback thresholds (`?? 1.32`, `?? 3`, `?? 6`) — removed; the note
  states thresholds only when GET /fsn sends its rules.
- The LP weight fallback `LP_DEFAULT_PCT` (45/35/20) — removed; a missing weight now
  renders "—" instead of a number typed in the frontend.
- The reorder card's "Placeholder:" tooltip copy — replaced with the LP objective's
  real terms.

Still hard-coded, flagged for a later decision (each is a *display* convention, not
a data value, but worth knowing about):
- `Dashboard.jsx` `SAFETY_STOCK_WATCH = 0.9` / `SAFETY_STOCK_ACT = 0.6` — the card
  colour thresholds for the Below-safety-stock KPI.
- `ABCClassification.jsx`'s Del Monte regrouping note ("about 63 sub-categories
  became 4–5") — a sentence about the source data with numbers typed in the page.
- Dressings' change column can render "— (−100% to −100%)" when a projection is all
  zeros — cosmetic; the range adds nothing when the point estimate is a dash.
