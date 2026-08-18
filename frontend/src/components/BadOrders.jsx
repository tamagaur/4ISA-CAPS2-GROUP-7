import React, { useState, useMemo } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Plus } from 'lucide-react';
import {
  LineChart,
  Line,
  ReferenceLine,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import ReportBadOrderModal from './ReportBadOrderModal';
import { COLORS } from '../theme/colors';
import './BadOrders.css';

const BO_RATE_TARGET = 3; // %, manuscript §3.4.1.3 target threshold

// SKUs with recorded incidents — the only ones a per-SKU rate is honest to show
const BO_TRACKED_SKUS = [
  { code: 'SKU-07642', product: 'Dove Shampoo 340ml' },
  { code: 'SKU-01523', product: 'Tomato Sauce 250g' },
  { code: 'SKU-09234', product: 'Sweet Corn 425g' },
  { code: 'SKU-04721', product: 'Surf Powder Detergent 1kg' },
  { code: 'SKU-08934', product: 'Pineapple Juice 1L' },
];

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

// Initial incident log list matching the prototype
const initialIncidents = [
  { id: 'INC-2024-135', sku: 'SKU-07642', brand: 'Unilever', product: 'Dove Shampoo 340ml', qty: 24, reason: 'Transport Damage', value: 12600, date: '2026-04-28', status: 'Open' },
  { id: 'INC-2024-134', sku: 'SKU-01523', brand: 'Del Monte', product: 'Tomato Sauce 250g', qty: 18, reason: 'Expiry', value: 8500, date: '2026-04-27', status: 'Resolved' },
  { id: 'INC-2024-133', sku: 'SKU-09234', brand: 'Del Monte', product: 'Sweet Corn 425g', qty: 32, reason: 'Storage Issue', value: 4200, date: '2026-04-26', status: 'Under Investigation' },
  { id: 'INC-2024-132', sku: 'SKU-04721', brand: 'Unilever', product: 'Surf Powder Detergent 1kg', qty: 50, reason: 'Transport Damage', value: 6400, date: '2026-04-24', status: 'Resolved' },
  { id: 'INC-2024-131', sku: 'SKU-08934', brand: 'Del Monte', product: 'Pineapple Juice 1L', qty: 15, reason: 'Expiry', value: 7500, date: '2026-04-22', status: 'Open' },
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
  const [activeTab, setActiveTab] = useState('ALL');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedBOSKU, setSelectedBOSKU] = useState(BO_TRACKED_SKUS[0].code);

  const boRateTrend = useMemo(() => generateBORateTrend(selectedBOSKU), [selectedBOSKU]);
  const latestBORate = boRateTrend[boRateTrend.length - 1]?.rate ?? 0;

  const { selectedMonth, selectedYear } = useOutletContext() || { selectedMonth: 'Apr', selectedYear: '2026' };

  const dateOffset = useMemo(() => {
    const monthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(selectedMonth) || 0;
    const yearVal = parseInt(selectedYear) || 2026;
    const seed = (monthIndex + yearVal) % 5;
    return seed - 4;
  }, [selectedMonth, selectedYear]);

  // Dynamic KPIs calculation
  const dynamicKPIs = useMemo(() => {
    const addedIncidents = incidents.length - initialIncidents.length;
    const addedUnits = incidents.reduce((sum, item, idx) => idx < addedIncidents ? sum + item.qty : sum, 0);
    const addedValue = incidents.reduce((sum, item, idx) => idx < addedIncidents ? sum + item.value : sum, 0);

    const baseIncidents = 135 + dateOffset * 6;
    const baseUnitsLost = 1247 + dateOffset * 45;
    const baseValueLostValue = 186.5 + dateOffset * 8.5;
    const baseBadOrderRate = 4.2 + dateOffset * 0.1;

    const totalIncidents = baseIncidents + addedIncidents;
    const totalUnitsLost = baseUnitsLost + addedUnits;
    const totalValueLostValue = baseValueLostValue + (addedValue / 1000);
    const totalValueLost = `₱${totalValueLostValue.toFixed(1)}k`;
    const badOrderRate = (baseBadOrderRate + (addedIncidents * 0.05)).toFixed(1) + '%';

    return {
      incidents: totalIncidents,
      unitsLost: totalUnitsLost.toLocaleString(),
      valueLost: totalValueLost,
      rate: badOrderRate,
    };
  }, [incidents, dateOffset]);

  // Dynamic Reason Counts
  const reasonCounts = useMemo(() => {
    const counts = {
      'Transport Damage': 48,
      'Expiry': 35,
      'Storage Issue': 28,
      'Supplier Defect': 24,
    };

    const addedIncidents = incidents.length - initialIncidents.length;
    for (let i = 0; i < addedIncidents; i++) {
      const reason = incidents[i].reason;
      if (counts[reason] !== undefined) {
        counts[reason] += 1;
      }
    }

    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [incidents]);

  // Filter incidents list based on active tab
  const filteredIncidents = useMemo(() => {
    if (activeTab === 'ALL') return incidents;
    if (activeTab === 'OPEN') return incidents.filter(i => i.status.toUpperCase() === 'OPEN');
    if (activeTab === 'RESOLVED') return incidents.filter(i => i.status.toUpperCase() === 'RESOLVED');
    if (activeTab === 'UNDER INVESTIGATION') return incidents.filter(i => i.status.toUpperCase() === 'UNDER INVESTIGATION');
    return incidents;
  }, [incidents, activeTab]);

  // Badge class helper
  const getStatusBadgeClass = (status) => {
    const cleanStatus = status.toUpperCase();
    if (cleanStatus === 'OPEN') return 'bo-status-badge bo-status-open';
    if (cleanStatus === 'RESOLVED') return 'bo-status-badge bo-status-resolved';
    return 'bo-status-badge bo-status-investigating';
  };

  const renderStatusText = (status) => {
    if (status.toUpperCase() === 'UNDER INVESTIGATION') {
      return (
        <>
          Under<br />Investigation
        </>
      );
    }
    return status;
  };

  // Submit new bad order handler from ReportBadOrderModal
  const handleAddReport = (reportData) => {
    const nextIncNum = 135 + (incidents.length - initialIncidents.length) + 1;
    const newIncident = {
      id: `INC-2024-${nextIncNum}`,
      sku: reportData.sku,
      brand: reportData.brand,
      product: reportData.product,
      qty: reportData.qty,
      reason: reportData.reason,
      value: reportData.value,
      date: new Date().toISOString().split('T')[0],
      status: 'Open',
    };

    setIncidents(prev => [newIncident, ...prev]);
  };

  return (
    <div className="bo-page">
      <div className="bo-content">
        {/* Page Header */}
        <div className="bo-page-header">
          <div className="bo-header-left">
            <h2 className="bo-page-title">Incident <span>log</span></h2>
            <p className="bo-page-subtitle">
              Damaged, expired, or defective stock. These reports sharpen forecast accuracy — consistent logging improves future SARIMA & LP optimization.
            </p>
          </div>
          <button className="bo-report-btn" onClick={() => setIsModalOpen(true)}>
            <Plus size={16} />
            Report
          </button>
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

          {/* Top Reasons Widget */}
          <div className="bo-widget">
            <h3 className="bo-widget-title">Top reasons</h3>
            <div className="bo-reasons-list">
              {reasonCounts.map(([reasonName, count]) => (
                <div key={reasonName} className="bo-reason-item">
                  <span className="bo-reason-name">{reasonName}</span>
                  <span className="bo-reason-count">{count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Filter Tabs */}
        <div className="bo-tabs">
          {['ALL', 'OPEN', 'RESOLVED', 'UNDER INVESTIGATION'].map((tab) => (
            <button
              key={tab}
              className={`bo-tab ${activeTab === tab ? 'active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Incident Table */}
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
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {filteredIncidents.map((incident) => (
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
                  <td>
                    <span className={getStatusBadgeClass(incident.status)}>
                      {renderStatusText(incident.status)}
                    </span>
                  </td>
                </tr>
              ))}
              {filteredIncidents.length === 0 && (
                <tr>
                  <td colSpan="9" className="bo-no-results">No incident reports found.</td>
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
