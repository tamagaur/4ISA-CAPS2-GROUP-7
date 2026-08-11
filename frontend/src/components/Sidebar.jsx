import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  List, 
  Layers, 
  TrendingUp, 
  RotateCcw, 
  Box, 
  AlertTriangle, 
  Upload,
  LogOut
} from 'lucide-react';
import './Sidebar.css';

const navItems = [
  { name: 'Dashboard', icon: LayoutDashboard, path: '/', badge: '00' },
  { name: 'SKU Management', icon: List, path: '/sku-management', badge: '01' },
  { name: 'ABC Classification', icon: Layers, path: '/abc', badge: '02' },
  { name: 'SKU Forecast', icon: TrendingUp, path: '/forecast', badge: '03' },
  { name: 'Reorder Recs', icon: RotateCcw, path: '/reorder', badge: '04' },
  { name: 'Warehouse Movement', icon: Box, path: '/warehouse', badge: '05' },
  { name: 'Bad Orders', icon: AlertTriangle, path: '/bad-orders', badge: '06' },
  { name: 'Data Upload', icon: Upload, path: '/upload', badge: '07' },
];

const Sidebar = ({ isOpen }) => {
  const navigate = useNavigate();

  const handleLogout = () => {
    navigate('/login');
  };

  return (
    <aside className={`sidebar ${isOpen ? '' : 'sidebar-hidden'}`}>
      {/* Top Profile */}
      <div className="sidebar-profile-top">
        <div className="avatar red-avatar">S</div>
        <div className="profile-info">
          <span className="profile-name">San San</span>
          <span className="profile-role">Marketing</span>
        </div>
      </div>

      <div className="sidebar-version">
        <span className="version-text">INVENTORY DSS - v2.0</span>
      </div>

      <div className="sidebar-modules-header">
        <span className="modules-title">MODULES</span>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        {navItems.map((item) => (
          <NavLink 
            key={item.name} 
            to={item.path} 
            className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}
          >
            <div className="nav-item-left">
              <item.icon className="nav-icon" size={18} />
              <span className="nav-item-text">
                {item.name === 'Warehouse Movement' ? (
                  <>
                    Warehouse<br />Movement
                  </>
                ) : (
                  item.name
                )}
              </span>
            </div>
            <span className="nav-badge">{item.badge}</span>
          </NavLink>
        ))}
      </nav>

      {/* Bottom Profile */}
      <div className="sidebar-bottom">
        <div className="sidebar-profile-bottom">
          <div className="avatar blue-avatar">JD</div>
          <div className="profile-info">
            <span className="profile-name">Juan dela Cruz</span>
            <span className="profile-role">ADMIN - URDANETA</span>
          </div>
        </div>
        
        <div className="sidebar-status">
          <div className="status-indicator">
            <span className="status-dot"></span>
            <span className="status-text">SYS ONLINE</span>
          </div>
          <span className="status-date">APR-22</span>
        </div>

        <button className="logout-btn" onClick={handleLogout}>
          <LogOut size={16} className="logout-icon" />
          <span>Log out</span>
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
