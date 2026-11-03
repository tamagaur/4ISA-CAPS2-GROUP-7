// The one page header every page uses: the title (with the serif accent
// word the app has always set in Fraunces), one short subtitle, and the
// page's own actions at the right. Explanations longer than a line belong
// in a Disclosure below, not here.
import React from 'react';

// `className` lets one page restyle its own header (the dashboard's,
// Dashboard.css .dash-page-header) without touching the others. `icon` is an
// optional tile before the title (the Reorder page's); without it nothing
// renders, so every other page's header is unchanged.
const PageHeader = ({ title, accent, subtitle, actions, children, className = '', icon }) => (
  <header className={`page-header${className ? ` ${className}` : ''}`}>
    {icon && <span className="page-header-icon" aria-hidden="true">{icon}</span>}
    <div className="page-header-text">
      <h2 className="page-header-title">
        {title}
        {accent && <> <span className="page-title-accent">{accent}</span></>}
      </h2>
      {subtitle && <p className="page-header-subtitle">{subtitle}</p>}
      {children}
    </div>
    {actions && <div className="page-header-actions">{actions}</div>}
  </header>
);

export default PageHeader;
