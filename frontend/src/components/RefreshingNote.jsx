import React from 'react';

// "Still fetching, what you're looking at is the previous answer."
//
// Shown alongside a view that has been kept on screen rather than blanked,
// so the staleness is stated instead of implied by a dimmed page. Lives in
// its own component because all three analytics pages need it and each had
// otherwise grown its own (the dashboard's pill, ABC's full-page takeover,
// SKU Forecast's bare line).
//
// role="status" rather than role="alert": a refetch is routine progress,
// not a problem, and alert interrupts a screen reader mid-sentence.
// aria-busy on the stale view itself is the caller's job — this is the
// visible half of the same message.
const RefreshingNote = ({ children }) => (
  <p className="view-refreshing" role="status">
    <span className="view-refreshing-dot" aria-hidden="true" />
    {children}
  </p>
);

export default RefreshingNote;
