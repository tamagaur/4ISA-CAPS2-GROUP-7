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
import { BAD_ORDER_REASONS } from '../data/mockData';
import './BadOrders.css';

const BO_RATE_TARGET = 3; // %, manuscript §3.4.1.3 target threshold

// Mock share of incidents per BAD_ORDER_REASONS entry, same index order,
// summing to 1.0 — Packaging Defect is the largest single cause, matching
// the dashboard footer strip's "top cause: packaging defect".
const REASON_WEIGHTS = [0.32, 0.14, 0.24, 0.08, 0.18, 0.04];

// Short axis-tick aliases for the two BAD_ORDER_REASONS entries too long to
// fit a chart's y-axis — the full wording still appears in the tooltip.
const SHORT_REASON_LABEL = {
  'Packaging Defect (Torn/Deformed/Broken)': 'Packaging Defect',
  'Order cancelled by customer': 'Order Cancelled',
};

// SKUs/categories with recorded incidents — the only ones a per-row rate is
// honest to show. Unilever has true per-SKU data; Del Monte has no SKU-level
// data anywhere in this project, so its rows are categories (CAT- codes).
const UNILEVER_TRACKED = [
  { code: 'SKU-07642', product: 'Dove Shampoo 340ml' },
  { code: 'SKU-04721', product: 'Surf Powder Detergent 1kg' },
];
const DELMONTE_TRACKED = [
  { code: 'CAT-SAUCES-VEG', product: 'Sauces & Vegetables' },
  { code: 'CAT-JUICES', product: 'Juices' },
];
const TRACKED_BY_PRINCIPAL = {
  unilever: UNILEVER_TRACKED,
  delmonte: DELMONTE_TRACKED,
  all: [...UNILEVER_TRACKED, ...DELMONTE_TRACKED],
};

// Components branch on this, never on the principal name.
const GRAIN_BY_PRINCIPAL = { unilever: 'sku', delmonte: 'category', all: 'mixed' };
const PRINCIPAL_BRAND = { unilever: 'Unilever', delmonte: 'Del Monte' };
// Same split BRAND_SHARE already used below, reused to scale the
// principal-blind mock aggregates (KPIs, reason/weekday breakdowns) down to
// whichever principal is selected, so they're not just the "all" totals
// repeated under every filter value.
const PRINCIPAL_SHARE = { unilever: 0.48, delmonte: 0.52, all: 1 };

function hashSeed(code) {
  let hash = 0;
  for (let i = 0; i < code.length; i++) {
    hash = (hash * 31 + code.charCodeAt(i)) >>> 0;
  }
  return hash;
}

// Manuscript §3.4.1.3: BO Rate (%) = Total Bad Order Units / Total Units
// Received x 100, tracked as a time series per SKU. Deterministic per SKU
// (not random) so the same SKU always shows the same shape.
const generateBORateTrend = (skuCode) => {
  const seed = hashSeed(skuCode);
  const base = 3.5 + (seed % 40) / 10; // 3.5 - 7.5, starts above target
  const monthNames = ['Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr'];
  return monthNames.map((month, i) => {
    const wobble = Math.sin((seed % 7) + i * 0.9) * 0.6;
    const drift = i * -0.35; // gradual improvement toward target
    const rate = Math.max(0.8, base + wobble + drift);
    return { month, rate: Math.round(rate * 10) / 10 };
  });
};

// Bad Orders Over Time — aggregate incident volume across all SKUs at a
// selectable granularity. Deterministic like generateBORateTrend, seeded off
// the period filter's dateOffset so it moves consistently with the KPI card.
// share scales the whole series down to the selected principal.
const generateBOTrend = (granularity, dateOffset, share) => {
  const base = (20 + dateOffset * 2) * share;
  if (granularity === 'daily') {
    return Array.from({ length: 14 }, (_, i) => ({
      label: `D${i + 1}`,
      count: Math.max(0, Math.round(base / 6 + Math.sin(i * 0.7) * 3)),
    }));
  }
  if (granularity === 'weekly') {
    return Array.from({ length: 8 }, (_, i) => ({
      label: `Wk ${i + 1}`,
      count: Math.max(0, Math.round(base / 1.5 + Math.sin(i * 0.9) * 4 - i * 0.4)),
    }));
  }
  const months = ['Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr'];
  return months.map((month, i) => ({
    label: month,
    count: Math.max(0, Math.round(base + Math.sin(i * 0.8) * 5 - i * 1.2)),
  }));
};

// When Bad Orders Happen — incident volume by weekday. Baseline shares
// reflect heavier Mon/Fri receiving cycles, plus an exact bump for
// manually-reported incidents' actual weekday.
const WEEKDAY_SHARES = { Mon: 0.22, Tue: 0.14, Wed: 0.12, Thu: 0.13, Fri: 0.20, Sat: 0.13, Sun: 0.06 };
const WEEKDAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const generateWeekdayBreakdown = (dateOffset, addedIncidents, share) => {
  const baseIncidents = (135 + dateOffset * 6) * share;
  const counts = {};
  Object.entries(WEEKDAY_SHARES).forEach(([day, share]) => {
    counts[day] = Math.round(baseIncidents * share);
  });
  addedIncidents.forEach((r) => {
    const day = WEEKDAY_NAMES[new Date(r.date).getDay()];
    counts[day] = (counts[day] ?? 0) + 1;
  });
  return Object.keys(WEEKDAY_SHARES).map((day) => ({ day, count: counts[day] }));
};

// Top SKUs/categories by Incidents — ranked count per tracked row,
// deterministic per-row baseline (same hashSeed as the BO rate trend) plus
// an exact bump for manually-reported incidents. trackedList is whichever
// principal's rows are active — never the unfiltered full set.
const generateTopSKUIncidents = (trackedList, addedIncidents) => {
  const counts = {};
  trackedList.forEach(({ code, product }) => {
    const seed = hashSeed(code);
    counts[code] = { product, count: 8 + (seed % 20) };
  });
  addedIncidents.forEach((r) => {
    if (counts[r.sku]) counts[r.sku].count += 1;
  });
  return Object.entries(counts)
    .map(([sku, { product, count }]) => ({ sku: formatSKU(sku), product, count }))
    .sort((a, b) => b.count - a.count);
};

// Incidents by Brand — Del Monte vs Unilever, split off the same
// period-driven baseline the KPI card uses, plus an exact bump for
// manually-reported incidents' actual brand. When a single principal is
// selected the page is already scoped to just that brand, so this only
// shows the other brand's bar for 'all' — never a stale second bar.
const BRAND_SHARE = { 'Del Monte': 0.52, 'Unilever': 0.48 };
const generateBrandBreakdown = (dateOffset, addedIncidents, principal) => {
  const baseIncidents = 135 + dateOffset * 6;
  const visibleBrands = principal === 'all'
    ? Object.keys(BRAND_SHARE)
    : [PRINCIPAL_BRAND[principal]];
  const counts = {};
  visibleBrands.forEach((brand) => {
    counts[brand] = Math.round(baseIncidents * BRAND_SHARE[brand]);
  });
  addedIncidents.forEach((r) => {
    if (counts[r.brand] !== undefined) counts[r.brand] += 1;
  });
  return Object.entries(counts).map(([brand, count]) => ({ brand, count }));
};

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
  const trackedList = useMemo(() => TRACKED_BY_PRINCIPAL[principal] ?? TRACKED_BY_PRINCIPAL.all, [principal]);
  const principalShare = PRINCIPAL_SHARE[principal] ?? 1;

  const [incidents, setIncidents] = useState([]);
  const [manualIncidents, setManualIncidents] = useState([]);
  const [dbKPIs, setDbKPIs] = useState({ incidents: 0, unitsLost: 0, valueLost: 0, rate: '0.0%' });
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedBOSKU, setSelectedBOSKU] = useState(trackedList[0].code);
  const [boTrendGranularity, setBoTrendGranularity] = useState('monthly');

  useEffect(() => {
    async function loadData() {
      try {
        let from = '';
        let to = '';
        const m = { Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06', Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12' };
        if (startYear && startMonth) from = `${startYear}-${m[startMonth]}-01`;
        if (endYear && endMonth) to = `${endYear}-${m[endMonth]}-28`;

        const data = await getBOMonitoringData({ principal, from, to });
        setIncidents(data.incidents || []);
        if (data.kpis) {
          setDbKPIs({
            incidents: data.kpis.incidents,
            unitsLost: data.kpis.unitsLost,
            valueLost: data.kpis.valueLost,
            rate: data.kpis.rate
          });
        }
      } catch (err) {
        console.error('Failed to load BO monitoring data:', err);
      }
    }
    loadData();
  }, [principal, startMonth, startYear, endMonth, endYear]);

  // Re-select when the principal filter changes — there is no per-SKU Del
  // Monte row to fall back to, so this always lands on a real tracked row.
  useEffect(() => {
    setSelectedBOSKU(trackedList[0].code);
  }, [trackedList]);

  const boRateTrend = useMemo(() => generateBORateTrend(selectedBOSKU), [selectedBOSKU]);
  const latestBORate = boRateTrend[boRateTrend.length - 1]?.rate ?? 0;

  const dateOffset = useMemo(() => {
    const startMonthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(startMonth) || 0;
    const endMonthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(endMonth) || 0;
    const yearVal = parseInt(startYear) || 2026;
    const seed = (startMonthIndex + endMonthIndex + yearVal) % 6;
    return seed - 1;
  }, [startMonth, startYear, endMonth, endYear]);

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

  // Real DB KPIs combined with manual reports
  const dynamicKPIs = useMemo(() => {
    const baseIncidents = dbKPIs.incidents;
    const baseUnitsLost = dbKPIs.unitsLost;
    const baseValueLostValue = dbKPIs.valueLost;
    const baseBadOrderRate = parseFloat(dbKPIs.rate) || 0;

    const addedUnits = addedIncidents.reduce((sum, r) => sum + r.qty, 0);
    const addedValue = addedIncidents.reduce((sum, r) => sum + r.value, 0);

    return {
      incidents: baseIncidents + addedIncidents.length,
      unitsLost: (baseUnitsLost + addedUnits).toLocaleString(),
      valueLost: `₱${((baseValueLostValue + addedValue) / 1000).toFixed(1)}k`,
      rate: (baseBadOrderRate + addedIncidents.length * 0.05).toFixed(1) + '%',
    };
  }, [dbKPIs, addedIncidents]);

  // Reason breakdown — fixed shares scaled against the same period-driven,
  // principal-scaled baseline the KPI card uses (so the two stay consistent
  // when either filter changes), plus an exact bump for manually-reported
  // incidents' actual reasons. Reasons come from BAD_ORDER_REASONS (SSM's
  // real return-reason codes), not the earlier invented Expiry/Transport
  // Damage/Storage Issue/Supplier Defect labels.
  const reasonCounts = useMemo(() => {
    const shares = BAD_ORDER_REASONS.reduce((acc, reason, i) => {
      acc[reason] = REASON_WEIGHTS[i];
      return acc;
    }, {});
    const baseIncidents = (135 + dateOffset * 6) * principalShare;
    const counts = {};
    Object.entries(shares).forEach(([reason, share]) => {
      counts[reason] = Math.round(baseIncidents * share);
    });
    addedIncidents.forEach((r) => {
      counts[r.reason] = (counts[r.reason] ?? 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [dateOffset, addedIncidents, principalShare]);

  const boTrend = useMemo(
    () => generateBOTrend(boTrendGranularity, dateOffset, principalShare),
    [boTrendGranularity, dateOffset, principalShare]
  );
  const weekdayBreakdown = useMemo(
    () => generateWeekdayBreakdown(dateOffset, addedIncidents, principalShare),
    [dateOffset, addedIncidents, principalShare]
  );
  const topSKUIncidents = useMemo(
    () => generateTopSKUIncidents(trackedList, addedIncidents),
    [trackedList, addedIncidents]
  );
  const brandBreakdown = useMemo(
    () => generateBrandBreakdown(dateOffset, addedIncidents, principal),
    [dateOffset, addedIncidents, principal]
  );

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
                Bad Order rate <span style={{ color: '#a0aec0', fontWeight: 400 }}>— 6 months, per {grain === 'category' ? 'category' : 'SKU'}</span>
              </h3>
              <select
                className="bo-sku-select"
                value={selectedBOSKU}
                onChange={(e) => setSelectedBOSKU(e.target.value)}
              >
                {trackedList.map(s => (
                  <option key={s.code} value={s.code}>{s.code} — {s.product}</option>
                ))}
                <option value="CURRENT_PERIOD">Current Period ({startMonth} {startYear} - {endMonth} {endYear})</option>
              </select>
            </div>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={boRateTrend} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf2f7" />
                  <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#a0aec0', fontSize: 12 }}
                    domain={[0, 8]}
                    ticks={[0, 2, 4, 6, 8]}
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
                    dataKey="rate"
                    stroke={COLORS.critical}
                    strokeWidth={2}
                    dot={{ r: 4, fill: COLORS.critical, strokeWidth: 0 }}
                    activeDot={{ r: 6 }}
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

          {/* Top Reasons Widget — horizontal bar: the job here is comparing
              magnitude across BAD_ORDER_REASONS' 6 named categories, which a
              bar shows at a glance (Packaging Defect is ~2x Overlanded/
              Shortlanded) in a way a plain number list doesn't. */}
          <div className="bo-widget">
            <h3 className="bo-widget-title">Top reasons</h3>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={reasonCounts.map(([reason, count]) => ({ reason, count }))}
                  layout="vertical"
                  margin={{ top: 5, right: 30, left: 10, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#edf2f7" />
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="reason"
                    width={140}
                    tick={{ fill: '#4a5568', fontSize: 11 }}
                    tickFormatter={(reason) => SHORT_REASON_LABEL[reason] || reason}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                    formatter={(value, name, props) => [value, props.payload.reason]}
                  />
                  <Bar dataKey="count" fill={COLORS.critical} radius={[0, 4, 4, 0]} barSize={22} isAnimationActive={false}>
                    <LabelList dataKey="count" position="right" style={{ fontSize: 12, fontWeight: 700, fill: '#1a202c' }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Bad Orders Over Time — aggregate volume trend, granularity toggle */}
          <div className="bo-widget">
            <div className="bo-widget-header-row">
              <h3 className="bo-widget-title">Bad orders <span>— over time</span></h3>
              <select
                className="bo-sku-select"
                value={boTrendGranularity}
                onChange={(e) => setBoTrendGranularity(e.target.value)}
              >
                <option value="daily">Daily (14d)</option>
                <option value="weekly">Weekly (8wk)</option>
                <option value="monthly">Monthly (6mo)</option>
              </select>
            </div>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={boTrend} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf2f7" />
                  <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 11 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} allowDecimals={false} />
                  <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
                  <Bar dataKey="count" name="Incidents" fill={COLORS.warning} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* When Bad Orders Happen — weekday breakdown */}
          <div className="bo-widget">
            <h3 className="bo-widget-title">When bad orders happen <span>— by day of week</span></h3>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={weekdayBreakdown} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf2f7" />
                  <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} allowDecimals={false} />
                  <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
                  <Bar dataKey="count" name="Incidents" fill={COLORS.dispatched} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Top SKUs by Incidents — ranked horizontal bar */}
          <div className="bo-widget">
            <h3 className="bo-widget-title">{grain === 'category' ? 'Top categories' : 'Top SKUs'} <span>— by incidents</span></h3>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={topSKUIncidents} layout="vertical" margin={{ top: 5, right: 30, left: 10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#edf2f7" />
                  <XAxis type="number" hide allowDecimals={false} />
                  <YAxis
                    type="category"
                    dataKey="sku"
                    width={90}
                    tick={{ fill: '#4a5568', fontSize: 12 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                    formatter={(value, name, props) => [value, props.payload.product]}
                  />
                  <Bar dataKey="count" fill={COLORS.critical} radius={[0, 4, 4, 0]} barSize={18} isAnimationActive={false}>
                    <LabelList dataKey="count" position="right" style={{ fontSize: 12, fontWeight: 700, fill: '#1a202c' }} />
                  </Bar>
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
                <BarChart data={brandBreakdown} margin={{ top: 20, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf2f7" />
                  <XAxis dataKey="brand" axisLine={false} tickLine={false} tick={{ fill: '#4a5568', fontSize: 12 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#a0aec0', fontSize: 12 }} allowDecimals={false} />
                  <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
                  <Bar dataKey="count" name="Incidents" radius={[4, 4, 0, 0]} barSize={60} isAnimationActive={false}>
                    <LabelList dataKey="count" position="top" style={{ fontSize: 12, fontWeight: 700, fill: '#1a202c' }} />
                    {brandBreakdown.map((entry) => (
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
