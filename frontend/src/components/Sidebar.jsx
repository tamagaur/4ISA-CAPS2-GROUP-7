import React, { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  List, 
  Layers, 
  TrendingUp,
  RotateCcw,
  Upload,
  LogOut,
  X,
  ClipboardList,
  Users,
  ChartLine
} from 'lucide-react';
import { logout, getCurrentUser, API_URL } from '../auth';
import { usePermissions } from '../permissions/context';
import { permissionForPath } from '../permissions/keys';
import Modal from './Modal';
import './Sidebar.css';

// Initials for the bottom-profile avatar, e.g. "Audrey Bugayong" -> "AB".
const getInitials = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] || '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase();
};

const navSections = [
  {
    label: 'Analytics',
    items: [
      { name: 'Dashboard', icon: LayoutDashboard, path: '/' },
      { name: 'SKU Forecast', icon: TrendingUp, path: '/forecast' },
      { name: 'Category Trends', icon: ChartLine, path: '/category-trends' },
    ],
  },
  {
    label: 'Management',
    items: [
      { name: 'SKU Management', icon: List, path: '/sku-management' },
      { name: 'ABC Classification', icon: Layers, path: '/abc' },
      { name: 'Reorder Recs', icon: RotateCcw, path: '/reorder' },
    ],
  },
  {
    label: 'Admin',
    items: [
      { name: 'Audit Log', icon: ClipboardList, path: '/audit-log' },
      { name: 'Data Management', icon: Upload, path: '/upload' },
      { name: 'User Management', icon: Users, path: '/users' },
    ],
  },
];

const API_STATUS_LABEL = { checking: 'CHECKING…', online: 'SYS ONLINE', offline: 'SYS OFFLINE' };

const Sidebar = ({ isOpen, onClose, onNavAttempt, currentMonth }) => {

  // Real backend reachability, re-checked every minute. Pings /status, not
  // /health (same check): ad blockers' EasyPrivacy list blocks
  // ||onrender.com/health, which showed SYS OFFLINE while the app worked.
  const [apiStatus, setApiStatus] = useState('checking');
  useEffect(() => {
    let cancelled = false;
    const check = () => {
      fetch(`${API_URL}/status`)
        .then((res) => { if (!cancelled) setApiStatus(res.ok ? 'online' : 'offline'); })
        .catch(() => { if (!cancelled) setApiStatus('offline'); });
    };
    check();
    const id = setInterval(check, 60000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);
  const navigate = useNavigate();
  const [showLogoutModal, setShowLogoutModal] = useState(false);
  const currentUser = getCurrentUser();
  // Role and tabs come from /auth/me (PermissionsProvider), not the login
  // token, so a change an admin makes shows on the next click.
  const { role, hasPermission } = usePermissions();
  const displayName = currentUser?.fullName || currentUser?.email || 'Signed in';
  const displayRole = role ? role.toUpperCase() : '';

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
        return;
      }
    }
    // On the overlay breakpoint, picking a page should also close the
    // slide-over so it doesn't keep covering the new page's content.
    if (onClose && window.matchMedia('(max-width: 900px)').matches) {
      onClose();
    }
  };

  return (
    <>
      {/* Only rendered (and only visible, via Sidebar.css's max-width: 900px
          block) on the overlay breakpoint, so the sidebar can slide over the
          page instead of pushing it, with a click-outside-to-close scrim. */}
      {isOpen && <div className="sidebar-backdrop" onClick={onClose} />}

      <aside className={`sidebar ${isOpen ? '' : 'sidebar-hidden'}`}>
        {/* App identity — the real SAN2 logo (cropped to its own content
            bounding box in public/logo-navbar.png; the source logo.png is a
            1920x1080 canvas with the mark filling only the middle ~627px,
            so using it uncropped here left the sidebar version tiny with
            huge dead padding above/below it) instead of a text lockup that
            just repeated the company name reworded. The "who am I" identity
            still lives only in .sidebar-bottom, unchanged. */}
        <div className="sidebar-profile-top">
          <img src="/logo-navbar.png" alt="SAN2 Corporation" className="sidebar-logo" />
        </div>

        {/* Navigation */}
        <nav className="sidebar-nav">
          {navSections.map((section) => {
            // Only the pages this person may open (permissions/keys.js PAGES).
            const visibleItems = section.items.filter(
              (item) => hasPermission(permissionForPath(item.path))
            );
            if (visibleItems.length === 0) return null;

            return (
              <div className="sidebar-nav-section" key={section.label}>
                <div className="sidebar-modules-header">
                  <span className="modules-title">{section.label.toUpperCase()}</span>
                </div>
                {visibleItems.map((item) => (
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
              </div>
            );
          })}
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
          
          {/* Was a hardcoded green "SYS ONLINE" (shown even with the backend
              down) next to the computer's real date, which disagreed with the
              app's own "today" (Feb 2026). Now reflects GET /status. */}
          <div className="sidebar-status">
            <div className={`status-indicator status-${apiStatus}`} role="status">
              <span className="status-dot"></span>
              <span className="status-text">{API_STATUS_LABEL[apiStatus]}</span>
            </div>
          </div>

          <button className="logout-btn" onClick={() => setShowLogoutModal(true)}>
            <LogOut size={16} className="logout-icon" />
            <span>Log out</span>
          </button>
        </div>
      </aside>

      {/* Logout Confirmation Modal Popup */}
      {showLogoutModal && (
        <Modal
          isOpen={showLogoutModal}
          onClose={() => setShowLogoutModal(false)}
          label="Log out confirmation"
          overlayClassName="logout-modal-overlay"
          containerClassName="logout-modal-card"
        >
            <div className="logout-modal-header">
              <div className="logout-modal-icon-wrap">
                <LogOut size={20} color="var(--color-brand-primary)" />
              </div>
              <h3 className="logout-modal-title">Log Out Confirmation</h3>
              <button className="logout-modal-close" onClick={() => setShowLogoutModal(false)} aria-label="Close">
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
        </Modal>
      )}
    </>
  );
};

export default Sidebar;
