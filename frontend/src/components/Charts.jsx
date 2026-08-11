import React, { useState, useMemo, useEffect } from 'react';
import { RotateCcw } from 'lucide-react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend
} from 'recharts';
import { COLORS } from '../theme/colors';
import './Charts.css';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const abcData = [
  { name: 'A', value: 187, color: COLORS.abcA },
  { name: 'B', value: 423, color: COLORS.abcB },
  { name: 'C', value: 637, color: COLORS.abcC },
];

export const LineChartWidget = () => {
  // Persistent Range Selection State for Monthly Sales Trend Chart
  const [presetRange, setPresetRange] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_sales_chart_range');
      return saved ? JSON.parse(saved).preset : '12M';
    } catch {
      return '12M';
    }
  });

  const [customFromMonth, setCustomFromMonth] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_sales_chart_range');
      return saved ? JSON.parse(saved).fromMonth || 'Jan' : 'Jan';
    } catch {
      return 'Jan';
    }
  });

  const [customFromYear, setCustomFromYear] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_sales_chart_range');
      return saved ? JSON.parse(saved).fromYear || '2025' : '2025';
    } catch {
      return '2025';
    }
  });

  const [customToMonth, setCustomToMonth] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_sales_chart_range');
      return saved ? JSON.parse(saved).toMonth || 'Aug' : 'Aug';
    } catch {
      return 'Aug';
    }
  });

  const [customToYear, setCustomToYear] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_sales_chart_range');
      return saved ? JSON.parse(saved).toYear || '2026' : '2026';
    } catch {
      return '2026';
    }
  });

  // Save selection changes to localStorage for persistence
  useEffect(() => {
    localStorage.setItem('san2_sales_chart_range', JSON.stringify({
      preset: presetRange,
      fromMonth: customFromMonth,
      fromYear: customFromYear,
      toMonth: customToMonth,
      toYear: customToYear,
    }));
  }, [presetRange, customFromMonth, customFromYear, customToMonth, customToYear]);

  // Real-world actuals anchor date: Aug 2026
  const realWorldAnchorYear = 2026;
  const realWorldAnchorMonthIdx = 7; // Aug 2026
  const realWorldAnchorTotalMonths = realWorldAnchorYear * 12 + realWorldAnchorMonthIdx;

  const { chartData, subtitleText } = useMemo(() => {
    let startTotalMonths;
    let endTotalMonths;

    const minBaselineMonths = 2021 * 12 + 0; // Jan 2021

    if (presetRange === '6M') {
      endTotalMonths = realWorldAnchorTotalMonths;
      startTotalMonths = Math.max(minBaselineMonths, endTotalMonths - 5);
    } else if (presetRange === '12M') {
      endTotalMonths = realWorldAnchorTotalMonths;
      startTotalMonths = Math.max(minBaselineMonths, endTotalMonths - 11);
    } else if (presetRange === '24M') {
      endTotalMonths = realWorldAnchorTotalMonths;
      startTotalMonths = Math.max(minBaselineMonths, endTotalMonths - 23);
    } else {
      // CUSTOM RANGE
      const fYear = parseInt(customFromYear) || 2025;
      const fMonthIdx = Math.max(0, MONTH_NAMES.indexOf(customFromMonth));
      startTotalMonths = Math.max(minBaselineMonths, fYear * 12 + fMonthIdx);

      const tYear = parseInt(customToYear) || 2026;
      const tMonthIdx = Math.max(0, MONTH_NAMES.indexOf(customToMonth));
      endTotalMonths = Math.max(startTotalMonths, tYear * 12 + tMonthIdx);
    }

    const data = [];
    let firstMonthLabel = '';
    let lastActualMonthLabel = '';
    let hasForecastData = false;

    for (let m = startTotalMonths; m <= endTotalMonths; m++) {
      const year = Math.floor(m / 12);
      const mIdx = m % 12;
      const monthShort = MONTH_NAMES[mIdx];
      const yearShort = year.toString().slice(-2);
      const label = `${monthShort} ${yearShort}`;

      if (!firstMonthLabel) {
        firstMonthLabel = `${monthShort} ${year}`;
      }

      const isActual = m <= realWorldAnchorTotalMonths;

      if (isActual) {
        lastActualMonthLabel = `${monthShort} ${year}`;
      } else {
        hasForecastData = true;
      }

      // Base sales calculation
      const baseTrend = 4.0 + (year - 2021) * 0.45 + (mIdx * 0.12);
      const seasonal = Math.sin((mIdx / 12) * Math.PI * 2) * 0.4;
      const salesVal = parseFloat((baseTrend + seasonal).toFixed(1));

      if (isActual) {
        // If this is the last actual point and forecast follows, include forecastSales to connect line segments
        const isLastActualBeforeForecast = (m === realWorldAnchorTotalMonths) && (endTotalMonths > realWorldAnchorTotalMonths);
        data.push({
          month: label,
          sales: salesVal,
          forecastSales: isLastActualBeforeForecast ? salesVal : null
        });
      } else {
        data.push({
          month: label,
          sales: null,
          forecastSales: salesVal
        });
      }
    }

    // Subtitle text construction
    let subtitleText = '';
    if (hasForecastData) {
      subtitleText = `${firstMonthLabel} - ${lastActualMonthLabel} (forecast in dashed indigo)`;
    } else {
      subtitleText = `${firstMonthLabel} - ${lastActualMonthLabel}`;
    }

    return { chartData: data, subtitleText };
  }, [presetRange, customFromMonth, customFromYear, customToMonth, customToYear]);

  const handleResetToDefault = () => {
    setPresetRange('6M');
    setCustomFromMonth('Mar');
    setCustomFromYear('2026');
    setCustomToMonth('Aug');
    setCustomToYear('2026');
  };

  return (
    <div className="chart-widget">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Monthly Sales Trend</h4>
          <p>{subtitleText}</p>
        </div>

        {/* Range Controls */}
        <div className="chart-range-controls">
          <div className="range-preset-group">
            {[
              { id: '6M', label: '6M' },
              { id: '12M', label: '12M' },
              { id: '24M', label: '24M' },
              { id: 'CUSTOM', label: 'Custom' }
            ].map(p => (
              <button
                key={p.id}
                className={`range-preset-btn ${presetRange === p.id ? 'active' : ''}`}
                onClick={() => setPresetRange(p.id)}
              >
                {p.label}
              </button>
            ))}
          </div>

          <button 
            className={`chart-reset-btn ${presetRange === '6M' ? 'disabled' : ''}`}
            onClick={handleResetToDefault}
            title="Reset to default trend (Last 6 months)"
            disabled={presetRange === '6M'}
          >
            <RotateCcw size={12} />
            <span>Default</span>
          </button>

          {presetRange === 'CUSTOM' && (
            <div className="custom-range-pickers">
              <div className="custom-picker-group">
                <span className="picker-label">From:</span>
                <select 
                  className="dropdown-select chart-picker-select"
                  value={customFromMonth}
                  onChange={(e) => setCustomFromMonth(e.target.value)}
                >
                  {MONTH_NAMES.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
                <select 
                  className="dropdown-select chart-picker-select"
                  value={customFromYear}
                  onChange={(e) => setCustomFromYear(e.target.value)}
                >
                  {['2021', '2022', '2023', '2024', '2025', '2026'].map(y => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </div>

              <div className="custom-picker-group">
                <span className="picker-label">To:</span>
                <select 
                  className="dropdown-select chart-picker-select"
                  value={customToMonth}
                  onChange={(e) => setCustomToMonth(e.target.value)}
                >
                  {MONTH_NAMES.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
                <select 
                  className="dropdown-select chart-picker-select"
                  value={customToYear}
                  onChange={(e) => setCustomToYear(e.target.value)}
                >
                  {['2021', '2022', '2023', '2024', '2025', '2026', '2027'].map(y => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="chart-container">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 20, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={COLORS.gridline} />
            <XAxis dataKey="month" axisLine={true} tickLine={true} tick={{fontSize: 10, fill: '#a0aec0'}} />
            <YAxis axisLine={true} tickLine={true} tick={{fontSize: 10, fill: '#a0aec0'}} tickFormatter={(val) => val + 'M'} />
            <Tooltip 
              formatter={(value, name) => [
                `${value}M`, 
                name === 'sales' ? 'Actual Sales' : 'Forecast'
              ]}
            />
            
            {/* Historical Actual Sales */}
            <Line 
              type="monotone" 
              dataKey="sales" 
              stroke={COLORS.salesTrend} 
              strokeWidth={2} 
              dot={{ r: 3, fill: COLORS.salesTrend }}
              activeDot={{ r: 6 }}
              name="sales"
              connectNulls={true}
              isAnimationActive={false}
            />

            {/* Forecast Segment */}
            <Line 
              type="monotone" 
              dataKey="forecastSales" 
              stroke={COLORS.salesTrend} 
              strokeWidth={2} 
              strokeDasharray="5 5"
              dot={{ r: 3, fill: COLORS.salesTrend }}
              activeDot={{ r: 6 }}
              name="forecastSales"
              connectNulls={true}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export const DonutChartWidget = () => {
  return (
    <div className="chart-widget">
      <div className="chart-header">
        <h4>ABC Breakdown</h4>
        <p>Category distribution</p>
      </div>
      <div className="chart-container donut-container">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={abcData}
              cx="50%"
              cy="45%"
              innerRadius={70}
              outerRadius={100}
              paddingAngle={5}
              dataKey="value"
            >
              {abcData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Pie>
            <Legend 
              verticalAlign="bottom" 
              height={36} 
              content={(props) => {
                const { payload } = props;
                return (
                  <ul className="custom-legend">
                    {payload.map((entry, index) => (
                      <li key={`item-${index}`} className="legend-item">
                        <span className="legend-color" style={{ backgroundColor: entry.payload.color }}></span>
                        <span className="legend-text">{entry.value}: {entry.payload.value}</span>
                      </li>
                    ))}
                  </ul>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
