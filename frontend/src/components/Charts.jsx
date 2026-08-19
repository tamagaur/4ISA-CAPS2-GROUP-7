import React from 'react';
import { 
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  AreaChart, Area, ReferenceLine, Legend, Label
} from 'recharts';
import { COLORS } from '../theme/colors';
import './Charts.css';

// Mock data for Sales vs Stock
const generateSalesData = () => {
  const data = [];
  for (let i = 1; i <= 12; i++) {
    data.push({
      week: `Wk ${i}`,
      sales: parseFloat((1.4 + Math.random() * 0.2).toFixed(2)),
      soh: 57.2, // flat line based on the KPI
    });
  }
  return data;
};
const salesVsStockData = generateSalesData();

export const SalesVsStockWidget = ({ startMonth, startYear, endMonth, endYear }) => {
  return (
    <div className="chart-widget">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Week-on-Week Sales Velocity vs. Stock-on-Hand</h4>
          <p>Weekly Replenishment View - Recent 12 Weeks</p>
        </div>
        <div className="chart-header-right" style={{ textAlign: 'right' }}>
          <div style={{ color: COLORS.critical, fontSize: '0.8rem', fontWeight: 600 }}>Weekly Trapped Capital</div>
          <div style={{ color: COLORS.critical, fontSize: '0.75rem' }}>P57.2M SOH vs P1.65M Weekly Demand</div>
        </div>
      </div>

      <div className="chart-container">
        <ResponsiveContainer width="99%" height="100%">
          <ComposedChart data={salesVsStockData} margin={{ top: 20, right: 20, left: 0, bottom: 35 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
            <XAxis dataKey="week" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: '#a0aec0'}} dy={10} />
            <YAxis 
              yAxisId="left" 
              axisLine={false} 
              tickLine={false} 
              tick={{fontSize: 10, fill: '#a0aec0'}} 
              domain={[0, 3.5]}
              tickCount={8}
            />
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              axisLine={false} 
              tickLine={false} 
              tick={{fontSize: 10, fill: '#a0aec0', dx: 10}} 
              domain={[0, 70]}
              tickCount={8}
            />
            <Tooltip 
              cursor={{fill: '#f4f4f4'}}
              contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
            />
            <Legend 
              verticalAlign="bottom" 
              wrapperStyle={{ paddingTop: '10px', display: 'flex', justifyContent: 'center' }}
              content={(props) => {
                return (
                  <ul className="custom-legend" style={{ justifyContent: 'center', gap: '2rem' }}>
                    <li className="legend-item" style={{ color: '#7b61ff', fontWeight: 500 }}>
                      <div style={{ width: '10px', height: '10px', backgroundColor: '#7b61ff', borderRadius: '2px' }}></div>
                      <span>Weekly Sales Revenue</span>
                    </li>
                    <li className="legend-item" style={{ color: '#E5484D', fontWeight: 500 }}>
                      <div style={{ display: 'flex', alignItems: 'center', width: '20px' }}>
                        <div style={{ width: '6px', height: '2px', backgroundColor: '#E5484D' }}></div>
                        <div style={{ width: '6px', height: '6px', borderRadius: '50%', border: '2px solid #E5484D', backgroundColor: '#ffffff', margin: '0 1px' }}></div>
                        <div style={{ width: '6px', height: '2px', backgroundColor: '#E5484D' }}></div>
                      </div>
                      <span>Stock-on-Hand / Inventory Value</span>
                    </li>
                  </ul>
                );
              }}
            />
            <Bar yAxisId="left" dataKey="sales" name="Weekly Sales Revenue" fill="#7b61ff" barSize={20} radius={[4, 4, 0, 0]} />
            <Line yAxisId="right" type="stepAfter" dataKey="soh" name="Stock-on-Hand" stroke={COLORS.critical} strokeWidth={2} dot={false} activeDot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-footer-legend" style={{ display: 'flex', justifyContent: 'flex-start', gap: '2rem', padding: '0 20px', fontSize: '0.75rem', color: '#a0aec0', marginTop: '0px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><div style={{width: 12, height: 12, borderRadius: '50%', backgroundColor: '#7b61ff'}}></div> Left: PHP M sales</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><div style={{width: 20, height: 2, backgroundColor: '#E5484D'}}></div> Right: PHP M SOH</div>
      </div>
    </div>
  );
};

// Mock data for ABC Classification
const generateABCData = () => {
  const data = [];
  // Exponential decay to mimic pareto
  for (let i = 0; i <= 1200; i += 20) {
    let val = 0;
    if (i < 50) val = 500 - (i * 4);
    else if (i < 200) val = 300 - ((i - 50) * 1.5);
    else if (i < 600) val = 75 - ((i - 200) * 0.15);
    else val = 15 - ((i - 600) * 0.02);
    
    data.push({
      sku: i,
      value: Math.max(0, val),
    });
  }
  return data;
};
const abcData = generateABCData();

export const ABCClassificationWidget = () => {
  return (
    <div className="chart-widget">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>ABC Classification</h4>
        </div>
        <div className="chart-header-right">
          <span style={{ fontSize: '0.75rem', color: '#a0aec0' }}>Pareto Analysis</span>
        </div>
      </div>
      
      <div className="chart-container" style={{ position: 'relative' }}>
        <ResponsiveContainer width="99%" height="100%">
          <ComposedChart data={abcData} margin={{ top: 20, right: 20, left: 0, bottom: 35 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={true} horizontal={true} stroke="#f0f0f0" />
            <XAxis 
              dataKey="sku" 
              type="number" 
              domain={[0, 1300]} 
              tickCount={7} 
              axisLine={false} 
              tickLine={false} 
              tick={{fontSize: 10, fill: '#a0aec0'}} 
              dy={10}
            >
              <Label value="SKUs (Ranked by Revenue)" offset={0} position="bottom" style={{ fontSize: '10px', fill: '#a0aec0' }} />
            </XAxis>
            <YAxis 
              yAxisId="left" 
              axisLine={false} 
              tickLine={false} 
              tick={{fontSize: 10, fill: '#a0aec0'}} 
              domain={[0, 500]}
              tickCount={6}
            />
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              axisLine={false} 
              tickLine={false} 
              tick={{fontSize: 10, fill: COLORS.critical, dx: 10}} 
              domain={[0, 100]}
              tickCount={6}
            />
            <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
            
            <Area yAxisId="left" type="monotone" dataKey="value" stroke="#a855f7" fill="#ebd4ff" strokeWidth={2} />
            
            <ReferenceLine yAxisId="left" x={187} stroke="#a855f7" strokeDasharray="3 3" />
            <ReferenceLine yAxisId="left" x={610} stroke="#a855f7" strokeDasharray="3 3" />
          </ComposedChart>
        </ResponsiveContainer>
        
        {/* Custom Overlay Labels for ABC */}
        <div style={{ position: 'absolute', top: '15%', left: '22%', border: '1px solid #d8b4fe', backgroundColor: '#faf5ff', padding: '6px 12px', borderRadius: '4px', fontSize: '0.7rem', color: '#6b21a8' }}>
          <strong>Class A</strong><br/>
          187 SKUs (15%)<br/>
          ~73.2% Rev
        </div>
        
        <div style={{ position: 'absolute', top: '15%', left: '46%', border: '1px solid #d8b4fe', backgroundColor: '#faf5ff', padding: '6px 12px', borderRadius: '4px', fontSize: '0.7rem', color: '#6b21a8' }}>
          <strong>Class B</strong><br/>
          423 SKUs (34%)<br/>
          ~23.4% Rev
        </div>
        
        <div style={{ position: 'absolute', bottom: '0', right: '0', border: '1px solid #e9d5ff', backgroundColor: '#ffffff', padding: '4px 8px', borderRadius: '4px', fontSize: '0.7rem', color: '#a855f7' }}>
          Class C - 637 SKUs (51%) - ~3.4% Rev
        </div>
      </div>
    </div>
  );
};
