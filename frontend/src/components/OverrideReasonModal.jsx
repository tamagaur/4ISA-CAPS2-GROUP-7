import React, { useState, useEffect } from 'react';
import { X, XOctagon } from 'lucide-react';
import Modal from './Modal';
import SaveResult from './SaveResult';
import { useSaveResult } from '../utils/useSaveResult';
import { formatUnits } from '../utils/formatNumber';
import { formatMonth } from '../utils/formatDate';
import { StockCountFields } from './ReorderRequests';
import { EMPTY_COUNT, stockCountError, stockObservationPayload } from '../utils/reorderRequests';
import './OverrideReasonModal.css';

// Story #82/#93: capturing a reason whenever a user dismisses the LP
// recommendation, so the override is auditable — who, when, why — rather
// than a silent status flip. Only two decision states exist end to end
// (LP_Recommendation.status CHECK IN ('pending','accepted','dismissed') in
// schema.sql) — Accept needs no reason, Dismiss always does.
//
// onConfirm(reason) saves the decision and throws when it fails; the dialog
// shows a green check (then closes through onCancel) or a red X (then comes
// back with the reason still typed, to try again).
//
// 2026-10-28, staff requests: mode 'request' is the same dialog for a staff
// member who can't dismiss, asking an admin to (POST
// /recommendations/{key}/dismissal-request); it also shows the row's opening
// and target stock. allowStockCount adds the optional stock count section
// (only once the server has migration 0070). onConfirm(reason,
// stockObservation) — the second argument is null when no count was typed.
const OverrideReasonModal = ({ isOpen, item, onCancel, onConfirm, mode = 'direct', allowStockCount = false }) => {
  const [reason, setReason] = useState('');
  const [count, setCount] = useState(EMPTY_COUNT);
  const [saveError, setSaveError] = useState('');
  const { saving, result, run, reset } = useSaveResult();

  useEffect(() => {
    if (isOpen) {
      setReason('');
      setCount(EMPTY_COUNT);
      setSaveError('');
      reset();
    }
  }, [isOpen, reset]);

  if (!isOpen || !item) return null;

  const isRequest = mode === 'request';
  const countError = allowStockCount ? stockCountError(count, item.packSize) : null;
  const isValid = reason.trim().length >= 8 && !countError;

  const handleConfirm = () => {
    setSaveError('');
    run(() => onConfirm(reason.trim(), allowStockCount ? stockObservationPayload(count) : null), {
      onSaved: onCancel,
      onFailed: setSaveError,
      fallbackError: "Couldn't save the decision. Please try again.",
    });
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      label={isRequest ? 'Request dismissal' : 'Dismiss recommendation'}
      overlayClassName="override-modal-overlay"
      containerClassName="override-modal-card"
      closeOnOverlayClick={!saving}
      closeOnEscape={!saving}
    >
      {result ? (
        <SaveResult
          ok={result.ok}
          title={result.ok
            ? (isRequest ? 'Dismissal requested' : 'Recommendation dismissed')
            : (isRequest ? "Couldn't send the request" : "Couldn't save the decision")}
          message={result.ok
            ? (isRequest
              ? <>An admin will approve or reject dismissing <strong>{item.product}</strong> ({item.sku}). It stays pending until then.</>
              : <>Your reason for <strong>{item.product}</strong> ({item.sku}) is in the decision log.</>)
            : result.message}
        />
      ) : (
        <>
          <div className="override-modal-header">
            <div className="override-icon-wrap override-icon-dismiss">
              <XOctagon size={18} />
            </div>
            <div>
              <h3 className="override-modal-title">{isRequest ? 'Request dismissal' : 'Dismiss recommendation'}</h3>
              {/* Name first, then the code (Sir Catubag, 2 Oct 2026). */}
              <p className="override-modal-subtitle">{item.product} · {item.sku}</p>
            </div>
            <button className="override-modal-close" onClick={onCancel} disabled={saving} aria-label="Close modal">
              <X size={18} />
            </button>
          </div>

          <div className="override-modal-body">
            {isRequest ? (
              <>
                <p className="override-modal-copy">
                  You&apos;re asking an admin to dismiss the order plan&apos;s suggested order of{' '}
                  <strong>{formatUnits(item.orderQty)} pieces</strong>
                  {item.planningCycleDate ? ` for the ${formatMonth(item.planningCycleDate)} plan` : ''}. Nothing changes until an
                  admin approves it; your reason goes with the request.
                </p>
                <dl className="rq-facts">
                  <div><dt>Opening stock</dt><dd>{item.stock != null ? `${formatUnits(item.stock)} pieces` : '—'}</dd></div>
                  <div><dt>Target stock</dt><dd>{item.rop != null ? `${formatUnits(item.rop)} pieces` : '—'}</dd></div>
                </dl>
              </>
            ) : (
              <p className="override-modal-copy">
                You're dismissing the order plan's suggested order of <strong>{formatUnits(item.orderQty)} pieces</strong>
                {item.planningCycleDate ? ` for the ${formatMonth(item.planningCycleDate)} plan` : ''}.
                This deviation is recorded in the decision log against your account so the reasoning is available for review.
              </p>
            )}

            <label className="override-label" htmlFor="override-reason">
              REASON <span className="override-req">*</span>
            </label>
            <textarea
              id="override-reason"
              className="override-textarea"
              rows={3}
              placeholder="e.g., Supplier out of stock this cycle, reordering next week instead."
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              // PATCH /recommendations rejects a reason over 500 characters.
              maxLength={500}
              autoFocus
            />
            {reason.trim().length < 8 && reason.length > 0 && (
              <span className="override-hint-error">Please provide a bit more detail (min. 8 characters).</span>
            )}
            {allowStockCount && (
              <StockCountFields value={count} onChange={setCount} packSize={item.packSize} idPrefix="override" disabled={saving} />
            )}
            {saveError && <span className="override-hint-error" role="alert">{saveError}</span>}
          </div>

          <div className="override-modal-actions">
            <button className="override-btn override-btn-cancel" onClick={onCancel} disabled={saving}>
              Cancel
            </button>
            <button
              className="override-btn override-btn-dismiss"
              disabled={!isValid || saving}
              onClick={handleConfirm}
            >
              {saving ? 'Saving…' : isRequest ? 'Send request' : 'Confirm dismiss'}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
};

export default OverrideReasonModal;
