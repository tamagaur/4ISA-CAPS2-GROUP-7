import { API_URL, apiFetch, authHeaders } from '../auth';

// The live demonstration (backend/routers/live_demo.py). Mounted only on a person's own machine, when they switched it on:
// everywhere else GET /live-demo/status is a 404 and the page is exactly what it was.

async function readJson(res, fallback) {
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const error = new Error(body?.detail && typeof body.detail === 'string' ? body.detail : fallback);
    error.code = body?.code;
    error.decisions = body?.decisions;
    throw error;
  }
  return body;
}

// Anything but a clear yes hides the card.
export async function getLiveDemoAvailable() {
  try {
    const res = await apiFetch('/live-demo/status');
    if (!res.ok) return null;
    const body = await res.json();
    return body.enabled ? body : null;
  } catch {
    return null;
  }
}

export async function getLiveDemoStatus() {
  return readJson(await apiFetch('/live-demo/status'), 'Could not read where the demonstration stands.');
}

export async function getLiveDemoJob() {
  return readJson(await apiFetch('/live-demo/job'), 'Could not read the running step.');
}

const post = async (path, body, fallback) => readJson(
  await apiFetch(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  fallback,
);

export const startLiveDemo = () => post('/live-demo/start', {}, 'Could not start the demonstration.');
export const settleLiveDemoOrders = () => post('/live-demo/settle', {}, 'Could not start accepting the orders.');
export const runLiveDemo = (calendarFactor = 'on') => post('/live-demo/run', { calendar_factor: calendarFactor }, 'Could not start the run.');
export const undoLiveDemo = () => post('/live-demo/undo', { confirm: true }, 'Could not start the undo.');

export async function uploadLiveDemoFile(file) {
  const form = new FormData();
  form.append('file', file);
  // Not apiFetch: the browser must set the multipart Content-Type itself.
  const res = await fetch(`${API_URL}/live-demo/file`, { method: 'POST', headers: authHeaders(), body: form });
  return readJson(res, 'The file could not be uploaded.');
}
