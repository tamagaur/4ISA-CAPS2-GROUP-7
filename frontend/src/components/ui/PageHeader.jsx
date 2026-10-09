// The one page header every page uses: the title (with the serif accent
// word the app has always set in Fraunces), one short subtitle, and the
// page's own actions at the right. Explanations longer than a line belong
// in a Disclosure below, not here.
import React from 'react';

const PageHeader = ({ title, accent, subtitle, actions, children }) => (
  <header className="page-header">
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
