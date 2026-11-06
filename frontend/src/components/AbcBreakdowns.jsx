import React, { useEffect, useMemo, useState } from 'react';
import { ArrowUp } from 'lucide-react';
import { getPareto } from '../api/analytics';
import { labelForPrincipal } from '../principals';
import { formatMonth } from '../utils/formatDate';
import { formatCompactPesos } from '../utils/formatters';
import { ChartTable, ChartViewToggle } from './ChartTable';
import { LoadingStatus, SkeletonChart } from './Skeleton';
import BasisTag from './BasisTag';
import SectionHeading from './ui/SectionHeading';
import './AbcBreakdowns.css';

// The card under the ABC stock check, for the analytical-mapping question
// the product table can't answer on its own:
//   ParetoCard    D1 — which brands and product categories drive the
//                 majority of sales (GET /pareto, same measure and 80/95%
//                 cutoffs as the product-level ABC; the cutoffs are
//                 explained in the page's "About these numbers").
//
// Simplified 2026-11-06: plain bars, the top 8 plus one "Others" bar, no
// axes, gridlines or cumulative line. Horizontal rows since the second pass
// that day (name | bar | share), so every name can be read. The brands that
// make up the first 80% of sales (Class A of GET /pareto) are the plum bars,
// closed by one thin line labelled with their summed share.

// Emphasis, not a colour per class: the Class A bars keep the plum, the rest
// recede into grey and "Others" into a lighter grey (palette validator,
// 2026-09-26: the lighter grey still clears 2:1 on white).
// A darker plum than Class A's #76295E (2026-11-06), so the top brands never
// read as the stock check's red "Could run out".
const TOP_COLOR = '#4F1A41';
const REST_COLOR = '#8E99A9';
const OTHERS_COLOR = '#C9D0DA';
// The chart's top N brands / categories; the rest are one "Others" bar.
const TOP_N = 8;
const titleCase = (name) => (name || '').toLowerCase().replace(/(^|[\s/&-])\S/g, (c) => c.toUpperCase());

// The Pareto's period as the Technical Adviser reads periods: one month
// ("Feb 2026") or a range ("Mar 2025 – Feb 2026"), from GET /pareto's own
// window, never the months the toggle asked for (a window is cut at the
// principal's latest data month).
const paretoPeriod = (section, months) =>
  months === 1 || !section?.window_start || section.window_start === section.period
    ? formatMonth(section?.period)
    : `${formatMonth(section.window_start)} – ${formatMonth(section.period)}`;

// The window toggle, per principal (2026-11-06): Unilever opens on 12 months
// and lists it first; Del Monte (and All) keep one month first.
const windowOptionsFor = (principal) => (principal === 'unilever'
  ? [[12, '12 months'], [1, 'Month']]
  : [[1, 'Month'], [12, '12 months']]);
const defaultMonthsFor = (principal) => (principal === 'unilever' ? 12 : 1);

// Months from one 'YYYY-MM' period to another, both counted.
const monthSpan = (start, end) => {
  const [ys, ms] = String(start).split('-').map(Number);
  const [ye, me] = String(end).split('-').map(Number);
  return (ye - ys) * 12 + (me - ms) + 1;
};

// onSelectBrand(name): a brand bar's click; the page filters its product
// table to that brand. Categories and "Others" are not clickable.
// headingInfo: the section's "?" text (the page's own grouping note).
export const ParetoCard = ({ principal, period, onSelectBrand = null, headingInfo = null }) => {
  const [grain, setGrain] = useState(principal === 'delmonte' ? 'category' : 'brand');
  const [months, setMonths] = useState(() => defaultMonthsFor(principal));
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  const [sectionIndex, setSectionIndex] = useState(0);
  const [view, setView] = useState('chart');

  // Del Monte has no brand at all — land on the category view for it. A new
  // principal also takes its own default window.
  useEffect(() => {
    if (principal === 'delmonte') setGrain('category');
    setMonths(defaultMonthsFor(principal));
  }, [principal]);

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, status: 'loading', error: null }));
    getPareto({ grain, principal, period, months })
      .then((data) => { if (!cancelled) setState({ status: 'loaded', data, error: null }); })
      .catch((err) => { if (!cancelled) setState({ status: 'error', data: null, error: err.message }); });
    return () => { cancelled = true; };
  }, [grain, principal, period, months]);

  const sections = state.data?.principals || [];
  const section = sections[Math.min(sectionIndex, Math.max(sections.length - 1, 0))];
  const rows = useMemo(
    () => (section?.rows || []).map((r) => ({ ...r, sharePct: r.revenue_share * 100, cumPct: r.cumulative_share * 100 })),
    [section]
  );
  // The top TOP_N plus one "Others (N)" bar with their summed share; the
  // headline and the table view use every row.
  const chartRows = useMemo(() => {
    if (rows.length <= TOP_N + 1) return rows;
    const rest = rows.slice(TOP_N);
    return [
      ...rows.slice(0, TOP_N),
      {
        name: `Others (${rest.length.toLocaleString()})`,
        isOthers: true,
        othersCount: rest.length,
        revenue: rest.reduce((sum, r) => sum + (r.revenue || 0), 0),
        products: rest.reduce((sum, r) => sum + (r.products || 0), 0),
        sharePct: rest.reduce((sum, r) => sum + r.sharePct, 0),
      },
    ];
  }, [rows]);
  const topCount = rows.filter((r) => r.tier === 'A').length;
  // Read off the running total at Class A's last row (rounded once), not
  // summed from per-row shares each rounded to 4 dp — the same fix as GET
  // /abc's class totals, where the sum read Class B 14.9% for 15.0%.
  const aShare = rows.filter((r) => r.tier === 'A').reduce((top, r) => Math.max(top, r.cumulative_share), 0);
  // The bracket spans the maroon bars on the chart: Class A within the top 8.
  const bracketCount = chartRows.filter((r) => !r.isOthers && r.tier === 'A').length;
  const bracketPct = bracketCount === topCount
    ? aShare * 100
    : chartRows.filter((r) => !r.isOthers && r.tier === 'A').reduce((sum, r) => sum + r.sharePct, 0);
  const tallest = Math.max(1, ...chartRows.map((r) => r.sharePct));
  const periodText = section?.period ? paretoPeriod(section, months) : null;
  const grainLabel = grain === 'brand' ? 'Brand' : 'Category';
  const grainPlural = grain === 'brand' ? 'brands' : 'categories';
  // What `products` counts: Unilever's sales are per SKU; Del Monte's are
  // per sell-out category (DEC-03), one product row each.
  const productUnit = (n) => (section?.principal === 'delmonte'
    ? (n === 1 ? 'category' : 'categories')
    : (n === 1 ? 'product' : 'products'));
  const clickable = (r) => grain === 'brand' && !r.isOthers && typeof onSelectBrand === 'function';
  const barTitle = (r) => `${r.isOthers ? `${r.othersCount.toLocaleString()} more ${grainPlural}, each smaller` : titleCase(r.name)}: `
    + `${r.sharePct.toFixed(1)}% of sales (${formatCompactPesos(r.revenue)}) in ${periodText} · `
    + `${(r.products || 0).toLocaleString()} ${productUnit(r.products)}`;

  // The section's period tag: the window GET /pareto answered for, never the
  // months asked ("12 months to Feb 2026", or one month). Grey with a pin:
  // it follows this card's own window and the month picked on the page, not
  // the date filter.
  const windowTag = !section?.period ? null
    : months === 1 || !section.window_start || section.window_start === section.period
      ? formatMonth(section.period)
      : `${monthSpan(section.window_start, section.period)} months to ${formatMonth(section.period)}`;

  // A Dashboard section (2026-11-06): the question the card's subtitle used
  // to ask, above the card, then the card with its title and controls.
  return (
    <section className="ui-section abcb-section" aria-labelledby="abcb-pareto-title">
    <SectionHeading
      id="abcb-pareto-title"
      info={headingInfo}
      infoLabel="How brands and categories are grouped"
      tags={windowTag ? <BasisTag label={windowTag} follows={false} /> : null}
    >
      Which {grainPlural} bring in <span className="title-accent">most of the sales</span>?
    </SectionHeading>
    <div className="abcb-card abcb-pareto card-accent-top">
      <div className="abcb-card-header">
        <div>
          <h4 className="section-card-title">Sales by <span className="title-accent">{grain}</span></h4>
        </div>
        <div className="abcb-toggles">
          <div className="abcb-toggle" role="group" aria-label="Group by">
            {['brand', 'category'].map((g) => (
              <button key={g} className={grain === g ? 'active' : ''} onClick={() => setGrain(g)} aria-pressed={grain === g}>
                {g === 'brand' ? 'Brand' : 'Category'}
              </button>
            ))}
          </div>
          <div className="abcb-toggle" role="group" aria-label="Window">
            {windowOptionsFor(principal).map(([m, label]) => (
              <button key={m} className={months === m ? 'active' : ''} onClick={() => setMonths(m)} aria-pressed={months === m}>
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {sections.length > 1 && (
        <div className="abcb-tabs" role="tablist" aria-label="Principal">
          {sections.map((s, i) => (
            <button key={s.principal} role="tab" aria-selected={i === sectionIndex} className={i === sectionIndex ? 'active' : ''} onClick={() => setSectionIndex(i)}>
              {labelForPrincipal(s.principal)}
            </button>
          ))}
        </div>
      )}

      {state.status === 'loading' && !state.data && (
        <>
          <LoadingStatus>Loading the brands…</LoadingStatus>
          <SkeletonChart variant="bars" height={200} />
        </>
      )}
      {state.status === 'error' && <p className="abcb-note" role="alert">Could not load the Pareto: {state.error}</p>}
      {section?.blocked_reason && <p className="abcb-note">{section.blocked_reason}</p>}

      {rows.length > 0 && (
        <>
          <div className="abcb-headline-row">
            <p className="abcb-headline">
              <strong>{topCount} of {rows.length}</strong> {grainPlural} bring in{' '}
              <strong>{(aShare * 100).toFixed(0)}%</strong> of {labelForPrincipal(section.principal)} sales.
              {/* The period is the section's tag (2026-11-06), not repeated here. */}
            </p>
            <ChartViewToggle view={view} onChange={setView} label="Pareto: chart or table" />
          </div>
          {view === 'table' ? (
            <ChartTable
              caption={`Share of sales by ${grain}, ${periodText}`}
              columns={[
                { key: 'name', label: grainLabel, format: (v) => titleCase(v), align: 'left' },
                { key: 'tier', label: 'Class', align: 'left' },
                { key: 'revenue', label: 'Sales (₱)', format: (v) => formatCompactPesos(v) },
                { key: 'sharePct', label: 'Share of sales (%)', format: (v) => `${v.toFixed(1)}%` },
                { key: 'cumPct', label: 'Cumulative share (%)', format: (v) => `${v.toFixed(1)}%` },
                { key: 'products', label: section.principal === 'delmonte' ? 'Categories' : 'Products' },
              ]}
              rows={rows.map((r) => ({ ...r, key: r.name }))}
            />
          ) : (
            <>
              {/* One row per bar (2026-11-06, horizontal, so every name can
                  be read): name | bar | share. Lengths on one linear scale
                  from one baseline, the largest share filling the bar
                  column. The top group's plum rows first, then a thin line
                  with their combined share, then the grey rows and the
                  hatched "Others", which is a group, not a brand. */}
              <div className="abcb-rows" role="list" aria-label={`Share of sales by ${grain}, ${periodText}`}>
                {chartRows.map((r, i) => {
                  const isTop = !r.isOthers && r.tier === 'A';
                  const color = r.isOthers ? OTHERS_COLOR : isTop ? TOP_COLOR : REST_COLOR;
                  const name = r.isOthers ? r.name : titleCase(r.name);
                  const body = (
                    <>
                      <span className={`abcb-row-name${isTop ? ' is-top' : ''}${r.isOthers ? ' is-others' : ''}`} title={name}>{name}</span>
                      {/* The share right after its bar, so a short bar is
                          never far from its number; whole numbers, as on the
                          cards. --abcb-w is the bar's length on the scale. */}
                      <span className="abcb-row-track">
                        <span
                          className={`abcb-row-bar chart-grow-x${r.isOthers ? ' is-others' : ''}`}
                          style={{ '--abcb-w': r.sharePct / tallest, '--abcb-bar': color }}
                        />
                        <span className="abcb-row-value">{Math.round(r.sharePct)}%</span>
                      </span>
                    </>
                  );
                  // The line under the top group's last row (not after the
                  // last row of the chart).
                  const cutAfter = bracketCount > 0 && i === bracketCount - 1 && i < chartRows.length - 1;
                  return (
                    <React.Fragment key={r.name}>
                      <div className="abcb-row" role="listitem">
                        {clickable(r) ? (
                          <button
                            type="button"
                            className="abcb-row-btn"
                            onClick={() => onSelectBrand(r.name)}
                            title={barTitle(r)}
                            aria-label={`${barTitle(r)}. Show its products below.`}
                          >
                            {body}
                          </button>
                        ) : (
                          <div className="abcb-row-btn is-static" title={barTitle(r)} aria-label={barTitle(r)}>{body}</div>
                        )}
                      </div>
                      {cutAfter && (
                        <div className="abcb-cut" aria-hidden="true">
                          <span className="abcb-cut-label">
                            <ArrowUp size={12} aria-hidden="true" /> {bracketPct.toFixed(0)}% of sales
                          </span>
                        </div>
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
              {grain === 'brand' && typeof onSelectBrand === 'function' && (
                <p className="abcb-hint">Click a brand to see its products below.</p>
              )}
            </>
          )}
        </>
      )}
    </div>
    </section>
  );
};
