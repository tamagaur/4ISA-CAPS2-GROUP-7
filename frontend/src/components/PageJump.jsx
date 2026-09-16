import React, { useState, useEffect } from 'react';

// "Go to page" input, shared by every paginated table (SKU Management, ABC
// Classification, Audit Log). Deliberately NOT backed by localStorage/
// sessionStorage/URL state: each page's `currentPage` is plain useState(1),
// so navigating away and back (a real unmount/remount, not a tab switch
// within the app) always starts back at page 1 — typing a page number here
// must not change that.
const PageJump = ({ currentPage, totalPages, onGo, idPrefix }) => {
  const [value, setValue] = useState('');

  // Clear the typed value once it's taken effect — covers a valid jump,
  // and Prev/Next/First/Last moving the page from elsewhere.
  useEffect(() => {
    setValue('');
  }, [currentPage]);

  if (totalPages <= 1) return null;

  const clamp = (n) => Math.min(Math.max(n, 1), totalPages);

  // Clamped on every keystroke, not just on submit: the box itself should
  // never be able to hold (or briefly flash) a number below 1 or above the
  // last page, not even for a moment before Go is pressed.
  const handleChange = (e) => {
    const raw = e.target.value;
    if (raw === '') {
      setValue('');
      return;
    }
    const n = parseInt(raw, 10);
    if (Number.isNaN(n)) return;
    setValue(String(clamp(n)));
  };

  const commit = () => {
    const n = parseInt(value, 10);
    if (!value.trim() || Number.isNaN(n)) return;
    onGo(clamp(n));
  };

  const inputId = `${idPrefix}-page-jump-input`;

  return (
    <form
      className="page-jump"
      // The input's min/max exist for the spinner/keyboard-step affordance,
      // but the browser also uses them for constraint validation — without
      // noValidate, typing a number outside [1, totalPages] silently blocks
      // this onSubmit from ever firing, so the clamp in commit() below
      // never runs and the "Go" button/Enter key appear to do nothing.
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        commit();
      }}
    >
      <label className="page-jump-label" htmlFor={inputId}>Go to page</label>
      <input
        id={inputId}
        type="number"
        min={1}
        max={totalPages}
        inputMode="numeric"
        className="page-jump-input"
        value={value}
        placeholder={String(currentPage)}
        onChange={handleChange}
        aria-label={`Go to page, 1 through ${totalPages}`}
      />
      <button type="submit" className="page-jump-btn" disabled={!value.trim()}>
        Go
      </button>
    </form>
  );
};

export default PageJump;
