import React, { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  List, 
  Layers, 
  TrendingUp, 
  RotateCcw, 
  AlertTriangle, 
  Upload,
  LogOut,
  X
} from 'lucide-react';
import { logout, getCurrentUser } from '../auth';
import './Sidebar.css';

// Initials for the bottom-profile avatar, e.g. "Audrey Bugayong" -> "AB".
const getInitials = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] || '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase();
};

const navItems = [
  { name: 'Dashboard', icon: LayoutDashboard, path: '/' },
  { name: 'SKU Management', icon: List, path: '/sku-management' },
  { name: 'ABC Classification', icon: Layers, path: '/abc' },
  { name: 'SKU Forecast', icon: TrendingUp, path: '/forecast' },
  { name: 'Reorder Recs', icon: RotateCcw, path: '/reorder' },
  { name: 'Bad Orders', icon: AlertTriangle, path: '/bad-orders' },
  { name: 'Data Upload', icon: Upload, path: '/upload' },
];

const Sidebar = ({ isOpen, onNavAttempt, currentMonth }) => {
  const navigate = useNavigate();
  const [showLogoutModal, setShowLogoutModal] = useState(false);
  const currentUser = getCurrentUser();
  const displayName = currentUser?.fullName || currentUser?.email || 'Signed in';
  const displayRole = currentUser?.role ? currentUser.role.toUpperCase() : '';

  const handleConfirmLogout = () => {
    setShowLogoutModal(false);
    logout();
    navigate('/login');
  };

  const handleNavClick = (e, path) => {
    if (onNavAttempt) {
      const allowed = onNavAttempt(path);
      if (!allowed) {
        e.preventDefault();
      }
    }
  };

  return (
    <>
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
              onClick={(e) => handleNavClick(e, item.path)}
              className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}
            >
              <div className="nav-item-left">
                <item.icon className="nav-icon" size={18} />
                <span className="nav-item-text">
                  {item.name}
                </span>
              </div>
            </NavLink>
          ))}
        </nav>

        {/* Bottom Profile */}
        <div className="sidebar-bottom">
          <div className="sidebar-profile-bottom">
            <div className="avatar blue-avatar">{getInitials(displayName)}</div>
            <div className="profile-info">
              <span className="profile-name">{displayName}</span>
              <span className="profile-role">{displayRole ? `${displayRole} - URDANETA` : 'URDANETA'}</span>
            </div>
          </div>
          
          <div className="sidebar-status">
            <div className="status-indicator">
              <span className="status-dot"></span>
              <span className="status-text">SYS ONLINE</span>
            </div>
            <span className="status-date">{(currentMonth || 'AUG').toUpperCase()}-11</span>
          </div>

          <button className="logout-btn" onClick={() => setShowLogoutModal(true)}>
            <LogOut size={16} className="logout-icon" />
            <span>Log out</span>
          </button>
        </div>
      </aside>

      {/* Logout Confirmation Modal Popup */}
      {showLogoutModal && (
        <div className="logout-modal-overlay" onClick={() => setShowLogoutModal(false)}>
          <div className="logout-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="logout-modal-header">
              <div className="logout-modal-icon-wrap">
                <LogOut size={20} color="#c53030" />
              </div>
              <h3 className="logout-modal-title">Log Out Confirmation</h3>
              <button className="logout-modal-close" onClick={() => setShowLogoutModal(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="logout-modal-body">
              <p>Are you sure you want to log out of <strong>SAN2 Inventory DSS</strong>?</p>
            </div>
            <div className="logout-modal-footer">
              <button className="logout-cancel-btn" onClick={() => setShowLogoutModal(false)}>
                Cancel
              </button>
              <button className="logout-confirm-btn" onClick={handleConfirmLogout}>
                Log Out
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default Sidebar;
