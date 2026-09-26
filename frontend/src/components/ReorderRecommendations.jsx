import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import {
  Loader2, ClipboardList, ListChecks, CheckCircle2, Calendar, ChevronDown, ChevronRight, CheckCheck,
} from 'lucide-react';
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
import { LoadingStatus, SkeletonLine, SkeletonStatCards, SkeletonTable } from './Skeleton';
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

// ── Impact ranking (2026-09-18) ──────────────────────────────────────────
// Live, the latest cycle was 248 of 250 rows CRITICAL and 0 URGENT — a
// severity that never varies carries no information, so the list is now
// ordered by business impact: GET /recommendations' priority_score
// (revenue share x units below the reorder point — a ranking index, not
// pesos; see backend/routers/recommendations.py for the unit caveat).
// The top ACT_NOW_COUNT are "Act now"; everything else is collapsed under
// "Review later". Rows the backend could not rank (no revenue share, or no
// stock record) sort to the bottom and are marked unranked — never
// ranked as if their score were zero.
const ACT_NOW_COUNT = 20;
const URGENCY_RANK = { CRITICAL: 0, URGENT: 1, PLANNED: 2, 'NO DATA': 3 };

// Fire at most this many PATCHes at once during a bulk accept — there is
// no bulk endpoint, so this is N sequential-ish writes against Supabase.
const BULK_CONCURRENCY = 5;

const COVER_BASIS_NOTE =
  'Stock at cost (₱) ÷ average daily sales value (₱/day, last 3 sales months) — the same peso basis the Dashboard’s '
  + 'weeks of cover uses. Understates cover by the margin, since stock is valued at last purchase cost while sales '
  + 'are at selling price.';

const ReorderRecommendations = () => {
  // Shared principal scope (Topbar's segmented control). lp_recommendation
  // has no Del Monte rows yet, so 'delmonte' renders this page's normal
  // empty state rather than an error.
  const { principal } = useOutletContext() || {};
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
  // Which LP cycle this list is, how many undecided rows from earlier runs
  // were withheld, and whether the run predates its own forecasts
  // (backend/lp_cycle.py). The list is the CURRENT cycle only — a leftover
  // 2023 row is not something to act on today — so the page has to say
  // that rather than quietly showing fewer rows than the database holds.
  const [meta, setMeta] = useState(null);
  const [selectedItem, setSelectedItem] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('RECOMMENDATIONS');
  const [showReviewLater, setShowReviewLater] = useState(false);

  // Pending override awaiting a reason (Dismiss only — Accept logs immediately).
  const [pendingOverride, setPendingOverride] = useState(null); // { item, action }
  const [pendingAccept, setPendingAccept] = useState(null); // the item awaiting Accept confirmation
  const [pendingBulk, setPendingBulk] = useState(null); // { rows } awaiting bulk-accept confirmation
  const [bulkRunning, setBulkRunning] = useState(false);
  // Accept/Dismiss is admin-only (backend: require_admin on PATCH
  // /recommendations); staff can review every recommendation but not act.
  const isAdmin = getCurrentUser()?.role === 'admin';
  const [decisionLog, setDecisionLog] = useState([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRecommendations({ status: 'pending', principal })
      .then((res) => {
        if (cancelled) return;
        setRawItems(res.items || []);
        setMeta({
          cycleDate: res.planning_cycle_date || null,
          supersededCount: res.superseded_count || 0,
          // Preview with the what-if LP (backend/data_mode.py): these rows
          // were never saved, so there is nothing to accept or dismiss.
          whatIf: Boolean(res.data_mode?.outputs),
        });
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
  }, [principal]);

  // GET /recommendations has no brand field; this was hardcoded 'Unilever'
  // (the principal) on every row. Real brand comes from the product master,
  // looked up at render time rather than mapped into `data` below: `data`
  // resets localData, so the lookup arriving late would wipe any
  // accept/dismiss state already applied to the rows.
  const brandLookup = useBrandLookup(principal);

  // Map API shape -> the row shape the rest of this page renders. actionStatus/
  // loadingAction are local-only UI state layered on top of each real row.
  const data = useMemo(
    () =>
      rawItems.map((item) => ({
        id: item.recommendation_key,
        sku: item.sku_id,
        product: item.product_name || 'Unknown Product',
        rop: item.rop_i,
        stock: item.current_stock, // null = no inventory row at the latest snapshot
        orderQty: item.q_i,
        safetyStock: item.ss_i,
        urgency: item.urgency,
        planningCycleDate: item.planning_cycle_date,
        revenueShare: item.revenue_share,
        priorityScore: item.priority_score,
        stockoutGap: item.stockout_gap,
        daysOfCover: item.days_of_cover,
        coverReason: item.cover_blocked_reason,
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

  // Ranked by priority_score (desc); unranked rows last, then by urgency,
  // then by ROP so the order is stable. Rank numbers are assigned here so
  // an accepted/dismissed row keeps its position (and number) instead of
  // reshuffling the list under the planner mid-session.
  const rankedRows = useMemo(() => {
    const score = (r) => (r.priorityScore == null ? -1 : r.priorityScore);
    const sorted = [...cycleRows].sort(
      (a, b) =>
        score(b) - score(a)
        || (URGENCY_RANK[a.urgency] ?? 9) - (URGENCY_RANK[b.urgency] ?? 9)
        || (b.rop ?? 0) - (a.rop ?? 0)
    );
    let rank = 0;
    return sorted.map((r) => ({ ...r, rank: r.priorityScore == null ? null : ++rank }));
  }, [cycleRows]);

  const actNowRows = rankedRows.slice(0, ACT_NOW_COUNT);
  const reviewLaterRows = rankedRows.slice(ACT_NOW_COUNT);
  const visibleRows = showReviewLater ? rankedRows : actNowRows;
  const bulkTargets = visibleRows.filter((r) => !r.actionStatus && !r.loadingAction);

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
      setShowReviewLater(true); // the linked SKU may sit below the top 20
      handleOpenDetails(match);
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete('sku');
        return next;
      }, { replace: true });
    }
  }, [localData, searchParams, setSearchParams]);

  const actNowPending = actNowRows.filter((r) => !r.actionStatus).length;
  const noStockRecordCount = cycleRows.filter((r) => r.stock == null).length;
  // Summed in whole units, so the card equals the sum of the table's rows.
  const totalOrderQty = cycleRows.reduce((sum, item) => sum + (wholeUnits(item.orderQty) || 0), 0);

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

  // Writes one decision. Returns true on success. `silent` skips the
  // per-row toast so a bulk accept can report once at the end.
  const applyAction = async (id, actionType, { silent = false } = {}) => {
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
      if (!silent) {
        toast.success(actionType === 'ACCEPTED' ? 'Reorder accepted' : 'Recommendation dismissed');
      }
      return true;
    } catch (err) {
      setLocalData(prev => prev.map(item =>
        item.id === id ? { ...item, loadingAction: null } : item
      ));
      if (!silent) {
        setError(err.message || 'Failed to update recommendation');
        toast.error(err.message || 'Failed to update recommendation');
      }
      return false;
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

  // Bulk accept — every pending row currently in view (the Act-now list,
  // or the whole cycle once Review later is expanded). Runs in small
  // batches; each success is logged individually so the decision log and
  // audit log read the same as if the rows had been accepted one by one.
  const handleConfirmBulk = async () => {
    const rows = pendingBulk?.rows || [];
    setPendingBulk(null);
    if (rows.length === 0) return;
    setBulkRunning(true);
    let accepted = 0;
    let failed = 0;
    for (let i = 0; i < rows.length; i += BULK_CONCURRENCY) {
      const batch = rows.slice(i, i + BULK_CONCURRENCY);
      const results = await Promise.all(batch.map((r) => applyAction(r.id, 'ACCEPTED', { silent: true })));
      results.forEach((ok, idx) => {
        if (ok) {
          accepted += 1;
          logDecision(batch[idx], 'ACCEPTED', `Accepted in bulk ("Accept all in view", ${formatMonth(selectedCycle)} cycle).`);
        } else {
          failed += 1;
        }
      });
    }
    setBulkRunning(false);
    if (failed === 0) {
      toast.success(`${accepted} reorder${accepted === 1 ? '' : 's'} accepted`);
    } else {
      toast.error(`${accepted} accepted, ${failed} failed — the failed rows are still pending`);
    }
  };

  const getUrgencyBadge = (urgency) => {
    switch (urgency) {
      case 'CRITICAL': return 'pill pill-critical';
      case 'URGENT': return 'pill pill-warning';
      case 'PLANNED': return 'pill pill-planned';
      default: return 'pill pill-neutral'; // 'NO DATA' — no stock record, no verdict
    }
  };

  const getLogActionBadge = (action) => {
    switch (action) {
      case 'ACCEPTED': return 'pill pill-planned';
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

    if (meta?.whatIf) {
      return (
        <div className="action-status-container">
          <span className="reorder-pending-label" title="A what-if row from the preview, never saved — nothing to decide">
            What-if
          </span>
        </div>
      );
    }

    // Staff: the row's state instead of buttons — the one-line note above
    // the table says why there's nothing to click.
    if (!isAdmin) {
      return (
        <div className="action-status-container">
          <span className="reorder-pending-label" title="Waiting for an admin to accept or dismiss">
            Pending
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
          disabled={bulkRunning}
        >
          Accept
        </button>
        <button
          className="table-btn"
          onClick={() => handleAction(item, 'DISMISSED')}
          aria-label={`Dismiss reorder for SKU ${item.sku}`}
          disabled={bulkRunning}
        >
          Dismiss
        </button>
      </div>
    );
  };

  const renderRow = (item) => {
    const brand = brandLookup?.get(String(item.sku));
    const stockKnown = item.stock != null;
    return (
      <tr key={item.id}>
        <td className="table-num reorder-rank">
          {item.rank != null ? (
            `#${item.rank}`
          ) : (
            <span className="cell-empty" title={stockKnown ? 'Unranked — no revenue share recorded for this SKU' : 'Unranked — no stock record, so the gap below the reorder point is unknown'}>
              —
            </span>
          )}
        </td>
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
        <td className="table-num" title="Share of period revenue at this SKU's latest ABC classification">
          {item.revenueShare != null ? `${(item.revenueShare * 100).toFixed(2)}%` : <span className="cell-empty">—</span>}
        </td>
        {/* ROP = forecast + safety stock, so the buffer sits right
            before it; it used to be visible only inside the modal. */}
        <td className="table-num" title={exactUnits(item.safetyStock)}>{formatUnits(item.safetyStock)}</td>
        <td className="table-num" title={exactUnits(item.rop)}>{formatUnits(item.rop)}</td>
        <td
          className={`table-num reorder-stock-cell ${
            !stockKnown
              ? ''
              : item.stock < item.rop * 0.5
                ? 'reorder-stock-critical'
                : item.stock < item.rop
                  ? 'reorder-stock-low'
                  : ''
          }`}
        >
          {stockKnown
            ? formatUnits(item.stock)
            : <span className="cell-empty" title="No inventory record for this SKU at the latest snapshot">—</span>}
        </td>
        <td className="table-num" title={item.daysOfCover != null ? COVER_BASIS_NOTE : (item.coverReason || COVER_BASIS_NOTE)}>
          {item.daysOfCover != null ? item.daysOfCover.toFixed(1) : <span className="cell-empty">—</span>}
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
  };

  const COLUMN_COUNT = 12;

  const renderRecommendationsTab = () => (
    <>
      {/* Summary Cards — coloured by the app-wide SEMANTIC rule: red = act
          now, amber = watch, slate = no data, indigo = model output. */}
      <div className="reorder-summary-grid">
        <div className="reorder-summary-card card-act">
          <div className="card-content">
            <span className="reorder-card-label">ACT NOW</span>
            <span className="reorder-card-value">{actNowPending}</span>
            <span className="reorder-card-desc">top {ACT_NOW_COUNT} by revenue at risk, still pending</span>
          </div>
        </div>
        <div className="reorder-summary-card card-watch">
          <div className="card-content">
            <span className="reorder-card-label">REVIEW LATER</span>
            <span className="reorder-card-value">{reviewLaterRows.length}</span>
            <span className="reorder-card-desc">lower revenue at risk</span>
          </div>
        </div>
        <div className="reorder-summary-card card-nodata">
          <div className="card-content">
            <span className="reorder-card-label">NO STOCK RECORD</span>
            <span className="reorder-card-value">{noStockRecordCount}</span>
            <span className="reorder-card-desc">not in the latest inventory snapshot</span>
          </div>
        </div>
        <div className="reorder-summary-card card-recommendation">
          <div className="card-content">
            <span className="reorder-card-label">TOTAL ORDER QTY</span>
            <span className="reorder-card-value">{totalOrderQty.toLocaleString()}</span>
            <span className="reorder-card-desc">LP - optimized units</span>
          </div>
        </div>
      </div>

      <div className="reorder-table-toolbar">
        <p className="reorder-table-note">
          Ranked by revenue share × units below the reorder point. Cover is in days on a peso basis
          (stock at cost ÷ daily sales value).
        </p>
        {meta?.whatIf && (
          <p className="chart-placeholder-note">
            Preview: these recommendations are a what-if run of the LP on the five-year history, 2021–22 placeholder
            months included. They are never saved, so they can&apos;t be accepted or dismissed.
          </p>
        )}
        {!isAdmin && !meta?.whatIf && (
          <p className="reorder-view-only-note">
            View only — accepting or dismissing reorders is limited to admin accounts.
          </p>
        )}
        {isAdmin && !meta?.whatIf && (
          <button
            className="reorder-bulk-btn"
            onClick={() => setPendingBulk({ rows: bulkTargets })}
            disabled={bulkTargets.length === 0 || bulkRunning}
            title={bulkTargets.length === 0 ? 'No pending rows in view' : undefined}
          >
            {bulkRunning ? <Loader2 className="spinner-icon" size={14} /> : <CheckCheck size={14} />}
            Accept all in view ({bulkTargets.length})
          </button>
        )}
      </div>

      {/* Table */}
      <div className="data-table-card">
        <table className="data-table reorder-table">
          <thead>
            <tr>
              <th className="table-num col-fit">#</th>
              <th className="col-fit">SKU</th>
              <th className="col-fit">Brand</th>
              <th className="col-text col-product">Product</th>
              <th className="table-num col-fit">Rev share</th>
              <th className="table-num col-fit">Safety stock</th>
              <th className="table-num col-fit">ROP</th>
              <th className="table-num col-fit">Current stock</th>
              <th className="table-num col-fit" title={COVER_BASIS_NOTE}>Cover (days)</th>
              <th className="table-num col-fit">LP qty</th>
              <th className="col-fit">Urgency</th>
              <th className="table-center col-fit"><span className="visually-hidden">Action</span></th>
            </tr>
          </thead>
          <tbody>
            {actNowRows.length > 0 && (
              <tr className="reorder-group-row reorder-group-act">
                <td colSpan={COLUMN_COUNT}>
                  Act now — top {Math.min(ACT_NOW_COUNT, actNowRows.length)} by revenue at risk
                </td>
              </tr>
            )}
            {actNowRows.map(renderRow)}
            {reviewLaterRows.length > 0 && (
              <tr className="reorder-group-row reorder-group-later">
                <td colSpan={COLUMN_COUNT}>
                  <button
                    type="button"
                    className="reorder-group-toggle"
                    onClick={() => setShowReviewLater((v) => !v)}
                    aria-expanded={showReviewLater}
                  >
                    {showReviewLater ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    Review later — {reviewLaterRows.length} more
                    {showReviewLater ? '' : ' (collapsed)'}
                  </button>
                </td>
              </tr>
            )}
            {showReviewLater && reviewLaterRows.map(renderRow)}
            {cycleRows.length === 0 && (
              <tr className="table-empty-row">
                <td colSpan={COLUMN_COUNT}>No pending recommendations for this planning cycle.</td>
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
            <th className="col-text col-product">Product</th>
            <th className="col-fit">Decision</th>
            <th className="col-text col-reason">Reason</th>
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
                <td className="col-text reorder-log-reason">{entry.reason || <span className="cell-empty">—</span>}</td>
                <td className="cell-muted">{entry.decidedBy}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );

  const bulkQty = (pendingBulk?.rows || []).reduce((sum, r) => sum + (wholeUnits(r.orderQty) || 0), 0);

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
                    onChange={(e) => { setSelectedCycle(e.target.value); setShowReviewLater(false); }}
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
            {meta?.supersededCount > 0 && (
              <>
                {' '}Showing the current cycle only — {meta.supersededCount.toLocaleString()} undecided
                {' '}row{meta.supersededCount === 1 ? '' : 's'} from earlier runs {meta.supersededCount === 1 ? 'is' : 'are'} superseded and not listed.
              </>
            )}
          </p>
          {/* LP freshness notice removed 2026-09-24 with the Dashboard's
              (see Dashboard.jsx); GET /recommendations still returns it. */}
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

        {loading && (
          <>
            <LoadingStatus>Loading recommendations…</LoadingStatus>
            {activeTab === 'RECOMMENDATIONS' ? (
              <>
                <div className="reorder-summary-grid">
                  <SkeletonStatCards count={4} cardClassName="reorder-summary-card" />
                </div>
                <div className="reorder-table-toolbar" aria-hidden="true">
                  <SkeletonLine width="58%" height="0.8rem" />
                </div>
                <div className="data-table-card">
                  <SkeletonTable rows={8} columns={13} />
                </div>
              </>
            ) : (
              <div className="data-table-card">
                <SkeletonTable rows={6} columns={7} />
              </div>
            )}
          </>
        )}
        {error && <p className="reorder-page-subtitle">Error: {error}</p>}
        {!loading && !error && (activeTab === 'RECOMMENDATIONS' ? renderRecommendationsTab() : renderDecisionLogTab())}
      </div>

      {/* Resolve the row through rankedRows so a modal opened from a
          Dashboard deep link (which selects from the unranked localData)
          still shows its impact rank once the cycle's rows are ranked. */}
      <ReorderModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        data={selectedItem ? (rankedRows.find((r) => r.id === selectedItem.id) || selectedItem) : null}
        principal={principal}
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

      {pendingBulk && (
        <Modal
          isOpen={Boolean(pendingBulk)}
          onClose={() => setPendingBulk(null)}
          label="Confirm bulk acceptance"
          overlayClassName="reorder-accept-overlay"
          containerClassName="reorder-accept-card"
        >
          <div className="reorder-accept-icon">
            <CheckCheck size={20} />
          </div>
          <h3 className="reorder-accept-title">Accept all {pendingBulk.rows.length} in view?</h3>
          <p className="reorder-accept-body">
            This accepts every pending recommendation currently shown
            {showReviewLater ? ' (Act now and Review later)' : ' in the Act-now list'} for the{' '}
            <strong>{formatMonth(selectedCycle)}</strong> cycle — <strong>{bulkQty.toLocaleString()}</strong> units
            across <strong>{pendingBulk.rows.length}</strong> SKUs, at the LP-recommended quantities. Each one is
            logged individually.
          </p>
          <div className="reorder-accept-actions">
            <button className="reorder-accept-cancel" onClick={() => setPendingBulk(null)}>
              Cancel
            </button>
            <button className="reorder-accept-confirm" onClick={handleConfirmBulk}>
              Accept {pendingBulk.rows.length} reorders
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
};

export default ReorderRecommendations;
