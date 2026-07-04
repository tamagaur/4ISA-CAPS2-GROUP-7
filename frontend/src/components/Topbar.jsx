import React from 'react';
import { ChevronDown, Menu } from 'lucide-react';
import './Topbar.css';

const Topbar = ({ toggleSidebar }) => {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className="sidebar-toggle-btn" onClick={toggleSidebar} aria-label="Toggle Sidebar">
          <Menu size={20} />
        </button>
        <span className="breadcrumb-path">89 / 87</span>
        
        <div className="dropdown">
          <span>Apr</span>
          <ChevronDown size={14} />
        </div>
        
        <div className="dropdown">
          <span>2026</span>
          <ChevronDown size={14} />
        </div>
      </div>
      
      <div className="topbar-right">
        <div className="avatar blue-avatar">JD</div>
      </div>
    </header>
  );
};

export default Topbar;
