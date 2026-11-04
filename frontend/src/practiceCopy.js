// Whether the API answering this page reads the local practice copy. The backend decides from its own connection
// (backend/practice_copy.py) and says so on every answer; nothing on this side can turn it on. The deployed API never
// sends the header, so the note stays null and nothing shows.
export const PRACTICE_HEADER = 'X-Practice-Copy';

let note = null;
const listeners = new Set();

export function notePracticeCopy(value) {
  if (!value || value === note) return;
  note = value;
  listeners.forEach((listener) => listener());
}

export function subscribePracticeCopy(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getPracticeCopyNote() {
  return note;
}
