// SAN2 Inventory DSS Design Tokens
export const COLORS = {
  // Data Visualization Color System
  critical: '#D9534F',       // Red: KPI negative deltas, critical reorders
  warning: '#E9A23B',        // Amber: Warnings, under investigation, low stock
  success: '#36A66B',        // Green: Good, resolved, positive trends, received units
  salesTrend: '#5B5FEF',     // Indigo: Sales trend / primary metric lines
  // Teal: sales / actual-demand lines. Was #14919B, which measured just
  // under the palette validator's saturation floor (chroma 0.099 < 0.10)
  // and read slightly gray on the white card; #0E96A1 passes every check
  // against both #2563EB (stock) and #A855F7 (forecast) — see
  // reports/CHART_DESIGN_PLAN_2026-09.md's appendix.
  dispatched: '#18A6B5',
  forecast: '#8866E8',       // Violet: Forecast / projected values
  forecastBg: '#EEE9FC',     // Light Violet tint: 90% CI uncertainty band

  // ABC Classification Single-Hue Plum Ramp (Ordinal by value)
  abcA: '#76295E',          // Category A - Top 20% / 80% revenue (darkest plum)
  abcB: '#A9579A',          // Category B - Middle tier (medium plum)
  // Category C - Long tail (lightest plum). Was #EBC9E1: 1.5:1 contrast on
  // the white card, so the C slice/segment barely registered. #D6A0C8
  // measures 2.16:1 and keeps the ramp's light-to-dark order.
  abcC: '#D7AFCC',

};

// ── Hue-pair rule (2026-09-26, measured, not judged by eye) ─────────────
// Blue (#2563EB), indigo (#5B5FEF) and violet (#A855F7) collapse into one
// colour for red-blind viewers (protan ΔE ≈ 2–3 where ≥ 8 is the target),
// so NO TWO of them may appear in the same chart. Pair any one of them
// with teal (COLORS.dispatched) instead — teal–blue, teal–indigo and
// teal–violet all validate. This is why every "actual" line app-wide is
// teal, never indigo, next to the violet forecast.

// ── Colour discipline (2026-09-18) ──────────────────────────────────────
// Two rules, app-wide:
//   1. Brand colours (the terracotta --color-brand-primary family in
//      index.css) are CHROME only — sidebar, buttons, focus rings, links.
//      They never encode a data state.
//   2. Each data colour has exactly ONE meaning, and never appears as
//      chrome:
//        green  = healthy / above threshold
//        amber  = watch / below threshold but not empty
//        red    = act now / empty or critical
//        slate  = no data / not measurable
//        indigo = a recommendation or model output (not a health state)
// Before this, green meant both "in stock" and the Accept button, amber
// meant "pending reorder", "low stock" AND "urgent", and the same red was
// used for CRITICAL, the brand accent and the page-title accent word.
// Every component now reads these names, so "what does amber mean here"
// has one answer.
export const SEMANTIC = {
  healthy: COLORS.success,
  watch: COLORS.warning,
  act: COLORS.critical,
  noData: '#64748B',
  // Nothing to judge against (e.g. a SKU the LP does not plan, so no
  // reorder point) — lighter than noData so "not applicable" never reads as
  // a missing record.
  notPlanned: '#CBD5E1',
  recommendation: COLORS.salesTrend,
};

// Status tiers — semantic meaning drives the color, never the reverse.
// A card's color comes from its metric type + direction (see KPICard.jsx's
// tierFor()), not a color chosen per instance, so "why is this card red"
// always has one answer.
//
// These alias straight into SEMANTIC so every "this is bad" on screen is
// provably the same pixel value as the chart under it, not a near-match.
export const STATUS_TIERS = {
  loss: SEMANTIC.act,          // TYPE 1/2: worsening direction, or a gap over target
  healthy: SEMANTIC.healthy,   // TYPE 2: at or under target
  neutral: SEMANTIC.noData,    // no inherent good/bad direction, or nothing to judge
  action: SEMANTIC.recommendation, // TYPE 3: a recommendation the system is outputting
};

// Chart series tokens — plain series hues with NO health meaning, so a
// line on a trend chart can never be misread as a verdict. stockSeries
// used to alias COLORS.warning (amber), which made the stock-on-hand line
// read as "watch" on the same dashboard where amber meant "low stock";
// it's now a neutral blue that no status uses. lpWeight (singular,
// 2026-09-26): the solver's cost/service/storage split is three co-equal
// weights of ONE model, not three categories — three hues implied a
// difference in kind that isn't there, and Storage's slate doubled as the
// app-wide "no data" colour. All three bars now wear the one
// model-output indigo (SEMANTIC.recommendation), and the row labels
// carry identity.
export const CHART_COLORS = {
  salesSeries: COLORS.dispatched,
  stockSeries: '#2563EB',
  // The dashboard's teal and navy (spec of 2026-10-03). Until 2026-10-12
  // they were the Sales vs Inventory Value chart's sales and inventory
  // lines; that chart now colours by year (yearLines below) and these two
  // are two of its year colours. heroInventory is also the Annual View
  // card's base year. Both pass the hue-pair rule above (teal beside one
  // blue).
  heroSales: '#18A6B5',
  heroInventory: '#3B5BA9',
  // One colour per calendar year on the Sales vs Inventory Value chart
  // (Audrey, 2026-10-12: with the years told apart by dash style alone the
  // chart was hard to follow). Indexed by year % 4, so a year keeps its
  // colour whatever the range: 2024 teal, 2025 navy, 2026 orange, 2023
  // berry, then round again. 2025 and 2026 match the Annual View card
  // beside the chart (base year navy, year in progress orange; the orange
  // is a shade deeper here so a thin line reads at 3:1 on the white card).
  // Measured, not judged by eye (CIEDE2000, with Machado 2009 simulation
  // for the three colour-blind types): every pair is at least 33 apart for
  // normal vision and at least 12 for protan, deutan and tritan vision
  // (targets: 15 and 8). No violet beside the navy (hue-pair rule), and
  // none of the four is a status colour (green, amber, red, slate).
  yearLines: ['#18A6B5', '#3B5BA9', '#E8710A', '#B5176B'],
  // Returns, the same chart's own view (2026-10-08): a deep amber, apart
  // from teal and navy, and >= 4.5:1 on the white card where the warning
  // amber (#F5A623) is too faint for a line.
  heroReturns: '#B45309',
  abcRamp: [COLORS.abcA, COLORS.abcB, COLORS.abcC], // Class A, B, C — sequential
  cumulativeCurve: '#475569',
  gridline: '#EEF1F5',
  axisLabel: '#8792A2',
  // Tint behind placeholder months in preview mode (src/dataMode.js). Its
  // one meaning is "not SSM's data"; mirrors --color-placeholder.
  placeholder: '#94A3B8',
  lpWeight: SEMANTIC.recommendation,
};
