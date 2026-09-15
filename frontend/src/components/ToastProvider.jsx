import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';
import './Toast.css';

// App-wide toast notifications.
//
// Before this, every success/failure signal was local to whatever component
// produced it: separate copy-pasted "success" panels inside AddSKUModal
// and EditSKUModal (each with its own 1.5s auto-dismiss timer), and
// nothing at all for actions that don't happen inside a modal —
// accepting a reorder recommendation, deleting a user. Confirmation therefore
// disappeared with the modal that produced it, and the data-entry-heavy parts
// of the app had no way to say "that worked" once the dialog closed.
//
// Usage:
//   const toast = useToast();
//   toast.success('SKU 20071069 created');
//   toast.error('Could not save changes: ' + err.message);
//
// Errors deliberately persist until dismissed (duration: 0) — a failure the
// user might need to read or act on shouldn't vanish on a timer the way a
// success confirmation reasonably can.

const ToastContext = createContext(null);

const DEFAULT_DURATION = 4000;
const ERROR_DURATION = 0; // 0 = stays until dismissed

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // A no-op fallback rather than a crash: a component rendered outside the
    // provider (a test harness, a stray render) should degrade quietly, not
    // take the page down over a notification.
    return {
      success: () => {},
      error: () => {},
      info: () => {},
      dismiss: () => {},
    };
  }
  return ctx;
};

const ICONS = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
};

const ToastItem = ({ toast, onDismiss }) => {
  const Icon = ICONS[toast.variant] || Info;
  return (
    <div
      className={`toast toast-${toast.variant}`}
      // Errors assert themselves to a screen reader immediately; successes
      // wait politely for a pause rather than interrupting.
      role={toast.variant === 'error' ? 'alert' : 'status'}
      aria-live={toast.variant === 'error' ? 'assertive' : 'polite'}
    >
      <Icon size={16} className="toast-icon" aria-hidden="true" />
      <span className="toast-message">{toast.message}</span>
      <button
        className="toast-dismiss"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
      >
        <X size={14} />
      </button>
    </div>
  );
};

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);
  // Timer handles are kept out of state so clearing them never triggers a
  // render, and so unmount can cancel every pending dismissal at once.
  const timersRef = useRef(new Map());

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const push = useCallback((message, variant, duration) => {
    if (!message) return undefined;
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setToasts((prev) => [...prev, { id, message: String(message), variant }]);

    const ms = duration ?? (variant === 'error' ? ERROR_DURATION : DEFAULT_DURATION);
    if (ms > 0) {
      const timer = setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
        timersRef.current.delete(id);
      }, ms);
      timersRef.current.set(id, timer);
    }
    return id;
  }, []);

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
    };
  }, []);

  // Memoised so consumers don't re-render on every toast state change.
  const api = React.useMemo(() => ({
    success: (message, duration) => push(message, 'success', duration),
    error: (message, duration) => push(message, 'error', duration),
    info: (message, duration) => push(message, 'info', duration),
    dismiss,
  }), [push, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-region" aria-label="Notifications">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export default ToastProvider;
