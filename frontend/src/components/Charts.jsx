import React from 'react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceDot,
  PieChart, Pie, Cell, Legend
} from 'recharts';
import './Charts.css';

const salesData = [
  { month: 'Jun 24', sales: 4.2 },
  { month: 'Jul 24', sales: 4.5 },
  { month: 'Aug 24', sales: 4.1 },
  { month: 'Sep 24', sales: 4.8 },
  { month: 'Oct 24', sales: 5.2 },
  { month: 'Nov 24', sales: 4.9 },
  { month: 'Dec 24', sales: 5.6 },
  { month: 'Jan 25', sales: 5.1 },
  { month: 'Feb 25', sales: 5.3 },
  { month: 'Mar 25', sales: 5.8 },
  { month: 'Apr 25', sales: 6.1 }, // Current
  { month: 'May 25', sales: 6.4, forecast: true },
  { month: 'Jun 25', sales: 6.8, forecast: true },
];

const abcData = [
  { name: 'A', value: 187, color: '#e53e3e' },
  { name: 'B', value: 423, color: '#3182ce' },
  { name: 'C', value: 637, color: '#a0aec0' },
];

export const LineChartWidget = () => {
  return (
    <div className="chart-widget">
      <div className="chart-header">
        <h4>Monthly Sales Trend</h4>
        <p>Jun 2024 - Jun 2025 (forecast in dashed blue)</p>
      </div>
      <div className="chart-container">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={salesData} margin={{ top: 20, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
            <XAxis dataKey="month" axisLine={true} tickLine={true} tick={{fontSize: 10, fill: '#a0aec0'}} />
            <YAxis axisLine={true} tickLine={true} tick={{fontSize: 10, fill: '#a0aec0'}} tickFormatter={(val) => val + 'M'} />
            <Tooltip />
            
            {/* Historical data */}
            <Line 
              type="monotone" 
              dataKey="sales" 
              stroke="#e53e3e" 
              strokeWidth={2} 
              dot={false}
              activeDot={{ r: 6 }}
              isAnimationActive={false}
            />
            {/* Overlay a dashed line for forecast if needed, but for simplicity we'll just style the whole line or split data */}
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
