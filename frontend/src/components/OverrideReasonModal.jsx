import React, { useState, useEffect } from 'react';
import { X, XOctagon } from 'lucide-react';
import Modal from './Modal';
import SaveResult from './SaveResult';
import { useSaveResult } from '../utils/useSaveResult';
import { formatUnits } from '../utils/formatNumber';
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
const OverrideReasonModal = ({ isOpen, item, onCancel, onConfirm }) => {
  const [reason, setReason] = useState('');
  const [saveError, setSaveError] = useState('');
  const { saving, result, run, reset } = useSaveResult();

  useEffect(() => {
    if (isOpen) {
      setReason('');
      setSaveError('');
      reset();
    }
  }, [isOpen, reset]);

  if (!isOpen || !item) return null;

  const isValid = reason.trim().length >= 8;

  const handleConfirm = () => {
    setSaveError('');
    run(() => onConfirm(reason.trim()), {
      onSaved: onCancel,
      onFailed: setSaveError,
      fallbackError: "Couldn't save the decision. Please try again.",
    });
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      label="Dismiss recommendation"
      overlayClassName="override-modal-overlay"
      containerClassName="override-modal-card"
      closeOnOverlayClick={!saving}
      closeOnEscape={!saving}
    >
      {result ? (
        <SaveResult
          ok={result.ok}
          title={result.ok ? 'Recommendation dismissed' : "Couldn't save the decision"}
          message={result.ok
            ? <>Your reason for <strong>{item.sku}</strong> is in the decision log.</>
            : result.message}
        />
      ) : (
        <>
          <div className="override-modal-header">
            <div className="override-icon-wrap override-icon-dismiss">
              <XOctagon size={18} />
            </div>
            <div>
              <h3 className="override-modal-title">Dismiss recommendation</h3>
              <p className="override-modal-subtitle">{item.sku} — {item.product}</p>
            </div>
            <button className="override-modal-close" onClick={onCancel} disabled={saving} aria-label="Close modal">
              <X size={18} />
            </button>
          </div>

          <div className="override-modal-body">
            <p className="override-modal-copy">
              You're dismissing the LP-optimized order of <strong>{formatUnits(item.orderQty)} units</strong>.
              This deviation is recorded in the decision log against your account so the reasoning is available for review.
            </p>

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
            {!isValid && reason.length > 0 && (
              <span className="override-hint-error">Please provide a bit more detail (min. 8 characters).</span>
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
              {saving ? 'Saving…' : 'Confirm dismiss'}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
};

export default OverrideReasonModal;
