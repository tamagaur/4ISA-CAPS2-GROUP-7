import React, { useState, useMemo, useRef, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Search, Clock, X, RotateCcw, Tag, Filter, AlertTriangle } from 'lucide-react';
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { COLORS, CHART_COLORS } from '../theme/colors';
import { chartAnim } from '../theme/motion';
import { getABCClassification } from '../api/abc';
import DateFilter from './DateFilter';
import { formatMonth } from '../utils/formatDate';
import { useBrandLookup } from '../utils/useBrandLookup';
import './ABCClassification.css';

// Story #43 / Manuscript §3.5.5: "flags SKUs approaching tier boundaries."
// Tier cutoffs are 80% and 95% cumulative revenue (§3.4.1.2). The backend
// (backend/routers/abc.py) already computes boundary_flag server-side, so
// this constant is display-only (used in the legend copy).
const BOUNDARY_TOLERANCE_PP = 3;

const MONTH_TO_NUM = {
  Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
  Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12',
};

// GET /abc takes a single 'YYYY-MM' classification_period (there's one
// classification run per period, not a range) — the shared date-range
// picker's *end* month/year is what maps onto it, so "Apr-Jun 2026"
// requests the Jun 2026 classification. Omitted (undefined) falls back to
// the backend's own "latest period present" default when the picker's
// applied period isn't available yet.
const toClassificationPeriod = (month, year) =>
  month && year ? `${year}-${MONTH_TO_NUM[month]}` : undefined;

// Product names render verbatim (see SKUManagement.jsx for why the old
// pack-size split was removed).

// Helper to format SKU to 5 digits (SKU-#####)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  return sku;
};

// Class-level aggregation replaces the old per-SKU Pareto chart: with
// 600+ SKUs a per-item bar chart is illegible and not actionable.
// Per class we show two things, both from real fields only (no $ value —
// unit_price is unpopulated on Product_Dimension — and no fabricated
// risk score):
//   1. Revenue Share % (existing revPct, rolled up)
//   2. Stock Status Mix — the % of that class's SKUs sitting in each of
//      the 3 real stock_status buckets (IN STOCK / LOW / CRITICAL).
// Comparing the two surfaces classes that look fine on revenue but are
// stock-unhealthy (or vice versa).
const CLASS_ARCHETYPE = {
  A: 'High-Value, Vital Few',
  B: 'Mid-Value, Secondary',
  C: 'Low-Value, Trivial Many',
};

// Copy for the drill-down panel's footer note, one per class — swapped
// in based on whichever class the user has clicked in the chart above.
const CLASS_DRILLDOWN_NOTE = {
  A: 'Top-value SKUs sitting at LOW/CRITICAL stock are the highest-priority reorders — a stockout here has the biggest revenue impact.',
  B: 'Mid-value SKUs at LOW/CRITICAL stock are worth a proactive reorder check before they slip toward a stockout.',
  C: 'Long-tail SKUs sitting at LOW/CRITICAL stock are the lowest-priority reorders by revenue, but still worth a periodic check so they don\u2019t go fully out of stock unnoticed.',
};

// Chart colors for each stock_status; the table's status pills
// (.pill-success / -warning / -critical in index.css) use the same hues.
// NO DATA (gray) is its own status, not folded into CRITICAL — as of
// 2025-12 Inventory_Fact_Real only covers a subset of classified
// products (partial ETL load, more coverage expected), so "no record
// yet" and "confirmed zero stock" are kept visibly distinct.
//
// Fixed 2026-09: LOW and CRITICAL were swapped (LOW was red, CRITICAL was
// orange) — a real severity-inversion bug, not a style choice. Red draws
// the eye harder than orange, so at a glance LOW read as the more urgent
// state and CRITICAL read as the calmer one, backwards from reality. Now
// pulled from theme/colors.js's own tokens instead of ad-hoc hex, which
// were already documented for exactly this ("Amber: ...low stock" /
// "Red: ...critical reorders") but weren't being used.
const STOCK_STATUS_COLORS = {
  'IN STOCK': '#38a169',
  LOW: COLORS.warning,
  CRITICAL: COLORS.critical,
  'NO DATA': '#667085',
};

const ClassAggregateTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    const point = payload[0].payload;
    return (
      <div className="abc-pareto-tooltip">
        <p className="abc-pareto-tooltip-title">{point.label}</p>
        <p className="abc-pareto-tooltip-line" style={{ color: COLORS[`abc${point.cat}`] }}>
          Revenue share: {point.revenueTotal.toFixed(1)}%
        </p>
        <p className="abc-pareto-tooltip-line" style={{ color: STOCK_STATUS_COLORS['IN STOCK'] }}>
          In stock: {point.inStockPct.toFixed(0)}%
        </p>
        <p className="abc-pareto-tooltip-line" style={{ color: STOCK_STATUS_COLORS.LOW }}>
          Low: {point.lowPct.toFixed(0)}%
        </p>
        <p className="abc-pareto-tooltip-line" style={{ color: STOCK_STATUS_COLORS.CRITICAL }}>
          Critical: {point.criticalPct.toFixed(0)}%
        </p>
        <p className="abc-pareto-tooltip-line" style={{ color: STOCK_STATUS_COLORS['NO DATA'] }}>
          No data: {point.noDataPct.toFixed(0)}%
        </p>
        <p className="abc-pareto-tooltip-line" style={{ color: CHART_COLORS.axisLabel }}>
          {point.skuCount} {point.skuCount === 1 ? 'item' : 'items'} ({point.skuSharePct.toFixed(0)}% of total)
        </p>
      </div>
    );
  }
  return null;
};

const ABCClassification = () => {
  // One classification run exists per month, and GET /abc only ever read
  // the END of the shared date range — so this page used to make people
  // pick a 6-month range whose start did nothing. It now keeps its own
  // single month, seeded from the dashboard range's end month on mount,
  // and never writes back to the shared range (same local-state pattern
  // as SKUForecast.jsx's own picker).
  const dashboardRange = useOutletContext() || {};
  const [selectedMonth, setSelectedMonth] = useState(() => ({
    month: dashboardRange.endMonth,
    year: dashboardRange.endYear,
  }));
  const requestedPeriod = toClassificationPeriod(selectedMonth.month, selectedMonth.year);
  const isCustomMonth =
    selectedMonth.month !== dashboardRange.endMonth || selectedMonth.year !== dashboardRange.endYear;

  const [rawData, setRawData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [classificationPeriod, setClassificationPeriod] = useState(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('ALL');
  const [brandFilter, setBrandFilter] = useState('ALL');

  // Table pagination — the full SKU table can run 600+ rows, which is
  // slow to render and hard to scan in one scroll. PAGE_SIZE_OPTIONS
  // lets the user trade off rows-per-page vs. number of pages; default
  // matches the old "show everything" feel most closely while still
  // capping the DOM node count per render.
  const PAGE_SIZE_OPTIONS = [25, 50, 100];
  const [pageSize, setPageSize] = useState(25);
  const [currentPage, setCurrentPage] = useState(1);

  // Which class's stock-status drill-down is showing below the chart.
  // Defaults to 'A' — Category A is the highest-value tier (top 20% of
  // SKUs, ~80% of revenue) and the one a reviewer most wants to see on
  // first load, not the long-tail Class C. Still swappable via any
  // class's bar or the tab buttons.
  const [selectedClass, setSelectedClass] = useState('A');

  const [isComboboxOpen, setIsComboboxOpen] = useState(false);
  const [highlightedSKUId, setHighlightedSKUId] = useState(null);
  const comboboxRef = useRef(null);

  // Persistent Recently Searched SKUs
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_recent_abc_searches');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getABCClassification({ classification_period: requestedPeriod })
      .then((res) => {
        if (cancelled) return;
        setRawData(res.items || []);
        setClassificationPeriod(res.classification_period || null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load ABC classification data');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [requestedPeriod]);

  // GET /abc has no brand field; this was hardcoded 'Unilever' (the
  // principal) on every row. Real brand comes from the product master.
  const brandLookup = useBrandLookup();

  // Map API shape -> the row shape the rest of this page renders.
  const sourceData = useMemo(
    () =>
      rawData.map((item) => ({
        id: item.sku_id,
        sku: item.sku_id,
        product: item.product_name || 'Unknown Product',
        brand: brandLookup?.get(String(item.sku_id)) ?? null,
        cat: item.tier,
        // revenue_share / cumulative_share come from the API as 0-1 fractions
        // (see analytics/classification/abc.py); everything downstream here
        // (table cells, chart axis 0-100, tooltip) expects 0-100 percentages.
        revPct: (item.revenue_share ?? 0) * 100,
        cumulativePct: (item.cumulative_share ?? 0) * 100,
        nearBoundary: !!item.boundary_flag,
        status: item.stock_status,
      })),
    [rawData, brandLookup]
  );

  // Handle click outside combobox to close dropdown
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (comboboxRef.current && !comboboxRef.current.contains(e.target)) {
        setIsComboboxOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const catACount = sourceData.filter(d => d.cat === 'A').length;
  const catBCount = sourceData.filter(d => d.cat === 'B').length;
  const catCCount = sourceData.filter(d => d.cat === 'C').length;

  const brandsList = ['ALL', ...Array.from(new Set(sourceData.map(d => d.brand).filter(Boolean))).sort()];

  // Rank by revenue share for the Pareto chart's x-axis; cumulative_share
  // and boundary_flag already come straight from the backend.
  const dataWithCumulative = useMemo(() => {
    const sorted = [...sourceData].sort((a, b) => b.revPct - a.revPct);
    return sorted.map((item, index) => ({ ...item, rank: index + 1 }));
  }, [sourceData]);

  // Roll per-item revenue share + stock_status up to the 3 tiers.
  const buildClassAggregates = (items) => {
    const totalCount = items.length;
    return ['A', 'B', 'C'].map((cat) => {
      const catItems = items.filter((d) => d.cat === cat);
      const n = catItems.length || 1; // guard divide-by-zero for an empty tier
      const countOf = (status) => catItems.filter((d) => d.status === status).length;
      return {
        cat,
        label: `Class ${cat}`,
        skuCount: catItems.length,
        skuSharePct: totalCount > 0 ? (catItems.length / totalCount) * 100 : 0,
        revenueTotal: catItems.reduce((sum, d) => sum + (d.revPct || 0), 0),
        inStockPct: (countOf('IN STOCK') / n) * 100,
        lowPct: (countOf('LOW') / n) * 100,
        criticalPct: (countOf('CRITICAL') / n) * 100,
        // Inventory_Fact_Real is a partial load (backend/routers/abc.py) —
        // most products currently have no stock record at all yet. Kept
        // as its own bucket rather than folded into CRITICAL, so the
        // chart doesn't misreport "no data" as "confirmed out of stock".
        noDataPct: (countOf('NO DATA') / n) * 100,
      };
    });
  };

  const buildStockBreakdown = (items) => {
    const total = items.length || 1;
    return ['CRITICAL', 'LOW', 'IN STOCK', 'NO DATA'].map((status) => {
      const count = items.filter((d) => d.status === status).length;
      return { status, count, pct: (count / total) * 100 };
    });
  };

  const classAggregates = useMemo(
    () => buildClassAggregates(dataWithCumulative),
    [dataWithCumulative]
  );
  // Drill-down now follows whichever class is selected (click a bar, or
  // a tab) instead of always being Class C.
  const selectedClassStockBreakdown = useMemo(
    () => buildStockBreakdown(dataWithCumulative.filter((d) => d.cat === selectedClass)),
    [dataWithCumulative, selectedClass]
  );

  const filteredData = useMemo(() => {
    return dataWithCumulative.filter(item => {
      const matchesSearch = searchQuery === '' ||
        item.sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (item.brand || '').toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = categoryFilter === 'ALL' || item.cat === categoryFilter;
      const matchesBrand = brandFilter === 'ALL' || item.brand === brandFilter;
      return matchesSearch && matchesCat && matchesBrand;
    });
  }, [dataWithCumulative, searchQuery, categoryFilter, brandFilter]);

  // Whenever the filtered set changes shape (new search, new filter, or
  // the page size itself), snap back to page 1 — staying on e.g. page 4
  // after a filter shrinks the result set would otherwise show a blank
  // page or an out-of-range slice.
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, categoryFilter, brandFilter, pageSize]);

  const totalPages = Math.max(1, Math.ceil(filteredData.length / pageSize));

  // Clamp defensively (e.g. if filteredData shrinks between renders
  // before the reset effect above has run) so slice() below never goes
  // out of range.
  const safeCurrentPage = Math.min(currentPage, totalPages);

  const paginatedData = useMemo(() => {
    const start = (safeCurrentPage - 1) * pageSize;
    return filteredData.slice(start, start + pageSize);
  }, [filteredData, safeCurrentPage, pageSize]);

  const boundaryCount = useMemo(
    () => dataWithCumulative.filter(item => item.nearBoundary).length,
    [dataWithCumulative]
  );

  const handleSelectSuggestion = (item) => {
    setSearchQuery(item.sku);
    setIsComboboxOpen(false);

    // Save to recent searches
    setRecentSearches(prev => {
      const filtered = prev.filter(s => s.id !== item.id);
      const updated = [item, ...filtered].slice(0, 5);
      localStorage.setItem('san2_recent_abc_searches', JSON.stringify(updated));
      return updated;
    });

    // Scroll & Highlight row
    setHighlightedSKUId(item.id);
    setTimeout(() => {
      const el = document.getElementById(`abc-row-${item.id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 80);

    setTimeout(() => {
      setHighlightedSKUId(null);
    }, 2000);
  };

  const hasActiveFilters = searchQuery !== '' || categoryFilter !== 'ALL' || brandFilter !== 'ALL';

  const handleClearFilters = () => {
    setSearchQuery('');
    setCategoryFilter('ALL');
    setBrandFilter('ALL');
  };

  const getStatusClass = (status) => {
    switch (status) {
      case 'IN STOCK': return 'pill pill-success';
      case 'LOW': return 'pill pill-warning';
      case 'CRITICAL': return 'pill pill-critical';
      case 'NO DATA': return 'pill pill-neutral';
      default: return 'pill pill-neutral';
    }
  };

  const getCatBadgeClass = (cat) => {
    switch (cat) {
      case 'A': return 'abc-cat-badge abc-cat-a';
      case 'B': return 'abc-cat-badge abc-cat-b';
      case 'C': return 'abc-cat-badge abc-cat-c';
      default: return 'abc-cat-badge';
    }
  };

  // Rendered in every state (loading, error, loaded) rather than only on
  // success — the date picker lives in this header, so blanking the page
  // while refetching removed the control the user had just changed. Same
  // fix as Dashboard.jsx's `header`.
  const header = (
    <div className="abc-page-header">
      <div className="abc-page-title-row">
        <h2 className="abc-page-title">ABC <span className="page-title-accent">Classification</span></h2>
        <DateFilter
          singleMonth
          localValue={{
            startMonth: selectedMonth.month, startYear: selectedMonth.year,
            endMonth: selectedMonth.month, endYear: selectedMonth.year,
          }}
          onLocalChange={(v) => setSelectedMonth({ month: v.endMonth, year: v.endYear })}
          onReset={isCustomMonth
            ? () => setSelectedMonth({ month: dashboardRange.endMonth, year: dashboardRange.endYear })
            : undefined}
        />
      </div>
      <p className="abc-page-subtitle">
        Products ranked by sales value. Category A = the top 20% of SKUs driving roughly 80% of revenue.
        {classificationPeriod && <> Period: {formatMonth(classificationPeriod)}.</>}
        <span className="abc-boundary-legend"> <AlertTriangle size={12} className="abc-boundary-legend-icon" /> flags a SKU within {BOUNDARY_TOLERANCE_PP}pp of a tier cutoff — likely to reclassify next review cycle.</span>
      </p>
    </div>
  );

  if (loading) {
    return (
      <div className="abc-page">
        <div className="abc-content">
          {header}
          <p className="abc-page-subtitle" role="status">Loading ABC classification data…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="abc-page">
        <div className="abc-content">
          {header}
          <p className="abc-page-subtitle" role="alert">Failed to load ABC classification data: {error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="abc-page">
      <div className="abc-content">
        {/* Page Header */}
        {header}

        {/* Summary Cards */}
        <div className="abc-summary-grid">
          <div className="abc-summary-card abc-card-a">
            <span className="abc-card-label">CATEGORY A</span>
            <span className="abc-card-value">{catACount}</span>
            <span className="abc-card-desc">Top 20% · 80% of revenue</span>
          </div>
          <div className="abc-summary-card abc-card-b">
            <span className="abc-card-label">CATEGORY B</span>
            <span className="abc-card-value">{catBCount}</span>
            <span className="abc-card-desc">Middle tier · 15% of revenue</span>
          </div>
          <div className="abc-summary-card abc-card-c">
            <span className="abc-card-label">CATEGORY C</span>
            <span className="abc-card-value">{catCCount}</span>
            <span className="abc-card-desc">Long tail · 5% of revenue</span>
          </div>
          <div className="abc-summary-card abc-card-total">
            <span className="abc-card-label">TOTAL SKUS</span>
            <span className="abc-card-value">{sourceData.length}</span>
            {boundaryCount > 0 && (
              <span className="abc-card-desc abc-card-desc-warning">
                <AlertTriangle size={11} /> {boundaryCount} near a tier boundary
              </span>
            )}
          </div>
        </div>

        {/* Class Aggregation Chart + interactive drill-down — replaces
            the per-SKU Pareto chart, which wasn't readable/actionable at
            600+ SKUs. Revenue share vs. stock-status mix per class (both
            real fields, no fabricated $ value or risk score). Clicking
            any bar for a class (or its tab below the chart) swaps the
            drill-down table on the right to that class's real
            stock_status counts — it's no longer locked to Class C. */}
        {[{ label: null, classAggregates, selectedClassStockBreakdown }].map((panel) => (
          <div className="abc-analysis-row" key="single">
            <div className="abc-pareto-container abc-analysis-chart">
              <div className="abc-pareto-header">
                <h3 className="abc-pareto-title">
                  {panel.label ? `${panel.label} — Stock Status Mix, by Class` : 'Stock Status Mix, by Class'}
                </h3>
                <div className="abc-pareto-legend">
                  <div className="abc-pareto-legend-item">
                    <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS['IN STOCK'] }} />
                    <span>In stock</span>
                  </div>
                  <div className="abc-pareto-legend-item">
                    <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS.LOW }} />
                    <span>Low</span>
                  </div>
                  <div className="abc-pareto-legend-item">
                    <span className="abc-pareto-legend-swatch abc-pareto-legend-swatch--critical" />
                    <span>Critical</span>
                  </div>
                  <div className="abc-pareto-legend-item">
                    <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS['NO DATA'] }} />
                    <span>No data</span>
                  </div>
                </div>
              </div>
              <div className="abc-pareto-chart-wrapper">
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={panel.classAggregates} margin={{ top: 10, right: 20, left: 0, bottom: 0 }} barCategoryGap="30%" barGap={4}>
                    {/* Colorblind safety: CRITICAL and IN STOCK sit right next
                        to each other in this stack, and red/green is the one
                        hue pair ~8% of men (red-green deficiency) can't
                        reliably tell apart. A hatch pattern gives CRITICAL a
                        texture cue that doesn't depend on hue at all, and the
                        white segment borders below mean no boundary in the
                        stack relies on color contrast alone. */}
                    <defs>
                      <pattern id="criticalHatch" patternUnits="userSpaceOnUse" width="7" height="7" patternTransform="rotate(45)">
                        <rect width="7" height="7" fill={STOCK_STATUS_COLORS.CRITICAL} />
                        <line x1="0" y1="0" x2="0" y2="7" stroke="rgba(255,255,255,0.6)" strokeWidth="3" />
                      </pattern>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                    <XAxis
                      dataKey="label"
                      axisLine={true}
                      tickLine={false}
                      tick={{ fill: CHART_COLORS.axisLabel, fontSize: 12, fontWeight: 600 }}
                    />
                    <YAxis
                      domain={[0, 100]}
                      ticks={[0, 20, 40, 60, 80, 100]}
                      tickFormatter={(v) => `${v}%`}
                      axisLine={true}
                      tickLine={true}
                      tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                    />
                    <Tooltip content={<ClassAggregateTooltip />} cursor={{ fill: '#f7fafc' }} />
                    {/* Was a two-bar-per-class combo: this stock-status stack
                        next to a separate solid "revenue share" bar on the
                        SAME 0-100% axis. Dropped the revenue-share bar
                        (2026-09) — it mixed two different kinds of
                        percentage on one axis (per-class stock composition
                        vs. share-of-portfolio-revenue), which invited a
                        false comparison, and it duplicated what the 4 KPI
                        cards above already say ("Top 20% · 80% of
                        revenue"). This chart now has one job: stock-status
                        composition, stacked to 100%. NO DATA sits at the
                        base since it's usually the largest segment right
                        now (partial inventory load) — putting it first
                        keeps the rounded top corner on whichever real
                        status segment is on top. Each stacked segment is
                        clickable and outlines the whole column for
                        whichever class is selected. */}
                    <Bar dataKey="noDataPct" stackId="stockMix" fill={STOCK_STATUS_COLORS['NO DATA']} barSize={54} {...chartAnim(0)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                      {panel.classAggregates.map((entry) => (
                        <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={entry.cat === selectedClass ? 2 : 1} />
                      ))}
                    </Bar>
                    <Bar dataKey="criticalPct" stackId="stockMix" fill="url(#criticalHatch)" barSize={54} {...chartAnim(1)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                      {panel.classAggregates.map((entry) => (
                        <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={entry.cat === selectedClass ? 2 : 1} />
                      ))}
                    </Bar>
                    <Bar dataKey="lowPct" stackId="stockMix" fill={STOCK_STATUS_COLORS.LOW} barSize={54} {...chartAnim(2)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                      {panel.classAggregates.map((entry) => (
                        <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={entry.cat === selectedClass ? 2 : 1} />
                      ))}
                    </Bar>
                    <Bar dataKey="inStockPct" stackId="stockMix" fill={STOCK_STATUS_COLORS['IN STOCK']} radius={[6, 6, 0, 0]} barSize={54} {...chartAnim(3)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                      {panel.classAggregates.map((entry) => (
                        <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={entry.cat === selectedClass ? 2 : 1} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="abc-drilldown-hint">Click a class's bar above to drill into its stock status.</p>
              <div className="abc-class-summary-row">
                {panel.classAggregates.map((entry) => (
                  <div key={entry.cat} className="abc-class-summary-item">
                    <span className="abc-class-summary-headline">
                      ~{entry.skuSharePct.toFixed(0)}% SKU Count · ~{entry.revenueTotal.toFixed(0)}% Revenue
                    </span>
                    <span className="abc-class-summary-archetype">{CLASS_ARCHETYPE[entry.cat]}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="abc-pareto-container abc-analysis-drilldown">
              <div className="abc-pareto-header">
                <h3 className="abc-pareto-title">
                  {panel.label ? `${panel.label} — Drill-down · Class ${selectedClass} Stock Status` : `Drill-down · Class ${selectedClass} Stock Status`}
                </h3>
              </div>
              {/* Tab buttons — same class-switching as clicking the chart,
                  but explicit/tappable for touch and keyboard users. */}
              <div className="abc-drilldown-tabs" role="tablist" aria-label="Select ABC class to drill into">
                {['A', 'B', 'C'].map((cat) => (
                  <button
                    key={cat}
                    role="tab"
                    aria-selected={selectedClass === cat}
                    className={`abc-drilldown-tab abc-drilldown-tab-${cat.toLowerCase()} ${selectedClass === cat ? 'active' : ''}`}
                    onClick={() => setSelectedClass(cat)}
                  >
                    Class {cat}
                  </button>
                ))}
              </div>
              <table className="abc-drilldown-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th className="table-num">SKU Count</th>
                    <th className="table-num">% of Class {selectedClass}</th>
                  </tr>
                </thead>
                <tbody>
                  {panel.selectedClassStockBreakdown.map((row) => (
                    <tr key={row.status}>
                      <td>
                        <span className="abc-drilldown-dot" style={{ backgroundColor: STOCK_STATUS_COLORS[row.status] }} />
                        {row.status}
                      </td>
                      <td className="table-num">{row.count}</td>
                      <td className="table-num">{row.pct.toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="abc-page-grain-note">
                {CLASS_DRILLDOWN_NOTE[selectedClass]}
              </p>
            </div>
          </div>
        ))}

        {/* Searchable Combobox & Filters Bar */}
        <div className="abc-filters-row">
          {/* Search Combobox */}
          <div className="abc-combobox-container" ref={comboboxRef}>
            <div className="abc-search-wrapper">
              <Search className="abc-search-icon" size={16} />
              <input
                type="text"
                placeholder="Search by product name, SKU, or brand..."
                value={searchQuery}
                onFocus={() => setIsComboboxOpen(true)}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setIsComboboxOpen(true);
                }}
                className="abc-search-input"
              />
              {searchQuery && (
                <button className="abc-input-clear-btn" onClick={() => setSearchQuery('')} title="Clear search">
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Combobox Dropdown Panel */}
            {isComboboxOpen && (
              <div className="abc-combobox-dropdown">
                {searchQuery.trim() !== '' ? (
                  /* Live Suggestions */
                  <div className="abc-combobox-section">
                    <div className="abc-section-header">
                      <span>SUGGESTIONS ({filteredData.length})</span>
                    </div>
                    {filteredData.length > 0 ? (
                      filteredData.map((item) => (
                        <div
                          key={item.id}
                          className="abc-suggestion-row"
                          onClick={() => handleSelectSuggestion(item)}
                        >
                          <div className="abc-row-left">
                            <span className="abc-row-sku">{formatSKU(item.sku)}</span>
                            <span className="abc-row-brand">{item.brand}</span>
                          </div>
                          <div className="abc-row-middle">
                            <span className="abc-row-product">{item.product}</span>
                            <span className="abc-row-rev">{item.revPct}% of revenue</span>
                          </div>
                          <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                        </div>
                      ))
                    ) : (
                      <div className="abc-no-suggestions">No matching products found.</div>
                    )}
                  </div>
                ) : (
                  /* Quick Access Panel */
                  <div className="abc-combobox-default">
                    {recentSearches.length > 0 && (
                      <div className="abc-combobox-section">
                        <div className="abc-section-header">
                          <Clock size={12} />
                          <span>RECENTLY SEARCHED</span>
                        </div>
                        {recentSearches.map((item) => (
                          <div
                            key={item.id}
                            className="abc-suggestion-row"
                            onClick={() => handleSelectSuggestion(item)}
                          >
                            <div className="abc-row-left">
                              <span className="abc-row-sku">{formatSKU(item.sku)}</span>
                              <span className="abc-row-brand">{item.brand}</span>
                            </div>
                            <div className="abc-row-middle">
                              <span className="abc-row-product">{item.product}</span>
                            </div>
                            <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="abc-combobox-section">
                      <div className="abc-section-header">
                        <span>TOP ABC CLASSIFIED SKUS</span>
                      </div>
                      {filteredData.slice(0, 5).map((item) => (
                        <div
                          key={item.id}
                          className="abc-suggestion-row"
                          onClick={() => handleSelectSuggestion(item)}
                        >
                          <div className="abc-row-left">
                            <span className="abc-row-sku">{formatSKU(item.sku)}</span>
                            <span className="abc-row-brand">{item.brand}</span>
                          </div>
                          <div className="abc-row-middle">
                            <span className="abc-row-product">{item.product}</span>
                            <span className="abc-row-rev">{item.revPct}% revenue</span>
                          </div>
                          <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Filter Controls Row */}
          <div className="abc-filter-controls">
            <div className="abc-filter-select-wrapper">
              <span className="abc-filter-icon-label"><Tag size={12} /> Brand:</span>
              <select
                value={brandFilter}
                onChange={(e) => setBrandFilter(e.target.value)}
              >
                {brandsList.map(b => (
                  <option key={b} value={b}>{b === 'ALL' ? 'All Brands' : b}</option>
                ))}
              </select>
            </div>

            <div className="abc-cat-toggle-group">
              {['ALL', 'A', 'B', 'C'].map(cat => (
                <button
                  key={cat}
                  className={`abc-cat-toggle-btn ${categoryFilter === cat ? 'active' : ''}`}
                  onClick={() => setCategoryFilter(cat)}
                >
                  {cat === 'ALL' ? 'ALL' : `CAT ${cat}`}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Active Filter Chips Bar */}
        {hasActiveFilters && (
          <div className="abc-active-chips-row">
            <span className="abc-chips-label">
              <Filter size={12} /> Active Filters:
            </span>

            {searchQuery && (
              <span className="abc-active-chip">
                Search: "{searchQuery}"
                <button className="abc-chip-remove" onClick={() => setSearchQuery('')}>
                  <X size={12} />
                </button>
              </span>
            )}

            {brandFilter !== 'ALL' && (
              <span className="abc-active-chip">
                Brand: {brandFilter}
                <button className="abc-chip-remove" onClick={() => setBrandFilter('ALL')}>
                  <X size={12} />
                </button>
              </span>
            )}

            {categoryFilter !== 'ALL' && (
              <span className="abc-active-chip">
                Category: CAT {categoryFilter}
                <button className="abc-chip-remove" onClick={() => setCategoryFilter('ALL')}>
                  <X size={12} />
                </button>
              </span>
            )}

            <button
              className="abc-clear-all-chips-btn"
              onClick={handleClearFilters}
              title="Reset all filters"
            >
              <RotateCcw size={12} />
              Clear all filters
            </button>
          </div>
        )}

        {/* Table */}
        <div className="data-table-card">
          <table className="data-table abc-table">
            <thead>
              <tr>
                <th className="table-num col-fit">#</th>
                <th className="col-fit">SKU</th>
                <th>Product</th>
                <th className="col-fit">Brand</th>
                <th className="table-center col-fit">Cat</th>
                <th className="table-num col-fit">Rev %</th>
                <th className="col-fit">Stock status</th>
              </tr>
            </thead>
            <tbody>
              {paginatedData.map((item, index) => (
                <tr
                  key={item.id}
                  id={`abc-row-${item.id}`}
                  className={highlightedSKUId === item.id ? 'highlighted-row-flash' : ''}
                >
                  <td className="cell-rownum table-num">{(safeCurrentPage - 1) * pageSize + index + 1}</td>
                  <td className="cell-code">{formatSKU(item.sku)}</td>
                  <td className="cell-product">{item.product}</td>
                  <td className={item.brand ? 'cell-muted' : 'cell-empty'}>{item.brand || '—'}</td>
                  <td className="table-center">
                    {/* The warning icon always has a reserved slot, so badges
                        stay in one straight column whether or not a row is
                        near a tier boundary. */}
                    <span className="abc-cat-cell-inner">
                      <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                      <span className="abc-boundary-slot">
                        {item.nearBoundary && (
                          <AlertTriangle
                            size={13}
                            className="abc-boundary-icon"
                            aria-label="Near a tier boundary"
                          >
                            <title>{`Cumulative revenue ${item.cumulativePct.toFixed(1)}% — within ${BOUNDARY_TOLERANCE_PP}pp of a tier cutoff`}</title>
                          </AlertTriangle>
                        )}
                      </span>
                    </span>
                  </td>
                  <td className="table-num cell-strong">{item.revPct.toFixed(1)}%</td>
                  <td><span className={getStatusClass(item.status)}>{item.status}</span></td>
                </tr>
              ))}
              {filteredData.length === 0 && (
                <tr className="table-empty-row">
                  <td colSpan="7">No data for this selection.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination — table can run 600+ rows; only PAGE_SIZE_OPTIONS
            rows render at once, so the DOM/scroll stays manageable. */}
        {filteredData.length > 0 && (
          <div className="abc-pagination-row">
            <span className="abc-pagination-info">
              Showing {(safeCurrentPage - 1) * pageSize + 1}–{Math.min(safeCurrentPage * pageSize, filteredData.length)} of {filteredData.length}
            </span>

            <div className="abc-pagination-controls">
              <button
                className="abc-pagination-btn"
                onClick={() => setCurrentPage(1)}
                disabled={safeCurrentPage === 1}
                aria-label="First page"
                title="First page"
              >
                «
              </button>
              <button
                className="abc-pagination-btn"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={safeCurrentPage === 1}
                aria-label="Previous page"
              >
                Prev
              </button>
              <span className="abc-pagination-page-label">
                Page {safeCurrentPage} of {totalPages}
              </span>
              <button
                className="abc-pagination-btn"
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={safeCurrentPage === totalPages}
                aria-label="Next page"
              >
                Next
              </button>
              <button
                className="abc-pagination-btn"
                onClick={() => setCurrentPage(totalPages)}
                disabled={safeCurrentPage === totalPages}
                aria-label="Last page"
                title="Last page"
              >
                »
              </button>
            </div>

            <div className="abc-pagination-size">
              <span>Rows per page:</span>
              <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
                {PAGE_SIZE_OPTIONS.map((size) => (
                  <option key={size} value={size}>{size}</option>
                ))}
              </select>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ABCClassification;
