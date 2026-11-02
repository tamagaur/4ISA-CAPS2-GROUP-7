import React, { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  BookOpen,
  Layers, 
  Package,
  Database,
  TrendingUp,
  RotateCcw,
  LogOut,
  X,
  ClipboardList,
  Users,
  ChartLine,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react';
import { logout, getCurrentUser, API_URL } from '../auth';
import { getMfaStatus, MFA_STATUS_EVENT } from '../api/mfa';
import { usePermissions } from '../permissions/context';
import { permissionForPath } from '../permissions/keys';
import Modal from './Modal';
import AccountSecurityModal from './AccountSecurityModal';
import AuthHandoff, { holdForHandoff } from './AuthHandoff';
import './Sidebar.css';

// Initials for the bottom-profile avatar, e.g. "Audrey Bugayong" -> "AB".
const getInitials = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] || '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase();
};

// Navigation groups follow the sidebar reference: dashboard first, then
// inventory operations, analytics, and data governance. Routes and
// permissions are unchanged.
const navSections = [
  {
    label: null,
    items: [
      { name: 'Dashboard', icon: LayoutDashboard, path: '/' },
    ],
  },
  {
    label: 'Inventory Operations',
    items: [
      { name: 'Reorder Recommendations', icon: RotateCcw, path: '/reorder' },
      { name: 'SKU Management', icon: Package, path: '/sku-management' },
      { name: 'ABC Classification', icon: Layers, path: '/abc' },
    ],
  },
  {
    label: 'Analytics & Forecasting',
    items: [
      { name: 'SKU Forecast', icon: TrendingUp, path: '/forecast' },
      { name: 'Category Trends', icon: ChartLine, path: '/category-trends' },
    ],
  },
  {
    label: 'Data & Governance',
    items: [
      { name: 'Reference Guide', icon: BookOpen, path: '/data-dictionary' },
      { name: 'Audit Log', icon: ClipboardList, path: '/audit-log' },
    ],
  },
  {
    label: 'Administration',
    items: [
      { name: 'Data Management', icon: Database, path: '/upload' },
      { name: 'User Management', icon: Users, path: '/users' },
    ],
  },
];

const API_STATUS_LABEL = { checking: 'CHECKING…', online: 'SERVER ONLINE', offline: 'SERVER OFFLINE' };

const Sidebar = ({ isOpen, onClose, onNavAttempt }) => {

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
  // Log out confirmed: the hand-off screen ("Logging out of the
  // dashboard…") over everything for a moment, then the sign-out.
  const [loggingOut, setLoggingOut] = useState(false);
  // Your own two-step sign-in, opened from your name below.
  const [showSecurity, setShowSecurity] = useState(false);
  // Whether it is on, for the "Account security" line under your name
  // (GET /auth/mfa, the same answer the dialog reads): "Action required"
  // while it is off, "Protected" once it is on. Null until it has
  // loaded, or when the server has two-step sign-in paused (available:
  // false), when the line just says "Account security": there is nothing
  // to act on. The dialog hands back the fresh status after any change,
  // so the line follows without a second request.
  const [mfaStatus, setMfaStatus] = useState(null);
  useEffect(() => {
    let cancelled = false;
    getMfaStatus()
      .then((status) => { if (!cancelled) setMfaStatus(status); })
      .catch(() => { if (!cancelled) setMfaStatus(null); });
    // A change made from the My profile page's copy of the dialog.
    const onStatus = (event) => setMfaStatus(event.detail);
    window.addEventListener(MFA_STATUS_EVENT, onStatus);
    return () => {
      cancelled = true;
      window.removeEventListener(MFA_STATUS_EVENT, onStatus);
    };
  }, []);
  const securityState = mfaStatus?.available ? (mfaStatus.enabled ? 'protected' : 'pending') : null;
  const currentUser = getCurrentUser();
  // Role and tabs come from /auth/me (PermissionsProvider), not the login
  // token, so a change an admin makes shows on the next click.
  const { role, hasPermission, profile } = usePermissions();
  // The name and picture as /auth/me has them now (a save on the My
  // profile page shows at once); the login token is the fallback.
  const displayName = profile?.fullName || currentUser?.fullName || currentUser?.email || 'Signed in';
  const avatarUrl = profile?.avatar || null;
  const displayRole = role ? role.toUpperCase() : '';

  const handleConfirmLogout = async () => {
    setShowLogoutModal(false);
    // The screen first, with the session still whole beneath it (a fetch
    // in those moments must not be taken for an expired session); then
    // the sign-out and the login page.
    setLoggingOut(true);
    await holdForHandoff();
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
      {loggingOut && <AuthHandoff kind="out" />}
      {isOpen && <div className="sidebar-backdrop" onClick={onClose} />}

      {/* Desktop: a docked column that pushes the page; the topbar's menu
          button slides it away and back. Below 900px the shell takes no
          space and the sidebar is a slide-over. (The shell is left from the
          floating icon rail, taken out 2026-10-11 — see Sidebar.css.) */}
      <div className={`sidebar-shell ${isOpen ? 'is-open' : 'is-closed'}`}>
        <aside className={`sidebar ${isOpen ? 'is-open' : 'is-closed'}`} aria-label="Main navigation">
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
                  {section.label && (
                    <div className="sidebar-modules-header">
                      <span className="modules-title">{section.label.toUpperCase()}</span>
                    </div>
                  )}
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
            {/* Your name and picture open My profile (/profile); the line
                under them opens Account security (two-step sign-in). */}
            <div className="sidebar-profile-bottom">
              <button
                type="button"
                className="sidebar-profile-btn"
                onClick={() => navigate('/profile')}
                title="My profile"
              >
                <div className="avatar blue-avatar" aria-hidden="true">
                  {avatarUrl ? <img src={avatarUrl} alt="" className="avatar-img" /> : getInitials(displayName)}
                </div>
                <div className="profile-info">
                  <span className="profile-name">{displayName}</span>
                  <span className="profile-role">{displayRole ? `${displayRole} - URDANETA` : 'URDANETA'}</span>
                </div>
              </button>
              <button
                type="button"
                className={`profile-security${securityState ? ` is-${securityState}` : ''}`}
                onClick={() => setShowSecurity(true)}
                title="Account security"
              >
                {securityState === 'pending' && (
                  <>
                    <AlertTriangle size={12} aria-hidden="true" />
                    Account security: Action required
                  </>
                )}
                {securityState === 'protected' && (
                  <>
                    <CheckCircle2 size={12} aria-hidden="true" />
                    Account security: <strong>Protected</strong>
                  </>
                )}
                {!securityState && 'Account security'}
              </button>
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
              <span className="logout-text">Log out</span>
            </button>
          </div>
        </aside>
      </div>

      <AccountSecurityModal isOpen={showSecurity} onClose={() => setShowSecurity(false)} onStatusChange={setMfaStatus} />

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
              <p>Are you sure you want to log out of <strong>SAN2 | SSM Decision Support Dashboard</strong>?</p>
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
