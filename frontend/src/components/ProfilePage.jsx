// My profile (/profile, 2026-10-16; laid out after Audrey's prototype the
// same day): the signed-in person's own display name and picture, opened
// from their name at the foot of the sidebar. Saves through PATCH /auth/me
// (api/profile.js); the sidebar reads the same /auth/me the permissions
// provider holds, so it follows a save at once. Email and role are shown,
// not edited: an admin changes those in User Management. The account
// security row reads GET /auth/mfa, as the sidebar's line does, and opens
// the same two-step sign-in dialog.
//
// The picture never leaves the browser at full size: the person frames it
// (sizes and moves it in the square: slider and drag, Audrey 2026-10-16),
// it is drawn at AVATAR_PX here (canvas), then sent as a small JPEG data
// URL, which the server keeps on the account row (migration 0058). On a server
// without that migration (/auth/me says profile_pictures: false) the
// button is disabled and says why; the name still saves.
import React, { useEffect, useRef, useState } from 'react';
import {
  Camera, Crown, Info, Mail, MapPin, Maximize2, ShieldAlert, ShieldCheck, Trash2, UserRound,
} from 'lucide-react';
import { usePermissions } from '../permissions/context';
import { getCurrentUser } from '../auth';
import { updateProfile } from '../api/profile';
import { getMfaStatus, MFA_STATUS_EVENT } from '../api/mfa';
import { useToast } from './ToastProvider';
import AccountSecurityModal from './AccountSecurityModal';
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

// How the picture sits in the square: `zoom` 1 fills the square with the
// picture's shorter side (3 shows a third of it); `ox`/`oy` (-1..1) slide
// it as far as the zoom leaves room, 0 being centred. drawFramed() paints
// the framed picture at AVATAR_PX on white (a transparent PNG would
// otherwise come out on black).
const MIN_ZOOM = 1;
const MAX_ZOOM = 3;
const NUDGE = 0.1;
const clamp1 = (v) => Math.max(-1, Math.min(1, v));
const frameOf = ({ bitmap, zoom }) => {
  const scale = (AVATAR_PX / Math.min(bitmap.width, bitmap.height)) * zoom;
  const dw = bitmap.width * scale;
  const dh = bitmap.height * scale;
  return { dw, dh, slackX: Math.max(0, dw - AVATAR_PX), slackY: Math.max(0, dh - AVATAR_PX) };
};
const drawFramed = (canvas, picture) => {
  const { dw, dh, slackX, slackY } = frameOf(picture);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, AVATAR_PX, AVATAR_PX);
  ctx.drawImage(picture.bitmap, (-(1 + picture.ox) * slackX) / 2, (-(1 + picture.oy) * slackY) / 2, dw, dh);
};

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

  // The picture being framed ({ bitmap, zoom, ox, oy }) or null. While one
  // is open the preview is a canvas the person drags, with a size slider,
  // and `avatar` is drawn again from it on every change, so Save sends
  // exactly what the preview shows.
  const [picture, setPicture] = useState(null);
  const pictureRef = useRef(null);
  pictureRef.current = picture;
  const canvasRef = useRef(null);
  const dragRef = useRef(null);
  const openPicture = (bitmap) => {
    pictureRef.current?.bitmap.close();
    setPicture({ bitmap, zoom: MIN_ZOOM, ox: 0, oy: 0 });
    setAvatarTouched(true);
  };
  const closePicture = () => {
    pictureRef.current?.bitmap.close();
    setPicture(null);
  };
  useEffect(() => () => pictureRef.current?.bitmap.close(), []);
  useEffect(() => {
    if (!picture || !canvasRef.current) return;
    drawFramed(canvasRef.current, picture);
    setAvatar(canvasRef.current.toDataURL('image/jpeg', 0.86));
  }, [picture]);
  const movePicture = (change) => setPicture((p) => (p ? { ...p, ...change(p) } : p));
  const onPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, ox: picture.ox, oy: picture.oy };
  };
  const onPointerMove = (e) => {
    const start = dragRef.current;
    if (!start) return;
    // Screen pixels to canvas pixels, then to the share of the room the
    // zoom leaves; dragging right shows more of the left.
    const perPx = AVATAR_PX / e.currentTarget.getBoundingClientRect().width;
    const dx = (e.clientX - start.x) * perPx;
    const dy = (e.clientY - start.y) * perPx;
    movePicture((p) => {
      const { slackX, slackY } = frameOf(p);
      return {
        ox: slackX ? clamp1(start.ox - (2 * dx) / slackX) : 0,
        oy: slackY ? clamp1(start.oy - (2 * dy) / slackY) : 0,
      };
    });
  };
  const endDrag = () => { dragRef.current = null; };
  const onCanvasKey = (e) => {
    const step = { ArrowLeft: [NUDGE, 0], ArrowRight: [-NUDGE, 0], ArrowUp: [0, NUDGE], ArrowDown: [0, -NUDGE] }[e.key];
    if (!step) return;
    e.preventDefault();
    movePicture((p) => ({ ox: clamp1(p.ox + step[0]), oy: clamp1(p.oy + step[1]) }));
  };

  // A fresh /auth/me (a save, or a re-check) resets what hasn't been
  // touched, so the form never shows a stale saved value.
  useEffect(() => { setName((current) => (current === savedName || saving ? current : savedName)); }, [savedName]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!avatarTouched) setAvatar(savedAvatar); }, [savedAvatar, avatarTouched]);

  // Two-step sign-in, as the sidebar's line reads it; the dialog (and any
  // other opener of it) announces every status it loads.
  const [mfa, setMfa] = useState(undefined);
  const [showSecurity, setShowSecurity] = useState(false);
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
      openPicture(await fileToBitmap(file));
    } catch (err) {
      setError(err.message);
    }
  };

  // Frame the picture that is already there (saved, or just chosen).
  const adjustPicture = async () => {
    if (!avatar) return;
    setError('');
    try {
      openPicture(await dataUrlToBitmap(avatar));
    } catch {
      setError("Couldn't open the picture to adjust it.");
    }
  };

  const removePicture = () => {
    closePicture();
    setAvatar(null);
    setAvatarTouched(true);
    setError('');
  };

  // Back to what was last loaded or saved.
  const cancel = () => {
    closePicture();
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
      closePicture();
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
              {picture ? (
                <div className="profile-avatar is-preview is-framing">
                  <canvas
                    ref={canvasRef}
                    width={AVATAR_PX}
                    height={AVATAR_PX}
                    className="profile-avatar-canvas"
                    tabIndex={0}
                    role="img"
                    aria-label="Your picture in its frame. Drag it, or use the arrow keys, to move it."
                    onPointerDown={onPointerDown}
                    onPointerMove={onPointerMove}
                    onPointerUp={endDrag}
                    onPointerCancel={endDrag}
                    onKeyDown={onCanvasKey}
                  />
                </div>
              ) : (
                <Avatar src={avatar} name={cleanName || savedName} className="is-preview" />
              )}
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
                  {picturesAvailable && avatar && !picture && (
                    <button type="button" className="btn btn-secondary" onClick={adjustPicture}>
                      <Maximize2 size={16} aria-hidden="true" />
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
                {picture ? (
                  <div className="profile-framing">
                    <span className="profile-framing-label">Size</span>
                    <input
                      type="range"
                      min={MIN_ZOOM}
                      max={MAX_ZOOM}
                      step={0.01}
                      value={picture.zoom}
                      onChange={(e) => movePicture(() => ({ zoom: Number(e.target.value) }))}
                      aria-label="Picture size in the frame"
                    />
                    <span className="profile-framing-value">{Math.round(picture.zoom * 100)}%</span>
                    <button
                      type="button"
                      className="profile-framing-reset"
                      onClick={() => movePicture(() => ({ zoom: MIN_ZOOM, ox: 0, oy: 0 }))}
                    >
                      Reset
                    </button>
                    <span className="profile-framing-hint">Drag the picture to move it.</span>
                  </div>
                ) : (
                  <p className="profile-help">
                    {picturesAvailable
                      ? `PNG, JPEG or WebP. You can size and move it in its frame; it is saved as a ${AVATAR_PX} px square.`
                      : "Picture uploads aren't available on this server yet; your initials are shown instead."}
                  </p>
                )}
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
              <p>Two-step sign-in: a code from your phone after your password.</p>
            </div>
            <div className="profile-section-body">
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
                <p>Indicates the current status of your account protection.</p>
              </div>
            </div>
          </div>
        </aside>
      </div>

      <AccountSecurityModal isOpen={showSecurity} onClose={() => setShowSecurity(false)} onStatusChange={setMfa} />
    </div>
  );
}
