// The parts every chart on the dashboard shares (2026-10-19), so the charts
// read as one family: the hover's boxes, the fade a bar or a shade wears,
// and the ringed dot a line ends in. They began as the Sales vs Inventory
// Value chart's own (Charts.jsx, .svs-callout) and moved here once the
// forecast cards, the yearly bars and the ABC ring took them up.
import React from 'react';
import '../Charts.css';
import './ChartParts.css';

// The hover: one box per series (Callout), in the series' tint — the
// period, the value large and in ink, the series' name — and lines under
// it (CalloutLine: the same period a year earlier, a count day). The bubble
// (Callouts) is bare, so the boxes float as separate cards; a note after
// them (CalloutNote) gets a plain card of its own.
export const Callouts = ({ children }) => <div className="chart-tooltip chart-callouts">{children}</div>;

export const Callout = ({ color, period = null, value, name = null, children = null }) => (
  <div className="chart-callout" style={{ '--chart-callout': color }}>
    {period && <span className="chart-callout-period">{period}</span>}
    <strong className="chart-callout-value">{value}</strong>
    {name && <span className="chart-callout-name">{name}</span>}
    {children}
  </div>
);

export const CalloutLine = ({ children }) => <span className="chart-callout-line">{children}</span>;

export const CalloutNote = ({ children }) => <p className="chart-tooltip-placeholder chart-tooltip-note">{children}</p>;

// A vertical fade in one colour, for a chart's <defs>: `from` opaque at the
// top to `to` at the bottom; `flip` turns it over, for a bar below zero
// (solid at its tip, fading up to the zero line). Every bar on the
// dashboard wears one, down to BAR_FADE_FLOOR.
export const BAR_FADE_FLOOR = 0.4;

export const Fade = ({ id, color, from = 1, to = 0, flip = false }) => (
  <linearGradient id={id} x1="0" y1={flip ? '1' : '0'} x2="0" y2={flip ? '0' : '1'}>
    <stop offset="0%" stopColor={color} stopOpacity={from} />
    <stop offset="100%" stopColor={color} stopOpacity={to} />
  </linearGradient>
);

// How a line looks is one design of its own: ui/lineDesign.jsx.
export { endDot } from './lineDesign';
