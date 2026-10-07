import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useOutletContext, useSearchParams } from 'react-router-dom';
import { Search, Star, ArrowRight, Clock, Filter, X, ArrowUp, ArrowDown, Minus, AlertTriangle } from 'lucide-react';
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import { COLORS, CHART_COLORS } from '../theme/colors';
import { useChartZoom, ChartZoomSlider, seriesDot, pointLabels, GRID_PROPS, EDGE_LABEL_MARGIN } from './ChartZoom';
import { ChartTable, ChartViewToggle } from './ChartTable';
import { useEntranceReplay } from '../theme/useEntranceReplay';
import RefreshingNote from './RefreshingNote';
import { LoadingStatus, SkeletonChart, SkeletonLine } from './Skeleton';
import { getABCClassification } from '../api/abc';
import { getForecast } from '../api/forecast';
import { getForecastAccuracy } from '../api/dashboard';
import { useBrandLookup } from '../utils/useBrandLookup';
import { describeServedModel, describeFallbackReason } from '../utils/forecastModel';
import DateFilter from './DateFilter';
import SkuDemandPatternPanel from './SkuDemandPatternPanel';
import { FIRST_DATA_YEAR, LATEST_DATA_PERIOD } from '../dataCoverage';
import { isPlaceholderPeriod, isPreviewMode } from '../dataMode';
import { placeholderSpan, renderPlaceholderBand } from '../utils/placeholderBand';
import InfoTip from './InfoTip';
import ProductName from './ProductName';
import './SKUForecast.css';
import { AccuracyLevels, ForecastErrorCard, StockLimitedNote } from './PendingCards';

// Pinned-star colour: brand chrome (--color-brand-primary's hex — SVG
// presentation attributes can't take a CSS var()). It used to be the
// amber data colour, which means "watch" everywhere else in the app.
// Forecast accuracy percentages (WAPE) are held back while they are
// recomputed on the fairer test — see the stat block that reads this.
const SHOW_ACCURACY_PCT = false;

const PIN_COLOR = '#C74E3D';
const PIN_IDLE_COLOR = '#667085';

// Del Monte's sales data is invoice-grain with no SKU column, so the pipeline
// never forecasts it per SKU — its ABC rows are product categories. With the
// Topbar on Del Monte this replaces the picker; it also heads the message
// for a Del Monte row that reaches the chart card some other way.
const DEL_MONTE_NO_FORECAST =
  'No SKU-level forecast for Del Monte — it has no SKU-level sales data, only category sell-out.';

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

const CustomTooltip = ({ active, payload, label, bandLabel = 'Likely range' }) => {
  if (active && payload && payload.length) {
    // Each line is drawn twice — the Line, plus the Area shading under it —
    // so the raw payload carries every value twice over. The fills declare
    // tooltipType="none", which Recharts passes through as `type`; dropping
    // those leaves one entry per real series.
    const series = payload.filter(p => p.type !== 'none');
    const hasActual = series.some(p => p.dataKey === 'actual');
    const displayPayload = hasActual
      ? series.filter(p => p.dataKey !== 'forecast')
      : series;

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
                {bandLabel}: {qty(entry.value[0])} – {qty(entry.value[1])} pieces
              </p>
            );
          }
          return (
            <p key={index} className="tooltip-item">
              <span className="tooltip-dot" style={{ backgroundColor: entry.color }}></span>
              {entry.name}: {qty(entry.value)} pieces
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
      : { ...floorStart, endMonth: LATEST_DATA_PERIOD.month, endYear: LATEST_DATA_PERIOD.year };
  })();
  const [localRange, setLocalRange] = useState(() => seedRange);
  // GET /data-mode answers after this page first renders, so a preview seed
  // taken before it lands is the real-floor one; re-seed once the what-if
  // outputs are known to exist, so the five-year range shows without a Clear.
  useEffect(() => {
    if (whatIf) setLocalRange(seedRange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [whatIf]);
  const rangeStartPeriod = toPeriod(localRange.startMonth, localRange.startYear);
  const rangeEndPeriod = toPeriod(localRange.endMonth, localRange.endYear);

  // "Clear" (DateFilter's local-mode reset button) — snaps this page's own
  // range back to the dashboard's, same source the initial seed above used.
  // Nothing else on this page writes to the shared dashboard range, so
  // comparing localRange against the LIVE dashboardRange is equivalent to
  // comparing against the original seed — only shown once the user has
  // actually picked something different, never just because the page loaded.
  const resetToDashboardRange = () => setLocalRange(seedRange);
  const isCustomRange =
    localRange.startMonth !== seedRange.startMonth ||
    localRange.startYear !== seedRange.startYear ||
    localRange.endMonth !== seedRange.endMonth ||
    localRange.endYear !== seedRange.endYear;

  const [rawItems, setRawItems] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(null);

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
      })
      .catch((err) => {
        if (cancelled) return;
        setListError(err.message || 'Failed to load SKU list');
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => { cancelled = true; };
  }, [principal]);

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
    return {
      checked: true,
      error: {
        pieces_per_month: sum('abs_miss_pieces') / rows.length,
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
        setForecastResult(res);
        setForecastFor({ sku: selectedSKU.code, principal });
      })
      .catch((err) => {
        if (cancelled) return;
        setForecastError(err.message || 'Failed to load forecast');
      })
      .finally(() => {
        if (!cancelled) setForecastLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedSKU, principal]);

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
  const bandLabel = bandLevel != null ? `~${bandLevel}% range` : 'Likely range';
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
      value: storedForecast.forecast_value,
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
        ci: derivedForecast.confidenceLower != null && derivedForecast.confidenceUpper != null
          ? [derivedForecast.confidenceLower, derivedForecast.confidenceUpper]
          : undefined,
      }]
      : [];
    return [...actualPoints, ...forecastPoints];
  }, [forecastResult, rangeStartPeriod, rangeEndPeriod, derivedForecast]);

  // Windowing for the chart below — see ./ChartZoom. This page's range can
  // run well past what the X axis can label without skipping months.
  const zoom = useChartZoom(chartData);

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

  // Small print under the provisional / no-order notice in the stat row:
  // what the pipeline stored and why it isn't a forecast. The counts come
  // from the run's own model_params, not recounted here.
  const describePlaceholder = () => {
    if (servedModel?.kind === 'no_order') {
      return 'Stored as 0 pieces: the reorder plan orders nothing for this SKU.';
    }
    const params = storedForecast?.model_params || {};
    const months = params.observed_months_used ?? params.months_with_sales;
    const needed = params.min_months_threshold ?? MIN_SALES_MONTHS;
    const basis = months != null ? `${months} month${months === 1 ? '' : 's'} of sales` : 'its sales so far';
    const value = Math.round(storedForecast?.forecast_value ?? 0).toLocaleString();
    return `Trailing average of ${basis}: ${value} pieces a month. A forecast needs at least ${needed} months of sales.`;
  };

  return (
    <div className="forecast-page">
      <div className="forecast-content" data-enter-cycle={enterCycle}>
        {/* Header */}
        <div className="forecast-header">
          <div className="header-text-group">
            <h2 className="forecast-title">
              Demand <span className="page-title-accent">forecasted</span>
            </h2>
            <p className="forecast-subtitle">
              Next-month forecast for Class A SKUs, from Forecast_Result. Each SKU&apos;s model depends on
              how many months of sales it has.
            </p>
            {whatIf && (
              <p className="chart-placeholder-note">
                Preview: this forecast is a what-if run of the same models on the five-year history, 2021–22
                placeholder months included (built {String(dashboardRange.previewInfo.outputs.built_at).slice(0, 10)}).
                It is never saved and is not the live forecast.
              </p>
            )}
            {realFloor && (
              <p className="chart-placeholder-note">
                Preview is on, but forecasts are made from real data only, so this chart starts no earlier than
                Jan {FIRST_DATA_YEAR}. The &ldquo;Demand pattern&rdquo; panel below does include the
                2021–22 placeholder months.
              </p>
            )}
          </div>

          <div className="forecast-header-actions">
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
              className="browse-all-skus-btn"
              onClick={() => navigate('/sku-management')}
              title="Go to SKU Management table"
            >
              <span>Browse all SKUs</span>
              <ArrowRight size={14} />
            </button>
          </div>
        </div>

        {/* Del Monte: the message REPLACES the picker and everything under
            it. Its ABC rows are product categories, and listing them here
            as if they were SKUs led to a request that could only 404. */}
        {isDelMonte && (
          <div className="forecast-empty-state">
            <div className="forecast-empty-icon">
              <Search size={28} strokeWidth={1.6} />
            </div>
            <h3 className="forecast-empty-title">{DEL_MONTE_NO_FORECAST}</h3>
            <p className="forecast-empty-body">
              Del Monte is ranked by product category on the ABC Classification page. Switch the scope to
              Unilever to forecast a SKU.
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
            <label className="selection-label">SELECT SKU TO FORECAST</label>
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
                <span className="filter-icon-label"><Filter size={12} /> Class:</span>
                <select
                  className="filter-select"
                  value={selectedCategory}
                  onChange={(e) => {
                    setSelectedCategory(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                >
                  <option value="ALL">All classes</option>
                  <option value="A">Class A</option>
                  <option value="B">Class B</option>
                  <option value="C">Class C</option>
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
                  placeholder="Search by product name, SKU code or brand…"
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
                              aria-label={`${pinnedSKUs.includes(sku.code) ? 'Unpin' : 'Pin'} ${sku.name} (${sku.code})`}
                              aria-pressed={pinnedSKUs.includes(sku.code)}
                            >
                              <Star size={15} fill={pinnedSKUs.includes(sku.code) ? PIN_COLOR : 'none'} />
                            </button>
                            <ProductName name={sku.name} code={sku.code} className="result-product" />
                            {sku.brand && <span className="result-brand">{sku.brand}</span>}
                            <span className={`forecast-cat-badge cat-${sku.cat}`}>Class {sku.cat}</span>
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
                            <Star size={12} fill={PIN_COLOR} color={PIN_COLOR} />
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
                                aria-label={`Unpin ${sku.name} (${sku.code})`}
                                aria-pressed={true}
                              >
                                <Star size={15} fill={PIN_COLOR} />
                              </button>
                              <ProductName name={sku.name} code={sku.code} className="result-product" />
                              {sku.brand && <span className="result-brand">{sku.brand}</span>}
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Class {sku.cat}</span>
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
                                aria-label={`Pin ${sku.name} (${sku.code})`}
                                aria-pressed={pinnedSKUs.includes(sku.code)}
                              >
                                <Star size={15} fill={pinnedSKUs.includes(sku.code) ? PIN_COLOR : 'none'} />
                              </button>
                              <ProductName name={sku.name} code={sku.code} className="result-product" />
                              {sku.brand && <span className="result-brand">{sku.brand}</span>}
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Class {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Section 3: Category A SKUs */}
                      {catASKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <span>CLASS A SKUS (HIGH PRIORITY)</span>
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
                                aria-label={`Pin ${sku.name} (${sku.code})`}
                                aria-pressed={pinnedSKUs.includes(sku.code)}
                              >
                                <Star size={15} fill={pinnedSKUs.includes(sku.code) ? PIN_COLOR : 'none'} />
                              </button>
                              <ProductName name={sku.name} code={sku.code} className="result-product" />
                              {sku.brand && <span className="result-brand">{sku.brand}</span>}
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Class {sku.cat}</span>
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
            <LoadingStatus>Loading SKU list…</LoadingStatus>
            <div className="forecast-empty-state" aria-hidden="true">
              <SkeletonLine className="skeleton-circle" width="56px" height="56px" />
              <SkeletonLine width="18rem" height="1rem" />
              <SkeletonLine width="26rem" height="0.75rem" />
            </div>
          </>
        )}
        {!isDelMonte && listError && <p className="forecast-subtitle">Error: {listError}</p>}

        {/* The page's resting state until the user picks a SKU — nothing is
            auto-selected, so this is what a fresh visit (or a refresh)
            shows. Also covers the genuinely empty list. */}
        {!isDelMonte && !selectedSKU && !listLoading && !listError && (
          <div className="forecast-empty-state">
            <div className="forecast-empty-icon">
              <Search size={28} strokeWidth={1.6} />
            </div>
            <h3 className="forecast-empty-title">
              {sourceSKUs.length === 0
                ? 'No classified SKUs for this principal'
                : 'Select or search a SKU to display forecast'}
            </h3>
            <p className="forecast-empty-body">
              {sourceSKUs.length === 0
                ? 'GET /abc returned no rows for the selected principal, so there is nothing to forecast yet.'
                : 'Search by product name, SKU code or brand above — or pick one from your pinned and recently viewed SKUs.'}
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
                    title={isSelectedPinned ? "Unpin SKU" : "Pin SKU to top of search"}
                    aria-label={`${isSelectedPinned ? 'Unpin' : 'Pin'} ${selectedSKU.name} (${selectedSKU.code})`}
                    aria-pressed={isSelectedPinned}
                  >
                    <Star size={15} fill={isSelectedPinned ? PIN_COLOR : 'none'} color={isSelectedPinned ? PIN_COLOR : PIN_IDLE_COLOR} />
                    <span className="pin-text">{isSelectedPinned ? 'Pinned' : 'Pin SKU'}</span>
                  </button>
                </div>
                {/* Name first, SKU code under it (Sir Catubag, 2 Oct 2026). */}
                <div className="sku-meta-row">
                  <ProductName name={selectedSKU.name} code={selectedSKU.code} className="sku-selected-name" />
                  {selectedSKU.brand && <span className="sku-brand-name">{selectedSKU.brand}</span>}
                </div>
              </div>
              <div className="sku-info-right">
                <span className={`forecast-cat-badge cat-${selectedSKU.cat}`}>Class {selectedSKU.cat}</span>
              </div>
            </div>

            {/* Demand pattern (trend and variability, D4), placed between
                the identity card and the chart so it reads as part of the
                SKU's story, not a footnote under the graph.
                Keyed on the SKU for the same reason the chart below is:
                the remount replays the card's entrance, so switching
                products visibly rebuilds the explanation instead of
                silently swapping the words inside a static box. */}
            <SkuDemandPatternPanel
              key={`pattern-${selectedSKU.code}`}
              skuId={selectedSKU.code}
              principal={principal}
            />

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
              {/* First load for this SKU: the headline stat row, the "how
                  this forecast was made" box and the 420px chart, in the
                  loaded card's own classes. */}
              {isForecastColdLoad && (
                <>
                  <LoadingStatus>Loading forecast…</LoadingStatus>
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
              {forecastError && <p className="forecast-subtitle">Error: {forecastError}</p>}

              {/* A null result (GET /forecast 404 -> getForecast null) gets a
                  message, never a blank card: every block below needs a
                  forecastResult. With the Topbar on Del Monte the picker is
                  replaced before this card exists; the Del Monte wording here
                  covers one of its category rows turning up in another
                  scope's list, since those rows can only ever 404. */}
              {!forecastLoading && !forecastError && showingThisSKU && !forecastResult && (
                <p className="forecast-subtitle">
                  {selectedSKU.principal === 'delmonte'
                    ? `${DEL_MONTE_NO_FORECAST} ${selectedSKU.name} is a product category, not a SKU.`
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
                    : `Forecasts are only produced for Class A SKUs.${selectedSKU.cat ? ` ${selectedSKU.name} (${selectedSKU.code}) is Class ${selectedSKU.cat}.` : ''}`}
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
              {!isForecastColdLoad && !forecastError && forecastResult && rangeStatus === 'none' && (
                <div className="forecast-range-error">
                  <span className="forecast-range-error-title">
                    No data for {selectedSKU.name} in the selected range
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

              {!isForecastColdLoad && !forecastError && forecastResult && (rangeStatus === 'ok' || rangeStatus === 'partial') && (
                <>
                  {/* Headline Forecast Stat Row — the number this whole page
                      exists to produce (next period's forecast) plus how it
                      compares to the last real month, so a reviewer doesn't
                      have to read it off the chart by eye. Replaces MAPE/
                      HORIZON: every served model is one-step-ahead, so
                      "accuracy of the latest run" and "how many points" (always
                      1) aren't meaningful headline numbers the way they
                      were for the old multi-point SARIMA forecast. */}
                  <div className="forecast-accuracy-row">
                    {servedModel && servedModel.kind !== 'forecast' ? (
                      /* A provisional average (under 3 sales months) or a
                         no-order row is a placeholder, not a forecast: no
                         headline number and no trend chip, so it can't be
                         read as one. The stored value is still named in the
                         small print, so what the pipeline holds isn't hidden. */
                      <div className="forecast-stat-block">
                        <span className="forecast-stat-label">Forecast status</span>
                        <span className="forecast-stat-value forecast-stat-value-notice">
                          {servedModel.kind === 'provisional'
                            ? 'Insufficient data — provisional average, not a forecast'
                            : 'No sales in the last 6 months — no order planned'}
                        </span>
                        <span className="forecast-stat-desc">{describePlaceholder()}</span>
                      </div>
                    ) : (
                    <>
                    {/* Each value is tinted to match the chart series it
                        refers to (violet = forecast line, indigo = actual
                        line, pale violet = confidence band), so the numbers
                        and the graph read as one thing. The model name sits
                        under the number: which model made it varies per SKU
                        (utils/forecastModel.js). */}
                    <div className="forecast-stat-block">
                      <span className="forecast-stat-label">
                        {derivedForecast && !derivedForecast.plotted ? 'Stored forecast' : 'Forecast'}
                        {derivedForecast ? ` for ${formatPeriod(derivedForecast.period)}` : ''}
                      </span>
                      <span className="forecast-stat-value forecast-stat-value-forecast">
                        {derivedForecast ? (
                          <>
                            <span className="forecast-stat-swatch" style={{ backgroundColor: COLORS.forecast }} aria-hidden="true" />
                            <span className="forecast-stat-number">
                              {Math.round(derivedForecast.value).toLocaleString()}
                            </span>
                            <span className="forecast-stat-unit">pieces</span>
                          </>
                        ) : (
                          '—'
                        )}
                      </span>
                      <span className="forecast-stat-desc">
                        {derivedForecast
                          ? (servedModel?.label ?? '')
                          : storedForecast
                            ? 'no sales in the selected range'
                            : selectedSKU.cat === 'A' ? 'no forecast yet' : 'Class A SKUs only'}
                      </span>
                    </div>

                    <div className="forecast-stat-divider" />

                    <div className="forecast-stat-block">
                      <span className="forecast-stat-label">
                        Vs. {latestActualPoint ? formatPeriod(latestActualPoint.period) : 'last'} actual (%)
                      </span>
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
                          ? `${latestActualPoint.quantity.toLocaleString()} pieces in ${formatPeriod(latestActualPoint.period)}`
                          : 'no sales history yet'}
                      </span>
                    </div>

                    {/* Surfaces the band the chart draws as an actual number.
                        Worth its own slot: the intervals on this data are
                        often wide, and that spread is a real caveat a reader
                        should see rather than having to eyeball off the cone. */}
                    {derivedForecast?.confidenceLower != null &&
                      derivedForecast?.confidenceUpper != null && (
                        <>
                          <div className="forecast-stat-divider" />
                          <div className="forecast-stat-block">
                            <span className="forecast-stat-label">{bandLabel} (pieces)</span>
                            <span className="forecast-stat-value forecast-stat-value-range">
                              <span className="forecast-stat-swatch forecast-stat-swatch-band" aria-hidden="true" />
                              <span className="range-low">
                                {Math.round(derivedForecast.confidenceLower).toLocaleString()}
                              </span>
                              <span className="range-dash">–</span>
                              <span className="range-high">
                                {Math.round(derivedForecast.confidenceUpper).toLocaleString()}
                              </span>
                            </span>
                            <span className="forecast-stat-desc">
                              for {formatPeriod(derivedForecast.period)}{bandLevel != null ? ', from past forecast errors' : ''}
                            </span>
                          </div>
                        </>
                      )}

                    {/* Per-SKU accuracy on the served model's own basis: WAPE
                        from its rolling one-month-ahead holdout (fraction in
                        model_params.wape). Only for the stored number — a
                        browser preview has no holdout behind it. Never
                        labelled an 80/20 score: that split was retired. */}
                    {/* Not shown for now (3 Oct 2026 analysis): the accuracy
                        percentages are being recomputed on a fairer test
                        (products that were top sellers at the time), so no
                        accuracy % is on screen until then. Flip
                        SHOW_ACCURACY_PCT to bring this block back. */}
                    {SHOW_ACCURACY_PCT && derivedForecast?.source === 'stored' && storedParams.wape != null && (
                      <>
                        <div className="forecast-stat-divider" />
                        <div className="forecast-stat-block">
                          <span className="forecast-stat-label">
                            Typical forecast miss
                            <InfoTip label="About typical forecast miss">
                              How far off this model was, on average, when it forecast past months it hadn&apos;t seen,
                              one month ahead at a time (WAPE, weighted absolute percentage error). Lower is better.
                              {storedParams.holdout_protocol ? ` Test protocol: ${storedParams.holdout_protocol}.` : ''}
                            </InfoTip>
                          </span>
                          <span className="forecast-stat-value forecast-stat-value-neutral">
                            {(storedParams.wape * 100).toFixed(1)}%
                          </span>
                          <span className="forecast-stat-desc">
                            WAPE{holdoutWindow ? `, tested on ${holdoutWindow}` : ''}, one month ahead
                            {holdoutMonths != null && holdoutSplitMonths != null && holdoutMonths < holdoutSplitMonths
                              ? ` (${holdoutMonths} of ${holdoutSplitMonths} months scored)`
                              : ''}
                          </span>
                        </div>
                      </>
                    )}
                    </>
                    )}
                  </div>

                  {/* The forecast's miss in pieces and pesos and any
                      stock-limited months, from this product's accuracy rows
                      over the page's range (productAccuracy). The accuracy
                      percentages stay held back (SHOW_ACCURACY_PCT). */}
                  {productAccuracy?.checked && (
                    <div className="forecast-pending-cards">
                      <ForecastErrorCard error={productAccuracy.error} />
                      {SHOW_ACCURACY_PCT && <AccuracyLevels accuracy={forecastResult?.accuracy} />}
                      <StockLimitedNote periods={stockLimitedPeriods} />
                    </div>
                  )}
                  {productAccuracy && !productAccuracy.checked && (
                    <p className="forecast-accuracy-none">
                      Not checked against sales in {formatPeriod(rangeStartPeriod)} – {formatPeriod(rangeEndPeriod)}:
                      no forecast for this product was scored in those months.
                    </p>
                  )}

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
                      <span className="forecast-howmade-title">How this forecast was made</span>
                      <dl className="forecast-howmade-list">
                        <div className="forecast-howmade-item">
                          <dt>Model</dt>
                          <dd>{servedModel.label ?? storedParams.method ?? '—'}</dd>
                        </div>
                        {storedParams.bin && (
                          <div className="forecast-howmade-item">
                            <dt>History</dt>
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
                            <dd>{Math.round(storedParams.ma3_value).toLocaleString()} pieces a month</dd>
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
                              </InfoTip>
                            </dt>
                            <dd className={storedForecast.mase < 1 ? '' : 'forecast-howmade-warn'}>
                              {/* Three decimals near 1, where two would round
                                  0.996 up to "1.00" beside "beats a naive
                                  forecast" (the verdict uses the stored value). */}
                              MASE {storedForecast.mase.toFixed(Math.abs(storedForecast.mase - 1) < 0.01 ? 3 : 2)} ·{' '}
                              {storedForecast.mase < 1 ? 'beats a naive forecast' : 'no better than a naive forecast'}
                              {holdoutWindow ? ` · tested on ${holdoutWindow}` : ''}
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
                              {' '}pieces, averaged
                            </dd>
                          </div>
                        )}
                      </dl>
                      {/* The guard rejected the TSB / XGBoost value and MA3
                          was served instead (router.py). The raw code stays
                          in the tooltip; the chip restates it plainly. */}
                      {storedParams.backup_fired === true && (
                        <span className="forecast-fallback-chip" title={storedParams.backup_reason || undefined}>
                          <AlertTriangle size={13} aria-hidden="true" />
                          Served MA3 as a fallback — {describeFallbackReason(storedParams.backup_reason)}
                        </span>
                      )}
                    </div>
                  )}

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
                        Use this SKU&apos;s range
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
                      <strong>Preview forecast for {formatPeriod(derivedForecast.period)}.</strong>{' '}
                      Because your range ends before {formatPeriod(skuCoverage?.end)}, this is the 3-month moving
                      average (this SKU&apos;s model) recalculated from {formatPeriod(derivedForecast.windowStart)} –{' '}
                      {formatPeriod(derivedForecast.basisPeriod)}, the same way the pipeline computes it. No
                      confidence interval or accuracy score is shown — those come from the pipeline&apos;s holdout
                      evaluation, which only exists for the stored {formatPeriod(storedForecastPeriod)} forecast.
                      Extend the range to {formatPeriod(skuCoverage?.end)} to see it.
                    </p>
                  )}

                  {/* An earlier cutoff the browser can't honestly forecast
                      from: the stored number stays the one shown (unplotted —
                      it projects from a month outside the range), and this
                      says why nothing was recomputed in its place. */}
                  {servedModel?.kind === 'forecast' && derivedForecast?.source === 'stored' && !derivedForecast.plotted && (
                    <p className="forecast-range-note">
                      <strong>Showing the stored {formatPeriod(derivedForecast.period)} forecast.</strong>{' '}
                      {servedModel.recomputable
                        ? `This SKU had fewer than ${MIN_SALES_MONTHS} months of sales up to ${formatPeriod(derivedForecast.earlierCutoff)}, so no forecast can be recomputed for a range ending there.`
                        : servedModel.fallback
                          ? `The pipeline fell back to the 3-month moving average for this SKU, and whether it would for an earlier end date can't be checked in the browser, so nothing is recomputed for a range ending ${formatPeriod(derivedForecast.earlierCutoff)}.`
                          : `This SKU's model${servedModel.label ? ` (${servedModel.label})` : ''} only runs in the forecasting pipeline, so its forecast can't be recomputed in the browser for a range ending ${formatPeriod(derivedForecast.earlierCutoff)}.`}
                      {' '}Extend the range to {formatPeriod(derivedForecast.basisPeriod)} to see it on the chart.
                    </p>
                  )}

                  {/* Chart, or its table twin. The legend sits ABOVE the
                      plot (under the stat rows), so the key is met before
                      the marks — same order as the dashboard's charts. */}
                  <div className="forecast-chart-tools">
                    <ChartViewToggle view={chartView} onChange={setChartView} label="Forecast: chart or table" />
                  </div>
                  {chartView === 'table' ? (
                    <ChartTable
                      caption="Actual sales and forecast by month, in pieces"
                      columns={[
                        {
                          key: 'period',
                          label: 'Month',
                          format: (v) => `${formatAxisPeriod(v)}${isPlaceholderPeriod(v, placeholder) ? ' (placeholder)' : ''}`,
                          align: 'left',
                        },
                        { key: 'actualV', label: 'Actual (pieces)', format: (v) => Math.round(v).toLocaleString() },
                        { key: 'forecastV', label: 'Forecast (pieces)', format: (v) => Math.round(v).toLocaleString() },
                        { key: 'ciLow', label: `${bandLabel} low (pieces)`, format: (v) => Math.round(v).toLocaleString() },
                        { key: 'ciHigh', label: `${bandLabel} high (pieces)`, format: (v) => Math.round(v).toLocaleString() },
                      ]}
                      rows={chartData.map((pt) => ({
                        period: pt.label,
                        actualV: pt.actual ?? null,
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
                    {chartData.some((pt) => isPlaceholderPeriod(pt.label, placeholder)) && (
                      <div className="legend-item">
                        <svg className="legend-swatch" viewBox="0 0 28 12" aria-hidden="true">
                          <rect x="1" y="1.5" width="26" height="9" rx="2.5" fill={CHART_COLORS.placeholder} fillOpacity="0.3" />
                        </svg>
                        <span className="legend-label">Placeholder months — not SSM&apos;s data</span>
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
                        <XAxis
                          dataKey="label"
                          axisLine={true}
                          tickLine={true}
                          tick={{ fill: '#556070', fontSize: 11 }}
                          tickFormatter={formatAxisPeriod}
                          tickMargin={10}
                          minTickGap={12}
                          height={44}
                          label={{ value: 'Month', position: 'insideBottom', offset: 0, fontSize: 10, fill: CHART_COLORS.axisLabel }}
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
                          label={{ value: 'Pieces', angle: -90, position: 'insideLeft', fontSize: 10, fill: CHART_COLORS.axisLabel }}
                        />
                        <Tooltip content={<CustomTooltip bandLabel={bandLabel} />} />

                        {/* Where actuals hand over to the forecast — the
                            divider the dashed style is read against. Only
                            while the bridge month is inside the window. */}
                        {derivedForecast?.plotted && lastPlottedActualPeriod &&
                          zoom.view.some((pt) => pt.label === lastPlottedActualPeriod) && (
                          <ReferenceLine
                            x={lastPlottedActualPeriod}
                            stroke={CHART_COLORS.axisLabel}
                            strokeDasharray="4 4"
                            label={{ value: 'Forecast starts', position: 'insideTopRight', fontSize: 10, fill: CHART_COLORS.axisLabel }}
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
                  </>
                  )}
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
