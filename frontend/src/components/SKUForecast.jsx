import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { Search, Star, ArrowRight, Clock, Filter, X, ArrowUp, ArrowDown, Minus } from 'lucide-react';
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import { COLORS, CHART_COLORS } from '../theme/colors';
import { chartAnim } from '../theme/motion';
import { getABCClassification } from '../api/abc';
import { getForecast } from '../api/forecast';
import DateFilter from './DateFilter';
import './SKUForecast.css';

// Unlike Dashboard/ABC Classification/Reorder Recs/Bad Orders, this page's
// date range is its OWN, local to this component — not the shared
// cross-page one in DashboardLayout (see the localRange state below, and
// DateFilter's "local mode"). It seeds from the dashboard's range once on
// mount, then never affects and is never affected by any other page.
// Trims which real actuals get plotted (see chartData below); the
// forecast point itself always stays anchored to the latest real month —
// MA3's one-step forecast is a batch-computed value, not something a
// picked range can honestly recompute on the fly.
const MONTH_TO_NUM = {
  Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
  Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12',
};
const toPeriod = (month, year) =>
  month && year ? `${year}-${MONTH_TO_NUM[month]}` : undefined;

// Inclusive month count between two 'YYYY-MM' periods (a === b -> 1). Only
// meaningful when a <= b — callers check chronological order first.
const monthsBetween = (a, b) => {
  const [ay, am] = a.split('-').map(Number);
  const [by, bm] = b.split('-').map(Number);
  return (by * 12 + bm) - (ay * 12 + am) + 1;
};

// Same reasoning as DateFilter.jsx/DashboardLayout.jsx's MIN_RANGE_MONTHS:
// below this, the chart this page exists to show renders as 1-2
// disconnected dots rather than a readable trend.
const MIN_RANGE_MONTHS = 6;

// 'YYYY-MM' minus (count-1) months, inclusive — the start of a `count`-month
// window ending at `period`. Used by the too-short fix button to widen a
// range by pulling the start back, keeping the end (what the user actually
// picked) untouched.
const periodMinusMonths = (period, count) => {
  const [y, m] = period.split('-').map(Number);
  const total = y * 12 + (m - 1) - (count - 1);
  const year = Math.floor(total / 12);
  const monthIndex = ((total % 12) + 12) % 12;
  return `${year}-${String(monthIndex + 1).padStart(2, '0')}`;
};

const NUM_TO_MONTH = Object.fromEntries(Object.entries(MONTH_TO_NUM).map(([m, n]) => [n, m]));
// -> 'Mon YYYY'. Deliberately accepts BOTH shapes the API returns: actuals
// carry a 'YYYY-MM' period string, while forecast_date is a full ISO date
// ('2026-03-01' — it's a DATE column, see backend/schemas/forecast.py).
// Destructuring only the first two segments discards any day part, so both
// render identically; don't "fix" this into a strict 'YYYY-MM' parse.
const formatPeriod = (period) => {
  if (!period) return '';
  const [year, num] = period.split('-');
  return `${NUM_TO_MONTH[num] || num} ${year}`;
};

// X-axis tick + tooltip header: "Jan · 2026" — short month, middle dot,
// full year (matches the same format used on the Dashboard's charts, see
// Charts.jsx's formatAxisPeriod). The raw labels arrive in two different
// shapes (actuals 'YYYY-MM', forecast 'YYYY-MM-DD'), which rendered as a
// visibly inconsistent axis; this normalises both and keeps ticks short
// enough to sit horizontally without overlapping.
const formatAxisPeriod = (period) => {
  if (!period) return '';
  const [year, num] = period.split('-');
  return `${NUM_TO_MONTH[num] || num} · ${year}`;
};

// Y-axis tick: 1.2M / 155k / 940. Monthly Unilever volumes run into the
// hundreds of thousands, and the raw values were wide enough to crowd the
// plot area.
const formatAxisQty = (value) => {
  const n = Math.abs(value);
  if (n >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  if (n >= 1_000) return `${Math.round(value / 1_000)}k`;
  return `${Math.round(value)}`;
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const hasActual = payload.some(p => p.dataKey === 'actual');
    const displayPayload = hasActual
      ? payload.filter(p => p.dataKey !== 'forecast')
      : payload;

    const qty = (v) => Math.round(v).toLocaleString();

    return (
      <div className="forecast-tooltip">
        <p className="tooltip-label">{formatAxisPeriod(label)}</p>
        {displayPayload.map((entry, index) => {
          if (entry.dataKey === 'ci') {
            // Zero-width at the anchor point (see chartData) — that's the
            // "no uncertainty yet" join, not a real interval, so skip it.
            if (!Array.isArray(entry.value) || entry.value[0] === entry.value[1]) return null;
            return (
              <p key={index} className="tooltip-item">
                <span className="tooltip-dot" style={{ backgroundColor: COLORS.forecastBg, border: `1px solid ${COLORS.forecast}` }}></span>
                Confidence interval: {qty(entry.value[0])} – {qty(entry.value[1])}
              </p>
            );
          }
          return (
            <p key={index} className="tooltip-item" style={{ color: entry.color }}>
              <span className="tooltip-dot" style={{ backgroundColor: entry.color }}></span>
              {entry.name}: {qty(entry.value)} units
            </p>
          );
        })}
      </div>
    );
  }
  return null;
};

const SKUForecast = () => {
  const navigate = useNavigate();
  const dropdownRef = useRef(null);

  // This page's chart has its OWN date range, independent of the shared
  // cross-page one in DashboardLayout — seeded from the dashboard's
  // CURRENT applied range the moment this page mounts (matching "opens
  // with the dashboard's selection"), then lives entirely in this
  // component's own state from that point on. Changing it here never
  // writes back to the shared range (see DateFilter's `localValue`/
  // `onLocalChange` "local mode"), and since this is a route-level
  // component it remounts — re-seeding fresh — every time the user
  // navigates back to this page, so a later dashboard change is picked
  // up on the NEXT visit without this page's own pick ever leaking to
  // any other page in the meantime.
  const dashboardRange = useOutletContext() || {};
  const [localRange, setLocalRange] = useState(() => ({
    startMonth: dashboardRange.startMonth,
    startYear: dashboardRange.startYear,
    endMonth: dashboardRange.endMonth,
    endYear: dashboardRange.endYear,
  }));
  const rangeStartPeriod = toPeriod(localRange.startMonth, localRange.startYear);
  const rangeEndPeriod = toPeriod(localRange.endMonth, localRange.endYear);

  // "Clear" (DateFilter's local-mode reset button) — snaps this page's own
  // range back to the dashboard's, same source the initial seed above used.
  // Nothing else on this page writes to the shared dashboard range, so
  // comparing localRange against the LIVE dashboardRange is equivalent to
  // comparing against the original seed — only shown once the user has
  // actually picked something different, never just because the page loaded.
  const resetToDashboardRange = () => setLocalRange({
    startMonth: dashboardRange.startMonth,
    startYear: dashboardRange.startYear,
    endMonth: dashboardRange.endMonth,
    endYear: dashboardRange.endYear,
  });
  const isCustomRange =
    localRange.startMonth !== dashboardRange.startMonth ||
    localRange.startYear !== dashboardRange.startYear ||
    localRange.endMonth !== dashboardRange.endMonth ||
    localRange.endYear !== dashboardRange.endYear;

  const [rawItems, setRawItems] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    setListError(null);
    getABCClassification({})
      .then((res) => {
        if (cancelled) return;
        setRawItems(res.items || []);
      })
      .catch((err) => {
        if (cancelled) return;
        setListError(err.message || 'Failed to load SKU list');
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Map ABC classification rows -> the SKU-picker shape this page renders.
  const sourceSKUs = useMemo(
    () =>
      rawItems.map((item) => ({
        code: item.sku_id,
        name: item.product_name || 'Unknown Product',
        brand: 'Unilever',
        cat: item.tier,
      })),
    [rawItems]
  );

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('ALL');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  // Selected SKU. Starts EMPTY — the page opens on a "pick a SKU" prompt
  // rather than auto-picking the first row of the list, which showed a chart
  // for an arbitrary SKU nobody asked for and read as if it were meaningful.
  //
  // The choice is remembered in sessionStorage rather than component state
  // because this is a route-level component: navigating to another page and
  // back remounts it, which would otherwise wipe the selection mid-session.
  // sessionStorage (not localStorage) matches "until the end of the session"
  // exactly — closing the tab starts clean again.
  const SELECTED_SKU_KEY = 'san2_selected_forecast_sku';
  const [selectedSKU, setSelectedSKU] = useState(null);

  // Restore the remembered SKU once the list has loaded — and only if that
  // code still exists in it, so a stale/renamed code can't leave the page
  // requesting a SKU that's no longer classified.
  useEffect(() => {
    if (sourceSKUs.length === 0) return;
    setSelectedSKU((prev) => {
      if (prev) return sourceSKUs.some((s) => s.code === prev.code) ? prev : null;
      let saved = null;
      try {
        saved = sessionStorage.getItem(SELECTED_SKU_KEY);
      } catch {
        saved = null; // private mode / storage blocked — just start empty
      }
      return saved ? sourceSKUs.find((s) => s.code === saved) || null : null;
    });
  }, [sourceSKUs]);

  // Persistent Pinned SKUs
  const [pinnedSKUs, setPinnedSKUs] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_pinned_skus');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  // Persistent Recently Viewed/Forecasted SKUs (Max 5)
  const [recentSKUs, setRecentSKUs] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_recent_forecast_skus');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Toggle pin/unpin SKU
  const togglePinSKU = (code, e) => {
    if (e) e.stopPropagation();
    let updated;
    if (pinnedSKUs.includes(code)) {
      updated = pinnedSKUs.filter(c => c !== code);
    } else {
      updated = [...pinnedSKUs, code];
    }
    setPinnedSKUs(updated);
    localStorage.setItem('san2_pinned_skus', JSON.stringify(updated));
  };

  // Select SKU handler
  const handleSelectSKU = (sku) => {
    setSelectedSKU(sku);
    setIsDropdownOpen(false);
    try {
      sessionStorage.setItem(SELECTED_SKU_KEY, sku.code);
    } catch { /* storage unavailable — selection still works for this view */ }

    // Update recent SKUs history (prepend, deduplicate, keep last 5)
    const updatedRecent = [sku.code, ...recentSKUs.filter(c => c !== sku.code)].slice(0, 5);
    setRecentSKUs(updatedRecent);
    localStorage.setItem('san2_recent_forecast_skus', JSON.stringify(updatedRecent));
  };

  // Clear — drops the SKU selection AND the search/filter state, returning
  // the page to the same empty "pick a SKU" prompt it opens on. Also forgets
  // the remembered selection so navigating away and back stays cleared.
  const handleClearSelection = () => {
    setSelectedSKU(null);
    setSelectedCategory('ALL');
    setSearchQuery('');
    try {
      sessionStorage.removeItem(SELECTED_SKU_KEY);
    } catch { /* nothing to forget if storage is unavailable */ }
  };

  // Filtering Logic. No brand filter: every SKU here is Unilever (see the
  // "Unilever only" scope badge above the picker) — brand is still matched
  // on for SEARCH, since typing "unilever" shouldn't come back empty.
  const filteredSKUs = useMemo(() => {
    return sourceSKUs.filter(sku => {
      const matchesSearch = searchQuery === '' ||
        sku.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.brand.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = selectedCategory === 'ALL' || sku.cat === selectedCategory;
      return matchesSearch && matchesCat;
    });
  }, [sourceSKUs, searchQuery, selectedCategory]);

  const hasActiveFilterOrSearch = selectedCategory !== 'ALL' || searchQuery.trim() !== '';

  const pinnedSKUObjects = sourceSKUs.filter(sku => pinnedSKUs.includes(sku.code));
  const recentSKUObjects = sourceSKUs.filter(sku => recentSKUs.includes(sku.code) && !pinnedSKUs.includes(sku.code));
  const catASKUObjects = sourceSKUs.filter(
    sku => sku.cat === 'A' && !pinnedSKUs.includes(sku.code) && !recentSKUs.includes(sku.code)
  );

  const isSelectedPinned = selectedSKU ? pinnedSKUs.includes(selectedSKU.code) : false;

  // Forecast data for the selected SKU — fetched from Forecast_Result via
  // GET /forecast/{sku_id}. May legitimately come back with an empty
  // forecast[] if the MA3 baseline runner (scripts/run_baseline_forecast.py)
  // hasn't produced output for this SKU.
  const [forecastResult, setForecastResult] = useState(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState(null);

  useEffect(() => {
    if (!selectedSKU) {
      setForecastResult(null);
      return;
    }
    let cancelled = false;
    setForecastLoading(true);
    setForecastError(null);
    getForecast(selectedSKU.code)
      .then((res) => {
        if (cancelled) return;
        setForecastResult(res);
      })
      .catch((err) => {
        if (cancelled) return;
        setForecastError(err.message || 'Failed to load forecast');
      })
      .finally(() => {
        if (!cancelled) setForecastLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedSKU]);

  // Combine real trailing actuals + real forecast horizon into one chart
  // series. It now dynamically fills missing months between the first and last
  // actual data point with 0 to prevent straight lines skipping across void periods.
  //
  // This page's OWN local date range (2026-09, see localRange above): actuals
  // are trimmed to [rangeStartPeriod, rangeEndPeriod] before the gap-fill
  // below runs, so a narrower pick shows a narrower trailing-history window —
  // same "picker controls what's plotted" behavior Dashboard/ABC/Bad Orders
  // have with the shared range, just scoped to this one chart. The forecast
  // point is NOT filtered by range — GET /forecast always returns MA3's
  // single latest-real-month+1 forecast regardless of what range is picked
  // (see this file's MONTH_TO_NUM comment above).
  // This SKU's own earliest real sale — independent of whatever range is
  // picked. When it's LATER than rangeStartPeriod, the chart's visible
  // start is set by this SKU genuinely having no sales before that month,
  // not by the picker "failing" to reach further back — surfaced as a
  // note below so that isn't mistaken for a bug (it isn't: some Category A
  // SKUs only have ~31 months of real history vs. others' full 38).
  // ── Per-SKU data coverage ────────────────────────────────────────────────
  // Coverage varies enormously across the corpus: SKUs begin AND end in
  // every month between 2023-01 and 2026-02 (only ~1/3 run the full span),
  // so a shared date range picked on another page is frequently outside a
  // given SKU's real history. Rather than silently drawing a truncated or
  // empty chart, the range is classified against this SKU's own bounds and
  // the result is reported to the user (see rangeStatus below).
  const skuCoverage = useMemo(() => {
    const periods = (forecastResult?.actuals || []).map((a) => a.period).sort();
    if (periods.length === 0) return null;
    return { start: periods[0], end: periods[periods.length - 1] };
  }, [forecastResult]);

  // MIN_RANGE_MONTHS (6) assumes the SKU HAS 6 months to show. Plenty of
  // real SKUs in the corpus don't — coverage runs from 2023-01 to 2026-02
  // but only ~1/3 of SKUs span the whole thing (see skuCoverage's own
  // comment above), so a SKU with 2 real months was being told to pick a
  // 6-month range it could never fill with real data — 4 of those months
  // would just be empty padding. The effective floor is now whichever is
  // SMALLER: the usual 6-month readability floor, or this SKU's own total
  // real coverage — so a 2-month SKU only needs to select 2 months, not
  // pad out to 6 for a rule that was never really about this SKU.
  const effectiveMinMonths = useMemo(() => {
    if (!skuCoverage) return MIN_RANGE_MONTHS;
    const skuSpan = monthsBetween(skuCoverage.start, skuCoverage.end);
    return Math.min(MIN_RANGE_MONTHS, skuSpan);
  }, [skuCoverage]);

  // The month the STORED forecast targets ('YYYY-MM'), sliced off the API's
  // ISO date. The pipeline always writes exactly last-real-month + 1, which
  // across the whole corpus is 2026-03.
  const storedForecastPeriod = useMemo(() => {
    const d = forecastResult?.forecast?.[0]?.forecast_date;
    return d ? String(d).slice(0, 7) : null;
  }, [forecastResult]);

  // 'invalid'   — the range itself is backwards (start after end), e.g.
  //               start Dec 2024, end Jan 2024. Checked before anything
  //               else, since asking "does this SKU have 6 months of data
  //               in a backwards range" is meaningless.
  // 'too-short' — chronologically fine, but under effectiveMinMonths — the
  //               chart below would render as 1-2 disconnected dots.
  //               Checked before coverage too: a 1-month pick that also
  //               misses this SKU's history should say "too short," not
  //               "no data," since widening it is the actual fix either way.
  //               Uses effectiveMinMonths (SKU-aware), not the flat
  //               MIN_RANGE_MONTHS, so a SKU with genuinely less than 6
  //               months of real history isn't asked to select more than
  //               it has (see effectiveMinMonths above).
  // 'ok'        — picked range sits fully inside this SKU's history
  // 'partial'   — overlaps, but one/both ends fall outside it
  // 'none'      — no overlap at all; nothing honest to plot
  const rangeStatus = useMemo(() => {
    if (rangeStartPeriod && rangeEndPeriod && rangeStartPeriod > rangeEndPeriod) return 'invalid';
    if (rangeStartPeriod && rangeEndPeriod && monthsBetween(rangeStartPeriod, rangeEndPeriod) < effectiveMinMonths) {
      return 'too-short';
    }
    if (!skuCoverage || !rangeStartPeriod || !rangeEndPeriod) return 'ok';
    if (rangeEndPeriod < skuCoverage.start || rangeStartPeriod > skuCoverage.end) return 'none';
    if (rangeStartPeriod < skuCoverage.start || rangeEndPeriod > skuCoverage.end) return 'partial';
    return 'ok';
  }, [skuCoverage, rangeStartPeriod, rangeEndPeriod, effectiveMinMonths]);

  // Snap this page's local range to exactly the months this SKU has data for.
  const applySkuCoverageRange = () => {
    if (!skuCoverage) return;
    const [sy, sm] = skuCoverage.start.split('-');
    const [ey, em] = skuCoverage.end.split('-');
    setLocalRange({
      startMonth: NUM_TO_MONTH[sm], startYear: sy,
      endMonth: NUM_TO_MONTH[em], endYear: ey,
    });
  };

  // ── The forecast point that gets plotted ────────────────────────────────
  // MA3 projects the month AFTER its last observation, so the forecast here
  // follows the selected range: end the range at Feb 2026 and it forecasts
  // Mar 2026; end it at Dec 2025 and it forecasts Jan 2026.
  //
  // Two sources, and the difference is deliberately visible to the user:
  //
  //   'stored'      — the target month matches what the pipeline actually
  //                   wrote to Forecast_Result. Carries the real confidence
  //                   interval and MAPE, both of which come from the SKU's
  //                   80/20 holdout evaluation in scripts/run_baseline_forecast.py.
  //
  //   'recomputed'  — any earlier cutoff. MA3's point forecast is just the
  //                   mean of the last 3 observations (see
  //                   analytics/forecasting/baseline.py::moving_average_forecast),
  //                   so it is honestly derivable here from real data alone.
  //                   The confidence interval is NOT: it needs that SKU's
  //                   holdout RMSE, which only the Python pipeline computes.
  //                   So no band and no MAPE are shown — they are left absent
  //                   rather than approximated. Flagged in the UI as a preview.
  //
  // Anchored to the last actual IN RANGE rather than the range's end month:
  // when a SKU's data stops early, forecasting off the range end would leave
  // a gap of empty months between the last real point and the projection.
  const MA_WINDOW = 3; // mirrors baseline.py's MA_WINDOW
  const addMonth = (period) => {
    const [y, m] = period.split('-').map(Number);
    return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
  };

  const derivedForecast = useMemo(() => {
    if (!forecastResult) return null;
    const inRange = (forecastResult.actuals || [])
      .filter((a) => (!rangeStartPeriod || a.period >= rangeStartPeriod) && (!rangeEndPeriod || a.period <= rangeEndPeriod))
      .sort((a, b) => a.period.localeCompare(b.period));
    if (inRange.length === 0) return null;

    const target = addMonth(inRange[inRange.length - 1].period);

    const stored = forecastResult.forecast?.[0];
    if (stored && storedForecastPeriod === target) {
      return {
        period: target,
        value: stored.forecast_value,
        confidenceLower: stored.confidence_lower,
        confidenceUpper: stored.confidence_upper,
        mape: stored.mape,
        source: 'stored',
      };
    }

    // MA3 = mean of the last `window` observations (all of them when the
    // series is shorter), matching baseline.py::moving_average_forecast
    // exactly — including run_baseline_forecast.py's max(0, ...) clamp, so
    // both paths produce the same number for the same months. MA3 is the
    // deployed method for every Tier A SKU (DEPLOYED_METHOD = "ma3"), so
    // there's no per-SKU method selection to reproduce here.
    const tail = inRange.slice(-MA_WINDOW);
    const value = Math.max(0, tail.reduce((sum, a) => sum + a.quantity, 0) / tail.length);
    return {
      period: target,
      value,
      confidenceLower: null,
      confidenceUpper: null,
      mape: null,
      source: 'recomputed',
      basisMonths: tail.length,
    };
  }, [forecastResult, storedForecastPeriod, rangeStartPeriod, rangeEndPeriod]);

  const chartData = useMemo(() => {
    if (!forecastResult) return [];

    // Sort actuals to ensure they are chronologically ordered, trimmed to
    // this page's own local range (never selected yet -> full history).
    const sortedActuals = [...(forecastResult.actuals || [])]
      .filter((a) => (!rangeStartPeriod || a.period >= rangeStartPeriod) && (!rangeEndPeriod || a.period <= rangeEndPeriod))
      .sort((a, b) => a.period.localeCompare(b.period));

    const actualPoints = [];
    if (sortedActuals.length > 0) {
      let currentPeriod = sortedActuals[0].period;
      const endPeriod = sortedActuals[sortedActuals.length - 1].period;
      let actualIndex = 0;

      while (currentPeriod <= endPeriod) {
        if (actualIndex < sortedActuals.length && sortedActuals[actualIndex].period === currentPeriod) {
          actualPoints.push({
            label: currentPeriod,
            actual: sortedActuals[actualIndex].quantity,
          });
          actualIndex++;
        } else {
          actualPoints.push({
            label: currentPeriod,
            actual: 0,
          });
        }

        const [yearStr, monthStr] = currentPeriod.split('-');
        let year = parseInt(yearStr, 10);
        let month = parseInt(monthStr, 10);
        month++;
        if (month > 12) {
          month = 1;
          year++;
        }
        currentPeriod = `${year}-${month.toString().padStart(2, '0')}`;
      }

      // Inject the final actual sales quantity into the forecast data key
      // so Recharts can draw a continuous line between the last actual point and the first forecast point
      const lastActualPoint = actualPoints[actualPoints.length - 1];
      if (derivedForecast) {
        lastActualPoint.forecast = lastActualPoint.actual;

        // ...and anchor the confidence band to that same point, collapsed to
        // zero width there. MA3 emits exactly ONE forecast point, and an
        // <Area> needs two points to have anything to fill between — with a
        // lone point the band rendered as a zero-width sliver, i.e. invisible.
        // Anchoring here is also the honest shape: uncertainty is nil at the
        // last known actual and widens into the forecast, so the band reads as
        // a cone rather than appearing from nowhere. Only when a real interval
        // exists — a recomputed forecast has none (see derivedForecast).
        if (derivedForecast.confidenceLower != null && derivedForecast.confidenceUpper != null) {
          lastActualPoint.ci = [lastActualPoint.actual, lastActualPoint.actual];
        }
      }
    }

    const forecastPoints = derivedForecast
      ? [{
        label: derivedForecast.period,
        forecast: derivedForecast.value,
        ci: derivedForecast.confidenceLower != null && derivedForecast.confidenceUpper != null
          ? [derivedForecast.confidenceLower, derivedForecast.confidenceUpper]
          : undefined,
      }]
      : [];
    return [...actualPoints, ...forecastPoints];
  }, [forecastResult, rangeStartPeriod, rangeEndPeriod, derivedForecast]);

  // The last real month INSIDE the selected range — the month the forecast
  // is projected from, so the "vs. last actual" comparison always pairs the
  // forecast with the observation it was actually derived from rather than
  // with a month that may sit outside the current window.
  const latestActualPoint = useMemo(() => {
    const inRange = (forecastResult?.actuals || [])
      .filter((a) => (!rangeStartPeriod || a.period >= rangeStartPeriod) && (!rangeEndPeriod || a.period <= rangeEndPeriod));
    if (inRange.length === 0) return null;
    return inRange.reduce((latest, a) => (a.period > latest.period ? a : latest), inRange[0]);
  }, [forecastResult, rangeStartPeriod, rangeEndPeriod]);

  // Forecast vs. that last real month — turns the raw forecast number into
  // an actionable "demand is rising/falling" read. null when either side
  // is missing (no forecast yet, no sales history) or the last actual was
  // 0 (a % change against zero isn't a meaningful number).
  const forecastTrendPct = useMemo(() => {
    if (!derivedForecast || !latestActualPoint || !latestActualPoint.quantity) return null;
    return ((derivedForecast.value - latestActualPoint.quantity) / latestActualPoint.quantity) * 100;
  }, [derivedForecast, latestActualPoint]);

  return (
    <div className="forecast-page">
      <div className="forecast-content">
        {/* Header */}
        <div className="forecast-header">
          <div className="header-text-group">
            <h2 className="forecast-title">
              Demand <span>forecasted</span>
            </h2>
            <p className="forecast-subtitle">
              MA3 (3-month moving average) projection for Category A SKUs, from Forecast_Result
            </p>
          </div>

          <div className="forecast-header-actions">
            <DateFilter
              localValue={localRange}
              onLocalChange={setLocalRange}
              onReset={isCustomRange ? resetToDashboardRange : undefined}
              minMonths={effectiveMinMonths}
            />
            <button
              className="browse-all-skus-btn"
              onClick={() => navigate('/sku-management')}
              title="Go to SKU Management table"
            >
              <span>Browse all SKUs</span>
              <ArrowRight size={14} />
            </button>
          </div>
        </div>

        {/* Selection Area with Filter Controls */}
        <div className="forecast-selection">
          <div className="selection-top-bar">
            <label className="selection-label">SELECT SKU TO FORECAST</label>
            {/* Replaces the old Brand dropdown, which had exactly one real
                option: this is a Unilever-only system (see the backend
                routers' hardcoded principal filter). Stated as fixed scope
                rather than offered as a choice, so nobody goes hunting for
                brands that were never in the data. */}
            <span className="forecast-scope-badge">Unilever only</span>
          </div>

          {/* Controls Bar: Filters & Search Combobox */}
          <div className="combobox-controls-bar">
            {/* Filter Chips / Dropdowns */}
            <div className="forecast-filter-group">
              <div className="filter-dropdown-wrapper">
                <span className="filter-icon-label"><Filter size={12} /> Cat:</span>
                <select
                  className="filter-select"
                  value={selectedCategory}
                  onChange={(e) => {
                    setSelectedCategory(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                >
                  <option value="ALL">All Categories</option>
                  <option value="A">Category A</option>
                  <option value="B">Category B</option>
                  <option value="C">Category C</option>
                </select>
              </div>

              {(selectedCategory !== 'ALL' || searchQuery !== '' || selectedSKU) && (
                <button
                  className="clear-filters-btn"
                  onClick={handleClearSelection}
                  title="Clear the selected SKU and all filters"
                >
                  <X size={12} />
                  <span>Clear</span>
                </button>
              )}
            </div>

            {/* Searchable Combobox */}
            <div className="search-combobox-wrapper" ref={dropdownRef}>
              <div className="search-input-inner">
                <Search className="search-icon" size={18} />
                <input
                  type="text"
                  placeholder="Search by SKU code, name, or brand..."
                  value={searchQuery}
                  onFocus={() => setIsDropdownOpen(true)}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                  className="search-input"
                />
                {searchQuery && (
                  <button className="input-clear-btn" onClick={() => setSearchQuery('')}>
                    <X size={14} />
                  </button>
                )}
              </div>

              {/* Combobox Results Dropdown Panel */}
              {isDropdownOpen && (
                <div className="combobox-results-panel">
                  {hasActiveFilterOrSearch ? (
                    /* Filtered Search Results List */
                    <div className="combobox-section">
                      <div className="section-header-title">
                        <span>SEARCH RESULTS ({filteredSKUs.length})</span>
                      </div>
                      {filteredSKUs.length > 0 ? (
                        filteredSKUs.map(sku => (
                          <div
                            key={sku.code}
                            className={`result-row ${selectedSKU?.code === sku.code ? 'selected' : ''}`}
                            onClick={() => handleSelectSKU(sku)}
                          >
                            <button
                              className={`star-pin-btn ${pinnedSKUs.includes(sku.code) ? 'pinned' : ''}`}
                              onClick={(e) => togglePinSKU(sku.code, e)}
                              title={pinnedSKUs.includes(sku.code) ? "Unpin SKU" : "Pin SKU to top"}
                              aria-label={`${pinnedSKUs.includes(sku.code) ? 'Unpin' : 'Pin'} SKU ${sku.code}`}
                              aria-pressed={pinnedSKUs.includes(sku.code)}
                            >
                              <Star size={15} fill={pinnedSKUs.includes(sku.code) ? '#F5A623' : 'none'} />
                            </button>
                            <div className="result-code-group">
                              <span className="result-sku-code">{sku.code}</span>
                              <span className="result-brand">{sku.brand}</span>
                            </div>
                            <span className="result-product-name">{sku.name}</span>
                            <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                          </div>
                        ))
                      ) : (
                        <div className="no-results-msg">No data for this selection.</div>
                      )}
                    </div>
                  ) : (
                    /* Default Panel (Empty Search & No Filters) */
                    <div className="combobox-default-view">
                      {/* Section 1: Pinned / Favorited SKUs */}
                      {pinnedSKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <Star size={12} fill="#F5A623" color="#F5A623" />
                            <span>PINNED SKUS</span>
                          </div>
                          {pinnedSKUObjects.map(sku => (
                            <div
                              key={sku.code}
                              className={`result-row ${selectedSKU?.code === sku.code ? 'selected' : ''}`}
                              onClick={() => handleSelectSKU(sku)}
                            >
                              <button
                                className="star-pin-btn pinned"
                                onClick={(e) => togglePinSKU(sku.code, e)}
                                title="Unpin SKU"
                                aria-label={`Unpin SKU ${sku.code}`}
                                aria-pressed={true}
                              >
                                <Star size={15} fill="#F5A623" />
                              </button>
                              <div className="result-code-group">
                                <span className="result-sku-code">{sku.code}</span>
                                <span className="result-brand">{sku.brand}</span>
                              </div>
                              <span className="result-product-name">{sku.name}</span>
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Section 2: Recently Forecasted SKUs */}
                      {recentSKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <Clock size={12} />
                            <span>RECENTLY FORECASTED</span>
                          </div>
                          {recentSKUObjects.map(sku => (
                            <div
                              key={sku.code}
                              className={`result-row ${selectedSKU?.code === sku.code ? 'selected' : ''}`}
                              onClick={() => handleSelectSKU(sku)}
                            >
                              <button
                                className={`star-pin-btn ${pinnedSKUs.includes(sku.code) ? 'pinned' : ''}`}
                                onClick={(e) => togglePinSKU(sku.code, e)}
                                title="Pin SKU"
                                aria-label={`Pin SKU ${sku.code}`}
                                aria-pressed={pinnedSKUs.includes(sku.code)}
                              >
                                <Star size={15} fill={pinnedSKUs.includes(sku.code) ? '#F5A623' : 'none'} />
                              </button>
                              <div className="result-code-group">
                                <span className="result-sku-code">{sku.code}</span>
                                <span className="result-brand">{sku.brand}</span>
                              </div>
                              <span className="result-product-name">{sku.name}</span>
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Section 3: Category A SKUs */}
                      {catASKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <span>CATEGORY A SKUS (HIGH PRIORITY)</span>
                          </div>
                          {catASKUObjects.map(sku => (
                            <div
                              key={sku.code}
                              className={`result-row ${selectedSKU?.code === sku.code ? 'selected' : ''}`}
                              onClick={() => handleSelectSKU(sku)}
                            >
                              <button
                                className={`star-pin-btn ${pinnedSKUs.includes(sku.code) ? 'pinned' : ''}`}
                                onClick={(e) => togglePinSKU(sku.code, e)}
                                title="Pin SKU"
                                aria-label={`Pin SKU ${sku.code}`}
                                aria-pressed={pinnedSKUs.includes(sku.code)}
                              >
                                <Star size={15} fill={pinnedSKUs.includes(sku.code) ? '#F5A623' : 'none'} />
                              </button>
                              <div className="result-code-group">
                                <span className="result-sku-code">{sku.code}</span>
                                <span className="result-brand">{sku.brand}</span>
                              </div>
                              <span className="result-product-name">{sku.name}</span>
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {listLoading && <p className="forecast-subtitle">Loading SKU list…</p>}
        {listError && <p className="forecast-subtitle">Error: {listError}</p>}

        {/* Nothing picked yet — the page deliberately opens here instead of
            auto-selecting a SKU, so the first chart a user sees is always one
            they actually asked for. Occupies the chart's slot so the layout
            doesn't jump once a selection is made. */}
        {!selectedSKU && !listLoading && !listError && (
          <div className="forecast-empty-state">
            <div className="forecast-empty-icon">
              <Search size={28} strokeWidth={1.6} />
            </div>
            <h3 className="forecast-empty-title">Select a SKU to see its forecast</h3>
            <p className="forecast-empty-body">
              Search by SKU code, product name, or brand above — or pick one from your pinned and
              recently viewed SKUs. The demand history and MA3 forecast will appear here.
            </p>
          </div>
        )}

        {selectedSKU && (
          <>
            {/* Selected SKU Card */}
            <div className="selected-sku-card">
              <div className="sku-info-left">
                <div className="sku-code-header-row">
                  <span className="sku-code-label">SELECTED SKU CODE</span>
                  <button
                    className={`card-star-btn ${isSelectedPinned ? 'pinned' : ''}`}
                    onClick={(e) => togglePinSKU(selectedSKU.code, e)}
                    title={isSelectedPinned ? "Unpin SKU" : "Pin SKU to top of search"}
                    aria-label={`${isSelectedPinned ? 'Unpin' : 'Pin'} SKU ${selectedSKU.code}`}
                    aria-pressed={isSelectedPinned}
                  >
                    <Star size={15} fill={isSelectedPinned ? '#F5A623' : 'none'} color={isSelectedPinned ? '#F5A623' : '#a0aec0'} />
                    <span className="pin-text">{isSelectedPinned ? 'Pinned' : 'Pin SKU'}</span>
                  </button>
                </div>
                <span className="sku-code-value">{selectedSKU.code}</span>
                <div className="sku-meta-row">
                  <span className="sku-product-name">{selectedSKU.name}</span>
                  <span className="sku-brand-name">{selectedSKU.brand}</span>
                </div>
              </div>
              <div className="sku-info-right">
                <span className={`forecast-cat-badge cat-${selectedSKU.cat}`}>Category {selectedSKU.cat}</span>
              </div>
            </div>

            {/* Chart Section */}
            {/* Keyed on the selected SKU so switching products replays the
                container's entrance animation (index.css's chartWidgetEnter)
                — a clear "this is a different product now" signal. The key
                deliberately excludes the date range: a range tweak keeps the
                same chart mounted and lets Recharts tween between the old
                and new values, which reads better than a re-fade for what is
                the same product's data. */}
            <div className="forecast-chart-container" key={selectedSKU?.code || 'none'}>
              {forecastLoading && <p className="forecast-subtitle">Loading forecast…</p>}
              {forecastError && <p className="forecast-subtitle">Error: {forecastError}</p>}

              {!forecastLoading && !forecastError && forecastResult && forecastResult.forecast.length === 0 && (
                <p className="forecast-subtitle">
                  No MA3 forecast has been generated for {selectedSKU.code} yet.
                </p>
              )}

              {/* Start after end (e.g. Dec 2024 - Jan 2024) — DateFilter
                  already shows an inline warning the instant this happens,
                  but this page still has to refuse to render a chart for a
                  backwards range rather than silently treating it as empty.
                  Offers a one-click fix (swap the two dates) since, unlike
                  the 'none' case below, there's no ambiguity about what the
                  user actually meant. */}
              {!forecastLoading && !forecastError && forecastResult && rangeStatus === 'invalid' && (
                <div className="forecast-range-error">
                  <span className="forecast-range-error-title">Invalid date range</span>
                  <p className="forecast-range-error-body">
                    Your start date (<strong>{formatPeriod(rangeStartPeriod)}</strong>) is after your end date
                    (<strong>{formatPeriod(rangeEndPeriod)}</strong>). Pick a start date on or before the end date
                    to see this SKU&apos;s demand history and forecast.
                  </p>
                  <button
                    className="forecast-range-fix-btn"
                    onClick={() => setLocalRange({
                      startMonth: localRange.endMonth, startYear: localRange.endYear,
                      endMonth: localRange.startMonth, endYear: localRange.startYear,
                    })}
                  >
                    Swap dates ({formatPeriod(rangeEndPeriod)} – {formatPeriod(rangeStartPeriod)})
                  </button>
                </div>
              )}

              {/* Chronologically fine but too narrow to read as a trend —
                  floor is effectiveMinMonths, not a flat MIN_RANGE_MONTHS,
                  so a SKU with less than 6 months of real history (common —
                  see skuCoverage's comment above) only has to select as
                  many months as it actually has, not pad out to 6. Fix
                  button widens to exactly that floor, ending at whatever
                  end date the user already picked, rather than resetting
                  the whole selection. */}
              {!forecastLoading && !forecastError && forecastResult && rangeStatus === 'too-short' && (
                <div className="forecast-range-error">
                  <span className="forecast-range-error-title">
                    Range too short — {monthsBetween(rangeStartPeriod, rangeEndPeriod)} month
                    {monthsBetween(rangeStartPeriod, rangeEndPeriod) === 1 ? '' : 's'} selected
                  </span>
                  <p className="forecast-range-error-body">
                    <strong>{formatPeriod(rangeStartPeriod)} – {formatPeriod(rangeEndPeriod)}</strong> isn&apos;t
                    enough points for a readable trend. Select at least <strong>{effectiveMinMonths} month{effectiveMinMonths === 1 ? '' : 's'}</strong>
                    {effectiveMinMonths < MIN_RANGE_MONTHS
                      ? ` — this SKU only has ${effectiveMinMonths} month${effectiveMinMonths === 1 ? '' : 's'} of real history, so that's this SKU's full available range.`
                      : '.'}
                  </p>
                  <button
                    className="forecast-range-fix-btn"
                    onClick={() => {
                      const widerStart = periodMinusMonths(rangeEndPeriod, effectiveMinMonths);
                      const [wy, wm] = widerStart.split('-');
                      setLocalRange({
                        startMonth: NUM_TO_MONTH[wm], startYear: wy,
                        endMonth: localRange.endMonth, endYear: localRange.endYear,
                      });
                    }}
                  >
                    Use last {effectiveMinMonths} month{effectiveMinMonths === 1 ? '' : 's'} (ending {formatPeriod(rangeEndPeriod)})
                  </button>
                </div>
              )}

              {/* No overlap at all between the picked range and this SKU's
                  history — a chart here would be an empty grid, so state the
                  problem and offer the fix instead of rendering nothing. */}
              {!forecastLoading && !forecastError && forecastResult && rangeStatus === 'none' && (
                <div className="forecast-range-error">
                  <span className="forecast-range-error-title">
                    No data for {selectedSKU.code} in the selected range
                  </span>
                  <p className="forecast-range-error-body">
                    You selected <strong>{formatPeriod(rangeStartPeriod)} – {formatPeriod(rangeEndPeriod)}</strong>,
                    but this SKU only has recorded sales from{' '}
                    <strong>{formatPeriod(skuCoverage?.start)}</strong> to{' '}
                    <strong>{formatPeriod(skuCoverage?.end)}</strong>. Pick a range inside that window to see its
                    demand history and forecast.
                  </p>
                  <button className="forecast-range-fix-btn" onClick={applySkuCoverageRange}>
                    Use this SKU&apos;s range ({formatPeriod(skuCoverage?.start)} – {formatPeriod(skuCoverage?.end)})
                  </button>
                </div>
              )}

              {!forecastLoading && !forecastError && forecastResult && (rangeStatus === 'ok' || rangeStatus === 'partial') && (
                <>
                  {/* Headline Forecast Stat Row — the number this whole page
                      exists to produce (next period's forecast) plus how it
                      compares to the last real month, so a reviewer doesn't
                      have to read it off the chart by eye. Replaces MAPE/
                      HORIZON: MA3 is a single one-step-ahead model, so
                      "accuracy of the latest run" and "how many points" (always
                      1) aren't meaningful headline numbers for it the way they
                      were for the old multi-point SARIMA forecast. */}
                  <div className="forecast-accuracy-row">
                    {/* Each value is tinted to match the chart series it
                        refers to (violet = forecast line, indigo = actual
                        line, pale violet = confidence band), so the numbers
                        and the graph read as one thing. */}
                    <div className="forecast-stat-block">
                      <span className="forecast-stat-label">Next period forecast</span>
                      <span className="forecast-stat-value forecast-stat-value-forecast">
                        {derivedForecast ? (
                          <>
                            <span className="forecast-stat-number">
                              {Math.round(derivedForecast.value).toLocaleString()}
                            </span>
                            <span className="forecast-stat-unit">units</span>
                          </>
                        ) : (
                          '—'
                        )}
                      </span>
                      <span className="forecast-stat-desc">
                        {derivedForecast ? `for ${formatPeriod(derivedForecast.period)}` : 'no MA3 forecast yet'}
                      </span>
                    </div>

                    <div className="forecast-stat-divider" />

                    <div className="forecast-stat-block">
                      <span className="forecast-stat-label">Vs. last actual</span>
                      {forecastTrendPct === null ? (
                        <span className="forecast-stat-value forecast-stat-value-neutral">—</span>
                      ) : (
                        <span
                          className={`forecast-stat-value forecast-trend-chip ${forecastTrendPct > 0.5 ? 'trend-up' : forecastTrendPct < -0.5 ? 'trend-down' : 'trend-flat'
                            }`}
                        >
                          {forecastTrendPct > 0.5 ? (
                            <ArrowUp size={16} className="forecast-trend-icon" />
                          ) : forecastTrendPct < -0.5 ? (
                            <ArrowDown size={16} className="forecast-trend-icon" />
                          ) : (
                            <Minus size={16} className="forecast-trend-icon" />
                          )}
                          {Math.abs(forecastTrendPct).toFixed(1)}%
                        </span>
                      )}
                      <span className="forecast-stat-desc">
                        {latestActualPoint
                          ? `${latestActualPoint.quantity.toLocaleString()} units in ${formatPeriod(latestActualPoint.period)}`
                          : 'no sales history yet'}
                      </span>
                    </div>

                    {/* Surfaces the band the chart draws as an actual number.
                        Worth its own slot: MA3's intervals on this data are
                        very wide, and that spread is a real caveat a reader
                        should see rather than having to eyeball off the cone. */}
                    {derivedForecast?.confidenceLower != null &&
                      derivedForecast?.confidenceUpper != null && (
                        <>
                          <div className="forecast-stat-divider" />
                          <div className="forecast-stat-block">
                            <span className="forecast-stat-label">Likely range</span>
                            <span className="forecast-stat-value forecast-stat-value-range">
                              <span className="range-low">
                                {Math.round(derivedForecast.confidenceLower).toLocaleString()}
                              </span>
                              <span className="range-dash">–</span>
                              <span className="range-high">
                                {Math.round(derivedForecast.confidenceUpper).toLocaleString()}
                              </span>
                            </span>
                            <span className="forecast-stat-desc">confidence interval, units</span>
                          </div>
                        </>
                      )}
                  </div>

                  {/* Partial overlap: the chart is real but narrower than what
                      was picked. Says exactly which end fell short and why,
                      names this SKU's true window, and offers a one-click
                      snap — so a short chart never reads as a broken filter. */}
                  {rangeStatus === 'partial' && skuCoverage && (
                    <div className="forecast-range-warning">
                      <div className="forecast-range-warning-text">
                        <strong>Showing {formatPeriod(chartData[0]?.label)} – {formatPeriod(skuCoverage.end)}.</strong>{' '}
                        {selectedSKU.code} only has recorded sales from {formatPeriod(skuCoverage.start)} to{' '}
                        {formatPeriod(skuCoverage.end)}
                        {rangeStartPeriod < skuCoverage.start && rangeEndPeriod > skuCoverage.end
                          ? ', so both ends of your selected range fall outside it.'
                          : rangeStartPeriod < skuCoverage.start
                            ? `, so the start of your range (${formatPeriod(rangeStartPeriod)}) has no data.`
                            : `, so the end of your range (${formatPeriod(rangeEndPeriod)}) has no data.`}
                      </div>
                      <button className="forecast-range-fix-btn" onClick={applySkuCoverageRange}>
                        Use this SKU&apos;s range
                      </button>
                    </div>
                  )}

                  {/* Never let a recomputed forecast pass as pipeline output.
                      The point estimate is a real MA3 calculation on real
                      months, but it has no confidence interval or accuracy
                      score because those need the holdout evaluation only
                      scripts/run_baseline_forecast.py performs. */}
                  {derivedForecast?.source === 'recomputed' && (
                    <p className="forecast-range-note">
                      <strong>Preview forecast for {formatPeriod(derivedForecast.period)}.</strong>{' '}
                      Because your range ends before {formatPeriod(skuCoverage?.end)}, this is MA3 recalculated
                      from the last {derivedForecast.basisMonths} month
                      {derivedForecast.basisMonths === 1 ? '' : 's'} in range. No confidence interval or accuracy
                      score is shown — those come from the model run&apos;s holdout evaluation, which only exists
                      for the stored {formatPeriod(storedForecastPeriod)} forecast. Extend the range to{' '}
                      {formatPeriod(skuCoverage?.end)} to see it.
                    </p>
                  )}

                  {/* Chart */}
                  <div className="chart-wrapper">
                    {/* height 420 + bottom margin 32: the X tick row sits
                        INSIDE the SVG, so with bottom:0 the month labels were
                        being clipped off the bottom edge on load. */}
                    <ResponsiveContainer width="100%" height={420}>
                      <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 8, bottom: 32 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                        <XAxis
                          dataKey="label"
                          axisLine={true}
                          tickLine={true}
                          tick={{ fill: '#718096', fontSize: 11 }}
                          tickFormatter={formatAxisPeriod}
                          tickMargin={10}
                          minTickGap={12}
                          // Recharts' default tick-skip anchors from the END
                          // of the axis (interval="preserveEnd") — harmless
                          // at the old fixed ~12-point series, but with a
                          // range picker now able to span ~39 months
                          // (Jan 2023 - Mar 2026), that default silently
                          // dropped the label at the true first month,
                          // reading as "the chart starts later than I
                          // picked" even though the plotted line itself
                          // was always correct (verified: chartData's
                          // first point is genuinely the picked start
                          // month). preserveStart guarantees the first
                          // tick is always shown; equidistant keeps the
                          // rest evenly spaced instead of clumping.
                          interval="equidistantPreserveStart"
                        />
                        <YAxis
                          axisLine={true}
                          tickLine={true}
                          tick={{ fill: '#718096', fontSize: 11 }}
                          tickFormatter={formatAxisQty}
                          width={56}
                          tickMargin={8}
                        />
                        <Tooltip content={<CustomTooltip />} />

                        {/* Drawn before the lines so the band sits behind
                            them. A faint stroke gives the cone a readable
                            edge — the pale fill alone washed out against the
                            white card at this opacity. */}
                        <Area
                          type="monotone"
                          dataKey="ci"
                          stroke={COLORS.forecast}
                          strokeOpacity={0.35}
                          strokeWidth={1}
                          fill={COLORS.forecast}
                          fillOpacity={0.16}
                          name="Confidence interval"
                          {...chartAnim()}
                          connectNulls={false}
                        />

                        {/* Teal, not the old indigo: indigo sat too close to
                            the forecast's violet to tell apart in a small
                            legend swatch. Teal-vs-violet is also exactly how
                            the Dashboard's portfolio forecast already
                            separates actual from forecast, so the two pages
                            now agree. */}
                        <Line
                          type="monotone"
                          dataKey="actual"
                          stroke={CHART_COLORS.salesSeries}
                          strokeWidth={2}
                          dot={{ r: 3, fill: CHART_COLORS.salesSeries, strokeWidth: 0 }}
                          activeDot={{ r: 6 }}
                          name="Actual Sales"
                          {...chartAnim()}
                          connectNulls
                        />

                        <Line
                          type="monotone"
                          dataKey="forecast"
                          stroke={COLORS.forecast}
                          strokeWidth={2}
                          strokeDasharray="5 5"
                          dot={{ r: 4, fill: COLORS.forecast, strokeWidth: 0 }}
                          activeDot={{ r: 6 }}
                          name="Forecast"
                          {...chartAnim()}
                          connectNulls
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Chart legend — bottom-center, matching the
                      .custom-legend convention every other page's charts
                      use (Dashboard/Bad Orders' Charts.jsx), so the legend
                      sits in the same spot on every graph app-wide instead
                      of this page being the one exception up at top-right.
                      Swatches are inline SVG so each one is an exact
                      miniature of the mark it stands for (solid stroke,
                      dashed stroke, filled band) — a CSS-only swatch faking
                      the dash via a background gradient rendered as a lumpy
                      bowtie at this size. */}
                  <div className="chart-legend">
                    {chartData.some((pt) => pt.actual != null) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <line x1="1" y1="6" x2="27" y2="6" stroke={CHART_COLORS.salesSeries} strokeWidth="2.5" strokeLinecap="round" />
                        </svg>
                        <span className="legend-label">Actual Sales</span>
                      </div>
                    )}
                    <div className="legend-item">
                      <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                        <line x1="1" y1="6" x2="27" y2="6" stroke={COLORS.forecast} strokeWidth="2.5" strokeLinecap="round" strokeDasharray="6 4" />
                      </svg>
                      <span className="legend-label">Forecast</span>
                    </div>
                    {forecastResult.forecast.some((f) => f.confidence_lower != null && f.confidence_upper != null) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <rect
                            x="1" y="1.5" width="26" height="9" rx="2.5"
                            fill={COLORS.forecast} fillOpacity="0.16"
                            stroke={COLORS.forecast} strokeOpacity="0.35" strokeWidth="1"
                          />
                        </svg>
                        <span className="legend-label">Confidence Interval</span>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default SKUForecast;
