import React, { useState, useEffect, useRef, useMemo } from 'react';
import SectionLede from './ui/SectionLede';
import { useNavigate, useOutletContext, useSearchParams } from 'react-router-dom';
import { Search, Pin, ArrowRight, Clock, Filter, X, ArrowUp, ArrowDown, Minus, AlertTriangle, CheckCircle2 } from 'lucide-react';
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
  ReferenceArea,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import { COLORS, CHART_COLORS } from '../theme/colors';
import { useChartZoom, ChartZoomSlider, seriesDot, pointLabels, GRID_PROPS, EDGE_LABEL_MARGIN } from './ChartZoom';
import { ChartTable, ChartViewToggle } from './ChartTable';
import { useEntranceReplay } from '../theme/useEntranceReplay';
import RefreshingNote from './RefreshingNote';
import { LoadingStatus, SkeletonChart, SkeletonLine } from './Skeleton';
import LoadError, { describeLoadError } from './ui/LoadError';
import SlowLoadNotice from './ui/SlowLoadNotice';
import { getABCClassification } from '../api/abc';
import { getForecast } from '../api/forecast';
import { getForecastAccuracy, getDashboardData } from '../api/dashboard';
import { getRecommendations } from '../api/recommendations';
import { getSKUs } from '../api/sku';
import { useBrandLookup } from '../utils/useBrandLookup';
import { describeServedModel, describeFallbackReason } from '../utils/forecastModel';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import TierBasisLabel from './TierBasisLabel';
import DateFilter from './DateFilter';
import SkuDemandPatternPanel from './SkuDemandPatternPanel';
import { FIRST_DATA_YEAR, LATEST_DATA_PERIOD } from '../dataCoverage';
import { isPlaceholderPeriod, isPreviewMode } from '../dataMode';
import { placeholderSpan, renderPlaceholderBand } from '../utils/placeholderBand';
import InfoTip from './InfoTip';
import MonthTick, { MONTH_TICK_EXTRA_HEIGHT, monthName } from './MonthTick';
import PageHeader from './ui/PageHeader';
import ProductName from './ProductName';
import './SKUForecast.css';
import GapNote from './GapNote';
import { DemoCategoryForecast } from './DemoForecasts';
import { gapLabel } from '../utils/gapReasons';
import { calendarSignoffText } from '../utils/calendarAdjustment';
import { AccuracyLevels, ForecastErrorCard, StockLimitedNote, STOCK_LIMITED_TEXT } from './PendingCards';
import ExactValue from './ExactValue';
import { formatApprox } from '../utils/formatNumber';
import {
  PAGE_NAMES, RELIABILITY_SHORT, TIER_LABEL, tierBadge, tierSingular, tierTechnical,
} from '../labels';
import { URGENCY_HOVER, getUrgencyBadge } from '../utils/urgency';

// Pinned-star colour: brand chrome (--color-brand-primary's hex — SVG
// presentation attributes can't take a CSS var()). It used to be the
// amber data colour, which means "watch" everywhere else in the app.
// Forecast accuracy percentages (WAPE) are held back while they are
// recomputed on the fairer test — see the stat block that reads this.
const SHOW_ACCURACY_PCT = false;

// Weeks in an average month (analytics/params.py WEEKS_PER_MONTH, 365.25/12/7):
// a product outside the order plan has its weeks left as stock ÷ (forecast ÷ this).
const WEEKS_PER_MONTH = 365.25 / 12 / 7;

// The order plan's urgency (GET /recommendations), most urgent first, and its
// pill: the Reorder page's own order and classes.
const URGENCY_RANK = { CRITICAL: 0, URGENT: 1, PLANNED: 2, 'NO DATA': 3 };

// A month the chart draws that was generated, not recorded (backend/
// series_gaps.py): marked on the chart, and its note shown, only when drawn.
const GENERATED_REASONS = new Set([
  'no_data_recorded_before_2023', 'interpolated', 'taxonomy_change_bridge',
  'no_observation_before_series_start', 'series_gap_forward_filled',
]);

// Which model a product's sales months pick (analytics/forecasting/router.py
// LIVE_MODEL over length_v2's 3 / 12 / 24 thresholds).
const modelRule = (months) => (months >= 24 ? '24 or more → XGBoost + MA3 average'
  : months >= 12 ? '12–23 → TSB' : '3–11 → 3-month average');

const fmtPcs = (v) => (v == null ? '—' : Math.round(v).toLocaleString());
const fmtWeeks = (w) => (w == null || !Number.isFinite(w) ? '—' : `${w < 10 ? w.toFixed(1) : Math.round(w)} weeks`);

// How long a plan row's stock lasts, in words (2026-10-20): a product the
// plan reads as 0 because it is missing from the stock count says so; a
// counted 0 is out of stock; under a day (1/7 of a week) says so instead of
// "0.0 weeks". Display only: the cover is the plan's own figure.
const NOT_IN_COUNT = 'Not in the stock count';
const coverText = (item, weeks) => {
  if (item.stock_not_in_count) return NOT_IN_COUNT;
  if (item.current_stock === 0) return 'Out of stock';
  if (weeks != null && Number.isFinite(weeks) && weeks < 1 / 7) return 'Less than a day';
  return fmtWeeks(weeks);
};


// The order as the plan works it out (the Reorder page's own arithmetic,
// ReorderRecommendations.jsx lpQtyTitle): the month's forecast + the
// order-up-to level (which includes the keep-at-least level) − stock on hand,
// never below 0, less any cut to fit the supplier allocation.
const orderBreakdown = (item, month) => {
  const n = (v) => Math.round(v).toLocaleString();
  const stock = item.stock_not_in_count ? '0 (not in the stock count)' : n(item.current_stock ?? 0);
  const parts = [
    item.forecast_units != null ? `${n(item.forecast_units)} forecast${month ? ` for ${month}` : ''}` : null,
    `${n(item.rop_i)} order up to (includes ${n(item.ss_i)} keep at least)`,
  ].filter(Boolean).join(' + ');
  const need = Math.max(0, (item.forecast_units ?? 0) + item.rop_i - (item.current_stock ?? 0));
  const line = `${parts} − ${stock} in stock = ${n(need)} pcs.`;
  return item.short_units > 0
    ? `${line} ${n(item.short_units)} cut to fit the supplier allocation, so the order is ${n(item.q_i)} pcs.`
    : line;
};

// Runs of consecutive chart points matching `pred`, as [first, last] labels.
const pointRuns = (points, pred) => {
  const runs = [];
  let start = null;
  let prev = null;
  points.forEach((pt) => {
    if (pred(pt)) {
      if (start == null) start = pt.label;
      prev = pt.label;
    } else if (start != null) {
      runs.push([start, prev]);
      start = null;
    }
  });
  if (start != null) runs.push([start, prev]);
  return runs;
};

const PIN_COLOR = '#C74E3D';
// The Show filter's "Pinned" option (2026-10-22): the search list and the
// order-plan table keep only pinned products.
const PINNED_FILTER = 'PINNED';
const PIN_IDLE_COLOR = '#667085';
// Months where stock may have run out: amber, the app's "watch" colour.
const STOCK_LIMITED_FILL = '#F59E0B';

// Del Monte's sales data is invoice-grain with no SKU column, so the pipeline
// never forecasts it per SKU — its ABC rows are product categories. With the
// Topbar on Del Monte this replaces the picker; it also heads the message
// for a Del Monte row that reaches the chart card some other way.
const DEL_MONTE_NO_FORECAST =
  'No product forecast for Del Monte: its sales data has no product detail, only category sales.';

// The SKU picked this session, held at module scope rather than in
// component state or sessionStorage.
//
// This is a route-level component, so navigating to another page and back
// remounts it — component state alone would drop the selection on every
// tab switch. sessionStorage is the other obvious home and is wrong in the
// opposite direction: it survives a page reload, and a reload is exactly
// when this page should go back to asking the user to pick a SKU. A module
// variable lives as long as the loaded JS context does, which is precisely
// "until the tab is refreshed or closed".
let rememberedSKUCode = null;

// Unlike Dashboard/ABC Classification/Reorder Recs, this page's
// date range is its OWN, local to this component — not the shared
// cross-page one in DashboardLayout (see the localRange state below, and
// DateFilter's "local mode"). It seeds from the dashboard's range once on
// mount, then never affects and is never affected by any other page.
// Trims which real actuals get plotted (see chartData below); the
// forecast itself stays the pipeline's stored one-step value — the served
// model (MA3, TSB or the XGBoost + MA3 average, see utils/forecastModel.js)
// is batch-computed, not something a picked range can honestly recompute on
// the fly. The one exception, a served MA3, is handled in derivedForecast.
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

// The newest stored forecast row. GET /forecast/{sku} lists rows oldest
// first and the runner keeps earlier planning months, so [0] would keep
// serving the oldest month once a newer one is written.
const latestForecastRow = (result) => {
  const rows = result?.forecast;
  return rows?.length ? rows[rows.length - 1] : null;
};

// 'YYYY-MM' minus (count-1) months, inclusive — the start of a `count`-month
// window ending at `period`. Used by the too-short fix button to widen a
// range by pulling the start back, keeping the end (what the user actually
// picked) untouched.
// The same month a year earlier: "2026-02" -> "2025-02".
const yearEarlier = (period) => {
  const [y, m] = period.split('-');
  return `${parseInt(y, 10) - 1}-${m}`;
};

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

const CustomTooltip = ({ active, payload, label, bandLabel = 'Likely range', bandLevel = null }) => {
  if (active && payload && payload.length) {
    // Each line is drawn twice — the Line, plus the Area shading under it —
    // so the raw payload carries every value twice over. The fills declare
    // tooltipType="none", which Recharts passes through as `type`; dropping
    // those leaves one entry per real series.
    const series = payload.filter(p => p.type !== 'none' && p.value != null);
    const hasActual = series.some(p => p.dataKey === 'actual');
    // Last year reads after this month's own figures.
    const displayPayload = (hasActual
      ? series.filter(p => p.dataKey !== 'forecast')
      : series)
      .slice()
      .sort((a, b) => (a.dataKey === 'lastYear') - (b.dataKey === 'lastYear'));

    const qty = (v) => Math.round(v).toLocaleString();

    return (
      <div className="forecast-tooltip">
        <p className="tooltip-label">{formatAxisPeriod(label)}</p>
        {payload[0]?.payload?.reason && (
          <p className="tooltip-item tooltip-gap">{gapLabel(payload[0].payload.reason)}</p>
        )}
        {payload[0]?.payload?.stockLimited && (
          <p className="tooltip-item tooltip-gap">Possibly stock-limited: {STOCK_LIMITED_TEXT}.</p>
        )}
        {displayPayload.map((entry, index) => {
          if (entry.dataKey === 'ci') {
            // Zero-width at the anchor point (see chartData) — that's the
            // "no uncertainty yet" join, not a real interval, so skip it.
            if (!Array.isArray(entry.value) || entry.value[0] === entry.value[1]) return null;
            return (
              <p key={index} className="tooltip-item">
                <span className="tooltip-dot" style={{ backgroundColor: COLORS.forecastBg, border: `1px solid ${COLORS.forecast}` }}></span>
                Most likely between {qty(entry.value[0])} and {qty(entry.value[1])} pcs
              </p>
            );
          }
          return (
            <p key={index} className="tooltip-item">
              <span className="tooltip-dot" style={{ backgroundColor: entry.color }}></span>
              {entry.name}: {qty(entry.value)} pcs
            </p>
          );
        })}
        {/* The band in plain words (Technical Adviser, 2 Oct 2026: "what is
            the range around the forecast?"). The level is GET /forecast's
            own interval.level_pct, so "9 times in 10" is that figure. */}
        {displayPayload.some((e) => e.dataKey === 'ci' && Array.isArray(e.value) && e.value[0] !== e.value[1]) && (
          <p className="tooltip-band-note">
            {bandLevel != null
              ? `Sales should land in this band about ${Math.round(bandLevel / 10)} times in 10.`
              : 'Sales usually land in this band.'}
            {' '}The keep-at-least level (safety stock) is the buffer for months near the top of it.
          </p>
        )}
      </div>
    );
  }
  return null;
};

const SKUForecast = () => {
  const navigate = useNavigate();
  const canOpenReorder = usePermissions().hasPermission(P.LP_VIEW);
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
  // Shared principal scope (Topbar's segmented control).
  const { principal } = dashboardRange;
  // Del Monte has no SKU-level forecasts at all (DEL_MONTE_NO_FORECAST): the
  // page shows that message in place of the picker and fetches nothing.
  const isDelMonte = principal === 'delmonte';
  // Preview (backend/data_mode.py): with the what-if forecasts built, this
  // page shows them against the five-year history and the shared range
  // passes through. Without them the forecasts are the live, real-only
  // ones, so the range never reaches into the placeholder months: a shared
  // range starting there starts at the first real month here instead, and
  // one lying wholly inside them falls back to all real months.
  const previewOn = isPreviewMode(dashboardRange.dataMode);
  // Synthetic data on, and the server has some (DM_DEMO_ENABLED): Del Monte
  // then shows the demonstration's category forecasts in place of its message.
  const syntheticOn = previewOn && dashboardRange.syntheticAvailable === true;
  const whatIf = previewOn && Boolean(dashboardRange.previewInfo?.outputs);
  const realFloor = previewOn && !whatIf;
  const seedRange = (() => {
    const shared = {
      startMonth: dashboardRange.startMonth,
      startYear: dashboardRange.startYear,
      endMonth: dashboardRange.endMonth,
      endYear: dashboardRange.endYear,
    };
    if (!realFloor || Number(shared.startYear) >= FIRST_DATA_YEAR) return shared;
    const floorStart = { startMonth: 'Jan', startYear: String(FIRST_DATA_YEAR) };
    return Number(shared.endYear) >= FIRST_DATA_YEAR
      ? { ...shared, ...floorStart }
      : { ...floorStart, endMonth: (dashboardRange.latestPeriod || LATEST_DATA_PERIOD).month,
        endYear: (dashboardRange.latestPeriod || LATEST_DATA_PERIOD).year };
  })();
  // The page follows the dashboard's range LIVE (Technical Adviser, 2 Oct
  // 2026: change the filter and the screen answers; one range across the
  // pages). A pick on this page's own picker is an override, kept until
  // "Clear"; with none, the range is the shared one as it is now, so a
  // change on the dashboard (or a preset) reaches this page too.
  const [rangeOverride, setLocalRange] = useState(null);
  const localRange = rangeOverride ?? seedRange;
  // GET /data-mode answers after this page first renders; once the what-if
  // outputs are known to exist, drop any override so the five-year range shows.
  useEffect(() => {
    if (whatIf) setLocalRange(null);
  }, [whatIf]);
  const rangeStartPeriod = toPeriod(localRange.startMonth, localRange.startYear);
  const rangeEndPeriod = toPeriod(localRange.endMonth, localRange.endYear);

  // "Clear" (DateFilter's local-mode reset button) — snaps this page's own
  // range back to the dashboard's, same source the initial seed above used.
  // Nothing else on this page writes to the shared dashboard range, so
  // comparing localRange against the LIVE dashboardRange is equivalent to
  // comparing against the original seed — only shown once the user has
  // actually picked something different, never just because the page loaded.
  const resetToDashboardRange = () => setLocalRange(null);
  const isCustomRange = rangeOverride != null && (
    localRange.startMonth !== seedRange.startMonth ||
    localRange.startYear !== seedRange.startYear ||
    localRange.endMonth !== seedRange.endMonth ||
    localRange.endYear !== seedRange.endYear);

  const [rawItems, setRawItems] = useState([]);
  // Which ABC run the classes on this page are from (GET /abc's tier_a_periods),
  // stated as the Dashboard, ABC, Reorder and SKU Management pages state it.
  const [tierAPeriods, setTierAPeriods] = useState({});
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(null);
  // Try again on a failed load re-runs that request (the list, the forecast).
  const [listAttempt, setListAttempt] = useState(0);
  const [forecastAttempt, setForecastAttempt] = useState(0);

  useEffect(() => {
    // Del Monte's ABC rows are product categories, not SKUs — there is
    // nothing to pick, so there is nothing to load.
    if (principal === 'delmonte') {
      setRawItems([]);
      setListError(null);
      setListLoading(false);
      return undefined;
    }
    let cancelled = false;
    setListLoading(true);
    setListError(null);
    getABCClassification({ principal })
      .then((res) => {
        if (cancelled) return;
        setRawItems(res.items || []);
        setTierAPeriods(res.tier_a_periods || {});
      })
      .catch((err) => {
        if (cancelled) return;
        setListError(describeLoadError(err));
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => { cancelled = true; };
  }, [principal, listAttempt]);

  // GET /abc has no brand field; this used to print 'Unilever' (the
  // principal) as every SKU's brand. Real brand comes from the product
  // master, same lookup ABC Classification and Reorder Recs use.
  const brandLookup = useBrandLookup(principal);

  // Map ABC classification rows -> the SKU-picker shape this page renders.
  const sourceSKUs = useMemo(
    () =>
      rawItems.map((item) => ({
        code: item.sku_id,
        name: item.product_name || 'Unknown Product',
        brand: brandLookup?.get(String(item.sku_id)) ?? '',
        cat: item.tier,
        principal: item.principal,
      })),
    [rawItems, brandLookup]
  );

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('ALL');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  // Selected SKU. The page opens with NOTHING selected: no chart, no
  // demand pattern, just the prompt to pick one. It used to auto-select the
  // top Category A SKU by revenue, which meant the first thing a user saw
  // was a forecast for a product they hadn't asked about — easy to read as
  // "this is my data" when it was only a placeholder.
  const [selectedSKU, setSelectedSKU] = useState(null);

  // /forecast?sku=<code> — the dashboard's Class A changes and over-forecast
  // lists open a product here. The code is read once and the parameter
  // dropped, so it selects that product when the list loads and never
  // overrides a pick made after.
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedSkuRef = useRef(searchParams.get('sku'));
  useEffect(() => {
    if (!searchParams.has('sku')) return;
    const next = new URLSearchParams(searchParams);
    next.delete('sku');
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-attach the selection to the freshly loaded list. Covers two cases
  // with one read: restoring the module-remembered pick after a route
  // remount, and refreshing the already-selected row so a late-arriving
  // brand shows up. A code that isn't in the list (a different principal's
  // scope, or no longer classified) clears the selection rather than
  // leaving the page requesting a SKU that isn't there — rememberedSKUCode
  // is deliberately left alone so switching the scope back restores it.
  useEffect(() => {
    if (sourceSKUs.length === 0) return;
    const linked = linkedSkuRef.current;
    if (linked) {
      linkedSkuRef.current = null;
      rememberedSKUCode = linked;
    }
    setSelectedSKU((prev) => {
      const code = linked ?? prev?.code ?? rememberedSKUCode;
      if (!code) return null;
      return sourceSKUs.find((s) => s.code === code) ?? null;
    });
  }, [sourceSKUs]);

  // Pinned SKUs. localStorage, NOT sessionStorage or the module-scoped
  // selection above: a pin is an explicit "keep this at the top for me"
  // that stays until the user unpins it, so it has to outlive a refresh,
  // a closed tab and a logout. auth.js's clearSession() only removes the
  // token and role keys, so signing out leaves this untouched by design.
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
    // Guarded like the read above — in private mode a throw here would
    // take the click handler down with it and the pin would not toggle.
    try {
      localStorage.setItem('san2_pinned_skus', JSON.stringify(updated));
    } catch { /* storage unavailable — the pin still holds for this view */ }
  };

  // Select SKU handler
  const handleSelectSKU = (sku) => {
    setSelectedSKU(sku);
    rememberedSKUCode = sku.code;
    setIsDropdownOpen(false);

    // Update recent SKUs history (prepend, deduplicate, keep last 5)
    const updatedRecent = [sku.code, ...recentSKUs.filter(c => c !== sku.code)].slice(0, 5);
    setRecentSKUs(updatedRecent);
    try {
      localStorage.setItem('san2_recent_forecast_skus', JSON.stringify(updatedRecent));
    } catch { /* storage unavailable — the list still holds for this view */ }
  };

  // Clear — drops the selection and the search/filter state, returning the
  // page to the prompt it opens on. Also forgets the remembered pick, so
  // navigating away and back stays on the prompt rather than restoring the
  // SKU the user just cleared.
  const handleClearSelection = () => {
    setSelectedSKU(null);
    rememberedSKUCode = null;
    setSelectedCategory('ALL');
    setSearchQuery('');
  };

  // Filtering Logic. No brand filter: which principal's SKUs appear here is
  // the Topbar's principal scope, not a per-page control, so a brand
  // dropdown would be a second, competing filter over the same axis. Brand
  // is still matched on for SEARCH, so typing a principal's name doesn't
  // come back empty.
  const filteredSKUs = useMemo(() => {
    return sourceSKUs.filter(sku => {
      const matchesSearch = searchQuery === '' ||
        sku.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.brand.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = selectedCategory === 'ALL'
        || (selectedCategory === PINNED_FILTER ? pinnedSKUs.includes(sku.code) : sku.cat === selectedCategory);
      return matchesSearch && matchesCat;
    });
  }, [sourceSKUs, searchQuery, selectedCategory, pinnedSKUs]);

  const hasActiveFilterOrSearch = selectedCategory !== 'ALL' || searchQuery.trim() !== '';

  const pinnedSKUObjects = sourceSKUs.filter(sku => pinnedSKUs.includes(sku.code));
  const recentSKUObjects = sourceSKUs.filter(sku => recentSKUs.includes(sku.code) && !pinnedSKUs.includes(sku.code));
  const catASKUObjects = sourceSKUs.filter(
    sku => sku.cat === 'A' && !pinnedSKUs.includes(sku.code) && !recentSKUs.includes(sku.code)
  );

  const isSelectedPinned = selectedSKU ? pinnedSKUs.includes(selectedSKU.code) : false;

  // Forecast data for the selected SKU — fetched from Forecast_Result via
  // GET /forecast/{sku_id}. forecast[] is legitimately empty for every SKU
  // outside Category A (forecasts are produced for Tier A only), and for a
  // Tier A SKU the runner (scripts/run_baseline_forecast.py) hasn't reached.
  const [forecastResult, setForecastResult] = useState(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  // Which request produced the forecast currently in state. forecastResult
  // is NOT cleared when the selection changes, so during a SKU switch it
  // still holds the PREVIOUS SKU's series — fine while a blanket
  // !forecastLoading guard hid everything, but not once a refetch keeps the
  // view. Without this, switching SKU would paint the old product's chart
  // under the new product's name. Kept as an object so a SKU code
  // containing the separator can't collide.
  const [forecastFor, setForecastFor] = useState(null); // { sku, principal }

  // Which of the two loading states the card is in. Same SKU, new scope
  // (principal or range) -> the series on screen is still this SKU's, so
  // keep it and mark it stale. Different SKU -> forecastResult still holds
  // the PREVIOUS product's series, so there is nothing honest to show yet
  // and the card waits.
  const showingThisSKU = Boolean(
    forecastFor && selectedSKU && forecastFor.sku === selectedSKU.code
  );
  const isForecastRefreshing = forecastLoading && showingThisSKU;
  const isForecastColdLoad = forecastLoading && !showingThisSKU;

  // Rebuild the chart card on any filter that changes what it plots: the
  // SKU, the principal scope, and this page's own date range. The SKU is in
  // here as well as on the container's `key` below — the key handles the
  // remount, this handles the other two, and a signature covering only some
  // of them would animate inconsistently depending on which control was
  // touched.
  //
  // Unlike the dashboard this is keyed on the CONTROLS, not on an arrival:
  // the range is sliced client-side from forecastResult with no request at
  // all, so there is no response landing to wait for.
  //
  // MUST stay below the state it reads. This block sat directly under
  // rangeEndPeriod, ~250 lines above selectedSKU/forecastLoading/
  // forecastFor — `const` bindings are in the temporal dead zone until
  // their declaration runs, so every render threw ReferenceError and the
  // route rendered nothing at all. It is still far above every early
  // return, so hook order is unaffected.
  const enterCycle = useEntranceReplay(
    `${selectedSKU?.code ?? ''}|${principal ?? ''}|${rangeStartPeriod ?? ''}|${rangeEndPeriod ?? ''}`
  );
  const [forecastError, setForecastError] = useState(null);

  // How far off the forecasts were for this product: its rows in GET
  // /dashboard/accuracy?level=product over this page's range (one row per
  // product x month, forecasts as made at the time). The endpoint has no
  // product filter, so the range's rows are fetched once per principal and
  // range (cached) and filtered here.
  const accuracyKey = `${principal ?? ''}|${rangeStartPeriod ?? ''}|${rangeEndPeriod ?? ''}`;
  const [accuracy, setAccuracy] = useState({ key: null, rows: [], basis: null });
  const accuracyLoadedKey = accuracy.key;
  useEffect(() => {
    if (!selectedSKU || principal === 'delmonte' || accuracyLoadedKey === accuracyKey) return undefined;
    let cancelled = false;
    getForecastAccuracy({ level: 'product', period: rangeEndPeriod, startPeriod: rangeStartPeriod, principal })
      .then((res) => {
        if (!cancelled) setAccuracy({ key: accuracyKey, rows: res.rows || [], basis: res.pesos_basis || null });
      })
      // The cards are extra to the page: on a failure they are left out.
      .catch(() => { if (!cancelled) setAccuracy({ key: accuracyKey, rows: [], basis: null }); });
    return () => { cancelled = true; };
  }, [selectedSKU, principal, accuracyKey, accuracyLoadedKey, rangeStartPeriod, rangeEndPeriod]);

  // This product's miss, summed from its rows: the average size of the miss
  // per month in pieces and (when every month has a price) pesos, and its
  // direction by the sign of the net miss — the backend's own rule
  // (backend/marts.py accuracy_summary) — with the months that ran each way.
  const productAccuracy = useMemo(() => {
    if (!selectedSKU || accuracy.key !== accuracyKey) return null;
    const rows = accuracy.rows
      .filter((r) => String(r.sku_code) === String(selectedSKU.code))
      .sort((a, b) => (a.month < b.month ? -1 : a.month > b.month ? 1 : 0));
    if (!rows.length) return { checked: false };
    const sum = (key) => rows.reduce((total, r) => total + (r[key] ?? 0), 0);
    const net = sum('miss_pieces');
    const forecastTotal = sum('forecast_pieces');
    return {
      checked: true,
      error: {
        pieces_per_month: sum('abs_miss_pieces') / rows.length,
        share_of_forecast: forecastTotal > 0 ? sum('abs_miss_pieces') / forecastTotal : null,
        pesos_per_month: rows.every((r) => r.abs_miss_pesos != null) ? sum('abs_miss_pesos') / rows.length : null,
        pesos_basis: accuracy.basis,
        direction: net > 0 ? 'surplus' : net < 0 ? 'shortage' : 'mixed',
        over_months: rows.filter((r) => r.direction === 'over').length,
        under_months: rows.filter((r) => r.direction === 'under').length,
        months_scored: rows.length,
        window_start: rows[0].month,
        window_end: rows[rows.length - 1].month,
        source: rows[0].forecast_source === 'backtest_recreated' ? 'forecasts as made at the time (backtest)' : 'stored forecast runs',
      },
      stockLimited: rows.filter((r) => r.possibly_stock_limited).map((r) => r.month),
    };
  }, [selectedSKU, accuracy, accuracyKey]);

  // The current order plan (GET /recommendations, its latest cycle): the
  // "What to order" section and, with nothing selected, the table of planned
  // products. Every status is kept, so an accepted row still counts as planned.
  const [plan, setPlan] = useState({ principal: null, items: [], cycle: null, failed: false });
  useEffect(() => {
    if (principal === 'delmonte') return undefined;
    let cancelled = false;
    getRecommendations({ principal })
      .then((res) => {
        if (cancelled) return;
        const items = res.items || [];
        const cycle = items.reduce((max, i) => (max == null || i.planning_cycle_date > max ? i.planning_cycle_date : max), null);
        setPlan({ principal, items: items.filter((i) => i.planning_cycle_date === cycle), cycle, failed: false });
      })
      .catch(() => { if (!cancelled) setPlan({ principal, items: [], cycle: null, failed: true }); });
    return () => { cancelled = true; };
  }, [principal]);
  const planLoaded = plan.principal === principal;
  const planBySku = useMemo(() => new Map(plan.items.map((i) => [String(i.sku_id), i])), [plan.items]);
  const planItem = selectedSKU && planLoaded ? planBySku.get(String(selectedSKU.code)) ?? null : null;

  // Stock on hand for a product outside the plan (GET /sku current_stock,
  // pieces at the latest count). The same request useBrandLookup makes, so
  // it is usually served from the cache.
  const [skuStock, setSkuStock] = useState({ principal: null, map: null });
  useEffect(() => {
    if (principal === 'delmonte') return undefined;
    let cancelled = false;
    getSKUs({ principal })
      .then((res) => {
        if (!cancelled) setSkuStock({ principal, map: new Map((res.items || []).map((x) => [String(x.sku_id), x.current_stock])) });
      })
      .catch(() => { if (!cancelled) setSkuStock({ principal, map: null }); });
    return () => { cancelled = true; };
  }, [principal]);

  // The latest forecast run's check against a "same as last month" guess
  // (GET /dashboard's forecast block: evaluated, unreliable and total counts),
  // for the line on why Class A products are missing from the plan.
  const [reliability, setReliability] = useState(null);
  useEffect(() => {
    if (principal === 'delmonte') return undefined;
    let cancelled = false;
    getDashboardData({ principal })
      .then((res) => { if (!cancelled) setReliability(res?.forecast || null); })
      .catch(() => { if (!cancelled) setReliability(null); });
    return () => { cancelled = true; };
  }, [principal]);

  // The planned products, most urgent first (then fewest weeks left), for the
  // table shown while nothing is selected. Weeks left is the plan's own cover.
  // Pinned products first (2026-10-22), each group most urgent first; the
  // Show filter's "Pinned" keeps only those.
  const planRows = useMemo(() => {
    const byCode = new Map(sourceSKUs.map((x) => [String(x.code), x]));
    const pinned = new Set(pinnedSKUs.map(String));
    return plan.items
      .map((item) => ({
        item,
        sku: byCode.get(String(item.sku_id)) ?? null,
        weeks: item.days_of_cover != null ? item.days_of_cover / 7 : null,
        pinned: pinned.has(String(item.sku_id)),
      }))
      .filter((r) => selectedCategory !== PINNED_FILTER || r.pinned)
      .sort((a, b) => Number(b.pinned) - Number(a.pinned)
        || (URGENCY_RANK[a.item.urgency] ?? 9) - (URGENCY_RANK[b.item.urgency] ?? 9)
        || (a.weeks ?? Infinity) - (b.weeks ?? Infinity));
  }, [plan.items, sourceSKUs, pinnedSKUs, selectedCategory]);

  // How many Class A products the plan leaves out, and why: the run's own
  // counts (failed the check; no tested forecast), the rest being products
  // the plan's input checks set aside (scripts/run_lp.py gate_out).
  const notInPlanLine = useMemo(() => {
    if (!planLoaded || plan.failed || !plan.cycle) return null;
    const classA = sourceSKUs.filter((x) => x.cat === 'A');
    const missing = classA.filter((x) => !planBySku.has(String(x.code))).length;
    if (!classA.length || missing === 0) return null;
    const head = `${missing.toLocaleString()} of ${classA.length.toLocaleString()} top sellers aren't in the plan`;
    const failed = reliability?.unreliable_count;
    const unscored = reliability?.total_count != null && reliability?.evaluated_count != null
      ? reliability.total_count - reliability.evaluated_count : null;
    const other = failed != null && unscored != null ? missing - failed - unscored : null;
    if (other == null || other < 0) {
      return `${head}: the plan takes only products whose forecast is reliable enough to use for ordering.`;
    }
    const parts = [
      `${failed.toLocaleString()} whose forecast isn't reliable enough yet`,
      unscored > 0 ? `${unscored.toLocaleString()} with no checked forecast yet (too few months of sales, or no recent sales)` : null,
      other > 0 ? `${other.toLocaleString()} set aside by the plan's own checks` : null,
    ].filter(Boolean);
    const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0];
    return `${head}: ${list}.`;
  }, [planLoaded, plan.failed, plan.cycle, sourceSKUs, planBySku, reliability]);

  useEffect(() => {
    if (!selectedSKU) {
      setForecastResult(null);
      return;
    }
    // No Del Monte SKU has a forecast. The selection and its loaded result
    // are kept, not cleared, so switching back refreshes in place.
    if (principal === 'delmonte') return;
    let cancelled = false;
    setForecastLoading(true);
    setForecastError(null);
    getForecast(selectedSKU.code, { principal })
      .then((res) => {
        if (cancelled) return;
        // Since kelvin-etl (2026-10-15) GET /forecast sends every month of a
        // common grid: months before the product's first sale or after its
        // last come as empty points (reason outside_product_lifespan). This
        // page works from the product's own months (its date span, the
        // year-earlier comparison, the last actual), so those are dropped
        // here, once. A zero-sale month (no_sale, 0) and a blank capture
        // (null) stay, with their reasons.
        setForecastResult(res
          ? { ...res, actuals: (res.actuals || []).filter((a) => a.reason !== 'outside_product_lifespan') }
          : res);
        setForecastFor({ sku: selectedSKU.code, principal });
      })
      .catch((err) => {
        if (cancelled) return;
        setForecastError(describeLoadError(err));
      })
      .finally(() => {
        if (!cancelled) setForecastLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedSKU, principal, forecastAttempt]);

  // Combine real trailing actuals + real forecast horizon into one chart
  // series. It now dynamically fills missing months between the first and last
  // actual data point with 0 to prevent straight lines skipping across void periods.
  //
  // This page's OWN local date range (2026-09, see localRange above): actuals
  // are trimmed to [rangeStartPeriod, rangeEndPeriod] before the gap-fill
  // below runs, so a narrower pick shows a narrower trailing-history window —
  // same "picker controls what's plotted" behavior Dashboard/ABC
  // have with the shared range, just scoped to this one chart. The forecast
  // point is NOT filtered by range — GET /forecast always returns the served
  // model's single latest-real-month+1 forecast regardless of what range is
  // picked (see this file's MONTH_TO_NUM comment above).
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
    const d = latestForecastRow(forecastResult)?.forecast_date;
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

  // ── The forecast the page shows ─────────────────────────────────────────
  // The pipeline writes ONE one-step-ahead value per Tier A SKU, for the
  // month after its last real sale, from the model its sales history bins it
  // into (see utils/forecastModel.js). The forecast here follows the selected
  // range where that can be done honestly: end the range at Feb 2026 and the
  // target is Mar 2026; end it at Dec 2025 and the target is Jan 2026.
  //
  // Two sources, and the difference is deliberately visible to the user:
  //
  //   'stored'      — what the pipeline actually wrote to Forecast_Result.
  //                   Carries the real confidence band and MAPE, both from
  //                   the served model's rolling one-step holdout in
  //                   scripts/run_baseline_forecast.py. `plotted` when the
  //                   range reaches the month it projects from. For an
  //                   earlier cutoff it is still the number shown, unplotted
  //                   and with a note, rather than a browser stand-in: TSB and
  //                   the XGBoost + MA3 average only run in the pipeline, and
  //                   a provisional or no-order row isn't a forecast at all.
  //
  //   'recomputed'  — an earlier cutoff for a SKU whose served model IS MA3
  //                   (not a fallback — see forecastModel.js). MA3 is just
  //                   the mean of the last 3 months, so it is honestly
  //                   derivable here, done the way the pipeline does it:
  //                   history up to the cutoff, zero-filled calendar months
  //                   (build_series), floored at 0, and only with at least 3
  //                   months of sales (MIN_MONTHS_WITH_SALES — below that the
  //                   pipeline serves a provisional average). The confidence
  //                   band is NOT derivable: it needs the holdout RMSE only
  //                   the pipeline computes. So no band and no MAPE — left
  //                   absent rather than approximated. Flagged as a preview.
  //
  // No stored row (every SKU outside Category A) means no served model, so
  // nothing is recomputed for it either.
  //
  // The cutoff is the last actual IN RANGE rather than the range's end
  // month: when a SKU's data stops early, forecasting off the range end
  // would leave a gap of empty months between the last real point and the
  // projection.
  const MA_WINDOW = 3; // mirrors baseline.py's MA_WINDOW
  const MIN_SALES_MONTHS = 3; // mirrors baseline.py's MIN_MONTHS_WITH_SALES
  const addMonth = (period) => {
    const [y, m] = period.split('-').map(Number);
    return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
  };

  const storedForecast = latestForecastRow(forecastResult);
  // The band's level, from GET /forecast's interval (backend/routers/
  // forecast.py, pinned to the runner's CONFIDENCE_Z): forecast +/- 1.645 x
  // the served model's holdout RMSE, a ~90% range. It was labelled a bare
  // "confidence interval".
  const bandLevel = forecastResult?.interval?.level_pct ?? null;
  const bandLabel = 'Most likely range';
  // Preview: the payload's own placeholder window, marked on the chart and
  // table the way the Dashboard and Category Trends mark it, so a 2021–22
  // placeholder month is never read as SSM's actual sales.
  const placeholder = forecastResult?.data_mode?.placeholder ?? null;
  const servedModel = useMemo(
    () => (storedForecast ? describeServedModel(storedForecast.model_params, storedForecast.status) : null),
    [storedForecast]
  );
  // The stored row's provenance, read by the stat row's holdout error and
  // the "How this forecast was made" block. holdout_metrics_served.months
  // is the served model's own scoring window; holdout_months is the same
  // count on rows written before it existed.
  const storedParams = storedForecast?.model_params || {};
  // The calendar adjustment (model_params.calendar_factor, Kelvin 2026-10-19)
  // is a method change still awaiting the adviser's sign-off (GET /forecast's
  // calendar_signed_off, analytics.params.CALENDAR_FACTOR_SIGNED_OFF). Until
  // he signs it off the page leads with the model's own number
  // (value_before_calendar) and names the adjusted one in "Show details"
  // (2026-10-20). Both figures are the API's; nothing is recomputed here.
  const calendarPending = servedModel?.calendar?.before != null && forecastResult?.calendar_signed_off !== true;
  const adjustedValue = storedForecast?.forecast_value ?? null;
  const headlineStoredValue = calendarPending ? servedModel.calendar.before : adjustedValue;
  // The model as it reads without the adjustment, for the details' "Time of
  // year" line while the headline is the unadjusted number.
  const unadjustedModel = useMemo(
    () => (storedForecast
      ? describeServedModel({ ...storedForecast.model_params, calendar_factor: null }, storedForecast.status)
      : null),
    [storedForecast]
  );
  // "March", the month the adjustment is for.
  const adjustmentMonth = storedForecastPeriod
    ? new Date(`${storedForecastPeriod}-01T00:00:00`).toLocaleString('en-US', { month: 'long' })
    : null;
  // The months where stock may have run out, from this product's accuracy
  // rows (productAccuracy below; GET /dashboard/accuracy, migration 0043's
  // stock-limited rule).
  const stockLimitedPeriods = productAccuracy?.stockLimited || [];
  const holdoutMonths = storedParams.holdout_metrics_served?.months ?? storedParams.holdout_months ?? null;

  // The months behind the accuracy figures and the MA3 benchmark, so each
  // states its period (Sir Catubag, 2 Oct 2026). The runner builds every
  // SKU's series from its own first to its own last month on record
  // (scripts/run_baseline_forecast.py build_series), so both windows end at
  // this SKU's last actual month (skuCoverage.end, from the same table):
  //   test window — the last model_params.holdout_months of that series (the
  //                 20% holdout train_holdout_split takes), each forecast one
  //                 month ahead from the months before it
  //   MA3 months  — the series' last 3 months (router.ma3_value)
  const holdoutSplitMonths = storedParams.holdout_months ?? holdoutMonths;
  const holdoutWindow = skuCoverage && holdoutSplitMonths
    ? `${formatPeriod(periodMinusMonths(skuCoverage.end, holdoutSplitMonths))} – ${formatPeriod(skuCoverage.end)}`
    : null;
  const ma3Window = skuCoverage
    ? `${formatPeriod(periodMinusMonths(skuCoverage.end, MA_WINDOW))} – ${formatPeriod(skuCoverage.end)}`
    : null;

  const derivedForecast = useMemo(() => {
    if (!forecastResult || !storedForecast || !servedModel) return null;
    const actuals = [...(forecastResult.actuals || [])].sort((a, b) => a.period.localeCompare(b.period));
    const inRange = actuals
      .filter((a) => (!rangeStartPeriod || a.period >= rangeStartPeriod) && (!rangeEndPeriod || a.period <= rangeEndPeriod));
    if (inRange.length === 0) return null;

    const cutoff = inRange[inRange.length - 1].period;
    const target = addMonth(cutoff);

    const stored = {
      period: storedForecastPeriod,
      value: headlineStoredValue,
      confidenceLower: storedForecast.confidence_lower,
      confidenceUpper: storedForecast.confidence_upper,
      mape: storedForecast.mape,
      source: 'stored',
      // The month the stored value projects from (the one before its target).
      basisPeriod: periodMinusMonths(storedForecastPeriod, 2),
    };
    if (storedForecastPeriod === target) {
      return { ...stored, plotted: servedModel.kind === 'forecast' };
    }

    if (servedModel.recomputable) {
      const history = actuals.filter((a) => a.period <= cutoff);
      if (history.filter((a) => a.quantity > 0).length >= MIN_SALES_MONTHS) {
        const qtyByPeriod = new Map(history.map((a) => [a.period, a.quantity]));
        const windowStart = periodMinusMonths(cutoff, MA_WINDOW);
        let sum = 0;
        for (let p = windowStart; p <= cutoff; p = addMonth(p)) sum += qtyByPeriod.get(p) ?? 0;
        return {
          period: target,
          value: Math.max(0, sum / MA_WINDOW),
          confidenceLower: null,
          confidenceUpper: null,
          mape: null,
          source: 'recomputed',
          plotted: true,
          basisPeriod: cutoff,
          windowStart,
        };
      }
    }

    return { ...stored, plotted: false, earlierCutoff: cutoff };
  }, [forecastResult, storedForecast, servedModel, storedForecastPeriod, rangeStartPeriod, rangeEndPeriod]);

  const chartData = useMemo(() => {
    if (!forecastResult) return [];
    const stockLimitedSet = new Set(stockLimitedPeriods);

    // Sort actuals to ensure they are chronologically ordered, trimmed to
    // this page's own local range (never selected yet -> full history).
    const sortedActuals = [...(forecastResult.actuals || [])]
      .filter((a) => (!rangeStartPeriod || a.period >= rangeStartPeriod) && (!rangeEndPeriod || a.period <= rangeEndPeriod))
      .sort((a, b) => a.period.localeCompare(b.period));

    // Same month last year (Technical Adviser, 2 Oct 2026: "2025 vs 2024,
    // per product?"), read from the product's whole history, not just the
    // range. A month before the product's first record has no comparison
    // and stays empty; a month inside its history with no row counts as 0,
    // the same rule this chart uses for its own gaps.
    const allActuals = forecastResult.actuals || [];
    const qtyAll = new Map(allActuals.map((a) => [a.period, a.quantity]));
    const firstRecord = allActuals.reduce((min, a) => (min == null || a.period < min ? a.period : min), null);
    const lastYearOf = (period) => {
      const prior = yearEarlier(period);
      if (firstRecord == null || prior < firstRecord) return null;
      // A month with no row inside the history is 0; a blank capture (a row
      // whose quantity was never recorded) stays empty, never 0.
      return qtyAll.has(prior) ? qtyAll.get(prior) : 0;
    };

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
            lastYear: lastYearOf(currentPeriod),
            // Why this month is 0 or empty (backend/series_gaps.py), for the tooltip.
            reason: sortedActuals[actualIndex].reason ?? null,
            stockLimited: stockLimitedSet.has(currentPeriod),
          });
          actualIndex++;
        } else {
          actualPoints.push({
            label: currentPeriod,
            actual: 0,
            lastYear: lastYearOf(currentPeriod),
            stockLimited: stockLimitedSet.has(currentPeriod),
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
      if (derivedForecast?.plotted) {
        lastActualPoint.forecast = lastActualPoint.actual;

        // ...and anchor the confidence band to that same point, collapsed to
        // zero width there. The pipeline emits exactly ONE forecast point, and an
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

    // Only a forecast for the month right after the last plotted actual goes
    // on the chart: a stored value for a later month (earlier cutoff) or a
    // provisional / no-order row is shown in the stat row instead.
    const forecastPoints = derivedForecast?.plotted
      ? [{
        label: derivedForecast.period,
        forecast: derivedForecast.value,
        lastYear: lastYearOf(derivedForecast.period),
        ci: derivedForecast.confidenceLower != null && derivedForecast.confidenceUpper != null
          ? [derivedForecast.confidenceLower, derivedForecast.confidenceUpper]
          : undefined,
      }]
      : [];
    return [...actualPoints, ...forecastPoints];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forecastResult, rangeStartPeriod, rangeEndPeriod, derivedForecast, stockLimitedPeriods.join(',')]);

  // Windowing for the chart below — see ./ChartZoom. This page's range can
  // run well past what the X axis can label without skipping months.
  const zoom = useChartZoom(chartData);

  // The shaded spans: months where stock may have run out (from this
  // product's accuracy rows) and months that were generated, not recorded.
  const stockLimitedRuns = useMemo(() => pointRuns(zoom.view, (pt) => pt.stockLimited), [zoom.view]);
  const generatedRuns = useMemo(() => pointRuns(zoom.view, (pt) => GENERATED_REASONS.has(pt.reason)), [zoom.view]);
  // The reasons on the months the chart draws: the note under it explains
  // only those (a generated month's note never shows for a chart without one).
  const drawnReasons = useMemo(() => new Set(chartData.map((pt) => pt.reason).filter(Boolean)), [chartData]);

  // Chart or its table twin ("view as table", design pass 2026-09-26).
  const [chartView, setChartView] = useState('chart');

  // Direct label at the projection's end — the number the page is FOR,
  // repeated where the dashed line stops. Skipped when the point leaves
  // the zoom window.
  const forecastEndLabels = useMemo(() => {
    const end = [...zoom.view].reverse().find((pt) => pt.forecast != null && pt.actual == null);
    return pointLabels(zoom.view, end
      ? [{ period: end.label, text: `Forecast ${formatAxisQty(end.forecast)}` }]
      : [], { key: 'label' });
  }, [zoom.view]);

  // The last month the chart plots an actual for — the end of what the
  // partial-range banner reports as "Showing …". Not skuCoverage.end: when
  // the range ends before the SKU's last sale, the chart stops at the range.
  // The forecast point never carries `actual`, so it is skipped.
  const lastPlottedActualPeriod = useMemo(
    () => [...chartData].reverse().find((pt) => pt.actual != null)?.label ?? null,
    [chartData]
  );

  // The month the forecast is projected from, so the "vs. last actual"
  // comparison always pairs the forecast with the observation it was
  // actually derived from. That is the last real month INSIDE the selected
  // range, except when an earlier cutoff shows the stored forecast unplotted
  // (see derivedForecast): its basis is the month before its own target,
  // outside the window. A basis month with no row is a real zero, the same
  // zero-fill the pipeline uses. With no forecast, the last month in range.
  const latestActualPoint = useMemo(() => {
    const actuals = forecastResult?.actuals || [];
    if (derivedForecast?.basisPeriod) {
      return actuals.find((a) => a.period === derivedForecast.basisPeriod)
        ?? { period: derivedForecast.basisPeriod, quantity: 0 };
    }
    const inRange = actuals
      .filter((a) => (!rangeStartPeriod || a.period >= rangeStartPeriod) && (!rangeEndPeriod || a.period <= rangeEndPeriod));
    if (inRange.length === 0) return null;
    return inRange.reduce((latest, a) => (a.period > latest.period ? a : latest), inRange[0]);
  }, [forecastResult, derivedForecast, rangeStartPeriod, rangeEndPeriod]);

  // Forecast vs. that last real month — turns the raw forecast number into
  // an actionable "demand is rising/falling" read. null when either side
  // is missing (no forecast yet, no sales history), the last actual was 0
  // or below (returns can make a month negative: against -1 unit a rise
  // read "↓ 78,800%"), or the stored row isn't a forecast at all
  // (provisional / no-order — no trend to read).
  const forecastTrendPct = useMemo(() => {
    if (!derivedForecast || servedModel?.kind !== 'forecast') return null;
    if (!latestActualPoint || !(latestActualPoint.quantity > 0)) return null;
    return ((derivedForecast.value - latestActualPoint.quantity) / latestActualPoint.quantity) * 100;
  }, [derivedForecast, servedModel, latestActualPoint]);

  // Why this product got its model (item 1, 2026-10-19): the sales months
  // that picked it, the guard that set it aside, or the demonstration.
  const whyModel = (() => {
    if (storedParams.demonstration) {
      return 'Sample data: a 3-month average for every product. Turn sample data off to see this product\u2019s real forecast.';
    }
    const months = storedParams.sales_months;
    if (servedModel?.fallback) {
      return `${months != null ? `Its ${months} months of sales call for ${modelRule(months).split('→ ')[1]}, but` : 'Its usual model was set aside because'} `
        + `${describeFallbackReason(storedParams.backup_reason)}, so the 3-month average was used.`;
    }
    return months != null ? `Chosen because it has ${months} months of sales (${modelRule(months)}).` : null;
  })();

  // MASE to two decimals, three near 1 (where two would round 0.996 to 1.00).
  const maseText = storedForecast?.mase != null
    ? storedForecast.mase.toFixed(Math.abs(storedForecast.mase - 1) < 0.01 ? 3 : 2) : null;

  // The headline's reliability sentence (src/labels.js): MASE below 1 is
  // reliable; sample data, a browser preview or no score is "not checked".
  const reliabilityState = !storedForecast || storedParams.demonstration || derivedForecast?.source !== 'stored'
    || storedForecast.mase == null ? 'unchecked' : storedForecast.mase < 1 ? 'reliable' : 'unreliable';
  // The usual miss is the real forecasts' record: not said beside the sample
  // forecast, which is never checked (rule 2).
  const missShare = productAccuracy?.checked && !storedParams.demonstration
    ? productAccuracy.error?.share_of_forecast ?? null : null;
  // The verdict sentence beside the number (2026-10-20): the MASE rule's
  // result in words, with the typical error when it is known.
  const typicalError = missShare != null ? `; typical error is about ${Math.round(missShare * 100)}%` : '';
  const verdictText = reliabilityState === 'reliable'
    ? `Suitable for ordering. Outperforms a simple last-month estimate${typicalError}.`
    : reliabilityState === 'unreliable'
      ? `Not yet suitable for ordering. Does not outperform a simple last-month estimate${typicalError}.`
      : RELIABILITY_SHORT[reliabilityState];

  // A product outside the plan: its stock and weeks left at this forecast
  // (stock ÷ (forecast ÷ weeks per month)), and why the plan leaves it out,
  // checked in order.
  const outsideStock = selectedSKU && skuStock.principal === principal
    ? skuStock.map?.get(String(selectedSKU.code)) ?? null : null;
  const outsideForecast = servedModel?.kind === 'forecast' ? headlineStoredValue ?? null : null;
  const outsideWeeks = outsideStock != null && outsideForecast > 0
    ? outsideStock / (outsideForecast / WEEKS_PER_MONTH) : null;
  const notPlannedReason = (() => {
    if (!selectedSKU) return null;
    if (selectedSKU.cat !== 'A') return `The plan covers top sellers only; this one is a ${tierSingular(selectedSKU.cat)}.`;
    if (storedParams.demonstration) {
      return 'The plan is built from real forecasts only. Turn sample data off to see why this product isn\u2019t in it.';
    }
    if (!storedForecast || servedModel?.kind === 'provisional') return 'It has no forecast yet (too few months of sales), and the plan needs one.';
    if (servedModel?.kind === 'no_order') return 'No sales in the last 6 months, so no order is planned.';
    if (storedForecast.mase != null && storedForecast.mase >= 1) {
      return 'Its forecast isn\u2019t reliable enough to use for ordering yet, so the plan leaves it out; nothing forecasts it '
        + 'another way.';
    }
    return 'Its forecast is reliable, but one of the plan\u2019s own checks set it aside.';
  })();

  // Small print under the provisional / no-order notice in the stat row:
  // what the pipeline stored and why it isn't a forecast. The counts come
  // from the run's own model_params, not recounted here.
  const describePlaceholder = () => {
    if (servedModel?.kind === 'no_order') {
      return 'Stored as 0 pcs: the order plan orders nothing for this product.';
    }
    const params = storedForecast?.model_params || {};
    const months = params.observed_months_used ?? params.months_with_sales;
    const needed = params.min_months_threshold ?? MIN_SALES_MONTHS;
    const basis = months != null ? `${months} month${months === 1 ? '' : 's'} of sales` : 'its sales so far';
    const value = Math.round(storedForecast?.forecast_value ?? 0).toLocaleString();
    return `Average of ${basis}: ${value} pcs a month. A forecast needs at least ${needed} months of sales.`;
  };

  return (
    <div className="forecast-page">
      <div className="forecast-content" data-enter-cycle={enterCycle}>
        <PageHeader
          title="Sales"
          accent="forecast"
          subtitle="How much each top seller will likely sell next month, and how much to order."
          actions={(
            <>
              {/* The range only trims the chart, and Del Monte has none. */}
              {!isDelMonte && (
                <DateFilter
                  localValue={localRange}
                  onLocalChange={setLocalRange}
                  onReset={isCustomRange ? resetToDashboardRange : undefined}
                  minMonths={effectiveMinMonths}
                  realOnly={realFloor}
                />
              )}
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => navigate('/sku-management')}
                title="Go to the {PAGE_NAMES.products} page"
              >
                Browse all products <ArrowRight size={14} aria-hidden="true" />
              </button>
            </>
          )}
        >
            {whatIf && (
              <p className="chart-placeholder-note">
                Sample data: this forecast is a what-if run of the same models on the five-year history, 2021–22
                sample months included (built {String(dashboardRange.previewInfo.outputs.built_at).slice(0, 10)}).
                It is never saved and is not the live forecast.
              </p>
            )}
            {realFloor && (
              <p className="chart-placeholder-note">
                Sample data is on, but forecasts are made from real data only, so this chart starts no earlier than
                Jan {FIRST_DATA_YEAR}. The &ldquo;Sales pattern&rdquo; panel below does include the
                2021–22 sample months.
              </p>
            )}
        </PageHeader>

        {/* Del Monte: the message REPLACES the picker and everything under
            it. Its ABC rows are product categories, and listing them here
            as if they were SKUs led to a request that could only 404. */}
        {isDelMonte && syntheticOn && <DemoCategoryForecast />}
        {isDelMonte && !syntheticOn && (
          <div className="forecast-empty-state">
            <div className="forecast-empty-icon">
              <Search size={28} strokeWidth={1.6} />
            </div>
            <h3 className="forecast-empty-title">{DEL_MONTE_NO_FORECAST}</h3>
            <p className="forecast-empty-body">
              Del Monte is ranked by product category on the ABC Classification page. Switch the scope to
              Unilever to forecast a product.
            </p>
            <button className="forecast-range-fix-btn" onClick={() => navigate('/abc')}>
              Open ABC Classification
            </button>
          </div>
        )}

        {/* Selection Area with Filter Controls */}
        {!isDelMonte && (
        <div className="forecast-selection">
          <div className="selection-top-bar">
            <label className="selection-label">CHOOSE A PRODUCT</label>
            {/* The "Unilever only" scope badge that used to sit here was
                removed 2026-09-17: the app is no longer Unilever-only, and
                scope is now the Topbar's principal filter, which this page
                already follows. A fixed badge would have contradicted the
                control the user just set. */}
          </div>

          {/* Controls Bar: Filters & Search Combobox */}
          <div className="combobox-controls-bar">
            {/* Filter Chips / Dropdowns */}
            <div className="forecast-filter-group">
              <div className="filter-dropdown-wrapper">
                <span className="filter-icon-label"><Filter size={12} /> Show:</span>
                <select
                  className="filter-select"
                  value={selectedCategory}
                  onChange={(e) => {
                    setSelectedCategory(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                >
                  <option value="ALL">All products</option>
                  <option value={PINNED_FILTER}>Pinned</option>
                  <option value="A">{TIER_LABEL.A}</option>
                  <option value="B">{TIER_LABEL.B}</option>
                  <option value="C">{TIER_LABEL.C}</option>
                </select>
              </div>

              {(selectedCategory !== 'ALL' || searchQuery !== '' || selectedSKU) && (
                <button
                  className="clear-filters-btn"
                  onClick={handleClearSelection}
                  title="Clear the selected product and all filters"
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
                  placeholder="Search by product name, code or brand…"
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
                              title={pinnedSKUs.includes(sku.code) ? "Unpin product" : "Pin product"}
                              aria-label={`${pinnedSKUs.includes(sku.code) ? 'Unpin' : 'Pin'} ${sku.name} (${sku.code})`}
                              aria-pressed={pinnedSKUs.includes(sku.code)}
                            >
                              <Pin size={15} fill={pinnedSKUs.includes(sku.code) ? PIN_COLOR : 'none'} />
                            </button>
                            <ProductName name={sku.name} code={sku.code} className="result-product" />
                            {sku.brand && <span className="result-brand">{sku.brand}</span>}
                            <span className={`forecast-cat-badge cat-${sku.cat}`} title={tierTechnical(sku.cat)}>{tierBadge(sku.cat)}</span>
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
                            <Pin size={12} fill={PIN_COLOR} color={PIN_COLOR} />
                            <span>PINNED PRODUCTS</span>
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
                                title="Unpin product"
                                aria-label={`Unpin ${sku.name} (${sku.code})`}
                                aria-pressed={true}
                              >
                                <Pin size={15} fill={PIN_COLOR} />
                              </button>
                              <ProductName name={sku.name} code={sku.code} className="result-product" />
                              {sku.brand && <span className="result-brand">{sku.brand}</span>}
                              <span className={`forecast-cat-badge cat-${sku.cat}`} title={tierTechnical(sku.cat)}>{tierBadge(sku.cat)}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Section 2: Recently Forecasted SKUs */}
                      {recentSKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <Clock size={12} />
                            <span>RECENTLY VIEWED</span>
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
                                title="Pin product"
                                aria-label={`Pin ${sku.name} (${sku.code})`}
                                aria-pressed={pinnedSKUs.includes(sku.code)}
                              >
                                <Pin size={15} fill={pinnedSKUs.includes(sku.code) ? PIN_COLOR : 'none'} />
                              </button>
                              <ProductName name={sku.name} code={sku.code} className="result-product" />
                              {sku.brand && <span className="result-brand">{sku.brand}</span>}
                              <span className={`forecast-cat-badge cat-${sku.cat}`} title={tierTechnical(sku.cat)}>{tierBadge(sku.cat)}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Section 3: Category A SKUs */}
                      {catASKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <span>TOP SELLERS</span>
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
                                title="Pin product"
                                aria-label={`Pin ${sku.name} (${sku.code})`}
                                aria-pressed={pinnedSKUs.includes(sku.code)}
                              >
                                <Pin size={15} fill={pinnedSKUs.includes(sku.code) ? PIN_COLOR : 'none'} />
                              </button>
                              <ProductName name={sku.name} code={sku.code} className="result-product" />
                              {sku.brand && <span className="result-brand">{sku.brand}</span>}
                              <span className={`forecast-cat-badge cat-${sku.cat}`} title={tierTechnical(sku.cat)}>{tierBadge(sku.cat)}</span>
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
        )}

        {/* In the shape of the "pick a SKU" panel the page rests on once
            the list lands, so that panel replaces this one in place. */}
        {!isDelMonte && listLoading && (
          <>
            <LoadingStatus>Loading products…</LoadingStatus>
            <SlowLoadNotice />
            <div className="forecast-empty-state" aria-hidden="true">
              <SkeletonLine className="skeleton-circle" width="56px" height="56px" />
              <SkeletonLine width="18rem" height="1rem" />
              <SkeletonLine width="26rem" height="0.75rem" />
            </div>
          </>
        )}
        {!isDelMonte && listError && !listLoading && (
          <LoadError what="the SKU list" message={listError} onRetry={() => setListAttempt((n) => n + 1)} />
        )}

        {/* The page's resting state until the user picks a SKU — nothing is
            auto-selected, so this is what a fresh visit (or a refresh)
            shows. Also covers the genuinely empty list. */}
        {/* With nothing selected: the products in the current order plan,
            most urgent first, each opening its forecast (2026-10-19); the
            old prompt only when there is no plan to list. */}
        {!isDelMonte && !selectedSKU && !listLoading && !listError && sourceSKUs.length > 0 && planLoaded && plan.items.length > 0 && (
          <div className="forecast-plan-card">
            <h3 className="forecast-card-title">Products in the current order plan</h3>
            <SectionLede>
              {selectedCategory === PINNED_FILTER
                ? `${planRows.length.toLocaleString()} pinned of ${plan.items.length.toLocaleString()} products`
                : `${plan.items.length.toLocaleString()} products`}
              {plan.cycle ? ` for ${formatPeriod(plan.cycle)}` : ''}, pinned first, then most urgent. Pick one to see its
              forecast, or search above.
            </SectionLede>
            {notInPlanLine && <p className="forecast-plan-missing">{notInPlanLine}</p>}
            <TierBasisLabel periods={tierAPeriods} />
            <div className="forecast-plan-scroll">
              <table className="forecast-plan-table">
                <thead>
                  <tr>
                    <th scope="col" className="forecast-plan-pin-col"><span className="visually-hidden">Pin</span></th>
                    <th scope="col">Product</th>
                    <th scope="col" className="num">Next month (pcs)</th>
                    <th scope="col" className="num">In stock (pcs)</th>
                    <th scope="col" className="num">
                      Lasts about
                      <InfoTip label="About how long stock lasts" size={12}>
                        How long the stock on hand lasts at the forecast, in weeks: the plan&apos;s own cover (days of
                        cover ÷ 7).
                      </InfoTip>
                    </th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {planRows.map(({ item, sku, weeks, pinned }) => {
                    const target = sku ?? {
                      code: String(item.sku_id), name: item.product_name || 'Unknown Product', brand: '', cat: item.tier, principal: item.principal,
                    };
                    return (
                      <tr
                        key={item.sku_id}
                        tabIndex={0}
                        onClick={() => handleSelectSKU(target)}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleSelectSKU(target); } }}
                      >
                        <td className="forecast-plan-pin-col">
                          {/* Pins or unpins without opening the product. */}
                          <button
                            type="button"
                            className={`star-pin-btn ${pinned ? 'pinned' : ''}`}
                            onClick={(e) => togglePinSKU(target.code, e)}
                            onKeyDown={(e) => e.stopPropagation()}
                            title={pinned ? 'Unpin product' : 'Pin product'}
                            aria-label={`${pinned ? 'Unpin' : 'Pin'} ${target.name} (${target.code})`}
                            aria-pressed={pinned}
                          >
                            <Pin size={15} fill={pinned ? PIN_COLOR : 'none'} />
                          </button>
                        </td>
                        <td><ProductName name={target.name} code={target.code} /></td>
                        <td className="num" title={item.forecast_units != null ? `${fmtPcs(item.forecast_units)} pcs (exact)` : undefined}>{formatApprox(item.forecast_units)}</td>
                        <td className="num" title={item.stock_not_in_count ? 'Missing from the stock count: the plan reads it as 0 on hand' : item.current_stock != null ? `${fmtPcs(item.current_stock)} pcs (exact)` : undefined}>
                          {item.stock_not_in_count ? 'Not in count' : formatApprox(item.current_stock)}
                        </td>
                        <td className="num">{item.stock_not_in_count ? '—' : coverText(item, weeks)}</td>
                        <td><span className={getUrgencyBadge(item.urgency)} title={URGENCY_HOVER[item.urgency]}>{item.urgency}</span></td>
                      </tr>
                    );
                  })}
                  {planRows.length === 0 && (
                    <tr className="table-empty-row">
                      <td colSpan={6}>No pinned products in this plan yet. Use the pin at the start of a row to pin one.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {!isDelMonte && !selectedSKU && !listLoading && !listError && sourceSKUs.length > 0 && !planLoaded && (
          <LoadingStatus>Loading the order plan…</LoadingStatus>
        )}
        {!isDelMonte && !selectedSKU && !listLoading && !listError && (sourceSKUs.length === 0 || (planLoaded && plan.items.length === 0)) && (
          <div className="forecast-empty-state">
            <div className="forecast-empty-icon">
              <Search size={28} strokeWidth={1.6} />
            </div>
            <h3 className="forecast-empty-title">
              {sourceSKUs.length === 0
                ? 'No ranked products for this principal'
                : 'Choose a product to see its forecast'}
            </h3>
            <p className="forecast-empty-body">
              {sourceSKUs.length === 0
                ? 'There are no ranked products for this principal yet, so there is nothing to forecast.'
                : 'Search by product name, code or brand above, or pick one from your pinned and recently viewed products.'}
            </p>
          </div>
        )}

        {!isDelMonte && selectedSKU && (
          <>
            {/* Selected SKU Card */}
            <div className="selected-sku-card">
              <div className="sku-info-left">
                <div className="sku-code-header-row">
                  <span className="sku-code-label">SELECTED PRODUCT</span>
                  <button
                    className={`card-star-btn ${isSelectedPinned ? 'pinned' : ''}`}
                    onClick={(e) => togglePinSKU(selectedSKU.code, e)}
                    title={isSelectedPinned ? "Unpin product" : "Pin product"}
                    aria-label={`${isSelectedPinned ? 'Unpin' : 'Pin'} ${selectedSKU.name} (${selectedSKU.code})`}
                    aria-pressed={isSelectedPinned}
                  >
                    <Pin size={15} fill={isSelectedPinned ? PIN_COLOR : 'none'} color={isSelectedPinned ? PIN_COLOR : PIN_IDLE_COLOR} />
                    <span className="pin-text">{isSelectedPinned ? 'Unpin product' : 'Pin product'}</span>
                  </button>
                </div>
                {/* Name first, SKU code under it (Sir Catubag, 2 Oct 2026). */}
                <div className="sku-meta-row">
                  <ProductName name={selectedSKU.name} code={selectedSKU.code} className="sku-selected-name" />
                  {selectedSKU.brand && <span className="sku-brand-name">{selectedSKU.brand}</span>}
                </div>
              </div>
              <div className="sku-info-right">
                <span className={`forecast-cat-badge cat-${selectedSKU.cat}`} title={tierTechnical(selectedSKU.cat)}>{tierBadge(selectedSKU.cat)}</span>
                {/* From the forecast to what was ordered on it. The plan
                    covers Class A products whose forecast passed the
                    last-month-guess check (the same test Reliability
                    states below), so the link shows for those; the Reorder
                    page says so if the plan has no row for it after all. */}
                {canOpenReorder && planItem && (
                  <button
                    type="button"
                    className="forecast-plan-link"
                    onClick={() => navigate(`/reorder?sku=${encodeURIComponent(selectedSKU.code)}`)}
                  >
                    See its order recommendation
                    <ArrowRight size={13} aria-hidden="true" />
                  </button>
                )}
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
            {/* No .is-refreshing here, unlike the dashboard and ABC. This
                element carries the entrance animation itself, and an
                animation with fill-mode `both` holds its own `to { opacity:
                1 }` over any value the cascade supplies — the dim would
                silently never render. It is also not needed: what the dim
                buys elsewhere is pointer-events off over stale reorder and
                SKU links, and this card holds a chart, not navigation. The
                note above states the staleness on its own. */}
            <div
              className="forecast-chart-container"
              key={`chart-${selectedSKU?.code || 'none'}`}
              aria-busy={isForecastRefreshing}
            >
              <h3 className="forecast-card-title">Next month</h3>
              {/* First load for this SKU: the headline stat row, the "how
                  this forecast was made" box and the 420px chart, in the
                  loaded card's own classes. */}
              {isForecastColdLoad && (
                <>
                  <LoadingStatus>Loading forecast…</LoadingStatus>
                  <SlowLoadNotice />
                  <div className="forecast-accuracy-row" aria-hidden="true">
                    {[0, 1, 2, 3].map((k) => (
                      <div className="forecast-stat-block" key={k}>
                        <SkeletonLine width="7rem" height="0.65rem" />
                        <SkeletonLine width="5.5rem" height="1.6rem" />
                        <SkeletonLine width="8rem" height="0.65rem" />
                      </div>
                    ))}
                  </div>
                  <div className="forecast-howmade" aria-hidden="true">
                    <SkeletonLine width="10rem" height="0.65rem" />
                    <SkeletonLine width="80%" height="0.75rem" />
                  </div>
                  <SkeletonChart variant="line" height={420} />
                </>
              )}
              {isForecastRefreshing && <RefreshingNote>Updating {selectedSKU.name}…</RefreshingNote>}
              {forecastError && !forecastLoading && (
                <LoadError
                  what={`the forecast for ${selectedSKU.name}`}
                  message={forecastError}
                  onRetry={() => setForecastAttempt((n) => n + 1)}
                />
              )}

              {/* A null result (GET /forecast 404 -> getForecast null) gets a
                  message, never a blank card: every block below needs a
                  forecastResult. With the Topbar on Del Monte the picker is
                  replaced before this card exists; the Del Monte wording here
                  covers one of its category rows turning up in another
                  scope's list, since those rows can only ever 404. */}
              {!forecastLoading && !forecastError && showingThisSKU && !forecastResult && (
                <p className="forecast-subtitle">
                  {selectedSKU.principal === 'delmonte'
                    ? `${DEL_MONTE_NO_FORECAST} ${selectedSKU.name} is a product category, not a product.`
                    : `No product record was found for ${selectedSKU.code}, so there is no forecast to show.`}
                </p>
              )}

              {/* Forecasts are produced for Category A only, so for B and C
                  an empty forecast[] is the design, not a gap — no "yet". */}
              {!isForecastColdLoad && !forecastError && forecastResult && forecastResult.forecast.length === 0 && (
                <p className="forecast-subtitle">
                  {forecastResult.blocked_reason
                    ? forecastResult.blocked_reason
                    : selectedSKU.cat === 'A'
                    ? `No forecast has been generated for ${selectedSKU.name} (${selectedSKU.code}) yet.`
                    : `Forecasts are made for top sellers only.${selectedSKU.cat ? ` ${selectedSKU.name} (${selectedSKU.code}) is a ${tierSingular(selectedSKU.cat)}.` : ''}`}
                </p>
              )}

              {/* Start after end (e.g. Dec 2024 - Jan 2024) — DateFilter
                  already shows an inline warning the instant this happens,
                  but this page still has to refuse to render a chart for a
                  backwards range rather than silently treating it as empty.
                  Offers a one-click fix (swap the two dates) since, unlike
                  the 'none' case below, there's no ambiguity about what the
                  user actually meant. */}
              {!isForecastColdLoad && !forecastError && forecastResult && rangeStatus === 'invalid' && (
                <div className="forecast-range-error">
                  <span className="forecast-range-error-title">Invalid date range</span>
                  <p className="forecast-range-error-body">
                    Your start date (<strong>{formatPeriod(rangeStartPeriod)}</strong>) is after your end date
                    (<strong>{formatPeriod(rangeEndPeriod)}</strong>). Pick a start date on or before the end date
                    to see this product&apos;s sales history and forecast.
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
              {!isForecastColdLoad && !forecastError && forecastResult && rangeStatus === 'too-short' && (
                <div className="forecast-range-error">
                  <span className="forecast-range-error-title">
                    Range too short — {monthsBetween(rangeStartPeriod, rangeEndPeriod)} month
                    {monthsBetween(rangeStartPeriod, rangeEndPeriod) === 1 ? '' : 's'} selected
                  </span>
                  <p className="forecast-range-error-body">
                    <strong>{formatPeriod(rangeStartPeriod)} – {formatPeriod(rangeEndPeriod)}</strong> isn&apos;t
                    enough points for a readable trend. Select at least <strong>{effectiveMinMonths} month{effectiveMinMonths === 1 ? '' : 's'}</strong>
                    {effectiveMinMonths < MIN_RANGE_MONTHS
                      ? `: this product only has ${effectiveMinMonths} month${effectiveMinMonths === 1 ? '' : 's'} of sales, so that's all it has.`
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
              {!isForecastColdLoad && !forecastError && forecastResult && rangeStatus === 'none' && (
                <div className="forecast-range-error">
                  <span className="forecast-range-error-title">
                    No data for {selectedSKU.name} in the selected range
                  </span>
                  <p className="forecast-range-error-body">
                    You selected <strong>{formatPeriod(rangeStartPeriod)} – {formatPeriod(rangeEndPeriod)}</strong>,
                    but this product only has recorded sales from{' '}
                    <strong>{formatPeriod(skuCoverage?.start)}</strong> to{' '}
                    <strong>{formatPeriod(skuCoverage?.end)}</strong>. Pick a range inside that window to see its
                    sales history and forecast.
                  </p>
                  <button className="forecast-range-fix-btn" onClick={applySkuCoverageRange}>
                    Use this product&apos;s range ({formatPeriod(skuCoverage?.start)} – {formatPeriod(skuCoverage?.end)})
                  </button>
                </div>
              )}

              {!isForecastColdLoad && !forecastError && forecastResult && (rangeStatus === 'ok' || rangeStatus === 'partial') && (
                <>
                  {/* The headline (2026-10-20): next month's forecast rounded (the
                      exact figure in the hover), its most likely range, whether
                      it is reliable enough to order on, how far off past
                      forecasts were, and the change from last month. Every
                      technical figure is in "Show details" at the bottom. */}
                  {servedModel && servedModel.kind !== 'forecast' ? (
                    <div className="forecast-headline">
                      <p className="forecast-headline-main">
                        {servedModel.kind === 'provisional'
                          ? 'Not enough sales yet for a forecast.'
                          : 'No sales in the last 6 months, so no order is planned.'}
                      </p>
                      <p className="forecast-headline-sub">{describePlaceholder()}</p>
                    </div>
                  ) : derivedForecast ? (
                    <div className="forecast-headline">
                      <p className="forecast-headline-main">
                        <span className="forecast-stat-swatch" style={{ backgroundColor: COLORS.forecast }} aria-hidden="true" />
                        {derivedForecast.source === 'recomputed' ? 'Preview' : 'Next month'} ({formatPeriod(derivedForecast.period)}): about{' '}
                        <strong className="forecast-headline-number">
                          <ExactValue value={derivedForecast.value} label="Exact forecast" /> pcs
                        </strong>
                        {/* The verdict beside the number (2026-10-20); the MASE
                            behind it is in "Show details". */}
                        <span className={`forecast-headline-verdict is-${reliabilityState}`}>
                          <span aria-hidden="true">·</span>
                          {reliabilityState === 'unreliable' && <AlertTriangle size={15} aria-hidden="true" />}
                          {reliabilityState === 'reliable' && <CheckCircle2 size={15} aria-hidden="true" />}
                          {verdictText}
                        </span>
                      </p>
                      {derivedForecast.confidenceLower != null && derivedForecast.confidenceUpper != null && (
                        <p className="forecast-headline-range">
                          Most likely between <ExactValue value={derivedForecast.confidenceLower} label="Exact low end" /> and{' '}
                          <ExactValue value={derivedForecast.confidenceUpper} label="Exact high end" /> pcs
                          <InfoTip label="About the most likely range" size={12}>
                            {bandLevel != null
                              ? `Sales should land in this range about ${Math.round(bandLevel / 10)} times in 10.`
                              : 'Sales usually land in this range.'}
                            {' '}It is the shaded band on the chart; how it is worked out is in &ldquo;Show details&rdquo;.
                          </InfoTip>
                        </p>
                      )}
                      {/* A very wide range, in plain words: the high end more
                          than 3 times the low end (or a low end of 0). Not
                          beside a reliable forecast, whose sentence above
                          already says how rough it is (2026-10-20). */}
                      {reliabilityState !== 'reliable'
                        && derivedForecast.confidenceLower != null && derivedForecast.confidenceUpper != null
                        && (derivedForecast.confidenceLower <= 0
                          || derivedForecast.confidenceUpper > 3 * derivedForecast.confidenceLower) && (
                        <p className="forecast-headline-sub">
                          Sales of this product are hard to predict; the real number could be much lower or higher.
                        </p>
                      )}
                      {missShare != null && reliabilityState === 'unchecked' && (
                        <p className="forecast-headline-sub">
                          Our forecasts for this product are usually off by about {Math.round(missShare * 100)}%.
                        </p>
                      )}
                      {productAccuracy && !productAccuracy.checked && !storedParams.demonstration && (
                        <p className="forecast-headline-sub">
                          Our forecasts for this product haven&apos;t been checked against past sales in this date range yet.
                        </p>
                      )}
                      {forecastTrendPct != null && latestActualPoint && (
                        <p className="forecast-headline-sub">
                          {forecastTrendPct > 0.5
                            ? `That's ${Math.round(forecastTrendPct)}% more than ${formatPeriod(latestActualPoint.period)}`
                            : forecastTrendPct < -0.5
                              ? `That's ${Math.round(-forecastTrendPct)}% less than ${formatPeriod(latestActualPoint.period)}`
                              : `That's about the same as ${formatPeriod(latestActualPoint.period)}`}
                          {' '}(about <ExactValue value={latestActualPoint.quantity} label="Exact sales that month" /> pcs)
                          {stockLimitedPeriods.includes(latestActualPoint.period)
                            ? ` (${formatPeriod(latestActualPoint.period).split(' ')[0]} may have been low because stock ran out)`
                            : ''}.
                        </p>
                      )}
                    </div>
                  ) : (
                    <p className="forecast-headline-main">
                      {storedForecast
                        ? 'No sales in the selected range.'
                        : selectedSKU.cat === 'A' ? 'No forecast yet for this product.' : 'Forecasts are made for top sellers only.'}
                    </p>
                  )}
                  <StockLimitedNote periods={stockLimitedPeriods} />

                  {/* Partial overlap: the chart is real but narrower than what
                      was picked. Says exactly which end fell short and why,
                      names this SKU's true window, and offers a one-click
                      snap — so a short chart never reads as a broken filter. */}
                  {rangeStatus === 'partial' && skuCoverage && (
                    <div className="forecast-range-warning">
                      <div className="forecast-range-warning-text">
                        <strong>Showing {formatPeriod(chartData[0]?.label)} – {formatPeriod(lastPlottedActualPeriod)}.</strong>{' '}
                        This product only has recorded sales from {formatPeriod(skuCoverage.start)} to{' '}
                        {formatPeriod(skuCoverage.end)}
                        {rangeStartPeriod < skuCoverage.start && rangeEndPeriod > skuCoverage.end
                          ? ', so both ends of your selected range fall outside it.'
                          : rangeStartPeriod < skuCoverage.start
                            ? `, so the start of your range (${formatPeriod(rangeStartPeriod)}) has no data.`
                            : `, so the end of your range (${formatPeriod(rangeEndPeriod)}) has no data.`}
                      </div>
                      <button className="forecast-range-fix-btn" onClick={applySkuCoverageRange}>
                        Use this product&apos;s range
                      </button>
                    </div>
                  )}

                  {/* Never let a recomputed forecast pass as pipeline output.
                      Only a served MA3 is recomputed (see derivedForecast), so
                      the point estimate is this SKU's own model on real
                      months, but it has no confidence interval or accuracy
                      score because those need the holdout evaluation only
                      scripts/run_baseline_forecast.py performs. */}
                  {derivedForecast?.source === 'recomputed' && (
                    <p className="forecast-range-note">
                      <strong>A preview for {formatPeriod(derivedForecast.period)}.</strong>{' '}
                      Your range ends before {formatPeriod(skuCoverage?.end)}, so this is the average of the 3 months up to{' '}
                      {formatPeriod(derivedForecast.basisPeriod)}, worked out the same way as the real forecast. It has no
                      &ldquo;most likely&rdquo; range and no reliability check: those exist only for the{' '}
                      {formatPeriod(storedForecastPeriod)} forecast. Extend the range to {formatPeriod(skuCoverage?.end)} to see it.
                    </p>
                  )}

                  {/* An earlier cutoff the browser can't honestly forecast
                      from: the stored number stays the one shown (unplotted —
                      it projects from a month outside the range), and this
                      says why nothing was recomputed in its place. */}
                  {servedModel?.kind === 'forecast' && derivedForecast?.source === 'stored' && !derivedForecast.plotted && (
                    <p className="forecast-range-note">
                      <strong>Showing the {formatPeriod(derivedForecast.period)} forecast.</strong>{' '}
                      {servedModel.recomputable
                        ? `This product had fewer than ${MIN_SALES_MONTHS} months of sales up to ${formatPeriod(derivedForecast.earlierCutoff)}, so no forecast can be worked out for a range ending there.`
                        : `This product's forecast can only be worked out by the forecasting run, not on this page, so nothing is shown for a range ending ${formatPeriod(derivedForecast.earlierCutoff)}.`}
                      {' '}Extend the range to {formatPeriod(derivedForecast.basisPeriod)} to see it on the chart.
                    </p>
                  )}

                </>
              )}
            </div>

            {/* What to order (2026-10-19): from the current order plan, or
                for a product outside it, its stock, weeks left at this
                forecast and why the plan leaves it out. */}
            {showingThisSKU && !isForecastColdLoad && !forecastError && (
              <section className="forecast-order-card" aria-label="What to order">
                <h3 className="forecast-card-title">What to order</h3>
                {!planLoaded ? (
                  <LoadingStatus>Loading the order plan…</LoadingStatus>
                ) : plan.failed ? (
                  <p className="forecast-order-reason">The order plan couldn&apos;t be loaded.</p>
                ) : planItem ? (
                  <>
                    <SectionLede>From the current order plan{plan.cycle ? ` for ${formatPeriod(plan.cycle)}` : ''}.</SectionLede>
                    {calendarPending && (
                      <p className="forecast-order-reason">
                        This plan uses the forecast with the {adjustmentMonth ?? 'calendar'} adjustment (pending approval).
                      </p>
                    )}
                    <dl className="forecast-order-grid">
                      <div>
                        <dt>In stock now</dt>
                        <dd>
                          {planItem.stock_not_in_count ? (
                            <>
                              {NOT_IN_COUNT}
                              <InfoTip label="About a product missing from the stock count" size={12}>
                                This product is missing from the stock count, so the plan reads it as 0 on hand. The stock
                                file lists no zero rows, so a missing product is most likely out of stock.
                              </InfoTip>
                            </>
                          ) : planItem.current_stock != null ? <><ExactValue value={planItem.current_stock} /> pcs</> : 'no stock count'}
                        </dd>
                      </div>
                      <div>
                        <dt>
                          Lasts about
                          <InfoTip label="About how long stock lasts" size={12}>
                            How long the stock on hand lasts at the forecast: the plan&apos;s own cover (days of cover ÷ 7).
                          </InfoTip>
                        </dt>
                        <dd>{coverText(planItem, planItem.days_of_cover != null ? planItem.days_of_cover / 7 : null)}</dd>
                      </div>
                      <div>
                        <dt>
                          Keep at least
                          <InfoTip label="About keep at least" size={12}>
                            Safety stock: the buffer the plan keeps for a month that sells more than forecast.
                          </InfoTip>
                        </dt>
                        <dd><ExactValue value={planItem.ss_i} /> pcs</dd>
                      </div>
                      <div>
                        <dt>
                          Order
                          <InfoTip label="How the order is worked out" size={12}>
                            {orderBreakdown(planItem, plan.cycle ? formatPeriod(plan.cycle) : null)}
                          </InfoTip>
                        </dt>
                        <dd><strong><ExactValue value={planItem.q_i} /> pcs</strong></dd>
                      </div>
                      <div>
                        <dt>Status</dt>
                        <dd>
                          <span className={getUrgencyBadge(planItem.urgency)} title={URGENCY_HOVER[planItem.urgency]}>
                            {planItem.urgency}
                          </span>
                        </dd>
                      </div>
                    </dl>
                    {canOpenReorder && (
                      <button
                        type="button"
                        className="forecast-plan-link"
                        onClick={() => navigate(`/reorder?sku=${encodeURIComponent(selectedSKU.code)}`)}
                      >
                        Open in Reorder Recommendations
                        <ArrowRight size={13} aria-hidden="true" />
                      </button>
                    )}
                  </>
                ) : (
                  <>
                    <p className="forecast-order-reason"><strong>Not in the current order plan.</strong> {notPlannedReason}</p>
                    <dl className="forecast-order-grid">
                      <div>
                        <dt>In stock now</dt>
                        <dd>{outsideStock != null ? <><ExactValue value={outsideStock} /> pcs</> : 'no stock count'}</dd>
                      </div>
                      <div>
                        <dt>
                          Lasts about
                          <InfoTip label="About how long stock lasts" size={12}>
                            Stock on hand ÷ (this forecast ÷ {WEEKS_PER_MONTH.toFixed(2)} weeks a month): how long the stock
                            lasts if sales match the forecast. Not from the plan.
                          </InfoTip>
                        </dt>
                        <dd>{fmtWeeks(outsideWeeks)}</dd>
                      </div>
                    </dl>
                  </>
                )}
              </section>
            )}

            {/* The chart, in its own card under What to order (2026-10-20). */}
            {!isForecastColdLoad && !forecastError && forecastResult && (rangeStatus === 'ok' || rangeStatus === 'partial') && (
              <div className="forecast-chart-container forecast-chart-card" key={`chartcard-${selectedSKU.code}`}>
                <h3 className="forecast-card-title">Past sales and the forecast</h3>
                  {/* Chart, or its table twin. The legend sits ABOVE the
                      plot (under the stat rows), so the key is met before
                      the marks — same order as the dashboard's charts. */}
                  <div className="forecast-chart-tools">
                    <ChartViewToggle view={chartView} onChange={setChartView} label="Forecast: chart or table" />
                  </div>
                  {chartView === 'table' ? (
                    <ChartTable
                      caption="Actual sales and forecast by month, in pcs"
                      columns={[
                        {
                          key: 'period',
                          label: 'Month',
                          format: (v) => `${formatAxisPeriod(v)}${isPlaceholderPeriod(v, placeholder) ? ' (sample data)' : ''}`,
                          align: 'left',
                        },
                        { key: 'actualV', label: 'Actual (pcs)', format: (v) => Math.round(v).toLocaleString() },
                        { key: 'forecastV', label: 'Forecast (pcs)', format: (v) => Math.round(v).toLocaleString() },
                        { key: 'lastYearV', label: 'Same month last year (pcs)', format: (v) => Math.round(v).toLocaleString() },
                        { key: 'ciLow', label: 'Most likely, low (pcs)', format: (v) => Math.round(v).toLocaleString() },
                        { key: 'ciHigh', label: 'Most likely, high (pcs)', format: (v) => Math.round(v).toLocaleString() },
                      ]}
                      rows={chartData.map((pt) => ({
                        period: pt.label,
                        actualV: pt.actual ?? null,
                        lastYearV: pt.lastYear ?? null,
                        // The bridge point borrows the last actual purely so
                        // the lines join — the table stays honest and shows
                        // the forecast only for its own month.
                        forecastV: pt.actual == null ? pt.forecast ?? null : null,
                        ciLow: pt.actual == null && Array.isArray(pt.ci) ? pt.ci[0] : null,
                        ciHigh: pt.actual == null && Array.isArray(pt.ci) ? pt.ci[1] : null,
                      }))}
                    />
                  ) : (
                  <>
                  <div className="chart-legend">
                    {chartData.some((pt) => pt.actual != null) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <line x1="1" y1="6" x2="27" y2="6" stroke={CHART_COLORS.salesSeries} strokeWidth="2.5" strokeLinecap="round" />
                        </svg>
                        <span className="legend-label">Actual Sales</span>
                      </div>
                    )}
                    {chartData.some((pt) => pt.lastYear != null) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <line x1="1" y1="6" x2="27" y2="6" stroke={CHART_COLORS.salesSeries} strokeWidth="1.5" strokeOpacity="0.55" strokeLinecap="round" strokeDasharray="3 3" />
                        </svg>
                        <span className="legend-label">Same month last year</span>
                      </div>
                    )}
                    {/* Forecast and band entries follow what is actually
                        plotted: no forecast point goes on the chart for a SKU
                        outside Category A, a provisional / no-order row, or
                        an earlier cutoff showing the stored value unplotted. */}
                    {chartData.some((pt) => pt.forecast != null) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <line x1="1" y1="6" x2="27" y2="6" stroke={COLORS.forecast} strokeWidth="2.5" strokeLinecap="round" strokeDasharray="6 4" />
                        </svg>
                        <span className="legend-label">Forecast</span>
                      </div>
                    )}
                    {chartData.some((pt) => Array.isArray(pt.ci) && pt.ci[0] !== pt.ci[1]) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <rect
                            x="1" y="1.5" width="26" height="9" rx="2.5"
                            fill={COLORS.forecast} fillOpacity="0.16"
                            stroke={COLORS.forecast} strokeOpacity="0.35" strokeWidth="1"
                          />
                        </svg>
                        <span className="legend-label">{bandLabel}</span>
                      </div>
                    )}
                    {chartData.some((pt) => pt.stockLimited) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <rect x="1" y="1.5" width="26" height="9" rx="2.5" fill={STOCK_LIMITED_FILL} fillOpacity="0.28" />
                        </svg>
                        <span className="legend-label">Stock may have run out</span>
                      </div>
                    )}
                    {chartData.some((pt) => GENERATED_REASONS.has(pt.reason)) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <rect x="1" y="1.5" width="26" height="9" rx="2.5" fill={CHART_COLORS.placeholder} fillOpacity="0.3" />
                        </svg>
                        <span className="legend-label">Sample data, not SSM&apos;s</span>
                      </div>
                    )}
                    {chartData.some((pt) => isPlaceholderPeriod(pt.label, placeholder)) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <rect x="1" y="1.5" width="26" height="9" rx="2.5" fill={CHART_COLORS.placeholder} fillOpacity="0.3" />
                        </svg>
                        <span className="legend-label">Sample data, not SSM&apos;s</span>
                      </div>
                    )}
                  </div>
                  <div className={`chart-wrapper${zoom.canPan ? ' chart-pannable' : ''}`} ref={zoom.containerRef} {...zoom.panHandlers}>
                    {/* The X axis is 44px tall so its "Month" title sits
                        under the tick row instead of on it; the bottom
                        margin keeps the title off the SVG's edge (with
                        bottom:0 the month labels were once clipped). */}
                    <ResponsiveContainer width="100%" height={420}>
                      <ComposedChart data={zoom.view} margin={{ top: 20, right: EDGE_LABEL_MARGIN, left: 8, bottom: 12 }}>
                        <CartesianGrid {...GRID_PROPS} />
                        {renderPlaceholderBand(placeholderSpan(zoom.view.map((pt) => ({ period: pt.label })), placeholder))}
                        {/* Generated months, then the months where stock may
                            have run out (the reason is in the hover). */}
                        {generatedRuns.map(([x1, x2]) => (
                          <ReferenceArea
                            key={`gen-${x1}`}
                            x1={x1}
                            x2={x2}
                            fill={CHART_COLORS.placeholder}
                            fillOpacity={0.18}
                            stroke="none"
                            label={{ value: 'Sample data', position: 'insideTop', fontSize: 10, fill: CHART_COLORS.axisLabel }}
                          />
                        ))}
                        {stockLimitedRuns.map(([x1, x2]) => (
                          <ReferenceArea
                            key={`sl-${x1}`}
                            x1={x1}
                            x2={x2}
                            fill={STOCK_LIMITED_FILL}
                            fillOpacity={0.14}
                            stroke="none"
                          />
                        ))}
                        <XAxis
                          dataKey="label"
                          axisLine={true}
                          tickLine={true}
                          tick={<MonthTick fill="#556070" fontSize={11} />}
                          tickFormatter={monthName}
                          tickMargin={10}
                          minTickGap={12}
                          height={44 + MONTH_TICK_EXTRA_HEIGHT}
                          label={{ value: 'Month', position: 'insideBottom', offset: 0, fontSize: 11, fill: CHART_COLORS.axisLabel }}
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
                          // Superseded by the zoom window: a numeric
                          // interval counts forward from index 0, so it
                          // keeps that first tick by construction, and
                          // drops to 0 — every month labelled — as soon as
                          // the window is narrow enough to fit them.
                          interval={zoom.labelInterval}
                        />
                        <YAxis
                          axisLine={true}
                          tickLine={true}
                          tick={{ fill: '#556070', fontSize: 11 }}
                          tickFormatter={formatAxisQty}
                          width={60}
                          tickMargin={8}
                          // From 0, never below (2026-10-20): sales can't be
                          // negative, so a range's low end under 0 is cut at 0.
                          domain={[0, 'auto']}
                          allowDataOverflow
                          label={{ value: 'Pcs', angle: -90, position: 'insideLeft', fontSize: 11, fill: CHART_COLORS.axisLabel }}
                        />
                        <Tooltip content={<CustomTooltip bandLabel={bandLabel} bandLevel={bandLevel} />} />

                        {/* Where actuals hand over to the forecast — the
                            divider the dashed style is read against. Only
                            while the bridge month is inside the window. */}
                        {derivedForecast?.plotted && lastPlottedActualPeriod &&
                          zoom.view.some((pt) => pt.label === lastPlottedActualPeriod) && (
                          <ReferenceLine
                            x={lastPlottedActualPeriod}
                            stroke={CHART_COLORS.axisLabel}
                            strokeDasharray="4 4"
                            label={{ value: 'Forecast starts', position: 'insideTopRight', fontSize: 11, fill: CHART_COLORS.axisLabel }}
                          />
                        )}

                        {/* Drawn before the lines so the band sits behind
                            them. A faint stroke gives the cone a readable
                            edge — the pale fill alone washed out against the
                            white card at this opacity. */}
                        <Area
                          type="linear"
                          dataKey="ci"
                          stroke={COLORS.forecast}
                          strokeOpacity={0.35}
                          strokeWidth={1}
                          fill={COLORS.forecast}
                          fillOpacity={0.16}
                          name={bandLabel}
                          {...zoom.zoomAnim(0)}
                          connectNulls={false}
                        />

                        {/* No washes under these lines (design pass
                            2026-09-26): the CI cone above is the one fill
                            that carries information, and the gradients
                            muddied it where the series overlapped. */}

                        {/* Teal, not the old indigo: indigo sat too close to
                            the forecast's violet to tell apart in a small
                            legend swatch. Teal-vs-violet is also exactly how
                            the Dashboard's portfolio forecast already
                            separates actual from forecast, so the two pages
                            now agree. */}
                        {/* Last year: the actual line's colour, thinner,
                            dotted and faded (the dashboard hero chart's rule:
                            colour = metric, line style = year). */}
                        <Line
                          type="linear"
                          dataKey="lastYear"
                          stroke={CHART_COLORS.salesSeries}
                          strokeWidth={1.5}
                          strokeOpacity={0.55}
                          strokeDasharray="3 3"
                          dot={false}
                          activeDot={{ r: 4 }}
                          name="Same month last year"
                          {...zoom.zoomAnim(1)}
                        />
                        <Line
                          type="linear"
                          dataKey="actual"
                          stroke={CHART_COLORS.salesSeries}
                          strokeWidth={2}
                          dot={seriesDot({ color: CHART_COLORS.salesSeries })}
                          activeDot={{ r: 6 }}
                          name="Actual Sales"
                          {...zoom.zoomAnim(1)}
                          connectNulls
                        />

                        <Line
                          type="linear"
                          dataKey="forecast"
                          stroke={COLORS.forecast}
                          strokeWidth={2}
                          strokeDasharray="5 5"
                          dot={seriesDot({ color: COLORS.forecast, r: 4, skip: (p) => p?.actual != null })}
                          activeDot={{ r: 6 }}
                          name="Forecast"
                          label={forecastEndLabels}
                          {...zoom.zoomAnim(2)}
                          connectNulls
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Chart legend — bottom-center, matching the
                      .custom-legend convention every other page's charts
                      use (Dashboard's Charts.jsx), so the legend
                      sits in the same spot on every graph app-wide instead
                      of this page being the one exception up at top-right.
                      Swatches are inline SVG so each one is an exact
                      miniature of the mark it stands for (solid stroke,
                      dashed stroke, filled band) — a CSS-only swatch faking
                      the dash via a background gradient rendered as a lumpy
                      bowtie at this size. */}
                  <ChartZoomSlider zoom={zoom} />
                  {/* What the chart's zero and empty months mean, in the
                      backend's words: only the reasons still on the chart. */}
                  <GapNote note={forecastResult?.gap_note} codes={drawnReasons} />
                  </>
                  )}
              </div>
            )}

            {/* How this product sells, in plain words (the measures are in
                "Show details"). Keyed on the product so it replays its entrance. */}
            <SkuDemandPatternPanel
              key={`pattern-${selectedSKU.code}`}
              skuId={selectedSKU.code}
              principal={principal}
            />

            {/* Everything technical, closed by default (2026-10-20): the model
                and why, bin, MASE, the range's method, the past misses with
                the backtest source and the pesos basis, the sales-pattern
                measures and the top-seller rule with its adviser caveat. */}
            {showingThisSKU && !isForecastColdLoad && !forecastError && forecastResult && (
              <details className="forecast-details">
                <summary>Show details: how this forecast was made</summary>
                <div className="forecast-details-body">
                  {/* How this forecast was made — the stored number's
                      provenance, straight from model_params: the served
                      model, the history bin that picked it, the MA3
                      benchmark (computed for every SKU), and for the
                      XGBoost + MA3 average both components. Shown only
                      beside the stored number it describes: a browser preview
                      is explained by its own note, and a provisional /
                      no-order row isn't a forecast. Names models only; no
                      claim that one is more accurate than MA3. */}
                  {servedModel?.kind === 'forecast' && derivedForecast?.source === 'stored' && (
                    <div className="forecast-howmade">
                      <span className="forecast-howmade-title">The forecast model</span>
                      <dl className="forecast-howmade-list">
                        <div className="forecast-howmade-item">
                          <dt>Model</dt>
                          <dd>
                            {servedModel.label ?? storedParams.method ?? '—'}
                            {servedModel.plain ? `: ${servedModel.plain.long}` : ''}
                            {whyModel && <span className="forecast-howmade-why">{whyModel}</span>}
                          </dd>
                        </div>
                        {/* Whether the forecast knows what time of year it is. */}
                        {(calendarPending ? unadjustedModel?.plain?.season : servedModel.plain?.season) && (
                          <div className="forecast-howmade-item">
                            <dt>Time of year</dt>
                            <dd>{calendarPending ? unadjustedModel.plain.season : servedModel.plain.season}</dd>
                          </div>
                        )}
                        {/* The adjusted forecast, awaiting sign-off (the
                            headline is the model's own number). */}
                        {calendarPending && adjustedValue != null && (
                          <div className="forecast-howmade-item">
                            <dt>With {adjustmentMonth ?? 'calendar'} adjustment (pending approval)</dt>
                            <dd>
                              {Math.round(adjustedValue).toLocaleString()} pcs: the forecast above
                              {' '}({Math.round(servedModel.calendar.before).toLocaleString()} pcs) × {servedModel.calendar.factor.toFixed(4)},
                              {' '}how this month has sold against the 3 months before it
                              {servedModel.calendar.years != null ? ` in ${servedModel.calendar.years} earlier ${servedModel.calendar.years === 1 ? 'year' : 'years'}` : ''}
                              {' '}(company total). {calendarSignoffText(forecastResult?.calendar_signed_off)
                                ? `${calendarSignoffText(forecastResult.calendar_signed_off).charAt(0).toUpperCase()}${calendarSignoffText(forecastResult.calendar_signed_off).slice(1)}; the headline shows the forecast without it.`
                                : 'The headline shows the forecast without it.'}
                              {' '}The order plan uses the adjusted figure.
                            </dd>
                          </div>
                        )}
                        {storedParams.bin && (
                          <div className="forecast-howmade-item">
                            <dt>Bin (history)</dt>
                            <dd>
                              {storedParams.sales_months != null
                                ? `${storedParams.sales_months} sales month${storedParams.sales_months === 1 ? '' : 's'} → `
                                : ''}
                              {storedParams.bin}
                            </dd>
                          </div>
                        )}
                        {storedParams.ma3_value != null && (
                          <div className="forecast-howmade-item">
                            <dt>3-month average (MA3){ma3Window ? `, ${ma3Window}` : ''}</dt>
                            <dd>{Math.round(storedParams.ma3_value).toLocaleString()} pcs a month</dd>
                          </div>
                        )}
                        {/* Reliability on the same basis as the dashboard's
                            count and the LP's gate: MASE < 1 means the
                            served model beat a naive last-month forecast
                            on its own rolling holdout. */}
                        {storedForecast?.mase != null && (
                          <div className="forecast-howmade-item">
                            <dt>
                              Reliability
                              <InfoTip label="About reliability">
                                MASE compares this model&apos;s errors with simply repeating last month&apos;s sales.
                                Below 1 means the model does better than that; 1 or more means it doesn&apos;t.
                                {/* Three decimals near 1, where two would round
                                    0.996 up to "1.00" beside "beats a simple
                                    last-month guess" (the verdict uses the
                                    stored value). */}
                                {' '}This product: MASE {storedForecast.mase.toFixed(Math.abs(storedForecast.mase - 1) < 0.01 ? 3 : 2)}.
                              </InfoTip>
                            </dt>
                            <dd className={storedForecast.mase < 1 ? '' : 'forecast-howmade-warn'}>
                              {/* The verdict in plain words; the score is
                                  behind the "?" for the adviser. */}
                              {storedForecast.mase < 1 ? 'Reliable enough to use for ordering' : 'Not reliable enough yet'}:
                              {' '}MASE {maseText} (below 1 beats simply repeating last month&apos;s sales)
                              {holdoutWindow ? `, tested on ${holdoutWindow}` : ''}
                              {calendarPending ? '. Worked out on the adjusted forecast; there is no separate check without the adjustment.' : ''}
                            </dd>
                          </div>
                        )}
                        {storedParams.method === 'xgb_ma3_avg' && storedParams.components && (
                          <div className="forecast-howmade-item">
                            <dt>Components</dt>
                            <dd>
                              XGBoost {storedParams.components.xgb != null ? Math.round(storedParams.components.xgb).toLocaleString() : '—'}
                              {' + '}
                              MA3 {storedParams.components.ma3 != null ? Math.round(storedParams.components.ma3).toLocaleString() : '—'}
                              {' '}pcs, averaged
                            </dd>
                          </div>
                        )}
                        {derivedForecast.confidenceLower != null && derivedForecast.confidenceUpper != null && (
                          <div className="forecast-howmade-item">
                            <dt>Most likely range</dt>
                            <dd>
                              {fmtPcs(derivedForecast.confidenceLower)}–{fmtPcs(derivedForecast.confidenceUpper)} pcs: the forecast
                              {' '}± 1.645 × the model&apos;s error on past months (holdout root-mean-square error)
                              {bandLevel != null ? `, so sales land in it about ${bandLevel}% of the time` : ''}.
                              {calendarPending && adjustedValue != null
                                ? ` Worked out around the adjusted forecast (${Math.round(adjustedValue).toLocaleString()} pcs); there is no separate range without the adjustment.`
                                : ''}
                            </dd>
                          </div>
                        )}
                      </dl>
                      {/* The guard rejected the TSB / XGBoost value and MA3
                          was served instead (router.py). The raw code stays
                          in the tooltip; the chip restates it plainly. */}
                      {storedParams.backup_fired === true && (
                        <span className="forecast-fallback-chip">
                          <AlertTriangle size={13} aria-hidden="true" />
                          Served MA3 as a fallback — {describeFallbackReason(storedParams.backup_reason)}
                        </span>
                      )}
                    </div>
                  )}

                  {productAccuracy?.checked && (
                    <div className="forecast-details-section">
                      <ForecastErrorCard error={productAccuracy.error} detailed />
                      {SHOW_ACCURACY_PCT && <AccuracyLevels accuracy={forecastResult?.accuracy} />}
                    </div>
                  )}
                  {productAccuracy && !productAccuracy.checked && (
                    <p className="forecast-accuracy-none">
                      Not checked against sales in {formatPeriod(rangeStartPeriod)} – {formatPeriod(rangeEndPeriod)}:
                      no forecast for this product was scored in those months.
                    </p>
                  )}
                  <div className="forecast-details-section">
                    <span className="forecast-howmade-title">Sales pattern, measured</span>
                    <SkuDemandPatternPanel
                      key={`pattern-details-${selectedSKU.code}`}
                      skuId={selectedSKU.code}
                      principal={principal}
                      variant="details"
                    />
                  </div>
                  <div className="forecast-details-section">
                    <span className="forecast-howmade-title">Top sellers</span>
                    <TierBasisLabel periods={tierAPeriods} />
                    {tierAPeriods?.Unilever && (
                      <p className="forecast-details-note">
                        Unilever&apos;s rule (Class A over the last 12 months, plus new products that are Class A over the
                        last 3) is pending adviser confirmation.
                      </p>
                    )}
                  </div>
                </div>
              </details>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default SKUForecast;
