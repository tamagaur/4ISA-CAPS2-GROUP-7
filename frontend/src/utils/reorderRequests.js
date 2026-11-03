// frontend/src/utils/reorderRequests.js — the arithmetic behind the Reorder
// page's staff requests (2026-10-28): a quantity typed in pieces or cases,
// the whole-case check the server makes (backend/case_pack.check_whole_cases),
// the warnings shown before a change is sent or approved, and whether a
// request still matches the row on screen. Kept apart from the components so
// node --test can check it (reorderRequests.test.js).
//
// Every quantity is in PIECES, the unit of the order plan's q_i. A case is
// the row's pack_size (pieces per case); null means only pieces can be used.
// The product master holds no packs-per-case figure, so there is no "packs".

// The server's own tolerance for "a whole number of cases" (case_pack.py
// PACK_TOLERANCE), so the page never accepts what the server refuses.
const PACK_TOLERANCE = 1e-6;

// Quantities are stored to 2 decimals (lp_quantity_change), so two figures
// are "the same" when they agree to 2 decimals, as the server compares them.
export const round2 = (n) => Math.round(Number(n) * 100) / 100;
export const sameQuantity = (a, b) => a != null && b != null && round2(a) === round2(b);

// Cases can be chosen only when a case holds more than one piece.
export const casesAvailable = (packSize) => Number(packSize) > 1;

// "4 cases" (whole) or "≈ 4.5 cases" for pieces, or null with no case size.
export function casesText(pieces, packSize) {
  if (pieces == null || !casesAvailable(packSize)) return null;
  const n = round2(Number(pieces) / Number(packSize));
  const shown = Number.isInteger(n) ? n.toLocaleString() : `≈ ${n.toLocaleString(undefined, { maximumFractionDigits: 1 })}`;
  return `${shown} case${n === 1 ? '' : 's'}`;
}

// The typed amount in pieces, or null when nothing usable was typed.
export function toPieces(amount, unit, packSize) {
  if (amount === '' || amount == null) return null;
  const n = Number(amount);
  if (!Number.isFinite(n)) return null;
  return unit === 'cases' ? n * Number(packSize) : n;
}

// The nearest whole-case quantities either side of `pieces`, as the server
// offers them in a 422 not_whole_cases (nearest_below, nearest_above).
export function nearestWholeCases(pieces, packSize) {
  const pack = Number(packSize);
  const below = Math.floor(pieces / pack) * pack;
  return { below, above: below + pack };
}

// What is wrong with a proposed quantity, or null when it can be sent.
// { code, message, alternatives? } — alternatives are pieces to click to.
export function validateProposedQuantity({ amount, unit, packSize, recommended }) {
  if (amount === '' || amount == null) return { code: 'empty', message: 'Enter the quantity you want ordered.' };
  const n = Number(amount);
  if (!Number.isFinite(n)) return { code: 'not_a_number', message: 'Enter a number.' };
  if (n < 0) return { code: 'negative', message: 'The quantity can’t be below 0.' };
  if (unit === 'cases') {
    if (!casesAvailable(packSize)) return { code: 'no_case_size', message: 'This product has no case size, so enter pieces.' };
    if (!Number.isInteger(n)) return { code: 'not_whole_cases', message: 'Enter a whole number of cases.' };
  } else if (!Number.isInteger(n)) {
    return { code: 'not_whole_pieces', message: 'Enter a whole number of pieces.' };
  }
  const pieces = toPieces(n, unit, packSize);
  if (sameQuantity(pieces, recommended)) {
    return {
      code: 'quantity_unchanged',
      // A row that orders nothing has no Accept (reorderView.js rowActions).
      message: Number(recommended) > 0
        ? 'That is the recommended quantity. Accept the recommendation as it is instead.'
        : 'The plan already orders nothing for this product. Enter the quantity you want ordered.',
    };
  }
  if (unit !== 'cases' && casesAvailable(packSize)) {
    const pack = Number(packSize);
    const cases = pieces / pack;
    if (Math.abs(cases - Math.round(cases)) * pack > PACK_TOLERANCE) {
      const { below, above } = nearestWholeCases(pieces, pack);
      return {
        code: 'not_whole_cases',
        message: `${pieces.toLocaleString()} pieces is ${cases.toFixed(2)} cases. This product is ordered in whole `
          + `cases of ${pack.toLocaleString()} pieces.`,
        alternatives: [below, above].filter((v) => v >= 0 && !sameQuantity(v, recommended)),
      };
    }
  }
  return null;
}

// The proposed quantity against the recommendation: pieces and percent.
// percent is null when the recommendation is 0 (any order is "new").
export function quantityDifference(proposed, recommended) {
  if (proposed == null || recommended == null) return null;
  const pieces = round2(proposed - recommended);
  const percent = Number(recommended) > 0 ? (pieces / Number(recommended)) * 100 : null;
  return { pieces, percent };
}

// "+120 pieces (+8.3%)" / "−40 pieces (−2.0%)" / "+600 pieces (from 0)".
export function differenceText(diff) {
  if (!diff) return '—';
  const sign = diff.pieces > 0 ? '+' : diff.pieces < 0 ? '−' : '';
  const abs = Math.abs(diff.pieces).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const pct = diff.percent == null
    ? (diff.pieces !== 0 ? ' (the plan suggested 0)' : '')
    : ` (${sign}${Math.abs(diff.percent).toFixed(1)}%)`;
  return `${sign}${abs} pieces${pct}`;
}

// The warnings for a proposed quantity, worked out from the plan row on the
// page (never blocking for the requester; an admin ticks that they read them
// before approving). `planHasCuts`: some row in the plan was cut to fit the
// supplier allocation (short_units > 0), i.e. the allocation is used up.
// Each warning: { key, text }.
export function quantityWarnings(row, proposed, { planHasCuts = false } = {}) {
  const warnings = [];
  if (!row || proposed == null) return warnings;
  const { forecast, rop, stock, orderQty } = row;
  if (forecast != null && rop != null && stock != null) {
    // Month-end stock = opening stock + order − forecast; above target by
    // that minus target stock, i.e. proposed − (forecast + target − stock).
    const need = forecast + rop - stock;
    if (proposed > Math.max(0, need)) {
      const over = Math.ceil(proposed - need - PACK_TOLERANCE);
      if (over > 0) {
        warnings.push({
          key: 'above_target',
          text: `This quantity ends the month above target stock by about ${over.toLocaleString()} pieces `
            + '(opening stock + this order − the month’s forecast, against the target stock).',
        });
      }
    }
  }
  if (planHasCuts && orderQty != null && proposed > orderQty) {
    warnings.push({
      key: 'allocation',
      text: 'The supplier allocation is already used up in this plan (some products were cut to fit it), so ordering '
        + 'more than the recommendation goes beyond the allocation.',
    });
  }
  if (row.needsReview) {
    warnings.push({ key: 'needs_review', text: 'This product is flagged for review before ordering: a large forecast miss is likely.' });
  }
  return warnings;
}

// The warnings for dismissing a row (ordering nothing for it this month).
export function dismissalWarnings(row) {
  const warnings = [];
  if (!row) return warnings;
  if (row.stock != null && row.safetyStock != null && row.stock < row.safetyStock && (row.orderQty || 0) > 0) {
    warnings.push({
      key: 'below_safety',
      text: 'Opening stock is below this product’s safety stock; dismissing orders nothing for it this month.',
    });
  }
  if (row.needsReview) {
    warnings.push({ key: 'needs_review', text: 'This product is flagged for review before ordering: a large forecast miss is likely.' });
  }
  return warnings;
}

// A waiting request is stale when the row on the page no longer carries the
// quantity the request was made against (a newer run of the order plan moved
// it). The server refuses to approve it (409 recommendation_changed) for the
// same reason. null when the row isn't on the page: unknown, not stale.
export function isStale(request, row) {
  if (!request || request.state !== 'pending_approval' || !row || row.orderQty == null) return null;
  return !sameQuantity(row.orderQty, request.recommended_q_i);
}

// The backend writes request times with datetime.utcnow(), which serialises
// without a zone ("2026-10-23T09:00:00"); new Date() would read that as local
// time. A time with no zone is read as UTC; one with a zone is kept as is.
const HAS_ZONE = /(Z|[+-]\d{2}:?\d{2})$/i;
export function serverTime(value) {
  if (!value) return null;
  const s = String(value);
  if (/^\d{4}-\d{2}-\d{2}T/.test(s) && !HAS_ZONE.test(s)) return new Date(`${s}Z`);
  return new Date(s);
}

// A stock count's form fields as the API's stock_observation, or null when
// no quantity was entered. counted_at comes from <input type="datetime-local">
// (local time), sent as an ISO time with its zone.
export function stockObservationPayload({ quantity, unit, countedAt, location, notes }) {
  if (quantity === '' || quantity == null) return null;
  const body = { quantity: Number(quantity), unit: unit === 'cases' ? 'cases' : 'pieces' };
  if (countedAt) {
    const d = new Date(countedAt);
    if (!Number.isNaN(d.getTime())) body.counted_at = d.toISOString();
  }
  if (location?.trim()) body.location = location.trim();
  if (notes?.trim()) body.notes = notes.trim();
  return body;
}

// A stock count form's fields before anything is typed.
export const EMPTY_COUNT = { quantity: '', unit: 'pieces', countedAt: '', location: '', notes: '' };

// What is wrong with a count form, or null.
export const stockCountError = (count, packSize) =>
  validateStockCount({ quantity: count.quantity, unit: count.unit, packSize });

// What is wrong with a stock count, or null. An empty count is fine (optional).
export function validateStockCount({ quantity, unit, packSize }) {
  if (quantity === '' || quantity == null) return null;
  const n = Number(quantity);
  if (!Number.isFinite(n)) return 'Enter the counted quantity as a number.';
  if (n < 0) return 'A count can’t be below 0.';
  if (unit === 'cases') {
    if (!casesAvailable(packSize)) return 'This product has no case size, so count in pieces.';
    if (!Number.isInteger(n)) return 'Enter a whole number of cases.';
  }
  return null;
}

// ── The Staff Requests table (2026-10-28) ───────────────────────────────────
// Quantity changes and dismissal requests are numbered by two tables
// (lp_quantity_change.change_key, lp_dismissal_request.request_key), so the
// same number can be both: the ID shown carries the kind.
export function requestId(item) {
  if (!item) return '';
  return item.kind === 'dismissal' ? `DR-${item.request_key}` : `QC-${item.change_key}`;
}

// The deep-link form, ?request=quantity_change-7 or dismissal-4 (the
// notification bell links there). The item's own key: c7 / d4.
const LINK_RE = /^(quantity_change|dismissal)-(\d+)$/;
export function parseRequestLink(value) {
  const m = LINK_RE.exec(String(value || '').trim());
  if (!m) return null;
  return { kind: m[1], key: `${m[1] === 'dismissal' ? 'd' : 'c'}${Number(m[2])}` };
}

// The staff member's name, or the email when users has no name for it.
export const requesterName = (item) => item?.byName || item?.by || '—';

// The three outcomes a request can have; anything else (an unknown state
// from a newer server) counts in no card and shows in "All" only.
export const STATUS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'pending_approval', label: 'Pending' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
];

export function requestCounts(items) {
  const counts = { all: 0, pending_approval: 0, approved: 0, rejected: 0 };
  (items || []).forEach((r) => {
    counts.all += 1;
    if (r.state in counts) counts[r.state] += 1;
  });
  return counts;
}

// The list under a status filter and a search (staff name or email,
// product, SKU, request ID), case-insensitive.
export function filterRequests(items, { status = 'all', query = '' } = {}) {
  const q = query.trim().toLowerCase();
  return (items || []).filter((r) => {
    if (status !== 'all' && r.state !== status) return false;
    if (!q) return true;
    return [r.byName, r.by, r.product_name, r.sku_code, requestId(r)]
      .some((v) => v != null && String(v).toLowerCase().includes(q));
  });
}
