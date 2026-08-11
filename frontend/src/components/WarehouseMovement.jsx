import React, { useState, useMemo } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import './WarehouseMovement.css';

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

// Mock data: 6-month movement log chart
const movementChartData = [
  { month: 'Nov', received: 38000, dispatched: 35000 },
  { month: 'Dec', received: 41000, dispatched: 39000 },
  { month: 'Jan', received: 44000, dispatched: 40000 },
  { month: 'Feb', received: 46000, dispatched: 43000 },
  { month: 'Mar', received: 48000, dispatched: 44000 },
  { month: 'Apr', received: 42000, dispatched: 37000 },
];

// Mock data: movement log table
const mockMovementLog = [
  { id: 1, date: '2026-04-22', sku: 'SKU-4721', product: 'Surf Powder Detergent 1kg', type: 'RECEIVED', qty: 500, ref: 'PO-2026-0412', supplier: 'Unilever Philippines' },
  { id: 2, date: '2026-04-22', sku: 'SKU-8934', product: 'Pineapple Juice 1L', type: 'DISPATCHED', qty: 320, ref: 'SO-2026-0891', supplier: 'Del Monte Philippines' },
  { id: 3, date: '2026-04-21', sku: 'SKU-2891', product: 'Knorr Cubes 8g', type: 'RECEIVED', qty: 1200, ref: 'PO-2026-0410', supplier: 'Unilever Philippines' },
  { id: 4, date: '2026-04-21', sku: 'SKU-5632', product: 'Sweet Corn Kernel 425g', type: 'DISPATCHED', qty: 180, ref: 'SO-2026-0889', supplier: 'Del Monte Philippines' },
  { id: 5, date: '2026-04-20', sku: 'SKU-7821', product: 'Dove Shampoo 340ml', type: 'RECEIVED', qty: 400, ref: 'PO-2026-0408', supplier: 'Unilever Philippines' },
  { id: 6, date: '2026-04-20', sku: 'SKU-3421', product: 'Tomato Sauce 250g', type: 'DISPATCHED', qty: 650, ref: 'SO-2026-0887', supplier: 'Del Monte Philippines' },
  { id: 7, date: '2026-04-19', sku: 'SKU-9012', product: 'Lux Bar Soap 135g', type: 'RECEIVED', qty: 800, ref: 'PO-2026-0405', supplier: 'Unilever Philippines' },
  { id: 8, date: '2026-04-19', sku: 'SKU-1234', product: 'Fruit Cocktail 432g', type: 'DISPATCHED', qty: 275, ref: 'SO-2026-0885', supplier: 'Del Monte Philippines' },
  { id: 9, date: '2026-04-18', sku: 'SKU-6543', product: 'Creamsilk Conditioner 180ml', type: 'RECEIVED', qty: 600, ref: 'PO-2026-0402', supplier: 'Unilever Philippines' },
  { id: 10, date: '2026-04-18', sku: 'SKU-4567', product: 'Spaghetti Sauce 500g', type: 'DISPATCHED', qty: 420, ref: 'SO-2026-0883', supplier: 'Del Monte Philippines' },
];

// Mock data: SKU Inventory (matching Figma prototype)
const mockInventory = [
  { id: 1, sku: 'SKU-4721', brand: 'Unilever', product: 'Surf Powder Detergent 1kg', currentStock: 45, receivedMts: 1200, dispatchedMts: 1080, status: 'CRITICAL' },
  { id: 2, sku: 'SKU-8934', brand: 'Del Monte', product: 'Pineapple Juice 1L', currentStock: 12, receivedMts: 950, dispatchedMts: 1100, status: 'CRITICAL' },
  { id: 3, sku: 'SKU-2891', brand: 'Unilever', product: 'Knorr Cubes 8g', currentStock: 78, receivedMts: 2100, dispatchedMts: 2240, status: 'LOW' },
  { id: 4, sku: 'SKU-1523', brand: 'Del Monte', product: 'Tomato Sauce 250g', currentStock: 89, receivedMts: 1300, dispatchedMts: 1420, status: 'LOW' },
  { id: 5, sku: 'SKU-7642', brand: 'Unilever', product: 'Dove Shampoo 340ml', currentStock: 66, receivedMts: 880, dispatchedMts: 1010, status: 'LOW' },
  { id: 6, sku: 'SKU-9234', brand: 'Del Monte', product: 'Sweet Corn 425g', currentStock: 102, receivedMts: 1450, dispatchedMts: 1380, status: 'IN STOCK' },
];

// Mock data: Capacity Monitor (matching Figma prototype)
const warehouseCapacity = {
  totalCapacity: 80000,
  currentStock: 54400,
  availableSpace: 25600,
  utilizationPct: 68,
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div style={{
        backgroundColor: '#ffffff',
        border: '1px solid #e2e8f0',
        padding: '0.8rem 1rem',
        borderRadius: '8px',
        boxShadow: '0 4px 15px rgba(0, 0, 0, 0.05)',
      }}>
        <p style={{ fontWeight: 600, color: '#1a202c', margin: '0 0 0.4rem 0', fontSize: '0.85rem' }}>{label}</p>
        {payload.map((entry, index) => (
          <p key={index} style={{ color: entry.color, margin: '0.2rem 0', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, backgroundColor: entry.color }}></span>
            {entry.name}: {entry.value.toLocaleString()}
          </p>
        ))}
      </div>
    );
  }
  return null;
};

const WarehouseMovement = () => {
  const [activeTab, setActiveTab] = useState('MOVEMENT_LOG');
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('ALL');

  const { selectedMonth, selectedYear } = useOutletContext() || { selectedMonth: 'Apr', selectedYear: '2026' };

  // Calculate dynamic movement values based on selectedMonth/selectedYear
  const dynamicData = useMemo(() => {
    const monthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(selectedMonth) || 0;
    const yearVal = parseInt(selectedYear) || 2026;
    const seed = (monthIndex + yearVal) % 6;
    const diff = seed - 1; // 0 offset for Apr 2026

    return {
      received: 42000 + diff * 1500,
      dispatched: 37000 + diff * 1200,
      netChange: 5000 + diff * 300,
      turnover: (2.3 + diff * 0.1).toFixed(1),
      utilizationPct: 68 + diff * 3,
    };
  }, [selectedMonth, selectedYear]);

  const dynamicCapacity = useMemo(() => {
    const totalCapacity = 80000;
    const utilizationPct = dynamicData.utilizationPct;
    const currentStock = Math.round((totalCapacity * utilizationPct) / 100);
    const availableSpace = totalCapacity - currentStock;

    return {
      totalCapacity,
      currentStock,
      availableSpace,
      utilizationPct,
    };
  }, [dynamicData]);

  // Movement log filtering
  const filteredLog = useMemo(() => {
    return mockMovementLog.filter(item => {
      const matchesSearch = searchQuery === '' ||
        item.sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.ref.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesType = typeFilter === 'ALL' || item.type === typeFilter;
      return matchesSearch && matchesType;
    });
  }, [searchQuery, typeFilter]);

  // Inventory status helpers
  const getInvStatusClass = (status) => {
    switch (status) {
      case 'IN STOCK': return 'wm-type-badge wm-type-received';
      case 'LOW': return 'wm-type-badge wm-type-low';
      case 'CRITICAL': return 'wm-type-badge wm-type-dispatched';
      default: return 'wm-type-badge';
    }
  };

  const renderMovementLogTab = () => (
    <>
      {/* KPI Cards */}
      <div className="wm-summary-grid">
        <div className="wm-summary-card wm-card-received">
          <span className="wm-card-label">RECEIVED</span>
          <span className="wm-card-value">{dynamicData.received.toLocaleString()}</span>
          <span className="wm-card-desc">units this month</span>
        </div>
        <div className="wm-summary-card wm-card-dispatched">
          <span className="wm-card-label">DISPATCHED</span>
          <span className="wm-card-value">{dynamicData.dispatched.toLocaleString()}</span>
          <span className="wm-card-desc">units sent out</span>
        </div>
        <div className="wm-summary-card wm-card-net">
          <span className="wm-card-label">NET CHANGE</span>
          <span className="wm-card-value">{(dynamicData.netChange >= 0 ? '+' : '') + dynamicData.netChange.toLocaleString()}</span>
          <span className="wm-card-desc positive">↑ 13% MoM</span>
        </div>
        <div className="wm-summary-card wm-card-turnover">
          <span className="wm-card-label">TURNOVER RATE</span>
          <span className="wm-card-value">{dynamicData.turnover}×</span>
          <span className="wm-card-desc">cycles / month</span>
        </div>
      </div>

      {/* Chart */}
      <div className="wm-chart-container">
        <h4 className="wm-chart-title">Movement Log <span>— 6 Months</span></h4>
        <div className="wm-chart-wrapper">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={movementChartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
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
                tick={{ fill: '#a0aec0', fontSize: 11 }}
                tickFormatter={(val) => (val / 1000) + 'k'}
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="received" name="received" fill="#38a169" radius={[2, 2, 0, 0]} barSize={28} />
              <Bar dataKey="dispatched" name="dispatched" fill="#e53e3e" radius={[2, 2, 0, 0]} barSize={28} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="wm-chart-legend">
          <div className="wm-legend-item">
            <span className="wm-legend-color" style={{ backgroundColor: '#38a169' }}></span>
            <span>received</span>
          </div>
          <div className="wm-legend-item">
            <span className="wm-legend-color" style={{ backgroundColor: '#e53e3e' }}></span>
            <span>dispatched</span>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="wm-filters-row">
        <div className="wm-search-wrapper">
          <svg className="wm-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input
            type="text"
            placeholder="Search by SKU, product, or reference..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="wm-search-input"
          />
        </div>

        <div className="wm-type-toggle-group">
          {['ALL', 'RECEIVED', 'DISPATCHED'].map(type => (
            <button
              key={type}
              className={`wm-type-toggle-btn ${typeFilter === type ? 'active' : ''}`}
              onClick={() => setTypeFilter(type)}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      {/* Movement Log Table */}
      <div className="wm-table-wrapper">
        <table className="wm-table">
          <thead>
            <tr>
              <th>DATE</th>
              <th>SKU</th>
              <th>PRODUCT</th>
              <th>TYPE</th>
              <th>QTY</th>
              <th>REFERENCE</th>
              <th>SUPPLIER</th>
            </tr>
          </thead>
          <tbody>
            {filteredLog.map((item) => (
              <tr key={item.id}>
                <td className="wm-date-cell">{item.date}</td>
                <td className="wm-sku-cell">{formatSKU(item.sku)}</td>
                <td className="wm-product-cell">
                  {(() => {
                    const { name, weight } = parseProductAndWeight(item.product);
                    return (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <span className="wm-product-name">{name}</span>
                        {weight && (
                          <span className="wm-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                            {weight}
                          </span>
                        )}
                      </div>
                    );
                  })()}
                </td>
                <td>
                  <span className={`wm-type-badge ${item.type === 'RECEIVED' ? 'wm-type-received' : 'wm-type-dispatched'}`}>
                    {item.type}
                  </span>
                </td>
                <td className="wm-qty-cell">{item.qty.toLocaleString()}</td>
                <td className="wm-ref-cell">{item.ref}</td>
                <td>{item.supplier}</td>
              </tr>
            ))}
            {filteredLog.length === 0 && (
              <tr>
                <td colSpan="7" className="wm-no-results">No movement records found matching your filters.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );

  const renderSKUInventoryTab = () => (
    <>
      {/* Same KPI Cards as Movement Log */}
      <div className="wm-summary-grid">
        <div className="wm-summary-card wm-card-received">
          <span className="wm-card-label">RECEIVED</span>
          <span className="wm-card-value">{dynamicData.received.toLocaleString()}</span>
          <span className="wm-card-desc">units this month</span>
        </div>
        <div className="wm-summary-card wm-card-dispatched">
          <span className="wm-card-label">DISPATCHED</span>
          <span className="wm-card-value">{dynamicData.dispatched.toLocaleString()}</span>
          <span className="wm-card-desc">units sent out</span>
        </div>
        <div className="wm-summary-card wm-card-net">
          <span className="wm-card-label">NET CHANGE</span>
          <span className="wm-card-value">{(dynamicData.netChange >= 0 ? '+' : '') + dynamicData.netChange.toLocaleString()}</span>
          <span className="wm-card-desc positive">↑ 13% MoM</span>
        </div>
        <div className="wm-summary-card wm-card-turnover">
          <span className="wm-card-label">TURNOVER RATE</span>
          <span className="wm-card-value">{dynamicData.turnover}×</span>
          <span className="wm-card-desc">cycles / month</span>
        </div>
      </div>

      {/* Section Header */}
      <div className="wm-section-header">
        <h3 className="wm-section-title">Current SKU Inventory Levels</h3>
        <p className="wm-section-subtitle">Stock levels reflect last order deductions and recent movements.</p>
      </div>

      {/* Inventory Table */}
      <div className="wm-table-wrapper">
        <table className="wm-table">
          <thead>
            <tr>
              <th>SKU</th>
              <th>BRAND</th>
              <th>PRODUCT</th>
              <th>CURRENT STOCK</th>
              <th>RECEIVED (MTS)</th>
              <th>DISPATCHED (MTS)</th>
              <th>STATUS</th>
            </tr>
          </thead>
          <tbody>
            {mockInventory.map((item) => (
              <tr key={item.id}>
                <td className="wm-sku-cell">{formatSKU(item.sku)}</td>
                <td>{item.brand}</td>
                <td className="wm-product-cell">
                  {(() => {
                    const { name, weight } = parseProductAndWeight(item.product);
                    return (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <span className="wm-product-name">{name}</span>
                        {weight && (
                          <span className="wm-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                            {weight}
                          </span>
                        )}
                      </div>
                    );
                  })()}
                </td>
                <td className="wm-qty-cell">{item.currentStock}</td>
                <td className="wm-qty-cell">{item.receivedMts.toLocaleString()}</td>
                <td className="wm-qty-cell">{item.dispatchedMts.toLocaleString()}</td>
                <td>
                  <span className={getInvStatusClass(item.status)}>{item.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );

  const renderCapacityMonitorTab = () => (
    <>
      {/* Same KPI Cards as Movement Log */}
      <div className="wm-summary-grid">
        <div className="wm-summary-card wm-card-received">
          <span className="wm-card-label">RECEIVED</span>
          <span className="wm-card-value">{dynamicData.received.toLocaleString()}</span>
          <span className="wm-card-desc">units this month</span>
        </div>
        <div className="wm-summary-card wm-card-dispatched">
          <span className="wm-card-label">DISPATCHED</span>
          <span className="wm-card-value">{dynamicData.dispatched.toLocaleString()}</span>
          <span className="wm-card-desc">units sent out</span>
        </div>
        <div className="wm-summary-card wm-card-net">
          <span className="wm-card-label">NET CHANGE</span>
          <span className="wm-card-value">{(dynamicData.netChange >= 0 ? '+' : '') + dynamicData.netChange.toLocaleString()}</span>
          <span className="wm-card-desc positive">↑ 13% MoM</span>
        </div>
        <div className="wm-summary-card wm-card-turnover">
          <span className="wm-card-label">TURNOVER RATE</span>
          <span className="wm-card-value">{dynamicData.turnover}×</span>
          <span className="wm-card-desc">cycles / month</span>
        </div>
      </div>

      {/* Capacity Utilization Section */}
      <div className="wm-capacity-section">
        <h3 className="wm-section-title">Warehouse capacity utilization</h3>

        <div className="wm-capacity-bar-row">
          <div className="wm-capacity-bar-area">
            <div className="wm-cap-bar-large-wrapper">
              <div
                className="wm-cap-bar-large-fill"
                style={{ width: `${dynamicCapacity.utilizationPct}%` }}
              ></div>
            </div>
            <div className="wm-cap-bar-labels">
              <span>0%</span>
              <span>{dynamicCapacity.utilizationPct}% utilized</span>
              <span>100%</span>
            </div>
          </div>
          <div className="wm-capacity-pct-display">
            <span className="wm-capacity-pct-value">{dynamicCapacity.utilizationPct}%</span>
            <span className="wm-capacity-pct-label">of total capacity</span>
          </div>
        </div>

        {/* Capacity Stats */}
        <div className="wm-capacity-stats">
          <div className="wm-cap-stat">
            <span className="wm-card-label">TOTAL CAPACITY</span>
            <span className="wm-cap-stat-value">{dynamicCapacity.totalCapacity.toLocaleString()}</span>
            <span className="wm-card-desc">units</span>
          </div>
          <div className="wm-cap-stat">
            <span className="wm-card-label">CURRENT STOCK</span>
            <span className="wm-cap-stat-value">{dynamicCapacity.currentStock.toLocaleString()}</span>
            <span className="wm-card-desc">units</span>
          </div>
          <div className="wm-cap-stat">
            <span className="wm-card-label">AVAILABLE SPACE</span>
            <span className="wm-cap-stat-value">{dynamicCapacity.availableSpace.toLocaleString()}</span>
            <span className="wm-card-desc">units</span>
          </div>
        </div>
      </div>
    </>
  );

  return (
    <div className="wm-page">
      <div className="wm-content">
        {/* Page Header */}
        <div className="wm-page-header">
          <h2 className="wm-page-title">Stock in motion</h2>
          <p className="wm-page-subtitle">
            Track all stock coming in, going out, and current storage capacity across the Urdaneta warehouse.
          </p>
        </div>

        {/* Tabs */}
        <div className="wm-tabs">
          <button
            className={`wm-tab ${activeTab === 'MOVEMENT_LOG' ? 'active' : ''}`}
            onClick={() => setActiveTab('MOVEMENT_LOG')}
          >
            MOVEMENT LOG
          </button>
          <button
            className={`wm-tab ${activeTab === 'SKU_INVENTORY' ? 'active' : ''}`}
            onClick={() => setActiveTab('SKU_INVENTORY')}
          >
            SKU INVENTORY
          </button>
          <button
            className={`wm-tab ${activeTab === 'CAPACITY_MONITOR' ? 'active' : ''}`}
            onClick={() => setActiveTab('CAPACITY_MONITOR')}
          >
            CAPACITY MONITOR
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === 'MOVEMENT_LOG' && renderMovementLogTab()}
        {activeTab === 'SKU_INVENTORY' && renderSKUInventoryTab()}
        {activeTab === 'CAPACITY_MONITOR' && renderCapacityMonitorTab()}
      </div>
    </div>
  );
};

export default WarehouseMovement;
