import React, { useState } from 'react';
import { X } from 'lucide-react';
import Modal from './Modal';

// "View as table" — every chart's WCAG-clean twin (design pass
// 2026-09-26). A tooltip must enhance, never gate: each chart offers the
// same numbers as a plain table, so nothing on these pages is readable
// only by hovering a mark or judging a pixel. The toggle sits in the
// chart's header; the table replaces the plot, not the card.
//
// Values are the exact rows the chart plots (the caller passes its own
// already-assembled chart data), so the two views can never disagree.

// `options` (2026-10-19): the views, as [key, text] pairs, for a chart with
// more than one plot of the same rows (the forecast card's "Lines" and
// "Monthly miss") — the default is the plain Chart / Table pair.
const CHART_OR_TABLE = [['chart', 'Chart'], ['table', 'Table']];
export function ChartViewToggle({ view, onChange, label = 'Chart or table view', options = CHART_OR_TABLE }) {
  return (
    <div className="chart-view-toggle" role="group" aria-label={label}>
      {options.map(([key, text]) => (
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

// columns: [{ key, label, sub?, format?, align? }] — format(value, row)
// renders the cell; a null/undefined value is an honest em dash, never a
// 0. `sub` is a second, smaller line under the heading (the price basis,
// what an estimate is made from), so a heading stays two or three short
// lines instead of one long one (Audrey, 2026-10-16). `wrap` lets a
// column of sentences fold onto several lines; every other cell stays on
// one line, as wide as its figure. `note` makes a column of sentences (a
// stock note) show its lead in full ("Needs checking"; the start of the
// sentence when there is no lead) with "See more", which opens the whole
// note in a small dialog (Audrey, 2026-10-16; lead only since 2026-10-19):
//   note: { lead: 'Needs checking', title: (row) => 'Stock count, Feb 2026' }
export function ChartTable({ columns, rows, caption }) {
  return (
    <div className="chart-table-wrap" tabIndex={0}>
      <table className="chart-table">
        {caption && <caption className="visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={`${c.align === 'left' ? '' : 'table-num'}${c.wrap ? ' table-wrap' : ''}`} scope="col">
                {c.label}
                {c.sub && <span className="chart-table-th-sub">{c.sub}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.period ?? row.key ?? i}>
              {columns.map((c) => {
                const v = row[c.key];
                return (
                  <td key={c.key} className={`${c.align === 'left' ? '' : 'table-num'}${c.wrap ? ' table-wrap' : ''}${c.note ? ' table-note' : ''}`}>
                    {v == null ? '—'
                      : c.note ? <NoteCell text={String(v)} lead={c.note.lead} title={c.note.title ? c.note.title(row) : c.label} />
                        : c.format ? c.format(v, row) : v}
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

// The start of a note on one line, and the whole of it in a dialog.
function NoteCell({ text, lead, title }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="chart-note">
      <span className="chart-note-preview" title={text}>
        {lead ? <strong>{lead}</strong> : text}
      </span>
      <button type="button" className="chart-note-more" onClick={() => setOpen(true)}>
        See more
      </button>
      <Modal
        isOpen={open}
        onClose={() => setOpen(false)}
        label={title}
        overlayClassName="chart-note-overlay"
        containerClassName="chart-note-dialog"
      >
        <div className="chart-note-head">
          <h3 className="chart-note-title">{title}</h3>
          <button type="button" className="chart-note-close" onClick={() => setOpen(false)} aria-label="Close">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        {lead && <p className="chart-note-lead">{lead}</p>}
        <p className="chart-note-text">{text}</p>
      </Modal>
    </span>
  );
}
