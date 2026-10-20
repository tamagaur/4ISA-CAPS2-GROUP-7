import React, { useState, useMemo, useRef, useEffect } from 'react';
import SectionLede from './ui/SectionLede';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { Plus, Search, Clock, X, RotateCcw, Tag, Layers, Filter, List } from 'lucide-react';
import KPICard from './KPICard';
import PageHeader from './ui/PageHeader';
import { ClassBadge } from './ui/StatusBadge';
import AddSKUModal from './AddSKUModal';
import { useToast } from './ToastProvider';
import ViewSKUModal from './ViewSKUModal';
import EditSKUModal from './EditSKUModal';
import { getSKUs, createSKU, updateSKU } from '../api/sku';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import { formatUnits, exactUnits } from '../utils/formatNumber';
import { formatDate, formatMonth } from '../utils/formatDate';
import { labelForPrincipal } from '../principals';
import { createLatestOnly } from '../utils/latestOnly';
import Pagination from './Pagination';
import ProductName from './ProductName';
import { LoadingStatus, SkeletonLine, SkeletonStatCards, SkeletonTable } from './Skeleton';
import TierBasisLabel, { currentPeriodFor, isStaleTier, latestPeriod } from './TierBasisLabel';
import './SKUManagement.css';

// Product names render verbatim. A helper used to pull a pack size out onto
// a second line, but its pattern only matched sizes after a space or
// bracket ("…40(6+1)65G" split, "…12X2X135ML" didn't), so a few rows got
// an odd "(65G)" line while most identical-looking names didn't.

// Brand filter sentinels. <select> values are strings, so "no brand" needs a
// literal that cannot collide with a real brand — hence the underscores.
// Both are excluded before the brand list is handed to AddSKUModal, which
// offers it as values to ASSIGN; neither is a brand anyone can pick.
const ALL_BRANDS = 'All Brands';
const NO_BRAND = '__NO_BRAND__';
// Category filter sentinel for SKUs with no ABC tier in any run (never
// ranked: no sales in any classified month). Same underscore convention.
const NOT_CLASSIFIED = '__NOT_CLASSIFIED__';

// The code shown under a product's name. A Del Monte sell-out category has
// no SKU code (its sku_id is the category path, DEC-03), so its name — the
// category — stands alone. Recently-viewed rows saved before `grain` was
// mapped have none and keep their code.
const codeOf = (sku) => (sku.grain === 'category' ? null : sku.code);

const SKUManagement = () => {
  // Shared principal scope (Topbar's segmented control) — the SKU list
  // reloads whenever it changes, via loadSKUs' effect dep below.
  const { principal } = useOutletContext() || {};
  // Adding and editing SKUs needs sku.edit (Kelvin's permissions proposal;
  // the backend checks POST/PATCH /sku). Without it the list is read-only.
  const { hasPermission } = usePermissions();
  const canEdit = hasPermission(P.SKU_EDIT);
  // The detail window links to the product's forecast and, when the plan
  // covers it, its order recommendation.
  const navigate = useNavigate();
  const [rawItems, setRawItems] = useState([]);
  // When each principal's stock was counted and which LP plan the target
  // stock comes from (GET /sku, 2026-10-03). The Technical Adviser asked
  // every stock figure to state its count date: the file filed as "Mar
  // 2026" was counted on 6 Apr 2026. planCycle is null without lp.view.
  const [stockCountDates, setStockCountDates] = useState({});
  const [planCycle, setPlanCycle] = useState(null);
  // Each principal's latest ABC run (GET /sku's tier_a_periods).
  const [tierAPeriods, setTierAPeriods] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Every load is tagged with the next number in this counter, and only the response
  // whose tag is still the latest may touch state. A principal switch (or a reload after
  // an edit) therefore makes every older in-flight response unusable however late it
  // lands (FE-2: the previous principal's SKUs used to overwrite the new list). The effect
  // cleanup bumps the counter too, so a response arriving after unmount is dropped.
  const latestLoad = useRef(createLatestOnly());

  const loadSKUs = () => {
    const tag = latestLoad.current.start();
    const isCurrent = () => latestLoad.current.isCurrent(tag);
    setLoading(true);
    setError(null);
    return getSKUs({ principal })
      .then((res) => {
        if (!isCurrent()) return;
        setRawItems(res.items || []);
        setStockCountDates(res.stock_count_dates || {});
        setPlanCycle(res.planning_cycle_date ?? null);
        setTierAPeriods(res.tier_a_periods || {});
      })
      .catch((err) => {
        if (!isCurrent()) return;
        setError(err.message || 'Failed to load SKUs');
      })
      .finally(() => {
        if (isCurrent()) setLoading(false);
      });
  };

  useEffect(() => {
    loadSKUs();
    const gate = latestLoad.current;
    return () => gate.invalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [principal]);

  // Map API shape -> the row shape the rest of this page renders.
  const skus = useMemo(
    () =>
      rawItems.map((item) => ({
        id: item.product_key,
        code: item.sku_id,
        principal: item.principal,
        // 'sku' (an item code) or 'category' (a Del Monte sell-out category).
        grain: item.grain,
        // Real Product_Dimension.brand. This used to be hardcoded 'Unilever'
        // — the principal, not a brand — and because the edit flow sends
        // brand back on save, any edit would have overwritten a real brand
        // with 'Unilever'.
        //
        // Trimmed, so a whitespace-padded value doesn't become its own entry
        // in the filter list alongside the clean one. Internal spacing is
        // left alone: 'False  (10)' really is stored with two spaces, and
        // collapsing it here would render a value that matches no row.
        //
        // Coverage is per principal, not uniform: every Unilever SKU has a
        // brand, while Del Monte has almost none (see the no-brand card).
        brand: (item.brand || '').trim() || null,
        // A Del Monte category's name is its path when it has no other; a
        // product with no name shows its code alone (ProductName's fallback).
        product: item.product_name || (item.grain === 'category' ? item.sku_id : ''),
        cat: item.tier,
        // The period `cat` was computed in. A tier is the SKU's LAST KNOWN
        // classification, so this is what says whether it is current.
        catPeriod: item.tier_period,
        leadTime: item.lead_time_days != null ? `${item.lead_time_days} days` : null,
        leadTimeDays: item.lead_time_days,
        reorderPt: item.reorder_point,
        status: item.status,
        currentStock: item.current_stock,
        currentStockCases: item.current_stock_cases,
        // The day this product's principal's latest stock was counted.
        stockCountDate: item.stock_count_date ?? null,
        // The LP cycle the target stock comes from (same for every row).
        planCycle,
        unitPrice: item.unit_price,
        unitCost: item.unit_cost,
        notes: item.notes,
      })),
    [rawItems, planCycle]
  );

  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isViewModalOpen, setIsViewModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);

  const [selectedSKU, setSelectedSKU] = useState(null);
  const [editingSKU, setEditingSKU] = useState(null);

  const toast = useToast();
  const [searchQuery, setSearchQuery] = useState('');
  const [brandFilter, setBrandFilter] = useState(ALL_BRANDS);
  const [categoryFilter, setCategoryFilter] = useState('All');

  // Combobox & Highlight State
  const [isComboboxOpen, setIsComboboxOpen] = useState(false);
  const [highlightedSKUId, setHighlightedSKUId] = useState(null);
  const comboboxRef = useRef(null);

  // Persistent Recently Viewed SKUs (max 5)
  const [recentlyViewedSKUs, setRecentlyViewedSKUs] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_recent_sku_views');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

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

  // Distinct brands for the filter, sorted case-insensitively so the list
  // reads alphabetically instead of putting every lowercase entry after Z.
  //
  // A "(No brand)" entry is offered whenever the loaded scope actually has
  // rows without one, because the summary card counts those rows and they
  // were otherwise unreachable — the card claimed thousands were missing a
  // brand and no filter could show you which.
  //
  // Values are deliberately NOT screened for plausibility. The column
  // currently holds Del Monte category names ('DAIRY', 'KETCHUPS') and 12
  // corrupt 'False (n)' entries from a bad cell in the source sheet.
  // Dropping them here would hide a data defect while the same values stayed
  // visible in the table and the edit modal, with no way left to find them.
  const brands = useMemo(() => {
    const distinct = [...new Set(skus.map(s => s.brand).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    const hasUnbranded = skus.some(s => !s.brand);
    return [ALL_BRANDS, ...(hasUnbranded ? [NO_BRAND] : []), ...distinct];
  }, [skus]);

  // Drop a brand selection that the currently loaded scope has no option
  // for. Switching principal swaps the whole brand list, so a filter left
  // on e.g. REXONA (Unilever) under Del Monte would sit in a <select> whose
  // options no longer contain it — the control renders blank while the
  // table silently shows nothing. Guarded on a non-empty list so a failed
  // or in-flight reload never clears a valid selection.
  useEffect(() => {
    if (skus.length === 0) return;
    if (!brands.includes(brandFilter)) setBrandFilter(ALL_BRANDS);
  }, [brands, brandFilter, skus.length]);

  const filteredSKUs = useMemo(() => {
    return skus.filter(sku => {
      const matchesSearch = searchQuery === '' ||
        sku.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (sku.brand || '').toLowerCase().includes(searchQuery.toLowerCase());
      const matchesBrand =
        brandFilter === ALL_BRANDS ||
        (brandFilter === NO_BRAND ? !sku.brand : sku.brand === brandFilter);
      const matchesCategory =
        categoryFilter === 'All' ||
        (categoryFilter === NOT_CLASSIFIED ? !sku.cat : sku.cat === categoryFilter);
      return matchesSearch && matchesBrand && matchesCategory;
    });
  }, [skus, searchQuery, brandFilter, categoryFilter]);

  // Pagination. The SKU master runs 2,000+ rows and this page renders the
  // whole table — unpaginated it built every row into the DOM at once, which
  // is slow to render and impossible to scan. Mirrors the pagination
  // ABCClassification.jsx already added over the same corpus, so the two
  // SKU tables behave the same way.
  const PAGE_SIZE_OPTIONS = [25, 50, 100];
  const [pageSize, setPageSize] = useState(25);
  const [currentPage, setCurrentPage] = useState(1);

  const totalPages = Math.max(1, Math.ceil(filteredSKUs.length / pageSize));
  // Clamped rather than stored, so narrowing the filters while on a high page
  // number can't strand the user on an empty page.
  const safeCurrentPage = Math.min(currentPage, totalPages);

  // Any filter/search change puts the user back on page 1 — staying on page 7
  // of a result set that just shrank to 2 pages shows nothing.
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, brandFilter, categoryFilter, pageSize]);

  const pagedSKUs = useMemo(() => {
    const start = (safeCurrentPage - 1) * pageSize;
    return filteredSKUs.slice(start, start + pageSize);
  }, [filteredSKUs, safeCurrentPage, pageSize]);

  // Summary cards show counts that can actually vary and mean something. The
  // old Active/Disabled pair (and matching tabs) could never change: every SKU
  // is ACTIVE in Product_Dimension and PATCH /sku doesn't write status yet.
  const totalSKUs = skus.length;
  const categoryASKUs = skus.filter(s => s.cat === 'A').length;

  // Each principal's newest classification period — its current ABC run.
  // Anything older is a carried-forward tier from a month the SKU last had
  // sales in, which the table marks so a stale category is never read as a
  // fresh one. Per principal: Unilever's run is 2026-02 and Del Monte's
  // 2025-12, so one latest month across both marked every Del Monte tier
  // "carried forward, no sales since" under All principals.
  const latestCatPeriodByPrincipal = useMemo(
    () => skus.reduce((acc, s) => {
      if (s.catPeriod && !(acc[s.principal] >= s.catPeriod)) acc[s.principal] = s.catPeriod;
      return acc;
    }, {}),
    [skus]
  );
  const isCurrentTier = (s) => s.catPeriod === currentPeriodFor(s.principal, tierAPeriods, latestCatPeriodByPrincipal[s.principal]);
  // Carried forward and more than 6 months behind the newest run: marked stale. Display only.
  const isStaleCat = (s) => !!s.catPeriod && !isCurrentTier(s)
    && isStaleTier(s.catPeriod, latestPeriod(tierAPeriods, latestCatPeriodByPrincipal[s.principal]));
  // Category A's own carried-forward count — the card used to print every
  // tier's (821 of them, 20 of which are A).
  const categoryACarried = skus.filter(s => s.cat === 'A' && s.catPeriod && !isCurrentTier(s)).length;
  const noBrandSKUs = skus.filter(s => !s.brand).length;
  // Del Monte's product master mixes item codes with sell-out categories
  // (DEC-03). Categories carry no brand, and item codes are never ranked one
  // by one (Del Monte is ranked by category), so the cards count them apart.
  const categoryRows = skus.filter(s => s.grain === 'category').length;
  const unrankedDelMonteItems = skus.filter(s => !s.cat && s.principal === 'delmonte' && s.grain !== 'category').length;
  // No tier in ANY run up to the latest one — not a stale tier, an absent
  // one. Shown as its own count (and filter) rather than defaulted to C:
  // an invented category is worse than an honest gap.
  const notClassifiedSKUs = skus.filter(s => !s.cat).length;

  // The stock column's period line: "counted Apr 6, 2026", or each
  // principal's own day when the list spans both (Unilever's latest count
  // is 6 Apr 2026, Del Monte's 1 Dec 2025).
  const countEntries = Object.entries(stockCountDates);
  const stockCountText = countEntries.length === 1
    ? `counted ${formatDate(countEntries[0][1])}`
    : countEntries.length > 1
      ? `counted ${countEntries.map(([p, d]) => `${labelForPrincipal(p)} ${formatDate(d)}`).join(', ')}`
      : null;
  // Each principal's ABC run month, for the Class A card ("Feb 2026").
  const runMonthsText = Object.entries(latestCatPeriodByPrincipal)
    .map(([p, period]) => (Object.keys(latestCatPeriodByPrincipal).length > 1
      ? `${labelForPrincipal(p)} ${formatMonth(period)}`
      : formatMonth(period)))
    .join(' · ');
  const countUnit = categoryRows > 0 ? 'products' : 'SKUs';

  // The Audit Log entries for adding and editing a SKU are written by the
  // server as part of POST/PATCH /sku, not from here.
  const handleAddSKU = async (formData) => {
    // Only fields POST /sku actually stores (see backend/routers/sku.py's
    // INSERT); unit price, lead time and notes have no column yet.
    const created = await createSKU({
      sku_code: formData.skuCode,
      principal: 'unilever',
      product_name: formData.productName,
      brand: formData.brand,
    });

    await loadSKUs();
    // Outlives the modal's own success screen, which auto-dismisses after 1.5s.
    toast.success(`SKU ${created.sku_id} created`);
  };

  const handleOpenViewModal = (sku) => {
    setSelectedSKU(sku);
    setIsViewModalOpen(true);

    // Track recently viewed SKU (max 5)
    setRecentlyViewedSKUs(prev => {
      const filtered = prev.filter(s => s.id !== sku.id);
      const updated = [sku, ...filtered].slice(0, 5);
      try {
        localStorage.setItem('san2_recent_sku_views', JSON.stringify(updated));
      } catch (err) {
        console.error('Failed to save recent view', err);
      }
      return updated;
    });
  };

  const handleOpenEditModal = (sku) => {
    setIsViewModalOpen(false);
    setEditingSKU(sku);
    setIsEditModalOpen(true);
  };

  const handleSaveSKU = async (updatedSKU) => {
    const previousSKU = skus.find(s => s.id === updatedSKU.id);

    // PATCH /sku only persists product_name, pack_size and brand (unit price,
    // lead time, status and notes have no column yet, so the edit form locks
    // them). Brand is sent only when it actually changed, so saving an
    // unrelated edit can never rewrite it.
    // The name is sent only when it changed, like the brand: a save must
    // never rewrite a name the user didn't touch.
    const payload = {};
    if (!previousSKU || (previousSKU.product || '') !== (updatedSKU.product || '')) {
      payload.product_name = updatedSKU.product;
    }
    if (previousSKU && (previousSKU.brand || '') !== (updatedSKU.brand || '') && updatedSKU.brand) {
      payload.brand = updatedSKU.brand;
    }
    await updateSKU(updatedSKU.id, payload);

    await loadSKUs();
    setSelectedSKU(updatedSKU);
    toast.success(`SKU ${updatedSKU.code} updated`);
  };

  // Handle selecting a combobox suggestion row
  const handleSelectSuggestion = (sku) => {
    setSearchQuery(sku.code);
    setIsComboboxOpen(false);

    // Highlight target row and scroll smoothly to it
    setHighlightedSKUId(sku.id);
    setTimeout(() => {
      const el = document.getElementById(`sku-row-${sku.id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 80);

    // Clear flash highlight after 2s
    setTimeout(() => {
      setHighlightedSKUId(null);
    }, 2000);
  };

  const hasActiveFilters =
    searchQuery !== '' ||
    brandFilter !== ALL_BRANDS ||
    categoryFilter !== 'All';

  const handleClearFilters = () => {
    setSearchQuery('');
    setBrandFilter(ALL_BRANDS);
    setCategoryFilter('All');
  };

  const getCatClass = (cat) => {
    switch (cat) {
      case 'A': return 'cat-badge cat-a';
      case 'B': return 'cat-badge cat-b';
      case 'C': return 'cat-badge cat-c';
      default: return 'cat-badge';
    }
  };

  // Says, on hover, which ABC run a category came from — and calls out a
  // carried-forward one explicitly rather than leaving the reader to
  // compare dates.
  const catTitle = (sku) => {
    if (!sku.cat) return 'No ABC classification in any period';
    if (!sku.catPeriod) return `Class ${sku.cat}`;
    const when = formatMonth(sku.catPeriod);
    return isCurrentTier(sku)
      ? `Class ${sku.cat} — current run (${when})`
      : `Class ${sku.cat} — last classified ${when}; no sales since, so this is carried forward${isStaleCat(sku) ? ' (stale: over 6 months old)' : ''}`;
  };

  // Hover text for a stock cell: the figure with both units and its count.
  const stockTitle = (sku) => {
    const when = sku.stockCountDate ? `, counted ${formatDate(sku.stockCountDate)}` : '';
    if (sku.currentStock != null) {
      const cases = sku.currentStockCases != null ? ` (${sku.currentStockCases.toLocaleString()} cases)` : '';
      return `${sku.currentStock.toLocaleString()} pieces${cases}${when}`;
    }
    if (sku.currentStockCases != null) {
      return `${sku.currentStockCases.toLocaleString()} cases${when}; no usable pack size to convert to pieces`;
    }
    return 'No stock record in the latest count';
  };

  return (
    <div className="sku-management">
      <div className="sku-content">
        <PageHeader
          title="SKU"
          accent="Management"
          subtitle={canEdit
            ? 'Add products or edit their name and brand. This is the master product list the forecasts draw from.'
            : "The master product list the forecasts draw from. View only — your account can't add or edit SKUs."}
          actions={canEdit && (
            <button type="button" className="btn btn-primary" onClick={() => setIsAddModalOpen(true)}>
              <Plus size={16} aria-hidden="true" />
              Add SKU
            </button>
          )}
        />
        <TierBasisLabel periods={tierAPeriods} />

        {/* Summary Cards — skeletons until the list lands: the counts are
            derived from it, so before then they would read 0, a number
            rather than a wait. */}
        {/* The shared KPI card (UI pass): one short line each, the longer
            notes behind the "?". A master-list count has no month: its
            period is "now", said in the first card's line. */}
        <SectionLede className="is-standalone">Gaps in the product list</SectionLede>
        <div className="kpi-strip sku-summary-grid">
          {loading ? <SkeletonStatCards count={4} cardClassName="kpi-card" /> : (<>
          <KPICard
            title={categoryRows > 0 ? 'Total products' : 'Total SKUs'}
            value={totalSKUs.toLocaleString()}
            unit={countUnit}
            contextLine={categoryRows > 0
              ? `${(totalSKUs - categoryRows).toLocaleString()} item codes · ${categoryRows.toLocaleString()} Del Monte categories · now`
              : 'in the current product master, now'}
            icon={<List size={20} />}
          />
          <KPICard
            title="Class A"
            value={categoryASKUs.toLocaleString()}
            unit={countUnit}
            contextLine={`latest ABC run per SKU${runMonthsText ? ` · ${runMonthsText}` : ''}`}
            tooltip={`Each SKU's class in the most recent ABC run that ranked it.${categoryACarried > 0
              ? ` ${categoryACarried.toLocaleString()} of these are carried forward from earlier runs.` : ''}`}
            icon={<Layers size={20} />}
          />
          <KPICard
            title="Not classified"
            value={notClassifiedSKUs.toLocaleString()}
            unit={countUnit}
            contextLine={unrankedDelMonteItems === 0
              ? 'no sales in any ABC run'
              : unrankedDelMonteItems === notClassifiedSKUs
                ? 'Del Monte item codes · ranked by category'
                : `${unrankedDelMonteItems.toLocaleString()} Del Monte item codes · the rest never sold`}
            tooltip={unrankedDelMonteItems > 0
              ? 'Del Monte is ranked by product category, not by item code, so its item codes carry no class of their own. The rest had no sales in any ABC run, so they were never ranked.'
              : 'These SKUs had no sales in any ABC run, so they were never ranked. Not a data defect.'}
            icon={<Filter size={20} />}
          />
          <KPICard
            title="No brand recorded"
            value={noBrandSKUs.toLocaleString()}
            unit={countUnit}
            metricType={noBrandSKUs > 0 ? 'watch' : undefined}
            contextLine="brand missing in the product master"
            tooltip={categoryRows > 0 ? `Includes ${categoryRows.toLocaleString()} Del Monte categories, which carry no brand.` : undefined}
            icon={<Tag size={20} />}
          />
          </>)}
        </div>

        {loading && (
          <>
            <LoadingStatus>Loading SKUs…</LoadingStatus>
            <div className="sku-filters-row" aria-hidden="true">
              <SkeletonLine width="100%" height="2.25rem" />
            </div>
            <div className="data-table-card">
              <SkeletonTable rows={8} columns={7} />
            </div>
          </>
        )}
        {error && <p className="sku-page-subtitle">Error: {error}</p>}

        {!loading && !error && (
          <>
            {/* Filters Row */}
            <div className="sku-filters-row">
              {/* Searchable Combobox */}
              <div className="sku-combobox-container" ref={comboboxRef}>
                <div className="sku-search-wrapper">
                  <Search className="search-icon" size={16} />
                  <input
                    type="text"
                    placeholder="Search by name, SKU code, or brand..."
                    value={searchQuery}
                    onFocus={() => setIsComboboxOpen(true)}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setIsComboboxOpen(true);
                    }}
                    className="sku-search-input"
                  />
                  {searchQuery && (
                    <button
                      className="sku-input-clear-btn"
                      onClick={() => setSearchQuery('')}
                      title="Clear search"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>

                {/* Combobox Dropdown Panel */}
                {isComboboxOpen && (
                  <div className="sku-combobox-dropdown">
                    {searchQuery.trim() !== '' ? (
                      /* Live Matching Suggestions */
                      <div className="sku-combobox-section">
                        <div className="sku-section-header">
                          <span>SUGGESTIONS ({filteredSKUs.length})</span>
                        </div>
                        {filteredSKUs.length > 0 ? (
                          filteredSKUs.map((sku) => (
                            <div
                              key={sku.id}
                              className="sku-suggestion-row"
                              onClick={() => handleSelectSuggestion(sku)}
                            >
                              <div className="sku-row-middle">
                                <ProductName name={sku.product} code={codeOf(sku)} className="sku-row-product" />
                              </div>
                              <div className="sku-row-left">
                                <span className="sku-row-brand">{sku.brand || '—'}</span>
                              </div>
                              <div className="sku-row-right">
                                <span className={getCatClass(sku.cat)}>{sku.cat || '—'}</span>
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="sku-no-suggestions">No matching SKUs found.</div>
                        )}
                      </div>
                    ) : (
                      /* Quick Access Panel when search input is focused with no query */
                      <div className="sku-combobox-default">
                        {recentlyViewedSKUs.length > 0 ? (
                          <div className="sku-combobox-section">
                            <div className="sku-section-header">
                              <Clock size={12} />
                              <span>RECENTLY VIEWED</span>
                            </div>
                            {recentlyViewedSKUs.map((saved) => skus.find((s) => s.id === saved.id) || saved).map((sku) => (
                              <div
                                key={sku.id}
                                className="sku-suggestion-row"
                                onClick={() => handleSelectSuggestion(sku)}
                              >
                                <div className="sku-row-middle">
                                  <ProductName name={sku.product} code={codeOf(sku)} className="sku-row-product" />
                                </div>
                                <div className="sku-row-left">
                                  <span className="sku-row-brand">{sku.brand || '—'}</span>
                                </div>
                                <div className="sku-row-right">
                                  <span className={getCatClass(sku.cat)}>{sku.cat || '—'}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="sku-combobox-section">
                            <div className="sku-section-header">
                              <span>RECENT SKUS</span>
                            </div>
                            {filteredSKUs.slice(0, 5).map((sku) => (
                              <div
                                key={sku.id}
                                className="sku-suggestion-row"
                                onClick={() => handleSelectSuggestion(sku)}
                              >
                                <div className="sku-row-middle">
                                  <ProductName name={sku.product} code={codeOf(sku)} className="sku-row-product" />
                                </div>
                                <div className="sku-row-left">
                                  <span className="sku-row-brand">{sku.brand || '—'}</span>
                                </div>
                                <div className="sku-row-right">
                                  <span className={getCatClass(sku.cat)}>{sku.cat || '—'}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Filter Controls Row: Icon-Labeled Wrappers */}
              <div className="sku-filter-controls">
                <div className="sku-filter-select-wrapper">
                  <span className="sku-filter-icon-label"><Tag size={12} /> Brand:</span>
                  <select
                    value={brandFilter}
                    onChange={(e) => setBrandFilter(e.target.value)}
                  >
                    {brands.map(b => (
                      <option key={b} value={b}>{b === NO_BRAND ? '(No brand)' : b}</option>
                    ))}
                  </select>
                </div>

                <div className="sku-filter-select-wrapper">
                  <span className="sku-filter-icon-label"><Layers size={12} /> ABC class:</span>
                  <select
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                  >
                    <option value="All">All classes</option>
                    <option value="A">Class A</option>
                    <option value="B">Class B</option>
                    <option value="C">Class C</option>
                    <option value={NOT_CLASSIFIED}>Not classified</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Active Filter Chips Bar */}
            {hasActiveFilters && (
              <div className="sku-active-chips-row">
                <span className="chips-label">
                  <Filter size={12} /> Active Filters:
                </span>

                {searchQuery && (
                  <span className="sku-active-chip">
                    Search: "{searchQuery}"
                    <button className="sku-chip-remove" onClick={() => setSearchQuery('')}>
                      <X size={12} />
                    </button>
                  </span>
                )}

                {brandFilter !== ALL_BRANDS && (
                  <span className="sku-active-chip">
                    Brand: {brandFilter === NO_BRAND ? '(No brand)' : brandFilter}
                    <button className="sku-chip-remove" onClick={() => setBrandFilter(ALL_BRANDS)}>
                      <X size={12} />
                    </button>
                  </span>
                )}

                {categoryFilter !== 'All' && (
                  <span className="sku-active-chip">
                    Class: {categoryFilter === NOT_CLASSIFIED ? 'Not classified' : `Class ${categoryFilter}`}
                    <button className="sku-chip-remove" onClick={() => setCategoryFilter('All')}>
                      <X size={12} />
                    </button>
                  </span>
                )}

                <button
                  className="clear-all-chips-btn"
                  onClick={handleClearFilters}
                  title="Reset all filters and search query"
                >
                  <RotateCcw size={12} />
                  Clear all filters
                </button>
              </div>
            )}

            {/* Table */}
            <SectionLede className="is-standalone">Every product and its details</SectionLede>
            <div className="data-table-card">
              <table className="data-table sku-table">
                <thead>
                  <tr>
                    <th className="table-num col-fit">#</th>
                    <th className="col-text col-product">Product</th>
                    <th className="col-fit">Brand</th>
                    <th className="table-center col-fit" title="The SKU's class in the most recent ABC run that ranked it">
                      Class
                      <span className="sku-th-sub">latest ABC run</span>
                    </th>
                    {/* Stock beside the target it is measured against, each
                        with its unit and period (Technical Adviser,
                        2026-10-03): the count's own date, not the month the
                        file is filed under, and the plan the target is from. */}
                    <th className="table-num col-fit" title="Stock on hand at the latest count, in pieces (cases x pack size + loose pieces)">
                      Stock (pieces)
                      {stockCountText && <span className="sku-th-sub">{stockCountText}</span>}
                    </th>
                    <th className="table-num col-fit" title="The stock level the LP orders up to: demand expected before the next delivery, plus safety stock">
                      Target stock (pieces)
                      {planCycle && <span className="sku-th-sub">{formatMonth(planCycle)} plan</span>}
                    </th>
                    <th className="table-center col-fit"><span className="visually-hidden">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {pagedSKUs.map((sku, index) => (
                    <tr
                      key={sku.id}
                      id={`sku-row-${sku.id}`}
                      className={highlightedSKUId === sku.id ? 'highlighted-row-flash' : ''}
                    >
                      {/* Row number is position in the FULL filtered set, not
                          within the page, so it stays stable across paging. */}
                      <td className="cell-rownum table-num">{(safeCurrentPage - 1) * pageSize + index + 1}</td>
                      <td className="cell-product">
                        <ProductName
                          name={sku.product}
                          code={codeOf(sku)}
                          onOpen={() => handleOpenViewModal(sku)}
                          openLabel="View details"
                        />
                      </td>
                      <td className={sku.brand ? 'cell-muted' : 'cell-empty'}>{sku.brand || '—'}</td>
                      <td className="table-center">
                        {/* The shared class badge; faded when the class is
                            carried forward from an earlier run. */}
                        <ClassBadge
                          tier={sku.cat}
                          faded={Boolean(sku.catPeriod && !isCurrentTier(sku))}
                          title={catTitle(sku)}
                        />
                        {isStaleCat(sku) && <span className="tier-chip-stale">stale</span>}
                      </td>
                      {/* Pieces when the pack size converts the warehouse's
                          case count; the cases alone, labelled, when it can't
                          (GET /sku sends no pieces then). */}
                      <td
                        className={`table-num ${sku.currentStock != null ? '' : 'cell-empty'}`}
                        title={stockTitle(sku)}
                      >
                        {sku.currentStock != null
                          ? formatUnits(sku.currentStock)
                          : sku.currentStockCases != null
                            ? `${sku.currentStockCases.toLocaleString()} cases`
                            : '—'}
                      </td>
                      <td
                        className={`table-num ${sku.reorderPt != null ? 'cell-strong' : 'cell-empty'}`}
                        title={exactUnits(sku.reorderPt)}
                      >
                        {formatUnits(sku.reorderPt)}
                      </td>
                      <td className="table-center">
                        <button
                          className="table-btn"
                          onClick={() => handleOpenViewModal(sku)}
                          aria-label={`View details: ${sku.product || sku.code}`}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredSKUs.length === 0 && (
                    <tr className="table-empty-row">
                      <td colSpan="6">No data for this selection.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <Pagination
              currentPage={safeCurrentPage}
              totalPages={totalPages}
              totalItems={filteredSKUs.length}
              pageSize={pageSize}
              onPageChange={setCurrentPage}
              onPageSizeChange={setPageSize}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              idPrefix="sku"
            />
          </>
        )}
      </div>

      <AddSKUModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onAdd={handleAddSKU}
        brands={brands.filter(b => b !== ALL_BRANDS && b !== NO_BRAND)}
      />

      <ViewSKUModal
        isOpen={isViewModalOpen}
        sku={selectedSKU}
        onClose={() => setIsViewModalOpen(false)}
        onEdit={canEdit ? handleOpenEditModal : undefined}
        // Unilever SKUs only: a Del Monte row is a category with no series.
        onOpenForecast={hasPermission(P.FORECAST_VIEW) && selectedSKU?.principal === 'unilever' && selectedSKU?.grain !== 'category'
          ? () => navigate(`/forecast?sku=${encodeURIComponent(selectedSKU.code)}`)
          : undefined}
        // A target stock means the current plan has a row for it.
        onOpenReorder={hasPermission(P.LP_VIEW) && selectedSKU?.reorderPt != null
          ? () => navigate(`/reorder?sku=${encodeURIComponent(selectedSKU.code)}`)
          : undefined}
      />

      <EditSKUModal
        isOpen={isEditModalOpen}
        sku={editingSKU}
        onClose={() => setIsEditModalOpen(false)}
        onSave={handleSaveSKU}
      />
    </div>
  );
};

export default SKUManagement;
