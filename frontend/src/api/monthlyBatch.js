import { apiFetch } from '../auth';

// Monthly Data Processing (backend/routers/monthly_batch.py). GET /batch/status answers { enabled: false } where no database is named.

// A refusal keeps the backend's code and what it sent with it, so the page can
// tell a blocked run from any other failure.
async function readJson(res, fallback) {
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const error = new Error(body?.detail && typeof body.detail === 'string' ? body.detail : fallback);
    error.code = body?.code;
    error.checks = body?.checks;
    error.decisions = body?.decisions;
    throw error;
  }
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

// Where the month stands, check by check. Reads only.
export async function getBatchChecklist(month) {
  const query = month ? `?month=${encodeURIComponent(month)}` : '';
  return readJson(await apiFetch(`/batch/checklist${query}`), 'Could not read the checklist.');
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
  // Through apiFetch (2026-11-13), which leaves a FormData body's Content-Type to the browser (the multipart boundary):
  // an expired session is caught before the upload is sent and a 401 signs out, as for every other request.
  const res = await apiFetch('/batch/files', { method: 'POST', body: form });
  return readJson(res, 'The file could not be uploaded.');
}

const post = async (path, body, fallback) => readJson(
  await apiFetch(path, { method: 'POST', body: JSON.stringify(body) }),
  fallback,
);

export const generatePracticeMonth = (month) => post('/batch/practice-month', { month }, 'Could not generate practice sales.');
export const validateBatch = (month) => post('/batch/validate', { month }, 'Could not start the validation.');
export const signoffBatch = (month) => post('/batch/signoff', { month }, 'The file could not be approved.');
export const runBatch = (month, calendarFactor, acceptWaiting = false) => post(
  '/batch/run',
  { month, calendar_factor: calendarFactor, accept_waiting: acceptWaiting },
  'Could not start the batch.',
);
// Puts the system back to before `month` was loaded (admin only: data.rollback). Also removes every month loaded after it.
export const rollbackMonth = (month) => post('/batch/rollback', { month, confirm: true }, 'Could not start the rollback.');
export const closeBatch = (month, calendarFactor, expectPlanPieces) => post(
  '/batch/close',
  { month, calendar_factor: calendarFactor, expect_plan_pieces: expectPlanPieces },
  'Could not close the month.',
);
