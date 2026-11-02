import { API_URL, apiFetch, authHeaders } from '../auth';

// The monthly batch (backend/routers/monthly_batch.py). Local practice database
// only for now: GET /batch/status answers { enabled: false } everywhere else.

async function readJson(res, fallback) {
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.detail && typeof body.detail === 'string' ? body.detail : fallback);
  return body;
}

// Anything but a clear yes hides the panel: the page then behaves as it always did.
export async function getBatchAvailable() {
  try {
    const res = await apiFetch('/batch/status');
    if (!res.ok) return null;
    const body = await res.json();
    return body.enabled ? body : null;
  } catch {
    return null;
  }
}

export async function getBatchStatus(month) {
  const query = month ? `?month=${encodeURIComponent(month)}` : '';
  return readJson(await apiFetch(`/batch/status${query}`), 'Could not read where the batch stands.');
}

export async function getBatchJob() {
  return readJson(await apiFetch('/batch/job'), 'Could not read the running step.');
}

export async function getBatchFeedback(cycle) {
  return readJson(await apiFetch(`/batch/feedback?cycle=${encodeURIComponent(cycle)}`), 'Could not read the feedback report.');
}

export async function uploadBatchFile(month, kind, file) {
  const form = new FormData();
  form.append('month', month);
  form.append('kind', kind);
  form.append('file', file);
  // Not apiFetch: it sets a JSON Content-Type, and the browser must set this one
  // itself so the multipart boundary is included.
  const res = await fetch(`${API_URL}/batch/files`, { method: 'POST', headers: authHeaders(), body: form });
  return readJson(res, 'The file could not be uploaded.');
}

const post = async (path, body, fallback) => readJson(
  await apiFetch(path, { method: 'POST', body: JSON.stringify(body) }),
  fallback,
);

export const generatePracticeMonth = (month) => post('/batch/practice-month', { month }, 'Could not generate practice sales.');
export const runBatch = (month, calendarFactor) => post('/batch/run', { month, calendar_factor: calendarFactor }, 'Could not start the batch.');
export const closeBatch = (month, calendarFactor, expectPlanPieces) => post(
  '/batch/close',
  { month, calendar_factor: calendarFactor, expect_plan_pieces: expectPlanPieces },
  'Could not close the month.',
);
