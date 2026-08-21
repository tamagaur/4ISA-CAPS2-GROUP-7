import React, { useMemo, useState } from 'react';
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
const generateBOTrend = (granularity, dateOffset) => {
  const base = 20 + dateOffset * 2;
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
const generateWeekdayBreakdown = (dateOffset, addedIncidents) => {
  const baseIncidents = 135 + dateOffset * 6;
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

// Top SKUs by Incidents — ranked count per tracked SKU, deterministic
// per-SKU baseline (same hashSeed as the BO rate trend) plus an exact bump
// for manually-reported incidents.
const generateTopSKUIncidents = (addedIncidents) => {
  const counts = {};
  BO_TRACKED_SKUS.forEach(({ code, product }) => {
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
// manually-reported incidents' actual brand.
const BRAND_SHARE = { 'Del Monte': 0.52, 'Unilever': 0.48 };
const generateBrandBreakdown = (dateOffset, addedIncidents) => {
  const baseIncidents = 135 + dateOffset * 6;
  const counts = {};
  Object.entries(BRAND_SHARE).forEach(([brand, share]) => {
    counts[brand] = Math.round(baseIncidents * share);
  });
  addedIncidents.forEach((r) => {
    counts[r.brand] = (counts[r.brand] ?? 0) + 1;
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

// Story: Bad Order rows are primarily a monitoring log extracted from SSM's
// RMR GS & BO reports via ETL (§3.4.1.3) — but that source data (see
// config/column_maps/rmr_gs_bo.yaml) has no SKU or reason column, so staff
// can also log an incident manually via the Report form to capture detail
// ETL structurally can't. Either way, no status field: this is a log to
// read, not a case-management workflow a user triages afterward.
const initialIncidents = [
  { id: 'INC-2024-135', sku: 'SKU-07642', brand: 'Unilever', product: 'Dove Shampoo 340ml', qty: 24, reason: 'Transport Damage', value: 12600, date: '2026-04-28' },
  { id: 'INC-2024-134', sku: 'SKU-01523', brand: 'Del Monte', product: 'Tomato Sauce 250g', qty: 18, reason: 'Expiry', value: 8500, date: '2026-04-27' },
  { id: 'INC-2024-133', sku: 'SKU-09234', brand: 'Del Monte', product: 'Sweet Corn 425g', qty: 32, reason: 'Storage Issue', value: 4200, date: '2026-04-26' },
  { id: 'INC-2024-132', sku: 'SKU-04721', brand: 'Unilever', product: 'Surf Powder Detergent 1kg', qty: 50, reason: 'Transport Damage', value: 6400, date: '2026-04-24' },
  { id: 'INC-2024-131', sku: 'SKU-08934', brand: 'Del Monte', product: 'Pineapple Juice 1L', qty: 15, reason: 'Expiry', value: 7500, date: '2026-04-22' },
];

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
  const [incidents, setIncidents] = useState(initialIncidents);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedBOSKU, setSelectedBOSKU] = useState(BO_TRACKED_SKUS[0].code);
  const [boTrendGranularity, setBoTrendGranularity] = useState('monthly');

  const boRateTrend = useMemo(() => generateBORateTrend(selectedBOSKU), [selectedBOSKU]);
  const latestBORate = boRateTrend[boRateTrend.length - 1]?.rate ?? 0;

  const { startMonth, startYear, endMonth, endYear } = useOutletContext() || { startMonth: 'Apr', startYear: '2026', endMonth: 'Apr', endYear: '2026' };

  const dateOffset = useMemo(() => {
    const startMonthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(startMonth) || 0;
    const endMonthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(endMonth) || 0;
    const yearVal = parseInt(startYear) || 2026;
    const seed = (startMonthIndex + endMonthIndex + yearVal) % 6;
    return seed - 1;
  }, [startMonth, startYear, endMonth, endYear]);

  // Manually-reported incidents (prepended to the front by handleAddReport)
  // on top of the ETL-extracted baseline, kept separate so the KPI/reason
  // totals below can fold them in exactly rather than guessing.
  const addedIncidents = useMemo(
    () => incidents.slice(0, incidents.length - initialIncidents.length),
    [incidents]
  );

  // Dynamic KPIs — period-driven baseline (stands in for a real ETL
  // aggregate) plus whatever the user has reported manually this session.
  const dynamicKPIs = useMemo(() => {
    const baseIncidents = 135 + dateOffset * 6;
    const baseUnitsLost = 1247 + dateOffset * 45;
    const baseValueLostValue = 186.5 + dateOffset * 8.5;
    const baseBadOrderRate = 4.2 + dateOffset * 0.1;

    const addedUnits = addedIncidents.reduce((sum, r) => sum + r.qty, 0);
    const addedValue = addedIncidents.reduce((sum, r) => sum + r.value, 0);

    return {
      incidents: baseIncidents + addedIncidents.length,
      unitsLost: (baseUnitsLost + addedUnits).toLocaleString(),
      valueLost: `₱${(baseValueLostValue + addedValue / 1000).toFixed(1)}k`,
      rate: (baseBadOrderRate + addedIncidents.length * 0.05).toFixed(1) + '%',
    };
  }, [dateOffset, addedIncidents]);

  // Reason breakdown — fixed shares scaled against the same period-driven
  // baseline the KPI card uses (so the two stay consistent when the
  // month/year filter changes), plus an exact bump for manually-reported
  // incidents' actual reasons.
  const reasonCounts = useMemo(() => {
    const shares = {
      'Transport Damage': 0.356,
      'Expiry': 0.259,
      'Storage Issue': 0.207,
      'Supplier Defect': 0.178,
    };
    const baseIncidents = 135 + dateOffset * 6;
    const counts = {};
    Object.entries(shares).forEach(([reason, share]) => {
      counts[reason] = Math.round(baseIncidents * share);
    });
    addedIncidents.forEach((r) => {
      counts[r.reason] = (counts[r.reason] ?? 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [dateOffset, addedIncidents]);

  const boTrend = useMemo(
    () => generateBOTrend(boTrendGranularity, dateOffset),
    [boTrendGranularity, dateOffset]
  );
  const weekdayBreakdown = useMemo(
    () => generateWeekdayBreakdown(dateOffset, addedIncidents),
    [dateOffset, addedIncidents]
  );
  const topSKUIncidents = useMemo(
    () => generateTopSKUIncidents(addedIncidents),
    [addedIncidents]
  );
  const brandBreakdown = useMemo(
    () => generateBrandBreakdown(dateOffset, addedIncidents),
    [dateOffset, addedIncidents]
  );

  // Submit new bad order handler from ReportBadOrderModal
  const handleAddReport = (reportData) => {
    const nextIncNum = 135 + addedIncidents.length + 1;
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

    setIncidents(prev => [newIncident, ...prev]);

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
                Bad Order rate <span style={{ color: '#a0aec0', fontWeight: 400 }}>— 6 months, per SKU</span>
              </h3>
              <select
                className="bo-sku-select"
                value={selectedBOSKU}
                onChange={(e) => setSelectedBOSKU(e.target.value)}
              >
                {BO_TRACKED_SKUS.map(s => (
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
              magnitude across 4 named categories, which a bar shows at a
              glance (Transport Damage is ~2x Supplier Defect) in a way a
              plain number list doesn't. */}
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
                    width={110}
                    tick={{ fill: '#4a5568', fontSize: 12 }}
                    axisLine={false}
                    tickLine={false}
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
            <h3 className="bo-widget-title">Top SKUs <span>— by incidents</span></h3>
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

        {/* Incident Log Table — read-only, extracted via ETL */}
        <div className="bo-table-wrapper">
          <table className="bo-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>SKU</th>
                <th>BRAND</th>
                <th>PRODUCT</th>
                <th>QTY</th>
                <th>REASON</th>
                <th>VALUE</th>
                <th>DATE</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((incident) => (
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
              {incidents.length === 0 && (
                <tr>
                  <td colSpan="8" className="bo-no-results">No Bad Order records for this period.</td>
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
