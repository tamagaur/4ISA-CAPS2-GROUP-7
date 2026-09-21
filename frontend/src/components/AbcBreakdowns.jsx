import React, { useEffect, useMemo, useState } from 'react';
import {
  ComposedChart,
  Bar,
  Cell,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import { getPareto } from '../api/analytics';
import { labelForPrincipal } from '../principals';
import { formatMonth } from '../utils/formatDate';
import { formatCompactPesos } from '../utils/formatters';
import { CHART_COLORS } from '../theme/colors';
import './AbcBreakdowns.css';

// Two cards under the ABC class chart, one per analytical-mapping question
// the SKU table can't answer on its own:
//   ParetoCard    D1 — which brands and product categories drive the
//                 majority of revenue (GET /pareto, same measure and 80/95%
//                 cutoffs as the SKU-level ABC).
//   AbcFsnMatrix  D3 — how the SKUs differ in movement frequency, crossed
//                 with their ABC class (GET /fsn, via the page's rows).

const TIER_COLOR = { A: CHART_COLORS.abcRamp[0], B: CHART_COLORS.abcRamp[1], C: CHART_COLORS.abcRamp[2] };
const titleCase = (name) => (name || '').toLowerCase().replace(/(^|[\s/&-])\S/g, (c) => c.toUpperCase());

const ParetoTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="abcb-tooltip">
      <p className="abcb-tooltip-title">{titleCase(row.name)} · Class {row.tier}</p>
      <p>{formatCompactPesos(row.revenue)} revenue · {(row.revenue_share * 100).toFixed(1)}% of the total</p>
      <p>Cumulative {(row.cumulative_share * 100).toFixed(1)}% · {row.products} product{row.products === 1 ? '' : 's'}</p>
    </div>
  );
};

export const ParetoCard = ({ principal, period }) => {
  const [grain, setGrain] = useState(principal === 'delmonte' ? 'category' : 'brand');
  const [months, setMonths] = useState(1);
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  const [sectionIndex, setSectionIndex] = useState(0);

  // Del Monte has no brand at all — land on the category view for it.
  useEffect(() => {
    if (principal === 'delmonte') setGrain('category');
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
  const tierCounts = rows.reduce((acc, r) => ({ ...acc, [r.tier]: (acc[r.tier] || 0) + 1 }), {});
  const aShare = rows.filter((r) => r.tier === 'A').reduce((sum, r) => sum + r.revenue_share, 0);

  return (
    <section className="abcb-card abcb-pareto">
      <div className="abcb-card-header">
        <div>
          <h3 className="abcb-card-title">What drives revenue — by {grain}</h3>
          <p className="abcb-card-subtitle">
            Pareto of revenue at {grain} level, ranked with the same measure and 80% / 95% cutoffs as the SKU table.
          </p>
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
            {[[1, 'Month'], [12, '12 months']].map(([m, label]) => (
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

      {state.status === 'loading' && !state.data && <p className="abcb-note">Loading…</p>}
      {state.status === 'error' && <p className="abcb-note" role="alert">Could not load the Pareto: {state.error}</p>}
      {section?.blocked_reason && <p className="abcb-note">{section.blocked_reason}</p>}

      {rows.length > 0 && (
        <>
          <p className="abcb-headline">
            <strong>{tierCounts.A || 0} of {rows.length}</strong> {grain === 'brand' ? 'brands' : 'categories'} make up{' '}
            <strong>{(aShare * 100).toFixed(0)}%</strong> of {labelForPrincipal(section.principal)} revenue
            {months === 1 ? ` in ${formatMonth(section.period)}` : ` from ${formatMonth(section.window_start)} to ${formatMonth(section.period)}`}.
          </p>
          <div className="abcb-chart">
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 48 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                <XAxis
                  dataKey="name"
                  tickFormatter={titleCase}
                  interval={0}
                  angle={-40}
                  textAnchor="end"
                  height={56}
                  tick={{ fill: CHART_COLORS.axisLabel, fontSize: 10 }}
                />
                <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }} width={40} />
                <Tooltip content={<ParetoTooltip />} cursor={{ fill: '#f7fafc' }} />
                <ReferenceLine y={80} stroke={CHART_COLORS.cumulativeCurve} strokeDasharray="4 3" label={{ value: 'A 80%', position: 'insideTopLeft', fontSize: 10, fill: CHART_COLORS.axisLabel }} />
                <ReferenceLine y={95} stroke={CHART_COLORS.cumulativeCurve} strokeDasharray="2 3" label={{ value: 'B 95%', position: 'insideTopLeft', fontSize: 10, fill: CHART_COLORS.axisLabel }} />
                <Bar dataKey="sharePct" name="Revenue share" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                  {rows.map((r) => <Cell key={r.name} fill={TIER_COLOR[r.tier]} />)}
                </Bar>
                <Line dataKey="cumPct" name="Cumulative share" stroke={CHART_COLORS.cumulativeCurve} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="abcb-legend">
            {['A', 'B', 'C'].map((t) => (
              <span key={t}><i style={{ backgroundColor: TIER_COLOR[t] }} />Class {t}: {tierCounts[t] || 0}</span>
            ))}
            <span><i className="abcb-legend-line" />Cumulative share</span>
          </div>
        </>
      )}
    </section>
  );
};

const FSN_META = {
  F: { label: 'Fast', title: 'Fast-moving' },
  S: { label: 'Slow', title: 'Slow-moving' },
  N: { label: 'Non-moving', title: 'Non-moving' },
};

export const AbcFsnMatrix = ({ rows, fsnOf, rules, loaded }) => {
  const matrix = useMemo(() => {
    const m = { A: { F: 0, S: 0, N: 0 }, B: { F: 0, S: 0, N: 0 }, C: { F: 0, S: 0, N: 0 } };
    if (!loaded) return m;
    rows.forEach((row) => {
      const fsn = fsnOf(row)?.fsn;
      if (m[row.cat] && fsn) m[row.cat][fsn] += 1;
    });
    return m;
  }, [rows, fsnOf, loaded]);
  const colTotals = ['F', 'S', 'N'].map((f) => ['A', 'B', 'C'].reduce((sum, t) => sum + matrix[t][f], 0));

  return (
    <section className="abcb-card abcb-matrix">
      <div className="abcb-card-header">
        <div>
          <h3 className="abcb-card-title">Movement × value (ABC × FSN)</h3>
          <p className="abcb-card-subtitle">
            How often each class actually sells, over the last {rules?.window_months ?? 12} months with data.
          </p>
        </div>
      </div>
      {!loaded ? (
        <p className="abcb-note">Loading movement classes…</p>
      ) : (
        <>
          <table className="abcb-matrix-table">
            <thead>
              <tr>
                <th />
                {['F', 'S', 'N'].map((f) => <th key={f} className={`fsn-col-${f}`}>{FSN_META[f].label}</th>)}
              </tr>
            </thead>
            <tbody>
              {['A', 'B', 'C'].map((t) => (
                <tr key={t}>
                  <th scope="row"><span className={`abcb-class-dot abcb-class-${t}`} />Class {t}</th>
                  {['F', 'S', 'N'].map((f) => (
                    <td key={f} className={matrix[t][f] === 0 ? 'is-zero' : `fsn-cell-${f}`}>{matrix[t][f].toLocaleString()}</td>
                  ))}
                </tr>
              ))}
              <tr className="abcb-matrix-total">
                <th scope="row">All</th>
                {colTotals.map((n, i) => <td key={i}>{n.toLocaleString()}</td>)}
              </tr>
            </tbody>
          </table>
          <p className="abcb-note">
            <strong>Fast</strong>: sold regularly (average gap between sales ≤ {rules?.fast_adi_max ?? 1.32} months, at least{' '}
            {rules?.min_fast_sales_months ?? 3} months of sales). <strong>Slow</strong>: sold, but intermittently.{' '}
            <strong>Non-moving</strong>: no sale in the last {rules?.non_moving_months ?? 6} months with data — the same rule
            the forecast uses for a dead SKU. Class A items that are slow or non-moving are the ones to question first.
          </p>
        </>
      )}
    </section>
  );
};
