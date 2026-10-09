// "How this works": methodology, formulas, assumptions and diagnostics
// stay on the page, folded under one line, so the first thing a reader
// sees is the answer. A native <details>, so it opens from the keyboard and
// a screen reader announces its state without extra wiring.
import React from 'react';
import { ChevronRight } from 'lucide-react';

const Disclosure = ({ title, hint, children, defaultOpen = false, flat = false, className = '' }) => (
  <details className={`disclosure${flat ? ' is-flat' : ''}${className ? ` ${className}` : ''}`} open={defaultOpen || undefined}>
    <summary>
      <ChevronRight size={15} className="disclosure-chevron" aria-hidden="true" />
      <span>{title}</span>
      {hint && <span className="disclosure-hint">{hint}</span>}
    </summary>
    <div className="disclosure-body">{children}</div>
  </details>
);

export default Disclosure;
