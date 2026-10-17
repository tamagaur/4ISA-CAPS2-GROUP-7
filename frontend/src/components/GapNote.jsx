// What the reason codes on a chart's points mean, in the backend's own words
// (`gap_note`, backend/series_gaps.py): one line per reason present, under
// the chart. Nothing when no point carries a reason.
import React from 'react';
import { gapNoteEntries } from '../utils/gapReasons';
import './GapNote.css';

const GapNote = ({ note, codes = null }) => {
  const entries = gapNoteEntries(note, codes);
  if (!entries.length) return null;
  return (
    <div className="gap-note" role="note">
      {entries.map((e) => (
        <p key={e.code}>
          <strong>{e.label}.</strong> {e.text}
        </p>
      ))}
    </div>
  );
};

export default GapNote;
