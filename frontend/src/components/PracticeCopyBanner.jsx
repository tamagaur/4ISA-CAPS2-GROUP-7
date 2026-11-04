import React, { useSyncExternalStore } from 'react';
import { AlertTriangle } from 'lucide-react';
import { getPracticeCopyNote, subscribePracticeCopy } from '../practiceCopy';

// On every page while the API answers from the local practice copy. The words are the backend's.
const PracticeCopyBanner = () => {
  const note = useSyncExternalStore(subscribePracticeCopy, getPracticeCopyNote);
  if (!note) return null;
  return (
    <p className="ui-note is-warning" role="note" data-testid="practice-copy-banner">
      <AlertTriangle size={16} aria-hidden="true" />
      <span><strong>Practice copy.</strong> {note}</span>
    </p>
  );
};

export default PracticeCopyBanner;
