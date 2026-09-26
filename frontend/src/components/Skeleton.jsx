import React from 'react';

// Skeleton loaders — the cold-load half of the shared loading vocabulary in
// index.css ("Cold load, nothing on screen yet -> a skeleton in the shape of
// the real thing"). Dashboard and ABC each grew their own skeleton markup;
// every other page showed a bare "Loading…" line, and SKU Management's
// summary cards read 0 until the request landed — a number, not a wait.
// These blocks are the one set every page now builds its skeleton from.
//
// Pages pass their loaded view's own container classes (kpi-card,
// sku-summary-card, data-table-card, …) so each block lands at its final
// size and nothing jumps when the data replaces it.
//
// Every block is aria-hidden. A page announces its load once, through
// <LoadingStatus>, rather than a screen reader walking dozens of empty divs.

export const LoadingStatus = ({ children }) => (
  <p className="visually-hidden" role="status">{children}</p>
);

const cx = (...names) => names.filter(Boolean).join(' ');

// `variant` picks one of index.css's preset line sizes (title / value /
// subtext / row); pass width/height instead for a one-off size.
export const SkeletonLine = ({ variant, width, height, className }) => (
  <div
    className={cx('skeleton-line', variant && `skeleton-line-${variant}`, className)}
    style={width || height ? { width, height } : undefined}
  />
);

// KPI and summary cards: label, big number, caption — the shape of every
// stat card in the app.
export const SkeletonStatCards = ({ count = 4, cardClassName = 'skeleton-panel' }) => (
  <>
    {Array.from({ length: count }, (_, k) => (
      <div className={cx(cardClassName, 'skeleton-card')} key={k} aria-hidden="true">
        <SkeletonLine variant="title" />
        <SkeletonLine variant="value" />
        <SkeletonLine variant="subtext" />
      </div>
    ))}
  </>
);

// Chart silhouettes. The shapes are fixed, not random: a skeleton that
// reshuffles on every render reads as data changing underneath the user.
const BAR_HEIGHTS = [42, 64, 55, 78, 60, 86, 48, 70, 58, 74, 52, 66];
const HBAR_WIDTHS = [88, 64, 76, 52, 70];
const LINE_POINTS = '0,30 9,24 18,27 27,18 36,21 45,14 54,19 63,11 72,15 81,9 90,13 100,7';
const LIST_WIDTHS = [78, 62, 84, 56, 70, 66];

// variant: 'line' (trends, forecasts), 'bars' (Pareto, monthly columns),
// 'hbars' (per-tier or per-policy bars), 'donut' (share rings), 'list'
// (ranked rows inside a card), 'block' (anything else).
// `height` is a minimum: in a flex card the silhouette grows with its row,
// the same way the real .chart-container does.
export const SkeletonChart = ({ variant = 'line', height = 200, rows = 3, className }) => (
  <div
    className={cx('skeleton-chart', `skeleton-chart-${variant}`, className)}
    style={{ minHeight: height }}
    aria-hidden="true"
  >
    {variant === 'line' && (
      <svg className="skeleton-chart-svg" viewBox="0 0 100 40" preserveAspectRatio="none">
        <polygon className="skeleton-chart-area" points={`${LINE_POINTS} 100,40 0,40`} />
        <polyline className="skeleton-chart-stroke" points={LINE_POINTS} vectorEffect="non-scaling-stroke" />
      </svg>
    )}
    {variant === 'bars' && (
      <div className="skeleton-bars">
        {BAR_HEIGHTS.map((h, k) => <span className="skeleton-bar" style={{ height: `${h}%` }} key={k} />)}
      </div>
    )}
    {variant === 'hbars' && (
      <div className="skeleton-hbars">
        {Array.from({ length: rows }, (_, k) => (
          <div className="skeleton-hbar-row" key={k}>
            <span className="skeleton-hbar-label" />
            <span className="skeleton-hbar" style={{ width: `${HBAR_WIDTHS[k % HBAR_WIDTHS.length]}%` }} />
          </div>
        ))}
      </div>
    )}
    {variant === 'donut' && (
      <div className="skeleton-donut-wrap">
        <span className="skeleton-donut" />
        <div className="skeleton-donut-legend">
          {[70, 55, 62].map((w, k) => <SkeletonLine width={`${w}%`} height="0.75rem" key={k} />)}
        </div>
      </div>
    )}
    {variant === 'list' && (
      <div className="skeleton-list">
        {LIST_WIDTHS.slice(0, Math.max(rows, 1) * 2).map((w, k) => (
          <SkeletonLine width={`${w}%`} height="0.8rem" key={k} />
        ))}
      </div>
    )}
  </div>
);

// A titled card around a chart silhouette, in the loaded card's own class.
export const SkeletonChartCard = ({ className = 'skeleton-panel', variant, height, rows, subtitle = true }) => (
  <div className={cx(className, 'skeleton-card')} aria-hidden="true">
    <SkeletonLine variant="title" />
    {subtitle && <SkeletonLine width="62%" height="0.7rem" />}
    <SkeletonChart variant={variant} height={height} rows={rows} />
  </div>
);

// Cell widths cycle through this list so rows vary like real data does,
// but identically on every render.
const CELL_WIDTHS = [72, 88, 60, 94, 54, 80, 66, 90];
const cellWidth = (r, c) => `${CELL_WIDTHS[(r * 3 + c) % CELL_WIDTHS.length]}%`;

// A table body as a grid of lines, for pages whose real <table> only
// renders once rows exist. Drop it inside the page's .data-table-card.
export const SkeletonTable = ({ rows = 8, columns = 5 }) => (
  <div className="skeleton-table" style={{ '--skeleton-cols': columns }} aria-hidden="true">
    <div className="skeleton-table-row skeleton-table-head">
      {Array.from({ length: columns }, (_, c) => (
        <div className="skeleton-table-cell" key={c}><SkeletonLine width="55%" height="0.6rem" /></div>
      ))}
    </div>
    {Array.from({ length: rows }, (_, r) => (
      <div className="skeleton-table-row" key={r}>
        {Array.from({ length: columns }, (_, c) => (
          <div className="skeleton-table-cell" key={c}><SkeletonLine width={cellWidth(r, c)} height="0.75rem" /></div>
        ))}
      </div>
    ))}
  </div>
);

// Skeleton <tr>s for a table whose header is already on screen (the real
// <thead> stays; only the body waits).
export const SkeletonTableRows = ({ rows = 5, columns }) => (
  <>
    {Array.from({ length: rows }, (_, r) => (
      <tr className="skeleton-tr" key={r} aria-hidden="true">
        {Array.from({ length: columns }, (_, c) => (
          <td key={c}><SkeletonLine width={cellWidth(r, c)} height="0.75rem" /></td>
        ))}
      </tr>
    ))}
  </>
);

// Route-level fallback, shown while a page's code chunk downloads — before
// the page itself exists to draw its own skeleton. Generic on purpose: it
// only has to hold the space the page is about to fill.
export const PageSkeleton = () => (
  <div className="skeleton-page" aria-hidden="true">
    <div className="skeleton-page-header">
      <SkeletonLine width="28%" height="1.6rem" />
      <SkeletonLine width="44%" height="0.8rem" />
    </div>
    <div className="skeleton-stat-strip">
      <SkeletonStatCards count={4} />
    </div>
    <SkeletonChartCard variant="line" height={220} />
    <div className="skeleton-panel skeleton-panel-flush">
      <SkeletonTable rows={5} columns={5} />
    </div>
  </div>
);
