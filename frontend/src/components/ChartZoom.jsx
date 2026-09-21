import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { chartAnim } from '../theme/motion';
import './ChartZoom.css';

// Fewest points a zoomed-in window may show. Below ~4 the line has too
// little shape left to read as a trend, and the tooltip becomes the only
// way to get anything out of the chart.
export const MIN_WINDOW = 4;

// Labels stay legible up to roughly this many ticks across a chart of this
// width; past it the XAxis has to start skipping or the months collide.
const MAX_COMFORTABLE_TICKS = 12;

// Above this many visible points, per-point dots stop helping and start
// reading as noise — three series across a 38-month range would put over a
// hundred marks on one chart. Below it you are reading individual months,
// and the dots are what say which values were measured rather than drawn by
// the monotone curve between them.
export const DOT_DENSITY_LIMIT = 12;

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

/**
 * Windowing state for a period-keyed chart: how many points are visible
 * (`size`) and where the window ends (`end`, exclusive).
 *
 * The window is anchored to the RIGHT — zooming keeps the most recent month
 * in view and reveals older ones as it widens, because the latest period is
 * where every question on these pages starts. Dragging the chart then moves
 * that window back in time.
 *
 * Returns `view` (the sliced data to plot) plus `labelInterval`, which is
 * the real reason this exists: Recharts skips X labels when they crowd, so
 * a 38-month range shows maybe a third of its months. Narrowing the window
 * is what lets every date actually appear.
 */
export function useChartZoom(data, { minWindow = MIN_WINDOW } = {}) {
  const total = data.length;

  // null = "follow the data" (show everything). Kept as null rather than
  // eagerly set to `total` so a date-range change that grows the series
  // keeps showing all of it instead of pinning to the old count.
  const [size, setSize] = useState(null);
  const [end, setEnd] = useState(null);
  const [isAdjusting, setIsAdjusting] = useState(false);

  // A new date range is a different question being asked — start it fully
  // zoomed out rather than carrying the previous range's window over onto
  // data it was never chosen for.
  const prevTotal = useRef(total);
  useEffect(() => {
    if (prevTotal.current !== total) {
      prevTotal.current = total;
      setSize(null);
      setEnd(null);
    }
  }, [total]);

  const effectiveSize = size === null ? total : clamp(size, Math.min(minWindow, total), total);
  const effectiveEnd = end === null ? total : clamp(end, effectiveSize, total);
  const start = Math.max(0, effectiveEnd - effectiveSize);

  const view = useMemo(() => data.slice(start, effectiveEnd), [data, start, effectiveEnd]);

  // Zooming holds the right edge unless the window is already panned back,
  // in which case it grows around where the viewer is actually looking.
  const applySize = useCallback((next) => {
    const clamped = clamp(next, Math.min(minWindow, total), total);
    setSize(clamped);
    setEnd((currentEnd) => clamp(currentEnd === null ? total : currentEnd, clamped, total));
  }, [minWindow, total]);

  const reset = useCallback(() => {
    setSize(null);
    setEnd(null);
  }, []);

  // Drag-to-pan, on the chart body itself. With no stepper buttons in the
  // UI this is the only way to move the window, so it stays on whenever the
  // window is narrower than the data, and the cursor advertises it.
  const panState = useRef(null);
  const canPan = effectiveSize < total;

  const onPointerDown = useCallback((event) => {
    if (!canPan || event.button !== 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    panState.current = {
      x: event.clientX,
      end: effectiveEnd,
      pointsPerPx: effectiveSize / rect.width,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setIsAdjusting(true);
  }, [canPan, effectiveEnd, effectiveSize]);

  const onPointerMove = useCallback((event) => {
    const pan = panState.current;
    if (!pan) return;
    // Dragging right reveals EARLIER months, matching the direction the
    // content moves under the cursor rather than the window's index.
    const deltaPoints = Math.round((pan.x - event.clientX) * pan.pointsPerPx);
    setEnd(clamp(pan.end + deltaPoints, effectiveSize, total));
  }, [effectiveSize, total]);

  const endPan = useCallback((event) => {
    if (!panState.current) return;
    panState.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    setIsAdjusting(false);
  }, []);

  const panHandlers = canPan
    ? { onPointerDown, onPointerMove, onPointerUp: endPan, onPointerCancel: endPan }
    : {};

  // Every Nth label, chosen so ticks never exceed what fits. 0 means
  // "draw them all" in Recharts' interval vocabulary.
  const labelInterval = Math.max(0, Math.ceil(effectiveSize / MAX_COMFORTABLE_TICKS) - 1);

  // Re-slicing on every slider step would restart Recharts' 700ms entrance
  // on each tick, so the chart would strobe instead of scrub. Animation
  // comes back once the interaction ends.
  const zoomAnim = useCallback(
    (seriesIndex = 0) => (isAdjusting ? { isAnimationActive: false } : chartAnim(seriesIndex)),
    [isAdjusting]
  );

  return {
    view,
    size: effectiveSize,
    total,
    minWindow: Math.min(minWindow, total),
    setSize: applySize,
    reset,
    isZoomed: effectiveSize < total,
    canZoom: total > minWindow,
    canPan,
    panHandlers,
    labelInterval,
    showDots: effectiveSize <= DOT_DENSITY_LIMIT,
    isAdjusting,
    setIsAdjusting,
    zoomAnim,
  };
}

/**
 * Soft wash under a line: that line's own hue, fading out toward the
 * baseline. Tying each fill to its series color lets someone tracking
 * several lines at once tell whose band is whose without going back to the
 * legend, and it stays faint so overlapping bands remain readable where
 * the series cross.
 *
 * Goes inside the chart's <defs>; the series then references it as
 * fill="url(#<id>)". Ids are global to the document, so charts that can
 * appear on the same page need distinct ones.
 */
export const SeriesFill = ({ id, color }) => (
  <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stopColor={color} stopOpacity={0.22} />
    <stop offset="100%" stopColor={color} stopOpacity={0.02} />
  </linearGradient>
);

/**
 * Per-point dot renderer for a Line, passed as its `dot` prop.
 *
 * Two rules:
 *
 *  1. Draw dots when the window is narrow enough to be read month by month
 *     (`show`), because the curve is type="monotone" — everything between
 *     two points is interpolation, and the dots are the only thing marking
 *     which values are real observations.
 *
 *  2. ALWAYS draw one for an isolated point, whatever the zoom. Recharts
 *     needs two adjacent non-null points to draw a segment, so a month whose
 *     neighbours are both null renders as nothing at all with dot={false} —
 *     real data, silently invisible. It is drawn slightly larger, since a
 *     lone dot is the entire visual record of that month.
 *
 * Recharts supplies the key on its own wrapper (see component/Dots.js), so
 * returning null here simply omits that dot.
 */
export function seriesDot({ show, color, r = 3 }) {
  return ({ cx, cy, index, points, dataKey }) => {
    // A null month has no coordinates — nothing to mark.
    if (cx == null || cy == null) return null;

    const valueAt = (i) => {
      const point = points?.[i];
      if (!point) return null;
      return point.value ?? point.payload?.[dataKey] ?? null;
    };
    const isolated = valueAt(index - 1) == null && valueAt(index + 1) == null;

    if (!show && !isolated) return null;

    return (
      <circle
        cx={cx}
        cy={cy}
        r={isolated ? r + 1 : r}
        fill={color}
        stroke="none"
      />
    );
  };
}

/**
 * A bare zoom slider, sitting between the chart and its legend.
 *
 * Deliberately unadorned: no label, no counter, no stepper buttons. It is a
 * secondary control on a page whose primary date control is the filter at
 * the top, so at rest it should read as a thin rule under the chart and
 * only come forward on hover or focus.
 *
 * Left narrows the window (fewer months, more shape per point), right opens
 * it back out to the full range. Double-click resets. The month count lives
 * in the native tooltip and the ARIA value text rather than on screen.
 */
export function ChartZoomSlider({ zoom, label = 'Date range zoom' }) {
  const { size, total, minWindow, setSize, reset, isZoomed, canZoom, setIsAdjusting } = zoom;

  if (!canZoom) return null;

  // Proportion of the full range in view, so the filled part of the track
  // doubles as a quiet gauge of how far the zoom has gone.
  const span = Math.max(1, total - minWindow);
  const pct = ((size - minWindow) / span) * 100;

  return (
    <div className={`chart-zoom${isZoomed ? ' is-zoomed' : ''}`}>
      <input
        type="range"
        className="chart-zoom-slider"
        min={minWindow}
        max={total}
        step={1}
        value={size}
        style={{ '--zoom-pct': `${pct}%` }}
        aria-label={label}
        aria-valuetext={`${size} of ${total} months`}
        title={`${size} of ${total} months — drag to zoom, double-click to reset`}
        onChange={(e) => setSize(Number(e.target.value))}
        onDoubleClick={reset}
        onPointerDown={() => setIsAdjusting(true)}
        onPointerUp={() => setIsAdjusting(false)}
        onPointerCancel={() => setIsAdjusting(false)}
        onBlur={() => setIsAdjusting(false)}
      />
    </div>
  );
}
