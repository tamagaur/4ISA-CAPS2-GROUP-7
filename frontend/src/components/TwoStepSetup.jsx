import React, { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Check, Copy } from 'lucide-react';
import TwoStepCodeForm from './TwoStepCodeForm';
import './TwoStep.css';

// "1234ABCD..." -> "1234 ABCD ...": easier to type into the app by hand.
const groupKey = (secret) => (secret.match(/.{1,4}/g) || []).join(' ');

// Setting up an authenticator app: scan the QR code (or type the key), then
// one code from the app turns it on. `setup` is { secret, otpauth_uri } from
// the server; onConfirm(code) throws on a wrong code.
const TwoStepSetup = ({ setup, onConfirm, variant }) => {
  const [copied, setCopied] = useState(false);

  const copyKey = async () => {
    try {
      await navigator.clipboard.writeText(setup.secret);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className={`twostep-setup ${variant === 'login' ? 'twostep-setup-login' : ''}`}>
      <ol className="twostep-steps">
        <li>
          <strong>Get an authenticator app</strong> on your phone: Google Authenticator or
          Microsoft Authenticator. Both are free.
        </li>
        <li>
          <strong>Scan this QR code</strong> in the app (tap <em>+</em> or <em>Add account</em>).
          <div className="twostep-qr">
            <QRCodeSVG value={setup.otpauth_uri} size={176} marginSize={2} title="QR code for your authenticator app" />
          </div>
          <details className="twostep-manual">
            <summary>Can&apos;t scan it? Type a key instead</summary>
            <p>Choose <em>Enter a setup key</em>, use your email as the account name, and enter:</p>
            <div className="twostep-key-row">
              <code className="twostep-key">{groupKey(setup.secret)}</code>
              <button type="button" className="twostep-btn twostep-btn-small" onClick={copyKey}>
                {copied ? <Check size={14} /> : <Copy size={14} />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </details>
        </li>
        <li>
          <strong>Enter the 6-digit code</strong> the app now shows for SAN2 Inventory DSS.
        </li>
      </ol>
      <TwoStepCodeForm onSubmit={onConfirm} submitLabel="Turn on two-step sign-in" variant={variant} />
    </div>
  );
};

export default TwoStepSetup;
