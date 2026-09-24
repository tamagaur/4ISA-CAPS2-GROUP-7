// Data mode — real data, or PREVIEW: real data plus Unilever's 2021-22
// placeholder months (backend/data_mode.py has the full rules).
//
// Asked for 2026-09-23: see the dashboard over five years before SSM's real
// 2021-22 files arrive. The placeholder rows are synthetic (is_demo), so
// preview is opt-in, labelled on every page while it is on, and limited to
// what it can honestly change: the descriptive views, recomputed per
// request, and, once scripts/build_preview_outputs.py has run, a what-if
// copy of the forecasts and LP results that is never saved.
//
// Kept for the browser tab only (sessionStorage): a new tab, or the next
// session, opens on real data, so nobody lands in preview without choosing it.

export const DATA_MODES = { REAL: 'real', PREVIEW: 'preview' };
export const DATA_MODE_HEADER = 'X-Data-Mode';
const STORAGE_KEY = 'san2_data_mode';

// The placeholder span preview adds, and the principal it belongs to. The
// backend's own window (a preview payload's data_mode.placeholder) is what
// charts mark; these constants size the date picker, which is built before
// any request has returned — same arrangement as dataCoverage.js.
export const PLACEHOLDER_START = { month: 'Jan', year: '2021' };
export const PLACEHOLDER_END_PERIOD = '2022-12';
export const PLACEHOLDER_PRINCIPAL = 'unilever';

const readStored = () => {
  try {
    return sessionStorage.getItem(STORAGE_KEY) === DATA_MODES.PREVIEW ? DATA_MODES.PREVIEW : DATA_MODES.REAL;
  } catch {
    return DATA_MODES.REAL;
  }
};

let current = readStored();

export const getDataMode = () => current;
export const isPreviewMode = (mode = current) => mode === DATA_MODES.PREVIEW;

export function setDataMode(mode) {
  current = mode === DATA_MODES.PREVIEW ? DATA_MODES.PREVIEW : DATA_MODES.REAL;
  try {
    sessionStorage.setItem(STORAGE_KEY, current);
  } catch {
    // Storage blocked: the mode still holds for this page load.
  }
  return current;
}

// Header for a READ request. Preview never reaches a write.
export const dataModeHeaders = (method) => (
  isPreviewMode() && (!method || method.toUpperCase() === 'GET') ? { [DATA_MODE_HEADER]: DATA_MODES.PREVIEW } : {}
);

/** True when 'YYYY-MM' falls inside a payload's data_mode.placeholder window. */
export function isPlaceholderPeriod(period, placeholder) {
  if (!period || !placeholder?.start || !placeholder?.end) return false;
  const p = String(period).slice(0, 7);
  return p >= placeholder.start && p <= placeholder.end;
}
