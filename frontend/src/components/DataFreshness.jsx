import React, { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { subscribeServed } from '../api/cache';
import './DataFreshness.css';

const formatAge = (fetchedAt, now) => {
  const seconds = Math.max(0, Math.round((now - fetchedAt) / 1000));
  if (seconds < 60) return 'Updated just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `Updated ${minutes} min ago`;
  return `Updated ${new Date(fetchedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
};

// Shows how old the figures on the current page are. Responses are cached
// for up to 5 minutes (api/cache.js), so a page can show data fetched a few
// minutes ago; Refresh drops the cache and reloads the page's data.
//
// `navKey` changes on every navigation or refresh. Only responses served
// after that point count, so a previous page's fetch time never shows here.
// This component renders before the page itself (it sits above <Outlet>),
// so the timestamp is taken before the page asks for its data.
const DataFreshness = ({ navKey, onRefresh }) => {
  const nav = useRef({ key: null, startedAt: 0 });
  if (nav.current.key !== navKey) {
    nav.current = { key: navKey, startedAt: Date.now() };
  }

  const [events, setEvents] = useState([]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => subscribeServed((event) => {
    setEvents((prev) => [...prev.slice(-19), event]);
    setNow(Date.now());
  }), []);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(id);
  }, []);

  // Newest fetch among this page's responses: the page's own data request.
  const fetchedAt = events
    .filter((e) => e.servedAt >= nav.current.startedAt && e.fetchedAt)
    .reduce((latest, e) => Math.max(latest, e.fetchedAt), 0);

  return (
    <div className="data-freshness">
      {fetchedAt > 0 && (
        <span className="data-freshness-age" title="Figures are cached for up to 5 minutes.">
          {formatAge(fetchedAt, now)}
        </span>
      )}
      <button
        type="button"
        className="data-freshness-refresh"
        onClick={onRefresh}
        title="Reload this page's data from the database"
      >
        <RefreshCw size={13} />
        Refresh
      </button>
    </div>
  );
};

export default DataFreshness;
