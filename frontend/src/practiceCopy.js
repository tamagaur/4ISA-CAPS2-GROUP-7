// Whether the API answering this page reads the local practice copy. The backend decides from its own connection
// (backend/practice_copy.py) and says so on every answer; nothing on this side can turn it on. The deployed API never
// sends the header, so the note stays null and nothing shows.
export const PRACTICE_HEADER = 'X-Practice-Copy';
// On every answer from any other database while it holds generated sales: the sentence the banner shows. Same mechanism, different words.
export const GENERATED_HEADER = 'X-Generated-Sales';

let note = null;
let kind = 'practice';
const listeners = new Set();

export function notePracticeCopy(value, nextKind = 'practice') {
  if (!value || (value === note && nextKind === kind)) return;
  note = value;
  kind = nextKind;
  listeners.forEach((listener) => listener());
}

export function subscribePracticeCopy(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getPracticeCopyNote() {
  return note;
}

export function getPracticeCopyKind() {
  return kind;
}

// A JSON answer without the header means the database holds no generated sales now (a month was rolled back): the sentence goes, without a reload.
// The practice copy's note stays, because that server labels every answer and a missing header there would be the odd case.
export function clearGeneratedNote() {
  if (kind !== 'generated' || !note) return;
  note = null;
  listeners.forEach((listener) => listener());
}
