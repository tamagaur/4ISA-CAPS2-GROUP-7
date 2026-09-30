import React, { useState, useMemo, useRef, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Plus, Search, Clock, X, RotateCcw, Tag, Layers, Filter } from 'lucide-react';
import AddSKUModal from './AddSKUModal';
import { useToast } from './ToastProvider';
import ViewSKUModal from './ViewSKUModal';
import EditSKUModal from './EditSKUModal';
import { getSKUs, createSKU, updateSKU } from '../api/sku';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import { formatUnits, exactUnits } from '../utils/formatNumber';
import { formatMonth } from '../utils/formatDate';
import Pagination from './Pagination';
import { LoadingStatus, SkeletonLine, SkeletonStatCards, SkeletonTable } from './Skeleton';
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

const SKUManagement = () => {
  // Shared principal scope (Topbar's segmented control) — the SKU list
  // reloads whenever it changes, via loadSKUs' effect dep below.
  const { principal } = useOutletContext() || {};
  // Adding and editing SKUs needs sku.edit (Kelvin's permissions proposal;
  // the backend checks POST/PATCH /sku). Without it the list is read-only.
  const { hasPermission } = usePermissions();
  const canEdit = hasPermission(P.SKU_EDIT);
  const [rawItems, setRawItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadSKUs = () => {
    setLoading(true);
    setError(null);
    return getSKUs({ principal })
      .then((res) => {
        setRawItems(res.items || []);
      })
      .catch((err) => {
        setError(err.message || 'Failed to load SKUs');
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadSKUs();
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
        product: item.product_name || 'Unknown Product',
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
        unitPrice: item.unit_price,
        notes: item.notes,
      })),
    [rawItems]
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
  const isCurrentTier = (s) => s.catPeriod === latestCatPeriodByPrincipal[s.principal];
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
    const payload = { product_name: updatedSKU.product };
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
    if (!sku.catPeriod) return `Category ${sku.cat}`;
    const when = formatMonth(sku.catPeriod);
    return isCurrentTier(sku)
      ? `Category ${sku.cat} — current run (${when})`
      : `Category ${sku.cat} — last classified ${when}; no sales since, so this is carried forward`;
  };

  return (
    <div className="sku-management">
      <div className="sku-content">
        {/* Page Header */}
        <div className="sku-page-header">
          <div>
            <h2 className="sku-page-title">SKU <span className="page-title-accent">Management</span></h2>
            <p className="sku-page-subtitle">
              {canEdit
                ? 'Add products or edit their name and brand. This is the master product list the forecasts draw from.'
                : "The master product list the forecasts draw from. View only — your account can't add or edit SKUs."}
            </p>
          </div>
          {canEdit && (
            <button className="add-sku-btn" onClick={() => setIsAddModalOpen(true)}>
              <Plus size={16} />
              Add SKU
            </button>
          )}
        </div>

        {/* Summary Cards — skeletons until the list lands: the counts are
            derived from it, so before then they would read 0, a number
            rather than a wait. */}
        <div className="sku-summary-grid">
          {loading ? <SkeletonStatCards count={4} cardClassName="sku-summary-card" /> : (<>
          <div className="sku-summary-card summary-total">
            <span className="summary-label">{categoryRows > 0 ? 'TOTAL PRODUCTS' : 'TOTAL SKUS'}</span>
            <span className="summary-value">{totalSKUs.toLocaleString()}</span>
            {categoryRows > 0 && (
              <span className="summary-desc">
                {(totalSKUs - categoryRows).toLocaleString()} item codes · {categoryRows.toLocaleString()} Del Monte categories
              </span>
            )}
          </div>
          <div className="sku-summary-card summary-cat-a">
            <span className="summary-label">CATEGORY A</span>
            <span className="summary-value">{categoryASKUs.toLocaleString()}</span>
            <span className="summary-desc">
              {categoryACarried > 0
                ? `most recent ABC run per SKU · ${categoryACarried.toLocaleString()} carried forward`
                : 'most recent ABC run per SKU'}
            </span>
          </div>
          <div className="sku-summary-card summary-not-classified">
            <span className="summary-label">NOT CLASSIFIED</span>
            <span className="summary-value">{notClassifiedSKUs.toLocaleString()}</span>
            <span className="summary-desc">
              {unrankedDelMonteItems === 0
                ? 'no sales in any ABC run, so never ranked'
                : unrankedDelMonteItems === notClassifiedSKUs
                  ? 'Del Monte item codes: Del Monte is ranked by category, not item'
                  : `${unrankedDelMonteItems.toLocaleString()} are Del Monte item codes (ranked by category); the rest had no sales in any ABC run`}
            </span>
          </div>
          <div className="sku-summary-card summary-no-brand">
            <span className="summary-label">NO BRAND RECORDED</span>
            <span className="summary-value">{noBrandSKUs.toLocaleString()}</span>
            <span className="summary-desc">
              brand missing in the product master
              {categoryRows > 0 && ` · includes ${categoryRows.toLocaleString()} categories, which carry no brand`}
            </span>
          </div>
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
                    placeholder="Search by code, name, or brand..."
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
                              <div className="sku-row-left">
                                <span className="sku-row-code">{sku.code}</span>
                                <span className="sku-row-brand">{sku.brand || '—'}</span>
                              </div>
                              <div className="sku-row-middle">
                                <span className="sku-row-product">{sku.product}</span>
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
                                <div className="sku-row-left">
                                  <span className="sku-row-code">{sku.code}</span>
                                  <span className="sku-row-brand">{sku.brand || '—'}</span>
                                </div>
                                <div className="sku-row-middle">
                                  <span className="sku-row-product">{sku.product}</span>
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
                                <div className="sku-row-left">
                                  <span className="sku-row-code">{sku.code}</span>
                                  <span className="sku-row-brand">{sku.brand || '—'}</span>
                                </div>
                                <div className="sku-row-middle">
                                  <span className="sku-row-product">{sku.product}</span>
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
                  <span className="sku-filter-icon-label"><Layers size={12} /> Category:</span>
                  <select
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                  >
                    <option value="All">Category (A/B/C)</option>
                    <option value="A">Category A</option>
                    <option value="B">Category B</option>
                    <option value="C">Category C</option>
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
                    Category: {categoryFilter === NOT_CLASSIFIED ? 'Not classified' : `Category ${categoryFilter}`}
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
            <div className="data-table-card">
              <table className="data-table sku-table">
                <thead>
                  <tr>
                    <th className="table-num col-fit">#</th>
                    <th className="col-fit">SKU code</th>
                    <th className="col-fit">Brand</th>
                    <th className="col-text col-product">Product</th>
                    <th className="table-center col-fit">Cat</th>
                    <th className="table-num col-fit" title="The stock level the LP orders up to: demand expected before the next delivery, plus safety stock">Target stock</th>
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
                      <td className="cell-code">
                        <span
                          className="cell-code-link"
                          role="button"
                          tabIndex={0}
                          onClick={() => handleOpenViewModal(sku)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              handleOpenViewModal(sku);
                            }
                          }}
                          title="View full SKU details"
                        >
                          {sku.code}
                        </span>
                      </td>
                      <td className={sku.brand ? 'cell-muted' : 'cell-empty'}>{sku.brand || '—'}</td>
                      <td className="cell-product">{sku.product}</td>
                      <td className="table-center" title={catTitle(sku)}>
                        {sku.cat
                          ? (
                            <span
                              className={`${getCatClass(sku.cat)}${
                                sku.catPeriod && !isCurrentTier(sku) ? ' cat-stale' : ''
                              }`}
                            >
                              {sku.cat}
                            </span>
                          )
                          : <span className="cell-empty">—</span>}
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
                          aria-label={`View SKU ${sku.code}`}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredSKUs.length === 0 && (
                    <tr className="table-empty-row">
                      <td colSpan="7">No data for this selection.</td>
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
