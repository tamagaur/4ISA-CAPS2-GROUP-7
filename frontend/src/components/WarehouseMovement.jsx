import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Search, Building, Calendar, Clock, X } from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import DateFilter from './DateFilter';
import './WarehouseMovement.css';

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

// Mock data: SKU Inventory
const mockInventory = [
  { id: 1, sku: 'SKU-4721', brand: 'Unilever', product: 'Surf Powder Detergent 1kg', currentStock: 45, receivedMts: 1200, dispatchedMts: 1080, status: 'CRITICAL' },
  { id: 2, sku: 'SKU-8934', brand: 'Del Monte', product: 'Pineapple Juice 1L', currentStock: 12, receivedMts: 950, dispatchedMts: 1100, status: 'CRITICAL' },
  { id: 3, sku: 'SKU-2891', brand: 'Unilever', product: 'Knorr Cubes 8g', currentStock: 78, receivedMts: 2100, dispatchedMts: 2240, status: 'LOW' },
  { id: 4, sku: 'SKU-1523', brand: 'Del Monte', product: 'Tomato Sauce 250g', currentStock: 89, receivedMts: 1300, dispatchedMts: 1420, status: 'LOW' },
  { id: 5, sku: 'SKU-7642', brand: 'Unilever', product: 'Dove Shampoo 340ml', currentStock: 66, receivedMts: 880, dispatchedMts: 1010, status: 'LOW' },
  { id: 6, sku: 'SKU-9234', brand: 'Del Monte', product: 'Sweet Corn 425g', currentStock: 102, receivedMts: 1450, dispatchedMts: 1380, status: 'IN STOCK' },
];

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
  const [selectedSupplier, setSelectedSupplier] = useState('ALL');
  const [selectedDateRange, setSelectedDateRange] = useState('CURRENT_PERIOD');
  const [isComboboxOpen, setIsComboboxOpen] = useState(false);
  const [activeFilterChip, setActiveFilterChip] = useState(null);

  const dropdownRef = useRef(null);

  const { startMonth, startYear, endMonth, endYear } = useOutletContext() || { startMonth: 'Apr', startYear: '2026', endMonth: 'Apr', endYear: '2026' };

  // Persistent Recently Searched history (Max 5)
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_recent_warehouse_searches');
      return saved ? JSON.parse(saved) : [
        { sku: 'SKU-4721', product: 'Surf Powder Detergent 1kg', ref: 'PO-2026-0412', supplier: 'Unilever Philippines' },
        { sku: 'SKU-8934', product: 'Pineapple Juice 1L', ref: 'SO-2026-0891', supplier: 'Del Monte Philippines' }
      ];
    } catch {
      return [];
    }
  });

  // Close combobox on click outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsComboboxOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Calculate dynamic movement values based on startMonth/endMonth
  const dynamicData = useMemo(() => {
    const startMonthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(startMonth) || 0;
    const endMonthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(endMonth) || 0;
    const yearVal = parseInt(startYear) || 2026;
    const seed = (startMonthIndex + endMonthIndex + yearVal) % 6;
    const diff = seed - 1; // 0 offset for Apr 2026

    return {
      received: 42000 + diff * 1500,
      dispatched: 37000 + diff * 1200,
      netChange: 5000 + diff * 300,
      turnover: (2.3 + diff * 0.1).toFixed(1),
      utilizationPct: 68 + diff * 3,
    };
  }, [startMonth, startYear, endMonth, endYear]);

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

  // Handle selecting a combobox suggestion item
  const handleSelectSuggestion = (item) => {
    setActiveFilterChip(item);
    setSearchQuery(item.product || item.sku || item.ref);
    setIsComboboxOpen(false);

    // Save to recent searches (prepend, deduplicate, keep last 5)
    const newEntry = {
      sku: item.sku,
      product: item.product,
      ref: item.ref,
      supplier: item.supplier
    };
    const updated = [newEntry, ...recentSearches.filter(s => s.sku !== item.sku || s.ref !== item.ref)].slice(0, 5);
    setRecentSearches(updated);
    localStorage.setItem('san2_recent_warehouse_searches', JSON.stringify(updated));
  };

  const handleClearFilterChip = () => {
    setActiveFilterChip(null);
    setSearchQuery('');
  };

  // List of suppliers
  const suppliersList = ['ALL', ...Array.from(new Set(mockMovementLog.map(i => i.supplier)))];

  // Combobox Live Suggestions matching search query
  const searchSuggestions = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase();
    return mockMovementLog.filter(item => 
      item.sku.toLowerCase().includes(q) ||
      item.product.toLowerCase().includes(q) ||
      item.ref.toLowerCase().includes(q) ||
      item.supplier.toLowerCase().includes(q)
    );
  }, [searchQuery]);

  // Movement log filtering
  const filteredLog = useMemo(() => {
    return mockMovementLog.filter(item => {
      // Search / Chip filter
      const matchesSearch = searchQuery.trim() === '' ||
        item.sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.ref.toLowerCase().includes(searchQuery.toLowerCase());

      // Type filter (ALL / RECEIVED / DISPATCHED)
      const matchesType = typeFilter === 'ALL' || item.type === typeFilter;

      // Supplier filter
      const matchesSupplier = selectedSupplier === 'ALL' || item.supplier === selectedSupplier;

      // Date Range filter
      let matchesDate = true;
      if (selectedDateRange === 'LAST_7_DAYS') {
        matchesDate = item.date >= '2026-04-18';
      } else if (selectedDateRange === 'LAST_30_DAYS') {
        matchesDate = item.date >= '2026-04-01';
      }

      return matchesSearch && matchesType && matchesSupplier && matchesDate;
    });
  }, [searchQuery, typeFilter, selectedSupplier, selectedDateRange]);

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
          <span className="wm-card-label">NET MOVEMENT</span>
          <span className="wm-card-value">+{dynamicData.netChange.toLocaleString()}</span>
          <span className="wm-card-desc">stock delta</span>
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
              <Bar dataKey="received" name="received" fill="#2E9E5B" radius={[2, 2, 0, 0]} barSize={28} />
              <Bar dataKey="dispatched" name="dispatched" fill="#14919B" radius={[2, 2, 0, 0]} barSize={28} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="wm-chart-legend">
          <div className="wm-legend-item">
            <span className="wm-legend-color" style={{ backgroundColor: '#2E9E5B' }}></span>
            <span>received</span>
          </div>
          <div className="wm-legend-item">
            <span className="wm-legend-color" style={{ backgroundColor: '#14919B' }}></span>
            <span>dispatched</span>
          </div>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="wm-filters-row">
        {/* Search Combobox */}
        <div className="wm-combobox-container" ref={dropdownRef}>
          <div className="wm-search-wrapper">
            <Search className="wm-search-icon" size={18} />
            <input
              type="text"
              placeholder="Search by SKU, product, or reference..."
              value={searchQuery}
              onFocus={() => setIsComboboxOpen(true)}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setIsComboboxOpen(true);
                if (!e.target.value) setActiveFilterChip(null);
              }}
              className="wm-search-input"
            />
            {searchQuery && (
              <button className="wm-input-clear-btn" onClick={handleClearFilterChip}>
                <X size={14} />
              </button>
            )}
          </div>

          {/* Combobox Panel */}
          {isComboboxOpen && (
            <div className="wm-combobox-dropdown">
              {searchQuery.trim() !== '' ? (
                /* Live Suggestions */
                <div className="wm-combobox-section">
                  <div className="wm-section-header">
                    <span>SUGGESTIONS ({searchSuggestions.length})</span>
                  </div>
                  {searchSuggestions.length > 0 ? (
                    searchSuggestions.map((item) => (
                      <div 
                        key={item.id} 
                        className="wm-suggestion-row"
                        onClick={() => handleSelectSuggestion(item)}
                      >
                        <div className="wm-row-left">
                          <span className="wm-row-sku">{formatSKU(item.sku)}</span>
                          <span className="wm-row-ref">{item.ref}</span>
                        </div>
                        <div className="wm-row-middle">
                          <span className="wm-row-product">{item.product}</span>
                          <span className="wm-row-supplier">{item.supplier}</span>
                        </div>
                        <span className={`wm-type-badge ${item.type === 'RECEIVED' ? 'wm-type-received' : 'wm-type-dispatched'}`}>
                          {item.type}
                        </span>
                      </div>
                    ))
                  ) : (
                    <div className="wm-no-suggestions">No matching products or SKU codes found.</div>
                  )}
                </div>
              ) : (
                /* Default Panel (Empty Search) */
                <div className="wm-combobox-default">
                  {recentSearches.length > 0 && (
                    <div className="wm-combobox-section">
                      <div className="wm-section-header">
                        <Clock size={12} />
                        <span>RECENTLY SEARCHED</span>
                      </div>
                      {recentSearches.map((item, idx) => (
                        <div 
                          key={idx} 
                          className="wm-suggestion-row"
                          onClick={() => handleSelectSuggestion(item)}
                        >
                          <div className="wm-row-left">
                            <span className="wm-row-sku">{formatSKU(item.sku)}</span>
                            {item.ref && <span className="wm-row-ref">{item.ref}</span>}
                          </div>
                          <div className="wm-row-middle">
                            <span className="wm-row-product">{item.product}</span>
                            {item.supplier && <span className="wm-row-supplier">{item.supplier}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="wm-combobox-section">
                    <div className="wm-section-header">
                      <span>RECENT MOVEMENT LOG ENTRIES</span>
                    </div>
                    {mockMovementLog.slice(0, 5).map((item) => (
                      <div 
                        key={item.id} 
                        className="wm-suggestion-row"
                        onClick={() => handleSelectSuggestion(item)}
                      >
                        <div className="wm-row-left">
                          <span className="wm-row-sku">{formatSKU(item.sku)}</span>
                          <span className="wm-row-ref">{item.ref}</span>
                        </div>
                        <div className="wm-row-middle">
                          <span className="wm-row-product">{item.product}</span>
                          <span className="wm-row-supplier">{item.supplier}</span>
                        </div>
                        <span className={`wm-type-badge ${item.type === 'RECEIVED' ? 'wm-type-received' : 'wm-type-dispatched'}`}>
                          {item.type}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Filter Controls Row: Supplier & Date Range */}
        <div className="wm-secondary-filters">
          <div className="wm-filter-select-wrapper">
            <span className="wm-filter-icon-label"><Building size={12} /> Supplier:</span>
            <select 
              value={selectedSupplier}
              onChange={(e) => setSelectedSupplier(e.target.value)}
              className="wm-select-input"
            >
              {suppliersList.map(s => (
                <option key={s} value={s}>{s === 'ALL' ? 'All Suppliers' : s}</option>
              ))}
            </select>
          </div>

          <div className="wm-filter-select-wrapper">
            <span className="wm-filter-icon-label"><Calendar size={12} /> Range:</span>
            <select 
              value={selectedDateRange}
              onChange={(e) => setSelectedDateRange(e.target.value)}
              className="wm-select-input"
            >
              <option value="CURRENT_PERIOD">Current Period ({startMonth} {startYear} - {endMonth} {endYear})</option>
              <option value="LAST_7_DAYS">Last 7 Days</option>
              <option value="LAST_30_DAYS">Last 30 Days</option>
              <option value="ALL">All Time</option>
            </select>
          </div>

          {/* Type Toggle Buttons (ALL / RECEIVED / DISPATCHED) */}
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
      </div>

      {/* Active Filter Chip Indicator */}
      {(activeFilterChip || selectedSupplier !== 'ALL' || selectedDateRange !== 'CURRENT_PERIOD' || searchQuery) && (
        <div className="wm-active-filter-bar">
          <span className="wm-filter-chip-text">
            Filtering by: {activeFilterChip ? (
              <strong>{activeFilterChip.product} ({formatSKU(activeFilterChip.sku)})</strong>
            ) : searchQuery ? (
              <strong>"{searchQuery}"</strong>
            ) : null}
            {selectedSupplier !== 'ALL' && <span> · Supplier: <strong>{selectedSupplier}</strong></span>}
            {selectedDateRange !== 'CURRENT_PERIOD' && <span> · Range: <strong>{selectedDateRange.replace('_', ' ')}</strong></span>}
          </span>

          <button 
            className="wm-clear-all-chip-btn"
            onClick={() => {
              setActiveFilterChip(null);
              setSearchQuery('');
              setSelectedSupplier('ALL');
              setSelectedDateRange('CURRENT_PERIOD');
              setTypeFilter('ALL');
            }}
          >
            <X size={12} /> Clear filter
          </button>
        </div>
      )}

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

  const renderInventoryTab = () => {
    const totalSKUs = mockInventory.length;
    const inStockCount = mockInventory.filter(i => i.status === 'IN STOCK').length;
    const lowStockCount = mockInventory.filter(i => i.status === 'LOW').length;
    const criticalCount = mockInventory.filter(i => i.status === 'CRITICAL').length;

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <div className="wm-inventory-grid">
          <div className="wm-inv-card wm-inv-total">
            <span className="wm-card-label">TOTAL MONITORED SKUS</span>
            <span className="wm-card-value">{totalSKUs}</span>
            <span className="wm-card-desc">active inventory items</span>
          </div>
          <div className="wm-inv-card wm-inv-instock">
            <span className="wm-card-label">IN STOCK</span>
            <span className="wm-card-value">{inStockCount}</span>
            <span className="wm-card-desc">healthy inventory level</span>
          </div>
          <div className="wm-inv-card wm-inv-low">
            <span className="wm-card-label">LOW STOCK</span>
            <span className="wm-card-value">{lowStockCount}</span>
            <span className="wm-card-desc">nearing reorder point</span>
          </div>
          <div className="wm-inv-card wm-inv-out">
            <span className="wm-card-label">CRITICAL REORDER</span>
            <span className="wm-card-value">{criticalCount}</span>
            <span className="wm-card-desc">requires immediate action</span>
          </div>
        </div>

        <div className="wm-table-wrapper">
          <table className="wm-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>BRAND</th>
                <th>PRODUCT NAME</th>
                <th>CURRENT STOCK</th>
                <th>REC (MTS)</th>
                <th>DISP (MTS)</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {mockInventory.map((item) => (
                <tr key={item.id}>
                  <td className="wm-sku-cell">{formatSKU(item.sku)}</td>
                  <td className="wm-brand-cell">{item.brand}</td>
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
                  <td className="wm-qty-cell">{item.currentStock.toLocaleString()}</td>
                  <td className="wm-qty-cell">{item.receivedMts.toLocaleString()}</td>
                  <td className="wm-qty-cell">{item.dispatchedMts.toLocaleString()}</td>
                  <td>
                    <span className={getInvStatusClass(item.status)}>
                      {item.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const renderCapacityTab = () => (
    <div className="wm-capacity-section">
      <h4 className="wm-chart-title">Warehouse Capacity Monitor <span>— Urdaneta Facility</span></h4>
      
      <div className="wm-capacity-bar-row">
        <div className="wm-capacity-bar-area">
          <div className="wm-cap-bar-large-wrapper">
            <div 
              className="wm-cap-bar-large-fill" 
              style={{ width: `${dynamicCapacity.utilizationPct}%` }}
            ></div>
          </div>
          <div className="wm-cap-bar-labels">
            <span>0 units (0%)</span>
            <span>{dynamicCapacity.totalCapacity.toLocaleString()} units (100%)</span>
          </div>
        </div>

        <div className="wm-capacity-pct-display">
          <span className="wm-capacity-pct-value">{dynamicCapacity.utilizationPct}%</span>
          <span className="wm-capacity-pct-label">Capacity Utilized</span>
        </div>
      </div>

      <div className="wm-capacity-stats">
        <div className="wm-cap-stat">
          <span className="wm-card-label">TOTAL CAPACITY</span>
          <span className="wm-cap-stat-value">{dynamicCapacity.totalCapacity.toLocaleString()}</span>
          <span className="wm-card-desc">units max volume</span>
        </div>
        <div className="wm-cap-stat">
          <span className="wm-card-label">CURRENT OCCUPIED</span>
          <span className="wm-cap-stat-value">{dynamicCapacity.currentStock.toLocaleString()}</span>
          <span className="wm-card-desc">units currently stored</span>
        </div>
        <div className="wm-cap-stat">
          <span className="wm-card-label">AVAILABLE SPACE</span>
          <span className="wm-cap-stat-value" style={{ color: '#2E9E5B' }}>{dynamicCapacity.availableSpace.toLocaleString()}</span>
          <span className="wm-card-desc">units free space remaining</span>
        </div>
      </div>
    </div>
  );

  return (
    <div className="wm-page">
      <div className="wm-content">
        {/* Header */}
        <div className="wm-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
          <div>
            <h2 className="wm-title" style={{ fontSize: '2rem', fontWeight: 700, color: '#1a202c', margin: '0 0 0.3rem 0' }}>
              Warehouse <span style={{ color: '#3b82f6' }}>movement</span>
            </h2>
            <p className="wm-subtitle" style={{ color: '#a0aec0', fontSize: '0.85rem', margin: 0, lineHeight: 1.5 }}>
              Stock movement log, SKU inventory status & warehouse capacity for {startMonth} {startYear} - {endMonth} {endYear}
            </p>
          </div>
          <DateFilter onRefresh={() => window.location.reload()} />
        </div>

        {/* Tab Navigation */}
        <div className="wm-tabs-row">
          <button
            className={`wm-tab-btn ${activeTab === 'MOVEMENT_LOG' ? 'active' : ''}`}
            onClick={() => setActiveTab('MOVEMENT_LOG')}
          >
            MOVEMENT LOG
          </button>
          <button
            className={`wm-tab-btn ${activeTab === 'SKU_INVENTORY' ? 'active' : ''}`}
            onClick={() => setActiveTab('SKU_INVENTORY')}
          >
            SKU INVENTORY
          </button>
          <button
            className={`wm-tab-btn ${activeTab === 'CAPACITY_MONITOR' ? 'active' : ''}`}
            onClick={() => setActiveTab('CAPACITY_MONITOR')}
          >
            CAPACITY MONITOR
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === 'MOVEMENT_LOG' && renderMovementLogTab()}
        {activeTab === 'SKU_INVENTORY' && renderInventoryTab()}
        {activeTab === 'CAPACITY_MONITOR' && renderCapacityTab()}
      </div>
    </div>
  );
};

export default WarehouseMovement;
