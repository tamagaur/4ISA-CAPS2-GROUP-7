import React from 'react';
import { useNavigate } from 'react-router-dom';
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

const AlertsList = ({ title, alerts, onViewAll, viewAllPath }) => {
  const navigate = useNavigate();

  const handleViewAllClick = (e) => {
    e.stopPropagation();
    if (onViewAll) {
      onViewAll();
    } else if (viewAllPath) {
      navigate(viewAllPath);
    }
  };

  return (
    <div className="alerts-widget">
      <div className="alerts-header">
        <h4>{title}</h4>
        <button className="view-all-btn" onClick={handleViewAllClick}>
          View all &rarr;
        </button>
      </div>
      
      <div className="alerts-list">
        {alerts.map((alert, index) => (
          <div key={index} className="alert-item" onClick={handleViewAllClick} style={{ cursor: 'pointer' }}>
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
