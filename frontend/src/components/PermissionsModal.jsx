// One user's access, for an admin to set (Kelvin's permissions proposal,
// frontend task 6): a role, then single permissions ticked on or off where
// this person should differ from that role's defaults.
//
// Everything listed comes from the catalog (GET /admin/permissions/catalog),
// so a permission added on the backend shows up here with no frontend
// change. Save sends only what differs from the role's preset; the backend
// enforces what's saved and refuses a change that would leave no admin or
// lock the saver out (409), which this screen puts in plain words.
//
// It is also step 2 of Add User: given `newUser` ({ fullName, email } from
// the Add User form's Next) instead of `user`, it starts from the Staff
// defaults, adds a Back button, and its Save calls onCreate to make the
// account with this access. While the backend can't store single
// permissions yet (PermissionsProvider's `legacy`), it offers Admin and
// Staff and shows, read-only, the pages that role opens.
import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, X } from 'lucide-react';
import Modal from './Modal';
import SaveResult from './SaveResult';
import { useSaveResult } from '../utils/useSaveResult';
import { getPermissionCatalog, getUserPermissions, saveUserPermissions } from '../api/permissions';
import { usePermissions } from '../permissions/context';
import { effectiveKeys, normalizeOverrides, presetKeys } from '../permissions/rules';
import { LEGACY_CATALOG, ROLES, roleLabel } from '../permissions/keys';
import './UserFormModal.css';
import './PermissionsModal.css';

// The proposal's refusals, in words.
const SAVE_ERRORS = {
  last_admin: () => 'This is the only admin. Make someone else an admin first.',
  self_lockout: () => "You can't take away your own admin access. Ask another admin to do it.",
  self_promotion: () => "You can't change your own access. Ask another admin to do it.",
  unknown_permission: (key) => `"${key}" isn't a known permission any more. Close this and open it again.`,
  user_not_found: () => 'This account no longer exists. Close this and refresh the list.',
};

// Catalog order, grouped by page ("group"), keeping each group's first place.
function groupPermissions(permissions) {
  const groups = new Map();
  for (const permission of permissions) {
    const group = permission.group || 'Other';
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(permission);
  }
  return [...groups.entries()];
}

const sameOverrides = (a, b) => {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((key) => a[key] === b[key]);
};

const PermissionsModal = ({ isOpen, user, newUser = null, isSelf = false, onClose, onSaved, onBack, onCreate }) => {
  const creating = Boolean(newUser);
  const { legacy } = usePermissions();
  // Nothing to tick until the backend can store it: show the role's access.
  const readOnly = creating && legacy;
  const [catalog, setCatalog] = useState(null);
  const [initial, setInitial] = useState({ role: null, overrides: {} });
  const [role, setRole] = useState(null);
  const [overrides, setOverrides] = useState({});
  const [load, setLoad] = useState({ status: 'idle', error: '' });
  const [apiError, setApiError] = useState('');
  const { saving, result, run, reset } = useSaveResult();

  useEffect(() => {
    if (!isOpen || (!user && !newUser)) return undefined;
    let cancelled = false;
    setLoad({ status: 'loading', error: '' });
    setApiError('');
    reset();
    if (newUser) {
      // A new person starts on Staff, or on what was chosen before Back.
      const start = newUser.access || { role: 'staff', overrides: {} };
      const ready = (loadedCatalog) => {
        if (cancelled) return;
        setCatalog(loadedCatalog);
        setInitial(start);
        setRole(start.role);
        setOverrides(normalizeOverrides(loadedCatalog, start.role, start.overrides));
        setLoad({ status: 'ready', error: '' });
      };
      if (legacy) {
        ready(LEGACY_CATALOG);
      } else {
        getPermissionCatalog()
          .then(ready)
          .catch((err) => { if (!cancelled) setLoad({ status: 'error', error: err.message }); });
      }
      return () => { cancelled = true; };
    }
    Promise.all([getPermissionCatalog(), getUserPermissions(user)])
      .then(([loadedCatalog, current]) => {
        if (cancelled) return;
        const start = {
          role: current.role,
          overrides: normalizeOverrides(loadedCatalog, current.role, current.overrides || {}),
        };
        setCatalog(loadedCatalog);
        setInitial(start);
        setRole(start.role);
        setOverrides(start.overrides);
        setLoad({ status: 'ready', error: '' });
      })
      .catch((err) => {
        if (!cancelled) setLoad({ status: 'error', error: err.message });
      });
    return () => { cancelled = true; };
  }, [isOpen, user, newUser, legacy, reset]);

  const preset = useMemo(() => presetKeys(catalog, role), [catalog, role]);
  const granted = useMemo(() => effectiveKeys(catalog, role, overrides), [catalog, role, overrides]);
  const groups = useMemo(() => groupPermissions(catalog?.permissions || []), [catalog]);

  if (!isOpen || (!user && !newUser)) return null;

  const person = creating ? { full_name: newUser.fullName, email: newUser.email } : user;
  const isAdminRole = role === 'admin';
  const changed = role !== initial.role || !sameOverrides(overrides, initial.overrides);
  const added = Object.values(overrides).filter(Boolean).length;
  const removed = Object.values(overrides).filter((value) => !value).length;

  const handleRole = (e) => {
    const next = e.target.value;
    setRole(next);
    // Overrides the new role's preset already covers are dropped.
    setOverrides((prev) => normalizeOverrides(catalog, next, prev));
  };

  const handleToggle = (key, checked) => {
    setOverrides((prev) => normalizeOverrides(catalog, role, { ...prev, [key]: checked }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setApiError('');
    if (creating) {
      // Add User: create the account with this access. onCreate resolves
      // with { message } for the check mark, or throws for the red X.
      await run(() => onCreate({
        fullName: newUser.fullName,
        email: newUser.email,
        role,
        overrides: readOnly ? {} : normalizeOverrides(catalog, role, overrides),
      }), {
        onSaved: (outcome) => onSaved?.(outcome),
        onFailed: setApiError,
      });
      return;
    }
    await run(async () => {
      try {
        const saved = await saveUserPermissions(user, { role, overrides: normalizeOverrides(catalog, role, overrides) });
        const count = Array.isArray(saved?.permissions) ? saved.permissions.length : granted.size;
        return { saved, message: `${user.full_name} is now ${roleLabel(saved?.role || role)}, with ${count} of ${catalog.permissions.length} permissions.` };
      } catch (err) {
        const explain = SAVE_ERRORS[err.code];
        throw new Error(explain ? explain(err.permission) : err.message);
      }
    }, {
      onSaved: (outcome) => onSaved?.(outcome?.saved),
      onFailed: setApiError,
    });
  };

  let summary = isAdminRole
    ? 'Admin: every permission, always.'
    : [`${roleLabel(role)} defaults`, added && `${added} added`, removed && `${removed} removed`].filter(Boolean).join(', ');
  if (readOnly && !isAdminRole) summary = `${roleLabel(role)}: ${granted.size} of ${catalog?.permissions.length || 0} permissions.`;
  const boxesLocked = isSelf || saving || isAdminRole || readOnly;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      label={`Permissions for ${person.full_name}`}
      overlayClassName="modal-overlay"
      containerClassName="modal-card permissions-modal-card"
      closeOnOverlayClick={!saving}
      closeOnEscape={!saving}
    >
      {result ? (
        <SaveResult
          ok={result.ok}
          title={result.ok ? (creating ? 'User added' : 'Permissions saved') : "Couldn't save"}
          message={result.ok ? result.value?.message : result.message}
        />
      ) : (
        <>
          <div className="modal-header">
            <div>
              <h3 className="modal-title">Permissions</h3>
              <p className="modal-subtitle">
                {creating && 'Step 2 of 2 · '}{person.full_name} · {person.email}
              </p>
            </div>
            <button className="modal-close-btn" onClick={onClose} disabled={saving} aria-label="Close">
              <X size={20} />
            </button>
          </div>

          {load.status === 'loading' && <p className="perm-status" role="status">Loading permissions…</p>}
          {load.status === 'error' && <div className="form-api-error">{load.error}</div>}

          {load.status === 'ready' && (
            <form onSubmit={handleSave} className="modal-form" noValidate>
              {isSelf && (
                <p className="perm-note">You can&apos;t change your own access. Ask another admin to do it.</p>
              )}
              {readOnly && (
                <p className="perm-note">
                  For now the role decides what they can open and do (ticked below). Ticking boxes person by
                  person turns on once the server supports it.
                </p>
              )}

              <div className="form-group">
                <label className="form-label" htmlFor="perm-role">ROLE</label>
                <select
                  id="perm-role"
                  className="form-input form-select"
                  value={role}
                  onChange={handleRole}
                  disabled={isSelf || saving}
                >
                  {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
                <span className="form-hint">
                  {isAdminRole && 'Admins can use everything, so there is nothing to tick.'}
                  {!isAdminRole && readOnly && `What a ${roleLabel(role)} can open and do.`}
                  {!isAdminRole && !readOnly
                    && `The boxes start from the ${roleLabel(role)} defaults; tick or untick only the exceptions.`}
                </span>
              </div>

              {groups.map(([group, permissions]) => (
                <fieldset className="perm-group" key={group} disabled={boxesLocked}>
                  <legend className="perm-group-title">{group}</legend>
                  {permissions.map((permission) => {
                    const change = overrides[permission.key];
                    return (
                      <label
                        key={permission.key}
                        className={`perm-row${change === undefined ? '' : ' perm-row-changed'}`}
                      >
                        <input
                          type="checkbox"
                          checked={granted.has(permission.key)}
                          onChange={(e) => handleToggle(permission.key, e.target.checked)}
                          aria-describedby={`perm-desc-${permission.key}`}
                        />
                        <span className="perm-text">
                          <span className="perm-label">
                            {permission.label}
                            {change !== undefined && (
                              <span className={`perm-change ${change ? 'added' : 'removed'}`}>
                                {change ? 'Added' : 'Removed'}
                              </span>
                            )}
                          </span>
                          {(permission.description || !readOnly) && (
                            <span className="perm-desc" id={`perm-desc-${permission.key}`}>
                              {permission.description}
                              {!isAdminRole && !readOnly && change === undefined && preset.has(permission.key)
                                && ' Part of this role.'}
                            </span>
                          )}
                        </span>
                      </label>
                    );
                  })}
                </fieldset>
              ))}

              <p className="perm-summary">{summary}</p>
              {apiError && <div className="form-api-error">{apiError}</div>}

              <div className="modal-actions">
                {creating && (
                  <button
                    type="button"
                    className="btn-cancel perm-back"
                    onClick={() => onBack?.({ role, overrides })}
                    disabled={saving}
                  >
                    <ArrowLeft size={16} aria-hidden="true" />
                    Back
                  </button>
                )}
                {!isSelf && !isAdminRole && !readOnly && (
                  <button
                    type="button"
                    className="btn-cancel perm-reset"
                    onClick={() => setOverrides({})}
                    disabled={saving || Object.keys(overrides).length === 0}
                  >
                    Reset to role defaults
                  </button>
                )}
                <button type="button" className="btn-cancel" onClick={onClose} disabled={saving}>
                  {isSelf ? 'Close' : 'Cancel'}
                </button>
                {!isSelf && (
                  <button type="submit" className="btn-submit" disabled={saving || (!creating && !changed)}>
                    {saving ? 'Saving...' : 'Save'}
                  </button>
                )}
              </div>
            </form>
          )}
        </>
      )}
    </Modal>
  );
};

export default PermissionsModal;
