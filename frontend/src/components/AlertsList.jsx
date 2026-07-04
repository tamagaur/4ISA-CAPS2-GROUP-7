import React from 'react';
import './AlertsList.css';

const Badge = ({ type, text }) => {
  let badgeClass = 'badge-default';
  
  if (type === 'CRITICAL' || type === 'OPEN') {
    badgeClass = 'badge-red';
  } else if (type === 'URGENT' || type === 'UNDER INVESTIGATION') {
    badgeClass = 'badge-yellow';
  } else if (type === 'RESOLVED') {
    badgeClass = 'badge-green';
  }

  return <span className={`alert-badge ${badgeClass}`}>{text || type}</span>;
};

const AlertsList = ({ title, alerts }) => {
  return (
    <div className="alerts-widget">
      <div className="alerts-header">
        <h4>{title}</h4>
        <button className="view-all-btn">View all &rarr;</button>
      </div>
      
      <div className="alerts-list">
        {alerts.map((alert, index) => (
          <div key={index} className="alert-item">
            <div className="alert-info">
              <span className="alert-title">{alert.title}</span>
              <span className="alert-subtitle">{alert.subtitle}</span>
            </div>
            <Badge type={alert.type} />
          </div>
        ))}
      </div>
    </div>
  );
};

export default AlertsList;
