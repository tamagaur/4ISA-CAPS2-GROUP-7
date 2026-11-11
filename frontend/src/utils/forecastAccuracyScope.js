// The line under "How close the forecasts were" on the SKU Forecast page (2026-11-06, the card moved there
// from the Dashboard). It names whose products the figures cover from the response's own coverage
// (GET /dashboard/accuracy: ['unilever'] today; Del Monte has no product-level forecasts, so it never
// appears), not from the principal switch, so the line cannot claim a principal the figures leave out.
const PRINCIPAL_NAMES = { unilever: 'Unilever', delmonte: 'Del Monte' };

export function accuracyScopeLine(coverage) {
  const names = (coverage || []).map((c) => PRINCIPAL_NAMES[c] || c).filter(Boolean);
  if (names.length === 0) return null;
  const who = names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
  return `${who} products whose forecast was checked against sales, over the months picked above.`;
}
