// frontend/src/api/mockDashboard.js
//
// The ONLY file that touches mock data for the dashboard. dashboard.js
// imports getMockDashboard() and knows nothing about how the numbers are
// produced — when the real backend exists, this file disappears and
// dashboard.js's fetch call replaces it with no other changes needed.

const MS_PER_STEP = 0.02; // ~2% swing per seed step, matching the rest of
                           // the app's existing mock-data magnitude.

// Company policy: stock beyond this many weeks of demand is excess, in both
// the weeks-of-cover card and the trapped-capital card — one number drives
// both "gap" cards so they can't disagree about what "normal" means.
const POLICY_TARGET_WEEKS = 3;

// Deterministic period seed, same spread (-1..4) the rest of the app's mock
// formulas already use, but derived from an ISO date instead of a month name.
function periodSeed(from) {
  const d = new Date(from);
  const month = Number.isNaN(d.getTime()) ? 0 : d.getUTCMonth();
  const year = Number.isNaN(d.getTime()) ? 2026 : d.getUTCFullYear();
  return ((month + year) % 6) - 1;
}

function applySeed(base, seed, stepPct) {
  return Number((base * (1 + seed * stepPct)).toFixed(1));
}

// A cost/rate KPI where a higher value is always worse. direction is decided
// here, once — the UI reads it directly instead of re-deriving good/bad from
// a delta's sign. This is TYPE 1 (loss): colour comes only from direction,
// never from the value itself.
function lossMetric(value, baseline, currency) {
  const delta = Number((value - baseline).toFixed(1));
  return {
    metric_type: 'loss',
    value,
    ...(currency ? { currency } : {}),
    delta_vs_prev: delta,
    direction: delta > 0 ? 'worse' : 'better',
  };
}

// Relative wiggle around the final value — same shape for every principal
// (so "not almost straight" holds everywhere), added to whatever that
// principal's actual current weeks-of-cover works out to. The last entry is
// always 0 by construction, so the series' final point is always exactly
// currentWeeksOfCover — this (not a separate hard-coded number) is what
// keeps the KPI card and the chart from ever contradicting each other.
const COVER_TREND_SHAPE = [-0.9, -0.4, -0.7, -0.2, -0.6, -0.3, 0.1, -0.3, 0.2, -0.1, 0.3, 0];

function buildCoverSeries(currentWeeksOfCover) {
  return COVER_TREND_SHAPE.map((delta, i) => ({
    period: `Wk ${i + 1}`,
    weeks_of_cover: Math.max(0.5, Number((currentWeeksOfCover + delta).toFixed(1))),
  }));
}

const UNILEVER_PROFILE = {
  stockValue: 38.5, // ₱M on hand — weeks_of_cover AND trapped_capital are both derived from this, never hard-coded separately
  weeklySales: 9.2,  // ₱M/week
  spoilageCostBase: 96,
  stockoutBase: 3.1,
  reorderCritical: 2,
  reorderValue: 1.65,
  grain: 'sku',
  tiers: [
    { tier: 'A', sku_count: 42, revenue_share: 68 },
    { tier: 'B', sku_count: 96, revenue_share: 24 },
    { tier: 'C', sku_count: 180, revenue_share: 8 },
  ],
  reorderAlerts: [
    { sku_id: 'SKU-4721', product_name: 'Surf Powder Detergent 1kg', current_stock: 45, rop: 120, urgency: 'CRITICAL' },
    { sku_id: 'SKU-7821', product_name: 'Dove Shampoo 340ml', current_stock: 58, rop: 130, urgency: 'CRITICAL' },
    { sku_id: 'SKU-9012', product_name: 'Lux Bar Soap 135g', current_stock: 90, rop: 150, urgency: 'URGENT' },
    { sku_id: 'SKU-6543', product_name: 'Creamsilk Conditioner 180ml', current_stock: 112, rop: 140, urgency: 'URGENT' },
    { sku_id: 'SKU-8901', product_name: 'Breeze Detergent Powder 500g', current_stock: 130, rop: 155, urgency: 'URGENT' },
  ],
  badOrders: [
    { incident_id: 'INC-2024-135', product_name: 'Dove Shampoo 340ml', reason: 'Transport Damage', quantity: 24, status: 'OPEN' },
    { incident_id: 'INC-2024-131', product_name: 'Rexona Deodorant 40ml', reason: 'Expiry', quantity: 15, status: 'RESOLVED' },
    { incident_id: 'INC-2024-128', product_name: 'Lux Bar Soap 135g', reason: 'Storage Issue', quantity: 20, status: 'UNDER INVESTIGATION' },
    { incident_id: 'INC-2024-124', product_name: 'Surf Powder Detergent 1kg', reason: 'Transport Damage', quantity: 30, status: 'OPEN' },
    { incident_id: 'INC-2024-119', product_name: "Pond's Powder 50g", reason: 'Expiry', quantity: 12, status: 'RESOLVED' },
  ],
};

const DELMONTE_PROFILE = {
  stockValue: 21.6,
  weeklySales: 3.79, // 21.6 / 3.79 ≈ 5.7 weeks of cover at baseline
  spoilageCostBase: 134,
  stockoutBase: 4.6,
  reorderCritical: 1,
  reorderValue: 0.98,
  grain: 'category',
  // Category-level, not per-SKU — Del Monte has no SKU-level data anywhere
  // in this project, so these counts are categories, not products.
  tiers: [
    { tier: 'A', sku_count: 3, revenue_share: 71 },
    { tier: 'B', sku_count: 5, revenue_share: 21 },
    { tier: 'C', sku_count: 4, revenue_share: 8 },
  ],
  reorderAlerts: [
    { sku_id: 'CAT-Canned Fruits', product_name: 'Canned Fruits', current_stock: 210, rop: 320, urgency: 'CRITICAL' },
    { sku_id: 'CAT-Pasta & Sauces', product_name: 'Pasta & Sauces', current_stock: 260, rop: 340, urgency: 'URGENT' },
    { sku_id: 'CAT-Juices', product_name: 'Juices', current_stock: 400, rop: 460, urgency: 'URGENT' },
  ],
  badOrders: [
    { incident_id: 'INC-2024-134', product_name: 'Tomato Sauce (category)', reason: 'Expiry', quantity: 18, status: 'RESOLVED' },
    { incident_id: 'INC-2024-133', product_name: 'Sweet Corn (category)', reason: 'Storage Issue', quantity: 32, status: 'UNDER INVESTIGATION' },
    { incident_id: 'INC-2024-130', product_name: 'Pineapple Juice (category)', reason: 'Transport Damage', quantity: 27, status: 'OPEN' },
    { incident_id: 'INC-2024-126', product_name: 'Fruit Cocktail (category)', reason: 'Expiry', quantity: 21, status: 'RESOLVED' },
    { incident_id: 'INC-2024-121', product_name: 'Spaghetti Pasta (category)', reason: 'Storage Issue', quantity: 14, status: 'UNDER INVESTIGATION' },
  ],
};

// grain 'mixed' — a blend, honestly labelled as such rather than pretending
// combined Unilever SKUs and Del Monte categories are the same unit.
function combineTiers(a, b) {
  return ['A', 'B', 'C'].map((letter) => {
    const ta = a.find((t) => t.tier === letter);
    const tb = b.find((t) => t.tier === letter);
    return {
      tier: letter,
      sku_count: ta.sku_count + tb.sku_count,
      revenue_share: Math.round((ta.revenue_share + tb.revenue_share) / 2),
    };
  });
}

const ALL_PROFILE = {
  stockValue: UNILEVER_PROFILE.stockValue + DELMONTE_PROFILE.stockValue,
  weeklySales: UNILEVER_PROFILE.weeklySales + DELMONTE_PROFILE.weeklySales,
  spoilageCostBase: UNILEVER_PROFILE.spoilageCostBase + DELMONTE_PROFILE.spoilageCostBase,
  stockoutBase: Number(((UNILEVER_PROFILE.stockoutBase + DELMONTE_PROFILE.stockoutBase) / 2).toFixed(1)),
  reorderCritical: UNILEVER_PROFILE.reorderCritical + DELMONTE_PROFILE.reorderCritical,
  reorderValue: Number((UNILEVER_PROFILE.reorderValue + DELMONTE_PROFILE.reorderValue).toFixed(2)),
  grain: 'mixed',
  tiers: combineTiers(UNILEVER_PROFILE.tiers, DELMONTE_PROFILE.tiers),
  reorderAlerts: [...UNILEVER_PROFILE.reorderAlerts.slice(0, 2), ...DELMONTE_PROFILE.reorderAlerts.slice(0, 2)],
  badOrders: [...UNILEVER_PROFILE.badOrders.slice(0, 3), ...DELMONTE_PROFILE.badOrders.slice(0, 3)],
};

const PROFILES = {
  unilever: UNILEVER_PROFILE,
  delmonte: DELMONTE_PROFILE,
  all: ALL_PROFILE,
};

function buildPrincipalData(key, profile, seed) {
  const spoilageCost = applySeed(profile.spoilageCostBase, seed, MS_PER_STEP * 1.25);
  const stockoutRate = Number(applySeed(profile.stockoutBase, seed, MS_PER_STEP * 2).toFixed(1));
  const reorderTotalValue = applySeed(profile.reorderValue, seed, MS_PER_STEP * 1.5);

  // Single stock + weekly-sales pair, seeded together — every "how much
  // stock" figure (held, weeks of cover, excess capital) is derived from
  // this one pair, never given its own independent number.
  const stockValue = applySeed(profile.stockValue, seed, MS_PER_STEP);
  const weeklySales = applySeed(profile.weeklySales, seed, MS_PER_STEP * 0.75);
  const weeksOfCover = Number((stockValue / weeklySales).toFixed(1));
  const weeksOfCoverBaseline = Number((profile.stockValue / profile.weeklySales).toFixed(1));

  // TYPE 2 (gap): capital "justified" by policy-paced demand vs. what's
  // actually held — the excess (never negative) is the headline figure,
  // not the raw held value.
  const justified = Number((POLICY_TARGET_WEEKS * weeklySales).toFixed(1));
  const excess = Number(Math.max(0, stockValue - justified).toFixed(1));

  return {
    principal: key,
    kpis: {
      trapped_capital: {
        metric_type: 'gap',
        held: { value: stockValue, currency: 'PHP_M' },
        justified: { value: justified, currency: 'PHP_M' },
        excess: { value: excess, currency: 'PHP_M' },
      },
      weeks_of_cover: {
        metric_type: 'gap',
        value: weeksOfCover,
        policy_target: POLICY_TARGET_WEEKS,
        delta_vs_prev: Number((weeksOfCover - weeksOfCoverBaseline).toFixed(1)),
      },
      spoilage_cost: {
        ...lossMetric(spoilageCost, profile.spoilageCostBase, 'PHP_K'),
        incident_count: profile.badOrders.length,
      },
      stockout_rate: lossMetric(stockoutRate, profile.stockoutBase),
      reorder_count: {
        metric_type: 'recommendation',
        // Derived from the actual alert list, never a separately hard-coded
        // number — that's exactly how "4 products, 3 alerts" happened.
        value: profile.reorderAlerts.length,
        critical_count: profile.reorderCritical,
        total_value: reorderTotalValue,
      },
    },
    cover_series: buildCoverSeries(weeksOfCover),
    abc: { grain: profile.grain, tiers: profile.tiers },
    reorder_alerts: profile.reorderAlerts,
    bad_orders: profile.badOrders,
  };
}

export function getMockDashboard({ principal, from, to }) {
  const key = principal === 'unilever' || principal === 'delmonte' ? principal : 'all';
  const seed = periodSeed(from);
  const data = buildPrincipalData(key, PROFILES[key], seed);

  return {
    ...data,
    period: { from, to },
  };
}
