import React from 'react';
import { useOutletContext } from 'react-router-dom';
import './DateFilter.css';

const DateFilter = ({ onRefresh }) => {
  const { startMonth, startYear, endMonth, endYear, updatePeriodImmediately, realWorldPeriod } = useOutletContext() || { 
    startMonth: 'Aug', startYear: '2026', endMonth: 'Aug', endYear: '2026',
    updatePeriodImmediately: () => {}, 
    realWorldPeriod: { month: 'Aug', year: '2026' } 
  };

  return (
    <div className="dashboard-date-controls">
      <div className="date-select-btn" style={{ position: 'relative' }}>
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-calendar"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
        {startMonth}
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-chevron-down"><path d="m6 9 6 6 6-6"/></svg>
        <select 
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
          value={startMonth}
          onChange={(e) => updatePeriodImmediately(e.target.value, startYear, endMonth, endYear)}
        >
          {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>
      
      <div className="date-select-btn" style={{ position: 'relative' }}>
        {startYear}
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-chevron-down"><path d="m6 9 6 6 6-6"/></svg>
        <select 
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
          value={startYear}
          onChange={(e) => updatePeriodImmediately(startMonth, e.target.value, endMonth, endYear)}
        >
          {['2021', '2022', '2023', '2024', '2025', '2026'].map(y => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
      </div>

      <span style={{ color: '#a0aec0', fontSize: '0.85rem', margin: '0 4px' }}>to</span>

      <div className="date-select-btn" style={{ position: 'relative' }}>
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-calendar"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
        {endMonth}
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-chevron-down"><path d="m6 9 6 6 6-6"/></svg>
        <select 
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
          value={endMonth}
          onChange={(e) => updatePeriodImmediately(startMonth, startYear, e.target.value, endYear)}
        >
          {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>
      
      <div className="date-select-btn" style={{ position: 'relative' }}>
        {endYear}
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-chevron-down"><path d="m6 9 6 6 6-6"/></svg>
        <select 
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
          value={endYear}
          onChange={(e) => updatePeriodImmediately(startMonth, startYear, endMonth, e.target.value)}
        >
          {['2021', '2022', '2023', '2024', '2025', '2026'].map(y => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
      </div>
      
      <button className="date-today-btn" onClick={() => updatePeriodImmediately(realWorldPeriod?.month || 'Aug', realWorldPeriod?.year || '2026', realWorldPeriod?.month || 'Aug', realWorldPeriod?.year || '2026')}>
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-calendar"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
        Today
      </button>

      {onRefresh && (
        <button className="refresh-btn" onClick={onRefresh}>
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-refresh-cw"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
          Refresh
        </button>
      )}
    </div>
  );
};

export default DateFilter;
