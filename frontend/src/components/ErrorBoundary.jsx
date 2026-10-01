// Catches a render crash so one broken page doesn't blank the whole app.
//
// Two places use it: around the page outlet in DashboardLayout (keyed on the
// path, so moving to another page clears it), and around <App/> in main.jsx
// as the last resort. A page file that no longer exists after a deploy (an
// old tab asking for a chunk Vercel has replaced) is not a bug in the page:
// the boundary reloads once to fetch the new build, and only shows the card
// if that reload fails too.
import React from 'react';
import { AlertTriangle } from 'lucide-react';
import '../permissions/AccessGate.css';
import './ErrorBoundary.css';

const RELOADED_KEY = 'san2_chunk_reload_at';
// A reload within this long of the last one means reloading didn't help.
const RELOAD_WINDOW_MS = 30000;

const isChunkLoadError = (error) => /dynamically imported module|Importing a module script failed|ChunkLoadError|Loading chunk/i
  .test(String(error?.message || error));

function reloadOnceForNewBuild() {
  try {
    const last = Number(sessionStorage.getItem(RELOADED_KEY) || 0);
    if (Date.now() - last < RELOAD_WINDOW_MS) return false;
    sessionStorage.setItem(RELOADED_KEY, String(Date.now()));
  } catch {
    return false;
  }
  window.location.reload();
  return true;
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, reloading: false, resetKey: props.resetKey };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  // A different page (or a refresh of the same one) gets a fresh start.
  static getDerivedStateFromProps(props, state) {
    if (props.resetKey !== state.resetKey) {
      return { error: null, reloading: false, resetKey: props.resetKey };
    }
    return null;
  }

  componentDidCatch(error, info) {
    if (isChunkLoadError(error) && reloadOnceForNewBuild()) {
      this.setState({ reloading: true });
      return;
    }
    console.error('Page crashed:', error, info?.componentStack);
  }

  render() {
    const { error, reloading } = this.state;
    if (!error) return this.props.children;
    if (reloading) {
      return <div className="access-gate error-boundary" role="status">Loading the latest version…</div>;
    }
    const outdated = isChunkLoadError(error);
    return (
      <div className={`access-gate error-boundary${this.props.fullScreen ? '' : ' error-boundary-page'}`} role="alert">
        <div className="access-gate-card">
          <AlertTriangle size={26} className="access-gate-icon" aria-hidden="true" />
          <h2 className="access-gate-title">
            {outdated ? 'This page needs the latest version of the app' : 'Something went wrong on this page'}
          </h2>
          <p className="access-gate-text">
            {outdated
              ? 'The app was updated while this tab was open. Reload to get the new version.'
              : 'Reload to try again. If it keeps happening, tell the admin which page you were on and what you clicked.'}
          </p>
          <div className="access-gate-actions">
            <button type="button" className="access-gate-btn primary" onClick={() => window.location.reload()}>
              Reload
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
