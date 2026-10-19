// A small "?" button that explains a term: opens on hover, on tap and on
// Enter/Space, closes on Escape, a second tap, or leaving it. Replaces native
// `title` tooltips, which phones and keyboards can't reach, for definitions
// a reader needs (cover, target stock, WAPE...).
//
// A long note (more than CARD_CHARS of text; 2026-10-19) does not go in the
// bubble, which turned a card's "?" into a wall of white-on-navy text. It
// opens, straight away on hover, as a card of its own beside the "?": the
// page's surface and type, a title, its lines as paragraphs, a close
// button. Hover alone keeps it while the pointer is on the "?" or the
// card; a click, a tap or Enter pins it until the close button, Escape or
// a click outside. A short note keeps the bubble, as before.
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
import { HelpCircle, X } from 'lucide-react';
import './InfoTip.css';

const GAP = 6;
const MARGIN = 8;
// A note with more text than this opens as a card, not a bubble: about
// three lines of the bubble's width.
const CARD_CHARS = 140;

// The plain text of a note, for its length: strings, numbers, arrays,
// fragments and elements with children. A component's own render is not
// seen, so a caller passes its lines as elements, not as a component.
const textOf = (node) => {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(' ');
  if (React.isValidElement(node)) return textOf(node.props.children);
  return '';
};

const InfoTip = ({ label, children, size = 13, className = '', trigger = null, triggerClassName = '' }) => {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  // Opened by a click, a tap or a key, or read (clicked or scrolled) once
  // open: stays until closed. Opened by hover alone: goes with the pointer.
  const pinnedRef = useRef(false);
  const id = useId();
  const btnRef = useRef(null);
  const popRef = useRef(null);
  const long = textOf(children).trim().length > CARD_CHARS;

  const close = useCallback(() => {
    pinnedRef.current = false;
    setOpen(false);
  }, []);

  // The card sits flush with the button (its wrapper's padding is the gap,
  // see InfoTip.css), so the pointer crosses from one to the other without
  // leaving either; the bubble keeps a real gap.
  const place = useCallback(() => {
    const btn = btnRef.current?.getBoundingClientRect();
    const pop = popRef.current?.getBoundingClientRect();
    if (!btn || !pop) return;
    const gap = long ? 0 : GAP;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = btn.left + btn.width / 2 - pop.width / 2;
    left = Math.max(MARGIN, Math.min(left, vw - pop.width - MARGIN));
    let top = btn.bottom + gap;
    if (top + pop.height > vh - MARGIN) top = Math.max(MARGIN, btn.top - pop.height - gap);
    setPos({ top, left });
  }, [long]);

  useLayoutEffect(() => {
    if (open) place();
    else setPos(null);
  }, [open, place]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const onOutside = (e) => {
      if (!btnRef.current?.contains(e.target) && !popRef.current?.contains(e.target)) close();
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
  }, [open, place, close]);

  // Mouse hover opens it and, unless it is pinned, closes it; touch and pen
  // rely on the tap. React's enter/leave events follow the React tree,
  // portal and all, so the pointer on the card still counts as inside.
  const hover = (next) => (e) => {
    if (e.pointerType !== 'mouse') return;
    if (next) setOpen(true);
    else if (!pinnedRef.current) setOpen(false);
  };
  const onClick = (e) => {
    e.stopPropagation();
    if (open && pinnedRef.current) {
      close();
    } else {
      pinnedRef.current = true;
      setOpen(true);
    }
  };
  const pin = () => { pinnedRef.current = true; };
  const style = pos ? { top: pos.top, left: pos.left } : { visibility: 'hidden' };

  return (
    <span className={`info-tip ${className}`} onPointerEnter={hover(true)} onPointerLeave={hover(false)}>
      <button
        ref={btnRef}
        type="button"
        className={trigger ? `info-tip-trigger ${triggerClassName}` : 'info-tip-btn'}
        // A trigger's own text names it (a number, a chip); the tip describes it.
        aria-label={trigger ? undefined : label}
        aria-expanded={open}
        aria-haspopup={long ? 'dialog' : undefined}
        aria-describedby={long ? `${id}-body` : id}
        onClick={onClick}
        onBlur={() => { if (!pinnedRef.current) setOpen(false); }}
      >
        {trigger ?? <HelpCircle size={size} aria-hidden="true" />}
      </button>
      {createPortal(
        long ? (
          // A click or a scroll in the card pins it; a click in it stops
          // here, not at whatever row or card the "?" sits in.
          <span
            ref={popRef}
            id={id}
            role="dialog"
            aria-label={label}
            className="info-tip-pop is-card"
            hidden={!open}
            style={style}
            onPointerDown={pin}
            onClick={(e) => e.stopPropagation()}
          >
            <span className="info-tip-card">
              <span className="info-tip-card-head">
                <span className="info-tip-card-title">{label}</span>
                <button type="button" className="info-tip-card-close" onClick={close} aria-label="Close">
                  <X size={16} aria-hidden="true" />
                </button>
              </span>
              <span id={`${id}-body`} className="info-tip-card-body">{children}</span>
            </span>
          </span>
        ) : (
          <span ref={popRef} id={id} role="tooltip" className="info-tip-pop" hidden={!open} style={style}>
            {children}
          </span>
        ),
        document.body,
      )}
    </span>
  );
};

export default InfoTip;
