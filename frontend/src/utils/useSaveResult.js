// frontend/src/utils/useSaveResult.js — drives a dialog's "did it save?"
// moment, shown with <SaveResult> (components/SaveResult.jsx).
//
// run(save) awaits the save, then:
//   saved  -> result { ok: true, value } for SAVED_SHOW_MS, then onSaved(value)
//             (usually closes the dialog)
//   failed -> result { ok: false, message } for FAILED_SHOW_MS, then the
//             dialog's own content comes back; onFailed(message) lets it keep
//             the reason on screen, afterFailed() runs when the red X ends
//
// Before this, most dialogs closed the moment Save was clicked and reported
// through a toast in the corner, or said nothing at all when a save failed.
import { useCallback, useEffect, useRef, useState } from 'react';

// Long enough to register the check mark, short enough not to feel like a wait.
export const SAVED_SHOW_MS = 1300;
// Longer: the reason has to be read.
export const FAILED_SHOW_MS = 2600;

export function useSaveResult() {
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null);
  // A ref as well as state: a double-click lands before the re-render.
  const savingRef = useRef(false);
  const timerRef = useRef(null);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const reset = useCallback(() => {
    clearTimeout(timerRef.current);
    savingRef.current = false;
    setSaving(false);
    setResult(null);
  }, []);

  const run = useCallback(async (save, {
    onSaved,
    onFailed,
    afterFailed,
    fallbackError = 'Something went wrong. Please try again.',
  } = {}) => {
    if (savingRef.current) return false;
    savingRef.current = true;
    clearTimeout(timerRef.current);
    setResult(null);
    setSaving(true);
    let value;
    try {
      value = await save();
    } catch (err) {
      const message = err?.message || fallbackError;
      savingRef.current = false;
      setSaving(false);
      setResult({ ok: false, message });
      onFailed?.(message);
      timerRef.current = setTimeout(() => {
        setResult(null);
        afterFailed?.();
      }, FAILED_SHOW_MS);
      return false;
    }
    savingRef.current = false;
    setSaving(false);
    setResult({ ok: true, value });
    timerRef.current = setTimeout(() => {
      setResult(null);
      onSaved?.(value);
    }, SAVED_SHOW_MS);
    return true;
  }, []);

  return { saving, result, run, reset };
}
