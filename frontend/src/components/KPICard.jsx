import React from 'react';
import './KPICard.css';

const KPICard = ({ title, value, subtext, subtextColor, borderColor }) => {
  return (
    <div className="kpi-card" style={{ borderLeftColor: borderColor || 'transparent' }}>
      <h3 className="kpi-title">{title}</h3>
      <div className="kpi-value">{value}</div>
      <div className="kpi-subtext" style={{ color: subtextColor }}>
        {subtext}
      </div>
    </div>
  );
};

export default KPICard;
