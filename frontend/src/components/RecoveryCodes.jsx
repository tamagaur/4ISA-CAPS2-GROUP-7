import React, { useState } from 'react';
import { Check, Copy, Download } from 'lucide-react';
import './TwoStep.css';

// The one-time recovery codes, right after setup or after asking for new
// ones. The server keeps only their hashes, so this is the only time they
// can be seen: Continue stays off until the person says they saved them.
const RecoveryCodes = ({ codes, email, onDone, doneLabel = 'Done', variant }) => {
  const [saved, setSaved] = useState(false);
  const [copyState, setCopyState] = useState('idle'); // 'idle' | 'copied' | 'failed'
  const isLogin = variant === 'login';

  const asText = [
    `SAN2 | SSM Decision Support Dashboard recovery codes${email ? ` for ${email}` : ''}`,
    'Each code works once, in place of the code from your authenticator app.',
    '',
    ...codes,
    '',
  ].join('\n');

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(asText);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  };

  const download = () => {
    const url = URL.createObjectURL(new Blob([asText], { type: 'text/plain' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'san2-recovery-codes.txt';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="twostep-recovery">
      <p className="twostep-recovery-intro">
        If you lose your phone, each of these codes lets you sign in once. Keep them somewhere safe,
        such as a password manager or a printout. <strong>They won&apos;t be shown again.</strong>
      </p>
      <ul className="twostep-recovery-list" aria-label="Recovery codes">
        {codes.map((code) => (
          <li key={code}><code>{code}</code></li>
        ))}
      </ul>
      <div className="twostep-recovery-actions">
        <button type="button" className="twostep-btn" onClick={copy}>
          {copyState === 'copied' ? <Check size={15} /> : <Copy size={15} />}
          {copyState === 'copied' ? 'Copied' : 'Copy'}
        </button>
        <button type="button" className="twostep-btn" onClick={download}>
          <Download size={15} />
          Download
        </button>
      </div>
      {copyState === 'failed' && (
        <p className="twostep-hint" role="status">Couldn&apos;t copy automatically. Use Download, or write them down.</p>
      )}
      <label className="twostep-check">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        I&apos;ve saved my recovery codes
      </label>
      <button
        type="button"
        className={isLogin ? 'submit-btn twostep-done-login' : 'twostep-btn twostep-btn-primary'}
        disabled={!saved}
        onClick={onDone}
      >
        {doneLabel}
      </button>
    </div>
  );
};

export default RecoveryCodes;
