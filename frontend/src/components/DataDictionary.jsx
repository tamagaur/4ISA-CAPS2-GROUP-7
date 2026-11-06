// Reference Guide (/data-dictionary): the dashboard's data dictionary, what
// each figure means and how it is formed. Content by Maica (94bc190); the
// layout redesigned 2026-10-18 after Audrey's mock-up: a header band, two
// notices, a search over every entry, category pills, and glossary rows
// whose definition is always visible and whose methodology opens on demand
// (a quick glossary for staff, the full method for reviewers).
//
// The entries below are the page's only content: Maica's definitions and
// methods (later edits dated beside each entry), split on 2026-10-26 into a
// plain "How it's computed" and a closed "Technical details" (her method
// text), with `caveat` as a short badge. Nothing on this page reads the principal, range or data mode:
// it explains them, so the top bar's principal switch is not shown here.
import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle, ArrowLeft, BarChart3, BookOpen, Calculator, ChartLine, ChevronDown, ClipboardCheck, Database, Info,
  Lightbulb, Search, SearchX, Star, TrendingUp, X,
} from 'lucide-react';
import { NOT_CONFIRMED, TO_BE_CONFIRMED } from '../labels';
import './DataDictionary.css';

// In alphabetical order (Audrey, 2026-10-18), for the pills and the sections.
// Each section has its own one-line description (2026-10-26).
const sections = [
  { id: 'category-trends', label: 'Category Trends', icon: ChartLine, blurb: 'Which way each product category is heading, and how sure the trend is.' },
  { id: 'forecasts', label: 'Forecasts', icon: TrendingUp, blurb: 'How next month’s sales forecast is made, and how far to trust it.' },
  { id: 'reorder-planning', label: 'Reorder Planning', icon: ClipboardCheck, blurb: 'How the order plan decides what to order and how urgently.' },
  { id: 'sales-stock', label: 'Sales & Stock', icon: Database, blurb: 'What the sales, stock and purchases charts show, and how gaps are handled.' },
  { id: 'summary', label: 'Summary', icon: BarChart3, blurb: 'What each card at the top of the Dashboard measures.' },
  { id: 'top-products', label: 'Top Products', icon: Star, blurb: 'How products are ranked into top, middle and low sellers.' },
];

// Each entry (2026-10-26): `definition` (always visible), `plain` ("How it's
// computed": one or two sentences for SSM's purchasing staff, no formulas,
// model names or acronyms) and `technical` (closed "Technical details": the
// formulas, model names and figures, for reviewers). `caveat` is a short
// badge. Page names are the sidebar's. The words follow src/labels.js.
const entries = {
  'category-trends': [
    {
      // analytics/forecasting/category_trend.py (Theil–Sen, Mann–Kendall).
      term: 'Growing, Declining and No clear trend',
      definition: 'Which way a category’s revenue has been moving over the last two years.',
      plain: 'A straight trend line is drawn through the last 24 months of sales. Growing or Declining is shown only when the direction is unlikely to be chance; otherwise the category shows No clear trend.',
      technical: 'A Theil–Sen line through the last 24 months of revenue with data, starting at the category’s first sale. The direction counts as real only when a Mann–Kendall test gives p < 0.05. The line is extended 12 months as the projection; its likely range uses the slope’s 95% confidence bounds. A trend projection, not a validated forecast.',
    },
    {
      term: 'How sure is this trend?',
      definition: 'Whether a category’s direction is unlikely to be chance.',
      plain: 'Sure means the rise or fall has been steady enough to trust. Not sure means it could be normal ups and downs.',
      technical: 'Sure when the Mann–Kendall test gives p < 0.05; Not sure otherwise. Each category’s p-value is in Show details on the Category Trends page.',
    },
    {
      term: 'Projected change (% and ₱)',
      definition: 'How much the trend line’s next 12 months differ from its last 12 months.',
      plain: 'Shown only for Growing or Declining categories. The ₱ figure is the same comparison in pesos.',
      technical: 'The trend line’s total over the next 12 months minus its total over the last 12 months on the same line; the % divides that by the last-12-month total, so the % and the ₱ always agree. The range in brackets uses the slope’s 95% confidence bounds.',
    },
    {
      term: 'Small category',
      definition: 'A category that earned under 1% of the principal’s revenue over the last 12 months.',
      plain: 'A large % change on such a small base is a small amount of money, so the tag warns against over-reading it.',
      technical: 'The category’s revenue over the last 12 months ÷ the revenue of all the principal’s categories over the same months, under 1%.',
    },
    {
      term: 'Unclassified',
      definition: 'Products listed under the category “Unclassified” in the product list.',
      plain: 'They have no real category yet. Assign them one on the SKU Management page.',
      technical: '“UNCLASSIFIED” is a value stored as the product’s category, not an empty field. Category Trends groups these products’ sales as one row.',
    },
    {
      term: 'Why some categories have no projection',
      definition: 'A category shows no projected change when it doesn’t have enough history, or when its trend line has reached zero.',
      plain: 'A category needs 12 months with sales, counted from its first sale, before its trend is projected. A category whose trend line has fallen to ₱0 has nothing to compare against, so it shows its direction but no change.',
      technical: 'At least 12 months with data from the first sale. No % (and no ₱) when the trend line’s total over the last 12 months is 0.',
    },
  ],
  forecasts: [
    {
      // analytics/forecasting/router.py (LIVE_MODEL, the history-length bins);
      // backend/routers/forecast.py (Unilever Tier A only).
      term: 'Forecast',
      caveat: 'Unilever top sellers only',
      definition: 'The number of pieces a top seller is expected to sell in the planning month.',
      plain: 'Each top seller’s own sales history is used to estimate next month. Products with a longer history use a more detailed method, and every forecast’s error in testing is checked against the average month-to-month change in the product’s sales before the test months.',
      technical: 'Made for Unilever’s top sellers (Class A) only; Del Monte’s sales have no product column, so it has no product forecasts. The model depends on how many months of sales the product has: under 3 months, a provisional trailing average; 3 to 11 months, a 3-month moving average (MA3); 12 to 23 months, TSB, a method for products that do not sell every month; 24 months or more, the average of a machine-learning model (XGBoost) and MA3. MA3 is the benchmark every model is scored against and the fallback when another cannot be used. On SSM’s data the other models tie with MA3; they are used because they draw on the product’s full history, not because they proved more accurate.',
    },
    {
      // scripts/run_baseline_forecast.py (_confidence_band, CONFIDENCE_Z =
      // analytics.params.FORECAST_INTERVAL_Z = 1.645).
      // "Meant to cover", not "will": 9 in 10 is what z = 1.645 is built for,
      // never a measured hit rate (2026-10-22).
      term: 'Most likely between X and Y',
      definition: 'The range meant to cover actual sales in about 9 in 10 months.',
      plain: 'The range is set by how far this product’s forecasts have missed on recent months: a product whose forecasts missed more gets a wider range.',
      technical: 'The forecast plus or minus 1.645 times the product’s own forecast error (RMSE) on its most recent months held back for testing, for the model actually used. The 9 in 10 is what the 1.645 multiplier is designed for, not a measured hit rate. It is an approximate band from a short test window. When that error cannot be measured, no band is drawn rather than an invented one.',
    },
    {
      // analytics/forecasting/diagnostic_metrics.py (mase, naive_scale);
      // analytics/params.MASE_GATE = 1.0; scripts/run_lp.py (candidate pool).
      // The order-plan cut-off is an open question to the adviser
      // (reports/ADVISER_QUESTIONS_SIRCG.md §3, no recorded decision).
      term: 'Suitable / Not yet suitable for ordering',
      caveat: 'Order-plan cut-off adopted by the team; not confirmed by SSM or the adviser',
      definition: 'Whether a product’s forecast is reliable enough for the order plan to use.',
      plain: 'Suitable means the forecast’s error in testing was below the average month-to-month change in the product’s sales before the test months. Only suitable products are put in the order plan.',
      technical: 'MASE (forecast error score): the average absolute error on the held-back months, divided by the average month-to-month change in the product’s real sales history. Below 1 means the forecast beats that simple guess (Suitable); 1 or more, Not yet suitable. Only products scoring below 1 go into the order plan; using this cut-off for that is a team decision, not confirmed by SSM or the adviser. It is computed on real months only, never on sample data.',
    },
    {
      // SKUForecast.jsx productAccuracy (share_of_forecast); RangeCards.jsx
      // and analytics/forecasting/diagnostic_metrics.py (wape: sum|a-p| / sum|a|).
      term: 'Usually off by about X%',
      definition: 'How far a product’s past forecasts were from actual sales, as a percentage.',
      plain: 'Past forecasts are compared with what actually sold, month by month. The misses are added up and shown as a percentage: 0% is a perfect forecast, and lower is better.',
      technical: 'WAPE (weighted absolute percentage error): the sum of the gaps between forecast and actual sales (each gap counted as positive). On the SKU Forecast page it is divided by the total forecast over the months scored in the date range; on the Dashboard’s forecast accuracy card, by the total actual sales, per product (weighted by sales) and for the company total, which is lower because misses on different products partly cancel out. Uses the forecasts as they were made at the time.',
    },
    {
      // SkuDemandPatternPanel.jsx CV_BAND_META; backend/routers/segment.py.
      term: 'How steady are sales? (Steady, Up and down, Very unpredictable)',
      definition: 'How much a product’s monthly sales swing around its average month.',
      plain: 'Steady: a typical month stays within about half of the average. Up and down: between half and the full average. Very unpredictable: more than that.',
      technical: 'The coefficient of variation (CV) of monthly pieces: under 0.5 is low volatility (Steady), 0.5 to under 1.0 medium (Up and down), 1.0 or more high (Very unpredictable).',
    },
    {
      // analytics/forecasting/calendar.py (calendar_factor), the wording of
      // utils/calendarAdjustment's CALENDAR_METHOD_FALLBACK; not yet signed
      // off (analytics.params.CALENDAR_FACTOR_SIGNED_OFF = False). Added
      // 2026-10-22 (Technical Adviser, 2 Oct 2026: no unexplained jargon;
      // methods awaiting sign-off flagged).
      term: 'Calendar adjustment',
      caveat: 'Team decision; adviser sign-off pending',
      definition: 'An adjustment for the time of year, applied to the stored forecast and shown beside it as ×factor.',
      plain: 'Each forecast is raised or lowered by how that month has usually sold compared with the months before it in earlier years. Until it is confirmed, the SKU Forecast page shows the forecast without it; the order plan uses the adjusted figure.',
      technical: 'The factor is how the calendar month sold against the 3 months before it in earlier years, for the Unilever company total in pieces, averaged over those years (geometric mean) and moved halfway toward no change. A month with no earlier year on record is left as it is; only months before the forecast month are read. The forecast is multiplied by the factor after the model’s own checks. It is a team decision; adviser sign-off is pending.',
    },
  ],
  'reorder-planning': [
    {
      // backend/stock_status.py; utils/urgency.js (the pills' hover text).
      term: 'CRITICAL, URGENT, PLANNED and NO DATA',
      definition: 'How pressing each suggested order is.',
      plain: 'CRITICAL: below safety stock, order now. URGENT: below target stock, order soon. PLANNED: at or above target stock, can wait. NO DATA: no usable pack size for this product, so its stock can’t be read.',
      technical: 'CRITICAL: stock is below the product’s safety stock. URGENT: stock is at or above safety stock but below the target stock. PLANNED: stock is at or above the target stock. NO DATA: the stock row has no pack size to turn cases into pieces. Stock is the count that opens the planning month, in pieces (cases × pack size + loose pieces).',
    },
    {
      // scripts/run_lp.py (_sigma_d_for_product, safety_stock_for);
      // analytics/params (SERVICE_Z 1.28, SERVICE_LEVEL_PCT 90,
      // PLACEHOLDERS review_days 5, lead_days 3).
      term: 'Safety stock',
      caveat: 'Inputs not yet confirmed; method pending adviser confirmation',
      definition: 'Extra stock kept so a product does not run out if sales come in higher than forecast before the next delivery.',
      plain: 'The extra stock grows with how much a product’s sales swing, and with how long it takes to reorder and receive it.',
      technical: `1.28 (for a 90% service level, set to cover demand about 9 times in 10) times the product’s daily demand variability times the square root of the review period plus the lead time, in pieces. The review period (weekly orders, 5 business days) and lead time (3 business days) are ${NOT_CONFIRMED}. Unilever has no daily sales, so its daily variability is worked out from monthly sales (the monthly variation divided by the square root of the average business days in a month), which assumes one day’s sales don’t affect the next: an assumption pending adviser confirmation.`,
    },
    {
      // analytics/optimization/lp.py (target_stock: T_i = w_i x (R + L) / 5 + SS_i).
      term: 'Target stock',
      definition: 'The stock level an order tops a product back up to.',
      plain: 'Enough stock to cover the sales expected before the next delivery arrives, plus the safety stock.',
      technical: 'The weekly forecast times (review days plus lead days) divided by 5, plus the safety stock: the sales expected before the next delivery arrives, plus the safety buffer. In pieces.',
    },
    {
      // backend/stock_status.py, analytics/optimization/lp.py: the plan
      // orders up to target stock; no reorder-point trigger is computed.
      term: 'Reorder point (ROP)',
      definition: 'The stock level at which a product should be reordered.',
      plain: 'The plan is made once a month, so instead of a separate reorder level, each product is topped back up to its target stock. Below target stock it is marked URGENT; below safety stock, CRITICAL.',
      technical: 'This dashboard plans once a month rather than reordering whenever stock falls to a set level, so it does not compute a separate reorder point: each product is ordered up to its target stock instead. The database column named “rop” holds that target stock. A product below its target stock is marked Urgent, and below its safety stock Critical.',
    },
    {
      // analytics/optimization/lp.py (need_i, the three layers, stage 1).
      term: 'Suggested order',
      definition: 'How many pieces to order for the month: one quantity per product. Nothing in the system divides it into weekly purchase orders.',
      plain: 'Enough to cover next month’s expected sales and bring stock back up to the target, minus what is already on hand. If the supplier’s allocation is short, the extra buffer is cut first and this month’s expected sales last.',
      technical: 'The need is the month’s forecast plus the target stock, minus the stock on hand, and never below zero, so an overstocked product orders nothing. The plan orders the whole need when the supplier allocation allows. When it does not, it cuts in this order: the rest of the target first, then the safety stock, and this month’s expected sales last.',
    },
    {
      // analytics/optimization/lp.py (solved in stages, PuLP);
      // scripts/run_lp.py (candidate pool: Class A, status ok, MASE < 1).
      term: 'Order plan optimizer (LP)',
      caveat: 'Product cut-off adopted by the team; not confirmed by SSM or the adviser',
      definition: 'The calculation that turns forecasts, stock on hand and the supplier allocation into the suggested orders.',
      plain: 'It works out how much of each top seller to order so stock gets back to its target, without going over what the supplier will allow.',
      technical: 'A linear program (LP), a standard method for choosing quantities within limits. It orders each product up to its target stock, net of the stock on hand. If the supplier allocation cannot cover every order, SSM’s 3-week stock rule and then the order weights decide which products are cut. Only Class A products whose forecast test error is below the average month-to-month change in their sales before the test months are planned (that cut-off is a team decision, not confirmed by SSM or the adviser). Quantities are in pieces.',
    },
    {
      // analytics/params.LP_WEIGHTS ("TEAM (asserted)", in no scribe note,
      // reports/LP_READINESS.md §1.5); analytics/optimization/lp.py (stage 3).
      term: 'Order weights (45 / 35 / 20)',
      caveat: 'Team setting, source not yet confirmed; costs not yet confirmed by SSM',
      definition: 'How the plan decides which products give way when the supplier allocation cannot cover every order.',
      plain: 'When the supplier can’t fill every order, the plan decides which products get less by weighing cost, how much of each product’s need is met, and storage.',
      technical: `Cost 45%, need met 35% (the share of the need met, weighted by each product’s sales value) and storage 20%. These weights are a team setting; their source is not yet confirmed. They only matter when the allocation is short; with enough allocation every need is ordered in full. The procurement and storage costs behind them are ${NOT_CONFIRMED}.`,
    },
    {
      // analytics/allocation.monthly_allocation; scripts/run_lp.py
      // (allocation_ceilings); analytics/params ALLOCATION_DEFAULT_PCT.
      term: 'Monthly supplier allocation',
      definition: 'The most pieces the plan may order from a principal in a month.',
      plain: 'A monthly ceiling on how much the plan may order from each principal, based on last year’s sales.',
      technical: 'Last year’s sales in pieces times the allocation percentage (103% by default; 105% or 108%), divided by 12, for each principal. The percentage is the rule SSM described in the September 2026 client meeting; which level applies is to be confirmed by SSM.',
    },
    {
      // backend/stock_status.py (COUNT_OMITS_ZERO_STOCK); scripts/run_lp.py
      // (stock on hand: no row counts as 0).
      term: 'Not in the stock count',
      definition: 'A planned product that does not appear in the stock count that opens the plan.',
      plain: 'Unilever’s stock files never list a product with zero stock, so a missing product is treated as out of stock. For Del Monte, a missing product says nothing about its stock, so it is shown as no data.',
      technical: 'The plan reads a missing Unilever product as 0 pieces on hand, so it can be CRITICAL; the Reorder Recommendations page marks it “not in count”.',
    },
    {
      // SKUForecast.jsx (togglePinSKU, PINNED_FILTER, planRows): browser
      // localStorage only.
      term: 'Pinned',
      definition: 'A product you marked on the SKU Forecast page so it is easy to find again.',
      plain: 'On the SKU Forecast page, pinned products have their own “Pinned products” list at the top of the search suggestions, come first in the “Products in the current order plan” table, and “Show: Pinned” lists only them. Pin or unpin with the pin button on a product, in the search list or at the start of a table row.',
      technical: 'Pins are saved in this web browser only, not on the server: they don’t follow you to another computer, and people who share a browser share the same pins. They stay after you sign out.',
    },
  ],
  summary: [
    {
      term: 'Annual sales and allocation',
      definition: 'Sales for the financial year (FY, January to December) so far, next to the supplier-allocation level you picked.',
      plain: 'The allocation is last year’s sales times the level you choose (103%, 105% or 108%). The card shows whether this year’s sales are on pace to reach it.',
      technical: 'The target is the prior year’s sales multiplied by the selected 103%, 105%, or 108% level. The pace compares average monthly sales so far with that level’s monthly amount. Year-to-date sales are compared with the same months in the prior year; if the months on record differ, the page marks the comparison as not like-for-like. FY is the calendar year.',
    },
    {
      term: 'Inventory value',
      definition: 'The value of stock in the latest available count on or before the selected date range ends.',
      plain: 'The stock counted, valued at what SSM last paid for each product.',
      technical: 'Stock is valued using each product’s last purchase price. This is a stock snapshot, not the value of purchases or sales during the selected range.',
    },
    {
      term: 'Weeks of stock (Stock cover card)',
      caveat: 'Provisional for Unilever',
      definition: 'An estimate of how long the counted stock would last at the recent sales rate.',
      plain: 'The counted stock is compared with average weekly sales over the last 12 months, and with SSM’s 3-week rule.',
      technical: 'Stock value is compared with average weekly sales over the 12 months up to the stock count. The card compares the result with SSM’s 3-week rule. Stock is valued at purchase price while sales are at selling price, so the bases differ. Unilever’s figure is marked provisional because its stock and sales sources do not yet have a confirmed location match.',
    },
    {
      term: 'Could run out (Below safety stock card)',
      definition: 'Top sellers whose counted stock is below their safety stock.',
      plain: 'Only products with both a stock count and a safety stock can be checked, so the total is not a count of every product.',
      technical: 'The plan’s safety stock against the latest stock count. A planned product missing from the count is left out here; the Reorder Recommendations page reads it as 0 on hand, so its CRITICAL count can be higher.',
    },
    {
      term: 'Pending reorders',
      definition: 'Reorder recommendations that are still waiting for a decision.',
      plain: 'Suggested orders in the current plan that nobody has accepted or dismissed yet.',
      technical: 'This reflects the current reorder-plan cycle, in the Reorder page’s three counts: Act Now (below target stock), Review Later (at or above target stock) and No order needed (a suggested order of 0 pieces). It is separate from the number of products below safety stock.',
    },
  ],
  'sales-stock': [
    {
      term: 'Sales',
      definition: 'Recorded sales value for the selected principal and period, shown in pesos.',
      plain: 'The selling value recorded in SSM’s sales files. Totals and comparisons count only the months that have sales on record.',
      technical: 'Sales use the source’s recorded selling values. The comparison and range totals only cover months with sales on record; gaps are not silently treated alike for both principals (see Missing months).',
    },
    {
      term: 'Stock on hand',
      definition: 'The value of stock recorded in an inventory count for a month.',
      plain: 'The value of the stock counted for the month, at what SSM last paid for each product.',
      technical: 'The chart labels stock by its count date when available. Del Monte’s records may identify only the count month, not the exact day. Inventory value uses last purchase price; this is not a unit count.',
    },
    {
      term: 'Purchases received',
      caveat: 'May be estimated',
      definition: 'The value of recorded stock receipts for a month, shown in the Purchases view.',
      plain: 'What arrived in the month. Where SSM’s purchase records are missing, it is estimated from the stock counts and sales, and the chart marks it as estimated.',
      technical: 'The estimate is the closing count minus the opening count plus the month’s sales. Estimated receipts are never a summary card figure.',
    },
    {
      term: 'Returns',
      definition: 'The value of returns present in the source records.',
      plain: 'Only returns recorded in SSM’s files are shown; missing returns are never estimated.',
      technical: 'The Returns view uses recorded returns only. It does not fill missing return data with an estimate.',
    },
    {
      term: 'Annual sales',
      definition: 'Sales for each financial year (FY), January to December.',
      plain: 'Each bar is one year’s total sales. A year with only some months on record is labelled with those months.',
      technical: 'FY is the calendar year, the same as on the Annual sales and allocation card. With sample data on, sample-data months are hatched and are not presented as real results.',
    },
    {
      term: 'Missing months and estimates',
      caveat: 'Means different things per principal',
      definition: 'A missing data point can mean different things depending on the source.',
      plain: 'For Unilever, a month without a sales row is zero sales. For Del Monte, a missing category month means the data was not collected, not that sales were zero.',
      technical: 'Sample data, when it is on, is labelled; it does not feed the summary cards, forecasts, ABC classes, or the real order plan.',
    },
    {
      // Charts.jsx WEEKS_UNDER / WEEKS_NEAR / WEEKS_OVER, WEEKS_NEAR_BAND 0.5.
      term: 'Weeks of stock (month by month)',
      definition: 'How many weeks each month’s stock would last at that month’s sales rate.',
      plain: 'Each month’s stock value is divided by that month’s average weekly sales. Bars under SSM’s 3-week rule are blue, bars within half a week of it are grey, and bars over it are orange.',
      technical: 'Weekly sales = the month’s sales ÷ 4.35 weeks (365.25 ÷ 12 ÷ 7). Blue under 2.5 weeks, grey 2.5 to 3.5 weeks, orange over 3.5 weeks; the dashed line is the 3-week rule. Stock is at last purchase price and sales at selling price. Only months with a real stock count are shown, and a count that needs checking is outlined.',
    },
    {
      term: 'SSM’s 3-week rule',
      definition: 'SSM’s practice of keeping about 3 weeks of sales in stock.',
      plain: 'The Dashboard compares stock with this rule so overstock and shortfalls stand out. The order plan sets its own level for each product instead (see Target stock).',
      technical: 'The rule is set at 3 weeks of sales. The Dashboard’s “plan vs SSM’s 3-week rule” card compares how much stock each would hold across the planned products.',
    },
    {
      term: 'Sample data',
      definition: 'Generated figures for months SSM has no data for, shown only when “Include sample data” is on.',
      plain: 'They fill 2021–22 and other gaps so the charts can be shown in full. They are always marked, and never used for the summary cards, forecasts, top-seller ranking or the real order plan.',
      technical: 'Kept apart from SSM’s own data. Four kinds, never mixed: copied from a real month, filled between two real months, carried across Del Monte’s January 2025 category change, and back-cast before 2023. No accuracy figures are worked out for sample data.',
    },
  ],
  'top-products': [
    {
      term: 'ABC classification',
      definition: 'A ranking that groups products into top, middle and low sellers by their share of recorded revenue.',
      plain: 'Products are sorted from highest to lowest revenue. Those making up the first 80% of revenue are top sellers, the next 15% middle sellers, and the rest low sellers.',
      technical: 'Items are sorted from highest to lowest revenue and assigned using cumulative revenue share: Class A through 80%, Class B from 80% to 95%, and Class C from 95% onward. These are ranking cutoffs, not a promise that a fixed number of items falls into each class.',
    },
    {
      term: 'Top, middle and low sellers (Class A / B / C)',
      caveat: TO_BE_CONFIRMED,
      definition: 'The three groups of the ABC ranking: top sellers (Class A), middle sellers (Class B) and low sellers (Class C).',
      plain: 'Top sellers bring in most of the revenue, and only they get forecasts and order plans. Middle and low sellers are watched on the Dashboard only.',
      technical: 'Unilever uses Class A over the latest 12 months, plus products first sold within 12 months that are Class A over the latest three months. This basis is to be confirmed. Del Monte remains classified on the single-month basis; its ranked items are categories, not individual products.',
    },
    {
      term: 'Classification period',
      definition: 'The month the ABC classes were calculated up to: for Unilever, the last of the 12 months ranked; for Del Monte, the one month ranked.',
      plain: 'The month the classes were worked out up to. Unilever’s are based on the 12 months ending then, Del Monte’s on that month alone. It can differ from the Dashboard’s date range.',
      technical: 'The classification period is shown separately from the dashboard’s selected sales range because a saved ABC run may be for a different period. A product not ranked in the latest run keeps its last class, shown faded with that month.',
    },
    {
      term: 'Revenue share and cumulative share',
      definition: 'Revenue share is one item’s portion of total ranked revenue; cumulative share is the running total down the revenue ranking.',
      plain: 'These shares set the classes. They describe past revenue, not a forecast, a stock risk or an order quantity.',
      technical: 'Share = the item’s revenue ÷ total ranked revenue; cumulative share is the running sum from the top of the ranking. A month where returns exceeded sales counts as 0.',
    },
  ],
};

const ALL = 'all';
const keyOf = (sectionId, term) => `${sectionId}:${term}`;
const norm = (text) => String(text || '').toLocaleLowerCase();

// The text with each occurrence of the query marked (case-insensitive).
function Highlight({ text, query }) {
  if (!query) return text;
  const lower = norm(text);
  const parts = [];
  let from = 0;
  let at = lower.indexOf(query, from);
  while (at !== -1) {
    if (at > from) parts.push(text.slice(from, at));
    parts.push(<mark key={at}>{text.slice(at, at + query.length)}</mark>);
    from = at + query.length;
    at = lower.indexOf(query, from);
  }
  if (from < text.length) parts.push(text.slice(from));
  return <>{parts}</>;
}

// One glossary row: the term and any caveat; the definition; "How it's
// computed" behind a toggle, and inside it the closed "Technical details"
// (2026-10-26). A search that matches the technical text opens both.
function GlossaryEntry({ entryKey, entry, query, open, techHit, onToggle }) {
  const panelId = `method-${entryKey.replace(/[^a-z0-9]+/gi, '-')}`;
  return (
    <article className={`dict-entry${open ? ' is-open' : ''}`}>
      <div className="dict-entry-main">
        <div className="dict-entry-term">
          <h4><Highlight text={entry.term} query={query} /></h4>
          {entry.caveat && (
            <span className="dict-caveat">
              <AlertTriangle size={12} aria-hidden="true" />
              {entry.caveat}
            </span>
          )}
        </div>
        <p className="dict-entry-def"><Highlight text={entry.definition} query={query} /></p>
        <button
          type="button"
          className="dict-entry-toggle"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
        >
          <Calculator size={15} aria-hidden="true" />
          <span>{open ? 'Hide how it’s computed' : 'How it’s computed'}</span>
          <ChevronDown size={16} className="dict-chevron" aria-hidden="true" />
        </button>
      </div>
      <div className="dict-method" id={panelId} role="region" aria-label={`How it’s computed: ${entry.term}`} hidden={!open}>
        <div className="dict-method-inner">
          <span className="dict-method-label">
            <Calculator size={14} aria-hidden="true" />
            How it&apos;s computed
          </span>
          <p><Highlight text={entry.plain} query={query} /></p>
          <details className="dict-tech" key={techHit ? 'hit' : 'closed'} open={techHit || undefined}>
            <summary>Technical details</summary>
            <p><Highlight text={entry.technical} query={query} /></p>
          </details>
        </div>
      </div>
    </article>
  );
}

const DataDictionary = () => {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState(ALL);
  // Methodologies the reader opened or closed; any other entry is open only
  // while the search matches its methodology text.
  const [chosen, setChosen] = useState(() => new Map());
  const searchRef = useRef(null);
  const q = norm(query.trim());

  // The search bar and pills stay where they are on screen when a category
  // or the search changes the list under them (Audrey: clicking Top
  // Products made the page jump). The toolbar's position is noted before
  // the change and the scroll corrected after it; .dict-results keeps
  // enough height under the toolbar for that to always be possible.
  const toolbarRef = useRef(null);
  const anchorRef = useRef(null);
  const holdToolbar = () => {
    anchorRef.current = toolbarRef.current?.getBoundingClientRect().top ?? null;
  };
  useLayoutEffect(() => {
    const before = anchorRef.current;
    anchorRef.current = null;
    if (before == null || !toolbarRef.current) return;
    const scroller = toolbarRef.current.closest('.main-content');
    const shift = toolbarRef.current.getBoundingClientRect().top - before;
    if (scroller && Math.abs(shift) > 0.5) scroller.scrollTop += shift;
  }, [category, q]);
  const pickCategory = (id) => {
    holdToolbar();
    setCategory(id);
  };
  const search = (text) => {
    holdToolbar();
    setQuery(text);
  };

  // Every entry with what the search matched in it.
  const matches = useMemo(() => {
    const out = {};
    sections.forEach(({ id }) => {
      out[id] = entries[id]
        .map((entry) => {
          if (!q) return { entry, methodHit: false, techHit: false };
          const inHead = [entry.term, entry.definition, entry.caveat].some((t) => norm(t).includes(q));
          const techHit = norm(entry.technical).includes(q);
          const methodHit = techHit || norm(entry.plain).includes(q);
          return inHead || methodHit ? { entry, methodHit, techHit } : null;
        })
        .filter(Boolean);
    });
    return out;
  }, [q]);

  const total = sections.reduce((n, { id }) => n + entries[id].length, 0);
  const found = sections.reduce((n, { id }) => n + matches[id].length, 0);
  const shown = sections.filter(({ id }) => (category === ALL || category === id) && matches[id].length > 0);
  const shownCount = shown.reduce((n, { id }) => n + matches[id].length, 0);

  const isOpen = (key, methodHit) => (chosen.has(key) ? chosen.get(key) : Boolean(q) && methodHit);
  const toggle = (key, methodHit) => setChosen((prev) => new Map(prev).set(key, !isOpen(key, methodHit)));
  const setAll = (open) => setChosen((prev) => {
    const next = new Map(prev);
    shown.forEach(({ id }) => matches[id].forEach(({ entry }) => next.set(keyOf(id, entry.term), open)));
    return next;
  });
  const clearSearch = () => {
    search('');
    searchRef.current?.focus();
  };

  return (
    <main className="data-dictionary-page">
      <header className="dict-hero">
        <div className="dict-hero-text">
          <span className="dict-eyebrow">Data dictionary</span>
          <h2 className="page-header-title">Reference <span className="page-title-accent">Guide</span></h2>
          <p className="dict-hero-sub">
            Understand the dashboard&apos;s terminology, metrics, and methodologies. Learn what each figure means,
            how it is calculated, and how to interpret the results.
          </p>
        </div>
        <div className="dict-hero-side">
          <Link className="btn btn-secondary" to="/">
            <ArrowLeft size={15} aria-hidden="true" />
            Back to dashboard
          </Link>
          <span className="dict-hero-icon" aria-hidden="true"><BookOpen size={34} strokeWidth={1.6} /></span>
        </div>
      </header>

      <div className="dict-notices">
        <div className="dict-notice is-info">
          <Info size={18} aria-hidden="true" />
          <div>
            <strong>Figures depend on the selected principal, date range, and whether sample data is on.</strong>
            <p>
              Where data is unavailable or a basis is still provisional, the dashboard labels the limitation
              rather than treating it as a measured value.
            </p>
          </div>
        </div>
        <div className="dict-notice is-tip">
          <Lightbulb size={18} aria-hidden="true" />
          <div>
            <strong>How to use this page</strong>
            <p>
              Search for a term or browse by category to understand what each metric means, how it is calculated,
              and any important limitations.
            </p>
          </div>
        </div>
      </div>

      <div className="ui-card dict-toolbar-card">
      <div className="dict-toolbar" ref={toolbarRef}>
        <div className="dict-search">
          <Search size={17} aria-hidden="true" />
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(e) => search(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Escape' && query) { e.preventDefault(); search(''); } }}
            placeholder="Search a term (e.g. safety stock, ABC)"
            aria-label="Search the reference guide"
          />
          {query && (
            <button type="button" className="dict-search-clear" onClick={clearSearch} aria-label="Clear search">
              <X size={16} aria-hidden="true" />
            </button>
          )}
        </div>
        <div className="dict-pills" role="group" aria-label="Categories">
          {[{ id: ALL, label: 'All terms', icon: BookOpen }, ...sections].map(({ id, label, icon: Icon }) => {
            const count = id === ALL ? found : matches[id].length;
            return (
              <button
                key={id}
                type="button"
                className={`dict-pill${category === id ? ' is-active' : ''}`}
                aria-pressed={category === id}
                onClick={() => pickCategory(id)}
              >
                <Icon size={15} aria-hidden="true" />
                <span>{label}</span>
                <span className="dict-pill-count">{count}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="dict-status" role="status">
        <span>
          {q
            ? `${shownCount} of ${total} terms match “${query.trim()}”${category !== ALL ? ` in ${sections.find((s) => s.id === category).label}` : ''}`
            : `${shownCount} ${shownCount === 1 ? 'term' : 'terms'}`}
        </span>
        {shownCount > 0 && (
          <span className="dict-status-actions">
            <button type="button" onClick={() => setAll(true)}>Open all</button>
            <button type="button" onClick={() => setAll(false)}>Close all</button>
          </span>
        )}
      </div>
      </div>

      <div className="dict-results">
      {shown.length === 0 ? (
        <div className="dict-empty ui-card">
          <SearchX size={28} aria-hidden="true" />
          <h3>No terms match “{query.trim()}”{category !== ALL ? ` in ${sections.find((s) => s.id === category).label}` : ''}</h3>
          <p>Try a shorter word, such as “stock”, “ABC” or “sales”.</p>
          <div className="dict-empty-actions">
            {category !== ALL && found > 0 && (
              <button type="button" className="btn btn-secondary" onClick={() => pickCategory(ALL)}>
                Show {found} {found === 1 ? 'match' : 'matches'} in all categories
              </button>
            )}
            <button type="button" className="btn btn-primary" onClick={clearSearch}>Clear search</button>
          </div>
        </div>
      ) : (
        <div className="dict-sections">
          {shown.map(({ id, label, icon: Icon, blurb }) => (
            <section key={id} className="dict-section ui-card" id={id} aria-labelledby={`${id}-title`}>
              <header className="dict-section-head">
                <span className="dict-section-icon" aria-hidden="true"><Icon size={18} /></span>
                <div>
                  <h3 id={`${id}-title`}>{label}</h3>
                  <p>{blurb}</p>
                </div>
                <span className="dict-section-count">
                  {matches[id].length} {matches[id].length === 1 ? 'term' : 'terms'}
                </span>
              </header>
              <div className="dict-entries">
                {matches[id].map(({ entry, methodHit, techHit }) => {
                  const key = keyOf(id, entry.term);
                  return (
                    <GlossaryEntry
                      key={key}
                      entryKey={key}
                      entry={entry}
                      query={q}
                      open={isOpen(key, methodHit)}
                      techHit={Boolean(q) && techHit}
                      onToggle={() => toggle(key, methodHit)}
                    />
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
      </div>
    </main>
  );
};

export default DataDictionary;
