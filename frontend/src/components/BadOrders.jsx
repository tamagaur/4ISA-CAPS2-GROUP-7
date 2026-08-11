import React, { useState, useMemo } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Plus, X } from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import './BadOrders.css';

// Helper to extract product name and weight
const parseProductAndWeight = (product) => {
  const weightRegex = /\b(\d+(?:g|ml|L|kg))\b/i;
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

// Chart Trend data: 6 months
const incidentTrendData = [
  { month: 'Nov', incidents: 18 },
  { month: 'Dec', incidents: 22 },
  { month: 'Jan', incidents: 28 },
  { month: 'Feb', incidents: 25 },
  { month: 'Mar', incidents: 31 },
  { month: 'Apr', incidents: 28 },
];

// Initial incident log list matching the screenshot
const initialIncidents = [
  { id: 'INC-2024-135', sku: 'SKU-7642', brand: 'Unilever', product: 'Dove Shampoo 340ml', qty: 24, reason: 'Transport Damage', value: 12600, date: '2026-04-28', status: 'Open' },
  { id: 'INC-2024-134', sku: 'SKU-1523', brand: 'Del Monte', product: 'Tomato Sauce 250g', qty: 18, reason: 'Expiry', value: 8500, date: '2026-04-27', status: 'Resolved' },
  { id: 'INC-2024-133', sku: 'SKU-9234', brand: 'Del Monte', product: 'Sweet Corn 425g', qty: 32, reason: 'Storage Issue', value: 4200, date: '2026-04-26', status: 'Under Investigation' },
  { id: 'INC-2024-132', sku: 'SKU-4721', brand: 'Unilever', product: 'Surf Powder Detergent 1kg', qty: 50, reason: 'Transport Damage', value: 6400, date: '2026-04-24', status: 'Resolved' },
  { id: 'INC-2024-131', sku: 'SKU-8934', brand: 'Del Monte', product: 'Pineapple Juice 1L', qty: 15, reason: 'Expiry', value: 7500, date: '2026-04-22', status: 'Open' },
];

// Simple mapping to lookup Brand/Product Name based on SKU
const skuDatabase = {
  'SKU-7642': { brand: 'Unilever', product: 'Dove Shampoo 340ml' },
  'SKU-4721': { brand: 'Unilever', product: 'Surf Powder Detergent 1kg' },
  'SKU-1523': { brand: 'Del Monte', product: 'Tomato Sauce 250g' },
  'SKU-9234': { brand: 'Del Monte', product: 'Sweet Corn 425g' },
  'SKU-8934': { brand: 'Del Monte', product: 'Pineapple Juice 1L' },
  'SKU-2891': { brand: 'Unilever', product: 'Knorr Cubes 8g' },
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div style={{
        backgroundColor: '#ffffff',
        border: '1px solid #e2e8f0',
        padding: '0.6rem 0.8rem',
        borderRadius: '8px',
        boxShadow: '0 4px 15px rgba(0, 0, 0, 0.05)',
      }}>
        <p style={{ fontWeight: 600, color: '#1a202c', margin: '0 0 0.2rem 0', fontSize: '0.8rem' }}>{label}</p>
        <p style={{ color: '#e53e3e', margin: 0, fontSize: '0.8rem', fontWeight: 600 }}>
          Incidents: {payload[0].value}
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

  // Form State
  const [skuInput, setSkuInput] = useState('');
  const [qtyInput, setQtyInput] = useState('');
  const [reasonInput, setReasonInput] = useState('');
  const [valueInput, setValueInput] = useState('');
  const [notesInput, setNotesInput] = useState('');

  const { selectedMonth, selectedYear } = useOutletContext() || { selectedMonth: 'Apr', selectedYear: '2026' };

  const dateOffset = useMemo(() => {
    const monthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(selectedMonth) || 0;
    const yearVal = parseInt(selectedYear) || 2026;
    const seed = (monthIndex + yearVal) % 5;
    return seed - 4; // 0 offset for Apr 2026 (seed = (3 + 2026) % 5 = 2029 % 5 = 4)
  }, [selectedMonth, selectedYear]);

  // Calculate dynamic KPIs starting from the base values in the prototype
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
    const totalValueLostValue = baseValueLostValue + (addedValue / 1000); // in thousands
    const totalValueLost = `₱${totalValueLostValue.toFixed(1)}k`;
    
    // Target Bad Order Rate
    const badOrderRate = (baseBadOrderRate + (addedIncidents * 0.05)).toFixed(1) + '%';

    return {
      incidents: totalIncidents,
      unitsLost: totalUnitsLost.toLocaleString(),
      valueLost: totalValueLost,
      rate: badOrderRate,
    };
  }, [incidents, dateOffset]);

  // Calculate dynamic Reason Counts starting from base values in the prototype
  const reasonCounts = useMemo(() => {
    const counts = {
      'Transport Damage': 48,
      'Expiry': 35,
      'Storage Issue': 28,
      'Supplier Defect': 24,
    };

    // Add any newly created incidents' reasons
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

  // Status text formatter to put Under Investigation on two lines
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

  // Submit new bad order handler
  const handleSubmit = (e) => {
    e.preventDefault();
    if (!skuInput || !qtyInput || !reasonInput || !valueInput) {
      alert('Please fill in all required fields.');
      return;
    }

    // Auto-resolve brand & product info
    const lookup = skuDatabase[skuInput.toUpperCase().trim()] || { brand: 'Other', product: 'Unknown SKU Product' };
    const nextIncNum = 135 + (incidents.length - initialIncidents.length) + 1;
    const newIncident = {
      id: `INC-2024-${nextIncNum}`,
      sku: skuInput.toUpperCase().trim(),
      brand: lookup.brand,
      product: lookup.product,
      qty: parseInt(qtyInput) || 0,
      reason: reasonInput,
      value: parseFloat(valueInput) || 0,
      date: new Date().toISOString().split('T')[0],
      status: 'Open',
    };

    // Prepend to display newly added items on top
    setIncidents(prev => [newIncident, ...prev]);

    // Reset Form & Close Modal
    setSkuInput('');
    setQtyInput('');
    setReasonInput('');
    setValueInput('');
    setNotesInput('');
    setIsModalOpen(false);
  };

  return (
    <div className="bo-page">
      <div className="bo-content">
        {/* Page Header */}
        <div className="bo-page-header">
          <div className="bo-header-left">
            <h2 className="bo-page-title">Incident log</h2>
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

        {/* Widgets section */}
        <div className="bo-widgets-grid">
          {/* Incident trend widget */}
          <div className="bo-widget">
            <h4 className="bo-widget-title">Incident trend <span>— 6 months</span></h4>
            <div className="bo-chart-wrapper">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={incidentTrendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorIncidents" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#e53e3e" stopOpacity={0.1}/>
                      <stop offset="95%" stopColor="#e53e3e" stopOpacity={0.0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis 
                    dataKey="month" 
                    axisLine={true} 
                    tickLine={true} 
                    tick={{ fill: '#a0aec0', fontSize: 12 }} 
                  />
                  <YAxis 
                    axisLine={true} 
                    tickLine={true} 
                    tick={{ fill: '#a0aec0', fontSize: 12 }} 
                    domain={[0, 32]}
                    ticks={[0, 8, 16, 24, 32]}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Area 
                    type="monotone" 
                    dataKey="incidents" 
                    stroke="#e53e3e" 
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorIncidents)" 
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Top reasons widget */}
          <div className="bo-widget">
            <h4 className="bo-widget-title">Top reasons</h4>
            <div className="bo-reasons-list">
              {reasonCounts.map(([reason, count]) => (
                <div className="bo-reason-item" key={reason}>
                  <span className="bo-reason-name">{reason}</span>
                  <span className="bo-reason-count">{count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Tab row */}
        <div className="bo-tabs">
          {['ALL', 'OPEN', 'RESOLVED', 'UNDER INVESTIGATION'].map(tab => (
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
              {filteredIncidents.map((item) => (
                <tr key={item.id}>
                  <td className="bo-id-cell">{item.id}</td>
                  <td className="bo-sku-cell">{formatSKU(item.sku)}</td>
                  <td>{item.brand}</td>
                  <td className="bo-product-cell">
                    {(() => {
                      const { name, weight } = parseProductAndWeight(item.product);
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
                  <td className="bo-qty-cell">{item.qty}</td>
                  <td>{item.reason}</td>
                  <td className="bo-value-cell">₱{item.value.toLocaleString()}</td>
                  <td className="bo-date-cell">{item.date}</td>
                  <td>
                    <span className={getStatusBadgeClass(item.status)}>
                      {renderStatusText(item.status)}
                    </span>
                  </td>
                </tr>
              ))}
              {filteredIncidents.length === 0 && (
                <tr>
                  <td colSpan="9" className="bo-no-results">No incidents found matching your filter.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Report Bad Order Modal Form Overlay */}
      {isModalOpen && (
        <div className="bo-modal-overlay" onClick={() => setIsModalOpen(false)}>
          <div className="bo-modal-container" onClick={(e) => e.stopPropagation()}>
            <div className="bo-modal-header">
              <h3 className="bo-modal-title">Report Bad Order</h3>
              <button className="bo-modal-close-btn" onClick={() => setIsModalOpen(false)} aria-label="Close modal">
                <X size={18} />
              </button>
            </div>
            <div className="bo-modal-body">
              <form className="bo-form" onSubmit={handleSubmit}>
                <div className="bo-form-group">
                  <label className="bo-label" htmlFor="sku-select">SKU</label>
                  <input
                    id="sku-select"
                    type="text"
                    placeholder="e.g., SKU-1847"
                    value={skuInput}
                    onChange={(e) => setSkuInput(e.target.value)}
                    className="bo-input"
                    required
                  />
                </div>
                <div className="bo-form-group">
                  <label className="bo-label" htmlFor="qty-input">Quantity</label>
                  <input
                    id="qty-input"
                    type="number"
                    placeholder="e.g., 24"
                    value={qtyInput}
                    onChange={(e) => setQtyInput(e.target.value)}
                    className="bo-input"
                    required
                  />
                </div>
                <div className="bo-form-group">
                  <label className="bo-label" htmlFor="reason-select">Reason</label>
                  <select
                    id="reason-select"
                    value={reasonInput}
                    onChange={(e) => setReasonInput(e.target.value)}
                    className="bo-select"
                    required
                  >
                    <option value="" disabled>Select a reason</option>
                    <option value="Transport Damage">Transport Damage</option>
                    <option value="Expiry">Expiry</option>
                    <option value="Storage Issue">Storage Issue</option>
                    <option value="Supplier Defect">Supplier Defect</option>
                  </select>
                </div>
                <div className="bo-form-group">
                  <label className="bo-label" htmlFor="value-input">Value (₱)</label>
                  <input
                    id="value-input"
                    type="number"
                    placeholder="e.g., 12600"
                    value={valueInput}
                    onChange={(e) => setValueInput(e.target.value)}
                    className="bo-input"
                    required
                  />
                </div>
                <div className="bo-form-group">
                  <label className="bo-label" htmlFor="notes-textarea">Notes</label>
                  <textarea
                    id="notes-textarea"
                    placeholder="Additional details..."
                    value={notesInput}
                    onChange={(e) => setNotesInput(e.target.value)}
                    className="bo-textarea"
                  />
                </div>
                <div className="bo-modal-actions">
                  <button type="button" className="bo-btn bo-btn-cancel" onClick={() => setIsModalOpen(false)}>
                    Cancel
                  </button>
                  <button type="submit" className="bo-btn bo-btn-submit">
                    Submit
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default BadOrders;
