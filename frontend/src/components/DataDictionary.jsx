// Reference Guide (/data-dictionary): the dashboard's data dictionary, what
// each figure means and how it is formed. Content by Maica (94bc190); the
// layout redesigned 2026-10-18 after Audrey's mock-up: a header band, two
// notices, a search over every entry, category pills, and glossary rows
// whose definition is always visible and whose methodology opens on demand
// (a quick glossary for staff, the full method for reviewers).
//
// The entries below are the page's only content. The definitions and
// methodologies are Maica's text, unchanged; `tags` and `caveat` are
// display-only labels (a caveat repeats, in a few words, a limitation its
// own methodology already states, so it stays visible while the methodology
// is closed). Nothing on this page reads the principal, range or data mode:
// it explains them, so the top bar's principal switch is not shown here.
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle, ArrowLeft, BarChart3, BookOpen, Calculator, ChevronDown, ClipboardCheck, Database, Info, Lightbulb,
  Search, SearchX, Star, TrendingUp, X,
} from 'lucide-react';
import './DataDictionary.css';

// In alphabetical order (Audrey, 2026-10-18), for the pills and the sections.
const sections = [
  { id: 'forecasts', label: 'Forecasts', icon: TrendingUp, blurb: 'The SKU Forecast page and the forecast cards.' },
  { id: 'reorder-planning', label: 'Reorder Planning', icon: ClipboardCheck, blurb: 'The Reorder Recommendations page and the order plan.' },
  { id: 'sales-stock', label: 'Sales & Stock', icon: Database, blurb: 'The sales, stock and purchases charts.' },
  { id: 'summary', label: 'Summary', icon: BarChart3, blurb: 'The cards at the top of the dashboard.' },
  { id: 'top-products', label: 'Top Products', icon: Star, blurb: 'How products are ranked into classes.' },
];

const entries = {
  // Forecasts and Reorder Planning: added 2026-10-18. Each entry states what
  // the code does, from the file named beside it; numbers that are
  // placeholders say so (analytics/params.PLACEHOLDERS).
  forecasts: [
    {
      // analytics/forecasting/router.py (LIVE_MODEL, the history-length bins);
      // backend/routers/forecast.py (Unilever Tier A only).
      term: 'Forecast',
      tags: ['Forecasting'],
      caveat: 'Unilever Class A only',
      definition: 'The number of pieces a top-selling product is expected to sell in the planning month.',
      method: 'Made for Unilever’s Class A products only; Del Monte’s sales have no product column, so it has no product forecasts. The model depends on how many months of sales the product has: under 3 months, a provisional trailing average; 3 to 11 months, a 3-month moving average (MA3); 12 to 23 months, TSB, a method for products that do not sell every month; 24 months or more, the average of a machine-learning model (XGBoost) and MA3. MA3 is the benchmark every model is scored against and the fallback when another cannot be used. On SSM’s data the other models tie with MA3; they are used because they draw on the product’s full history, not because they proved more accurate.',
    },
    {
      // scripts/run_baseline_forecast.py (_confidence_band, CONFIDENCE_Z =
      // analytics.params.FORECAST_INTERVAL_Z = 1.645).
      term: 'Likely range',
      tags: ['Forecasting'],
      definition: 'The band around a forecast where actual sales are expected to land about 9 times in 10.',
      method: 'The forecast plus or minus 1.645 times the product’s own forecast error (RMSE) on its most recent months held back for testing, for the model actually used. It is an approximate band from a short test window. When that error cannot be measured, no band is drawn rather than an invented one.',
    },
    {
      // analytics/forecasting/diagnostic_metrics.py (mase, naive_scale);
      // analytics/params.MASE_GATE = 1.0; scripts/run_lp.py (candidate pool).
      term: 'MASE (forecast error score)',
      tags: ['Forecasting', 'Accuracy'],
      definition: 'How large a forecast’s errors are compared with simply guessing that next month will equal this month.',
      method: 'The average absolute error on the held-back months, divided by the average month-to-month change in the product’s real sales history. Below 1 means the forecast beats that simple guess. Only products scoring below 1 go into the order plan. It is computed on real months only, never on synthetic data.',
    },
  ],
  'reorder-planning': [
    {
      // backend/stock_status.py (CRITICAL / LOW / IN STOCK -> CRITICAL /
      // URGENT / PLANNED).
      term: 'Critical, Urgent and Planned',
      tags: ['Reorder', 'Risk'],
      definition: 'How pressing each suggested order is.',
      method: 'Critical: stock is below the product’s safety stock. Urgent: stock is at or above safety stock but below the target stock. Planned: stock is at or above the target stock. Stock is the count that opens the planning month, in pieces.',
    },
    {
      // scripts/run_lp.py (_sigma_d_for_product, safety_stock_for);
      // analytics/params (SERVICE_Z 1.28, SERVICE_LEVEL_PCT 90,
      // PLACEHOLDERS review_days 5, lead_days 3).
      term: 'Safety stock',
      tags: ['Reorder', 'Stock'],
      caveat: 'Inputs are placeholders',
      definition: 'Extra stock kept so a product does not run out if sales come in higher than forecast before the next delivery.',
      method: '1.28 (for a 90% service level) times the product’s daily demand variability times the square root of the review period plus the lead time, in pieces. The review period (weekly orders, 5 business days) and lead time (3 business days) are placeholders until SSM confirms them. Unilever has no daily sales, so its daily variability is worked out from monthly sales (the monthly variation divided by the square root of the average business days in a month); that assumption awaits the adviser’s ruling.',
    },
    {
      // analytics/optimization/lp.py (target_stock: T_i = w_i x (R + L) / 5
      // + SS_i); scripts/run_lp.py (stored as rop_i).
      term: 'Target stock',
      tags: ['Reorder', 'Stock'],
      definition: 'The stock level an order tops a product back up to.',
      method: 'The weekly forecast times (review days plus lead days) divided by 5, plus the safety stock: the sales expected before the next delivery arrives, plus the safety buffer. In pieces. It is stored in a database column named “rop”, but it is a target level, not a reorder point.',
    },
    {
      // analytics/optimization/lp.py (need_i, the three layers, stage 1).
      term: 'Suggested order',
      tags: ['Reorder', 'Planning'],
      definition: 'How many pieces to order for the month, which SSM splits into weekly purchase orders.',
      method: 'The need is the month’s forecast plus the target stock, minus the stock on hand, and never below zero, so an overstocked product orders nothing. The plan orders the whole need when the supplier allocation allows. When it does not, it cuts in this order: the rest of the target first, then the safety stock, and this month’s expected sales last.',
    },
    {
      // analytics/params.LP_WEIGHTS; analytics/optimization/lp.py (stage 3).
      term: 'Order weights (45 / 35 / 20)',
      tags: ['Reorder', 'Planning'],
      caveat: 'Costs are placeholders',
      definition: 'How the plan decides which products give way when the supplier allocation cannot cover every order.',
      method: 'Cost 45%, service level 35% (the share of the need met, weighted by each product’s sales value) and storage 20%. They only matter when the allocation is short; with enough allocation every need is ordered in full. The procurement and storage costs behind them are placeholders until SSM supplies its figures.',
    },
    {
      // analytics/allocation.monthly_allocation; scripts/run_lp.py
      // (allocation_ceilings); analytics/params ALLOCATION_DEFAULT_PCT.
      term: 'Monthly supplier allocation',
      tags: ['Reorder', 'Planning'],
      definition: 'The most pieces the plan may order from a principal in a month.',
      method: 'Last year’s sales in pieces times the allocation percentage (103% by default; 105% or 108%), divided by 12, for each principal. The percentage is the rule SSM described in the September 2026 client meeting; which level applies is still to be confirmed by SSM.',
    },
    {
      // backend/stock_status.py (COUNT_OMITS_ZERO_STOCK, NO DATA);
      // scripts/run_lp.py (stock on hand: no row counts as 0).
      term: 'Not in the stock count',
      tags: ['Stock', 'Data quality'],
      definition: 'A planned product that does not appear in the stock count that opens the plan.',
      method: 'For Unilever it is read as 0 on hand, because its stock files never list a product with zero stock. For Del Monte a missing product says nothing about its stock, so it is shown as no data instead.',
    },
  ],
  summary: [
    {
      term: 'Annual sales and allocation',
      tags: ['Sales', 'KPI'],
      definition: 'Sales recorded for the displayed financial year, alongside the selected supplier-allocation level.',
      method: 'The target is the prior year’s sales multiplied by the selected 103%, 105%, or 108% level. The pace compares average monthly sales so far with that level’s monthly amount. Year-to-date sales are compared with the same months in the prior year; if the months on record differ, the page marks the comparison as not like-for-like.',
    },
    {
      term: 'Inventory value',
      tags: ['Inventory', 'Stock'],
      definition: 'The value of stock in the latest available count on or before the selected date range ends.',
      method: 'Stock is valued using each product’s last purchase price. This is a stock snapshot, not the value of purchases or sales during the selected range.',
    },
    {
      term: 'Stock cover',
      tags: ['Inventory', 'KPI'],
      caveat: 'Provisional for Unilever',
      definition: 'An estimate of how long the counted stock would last at the recent sales rate.',
      method: 'Stock value is compared with average weekly sales over the 12 months up to the stock count. The card compares the result with SSM’s three-week policy. Stock is valued at purchase price while sales are at selling price, so the bases differ. Unilever’s figure is marked provisional because its stock and sales sources do not yet have a confirmed location match.',
    },
    {
      term: 'Below safety stock',
      tags: ['Inventory', 'Risk'],
      definition: 'Counted top sellers whose available stock is below their calculated safety-stock level.',
      method: 'Only products with both a usable stock count and a safety-stock target can be compared. The displayed total is not a count of every product in the catalogue.',
    },
    {
      term: 'Pending reorders',
      tags: ['Reorder', 'Planning'],
      definition: 'Reorder recommendations that are still waiting for a decision.',
      method: 'This reflects the current reorder-plan cycle. It is separate from the number of products below safety stock.',
    },
  ],
  'sales-stock': [
    {
      term: 'Sales',
      tags: ['Sales'],
      definition: 'Recorded sales value for the selected principal and period, shown in pesos.',
      method: 'Sales use the source’s recorded selling values. The comparison and range totals only cover months with sales on record; gaps are not silently treated alike for both principals.',
    },
    {
      term: 'Stock on hand',
      tags: ['Inventory', 'Stock'],
      definition: 'The value of stock recorded in an inventory count for a month.',
      method: 'The chart labels stock by its count date when available. Del Monte’s records may identify only the count month, not the exact day. Inventory value uses last purchase price; this is not a unit count.',
    },
    {
      term: 'Purchases received',
      tags: ['Stock', 'Purchases'],
      caveat: 'May be estimated',
      definition: 'The value of recorded stock receipts for a month, shown in the Purchases view.',
      method: 'Where purchase records are unavailable, receipts may be estimated from stock counts and sales. The chart marks estimates explicitly; estimated receipts are not a dashboard KPI.',
    },
    {
      term: 'Returns',
      tags: ['Sales'],
      definition: 'The value of returns present in the source records.',
      method: 'The Returns view uses recorded returns only. It does not fill missing return data with an estimate.',
    },
    {
      term: 'Annual sales',
      tags: ['Sales'],
      definition: 'Sales grouped by calendar year in the annual view.',
      method: 'A partial year is labelled with the months on record. In demonstration mode, generated months are visibly identified and are not presented as real results.',
    },
    {
      term: 'Missing months and estimates',
      tags: ['Data quality'],
      caveat: 'Means different things per principal',
      definition: 'A missing data point can mean different things depending on the source.',
      method: 'For Unilever, a month without a sales row is treated as zero sales. For Del Monte, a missing category month means the data was not collected, not that sales were zero. Any demonstration estimates are labelled; generated data does not feed real KPIs, forecasts, ABC classifications, or the real order plan.',
    },
  ],
  'top-products': [
    {
      term: 'ABC classification',
      tags: ['ABC', 'Ranking'],
      definition: 'A ranking that groups products by their share of recorded revenue.',
      method: 'Items are sorted from highest to lowest revenue and assigned using cumulative revenue share: Class A through 80%, Class B from 80% to 95%, and Class C from 95% onward. These are ranking cutoffs, not a promise that a fixed number of items falls into each class.',
    },
    {
      term: 'Top products / Class A',
      tags: ['ABC'],
      caveat: 'Basis pending adviser confirmation',
      definition: 'The high-revenue items in the most recent applicable ABC classification run.',
      method: 'Unilever uses Class A over the latest 12 months, plus products first sold within 12 months that are Class A over the latest three months. This basis is pending Technical Adviser confirmation. Del Monte remains classified on the single-month basis; its ranked items are categories, not individual SKUs.',
    },
    {
      term: 'Classification period',
      tags: ['ABC'],
      definition: 'The month for which the ABC classes were calculated.',
      method: 'The classification period is shown separately from the dashboard’s selected sales range because a saved ABC run may be for a different period. Check the displayed period before comparing classes with the range.',
    },
    {
      term: 'Revenue share and cumulative share',
      tags: ['ABC', 'Sales'],
      definition: 'Revenue share is one item’s portion of total ranked revenue; cumulative share is the running total down the revenue ranking.',
      method: 'These shares determine ABC class. They describe historical revenue contribution and are not a forecast, stock-risk score, or order quantity.',
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

// One glossary row: the term, its tags and any caveat; the definition; the
// methodology behind a toggle.
function GlossaryEntry({ entryKey, entry, query, open, onToggle }) {
  const panelId = `method-${entryKey.replace(/[^a-z0-9]+/gi, '-')}`;
  return (
    <article className={`dict-entry${open ? ' is-open' : ''}`}>
      <div className="dict-entry-main">
        <div className="dict-entry-term">
          <h4><Highlight text={entry.term} query={query} /></h4>
          <div className="dict-tags">
            {entry.tags.map((t) => (
              <span key={t} className="dict-tag"><Highlight text={t} query={query} /></span>
            ))}
          </div>
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
          <span>{open ? 'Hide methodology' : 'View methodology'}</span>
          <ChevronDown size={16} className="dict-chevron" aria-hidden="true" />
        </button>
      </div>
      <div className="dict-method" id={panelId} role="region" aria-label={`Methodology: ${entry.term}`} hidden={!open}>
        <div className="dict-method-inner">
          <span className="dict-method-label">
            <Calculator size={14} aria-hidden="true" />
            Methodology
          </span>
          <p><Highlight text={entry.method} query={query} /></p>
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

  // A shorter placeholder where the long one would be cut off.
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 600px)').matches);
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 600px)');
    const onChange = (e) => setNarrow(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  // Every entry with what the search matched in it.
  const matches = useMemo(() => {
    const out = {};
    sections.forEach(({ id }) => {
      out[id] = entries[id]
        .map((entry) => {
          if (!q) return { entry, methodHit: false };
          const inHead = [entry.term, entry.definition, ...entry.tags].some((t) => norm(t).includes(q));
          const methodHit = norm(entry.method).includes(q);
          return inHead || methodHit ? { entry, methodHit } : null;
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
            <strong>Figures depend on the selected principal, date range, and data mode.</strong>
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

      <div className="dict-toolbar" ref={toolbarRef}>
        <div className="dict-search">
          <Search size={17} aria-hidden="true" />
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(e) => search(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Escape' && query) { e.preventDefault(); search(''); } }}
            placeholder={narrow ? 'Search terms or metrics…' : 'Search terms or metrics (e.g., sales, inventory, ABC, returns...)'}
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
            <button type="button" onClick={() => setAll(true)}>Open all methodologies</button>
            <button type="button" onClick={() => setAll(false)}>Close all</button>
          </span>
        )}
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
                  <p>{blurb} Definitions and how the dashboard figures are formed.</p>
                </div>
                <span className="dict-section-count">
                  {matches[id].length} {matches[id].length === 1 ? 'term' : 'terms'}
                </span>
              </header>
              <div className="dict-entries">
                {matches[id].map(({ entry, methodHit }) => {
                  const key = keyOf(id, entry.term);
                  return (
                    <GlossaryEntry
                      key={key}
                      entryKey={key}
                      entry={entry}
                      query={q}
                      open={isOpen(key, methodHit)}
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
