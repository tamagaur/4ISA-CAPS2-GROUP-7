import React, { useState, useEffect } from 'react';
import SectionLede from './ui/SectionLede';
import { getAuditLog, getAuditUserSummary } from '../api/auditLog';
import { formatDate, formatDateTime } from '../utils/formatDate';
import { LoadingStatus, SkeletonTable } from './Skeleton';
import LoadError, { describeLoadError } from './ui/LoadError';
import SlowLoadNotice from './ui/SlowLoadNotice';
import PageHeader from './ui/PageHeader';
import './AuditLog.css';

// Events out of the ordinary get the one badge on the page; the rest are
// plain text, so a badge still means something.
const EXCEPTIONAL_ACTIONS = new Set(['Sign-in Failed', 'Sign-in Locked', 'Delete User']);

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

// One neutral tile for every avatar (UI pass): a column of six strong
// colours competed with the one badge on the page that means something.
const getAvatarColor = () => 'var(--badge-neutral-bg)';

// A span of days as the page states periods: "Aug 23, 2026 – Oct 2, 2026", or
// one day when both ends fall on it. Every count on this page says the span
// it covers (Technical Adviser, 2026-10-03): a bare "90 sign-ins" read as
// "ever", while the record only starts at the first tracked sign-in.
const daySpan = (from, to) => {
  if (!from || !to) return null;
  const a = formatDate(from);
  const b = formatDate(to);
  return a === b ? a : `${a} \u2013 ${b}`;
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
// `meta` keeps the rest of the response (GET /audit-log/users' sign-in span).
const useSection = (load) => {
  const [state, setState] = useState({ loading: true, error: null, items: [], meta: {} });
  // Try again re-runs this section's request only.
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    load()
      .then((res) => {
        if (!cancelled) setState({ loading: false, error: null, items: res.items || [], meta: res || {} });
      })
      .catch((err) => {
        if (!cancelled) setState({ loading: false, error: describeLoadError(err), items: [], meta: {} });
      });
    return () => { cancelled = true; };
  }, [load, attempt]);
  return { ...state, retry: () => setAttempt((n) => n + 1) };
};

const loadUsers = () => getAuditUserSummary();
const loadChanges = () => getAuditLog({ excludeActions: SIGN_IN_ACTIONS, limit: RECENT_CHANGES_LIMIT });

// While loading, the section's table as a skeleton in the same wrapper, sized
// to that table's own column count.
const SectionStatus = ({ loading, error, label, columns, rows = 4, onRetry }) => {
  if (loading) {
    return (
      <>
        <LoadingStatus>Loading {label}…</LoadingStatus>
        <SlowLoadNotice />
        <div className="audit-table-wrapper">
          <SkeletonTable rows={rows} columns={columns} />
        </div>
      </>
    );
  }
  if (error) return <LoadError what={label} message={error} onRetry={onRetry} />;
  return null;
};

// Admin-only page (AdminRoute + require_admin on the API): sign-ins
// summarised per user, then the latest changes made in the app.
const AuditLog = () => {
  const users = useSection(loadUsers);
  const changes = useSection(loadChanges);

  const totalLogins = users.items.reduce((sum, u) => sum + u.login_count, 0);
  const longestSeconds = users.items[0]?.longest_session_seconds ?? null;
  // The span the sign-in counts cover: the first recorded sign-in (session
  // tracking plus the sign-ins backfilled from the audit log) to the latest.
  const signInSpan = daySpan(users.meta.first_login_at, users.meta.last_login_at);
  // The span the listed changes cover, oldest to newest of those shown.
  const changeTimes = changes.items.map((c) => c.created_at).filter(Boolean).sort();
  const changesSpan = daySpan(changeTimes[0], changeTimes[changeTimes.length - 1]);

  return (
    <div className="audit-page">
      <div className="audit-content">
        <PageHeader title="Audit" accent="log" subtitle="Who signs in, and what they change. Visible to people with Audit Log access." />

        <section className="audit-section" aria-labelledby="audit-users-heading">
          <div className="audit-section-header">
            <h3 id="audit-users-heading" className="audit-section-title">Sign-ins by user</h3>
            {!users.loading && !users.error && (
              <span className="audit-section-count">
                {users.items.length.toLocaleString()} user{users.items.length === 1 ? '' : 's'} ·{' '}
                {totalLogins.toLocaleString()} sign-in{totalLogins === 1 ? '' : 's'}
                {signInSpan ? `, ${signInSpan}` : ''}
              </span>
            )}
          </div>
          <SectionLede className="is-standalone">Who uses the system</SectionLede>
          <p className="audit-section-note">
            Sign-ins are counted from the first recorded sign-in
            {users.meta.first_login_at ? ` (${formatDate(users.meta.first_login_at)})` : ''}; nothing earlier is
            on record. A session lasts from sign-in until the user&apos;s last activity or sign-out, and ends after
            4 hours without activity. Older sign-ins have no measured length.
          </p>
          <SectionStatus loading={users.loading} error={users.error} label="sign-ins by user" columns={5} onRetry={users.retry} />
          {!users.loading && !users.error && (
            <div className="audit-table-wrapper">
              <table className="audit-table audit-table-stack">
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Role</th>
                    <th className="audit-num-cell" title="Since the user's first recorded sign-in">Sign-ins (count)</th>
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
                          <td
                            data-label="Sign-ins"
                            className="audit-num-cell"
                            title={row.first_login_at ? `Since ${formatDateTime(row.first_login_at)}` : undefined}
                          >
                            {row.login_count.toLocaleString()}
                          </td>
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
            {/* Its scope: the newest RECENT_CHANGES_LIMIT changes, and the
                days those span — or every change, when fewer are recorded. */}
            <span className="audit-section-count">
              {!changes.loading && !changes.error && changes.items.length < RECENT_CHANGES_LIMIT
                ? `All ${changes.items.length.toLocaleString()} recorded`
                : `Latest ${RECENT_CHANGES_LIMIT}`}
              {!changes.loading && !changes.error && changesSpan ? `, ${changesSpan}` : ''}
            </span>
          </div>
          <SectionLede className="is-standalone">What changed, and who changed it</SectionLede>
          <p className="audit-section-note">
            SKU edits, reorder decisions, user account changes and password or sign-in events, newest first.
          </p>
          <SectionStatus loading={changes.loading} error={changes.error} label="recent changes" columns={4} rows={6} onRetry={changes.retry} />
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
                        <td className="audit-stack-head audit-action-cell">
                          {EXCEPTIONAL_ACTIONS.has(log.action)
                            ? <span className="badge badge-warning">{ACTION_LABELS[log.action] || log.action}</span>
                            : (ACTION_LABELS[log.action] || log.action)}
                        </td>
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
