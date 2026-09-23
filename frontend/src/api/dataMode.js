import { apiFetch } from '../auth';

// GET /data-mode — what preview mode means right now (src/dataMode.js):
// the placeholder window, and `outputs` when the file-backed what-if
// forecasts and LP results exist (scripts/build_preview_outputs.py), null
// when they don't. Fetched by the layout when preview turns on, so every
// page can label its predictive and prescriptive figures before its own
// payload arrives. Not cached: it is one small request per switch.
export async function getDataModeInfo() {
  const res = await apiFetch('/data-mode');
  if (!res.ok) throw new Error('Failed to fetch data mode');
  return res.json();
}
