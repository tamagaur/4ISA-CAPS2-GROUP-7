import React, { useState } from 'react';
import { Loader2, ArrowDown, ClipboardList, ListChecks } from 'lucide-react';
import ReorderModal from './ReorderModal';
import OverrideReasonModal from './OverrideReasonModal';
import { getCurrentUser } from '../auth';
import './ReorderRecommendations.css';

// threeWeekRuleQty = what SSM's blanket "three weeks of stock" rule would
// have ordered, computed here as the same baseline used pre-LP (rop * 7/3,
// rounded) so the dashboard can show the paper's headline comparison
// (backlog #56) instead of just the LP output in isolation.
const mockReorderData = [
  { id: 1, sku: 'SKU-4721', brand: 'Unilever', product: 'Surf Powder Detergent 1kg', rop: 120, stock: 45, orderQty: 200, threeWeekRuleQty: 280, unitCost: 122.5, urgency: 'CRITICAL', estCost: '₱24,500', safetyStock: 34, leadTimeDays: 7, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
  { id: 2, sku: 'SKU-8934', brand: 'Del Monte', product: 'Pineapple Juice 1L', rop: 80, stock: 12, orderQty: 180, threeWeekRuleQty: 210, unitCost: 180, urgency: 'CRITICAL', estCost: '₱32,400', safetyStock: 22, leadTimeDays: 10, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
  { id: 3, sku: 'SKU-2891', brand: 'Unilever', product: 'Knorr Cubes 8g', rop: 150, stock: 78, orderQty: 150, threeWeekRuleQty: 175, unitCost: 125, urgency: 'URGENT', estCost: '₱18,750', safetyStock: 40, leadTimeDays: 5, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
  { id: 4, sku: 'SKU-1523', brand: 'Del Monte', product: 'Tomato Sauce 250g', rop: 100, stock: 89, orderQty: 140, threeWeekRuleQty: 165, unitCost: 107.1, urgency: 'URGENT', estCost: '₱15,000', safetyStock: 26, leadTimeDays: 10, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
  { id: 5, sku: 'SKU-7642', brand: 'Unilever', product: 'Dove Shampoo 340ml', rop: 90, stock: 56, orderQty: 120, threeWeekRuleQty: 130, unitCost: 118.3, urgency: 'PLANNED', estCost: '₱14,200', safetyStock: 24, leadTimeDays: 7, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
  { id: 6, sku: 'SKU-9234', brand: 'Del Monte', product: 'Sweet Corn 425g', rop: 140, stock: 102, orderQty: 160, threeWeekRuleQty: 155, unitCost: 73.1, urgency: 'PLANNED', estCost: '₱11,700', safetyStock: 38, leadTimeDays: 10, lpBreakdown: { cost: 45, service: 35, capacity: 20 }, actionStatus: null, loadingAction: null },
];

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
  const [data, setData] = useState(mockReorderData);
  const [selectedItem, setSelectedItem] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('RECOMMENDATIONS');

  // Pending override awaiting a reason (Dismiss only — Accept logs immediately).
  // Two states only, matching LP_Recommendation.status in schema.sql:
  // CHECK (status IN ('pending', 'accepted', 'dismissed')) — no "hold" state exists.
  const [pendingOverride, setPendingOverride] = useState(null); // { item, action }
  const [decisionLog, setDecisionLog] = useState([]);

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
      {/* Summary Cards */}
      <div className="reorder-summary-grid">
        <div className="reorder-summary-card card-red">
          <div className="card-content">
            <span className="reorder-card-label">CRITICAL SKUS</span>
            <span className="reorder-card-value">2</span>
          </div>
        </div>
        <div className="reorder-summary-card card-yellow">
          <div className="card-content">
            <span className="reorder-card-label">URGENT SKUS</span>
            <span className="reorder-card-value">2</span>
            <span className="reorder-card-desc">Within 3 days</span>
          </div>
        </div>
        <div className="reorder-summary-card card-blue">
          <div className="card-content">
            <span className="reorder-card-label">LP BUDGET</span>
            <span className="reorder-card-value">₱930.4k</span>
            <span className="reorder-card-desc">LP - optimized</span>
          </div>
        </div>
        <div className="reorder-summary-card card-green">
          <div className="card-content">
            <span className="reorder-card-label">WAREHOUSE UTIL.</span>
            <span className="reorder-card-value">68%</span>
            <span className="reorder-card-desc">of capacity</span>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="reorder-table-wrapper">
        <table className="reorder-table">
          <thead>
            <tr>
              <th>SKU</th>
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
            {data.map((item) => {
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
