// Why a month has no figure, or a zero (kelvin-etl, merged 2026-10-16): the
// reason codes backend/series_gaps.py puts on chart points, as short labels
// for a chart's tooltip or a table cell. The long explanation is the
// backend's own `gap_note` on the same response, shown under the chart by
// GapNote.jsx, so the words are written once, in the backend.
export const GAP_LABEL = {
  no_sale: 'No sale this month',
  blank_capture: 'Quantity not recorded',
  outside_product_lifespan: 'Not on sale then',
  not_collected: 'Not collected',
  category_absent: 'Category not reported',
  no_data_recorded_before_2023: 'No data recorded before 2023',
  interpolated: 'Generated between real months',
  taxonomy_change_bridge: 'Generated across the category change',
  no_observation_before_series_start: 'Generated before the first real month',
};

export const gapLabel = (code) => (code ? GAP_LABEL[code] || code.replace(/_/g, ' ') : null);

// The backend's note reads "[code] text [code] text"; as [{ code, label, text }],
// keeping only `codes` when given (a page that drops some points drops their
// explanation too).
export function gapNoteEntries(note, codes = null) {
  if (!note) return [];
  const out = [];
  const re = /\[([a-z0-9_]+)\]\s*([^[]*)/g;
  let m;
  while ((m = re.exec(note)) !== null) {
    if (!codes || codes.has(m[1])) out.push({ code: m[1], label: gapLabel(m[1]), text: m[2].trim() });
  }
  return out;
}

// How a synthetic demonstration month was made (schema demo, CLAUDE.md rule 2;
// docs/DEMO_DATA.md). The four origins are kept apart in every label. GET
// /dashboard's demonstration.monthly_totals names them real / interpolated /
// bridged / backcast; a series point or a demo forecast's history names them
// real_copy / interpolated / bridged / backcast.
export const ORIGIN_LABEL = {
  real: 'copied from a real month',
  real_copy: 'copied from a real month',
  interpolated: 'filled between two real months',
  bridged: 'carried across the Jan 2025 change of categories',
  backcast: 'back-cast, no data recorded then',
  // Migrations 0056-0057 (2026-10-16): a category's last real month carried forward, and generated stock.
  forward_filled: 'carried forward from its last real month',
  generated_months_of_cover: 'generated around 3 weeks of cover',
};

export const originLabel = (origin) => (origin ? ORIGIN_LABEL[origin] || origin.replace(/_/g, ' ') : null);
