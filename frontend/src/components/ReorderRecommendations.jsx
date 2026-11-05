import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import SectionLede from './ui/SectionLede';
import { useNavigate, useOutletContext, useSearchParams } from 'react-router-dom';
import { isPreviewMode } from '../dataMode';
import {
  Loader2, Boxes, ClipboardCheck, ClipboardList, ListChecks, CheckCircle2, Calendar, CalendarClock, ChevronDown, ChevronRight, CheckCheck, AlertTriangle, Clock, Layers, Package,
  MoreHorizontal, PackageSearch, ShoppingCart, Target, Users,
} from 'lucide-react';
import ReorderActionMenu from './ReorderActionMenu';
import ReorderNotPlanned from './ReorderNotPlanned';
import ReorderReviewDrawer from './ReorderReviewDrawer';
import ReorderTableControls from './ReorderTableControls';
import InfoTip from './InfoTip';
import KPICard from './KPICard';
import PageHeader from './ui/PageHeader';
import ProductName from './ProductName';
import OverrideReasonModal from './OverrideReasonModal';
import Modal from './Modal';
import SaveResult from './SaveResult';
import { useToast } from './ToastProvider';
import { useSaveResult } from '../utils/useSaveResult';
import { getCurrentUser } from '../auth';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import {
  getRecommendations, decideRecommendation, getOpenRequests, getDirectApplyStatus, requestQuantityChange, requestDismissal,
} from '../api/recommendations';
import { HistoryModal, QuantityChangeModal, StaffRequestsTab } from './ReorderRequests';
import { useStaffRequests } from '../utils/useStaffRequests';
import { sameQuantity } from '../utils/reorderRequests';
import { formatDate, formatDateTime, formatMonth } from '../utils/formatDate';
import { labelForPrincipal } from '../principals';
import { decisionCounts, decisionLine, planStateLine } from '../decisionCounts';
import { DemoOrderPlanCard } from './DemoOrderPlan';
import { formatCoverDays, formatUnits, wholeUnits } from '../utils/formatNumber';
import { useBrandLookup } from '../utils/useBrandLookup';
import { LoadingStatus, SkeletonLine, SkeletonStatCards, SkeletonTable } from './Skeleton';
import LoadError, { describeLoadError } from './ui/LoadError';
import SlowLoadNotice from './ui/SlowLoadNotice';
// The cycle selector reuses DateFilter's control styles without the component.
import './DateFilter.css';
// .dash-stale-note — the LP freshness notice, defined once with the
// Dashboard's styles and reused here so both pages warn identically.
import './Dashboard.css';
import TierBasisLabel, { TierChip } from './TierBasisLabel';
import { REVIEW_REASON_TEXT } from '../utils/reviewReasons';
import { compareCycles, previousRunCycleDate, previousWindow, runCycles } from '../utils/cycleComparison';
import { calendarSignoffText } from '../utils/calendarAdjustment';
import {
  COVER_BASIS_NOTE, MONTH_TOTAL_NOTE, NO_SALES_FORECAST_NOTE, awaitsDecision, bulkSummary, casesCell, casesNote, filterRows,
  forecastsNoSales, formatUpdatedAgo, isBelowTarget, isProjectedOpening, noOrderReason, ordersNothing, paramsWithView, parseView,
  planOrderCounts, projectedLabel, projectedNote, provisionalDetail, revenueShareBasis, rowActions, splitBulkRows, tableTier,
  viewCounts,
} from '../utils/reorderView';
import './ReorderRecommendations.css';
import { URGENCY_HOVER, getUrgencyBadge, urgencyWord } from '../utils/urgency';

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
// Every row below its target stock is "Act now" (utils/reorderView.js
// isBelowTarget); everything else is collapsed under "Review later". Until
// 2026-11-03 Act now was a fixed top 20 with no recorded basis, which left a
// Critical product collapsed at rank 21. Rows the backend could not rank (no
// revenue share, or no stock figure in pieces) sort to the bottom and are marked unranked — never
// ranked as if their score were zero. A SKU missing from the opening stock
// count is NOT one of them since 2026-10-01: the LP plans it as 0 on hand,
// so the API does too (stock_not_in_count) and it is ranked like the rest.
const URGENCY_RANK = { CRITICAL: 0, URGENT: 1, PLANNED: 2, 'NO DATA': 3 };

// Fire at most this many PATCHes at once during a bulk accept — there is
// no bulk endpoint, so this is N sequential-ish writes against Supabase.
const BULK_CONCURRENCY = 5;


// Accept needs no typed reason; this is the one recorded for it.
const ACCEPT_REASON = 'Accepted the order plan\u2019s quantity as-is.';

// The views the table can filter to (utils/reorderView.js). The three urgencies
// a link can ask for (?urgency=critical) keep the dashboard's own words for each
// (backend/stock_status.py's rule).
const VIEW_LABEL = {
  critical: { title: 'Critical', what: 'below safety stock' },
  urgent: { title: 'Urgent', what: 'below target stock' },
  planned: { title: 'Planned', what: 'at or above target stock' },
  review: { title: 'Needs review', what: 'flagged to review before ordering' },
  not_in_count: { title: 'Not in stock count', what: 'missing from the opening stock count' },
};

// What a wider column needs of the table's width, in pixels: On order when a row
// carries it, and the action column when it holds Review order or Review request.
const ON_ORDER_COLUMN_WIDTH = 70;
const WIDE_ACTION_WIDTH = 75;

// Every quantity on this page is in PIECES — the LP's unit (q_i, rop_i,
// ss_i and the forecast all come from the pieces demand series) — while SSM
// buys in cases. formatNumber.js's exactUnits says "units", so the exact
// figure in this page's tooltips is spelled out here instead.
const exactPieces = (value) => {
  if (value == null || Number.isNaN(Number(value))) return undefined;
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} pieces (exact)`;
};

// Tooltip for a quantity cell: the exact pieces, then the case count
// (utils/reorderView.js casesNote).
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
  // Worked out from a projection, so the stock a row can show isn't what this came from.
  if (item.openingProjected) {
    const exact = piecesTitle(item.orderQty, item.packSize);
    return `${exact ? `${exact}. ` : ''}Worked out from projected opening stock, not a count.`;
  }
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

// The stale-plan notice in plain words, from GET /recommendations'
// freshness counts and timestamps only (2026-10-22).
const staleText = (f) => {
  const fc = f.forecast_generated_at ? ` on ${formatDateTime(f.forecast_generated_at)}` : '';
  if (f.stale_row_count != null && f.row_count != null && f.stale_row_count < f.row_count) {
    return `${f.stale_row_count.toLocaleString()} of the ${f.row_count.toLocaleString()} products in this plan were `
      + `worked out before the forecasts were updated${fc}, so their order quantity and target stock come from `
      + 'forecasts that have since changed. Check those before ordering.';
  }
  const lp = f.lp_generated_at ? `, last run ${formatDateTime(f.lp_generated_at)},` : '';
  return `The order plan${lp} was worked out before the forecasts were updated${fc}, so its order quantities and `
    + 'target stock come from forecasts that have since changed. A new run of the order plan clears this.';
};

// ── Changes since the previous plan (2026-10-24) ─────────────────────────
// The current cycle's plan rows (every status: a decided row is still the
// plan, backend/lp_cycle.PLAN_STATUSES) against the newest earlier cycle
// GET /recommendations still holds (cycle=all, from/to = the 12 months
// before). Compared by product code with the plan total's quantity
// (plan_q_i, else q_i); the maths is utils/cycleComparison.js. Read only,
// and the same endpoint (lp.view) the page already reads.
// 2026-10-26: only an earlier cycle a stored plan run produced counts
// (lp_model.run; previousRunCycleDate). Live, 2025-03..2026-02 hold 2-15
// leftover rows each from the retired planner and no run, so comparing with
// them read as "108 new · 14 no longer in it". None with a run: a plain line.
const COMPARE_PREVIEW = 5; // rows per list before "See all"
const COMPARE_WINDOW_MONTHS = 12;

const pieces = (n) => `${n == null ? '—' : n.toLocaleString()} pieces`;
const signed = (n) => (n > 0 ? `+${n.toLocaleString()}` : `−${Math.abs(n).toLocaleString()}`);

function CycleChangeList({ title, rows, render, emptyText }) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? rows : rows.slice(0, COMPARE_PREVIEW);
  return (
    <div className="reorder-compare-group">
      <h3 className="reorder-compare-group-title">
        {title} <span className="reorder-compare-count">{rows.length.toLocaleString()}</span>
      </h3>
      {rows.length === 0 ? (
        <p className="reorder-compare-empty">{emptyText}</p>
      ) : (
        <ul className="reorder-compare-list">
          {shown.map((r) => (
            <li key={r.key}>
              <span className="reorder-compare-product">
                {r.product || 'Unknown Product'}
                <span className="reorder-compare-code">{formatSKU(r.sku)}</span>
              </span>
              <span className="reorder-compare-qty">{render(r)}</span>
            </li>
          ))}
        </ul>
      )}
      {rows.length > COMPARE_PREVIEW && (
        <button type="button" className="link-button" onClick={() => setShowAll((v) => !v)} aria-expanded={showAll}>
          {showAll ? 'Show fewer' : `See all ${rows.length.toLocaleString()}`}
        </button>
      )}
    </div>
  );
}

function CycleComparison({ principal, dataMode }) {
  const [state, setState] = useState({ status: 'loading' });
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // The parent remounts this per principal and data mode (its key), so a
    // response for an earlier scope is dropped by `cancelled`, never shown.
    let cancelled = false;
    setState({ status: 'loading' });
    (async () => {
      const current = await getRecommendations({ principal, cycle: 'current' });
      if (cancelled) return;
      const cycle = current.planning_cycle_date ? String(current.planning_cycle_date).slice(0, 10) : null;
      if (!cycle) {
        setState({ status: 'no-plan' });
        return;
      }
      // A what-if preview was never saved: there is no earlier saved plan of it to compare with.
      if (current.data_mode?.outputs) {
        setState({ status: 'what-if' });
        return;
      }
      const span = previousWindow(cycle, COMPARE_WINDOW_MONTHS);
      if (!span) throw new Error(`Unreadable planning cycle date: ${cycle}`);
      const earlier = await getRecommendations({ principal, cycle: 'all', from: span.from, to: span.to });
      if (cancelled) return;
      const currentRows = (current.items || []).filter((it) => String(it.planning_cycle_date).slice(0, 10) === cycle);
      const previousCycle = previousRunCycleDate(earlier.items, cycle, runCycles(current, earlier));
      if (!previousCycle) {
        setState({ status: 'no-previous', cycle });
        return;
      }
      const previousRows = (earlier.items || []).filter((it) => String(it.planning_cycle_date).slice(0, 10) === previousCycle);
      setState({ status: 'ready', cycle, previousCycle, diff: compareCycles(currentRows, previousRows) });
    })().catch((err) => {
      if (!cancelled) setState({ status: 'error', message: describeLoadError(err) });
    });
    return () => {
      cancelled = true;
    };
  }, [principal, dataMode, attempt]);

  if (state.status === 'no-plan') return null; // the table already says there is no plan

  const heading = 'Changes since the previous plan';
  let summary;
  if (state.status === 'loading') {
    summary = <span className="reorder-compare-muted"><Loader2 className="spinner-icon" size={14} aria-hidden="true" /> Checking the previous plan…</span>;
  } else if (state.status === 'error') {
    summary = (
      <span className="reorder-compare-muted">
        Couldn&apos;t load the previous plan to compare with.{' '}
        <button type="button" className="link-button" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
      </span>
    );
  } else if (state.status === 'what-if') {
    summary = <span className="reorder-compare-muted">Not compared in preview: these what-if rows were never saved, so there is no earlier saved plan of them.</span>;
  } else if (state.status === 'no-previous') {
    summary = (
      <span className="reorder-compare-muted">
        No earlier plan from the current planning method to compare with yet. Current plan:{' '}
        {formatMonth(state.cycle)}.
      </span>
    );
  }

  if (state.status !== 'ready') {
    return (
      <section className="reorder-compare" aria-label={heading} aria-live="polite">
        <span className="reorder-how-title">{heading}</span>
        <p className="reorder-compare-summary">{summary}</p>
      </section>
    );
  }

  const { diff, cycle, previousCycle } = state;
  const cur = formatMonth(cycle);
  const prev = formatMonth(previousCycle);
  const n = (v) => v.toLocaleString();
  const panelId = 'reorder-compare-panel';
  return (
    <section className="reorder-compare" aria-label={heading}>
      <button
        type="button"
        className="reorder-compare-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
      >
        {open ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
        <span className="reorder-how-title">{heading}</span>
        <span className="reorder-compare-period">{cur} plan compared with {prev}</span>
      </button>
      <p className="reorder-compare-summary">
        <strong>{n(diff.added.length)}</strong> new in the plan · <strong>{n(diff.removed.length)}</strong> no longer
        in it · <strong>{n(diff.increased.length)}</strong> ordering more · <strong>{n(diff.decreased.length)}</strong>{' '}
        ordering less · {n(diff.unchanged)} unchanged
        {diff.unknownQuantity > 0 && <> · {n(diff.unknownQuantity)} with no quantity recorded</>}
      </p>
      {open && (
        <div id={panelId}>
          <div className="reorder-compare-grid">
            <CycleChangeList
              title={`New in the ${cur} plan`}
              rows={diff.added}
              emptyText={`None: every product in the ${cur} plan was also in ${prev}.`}
              render={(r) => pieces(r.quantity)}
            />
            <CycleChangeList
              title={`In ${prev}, no longer in the plan`}
              rows={diff.removed}
              emptyText={`None: every product in ${prev} is still in the plan.`}
              render={(r) => `${pieces(r.quantity)} in ${prev}`}
            />
            <CycleChangeList
              title="Ordering more"
              rows={diff.increased}
              emptyText="None."
              render={(r) => `${n(r.before)} → ${pieces(r.after)} (${signed(r.change)})`}
            />
            <CycleChangeList
              title="Ordering less"
              rows={diff.decreased}
              emptyText="None."
              render={(r) => `${n(r.before)} → ${pieces(r.after)} (${signed(r.change)})`}
            />
          </div>
          <p className="reorder-table-note reorder-compare-note">
            Matched by product code. Each quantity is the plan&apos;s suggested order in pieces, or the quantity a planner
            accepted instead where one did. {n(diff.previousCount)} product
            {diff.previousCount === 1 ? ' is' : 's are'} stored for {prev} and {n(diff.currentCount)} for {cur}. An earlier
            month&apos;s rows are kept as they were saved and are never worked out again, so they may come from an earlier
            version of the order plan: a large difference in the number of products can mean that rather than a change in
            demand.
            {diff.unmatched > 0 && <> {n(diff.unmatched)} product{diff.unmatched === 1 ? '' : 's'} could not be matched (no product code, or the code listed twice in one month) and {diff.unmatched === 1 ? 'is' : 'are'} left out.</>}
          </p>
        </div>
      )}
    </section>
  );
}

// The planning panel's Last Update: when this page last read the plan, ticking
// by itself so the whole table doesn't re-render every 30 seconds.
function LastUpdate({ fetchedAt }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(id);
  }, [fetchedAt]);
  return <>{formatUpdatedAgo(fetchedAt, now)}</>;
}

const ReorderRecommendations = () => {
  // Shared principal scope (Topbar's segmented control). lp_recommendation
  // has no Del Monte rows yet, so 'delmonte' renders this page's normal
  // empty state rather than an error.
  const { principal, dataMode } = useOutletContext() || {};
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
  // Try again on a failed load re-runs the request below.
  const [attempt, setAttempt] = useState(0);
  // Which LP cycle this list is, how many undecided rows from earlier runs
  // were withheld, and whether the run predates its own forecasts
  // (backend/lp_cycle.py). The list is the CURRENT cycle only — a leftover
  // 2023 row is not something to act on today — so the page has to say
  // that rather than quietly showing fewer rows than the database holds.
  const [meta, setMeta] = useState(null);
  const [loadedAt, setLoadedAt] = useState(null); // when this page last read the plan
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
  const { role, hasPermission } = usePermissions();
  const canDecide = hasPermission(P.LP_DECIDE);
  // Staff requests (2026-10-28, ReorderRequests.jsx): lp.propose asks for a
  // different quantity or a dismissal, held for an admin. An admin (role, on
  // top of every key) applies a quantity change at once and approves or
  // rejects the requests. lp.decide or lp.propose opens the requests list and
  // a row's history (the endpoints' own permission).
  const isAdmin = role === 'admin';
  const canPropose = hasPermission(P.LP_PROPOSE);
  const canSeeRequests = canDecide || canPropose;
  // The review drawer links to the product's own page (SKU Forecast).
  const navigate = useNavigate();
  const canOpenForecast = hasPermission(P.FORECAST_VIEW);
  // The Dashboard's idle-stock card (#idle-stock): what to do with stock
  // that stopped selling, one click from the order plan (Technical Adviser,
  // 2 Oct 2026; 2026-10-22).
  const canOpenDashboard = hasPermission(P.DASHBOARD_VIEW);
  const [decisionLog, setDecisionLog] = useState([]);

  // Requests waiting for an admin, by recommendation_key, for EVERY viewer
  // (GET /recommendations/open-requests, lp.view): the row shows "Pending
  // approval" or "Dismissal requested" instead of buttons that the server
  // would refuse (409) while one is open. `ready` is false until the server
  // has dismissal requests and stock counts (migration 0070). A failed read
  // leaves the table as it was before this existed: no badges.
  const [openRequests, setOpenRequests] = useState({ ready: false, byKey: new Map() });
  const [openAttempt, setOpenAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    getOpenRequests()
      .then((res) => {
        if (cancelled) return;
        setOpenRequests({
          ready: Boolean(res.ready),
          byKey: new Map((res.items || []).map((r) => [r.recommendation_key, r])),
        });
      })
      .catch(() => {
        if (!cancelled) setOpenRequests({ ready: false, byKey: new Map() });
      });
    return () => { cancelled = true; };
  }, [principal, attempt, dataMode, openAttempt]);

  // Whether this user's quantity change applies at once or waits for an
  // admin, to word the button (GET /recommendations/direct-apply-grants/me).
  // approval_ready false: the server can't hold a change yet, so no button.
  const [directApply, setDirectApply] = useState(null);
  useEffect(() => {
    if (!canSeeRequests) return undefined;
    let cancelled = false;
    getDirectApplyStatus()
      .then((res) => { if (!cancelled) setDirectApply(res); })
      .catch(() => { if (!cancelled) setDirectApply({ can_apply_directly: false, approval_ready: false }); });
    return () => { cancelled = true; };
  }, [canSeeRequests]);
  const approvalReady = directApply?.approval_ready === true;
  // A row's history is migration 0070's endpoint, like open-requests' `ready`.
  const canSeeHistory = canSeeRequests && openRequests.ready;
  const appliesDirectly = isAdmin || directApply?.can_apply_directly === true;

  // The Requests tab's list, loaded with the page (every state, once) so the
  // tab's badge counts what is waiting whatever the tab's filter shows. The
  // filter is kept here so it survives a tab switch; null = the default
  // (an admin starts on Pending, staff on All).
  const [requestsFilter, setRequestsFilter] = useState(null);
  const requestsView = requestsFilter ?? (isAdmin ? 'pending_approval' : 'all');
  const staffRequests = useStaffRequests({ enabled: canSeeRequests, isAdmin });

  // Deep link from the notification bell: /reorder?tab=requests&request=quantity_change-7
  // (or dismissal-4) opens the Requests tab, and the tab opens that request
  // once its list has loaded, then drops both params so a refresh or Back
  // doesn't open it again. Someone who can't see requests just lands on the page.
  const tabParam = searchParams.get('tab');
  const requestParam = searchParams.get('request');
  useEffect(() => {
    if (tabParam !== 'requests' && !requestParam) return;
    if (canSeeRequests) setActiveTab('REQUESTS');
    if (!canSeeRequests || !requestParam) {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete('tab');
        next.delete('request');
        return next;
      }, { replace: true });
    }
  }, [tabParam, requestParam, canSeeRequests, setSearchParams]);
  const clearRequestLink = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('tab');
      next.delete('request');
      return next;
    }, { replace: true });
  }, [setSearchParams]);
  const reloadStaffRequests = staffRequests.reload;
  const refreshRequests = () => {
    setOpenAttempt((n) => n + 1);
    reloadStaffRequests();
  };

  const [pendingQtyChange, setPendingQtyChange] = useState(null); // the row whose quantity is being changed
  const [pendingDismissRequest, setPendingDismissRequest] = useState(null); // the row a dismissal is asked for
  const [historyFor, setHistoryFor] = useState(null); // { id, product, sku, packSize }

  // What is outstanding on the current plan. The table below holds pending rows only, so this reads the plan
  // itself (the request CycleComparison makes too), and again after any decision lands.
  const [decisions, setDecisions] = useState(null);
  const [decisionsVersion, setDecisionsVersion] = useState(0);
  const decisionLanded = useCallback(() => setDecisionsVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    getRecommendations({ principal, cycle: 'current' })
      .then((res) => {
        if (!cancelled) {
          setDecisions({
            status: 'ok',
            cycle: res.planning_cycle_date || null,
            whatIf: Boolean(res.data_mode?.outputs),
            counts: decisionCounts(res.items || []),
            planState: res.plan_state || null,
          });
        }
      })
      .catch(() => { if (!cancelled) setDecisions({ status: 'error' }); });
    return () => { cancelled = true; };
  }, [principal, attempt, dataMode, decisionsVersion]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    // The whole plan, decided rows too: a decision doesn't take a row out of the
    // plan (backend/lp_cycle.PLAN_STATUSES). Asking for pending rows only dropped
    // decided rows on a reload, so the total fell below the Dashboard's, Act Now
    // refilled from lower ranks and nothing showed what had been decided.
    getRecommendations({ principal })
      .then((res) => {
        if (cancelled) return;
        setLoadedAt(Date.now());
        // The stock count each row was checked against — the one that opens
        // its cycle — attached here so the row can say when it was counted.
        const counts = new Map((res.stock_counts || []).map((c) => [`${c.cycle}|${c.principal}`, c]));
        setRawItems((res.items || []).map((it) => ({
          ...it, stock_count: counts.get(`${it.planning_cycle_date}|${it.principal}`) || null,
        })));
        setMeta({
          cycleDate: res.planning_cycle_date || null,
          tierAPeriods: res.tier_a_periods || {},
          // The Class A products this plan has no row for: read-only, listed below the table.
          notPlanned: res.not_planned || null,
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
          // The periods the figures were read at (GET /recommendations'
          // label_context), for the period on every header and card.
          stockPeriod: res.stock_period || null,
          stockCountDate: res.stock_count_date || null,
          stockCountNote: res.stock_count_note || null,
          abcPeriod: res.abc_period || null,
          coverSalesStart: res.cover_sales_start || null,
          coverSalesEnd: res.cover_sales_end || null,
          // Del Monte with the server's demonstration switch on: why the
          // synthetic data has no order plan either (GET /recommendations).
          demoOrderPlan: res.demonstration ? res.order_plan || null : null,
          // Unilever with the switch on: the synthetic order plan (demo forecast, real stock) the server adds
          // BESIDE the real items (GET /recommendations `demo_unilever`). Listed apart, never merged.
          demoUnileverPlan: res.demo_unilever || null,
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(describeLoadError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [principal, attempt, dataMode]);

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
        principal: item.principal, // for the request dialog's header
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
        openingProjected: isProjectedOpening(item.stock_count),
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
        // What the row adds to the plan total: the accepted quantity if the planner changed it, else q_i.
        planQty: item.plan_q_i ?? item.q_i,
        safetyStock: item.ss_i,
        urgency: item.urgency,
        planningCycleDate: item.planning_cycle_date,
        revenueShare: item.revenue_share,
        tier: item.tier, // last-known tier at or before the cycle month; carried forward when tierIsCurrent is false
        tierPeriod: item.tier_period,
        tierIsCurrent: item.tier_is_current,
        priorityScore: item.priority_score,
        stockoutGap: item.stockout_gap,
        daysOfCover: item.days_of_cover,
        coverReason: item.cover_blocked_reason,
        // The cycle month's forecast and any cut made to fit the allocation
        // (GET /recommendations): LP qty = forecast + target - stock - short.
        forecast: item.forecast_units,
        shortUnits: item.short_units,
        // Review before ordering (review_flag): a likely large miss, never
        // accepted in bulk; the server needs reviewed=true to accept it.
        needsReview: item.needs_review === true,
        reviewReasons: item.review_reasons || [],
        // The badge's hover text (PendingCards ReviewBadge): the reasons in a planner's words.
        reviewFlag: item.needs_review === true
          ? `Flagged for review: ${(item.review_reasons || []).map((r) => REVIEW_REASON_TEXT[r] || r).join('; ') || 'likely large miss'}.`
          : null,
        // Pieces on order from the opening count's PO Qty: information only,
        // never subtracted from the order (DEC-34; on_order_note says so).
        onOrderQty: item.on_order ?? null,
        onOrderNote: item.on_order_note || item.on_order_blocked_reason || null,
        actionStatus: item.status === 'pending' ? null : item.status.toUpperCase(),
        loadingAction: null,
      })),
    [rawItems]
  );
  const [localData, setLocalData] = useState([]);
  useEffect(() => setLocalData(data), [data]);

  // Distinct planning cycles, newest first, with how many rows still wait for a decision.
  const cycles = useMemo(() => {
    const counts = new Map();
    localData.forEach((item) => {
      if (!item.planningCycleDate) return;
      counts.set(item.planningCycleDate, (counts.get(item.planningCycleDate) || 0) + (awaitsDecision(item) ? 1 : 0));
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

  // ?urgency=critical (the dashboard's "Review the N critical", 2026-10-19), or
  // ?view=review / ?view=not_in_count: only that view, every row of it in one
  // list. The search narrows whatever view is on, over the rows already loaded.
  // Neither touches the figures on the cards above the table, or the row's rank.
  const view = parseView(searchParams);
  const setView = (next) => setSearchParams((prev) => paramsWithView(prev, next), { replace: true });
  const [searchQuery, setSearchQuery] = useState('');
  const clearFilters = () => {
    setSearchQuery('');
    setView('all');
  };
  const searching = searchQuery.trim() !== '';
  const filtered = view !== 'all' || searching;
  const brandOf = useCallback((row) => brandLookup?.get(String(row.sku)) ?? null, [brandLookup]);
  const viewTotals = useMemo(() => viewCounts(rankedRows), [rankedRows]);
  const filteredRows = useMemo(
    () => (filtered ? filterRows(rankedRows, { view, query: searchQuery, brandOf }) : null),
    [filtered, rankedRows, view, searchQuery, brandOf]
  );
  const topRows = rankedRows.filter(isBelowTarget);
  const laterRows = rankedRows.filter((r) => !isBelowTarget(r));
  const actNowRows = filteredRows ?? topRows;
  const reviewLaterRows = filteredRows ? [] : laterRows;
  const visibleRows = filteredRows ?? (showReviewLater ? rankedRows : actNowRows);
  // "18 SKUs below safety stock", said over the list and beside the Show all link.
  const listedText = (() => {
    const n = visibleRows.length;
    const skus = `${n.toLocaleString()} ${n === 1 ? 'SKU' : 'SKUs'}`;
    const what = VIEW_LABEL[view]?.what;
    return `${skus}${what ? ` ${what}` : ''}${searching ? ` matching “${searchQuery.trim()}”` : ''}`;
  })();
  // Which columns fit, from the width the table really has (the sidebar's state
  // counts). Whatever a tier leaves out is in the row's detail window.
  const [tableArea, setTableArea] = useState(null);
  const [tableWidth, setTableWidth] = useState(Infinity);
  useEffect(() => {
    if (!tableArea || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => setTableWidth(entry.contentRect.width));
    observer.observe(tableArea);
    return () => observer.disconnect();
  }, [tableArea]);
  // What "Accept all in view" would submit, and what it leaves out and why:
  // rows flagged for review (each is accepted from its own row) and rows with a
  // staff request open (the server refuses to decide them until an admin settles
  // the request). The dialog keeps this list and submits it as it is.
  const bulkSplit = splitBulkRows(visibleRows, (r) => openRequests.byKey.has(r.id));
  const bulkTargets = bulkSplit.eligible;

  // Deep link from the Dashboard's reorder widget (?sku=...): switch to the
  // most recent cycle holding that SKU, then open its review drawer — the
  // same drawer a click on the table's product name opens. deepLinkHandled stops
  // it reopening if it's closed while ?sku= is still in the URL.
  //
  // Waits for the load to finish, not for a non-empty list (FE-9,
  // 2026-10-22): an empty plan used to return early and the link landed
  // with no message. Matched against `data`, not localData: localData is
  // copied from it in an effect, so it is still [] on the first render after
  // loading ends and would read as "not in the plan". A failed load says
  // nothing here; the page's own error is shown instead.
  const deepLinkHandled = useRef(false);
  // What opened the review drawer, to hand focus back to once it finally closes.
  const drawerTrigger = useRef(null);
  useEffect(() => {
    const targetSku = searchParams.get('sku');
    if (!targetSku || deepLinkHandled.current || loading || error) return;
    const match = data
      .filter((item) => String(item.sku) === targetSku)
      .sort((a, b) => (a.planningCycleDate < b.planningCycleDate ? 1 : -1))[0];
    deepLinkHandled.current = true;
    if (match) {
      setSelectedCycle(match.planningCycleDate);
      setShowReviewLater(true); // the linked SKU may sit under Review later
      // handleOpenDetails' two setters, inline so the effect doesn't depend
      // on a function re-created every render. No trigger to hand focus back to.
      drawerTrigger.current = null;
      setSelectedItem(match);
      setIsModalOpen(true);
    } else {
      // Linked from a product's own page (SKU Forecast, SKU Management) for a
      // product the plan does not cover: say so, rather than land on the
      // list with nothing opened.
      toast.info(`${targetSku} has no order recommendation in the plans listed here.`, 8000);
    }
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('sku');
      return next;
    }, { replace: true });
    // toast is useToast()'s memoised api (ToastProvider.jsx), stable across renders.
  }, [loading, error, data, searchParams, setSearchParams, toast]);

  const actNowPending = topRows.filter(awaitsDecision).length;
  // Rows the backend could not rank (no stock figure or no revenue share)
  // have an UNKNOWN risk, not a lower one, so the card counts them apart.
  // Counted from the whole cycle, not the list on screen: until 2026-11-02 a
  // ?urgency= link emptied reviewLaterRows and the Review Later card read 0. Those
  // still awaiting a decision, as Act Now counts; a row that orders nothing has none to make.
  const reviewLaterTotal = laterRows.filter(awaitsDecision);
  const reviewLaterNoOrder = laterRows.filter(ordersNothing).length;
  const reviewLaterUnranked = reviewLaterTotal.filter((r) => r.priorityScore == null).length;
  // Missing from the opening stock count, so planned (and shown) as 0 on
  // hand — 3 of the 73 rows in the 2026-03 cycle, all cut by the LP. Kept
  // apart from rows with no stock figure at all (NO DATA: a stock row the
  // API can't put in pieces), which stay unranked.
  const notInCountCount = cycleRows.filter((r) => r.stockNotInCount).length;
  const noStockFigureCount = cycleRows.filter((r) => r.stock == null).length;
  // The LP plans Category A, but a cycle outlives the ABC run it was solved
  // against; GET /recommendations sends each row's tier in the latest run.
  // An aged tier (tierIsCurrent false) is display only: a carried-forward A is not Class A here.
  const notCategoryACount = cycleRows.filter((r) => r.tier !== 'A' || r.tierIsCurrent === false).length;
  // Summed in whole pieces, so the card equals the sum of the table's rows.
  const totalOrderQty = cycleRows.reduce((sum, item) => sum + (wholeUnits(item.planQty) || 0), 0);
  // Rows the allocation couldn't fully fund (short_units > 0) — the
  // allocation binds, so the total above is the allocation, not the need.
  const cutCount = cycleRows.filter((item) => item.shortUnits > 0).length;
  // Rows whose suggested order is 0 pieces: 36 of the 109 in the Mar 2026 plan.
  // "109 in the plan" reads as 109 orders without this. Over the whole plan, like
  // the total beside it.
  const { ordering: orderingCount, none: noOrderCount } = planOrderCounts(cycleRows);
  // The LP's own settings (backend/lp_cycle.lp_model_info), so the page's
  // account of how it cuts follows the run rather than a retyped copy.
  const lpInputs = meta?.lpModel?.inputs || {};
  // The solver's weights (lp_model.weights), for the compact "How this was
  // optimized" block above the table.
  const lpWeights = meta?.lpModel?.weights || null;
  const weightRows = lpWeights ? [
    ['Cost', lpWeights.cost],
    ['Service level', lpWeights.service_level],
    ['Storage', lpWeights.storage],
  ] : [];
  // "Opening stock: Unilever count of Feb 2026, counted Mar 2, 2026 (accepted
  // for planning, pending SSM confirmation …)" for the cycle on screen, or the
  // reason there is none ("no opening stock count for …").
  const openingCountNote = (meta?.stockCounts || [])
    .filter((c) => !selectedCycle || c.cycle === selectedCycle)
    .map((c) => {
      const who = labelForPrincipal(c.principal);
      if (isProjectedOpening(c)) return `${who}: ${projectedNote(c)}`;
      if (!c.available) return `${who}: ${c.reason}.`;
      const when = c.counted_on
        ? `counted ${formatDate(c.counted_on)}`
        : 'exact date not recorded';
      return `Opening stock: ${who} count of ${formatMonth(c.period)}, ${when}${c.flag ? ` (${c.flag})` : ''}.`;
    })
    .join(' ');
  const allocationPct = lpInputs.allocation_pct ?? null;
  // "On order (not yet arrived)": its column exists only once a row carries
  // the figure (purchase-order quantities are not loaded yet).
  const hasOnOrder = cycleRows.some((r) => r.onOrderQty != null);
  // Those columns take their width from the others, when they appear.
  const tier = tableTier(tableWidth
    - (hasOnOrder ? ON_ORDER_COLUMN_WIDTH : 0)
    - (!canDecide || openRequests.byKey.size > 0 ? WIDE_ACTION_WIDTH : 0));
  const wide = tier === 'full' || tier === 'compact';
  // The opening count's reviewed note for the cycle on screen ("accepted for
  // planning, pending SSM confirmation …"), for the stock column's header.
  const openingCountFlag = (meta?.stockCounts || [])
    .filter((c) => (!selectedCycle || c.cycle === selectedCycle) && c.available && c.flag)
    .map((c) => c.flag)[0] || null;
  // The plan's own facts, from the stored run (lp_model): which run, when it
  // was made, the allocation and service level it used, and the stock count
  // it opened from — so the page states what its numbers rest on.
  const lpRun = meta?.lpModel?.run || null;
  const runCounts = Object.values(meta?.lpModel?.stock_counts || {});
  const runIsThisCycle = Boolean(lpRun) && (!selectedCycle || lpRun.planning_cycle_date === selectedCycle);
  const planFacts = runIsThisCycle
    ? [
        `Plan run ${lpRun.run_key}`,
        lpRun.created_at ? `made ${formatDate(lpRun.created_at)}` : null,
        allocationPct != null ? `allocation ${allocationPct}%` : null,
        meta.lpModel.service_level_pct != null ? `service level ${meta.lpModel.service_level_pct}%` : null,
        ...runCounts.map((c) => {
          if (isProjectedOpening(c)) return `stock ${projectedLabel(c)}`;
          return c.counted_on ? `stock counted ${formatDate(c.counted_on)}` : null;
        }),
      ].filter(Boolean).join(' · ')
    : null;
  // Caveats the run recorded about its data (lp_model.inputs.notes), less
  // the opening-count note, which the line under the table already gives.
  const planNotes = lpRun
    ? (lpInputs.notes || []).filter((note) => !/stock count \d{4}-\d{2} \(counted/.test(note))
      .map((note) => note.charAt(0).toUpperCase() + note.slice(1))
    : [];

  // Every figure on this page says which period it belongs to (Sir
  // Catubag, 2 Oct 2026: a number without its period and unit can't be
  // checked). Four different periods meet in one row, which is why each
  // header carries its own rather than one date for the page:
  //   plan       — the LP cycle: forecast, target, safety stock, order
  //   count      — the stock count the stock column is from. Unilever's
  //                "2026-03" count was taken on 6 Apr 2026, so the day is
  //                named; calling it "Mar 2026 stock" hid how late it is
  //   abc        — the ABC run revenue share comes from; Unilever's covers the
  //                12 months ending then (utils/reorderView.js revenueShareBasis)
  //   coverSales — the sales months cover's daily rate averages
  const cycleMonth = selectedCycle ? formatMonth(selectedCycle) : null;
  const planLabel = cycleMonth ? `${cycleMonth} plan` : 'this plan';
  // A plan that started from a projection says so, wherever a count would be named.
  const projectedCount = (meta?.stockCounts || [])
    .find((c) => (!selectedCycle || c.cycle === selectedCycle) && isProjectedOpening(c)) || null;
  let countLabel = 'latest count';
  if (projectedCount) countLabel = projectedLabel(projectedCount);
  else if (meta?.stockCountDate) countLabel = `counted ${formatDate(meta.stockCountDate)}`;
  else if (meta?.stockPeriod) countLabel = `${formatMonth(meta.stockPeriod)} count${meta.stockCountNote ? ' (day not recorded)' : ''}`;
  const abcLabel = meta?.abcPeriod ? formatMonth(meta.abcPeriod) : null;
  const coverSalesLabel = meta?.coverSalesStart && meta?.coverSalesEnd
    ? `${formatMonth(meta.coverSalesStart)} – ${formatMonth(meta.coverSalesEnd)}`
    : null;
  const coverNote = `${COVER_BASIS_NOTE} Stock ${countLabel}${coverSalesLabel ? `; sales ${coverSalesLabel}` : ''}.`;

  const handleOpenDetails = (item) => {
    drawerTrigger.current = document.activeElement;
    setSelectedItem(item);
    setIsModalOpen(true);
  };
  const closeDrawer = () => {
    setIsModalOpen(false);
    const trigger = drawerTrigger.current;
    // After Modal's own cleanup, which only knows the dialog it came back from.
    if (trigger && document.contains(trigger)) requestAnimationFrame(() => trigger.focus?.());
  };

  // One overlay at a time. An action from the drawer closes it while its dialog
  // is up, and the drawer comes back after, showing the row as it now stands.
  const [drawerReturn, setDrawerReturn] = useState(false);
  const dialogOpen = Boolean(pendingAccept || pendingOverride || pendingDismissRequest || pendingQtyChange || historyFor);
  useEffect(() => {
    if (drawerReturn && !dialogOpen) {
      setDrawerReturn(false);
      setIsModalOpen(true);
    }
  }, [drawerReturn, dialogOpen]);

  // An admin's way from a row to its waiting request: the same address the
  // notification bell links to, so the tab opens that request.
  const reviewRequest = (item) => {
    const open = openRequests.byKey.get(item.id);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('tab', 'requests');
      if (open) next.set('request', `${open.kind}-${open.key}`);
      return next;
    }, { replace: true });
  };

  // What this user may do with a row, from the one rule the table and the drawer
  // share (utils/reorderView.js). The server checks every request regardless.
  const actionsFor = (item) => rowActions(item, {
    canDecide,
    canPropose,
    isAdmin,
    approvalReady,
    requestsReady: openRequests.ready,
    canSeeHistory,
    appliesDirectly,
    whatIf: Boolean(meta?.whatIf),
    openRequest: openRequests.byKey.get(item.id) || null,
    bulkRunning,
  });

  // Runs an action through the handler and dialog it has always had.
  const runRowAction = (id, item, { fromDrawer = false } = {}) => {
    if (fromDrawer) {
      setIsModalOpen(false);
      // A request opens on another tab, so there's no coming back to the drawer.
      setDrawerReturn(id !== 'review_request');
    }
    if (id === 'accept') handleAction(item, 'ACCEPTED');
    else if (id === 'dismiss') handleAction(item, 'DISMISSED');
    else if (id === 'quantity') setPendingQtyChange(item);
    else if (id === 'request_dismissal') setPendingDismissRequest(item);
    else if (id === 'history') openHistory(item);
    else if (id === 'review_order') handleOpenDetails(item);
    else if (id === 'review_request') reviewRequest(item);
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
        cycle: item.planningCycleDate,
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
  const applyAction = async (id, actionType, { silent = false, reason, rethrow = false, reviewed = false, stockObservation = null } = {}) => {
    setLocalData(prev => prev.map(item =>
      item.id === id ? { ...item, loadingAction: actionType } : item
    ));

    try {
      await decideRecommendation(id, actionType === 'ACCEPTED' ? 'accepted' : 'dismissed', reason, { reviewed, stockObservation });
      setLocalData(prev => prev.map(item =>
        item.id === id ? { ...item, loadingAction: null, actionStatus: actionType } : item
      ));
      decisionLanded();
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
      await applyAction(item.id, 'ACCEPTED', { reason: ACCEPT_REASON, silent: true, rethrow: true, reviewed: item.needsReview });
      logDecision(item, 'ACCEPTED', ACCEPT_REASON);
    }, {
      onSaved: () => setPendingAccept(null),
      onFailed: setAcceptError,
      fallbackError: 'Failed to update recommendation',
    });
  };

  // OverrideReasonModal shows the check or X itself; a throw here is its X.
  // stockObservation: the optional count typed in the dialog (null if none).
  const handleConfirmOverride = async (reason, stockObservation) => {
    const { item, action } = pendingOverride;
    await applyAction(item.id, action, { reason, silent: true, rethrow: true, stockObservation });
    logDecision(item, action, reason);
    if (stockObservation) reloadStaffRequests(); // the count joins the admin's list to check
  };

  // A row's state once a decision lands outside a PATCH from this page: an
  // applied or approved quantity change (accepted, planQty = the decided
  // quantity, which the plan total already counts) or an approved dismissal.
  const markDecided = (id, actionType, planQty) => {
    decisionLanded();
    setLocalData((prev) => prev.map((item) => (item.id === id
      ? { ...item, loadingAction: null, actionStatus: actionType, ...(planQty != null ? { planQty } : {}) }
      : item)));
  };

  // The quantity dialog's submit: held for an admin (202) or applied (200).
  // The server's outcome decides what the row shows, never the guess that
  // worded the button.
  const handleSubmitQtyChange = async ({ quantity, reason, reviewed, stockObservation }) => {
    const item = pendingQtyChange;
    const res = await requestQuantityChange(item.id, { quantity, reason, reviewed, stockObservation });
    if (res.outcome === 'applied') {
      markDecided(item.id, 'ACCEPTED', res.item?.plan_q_i ?? quantity);
      logDecision(item, 'ACCEPTED', `Changed the quantity to ${formatUnits(quantity)} pieces: ${reason}`);
    }
    refreshRequests();
    return res;
  };

  const handleSubmitDismissRequest = async (reason, stockObservation) => {
    await requestDismissal(pendingDismissRequest.id, { reason, stockObservation });
    refreshRequests();
  };

  // The Requests tab settled one: the row on the page follows it.
  const handleRequestResolved = (request, outcome) => {
    if (outcome === 'approved') {
      const row = localData.find((r) => r.id === request.recommendation_key);
      if (request.kind === 'dismissal') {
        markDecided(request.recommendation_key, 'DISMISSED');
        if (row) logDecision(row, 'DISMISSED', `Approved ${request.by}'s dismissal request: ${request.reason}`);
      } else {
        markDecided(request.recommendation_key, 'ACCEPTED', request.proposed_q_i);
        if (row) {
          logDecision(row, 'ACCEPTED',
            `Approved ${request.by}'s change to ${formatUnits(request.proposed_q_i)} pieces: ${request.reason}`);
        }
      }
    }
    refreshRequests();
  };

  // Rows by recommendation_key, for the Requests tab's warnings and stale check.
  const rowsByKey = useMemo(() => new Map(localData.map((r) => [r.id, r])), [localData]);
  // Some row of the plan on screen was cut to fit the supplier allocation.
  const planHasCuts = cycleRows.some((r) => r.shortUnits > 0);
  const openHistory = (row) => setHistoryFor({ id: row.id, product: row.product, sku: formatSKU(row.sku), packSize: row.packSize });

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

  const getLogActionBadge = (action) => {
    switch (action) {
      case 'ACCEPTED': return 'pill pill-planned';
      case 'DISMISSED': return 'pill pill-neutral';
      default: return 'pill pill-neutral';
    }
  };

  // A waiting request in words. Who asked shows to the requester and admins only
  // (the server leaves requested_by empty for everyone else).
  const requestText = (open) => {
    const what = open.kind === 'dismissal' ? 'Dismissal requested' : `Quantity change to ${formatUnits(open.proposed_q_i)} pieces requested`;
    return `${what}${open.requested_by ? ` by ${open.requested_by}` : ''}, waiting for an admin to approve or reject it.`;
  };

  const renderActionColumn = (item) => {
    const { state, primary, secondary } = actionsFor(item);

    if (state === 'loading') {
      return (
        <div className="action-status-container">
          <Loader2 className="spinner-icon" size={16} />
          <span className="loading-text">Processing...</span>
        </div>
      );
    }

    const name = `${item.product} (${item.sku})`;
    const menu = secondary.length > 0 && (
      <ReorderActionMenu
        label={`More actions for ${name}`}
        buttonClassName="table-btn reorder-menu-btn"
        buttonContent={primary ? <ChevronDown size={15} aria-hidden="true" /> : <MoreHorizontal size={15} aria-hidden="true" />}
        items={secondary.map((action) => ({
          key: action.id,
          label: action.label,
          disabled: action.disabled,
          onSelect: () => runRowAction(action.id, item),
        }))}
      />
    );

    if (state === 'decided' || state === 'what_if' || state === 'no_order') {
      return (
        <div className="action-status-container reorder-action-status">
          {state === 'decided' && <span className={getLogActionBadge(item.actionStatus)}>{item.actionStatus}</span>}
          {state === 'what_if' && (
            <span className="reorder-pending-label" title="A what-if row from the preview, never saved — nothing to decide">
              What-if
            </span>
          )}
          {state === 'no_order' && <span className="reorder-pending-label" title={noOrderReason(item, { countLabel, countFlag: openingCountFlag })}>No order</span>}
          {menu}
        </div>
      );
    }

    return (
      <div className={`reorder-split${menu ? ' has-menu' : ''}`}>
        <button
          type="button"
          className={`table-btn reorder-split-main ${primary.id === 'accept' ? 'table-btn-primary' : 'reorder-btn-review'}`}
          onClick={() => runRowAction(primary.id, item)}
          aria-label={`${primary.label} for ${name}`}
          disabled={primary.disabled}
        >
          {primary.label}
        </button>
        {menu}
      </div>
    );
  };

  // Red for a counted figure below safety stock, amber below target: the same
  // rule as the row's urgency (backend/stock_status.py), so the figure and its
  // badge can't disagree.
  const openingStockClass = (item) => {
    if (item.urgency === 'CRITICAL') return 'reorder-stock-critical';
    if (item.urgency === 'URGENT') return 'reorder-stock-low';
    return '';
  };

  const renderRow = (item) => {
    const brand = brandOf(item);
    const stockKnown = item.stock != null;
    const open = openRequests.byKey.get(item.id);
    const share = item.revenueShare != null
      ? `Revenue share ${(item.revenueShare * 100).toFixed(2)}%${abcLabel ? ` ${revenueShareBasis(item.principal, abcLabel)}` : ''}`
      : undefined;
    // Urgency, the review flag and a waiting request are three different things,
    // so three badges, each saying its own in words: the Decision column's, or
    // under the product where a tablet has no room for that column.
    const badges = (
      <>
        <span className={getUrgencyBadge(item.urgency)} title={URGENCY_HOVER[item.urgency]}>
          {urgencyWord(item.urgency)}
        </span>
        {item.reviewFlag && (
          <span className="reorder-review-pill" title={item.reviewFlag}>
            <AlertTriangle size={12} aria-hidden="true" />
            Needs review
          </span>
        )}
        {forecastsNoSales(item) && (
          <span className="reorder-review-pill" title={NO_SALES_FORECAST_NOTE}>
            <AlertTriangle size={12} aria-hidden="true" />
            No sales forecast
          </span>
        )}
        {open && (
          <span className="pill reorder-request-pill" title={requestText(open)}>
            {open.kind === 'dismissal' ? 'Dismissal requested' : 'Pending approval'}
          </span>
        )}
        {open && open.kind !== 'dismissal' && open.proposed_q_i != null && (
          <span className="reorder-cell-note">{formatUnits(open.proposed_q_i)} pieces asked</span>
        )}
      </>
    );
    return (
      <tr key={item.id} className="reorder-row">
        {tier !== 'tablet' && (
          <td className="table-center reorder-rank">
            {item.rank != null ? (
              `#${item.rank}`
            ) : (
              <span className="cell-empty" title={stockKnown ? 'Unranked — no revenue share recorded for this SKU' : 'Unranked — no stock figure in pieces, so the gap below the target stock is unknown'}>
                —
              </span>
            )}
          </td>
        )}
        {/* Name first, its code, brand and class on one quiet line under it
            (Sir Catubag, 2 Oct 2026). The name opens the review drawer, which
            also has the revenue share this line's hover states. */}
        <td className="cell-product">
          <ProductName
            name={item.product}
            onOpen={() => handleOpenDetails(item)}
            openLabel="View recommendation details"
          />
          <span className="reorder-product-meta" title={share}>
            <span>{formatSKU(item.sku)}</span>
            {brand && <span>{brand}</span>}
            <TierChip tier={item.tier} tierPeriod={item.tierPeriod} isCurrent={item.tierIsCurrent} anchor={String(item.planningCycleDate || '').slice(0, 7)} />
          </span>
          {tier === 'tablet' && <div className="reorder-badges reorder-product-badges">{badges}</div>}
        </td>
        {/* A SKU missing from the count says so instead of a figure: the plan
            reads it as 0, but nobody counted a 0, so it never looks like one. */}
        <td
          className={`table-center reorder-stock-cell reorder-group-start ${stockKnown ? openingStockClass(item) : ''}`}
          data-label="Opening Stock"
          title={item.stockNotInCount ? NOT_IN_COUNT_NOTE : (stockKnown ? piecesTitle(item.stock, item.packSize) : undefined)}
        >
          {!stockKnown && <span className="cell-empty" title={item.stockBlockedReason || 'No stock figure in pieces for this SKU'}>—</span>}
          {stockKnown && item.stockNotInCount && (
            <span className="reorder-count-flag">
              <AlertTriangle size={12} aria-hidden="true" />
              Not in stock count
            </span>
          )}
          {stockKnown && !item.stockNotInCount && formatUnits(item.stock)}
        </td>
        <td className="table-center" data-label="Safety Stock" title={piecesTitle(item.safetyStock, item.packSize)}>{formatUnits(item.safetyStock)}</td>
        {/* Target stock (rop_i since the 2026-09-30 LP run: demand over the
            review + lead window + safety stock). */}
        <td className="table-center" data-label="Target Stock" title={piecesTitle(item.rop, item.packSize)}>{formatUnits(item.rop)}</td>
        {hasOnOrder && wide && (
          <td className="table-center" title={item.onOrderNote || 'Pieces on order (PO Qty), information only'}>
            {item.onOrderQty != null ? formatUnits(item.onOrderQty) : <span className="cell-empty">—</span>}
          </td>
        )}
        <td className="table-center reorder-group-start" data-label="Forecast" title={item.forecast != null ? exactPieces(item.forecast) : `No forecast for ${cycleMonth ?? 'this planning month'}`}>
          {item.forecast != null ? formatUnits(item.forecast) : <span className="cell-empty">—</span>}
        </td>
        {wide && (
          <td className="table-center" title={item.daysOfCover != null ? coverNote : (item.coverReason || coverNote)}>
            {item.daysOfCover != null ? formatCoverDays(item.daysOfCover) : <span className="cell-empty">—</span>}
          </td>
        )}
        <td className="table-center reorder-qty-cell reorder-group-start" data-label="Suggested Order, month's total" title={lpQtyTitle(item)}>
          <strong className="reorder-qty">{formatUnits(item.orderQty)}</strong>
          {tier !== 'full' && item.cases.order && (
            <span className="reorder-cell-note">{tier === 'tablet' ? casesCell(item.cases.order) : item.cases.order}</span>
          )}
          {/* Accepted at a different quantity (a planner's change, applied or
              approved): the figure the plan total counts (plan_q_i). */}
          {item.planQty != null && !sameQuantity(item.planQty, item.orderQty) && (
            <span className="reorder-cell-note rq-plan-note">accepted: {formatUnits(item.planQty)}</span>
          )}
          {item.shortUnits > 0 && <span className="reorder-short-note">{formatUnits(item.shortUnits)} short</span>}
        </td>
        {tier === 'full' && (
          <td className="table-center reorder-cases-cell" title={item.cases.order || undefined}>
            {casesCell(item.cases.order) ?? <span className="cell-empty">—</span>}
          </td>
        )}
        {tier !== 'tablet' && <td className="table-center reorder-urgency-cell reorder-badges reorder-group-start">{badges}</td>}
        <td className="table-center reorder-action-cell">
          {renderActionColumn(item)}
        </td>
      </tr>
    );
  };

  // Opening, safety and target stock, and on order when a row carries it.
  const inventoryColumns = 3 + (hasOnOrder && wide ? 1 : 0);
  const demandColumns = wide ? 2 : 1;
  const orderColumns = tier === 'full' ? 2 : 1;
  // Rank and product, the groups, then decision and actions; a tablet folds rank
  // and the decision column away.
  const COLUMN_COUNT = (tier === 'tablet' ? 2 : 4) + inventoryColumns + demandColumns + orderColumns;

  const renderRecommendationsTab = () => (
    <>
      {decisions?.status === 'ok' && !decisions.whatIf && decisions.cycle && (
        <p className={`ui-note ${decisions.counts.pending > 0 ? 'is-warning' : 'is-info'}`} role="status" data-testid="reorder-decision-state">
          <ClipboardList size={16} aria-hidden="true" />
          <span><strong>{formatMonth(String(decisions.cycle).slice(0, 10))} plan:</strong> {decisionLine(decisions.counts)}.{planStateLine(decisions.planState) && ` ${planStateLine(decisions.planState)}`}</span>
        </p>
      )}
      {decisions?.status === 'error' && (
        <p className="ui-note is-warning" role="status" data-testid="reorder-decision-state">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>How many of this plan's rows are decided could not be read.</span>
        </p>
      )}
      {/* Provisional until SSM confirms the run's inputs (lp_model.inputs_are_placeholders):
          the quantities show how the model behaves on real demand and stock, and the
          buttons below shouldn't read as if they were final. Not called a "demonstration":
          that word is the labelled synthetic data's, and these rows are real. */}
      {meta?.lpModel?.inputs_are_placeholders && !meta?.whatIf && cycleRows.length > 0 && (
        <div className="dash-stale-note reorder-provisional-note" role="note">
          <AlertTriangle size={14} aria-hidden="true" />
          <span>
            <strong>Provisional plan, not a final purchasing figure.</strong>{' '}
            SSM has not yet confirmed the procurement and storage costs, the warehouse capacity
            {openingCountFlag ? `, the supplier allocation or the stock ${countLabel}` : ' or the supplier allocation'}. Check
            each quantity before ordering.
            <InfoTip label="What SSM has not confirmed">
              {provisionalDetail({ inputs: lpInputs, countLabel, countFlag: openingCountFlag, notes: planNotes })}
            </InfoTip>
          </span>
        </div>
      )}

      {/* The four figures for the whole cycle: the search and filters below
          never change them. Each card's accent says what kind of figure it is
          (ReorderRecommendations.css --reorder-kpi-*). */}
      <div className="reorder-kpi-wrap">
      <div className="kpi-strip reorder-summary-grid">
        <KPICard
          title="Act Now"
          value={actNowPending.toLocaleString()}
          unit="SKUs"
          metricType={actNowPending > 0 ? 'danger' : undefined}
          accent="var(--reorder-kpi-act)"
          contextLine={`${planLabel} · Below target stock`}
          decoration={<Boxes size={38} strokeWidth={1.4} />}
          tooltip="Every SKU below its target stock that still awaits a decision, ranked by revenue share × pieces below the target stock."
          icon={<AlertTriangle size={20} />}
        />
        <KPICard
          title="Review Later"
          value={reviewLaterTotal.length.toLocaleString()}
          unit="SKUs"
          metricType={reviewLaterTotal.length > 0 ? 'watch' : undefined}
          accent="var(--reorder-kpi-later)"
          contextLine={`${planLabel} · At or above target stock`}
          decoration={<ClipboardCheck size={38} strokeWidth={1.4} />}
          tooltip={`${reviewLaterUnranked > 0
            ? `${reviewLaterTotal.length - reviewLaterUnranked} at or above the target stock; ${reviewLaterUnranked} not ranked (no stock figure or revenue share).`
            : 'Every SKU at or above its target stock, still awaiting a decision.'}${reviewLaterNoOrder > 0
            ? ` Leaves out the ${reviewLaterNoOrder} with nothing to order, which have no decision to make.` : ''}`}
          icon={<Clock size={20} />}
        />
        {/* Until 2026-10-01 "NO STOCK RECORD": these rows showed no stock and
            went unranked, while the LP had planned them as 0 on hand and cut
            all three. They are now 0 like in the plan, counted here so the
            inferred 0 is never mistaken for a counted one. */}
        <KPICard
          title="Not in Stock Count"
          value={notInCountCount.toLocaleString()}
          unit="SKUs"
          accent="var(--reorder-kpi-count)"
          contextLine={`${countLabel.charAt(0).toUpperCase()}${countLabel.slice(1)} · Treated as 0 on hand`}
          decoration={<PackageSearch size={38} strokeWidth={1.4} />}
          tooltip={`Missing from the opening stock count, so the plan treats them as out of stock.${noStockFigureCount > 0
            ? ` ${noStockFigureCount} more have no stock figure in pieces (NO DATA).` : ''}`}
          icon={<Package size={20} />}
        />
        <KPICard
          title="Total Suggested Order"
          value={totalOrderQty.toLocaleString()}
          unit="pieces"
          metricType="recommendation"
          accent="var(--reorder-kpi-total)"
          contextLine={cutCount > 0
            ? `${planLabel} · ${cutCount} of ${cycleRows.length} SKUs cut to fit the allocation`
            : noOrderCount > 0
              ? `${planLabel} · ${orderingCount} SKUs to order, ${noOrderCount} need none`
              : `${planLabel} · suggested by the optimizer`}
          tooltip={`${allocationPct != null
            ? `Suggested by the optimizer within the ${allocationPct}% supplier allocation.`
            : 'Suggested by the optimizer.'}${noOrderCount > 0
            ? ` ${noOrderCount} of the ${cycleRows.length} SKUs in the plan have a suggested order of 0 pieces.`
            : ''} ${MONTH_TOTAL_NOTE}`}
          decoration={<ShoppingCart size={38} strokeWidth={1.4} />}
          icon={<ShoppingCart size={20} />}
        />
      </div>
      </div>

      {/* How the quantities were arrived at: one line until it is opened, with
          every paragraph, note, flag and weight inside. Quieter than the table
          it explains. */}
      <details className="reorder-how">
        <summary className="reorder-how-summary">
          <span className="reorder-how-icon" aria-hidden="true"><Target size={18} /></span>
          <span className="reorder-how-heading">
            <span className="reorder-how-title">How this was optimized</span>
            <span className="reorder-how-lede">
              Orders each SKU up to its target stock. If the supplier allocation can&apos;t cover every SKU,
              {lpInputs.cover_rule === 'per-sku'
                ? <> the plan&apos;s cost and service weights decide which SKUs come up short.</>
                : <> SSM&apos;s {lpInputs.target_weeks ?? 3}-week stock rule and the plan&apos;s cost and service weights decide which SKUs come up short.</>}
            </span>
          </span>
          <ChevronDown className="reorder-how-chevron" size={18} aria-hidden="true" />
        </summary>
        <div className="reorder-how-body">
          <div className="reorder-how-text">
            <p className="reorder-table-note">
              The order plan orders each SKU up to its target stock, net of what is on hand. Only when the supplier allocation
              can&apos;t cover every SKU does it cut some orders, and then
              {lpInputs.cover_rule === 'per-sku'
                ? <> the plan&apos;s cost and service weights decide which SKUs come up short.</>
                : <>
                    {' '}SSM&apos;s {lpInputs.target_weeks ?? 3}-week stock rule (counted over the SKUs in this plan, not the
                    whole warehouse) and the plan&apos;s cost and service weights decide which SKUs come up short.
                  </>}
            </p>
            {(lpInputs.storage_cost_per_unit != null || notCategoryACount > 0 || meta?.supersededCount > 0) && (
            <p className="reorder-table-note">
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
              {meta?.supersededCount > 0 && (
                <>
                  {' '}Showing the current cycle only — {meta.supersededCount.toLocaleString()} undecided
                  {' '}row{meta.supersededCount === 1 ? '' : 's'} from earlier runs {meta.supersededCount === 1 ? 'is' : 'are'} superseded and not listed.
                </>
              )}
            </p>
            )}
            {/* Since migration 0066 the LP rounds each order to whole case
                packs; this used to call the case count "rough". */}
            <p className="reorder-table-note">
              All quantities are in pieces, for the {planLabel}; under each order is its size in cases (pieces ÷
              pieces per case). Suggested qty = the month&apos;s forecast + target stock − stock at the start of the month
              (the stock count that opens it), rounded to whole cases where the product has a pack size. {MONTH_TOTAL_NOTE} A row marked
              {' '}&ldquo;short&rdquo; was cut to fit the supplier allocation and
              ends the month that far below its target. A SKU missing from that stock count shows 0, &ldquo;not in
              stock count&rdquo;: the plan treats it as out of stock. Ranked by revenue share × pieces below the target stock.
              Cover is in days: stock in pieces ÷ average daily sales in pieces
              {coverSalesLabel ? ` over ${coverSalesLabel}` : ''}.
            </p>
            {/* The calendar adjustment inside the forecasts this plan ordered
                from (lp_model.calendar_factor_on, from the run's own record):
                it moves every order quantity, so its sign-off status is said
                here too (Technical Adviser, 2 Oct 2026; 2026-10-22). */}
            {meta?.lpModel?.calendar_factor_on && (
              <p className="reorder-table-note">
                The forecasts behind these orders include the company calendar adjustment (each month scaled by how
                that month has sold in earlier years){calendarSignoffText(meta.lpModel.calendar_signed_off)
                  ? `, ${calendarSignoffText(meta.lpModel.calendar_signed_off)}` : ''}.
              </p>
            )}
            {/* Methods that set these numbers and still await the adviser's
                sign-off, flagged where they act (Technical Adviser, 2 Oct
                2026; 2026-10-22): which products get a plan (MASE < 1,
                analytics/params.py MASE_GATE, a team decision, DEC-46, not
                confirmed by SSM or the adviser) and how safety stock
                scales monthly variation to days (lp_model
                .safety_stock_assumption, CLAUDE.md "needs adviser ruling"). */}
            <p className="reorder-table-note">
              One run per planning cycle, for the month after the latest sales data. Only Class A products whose forecast
              test error is below the average month-to-month change in their sales before the test months are planned here
              (a reliability check the team adopted, not confirmed by SSM or the adviser).
              {meta?.notPlanned?.length > 0 && ' The rest are listed under “Not in This Plan”, below the table.'}
              {meta?.lpModel?.safety_stock_assumption && (
                <>
                  {' '}Safety stock scales each product&apos;s month-to-month swings in sales down to the review and
                  delivery days
                  {lpInputs.review_days != null && lpInputs.lead_days != null
                    ? ` (${lpInputs.review_days} + ${lpInputs.lead_days} business days)` : ''}, which assumes one
                  day&apos;s sales don&apos;t affect the next: an assumption pending adviser confirmation.
                  <InfoTip label="The safety stock formula">{meta.lpModel.safety_stock_assumption}</InfoTip>
                </>
              )}
            </p>
            {openingCountNote && <p className="reorder-table-note">{openingCountNote}</p>}
            {planNotes.map((note) => <p className="reorder-table-note" key={note}>Data note: {note}</p>)}
            {canOpenDashboard && (
              <p className="reorder-table-note">
                <button type="button" className="link-button" onClick={() => navigate({ pathname: '/', hash: '#idle-stock' })}>
                  See stock that has stopped selling
                </button>
                {' '}— products this plan orders nothing for may still be sitting in the warehouse.
              </p>
            )}
          </div>
          {weightRows.length > 0 && (
            <div className="reorder-how-side">
              <dl className="reorder-how-weights" aria-label="The optimizer's weights">
                {weightRows.map(([label, value]) => (
                  <div className="reorder-how-weight" key={label}>
                    <dt>{label}<span>{typeof value === 'number' ? `${Math.round(value * 100)}%` : '—'}</span></dt>
                    <dd><span style={{ width: `${typeof value === 'number' ? Math.round(value * 100) : 0}%` }} /></dd>
                  </div>
                ))}
              </dl>
              {/* analytics/params.py LP_WEIGHTS: "TEAM (asserted)", in no
                  scribe note (reports/LP_READINESS.md §1.5). */}
              <p className="reorder-how-weight-note">Weights: a team setting; source not yet confirmed.</p>
            </div>
          )}
        </div>
      </details>

      {/* What changed since the previous cycle: collapsed to one line by
          default. No plan covers Del Monte (the table says so), so nothing
          to compare there. Keyed so a principal or data-mode switch starts
          afresh and an earlier scope's answer can never land in it. */}
      {principal !== 'delmonte' && (
        <CycleComparison key={`${principal}|${dataMode}`} principal={principal} dataMode={dataMode} />
      )}

      <div className="ui-card is-flush reorder-orders-card">
      <div className="ui-card-intro">
      <ReorderTableControls
        view={view}
        onViewChange={setView}
        counts={viewTotals}
        query={searchQuery}
        onQueryChange={setSearchQuery}
      />

      {meta?.whatIf && (
        <p className="chart-placeholder-note">
          Preview: these recommendations are a what-if run of the order plan on the five-year history, 2021–22 placeholder
          months included. They are never saved, so they can&apos;t be accepted or dismissed.
        </p>
      )}
      {!canDecide && !meta?.whatIf && (
        <p className="reorder-view-only-note">
          {canPropose && approvalReady
            ? 'Your account can’t accept or dismiss reorders directly. Request a quantity change or a dismissal on a row, and an admin approves or rejects it.'
            : <>View only — your account can&apos;t accept or dismiss reorders. Ask an admin if you need to.</>}
        </p>
      )}

      </div>

      {/* The table scrolls inside its own frame on a wide screen, so its header
          stays in view; on a phone each row is a card and the page scrolls. */}
      <div className="reorder-table-section">
      <div ref={setTableArea} className={`reorder-table-area is-${tier}`}>
        <div className="data-table-card ui-card-table reorder-table-scroll" tabIndex={tier === 'cards' ? undefined : 0} role={tier === 'cards' ? undefined : 'region'} aria-label={tier === 'cards' ? undefined : 'Recommended orders'}>
          <table className="data-table reorder-table">
            {tier !== 'cards' && (
              <thead>
                {/* Periods and units sit once, on the group they apply to (Sir
                    Catubag, 2 Oct 2026: a number without its period and unit
                    can't be checked); the explanations behind one "?" each. */}
                <tr className="reorder-head-groups">
                  {tier !== 'tablet' && <th rowSpan={2} scope="col">#</th>}
                  <th rowSpan={2} scope="col" className="col-text col-product">
                    Product (SKU)
                    <span className="reorder-th-period">Brand · Class{tier === 'tablet' ? ' · Urgency & Flags' : ''}</span>
                  </th>
                  <th colSpan={inventoryColumns} scope="colgroup" className="reorder-head-group reorder-group-start">
                    <span className="reorder-head-label">
                      Inventory Position
                      <InfoTip label="About target stock">Target stock is the stock level each order tops up to: the demand expected before the next delivery, plus safety stock.</InfoTip>
                    </span>
                    <span className="reorder-th-period">{planLabel}, in pieces</span>
                    <span className="reorder-th-period">Opening stock {countLabel}</span>
                  </th>
                  <th colSpan={demandColumns} scope="colgroup" className="reorder-head-group reorder-group-start">
                    <span className="reorder-head-label">
                      Demand
                      <InfoTip label="About forecast and cover">
                        {`Forecast is this SKU's forecast sales for the planning month${cycleMonth ? ` (${cycleMonth})` : ''}, in pieces: what the order has to cover before it can build stock up to target. Cover: ${coverNote}`}
                      </InfoTip>
                    </span>
                    {cycleMonth && <span className="reorder-th-period">{cycleMonth} forecast</span>}
                    {wide && <span className="reorder-th-period">{coverSalesLabel ? `Sales ${coverSalesLabel}` : countLabel}</span>}
                  </th>
                  <th colSpan={orderColumns} scope="colgroup" className="reorder-head-group reorder-group-start">
                    <span className="reorder-head-label">
                      Suggested Order
                      <InfoTip label="About suggested quantity">
                        What to order, in pieces, worked out by the order plan (an optimisation model; the Reference Guide explains it): forecast +
                        target stock − opening stock, less any cut made to fit the supplier allocation. Cases show the same order for a
                        product with a pack size; a run of the plan rounds each order to whole cases. {MONTH_TOTAL_NOTE}
                      </InfoTip>
                    </span>
                    <span className="reorder-th-period">{planLabel}</span>
                    <span className="reorder-th-period">Month&apos;s total</span>
                  </th>
                  {tier !== 'tablet' && (
                    <th rowSpan={2} scope="col" className="reorder-group-start">
                      Decision
                      <span className="reorder-th-period">Urgency &amp; Flags</span>
                    </th>
                  )}
                  <th rowSpan={2} scope="col" className="reorder-head-actions table-center">Actions</th>
                </tr>
                <tr className="reorder-head-columns">
                  <th scope="col" className="table-center reorder-group-start">
                    {/* The count's reviewed note behind a "?". */}
                    <span className="reorder-head-label">
                      Opening Stock
                      <InfoTip label="About this stock count">
                        {projectedCount
                          ? projectedNote(projectedCount)
                          : `Stock ${countLabel}, the count that opens this plan.${openingCountFlag ? ` ${openingCountFlag}` : ''}`}
                      </InfoTip>
                    </span>
                  </th>
                  <th scope="col" className="table-center">Safety Stock</th>
                  <th scope="col" className="table-center">Target Stock</th>
                  {hasOnOrder && wide && (
                    <th scope="col" className="table-center">
                      On Order
                      <span className="reorder-th-period">not yet arrived</span>
                    </th>
                  )}
                  <th scope="col" className="table-center reorder-group-start">Forecast</th>
                  {wide && <th scope="col" className="table-center">Cover (Days)</th>}
                  <th scope="col" className="table-center reorder-group-start">{tier === 'full' ? 'Pieces' : 'Pieces · Cases'}</th>
                  {tier === 'full' && <th scope="col" className="table-center">Cases</th>}
                </tr>
              </thead>
            )}
            <tbody>
              {(filtered ? actNowRows.length > 0 : cycleRows.length > 0) && (
                <tr className="reorder-group-row reorder-group-act">
                  <td colSpan={COLUMN_COUNT}>
                    {filtered
                      ? `${VIEW_LABEL[view]?.title ?? 'Search'} — ${listedText}, by revenue at risk`
                      : actNowRows.length > 0
                        ? `Act now — ${actNowRows.length} ${actNowRows.length === 1 ? 'SKU' : 'SKUs'} below target stock, by revenue at risk`
                        : 'Act now — no SKU is below its target stock'}
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
                      Review later — {reviewLaterRows.length} more SKUs
                      {reviewLaterNoOrder > 0 ? `, ${reviewLaterNoOrder} with no order` : ''}
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
                      ? 'The order plan does not cover Del Monte: it has no SKU-level sales to forecast, so there are no reorder recommendations for it.'
                        + (isPreviewMode(dataMode) && meta?.demoOrderPlan?.reason
                          ? ` The synthetic data has no order plan either: ${meta.demoOrderPlan.reason}.` : '')
                      : meta?.cycleDate
                        ? 'No recommendations for this planning cycle.'
                        : 'No run of the order plan has produced recommendations for this scope yet.'}
                  </td>
                </tr>
              )}
              {cycleRows.length > 0 && filtered && visibleRows.length === 0 && (
                <tr className="table-empty-row">
                  <td colSpan={COLUMN_COUNT}>
                    No SKUs in this plan match.{' '}
                    <button type="button" className="link-button" onClick={clearFilters}>Show all</button>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="reorder-table-footer">
        {planFacts && <p className="reorder-table-note reorder-plan-facts">{planFacts}</p>}
        {filtered && (
          <p className="reorder-filter-chip" role="status">
            <span>
              Showing {view !== 'all' && <><strong>{VIEW_LABEL[view].title.toLowerCase()}</strong> only: </>}{listedText}
            </span>
            <button type="button" className="link-button" onClick={clearFilters}>Show all</button>
          </p>
        )}
        {canDecide && !meta?.whatIf && (
          <button
            type="button"
            className="btn btn-primary reorder-bulk-btn"
            onClick={() => {
              bulkSave.reset();
              // Saved here: what the dialog previews is what it submits.
              setPendingBulk({ rows: bulkTargets, excluded: bulkSplit.excluded, listed: filtered ? listedText : null });
            }}
            disabled={bulkTargets.length === 0 || bulkRunning}
            title={bulkTargets.length === 0 ? 'No pending rows in view' : undefined}
          >
            {bulkRunning ? <Loader2 className="spinner-icon" size={14} /> : <CheckCheck size={14} aria-hidden="true" />}
            Accept all in view ({bulkTargets.length})
          </button>
        )}
      </div>
      </div>
      </div>

      {/* The top sellers this plan leaves out. Read-only and beside the plan: never
          in its counts, its total or Accept all. An urgency or flag view asks for
          those rows only, so the list steps aside; a search narrows it too. */}
      {view === 'all' && meta?.notPlanned?.length > 0 && (
        <ReorderNotPlanned
          items={meta.notPlanned}
          tier={tier}
          tierPeriod={meta.tierAPeriods?.Unilever}
          countLabel={countLabel}
          coverSalesLabel={coverSalesLabel}
          coverNote={coverNote}
          abcLabel={abcLabel}
          notInCountNote={NOT_IN_COUNT_NOTE}
          query={searchQuery}
          brandOf={brandOf}
          formatSku={formatSKU}
          onOpenForecast={canOpenForecast ? (sku) => navigate(`/forecast?sku=${encodeURIComponent(sku)}`) : undefined}
        />
      )}
    </>
  );

  const renderDecisionLogTab = () => (
    <div className="ui-card is-flush">
    <div className="ui-card-intro">
      <div className="ui-card-head">
        <span className="icon-tile" aria-hidden="true"><ListChecks size={20} /></span>
        <div className="ui-card-head-text">
          <SectionLede className="ui-card-label">Who decided what, and when</SectionLede>
          <p className="reorder-table-note reorder-log-note">
            Decisions made in this session. The permanent records are each recommendation&apos;s History and the Audit Log.
          </p>
        </div>
      </div>
    </div>
    <div className="data-table-card ui-card-table">
      <table className="data-table reorder-log-table">
        <thead>
          <tr>
            {/* formatDateTime renders in the browser's own time zone. */}
            <th className="col-fit table-center">When (local time)</th>
            <th className="col-text col-product">Product</th>
            <th className="col-fit table-center">Plan</th>
            <th className="col-fit table-center">Decision</th>
            <th className="col-text col-reason">Reason</th>
            <th className="col-fit table-center">Decided by</th>
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
                <td className="cell-muted table-center">{entry.timestamp}</td>
                <td className="cell-product"><ProductName name={entry.product} code={formatSKU(entry.sku)} /></td>
                <td className="cell-muted table-center">{entry.cycle ? `${formatMonth(entry.cycle)} plan` : '—'}</td>
                <td className="table-center">
                  <span className={getLogActionBadge(entry.action)}>
                    {entry.action}
                  </span>
                </td>
                <td className="col-text reorder-log-reason">{entry.reason || <span className="cell-empty">—</span>}</td>
                <td className="cell-muted table-center">{entry.decidedBy}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
    </div>
  );

  // Counted from the list the dialog holds, the one it submits.
  const bulkFigures = bulkSummary(pendingBulk?.rows || []);
  const bulkPrincipals = [...new Set((pendingBulk?.rows || []).map((r) => labelForPrincipal(r.principal)))].join(', ');
  const drawerRow = selectedItem ? (rankedRows.find((r) => r.id === selectedItem.id) || selectedItem) : null;
  const drawerRequest = drawerRow ? openRequests.byKey.get(drawerRow.id) || null : null;

  const tabs = [
    { key: 'RECOMMENDATIONS', label: 'Recommendations', Icon: ClipboardList },
    { key: 'DECISION_LOG', label: 'Decision log', Icon: ListChecks, count: decisionLog.length },
    // lp.decide or lp.propose: an admin's queue of everyone's requests, or a staff member's own.
    ...(canSeeRequests
      ? [{ key: 'REQUESTS', label: isAdmin ? 'Staff requests' : 'My requests', Icon: Users, badge: staffRequests.pendingCount }]
      : []),
  ];
  const handleTabKeyDown = (e) => {
    const keys = tabs.map((t) => t.key);
    const at = keys.indexOf(activeTab);
    const next = { ArrowRight: (at + 1) % keys.length, ArrowLeft: (at - 1 + keys.length) % keys.length, Home: 0, End: keys.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    setActiveTab(keys[next]);
    document.getElementById(`reorder-tab-${keys[next]}`)?.focus();
  };

  return (
    <div className="reorder-page">
      <div className="reorder-content">
        <PageHeader
          className="reorder-head"
          icon={<CalendarClock size={24} />}
          title="Reorder Recommendations"
          subtitle="Review inventory risks and approve purchasing decisions based on the latest sales and forecast."
          actions={cycles.length > 0 && (
            <dl className="reorder-planinfo">
              {/* A label: the page reads one cycle, the current one (backend/lp_cycle.current_cycle),
                  and a dropdown with one option offers nothing. It appears if there is ever a choice. */}
              <div className={`reorder-planinfo-item reorder-planinfo-cycle${cycles.length > 1 ? ' has-choice' : ''}`}>
                <Calendar size={20} aria-hidden="true" />
                <div>
                  <dt>Planning Cycle</dt>
                  <dd>
                    {selectedCycle ? formatMonth(selectedCycle) : ''}
                    {selectedCycle === cycles[0].date && <span className="reorder-cycle-latest">Latest</span>}
                    {cycles.length > 1 && <ChevronDown size={14} aria-hidden="true" />}
                  </dd>
                </div>
                {cycles.length > 1 && (
                  <select
                    className="reorder-planinfo-select"
                    aria-label="Planning cycle"
                    value={selectedCycle || ''}
                    onChange={(e) => { setSelectedCycle(e.target.value); setShowReviewLater(false); }}
                  >
                    {cycles.map((c, i) => (
                      <option key={c.date} value={c.date}>
                        {formatMonth(c.date)}{i === 0 ? ' (latest)' : ''} · {c.count} pending
                      </option>
                    ))}
                  </select>
                )}
              </div>
              {runIsThisCycle && (
                <div className="reorder-planinfo-item">
                  <Layers size={20} aria-hidden="true" />
                  <div>
                    <dt>Plan Run</dt>
                    <dd>#{lpRun.run_key}{lpRun.created_at ? ` · ${formatDate(lpRun.created_at)}` : ''}</dd>
                  </div>
                </div>
              )}
              <div
                className="reorder-planinfo-item"
                title="When this page last read the plan from the database. Refresh, at the top of the page, reads it again."
              >
                <Clock size={20} aria-hidden="true" />
                <div>
                  <dt>Last Update</dt>
                  <dd><LastUpdate fetchedAt={loadedAt} /></dd>
                </div>
              </div>
            </dl>
          )}
        >
          <TierBasisLabel periods={meta?.tierAPeriods} />
          {/* What decides a cut (analytics/optimization/lp.py, 2026-10-01)
              is in "How this was optimized" above the table. Same freshness
              notice as the Dashboard's, for the page where
              the affected numbers (q_i, rop_i) are actually acted on.
              Restored 2026-09-29 with the Dashboard's (see Dashboard.jsx).
              Worded here from freshness' own counts and dates (2026-10-22):
              its `reason` names backend columns (q_i, rop_i) and scripts,
              so it sits behind the "?" instead of on the page. */}
          {meta?.freshness?.is_stale && (
            <div className="dash-stale-note" role="status">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                <strong>
                  {meta.freshness.stale_row_count < meta.freshness.row_count ? 'Some of these quantities are' : 'These quantities are'}
                  {' '}from an older run of the order plan.
                </strong> {staleText(meta.freshness)}
                {meta.freshness.reason && <InfoTip label="Technical detail">{meta.freshness.reason}</InfoTip>}
              </span>
            </div>
          )}
        </PageHeader>

        {/* The page's views, in the shared segmented control. Arrow keys move
            between them; the Staff requests badge is the requests still waiting
            for a decision (an admin: everyone's; staff: their own), shown from
            every tab. */}
        <div className="segmented reorder-tabs" role="tablist" aria-label="Reorder views" onKeyDown={handleTabKeyDown}>
          {tabs.map(({ key, label, Icon, count, badge }) => (
            <button
              key={key}
              id={`reorder-tab-${key}`}
              type="button"
              role="tab"
              className={`segmented-item${activeTab === key ? ' is-active' : ''}`}
              aria-selected={activeTab === key}
              aria-controls="reorder-tabpanel"
              tabIndex={activeTab === key ? 0 : -1}
              onClick={() => setActiveTab(key)}
            >
              <Icon size={15} aria-hidden="true" />
              {label}
              {count > 0 && <span className="segmented-count">{count}</span>}
              {badge > 0 && (
                <>
                  <span className="reorder-tab-badge" aria-hidden="true">{badge > 99 ? '99+' : badge}</span>
                  <span className="visually-hidden">, {badge} pending approval</span>
                </>
              )}
            </button>
          ))}
        </div>

        <div className="reorder-tabpanel" id="reorder-tabpanel" role="tabpanel" aria-labelledby={`reorder-tab-${activeTab}`}>
        {loading && (
          <>
            <LoadingStatus>Loading recommendations…</LoadingStatus>
            <SlowLoadNotice />
            {activeTab === 'RECOMMENDATIONS' ? (
              <>
                <div className="reorder-kpi-wrap">
                  <div className="kpi-strip reorder-summary-grid">
                    <SkeletonStatCards count={4} cardClassName="kpi-card" />
                  </div>
                </div>
                <div className="reorder-table-footer" aria-hidden="true">
                  <SkeletonLine width="58%" height="0.8rem" />
                </div>
                <div className="data-table-card">
                  <SkeletonTable rows={8} columns={12} />
                </div>
              </>
            ) : (
              <div className="data-table-card">
                <SkeletonTable rows={6} columns={7} />
              </div>
            )}
          </>
        )}
        {error && !loading && (
          <LoadError what="the reorder recommendations" message={error} onRetry={() => setAttempt((n) => n + 1)} />
        )}
        {!loading && !error && activeTab === 'RECOMMENDATIONS' && renderRecommendationsTab()}
        {!loading && !error && activeTab === 'DECISION_LOG' && renderDecisionLogTab()}
        {!loading && !error && activeTab === 'REQUESTS' && canSeeRequests && (
          <StaffRequestsTab
            requests={staffRequests}
            isAdmin={isAdmin}
            filter={requestsView}
            onFilterChange={setRequestsFilter}
            linkRequest={canSeeRequests ? requestParam : null}
            onLinkHandled={clearRequestLink}
            rowsByKey={rowsByKey}
            planHasCuts={planHasCuts}
            onResolved={handleRequestResolved}
            onOpenHistory={canSeeHistory ? (request) => setHistoryFor({
              id: request.recommendation_key,
              product: request.product_name || 'Unknown Product',
              sku: formatSKU(request.sku_code),
              packSize: rowsByKey.get(request.recommendation_key)?.packSize ?? null,
            }) : undefined}
          />
        )}
        {/* The synthetic order plans, below and framed apart from the real list: only with the Topbar switch on
            (and then only when the server sent them, i.e. DM_DEMO_ENABLED too). Never part of the real rows,
            the counts or the Accept buttons above. */}
        {!loading && !error && activeTab === 'RECOMMENDATIONS' && isPreviewMode(dataMode) && (
          principal === 'delmonte'
            ? (meta?.demoOrderPlan && <DemoOrderPlanCard plan={meta.demoOrderPlan} kind="delmonte" id="demo-order-plan" />)
            : (meta?.demoUnileverPlan && <DemoOrderPlanCard plan={meta.demoUnileverPlan} kind="unilever" id="demo-order-plan" />)
        )}
        </div>
      </div>

      {/* Resolve the row through rankedRows so a drawer opened from a
          Dashboard deep link (which selects from the unranked localData)
          still shows its impact rank once the cycle's rows are ranked. */}
      <ReorderReviewDrawer
        isOpen={isModalOpen}
        onClose={closeDrawer}
        data={drawerRow}
        brand={drawerRow ? brandOf(drawerRow) : null}
        principal={principal}
        lpModel={meta?.lpModel}
        periods={meta || {}}
        projectedCount={projectedCount}
        countFlag={openingCountFlag}
        actions={drawerRow ? actionsFor(drawerRow) : null}
        onAction={(id) => runRowAction(id, drawerRow, { fromDrawer: true })}
        openRequest={drawerRequest}
        requestNote={drawerRequest ? requestText(drawerRequest) : null}
        onOpenForecast={canOpenForecast
          ? (sku) => navigate(`/forecast?sku=${encodeURIComponent(sku)}`)
          : undefined}
      />

      {/* Admin (lp.decide) Dismiss: the reason, and since 2026-10-28 an
          optional stock count once the server keeps them (migration 0070). */}
      <OverrideReasonModal
        isOpen={Boolean(pendingOverride)}
        item={pendingOverride?.item}
        onCancel={() => setPendingOverride(null)}
        onConfirm={handleConfirmOverride}
        allowStockCount={openRequests.ready}
      />

      {/* Staff (lp.propose): ask an admin to dismiss. */}
      <OverrideReasonModal
        isOpen={Boolean(pendingDismissRequest)}
        item={pendingDismissRequest}
        mode="request"
        onCancel={() => setPendingDismissRequest(null)}
        onConfirm={handleSubmitDismissRequest}
        allowStockCount={openRequests.ready}
      />

      <QuantityChangeModal
        isOpen={Boolean(pendingQtyChange)}
        item={pendingQtyChange}
        directApply={appliesDirectly}
        planHasCuts={planHasCuts}
        countsReady={openRequests.ready}
        onCancel={() => setPendingQtyChange(null)}
        onSubmit={handleSubmitQtyChange}
      />

      <HistoryModal isOpen={Boolean(historyFor)} item={historyFor} onClose={() => setHistoryFor(null)} />

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
                ? <><strong>{formatUnits(pendingAccept.orderQty)}</strong> pieces of <strong>{pendingAccept.product}</strong> ({formatSKU(pendingAccept.sku)}) are in the decision log.</>
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
                <strong>{pendingAccept.product}</strong> ({formatSKU(pendingAccept.sku)}) for the{' '}
                {pendingAccept.planningCycleDate ? `${formatMonth(pendingAccept.planningCycleDate)} plan` : 'current plan'},
                as suggested by the order plan. {MONTH_TOTAL_NOTE}
              </p>
              {pendingAccept.needsReview && (
                <p className="reorder-accept-body">
                  Flagged for review: {pendingAccept.reviewReasons.map((r) => REVIEW_REASON_TEXT[r] || r).join('; ')}.
                  A large miss is likely; accepting confirms you checked this quantity.
                </p>
              )}
              {forecastsNoSales(pendingAccept) && <p className="reorder-accept-body">{NO_SALES_FORECAST_NOTE}</p>}
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
          labelledBy="reorder-bulk-title"
          overlayClassName="reorder-accept-overlay"
          containerClassName="reorder-accept-card reorder-bulk-card"
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
              <h3 className="reorder-accept-title" id="reorder-bulk-title">Confirm Bulk Acceptance</h3>
              <p className="reorder-accept-body">
                This accepts these recommendations at the order plan&apos;s quantities
                {pendingBulk.listed ? ` (showing ${pendingBulk.listed})` : showReviewLater ? ' (Act now and Review later)' : ' (the Act-now list)'}.
                Each one is logged individually.
              </p>
              <dl className="reorder-bulk-facts">
                <div><dt>Recommendations</dt><dd>{bulkFigures.count.toLocaleString()}</dd></div>
                <div><dt>Total for the month</dt><dd>{bulkFigures.totalPieces.toLocaleString()} pieces</dd></div>
                <div><dt>Planning cycle</dt><dd>{formatMonth(pendingBulk.rows[0]?.planningCycleDate ?? selectedCycle)}</dd></div>
                <div><dt>Principal</dt><dd>{bulkPrincipals}</dd></div>
                <div><dt>Critical</dt><dd>{bulkFigures.critical.toLocaleString()}</dd></div>
                <div><dt>Not in stock count</dt><dd>{bulkFigures.notInCount.toLocaleString()}</dd></div>
              </dl>
              {bulkFigures.notInCount > 0 && (
                <p className="reorder-bulk-warning">
                  <AlertTriangle size={15} aria-hidden="true" />
                  <span>
                    {bulkFigures.notInCount.toLocaleString()} of these {bulkFigures.notInCount === 1 ? 'is' : 'are'} not in the
                    opening stock count, so the plan treats {bulkFigures.notInCount === 1 ? 'it' : 'them'} as 0 on hand. That 0
                    was never counted: confirm the stock before ordering.
                  </span>
                </p>
              )}
              {Object.values(pendingBulk.excluded).some((list) => list.length > 0) && (
                <div className="reorder-bulk-excluded">
                  <strong>Not included</strong>
                  <ul>
                    {pendingBulk.excluded.flagged.length > 0 && (
                      <li>{pendingBulk.excluded.flagged.length.toLocaleString()} flagged for review: accept each from its own row, after checking it.</li>
                    )}
                    {pendingBulk.excluded.noSalesForecast.length > 0 && (
                      <li>{pendingBulk.excluded.noSalesForecast.length.toLocaleString()} with a forecast under 1 piece: accept each from its own row, after checking it.</li>
                    )}
                    {pendingBulk.excluded.openRequest.length > 0 && (
                      <li>{pendingBulk.excluded.openRequest.length.toLocaleString()} with a staff request waiting: settle the request first.</li>
                    )}
                    {pendingBulk.excluded.noOrder.length > 0 && (
                      <li>{pendingBulk.excluded.noOrder.length.toLocaleString()} with nothing to order.</li>
                    )}
                    {pendingBulk.excluded.decided.length > 0 && (
                      <li>{pendingBulk.excluded.decided.length.toLocaleString()} already accepted or dismissed.</li>
                    )}
                  </ul>
                </div>
              )}
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
