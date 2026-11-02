import React, { useState, useEffect, useCallback, useRef } from 'react';
import SectionLede from './ui/SectionLede';
import {
  Plus, Pencil, Trash2, AlertTriangle, Mail, KeyRound, Link2, Copy, Check, Loader2, ShieldCheck, ShieldOff,
} from 'lucide-react';
import UserFormModal from './UserFormModal';
import PermissionsModal from './PermissionsModal';
import Modal from './Modal';
import { useToast } from './ToastProvider';
import { listUsers, createUser, updateUser, deleteUser, sendUserLink, resetUserMfa } from '../utils/usersApi';
import { getMfaStatus } from '../api/mfa';
import { getCurrentUser } from '../auth';
import { saveUserPermissions } from '../api/permissions';
import { usePermissions } from '../permissions/context';
import { roleLabel } from '../permissions/keys';
import { formatDateTime } from '../utils/formatDate';
import { LoadingStatus, SkeletonTableRows } from './Skeleton';
import PageHeader from './ui/PageHeader';
import './UserManagement.css';


// Selects the whole link, then scrolls the field back to its start (the
// site's address): focusing it leaves it scrolled to the end of the token.
const selectLink = (input) => {
  if (!input) return;
  input.select();
  input.scrollLeft = 0;
};

const getInitials = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] || '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase();
};

// One neutral tile for every avatar (UI pass), initials in ink.
const getAvatarColor = () => 'var(--badge-neutral-bg)';

const UserManagement = () => {
  const toast = useToast();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  // Add User is two modals: the form (name, email), then Next opens the
  // Permissions modal for the new person. newUser carries what they typed,
  // and the access chosen so far if they went Back.
  const [newUser, setNewUser] = useState(null);
  const [choosingAccess, setChoosingAccess] = useState(false);
  const [deletingUser, setDeletingUser] = useState(null);
  // Whose permissions are open (Kelvin's permissions proposal, task 6).
  const [permissionsUser, setPermissionsUser] = useState(null);
  const [deleteError, setDeleteError] = useState('');
  // Two-step sign-in (backend/mfa.py): whether the server has it at all, and
  // which roles must use it. The column and Reset button show only when it does.
  const [mfaInfo, setMfaInfo] = useState({ available: false, requiredRoles: [] });
  const [resettingMfaUser, setResettingMfaUser] = useState(null);
  const [resetMfaError, setResetMfaError] = useState('');
  // One link send at a time: a second result could open the share dialog
  // over the first and replace its link before the admin had copied it.
  const [sendingLinkFor, setSendingLinkFor] = useState(null);
  // A link the server couldn't email, for the admin to pass on by hand:
  // { url, expiresAt, problem, purpose, name, email, isNew }
  const [shareLink, setShareLink] = useState(null);
  const [copyState, setCopyState] = useState('idle'); // 'idle' | 'copied' | 'failed'
  const shareInputRef = useRef(null);

  const currentUser = getCurrentUser();
  // The Permissions screen needs the backend's permission endpoints; until
  // they exist (PermissionsProvider's `legacy`), its button stays hidden.
  const { legacy } = usePermissions();

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

  useEffect(() => {
    getMfaStatus()
      .then((s) => setMfaInfo({ available: s.available, requiredRoles: s.required_roles || [] }))
      .catch(() => {});
  }, []);

  const columnCount = mfaInfo.available ? 8 : 7;

  const handleOpenAdd = () => {
    setEditingUser(null);
    setNewUser(null);
    setIsFormOpen(true);
  };

  // The form's Next: on to the Permissions modal, same render so focus
  // passes straight from one dialog to the other.
  const handleNext = (details) => {
    setNewUser((prev) => ({ ...details, access: prev?.access }));
    setIsFormOpen(false);
    setChoosingAccess(true);
  };

  // The Permissions modal's Back: the form again, filled in as it was.
  const handleBackToDetails = (access) => {
    setNewUser((prev) => ({ ...prev, access }));
    setChoosingAccess(false);
    setIsFormOpen(true);
  };

  const closeAddUser = () => {
    setChoosingAccess(false);
    setNewUser(null);
  };

  const handleOpenEdit = (user) => {
    setEditingUser(user);
    setIsFormOpen(true);
  };

  // After an invite or reset link is issued: a toast when the server emailed
  // it, otherwise the link itself to share. The server only returns the link
  // when its email didn't go out, so normally an admin never sees one.
  const reportLink = (result, { purpose, name, email, isNew = false }) => {
    if (result.email_sent) {
      toast.success(`${purpose === 'reset' ? 'Reset link' : 'Invite'} emailed to ${email}`);
      return;
    }
    if (!result.setup_link) {
      toast.error(
        `The ${purpose === 'reset' ? 'password reset' : 'invite'} email to ${email} wasn't sent. `
        + (result.email_problem || 'Try again in a moment.')
      );
      return;
    }
    setCopyState('idle');
    setShareLink({
      url: result.setup_link,
      expiresAt: result.expires_at,
      problem: result.email_problem,
      purpose,
      name,
      email,
      isNew,
    });
  };

  // Edit User's Save, resolving with what its green check says;
  // handleFormSaved runs once that has played. A failure throws, and the
  // form shows it with a red X instead.
  const handleFormSubmit = async (values) => {
    // Only what changed: the server's audit entry then records exactly
    // that, and an unchanged role never trips its own-role check.
    const changes = {};
    if (values.fullName !== editingUser.full_name) changes.fullName = values.fullName;
    if (values.email !== editingUser.email) changes.email = values.email;
    if (values.role !== editingUser.role) changes.role = values.role;
    if (Object.keys(changes).length === 0) return { message: 'Nothing needed changing.' };
    await updateUser(editingUser.user_id, changes);
    loadUsers();
    return { message: `${values.email} was updated.` };
  };

  // Add User's Save, in the Permissions modal: creates the account with the
  // chosen role, then stores the pages ticked on or off.
  const handleCreate = async (values) => {
    let result;
    try {
      result = await createUser(values);
    } catch (err) {
      // Someone added this email since the list loaded (step 1 checks the
      // list): back to step 1, where the email can be changed, with the
      // error on the field and the chosen access kept.
      if (err.status === 409) {
        setNewUser((prev) => ({
          ...prev,
          access: { role: values.role, overrides: values.overrides || {} },
          emailError: err.message,
        }));
        setChoosingAccess(false);
        setIsFormOpen(true);
        loadUsers();
      }
      throw err;
    }
    // The pages ticked on or off, stored once the account exists. The account is already made if this part fails, so it
    // is reported rather than thrown: saving again would only hit "a user
    // with this email already exists".
    const exceptions = values.overrides || {};
    let accessFailed = '';
    if (!legacy && Object.keys(exceptions).length > 0) {
      try {
        await saveUserPermissions(result.user, { role: values.role, overrides: exceptions });
      } catch (err) {
        accessFailed = err.message || 'unknown error';
      }
    }
    loadUsers();
    // Short enough to read before the check mark closes (1.3 s). A failure
    // to store the page choices is not tucked in here: handleCreated raises
    // it as an error toast that stays until dismissed.
    return {
      message: `${values.fullName} added as ${roleLabel(values.role)}.`,
      invite: { result, name: values.fullName, email: values.email },
      accessFailed,
      role: values.role,
    };
  };

  const handleFormSaved = () => {
    setIsFormOpen(false);
  };

  // After Add User's check mark: close and, when the invite email didn't go
  // out, open the link to share in the same render, so focus passes straight
  // from one dialog to the other.
  const handleCreated = (outcome) => {
    closeAddUser();
    if (outcome?.accessFailed) {
      toast.error(
        `${outcome.invite.name}'s account was created, but their page choices didn't save `
        + `(${outcome.accessFailed}). For now they have the ${roleLabel(outcome.role)} defaults. `
        + 'Set them again with the Permissions button on their row.',
      );
    }
    const invite = outcome?.invite;
    if (invite && !invite.result.email_sent) {
      reportLink(invite.result, { purpose: 'invite', name: invite.name, email: invite.email, isNew: true });
    }
  };

  // "Now", re-read every 30 seconds, so an invite turns to "Invite expired"
  // while the page is open, not only after a reload.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const handleSendLink = async (user) => {
    if (sendingLinkFor !== null) return;
    setSendingLinkFor(user.user_id);
    try {
      const result = await sendUserLink(user.user_id);
      // A new invite replaces the old link: the row goes back to "Invite
      // pending" with the new expiry at once.
      if (result.purpose === 'invite' && result.expires_at) {
        setUsers((prev) => prev.map((u) => (u.user_id === user.user_id ? { ...u, invite_expires_at: result.expires_at } : u)));
        setNow(Date.now());
      }
      reportLink(result, { purpose: result.purpose, name: user.full_name, email: user.email });
    } catch (err) {
      toast.error(err.message || 'Failed to send the link.');
    } finally {
      setSendingLinkFor(null);
    }
  };

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareLink.url);
      setCopyState('copied');
    } catch {
      // No clipboard access (a plain-http address other than localhost, or
      // permission refused): select the link so Ctrl+C still works.
      shareInputRef.current?.focus();
      selectLink(shareInputRef.current);
      setCopyState('failed');
    }
  };

  const handleConfirmResetMfa = async () => {
    if (!resettingMfaUser) return;
    setResetMfaError('');
    try {
      await resetUserMfa(resettingMfaUser.user_id);
      toast.success(`Two-step sign-in reset for ${resettingMfaUser.email}`);
      setResettingMfaUser(null);
      await loadUsers();
    } catch (err) {
      setResetMfaError(err.message || 'Failed to reset two-step sign-in.');
    }
  };

  const handleConfirmDelete = async () => {
    if (!deletingUser) return;
    setDeleteError('');
    try {
      await deleteUser(deletingUser.user_id);
      toast.success(`${deletingUser.email} removed`);
      setDeletingUser(null);
      await loadUsers();
    } catch (err) {
      setDeleteError(err.message || 'Failed to delete user.');
    }
  };

  return (
    <div className="user-mgmt-page">
      <div className="user-mgmt-content">
        <PageHeader
          title="User"
          accent="management"
          subtitle="Manage access to the SSM Decision Support Dashboard: invite, edit and remove accounts, and choose what each person can open and do. New users get an email link to set their own password."
          actions={(
            <button type="button" className="btn btn-primary" onClick={handleOpenAdd}>
              <Plus size={16} aria-hidden="true" />
              Add user
            </button>
          )}
        />

        {loadError && (
          <div className="user-mgmt-banner-error">
            <AlertTriangle size={16} />
            {loadError}
          </div>
        )}

        {loading && <LoadingStatus>Loading users…</LoadingStatus>}
        <SectionLede className="is-standalone">Who has access</SectionLede>
        <div className="user-mgmt-table-wrapper">
          <table className="user-mgmt-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                {mfaInfo.available && <th>Two-step</th>}
                <th title="When the account was created">Joined</th>
                <th title="The account's most recent sign-in">Last sign-in</th>
                <th className="user-mgmt-actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <SkeletonTableRows rows={4} columns={columnCount} />
              ) : users.length > 0 ? (
                users.map((user) => {
                  // Invited = the account exists but no password has been set
                  // yet, so the link to send is the invite again.
                  const invited = user.status === 'invited';
                  // Expired = the newest invite link has stopped working
                  // (GET /users invite_expires_at); they need a new one.
                  const inviteExpiry = invited && user.invite_expires_at ? new Date(user.invite_expires_at) : null;
                  const inviteExpired = inviteExpiry !== null && inviteExpiry.getTime() <= now;
                  const linkLabel = invited ? 'Resend invite' : 'Send password reset link';
                  const LinkIcon = invited ? Mail : KeyRound;
                  const isSending = sendingLinkFor === user.user_id;
                  return (
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
                        <span className={`badge ${user.role === 'admin' ? 'badge-plum' : 'badge-info'} user-mgmt-role-badge`}>
                          {user.role}
                        </span>
                      </td>
                      <td>
                        {inviteExpired ? (
                          <span
                            className="badge badge-dot user-mgmt-invite-expired"
                            title={`The invite link expired ${formatDateTime(user.invite_expires_at)}. Resend the invite to send a new link.`}
                          >
                            Invite expired
                          </span>
                        ) : invited ? (
                          <span
                            className="badge badge-warning badge-dot"
                            title={inviteExpiry
                              ? `Hasn't set a password yet, so can't sign in. The invite link expires ${formatDateTime(user.invite_expires_at)}.`
                              : "Hasn't set a password yet, so can't sign in"}
                          >
                            Invite pending
                          </span>
                        ) : (
                          <span className="badge badge-success badge-dot">Active</span>
                        )}
                      </td>
                      {mfaInfo.available && (
                        <td>
                          {user.mfa_enabled ? (
                            <span className="user-mgmt-mfa on">On</span>
                          ) : mfaInfo.requiredRoles.includes(user.role) ? (
                            <span
                              className="user-mgmt-mfa due"
                              title="Required for this role: they set it up at their next sign-in"
                            >
                              Setup due
                            </span>
                          ) : (
                            <span className="user-mgmt-mfa off">Off</span>
                          )}
                        </td>
                      )}
                      <td className="user-mgmt-date-cell">
                        {formatDateTime(user.created_at)}
                      </td>
                      {/* From the sign-in history (user_session), for the security audit. */}
                      <td className="user-mgmt-date-cell">
                        {user.last_sign_in_at ? (
                          formatDateTime(user.last_sign_in_at)
                        ) : (
                          <span className="user-mgmt-never">Never</span>
                        )}
                      </td>
                      <td className="user-mgmt-actions-col">
                        {/* aria-busy rather than disabled while its own request
                            runs, so keyboard focus stays on the button. */}
                        <button
                          className="user-mgmt-icon-btn link"
                          onClick={() => handleSendLink(user)}
                          disabled={sendingLinkFor !== null && !isSending}
                          aria-busy={isSending || undefined}
                          aria-label={`${linkLabel} to ${user.full_name}`}
                          title={linkLabel}
                        >
                          {isSending
                            ? <Loader2 size={15} className="user-mgmt-spin" />
                            : <LinkIcon size={15} />}
                        </button>
                        {!legacy && (
                          <button
                            className="user-mgmt-icon-btn access"
                            onClick={() => setPermissionsUser(user)}
                            aria-label={`Permissions for ${user.full_name}`}
                            title="Permissions"
                          >
                            <ShieldCheck size={15} />
                          </button>
                        )}
                        {mfaInfo.available && user.mfa_enabled && user.email !== currentUser?.email && (
                          <button
                            className="user-mgmt-icon-btn mfa-reset"
                            onClick={() => { setResetMfaError(''); setResettingMfaUser(user); }}
                            aria-label={`Reset two-step sign-in for ${user.full_name}`}
                            title="Reset two-step sign-in"
                          >
                            <ShieldOff size={15} />
                          </button>
                        )}
                        <button
                          className="user-mgmt-icon-btn edit"
                          onClick={() => handleOpenEdit(user)}
                          aria-label={`Edit ${user.full_name}`}
                          title="Edit"
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
                              : 'Delete'
                          }
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={columnCount} className="user-mgmt-empty">No users found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <PermissionsModal
        isOpen={permissionsUser !== null}
        user={permissionsUser}
        isSelf={permissionsUser?.email === currentUser?.email}
        onClose={() => setPermissionsUser(null)}
        onSaved={() => {
          setPermissionsUser(null);
          loadUsers();
        }}
      />

      <PermissionsModal
        isOpen={choosingAccess}
        newUser={newUser}
        onBack={handleBackToDetails}
        onClose={closeAddUser}
        onCreate={handleCreate}
        onSaved={handleCreated}
      />

      <UserFormModal
        isOpen={isFormOpen}
        user={editingUser}
        draft={editingUser ? null : newUser}
        existingEmails={users.filter((u) => u.user_id !== editingUser?.user_id).map((u) => u.email)}
        onClose={() => {
          setIsFormOpen(false);
          if (!editingUser) setNewUser(null);
        }}
        onSubmit={handleFormSubmit}
        onSaved={handleFormSaved}
        onNext={handleNext}
      />

      {deletingUser && (
        <Modal
          isOpen={!!deletingUser}
          onClose={() => setDeletingUser(null)}
          label="Delete user confirmation"
          overlayClassName="user-mgmt-modal-overlay"
          containerClassName="user-mgmt-confirm-card"
        >
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
        </Modal>
      )}

      {resettingMfaUser && (
        <Modal
          isOpen={!!resettingMfaUser}
          onClose={() => setResettingMfaUser(null)}
          label="Reset two-step sign-in confirmation"
          overlayClassName="user-mgmt-modal-overlay"
          containerClassName="user-mgmt-confirm-card"
        >
            <div className="user-mgmt-confirm-icon">
              <ShieldOff size={20} />
            </div>
            <h3 className="user-mgmt-confirm-title">Reset two-step sign-in?</h3>
            <p className="user-mgmt-confirm-body">
              For when <strong>{resettingMfaUser.full_name}</strong> ({resettingMfaUser.email}) has lost
              their phone and their recovery codes. Their authenticator stops working and they&apos;re
              signed out.{' '}
              {mfaInfo.requiredRoles.includes(resettingMfaUser.role)
                ? 'Their role requires it, so they set it up again at their next sign-in.'
                : 'They can sign in with their password alone until they set it up again.'}
            </p>
            {resetMfaError && <div className="form-api-error">{resetMfaError}</div>}
            <div className="user-mgmt-confirm-actions">
              <button className="btn-cancel" onClick={() => setResettingMfaUser(null)}>
                Cancel
              </button>
              <button className="user-mgmt-confirm-delete-btn" onClick={handleConfirmResetMfa}>
                Reset
              </button>
            </div>
        </Modal>
      )}

      {/* The link is shown this once and never stored, so a stray click on
          the backdrop must not close it — only Done or Escape. */}
      {shareLink && (
        <Modal
          isOpen={Boolean(shareLink)}
          onClose={() => setShareLink(null)}
          labelledBy="user-mgmt-share-title"
          overlayClassName="user-mgmt-modal-overlay"
          containerClassName="user-mgmt-confirm-card user-mgmt-share-card"
          closeOnOverlayClick={false}
        >
          <div className="user-mgmt-share-icon">
            <Link2 size={20} />
          </div>
          <h3 id="user-mgmt-share-title" className="user-mgmt-confirm-title">Share this link</h3>
          <p className="user-mgmt-confirm-body">
            {shareLink.isNew ? 'The account is created, but the' : 'The'}{' '}
            {shareLink.purpose === 'reset' ? 'password reset' : 'invite'} email to{' '}
            <strong>{shareLink.email}</strong> wasn&apos;t sent.
          </p>
          {shareLink.problem && <p className="user-mgmt-share-problem">{shareLink.problem}</p>}
          <div className="user-mgmt-share-field">
            <input
              ref={shareInputRef}
              className="user-mgmt-share-input"
              value={shareLink.url}
              readOnly
              aria-label="Link to set a password"
              onFocus={(e) => selectLink(e.target)}
            />
            <button type="button" className="user-mgmt-copy-btn" onClick={handleCopyLink}>
              {copyState === 'copied' ? <Check size={15} /> : <Copy size={15} />}
              {copyState === 'copied' ? 'Copied' : 'Copy link'}
            </button>
          </div>
          {copyState === 'failed' && (
            <p className="user-mgmt-share-hint" role="status">
              Couldn&apos;t copy automatically. The link is selected, so press Ctrl+C (⌘C on a Mac).
            </p>
          )}
          <p className="user-mgmt-confirm-body">
            Send this link to <strong>{shareLink.name || shareLink.email}</strong> yourself, for example
            by chat. It works once
            {shareLink.expiresAt ? ` and expires ${formatDateTime(shareLink.expiresAt)}` : ''}.
          </p>
          <div className="user-mgmt-confirm-actions">
            <button type="button" className="user-mgmt-share-done-btn" onClick={() => setShareLink(null)}>
              Done
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
};

export default UserManagement;
