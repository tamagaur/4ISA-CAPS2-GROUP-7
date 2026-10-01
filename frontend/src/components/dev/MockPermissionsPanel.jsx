// DEV ONLY. Act as Admin or Staff, or tick single permissions, to
// try the permission screens before the backend has them. DashboardLayout
// renders this only on a dev server with VITE_MOCK_PERMISSIONS=true (see
// api/mocks/permissionsMock.js); it is deleted with the mock in Phase 6.
import React, { useState } from 'react';
import { MOCK_CATALOG, getMockMe, resetMock, setMockMe } from '../../api/mocks/permissionsMock';
import { getCurrentUser } from '../../auth';
import { usePermissions } from '../../permissions/context';
import { ROLES } from '../../permissions/keys';
import { effectiveKeys, presetKeys } from '../../permissions/rules';
import './MockPermissionsPanel.css';

const MockPermissionsPanel = () => {
  const { refresh } = usePermissions();
  const tokenRole = getCurrentUser()?.role;
  const [open, setOpen] = useState(false);
  const [me, setMe] = useState(() => getMockMe(tokenRole));
  const [pending, setPending] = useState(false);

  const granted = effectiveKeys(MOCK_CATALOG, me.role, me.overrides);
  const preset = presetKeys(MOCK_CATALOG, me.role);

  const save = (next) => {
    setMockMe(next);
    setMe(getMockMe(tokenRole));
    setPending(true);
  };

  const toggle = (key, checked) => {
    const overrides = { ...me.overrides };
    if (preset.has(key) === checked) delete overrides[key];
    else overrides[key] = checked;
    save({ role: me.role, overrides });
  };

  const apply = () => {
    setPending(false);
    refresh();
  };

  const reset = () => {
    resetMock();
    setMe(getMockMe(tokenRole));
    setPending(false);
    refresh();
  };

  return (
    <div className="mock-perm-panel">
      <button type="button" className="mock-perm-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        DEV · acting as {me.role}{pending ? ' (not applied)' : ''}
      </button>
      {open && (
        <div className="mock-perm-body">
          <label className="mock-perm-role">
            Act as
            <select value={me.role} onChange={(e) => save({ role: e.target.value, overrides: {} })}>
              {ROLES.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
            </select>
          </label>
          <fieldset className="mock-perm-list" disabled={me.role === 'admin'}>
            <legend>Permissions</legend>
            {MOCK_CATALOG.permissions.map((permission) => (
              <label key={permission.key} className="mock-perm-item">
                <input
                  type="checkbox"
                  checked={granted.has(permission.key)}
                  onChange={(e) => toggle(permission.key, e.target.checked)}
                />
                <span>{permission.key}</span>
              </label>
            ))}
          </fieldset>
          <p className="mock-perm-hint">
            Apply updates the app now. Leave a change unapplied to try the 403 path: the next refused
            action shows its message and the app catches up.
          </p>
          <div className="mock-perm-actions">
            <button type="button" onClick={apply}>Apply</button>
            <button type="button" onClick={reset}>Reset mock</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default MockPermissionsPanel;
