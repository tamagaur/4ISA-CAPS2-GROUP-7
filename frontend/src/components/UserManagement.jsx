import React, { useState, useEffect, useCallback } from 'react';
import { Plus, Pencil, Trash2, AlertTriangle } from 'lucide-react';
import UserFormModal from './UserFormModal';
import { listUsers, createUser, updateUser, deleteUser } from '../utils/usersApi';
import { logAction } from '../utils/auditLogger';
import { getCurrentUser } from '../auth';
import './UserManagement.css';

const getInitials = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] || '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase();
};

const getAvatarColor = (name) => {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const colors = ['#f56565', '#4299e1', '#48bb78', '#ed8936', '#9f7aea', '#ed64a6'];
  return colors[Math.abs(hash) % colors.length];
};

const UserManagement = () => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [deletingUser, setDeletingUser] = useState(null);
  const [deleteError, setDeleteError] = useState('');

  const currentUser = getCurrentUser();

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const data = await listUsers();
      setUsers(data);
    } catch (err) {
      setLoadError(err.message || 'Failed to load users.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const handleOpenAdd = () => {
    setEditingUser(null);
    setIsFormOpen(true);
  };

  const handleOpenEdit = (user) => {
    setEditingUser(user);
    setIsFormOpen(true);
  };

  const handleFormSubmit = async (values) => {
    if (editingUser) {
      await updateUser(editingUser.user_id, values);
      logAction('Edit User', `Updated ${values.email} (${values.role})`);
    } else {
      await createUser(values);
      logAction('Add User', `Created ${values.email} (${values.role})`);
    }
    await loadUsers();
  };

  const handleConfirmDelete = async () => {
    if (!deletingUser) return;
    setDeleteError('');
    try {
      await deleteUser(deletingUser.user_id);
      logAction('Delete User', `Removed ${deletingUser.email}`);
      setDeletingUser(null);
      await loadUsers();
    } catch (err) {
      setDeleteError(err.message || 'Failed to delete user.');
    }
  };

  return (
    <div className="user-mgmt-page">
      <div className="user-mgmt-content">
        <div className="user-mgmt-header">
          <div>
            <h2 className="user-mgmt-title">User <span>management</span></h2>
            <p className="user-mgmt-subtitle">
              Create, edit, and remove staff accounts. Only admins can access this page.
            </p>
          </div>
          <button className="user-mgmt-add-btn" onClick={handleOpenAdd}>
            <Plus size={16} />
            Add User
          </button>
        </div>

        {loadError && (
          <div className="user-mgmt-banner-error">
            <AlertTriangle size={16} />
            {loadError}
          </div>
        )}

        <div className="user-mgmt-table-wrapper">
          <table className="user-mgmt-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Created</th>
                <th className="user-mgmt-actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan="5" className="user-mgmt-empty">Loading users...</td>
                </tr>
              ) : users.length > 0 ? (
                users.map((user) => (
                  <tr key={user.user_id}>
                    <td className="user-mgmt-name-cell">
                      <div className="user-mgmt-name-info">
                        <div
                          className="user-mgmt-avatar"
                          style={{ backgroundColor: getAvatarColor(user.full_name) }}
                        >
                          {getInitials(user.full_name)}
                        </div>
                        <span className="user-mgmt-name">{user.full_name}</span>
                      </div>
                    </td>
                    <td className="user-mgmt-email-cell">{user.email}</td>
                    <td>
                      <span className={`user-mgmt-role-badge role-${user.role}`}>
                        {user.role}
                      </span>
                    </td>
                    <td className="user-mgmt-date-cell">
                      {new Date(user.created_at).toLocaleDateString()}
                    </td>
                    <td className="user-mgmt-actions-col">
                      <button
                        className="user-mgmt-icon-btn"
                        onClick={() => handleOpenEdit(user)}
                        aria-label={`Edit ${user.full_name}`}
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        className="user-mgmt-icon-btn danger"
                        onClick={() => setDeletingUser(user)}
                        disabled={user.email === currentUser?.email}
                        aria-label={`Delete ${user.full_name}`}
                        title={
                          user.email === currentUser?.email
                            ? "You can't delete your own account"
                            : undefined
                        }
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan="5" className="user-mgmt-empty">No users found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <UserFormModal
        isOpen={isFormOpen}
        user={editingUser}
        onClose={() => setIsFormOpen(false)}
        onSubmit={handleFormSubmit}
      />

      {deletingUser && (
        <div className="user-mgmt-modal-overlay" onClick={() => setDeletingUser(null)}>
          <div className="user-mgmt-confirm-card" onClick={(e) => e.stopPropagation()}>
            <div className="user-mgmt-confirm-icon">
              <AlertTriangle size={20} />
            </div>
            <h3 className="user-mgmt-confirm-title">Delete this user?</h3>
            <p className="user-mgmt-confirm-body">
              <strong>{deletingUser.full_name}</strong> ({deletingUser.email}) will lose access
              immediately. This can't be undone.
            </p>
            {deleteError && <div className="form-api-error">{deleteError}</div>}
            <div className="user-mgmt-confirm-actions">
              <button className="btn-cancel" onClick={() => setDeletingUser(null)}>
                Cancel
              </button>
              <button className="user-mgmt-confirm-delete-btn" onClick={handleConfirmDelete}>
                Delete User
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default UserManagement;
