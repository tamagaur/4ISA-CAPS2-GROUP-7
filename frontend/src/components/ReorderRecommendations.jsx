import React, { useState, useMemo, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Loader2, ClipboardList, ListChecks, CheckCircle2 } from 'lucide-react';
import ReorderModal from './ReorderModal';
import OverrideReasonModal from './OverrideReasonModal';
import Modal from './Modal';
import { useToast } from './ToastProvider';
import { getCurrentUser } from '../auth';
import { logAction } from '../utils/auditLogger';
import { getRecommendations, decideRecommendation } from '../api/recommendations';
import DateFilter from './DateFilter';
import './ReorderRecommendations.css';

// Helper to extract product name and weight (supports decimals like 1.5L, 2.5kg)
const parseProductAndWeight = (product) => {
  if (!product) return { name: '', weight: '' };
  const weightRegex = /\b(\d+(?:\.\d+)?\s*(?:g|ml|l|kg|L|KG|ML|G))\b/;
  const match = product.match(weightRegex);
  if (match) {
    const weight = `(${match[1]})`;
    let name = product.replace(weightRegex, '').replace(/\s+/g, ' ').trim();
    name = name.replace(/\(\s*\)/g, '').trim();
    return { name, weight };
  }
  return { name: product, weight: '' };
};

// Helper to format SKU to 5 digits (SKU-#####)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  return sku;
};

const formatTimestamp = (date) =>
  date.toLocaleString('en-PH', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

// Same shared date-range picker convention every other page's fetch effect
// uses (Dashboard.jsx, ABCClassification.jsx, BadOrders.jsx) — DashboardLayout
// holds the one applied {startMonth, startYear, endMonth, endYear}, passed
// down via Outlet context, so it persists across page navigation and is
// never reset except by the "Today" button.
const MONTH_TO_NUM = {
  Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
  Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12',
};

const ReorderRecommendations = () => {
  const toast = useToast();
  const { startMonth, startYear, endMonth, endYear } = useOutletContext() || {};

  const [rawItems, setRawItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedItem, setSelectedItem] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('RECOMMENDATIONS');

  // Pending override awaiting a reason (Dismiss only — Accept logs immediately).
  const [pendingOverride, setPendingOverride] = useState(null); // { item, action }
  const [pendingAccept, setPendingAccept] = useState(null); // the item awaiting Accept confirmation
  const [decisionLog, setDecisionLog] = useState([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const from = startYear && startMonth ? `${startYear}-${MONTH_TO_NUM[startMonth]}-01` : undefined;
    const to = endYear && endMonth ? `${endYear}-${MONTH_TO_NUM[endMonth]}-28` : undefined;
    getRecommendations({ status: 'pending', from, to })
      .then((res) => {
        if (cancelled) return;
        setRawItems(res.items || []);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load reorder recommendations');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [startMonth, startYear, endMonth, endYear]);

  // Map API shape -> the row shape the rest of this page renders. actionStatus/
  // loadingAction are local-only UI state layered on top of each real row.
  const data = useMemo(
    () =>
      rawItems.map((item) => ({
        id: item.recommendation_key,
        sku: item.sku_id,
        brand: 'Unilever',
        product: item.product_name || 'Unknown Product',
        rop: item.rop_i,
        stock: item.current_stock,
        orderQty: item.q_i,
        safetyStock: item.ss_i,
        urgency: item.urgency,
        planningCycleDate: item.planning_cycle_date,
        actionStatus: item.status === 'pending' ? null : item.status.toUpperCase(),
        loadingAction: null,
      })),
    [rawItems]
  );
  const [localData, setLocalData] = useState([]);
  useEffect(() => setLocalData(data), [data]);

  const criticalCount = localData.filter(item => item.urgency === 'CRITICAL').length;
  const urgentCount = localData.filter(item => item.urgency === 'URGENT').length;
  const totalOrderQty = localData.reduce((sum, item) => sum + (item.orderQty || 0), 0);
  const totalStock = localData.reduce((sum, item) => sum + (item.stock || 0), 0);

  const handleOpenDetails = (item) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  const logDecision = (item, action, reason) => {
    const user = getCurrentUser();
    setDecisionLog(prev => [
      {
        id: `${item.id}-${Date.now()}`,
        sku: item.sku,
        product: item.product,
        action,
        reason,
        decidedBy: user?.email || 'unknown user',
        timestamp: formatTimestamp(new Date()),
      },
      ...prev,
    ]);

    // Also push to the global audit log
    logAction(`Reorder Recommendation ${action === 'ACCEPTED' ? 'Accepted' : 'Dismissed'}`, `SKU ${item.sku}: ${reason}`);
  };

  const applyAction = async (id, actionType) => {
    setLocalData(prev => prev.map(item =>
      item.id === id ? { ...item, loadingAction: actionType } : item
    ));

    try {
      await decideRecommendation(id, actionType === 'ACCEPTED' ? 'accepted' : 'dismissed');
      setLocalData(prev => prev.map(item =>
        item.id === id ? { ...item, loadingAction: null, actionStatus: actionType } : item
      ));
      // The row itself only changes to a small status pill, which is easy to
      // miss in a long table — the toast is the actual confirmation.
      toast.success(
        actionType === 'ACCEPTED' ? 'Reorder accepted' : 'Recommendation dismissed'
      );
    } catch (err) {
      setLocalData(prev => prev.map(item =>
        item.id === id ? { ...item, loadingAction: null } : item
      ));
      setError(err.message || 'Failed to update recommendation');
      toast.error(err.message || 'Failed to update recommendation');
    }
  };

  const handleAction = (item, actionType) => {
    if (actionType === 'ACCEPTED') {
      // Accept commits a real purchase quantity, so it gets a confirmation
      // step too. It used to fire instantly on click while Dismiss — the
      // adjacent button in the same row — demanded a typed justification;
      // that asymmetry made an accidental Accept the easiest mistake on the
      // page. This confirm is deliberately lighter than Dismiss's (no typed
      // reason): accepting the LP's own recommendation is the expected
      // path, it just shouldn't be a single unguarded click.
      setPendingAccept(item);
      return;
    }
    // Dismiss deviates from the recommendation — require a reason first
    setPendingOverride({ item, action: actionType });
  };

  const handleConfirmAccept = () => {
    const item = pendingAccept;
    if (!item) return;
    applyAction(item.id, 'ACCEPTED');
    logDecision(item, 'ACCEPTED', 'Accepted the LP-recommended order quantity as-is.');
    setPendingAccept(null);
  };

  const handleConfirmOverride = (reason) => {
    const { item, action } = pendingOverride;
    applyAction(item.id, action);
    logDecision(item, action, reason);
    setPendingOverride(null);
  };

  const getUrgencyBadge = (urgency) => {
    switch (urgency) {
      case 'CRITICAL': return 'urgency-badge badge-critical';
      case 'URGENT': return 'urgency-badge badge-urgent';
      case 'PLANNED': return 'urgency-badge badge-planned';
      default: return 'urgency-badge';
    }
  };

  // Left-edge severity stripe on the row itself, not just the badge cell —
  // when most rows share one urgency (real data here runs heavily
  // CRITICAL), a stripe down the whole row is scannable at a glance
  // without hunting for the badge column.
  const getUrgencyRowClass = (urgency) => {
    switch (urgency) {
      case 'CRITICAL': return 'reorder-row-critical';
      case 'URGENT': return 'reorder-row-urgent';
      case 'PLANNED': return 'reorder-row-planned';
      default: return '';
    }
  };

  const getLogActionBadge = (action) => {
    switch (action) {
      case 'ACCEPTED': return 'status-badge status-accepted';
      case 'DISMISSED': return 'status-badge status-dismissed';
      default: return 'status-badge';
    }
  };

  const renderActionColumn = (item) => {
    if (item.loadingAction) {
      return (
        <div className="action-status-container">
          <Loader2 className="spinner-icon" size={16} />
          <span className="loading-text">Processing...</span>
        </div>
      );
    }

    if (item.actionStatus) {
      return (
        <div className="action-status-container">
          <span className={`status-badge status-${item.actionStatus.toLowerCase()}`}>
            {item.actionStatus}
          </span>
        </div>
      );
    }

    return (
      <div className="action-buttons">
        <button className="action-btn accept-btn" onClick={() => handleAction(item, 'ACCEPTED')}>Accept</button>
        <button className="action-btn dismiss-btn" onClick={() => handleAction(item, 'DISMISSED')}>Dismiss</button>
      </div>
    );
  };

  const renderRecommendationsTab = () => (
    <>
      {/* Summary Cards */}
      <div className="reorder-summary-grid">
        <div className="reorder-summary-card card-red">
          <div className="card-content">
            <span className="reorder-card-label">CRITICAL SKUS</span>
            <span className="reorder-card-value">{criticalCount}</span>
          </div>
        </div>
        <div className="reorder-summary-card card-yellow">
          <div className="card-content">
            <span className="reorder-card-label">URGENT SKUS</span>
            <span className="reorder-card-value">{urgentCount}</span>
          </div>
        </div>
        <div className="reorder-summary-card card-green">
          <div className="card-content">
            <span className="reorder-card-label">CURRENT STOCK</span>
            <span className="reorder-card-value">{totalStock.toLocaleString()}</span>
            <span className="reorder-card-desc">on hand across list</span>
          </div>
        </div>
        <div className="reorder-summary-card card-blue">
          <div className="card-content">
            <span className="reorder-card-label">TOTAL ORDER QTY</span>
            <span className="reorder-card-value">{totalOrderQty.toLocaleString()}</span>
            <span className="reorder-card-desc">LP - optimized units</span>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="reorder-table-wrapper">
        <table className="reorder-table">
          <thead>
            <tr>
              <th>SKU</th>
              <th>BRAND</th>
              <th>PRODUCT</th>
              <th>ROP</th>
              <th>CURRENT STOCK</th>
              <th>LP QTY</th>
              <th>URGENCY</th>
              <th>ACTION</th>
            </tr>
          </thead>
          <tbody>
            {localData.map((item) => (
              <tr key={item.id} className={getUrgencyRowClass(item.urgency)}>
                <td
                  className="reorder-sku-cell"
                  role="button"
                  tabIndex={0}
                  onClick={() => handleOpenDetails(item)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleOpenDetails(item);
                    }
                  }}
                >
                  {formatSKU(item.sku)}
                </td>
                <td>{item.brand}</td>
                <td className="reorder-product-cell">
                  {(() => {
                    const { name, weight } = parseProductAndWeight(item.product);
                    return (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <span className="reorder-product-name">{name}</span>
                        {weight && (
                          <span className="reorder-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                            {weight}
                          </span>
                        )}
                      </div>
                    );
                  })()}
                </td>
                <td>{item.rop}</td>
                <td
                  className="reorder-stock-cell"
                  style={{
                    color: item.stock < item.rop * 0.5
                      ? 'var(--color-severity-critical)'
                      : item.stock < item.rop
                        ? 'var(--color-severity-urgent)'
                        : 'var(--color-text-body)',
                  }}
                >
                  {item.stock}
                </td>
                <td className="reorder-qty-cell">
                  <span className="reorder-qty-main">{item.orderQty}</span>
                </td>
                <td>
                  <span className={getUrgencyBadge(item.urgency)}>
                    {item.urgency}
                  </span>
                </td>
                <td>
                  {renderActionColumn(item)}
                </td>
              </tr>
            ))}
            {localData.length === 0 && (
              <tr>
                <td colSpan="9" className="reorder-no-results">No pending recommendations for this selection.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );

  const renderDecisionLogTab = () => (
    <div className="reorder-table-wrapper">
      <table className="reorder-table reorder-log-table">
        <thead>
          <tr>
            <th>WHEN</th>
            <th>SKU</th>
            <th>PRODUCT</th>
            <th>ACTION</th>
            <th>REASON</th>
            <th>DECIDED BY</th>
          </tr>
        </thead>
        <tbody>
          {decisionLog.length === 0 ? (
            <tr>
              <td colSpan="6" className="reorder-log-empty">
                No decisions recorded yet this session. Accept or dismiss a recommendation to see it logged here.
              </td>
            </tr>
          ) : (
            decisionLog.map((entry) => (
              <tr key={entry.id}>
                <td className="reorder-log-when">{entry.timestamp}</td>
                <td className="reorder-sku-cell" style={{ cursor: 'default' }}>{formatSKU(entry.sku)}</td>
                <td className="reorder-product-cell">{entry.product}</td>
                <td>
                  <span className={getLogActionBadge(entry.action)}>
                    {entry.action}
                  </span>
                </td>
                <td className="reorder-log-reason">{entry.reason}</td>
                <td className="reorder-log-user">{entry.decidedBy}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="reorder-page">
      <div className="reorder-content">
        {/* Page Header */}
        <div className="reorder-page-header">
          <div className="reorder-page-title-row">
            <h2 className="reorder-page-title">
              Reorder Recommendations
            </h2>
            <DateFilter />
          </div>
          <p className="reorder-page-subtitle">
            LP-optimized purchase quantities for Category A SKUs. Minimizes total inventory cost while preventing stockouts.
          </p>
        </div>

        {/* Tab Navigation */}
        <div className="reorder-tabs-row">
          <button
            className={`reorder-tab-btn ${activeTab === 'RECOMMENDATIONS' ? 'active' : ''}`}
            onClick={() => setActiveTab('RECOMMENDATIONS')}
          >
            <ClipboardList size={14} />
            RECOMMENDATIONS
          </button>
          <button
            className={`reorder-tab-btn ${activeTab === 'DECISION_LOG' ? 'active' : ''}`}
            onClick={() => setActiveTab('DECISION_LOG')}
          >
            <ListChecks size={14} />
            DECISION LOG {decisionLog.length > 0 && <span className="reorder-tab-count">{decisionLog.length}</span>}
          </button>
        </div>

        {loading && <p className="reorder-page-subtitle">Loading recommendations…</p>}
        {error && <p className="reorder-page-subtitle">Error: {error}</p>}
        {!loading && !error && (activeTab === 'RECOMMENDATIONS' ? renderRecommendationsTab() : renderDecisionLogTab())}
      </div>

      <ReorderModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        data={selectedItem}
      />

      <OverrideReasonModal
        isOpen={Boolean(pendingOverride)}
        item={pendingOverride?.item}
        onCancel={() => setPendingOverride(null)}
        onConfirm={handleConfirmOverride}
      />

      {pendingAccept && (
        <Modal
          isOpen={Boolean(pendingAccept)}
          onClose={() => setPendingAccept(null)}
          label="Confirm reorder acceptance"
          overlayClassName="reorder-accept-overlay"
          containerClassName="reorder-accept-card"
        >
          <div className="reorder-accept-icon">
            <CheckCircle2 size={20} />
          </div>
          <h3 className="reorder-accept-title">Accept this reorder?</h3>
          <p className="reorder-accept-body">
            Order <strong>{pendingAccept.orderQty}</strong> units of{' '}
            <strong>{formatSKU(pendingAccept.sku)}</strong>
            {pendingAccept.product ? ` — ${pendingAccept.product}` : ''}, as recommended by the LP optimizer.
          </p>
          <div className="reorder-accept-actions">
            <button className="reorder-accept-cancel" onClick={() => setPendingAccept(null)}>
              Cancel
            </button>
            <button className="reorder-accept-confirm" onClick={handleConfirmAccept}>
              Accept Reorder
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
};

export default ReorderRecommendations;
