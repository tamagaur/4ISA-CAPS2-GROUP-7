import React from 'react';

// One short line under a section's or chart's title saying what the reader
// learns from it ("Where changes happened", "Who carries the sales"),
// 2026-10-16. Always shown, on every page, in the same place and style. It
// is a phrase, not an explanation: longer text belongs in an InfoTip or a
// Disclosure. Dashboard.css keeps it visible when the dashboard hides its
// longer chart subtitles (SHOW_CHART_DESCRIPTIONS).
const SectionLede = ({ children, className = '' }) => (
  <p className={`section-lede${className ? ` ${className}` : ''}`}>{children}</p>
);

export default SectionLede;
