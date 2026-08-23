import React, { useState, useMemo, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Loader2, ArrowDown, ClipboardList, ListChecks } from 'lucide-react';
import ReorderModal from './ReorderModal';
import OverrideReasonModal from './OverrideReasonModal';
import { getCurrentUser } from '../auth';
import { logAction } from '../utils/auditLogger';
import { getMockDashboard } from '../data/mockData';
import './ReorderRecommendations.css';

// MAPE_GATE mirrors the Dashboard's Forecast health gate (mockData.js's
// forecastHealth: pass under 20% error, fallback/manual review above it) —
// same threshold, applied fresh to this page's own rows so "Manual
// review"'s count and its click-to-filter correspond to real rows in the
// table below, not a population figure from a different tracked SKU set.
const MAPE_GATE = 20;

// threeWeekRuleQty = what SSM's blanket "three weeks of stock" rule would
// have ordered, computed here as the same baseline used pre-LP (rop * 7/3,
// rounded) so the dashboard can show the paper's headline comparison
// (backlog #56) instead of just the LP output in isolation.
//
// mapeError = this SKU's forecast error (%) for the cycle just solved —
// not previously tracked on this page; added so "Manual review" (KPI card
// 4) has a real per-row figure to count and filter by.
//
// Unilever has true per-SKU data.
const UNILEVER_REORDER_DATA = [
  { id: 1, sku: 'SKU-4721', brand: 'Unilever', product: 'Surf Powder Detergent 1kg', rop: 120, stock: 45, orderQty: 200, threeWeekRuleQty: 280, unitCost: 122.5, urgency: 'CRITICAL', estCost: '₱24,500', safetyStock: 34, leadTimeDays: 7, mapeError: 14, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
  { id: 3, sku: 'SKU-2891', brand: 'Unilever', product: 'Knorr Cubes 8g', rop: 150, stock: 78, orderQty: 150, threeWeekRuleQty: 175, unitCost: 125, urgency: 'URGENT', estCost: '₱18,750', safetyStock: 40, leadTimeDays: 5, mapeError: 27, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
  { id: 5, sku: 'SKU-7642', brand: 'Unilever', product: 'Dove Shampoo 340ml', rop: 90, stock: 56, orderQty: 120, threeWeekRuleQty: 130, unitCost: 118.3, urgency: 'PLANNED', estCost: '₱14,200', safetyStock: 24, leadTimeDays: 7, mapeError: 11, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
];

// Del Monte has no SKU-level data anywhere in this project — these rows
// aggregate what used to be fabricated per-SKU Del Monte rows into
// categories (CAT- codes).
const DELMONTE_REORDER_DATA = [
  { id: 101, sku: 'CAT-JUICES', brand: 'Del Monte', product: 'Juices', rop: 80, stock: 12, orderQty: 180, threeWeekRuleQty: 210, unitCost: 180, urgency: 'CRITICAL', estCost: '₱32,400', safetyStock: 22, leadTimeDays: 10, mapeError: 24, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
  { id: 102, sku: 'CAT-SAUCES-VEG', brand: 'Del Monte', product: 'Sauces & Vegetables', rop: 240, stock: 191, orderQty: 300, threeWeekRuleQty: 320, unitCost: 89.0, urgency: 'URGENT', estCost: '₱26,700', safetyStock: 64, leadTimeDays: 10, mapeError: 9, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
];

const REORDER_DATA_BY_PRINCIPAL = {
  unilever: UNILEVER_REORDER_DATA,
  delmonte: DELMONTE_REORDER_DATA,
  all: [...UNILEVER_REORDER_DATA, ...DELMONTE_REORDER_DATA],
};

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

const formatTimestamp = (date) =>
  date.toLocaleString('en-PH', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

const ReorderRecommendations = () => {
  const { principal } = useOutletContext() || { principal: 'all' };
  const grain = GRAIN_BY_PRINCIPAL[principal] ?? 'mixed';
  const sourceData = useMemo(() => REORDER_DATA_BY_PRINCIPAL[principal] ?? REORDER_DATA_BY_PRINCIPAL.all, [principal]);

  // Cards 1-2 (Order value, Capital saved) are population-level financial
  // figures with no equivalent in this page's own table (there's no
  // "offered by suppliers" concept in rop/stock/orderQty) — read from the
  // same shared mockData.js the Dashboard uses, so they can't disagree
  // with it. Cards 3-4 (Below reorder point, Manual review) instead come
  // from THIS page's own `data` below, because card 4 must correspond to
  // real, clickable rows in the table beneath it — mockData.js tracks a
  // different illustrative SKU set entirely, so it can't be the source of
  // truth for something the reader is meant to click and filter by.
  const dashboardKpis = useMemo(() => getMockDashboard(principal).kpis, [principal]);

  const [data, setData] = useState(sourceData);
  const [selectedItem, setSelectedItem] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('RECOMMENDATIONS');
  const [showOnlyReview, setShowOnlyReview] = useState(false);

  // Pending override awaiting a reason (Dismiss only — Accept logs immediately).
  // Two states only, matching LP_Recommendation.status in schema.sql:
  // CHECK (status IN ('pending', 'accepted', 'dismissed')) — no "hold" state exists.
  const [pendingOverride, setPendingOverride] = useState(null); // { item, action }
  const [decisionLog, setDecisionLog] = useState([]);

  // Re-source recommendations when the principal filter changes. In-session
  // accept/dismiss actions are tied to whichever principal's view they were
  // made in and reset with it. The manual-review filter resets too — a
  // filter set under one principal shouldn't silently carry over and hide
  // rows under another.
  useEffect(() => {
    setData(sourceData);
    setShowOnlyReview(false);
  }, [sourceData]);

  // "Below reorder point" — every row on this page is, by definition, a
  // reorder recommendation (i.e. already below its ROP), so this is the
  // full table's count, not a separate filtered figure.
  const belowRopCount = data.length;

  // "Manual review" — rows whose forecast error exceeds the same 20% MAPE
  // gate the Dashboard's Forecast health card uses (MAPE_GATE), computed
  // fresh on this page's own rows.
  const reviewItems = useMemo(() => data.filter((item) => item.mapeError > MAPE_GATE), [data]);
  const reviewCount = reviewItems.length;
  const reliableCount = data.length - reviewCount;
  // Every row in this table is already below its reorder point (see
  // belowRopCount above), so every manual-review row necessarily is too —
  // the two cards' counts describe overlapping, not separate, groups.
  const reviewBelowRopOverlap = reviewCount;

  const displayedData = showOnlyReview ? reviewItems : data;

  const handleOpenDetails = (item) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  const logDecision = (item, action, reason) => {
    const user = getCurrentUser();
    setDecisionLog(prev => [
      {
        id: `${item.id}-${Date.now()}`,
        sku: item.sku,
        product: item.product,
        action,
        reason,
        decidedBy: user?.email || 'unknown user',
        timestamp: formatTimestamp(new Date()),
      },
      ...prev,
    ]);
    
    // Also push to the global audit log
    logAction(`Reorder Recommendation ${action === 'ACCEPTED' ? 'Accepted' : 'Dismissed'}`, `SKU ${item.sku}: ${reason}`);
  };

  const applyAction = (id, actionType) => {
    setData(prev => prev.map(item =>
      item.id === id ? { ...item, loadingAction: actionType } : item
    ));

    // Simulate API call
    setTimeout(() => {
      setData(prev => prev.map(item =>
        item.id === id ? { ...item, loadingAction: null, actionStatus: actionType } : item
      ));
    }, 800);
  };

  const handleAction = (item, actionType) => {
    if (actionType === 'ACCEPTED') {
      applyAction(item.id, actionType);
      logDecision(item, actionType, 'Accepted the LP-recommended order quantity as-is.');
      return;
    }
    // Dismiss deviates from the recommendation — require a reason first
    setPendingOverride({ item, action: actionType });
  };

  const handleConfirmOverride = (reason) => {
    const { item, action } = pendingOverride;
    applyAction(item.id, action);
    logDecision(item, action, reason);
    setPendingOverride(null);
  };

  const getUrgencyBadge = (urgency) => {
    switch (urgency) {
      case 'CRITICAL': return 'urgency-badge badge-critical';
      case 'URGENT': return 'urgency-badge badge-urgent';
      case 'PLANNED': return 'urgency-badge badge-planned';
      default: return 'urgency-badge';
    }
  };

  const getLogActionBadge = (action) => {
    switch (action) {
      case 'ACCEPTED': return 'status-badge status-accepted';
      case 'DISMISSED': return 'status-badge status-dismissed';
      default: return 'status-badge';
    }
  };

  const renderActionColumn = (item) => {
    if (item.loadingAction) {
      return (
        <div className="action-status-container">
          <Loader2 className="spinner-icon" size={16} />
          <span className="loading-text">Processing...</span>
        </div>
      );
    }

    if (item.actionStatus) {
      return (
        <div className="action-status-container">
          <span className={`status-badge status-${item.actionStatus.toLowerCase()}`}>
            {item.actionStatus}
          </span>
        </div>
      );
    }

    return (
      <div className="action-buttons">
        <button className="action-btn accept-btn" onClick={() => handleAction(item, 'ACCEPTED')}>Accept</button>
        <button className="action-btn dismiss-btn" onClick={() => handleAction(item, 'DISMISSED')}>Dismiss</button>
      </div>
    );
  };

  const renderRecommendationsTab = () => (
    <>
      {/* Summary Cards — same black accent on all four; colour lives only
          in the status chip on the two cards that flag a problem. */}
      <div className="reorder-summary-grid">
        <div className="reorder-summary-card reorder-card-neutral">
          <div className="card-content">
            <span className="reorder-card-label">ORDER VALUE</span>
            <span className="reorder-card-value">₱{dashboardKpis.cashFreed.offeredM}M</span>
            <span className="reorder-card-desc">of ₱{dashboardKpis.allocationOffered.valueM}M offered by suppliers</span>
          </div>
        </div>
        <div className="reorder-summary-card reorder-card-neutral">
          <div className="card-content">
            <span className="reorder-card-label">CAPITAL SAVED</span>
            <span className="reorder-card-value">₱{dashboardKpis.cashFreed.valueM}M</span>
            <span className="reorder-card-desc">{dashboardKpis.cashFreed.pctLess}% less capital tied up</span>
          </div>
        </div>
        <div className="reorder-summary-card reorder-card-neutral">
          <div className="card-content">
            <div className="reorder-card-label-row">
              <span className="reorder-card-label">BELOW REORDER POINT</span>
              <span className="reorder-card-chip reorder-card-chip-danger">ACTION</span>
            </div>
            <span className="reorder-card-value">{belowRopCount} products</span>
            <span className="reorder-card-desc">Short of demand even at the full offer</span>
          </div>
        </div>
        <div className="reorder-summary-card reorder-card-neutral">
          <div className="card-content">
            <div className="reorder-card-label-row">
              <span className="reorder-card-label">MANUAL REVIEW</span>
              <span className="reorder-card-chip reorder-card-chip-warning">REVIEW</span>
            </div>
            <button
              type="button"
              className="reorder-card-value reorder-card-value-clickable"
              onClick={() => setShowOnlyReview((v) => !v)}
              disabled={reviewCount === 0}
              title={reviewCount > 0 ? 'Filter the table below to these products' : undefined}
            >
              {reviewCount} products
            </button>
            <span className="reorder-card-desc">Forecast too irregular to rely on</span>
            <span className="reorder-card-delta">{reliableCount} of {data.length} forecasts are reliable</span>
            {reviewCount > 0 && (
              <span className="reorder-card-delta">All {reviewBelowRopOverlap} also below reorder point</span>
            )}
          </div>
        </div>
      </div>

      {showOnlyReview && (
        <p className="reorder-filter-note">
          Showing only the {reviewCount} product{reviewCount === 1 ? '' : 's'} flagged for manual review —{' '}
          <button type="button" className="reorder-filter-clear" onClick={() => setShowOnlyReview(false)}>
            clear filter
          </button>
        </p>
      )}

      {(grain === 'category' || grain === 'mixed') && (
        <p className="reorder-grain-note">
          Del Monte is analysed at category level — no SKU-level data is available from this principal
        </p>
      )}

      {/* Table */}
      <div className="reorder-table-wrapper">
        <table className="reorder-table">
          <thead>
            <tr>
              <th>{grain === 'category' ? 'CATEGORY' : 'SKU'}</th>
              <th>BRAND</th>
              <th>PRODUCT</th>
              <th>ROP</th>
              <th>CURRENT STOCK</th>
              <th>LP QTY <span className="th-sub">vs 3-WK RULE</span></th>
              <th>URGENCY</th>
              <th>EST. COST</th>
              <th>DETAILS</th>
              <th>ACTION</th>
            </tr>
          </thead>
          <tbody>
            {displayedData.map((item) => {
              const savedUnits = item.threeWeekRuleQty - item.orderQty;
              const savedPct = Math.round((savedUnits / item.threeWeekRuleQty) * 100);
              return (
                <tr key={item.id}>
                  <td className="reorder-sku-cell">{formatSKU(item.sku)}</td>
                  <td>{item.brand}</td>
                  <td className="reorder-product-cell">
                    {(() => {
                      const { name, weight } = parseProductAndWeight(item.product);
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                          <span className="reorder-product-name">{name}</span>
                          {weight && (
                            <span className="reorder-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                              {weight}
                            </span>
                          )}
                        </div>
                      );
                    })()}
                  </td>
                  <td>{item.rop}</td>
                  <td className="reorder-stock-cell" style={{ color: item.stock < item.rop * 0.5 ? '#e53e3e' : item.stock < item.rop ? '#d69e2e' : '#4a5568' }}>{item.stock}</td>
                  <td className="reorder-qty-cell">
                    <div className="reorder-qty-compare">
                      <span className="reorder-qty-main">{item.orderQty}</span>
                      <span className="reorder-qty-baseline">
                        <ArrowDown size={11} className="reorder-qty-down-icon" />
                        {savedPct}% vs {item.threeWeekRuleQty}
                      </span>
                    </div>
                  </td>
                  <td>
                    <span className={getUrgencyBadge(item.urgency)}>
                      {item.urgency}
                    </span>
                  </td>
                  <td className="reorder-cost-cell">{item.estCost}</td>
                  <td>
                    <button className="details-btn" onClick={() => handleOpenDetails(item)}>Details</button>
                  </td>
                  <td>
                    {renderActionColumn(item)}
                  </td>
                </tr>
              );
            })}
            {displayedData.length === 0 && (
              <tr>
                <td colSpan="10" className="reorder-no-results">
                  {showOnlyReview ? 'No products currently need manual review.' : 'No data for this selection.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );

  const renderDecisionLogTab = () => (
    <div className="reorder-table-wrapper">
      <table className="reorder-table reorder-log-table">
        <thead>
          <tr>
            <th>WHEN</th>
            <th>SKU</th>
            <th>PRODUCT</th>
            <th>ACTION</th>
            <th>REASON</th>
            <th>DECIDED BY</th>
          </tr>
        </thead>
        <tbody>
          {decisionLog.length === 0 ? (
            <tr>
              <td colSpan="6" className="reorder-log-empty">
                No decisions recorded yet this session. Accept or dismiss a recommendation to see it logged here.
              </td>
            </tr>
          ) : (
            decisionLog.map((entry) => (
              <tr key={entry.id}>
                <td className="reorder-log-when">{entry.timestamp}</td>
                <td className="reorder-sku-cell" style={{ cursor: 'default' }}>{formatSKU(entry.sku)}</td>
                <td className="reorder-product-cell">{entry.product}</td>
                <td>
                  <span className={getLogActionBadge(entry.action)}>
                    {entry.action}
                  </span>
                </td>
                <td className="reorder-log-reason">{entry.reason}</td>
                <td className="reorder-log-user">{entry.decidedBy}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="reorder-page">
      <div className="reorder-content">
        {/* Page Header */}
        <div className="reorder-page-header">
          <h2 className="reorder-page-title">
            Reorder Recommendations
          </h2>
          <p className="reorder-page-subtitle">
            LP-optimized purchase quantities for Category A SKUs. Minimizes total inventory cost while preventing stockouts.
          </p>
        </div>

        {/* Tab Navigation */}
        <div className="reorder-tabs-row">
          <button
            className={`reorder-tab-btn ${activeTab === 'RECOMMENDATIONS' ? 'active' : ''}`}
            onClick={() => setActiveTab('RECOMMENDATIONS')}
          >
            <ClipboardList size={14} />
            RECOMMENDATIONS
          </button>
          <button
            className={`reorder-tab-btn ${activeTab === 'DECISION_LOG' ? 'active' : ''}`}
            onClick={() => setActiveTab('DECISION_LOG')}
          >
            <ListChecks size={14} />
            DECISION LOG {decisionLog.length > 0 && <span className="reorder-tab-count">{decisionLog.length}</span>}
          </button>
        </div>

        {activeTab === 'RECOMMENDATIONS' ? renderRecommendationsTab() : renderDecisionLogTab()}
      </div>

      <ReorderModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        data={selectedItem}
      />

      <OverrideReasonModal
        isOpen={Boolean(pendingOverride)}
        item={pendingOverride?.item}
        onCancel={() => setPendingOverride(null)}
        onConfirm={handleConfirmOverride}
      />
    </div>
  );
};

export default ReorderRecommendations;
