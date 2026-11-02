// The order plan's urgency (GET /recommendations and GET /dashboard's
// reorder_preview `urgency`, backend/stock_status.py's rule), shown the same
// way on every page (2026-10-20): the Reorder page's uppercase pill with its
// dot and colours (index.css .pill-*), the backend's own word as its text,
// and what to do in the hover. Used by Reorder Recommendations, the Sales
// forecast page and the Dashboard (Pending reorders card, Suggested orders).

// The pill's class for an urgency, as the Reorder page has always drawn it.
export function getUrgencyBadge(urgency) {
  switch (urgency) {
    case 'CRITICAL': return 'pill pill-critical';
    case 'URGENT': return 'pill pill-warning';
    case 'PLANNED': return 'pill pill-planned';
    default: return 'pill pill-neutral'; // 'NO DATA' — no stock record, no verdict
  }
}

// What each urgency means and what to do, for the pill's hover.
export const URGENCY_HOVER = {
  CRITICAL: 'Below safety stock: order now',
  URGENT: 'Below target stock: order soon',
  PLANNED: 'At or above target stock: can wait',
  'NO DATA': 'No usable pack size for this product, so its stock can’t be read',
};
