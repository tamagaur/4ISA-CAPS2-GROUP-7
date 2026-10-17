import React from 'react';

// "Nothing to show here", in one shape on every page: what is missing, why,
// and what to do next (2026-10-16). The words come from the caller; this
// only lays them out, with ui.css's .empty-state styles.
//
// tone="error" is the same box for a request that failed (LoadError.jsx).
// An empty answer and a failed one are different things: the system worked
// and found nothing, or it could not answer at all. Only the second gets a
// Try again button. Neither ever shows a made-up 0 (CLAUDE.md hard rule 3).
// compact: a strip above the page's cards instead of a full-width block.
const EmptyState = ({
  icon: Icon, title, children, actions, tone = 'empty', compact = false, role, className = '',
}) => (
  <div
    className={['empty-state', tone === 'error' && 'is-error', compact && 'is-compact', className].filter(Boolean).join(' ')}
    role={role}
  >
    {Icon && (
      <span className="empty-state-icon" aria-hidden="true">
        <Icon size={compact ? 18 : 22} />
      </span>
    )}
    <div className="empty-state-body">
      <p className="empty-state-title">{title}</p>
      {children && <div className="empty-state-text">{children}</div>}
      {actions && <div className="empty-state-actions">{actions}</div>}
    </div>
  </div>
);

export default EmptyState;
