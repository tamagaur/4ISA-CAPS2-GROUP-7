import React, { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Loader2, ShieldCheck, X } from 'lucide-react';
import Modal from './Modal';
import TwoStepSetup from './TwoStepSetup';
import TwoStepCodeForm from './TwoStepCodeForm';
import RecoveryCodes from './RecoveryCodes';
import { useToast } from './ToastProvider';
import {
  confirmMfaSetup, disableMfa, getMfaStatus, MFA_STATUS_EVENT, replaceRecoveryCodes, startMfaSetup,
} from '../api/mfa';
import { getCurrentUser } from '../auth';
import './TwoStep.css';

// Your own two-step sign-in, opened from your name in the sidebar
// (backend/routers/two_factor.py). Views: the overview, setup (QR code),
// the recovery codes, and the code check before turning it off or making
// new recovery codes.
const RECOVERY_LOW = 3;

// `onStatusChange` gets every status this dialog loads (on open, and after
// setup, new codes or turning it off), so the sidebar's "Account security"
// line can follow it.
const AccountSecurityModal = ({ isOpen, onClose, onStatusChange }) => {
  const toast = useToast();
  const email = getCurrentUser()?.email;
  const [status, setStatus] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [view, setView] = useState('overview'); // overview | setup | codes | disable | regenerate
  const [setup, setSetup] = useState(null);
  const [codes, setCodes] = useState(null);
  const [actionError, setActionError] = useState('');
  const [starting, setStarting] = useState(false);

  const load = useCallback(async () => {
    setLoadError('');
    try {
      const fresh = await getMfaStatus();
      setStatus(fresh);
      onStatusChange?.(fresh);
      window.dispatchEvent(new CustomEvent(MFA_STATUS_EVENT, { detail: fresh }));
    } catch (err) {
      setLoadError(err.message || 'Could not load two-step sign-in.');
    }
  }, [onStatusChange]);

  useEffect(() => {
    if (!isOpen) return;
    setView('overview');
    setSetup(null);
    setCodes(null);
    setActionError('');
    setStatus(null);
    load();
  }, [isOpen, load]);

  const handleStart = async () => {
    setActionError('');
    setStarting(true);
    try {
      setSetup(await startMfaSetup());
      setView('setup');
    } catch (err) {
      setActionError(err.message);
    } finally {
      setStarting(false);
    }
  };

  const handleConfirm = async (code) => {
    const result = await confirmMfaSetup(code);
    setCodes(result.recovery_codes);
    setSetup(null);
    setView('codes');
    load();
  };

  const handleRegenerate = async (code) => {
    const result = await replaceRecoveryCodes(code);
    setCodes(result.recovery_codes);
    setView('codes');
    load();
  };

  const handleDisable = async (code) => {
    await disableMfa(code);
    toast.success('Two-step sign-in is off');
    setView('overview');
    load();
  };

  const back = () => {
    setActionError('');
    setView('overview');
  };

  const titles = {
    overview: 'Account security',
    setup: 'Set up two-step sign-in',
    codes: 'Save your recovery codes',
    disable: 'Turn off two-step sign-in',
    regenerate: 'New recovery codes',
  };

  const renderOverview = () => {
    if (loadError) return <div className="twostep-error" role="alert">{loadError}</div>;
    if (!status) {
      return <p className="twostep-muted"><Loader2 size={15} className="twostep-spin" /> Loading…</p>;
    }
    if (!status.available) {
      return (
        <p className="twostep-muted">
          Two-step sign-in isn&apos;t available on this server yet. Ask your administrator.
        </p>
      );
    }
    const left = status.recovery_codes_left;
    return (
      <>
        <div className="twostep-status-row">
          <span className="twostep-status-label">Two-step sign-in</span>
          <span className={`twostep-pill ${status.enabled ? 'on' : 'off'}`}>{status.enabled ? 'On' : 'Off'}</span>
        </div>
        {status.enabled ? (
          <>
            <p className="twostep-text">
              Each sign-in asks for the 6-digit code from your authenticator app after your password.
            </p>
            <p className={`twostep-text ${left !== null && left <= RECOVERY_LOW ? 'twostep-warn' : ''}`}>
              Recovery codes left: <strong>{left}</strong>
              {left !== null && left <= RECOVERY_LOW ? '. Make new ones before you run out.' : ''}
            </p>
            {status.required && (
              <p className="twostep-muted">Required for your role, so it can&apos;t be turned off.</p>
            )}
            <div className="twostep-actions">
              <button type="button" className="twostep-btn" onClick={() => setView('regenerate')}>
                New recovery codes
              </button>
              {!status.required && (
                <button type="button" className="twostep-btn twostep-btn-danger" onClick={() => setView('disable')}>
                  Turn off
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <p className="twostep-text">
              After your password, sign-in also asks for a code from an app on your phone, so a stolen
              password alone can&apos;t get into your account.
            </p>
            {status.required && <p className="twostep-warn">Required for your role.</p>}
            {actionError && <div className="twostep-error" role="alert">{actionError}</div>}
            <div className="twostep-actions">
              <button
                type="button"
                className="twostep-btn twostep-btn-primary"
                onClick={handleStart}
                disabled={starting}
              >
                {starting ? 'Starting…' : 'Set up two-step sign-in'}
              </button>
            </div>
          </>
        )}
      </>
    );
  };

  const renderBody = () => {
    switch (view) {
      case 'setup':
        return <TwoStepSetup setup={setup} onConfirm={handleConfirm} />;
      case 'codes':
        return <RecoveryCodes codes={codes} email={email} onDone={back} />;
      case 'disable':
        return (
          <>
            <p className="twostep-text">
              Enter a code from your app, or a recovery code, to turn it off. Sign-in will need only
              your password.
            </p>
            <TwoStepCodeForm onSubmit={handleDisable} submitLabel="Turn off" busyLabel="Turning off…" allowRecovery />
          </>
        );
      case 'regenerate':
        return (
          <>
            <p className="twostep-text">
              Enter a code from your app to make 10 new recovery codes. Your current ones stop working.
            </p>
            <TwoStepCodeForm onSubmit={handleRegenerate} submitLabel="Make new codes" allowRecovery />
          </>
        );
      default:
        return renderOverview();
    }
  };

  // While the codes are on screen, only Done closes: they can't be shown again.
  const showingCodes = view === 'codes';

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      labelledBy="account-security-title"
      overlayClassName="twostep-modal-overlay"
      containerClassName="twostep-modal-card"
      closeOnOverlayClick={!showingCodes && view !== 'setup'}
      closeOnEscape={!showingCodes}
    >
      <div className="twostep-modal-header">
        {view !== 'overview' && !showingCodes ? (
          <button type="button" className="twostep-icon-btn" onClick={back} aria-label="Back">
            <ArrowLeft size={18} />
          </button>
        ) : (
          <div className="twostep-modal-icon"><ShieldCheck size={20} /></div>
        )}
        <h3 id="account-security-title" className="twostep-modal-title">{titles[view]}</h3>
        {!showingCodes && (
          <button type="button" className="twostep-icon-btn" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        )}
      </div>
      <div className="twostep-modal-body">{renderBody()}</div>
    </Modal>
  );
};

export default AccountSecurityModal;
