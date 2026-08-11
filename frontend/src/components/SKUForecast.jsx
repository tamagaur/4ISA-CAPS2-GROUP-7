import React, { useState } from 'react';
import { Search } from 'lucide-react';
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
import './SKUForecast.css';

const forecastData = [
  { month: 'Oct 24', actual: 1400 },
  { month: 'Nov 24', actual: 1600 },
  { month: 'Dec 24', actual: 1900 },
  { month: 'Jan 25', actual: 1200 },
  { month: 'Feb 25', actual: 1400 },
  { month: 'Mar 25', actual: 1650 },
  { month: 'Apr 25', actual: 1600, forecast: 1600, ci: [1600, 1600] },
  { month: 'May 25', forecast: 1700, ci: [1600, 1800] },
  { month: 'Jun 25', forecast: 1800, ci: [1650, 1950] },
  { month: 'Jul 25', forecast: 1850, ci: [1680, 2050] },
];

const mockSKUDatabase = [
  { code: 'SKU-4721', name: 'Surf Powder Detergent 1kg', brand: 'Unilever', cat: 'A' },
  { code: 'SKU-8934', name: 'Pineapple Juice 1L', brand: 'Del Monte', cat: 'B' },
  { code: 'SKU-3421', name: 'Tomato Sauce 250g', brand: 'Del Monte', cat: 'C' }
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
                <span className="tooltip-dot" style={{ backgroundColor: '#ebf8ff', border: '1px solid #3182ce' }}></span>
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
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSKU, setSelectedSKU] = useState(mockSKUDatabase[0]);

  const handleSearchChange = (e) => {
    const val = e.target.value;
    setSearchQuery(val);
    const matched = mockSKUDatabase.find(sku => 
      sku.code.toLowerCase().includes(val.toLowerCase()) || 
      sku.name.toLowerCase().includes(val.toLowerCase())
    );
    if (matched) {
      setSelectedSKU(matched);
    }
  };

  return (
    <div className="forecast-page">
      <div className="forecast-content">
        {/* Header */}
        <div className="forecast-header">
          <h2 className="forecast-title">
            Demand <span>forecasted</span>
          </h2>
          <p className="forecast-subtitle">
            SARIMA projection for Category A SKUs - 90 day horizon
          </p>
        </div>

        {/* Selection Area */}
        <div className="forecast-selection">
          <label className="selection-label">SELECT SKU TO FORECAST</label>
          <div className="search-wrapper">
            <Search className="search-icon" size={18} />
            <input
              type="text"
              placeholder="Search by SKU code or product name..."
              value={searchQuery}
              onChange={handleSearchChange}
              className="search-input"
            />
          </div>
        </div>

        {/* Selected SKU Card */}
        <div className="selected-sku-card">
          <div className="sku-info-left">
            <span className="sku-code-label">SKU CODE</span>
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
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
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
                  fill="#ebf8ff" 
                  name="90% CI"
                  isAnimationActive={false}
                />
                
                {/* Actual Sales */}
                <Line 
                  type="monotone" 
                  dataKey="actual" 
                  stroke="#e53e3e" 
                  strokeWidth={2}
                  dot={{ r: 4, fill: '#e53e3e', strokeWidth: 0 }}
                  activeDot={{ r: 6 }}
                  name="Actual Sales"
                  isAnimationActive={false}
                />
                
                {/* Forecast */}
                <Line 
                  type="monotone" 
                  dataKey="forecast" 
                  stroke="#3182ce" 
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={{ r: 4, fill: '#3182ce', strokeWidth: 0 }}
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
