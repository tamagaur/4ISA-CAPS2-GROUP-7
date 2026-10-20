// My profile (/profile, 2026-10-16; laid out after Audrey's prototype the
// same day): the signed-in person's own display name and picture, opened
// from their name at the foot of the sidebar. Saves through PATCH /auth/me
// (api/profile.js); the sidebar reads the same /auth/me the permissions
// provider holds, so it follows a save at once. Email and role are shown,
// not edited: an admin changes those in User Management. The account
// security row reads GET /auth/mfa, as the sidebar's line does, and opens
// the same two-step sign-in dialog. Below it, Change password opens its own
// dialog (ChangePasswordModal: asks for the current password, Audrey
// 2026-10-20) — a dialog, since this whole page is one form.
//
// The picture never leaves the browser at full size: the person crops,
// zooms, turns and flips it in AvatarEditor (a dialog, Audrey 2026-10-18),
// which draws it at AVATAR_PX (canvas); it is sent as a small JPEG data
// URL, which the server keeps on the account row (migration 0058). On a server
// without that migration (/auth/me says profile_pictures: false) the
// button is disabled and says why; the name still saves.
import React, { useEffect, useRef, useState } from 'react';
import {
  Camera, Crop, Crown, Info, KeyRound, Mail, MapPin, ShieldAlert, ShieldCheck, Trash2, UserRound,
} from 'lucide-react';
import { usePermissions } from '../permissions/context';
import { getCurrentUser } from '../auth';
import { updateProfile } from '../api/profile';
import { getMfaStatus, MFA_STATUS_EVENT } from '../api/mfa';
import { useToast } from './ToastProvider';
import AccountSecurityModal from './AccountSecurityModal';
import AvatarEditor from './AvatarEditor';
import ChangePasswordModal from './ChangePasswordModal';
import './ProfilePage.css';

const AVATAR_PX = 192;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const NAME_MAX = 200;
// The one branch the app serves (the sidebar says the same under every
// name); accounts carry no branch of their own.
const BRANCH = 'Urdaneta';

const initialsOf = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] || '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase();
};

const titleCase = (word) => (word ? word[0].toUpperCase() + word.slice(1).toLowerCase() : '');

// The chosen file as a bitmap to frame. Throws a readable message for
// anything that isn't an image.
async function fileToBitmap(file) {
  if (!file.type.startsWith('image/')) throw new Error('Choose an image file (PNG, JPEG or WebP).');
  if (file.size > MAX_FILE_BYTES) throw new Error('That image is over 10 MB. Choose a smaller one.');
  try {
    return await createImageBitmap(file);
  } catch {
    throw new Error("That file couldn't be read as an image.");
  }
}

// The saved picture (a data URL) as a bitmap, to frame it again.
async function dataUrlToBitmap(dataUrl) {
  const blob = await (await fetch(dataUrl)).blob();
  return createImageBitmap(blob);
}

// What the security row says for each two-step sign-in state (GET
// /auth/mfa): on, off, paused on the server, or not loaded.
const SECURITY = {
  protected: {
    tone: 'good', icon: ShieldCheck, title: 'Protected',
    text: 'Two-step sign-in is on for your account.', action: 'Manage',
  },
  pending: {
    tone: 'warn', icon: ShieldAlert, title: 'Action required',
    text: 'Two-step sign-in is off. Turn it on to protect your account.', action: 'Set up',
  },
  unavailable: {
    tone: 'neutral', icon: ShieldAlert, title: 'Not available yet',
    text: "Two-step sign-in isn't turned on for this server.", action: null,
  },
  unknown: {
    tone: 'neutral', icon: ShieldAlert, title: 'Status unavailable',
    text: "Couldn't load your two-step sign-in status just now.", action: null,
  },
};

const Avatar = ({ src, name, className }) => (
  <div className={`profile-avatar ${className || ''}`} aria-hidden="true">
    {src ? <img src={src} alt="" className="profile-avatar-img" /> : initialsOf(name)}
  </div>
);

export default function ProfilePage() {
  const { profile, refresh } = usePermissions();
  const toast = useToast();
  const token = getCurrentUser();
  // What the server has now (the provider's /auth/me), with the login
  // token as the fallback on a backend without /auth/me.
  const savedName = profile?.fullName ?? token?.fullName ?? '';
  const savedAvatar = profile?.avatar ?? null;
  const email = profile?.email ?? token?.email ?? '';
  const role = profile?.role ?? token?.role ?? '';
  const picturesAvailable = Boolean(profile?.profilePictures);

  const [name, setName] = useState(savedName);
  const [avatar, setAvatar] = useState(savedAvatar);
  const [avatarTouched, setAvatarTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef(null);

  // The picture being adjusted: the bitmap (the chosen file at full size,
  // or the saved picture) and the editor's last settings for it, so
  // Adjust reopens where the person left off. `editing` opens the dialog.
  const [source, setSource] = useState(null);
  const sourceRef = useRef(null);
  sourceRef.current = source;
  const [editing, setEditing] = useState(false);
  const dropSource = () => {
    sourceRef.current?.bitmap.close();
    setSource(null);
    setEditing(false);
  };
  useEffect(() => () => sourceRef.current?.bitmap.close(), []);
  const openEditor = (bitmap, settings = null) => {
    if (sourceRef.current && sourceRef.current.bitmap !== bitmap) sourceRef.current.bitmap.close();
    setSource({ bitmap, settings, fresh: !settings });
    setEditing(true);
  };
  const applyEdit = ({ dataUrl, settings }) => {
    setSource((src) => (src ? { ...src, settings, fresh: false } : src));
    setAvatar(dataUrl);
    setAvatarTouched(true);
    setEditing(false);
  };
  // Cancel on a picture just chosen drops it; on Adjust it keeps the
  // picture as it was.
  const cancelEdit = () => {
    if (source?.fresh) dropSource();
    else setEditing(false);
  };

  // A fresh /auth/me (a save, or a re-check) resets what hasn't been
  // touched, so the form never shows a stale saved value.
  useEffect(() => { setName((current) => (current === savedName || saving ? current : savedName)); }, [savedName]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!avatarTouched) setAvatar(savedAvatar); }, [savedAvatar, avatarTouched]);

  // Two-step sign-in, as the sidebar's line reads it; the dialog (and any
  // other opener of it) announces every status it loads.
  const [mfa, setMfa] = useState(undefined);
  const [showSecurity, setShowSecurity] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getMfaStatus()
      .then((status) => { if (!cancelled) setMfa(status); })
      .catch(() => { if (!cancelled) setMfa(null); });
    const onStatus = (event) => setMfa(event.detail);
    window.addEventListener(MFA_STATUS_EVENT, onStatus);
    return () => {
      cancelled = true;
      window.removeEventListener(MFA_STATUS_EVENT, onStatus);
    };
  }, []);
  const securityKey = mfa === undefined ? null
    : mfa === null ? 'unknown'
      : !mfa.available ? 'unavailable'
        : mfa.enabled ? 'protected' : 'pending';
  const security = securityKey ? SECURITY[securityKey] : null;

  const cleanName = name.replace(/\s+/g, ' ').trim();
  const nameChanged = cleanName !== savedName;
  const avatarChanged = avatarTouched && avatar !== savedAvatar;
  const dirty = nameChanged || avatarChanged;
  const canSave = !saving && dirty && cleanName.length > 0 && cleanName.length <= NAME_MAX;

  const choosePicture = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError('');
    try {
      openEditor(await fileToBitmap(file));
    } catch (err) {
      setError(err.message);
    }
  };

  // Adjust the picture that is there: the chosen file at full size while it
  // is at hand, else the saved picture.
  const adjustPicture = async () => {
    if (!avatar) return;
    setError('');
    if (source && !source.fresh) {
      setEditing(true);
      return;
    }
    try {
      openEditor(await dataUrlToBitmap(avatar));
    } catch {
      setError("Couldn't open the picture to adjust it.");
    }
  };

  const removePicture = () => {
    dropSource();
    setAvatar(null);
    setAvatarTouched(true);
    setError('');
  };

  // Back to what was last loaded or saved.
  const cancel = () => {
    dropSource();
    setName(savedName);
    setAvatar(savedAvatar);
    setAvatarTouched(false);
    setError('');
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!canSave) return;
    setError('');
    setSaving(true);
    const body = {};
    if (nameChanged) body.full_name = cleanName;
    if (avatarChanged) body.avatar_data_url = avatar;
    try {
      await updateProfile(body);
      await refresh();
      setAvatarTouched(false);
      toast.success('Profile saved');
    } catch (err) {
      setError(err.message || 'Could not save your profile.');
    } finally {
      setSaving(false);
    }
  };

  const SecurityIcon = security?.icon;

  return (
    <div className="profile-page">
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-header-title">My <span className="page-title-accent">profile</span></h1>
          <p className="page-header-subtitle">Manage how you appear in the dashboard and in the audit log.</p>
        </div>
      </div>

      <div className="profile-layout">
        <form className="ui-card profile-card" onSubmit={handleSubmit} noValidate>
          {/* Who this is, as the server has it now. */}
          <header className="profile-hero">
            <Avatar src={savedAvatar} name={savedName} className="is-hero" />
            <div className="profile-hero-text">
              <h2 className="profile-hero-name">{savedName || email}</h2>
              <div className="profile-badges">
                {role && (
                  <span className="profile-badge is-role">
                    <Crown size={14} aria-hidden="true" />
                    {titleCase(role)}
                  </span>
                )}
                <span className="profile-badge">
                  <MapPin size={14} aria-hidden="true" />
                  {BRANCH}
                </span>
              </div>
              <p className="profile-hero-note">This profile controls how you appear in the dashboard and audit log.</p>
            </div>
          </header>

          <div className="profile-section">
            <div className="profile-section-label">
              <h3>Profile picture</h3>
              <p>This will be shown in the sidebar and throughout the dashboard.</p>
            </div>
            <div className="profile-section-body profile-picture">
              <Avatar src={avatar} name={cleanName || savedName} className="is-preview" />
              <div className="profile-picture-controls">
                <div className="profile-picture-buttons">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => fileRef.current?.click()}
                    disabled={!picturesAvailable}
                  >
                    <Camera size={16} aria-hidden="true" />
                    {avatar ? 'Change picture' : 'Choose a picture'}
                  </button>
                  {picturesAvailable && avatar && (
                    <button type="button" className="btn btn-secondary" onClick={adjustPicture}>
                      <Crop size={16} aria-hidden="true" />
                      Adjust
                    </button>
                  )}
                  {picturesAvailable && avatar && (
                    <button type="button" className="btn btn-secondary" onClick={removePicture}>
                      <Trash2 size={16} aria-hidden="true" />
                      Remove
                    </button>
                  )}
                </div>
                <p className="profile-help">
                  {picturesAvailable
                    ? `PNG, JPEG or WebP. Crop, zoom, rotate or flip it before saving; it is saved as a ${AVATAR_PX} px square.`
                    : "Picture uploads aren't available on this server yet; your initials are shown instead."}
                </p>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="visually-hidden"
                  onChange={choosePicture}
                  disabled={!picturesAvailable}
                  aria-label="Choose a profile picture"
                />
              </div>
            </div>
          </div>

          <div className="profile-section">
            <div className="profile-section-label">
              <label htmlFor="profile-name"><h3>Display name</h3></label>
              <p>This is how your name appears in the sidebar and in the audit log.</p>
            </div>
            <div className="profile-section-body">
              <input
                id="profile-name"
                className={`profile-input${cleanName.length === 0 ? ' is-invalid' : ''}`}
                type="text"
                value={name}
                maxLength={NAME_MAX}
                autoComplete="name"
                aria-invalid={cleanName.length === 0 || undefined}
                aria-describedby="profile-name-help"
                onChange={(e) => { setName(e.target.value); setError(''); }}
              />
              <p id="profile-name-help" className={`profile-help${cleanName.length === 0 ? ' is-error' : ''}`}>
                {cleanName.length === 0 ? 'Enter a display name.' : `Up to ${NAME_MAX} characters.`}
              </p>
            </div>
          </div>

          <div className="profile-section">
            <div className="profile-section-label">
              <h3>Account details</h3>
              <p>These details are managed by an administrator and cannot be changed here.</p>
            </div>
            <div className="profile-section-body profile-details">
              <div className="profile-detail">
                <Mail size={20} className="profile-detail-icon" aria-hidden="true" />
                <div>
                  <span className="profile-detail-label">Email</span>
                  <span className="profile-detail-value">{email || '—'}</span>
                  <span className="profile-detail-note">Managed in User Management.</span>
                </div>
              </div>
              <div className="profile-detail">
                <UserRound size={20} className="profile-detail-icon" aria-hidden="true" />
                <div>
                  <span className="profile-detail-label">Role</span>
                  <span className="profile-detail-value">{role ? role.toUpperCase() : '—'}</span>
                  <span className="profile-detail-note">Managed in User Management.</span>
                </div>
              </div>
            </div>
          </div>

          <div className="profile-section">
            <div className="profile-section-label">
              <h3>Account security</h3>
              <p>Two-step sign-in (a code from your phone after your password), and your password.</p>
            </div>
            <div className="profile-section-body profile-security-list">
              {security ? (
                <div className={`profile-security-panel is-${security.tone}`} role="status">
                  <span className="profile-security-icon"><SecurityIcon size={22} aria-hidden="true" /></span>
                  <div className="profile-security-text">
                    <strong>{security.title}</strong>
                    <span>{security.text}</span>
                  </div>
                  {security.action && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowSecurity(true)}>
                      {security.action}
                    </button>
                  )}
                </div>
              ) : (
                <div className="profile-security-panel is-neutral" role="status">
                  <span className="profile-security-text"><span>Checking your two-step sign-in…</span></span>
                </div>
              )}
              <div className="profile-security-panel is-neutral">
                <span className="profile-security-icon"><KeyRound size={22} aria-hidden="true" /></span>
                <div className="profile-security-text">
                  <strong>Password</strong>
                  <span>Change the password you sign in with. You&apos;ll need your current one.</span>
                </div>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowPassword(true)}>
                  Change password
                </button>
              </div>
            </div>
          </div>

          {error && <div className="form-api-error" role="alert">{error}</div>}

          <div className="profile-actions">
            <button type="button" className="btn btn-secondary" onClick={cancel} disabled={!dirty || saving}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={!canSave}>
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </form>

        <aside className="ui-card profile-aside" aria-label="About your profile">
          <div className="profile-aside-panel">
            <div className="profile-aside-item">
              <span className="profile-aside-icon"><Info size={18} aria-hidden="true" /></span>
              <div>
                <h3>About your profile</h3>
                <p>Your profile information is used to personalize your experience and identify your activity in the audit log.</p>
              </div>
            </div>
            <div className="profile-aside-item">
              <span className="profile-aside-icon"><UserRound size={18} aria-hidden="true" /></span>
              <div>
                <h3>Display name</h3>
                <p>Shown in the sidebar and in audit logs across the system.</p>
              </div>
            </div>
            <div className="profile-aside-item">
              <span className="profile-aside-icon"><Mail size={18} aria-hidden="true" /></span>
              <div>
                <h3>Email &amp; role</h3>
                <p>Managed by an administrator in User Management.</p>
              </div>
            </div>
            <div className="profile-aside-item">
              <span className="profile-aside-icon is-green"><ShieldCheck size={18} aria-hidden="true" /></span>
              <div>
                <h3>Account security</h3>
                <p>Indicates the current status of your account protection, and where you change your password.</p>
              </div>
            </div>
          </div>
        </aside>
      </div>

      <AvatarEditor
        isOpen={editing}
        bitmap={source?.bitmap ?? null}
        initial={source?.settings ?? null}
        outputPx={AVATAR_PX}
        onCancel={cancelEdit}
        onApply={applyEdit}
      />
      <AccountSecurityModal isOpen={showSecurity} onClose={() => setShowSecurity(false)} onStatusChange={setMfa} />
      <ChangePasswordModal isOpen={showPassword} onClose={() => setShowPassword(false)} email={email} />
    </div>
  );
}
