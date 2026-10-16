// The full-screen moment between the sign-in form and the dashboard, and
// between the dashboard and the sign-in page (2026-10-16): the SAN2 logo,
// a turning ring and a line saying what is happening ("Signing in to the
// dashboard…", "Logging out of the dashboard…"). Shown by Login.jsx once
// the password (and code) are accepted, and by Sidebar.jsx once Log out
// is confirmed, for HANDOFF_HOLD_MS before the page changes, so the
// change reads as a deliberate step rather than a jump. It is drawn in a
// portal on <body>, above every dialog and toast, and takes every click
// while it is up. A screen reader hears the line (role="status").
import React from 'react';
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
  in: { title: 'Signing in to the dashboard…', detail: 'Loading your workspace.' },
  out: { title: 'Logging out of the dashboard…', detail: 'Ending your session securely.' },
};

export default function AuthHandoff({ kind }) {
  const text = HANDOFF_TEXT[kind] || HANDOFF_TEXT.in;
  return createPortal(
    <div className="auth-handoff" role="status" aria-live="polite">
      <div className="auth-handoff-panel">
        <img src="/images/login-logo-red-light.png" alt="SAN2 Corporation" className="auth-handoff-logo" />
        <span className="auth-handoff-ring" aria-hidden="true" />
        <p className="auth-handoff-title">{text.title}</p>
        <p className="auth-handoff-detail">{text.detail}</p>
      </div>
    </div>,
    document.body,
  );
}
