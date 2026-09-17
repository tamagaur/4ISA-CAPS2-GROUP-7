import React, { useState, useEffect } from 'react';
import { getAuditLog } from '../api/auditLog';
import { formatDateTime } from '../utils/formatDate';
import Pagination from './Pagination';
import './AuditLog.css';

const ExpandableText = ({ text, maxLength = 60 }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  if (!text) return null;

  if (text.length <= maxLength) {
    return <span>{text}</span>;
  }

  return (
    <div className="audit-desc-expandable">
      <span>{isExpanded ? text : `${text.substring(0, maxLength)}...`}</span>
      <button
        className="audit-desc-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        {isExpanded ? 'See less' : 'See more'}
      </button>
    </div>
  );
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


const AuditLog = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [actionFilter, setActionFilter] = useState('');
  const [userFilter, setUserFilter] = useState('');
  // Same options/default as SKU Management and ABC Classification's
  // tables (was a fixed 10-per-page with no way to change it).
  const PAGE_SIZE_OPTIONS = [25, 50, 100];
  const [logsPerPage, setLogsPerPage] = useState(25);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAuditLog({ limit: 500 })
      .then((res) => {
        if (cancelled) return;
        const formatted = (res.items || []).map((log) => ({
          id: log.audit_log_key,
          user: log.user_name || log.user_email,
          email: log.user_email,
          action: log.action,
          details: log.details,
          formattedTimestamp: formatDateTime(log.created_at),
        }));
        setLogs(formatted);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load audit log');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Compute unique values for filters
  const uniqueActions = [...new Set(logs.map(log => log.action))];
  const uniqueUsers = [...new Set(logs.map(log => log.user))];

  // Filter logs
  const filteredLogs = logs.filter(log => {
    if (actionFilter && log.action !== actionFilter) return false;
    if (userFilter && log.user !== userFilter) return false;
    return true;
  });

  // Pagination logic
  const totalPages = Math.max(1, Math.ceil(filteredLogs.length / logsPerPage));
  const indexOfLastLog = currentPage * logsPerPage;
  const indexOfFirstLog = indexOfLastLog - logsPerPage;
  const currentLogs = filteredLogs.slice(indexOfFirstLog, indexOfLastLog);

  // Ensure current page is valid after filtering
  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [totalPages, currentPage]);

  // Any filter/page-size change puts the user back on page 1 — staying on
  // page 7 of a result set that just shrank to 2 pages shows nothing.
  // Mirrors SKU Management/ABC Classification's own reset effect.
  useEffect(() => {
    setCurrentPage(1);
  }, [actionFilter, userFilter, logsPerPage]);

  const handleClearFilters = () => {
    setActionFilter('');
    setUserFilter('');
  };

  return (
    <div className="audit-page">
      <div className="audit-content">
        <div className="audit-page-header">
          <div className="audit-header-left">
            <h2 className="audit-page-title">Audit <span className="page-title-accent">log</span></h2>
            <p className="audit-page-subtitle">
              Who did what, and when: sign-ins, SKU changes, and reorder decisions recorded in this system.
            </p>
          </div>
        </div>

        {/* Filters Section */}
        <div className="audit-filters-container">
          <div className="audit-filter-group">
            <label>Action</label>
            <select
              className="audit-dropdown-select"
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
            >
              <option value="">All Actions</option>
              {uniqueActions.map(action => (
                <option key={action} value={action}>{action}</option>
              ))}
            </select>
          </div>

          <div className="audit-filter-group">
            <label>Select User</label>
            <select
              className="audit-dropdown-select"
              value={userFilter}
              onChange={(e) => setUserFilter(e.target.value)}
            >
              <option value="">All Users</option>
              {uniqueUsers.map(user => (
                <option key={user} value={user}>{user}</option>
              ))}
            </select>
          </div>

          <div className="audit-filter-actions">
            <button className="audit-btn-outline" onClick={handleClearFilters}>Clear Filters</button>
          </div>
        </div>

        {loading && <p className="audit-page-subtitle">Loading audit log…</p>}
        {error && <p className="audit-page-subtitle">Error: {error}</p>}

        {/* Table Section */}
        {!loading && !error && (
          <div className="audit-table-wrapper">
            <table className="audit-table">
              <thead>
                <tr>
                  <th>User Name</th>
                  <th>User email</th>
                  <th>Action</th>
                  <th>Timestamp</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {currentLogs.length > 0 ? (
                  currentLogs.map((log) => (
                    <tr key={log.id}>
                      <td className="audit-user-cell">
                        <div className="audit-user-info">
                          <div
                            className="audit-avatar"
                            style={{ backgroundColor: getAvatarColor(log.user) }}
                          >
                            {getInitials(log.user)}
                          </div>
                          <div className="audit-user-details">
                            <span className="audit-user-name">{log.user}</span>
                          </div>
                        </div>
                      </td>
                      <td className="audit-email-cell">
                        <a href={`mailto:${log.email}`}>{log.email}</a>
                      </td>
                      <td className="audit-action-cell">{log.action}</td>
                      <td className="audit-timestamp-cell">{log.formattedTimestamp}</td>
                      <td className="audit-desc-cell">
                        <ExpandableText text={log.details} />
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="5" className="audit-no-results">No audit logs found.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          totalItems={filteredLogs.length}
          pageSize={logsPerPage}
          onPageChange={setCurrentPage}
          onPageSizeChange={setLogsPerPage}
          pageSizeOptions={PAGE_SIZE_OPTIONS}
          idPrefix="audit"
        />
      </div>
    </div>
  );
};

export default AuditLog;
