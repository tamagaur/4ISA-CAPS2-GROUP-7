import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2, ClipboardList, ListChecks, CheckCircle2, Calendar, ChevronDown } from 'lucide-react';
import ReorderModal from './ReorderModal';
import OverrideReasonModal from './OverrideReasonModal';
import Modal from './Modal';
import { useToast } from './ToastProvider';
import { getCurrentUser } from '../auth';
import { logAction } from '../utils/auditLogger';
import { getRecommendations, decideRecommendation } from '../api/recommendations';
import { formatDateTime, formatMonth } from '../utils/formatDate';
import { formatUnits, exactUnits, wholeUnits } from '../utils/formatNumber';
import { useBrandLookup } from '../utils/useBrandLookup';
// The cycle selector reuses DateFilter's control styles without the component.
import './DateFilter.css';
import './ReorderRecommendations.css';

// Helper to format SKU to 5 digits (SKU-#####)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  return sku;
};



const ReorderRecommendations = () => {
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();

  // Recommendations are grouped by planning cycle — one LP run, for the
  // month after the latest real sales. This page used to filter by the
  // shared date range instead, whose picker stops at Feb 2026, so the
  // current Mar 2026 cycle (the one a planner acts on) could never be
  // shown, while older still-pending cycles got mixed into one table.
  // null until the data loads, then defaults to the most recent cycle.
  const [selectedCycle, setSelectedCycle] = useState(null);

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
    getRecommendations({ status: 'pending' })
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
  }, []);

  // GET /recommendations has no brand field; this was hardcoded 'Unilever'
  // (the principal) on every row. Real brand comes from the product master,
  // looked up at render time rather than mapped into `data` below: `data`
  // resets localData, so the lookup arriving late would wipe any
  // accept/dismiss state already applied to the rows.
  const brandLookup = useBrandLookup();

  // Map API shape -> the row shape the rest of this page renders. actionStatus/
  // loadingAction are local-only UI state layered on top of each real row.
  const data = useMemo(
    () =>
      rawItems.map((item) => ({
        id: item.recommendation_key,
        sku: item.sku_id,
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

  // Distinct planning cycles, newest first, with how many rows each holds.
  const cycles = useMemo(() => {
    const counts = new Map();
    localData.forEach((item) => {
      if (item.planningCycleDate) counts.set(item.planningCycleDate, (counts.get(item.planningCycleDate) || 0) + 1);
    });
    return [...counts.entries()]
      .sort((a, b) => (a[0] < b[0] ? 1 : -1))
      .map(([date, count]) => ({ date, count }));
  }, [localData]);

  useEffect(() => {
    if (cycles.length && !cycles.some((c) => c.date === selectedCycle)) {
      setSelectedCycle(cycles[0].date);
    }
  }, [cycles, selectedCycle]);

  const cycleRows = useMemo(
    () => localData.filter((item) => item.planningCycleDate === selectedCycle),
    [localData, selectedCycle]
  );

  // Deep link from the Dashboard's reorder widget (?sku=...): switch to the
  // most recent cycle holding that SKU, then open its detail modal — the
  // same modal a click on the table's SKU cell opens. deepLinkHandled stops
  // the modal reopening if it's closed while ?sku= is still in the URL.
  const deepLinkHandled = useRef(false);
  useEffect(() => {
    const targetSku = searchParams.get('sku');
    if (!targetSku || deepLinkHandled.current || localData.length === 0) return;
    const match = localData
      .filter((item) => String(item.sku) === targetSku)
      .sort((a, b) => (a.planningCycleDate < b.planningCycleDate ? 1 : -1))[0];
    if (match) {
      deepLinkHandled.current = true;
      setSelectedCycle(match.planningCycleDate);
      handleOpenDetails(match);
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete('sku');
        return next;
      }, { replace: true });
    }
  }, [localData, searchParams, setSearchParams]);

  const criticalCount = cycleRows.filter(item => item.urgency === 'CRITICAL').length;
  const urgentCount = cycleRows.filter(item => item.urgency === 'URGENT').length;
  // Summed in whole units, so the card equals the sum of the table's rows.
  const totalOrderQty = cycleRows.reduce((sum, item) => sum + (wholeUnits(item.orderQty) || 0), 0);
  const totalStock = cycleRows.reduce((sum, item) => sum + (item.stock || 0), 0);

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
        timestamp: formatDateTime(new Date()),
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
      case 'CRITICAL': return 'pill pill-critical';
      case 'URGENT': return 'pill pill-warning';
      case 'PLANNED': return 'pill pill-planned';
      default: return 'pill pill-neutral';
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
      case 'ACCEPTED': return 'pill pill-success';
      case 'DISMISSED': return 'pill pill-neutral';
      default: return 'pill pill-neutral';
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
          <span className={getLogActionBadge(item.actionStatus)}>
            {item.actionStatus}
          </span>
        </div>
      );
    }

    return (
      <div className="table-btn-group">
        <button
          className="table-btn table-btn-primary"
          onClick={() => handleAction(item, 'ACCEPTED')}
          aria-label={`Accept reorder for SKU ${item.sku}`}
        >
          Accept
        </button>
        <button
          className="table-btn"
          onClick={() => handleAction(item, 'DISMISSED')}
          aria-label={`Dismiss reorder for SKU ${item.sku}`}
        >
          Dismiss
        </button>
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
      <div className="data-table-card">
        <table className="data-table reorder-table">
          <thead>
            <tr>
              <th className="col-fit">SKU</th>
              <th className="col-fit">Brand</th>
              <th>Product</th>
              <th className="table-num col-fit">Safety stock</th>
              <th className="table-num col-fit">ROP</th>
              <th className="table-num col-fit">Current stock</th>
              <th className="table-num col-fit">LP qty</th>
              <th className="col-fit">Urgency</th>
              <th className="table-center col-fit"><span className="visually-hidden">Action</span></th>
            </tr>
          </thead>
          <tbody>
            {cycleRows.map((item) => {
              const brand = brandLookup?.get(String(item.sku));
              return (
                <tr key={item.id} className={getUrgencyRowClass(item.urgency)}>
                  <td className="cell-code">
                    <span
                      className="cell-code-link"
                      role="button"
                      tabIndex={0}
                      onClick={() => handleOpenDetails(item)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleOpenDetails(item);
                        }
                      }}
                      title="View recommendation details"
                    >
                      {formatSKU(item.sku)}
                    </span>
                  </td>
                  <td className={brand ? 'cell-muted' : 'cell-empty'}>{brand || '—'}</td>
                  <td className="cell-product">{item.product}</td>
                  {/* ROP = forecast + safety stock, so the buffer sits right
                      before it; it used to be visible only inside the modal. */}
                  <td className="table-num" title={exactUnits(item.safetyStock)}>{formatUnits(item.safetyStock)}</td>
                  <td className="table-num" title={exactUnits(item.rop)}>{formatUnits(item.rop)}</td>
                  <td
                    className={`table-num reorder-stock-cell ${
                      item.stock < item.rop * 0.5
                        ? 'reorder-stock-critical'
                        : item.stock < item.rop
                          ? 'reorder-stock-low'
                          : ''
                    }`}
                  >
                    {formatUnits(item.stock)}
                  </td>
                  <td className="table-num cell-strong" title={exactUnits(item.orderQty)}>{formatUnits(item.orderQty)}</td>
                  <td>
                    <span className={getUrgencyBadge(item.urgency)}>
                      {item.urgency}
                    </span>
                  </td>
                  <td className="table-center">
                    {renderActionColumn(item)}
                  </td>
                </tr>
              );
            })}
            {cycleRows.length === 0 && (
              <tr className="table-empty-row">
                <td colSpan="9">No pending recommendations for this planning cycle.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );

  const renderDecisionLogTab = () => (
    <div className="data-table-card">
      <table className="data-table reorder-table reorder-log-table">
        <thead>
          <tr>
            <th className="col-fit">When</th>
            <th className="col-fit">SKU</th>
            <th>Product</th>
            <th className="col-fit">Decision</th>
            <th>Reason</th>
            <th className="col-fit">Decided by</th>
          </tr>
        </thead>
        <tbody>
          {decisionLog.length === 0 ? (
            <tr className="table-empty-row">
              <td colSpan="6">
                No decisions recorded yet this session. Accept or dismiss a recommendation to see it logged here.
              </td>
            </tr>
          ) : (
            decisionLog.map((entry) => (
              <tr key={entry.id}>
                <td className="cell-muted">{entry.timestamp}</td>
                <td className="cell-code">{formatSKU(entry.sku)}</td>
                <td className="cell-product">{entry.product}</td>
                <td>
                  <span className={getLogActionBadge(entry.action)}>
                    {entry.action}
                  </span>
                </td>
                <td className="reorder-log-reason">{entry.reason || <span className="cell-empty">—</span>}</td>
                <td className="cell-muted">{entry.decidedBy}</td>
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
              Reorder <span className="page-title-accent">recommendations</span>
            </h2>
            {cycles.length > 0 && (
              <div className="dashboard-date-controls">
                <span className="date-single-label">Planning cycle</span>
                <div className="date-select-btn" style={{ position: 'relative' }}>
                  <Calendar size={14} />
                  {selectedCycle ? formatMonth(selectedCycle) : ''}
                  {selectedCycle === cycles[0].date && <span className="reorder-cycle-latest">latest</span>}
                  <ChevronDown size={14} />
                  <select
                    aria-label="Planning cycle"
                    style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
                    value={selectedCycle || ''}
                    onChange={(e) => setSelectedCycle(e.target.value)}
                  >
                    {cycles.map((c, i) => (
                      <option key={c.date} value={c.date}>
                        {formatMonth(c.date)}{i === 0 ? ' (latest)' : ''} · {c.count} pending
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}
          </div>
          <p className="reorder-page-subtitle">
            LP-optimized purchase quantities for Category A SKUs. Minimizes total inventory cost while preventing stockouts.
            {' '}Each planning cycle is one optimization run, for the month after the latest sales data.
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
            Order <strong>{formatUnits(pendingAccept.orderQty)}</strong> units of{' '}
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
