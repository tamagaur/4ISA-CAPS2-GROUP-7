import React, { useState, useEffect } from 'react';
import { getAuditLog } from '../api/auditLog';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { formatDateTime } from '../utils/formatDate';
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
  const logsPerPage = 10;

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

  const handleNextPage = () => {
    setCurrentPage(prev => Math.min(prev + 1, totalPages));
  };

  const handlePrevPage = () => {
    setCurrentPage(prev => Math.max(prev - 1, 1));
  };

  const handleClearFilters = () => {
    setActionFilter('');
    setUserFilter('');
    setCurrentPage(1);
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

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="audit-pagination">
            <button
              className="audit-page-nav"
              onClick={handlePrevPage}
              disabled={currentPage === 1}
              style={{ opacity: currentPage === 1 ? 0.5 : 1, cursor: currentPage === 1 ? 'default' : 'pointer' }}
            >
              <ChevronLeft size={16} style={{ marginRight: '4px' }} />
              Previous
            </button>

            <div className="audit-page-numbers">
              {Array.from({ length: totalPages }, (_, i) => i + 1).map(num => (
                <button
                  key={num}
                  className={`audit-page-num ${currentPage === num ? 'active' : ''}`}
                  onClick={() => setCurrentPage(num)}
                >
                  {num}
                </button>
              ))}
            </div>

            <button
              className="audit-page-nav"
              onClick={handleNextPage}
              disabled={currentPage === totalPages}
              style={{ opacity: currentPage === totalPages ? 0.5 : 1, cursor: currentPage === totalPages ? 'default' : 'pointer' }}
            >
              Next
              <ChevronRight size={16} style={{ marginLeft: '4px' }} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default AuditLog;
