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

// Status tiers — semantic meaning drives the color, never the reverse.
// A card's color comes from its metric type + direction (see KPICard.jsx's
// tierFor()), not a color chosen per instance, so "why is this card red"
// always has one answer.
//
// These alias straight into COLORS rather than defining their own hex.
// They used to carry near-duplicate values (e.g. loss was #DC2626 vs
// COLORS.critical's #E5484D) — close enough to look intentional, different
// enough that the same "this is bad" meaning rendered as two different
// reds on the same Dashboard screen (KPI card text vs. the chart under
// it). Aliasing means every "critical" on screen is now provably the same
// pixel value, not just a similar one. --color-brand-primary in index.css
// (the sidebar/logo red) stays its own hue on purpose — nav chrome isn't a
// data-alert color and was never meant to match this red.
export const STATUS_TIERS = {
  loss: COLORS.critical,       // TYPE 1/2: worsening direction, or a gap over target
  healthy: COLORS.success,     // TYPE 2: at or under target
  diagnostic: '#64748B',       // no inherent good/bad direction — no COLORS equivalent to alias
  action: COLORS.salesTrend,   // TYPE 3: a recommendation the system is outputting
};

// Chart series tokens — kept separate from STATUS_TIERS so the naming stays
// chart-specific, but aliased to the same COLORS hexes for the same reason:
// salesSeries/stockSeries used to be their own slightly-off teal/amber
// (#0D9488, #D97706) instead of the COLORS.dispatched/COLORS.warning used
// everywhere else, so the SKU Forecast and Dashboard trend lines were a
// visibly different shade from the same-meaning bars on ABC
// Classification. abcRamp is a fallback only (see ABC_TIER_COLORS in
// Charts.jsx) — pointed at the real plum ramp so even the fallback can't
// disagree with the ABC badges/tables that use COLORS.abcA/B/C directly.
export const CHART_COLORS = {
  salesSeries: COLORS.dispatched,
  stockSeries: COLORS.warning,
  abcRamp: [COLORS.abcA, COLORS.abcB, COLORS.abcC], // Class A, B, C — sequential
  cumulativeCurve: '#475569',
  gridline: '#E2E8F0',
  axisLabel: '#64748B',
};
