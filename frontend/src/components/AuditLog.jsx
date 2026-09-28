import React, { useState, useEffect } from 'react';
import { getAuditLog, getAuditUserSummary } from '../api/auditLog';
import { formatDateTime } from '../utils/formatDate';
import { LoadingStatus, SkeletonTable } from './Skeleton';
import './AuditLog.css';

const RECENT_CHANGES_LIMIT = 10;
// Sign-ins are summarised per user above, so they are left out of the
// changes list — otherwise it would be almost nothing but logins.
const SIGN_IN_ACTIONS = ['Login', 'Logout'];

// Shorter labels for the long action names the app records.
const ACTION_LABELS = {
  'Reorder Recommendation Accepted': 'Reorder accepted',
  'Reorder Recommendation Dismissed': 'Reorder dismissed',
  'Password Reset Requested': 'Reset requested',
};

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

// 5400 -> "1h 30m", 600 -> "10m", 42 -> "42s".
const formatDuration = (seconds) => {
  if (seconds == null) return '—';
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
};

const longestSessionTitle = (row) => {
  if (row.longest_session_seconds == null) {
    return row.login_count > 0
      ? 'No measured session yet — these sign-ins predate session tracking'
      : 'Never signed in';
  }
  return `Started ${formatDateTime(row.longest_session_started_at)} · ` +
    `${row.timed_session_count} of ${row.login_count} sign-ins have a measured length`;
};

const UserBadge = ({ name, email }) => {
  // An entry from a signed-out page (a "Forgot password?" request, a sign-in
  // lockout) may carry no user at all.
  if (!name) return '—';
  return (
    <div className="audit-user-info">
      <div className="audit-avatar" style={{ backgroundColor: getAvatarColor(name) }} aria-hidden="true">
        {getInitials(name)}
      </div>
      <div className="audit-user-details">
        <span className="audit-user-name">{name}</span>
        {email && email !== name && <span className="audit-user-handle">{email}</span>}
      </div>
    </div>
  );
};

// Loads one section's data; each section fails or loads on its own, so a
// problem with one never blanks the other.
const useSection = (load) => {
  const [state, setState] = useState({ loading: true, error: null, items: [] });
  useEffect(() => {
    let cancelled = false;
    load()
      .then((res) => { if (!cancelled) setState({ loading: false, error: null, items: res.items || [] }); })
      .catch((err) => {
        if (!cancelled) setState({ loading: false, error: err.message || 'Failed to load', items: [] });
      });
    return () => { cancelled = true; };
  }, [load]);
  return state;
};

const loadUsers = () => getAuditUserSummary();
const loadChanges = () => getAuditLog({ excludeActions: SIGN_IN_ACTIONS, limit: RECENT_CHANGES_LIMIT });

// While loading, the section's table as a skeleton in the same wrapper, sized
// to that table's own column count.
const SectionStatus = ({ loading, error, label, columns, rows = 4 }) => {
  if (loading) {
    return (
      <>
        <LoadingStatus>Loading {label}…</LoadingStatus>
        <div className="audit-table-wrapper">
          <SkeletonTable rows={rows} columns={columns} />
        </div>
      </>
    );
  }
  if (error) return <p className="audit-section-status audit-section-error">Couldn&apos;t load this section: {error}</p>;
  return null;
};

// Admin-only page (AdminRoute + require_admin on the API): sign-ins
// summarised per user, then the latest changes made in the app.
const AuditLog = () => {
  const users = useSection(loadUsers);
  const changes = useSection(loadChanges);

  const totalLogins = users.items.reduce((sum, u) => sum + u.login_count, 0);
  const longestSeconds = users.items[0]?.longest_session_seconds ?? null;

  return (
    <div className="audit-page">
      <div className="audit-content">
        <div className="audit-page-header">
          <div className="audit-header-left">
            <h2 className="audit-page-title">Audit <span className="page-title-accent">log</span></h2>
            <p className="audit-page-subtitle">Who signs in, and what they change. Visible to admins only.</p>
          </div>
        </div>

        <section className="audit-section" aria-labelledby="audit-users-heading">
          <div className="audit-section-header">
            <h3 id="audit-users-heading" className="audit-section-title">Sign-ins by user</h3>
            {!users.loading && !users.error && (
              <span className="audit-section-count">
                {users.items.length.toLocaleString()} user{users.items.length === 1 ? '' : 's'} ·{' '}
                {totalLogins.toLocaleString()} sign-in{totalLogins === 1 ? '' : 's'}
              </span>
            )}
          </div>
          <p className="audit-section-note">
            A session lasts from sign-in until the user&apos;s last activity or sign-out, and ends after
            30 minutes without activity. Older sign-ins have no measured length.
          </p>
          <SectionStatus loading={users.loading} error={users.error} label="sign-ins by user" columns={5} />
          {!users.loading && !users.error && (
            <div className="audit-table-wrapper">
              <table className="audit-table audit-table-stack">
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Role</th>
                    <th className="audit-num-cell">Sign-ins</th>
                    <th className="audit-num-cell">Longest session</th>
                    <th>Last sign-in</th>
                  </tr>
                </thead>
                <tbody>
                  {users.items.length > 0 ? (
                    users.items.map((row) => {
                      const name = row.user_name || row.user_email;
                      const isLongest =
                        longestSeconds != null && row.longest_session_seconds === longestSeconds;
                      return (
                        <tr key={row.user_email}>
                          <td className="audit-stack-head"><UserBadge name={name} email={row.user_email} /></td>
                          <td data-label="Role" className="audit-role-cell">{row.role || '—'}</td>
                          <td data-label="Sign-ins" className="audit-num-cell">{row.login_count.toLocaleString()}</td>
                          <td data-label="Longest session" className="audit-num-cell" title={longestSessionTitle(row)}>
                            <span className="audit-duration">
                              {isLongest && <span className="pill pill-planned audit-longest-badge">Longest</span>}
                              {formatDuration(row.longest_session_seconds)}
                            </span>
                          </td>
                          <td data-label="Last sign-in" className="audit-timestamp-cell">
                            {row.last_login_at ? formatDateTime(row.last_login_at) : 'Never'}
                          </td>
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan="5" className="audit-no-results">No users found.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="audit-section" aria-labelledby="audit-changes-heading">
          <div className="audit-section-header">
            <h3 id="audit-changes-heading" className="audit-section-title">Recent changes</h3>
            <span className="audit-section-count">Latest {RECENT_CHANGES_LIMIT}</span>
          </div>
          <p className="audit-section-note">
            SKU edits, reorder decisions, user account changes and password or sign-in events, newest first.
          </p>
          <SectionStatus loading={changes.loading} error={changes.error} label="recent changes" columns={4} rows={6} />
          {!changes.loading && !changes.error && (
            <div className="audit-table-wrapper">
              <table className="audit-table audit-table-stack">
                <thead>
                  <tr>
                    <th>Change</th>
                    <th>By</th>
                    <th>When</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.items.length > 0 ? (
                    changes.items.map((log) => (
                      <tr key={log.audit_log_key}>
                        <td className="audit-stack-head audit-action-cell">{ACTION_LABELS[log.action] || log.action}</td>
                        <td data-label="By"><UserBadge name={log.user_name || log.user_email} /></td>
                        <td data-label="When" className="audit-timestamp-cell">{formatDateTime(log.created_at)}</td>
                        <td data-label="Details" className="audit-desc-cell">{log.details || '—'}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan="4" className="audit-no-results">No changes recorded yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export default AuditLog;
