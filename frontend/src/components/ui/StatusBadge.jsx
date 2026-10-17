// One badge for every status in the app. `tone` picks the soft tint
// (critical, warning, success, neutral, info, plum, teal, brand); the words
// always carry the meaning, so colour is never the only signal.
import React from 'react';

// The app's statuses mapped to tones, so a status reads the same on every page.
export const STATUS_TONE = {
  CRITICAL: 'critical',
  URGENT: 'warning',
  PLANNED: 'neutral',
  'NO DATA': 'neutral',
  'IN STOCK': 'success',
  LOW: 'warning',
  ACCEPTED: 'success',
  DISMISSED: 'neutral',
  PENDING: 'info',
  GROWING: 'success',
  DECLINING: 'warning',
};

const StatusBadge = ({ tone = 'neutral', dot = false, title, children, className = '' }) => (
  <span className={`badge badge-${tone}${dot ? ' badge-dot' : ''}${className ? ` ${className}` : ''}`} title={title}>
    {children}
  </span>
);

// An ABC class letter: A strongest, then B, then C.
export const ClassBadge = ({ tier, faded = false, title }) => {
  if (!tier) return <span className="cell-empty">—</span>;
  const t = String(tier).toUpperCase();
  return (
    <span
      className={`badge badge-class badge-class-${t.toLowerCase()}`}
      style={faded ? { opacity: 0.55 } : undefined}
      title={title || `Class ${t}`}
    >
      {t}
    </span>
  );
};

export default StatusBadge;
