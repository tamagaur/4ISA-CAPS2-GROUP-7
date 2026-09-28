import React, { useEffect, useRef } from 'react';
import './SaveResult.css';

// Shown inside a dialog, in place of its content, right after Save: a green
// ring and check mark that draw themselves when the save worked, a red ring
// and X (with a small shake) when it didn't, plus what happened in words.
// Timing lives in utils/useSaveResult.js. Every dialog that saves uses this
// one, so success and failure read the same across the app.
const SaveResult = ({ ok, title, message }) => {
  const ref = useRef(null);

  // The button that was clicked has just been replaced by this: hold focus
  // here so it stays inside the dialog and screen readers read the result.
  useEffect(() => {
    ref.current?.focus();
  }, []);

  return (
    <div
      ref={ref}
      tabIndex={-1}
      className={`save-result ${ok ? 'is-ok' : 'is-failed'}`}
      role={ok ? 'status' : 'alert'}
    >
      <svg className="save-result-icon" viewBox="0 0 56 56" aria-hidden="true">
        <circle className="save-result-ring" cx="28" cy="28" r="25" />
        {ok ? (
          <path className="save-result-mark" d="M17 29.5l7.5 7.5L40 21.5" />
        ) : (
          <>
            <path className="save-result-mark" d="M20 20L36 36" />
            <path className="save-result-mark save-result-mark-second" d="M36 20L20 36" />
          </>
        )}
      </svg>
      <h3 className="save-result-title">{title}</h3>
      {message && <p className="save-result-message">{message}</p>}
    </div>
  );
};

export default SaveResult;
