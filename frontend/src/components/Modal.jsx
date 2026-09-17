import React, { useEffect, useRef, useCallback } from 'react';

// Shared dialog shell for every modal in the app.
//
// Before this existed, each modal was a bare <div className="...-overlay">:
// no role="dialog", so a screen reader never announced that a dialog had
// opened; no focus trap, so Tab walked straight out of the dialog into the
// sidebar behind it; and Escape-to-close was implemented ad hoc in 3 of ~9
// modals, so keyboard users could dismiss some dialogs but not others —
// including two destructive-action confirmations (logout, delete user).
//
// This component owns all four of those concerns in one place, so a modal
// author only supplies content. It deliberately does NOT own any visual
// styling: each caller keeps its own overlay/card classNames, so adopting
// this changes behavior without restyling anything.
//
// Focus handling follows the WAI-ARIA dialog pattern: focus moves into the
// dialog on open, is confined while open (Tab from the last focusable
// wraps to the first, Shift+Tab from the first wraps to the last), and is
// restored to whatever was focused before the dialog opened on close —
// so dismissing a dialog returns you to the button you opened it from.
const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

const Modal = ({
  isOpen,
  onClose,
  labelledBy,
  label,
  overlayClassName = 'modal-overlay',
  containerClassName,
  closeOnOverlayClick = true,
  closeOnEscape = true,
  children,
}) => {
  const containerRef = useRef(null);
  // What had focus before we opened, so it can be handed back on close.
  const previouslyFocusedRef = useRef(null);

  const getFocusable = useCallback(() => {
    if (!containerRef.current) return [];
    return Array.from(containerRef.current.querySelectorAll(FOCUSABLE))
      // offsetParent is null for display:none subtrees — a hidden step of a
      // multi-step modal (e.g. the CONFIRM view while FORM is showing)
      // shouldn't capture focus.
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
  }, []);

  // Move focus into the dialog on open; restore it on close.
  useEffect(() => {
    if (!isOpen) return undefined;

    previouslyFocusedRef.current = document.activeElement;

    // Defer a tick so children (and any conditional step) have mounted.
    const raf = requestAnimationFrame(() => {
      const focusable = getFocusable();
      if (focusable.length) {
        focusable[0].focus();
      } else if (containerRef.current) {
        // No focusable child (a purely informational dialog) — focus the
        // container itself so the screen reader still lands inside it.
        containerRef.current.focus();
      }
    });

    return () => {
      cancelAnimationFrame(raf);
      const prev = previouslyFocusedRef.current;
      if (prev && typeof prev.focus === 'function' && document.contains(prev)) {
        prev.focus();
      }
    };
  }, [isOpen, getFocusable]);

  // Escape to close + Tab confinement, bound while open.
  useEffect(() => {
    if (!isOpen) return undefined;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && closeOnEscape) {
        e.stopPropagation();
        onClose?.();
        return;
      }

      if (e.key !== 'Tab') return;

      const focusable = getFocusable();
      if (!focusable.length) {
        // Nothing to move between — keep focus in the dialog rather than
        // letting Tab escape to the page behind it.
        e.preventDefault();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (e.shiftKey && (active === first || !containerRef.current?.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [isOpen, onClose, closeOnEscape, getFocusable]);

  // Background scroll lock — without it, scrolling inside a dialog that has
  // reached its end scrolls the page behind it instead.
  useEffect(() => {
    if (!isOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previousOverflow; };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className={overlayClassName}
      onClick={closeOnOverlayClick ? onClose : undefined}
    >
      <div
        ref={containerRef}
        className={containerClassName}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-label={labelledBy ? undefined : label}
        tabIndex={-1}
        // The overlay closes on click; without this a click anywhere inside
        // the card would bubble up and close it too.
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
};

export default Modal;
