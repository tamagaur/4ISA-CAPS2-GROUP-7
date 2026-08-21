// frontend/src/api/mockDashboard.js
//
// The ONLY file that touches mock data for the dashboard. dashboard.js
// imports getMockDashboard() and knows nothing about how the numbers are
// produced — when the real backend exists, this file disappears and
// dashboard.js's fetch call replaces it with no other changes needed.
//
// KPIs reflect what the project can ACTUALLY produce from real data:
//   bad_order_value    → SalesReturn_Fact / bo_monitoring_view (value-based only;
//                        bo_units is always NULL in real source files)
//   bad_order_incidents → COUNT of OPEN + UNDER INVESTIGATION rows
//   reorder_items      → LP_Recommendation (item count below ROP)
//   reorder_value      → LP_Recommendation (total ₱ value of items to order)
//
// Removed from mock (can't be produced without Inventory_Fact Transform fix):
//   trapped_capital, weeks_of_cover, stockout_rate
//
// Primary chart changed from Cover Trend → Bad Order Trend (stacked bar by
// reason: Expiry / Transport Damage / Storage Issue) — all from SalesReturn_Fact.

const MS_PER_STEP = 0.02;

function periodSeed(from) {
  const d = new Date(from);
  const month = Number.isNaN(d.getTime()) ? 0 : d.getUTCMonth();
  const year  = Number.isNaN(d.getTime()) ? 2026 : d.getUTCFullYear();
  return ((month + year) % 6) - 1;
}

function applySeed(base, seed, stepPct) {
  return Number((base * (1 + seed * stepPct)).toFixed(1));
}

// A loss metric where higher is always worse. direction is decided here once.
function lossMetric(value, baseline) {
  const delta = Number((value - baseline).toFixed(1));
  return {
    value,
    delta_vs_prev: delta,
    direction: delta > 0 ? 'worse' : 'better',
  };
}

// Bad Order Trend series — weekly bad order value (₱k) broken down by reason.
// Last 12 weeks. Values represent ₱k lost per week per reason type.
// Computed from SalesReturn_Fact grouped by (week, return_type) in real backend.
const BAD_ORDER_SERIES_SHAPE = [
  { expiry: 38, transport_damage: 25, storage_issue: 12 },
  { expiry: 42, transport_damage: 30, storage_issue: 18 },
  { expiry: 35, transport_damage: 28, storage_issue: 15 },
  { expiry: 48, transport_damage: 22, storage_issue: 20 },
  { expiry: 40, transport_damage: 35, storage_issue: 14 },
  { expiry: 44, transport_damage: 27, storage_issue: 17 },
  { expiry: 52, transport_damage: 31, storage_issue: 22 },
  { expiry: 38, transport_damage: 33, storage_issue: 19 },
  { expiry: 46, transport_damage: 29, storage_issue: 16 },
  { expiry: 41, transport_damage: 36, storage_issue: 21 },
  { expiry: 50, transport_damage: 32, storage_issue: 18 },
  { expiry: 45, transport_damage: 35, storage_issue: 16 }, // current week
];

function buildBadOrderSeries(seed) {
  return BAD_ORDER_SERIES_SHAPE.map((point, i) => ({
    period: `Wk ${i + 1}`,
    expiry:           Math.max(0, Math.round(point.expiry           * (1 + seed * 0.05))),
    transport_damage: Math.max(0, Math.round(point.transport_damage * (1 + seed * 0.04))),
    storage_issue:    Math.max(0, Math.round(point.storage_issue    * (1 + seed * 0.03))),
  }));
}

// Profiles — only fields that have a real data source are kept.
// stockValue / weeklySales / stockoutBase removed (Inventory_Fact Transform
// is broken; those KPIs cannot be produced from real data yet).
const UNILEVER_PROFILE = {
  boValueBase:     96,  // ₱k total bad order value baseline
  reorderCritical:  2,
  reorderValue:  1.65,  // ₱M total order value
  grain: 'sku',
  tiers: [
    { tier: 'A', sku_count: 42, revenue_share: 68 },
    { tier: 'B', sku_count: 96, revenue_share: 24 },
    { tier: 'C', sku_count: 180, revenue_share: 8  },
  ],
  reorderAlerts: [
    { sku_id: 'SKU-4721', product_name: 'Surf Powder Detergent 1kg',    current_stock:  45, rop: 120, urgency: 'CRITICAL' },
    { sku_id: 'SKU-7821', product_name: 'Dove Shampoo 340ml',            current_stock:  58, rop: 130, urgency: 'CRITICAL' },
    { sku_id: 'SKU-9012', product_name: 'Lux Bar Soap 135g',             current_stock:  90, rop: 150, urgency: 'URGENT'   },
    { sku_id: 'SKU-6543', product_name: 'Creamsilk Conditioner 180ml',   current_stock: 112, rop: 140, urgency: 'URGENT'   },
    { sku_id: 'SKU-8901', product_name: 'Breeze Detergent Powder 500g',  current_stock: 130, rop: 155, urgency: 'URGENT'   },
  ],
  badOrders: [
    { incident_id: 'INC-2024-135', product_name: 'Dove Shampoo 340ml',          reason: 'Transport Damage', status: 'OPEN'                 },
    { incident_id: 'INC-2024-131', product_name: 'Rexona Deodorant 40ml',       reason: 'Expiry',           status: 'RESOLVED'             },
    { incident_id: 'INC-2024-128', product_name: 'Lux Bar Soap 135g',           reason: 'Storage Issue',    status: 'UNDER INVESTIGATION'  },
    { incident_id: 'INC-2024-124', product_name: 'Surf Powder Detergent 1kg',   reason: 'Transport Damage', status: 'OPEN'                 },
    { incident_id: 'INC-2024-119', product_name: "Pond's Powder 50g",           reason: 'Expiry',           status: 'RESOLVED'             },
  ],
};

const DELMONTE_PROFILE = {
  boValueBase:    134,  // ₱k — higher per-incident value at category grain
  reorderCritical:  1,
  reorderValue:  0.98,
  grain: 'category',
  tiers: [
    { tier: 'A', sku_count: 3, revenue_share: 71 },
    { tier: 'B', sku_count: 5, revenue_share: 21 },
    { tier: 'C', sku_count: 4, revenue_share: 8  },
  ],
  reorderAlerts: [
    { sku_id: 'CAT-Canned Fruits',  product_name: 'Canned Fruits',  current_stock: 210, rop: 320, urgency: 'CRITICAL' },
    { sku_id: 'CAT-Pasta & Sauces', product_name: 'Pasta & Sauces', current_stock: 260, rop: 340, urgency: 'URGENT'   },
    { sku_id: 'CAT-Juices',         product_name: 'Juices',         current_stock: 400, rop: 460, urgency: 'URGENT'   },
  ],
  badOrders: [
    { incident_id: 'INC-2024-134', product_name: 'Tomato Sauce (category)',    reason: 'Expiry',           status: 'RESOLVED'             },
    { incident_id: 'INC-2024-133', product_name: 'Sweet Corn (category)',      reason: 'Storage Issue',    status: 'UNDER INVESTIGATION'  },
    { incident_id: 'INC-2024-130', product_name: 'Pineapple Juice (category)', reason: 'Transport Damage', status: 'OPEN'                 },
    { incident_id: 'INC-2024-126', product_name: 'Fruit Cocktail (category)',  reason: 'Expiry',           status: 'RESOLVED'             },
    { incident_id: 'INC-2024-121', product_name: 'Spaghetti Pasta (category)', reason: 'Storage Issue',    status: 'UNDER INVESTIGATION'  },
  ],
};

function combineTiers(a, b) {
  return ['A', 'B', 'C'].map((letter) => {
    const ta = a.find((t) => t.tier === letter);
    const tb = b.find((t) => t.tier === letter);
    return {
      tier: letter,
      sku_count:     ta.sku_count     + tb.sku_count,
      revenue_share: Math.round((ta.revenue_share + tb.revenue_share) / 2),
    };
  });
}

const ALL_PROFILE = {
  boValueBase:     UNILEVER_PROFILE.boValueBase + DELMONTE_PROFILE.boValueBase,
  reorderCritical: UNILEVER_PROFILE.reorderCritical + DELMONTE_PROFILE.reorderCritical,
  reorderValue:    Number((UNILEVER_PROFILE.reorderValue + DELMONTE_PROFILE.reorderValue).toFixed(2)),
  grain: 'mixed',
  tiers: combineTiers(UNILEVER_PROFILE.tiers, DELMONTE_PROFILE.tiers),
  reorderAlerts: [
    ...UNILEVER_PROFILE.reorderAlerts.slice(0, 2),
    ...DELMONTE_PROFILE.reorderAlerts.slice(0, 2),
  ],
  badOrders: [
    ...UNILEVER_PROFILE.badOrders.slice(0, 3),
    ...DELMONTE_PROFILE.badOrders.slice(0, 3),
  ],
};

const PROFILES = {
  unilever: UNILEVER_PROFILE,
  delmonte: DELMONTE_PROFILE,
  all:      ALL_PROFILE,
};

function buildPrincipalData(key, profile, seed) {
  const unitNoun = profile.grain === 'category' ? 'categories' : profile.grain === 'mixed' ? 'items' : 'products';

  // ── KPI 1: Bad Order Value (₱k) ──────────────────────────────────────────
  // Source: SalesReturn_Fact.net_amount filtered to bad-order return types,
  // aggregated by period. Value-based only — bo_units is always NULL in real
  // source files (DATABASE_ARCHITECTURE.md §7).
  const boValue = applySeed(profile.boValueBase, seed, MS_PER_STEP * 1.25);
  const { value: boVal, delta_vs_prev: boDelta, direction: boDir } = lossMetric(boValue, profile.boValueBase);
  // Rough reason split derived from the actual bad_orders list's reason distribution.
  const expiryCount        = profile.badOrders.filter(b => b.reason === 'Expiry').length;
  const transportCount     = profile.badOrders.filter(b => b.reason === 'Transport Damage').length;
  const storageCount       = profile.badOrders.filter(b => b.reason === 'Storage Issue').length;
  const total              = expiryCount + transportCount + storageCount || 1;
  const boByReason = {
    expiry:           Number((boVal * expiryCount    / total).toFixed(1)),
    transport_damage: Number((boVal * transportCount / total).toFixed(1)),
    storage_issue:    Number((boVal * storageCount   / total).toFixed(1)),
  };

  // ── KPI 2: Active Incidents ───────────────────────────────────────────────
  // Source: COUNT of SalesReturn_Fact rows where status IN ('OPEN',
  // 'UNDER INVESTIGATION') for the selected period.
  const openCount        = profile.badOrders.filter(b => b.status === 'OPEN').length;
  const underInvCount    = profile.badOrders.filter(b => b.status === 'UNDER INVESTIGATION').length;
  const resolvedCount    = profile.badOrders.filter(b => b.status === 'RESOLVED').length;
  const activeCount      = openCount + underInvCount;
  // Seed-driven delta so medium/high periods show slight movement.
  const activeBaseline   = Math.max(0, activeCount - (seed > 0 ? 1 : 0));
  const activeDelta      = activeCount - activeBaseline;

  // ── KPI 3: Items to Reorder ───────────────────────────────────────────────
  // Source: COUNT of LP_Recommendation rows for the current planning_cycle_date.
  const reorderTotalValue = applySeed(profile.reorderValue, seed, MS_PER_STEP * 1.5);

  // ── KPI 4: Total Reorder Value (₱M) ──────────────────────────────────────
  // Source: SUM of (LP_Recommendation.recommended_qty × unit_cost) for current cycle.
  // reorderTotalValue above is reused for both count-card context and value headline.

  return {
    principal: key,
    kpis: {
      bad_order_value: {
        metric_type: 'loss',
        value:        boVal,
        delta_vs_prev: boDelta,
        direction:    boDir,
        incident_count: profile.badOrders.length,
        by_reason:    boByReason,
      },
      bad_order_incidents: {
        metric_type:          'loss',
        value:                activeCount,
        open_count:           openCount,
        under_investigation:  underInvCount,
        resolved_count:       resolvedCount,
        total_count:          profile.badOrders.length,
        delta_vs_prev:        activeDelta,
        direction:            activeDelta > 0 ? 'worse' : activeDelta < 0 ? 'better' : 'stable',
      },
      reorder_items: {
        metric_type:    'recommendation',
        value:          profile.reorderAlerts.length,
        critical_count: profile.reorderCritical,
        total_value:    reorderTotalValue,
        unit_noun:      unitNoun,
      },
      reorder_value: {
        metric_type:    'recommendation',
        value:          reorderTotalValue,
        item_count:     profile.reorderAlerts.length,
        critical_count: profile.reorderCritical,
        unit_noun:      unitNoun,
      },
    },
    // Primary chart data — SalesReturn_Fact grouped by (week, return_type).
    bad_order_series: buildBadOrderSeries(seed),
    abc:              { grain: profile.grain, tiers: profile.tiers },
    reorder_alerts:   profile.reorderAlerts,
    bad_orders:       profile.badOrders,
  };
}

export function getMockDashboard({ principal, from, to }) {
  const key  = principal === 'unilever' || principal === 'delmonte' ? principal : 'all';
  const seed = periodSeed(from);
  const data = buildPrincipalData(key, PROFILES[key], seed);
  return { ...data, period: { from, to } };
}
