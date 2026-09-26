import React from 'react';

// "View as table" — every chart's WCAG-clean twin (design pass
// 2026-09-26). A tooltip must enhance, never gate: each chart offers the
// same numbers as a plain table, so nothing on these pages is readable
// only by hovering a mark or judging a pixel. The toggle sits in the
// chart's header; the table replaces the plot, not the card.
//
// Values are the exact rows the chart plots (the caller passes its own
// already-assembled chart data), so the two views can never disagree.

export function ChartViewToggle({ view, onChange, label = 'Chart or table view' }) {
  return (
    <div className="chart-view-toggle" role="group" aria-label={label}>
      {[['chart', 'Chart'], ['table', 'Table']].map(([key, text]) => (
        <button
          key={key}
          type="button"
          className={view === key ? 'active' : ''}
          aria-pressed={view === key}
          onClick={() => onChange(key)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

// columns: [{ key, label, format?, align? }] — format(value, row) renders
// the cell; a null/undefined value is an honest em dash, never a 0.
export function ChartTable({ columns, rows, caption }) {
  return (
    <div className="chart-table-wrap" tabIndex={0}>
      <table className="chart-table">
        {caption && <caption className="visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.align === 'left' ? '' : 'table-num'} scope="col">{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.period ?? row.key ?? i}>
              {columns.map((c) => {
                const v = row[c.key];
                return (
                  <td key={c.key} className={c.align === 'left' ? '' : 'table-num'}>
                    {v == null ? '—' : c.format ? c.format(v, row) : v}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
