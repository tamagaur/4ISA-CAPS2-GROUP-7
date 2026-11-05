import React, { useEffect, useMemo, useState } from 'react';
import {
  X, AlertTriangle, PencilLine, History, CheckCircle2, XOctagon, XCircle, Loader2, ClipboardCheck, Clock3, Inbox, Search, Users,
} from 'lucide-react';
import Modal from './Modal';
import SaveResult from './SaveResult';
import ProductName from './ProductName';
import LoadError from './ui/LoadError';
import { SkeletonTable } from './Skeleton';
import { useSaveResult } from '../utils/useSaveResult';
import { getCurrentUser } from '../auth';
import { labelForPrincipal } from '../principals';
import { formatDateTime, formatMonth } from '../utils/formatDate';
import { formatUnits } from '../utils/formatNumber';
import { ordersNothing } from '../utils/reorderView';
import { REVIEW_REASON_TEXT } from '../utils/reviewReasons';
import {
  approveDismissalRequest, approveQuantityChange, getRecommendationHistory, rejectDismissalRequest, rejectQuantityChange,
  verifyStockObservation,
} from '../api/recommendations';
import {
  EMPTY_COUNT, STATUS_FILTERS, casesAvailable, casesText, differenceText, dismissalWarnings, filterRequests, isStale,
  parseRequestLink, quantityDifference, quantityWarnings, requestId, requesterName, sameQuantity, serverTime, stockCountError,
  stockObservationPayload, toPieces, validateProposedQuantity,
} from '../utils/reorderRequests';
import './OverrideReasonModal.css';
import './ReorderRequests.css';

// Staff requests on the Reorder page (2026-10-28). A staff member with
// lp.propose can't accept or dismiss a recommendation, but can ask for a
// different quantity or for a dismissal; an admin approves or rejects it
// (backend/routers/reorder_approval.py, reorder_requests.py;
// docs/REORDER_APPROVAL_API.md). An admin's own quantity change applies at
// once. Everything here is in PIECES, the unit of the order plan, with the
// case count beside it where the product has a case size. The arithmetic
// (whole cases, warnings, staleness) is utils/reorderRequests.js.

// Reasons need a little detail, as the Dismiss dialog has always asked.
const MIN_REASON = 8;
const reasonOk = (s) => s.trim().length >= MIN_REASON;

// Shown wherever a stock count can be typed or checked: a count is evidence
// for the admin, never a correction to the stock the plan read.
const COUNT_IS_OBSERVATION =
  'A stock count is recorded for an admin to check. It does not change stock on hand or the order plan.';

const piecesWithCases = (pieces, packSize) => {
  if (pieces == null) return '—';
  const cases = casesText(pieces, packSize);
  return `${formatUnits(pieces)} pieces${cases ? ` (${cases})` : ''}`;
};

const when = (value) => {
  const d = serverTime(value);
  return d ? formatDateTime(d) : '—';
};

// ── Stock count (optional, inside the request and dismiss dialogs) ─────────
export function StockCountFields({ value, onChange, packSize, idPrefix, disabled = false }) {
  const set = (key) => (e) => onChange({ ...value, [key]: e.target.value });
  const error = stockCountError(value, packSize);
  const inPieces = value.unit === 'cases' && value.quantity !== '' && !error
    ? toPieces(value.quantity, 'cases', packSize) : null;
  return (
    <details className="rq-count" open={value.quantity !== '' || undefined}>
      <summary>Add a stock count (optional)</summary>
      <p className="rq-help">{COUNT_IS_OBSERVATION}</p>
      <div className="rq-grid">
        <label className="rq-field" htmlFor={`${idPrefix}-count-qty`}>
          <span className="override-label">Counted quantity</span>
          <input
            id={`${idPrefix}-count-qty`}
            className="rq-input"
            type="number"
            inputMode="numeric"
            min="0"
            step="1"
            value={value.quantity}
            onChange={set('quantity')}
            disabled={disabled}
          />
        </label>
        <label className="rq-field" htmlFor={`${idPrefix}-count-unit`}>
          <span className="override-label">Unit</span>
          <select id={`${idPrefix}-count-unit`} className="rq-input" value={value.unit} onChange={set('unit')} disabled={disabled}>
            <option value="pieces">Pieces</option>
            {casesAvailable(packSize) && <option value="cases">Cases of {Number(packSize).toLocaleString()}</option>}
          </select>
        </label>
        <label className="rq-field" htmlFor={`${idPrefix}-count-at`}>
          <span className="override-label">Counted at</span>
          <input id={`${idPrefix}-count-at`} className="rq-input" type="datetime-local" value={value.countedAt} onChange={set('countedAt')} disabled={disabled} />
        </label>
        <label className="rq-field" htmlFor={`${idPrefix}-count-loc`}>
          <span className="override-label">Location</span>
          <input
            id={`${idPrefix}-count-loc`}
            className="rq-input"
            type="text"
            maxLength={120}
            placeholder="e.g., Main warehouse, bay 3"
            value={value.location}
            onChange={set('location')}
            disabled={disabled}
          />
        </label>
      </div>
      <label className="rq-field" htmlFor={`${idPrefix}-count-notes`}>
        <span className="override-label">Notes</span>
        <textarea
          id={`${idPrefix}-count-notes`}
          className="override-textarea"
          rows={2}
          maxLength={500}
          value={value.notes}
          onChange={set('notes')}
          disabled={disabled}
        />
      </label>
      {!casesAvailable(packSize) && (
        <p className="rq-help">This product has no pieces-per-case figure, so the count is in pieces only.</p>
      )}
      {inPieces != null && <p className="rq-help">= {formatUnits(inPieces)} pieces</p>}
      {error && <span className="override-hint-error" role="alert">{error}</span>}
    </details>
  );
}

function WarningList({ warnings }) {
  if (!warnings.length) return null;
  return (
    <div className="rq-warnings" role="note">
      <AlertTriangle size={15} aria-hidden="true" />
      <ul>
        {warnings.map((w) => <li key={w.key}>{w.text}</li>)}
      </ul>
    </div>
  );
}

function ModalHeader({ icon, iconClass = '', title, subtitle, onClose, disabled, titleId }) {
  return (
    <div className="override-modal-header">
      <div className={`override-icon-wrap ${iconClass}`}>{icon}</div>
      <div>
        <h3 className="override-modal-title" id={titleId}>{title}</h3>
        {subtitle && <p className="override-modal-subtitle">{subtitle}</p>}
      </div>
      <button type="button" className="override-modal-close" onClick={onClose} disabled={disabled} aria-label="Close">
        <X size={18} />
      </button>
    </div>
  );
}

// ── Request (or, for an admin, apply) a different quantity ──────────────────
// `directApply`: the caller's change applies at once (admin, or a grant) —
// GET /recommendations/direct-apply-grants/me. Only words the dialog; the
// response's own outcome decides what the result says. `planHasCuts`: some
// row of the plan was cut to fit the supplier allocation.
// onSubmit({quantity, reason, reviewed, stockObservation}) returns the
// server's {outcome, change|item} and throws a RequestError when refused.
export function QuantityChangeModal({ isOpen, item, directApply, planHasCuts, countsReady, onCancel, onSubmit }) {
  const packSize = item?.packSize;
  const [amount, setAmount] = useState('');
  const [unit, setUnit] = useState('pieces');
  const [reason, setReason] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const [count, setCount] = useState(EMPTY_COUNT);
  const [saveError, setSaveError] = useState('');
  // The server's own whole-case alternatives after a 422 not_whole_cases.
  const [serverAlternatives, setServerAlternatives] = useState([]);
  const { saving, result, run, reset } = useSaveResult();

  useEffect(() => {
    if (!isOpen) return;
    setAmount('');
    setUnit(casesAvailable(packSize) ? 'cases' : 'pieces');
    setReason('');
    setReviewed(false);
    setCount(EMPTY_COUNT);
    setSaveError('');
    setServerAlternatives([]);
    reset();
  }, [isOpen, packSize, reset]);

  if (!isOpen || !item) return null;

  const recommended = item.orderQty;
  const pieces = toPieces(amount, unit, packSize);
  const invalid = validateProposedQuantity({ amount, unit, packSize, recommended });
  const diff = invalid ? null : quantityDifference(pieces, recommended);
  const warnings = invalid ? [] : quantityWarnings(item, pieces, { planHasCuts }).filter((w) => w.key !== 'needs_review');
  const countError = directApply ? null : stockCountError(count, packSize);
  const canSubmit = !invalid && reasonOk(reason) && (!item.needsReview || reviewed) && !countError && !saving;
  const alternatives = invalid?.alternatives?.length ? invalid.alternatives : serverAlternatives;

  // Clicking an alternative sets the quantity in pieces: shown, never silently rounded.
  const pickAlternative = (value) => {
    setUnit('pieces');
    setAmount(String(value));
    setServerAlternatives([]);
  };

  const changeUnit = (next) => {
    if (next === unit) return;
    const n = Number(amount);
    if (amount !== '' && Number.isFinite(n)) {
      const converted = next === 'cases' ? n / Number(packSize) : n * Number(packSize);
      setAmount(Number.isInteger(converted) ? String(converted) : amount);
    }
    setUnit(next);
  };

  const handleSubmit = () => {
    setSaveError('');
    run(async () => {
      try {
        return await onSubmit({
          quantity: pieces,
          reason: reason.trim(),
          reviewed: item.needsReview ? reviewed : false,
          stockObservation: directApply ? null : stockObservationPayload(count),
        });
      } catch (err) {
        if (err?.code === 'not_whole_cases') {
          setServerAlternatives([err.extra?.nearest_below, err.extra?.nearest_above].filter((v) => v != null && v >= 0));
        }
        throw err;
      }
    }, {
      onSaved: onCancel,
      onFailed: setSaveError,
      fallbackError: "Couldn't send the quantity change. Please try again.",
    });
  };

  const applied = result?.ok && result.value?.outcome === 'applied';
  const title = directApply ? 'Change quantity' : 'Request quantity change';

  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      labelledBy="rq-qty-title"
      overlayClassName="override-modal-overlay"
      containerClassName="override-modal-card rq-modal-card"
      closeOnOverlayClick={!saving}
      closeOnEscape={!saving}
    >
      {result ? (
        <SaveResult
          ok={result.ok}
          title={result.ok ? (applied ? 'Applied' : 'Sent for approval') : "Couldn't send the change"}
          message={result.ok
            ? (applied
              ? <><strong>{formatUnits(pieces)}</strong> pieces of <strong>{item.product}</strong> are now the accepted order.</>
              : <>An admin will approve or reject <strong>{formatUnits(pieces)}</strong> pieces for <strong>{item.product}</strong>. The recommendation stays as it is until then.</>)
            : result.message}
        />
      ) : (
        <>
          <ModalHeader
            titleId="rq-qty-title"
            icon={<PencilLine size={18} />}
            iconClass="rq-icon-change"
            title={title}
            subtitle={`${item.product} · ${item.sku}${item.principal ? ` · ${labelForPrincipal(item.principal)}` : ''}`}
            onClose={onCancel}
            disabled={saving}
          />
          <div className="override-modal-body">
            <dl className="rq-facts">
              <div>
                <dt>Recommended order</dt>
                <dd>{piecesWithCases(recommended, packSize)}</dd>
              </div>
              <div>
                <dt>Plan</dt>
                <dd>{item.planningCycleDate ? formatMonth(item.planningCycleDate) : '—'}</dd>
              </div>
            </dl>

            <div className="rq-qty-row">
              <label className="rq-field rq-field-grow" htmlFor="rq-qty-amount">
                <span className="override-label">Proposed quantity <span className="override-req">*</span></span>
                <input
                  id="rq-qty-amount"
                  className="rq-input"
                  type="number"
                  inputMode="numeric"
                  min="0"
                  step="1"
                  value={amount}
                  onChange={(e) => { setAmount(e.target.value); setServerAlternatives([]); }}
                  aria-describedby="rq-qty-live"
                  autoFocus
                />
              </label>
              <label className="rq-field" htmlFor="rq-qty-unit">
                <span className="override-label">Unit</span>
                <select id="rq-qty-unit" className="rq-input" value={unit} onChange={(e) => changeUnit(e.target.value)}>
                  {casesAvailable(packSize) && <option value="cases">Cases of {Number(packSize).toLocaleString()}</option>}
                  <option value="pieces">Pieces</option>
                </select>
              </label>
            </div>
            {!casesAvailable(packSize) && (
              <p className="rq-help">
                {packSize == null
                  ? 'This product has no pieces-per-case figure in the product master, so the quantity is in pieces only.'
                  : 'A case of this product is a single piece, so the quantity is in pieces.'}
              </p>
            )}

            <div id="rq-qty-live" className="rq-live" aria-live="polite">
              {pieces != null && !invalid && (
                <>
                  <span>= <strong>{formatUnits(pieces)}</strong> pieces{unit === 'pieces' && casesText(pieces, packSize) ? ` (${casesText(pieces, packSize)})` : ''}</span>
                  <span className={diff?.pieces > 0 ? 'rq-diff-up' : 'rq-diff-down'}>{differenceText(diff)} against the recommendation</span>
                </>
              )}
              {invalid && amount !== '' && <span className="override-hint-error">{invalid.message}</span>}
            </div>
            {alternatives.length > 0 && (
              <div className="rq-alternatives">
                <span>Use a whole number of cases:</span>
                {alternatives.map((v) => (
                  <button type="button" key={v} className="table-btn" onClick={() => pickAlternative(v)}>
                    {piecesWithCases(v, packSize)}
                  </button>
                ))}
              </div>
            )}

            <WarningList warnings={warnings} />

            {item.needsReview && (
              <label className="rq-check">
                <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
                <span>
                  This product is flagged for review before ordering
                  {item.reviewReasons?.length ? ` (${item.reviewReasons.map((r) => REVIEW_REASON_TEXT[r] || r).join('; ')})` : ''}.
                  I have checked this quantity.
                </span>
              </label>
            )}

            <label className="override-label" htmlFor="rq-qty-reason">
              Reason <span className="override-req">*</span>
            </label>
            <textarea
              id="rq-qty-reason"
              className="override-textarea"
              rows={3}
              maxLength={500}
              placeholder="e.g., The supplier only ships this in full pallets this month."
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            {!reasonOk(reason) && reason.length > 0 && (
              <span className="override-hint-error">Please provide a bit more detail (min. {MIN_REASON} characters).</span>
            )}

            {!directApply && countsReady && (
              <StockCountFields value={count} onChange={setCount} packSize={packSize} idPrefix="rq-qty" disabled={saving} />
            )}
            {directApply && (
              <p className="rq-help">
                Your change applies at once as the accepted order.
                {!ordersNothing(item) && ' A stock count can be recorded with a dismissal instead.'}
              </p>
            )}
            {saveError && <span className="override-hint-error" role="alert">{saveError}</span>}
          </div>
          <div className="override-modal-actions">
            <button type="button" className="override-btn override-btn-cancel" onClick={onCancel} disabled={saving}>
              Cancel
            </button>
            <button type="button" className="override-btn override-btn-dismiss" onClick={handleSubmit} disabled={!canSubmit}>
              {saving ? 'Sending…' : directApply ? 'Apply change' : 'Submit for approval'}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

// ── A recommendation's history ──────────────────────────────────────────────
const EVENT_LABEL = {
  recommended: 'Recommended',
  change_proposed: 'Quantity change requested',
  change_approved: 'Quantity change approved',
  change_rejected: 'Quantity change rejected',
  dismissal_requested: 'Dismissal requested',
  dismissal_approved: 'Dismissal approved',
  dismissal_rejected: 'Dismissal rejected',
  decided: 'Decided',
  reversed: 'Decision reversed',
  stock_reported: 'Stock count reported',
  stock_verified: 'Stock count verified',
  stock_rejected: 'Stock count rejected',
};

export function HistoryModal({ isOpen, item, onClose }) {
  const [state, setState] = useState({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const key = item?.id;

  useEffect(() => {
    if (!isOpen || key == null) return undefined;
    let cancelled = false;
    setState({ status: 'loading' });
    getRecommendationHistory(key)
      .then((res) => { if (!cancelled) setState({ status: 'ready', data: res }); })
      .catch((err) => { if (!cancelled) setState({ status: 'error', message: err.message }); });
    return () => { cancelled = true; };
  }, [isOpen, key, attempt]);

  if (!isOpen || !item) return null;
  const pack = state.data?.pack_size ?? item.packSize;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      labelledBy="rq-history-title"
      overlayClassName="override-modal-overlay"
      containerClassName="override-modal-card rq-modal-card"
    >
      <ModalHeader
        titleId="rq-history-title"
        icon={<History size={18} />}
        iconClass="rq-icon-change"
        title="History"
        subtitle={`${item.product} · ${item.sku}`}
        onClose={onClose}
      />
      <div className="override-modal-body">
        {state.status === 'loading' && (
          <p className="rq-muted" role="status"><Loader2 className="spinner-icon" size={14} aria-hidden="true" /> Loading the history…</p>
        )}
        {state.status === 'error' && (
          <p className="rq-muted" role="alert">
            Couldn&apos;t load the history: {state.message}{' '}
            <button type="button" className="link-button" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
          </p>
        )}
        {state.status === 'ready' && (state.data.events || []).length === 0 && (
          <p className="rq-muted">Nothing recorded for this recommendation yet.</p>
        )}
        {state.status === 'ready' && (state.data.events || []).length > 0 && (
          <>
            <p className="rq-help">Oldest first. Times are in your local time. You see every decision, and your own requests and counts{' '}
              (an admin sees everyone&apos;s).</p>
            <ol className="rq-history">
              {state.data.events.map((ev, i) => (
                <li key={`${ev.kind}-${ev.at}-${i}`}>
                  <div className="rq-history-head">
                    <strong>{EVENT_LABEL[ev.kind] || ev.kind}</strong>
                    <span className="rq-muted">{when(ev.at)}{ev.actor ? ` · ${ev.actor}` : ''}</span>
                  </div>
                  <p className="rq-history-summary">{ev.summary}</p>
                  {(ev.quantity_before != null || ev.quantity_after != null) && (
                    <p className="rq-history-qty">
                      {ev.quantity_before != null && <>{piecesWithCases(ev.quantity_before, pack)} → </>}
                      {ev.quantity_after != null ? piecesWithCases(ev.quantity_after, pack) : '—'}
                    </p>
                  )}
                  {ev.reason && <p className="rq-history-reason">Reason: {ev.reason}</p>}
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
      <div className="override-modal-actions">
        <button type="button" className="override-btn override-btn-cancel" onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}

// ── The Staff Requests tab (redesign 2026-10-28) ────────────────────────────
// Summary cards, a searchable table, and one detail panel that shows a
// request and, for an admin who didn't make it, approves or rejects it after
// a confirmation step. All from GET /recommendations/changes and
// /dismissal-requests (useStaffRequests, state=all).

const TYPE_LABEL = { quantity_change: 'Quantity change', dismissal: 'Dismissal' };

function statusPill(item) {
  if (item.state === 'pending_approval') return { label: 'Pending', className: 'pill pill-warning' };
  if (item.state === 'approved') return { label: 'Approved', className: 'pill pill-success' };
  if (item.state === 'rejected') return { label: 'Rejected', className: 'pill pill-critical rq-pill-rejected' };
  return { label: item.state, className: 'pill pill-neutral' };
}

function StatusBadges({ item, stale }) {
  const s = statusPill(item);
  return (
    <span className="rq-badges">
      <span className={s.className}>{s.label}</span>
      {stale && (
        <span className="pill pill-critical" title="The plan’s quantity changed since this was asked. It can’t be approved.">Stale</span>
      )}
      {item.reversed_at && (
        <span className="pill pill-neutral" title={`Reversed${item.reversed_by ? ` by ${item.reversed_by}` : ''} on ${when(item.reversed_at)}`}>
          Reversed
        </span>
      )}
    </span>
  );
}

const VERIFY_LABEL = { unverified: 'Unverified', verified: 'Verified', rejected: 'Count rejected' };

function ObservationLine({ obs, isAdmin, onVerify }) {
  if (!obs) return null;
  const typed = obs.unit_entered === 'cases'
    ? `${Number(obs.quantity_entered).toLocaleString()} cases = ${formatUnits(obs.quantity_pieces)} pieces`
    : `${formatUnits(obs.quantity_pieces)} pieces`;
  return (
    <div className="rq-obs">
      <span className="rq-obs-main">
        <strong>{typed}</strong>
        {obs.counted_at ? `, counted ${when(obs.counted_at)}` : ''}
        {obs.location ? ` at ${obs.location}` : ''}
      </span>
      <span className={`pill ${obs.verification_state === 'verified' ? 'pill-success' : obs.verification_state === 'rejected' ? 'pill-critical' : 'pill-neutral'}`}>
        {VERIFY_LABEL[obs.verification_state] || obs.verification_state}
      </span>
      {obs.notes && <span className="rq-muted">“{obs.notes}”</span>}
      {obs.verification_note && <span className="rq-muted">Check: {obs.verification_note}</span>}
      {isAdmin && obs.verification_state === 'unverified' && onVerify && (
        <span className="rq-obs-actions">
          <button type="button" className="table-btn" onClick={() => onVerify(obs, true)}>Mark verified</button>
          <button type="button" className="table-btn table-btn-quiet" onClick={() => onVerify(obs, false)}>Mark rejected</button>
        </span>
      )}
    </div>
  );
}

// A stock count's verification: a note, required when the count is rejected.
function NoteModal({ title, subtitle, icon, iconClass, intro, label, required, confirmLabel, successTitle, onCancel, onConfirm }) {
  const [note, setNote] = useState('');
  const [saveError, setSaveError] = useState('');
  const { saving, result, run } = useSaveResult();
  const valid = required ? reasonOk(note) : true;

  const handleConfirm = () => {
    setSaveError('');
    run(() => onConfirm(note.trim()), {
      onSaved: onCancel,
      onFailed: setSaveError,
      fallbackError: "Couldn't save. Please try again.",
    });
  };

  return (
    <Modal
      isOpen
      onClose={onCancel}
      labelledBy="rq-note-title"
      overlayClassName="override-modal-overlay"
      containerClassName="override-modal-card"
      closeOnOverlayClick={!saving}
      closeOnEscape={!saving}
    >
      {result ? (
        <SaveResult ok={result.ok} title={result.ok ? successTitle : "Couldn't save"} message={result.ok ? null : result.message} />
      ) : (
        <>
          <ModalHeader titleId="rq-note-title" icon={icon} iconClass={iconClass} title={title} subtitle={subtitle} onClose={onCancel} disabled={saving} />
          <div className="override-modal-body">
            {intro && <p className="override-modal-copy">{intro}</p>}
            <label className="override-label" htmlFor="rq-note-text">
              {label} {required && <span className="override-req">*</span>}
            </label>
            <textarea
              id="rq-note-text"
              className="override-textarea"
              rows={3}
              maxLength={500}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              autoFocus
            />
            {required && !valid && note.length > 0 && (
              <span className="override-hint-error">Please provide a bit more detail (min. {MIN_REASON} characters).</span>
            )}
            {saveError && <span className="override-hint-error" role="alert">{saveError}</span>}
          </div>
          <div className="override-modal-actions">
            <button type="button" className="override-btn override-btn-cancel" onClick={onCancel} disabled={saving}>Cancel</button>
            <button type="button" className="override-btn override-btn-dismiss" onClick={handleConfirm} disabled={!valid || saving}>
              {saving ? 'Saving…' : confirmLabel}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

function Fact({ label, children, wide = false }) {
  return (
    <div className={wide ? 'rq-fact-wide' : undefined}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Person({ item }) {
  return (
    <span className="rq-person">
      <span className="rq-person-name">{requesterName(item)}</span>
      {item.byName && item.by && <span className="rq-person-email">{item.by}</span>}
    </span>
  );
}

// One request, read-only or (an admin, not the requester, still pending)
// with Approve / Reject. Each decision goes through a confirmation step:
// approval shows the warnings again and needs them ticked; rejection needs a
// reason (the server requires one). `onApprove` / `onReject` throw the
// server's RequestError; a 409 (decided meanwhile, plan changed, own
// request) returns the panel to its details with the message, and the list
// reloads so the panel shows the request as it now is.
function RequestPanel({
  item, row, isAdmin, own, stale, planHasCuts, onClose, onApprove, onReject, onVerify, onOpenHistory,
}) {
  const [step, setStep] = useState('view'); // 'view' | 'approve' | 'reject'
  const [lastAction, setLastAction] = useState('approve');
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('');
  const [ack, setAck] = useState(false);
  const [saveError, setSaveError] = useState('');
  const { saving, result, run } = useSaveResult();

  const id = requestId(item);
  const isDismissal = item.kind === 'dismissal';
  const pending = item.state === 'pending_approval';
  const decidable = isAdmin && pending && !own;
  const shownStep = decidable ? step : 'view';
  const pack = row?.packSize ?? item.stock_observation?.pieces_per_case ?? null;
  const diff = isDismissal ? null : quantityDifference(item.proposed, item.recommended_q_i);
  const warnings = row && decidable
    ? (isDismissal ? dismissalWarnings(row) : quantityWarnings(row, item.proposed, { planHasCuts }))
    : [];
  const canConfirmApprove = !saving && !stale && (warnings.length === 0 || ack);
  const canConfirmReject = !saving && reasonOk(reason);

  const submit = (action, kind, fallbackError) => {
    setSaveError('');
    setLastAction(kind);
    run(async () => {
      try {
        return await action();
      } catch (err) {
        if (err?.status === 409) setStep('view');
        throw err;
      }
    }, { onSaved: onClose, onFailed: setSaveError, fallbackError });
  };

  const approve = () => submit(() => onApprove(item, note.trim()), 'approve', "Couldn't approve the request. Please try again.");
  const reject = () => submit(() => onReject(item, reason.trim()), 'reject', "Couldn't reject the request. Please try again.");

  const rejecting = lastAction === 'reject';
  const resultTitle = result?.ok
    ? (rejecting ? 'Request rejected' : 'Request approved')
    : (rejecting ? "Couldn't reject" : "Couldn't approve");
  let resultMessage = result?.message;
  if (result?.ok) {
    if (rejecting) {
      resultMessage = <>{id} is rejected. The recommendation for <strong>{item.product_name}</strong> stays as the plan suggested it.</>;
    } else if (isDismissal) {
      resultMessage = <><strong>{item.product_name}</strong> is dismissed for this plan.</>;
    } else {
      resultMessage = <><strong>{formatUnits(item.proposed)}</strong> pieces of <strong>{item.product_name}</strong> are now the accepted order.</>;
    }
  }

  let title = `Request ${id}`;
  if (shownStep === 'approve') title = `Confirm approval of ${id}`;
  else if (shownStep === 'reject') title = `Reject ${id}`;
  else if (decidable) title = `Review request ${id}`;
  let icon = <Inbox size={18} />;
  let iconClass = 'rq-icon-change';
  if (shownStep === 'approve') { icon = <CheckCircle2 size={18} />; iconClass = 'rq-icon-approve'; }
  if (shownStep === 'reject') { icon = <XOctagon size={18} />; iconClass = 'override-icon-dismiss'; }

  return (
    <Modal
      isOpen
      onClose={onClose}
      labelledBy="rq-panel-title"
      overlayClassName="override-modal-overlay"
      containerClassName="override-modal-card rq-modal-card rq-panel"
      closeOnOverlayClick={!saving}
      closeOnEscape={!saving}
    >
      {result ? (
        <SaveResult ok={result.ok} title={resultTitle} message={resultMessage} />
      ) : (
        <>
          <ModalHeader
            titleId="rq-panel-title"
            icon={icon}
            iconClass={iconClass}
            title={title}
            subtitle={`${item.product_name || 'Unknown Product'} · ${item.sku_code || '—'}`}
            onClose={onClose}
            disabled={saving}
          />
          <div className="override-modal-body">
            {shownStep === 'view' && (
              <>
                <dl className="rq-facts rq-panel-facts">
                  <Fact label="Request ID"><span className="rq-id">{id}</span></Fact>
                  <Fact label="Status"><StatusBadges item={item} stale={stale} /></Fact>
                  <Fact label="Staff member"><Person item={item} /></Fact>
                  <Fact label="Submitted">{when(item.at)}</Fact>
                  <Fact label="Request type">{TYPE_LABEL[item.kind] || item.kind}</Fact>
                  <Fact label="Plan">{item.planning_cycle_date ? formatMonth(item.planning_cycle_date) : '—'}</Fact>
                  <Fact label="Product" wide>
                    <ProductName name={item.product_name || 'Unknown Product'} code={item.sku_code || '—'} />
                  </Fact>
                </dl>

                <div className="rq-compare">
                  <div>
                    <span className="rq-compare-label">Recommended when asked</span>
                    <span className="rq-compare-value">{piecesWithCases(item.recommended_q_i, pack)}</span>
                    {row && row.orderQty != null && !sameQuantity(row.orderQty, item.recommended_q_i) && (
                      <span className="rq-compare-note">The plan now says {piecesWithCases(row.orderQty, pack)}</span>
                    )}
                  </div>
                  <div>
                    <span className="rq-compare-label">{isDismissal ? 'Requested' : 'Requested quantity'}</span>
                    <span className="rq-compare-value">{isDismissal ? 'Order nothing (dismiss)' : piecesWithCases(item.proposed, pack)}</span>
                  </div>
                  {!isDismissal && (
                    <div>
                      <span className="rq-compare-label">Difference</span>
                      <span className="rq-compare-value">{differenceText(diff)}</span>
                    </div>
                  )}
                  {isDismissal && row && (
                    <div>
                      <span className="rq-compare-label">Opening / target stock</span>
                      <span className="rq-compare-value">{formatUnits(row.stock)} / {formatUnits(row.rop)} pieces</span>
                    </div>
                  )}
                </div>

                <div className="rq-block">
                  <span className="rq-obs-label">Staff justification</span>
                  <p className="rq-block-text">{item.reason || <span className="cell-empty">No reason recorded.</span>}</p>
                </div>

                {item.stock_observation && (
                  <div className="rq-block">
                    <span className="rq-obs-label">Attached stock count</span>
                    <ObservationLine obs={item.stock_observation} isAdmin={isAdmin} onVerify={onVerify} />
                    <p className="rq-help">{COUNT_IS_OBSERVATION}</p>
                  </div>
                )}

                {stale && (
                  <p className="rq-stale" role="note">
                    The order plan&apos;s quantity for this product is now {piecesWithCases(row?.orderQty, pack)}, not the{' '}
                    {piecesWithCases(item.recommended_q_i, pack)} this request was made against. It can&apos;t be approved: reject it
                    and ask for it again against the current plan.
                  </p>
                )}
                {decidable && !row && (
                  <p className="rq-help">
                    This product isn&apos;t in the plan on screen (another principal or an older cycle), so its warnings can&apos;t be
                    worked out here. The server still checks the quantity when you approve.
                  </p>
                )}
                {decidable && <WarningList warnings={warnings} />}

                {!pending && (item.resolved_by || item.resolved_at) && (
                  <div className="rq-block rq-decision">
                    <span className="rq-obs-label">Decision</span>
                    <p className="rq-block-text">
                      {item.state === 'rejected' ? 'Rejected' : 'Approved'}
                      {item.resolved_by ? ` by ${item.resolved_by}` : ''}
                      {item.resolved_at ? ` on ${when(item.resolved_at)}` : ''}.
                    </p>
                    {item.resolution_note && (
                      <p className="rq-block-text">
                        <span className="rq-muted-inline">{item.state === 'rejected' ? 'Reason: ' : 'Admin remarks: '}</span>
                        {item.resolution_note}
                      </p>
                    )}
                    {item.reversed_at && (
                      <p className="rq-block-text">
                        Later reversed{item.reversed_by ? ` by ${item.reversed_by}` : ''} on {when(item.reversed_at)}.
                      </p>
                    )}
                  </div>
                )}

                {isAdmin && pending && own && (
                  <p className="rq-self" role="note">You can&apos;t decide your own request. Another admin approves or rejects it.</p>
                )}
              </>
            )}

            {shownStep === 'approve' && (
              <>
                <p className="override-modal-copy">
                  {isDismissal
                    ? <>Approving dismisses <strong>{item.product_name}</strong> for this plan, as {requesterName(item)} asked.</>
                    : <>Approving makes <strong>{piecesWithCases(item.proposed, pack)}</strong> the accepted order for{' '}
                      <strong>{item.product_name}</strong>, instead of {piecesWithCases(item.recommended_q_i, pack)} ({differenceText(diff)}).</>}
                </p>
                {!row && <p className="rq-help">This product isn&apos;t in the plan on screen, so no warnings could be worked out here.</p>}
                <WarningList warnings={warnings} />
                {warnings.length > 0 && (
                  <label className="rq-check">
                    <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} disabled={saving} />
                    <span>I have reviewed these warnings.</span>
                  </label>
                )}
                <label className="override-label" htmlFor="rq-approve-note">Admin remarks (optional)</label>
                <textarea
                  id="rq-approve-note"
                  className="override-textarea"
                  rows={3}
                  maxLength={500}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  disabled={saving}
                />
              </>
            )}

            {shownStep === 'reject' && (
              <>
                <p className="override-modal-copy">
                  The recommendation stays as the order plan suggested it, still waiting for a decision. Your reason is shown to{' '}
                  {requesterName(item)}.
                </p>
                <label className="override-label" htmlFor="rq-reject-reason">
                  Reason for rejection (required) <span className="override-req">*</span>
                </label>
                <textarea
                  id="rq-reject-reason"
                  className="override-textarea"
                  rows={3}
                  maxLength={500}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  disabled={saving}
                  aria-required="true"
                />
                {!reasonOk(reason) && reason.length > 0 && (
                  <span className="override-hint-error">Please provide a bit more detail (min. {MIN_REASON} characters).</span>
                )}
              </>
            )}

            {saveError && <p className="override-hint-error rq-save-error" role="alert">{saveError}</p>}
          </div>

          <div className="override-modal-actions rq-panel-actions">
            {shownStep === 'view' && onOpenHistory && (
              <button type="button" className="link-button rq-history-link" onClick={() => onOpenHistory(item)}>
                <History size={14} aria-hidden="true" /> History
              </button>
            )}
            {shownStep === 'view' && decidable && (
              <>
                <button type="button" className="override-btn override-btn-cancel" onClick={() => { setSaveError(''); setStep('reject'); }}>
                  Reject Request
                </button>
                <button
                  type="button"
                  className="override-btn override-btn-dismiss"
                  onClick={() => { setSaveError(''); setStep('approve'); }}
                  disabled={stale === true}
                  title={stale ? 'Stale: the plan’s quantity changed since this was asked. Reject it instead.' : undefined}
                >
                  Approve Request
                </button>
              </>
            )}
            {shownStep === 'view' && !decidable && (
              <button type="button" className="override-btn override-btn-cancel" onClick={onClose}>Close</button>
            )}
            {shownStep === 'approve' && (
              <>
                <button type="button" className="override-btn override-btn-cancel" onClick={() => setStep('view')} disabled={saving}>Back</button>
                <button type="button" className="override-btn override-btn-dismiss" onClick={approve} disabled={!canConfirmApprove}>
                  {saving ? 'Approving…' : 'Confirm approval'}
                </button>
              </>
            )}
            {shownStep === 'reject' && (
              <>
                <button type="button" className="override-btn override-btn-cancel" onClick={() => setStep('view')} disabled={saving}>Back</button>
                <button type="button" className="override-btn override-btn-dismiss" onClick={reject} disabled={!canConfirmReject}>
                  {saving ? 'Rejecting…' : 'Confirm rejection'}
                </button>
              </>
            )}
          </div>
        </>
      )}
    </Modal>
  );
}

const SUMMARY_CARDS = [
  { value: 'pending_approval', label: 'Pending Approval', tone: 'pending', Icon: Clock3 },
  { value: 'approved', label: 'Approved', tone: 'approved', Icon: CheckCircle2 },
  { value: 'rejected', label: 'Rejected', tone: 'rejected', Icon: XCircle },
];

// The three counts, from every request loaded (not the filter); clicking one
// filters the table to it, clicking it again shows all.
function SummaryCards({ counts, isAdmin, filter, onFilterChange }) {
  const caption = {
    pending_approval: isAdmin ? 'Waiting for an admin decision' : 'Your requests waiting for an admin',
    approved: isAdmin ? 'Approved by an admin' : 'Your requests an admin approved',
    rejected: isAdmin ? 'Recommendation left as planned' : 'Your requests an admin rejected',
  };
  return (
    <div className="rq-summary" role="group" aria-label="Requests by status">
      {SUMMARY_CARDS.map(({ value, label, tone, Icon }) => (
        <button
          type="button"
          key={value}
          className={`rq-summary-card rq-tone-${tone}`}
          aria-pressed={filter === value}
          onClick={() => onFilterChange(filter === value ? 'all' : value)}
        >
          <span className="rq-summary-icon" aria-hidden="true"><Icon size={16} /></span>
          <span className="rq-summary-text">
            <span className="rq-summary-label">{label}</span>
            <span className="rq-summary-value">{counts[value].toLocaleString()}</span>
            <span className="rq-summary-caption">{caption[value]}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

function emptyText({ filter, query, isAdmin }) {
  if (query.trim()) return `No requests match “${query.trim()}”.`;
  if (filter === 'pending_approval') return isAdmin ? 'No requests are waiting for a decision.' : 'None of your requests are waiting for a decision.';
  if (filter === 'approved') return isAdmin ? 'No requests have been approved yet.' : 'None of your requests have been approved yet.';
  if (filter === 'rejected') return isAdmin ? 'No requests have been rejected.' : 'None of your requests have been rejected.';
  return isAdmin
    ? 'No requests have been made yet.'
    : 'You haven’t made any requests yet. Use “Request quantity change” or “Request dismissal” on a row of the plan.';
}

function RequestTable({ items, canReview, staleFor, onOpen }) {
  return (
    <div className="data-table-card rq-table-card">
      <table className="data-table rq-table">
        <caption className="visually-hidden">Staff requests</caption>
        <thead>
          <tr>
            <th scope="col" className="table-center">Request ID</th>
            <th scope="col" className="table-center">Staff member</th>
            <th scope="col" className="table-center">Request type</th>
            <th scope="col" className="cell-product">Product</th>
            <th scope="col" className="table-center">Date submitted</th>
            <th scope="col" className="table-center">Status</th>
            <th scope="col" className="table-center">Action</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const review = canReview(item);
            return (
              <tr key={item.key}>
                <td data-label="Request ID" className="table-center"><span className="rq-id">{requestId(item)}</span></td>
                <td data-label="Staff member" className="table-center"><Person item={item} /></td>
                <td data-label="Request type" className="table-center">{TYPE_LABEL[item.kind] || item.kind}</td>
                <td data-label="Product" className="cell-product rq-cell-product">
                  <ProductName name={item.product_name || 'Unknown Product'} code={item.sku_code || '—'} />
                </td>
                <td data-label="Date submitted" className="table-center rq-cell-date">{when(item.at)}</td>
                <td data-label="Status" className="table-center"><StatusBadges item={item} stale={staleFor(item)} /></td>
                <td data-label="Action" className="table-center rq-cell-action">
                  <button
                    type="button"
                    className={`table-btn${review ? ' table-btn-primary' : ''}`}
                    onClick={() => onOpen(item)}
                    aria-label={`${review ? 'Review' : 'View details of'} request ${requestId(item)}`}
                  >
                    {review ? 'Review' : 'View details'}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// The tab itself. `rowsByKey`: the plan rows on the page, by
// recommendation_key, for the warnings and the stale check. onResolved(item,
// 'approved' | 'rejected') lets the page update the row and its badges.
// `filter`: 'all' | 'pending_approval' | 'approved' | 'rejected', kept by the
// page so it survives a tab switch. `linkRequest` (the ?request= deep link,
// e.g. quantity_change-7) opens that request's panel once the list has
// loaded; `onLinkHandled` then drops it from the URL.
export function StaffRequestsTab({
  requests, isAdmin, filter, onFilterChange, rowsByKey, planHasCuts, onResolved, onOpenHistory, linkRequest, onLinkHandled,
}) {
  const [openKey, setOpenKey] = useState(null);
  const [snapshot, setSnapshot] = useState(null); // the item as opened, in case a reload drops it
  const [verifying, setVerifying] = useState(null); // { obs, verified }
  const [query, setQuery] = useState('');
  const [linkNotice, setLinkNotice] = useState('');
  // Requests the server called stale (409 recommendation_changed) this visit,
  // e.g. when the row isn't on the page for the client-side check.
  const [serverStale, setServerStale] = useState(() => new Set());
  const me = getCurrentUser()?.email || '';
  const ready = requests.status === 'ready';
  const items = useMemo(() => (ready ? requests.items || [] : []), [ready, requests.items]);
  const counts = requests.counts || { all: 0, pending_approval: 0, approved: 0, rejected: 0 };

  const isOwn = (item) => Boolean(me) && (item.by || '').toLowerCase() === me.toLowerCase();
  const canReview = (item) => isAdmin && item.state === 'pending_approval' && !isOwn(item);
  const staleFor = (item) => {
    if (item.state !== 'pending_approval') return false;
    if (serverStale.has(item.key)) return true;
    return isStale(item, rowsByKey.get(item.recommendation_key)) === true;
  };

  // The deep link: once the list is in (or failed), open the request or say why not.
  useEffect(() => {
    if (!linkRequest || requests.status === 'loading' || requests.status === 'off') return;
    const target = parseRequestLink(linkRequest);
    const found = target && requests.status === 'ready' ? (requests.items || []).find((r) => r.key === target.key) : null;
    if (found) {
      setOpenKey(found.key);
      setSnapshot(found);
      setLinkNotice('');
    } else if (requests.status === 'ready') {
      setLinkNotice(target
        ? 'The request in that link isn’t in this list. It may have been made by someone else, or no longer exist.'
        : 'That link doesn’t point to a request.');
    }
    onLinkHandled?.();
  }, [linkRequest, requests.status, requests.items, onLinkHandled]);

  const shown = useMemo(() => filterRequests(items, { status: filter, query }), [items, filter, query]);

  const shownObservationKeys = useMemo(() => new Set(
    items.map((r) => r.stock_observation?.observation_key).filter((k) => k != null),
  ), [items]);
  const otherObservations = (requests.observations || []).filter((o) => !shownObservationKeys.has(o.observation_key));

  const open = (item) => { setOpenKey(item.key); setSnapshot(item); };
  const close = () => { setOpenKey(null); setSnapshot(null); };
  // The list's copy, so a reload after a 409 shows the request as it is now.
  const openItem = openKey ? (items.find((r) => r.key === openKey) || snapshot) : null;

  // A 409: the request moved under us (decided by someone else, the plan's
  // quantity changed, or it is the admin's own). Reload the list.
  const onConflict = (item, err) => {
    if (err?.code === 'recommendation_changed') setServerStale((prev) => new Set(prev).add(item.key));
    if (err?.status === 409) requests.reload();
  };

  const approve = async (item, note) => {
    try {
      if (item.kind === 'dismissal') await approveDismissalRequest(item.request_key, note);
      else await approveQuantityChange(item.change_key, note);
    } catch (err) {
      onConflict(item, err);
      throw err;
    }
    onResolved(item, 'approved');
  };

  const reject = async (item, reason) => {
    try {
      if (item.kind === 'dismissal') await rejectDismissalRequest(item.request_key, reason);
      else await rejectQuantityChange(item.change_key, reason);
    } catch (err) {
      onConflict(item, err);
      throw err;
    }
    onResolved(item, 'rejected');
  };

  const verify = async (obs, verified, note) => {
    await verifyStockObservation(obs.observation_key, { verified, note });
    requests.reload();
  };
  // One dialog at a time: the panel closes for the verification dialog.
  const startVerify = (obs, verified) => { close(); setVerifying({ obs, verified }); };

  const heading = isAdmin ? 'Staff requests' : 'My requests';
  const lede = isAdmin
    ? 'Quantity changes and dismissals staff asked for. Nothing changes in the order plan until an admin approves it.'
    : 'The quantity changes and dismissals you asked for, and what an admin decided.';

  let body;
  if (requests.status === 'loading') {
    body = (
      <>
        <p className="rq-muted rq-loading" role="status"><Loader2 className="spinner-icon" size={14} aria-hidden="true" /> Loading requests…</p>
        <div className="data-table-card" aria-hidden="true"><SkeletonTable rows={5} columns={7} /></div>
      </>
    );
  } else if (requests.status === 'error') {
    body = <LoadError what="the staff requests" message={requests.message} onRetry={requests.reload} />;
  } else if (ready && !requests.changesReady) {
    body = <div className="rq-empty-card"><Inbox size={20} aria-hidden="true" /><p className="rq-muted">Staff requests are not set up on this server yet.</p></div>;
  } else if (ready) {
    body = (
      <>
        <SummaryCards counts={counts} isAdmin={isAdmin} filter={filter} onFilterChange={onFilterChange} />
        {!requests.dismissalsReady && (
          <p className="rq-help">Dismissal requests and stock counts are not set up on this server yet; quantity changes are listed.</p>
        )}
        <div className="rq-toolbar">
          <label className="filter-search rq-search">
            <Search size={15} aria-hidden="true" />
            <span className="visually-hidden">Search requests</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={isAdmin ? 'Search staff, product, SKU or request ID' : 'Search product, SKU or request ID'}
            />
          </label>
          <div className="segmented rq-status-filter" role="group" aria-label="Filter by status">
            {STATUS_FILTERS.map((f) => (
              <button
                type="button"
                key={f.value}
                className="segmented-item"
                aria-pressed={filter === f.value}
                onClick={() => onFilterChange(f.value)}
              >
                {f.label}
                <span className="segmented-count">{counts[f.value].toLocaleString()}</span>
              </button>
            ))}
          </div>
          {requests.refreshing && (
            <span className="rq-muted" role="status"><Loader2 className="spinner-icon" size={13} aria-hidden="true" /> Updating…</span>
          )}
        </div>
        {shown.length === 0 ? (
          <div className="rq-empty-card">
            <Inbox size={20} aria-hidden="true" />
            <p className="rq-muted">{emptyText({ filter, query, isAdmin })}</p>
          </div>
        ) : (
          <RequestTable items={shown} canReview={canReview} staleFor={staleFor} onOpen={open} />
        )}
        {isAdmin && otherObservations.length > 0 && (
          <section className="rq-other-obs" aria-labelledby="rq-other-obs-title">
            <div className="rq-other-obs-head">
              <ClipboardCheck size={16} aria-hidden="true" />
              <h3 className="rq-subheading" id="rq-other-obs-title">Stock counts awaiting verification</h3>
              <span className="pill pill-neutral">{otherObservations.length}</span>
            </div>
            <p className="rq-help">Sent with a direct dismissal or a request not listed above. {COUNT_IS_OBSERVATION}</p>
            <ul className="rq-obs-list">
              {otherObservations.map((obs) => (
                <li key={obs.observation_key}>
                  <ProductName name={obs.product_name || 'Unknown Product'} code={obs.sku_code || '—'} />
                  <p className="rq-help rq-obs-by">Reported by {obs.reported_by} on {when(obs.reported_at)}.</p>
                  <ObservationLine obs={obs} isAdmin onVerify={(o, verified) => setVerifying({ obs: o, verified })} />
                </li>
              ))}
            </ul>
          </section>
        )}
      </>
    );
  }

  return (
    <section className="rq-tab ui-card" aria-labelledby="rq-tab-title">
      <div className="ui-card-head">
        <span className="icon-tile" aria-hidden="true"><Users size={20} /></span>
        <div className="ui-card-head-text rq-tab-head">
          <h2 className="rq-subheading" id="rq-tab-title">{heading}</h2>
          <p className="rq-tab-lede">{lede}</p>
        </div>
      </div>
      {linkNotice && (
        <div className="rq-link-notice" role="status">
          <AlertTriangle size={15} aria-hidden="true" />
          <span>{linkNotice}</span>
          <button type="button" className="rq-link-notice-close" onClick={() => setLinkNotice('')} aria-label="Dismiss notice">
            <X size={15} />
          </button>
        </div>
      )}
      {body}

      {openItem && (
        <RequestPanel
          key={openItem.key}
          item={openItem}
          row={rowsByKey.get(openItem.recommendation_key)}
          isAdmin={isAdmin}
          own={isOwn(openItem)}
          stale={staleFor(openItem)}
          planHasCuts={planHasCuts}
          onClose={close}
          onApprove={approve}
          onReject={reject}
          onVerify={startVerify}
          onOpenHistory={onOpenHistory ? (item) => { close(); onOpenHistory(item); } : undefined}
        />
      )}
      {verifying && (
        <NoteModal
          title={verifying.verified ? 'Mark this stock count verified' : 'Reject this stock count'}
          subtitle={`${formatUnits(verifying.obs.quantity_pieces)} pieces, reported by ${verifying.obs.reported_by}`}
          icon={<ClipboardCheck size={18} />}
          iconClass={verifying.verified ? 'rq-icon-approve' : 'override-icon-dismiss'}
          intro={`This records that you checked the count. ${COUNT_IS_OBSERVATION}`}
          label={verifying.verified ? 'Note (optional)' : 'Why the count is rejected'}
          required={!verifying.verified}
          confirmLabel={verifying.verified ? 'Mark verified' : 'Reject count'}
          successTitle="Check recorded"
          onCancel={() => setVerifying(null)}
          onConfirm={(note) => verify(verifying.obs, verifying.verified, note)}
        />
      )}
    </section>
  );
}
