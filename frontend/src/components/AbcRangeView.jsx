// The ABC page ranked over the dashboard's selected range, not one month
// (Technical Adviser, 2 Oct 2026: "important" should follow the chosen
// period). Same ranking as the dashboard's ABC ring and class list
// (GET /dashboard/pareto), so a count on the dashboard is the count here.
//
// Stock status, target stock and the movement (FSN) classes belong to one
// month's plan and run, so this view leaves them out and says where they
// are, instead of pairing a range ranking with one month's stock.
import React, { useEffect, useMemo, useState } from 'react';
import SectionLede from './ui/SectionLede';
import { useNavigate } from 'react-router-dom';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import { AlertTriangle, CheckCircle2, Info, Search, X } from 'lucide-react';
import KPICard from './KPICard';
import ProductName from './ProductName';
import Pagination from './Pagination';
import ParetoCurve from './ParetoCurve';
import { ClassBadge } from './ui/StatusBadge';
import { formatCompactPesos } from '../utils/formatters';
import { yoyText } from './ClassProductsModal';
import { getRangePareto, getRangeYoy } from '../api/dashboard';
import { labelForPrincipal } from '../principals';
import { LoadingStatus, SkeletonStatCards, SkeletonTable } from './Skeleton';

// Below this many ranked items the 80/20 check says nothing: the same
// floor the monthly view uses (PARETO_MIN_ITEMS, backend/routers/abc.py:160).
const PARETO_MIN_ITEMS = 10;
const PAGE_SIZE_OPTIONS = [25, 50, 100];
const CLASS_ACCENT = { A: 'var(--color-abc-a)', B: 'var(--color-abc-b)', C: 'var(--color-abc-c)' };

const pct = (share, digits = 1) => (share == null ? '—' : `${(share * 100).toFixed(digits)}%`);

const AbcRangeView = ({ startPeriod, endPeriod, principal, initialClass = null, onShowMonth }) => {
  const navigate = useNavigate();
  const canOpenForecast = usePermissions().hasPermission(P.FORECAST_VIEW);
  const key = JSON.stringify([startPeriod, endPeriod, principal]);
  const [state, setState] = useState({ key: null, pareto: null, yoy: null, error: null });
  const [classFilter, setClassFilter] = useState(initialClass || 'ALL');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  useEffect(() => {
    let cancelled = false;
    const args = { period: endPeriod, startPeriod, principal };
    // Year-over-year is an extra column: the ranking still shows without it.
    Promise.all([getRangePareto(args), getRangeYoy(args).catch(() => null)])
      .then(([pareto, yoy]) => { if (!cancelled) setState({ key, pareto, yoy, error: null }); })
      .catch((err) => { if (!cancelled) setState({ key, pareto: null, yoy: null, error: err.message || 'Failed to load the ranking' }); });
    return () => { cancelled = true; };
    // The three inputs are read through `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const loading = state.key !== key;
  const pareto = loading ? null : state.pareto;
  const blocks = useMemo(() => pareto?.principals || [], [pareto]);

  // One row per ranked product (Del Monte: category) across the principals
  // in scope, each keeping its own principal's rank and shares.
  const rows = useMemo(() => {
    const yoyByKey = new Map(
      (state.yoy?.principals || []).flatMap((p) => (p.rows || []).map((r) => [`${p.principal}|${r.product_key}`, r])),
    );
    return blocks.flatMap((block) => (block.classes || []).flatMap((cls) => (cls.products || []).map((item) => ({
      ...item,
      principal: block.principal,
      isCategory: block.grain === 'category',
      tier: cls.tier,
      yoy: yoyText(yoyByKey.get(`${block.principal}|${item.product_key}`)),
    }))));
  }, [blocks, state.yoy]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => (classFilter === 'ALL' || r.tier === classFilter)
      && (!q || String(r.product_name || r.category_path || '').toLowerCase().includes(q)
        || String(r.sku_id || '').toLowerCase().includes(q)));
  }, [rows, classFilter, query]);

  useEffect(() => { setPage(1); }, [classFilter, query, key]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageRows = filtered.slice((page - 1) * pageSize, page * pageSize);
  const label = pareto?.label || 'the selected range';
  const multi = blocks.length > 1;
  const allCategories = blocks.length > 0 && blocks.every((b) => b.grain === 'category');
  const noun = allCategories ? 'categories' : multi ? 'items' : 'SKUs';

  const monthNote = (
    <p className="ui-note is-info">
      <Info size={14} aria-hidden="true" />
      <span>
        <strong>Ranked on sales over {label}</strong>, the same ranking as the dashboard. Stock status, target stock
        and fast/slow/non-moving belong to one month&apos;s plan, so they are on the{' '}
        <button type="button" className="abc-range-inline-link" onClick={onShowMonth}>one-month view</button>.
      </span>
    </p>
  );

  if (loading && !state.pareto) {
    return (
      <>
        {monthNote}
        <LoadingStatus>Loading the ranking for the selected range…</LoadingStatus>
        <div className="kpi-strip abc-summary-grid abc-range-kpis"><SkeletonStatCards count={3} /></div>
        <div className="data-table-card"><SkeletonTable rows={8} columns={7} /></div>
      </>
    );
  }
  if (state.error) {
    return (
      <>
        {monthNote}
        <p className="abc-page-subtitle" role="alert">Failed to load the ranking: {state.error}</p>
      </>
    );
  }

  return (
    <>
      {monthNote}

      {blocks.map((block) => {
        const check = block.pareto_check;
        const many = block.grain === 'category' ? 'categories' : 'SKUs';
        return (
          <React.Fragment key={block.principal}>
            {multi && <h3 className="abc-range-principal">{labelForPrincipal(block.principal)}</h3>}
            <SectionLede className="is-standalone">How the products split by value</SectionLede>
            <div className="kpi-strip abc-summary-grid abc-range-kpis">
              {(block.classes || []).map((cls) => (
                <KPICard
                  key={cls.tier}
                  title={`Class ${cls.tier}`}
                  value={cls.count.toLocaleString()}
                  unit={many}
                  contextLine={`${pct(cls.share)} of revenue · ${label}`}
                  note={cls.revenue != null ? `about ${formatCompactPesos(cls.revenue)}` : null}
                  accent={CLASS_ACCENT[cls.tier]}
                  icon={<span className={`abc-kpi-letter abc-kpi-letter-${cls.tier.toLowerCase()}`} aria-hidden="true">{cls.tier}</span>}
                />
              ))}
            </div>
            {block.blocked_reason && <p className="ui-note is-info"><Info size={14} aria-hidden="true" /><span>{block.blocked_reason}</span></p>}
            {check && check.ranked_count < PARETO_MIN_ITEMS && (
              <p className="ui-note is-info">
                <Info size={14} aria-hidden="true" />
                <span>
                  <strong>Pareto check not applicable:</strong> too few {many} for an 80/20 check ({check.ranked_count} ranked;
                  it needs at least {PARETO_MIN_ITEMS}).
                </span>
              </p>
            )}
            {check && check.ranked_count >= PARETO_MIN_ITEMS && (
              <p className={`ui-note ${check.passes ? 'is-success' : 'is-warning'}`}>
                {check.passes ? <CheckCircle2 size={14} aria-hidden="true" /> : <AlertTriangle size={14} aria-hidden="true" />}
                <span>
                  <strong>Pareto check {check.passes ? 'passes' : 'fails'}:</strong>{' '}
                  the top {pct(check.top_fraction, 0)} of {many} ({check.top_count.toLocaleString()} of the{' '}
                  {check.ranked_count.toLocaleString()} ranked) earn {pct(check.revenue_share)} of {label} revenue,{' '}
                  {check.passes ? 'inside' : 'outside'} the {pct(check.band_low, 0)}–{pct(check.band_high, 0)} range
                  a valid classification should fall in.
                </span>
              </p>
            )}
            <SectionLede className="is-standalone">How few products make most of the sales</SectionLede>
            <ParetoCurve block={block} cutoffs={pareto?.cutoffs} label={label} />
          </React.Fragment>
        );
      })}

      <div className="abc-filters-row abc-range-filters">
        <div className="abc-search-wrapper">
          <Search size={16} className="abc-search-icon" aria-hidden="true" />
          <input
            type="search"
            className="abc-search-input"
            placeholder={allCategories ? 'Search a category' : 'Search a product name or SKU code'}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search the ranking"
          />
          {query && (
            <button type="button" className="abc-range-clear" onClick={() => setQuery('')} aria-label="Clear the search">
              <X size={14} />
            </button>
          )}
        </div>
        <div className="segmented" role="tablist" aria-label="Filter by class">
          {['ALL', 'A', 'B', 'C'].map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={classFilter === t}
              className={`segmented-item${classFilter === t ? ' is-active' : ''}`}
              onClick={() => setClassFilter(t)}
            >
              {t === 'ALL' ? 'All classes' : `Class ${t}`}
              <span className="segmented-count">{(t === 'ALL' ? rows : rows.filter((r) => r.tier === t)).length.toLocaleString()}</span>
            </button>
          ))}
        </div>
      </div>

      <SectionLede className="is-standalone">Every product, ranked by sales value</SectionLede>
      <div className="data-table-card">
        <table className="data-table abc-table">
          <thead>
            <tr>
              <th className="table-num col-fit">#</th>
              <th className="col-text col-product">{allCategories ? 'Category' : 'Product'}</th>
              <th className="table-center col-fit">Class</th>
              <th className="table-num">Revenue (₱)<span className="abc-th-sub">{label}</span></th>
              <th className="table-num">Sold (pieces)<span className="abc-th-sub">{label}</span></th>
              <th className="table-num">Share<span className="abc-th-sub">of revenue</span></th>
              <th className="table-num">Running total<span className="abc-th-sub">top seller down</span></th>
              <th className="table-num">Change<span className="abc-th-sub">vs {state.yoy?.prior_label || 'a year earlier'}</span></th>
              <th className="table-num col-fit">Months sold<span className="abc-th-sub">in the range</span></th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r) => (
              <tr key={`${r.principal}|${r.product_key ?? r.category_path}`}>
                <td className="table-num col-fit">{r.rank}</td>
                <td className="col-text col-product">
                  <ProductName
                    name={r.product_name || r.category_path}
                    code={r.isCategory ? null : r.sku_id}
                    onOpen={canOpenForecast && !r.isCategory && r.sku_id ? () => navigate(`/forecast?sku=${encodeURIComponent(r.sku_id)}`) : undefined}
                    openLabel="Open its forecast"
                  />
                  {multi && <span className="abc-th-sub">{labelForPrincipal(r.principal)}</span>}
                </td>
                <td className="table-center col-fit"><ClassBadge tier={r.tier} /></td>
                <td className="table-num">{formatCompactPesos(r.revenue)}</td>
                <td className="table-num">{r.isCategory || r.pieces == null ? '—' : Math.round(r.pieces).toLocaleString()}</td>
                <td className="table-num">{pct(r.share, 2)}</td>
                <td className="table-num">{pct(r.cumulative_share)}</td>
                <td className={`table-num${r.yoy.tone ? ` abc-yoy-${r.yoy.tone}` : ''}`}>{r.yoy.text}</td>
                <td className="table-num col-fit">{r.months_with_sales ?? '—'}</td>
              </tr>
            ))}
            {pageRows.length === 0 && (
              <tr><td colSpan={9} className="abc-range-empty">No {noun} match this filter.</td></tr>
            )}
          </tbody>
        </table>
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          totalItems={filtered.length}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={(n) => { setPageSize(n); setPage(1); }}
          pageSizeOptions={PAGE_SIZE_OPTIONS}
          idPrefix="abc-range"
        />
      </div>
    </>
  );
};

export default AbcRangeView;
