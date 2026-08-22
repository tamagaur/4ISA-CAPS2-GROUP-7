import React, { useState, useMemo, useRef, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Search, Clock, X, RotateCcw, Tag, Filter, AlertTriangle } from 'lucide-react';
import {
  ComposedChart,
  Bar,
  Line,
  ReferenceLine,
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

// Manuscript §3.4.4.2.2/§3.4.4.2.3: Pareto/80-20 validation and Cumulative
// Revenue Coverage Ratio. Both series are already percentages (revenue %
// per SKU, cumulative %), so bars and the cumulative line share one 0-100
// axis by construction — no dual-axis needed.
const ParetoTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const point = payload[0].payload;
    return (
      <div className="abc-pareto-tooltip">
        <p className="abc-pareto-tooltip-title">Rank #{label} — {formatSKU(point.sku)}</p>
        <p className="abc-pareto-tooltip-line" style={{ color: COLORS.dispatched }}>
          Revenue share: {point.revPct.toFixed(1)}%
        </p>
        <p className="abc-pareto-tooltip-line" style={{ color: CHART_COLORS.cumulativeCurve }}>
          Cumulative: {point.cumulativePct.toFixed(1)}%
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
        cat: item.tier,
        revPct: item.revenue_share ?? 0,
        cumulativePct: item.cumulative_share ?? 0,
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

        {/* Pareto Chart — Manuscript §3.4.4.2.2 (80/20 validation) / §3.4.4.2.3 (CRCR) */}
        <div className="abc-pareto-container">
          <div className="abc-pareto-header">
            <h3 className="abc-pareto-title">Pareto analysis</h3>
            <div className="abc-pareto-legend">
              <div className="abc-pareto-legend-item">
                <span className="abc-pareto-legend-swatch" style={{ backgroundColor: COLORS.dispatched }} />
                <span>Revenue share per SKU</span>
              </div>
              <div className="abc-pareto-legend-item">
                <span className="abc-pareto-legend-line" style={{ backgroundColor: CHART_COLORS.cumulativeCurve }} />
                <span>Cumulative revenue</span>
              </div>
              <div className="abc-pareto-legend-item">
                <span className="abc-pareto-legend-line abc-pareto-legend-dashed" style={{ backgroundColor: CHART_COLORS.gridline }} />
                <span>Tier cutoffs (80% / 95%)</span>
              </div>
            </div>
          </div>
          <div className="abc-pareto-chart-wrapper">
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={dataWithCumulative} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                <XAxis
                  dataKey="rank"
                  axisLine={true}
                  tickLine={true}
                  tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                  label={{ value: `${grain === 'category' ? 'Category' : 'SKU'} rank, by revenue`, position: 'insideBottom', offset: -5, fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                />
                <YAxis
                  domain={[0, 100]}
                  ticks={[0, 20, 40, 60, 80, 100]}
                  tickFormatter={(v) => `${v}%`}
                  axisLine={true}
                  tickLine={true}
                  tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                />
                <Tooltip content={<ParetoTooltip />} cursor={{ fill: '#f7fafc' }} />
                <ReferenceLine y={80} stroke={CHART_COLORS.gridline} strokeDasharray="4 4" label={{ value: 'A/B — 80%', position: 'right', fill: CHART_COLORS.axisLabel, fontSize: 10 }} />
                <ReferenceLine y={95} stroke={CHART_COLORS.gridline} strokeDasharray="4 4" label={{ value: 'B/C — 95%', position: 'right', fill: CHART_COLORS.axisLabel, fontSize: 10 }} />
                <Bar dataKey="revPct" fill={COLORS.dispatched} radius={[2, 2, 0, 0]} barSize={16} isAnimationActive={false} />
                <Line
                  type="monotone"
                  dataKey="cumulativePct"
                  stroke={CHART_COLORS.cumulativeCurve}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 5 }}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>

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
