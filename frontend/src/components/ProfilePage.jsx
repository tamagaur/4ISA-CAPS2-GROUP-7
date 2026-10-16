// My profile (/profile, 2026-10-16): the signed-in person's own display
// name and picture, opened from their name at the foot of the sidebar.
// Saves through PATCH /auth/me (api/profile.js); the sidebar reads the
// same /auth/me the permissions provider holds, so it follows a save at
// once. Email and role are shown, not edited: an admin changes those in
// User Management.
//
// The picture never leaves the browser at full size: it is squared and
// shrunk to AVATAR_PX here (canvas), then sent as a small JPEG data URL,
// which the server keeps on the account row (migration 0058). On a server
// without that migration the picture controls say so and stay off; the
// name still saves.
import React, { useEffect, useRef, useState } from 'react';
import { Camera, Trash2 } from 'lucide-react';
import { usePermissions } from '../permissions/context';
import { getCurrentUser } from '../auth';
import { updateProfile } from '../api/profile';
import { useToast } from './ToastProvider';
import './ProfilePage.css';

const AVATAR_PX = 192;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const NAME_MAX = 200;

const initialsOf = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] || '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase();
};

// The chosen file as a 192 x 192 JPEG data URL: the middle square of the
// image, scaled down, on white (a transparent PNG would otherwise come out
// on black). Throws a readable message for anything that isn't an image.
async function fileToAvatar(file) {
  if (!file.type.startsWith('image/')) throw new Error('Choose an image file (PNG, JPEG or WebP).');
  if (file.size > MAX_FILE_BYTES) throw new Error('That image is over 10 MB. Choose a smaller one.');
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error("That file couldn't be read as an image.");
  }
  const side = Math.min(bitmap.width, bitmap.height);
  const canvas = document.createElement('canvas');
  canvas.width = AVATAR_PX;
  canvas.height = AVATAR_PX;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, AVATAR_PX, AVATAR_PX);
  ctx.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, AVATAR_PX, AVATAR_PX);
  bitmap.close();
  return canvas.toDataURL('image/jpeg', 0.86);
}

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

  // A fresh /auth/me (a save, or a re-check) resets what hasn't been
  // touched, so the form never shows a stale saved value.
  useEffect(() => { setName((current) => (current === savedName ? current : (saving ? current : savedName))); }, [savedName]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!avatarTouched) setAvatar(savedAvatar); }, [savedAvatar, avatarTouched]);

  const cleanName = name.replace(/\s+/g, ' ').trim();
  const nameChanged = cleanName !== savedName;
  const avatarChanged = avatarTouched && avatar !== savedAvatar;
  const canSave = !saving && (nameChanged || avatarChanged) && cleanName.length > 0 && cleanName.length <= NAME_MAX;

  const choosePicture = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError('');
    try {
      setAvatar(await fileToAvatar(file));
      setAvatarTouched(true);
    } catch (err) {
      setError(err.message);
    }
  };

  const removePicture = () => {
    setAvatar(null);
    setAvatarTouched(true);
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

  return (
    <div className="profile-page">
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-header-title">My <span className="page-title-accent">profile</span></h1>
          <p className="page-header-subtitle">How you appear in the dashboard and in the audit log.</p>
        </div>
      </div>

      <form className="ui-card profile-card" onSubmit={handleSubmit}>
        <div className="profile-picture-row">
          <div className="profile-avatar" aria-hidden="true">
            {avatar ? <img src={avatar} alt="" className="profile-avatar-img" /> : initialsOf(cleanName || savedName)}
          </div>
          <div className="profile-picture-actions">
            <span className="form-label">PROFILE PICTURE</span>
            {picturesAvailable ? (
              <>
                <div className="profile-picture-buttons">
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => fileRef.current?.click()}>
                    <Camera size={14} aria-hidden="true" />
                    {avatar ? 'Change picture' : 'Choose a picture'}
                  </button>
                  {avatar && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={removePicture}>
                      <Trash2 size={14} aria-hidden="true" />
                      Remove
                    </button>
                  )}
                </div>
                <span className="form-hint">PNG, JPEG or WebP. It is cropped to a square and shrunk to {AVATAR_PX} px.</span>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="visually-hidden"
                  onChange={choosePicture}
                  aria-label="Choose a profile picture"
                />
              </>
            ) : (
              <span className="form-hint">Profile pictures aren&apos;t available on this server yet. Your initials are shown.</span>
            )}
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="profile-name">DISPLAY NAME</label>
          <input
            id="profile-name"
            className="profile-input"
            type="text"
            value={name}
            maxLength={NAME_MAX}
            autoComplete="name"
            onChange={(e) => { setName(e.target.value); setError(''); }}
            required
          />
          <span className="form-hint">Shown in the sidebar and on your entries in the audit log.</span>
        </div>

        <div className="profile-readonly">
          <div className="form-group">
            <span className="form-label">EMAIL</span>
            <span className="profile-readonly-value">{email}</span>
          </div>
          <div className="form-group">
            <span className="form-label">ROLE</span>
            <span className="profile-readonly-value">{role ? role.toUpperCase() : '—'}</span>
          </div>
          <span className="form-hint">An admin changes these in User Management.</span>
        </div>

        {error && <div className="form-api-error" role="alert">{error}</div>}

        <div className="profile-actions">
          <button type="submit" className="btn btn-primary" disabled={!canSave}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </form>
    </div>
  );
}
