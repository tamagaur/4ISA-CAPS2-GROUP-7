import React, { useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { getBoMonitoring } from '../api/boMonitoring';
import { labelForPrincipal } from '../principals';
import { formatMonth } from '../utils/formatDate';
import { formatCompactPesos } from '../utils/formatters';
import { CHART_COLORS, SEMANTIC } from '../theme/colors';
import RefreshingNote from './RefreshingNote';
import './BadOrders.css';

// "Monitor bad-order trends" — the north star's second half, and the
// analytical mapping's D5: what share of received stock is lost to bad
// orders, and how it varies across principals and months.
//
// Everything here is what GET /bo-monitoring measured, with its limits said
// out loud (backend/routers/bo_monitoring.py's module note):
//   - BO rate is VALUE-based: BO net amount / purchase net amount for the
//     same principal and month. The source records no units for returns.
//   - A month with no returns file is a gap, not zero BO — drawn as a gap.
//   - Only Del Monte's returns are loaded; Unilever has none.
//   - No return dates are recorded, so there is no day-of-week view.

const PESO = new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', maximumFractionDigits: 0 });
const pct = (value) => (value == null ? '—' : `${value.toFixed(2)}%`);
const axisMonth = (period) => {
  const label = formatMonth(period) || period;
  const [month, year] = label.split(' ');
  return year ? `${month} · ${year}` : label;
};
const INCIDENT_PAGE = 25;

const TrendTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="bo-tooltip">
      <p className="bo-tooltip-label">{axisMonth(label)}</p>
      {!point.has_data ? (
        <p className="bo-tooltip-row">No returns file for this month — not zero, no data.</p>
      ) : (
        <>
          <p className="bo-tooltip-row">{point.incident_count} bad orders · {PESO.format(point.value_lost)} lost</p>
          <p className="bo-tooltip-row">
            {point.bo_rate != null
              ? `${pct(point.bo_rate)} of ${PESO.format(point.purchase_value)} purchased`
              : 'No purchases recorded this month, so no rate'}
          </p>
        </>
      )}
    </div>
  );
};

const BadOrders = () => {
  const { principal } = useOutletContext() || {};
  const principalLabel = labelForPrincipal(principal);
  const [state, setState] = useState({ status: 'loading', data: null, error: null, key: null });
  const [showAllIncidents, setShowAllIncidents] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, status: 'loading', error: null }));
    getBoMonitoring({ principal })
      .then((data) => { if (!cancelled) setState({ status: 'loaded', data, error: null, key: principal ?? '' }); })
      .catch((err) => {
        if (!cancelled) setState((prev) => ({ ...prev, status: 'error', error: err.message || 'Failed to load bad-order data' }));
      });
    return () => { cancelled = true; };
  }, [principal]);

  const data = state.data;
  const kpis = data?.kpis || {};
  const trend = useMemo(() => (data?.trend || []).map((t) => ({ ...t })), [data]);
  const hasData = trend.some((t) => t.has_data);
  const isColdLoad = state.status === 'loading' && !data;
  const isRefreshing = state.status === 'loading' && !!data;
  const missing = kpis.months_missing || [];
  const incidents = data?.incidents || [];
  const shownIncidents = showAllIncidents ? incidents : incidents.slice(0, INCIDENT_PAGE);
  const regionTotal = (data?.region_breakdown || []).reduce((sum, r) => sum + r.value_lost, 0);

  const header = (
    <div className="bo-header">
      <h2 className="bo-title">
        Bad <span className="page-title-accent">orders</span>
      </h2>
      <p className="bo-subtitle">
        Stock returned as bad orders (BO), by month and principal: the value lost, and its share of what was
        purchased that month.
      </p>
    </div>
  );

  if (isColdLoad) {
    return (
      <div className="bo-page"><div className="bo-content">{header}<p className="bo-note" role="status">Loading bad-order data…</p></div></div>
    );
  }

  if (state.status === 'error' && !data) {
    return (
      <div className="bo-page"><div className="bo-content">{header}<p className="bo-note" role="alert">Could not load bad-order data: {state.error}</p></div></div>
    );
  }

  return (
    <div className="bo-page">
      <div className="bo-content">
        {header}
        {isRefreshing && <RefreshingNote>Updating {principalLabel}…</RefreshingNote>}
        {state.status === 'error' && (
          <p className="bo-note" role="alert">Could not update: {state.error}. Showing the last data that loaded.</p>
        )}

        {!hasData ? (
          <div className="bo-empty">
            <h3 className="bo-empty-title">No bad-order data for {principalLabel}</h3>
            <p className="bo-empty-body">
              {principal === 'unilever'
                ? 'No Unilever returns have been loaded — only Del Monte’s returns files are in the database. Switch the scope to Del Monte or All principals.'
                : 'No returns typed as bad orders are loaded for this scope.'}
            </p>
          </div>
        ) : (
          <div className={`bo-body${isRefreshing ? ' is-refreshing' : ''}`} aria-busy={isRefreshing}>
            <div className="bo-kpi-grid">
              <div className="bo-kpi-card">
                <span className="bo-kpi-label">Bad orders</span>
                <span className="bo-kpi-value">{(kpis.incidents ?? 0).toLocaleString()}</span>
                <span className="bo-kpi-desc">return slips in {kpis.months_with_data} month{kpis.months_with_data === 1 ? '' : 's'} with returns data</span>
              </div>
              <div className="bo-kpi-card">
                <span className="bo-kpi-label">Value lost</span>
                <span className="bo-kpi-value">{PESO.format(kpis.valueLost ?? 0)}</span>
                <span className="bo-kpi-desc">BO net amount</span>
              </div>
              <div className="bo-kpi-card bo-kpi-rate">
                <span className="bo-kpi-label">BO rate</span>
                <span className="bo-kpi-value">{pct(kpis.ratePct)}</span>
                <span className="bo-kpi-desc">
                  of purchase value, over the {(kpis.rate_periods || []).length} month
                  {(kpis.rate_periods || []).length === 1 ? '' : 's'} with both returns and purchases
                </span>
              </div>
              <div className="bo-kpi-card bo-kpi-gaps">
                <span className="bo-kpi-label">Months without data</span>
                <span className="bo-kpi-value">{missing.length}</span>
                <span className="bo-kpi-desc">
                  {missing.length ? `${missing.map(formatMonth).join(', ')} — no returns file, not zero` : 'every month in range has returns data'}
                </span>
              </div>
            </div>

            <section className="bo-card">
              <div className="bo-card-header">
                <h3 className="bo-card-title">Monthly trend</h3>
                <p className="bo-card-subtitle">
                  Bars: value lost to bad orders. Line: BO rate, the value lost as a share of that month&apos;s purchases.
                  Hatched months have no returns file.
                </p>
              </div>
              <div className="bo-chart">
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={trend} margin={{ top: 10, right: 12, left: 4, bottom: 8 }}>
                    <defs>
                      <pattern id="bo-gap-hatch" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
                        <line x1="0" y1="0" x2="0" y2="6" stroke={CHART_COLORS.gridline} strokeWidth="3" />
                      </pattern>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                    <XAxis dataKey="period" tickFormatter={axisMonth} tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }} tickMargin={8} />
                    <YAxis yAxisId="value" tickFormatter={formatCompactPesos} tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }} width={56} />
                    <YAxis yAxisId="rate" orientation="right" tickFormatter={(v) => `${v}%`} tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }} width={44} />
                    <Tooltip content={<TrendTooltip />} cursor={{ fill: '#f7fafc' }} />
                    {/* A gap month gets a full-height hatched bar on its own
                        key, so "no data" is visible rather than an empty slot
                        that reads as zero. */}
                    <Bar
                      yAxisId="value"
                      dataKey={(p) => (p.has_data ? null : Math.max(...trend.map((t) => t.value_lost || 0)))}
                      fill="url(#bo-gap-hatch)"
                      barSize={34}
                      isAnimationActive={false}
                      name="No data"
                    />
                    <Bar yAxisId="value" dataKey="value_lost" fill={SEMANTIC.act} fillOpacity={0.85} radius={[5, 5, 0, 0]} barSize={34} name="Value lost" />
                    <Line yAxisId="rate" type="monotone" dataKey="bo_rate" stroke={SEMANTIC.noData} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} name="BO rate" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </section>

            <div className="bo-two-col">
              <section className="bo-card">
                <div className="bo-card-header">
                  <h3 className="bo-card-title">By principal</h3>
                  <p className="bo-card-subtitle">BO rate uses only months with both returns and purchases for that principal.</p>
                </div>
                <div className="data-table-card bo-table-card">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Principal</th>
                        <th className="table-num">Bad orders</th>
                        <th className="table-num">Value lost</th>
                        <th className="table-num">Months with data</th>
                        <th className="table-num">BO rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(data.principal_breakdown || []).map((p) => (
                        <tr key={p.principal}>
                          <td>{labelForPrincipal(p.principal)}</td>
                          <td className="table-num">{p.incidents.toLocaleString()}</td>
                          <td className="table-num">{PESO.format(p.value_lost)}</td>
                          <td className="table-num">{p.months_with_data}</td>
                          <td className="table-num">{pct(p.bo_rate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {principal !== 'delmonte' && (
                  <p className="bo-note">Unilever has no returns loaded, so it can&apos;t appear here yet.</p>
                )}
              </section>

              <section className="bo-card">
                <div className="bo-card-header">
                  <h3 className="bo-card-title">By region</h3>
                  <p className="bo-card-subtitle">The finest breakdown the returns data has — it records no SKU, brand or reason.</p>
                </div>
                <div className="bo-region-list">
                  {(data.region_breakdown || []).map((r) => (
                    <div className="bo-region-row" key={r.region ?? 'unknown'}>
                      <span className="bo-region-name">{r.region ? r.region[0].toUpperCase() + r.region.slice(1) : 'Unknown'}</span>
                      <div className="bo-region-track" role="img" aria-label={`${r.region}: ${PESO.format(r.value_lost)}`}>
                        <span style={{ width: `${regionTotal ? (r.value_lost / regionTotal) * 100 : 0}%` }} />
                      </div>
                      <span className="bo-region-value">{PESO.format(r.value_lost)} · {r.incidents}</span>
                    </div>
                  ))}
                </div>
                {kpis.dated_incidents === 0 && (
                  <p className="bo-note">
                    Return dates aren&apos;t recorded in the source, so bad orders can&apos;t be broken down by day of week.
                  </p>
                )}
              </section>
            </div>

            <section className="bo-card">
              <div className="bo-card-header">
                <h3 className="bo-card-title">Bad-order slips</h3>
                <p className="bo-card-subtitle">Newest month first, largest value first within a month.</p>
              </div>
              <div className="data-table-card bo-table-card">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Return slip</th>
                      <th>Month</th>
                      <th>Principal</th>
                      <th>Region</th>
                      <th className="table-num">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shownIncidents.map((i, index) => (
                      <tr key={`${i.id ?? 'slip'}-${index}`}>
                        <td className="cell-code">{i.id ?? '—'}</td>
                        <td>{i.period ? formatMonth(i.period) : '—'}</td>
                        <td>{labelForPrincipal(i.principal)}</td>
                        <td>{i.region ? i.region[0].toUpperCase() + i.region.slice(1) : '—'}</td>
                        <td className="table-num">{PESO.format(i.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {incidents.length > INCIDENT_PAGE && (
                <button className="bo-more-btn" onClick={() => setShowAllIncidents((v) => !v)}>
                  {showAllIncidents ? `Show the first ${INCIDENT_PAGE}` : `Show all ${incidents.length} slips`}
                </button>
              )}
            </section>

            <p className="bo-definition">
              <strong>How this is measured.</strong> A bad order is a return slip the source types as BO. BO rate = BO net
              amount ÷ purchase net amount for the same principal and month — value-based, because the returns data records
              no units. Months with no returns file are gaps, not zeros; months with returns but no purchases have no rate.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default BadOrders;
