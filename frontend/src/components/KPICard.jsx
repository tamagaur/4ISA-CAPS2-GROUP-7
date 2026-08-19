import React from 'react';
import './KPICard.css';

const KPICard = ({ title, value, subtext, subtextColor, borderColor, icon }) => {
  return (
    <div className="kpi-card" style={{ borderLeftColor: borderColor || 'transparent' }}>
      <div className="kpi-header">
        <h3 className="kpi-title">{title}</h3>
        {icon && <div className="kpi-icon" style={{ color: subtextColor }}>{icon}</div>}
      </div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-subtext" style={{ color: subtextColor }}>
        {subtext}
      </div>
    </div>
  );
};

export default KPICard;
