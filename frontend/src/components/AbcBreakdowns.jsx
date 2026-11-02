import React, { useEffect, useMemo, useState } from 'react';
import SectionLede from './ui/SectionLede';
import {
  ComposedChart,
  Bar,
  Cell,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import { getPareto } from '../api/analytics';
import { labelForPrincipal } from '../principals';
import { formatMonth } from '../utils/formatDate';
import { formatCompactPesos } from '../utils/formatters';
import { CHART_COLORS } from '../theme/colors';
import { GRID_PROPS } from './ChartZoom';
import { ChartTable, ChartViewToggle } from './ChartTable';
import { LoadingStatus, SkeletonChart, SkeletonTable } from './Skeleton';
import './AbcBreakdowns.css';

// Two cards under the ABC class chart, one per analytical-mapping question
// the SKU table can't answer on its own:
//   ParetoCard    D1 — which brands and product categories drive the
//                 majority of revenue (GET /pareto, same measure and 80/95%
//                 cutoffs as the SKU-level ABC).
//   AbcFsnMatrix  D3 — how the SKUs differ in movement frequency, crossed
//                 with their ABC class (GET /fsn, via the page's rows).

const TIER_COLOR = { A: CHART_COLORS.abcRamp[0], B: CHART_COLORS.abcRamp[1], C: CHART_COLORS.abcRamp[2] };
// Emphasis, not eight colours: the Pareto's whole story is "the A tier is
// the revenue", so only Class A bars keep the plum — B and C recede into
// grays (design pass 2026-09-26). The legend uses the same map, so a gray
// swatch beside "Class B" is a statement, not a mismatch. The two grays
// are one hue, one visible lightness step apart, and the lighter one
// still clears the 2:1 on-white floor (palette validator, 2026-09-26) —
// muted must never mean invisible.
const PARETO_BAR_COLOR = { A: TIER_COLOR.A, B: '#8E99A9', C: '#ACB5C3' };
const titleCase = (name) => (name || '').toLowerCase().replace(/(^|[\s/&-])\S/g, (c) => c.toUpperCase());

// The Pareto's period as the Technical Adviser reads periods: one month
// ("Feb 2026") or a range ("Mar 2025 – Feb 2026"), from GET /pareto's own
// window, never the months the toggle asked for (a window is cut at the
// principal's latest data month).
const paretoPeriod = (section, months) =>
  months === 1 || !section?.window_start || section.window_start === section.period
    ? formatMonth(section?.period)
    : `${formatMonth(section.window_start)} \u2013 ${formatMonth(section.period)}`;

const ParetoTooltip = ({ active, payload, periodText, unit }) => {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="abcb-tooltip">
      <p className="abcb-tooltip-title">{titleCase(row.name)} · Class {row.tier}</p>
      <p>{formatCompactPesos(row.revenue)} revenue in {periodText} · {(row.revenue_share * 100).toFixed(1)}% of the total</p>
      <p>Cumulative {(row.cumulative_share * 100).toFixed(1)}% · {row.products.toLocaleString()} {unit(row.products)}</p>
    </div>
  );
};

export const ParetoCard = ({ principal, period }) => {
  const [grain, setGrain] = useState(principal === 'delmonte' ? 'category' : 'brand');
  const [months, setMonths] = useState(1);
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  const [sectionIndex, setSectionIndex] = useState(0);
  const [view, setView] = useState('chart');

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
  // Read off the running total at Class A's last row (rounded once), not
  // summed from per-row shares each rounded to 4 dp — the same fix as GET
  // /abc's class totals, where the sum read Class B 14.9% for 15.0%.
  const aShare = rows.filter((r) => r.tier === 'A').reduce((top, r) => Math.max(top, r.cumulative_share), 0);
  // The ABC run's own cutoffs, from GET /pareto's payload — the reference
  // lines state the constants the ranking used, not numbers retyped here.
  const cutoffs = state.data?.cutoffs || null;
  const aCutPct = cutoffs ? cutoffs.A * 100 : null;
  const bCutPct = cutoffs ? cutoffs.B * 100 : null;
  // Where the cumulative curve first clears the A cutoff — the visual
  // anchor for the headline's "N of M make up 80%".
  const crossing = aCutPct != null ? rows.find((r) => r.cumPct >= aCutPct) : null;
  const periodText = section?.period ? paretoPeriod(section, months) : null;
  const grainLabel = grain === 'brand' ? 'Brand' : 'Category';
  // What `products` counts: Unilever's revenue is per SKU; Del Monte's is
  // per sell-out category (DEC-03), one product row each.
  const productUnit = (n) => (section?.principal === 'delmonte'
    ? (n === 1 ? 'category' : 'categories')
    : (n === 1 ? 'SKU' : 'SKUs'));

  return (
    <section className="abcb-card abcb-pareto">
      <div className="abcb-card-header">
        <div>
          <h3 className="abcb-card-title">What drives revenue — by {grain}</h3>
          <SectionLede>What moves, and who is behind it</SectionLede>
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

      {state.status === 'loading' && !state.data && (
        <>
          <LoadingStatus>Loading the Pareto…</LoadingStatus>
          <SkeletonChart variant="bars" height={260} />
        </>
      )}
      {state.status === 'error' && <p className="abcb-note" role="alert">Could not load the Pareto: {state.error}</p>}
      {section?.blocked_reason && <p className="abcb-note">{section.blocked_reason}</p>}

      {rows.length > 0 && (
        <>
          <div className="abcb-headline-row">
            <p className="abcb-headline">
              <strong>{tierCounts.A || 0} of {rows.length}</strong> {grain === 'brand' ? 'brands' : 'categories'} make up{' '}
              <strong>{(aShare * 100).toFixed(0)}%</strong> of {labelForPrincipal(section.principal)} revenue
              {' '}in {periodText}.
            </p>
            <ChartViewToggle view={view} onChange={setView} label="Pareto: chart or table" />
          </div>
          {view === 'table' ? (
            <ChartTable
              caption={`Revenue Pareto by ${grain}, ${periodText}`}
              columns={[
                { key: 'name', label: grainLabel, format: (v) => titleCase(v), align: 'left' },
                { key: 'tier', label: 'Class', align: 'left' },
                { key: 'revenue', label: 'Revenue (₱)', format: (v) => formatCompactPesos(v) },
                { key: 'sharePct', label: 'Share of revenue (%)', format: (v) => `${v.toFixed(1)}%` },
                { key: 'cumPct', label: 'Cumulative share (%)', format: (v) => `${v.toFixed(1)}%` },
                { key: 'products', label: section.principal === 'delmonte' ? 'Categories' : 'SKUs' },
              ]}
              rows={rows.map((r) => ({ ...r, key: r.name }))}
            />
          ) : (
            <>
              <div className="abcb-legend">
                {['A', 'B', 'C'].map((t) => (
                  <span key={t}><i style={{ backgroundColor: PARETO_BAR_COLOR[t] }} />Class {t}: {tierCounts[t] || 0}</span>
                ))}
                <span><i className="abcb-legend-line" />Cumulative share (%)</span>
              </div>
              <div className="abcb-chart">
                <ResponsiveContainer width="100%" height={260}>
                  <ComposedChart data={rows} margin={{ top: 8, right: 12, left: 8, bottom: 48 }}>
                    <CartesianGrid {...GRID_PROPS} />
                    <XAxis
                      dataKey="name"
                      tickFormatter={titleCase}
                      interval={0}
                      angle={-40}
                      textAnchor="end"
                      height={56}
                      tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                    />
                    <YAxis
                      domain={[0, 100]}
                      tickFormatter={(v) => `${v}%`}
                      tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                      width={54}
                      label={{
                        value: '% of revenue',
                        angle: -90,
                        position: 'insideLeft',
                        style: { textAnchor: 'middle', fill: CHART_COLORS.axisLabel, fontSize: 11 },
                      }}
                    />
                    <Tooltip content={<ParetoTooltip periodText={periodText} unit={productUnit} />} cursor={{ fill: '#f7fafc' }} />
                    {/* The run's own cutoffs (GET /pareto payload) — drawn
                        only when the API sent them, never a retyped 80/95. */}
                    {aCutPct != null && (
                      <ReferenceLine y={aCutPct} stroke={CHART_COLORS.cumulativeCurve} strokeDasharray="4 3" label={{ value: `A ${Math.round(aCutPct)}%`, position: 'insideTopLeft', fontSize: 11, fill: CHART_COLORS.axisLabel }} />
                    )}
                    {bCutPct != null && (
                      <ReferenceLine y={bCutPct} stroke={CHART_COLORS.cumulativeCurve} strokeDasharray="2 3" label={{ value: `B ${Math.round(bCutPct)}%`, position: 'insideTopLeft', fontSize: 11, fill: CHART_COLORS.axisLabel }} />
                    )}
                    <Bar dataKey="sharePct" name="Revenue share" maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false}>
                      {rows.map((r) => <Cell key={r.name} fill={PARETO_BAR_COLOR[r.tier]} />)}
                    </Bar>
                    <Line dataKey="cumPct" name="Cumulative share" stroke={CHART_COLORS.cumulativeCurve} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
                    {/* The month's Pareto moment: where the cumulative curve
                        clears the A cutoff — the dot the headline sentence
                        is pointing at. */}
                    {crossing && (
                      <ReferenceDot
                        x={crossing.name}
                        y={crossing.cumPct}
                        r={5}
                        fill={CHART_COLORS.cumulativeCurve}
                        stroke="var(--color-surface, #fff)"
                        strokeWidth={2}
                        isFront
                      />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
                {/* The X axis title, as text under the chart: the angled
                    tick labels (long category paths) run to different
                    depths, so an in-chart label would sit on top of them. */}
                <p className="abcb-axis-title">{grainLabel}, ranked by {periodText} revenue</p>
              </div>
            </>
          )}
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

// `rows` are the items ranked in the page's run only. Carried-forward tiers
// (no sales since their last run) used to be counted too, so every
// non-moving Class A item in the matrix was one that had simply stopped
// selling (16 of 16, 2026-09-29) — the note below then pointed at stale
// tiers. `carriedCount` says how many were left out.
export const AbcFsnMatrix = ({
  rows, fsnOf, rules, loaded, carriedCount = 0, windowText = null, periodLabel = null, unit = 'SKUs',
}) => {
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
  // Heatmap shading: ONE neutral hue, deeper where the count is larger,
  // so the matrix's shape (where the SKUs pile up) reads at a glance
  // before any number is read. Sequential = single hue, light -> dark;
  // zero cells stay unshaded (a blank is a fact here, not a low value).
  const maxCount = Math.max(1, ...['A', 'B', 'C'].flatMap((t) => ['F', 'S', 'N'].map((f) => matrix[t][f])));
  // Soft cells (UI pass): fast in a pale slate-blue, slow in neutral grey,
  // each a little deeper where the count is larger; non-moving in a soft
  // coral, the one risk the matrix is there to show.
  const CELL_HUE = { F: '#5B7BA8', S: '#8792A2', N: '#E85C4A' };
  const heat = (count, f) =>
    count > 0
      ? { backgroundColor: `color-mix(in srgb, ${CELL_HUE[f]} ${Math.round((count / maxCount) * 18) + (f === 'N' ? 10 : 5)}%, var(--color-surface))` }
      : undefined;

  return (
    <section className="abcb-card abcb-matrix">
      <div className="abcb-card-header">
        <div>
          <h3 className="abcb-card-title">Movement × value (fast, slow or non-moving, by ABC class)</h3>
          <SectionLede>Which classes keep selling, and which sit still</SectionLede>
          <p className="abcb-card-subtitle">
            How often each class actually sells, over{' '}
            {windowText
              ? <strong>{windowText}</strong>
              : <>the last {rules?.window_months ?? 12} months with data</>}
.
            {' '}Counts are {unit} ranked in {periodLabel ?? 'this run'}
            {carriedCount > 0 && <> — {carriedCount.toLocaleString()} carried forward (no sales since) are left out</>}.
          </p>
        </div>
      </div>
      {!loaded ? (
        <>
          <LoadingStatus>Loading movement classes…</LoadingStatus>
          <SkeletonTable rows={3} columns={4} />
        </>
      ) : (
        <>
          <table className="abcb-matrix-table">
            <thead>
              <tr>
                <th className="abcb-matrix-unit">{unit}</th>
                {['F', 'S', 'N'].map((f) => <th key={f} className={`fsn-col-${f}`}>{FSN_META[f].label}</th>)}
              </tr>
            </thead>
            <tbody>
              {['A', 'B', 'C'].map((t) => (
                <tr key={t}>
                  <th scope="row"><span className={`abcb-class-dot abcb-class-${t}`} />Class {t}</th>
                  {['F', 'S', 'N'].map((f) => (
                    <td key={f} className={matrix[t][f] === 0 ? 'is-zero' : `fsn-cell-${f}`} style={heat(matrix[t][f], f)}>
                      {matrix[t][f].toLocaleString()}
                    </td>
                  ))}
                </tr>
              ))}
              <tr className="abcb-matrix-total">
                <th scope="row">All</th>
                {colTotals.map((n, i) => <td key={i}>{n.toLocaleString()}</td>)}
              </tr>
            </tbody>
          </table>
          {/* Every threshold below is GET /fsn's rules block — no local
              fallback numbers, so the note can never state a rule the
              backend didn't apply. Without rules, no thresholds are
              claimed at all. */}
          {rules ? (
            <p className="abcb-note">
              <strong>Fast</strong>: sold regularly (average gap between sales ≤ {rules.fast_adi_max} months, at least{' '}
              {rules.min_fast_sales_months} months of sales). <strong>Slow</strong>: sold, but intermittently.{' '}
              <strong>Non-moving</strong>: no sale in the last {rules.non_moving_months} months with data — the same rule
              the forecast uses for a dead SKU. Class A items that are slow or non-moving are the ones to question first.
            </p>
          ) : (
            <p className="abcb-note">
              <strong>Fast</strong> sells regularly, <strong>Slow</strong> intermittently, <strong>Non-moving</strong> not
              recently. Class A items that are slow or non-moving are the ones to question first.
            </p>
          )}
        </>
      )}
    </section>
  );
};
