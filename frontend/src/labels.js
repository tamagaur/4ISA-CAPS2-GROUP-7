// The words the app shows SSM's purchasing staff, in one place (2026-10-20).
//
// Every page takes its on-screen wording for these ideas from here, so a
// product is never a "SKU" on one page and a "product" on the next. The
// technical term stays in code, in the (?) explanations and in "Show
// details" sections; the screen shows the plain word. GLOSSARY at the end is
// the same list as a table (plain word → technical term → where it's used),
// for the manuscript; scripts can read it as plain data.
//
// Wording only: nothing here changes a figure. Rules a label summarises (the
// urgency bands, the 3-week rule, the reliability check) are computed by the
// backend; these are their names.

// ── Products and classes ────────────────────────────────────────────────
export const PRODUCT = 'product';
export const PRODUCTS = 'products';

// ABC classes. The letter stays in the (?) / hover ("Class A").
export const TIER_LABEL = { A: 'Top sellers', B: 'Middle sellers', C: 'Low sellers' };
// One product of a class ("a top seller"), and the short chip for tables.
export const TIER_SINGULAR = { A: 'top seller', B: 'middle seller', C: 'low seller' };
export const TIER_SHORT = { A: 'Top', B: 'Middle', C: 'Low' };
// A product's badge ("Top seller").
export const TIER_BADGE = { A: 'Top seller', B: 'Middle seller', C: 'Low seller' };
export const tierBadge = (tier) => TIER_BADGE[tier] ?? (tier ? `Class ${tier}` : '');
export const tierLabel = (tier) => TIER_LABEL[tier] ?? (tier ? `Class ${tier}` : '');
export const tierShort = (tier) => TIER_SHORT[tier] ?? tier ?? '';
export const tierSingular = (tier) => TIER_SINGULAR[tier] ?? (tier ? `Class ${tier} product` : 'product');
// The technical name, for hovers and (?) text.
export const tierTechnical = (tier) => (tier ? `Class ${tier}` : '');

// ── Forecast ────────────────────────────────────────────────────────────
// The ~90% band (forecast ± 1.645 × holdout RMSE).
export const mostLikely = (low, high) => `Most likely between ${low} and ${high}`;
// MASE below 1 (test error below the average month-to-month change in the product's sales) or not.
export const RELIABLE = 'Reliable enough to use for ordering';
export const NOT_RELIABLE = 'Not reliable enough yet';
export const NOT_CHECKED = 'Not checked yet';
// The same verdict as a sentence (Sales forecast headline).
export const RELIABILITY_SENTENCE = {
  reliable: 'This forecast is reliable enough to use for ordering.',
  unreliable: 'This forecast isn’t reliable enough to use for ordering yet.',
  unchecked: 'This forecast hasn’t been checked yet.',
};
// The verdict beside the forecast number (Sales forecast headline, 2026-10-20).
export const RELIABILITY_SHORT = {
  reliable: 'Suitable for ordering',
  unreliable: 'Not yet suitable for ordering',
  unchecked: 'Not checked yet',
};
export const reliabilityLabel = (mase) => (mase == null ? NOT_CHECKED : mase < 1 ? RELIABLE : NOT_RELIABLE);
// Typical miss (WAPE, or the miss as a share of the forecast).
export const offBy = (pct) => `Usually off by about ${pct}%`;

// ── Stock ───────────────────────────────────────────────────────────────
// Weeks of cover / stock cover / weeks of stock / weeks left.
export const LASTS = 'Lasts about';
export const lastsWeeks = (weeks) => `Lasts about ${weeks} week${weeks === '1' || weeks === 1 ? '' : 's'}`;
// Safety stock (ss_i).
export const KEEP_AT_LEAST = 'Keep at least';
// Stock below safety stock: the Summary card's word.
export const RUNNING_LOW = 'Running low';
// Target stock (the plan's order-up-to level, rop_i): not the 3-week rule.
export const ORDER_UP_TO = 'Order up to';
// SSM's policy of about 3 weeks of sales in stock (POLICY_COVER_WEEKS).
export const ssmRule = (weeks) => `SSM's ${weeks}-week rule`;

// ── Urgency (GET /recommendations urgency) ──────────────────────────────
// Shown as the Reorder page's own pills, CRITICAL / URGENT / PLANNED / NO
// DATA, with the hover text in utils/urgency.js (2026-10-20).
// Most urgent first: the Reorder page's order.
export const URGENCY_RANK = { CRITICAL: 0, URGENT: 1, PLANNED: 2, 'NO DATA': 3 };

// ── Data ────────────────────────────────────────────────────────────────
// Synthetic / generated / placeholder / demonstration / preview months.
export const SAMPLE_DATA = 'sample data';
export const SAMPLE_DATA_TITLE = 'Sample data';
export const INCLUDE_SAMPLE_DATA = 'Include sample data';
// A cost or capacity input SSM hasn't given yet (not sample data).
export const NOT_CONFIRMED = 'not yet confirmed by SSM';

// ── Units ───────────────────────────────────────────────────────────────
export const PCS = 'pcs';

// ── Page names ──────────────────────────────────────────────────────────
export const PAGE_NAMES = {
  forecast: 'Sales forecast',
  products: 'Products',
};

// ── The glossary as a table (manuscript) ────────────────────────────────
export const GLOSSARY = [
  { plain: 'product', technical: 'SKU (stock-keeping unit)', where: 'Every page; sidebar, search boxes, tables, messages' },
  { plain: 'Top sellers / Middle sellers / Low sellers (chips: Top / Middle / Low)', technical: 'ABC Class A / B / C', where: 'Dashboard, ABC Classification, Products, Sales forecast, Reorder Recommendations' },
  { plain: 'Most likely between X and Y', technical: '~90% prediction interval (forecast ± 1.645 × holdout RMSE)', where: 'Sales forecast, Dashboard forecast card, Category Trends' },
  { plain: 'Reliable enough to use for ordering / Not reliable enough yet / Not checked yet', technical: 'MASE below 1 / 1 or more / no MASE (lag-1 naive baseline)', where: 'Sales forecast, Dashboard, ABC Classification, Reorder Recommendations' },
  { plain: 'Usually off by about X%', technical: 'WAPE; for one product, summed absolute miss ÷ summed forecast', where: 'Sales forecast, Dashboard forecast-accuracy card' },
  { plain: 'Lasts about X weeks', technical: 'Weeks of cover / stock cover / days of cover ÷ 7', where: 'Dashboard, Reorder Recommendations, ABC Classification, Sales forecast' },
  { plain: 'Keep at least', technical: 'Safety stock (ss_i)', where: 'Reorder Recommendations, Sales forecast, Dashboard' },
  { plain: 'Running low', technical: 'Stock below safety stock', where: 'Dashboard summary card, ABC Classification stock status' },
  { plain: 'Order up to', technical: 'Target stock / order-up-to level (rop_i)', where: 'Reorder Recommendations, ABC Classification, Products' },
  { plain: "SSM's 3-week rule", technical: 'Policy cover target (POLICY_COVER_WEEKS = 3)', where: 'Dashboard, Reorder Recommendations' },
  { plain: 'CRITICAL / URGENT / PLANNED / NO DATA (hover: order now / order soon / can wait / stock can’t be read)', technical: 'Order-plan urgency: below safety stock / below target stock / at or above target stock / no usable pack size', where: 'Reorder Recommendations, Dashboard, Sales forecast' },
  { plain: 'Sample data', technical: 'Synthetic / generated / placeholder / demonstration data (is_demo, demo schema, X-Data-Mode: preview)', where: 'Top bar switch, banner, every chart that draws it' },
  { plain: 'not yet confirmed by SSM', technical: 'Placeholder cost and capacity inputs to the LP', where: 'Dashboard order-plan card, Reorder Recommendations' },
  { plain: 'pcs', technical: 'Pieces (the unit the LP solves in; cases shown as a second line)', where: 'Every quantity on every page' },
];
