import React, { useState, useEffect } from 'react';
import { X, PauseCircle, XOctagon } from 'lucide-react';
import './OverrideReasonModal.css';

// Story #82/#93: capturing a reason whenever a user deviates from the LP
// recommendation (Hold/Reject), so the override is auditable — who, when,
// why — rather than a silent status flip.
const OverrideReasonModal = ({ isOpen, action, item, onCancel, onConfirm }) => {
  const [reason, setReason] = useState('');

  useEffect(() => {
    if (isOpen) setReason('');
  }, [isOpen]);

  if (!isOpen || !item) return null;

  const isReject = action === 'REJECTED';
  const isValid = reason.trim().length >= 8;

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) onCancel();
  };

  return (
    <div className="override-modal-overlay" onClick={handleOverlayClick}>
      <div className="override-modal-card">
        <div className="override-modal-header">
          <div className={`override-icon-wrap ${isReject ? 'override-icon-reject' : 'override-icon-hold'}`}>
            {isReject ? <XOctagon size={18} /> : <PauseCircle size={18} />}
          </div>
          <div>
            <h3 className="override-modal-title">
              {isReject ? 'Reject recommendation' : 'Hold recommendation'}
            </h3>
            <p className="override-modal-subtitle">{item.sku} — {item.product}</p>
          </div>
          <button className="override-modal-close" onClick={onCancel} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        <div className="override-modal-body">
          <p className="override-modal-copy">
            You're overriding the LP-optimized order of <strong>{item.orderQty} units</strong>.
            This deviation is recorded in the decision log against your account so the reasoning is available for review.
          </p>

          <label className="override-label" htmlFor="override-reason">
            REASON <span className="override-req">*</span>
          </label>
          <textarea
            id="override-reason"
            className="override-textarea"
            rows={3}
            placeholder={isReject
              ? 'e.g., Supplier out of stock this cycle, reordering next week instead.'
              : 'e.g., Waiting on warehouse space confirmation before committing.'}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
          />
          {!isValid && reason.length > 0 && (
            <span className="override-hint-error">Please provide a bit more detail (min. 8 characters).</span>
          )}
        </div>

        <div className="override-modal-actions">
          <button className="override-btn override-btn-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button
            className={`override-btn ${isReject ? 'override-btn-reject' : 'override-btn-hold'}`}
            disabled={!isValid}
            onClick={() => onConfirm(reason.trim())}
          >
            Confirm {isReject ? 'reject' : 'hold'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default OverrideReasonModal;
