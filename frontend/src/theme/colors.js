// SAN2 Inventory DSS Design Tokens
export const COLORS = {
  // Data Visualization Color System
  critical: '#E5484D',       // Red: KPI negative deltas, critical reorders, bad order incidents
  warning: '#F5A623',        // Amber: Warnings, under investigation, low stock
  success: '#2E9E5B',        // Green: Good, resolved, positive trends, received units
  salesTrend: '#5B5FEF',     // Indigo: Sales trend / primary metric lines
  dispatched: '#14919B',     // Teal: Dispatched / secondary flow metrics
  forecast: '#A855F7',       // Violet: Forecast / projected values
  forecastBg: '#F3E8FF',     // Light Violet tint: 90% CI uncertainty band
  gridline: '#B4BCC7',       // Gray: Gridlines & baselines

  // ABC Classification Single-Hue Plum Ramp (Ordinal by value)
  abcA: '#6B2C5F',          // Category A - Top 20% / 80% revenue (darkest plum)
  abcB: '#B565A0',          // Category B - Middle tier (medium plum)
  abcC: '#EBC9E1',          // Category C - Long tail (lightest plum)

  // UI Chrome & Brand Accent
  brandPrimary: '#c53030',   // SAN2 Corporate Red (UI Chrome / Nav)
  brandAccent: '#e53e3e',
};
