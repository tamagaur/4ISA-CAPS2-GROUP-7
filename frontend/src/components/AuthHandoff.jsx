// The full-screen moment between the sign-in form and the dashboard, and
// between the dashboard and the sign-in page (2026-10-16; in the sign-in
// page's golden-hour theme since 2026-10-19): the SAN2 logo, a turning
// ring and a line saying what is happening ("Signing in to the
// dashboard…", "Logging out of the dashboard…"). It is drawn in a portal
// on <body>, above every dialog and toast, and takes every click while it
// is up. A screen reader hears the line (role="status").
//
// Logging out: Sidebar.jsx shows it for HANDOFF_HOLD_MS, then signs out.
// Signing in: Login.jsx begins it (beginHandoff) once the password and
// code are accepted, and SignInHandoff, mounted in App.jsx for the whole
// session, keeps it up through the change of page until the first page
// has nothing left loading (Audrey, 2026-10-16: no skeleton or "Loading…"
// between the sign-in and the dashboard), then fades it out.
import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { prefersReducedMotion } from '../theme/motion';
import './AuthHandoff.css';

// How long the screen stays before the page changes: long enough to read,
// short enough not to feel like waiting. Shorter for a viewer who asks for
// reduced motion, who gets the words without the ring turning or the fade.
export const HANDOFF_HOLD_MS = 1100;
export const HANDOFF_HOLD_REDUCED_MS = 600;

export const holdForHandoff = () => new Promise((resolve) => {
  setTimeout(resolve, prefersReducedMotion() ? HANDOFF_HOLD_REDUCED_MS : HANDOFF_HOLD_MS);
});

export const HANDOFF_TEXT = {
  in: { title: 'Signing in to the dashboard…', detail: 'Opening your dashboard.' },
  out: { title: 'Logging out of the dashboard…', detail: 'Ending your session securely.' },
};

// The sign-in hand-off, kept outside any page since the login page and
// the app shell never render together: Login.jsx begins it, SignInHandoff
// shows it and ends it.
const listeners = new Set();
let current = null;
const announce = () => listeners.forEach((listener) => listener(current));
export const beginHandoff = (kind) => { current = kind; announce(); };
export const endHandoff = () => { current = null; announce(); };
export const useHandoff = () => {
  const [kind, setKind] = useState(current);
  useEffect(() => {
    listeners.add(setKind);
    setKind(current);
    return () => { listeners.delete(setKind); };
  }, []);
  return kind;
};

// The page pane is "in" once nothing in it is still a skeleton block or a
// "Loading…" notice (Skeleton.jsx); until the shell is up at all, it is
// not. Checked every HANDOFF_POLL_MS; the screen is never kept past
// HANDOFF_MAX_MS, and it goes at once if the sign-in bounced back to the
// login page.
const HANDOFF_POLL_MS = 150;
const HANDOFF_MIN_MS = 400;
const HANDOFF_MAX_MS = 12000;
const HANDOFF_BOUNCE_MS = 2500;
const HANDOFF_FADE_MS = 240;
const stillLoading = () => {
  const pane = document.querySelector('.main-content');
  if (!pane) return true;
  if (pane.querySelector('[class^="skeleton-"], [class*=" skeleton-"]')) return true;
  return [...pane.querySelectorAll('.visually-hidden[role="status"]')].some((el) => /^Loading/i.test(el.textContent));
};

export function SignInHandoff() {
  const handoff = useHandoff();
  const [ending, setEnding] = useState(false);
  useEffect(() => {
    if (handoff !== 'in') return undefined;
    const started = Date.now();
    let fade = null;
    const timer = setInterval(() => {
      const waited = Date.now() - started;
      const bounced = waited >= HANDOFF_BOUNCE_MS && document.querySelector('.login-page');
      if ((waited >= HANDOFF_MIN_MS && !stillLoading()) || waited >= HANDOFF_MAX_MS || bounced) {
        clearInterval(timer);
        setEnding(true);
        fade = setTimeout(() => { setEnding(false); endHandoff(); }, HANDOFF_FADE_MS);
      }
    }, HANDOFF_POLL_MS);
    return () => {
      clearInterval(timer);
      clearTimeout(fade);
    };
  }, [handoff]);
  if (handoff !== 'in') return null;
  return <AuthHandoff kind="in" ending={ending} />;
}

export default function AuthHandoff({ kind, ending = false }) {
  const text = HANDOFF_TEXT[kind] || HANDOFF_TEXT.in;
  return createPortal(
    <div className={`auth-handoff${ending ? ' is-ending' : ''}`} role="status" aria-live="polite">
      <div className="auth-handoff-panel">
        <img src="/images/login-logo-red.png" alt="SAN2 Corporation" className="auth-handoff-logo" />
        <span className="auth-handoff-ring" aria-hidden="true" />
        <p className="auth-handoff-title">{text.title}</p>
        <p className="auth-handoff-detail">{text.detail}</p>
      </div>
    </div>,
    document.body,
  );
}
