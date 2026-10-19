// A small "?" button that explains a term: opens on hover, on tap and on
// Enter/Space, closes on Escape, a second tap, or leaving it. Replaces native
// `title` tooltips, which phones and keyboards can't reach, for definitions
// a reader needs (cover, target stock, WAPE...).
//
// The text is always in the DOM (hidden while closed) and linked with
// aria-describedby, so a screen reader reads it on focus without opening.
// The popover is portalled to <body> and placed (position: fixed) from the
// button's rectangle, so neither a table's scroll container nor an animated
// card (a transform makes it the containing block) can clip or squeeze it.
//
// `trigger` (optional, 2026-10-18): what the button shows instead of the "?"
// icon — a number or a chip that opens its own explanation (the Dashboard's
// Summary cards). `triggerClassName` styles that button. Without `trigger`
// nothing changes.
import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { HelpCircle } from 'lucide-react';
import './InfoTip.css';

const GAP = 6;
const MARGIN = 8;

const InfoTip = ({ label, children, size = 13, className = '', trigger = null, triggerClassName = '' }) => {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const id = useId();
  const btnRef = useRef(null);
  const popRef = useRef(null);

  const place = useCallback(() => {
    const btn = btnRef.current?.getBoundingClientRect();
    const pop = popRef.current?.getBoundingClientRect();
    if (!btn || !pop) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = btn.left + btn.width / 2 - pop.width / 2;
    left = Math.max(MARGIN, Math.min(left, vw - pop.width - MARGIN));
    let top = btn.bottom + GAP;
    if (top + pop.height > vh - MARGIN) top = Math.max(MARGIN, btn.top - pop.height - GAP);
    setPos({ top, left });
  }, []);

  useLayoutEffect(() => {
    if (open) place();
    else setPos(null);
  }, [open, place]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    const onOutside = (e) => {
      if (!btnRef.current?.contains(e.target) && !popRef.current?.contains(e.target)) setOpen(false);
    };
    // Follows its button while the page or a table scrolls.
    const onMove = () => place();
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onOutside);
    window.addEventListener('scroll', onMove, true);
    window.addEventListener('resize', onMove);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onOutside);
      window.removeEventListener('scroll', onMove, true);
      window.removeEventListener('resize', onMove);
    };
  }, [open, place]);

  // Mouse hover opens and closes it; touch and pen rely on the tap.
  const hover = (next) => (e) => { if (e.pointerType === 'mouse') setOpen(next); };

  return (
    <span className={`info-tip ${className}`} onPointerEnter={hover(true)} onPointerLeave={hover(false)}>
      <button
        ref={btnRef}
        type="button"
        className={trigger ? `info-tip-trigger ${triggerClassName}` : 'info-tip-btn'}
        // A trigger's own text names it (a number, a chip); the tip describes it.
        aria-label={trigger ? undefined : label}
        aria-expanded={open}
        aria-describedby={id}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        onBlur={() => setOpen(false)}
      >
        {trigger ?? <HelpCircle size={size} aria-hidden="true" />}
      </button>
      {createPortal(
        <span
          ref={popRef}
          id={id}
          role="tooltip"
          className="info-tip-pop"
          hidden={!open}
          style={pos ? { top: pos.top, left: pos.left } : { visibility: 'hidden' }}
        >
          {children}
        </span>,
        document.body,
      )}
    </span>
  );
};

export default InfoTip;
