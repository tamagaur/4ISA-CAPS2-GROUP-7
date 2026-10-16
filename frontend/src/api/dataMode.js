import { apiFetch } from '../auth';
import { DATA_MODE_HEADER, DATA_MODES } from '../dataMode';

// GET /data-mode — what the synthetic view means right now (src/dataMode.js):
// `placeholder`, the generated window (Unilever's 2021-22 back-cast, schema
// demo) when the server's DM_DEMO_ENABLED switch is on and null when it is
// off; `outputs`, the what-if run retired on 2026-10-15 (null). `preview`
// asks as the synthetic view does whatever the mode is now, so the layout
// knows before the switch is used whether this server has synthetic data to
// show. Not cached: one small request per switch or Refresh.
export async function getDataModeInfo({ preview = false } = {}) {
  const res = await apiFetch('/data-mode', preview ? { headers: { [DATA_MODE_HEADER]: DATA_MODES.PREVIEW } } : undefined);
  if (!res.ok) throw new Error('Failed to fetch data mode');
  return res.json();
}
