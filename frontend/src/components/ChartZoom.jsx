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

// Horizontal room one "Mmm · YYYY" tick needs (~52px at 10-11px, plus a
// gap), and the part of a chart container the plot doesn't get (Y axis and
// margins). A chart that attaches `containerRef` gets ticks sized to its
// measured width: 12 fixed ticks overlapped in a half-width card once a
// range passed ~3 years (the 5-year preview's default, 2026-09-24).
const LABEL_SLOT_PX = 64;
const NON_PLOT_PX = 70;

// Right margin for any chart whose XAxis takes `labelInterval`. With no
// bars the X axis is a point scale, so the latest month sits exactly on the
// plot's right edge and its label is centred there, half of it hanging past
// the plot. Recharts' own interval modes pull that label back inside, but a
// numeric interval skips that step, so the margin has to hold the overhang
// or the SVG crops it ("Feb · 202"). Half the widest "Mmm · YYYY" label in
// Inter is ~27px at the Dashboard's 10px ticks and ~30px at SKU Forecast's
// 11px; 36 covers both with room to spare.
export const EDGE_LABEL_MARGIN = 36;

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

  // Width of the chart container, when the caller attaches containerRef.
  const [width, setWidth] = useState(null);
  const observer = useRef(null);
  const containerRef = useCallback((node) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node || typeof ResizeObserver === 'undefined') return;
    observer.current = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.current.observe(node);
  }, []);
  useEffect(() => () => observer.current?.disconnect(), []);

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
  // "draw them all" in Recharts' interval vocabulary. Without a measured
  // width (no containerRef) it is the fixed MAX_COMFORTABLE_TICKS, as before.
  const maxTicks = width
    ? clamp(Math.floor((width - NON_PLOT_PX) / LABEL_SLOT_PX), 2, MAX_COMFORTABLE_TICKS)
    : MAX_COMFORTABLE_TICKS;
  const labelInterval = Math.max(0, Math.ceil(effectiveSize / maxTicks) - 1);

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
    containerRef,
    // The container's width in px (null until measured), for a chart that
    // places its own labels (SKU Forecast's annotation band).
    width,
    labelInterval,
    isAdjusting,
    setIsAdjusting,
    zoomAnim,
  };
}

// Solid hairline gridlines, one shade off the surface — shared by every
// chart so "what does the grid look like" has one answer. Dashing is
// reserved for the marks that MEAN "projected / reference", which is why
// the grid itself must never dash (it used to, and the forecast lines'
// dashes stopped standing out against it).
export const GRID_PROPS = {
  vertical: false,
  stroke: '#E2E8F0',
  strokeWidth: 1,
};

// Texture (hatching) as the backup identity channel is OPT-IN: on when
// the reader has asked their OS/browser for a non-colour cue
// (high-contrast or forced-colors mode) or when printing, off otherwise —
// dense angled fills read as noise by default. Charts that carry a status
// hatch (the ABC page's CRITICAL segment) key it off this, and the
// matching legend swatches switch via the same media queries in CSS.
const TEXTURE_QUERIES = ['(prefers-contrast: more)', '(forced-colors: active)'];

export function usePrefersTexture() {
  const [wants, setWants] = useState(() =>
    typeof window !== 'undefined' && 'matchMedia' in window
      ? TEXTURE_QUERIES.some((q) => window.matchMedia(q).matches)
      : false
  );
  useEffect(() => {
    if (typeof window === 'undefined' || !('matchMedia' in window)) return undefined;
    const lists = TEXTURE_QUERIES.map((q) => window.matchMedia(q));
    const update = () => setWants(lists.some((l) => l.matches));
    lists.forEach((l) => l.addEventListener?.('change', update));
    return () => lists.forEach((l) => l.removeEventListener?.('change', update));
  }, []);
  return wants;
}

// Below this per-point spacing (px) a dot on every month reads as a rope
// of beads and the dots start touching; the line alone carries the shape,
// with dots kept only where they carry information nothing else does
// (isolated points, and the latest observation).
const DOT_MIN_SPACING_PX = 14;

/**
 * Per-point dot renderer for a Line, passed as its `dot` prop.
 *
 * Dots mark REAL observations (everything between two points is
 * interpolation), so every month gets one — 8px (r=4) with a 2px ring in
 * the surface colour, which keeps a dot legible where it crosses the other
 * series' line. When the zoom window packs points tighter than
 * DOT_MIN_SPACING_PX, per-month dots drop out and only the latest point
 * and isolated points keep theirs.
 *
 * An isolated point is drawn slightly larger. Recharts needs two adjacent
 * non-null points to draw a segment, so a month whose neighbours are both
 * null has no line at all — the lone dot is the entire visual record of
 * that month.
 *
 * `skip(payload)` omits the dot at points that aren't this series' own
 * observation — e.g. the actual/forecast bridge, where the forecast line
 * borrows the last actual value purely so the two lines join. Marking it
 * would put a forecast dot on top of a real month.
 *
 * Recharts supplies the key on its own wrapper (see component/Dots.js), so
 * returning null here simply omits that dot.
 */
export function seriesDot({ color, r = 4, skip }) {
  return ({ cx, cy, index, points, dataKey, payload }) => {
    // A null month has no coordinates — nothing to mark.
    if (cx == null || cy == null) return null;
    if (skip?.(payload)) return null;

    const valueAt = (i) => {
      const point = points?.[i];
      if (!point) return null;
      return point.value ?? point.payload?.[dataKey] ?? null;
    };
    const isolated = valueAt(index - 1) == null && valueAt(index + 1) == null;

    // The last point of this series that has a value at all — its dot
    // stays at every density (it anchors the end label / latest reading).
    let lastIdx = (points?.length ?? 0) - 1;
    while (lastIdx >= 0 && valueAt(lastIdx) == null) lastIdx -= 1;

    const spacing = points && points.length > 1 && points[0]?.x != null && points[points.length - 1]?.x != null
      ? Math.abs(points[points.length - 1].x - points[0].x) / (points.length - 1)
      : Infinity;
    if (spacing < DOT_MIN_SPACING_PX && !isolated && index !== lastIdx) return null;

    return (
      <circle
        cx={cx}
        cy={cy}
        r={isolated ? r + 1 : r}
        fill={color}
        stroke="var(--color-surface, #fff)"
        strokeWidth={2}
      />
    );
  };
}

/**
 * Selective direct labels ON the line — the series' latest value at its
 * end, or a marked month (a peak, a low), where the eye already is.
 * Passed as a Line's `label` prop.
 *
 * `entries` name the months to label: [{ period, text, below }] — matched
 * against the plotted rows by `key`, so a label simply drops out when its
 * month is zoomed/panned out of the window, and never a label on every
 * point (that is chaos, and goes unread).
 *
 * Drawn INSIDE the plot: anchored to the point, pulled left at the last
 * point and right at the first so the text can't leave the SVG. Ink text,
 * never the series colour — the line the label touches carries identity.
 * The .chart-end-label class hides them all at phone widths, where the
 * legend + tooltip take over.
 */
export function pointLabels(view, entries, { key = 'period' } = {}) {
  const list = (entries || []).filter((e) => e && e.text != null);
  if (!list.length) return false;
  return (props) => {
    const { x, y, index, value } = props;
    if (x == null || y == null || value == null) return null;
    const period = view[index]?.[key];
    const match = list.find((e) => e.period === period);
    if (!match) return null;
    const anchor = index >= view.length - 1 ? 'end' : index === 0 ? 'start' : 'middle';
    const dx = anchor === 'end' ? 6 : anchor === 'start' ? -4 : 0;
    return (
      <text
        x={x + dx}
        y={match.below ? y + 20 : y - 12}
        textAnchor={anchor}
        className="chart-end-label"
        fill="var(--color-text, #1a202c)"
        fontSize={11}
        fontWeight={600}
      >
        {match.text}
      </text>
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
 *
 * `zoomInRight` flips that to the way a zoom control usually reads: the
 * handle rests at the LEFT with the whole range in view (compressed), and
 * dragging right zooms in (fewer months across the same width, so the
 * chart gets larger); dragging back left compresses it again. Opt-in while
 * it is tried on the Dashboard's line charts.
 */
export function ChartZoomSlider({ zoom, label = 'Date range zoom', zoomInRight = false }) {
  const { size, total, minWindow, setSize, reset, isZoomed, canZoom, setIsAdjusting } = zoom;

  if (!canZoom) return null;

  // The input's own value runs the other way when right zooms in: it counts
  // how far in the zoom has gone rather than how many months are shown.
  // Either way the filled part of the track runs up to the handle, so it
  // doubles as a quiet gauge of the zoom.
  const toValue = (months) => (zoomInRight ? total + minWindow - months : months);
  const value = toValue(size);
  const span = Math.max(1, total - minWindow);
  const pct = ((value - minWindow) / span) * 100;

  return (
    <div className={`chart-zoom${isZoomed ? ' is-zoomed' : ''}`}>
      <input
        type="range"
        className="chart-zoom-slider"
        min={minWindow}
        max={total}
        step={1}
        value={value}
        style={{ '--zoom-pct': `${pct}%` }}
        aria-label={label}
        aria-valuetext={`${size} of ${total} months`}
        title={zoomInRight
          ? `${size} of ${total} months — drag right to zoom in, left to zoom out, double-click to reset`
          : `${size} of ${total} months — drag to zoom, double-click to reset`}
        // toValue is its own inverse (a mirror across the track), so it
        // also turns the handle's position back into a month count.
        onChange={(e) => setSize(toValue(Number(e.target.value)))}
        onDoubleClick={reset}
        onPointerDown={() => setIsAdjusting(true)}
        onPointerUp={() => setIsAdjusting(false)}
        onPointerCancel={() => setIsAdjusting(false)}
        onBlur={() => setIsAdjusting(false)}
      />
    </div>
  );
}
