// frontend/src/permissions/PermissionsProvider.jsx — what the signed-in
// person may open and do, from GET /auth/me (Kelvin's permissions proposal).
//
// Loaded each time the signed-in app mounts (sign-in, or a page reload), and
// again whenever the backend refuses a request with 403 missing_permission:
// an admin may just have changed this person's access, so the tab or button
// they used disappears on that click, not at their next sign-in. Pages only
// hide what the backend would refuse anyway; the backend is the real control.
//
// Replaces reading the role off the login token (auth.getCurrentUser), which
// stayed stale after a role change until the token expired.
//
// Until the backend has /auth/me (a 404 today), `legacy` is true and access
// is what the app gave before: the token's role, with LEGACY_STAFF_ACCESS
// for staff. So this can deploy ahead of the backend without changing
// anyone's access, and it switches over by itself once /auth/me exists.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, ShieldAlert } from 'lucide-react';
import { getMe } from '../api/permissions';
import { PERMISSION_DENIED_EVENT, getCurrentUser, logout } from '../auth';
import { PermissionsContext } from './context';
import { LEGACY_STAFF_ACCESS } from './keys';
import './AccessGate.css';

const PermissionsProvider = ({ children }) => {
  const navigate = useNavigate();
  const [state, setState] = useState({ status: 'loading', role: null, permissions: [], legacy: false, error: '' });

  const refresh = useCallback(async () => {
    try {
      const me = await getMe();
      setState({
        status: 'ready',
        role: me?.role ?? null,
        permissions: Array.isArray(me?.permissions) ? me.permissions : [],
        legacy: false,
        error: '',
      });
    } catch (err) {
      // No /auth/me on this backend yet: keep the access the app gave before.
      if (err?.status === 404) {
        const role = getCurrentUser()?.role ?? null;
        setState({
          status: 'ready',
          role,
          permissions: role === 'staff' ? LEGACY_STAFF_ACCESS : [],
          legacy: true,
          error: '',
        });
        return;
      }
      // A failed refresh keeps what was already loaded: the backend still
      // refuses anything this person lost. Only a first load, with nothing
      // to show yet, stops at the error.
      setState((prev) => (prev.status === 'ready'
        ? prev
        : { status: 'error', role: null, permissions: [], legacy: false, error: err.message }));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const onDenied = () => refresh();
    window.addEventListener(PERMISSION_DENIED_EVENT, onDenied);
    return () => window.removeEventListener(PERMISSION_DENIED_EVENT, onDenied);
  }, [refresh]);

  const value = useMemo(() => {
    const granted = new Set(state.permissions);
    return {
      role: state.role,
      permissions: state.permissions,
      // True while the backend has no /auth/me: hide what needs it (the
      // Permissions screen).
      legacy: state.legacy,
      // An admin always has everything (the proposal's rule); anyone else
      // has what /auth/me lists. No key means no access.
      hasPermission: (key) => state.role === 'admin' || (Boolean(key) && granted.has(key)),
      refresh,
    };
  }, [state.role, state.permissions, state.legacy, refresh]);

  if (state.status === 'loading') {
    return (
      <div className="access-gate" role="status">
        <Loader2 size={22} className="access-gate-spin" aria-hidden="true" />
        <span>Loading your access…</span>
      </div>
    );
  }

  if (state.status === 'error') {
    const retry = () => {
      setState((prev) => ({ ...prev, status: 'loading' }));
      refresh();
    };
    const signOut = () => {
      logout();
      navigate('/login');
    };
    return (
      <div className="access-gate" role="alert">
        <div className="access-gate-card">
          <ShieldAlert size={26} className="access-gate-icon" aria-hidden="true" />
          <h2 className="access-gate-title">Couldn&apos;t load what your account can open</h2>
          <p className="access-gate-text">{state.error}</p>
          <div className="access-gate-actions">
            <button type="button" className="access-gate-btn primary" onClick={retry}>Try again</button>
            <button type="button" className="access-gate-btn" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </div>
    );
  }

  return <PermissionsContext.Provider value={value}>{children}</PermissionsContext.Provider>;
};

export default PermissionsProvider;
