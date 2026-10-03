import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import {
  Loader2, ClipboardList, ListChecks, CheckCircle2, Calendar, ChevronDown, ChevronRight, CheckCheck,
  AlertTriangle,
} from 'lucide-react';
import ReorderModal from './ReorderModal';
import InfoTip from './InfoTip';
import OverrideReasonModal from './OverrideReasonModal';
import Modal from './Modal';
import SaveResult from './SaveResult';
import { useToast } from './ToastProvider';
import { useSaveResult } from '../utils/useSaveResult';
import { getCurrentUser } from '../auth';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import { getRecommendations, decideRecommendation } from '../api/recommendations';
import { formatDate, formatDateTime, formatMonth } from '../utils/formatDate';
import { labelForPrincipal } from '../principals';
import { formatUnits, wholeUnits } from '../utils/formatNumber';
import { useBrandLookup } from '../utils/useBrandLookup';
import { LoadingStatus, SkeletonLine, SkeletonStatCards, SkeletonTable } from './Skeleton';
// The cycle selector reuses DateFilter's control styles without the component.
import './DateFilter.css';
// .dash-stale-note — the LP freshness notice, defined once with the
// Dashboard's styles and reused here so both pages warn identically.
import './Dashboard.css';
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
// (revenue share x pieces below the target stock, rop_i — a ranking index,
// not pesos; see backend/routers/recommendations.py).
// The top ACT_NOW_COUNT are "Act now"; everything else is collapsed under
// "Review later". Rows the backend could not rank (no revenue share, or no
// stock figure in pieces) sort to the bottom and are marked unranked — never
// ranked as if their score were zero. A SKU missing from the opening stock
// count is NOT one of them since 2026-10-01: the LP plans it as 0 on hand,
// so the API does too (stock_not_in_count) and it is ranked like the rest.
const ACT_NOW_COUNT = 20;
const URGENCY_RANK = { CRITICAL: 0, URGENT: 1, PLANNED: 2, 'NO DATA': 3 };

// Fire at most this many PATCHes at once during a bulk accept — there is
// no bulk endpoint, so this is N sequential-ish writes against Supabase.
const BULK_CONCURRENCY = 5;

// Accept needs no typed reason; this is the one recorded for it.
const ACCEPT_REASON = 'Accepted the LP-recommended order quantity as-is.';

const COVER_BASIS_NOTE =
  'Stock at cost (₱) ÷ average daily sales value (₱/day, last 3 sales months) — the same peso basis the Dashboard’s '
  + 'weeks of cover uses. Understates cover by the margin, since stock is valued at last purchase cost while sales '
  + 'are at selling price.';

// Every quantity on this page is in PIECES — the LP's unit (q_i, rop_i,
// ss_i and the forecast all come from the pieces demand series) — while SSM
// buys in cases. formatNumber.js's exactUnits says "units", so the exact
// figure in this page's tooltips is spelled out here instead.
const exactPieces = (value) => {
  if (value == null || Number.isNaN(Number(value))) return undefined;
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} pieces (exact)`;
};

// Pieces as an approximate case count, e.g. "≈ 363 cases of 288", from the
// row's pack size (pieces per case, GET /recommendations' pack_size). Only
// 6 of the 73 orders in the 2026-03 cycle are whole cases (pack sizes run
// from 6 to 576 pieces), so this is a reading aid next to the pieces, never
// a rounded order. null with no pack size (pieces only) or nothing to count.
const casesNote = (pieces, packSize) => {
  const whole = wholeUnits(pieces); // the figure the table shows
  if (!whole || !(packSize > 0)) return null;
  const cases = whole / packSize;
  const of = `of ${packSize.toLocaleString()}`;
  if (cases < 1) return `under 1 case ${of}`;
  const n = Math.round(cases);
  return `${Number.isInteger(cases) ? '' : '≈ '}${n.toLocaleString()} case${n === 1 ? '' : 's'} ${of}`;
};

// Tooltip for a quantity cell: the exact pieces, then the case count.
const piecesTitle = (pieces, packSize) => {
  const exact = exactPieces(pieces);
  const cases = casesNote(pieces, packSize);
  return exact && cases ? `${exact} · ${cases}` : exact;
};

// Said wherever a 0 on hand was inferred rather than counted.
const NOT_IN_COUNT_NOTE = 'Not in the opening stock count — treated as 0, as the plan does (the stock file lists no '
  + 'zero-stock rows, so a missing SKU is most likely out of stock).';

// The LP's arithmetic for one row, in its Suggested qty tooltip: forecast +
// target − stock on hand is the need (never below 0), and any cut made to
// fit the supplier allocation is subtracted from it. Falls back to the exact
// figure when the row has no forecast or stock to show the working with.
const lpQtyTitle = (item) => {
  const n = (v) => Math.round(v).toLocaleString();
  if (item.forecast == null || item.stock == null) return piecesTitle(item.orderQty, item.packSize);
  const need = Math.max(0, item.forecast + item.rop - item.stock);
  // A Del Monte count has no loaded date: name its month, never the 1st-of-month placeholder.
  const counted = item.stockCountedOn
    ? `stock counted ${formatDate(item.stockCountedOn)}`
    : item.stockCountMonth ? `count month: ${formatMonth(item.stockCountMonth)} (exact date not recorded)` : null;
  const onHand = item.stockNotInCount
    ? `0 on hand (not in the opening stock count${counted ? `, ${counted}` : ''})`
    : `${n(item.stock)} on hand${counted ? ` (${counted})` : ''}`;
  const working = `${n(item.forecast)} forecast + ${n(item.rop)} target − ${onHand} = ${n(need)} pieces needed`;
  if (item.shortUnits > 0) {
    return `${working}; ${n(item.shortUnits)} cut to fit the supplier allocation, so ${n(item.orderQty)} ordered `
      + `and the SKU ends the month ${n(item.shortUnits)} pieces below its target.`;
  }
  return need === 0 ? `${working} — stock already covers the month and the target, so nothing is ordered.` : working;
};

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
  const [bulkDone, setBulkDone] = useState(0); // rows answered so far, for the dialog's progress
  // The Accept and bulk-Accept dialogs show their result in place: a green
  // check then close, or a red X with the reason.
  const acceptSave = useSaveResult();
  const bulkSave = useSaveResult();
  const [acceptError, setAcceptError] = useState('');
  // Accept/Dismiss need lp.decide (Kelvin's permissions proposal; the
  // backend checks it on PATCH /recommendations). Without it the page is
  // view only: every recommendation can be reviewed, none acted on.
  const { hasPermission } = usePermissions();
  const canDecide = hasPermission(P.LP_DECIDE);
  const [decisionLog, setDecisionLog] = useState([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRecommendations({ status: 'pending', principal })
      .then((res) => {
        if (cancelled) return;
        // The stock count each row was checked against — the one that opens
        // its cycle — attached here so the row can say when it was counted.
        const counts = new Map((res.stock_counts || []).map((c) => [`${c.cycle}|${c.principal}`, c]));
        setRawItems((res.items || []).map((it) => ({
          ...it, stock_count: counts.get(`${it.planning_cycle_date}|${it.principal}`) || null,
        })));
        setMeta({
          cycleDate: res.planning_cycle_date || null,
          supersededCount: res.superseded_count || 0,
          freshness: res.freshness || null,
          // The solver's own weights and service level (backend/lp_cycle.py),
          // for the detail modal to state instead of repeating constants.
          lpModel: res.lp_model || null,
          // The opening stock counts the rows were checked against, with
          // their dates and any flag (backend/stock_units.stock_count_info).
          stockCounts: res.stock_counts || [],
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
        // Pieces. 0 with stockNotInCount when the SKU is missing from the
        // opening stock count (the LP's reading); null only when there is no
        // figure in pieces at all — stockBlockedReason says why.
        stock: item.current_stock,
        // When that count was taken; null where the file's date isn't loaded
        // (Del Monte), which names the count's month instead.
        stockCountedOn: item.stock_count?.counted_on || null,
        stockCountMonth: item.stock_count?.available ? item.stock_count.period : null,
        stockNotInCount: Boolean(item.stock_not_in_count),
        stockBlockedReason: item.stock_blocked_reason,
        packSize: item.pack_size, // pieces per case; null = show pieces only
        // "≈ 363 cases of 288" for the order, target and stock, worked out
        // once here so the table and the detail modal say the same thing.
        cases: {
          order: casesNote(item.q_i, item.pack_size),
          target: casesNote(item.rop_i, item.pack_size),
          stock: casesNote(item.current_stock, item.pack_size),
        },
        orderQty: item.q_i,
        safetyStock: item.ss_i,
        urgency: item.urgency,
        planningCycleDate: item.planning_cycle_date,
        revenueShare: item.revenue_share,
        tier: item.tier, // latest ABC run's tier; null = not ranked in that run
        priorityScore: item.priority_score,
        stockoutGap: item.stockout_gap,
        daysOfCover: item.days_of_cover,
        coverReason: item.cover_blocked_reason,
        // The cycle month's forecast and any cut made to fit the allocation
        // (GET /recommendations): LP qty = forecast + target - stock - short.
        forecast: item.forecast_units,
        shortUnits: item.short_units,
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
  // then by target stock (rop_i) so the order is stable. Rank numbers are assigned here so
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
  // Rows the backend could not rank (no stock figure or no revenue share)
  // have an UNKNOWN risk, not a lower one, so the card counts them apart.
  const reviewLaterUnranked = reviewLaterRows.filter((r) => r.priorityScore == null).length;
  // Missing from the opening stock count, so planned (and shown) as 0 on
  // hand — 3 of the 73 rows in the 2026-03 cycle, all cut by the LP. Kept
  // apart from rows with no stock figure at all (NO DATA: a stock row the
  // API can't put in pieces), which stay unranked.
  const notInCountCount = cycleRows.filter((r) => r.stockNotInCount).length;
  const noStockFigureCount = cycleRows.filter((r) => r.stock == null).length;
  // The LP plans Category A, but a cycle outlives the ABC run it was solved
  // against; GET /recommendations sends each row's tier in the latest run.
  const notCategoryACount = cycleRows.filter((r) => r.tier !== 'A').length;
  // Summed in whole pieces, so the card equals the sum of the table's rows.
  const totalOrderQty = cycleRows.reduce((sum, item) => sum + (wholeUnits(item.orderQty) || 0), 0);
  // Rows the allocation couldn't fully fund (short_units > 0) — the
  // allocation binds, so the total above is the allocation, not the need.
  const pendingRows = cycleRows.filter((item) => !item.actionStatus);
  const cutCount = pendingRows.filter((item) => item.shortUnits > 0).length;
  // The LP's own settings (backend/lp_cycle.lp_model_info), so the page's
  // account of how it cuts follows the run rather than a retyped copy.
  const lpInputs = meta?.lpModel?.inputs || {};
  // "Opening stock: Unilever count of Feb 2026, counted Mar 2, 2026 (accepted
  // for planning, pending SSM confirmation …)" for the cycle on screen, or the
  // reason there is none ("no opening stock count for …").
  const openingCountNote = (meta?.stockCounts || [])
    .filter((c) => !selectedCycle || c.cycle === selectedCycle)
    .map((c) => {
      const who = labelForPrincipal(c.principal);
      if (!c.available) return `${who}: ${c.reason}.`;
      const when = c.counted_on
        ? `counted ${formatDate(c.counted_on)}`
        : 'exact date not recorded';
      return `Opening stock: ${who} count of ${formatMonth(c.period)}, ${when}${c.flag ? ` (${c.flag})` : ''}.`;
    })
    .join(' ');
  const allocationPct = lpInputs.allocation_pct ?? null;

  const handleOpenDetails = (item) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  // This session's decision history (the Decision Log tab). The Audit Log
  // entry is the server's: PATCH /recommendations records it, reason and all.
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
  };

  // Writes one decision, with its reason. Returns true on success. `silent`
  // skips the per-row toast so a bulk accept can report once at the end;
  // `rethrow` passes a failure on to a dialog that shows it itself.
  const applyAction = async (id, actionType, { silent = false, reason, rethrow = false } = {}) => {
    setLocalData(prev => prev.map(item =>
      item.id === id ? { ...item, loadingAction: actionType } : item
    ));

    try {
      await decideRecommendation(id, actionType === 'ACCEPTED' ? 'accepted' : 'dismissed', reason);
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
      if (rethrow) throw err;
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
      acceptSave.reset();
      setAcceptError('');
      setPendingAccept(item);
      return;
    }
    // Dismiss deviates from the recommendation — require a reason first
    setPendingOverride({ item, action: actionType });
  };

  const handleConfirmAccept = () => {
    const item = pendingAccept;
    if (!item) return;
    setAcceptError('');
    acceptSave.run(async () => {
      await applyAction(item.id, 'ACCEPTED', { reason: ACCEPT_REASON, silent: true, rethrow: true });
      logDecision(item, 'ACCEPTED', ACCEPT_REASON);
    }, {
      onSaved: () => setPendingAccept(null),
      onFailed: setAcceptError,
      fallbackError: 'Failed to update recommendation',
    });
  };

  // OverrideReasonModal shows the check or X itself; a throw here is its X.
  const handleConfirmOverride = async (reason) => {
    const { item, action } = pendingOverride;
    await applyAction(item.id, action, { reason, silent: true, rethrow: true });
    logDecision(item, action, reason);
  };

  // Bulk accept — every pending row currently in view (the Act-now list,
  // or the whole cycle once Review later is expanded). Runs in small
  // batches; each row is its own PATCH, carrying the same reason, so the
  // decision log and audit log read the same as if the rows had been
  // accepted one by one. The dialog stays open with a count while it runs,
  // then shows a check, or an X when any row failed. Rows that did save stay
  // saved, so after a failure it closes rather than offering to re-run them.
  const handleConfirmBulk = () => {
    const rows = pendingBulk?.rows || [];
    if (rows.length === 0) {
      setPendingBulk(null);
      return;
    }
    setBulkDone(0);
    bulkSave.run(async () => {
      setBulkRunning(true);
      const reason = `Accepted in bulk ("Accept all in view", ${formatMonth(selectedCycle)} cycle).`;
      let accepted = 0;
      let failed = 0;
      try {
        for (let i = 0; i < rows.length; i += BULK_CONCURRENCY) {
          const batch = rows.slice(i, i + BULK_CONCURRENCY);
          const results = await Promise.all(batch.map((r) => applyAction(r.id, 'ACCEPTED', { silent: true, reason })));
          results.forEach((ok, idx) => {
            if (ok) {
              accepted += 1;
              logDecision(batch[idx], 'ACCEPTED', reason);
            } else {
              failed += 1;
            }
          });
          setBulkDone(accepted + failed);
        }
      } finally {
        setBulkRunning(false);
      }
      if (failed > 0) {
        throw new Error(`${accepted} accepted, ${failed} failed. The failed rows are still pending, so you can accept them again.`);
      }
      return accepted;
    }, {
      onSaved: () => setPendingBulk(null),
      // Stays in the corner after the dialog closes, for the rows to redo.
      onFailed: (message) => toast.error(message),
      afterFailed: () => setPendingBulk(null),
    });
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

    // Without lp.decide: the row's state instead of buttons — the one-line
    // note above the table says why there's nothing to click.
    if (!canDecide) {
      return (
        <div className="action-status-container">
          <span className="reorder-pending-label" title="Waiting for someone who can accept or dismiss">
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
            <span className="cell-empty" title={stockKnown ? 'Unranked — no revenue share recorded for this SKU' : 'Unranked — no stock figure in pieces, so the gap below the target stock is unknown'}>
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
        {/* Target stock (rop_i since the 2026-09-30 LP run: demand over
            the review + lead window + safety stock), so the buffer sits
            right before it; it used to be visible only inside the modal. */}
        {/* Pieces throughout; a hover adds the exact figure and the
            approximate case count. Only the order carries its case count
            on the face of the table — it is the figure a PO is raised from. */}
        <td className="table-num" title={piecesTitle(item.safetyStock, item.packSize)}>{formatUnits(item.safetyStock)}</td>
        <td className="table-num" title={piecesTitle(item.rop, item.packSize)}>{formatUnits(item.rop)}</td>
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
          title={item.stockNotInCount ? NOT_IN_COUNT_NOTE : (stockKnown ? piecesTitle(item.stock, item.packSize) : undefined)}
        >
          {stockKnown
            ? <>
                {formatUnits(item.stock)}
                {item.stockNotInCount && <span className="reorder-cell-note">not in count</span>}
              </>
            : <span className="cell-empty" title={item.stockBlockedReason || 'No stock figure in pieces for this SKU'}>—</span>}
        </td>
        <td className="table-num" title={item.daysOfCover != null ? COVER_BASIS_NOTE : (item.coverReason || COVER_BASIS_NOTE)}>
          {item.daysOfCover != null ? item.daysOfCover.toFixed(1) : <span className="cell-empty">—</span>}
        </td>
        <td className="table-num" title={item.forecast != null ? exactPieces(item.forecast) : 'No forecast for this planning month'}>
          {item.forecast != null ? formatUnits(item.forecast) : <span className="cell-empty">—</span>}
        </td>
        <td className="table-num cell-strong" title={lpQtyTitle(item)}>
          {formatUnits(item.orderQty)}
          {item.cases.order && <span className="reorder-cell-note">{item.cases.order}</span>}
          {item.shortUnits > 0 && <span className="reorder-short-note">{formatUnits(item.shortUnits)} short</span>}
        </td>
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

  const COLUMN_COUNT = 13;

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
            <span className="reorder-card-desc">
              {reviewLaterRows.length - reviewLaterUnranked} lower revenue at risk
              {reviewLaterUnranked > 0 && <> · {reviewLaterUnranked} not ranked (no stock figure or revenue share)</>}
            </span>
          </div>
        </div>
        {/* Until 2026-10-01 "NO STOCK RECORD": these rows showed no stock and
            went unranked, while the LP had planned them as 0 on hand and cut
            all three. They are now 0 like in the plan, counted here so the
            inferred 0 is never mistaken for a counted one. */}
        <div className="reorder-summary-card card-nodata">
          <div className="card-content">
            <span className="reorder-card-label">NOT IN STOCK COUNT</span>
            <span className="reorder-card-value">{notInCountCount}</span>
            <span className="reorder-card-desc">
              treated as 0 on hand, as the plan does
              {noStockFigureCount > 0 && <> · {noStockFigureCount} with no stock figure in pieces (NO DATA)</>}
            </span>
          </div>
        </div>
        <div className="reorder-summary-card card-recommendation">
          <div className="card-content">
            <span className="reorder-card-label">TOTAL ORDER (PIECES)</span>
            <span className="reorder-card-value">{totalOrderQty.toLocaleString()}</span>
            <span className="reorder-card-desc">
              {cutCount > 0
                ? `${cutCount} of ${pendingRows.length} SKUs cut to fit the ${allocationPct != null ? `${allocationPct}% ` : ''}supplier allocation`
                : 'Pieces suggested by the optimizer'}
            </span>
          </div>
        </div>
      </div>

      <div className="reorder-table-toolbar">
        <p className="reorder-table-note">
          All quantities are in pieces; under each order is its rough size in cases (pieces ÷ pieces per case).
          Suggested qty = the month&apos;s forecast + target stock − stock at the start of the month (the stock count
          that opens it). A row marked &ldquo;short&rdquo; was cut to fit the supplier allocation and ends the month that
          far below its target. A SKU missing from that stock count shows 0, &ldquo;not in count&rdquo;: the plan treats
          it as out of stock. Ranked by revenue share ×
          pieces below the target stock. Cover is in days on a peso basis (stock at cost ÷ daily sales value).
        </p>
        {openingCountNote && <p className="reorder-table-note">{openingCountNote}</p>}
        {meta?.whatIf && (
          <p className="chart-placeholder-note">
            Preview: these recommendations are a what-if run of the LP on the five-year history, 2021–22 placeholder
            months included. They are never saved, so they can&apos;t be accepted or dismissed.
          </p>
        )}
        {!canDecide && !meta?.whatIf && (
          <p className="reorder-view-only-note">
            View only — your account can&apos;t accept or dismiss reorders. Ask an admin if you need to.
          </p>
        )}
        {canDecide && !meta?.whatIf && (
          <button
            className="reorder-bulk-btn"
            onClick={() => {
              bulkSave.reset();
              setPendingBulk({ rows: bulkTargets });
            }}
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
              <th className="table-num col-fit">
                Target stock
                <InfoTip label="About target stock">The stock level each order tops up to: the demand expected before the next delivery, plus safety stock.</InfoTip>
              </th>
              <th className="table-num col-fit">Opening stock</th>
              <th className="table-num col-fit">
                Cover (days)
                <InfoTip label="About cover">{COVER_BASIS_NOTE}</InfoTip>
              </th>
              <th className="table-num col-fit">
                Forecast
                <InfoTip label="About forecast">This SKU&apos;s forecast sales for the planning month: what the order has to cover before it can build stock up to target.</InfoTip>
              </th>
              <th className="table-num col-fit">
                Suggested qty
                <InfoTip label="About suggested quantity">
                  What to order, in pieces, worked out by the optimizer (an LP, or linear-programming model): forecast +
                  target stock − opening stock, less any cut made to fit the supplier allocation. The line under it is
                  the rough case count; the LP doesn&apos;t round to whole cases.
                </InfoTip>
              </th>
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
                <td colSpan={COLUMN_COUNT}>
                  {principal === 'delmonte'
                    ? 'The LP does not plan Del Monte: it has no SKU-level sales to forecast, so there are no reorder recommendations for it.'
                    : meta?.cycleDate
                      ? 'No pending recommendations for this planning cycle.'
                      : 'No LP run has produced pending recommendations for this scope yet.'}
                </td>
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
          {/* What decides a cut, as analytics/optimization/lp.py solves it
              (2026-10-01): the target comes first and the weights only act
              when the allocation is short — after SSM's 3-week rule, which
              counts the planned SKUs' stock, not the whole warehouse. With
              one flat storage cost for every SKU the storage term is the
              same whoever is cut, so it can't decide anything; this used to
              credit it with a say. */}
          <p className="reorder-page-subtitle">
            Order quantities, in pieces, suggested by the optimizer (an LP, or linear-programming model) for the Class A
            SKUs whose forecasts beat a simple last-month guess (MASE &lt; 1).
            The LP orders each SKU up to its target stock, net of what is on hand. Only when the supplier allocation
            can&apos;t cover every SKU does it cut some orders, and then
            {lpInputs.cover_rule === 'per-sku'
              ? <> the LP&apos;s cost and service weights decide which SKUs come up short.</>
              : <>
                  {' '}SSM&apos;s {lpInputs.target_weeks ?? 3}-week stock rule (counted over the SKUs in this plan, not the
                  whole warehouse) and the LP&apos;s cost and service weights decide which SKUs come up short.
                </>}
            {lpInputs.storage_cost_per_unit != null && (
              <>
                {' '}The storage weight has no say for now: the placeholder storage cost is the same
                {' '}₱{Number(lpInputs.storage_cost_per_unit).toFixed(2)} a piece for every SKU.
              </>
            )}
            {notCategoryACount > 0 && (
              <>
                {' '}{notCategoryACount.toLocaleString()} of this cycle&apos;s {cycleRows.length.toLocaleString()} rows
                {' '}are no longer Class A in the latest ABC run.
              </>
            )}
            {' '}Each planning cycle is one optimization run, for the month after the latest sales data.
            {meta?.supersededCount > 0 && (
              <>
                {' '}Showing the current cycle only — {meta.supersededCount.toLocaleString()} undecided
                {' '}row{meta.supersededCount === 1 ? '' : 's'} from earlier runs {meta.supersededCount === 1 ? 'is' : 'are'} superseded and not listed.
              </>
            )}
          </p>
          {/* Same freshness notice as the Dashboard's, for the page where
              the affected numbers (q_i, rop_i) are actually acted on.
              Restored 2026-09-29 with the Dashboard's (see Dashboard.jsx). */}
          {meta?.freshness?.is_stale && (
            <div className="dash-stale-note" role="status">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                <strong>
                  {meta.freshness.stale_row_count < meta.freshness.row_count ? 'Some of these quantities are' : 'These quantities are'}
                  {' '}from an older LP run.
                </strong> {meta.freshness.reason}
              </span>
            </div>
          )}
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
        lpModel={meta?.lpModel}
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
          closeOnOverlayClick={!acceptSave.saving}
          closeOnEscape={!acceptSave.saving}
        >
          {acceptSave.result ? (
            <SaveResult
              ok={acceptSave.result.ok}
              title={acceptSave.result.ok ? 'Reorder accepted' : "Couldn't accept the reorder"}
              message={acceptSave.result.ok
                ? <><strong>{formatUnits(pendingAccept.orderQty)}</strong> pieces of <strong>{formatSKU(pendingAccept.sku)}</strong> are in the decision log.</>
                : acceptSave.result.message}
            />
          ) : (
            <>
              <div className="reorder-accept-icon">
                <CheckCircle2 size={20} />
              </div>
              <h3 className="reorder-accept-title">Accept this reorder?</h3>
              <p className="reorder-accept-body">
                Order <strong>{formatUnits(pendingAccept.orderQty)}</strong> pieces
                {pendingAccept.cases?.order ? ` (${pendingAccept.cases.order})` : ''} of{' '}
                <strong>{formatSKU(pendingAccept.sku)}</strong>
                {pendingAccept.product ? ` — ${pendingAccept.product}` : ''}, as recommended by the LP optimizer.
              </p>
              {acceptError && <p className="reorder-accept-error" role="alert">{acceptError}</p>}
              <div className="reorder-accept-actions">
                <button className="reorder-accept-cancel" onClick={() => setPendingAccept(null)} disabled={acceptSave.saving}>
                  Cancel
                </button>
                <button className="reorder-accept-confirm" onClick={handleConfirmAccept} disabled={acceptSave.saving}>
                  {acceptSave.saving ? 'Accepting…' : 'Accept Reorder'}
                </button>
              </div>
            </>
          )}
        </Modal>
      )}

      {pendingBulk && (
        <Modal
          isOpen={Boolean(pendingBulk)}
          onClose={() => setPendingBulk(null)}
          label="Confirm bulk acceptance"
          overlayClassName="reorder-accept-overlay"
          containerClassName="reorder-accept-card"
          closeOnOverlayClick={!bulkSave.saving}
          closeOnEscape={!bulkSave.saving}
        >
          {bulkSave.result ? (
            <SaveResult
              ok={bulkSave.result.ok}
              title={bulkSave.result.ok ? 'Reorders accepted' : 'Some reorders failed'}
              message={bulkSave.result.ok
                ? `${bulkSave.result.value} reorder${bulkSave.result.value === 1 ? '' : 's'} accepted for the ${formatMonth(selectedCycle)} cycle.`
                : bulkSave.result.message}
            />
          ) : (
            <>
              <div className="reorder-accept-icon">
                <CheckCheck size={20} />
              </div>
              <h3 className="reorder-accept-title">Accept all {pendingBulk.rows.length} in view?</h3>
              <p className="reorder-accept-body">
                This accepts every pending recommendation currently shown
                {showReviewLater ? ' (Act now and Review later)' : ' in the Act-now list'} for the{' '}
                <strong>{formatMonth(selectedCycle)}</strong> cycle — <strong>{bulkQty.toLocaleString()}</strong> pieces
                across <strong>{pendingBulk.rows.length}</strong> SKUs, at the LP-recommended quantities. Each one is
                logged individually.
              </p>
              <div className="reorder-accept-actions">
                <button className="reorder-accept-cancel" onClick={() => setPendingBulk(null)} disabled={bulkSave.saving}>
                  Cancel
                </button>
                <button className="reorder-accept-confirm" onClick={handleConfirmBulk} disabled={bulkSave.saving}>
                  {bulkSave.saving
                    ? `Accepting… ${bulkDone} of ${pendingBulk.rows.length}`
                    : `Accept ${pendingBulk.rows.length} reorders`}
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
    </div>
  );
};

export default ReorderRecommendations;
