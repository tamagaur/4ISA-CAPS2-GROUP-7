import React, { useEffect, useState } from 'react';
import { Hourglass } from 'lucide-react';

// Shown once a load has run longer than `after` ms (2026-10-16). The live
// backend is on Render's free plan, which sleeps after 15 minutes with no
// visitors; its first answer after that took 83 s (measured 2026-10-16),
// with nothing on screen but loading placeholders. This says why, and that
// waiting is enough. Render it only while loading: it starts timing when it
// appears, and unmounting it resets the clock.
const SlowLoadNotice = ({ after = 8000 }) => {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), after);
    return () => clearTimeout(timer);
  }, [after]);
  if (!slow) return null;
  return (
    <p className="slow-load-notice" role="status">
      <Hourglass size={14} aria-hidden="true" />
      <span>
        <strong>Still loading.</strong> The server may be starting up: on the live site this can take up to a minute
        after a quiet period. The page fills in by itself, so there&apos;s no need to refresh.
      </span>
    </p>
  );
};

export default SlowLoadNotice;
