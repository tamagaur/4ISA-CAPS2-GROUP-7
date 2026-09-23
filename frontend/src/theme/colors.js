// SAN2 Inventory DSS Design Tokens
export const COLORS = {
  // Data Visualization Color System
  critical: '#E5484D',       // Red: KPI negative deltas, critical reorders
  warning: '#F5A623',        // Amber: Warnings, under investigation, low stock
  success: '#2E9E5B',        // Green: Good, resolved, positive trends, received units
  salesTrend: '#5B5FEF',     // Indigo: Sales trend / primary metric lines
  dispatched: '#14919B',     // Teal: Dispatched / secondary flow metrics
  forecast: '#A855F7',       // Violet: Forecast / projected values
  forecastBg: '#F3E8FF',     // Light Violet tint: 90% CI uncertainty band

  // ABC Classification Single-Hue Plum Ramp (Ordinal by value)
  abcA: '#6B2C5F',          // Category A - Top 20% / 80% revenue (darkest plum)
  abcB: '#B565A0',          // Category B - Middle tier (medium plum)
  abcC: '#EBC9E1',          // Category C - Long tail (lightest plum)

};

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
  diagnostic: SEMANTIC.noData, // no inherent good/bad direction, or nothing to judge
  action: SEMANTIC.recommendation, // TYPE 3: a recommendation the system is outputting
};

// Chart series tokens — plain series hues with NO health meaning, so a
// line on a trend chart can never be misread as a verdict. stockSeries
// used to alias COLORS.warning (amber), which made the stock-on-hand line
// read as "watch" on the same dashboard where amber meant "low stock";
// it's now a neutral blue that no status uses. lpWeights are three
// co-equal categorical hues for the solver's cost/service/storage split
// (Storage used to be amber, implying a severity it doesn't have).
export const CHART_COLORS = {
  salesSeries: COLORS.dispatched,
  stockSeries: '#2563EB',
  abcRamp: [COLORS.abcA, COLORS.abcB, COLORS.abcC], // Class A, B, C — sequential
  cumulativeCurve: '#475569',
  gridline: '#E2E8F0',
  axisLabel: '#64748B',
  // Tint behind placeholder months in preview mode (src/dataMode.js). Its
  // one meaning is "not SSM's data"; mirrors --color-placeholder.
  placeholder: '#94A3B8',
  lpWeights: {
    cost: COLORS.dispatched,
    service_level: COLORS.salesTrend,
    storage: '#475569',
  },
};
