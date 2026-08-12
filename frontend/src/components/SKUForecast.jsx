import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Star, ArrowRight, Clock, Filter, X } from 'lucide-react';
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import { COLORS } from '../theme/colors';
import './SKUForecast.css';

// Dynamic 6-month historical actuals + 90-day (3-month) forward forecast recalculating from today's system date
const generateDynamicForecastData = () => {
  const today = new Date();
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  
  const data = [];
  
  // 6 months of trailing historical actuals ending at current month
  for (let i = 5; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
    const mStr = `${monthNames[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
    const baseActual = 1380 + Math.floor(Math.sin(i * 0.8) * 220) + (5 - i) * 35;
    
    if (i === 0) {
      // Current month bridge point connecting actual sales to 90-day forecast & confidence band
      data.push({
        month: mStr,
        actual: baseActual,
        forecast: baseActual,
        ci: [baseActual, baseActual]
      });
    } else {
      data.push({
        month: mStr,
        actual: baseActual
      });
    }
  }
  
  // 3 months (90 days) forward projection from current month
  const lastActual = data[data.length - 1].actual;
  for (let i = 1; i <= 3; i++) {
    const d = new Date(today.getFullYear(), today.getMonth() + i, 1);
    const mStr = `${monthNames[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
    const fValue = Math.round(lastActual + i * 55 + Math.sin(i) * 25);
    const lowerCi = Math.round(fValue - (75 + i * 35));
    const upperCi = Math.round(fValue + (75 + i * 40));
    
    data.push({
      month: mStr,
      forecast: fValue,
      ci: [lowerCi, upperCi]
    });
  }
  
  return data;
};

const forecastData = generateDynamicForecastData();

const mockSKUDatabase = [
  { code: 'SKU-4721', name: 'Surf Powder Detergent 1kg', brand: 'Unilever', cat: 'A' },
  { code: 'SKU-1052', name: 'Knorr Seasoning 250ml', brand: 'Unilever', cat: 'A' },
  { code: 'SKU-6190', name: 'Great Taste Coffee 3-in-1 30g', brand: 'Universal Robina', cat: 'A' },
  { code: 'SKU-2981', name: 'Pantasene Shampoo 180ml', brand: 'P&G', cat: 'A' },
  { code: 'SKU-9023', name: 'Nescafe Classic 200g', brand: 'Nestle', cat: 'A' },
  { code: 'SKU-8934', name: 'Pineapple Juice 1L', brand: 'Del Monte', cat: 'B' },
  { code: 'SKU-7743', name: 'Jack n Jill Piattos Cheese 85g', brand: 'Universal Robina', cat: 'B' },
  { code: 'SKU-5412', name: 'Downy Sunrise Fresh 900ml', brand: 'P&G', cat: 'B' },
  { code: 'SKU-3421', name: 'Tomato Sauce 250g', brand: 'Del Monte', cat: 'C' },
  { code: 'SKU-8104', name: 'Bear Brand Fortified Milk 330g', brand: 'Nestle', cat: 'C' }
];

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="forecast-tooltip">
        <p className="tooltip-label">{label}</p>
        {payload.map((entry, index) => {
          if (entry.dataKey === 'ci') {
            return (
              <p key={index} className="tooltip-item">
                <span className="tooltip-dot" style={{ backgroundColor: '#F3E8FF', border: '1px solid #EBC9E1' }}></span>
                90% CI: {entry.value[0]} - {entry.value[1]}
              </p>
            );
          }
          return (
            <p key={index} className="tooltip-item" style={{ color: entry.color }}>
              <span className="tooltip-dot" style={{ backgroundColor: entry.color }}></span>
              {entry.name}: {entry.value}
            </p>
          );
        })}
      </div>
    );
  }
  return null;
};

const SKUForecast = () => {
  const navigate = useNavigate();
  const dropdownRef = useRef(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('ALL');
  const [selectedBrand, setSelectedBrand] = useState('ALL');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  // Selected SKU
  const [selectedSKU, setSelectedSKU] = useState(mockSKUDatabase[0]);

  // Persistent Pinned SKUs
  const [pinnedSKUs, setPinnedSKUs] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_pinned_skus');
      return saved ? JSON.parse(saved) : ['SKU-4721'];
    } catch {
      return ['SKU-4721'];
    }
  });

  // Persistent Recently Viewed/Forecasted SKUs (Max 5)
  const [recentSKUs, setRecentSKUs] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_recent_forecast_skus');
      return saved ? JSON.parse(saved) : ['SKU-4721', 'SKU-1052', 'SKU-6190'];
    } catch {
      return ['SKU-4721', 'SKU-1052', 'SKU-6190'];
    }
  });

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Toggle pin/unpin SKU
  const togglePinSKU = (code, e) => {
    if (e) e.stopPropagation();
    let updated;
    if (pinnedSKUs.includes(code)) {
      updated = pinnedSKUs.filter(c => c !== code);
    } else {
      updated = [...pinnedSKUs, code];
    }
    setPinnedSKUs(updated);
    localStorage.setItem('san2_pinned_skus', JSON.stringify(updated));
  };

  // Select SKU handler
  const handleSelectSKU = (sku) => {
    setSelectedSKU(sku);
    setIsDropdownOpen(false);

    // Update recent SKUs history (prepend, deduplicate, keep last 5)
    const updatedRecent = [sku.code, ...recentSKUs.filter(c => c !== sku.code)].slice(0, 5);
    setRecentSKUs(updatedRecent);
    localStorage.setItem('san2_recent_forecast_skus', JSON.stringify(updatedRecent));
  };

  // Unique Brands list
  const brandsList = ['ALL', ...Array.from(new Set(mockSKUDatabase.map(s => s.brand)))];

  // Filtering Logic
  const filteredSKUs = useMemo(() => {
    return mockSKUDatabase.filter(sku => {
      const matchesSearch = searchQuery === '' || 
        sku.code.toLowerCase().includes(searchQuery.toLowerCase()) || 
        sku.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.brand.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = selectedCategory === 'ALL' || sku.cat === selectedCategory;
      const matchesBrand = selectedBrand === 'ALL' || sku.brand === selectedBrand;
      return matchesSearch && matchesCat && matchesBrand;
    });
  }, [searchQuery, selectedCategory, selectedBrand]);

  const hasActiveFilterOrSearch = selectedCategory !== 'ALL' || selectedBrand !== 'ALL' || searchQuery.trim() !== '';

  const pinnedSKUObjects = mockSKUDatabase.filter(sku => pinnedSKUs.includes(sku.code));
  const recentSKUObjects = mockSKUDatabase.filter(sku => recentSKUs.includes(sku.code) && !pinnedSKUs.includes(sku.code));
  const catASKUObjects = mockSKUDatabase.filter(
    sku => sku.cat === 'A' && !pinnedSKUs.includes(sku.code) && !recentSKUs.includes(sku.code)
  );

  const isSelectedPinned = pinnedSKUs.includes(selectedSKU.code);

  return (
    <div className="forecast-page">
      <div className="forecast-content">
        {/* Header */}
        <div className="forecast-header">
          <div className="header-text-group">
            <h2 className="forecast-title">
              Demand <span>forecasted</span>
            </h2>
            <p className="forecast-subtitle">
              SARIMA projection for Category A SKUs - 90 day horizon
            </p>
            <p className="forecast-subtext-today">
              Always shows the latest data as of today — this forecast doesn't change based on a selected month or year.
            </p>
          </div>

          <button 
            className="browse-all-skus-btn"
            onClick={() => navigate('/sku-management')}
            title="Go to SKU Management table"
          >
            <span>Browse all SKUs</span>
            <ArrowRight size={14} />
          </button>
        </div>

        {/* Selection Area with Filter Controls */}
        <div className="forecast-selection">
          <div className="selection-top-bar">
            <label className="selection-label">SELECT SKU TO FORECAST</label>
          </div>

          {/* Controls Bar: Filters & Search Combobox */}
          <div className="combobox-controls-bar">
            {/* Filter Chips / Dropdowns */}
            <div className="forecast-filter-group">
              <div className="filter-dropdown-wrapper">
                <span className="filter-icon-label"><Filter size={12} /> Cat:</span>
                <select 
                  className="filter-select"
                  value={selectedCategory}
                  onChange={(e) => {
                    setSelectedCategory(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                >
                  <option value="ALL">All Categories</option>
                  <option value="A">Category A</option>
                  <option value="B">Category B</option>
                  <option value="C">Category C</option>
                </select>
              </div>

              <div className="filter-dropdown-wrapper">
                <span className="filter-icon-label">Brand:</span>
                <select 
                  className="filter-select"
                  value={selectedBrand}
                  onChange={(e) => {
                    setSelectedBrand(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                >
                  {brandsList.map(b => (
                    <option key={b} value={b}>{b === 'ALL' ? 'All Brands' : b}</option>
                  ))}
                </select>
              </div>

              {(selectedCategory !== 'ALL' || selectedBrand !== 'ALL' || searchQuery !== '') && (
                <button 
                  className="clear-filters-btn"
                  onClick={() => {
                    setSelectedCategory('ALL');
                    setSelectedBrand('ALL');
                    setSearchQuery('');
                  }}
                  title="Clear all filters"
                >
                  <X size={12} />
                  <span>Clear</span>
                </button>
              )}
            </div>

            {/* Searchable Combobox */}
            <div className="search-combobox-wrapper" ref={dropdownRef}>
              <div className="search-input-inner">
                <Search className="search-icon" size={18} />
                <input
                  type="text"
                  placeholder="Search by SKU code, name, or brand..."
                  value={searchQuery}
                  onFocus={() => setIsDropdownOpen(true)}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                  className="search-input"
                />
                {searchQuery && (
                  <button className="input-clear-btn" onClick={() => setSearchQuery('')}>
                    <X size={14} />
                  </button>
                )}
              </div>

              {/* Combobox Results Dropdown Panel */}
              {isDropdownOpen && (
                <div className="combobox-results-panel">
                  {hasActiveFilterOrSearch ? (
                    /* Filtered Search Results List */
                    <div className="combobox-section">
                      <div className="section-header-title">
                        <span>SEARCH RESULTS ({filteredSKUs.length})</span>
                      </div>
                      {filteredSKUs.length > 0 ? (
                        filteredSKUs.map(sku => (
                          <div 
                            key={sku.code} 
                            className={`result-row ${selectedSKU.code === sku.code ? 'selected' : ''}`}
                            onClick={() => handleSelectSKU(sku)}
                          >
                            <button 
                              className={`star-pin-btn ${pinnedSKUs.includes(sku.code) ? 'pinned' : ''}`}
                              onClick={(e) => togglePinSKU(sku.code, e)}
                              title={pinnedSKUs.includes(sku.code) ? "Unpin SKU" : "Pin SKU to top"}
                            >
                              <Star size={15} fill={pinnedSKUs.includes(sku.code) ? '#F5A623' : 'none'} />
                            </button>
                            <div className="result-code-group">
                              <span className="result-sku-code">{sku.code}</span>
                              <span className="result-brand">{sku.brand}</span>
                            </div>
                            <span className="result-product-name">{sku.name}</span>
                            <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                          </div>
                        ))
                      ) : (
                        <div className="no-results-msg">No SKUs match your search or filter criteria.</div>
                      )}
                    </div>
                  ) : (
                    /* Default Panel (Empty Search & No Filters) */
                    <div className="combobox-default-view">
                      {/* Section 1: Pinned / Favorited SKUs */}
                      {pinnedSKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <Star size={12} fill="#F5A623" color="#F5A623" />
                            <span>PINNED SKUS</span>
                          </div>
                          {pinnedSKUObjects.map(sku => (
                            <div 
                              key={sku.code} 
                              className={`result-row ${selectedSKU.code === sku.code ? 'selected' : ''}`}
                              onClick={() => handleSelectSKU(sku)}
                            >
                              <button 
                                className="star-pin-btn pinned"
                                onClick={(e) => togglePinSKU(sku.code, e)}
                                title="Unpin SKU"
                              >
                                <Star size={15} fill="#F5A623" />
                              </button>
                              <div className="result-code-group">
                                <span className="result-sku-code">{sku.code}</span>
                                <span className="result-brand">{sku.brand}</span>
                              </div>
                              <span className="result-product-name">{sku.name}</span>
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Section 2: Recently Forecasted SKUs */}
                      {recentSKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <Clock size={12} />
                            <span>RECENTLY FORECASTED</span>
                          </div>
                          {recentSKUObjects.map(sku => (
                            <div 
                              key={sku.code} 
                              className={`result-row ${selectedSKU.code === sku.code ? 'selected' : ''}`}
                              onClick={() => handleSelectSKU(sku)}
                            >
                              <button 
                                className={`star-pin-btn ${pinnedSKUs.includes(sku.code) ? 'pinned' : ''}`}
                                onClick={(e) => togglePinSKU(sku.code, e)}
                                title="Pin SKU"
                              >
                                <Star size={15} fill={pinnedSKUs.includes(sku.code) ? '#F5A623' : 'none'} />
                              </button>
                              <div className="result-code-group">
                                <span className="result-sku-code">{sku.code}</span>
                                <span className="result-brand">{sku.brand}</span>
                              </div>
                              <span className="result-product-name">{sku.name}</span>
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Section 3: Category A SKUs */}
                      {catASKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <span>CATEGORY A SKUS (HIGH PRIORITY)</span>
                          </div>
                          {catASKUObjects.map(sku => (
                            <div 
                              key={sku.code} 
                              className={`result-row ${selectedSKU.code === sku.code ? 'selected' : ''}`}
                              onClick={() => handleSelectSKU(sku)}
                            >
                              <button 
                                className={`star-pin-btn ${pinnedSKUs.includes(sku.code) ? 'pinned' : ''}`}
                                onClick={(e) => togglePinSKU(sku.code, e)}
                                title="Pin SKU"
                              >
                                <Star size={15} fill={pinnedSKUs.includes(sku.code) ? '#F5A623' : 'none'} />
                              </button>
                              <div className="result-code-group">
                                <span className="result-sku-code">{sku.code}</span>
                                <span className="result-brand">{sku.brand}</span>
                              </div>
                              <span className="result-product-name">{sku.name}</span>
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Selected SKU Card */}
        <div className="selected-sku-card">
          <div className="sku-info-left">
            <div className="sku-code-header-row">
              <span className="sku-code-label">SELECTED SKU CODE</span>
              <button 
                className={`card-star-btn ${isSelectedPinned ? 'pinned' : ''}`}
                onClick={(e) => togglePinSKU(selectedSKU.code, e)}
                title={isSelectedPinned ? "Unpin SKU" : "Pin SKU to top of search"}
              >
                <Star size={15} fill={isSelectedPinned ? '#F5A623' : 'none'} color={isSelectedPinned ? '#F5A623' : '#a0aec0'} />
                <span className="pin-text">{isSelectedPinned ? 'Pinned' : 'Pin SKU'}</span>
              </button>
            </div>
            <span className="sku-code-value">{selectedSKU.code}</span>
            <span className="sku-product-name">{selectedSKU.name}</span>
            <span className="sku-brand-name">Brand: {selectedSKU.brand}</span>
          </div>
          <div className="sku-info-right">
            <span className={`forecast-cat-badge cat-${selectedSKU.cat}`}>Category {selectedSKU.cat}</span>
          </div>
        </div>

        {/* Chart Section */}
        <div className="forecast-chart-container">
          {/* Chart Legend */}
          <div className="chart-legend">
            <div className="legend-item">
              <span className="legend-line line-actual"></span>
              <span className="legend-label">Actual Sales</span>
            </div>
            <div className="legend-item">
              <span className="legend-line line-forecast"></span>
              <span className="legend-label">Forecast</span>
            </div>
            <div className="legend-item">
              <span className="legend-area area-ci"></span>
              <span className="legend-label">Uncertainty Band (90% CI)</span>
            </div>
          </div>

          {/* Chart */}
          <div className="chart-wrapper">
            <ResponsiveContainer width="100%" height={400}>
              <ComposedChart data={forecastData} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={COLORS.gridline} />
                <XAxis 
                  dataKey="month" 
                  axisLine={true} 
                  tickLine={true} 
                  tick={{ fill: '#a0aec0', fontSize: 12 }} 
                  dy={10}
                />
                <YAxis 
                  axisLine={true} 
                  tickLine={true} 
                  tick={{ fill: '#a0aec0', fontSize: 12 }} 
                  domain={[0, 2200]}
                  ticks={[0, 550, 1100, 1650, 2200]}
                  dx={-10}
                />
                <Tooltip content={<CustomTooltip />} />
                
                {/* Uncertainty Band */}
                <Area 
                  type="monotone" 
                  dataKey="ci" 
                  stroke="none" 
                  fill={COLORS.forecastBg} 
                  name="90% CI"
                  isAnimationActive={false}
                />
                
                {/* Actual Sales */}
                <Line 
                  type="monotone" 
                  dataKey="actual" 
                  stroke={COLORS.salesTrend} 
                  strokeWidth={2}
                  dot={{ r: 4, fill: COLORS.salesTrend, strokeWidth: 0 }}
                  activeDot={{ r: 6 }}
                  name="Actual Sales"
                  isAnimationActive={false}
                />
                
                {/* Forecast */}
                <Line 
                  type="monotone" 
                  dataKey="forecast" 
                  stroke={COLORS.forecast} 
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={{ r: 4, fill: COLORS.forecast, strokeWidth: 0 }}
                  activeDot={{ r: 6 }}
                  name="Forecast"
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SKUForecast;
