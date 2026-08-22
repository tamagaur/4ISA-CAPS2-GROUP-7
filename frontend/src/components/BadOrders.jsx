import React, { useEffect, useMemo, useState } from 'react';
import { getBOMonitoringData } from '../api/bo_monitoring';
import { useOutletContext } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { logAction } from '../utils/auditLogger';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  Cell,
  LabelList,
  ReferenceLine,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import ReportBadOrderModal from './ReportBadOrderModal';
import DateFilter from './DateFilter';
import { COLORS } from '../theme/colors';
import './BadOrders.css';

const BO_RATE_TARGET = 3; // %, manuscript §3.4.1.3 target threshold

// Components branch on this, never on the principal name.
const GRAIN_BY_PRINCIPAL = { unilever: 'sku', delmonte: 'category', all: 'mixed' };
const PRINCIPAL_BRAND = { unilever: 'Unilever', delmonte: 'Del Monte' };

// Helper to extract product name and weight (supports decimals like 1.5L, 2.5kg)
const parseProductAndWeight = (product) => {
  if (!product) return { name: '', weight: '' };
  const weightRegex = /\b(\d+(?:\.\d+)?\s*(?:g|ml|l|kg|L|KG|ML|G))\b/;
  const match = product.match(weightRegex);
  if (match) {
    const weight = `(${match[1]})`;
    let name = product.replace(weightRegex, '').replace(/\s+/g, ' ').trim();
    name = name.replace(/\(\s*\)/g, '').trim();
    return { name, weight };
  }
  return { name: product, weight: '' };
};

// Helper to format SKU to 5 digits (SKU-#####)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  return sku;
};

// Bad Orders array is fetched from the backend now.

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const rate = payload[0].value;
    const overTarget = rate > BO_RATE_TARGET;
    return (
      <div style={{
        backgroundColor: '#ffffff',
        border: '1px solid #e2e8f0',
        padding: '0.6rem 0.8rem',
        borderRadius: '8px',
        boxShadow: '0 4px 15px rgba(0, 0, 0, 0.05)',
      }}>
        <p style={{ fontWeight: 600, color: '#1a202c', margin: '0 0 0.2rem 0', fontSize: '0.8rem' }}>{label}</p>
        <p style={{ color: overTarget ? COLORS.critical : COLORS.success, margin: 0, fontSize: '0.8rem', fontWeight: 600 }}>
          BO Rate: {rate}% {overTarget ? '(above target)' : '(within target)'}
        </p>
      </div>
    );
  }
  return null;
};

const BadOrders = () => {
  const { startMonth, startYear, endMonth, endYear, principal } = useOutletContext() || {
    startMonth: 'Apr', startYear: '2026', endMonth: 'Apr', endYear: '2026', principal: 'all',
  };
  const grain = GRAIN_BY_PRINCIPAL[principal] ?? 'mixed';

  const [incidents, setIncidents] = useState([]);
  const [manualIncidents, setManualIncidents] = useState([]);
  const [dbKPIs, setDbKPIs] = useState({ incidents: 0, unitsLost: 0, valueLost: 0, rate: '0.0%' });
  const [trend, setTrend] = useState([]);
  const [weekdayBreakdown, setWeekdayBreakdown] = useState([]);
  const [brandBreakdown, setBrandBreakdown] = useState([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [queriedRange, setQueriedRange] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function loadData() {
      setLoading(true);
      setLoadError(null);
      try {
        let from = '';
        let to = '';
        const m = { Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06', Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12' };
        if (startYear && startMonth) from = `${startYear}-${m[startMonth]}-01`;
        if (endYear && endMonth) to = `${endYear}-${m[endMonth]}-28`;
        if (!cancelled) setQueriedRange({ from, to });

        const data = await getBOMonitoringData({ principal, from, to });
        if (cancelled) return;
        setIncidents(data.incidents || []);
        if (data.kpis) {
          setDbKPIs({
            incidents: data.kpis.incidents,
            unitsLost: data.kpis.unitsLost,
            valueLost: data.kpis.valueLost,
            rate: data.kpis.rate
          });
        }
        setTrend(data.trend || []);
        setWeekdayBreakdown(data.weekday_breakdown || []);
        setBrandBreakdown(data.brand_breakdown || []);
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to load BO monitoring data:', err);
        setLoadError(err.message || 'Failed to load Bad Order monitoring data');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadData();
    return () => { cancelled = true; };
  }, [principal, startMonth, startYear, endMonth, endYear]);

  const latestBORate = trend.length > 0 ? (trend[trend.length - 1].bo_rate ?? 0) : 0;

  const allIncidents = useMemo(() => [...manualIncidents, ...incidents], [manualIncidents, incidents]);

  // Incidents scoped to the selected principal — read via the same Outlet
  // context the Dashboard uses, no second state mechanism.
  const visibleIncidents = useMemo(
    () => principal === 'all' ? allIncidents : allIncidents.filter(i => i.brand === PRINCIPAL_BRAND[principal]),
    [allIncidents, principal]
  );

  // Manually-reported incidents during this session
  const addedIncidents = useMemo(
    () => principal === 'all' ? manualIncidents : manualIncidents.filter(i => i.brand === PRINCIPAL_BRAND[principal]),
    [manualIncidents, principal]
  );

  // Real DB KPIs combined with manual reports made this session
  const dynamicKPIs = useMemo(() => {
    const baseIncidents = dbKPIs.incidents;
    const baseUnitsLost = dbKPIs.unitsLost;
    const baseValueLostValue = dbKPIs.valueLost;

    const addedUnits = addedIncidents.reduce((sum, r) => sum + r.qty, 0);
    const addedValue = addedIncidents.reduce((sum, r) => sum + r.value, 0);

    return {
      incidents: baseIncidents + addedIncidents.length,
      unitsLost: (baseUnitsLost + addedUnits).toLocaleString(),
      valueLost: `₱${((baseValueLostValue + addedValue) / 1000).toFixed(1)}k`,
      rate: dbKPIs.rate,
    };
  }, [dbKPIs, addedIncidents]);

  // Manually-reported incidents (real staff input, not fabricated) bump the
  // weekday/brand breakdowns the backend already computed from real data.
  const weekdayBreakdownWithManual = useMemo(() => {
    const counts = {};
    weekdayBreakdown.forEach((row) => { counts[row.day] = row.count; });
    addedIncidents.forEach((r) => {
      const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      const day = dayNames[new Date(r.date).getDay()];
      counts[day] = (counts[day] ?? 0) + 1;
    });
    return weekdayBreakdown.map((row) => ({ day: row.day, count: counts[row.day] ?? row.count }));
  }, [weekdayBreakdown, addedIncidents]);

  const brandBreakdownWithManual = useMemo(() => {
    const counts = {};
    brandBreakdown.forEach((row) => { counts[row.brand] = row.count; });
    addedIncidents.forEach((r) => {
      counts[r.brand] = (counts[r.brand] ?? 0) + 1;
    });
    return brandBreakdown.map((row) => ({ brand: row.brand, count: counts[row.brand] ?? row.count }));
  }, [brandBreakdown, addedIncidents]);

  const handleAddReport = (reportData) => {
    const nextIncNum = incidents.length + manualIncidents.length + 1;
    const newIncident = {
      id: `INC-2024-${nextIncNum}`,
      sku: reportData.sku,
      brand: reportData.brand,
      product: reportData.product,
      qty: reportData.qty,
      reason: reportData.reason,
      value: reportData.value,
      date: new Date().toISOString().split('T')[0],
    };

    setManualIncidents(prev => [newIncident, ...prev]);

    logAction(
      'Reported Bad Order',
      `Logged ${newIncident.id} for ${newIncident.sku} (${newIncident.reason})`
    );
  };

  return (
    <div className="bo-page">
      <div className="bo-content">
        <div className="bo-page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
          <div className="bo-header-left">
            <h2 className="bo-page-title" style={{ fontSize: '2rem', fontWeight: 700, color: '#1a202c', margin: '0 0 0.3rem 0' }}>
              Bad order <span style={{ color: '#e53e3e' }}>monitoring</span>
            </h2>
            <p className="bad-subtitle" style={{ color: '#a0aec0', fontSize: '0.85rem', margin: 0, lineHeight: 1.5 }}>
              Manage damage, expiry, and loss reports for {startMonth} {startYear} - {endMonth} {endYear}
            </p>
            <p className="bo-page-subtitle" style={{ color: '#718096', fontSize: '0.8rem', margin: '0.4rem 0 0 0', maxWidth: '800px', lineHeight: 1.4 }}>
              RMR GS &amp; BO reports where possible, or flagged directly by staff where the source reports don't capture it (e.g. SKU, reason). Consistent BO data sharpens future SARIMA &amp; LP optimization.
            </p>
          </div>
          <div className="bo-header-right" style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem', alignItems: 'flex-end' }}>
            <button className="bo-report-btn" onClick={() => setIsModalOpen(true)}>
              <Plus size={16} />
              Report
            </button>
            <DateFilter onRefresh={() => window.location.reload()} />
          </div>
        </div>

        {loading && <p className="bo-page-subtitle">Loading Bad Order data…</p>}

        {loadError && (
          <div className="dashboard-error-state">
            <p>{loadError}</p>
          </div>
        )}

        {!loading && !loadError && incidents.length === 0 && manualIncidents.length === 0 && (
          <p className="bo-page-subtitle">
            No incidents returned for {queriedRange?.from} to {queriedRange?.to}
            {principal !== 'all' ? ` (principal: ${principal})` : ''}.
            If you expect data here, check that SalesReturn_Fact_Real has rows with return_type='BO'
            in that period, and that the _period column format matches 'YYYY-MM'.
          </p>
        )}

        {/* Summary KPI Cards */}
        <div className="bo-summary-grid">
          <div className="bo-summary-card bo-card-incidents">
            <span className="bo-card-label">INCIDENTS</span>
            <span className="bo-card-value">{dynamicKPIs.incidents}</span>
            <span className="bo-card-desc">this month</span>
          </div>
          <div className="bo-summary-card bo-card-units">
            <span className="bo-card-label">UNITS LOST</span>
            <span className="bo-card-value">{dynamicKPIs.unitsLost}</span>
            <span className="bo-card-desc">damaged / expired</span>
          </div>
          <div className="bo-summary-card bo-card-value">
            <span className="bo-card-label">VALUE LOST</span>
            <span className="bo-card-value">{dynamicKPIs.valueLost}</span>
            <span className="bo-card-desc">cost of waste</span>
          </div>
          <div className="bo-summary-card bo-card-rate">
            <span className="bo-card-label">BAD ORDER RATE</span>
            <span className="bo-card-value">{dynamicKPIs.rate}</span>
            <span className="bo-card-desc">target &lt; 3%</span>
          </div>
        </div>

        {/* Main Content Area: Widgets Grid */}
        <div className="bo-widgets-grid">
          {/* Chart Widget — Manuscript §3.4.1.3/§3.5.5: BO Rate per SKU, time series, vs target */}
          <div className="bo-widget">
            <div className="bo-widget-header-row">
              <h3 className="bo-widget-title">
                Bad Order rate <span style={{ color: '#a0aec0', fontWeight: 400 }}>— by period (BO returns ÷ purchases, peso-based)</span>
              </h3>
            </div>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={trend} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf2f7" />
                  <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#a0aec0', fontSize: 12 }}
                    tickFormatter={(v) => `${v}%`}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <ReferenceLine
                    y={BO_RATE_TARGET}
                    stroke={COLORS.success}
                    strokeDasharray="4 4"
                    strokeWidth={1.5}
                    label={{ value: `Target < ${BO_RATE_TARGET}%`, position: 'insideTopRight', fill: COLORS.success, fontSize: 11, fontWeight: 600 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="bo_rate"
                    stroke={COLORS.critical}
                    strokeWidth={2}
                    dot={{ r: 4, fill: COLORS.critical, strokeWidth: 0 }}
                    activeDot={{ r: 6 }}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="bo-chart-footnote">
              Latest: <strong className={latestBORate > BO_RATE_TARGET ? 'bo-footnote-over' : 'bo-footnote-under'}>
                {latestBORate}%
              </strong> {latestBORate > BO_RATE_TARGET ? 'above' : 'within'} the {BO_RATE_TARGET}% target
            </p>
          </div>

          {/* Bad Orders Over Time — incident count per period. Reason-code and
              per-SKU breakdowns aren't shown here: RMR GS/BO source data has
              no reason or SKU column at all (only Untaxed/Discount/Tax/Net
              Amount/Balance — see analytics/db/schema.sql SalesReturn_Fact),
              so those series would have to be fabricated to exist. */}
          <div className="bo-widget">
            <div className="bo-widget-header-row">
              <h3 className="bo-widget-title">Bad orders <span>— over time</span></h3>
            </div>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={trend} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf2f7" />
                  <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 11 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} allowDecimals={false} />
                  <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
                  <Bar dataKey="incident_count" name="Incidents" fill={COLORS.warning} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* When Bad Orders Happen — weekday breakdown, from return_date */}
          <div className="bo-widget">
            <h3 className="bo-widget-title">When bad orders happen <span>— by day of week</span></h3>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={weekdayBreakdownWithManual} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf2f7" />
                  <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} allowDecimals={false} />
                  <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
                  <Bar dataKey="count" name="Incidents" fill={COLORS.dispatched} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Incidents by Brand — two-series comparison; passes the CVD
              validator (ΔE 27.4 deutan / 31.7 normal) and each bar carries
              its own text label + x-axis category, so identity never
              depends on color alone. */}
          <div className="bo-widget">
            <h3 className="bo-widget-title">Incidents <span>— by brand</span></h3>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={brandBreakdownWithManual} margin={{ top: 20, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf2f7" />
                  <XAxis dataKey="brand" axisLine={false} tickLine={false} tick={{ fill: '#4a5568', fontSize: 12 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} allowDecimals={false} />
                  <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
                  <Bar dataKey="count" name="Incidents" radius={[4, 4, 0, 0]} barSize={60} isAnimationActive={false}>
                    <LabelList dataKey="count" position="top" style={{ fontSize: 12, fontWeight: 700, fill: '#1a202c' }} />
                    {brandBreakdownWithManual.map((entry) => (
                      <Cell key={entry.brand} fill={entry.brand === 'Del Monte' ? COLORS.success : COLORS.salesTrend} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {(grain === 'category' || grain === 'mixed') && (
          <p className="bo-grain-note">
            Del Monte is analysed at category level — no SKU-level data is available from this principal
          </p>
        )}

        {/* Incident Log Table — read-only, extracted via ETL */}
        <div className="bo-table-wrapper">
          <table className="bo-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>{grain === 'category' ? 'CATEGORY' : 'SKU'}</th>
                <th>BRAND</th>
                <th>PRODUCT</th>
                <th>QTY</th>
                <th>REASON</th>
                <th>VALUE</th>
                <th>DATE</th>
              </tr>
            </thead>
            <tbody>
              {visibleIncidents.map((incident) => (
                <tr key={incident.id}>
                  <td className="bo-id-cell">{incident.id}</td>
                  <td className="bo-sku-cell">{formatSKU(incident.sku)}</td>
                  <td>{incident.brand}</td>
                  <td className="bo-product-cell">
                    {(() => {
                      const { name, weight } = parseProductAndWeight(incident.product);
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                          <span className="bo-product-name">{name}</span>
                          {weight && (
                            <span className="bo-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                              {weight}
                            </span>
                          )}
                        </div>
                      );
                    })()}
                  </td>
                  <td className="bo-qty-cell">{incident.qty}</td>
                  <td>{incident.reason}</td>
                  <td className="bo-value-cell">₱{incident.value.toLocaleString()}</td>
                  <td className="bo-date-cell">{incident.date}</td>
                </tr>
              ))}
              {visibleIncidents.length === 0 && (
                <tr>
                  <td colSpan="8" className="bo-no-results">No data for this selection.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <ReportBadOrderModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSubmitReport={handleAddReport}
      />
    </div>
  );
};

export default BadOrders;
