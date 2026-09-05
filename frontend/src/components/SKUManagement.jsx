import React, { useState, useMemo, useRef, useEffect } from 'react';
import { Plus, Search, Clock, X, RotateCcw, Building, Tag, Layers, Filter, CheckCircle, XCircle, Package } from 'lucide-react';
import AddSKUModal from './AddSKUModal';
import ViewSKUModal from './ViewSKUModal';
import EditSKUModal from './EditSKUModal';
import { logAction } from '../utils/auditLogger';
import { getSKUs, createSKU, updateSKU } from '../api/sku';
import './SKUManagement.css';

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

const SKUManagement = () => {
  const [rawItems, setRawItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadSKUs = () => {
    setLoading(true);
    setError(null);
    return getSKUs({})
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
  }, []);

  // Map API shape -> the row shape the rest of this page renders.
  const skus = useMemo(
    () =>
      rawItems.map((item) => ({
        id: item.product_key,
        code: item.sku_id,
        brand: 'Unilever',
        supplier: 'Unilever Philippines',
        product: item.product_name || 'Unknown Product',
        cat: item.tier,
        leadTime: item.lead_time_days != null ? `${item.lead_time_days} days` : null,
        leadTimeDays: item.lead_time_days,
        reorderPt: item.reorder_point,
        status: item.status,
        currentStock: item.current_stock,
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

  const [searchQuery, setSearchQuery] = useState('');
  const [supplierFilter, setSupplierFilter] = useState('All Suppliers');
  const [brandFilter, setBrandFilter] = useState('All Brands');
  const [categoryFilter, setCategoryFilter] = useState('All');

  const [activeTab, setActiveTab] = useState('ALL'); // 'ALL' | 'ACTIVE' | 'DISABLED'

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

  const suppliers = ['All Suppliers', ...new Set(skus.map(s => s.supplier))];
  const brands = ['All Brands', ...new Set(skus.map(s => s.brand))];

  const filteredSKUs = useMemo(() => {
    return skus.filter(sku => {
      const matchesSearch = searchQuery === '' ||
        sku.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.brand.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesSupplier = supplierFilter === 'All Suppliers' || sku.supplier === supplierFilter;
      const matchesBrand = brandFilter === 'All Brands' || sku.brand === brandFilter;
      const matchesCategory = categoryFilter === 'All' || sku.cat === categoryFilter;
      const matchesStatus = activeTab === 'ALL' || sku.status === activeTab;
      return matchesSearch && matchesSupplier && matchesBrand && matchesCategory && matchesStatus;
    });
  }, [skus, searchQuery, supplierFilter, brandFilter, categoryFilter, activeTab]);

  const totalSKUs = skus.length;
  const activeSKUs = skus.filter(s => s.status === 'ACTIVE').length;
  const inactiveSKUs = skus.filter(s => s.status === 'DISABLED').length;

  const handleAddSKU = async (formData) => {
    if (formData.brand !== 'Unilever') {
      throw new Error(`Unrecognized brand "${formData.brand}"`);
    }
    const created = await createSKU({
      sku_code: formData.skuCode,
      principal: 'unilever',
      product_name: formData.productName,
      brand: formData.brand,
      unit_price: parseFloat(formData.unitPrice) || null,
      lead_time_days: formData.leadTimeDays ? parseInt(formData.leadTimeDays) : null,
      notes: formData.notes || null,
    });

    await loadSKUs();
    logAction('Add SKU', `Added new SKU: ${created.sku_id} (${created.product_name})`);
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

    // Determine what changed for the audit log
    const changes = [];
    if (previousSKU) {
      if (previousSKU.product !== updatedSKU.product) changes.push(`Product Name: ${previousSKU.product} -> ${updatedSKU.product}`);
      if (previousSKU.brand !== updatedSKU.brand) changes.push(`Brand: ${previousSKU.brand} -> ${updatedSKU.brand}`);
      if (previousSKU.unitPrice !== updatedSKU.unitPrice) changes.push(`Unit Price: ${previousSKU.unitPrice} -> ${updatedSKU.unitPrice}`);
      if (previousSKU.status !== updatedSKU.status) changes.push(`Status: ${previousSKU.status} -> ${updatedSKU.status}`);
    }

    await updateSKU(updatedSKU.id, {
      product_name: updatedSKU.product,
      brand: updatedSKU.brand,
      unit_price: updatedSKU.unitPrice,
      lead_time_days: updatedSKU.leadTimeDays,
      notes: updatedSKU.notes,
      status: updatedSKU.status,
    });

    await loadSKUs();
    setSelectedSKU(updatedSKU);

    const details = changes.length > 0
      ? `Updated SKU ${updatedSKU.code}. Changes: ${changes.join(', ')}`
      : `Updated SKU ${updatedSKU.code} (minor details)`;

    logAction('Edit SKU', details);
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
    supplierFilter !== 'All Suppliers' ||
    brandFilter !== 'All Brands' ||
    categoryFilter !== 'All';

  const handleClearFilters = () => {
    setSearchQuery('');
    setSupplierFilter('All Suppliers');
    setBrandFilter('All Brands');
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

  return (
    <div className="sku-management">
      <div className="sku-content">
        {/* Page Header */}
        <div className="sku-page-header">
          <div>
            <h2 className="sku-page-title">SKU Ledger</h2>
            <p className="sku-page-subtitle">
              Add, edit, or deactivate products from the inventory system. The master record the forecasts draw from.
            </p>
          </div>
          <button className="add-sku-btn" onClick={() => setIsAddModalOpen(true)}>
            <Plus size={16} />
            Add SKU
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="sku-top-tabs">
          <button
            className={`sku-tab-btn ${activeTab === 'ALL' ? 'active' : ''}`}
            onClick={() => setActiveTab('ALL')}
          >
            <Package size={16} color="#3b82f6" className="sku-tab-icon" />
            All SKUs
          </button>
          <button
            className={`sku-tab-btn ${activeTab === 'ACTIVE' ? 'active' : ''}`}
            onClick={() => setActiveTab('ACTIVE')}
          >
            <CheckCircle size={16} color="#38a169" className="sku-tab-icon" />
            Active SKUs
          </button>
          <button
            className={`sku-tab-btn ${activeTab === 'DISABLED' ? 'active' : ''}`}
            onClick={() => setActiveTab('DISABLED')}
          >
            <XCircle size={16} color="#e53e3e" className="sku-tab-icon" />
            Disabled SKUs
          </button>
        </div>

        {/* Summary Cards */}
        <div className="sku-summary-grid">
          <div className="sku-summary-card summary-total">
            <span className="summary-label">TOTAL SKUS</span>
            <span className="summary-value">{totalSKUs}</span>
          </div>
          <div className="sku-summary-card summary-active">
            <span className="summary-label">ACTIVE</span>
            <span className="summary-value">{activeSKUs}</span>
          </div>
          <div className="sku-summary-card summary-inactive">
            <span className="summary-label">DISABLED</span>
            <span className="summary-value">{inactiveSKUs}</span>
          </div>
        </div>

        {loading && <p className="sku-page-subtitle">Loading SKUs…</p>}
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
                                <span className="sku-row-brand">{sku.brand}</span>
                              </div>
                              <div className="sku-row-middle">
                                <span className="sku-row-product">{sku.product}</span>
                                <span className="sku-row-supplier">{sku.supplier}</span>
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
                            {recentlyViewedSKUs.map((sku) => (
                              <div
                                key={sku.id}
                                className="sku-suggestion-row"
                                onClick={() => handleSelectSuggestion(sku)}
                              >
                                <div className="sku-row-left">
                                  <span className="sku-row-code">{sku.code}</span>
                                  <span className="sku-row-brand">{sku.brand}</span>
                                </div>
                                <div className="sku-row-middle">
                                  <span className="sku-row-product">{sku.product}</span>
                                  <span className="sku-row-supplier">{sku.supplier}</span>
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
                                  <span className="sku-row-brand">{sku.brand}</span>
                                </div>
                                <div className="sku-row-middle">
                                  <span className="sku-row-product">{sku.product}</span>
                                  <span className="sku-row-supplier">{sku.supplier}</span>
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
                  <span className="sku-filter-icon-label"><Building size={12} /> Supplier:</span>
                  <select
                    value={supplierFilter}
                    onChange={(e) => setSupplierFilter(e.target.value)}
                  >
                    {suppliers.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>

                <div className="sku-filter-select-wrapper">
                  <span className="sku-filter-icon-label"><Tag size={12} /> Brand:</span>
                  <select
                    value={brandFilter}
                    onChange={(e) => setBrandFilter(e.target.value)}
                  >
                    {brands.map(b => <option key={b} value={b}>{b}</option>)}
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

                {supplierFilter !== 'All Suppliers' && (
                  <span className="sku-active-chip">
                    Supplier: {supplierFilter}
                    <button className="sku-chip-remove" onClick={() => setSupplierFilter('All Suppliers')}>
                      <X size={12} />
                    </button>
                  </span>
                )}

                {brandFilter !== 'All Brands' && (
                  <span className="sku-active-chip">
                    Brand: {brandFilter}
                    <button className="sku-chip-remove" onClick={() => setBrandFilter('All Brands')}>
                      <X size={12} />
                    </button>
                  </span>
                )}

                {categoryFilter !== 'All' && (
                  <span className="sku-active-chip">
                    Category: Category {categoryFilter}
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
            <div className="sku-table-wrapper">
              <table className="sku-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>SKU CODE</th>
                    <th>BRAND</th>
                    <th>SUPPLIER</th>
                    <th>PRODUCT</th>
                    <th>CAT</th>
                    <th>LEAD TIME (DAYS)</th>
                    <th>REORDER PT</th>
                    <th>STATUS</th>
                    <th>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSKUs.map((sku, index) => (
                    <tr
                      key={sku.id}
                      id={`sku-row-${sku.id}`}
                      className={highlightedSKUId === sku.id ? 'highlighted-row-flash' : ''}
                    >
                      <td className="row-number">{index + 1}</td>
                      <td
                        className="sku-code-cell"
                        style={{ cursor: 'pointer' }}
                        onClick={() => handleOpenViewModal(sku)}
                        title="Click to view full SKU details"
                      >
                        {sku.code}
                      </td>
                      <td>{sku.brand}</td>
                      <td className="supplier-cell">{sku.supplier}</td>
                      <td className="product-cell">
                        {(() => {
                          const { name, weight } = parseProductAndWeight(sku.product);
                          return (
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                              <span className="sku-product-name">{name}</span>
                              {weight && (
                                <span className="sku-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                                  {weight}
                                </span>
                              )}
                            </div>
                          );
                        })()}
                      </td>
                      <td><span className={getCatClass(sku.cat)}>{sku.cat || '—'}</span></td>
                      <td>{sku.leadTime || '—'}</td>
                      <td className="reorder-cell">{sku.reorderPt != null ? sku.reorderPt.toLocaleString() : '—'}</td>
                      <td>
                        <span className={`status-badge ${sku.status === 'ACTIVE' ? 'status-active' : 'status-inactive'}`}>
                          {sku.status}
                        </span>
                      </td>
                      <td>
                        <button
                          className="view-btn"
                          onClick={() => handleOpenViewModal(sku)}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredSKUs.length === 0 && (
                    <tr>
                      <td colSpan="10" className="no-results">No data for this selection.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <AddSKUModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onAdd={handleAddSKU}
        brands={brands.filter(b => b !== 'All Brands')}
      />

      <ViewSKUModal
        isOpen={isViewModalOpen}
        sku={selectedSKU}
        onClose={() => setIsViewModalOpen(false)}
        onEdit={handleOpenEditModal}
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
