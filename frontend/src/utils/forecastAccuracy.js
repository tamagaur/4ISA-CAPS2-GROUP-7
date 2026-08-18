// frontend/src/utils/forecastAccuracy.js — deterministic placeholder MAPE
// per SKU, standing in for analytics/forecasting/sarima.py's real
// MAPE/MASE output (backlog #49) until SKUForecast is wired to the live
// /forecast endpoint. Deterministic (hashed from the SKU code) rather than
// random so the same SKU always shows the same figure across renders.

function hashSeed(code) {
  let hash = 0;
  for (let i = 0; i < code.length; i++) {
    hash = (hash * 31 + code.charCodeAt(i)) >>> 0;
  }
  return hash;
}

// Returns a plausible MAPE% between 4.0 and 24.0 for a given SKU code.
export function getSKUMape(code) {
  const seed = hashSeed(code || '');
  return 4 + (seed % 201) / 10; // 4.0 - 24.0
}

export function getConfidenceTier(mape) {
  if (mape <= 10) return { label: 'High confidence', level: 'high' };
  if (mape <= 18) return { label: 'Moderate confidence', level: 'moderate' };
  return { label: 'Low confidence', level: 'low' };
}

export function getAverageMape(codes) {
  if (!codes || codes.length === 0) return 0;
  const total = codes.reduce((sum, code) => sum + getSKUMape(code), 0);
  return total / codes.length;
}
