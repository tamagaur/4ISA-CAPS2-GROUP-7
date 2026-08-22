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
import { getABCClassification } from '../api/abc';
import './ABCClassification.css';

// Story #43 / Manuscript §3.5.5: "flags SKUs approaching tier boundaries."
// Tier cutoffs are 80% and 95% cumulative revenue (§3.4.1.2). The backend
// (backend/routers/abc.py) already computes boundary_flag server-side, so
// this constant is display-only (used in the legend copy).
const BOUNDARY_TOLERANCE_PP = 3;

const PRINCIPAL_BRAND = { unilever: 'Unilever', delmonte: 'Del Monte' };
// Components branch on this, never on the principal name.
const GRAIN_BY_PRINCIPAL = { unilever: 'sku', delmonte: 'category', all: 'mixed' };

// Helper to extract product name and weight (supports decimals like 1.5L, 2.5kg)
const parseProductAndWeight = (product) => {
  if (!product) return { name: '', weight: '' };
  const weightRegex = /\b(\d+(?:\.\d+)?\s*(?:g|ml|l|kg|L|KG|ML|G))\b/;
  const match = product.match(weightRegex);
  if (match) {
    const weight = `(${match[1]})`;
    let name = product.replace(weightRegex, '').replace(/\s+/g, ' ').trim();
    name = name.replace(/\(\s*\)/g, '').trim();
    return { name, weight };
  }
  return { name: product, weight: '' };
};

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

// Mirrors the colors already used for stock_status badges elsewhere on
// this page (.abc-in-stock / .abc-low / .abc-critical in the CSS) so the
// same status always reads as the same color across the whole view.
// NO DATA (gray) is its own status, not folded into CRITICAL — as of
// 2025-12 Inventory_Fact_Real only covers a subset of classified
// products (partial ETL load, more coverage expected), so "no record
// yet" and "confirmed zero stock" are kept visibly distinct.
const STOCK_STATUS_COLORS = {
  'IN STOCK': '#38a169',
  LOW: '#e53e3e',
  CRITICAL: '#dd6b20',
  'NO DATA': '#a0aec0',
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
  const { principal } = useOutletContext() || { principal: 'all' };
  const grain = GRAIN_BY_PRINCIPAL[principal] ?? 'mixed';

  const [rawData, setRawData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [classificationPeriod, setClassificationPeriod] = useState(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('ALL');
  const [brandFilter, setBrandFilter] = useState('ALL');

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
    getABCClassification({ principal })
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
  }, [principal]);

  // Map API shape -> the row shape the rest of this page renders.
  const sourceData = useMemo(
    () =>
      rawData.map((item) => ({
        id: item.sku_id,
        sku: item.sku_id,
        product: item.product_name || 'Unknown Product',
        brand: PRINCIPAL_BRAND[item.principal] || item.principal,
        principal: item.principal,
        cat: item.tier,
        // revenue_share / cumulative_share come from the API as 0-1 fractions
        // (see analytics/classification/abc.py); everything downstream here
        // (table cells, chart axis 0-100, tooltip) expects 0-100 percentages.
        revPct: (item.revenue_share ?? 0) * 100,
        cumulativePct: (item.cumulative_share ?? 0) * 100,
        nearBoundary: !!item.boundary_flag,
        status: item.stock_status,
      })),
    [rawData]
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

  const brandsList = ['ALL', ...Array.from(new Set(sourceData.map(d => d.brand)))];

  // Rank by revenue share for the Pareto chart's x-axis; cumulative_share
  // and boundary_flag already come straight from the backend.
  const dataWithCumulative = useMemo(() => {
    const sorted = [...sourceData].sort((a, b) => b.revPct - a.revPct);
    return sorted.map((item, index) => ({ ...item, rank: index + 1 }));
  }, [sourceData]);

  // Roll per-item revenue share + stock_status up to the 3 tiers. Pulled
  // out as a plain function (not a hook) because it needs to run once for
  // "all items" (single-principal view) and once per principal (mixed
  // "All" view) — see isMixedPrincipal below for why revenue_share can't
  // just be summed across principals directly.
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

  // orchestrate_abc.py runs ABC classification ONCE PER PRINCIPAL — each
  // principal's revenue_share sums to 100% within itself only (Unilever
  // SKU revenue and Del Monte category revenue are different, non-
  // comparable magnitudes). Loading "All" principals returns both sets
  // of rows together with no filter, so simply summing revenue_share
  // across all of them adds two different 100% baselines together
  // (Class A could read ~160%, not a bug in the math — just an invalid
  // combination). isMixedPrincipal detects that case so the revenue
  // chart is never built by summing across principals.
  const presentPrincipals = useMemo(
    () => Array.from(new Set(dataWithCumulative.map((d) => d.principal).filter(Boolean))),
    [dataWithCumulative]
  );
  const isMixedPrincipal = presentPrincipals.length > 1;

  // Single-principal view (or the whole dataset when only one principal
  // is present/selected): one set of aggregates, same as before.
  const classAggregates = useMemo(
    () => buildClassAggregates(dataWithCumulative),
    [dataWithCumulative]
  );
  const classCStockBreakdown = useMemo(
    () => buildStockBreakdown(dataWithCumulative.filter((d) => d.cat === 'C')),
    [dataWithCumulative]
  );

  // Mixed view: one full aggregate set PER principal, each computed only
  // from that principal's own rows — revenue and stock mix both stay
  // within one classification run's own 100% baseline.
  const perPrincipalPanels = useMemo(() => {
    if (!isMixedPrincipal) return [];
    return presentPrincipals.map((p) => {
      const items = dataWithCumulative.filter((d) => d.principal === p);
      return {
        principal: p,
        label: PRINCIPAL_BRAND[p] || p,
        classAggregates: buildClassAggregates(items),
        classCStockBreakdown: buildStockBreakdown(items.filter((d) => d.cat === 'C')),
      };
    });
  }, [isMixedPrincipal, presentPrincipals, dataWithCumulative]);

  // Cross-principal comparison chart: one bar per principal per tier,
  // never summed — each principal's own revenue % stays on its own
  // 0-100 scale, just placed side by side for comparison.
  const tierComparisonData = useMemo(() => {
    if (!isMixedPrincipal) return [];
    return ['A', 'B', 'C'].map((cat) => {
      const row = { cat, label: `Class ${cat}` };
      presentPrincipals.forEach((p) => {
        const items = dataWithCumulative.filter((d) => d.principal === p && d.cat === cat);
        row[p] = items.reduce((sum, d) => sum + (d.revPct || 0), 0);
      });
      return row;
    });
  }, [isMixedPrincipal, presentPrincipals, dataWithCumulative]);

  const PRINCIPAL_CHART_COLOR = { unilever: COLORS.abcA, delmonte: COLORS.dispatched };

  const filteredData = useMemo(() => {
    return dataWithCumulative.filter(item => {
      const matchesSearch = searchQuery === '' ||
        item.sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.brand.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = categoryFilter === 'ALL' || item.cat === categoryFilter;
      const matchesBrand = brandFilter === 'ALL' || item.brand === brandFilter;
      return matchesSearch && matchesCat && matchesBrand;
    });
  }, [dataWithCumulative, searchQuery, categoryFilter, brandFilter]);

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
      case 'IN STOCK': return 'abc-status abc-in-stock';
      case 'LOW': return 'abc-status abc-low';
      case 'CRITICAL': return 'abc-status abc-critical';
      case 'NO DATA': return 'abc-status abc-no-data';
      default: return 'abc-status';
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

  if (loading) {
    return (
      <div className="abc-page">
        <div className="abc-content">
          <p className="abc-page-subtitle">Loading ABC classification data…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="abc-page">
        <div className="abc-content">
          <p className="abc-page-subtitle">Failed to load ABC classification data: {error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="abc-page">
      <div className="abc-content">
        {/* Page Header */}
        <div className="abc-page-header">
          <h2 className="abc-page-title">ABC Classification</h2>
          <p className="abc-page-subtitle">
            Products ranked by sales value. Category A = the top 20% of SKUs driving roughly 80% of revenue.
            {classificationPeriod && <> Period: {classificationPeriod}.</>}
            <span className="abc-boundary-legend"> <AlertTriangle size={12} className="abc-boundary-legend-icon" /> flags a SKU within {BOUNDARY_TOLERANCE_PP}pp of a tier cutoff — likely to reclassify next review cycle.</span>
          </p>
        </div>

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
            <span className="abc-card-label">{grain === 'category' ? 'TOTAL CATEGORIES' : 'TOTAL SKUS'}</span>
            <span className="abc-card-value">{sourceData.length}</span>
            {boundaryCount > 0 && (
              <span className="abc-card-desc abc-card-desc-warning">
                <AlertTriangle size={11} /> {boundaryCount} near a tier boundary
              </span>
            )}
          </div>
        </div>

        {(grain === 'category' || grain === 'mixed') && (
          <p className="abc-page-grain-note">
            Del Monte is analysed at category level — no SKU-level data is available from this principal
          </p>
        )}

        {/* Revenue Concentration by Tier, by Principal — cross-principal
            comparison chart, shown only when "All" is selected. Never
            sums revenue_share across principals (see isMixedPrincipal
            above for why that's invalid) — one bar per principal per
            tier, each on its own 0-100% scale, placed side by side. */}
        {isMixedPrincipal && (
          <div className="abc-pareto-container">
            <div className="abc-pareto-header">
              <h3 className="abc-pareto-title">Revenue Concentration by Tier, by Principal</h3>
              <div className="abc-pareto-legend">
                {presentPrincipals.map((p) => (
                  <div className="abc-pareto-legend-item" key={p}>
                    <span className="abc-pareto-legend-swatch" style={{ backgroundColor: PRINCIPAL_CHART_COLOR[p] || CHART_COLORS.axisLabel }} />
                    <span>{PRINCIPAL_BRAND[p] || p}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="abc-pareto-chart-wrapper">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={tierComparisonData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }} barCategoryGap="30%" barGap={4}>
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
                  <Tooltip
                    formatter={(value, name) => [`${value.toFixed(1)}%`, PRINCIPAL_BRAND[name] || name]}
                    cursor={{ fill: '#f7fafc' }}
                  />
                  {presentPrincipals.map((p) => (
                    <Bar
                      key={p}
                      dataKey={p}
                      name={p}
                      fill={PRINCIPAL_CHART_COLOR[p] || CHART_COLORS.axisLabel}
                      radius={[6, 6, 0, 0]}
                      barSize={44}
                      isAnimationActive={false}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* Class Aggregation Chart(s) + Class C drill-down — replaces the
            per-SKU Pareto chart, which wasn't readable/actionable at 600+
            SKUs. Each panel: revenue share vs. stock-status mix per class
            (both real fields, no fabricated $ value or risk score), plus
            real stock_status counts for Class C only. In mixed mode this
            renders once per principal (see perPrincipalPanels above) so
            revenue/stock numbers never cross a classification-run
            boundary; otherwise it renders once for the whole dataset. */}
        {(isMixedPrincipal ? perPrincipalPanels : [{ principal: null, label: null, classAggregates, classCStockBreakdown }]).map((panel) => (
          <div className="abc-analysis-row" key={panel.principal || 'single'}>
            <div className="abc-pareto-container abc-analysis-chart">
              <div className="abc-pareto-header">
                <h3 className="abc-pareto-title">
                  {panel.label ? `${panel.label} — Revenue Share vs. Stock Status Mix, by Class` : 'Revenue Share vs. Stock Status Mix, by Class'}
                </h3>
                <div className="abc-pareto-legend">
                  <div className="abc-pareto-legend-item">
                    <span className="abc-pareto-legend-swatch" style={{ backgroundColor: COLORS.abcA }} />
                    <span>Revenue share</span>
                  </div>
                  <div className="abc-pareto-legend-item">
                    <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS['IN STOCK'] }} />
                    <span>In stock</span>
                  </div>
                  <div className="abc-pareto-legend-item">
                    <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS.LOW }} />
                    <span>Low</span>
                  </div>
                  <div className="abc-pareto-legend-item">
                    <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS.CRITICAL }} />
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
                    {/* Bar 1 of the pair: revenue share, one solid bar per class */}
                    <Bar dataKey="revenueTotal" radius={[6, 6, 0, 0]} barSize={54} isAnimationActive={false}>
                      {panel.classAggregates.map((entry) => (
                        <Cell key={entry.cat} fill={COLORS[`abc${entry.cat}`]} />
                      ))}
                    </Bar>
                    {/* Bar 2 of the pair: stock-status mix, stacked to 100%.
                        NO DATA sits at the base since it's usually the
                        largest segment right now (partial inventory load)
                        — putting it first keeps the rounded top corner on
                        whichever real status segment is on top. */}
                    <Bar dataKey="noDataPct" stackId="stockMix" fill={STOCK_STATUS_COLORS['NO DATA']} barSize={54} isAnimationActive={false} />
                    <Bar dataKey="criticalPct" stackId="stockMix" fill={STOCK_STATUS_COLORS.CRITICAL} barSize={54} isAnimationActive={false} />
                    <Bar dataKey="lowPct" stackId="stockMix" fill={STOCK_STATUS_COLORS.LOW} barSize={54} isAnimationActive={false} />
                    <Bar dataKey="inStockPct" stackId="stockMix" fill={STOCK_STATUS_COLORS['IN STOCK']} radius={[6, 6, 0, 0]} barSize={54} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="abc-class-summary-row">
                {panel.classAggregates.map((entry) => (
                  <div key={entry.cat} className="abc-class-summary-item">
                    <span className="abc-class-summary-headline">
                      ~{entry.skuSharePct.toFixed(0)}% {grain === 'category' ? 'Category' : 'SKU'} Count · ~{entry.revenueTotal.toFixed(0)}% Revenue
                    </span>
                    <span className="abc-class-summary-archetype">{CLASS_ARCHETYPE[entry.cat]}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="abc-pareto-container abc-analysis-drilldown">
              <div className="abc-pareto-header">
                <h3 className="abc-pareto-title">
                  {panel.label ? `${panel.label} — Drill-down · Class C Stock Status` : 'Drill-down · Class C Stock Status'}
                </h3>
              </div>
              <table className="abc-drilldown-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>{grain === 'category' ? 'Category' : 'SKU'} Count</th>
                    <th>% of Class C</th>
                  </tr>
                </thead>
                <tbody>
                  {panel.classCStockBreakdown.map((row) => (
                    <tr key={row.status}>
                      <td>
                        <span className="abc-drilldown-dot" style={{ backgroundColor: STOCK_STATUS_COLORS[row.status] }} />
                        {row.status}
                      </td>
                      <td>{row.count}</td>
                      <td>{row.pct.toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="abc-page-grain-note">
                Long-tail SKUs sitting at LOW/CRITICAL stock are the lowest-priority reorders by revenue, but still worth a periodic check so they don't go fully out of stock unnoticed.
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
        <div className="abc-table-wrapper">
          <table className="abc-table">
            <thead>
              <tr>
                <th>#</th>
                <th>{grain === 'category' ? 'CATEGORY' : 'SKU'}</th>
                <th>PRODUCT</th>
                <th>BRAND</th>
                <th>CAT</th>
                <th>REV %</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {filteredData.map((item, index) => (
                <tr
                  key={item.id}
                  id={`abc-row-${item.id}`}
                  className={highlightedSKUId === item.id ? 'highlighted-row-flash' : ''}
                >
                  <td className="abc-row-num">{index + 1}</td>
                  <td className="abc-sku-cell">{formatSKU(item.sku)}</td>
                  <td className="abc-product-cell">
                    {(() => {
                      const { name, weight } = parseProductAndWeight(item.product);
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                          <span className="abc-product-name">{name}</span>
                          {weight && (
                            <span className="abc-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                              {weight}
                            </span>
                          )}
                        </div>
                      );
                    })()}
                  </td>
                  <td className="abc-brand-cell">{item.brand}</td>
                  <td>
                    <span className="abc-cat-cell-inner">
                      <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                      {item.nearBoundary && (
                        <AlertTriangle
                          size={13}
                          className="abc-boundary-icon"
                          title={`Cumulative revenue ${item.cumulativePct.toFixed(1)}% — within ${BOUNDARY_TOLERANCE_PP}pp of a tier cutoff`}
                        />
                      )}
                    </span>
                  </td>
                  <td className="abc-rev-cell">{item.revPct.toFixed(1)}%</td>
                  <td><span className={getStatusClass(item.status)}>{item.status}</span></td>
                </tr>
              ))}
              {filteredData.length === 0 && (
                <tr>
                  <td colSpan="7" className="abc-no-results">No data for this selection.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default ABCClassification;
