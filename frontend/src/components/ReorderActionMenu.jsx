// A small dropdown menu for the Reorder page: a row's secondary actions and the
// table's Filter button. It renders through a portal (as InfoTip does), because
// the table's scroll area would clip anything floating inside it, and it follows
// the WAI-ARIA menu pattern: arrow keys, Home and End move, Escape closes and
// returns focus to the button, Tab closes.
//
// items: [{ key, label, onSelect, disabled, checked }]. An item with `checked`
// (true or false) is a menuitemradio: the Filter menu's current choice.
import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const GAP = 4;
const MARGIN = 8;

const ReorderActionMenu = ({ label, items, buttonClassName = '', buttonContent }) => {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const buttonRef = useRef(null);
  const menuRef = useRef(null);

  const close = useCallback((returnFocus = true) => {
    setOpen(false);
    setPos(null);
    if (returnFocus) buttonRef.current?.focus({ preventScroll: true });
  }, []);

  // Under the button, right edges aligned; above it when there's no room below.
  useLayoutEffect(() => {
    if (!open) return;
    const button = buttonRef.current?.getBoundingClientRect();
    const menu = menuRef.current?.getBoundingClientRect();
    if (!button || !menu) return;
    const left = Math.max(MARGIN, Math.min(button.right - menu.width, window.innerWidth - menu.width - MARGIN));
    const below = button.bottom + GAP;
    const top = below + menu.height > window.innerHeight - MARGIN
      ? Math.max(MARGIN, button.top - menu.height - GAP)
      : below;
    setPos({ top, left });
  }, [open]);

  // Focus moves in once the menu is placed.
  useEffect(() => {
    if (!open || !pos) return;
    const first = menuRef.current?.querySelector('[aria-checked="true"]:not([disabled])')
      || menuRef.current?.querySelector('[role^="menuitem"]:not([disabled])');
    first?.focus({ preventScroll: true });
  }, [open, pos]);

  // A click elsewhere closes it without taking focus back; so does scrolling or
  // resizing, which would leave it floating away from its button.
  useEffect(() => {
    if (!open) return undefined;
    const onOutside = (e) => {
      if (!buttonRef.current?.contains(e.target) && !menuRef.current?.contains(e.target)) close(false);
    };
    const onMove = (e) => {
      if (!menuRef.current?.contains(e.target)) close(false);
    };
    const onResize = () => close(false);
    document.addEventListener('pointerdown', onOutside);
    window.addEventListener('scroll', onMove, true);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('pointerdown', onOutside);
      window.removeEventListener('scroll', onMove, true);
      window.removeEventListener('resize', onResize);
    };
  }, [open, close]);

  const onMenuKeyDown = (e) => {
    const all = [...(menuRef.current?.querySelectorAll('[role^="menuitem"]:not([disabled])') || [])];
    const at = all.indexOf(document.activeElement);
    const go = (i) => { e.preventDefault(); all[(i + all.length) % all.length]?.focus({ preventScroll: true }); };
    if (e.key === 'ArrowDown') go(at + 1);
    else if (e.key === 'ArrowUp') go(at - 1);
    else if (e.key === 'Home') go(0);
    else if (e.key === 'End') go(all.length - 1);
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'Tab') close(false);
  };

  // Down or Up on the closed button opens it, as Enter and Space already do.
  const onButtonKeyDown = (e) => {
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !open) {
      e.preventDefault();
      setOpen(true);
    }
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={buttonClassName}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close(false) : setOpen(true))}
        onKeyDown={onButtonKeyDown}
      >
        {buttonContent}
      </button>
      {open && createPortal(
        <div
          ref={menuRef}
          className="reorder-menu"
          role="menu"
          aria-label={label}
          style={pos ? { top: pos.top, left: pos.left } : { visibility: 'hidden' }}
          onKeyDown={onMenuKeyDown}
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role={item.checked === undefined ? 'menuitem' : 'menuitemradio'}
              aria-checked={item.checked}
              className="reorder-menu-item"
              disabled={item.disabled}
              tabIndex={-1}
              onClick={() => {
                // Focus goes back first, so a dialog opened by the item hands it
                // back to this button when it closes.
                close();
                item.onSelect();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
};

export default ReorderActionMenu;
