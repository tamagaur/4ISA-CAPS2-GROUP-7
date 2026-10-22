import React, { useEffect, useState } from 'react';
import SectionLede from './ui/SectionLede';
import { ArrowUpRight, ArrowDownRight, Minus, Activity, CalendarRange, Waves } from 'lucide-react';
import { getSegment } from '../api/segment';
import { getDecomposition } from '../api/analytics';
import { formatMonth } from '../utils/formatDate';
import { SEMANTIC } from '../theme/colors';
import { LoadingStatus, SkeletonLine } from './Skeleton';
import InfoTip from './InfoTip';
import './SkuDemandPatternPanel.css';

// "Demand pattern" — the SKU's trend and variability, question D4 of the
// analytical mapping (reports/PROJECT_DIAGNOSIS_2026-09-21.md §3): the
// Phase-2 segmentation traits (sku_traits + sku_segment, migration 0018)
// read through GET /segment, and STL seasonality from GET /decomposition.
// Descriptive: it measures the SKU's own history. Shown on the SKU
// Forecast page and inside the Reorder detail modal, the two places a
// planner looks at one SKU. Everything here is printed from a real column;
// the only labels this component adds are the volatility band (from the
// backend's cv_band, with the cv under it as a percentage of an average
// month and the raw figure behind the "?"), the plain-
// language gloss on each stability_group code, the plain name of the
// SKU's bin (both codes stay in the tooltip), and the seasonality band
// over STL's measured strength (GET /decomposition). bin_reason is printed
// verbatim — it is the pipeline's own explanation and must not be
// paraphrased into something it didn't say.

// Coefficient-of-variation bands are a display convention over the stored
// cv (thresholds live in backend/routers/segment.py: < 0.5 low, < 1.0
// medium, else high). Colours follow the app-wide rule: green = steady,
// amber = watch, red = erratic enough to act on.
// `label` is the plain word on the tile (2026-10-20, src/labels.js wording);
// `technical` keeps the band's own name for the "?" and the details list.
const CV_BAND_META = {
  low: { label: 'Steady', technical: 'Low volatility', gloss: 'steady month to month', color: SEMANTIC.healthy },
  medium: { label: 'Up and down', technical: 'Medium volatility', gloss: 'noticeable month-to-month swings', color: SEMANTIC.watch },
  high: { label: 'Very unpredictable', technical: 'High volatility', gloss: 'erratic — spikes and gaps', color: SEMANTIC.act },
};

// Mann-Kendall trend (p < 0.05). Direction only — a rising or falling
// series isn't good or bad on its own, so these stay neutral ink, never
// green/red. `plain` is the tile's own line (the Technical Adviser, 2 Oct
// 2026: no score without its meaning); the test's name sits behind the "?".
const TREND_META = {
  up: { label: 'Going up', Icon: ArrowUpRight, gloss: 'statistically significant upward trend', plain: 'a steady rise over time' },
  down: { label: 'Going down', Icon: ArrowDownRight, gloss: 'statistically significant downward trend', plain: 'a steady fall over time' },
  none: { label: 'Not going up or down', Icon: Minus, gloss: 'no significant direction either way', plain: 'no steady rise or fall' },
};

// stability_group codes from reports/BINNING_ROUND1_2026-09.md (38-period
// window, 2023-01 to 2026-02).
//
// These count CATEGORY-A MEMBERSHIP, not selling months: orchestrate_segment.py
// derives them from COUNT(*) over abc_classification WHERE tier = 'A', and
// traits.py::stability_group() buckets that count (== 38 -> all_38,
// >= 30 -> at_least_30, else churn). An earlier version of this gloss
// described them as selling months, which printed a visible contradiction —
// a SKU with history_months = 31 rendered "31 selling months" beside
// "Fewer than 30 selling months". history_months is a separate trait and is
// shown in its own tile.
//
// The number in a code is the run's own period count: 38 on the single-month
// Tier A basis, 27 on the 12-month one (all_27 and at_least_21 are live since
// 2026-10-11, Kelvin's 930792a and migration 0051). It is read from the code,
// so another basis needs no change here.
const stabilityGloss = (group) => {
  const all = /^all_(\d+)$/.exec(group || '');
  if (all) return `A top seller (Class A) in all ${all[1]} periods observed`;
  const atLeast = /^at_least_(\d+)$/.exec(group || '');
  if (atLeast) return `A top seller (Class A) in at least ${atLeast[1]} of the periods observed, but not all`;
  if (group === 'churn') return 'Moves in and out of the top sellers (Class A)';
  return group;
};

// Bins of the combined_v1 scheme (sales-month length, with the long bin
// split by Mann-Kendall trend), plus length_v2's plain `long` for the
// fallback when combined_v1 is absent. The history-length bins are the same
// ones the forecast router serves a model per (utils/forecastModel.js).
const BIN_LABELS = {
  insufficient: 'Too little history',
  short: 'Short history',
  medium: 'Medium history',
  long: 'Long history',
  long_up: 'Long history, rising',
  long_flat: 'Long history, flat',
  long_down: 'Long history, falling',
};

// The seasonality label is the backend's (GET /decomposition yearly_pattern,
// analytics/forecasting/decomposition.py, 2026-10-04): "Repeats yearly",
// "No reliable yearly pattern" or "Not enough history (needs 24 months)",
// from the lag-12 autocorrelation test. It replaced bands over STL strength
// ("Strong seasonality" at >= 0.6), which read 15-18% of patternless series
// as strong at our lengths. Peak and trough months are named only for a
// product that repeats yearly; STL strength stays as a measured number.
const SEASONALITY_TOOLTIP =
  'Does a month sell like the same month a year earlier? Measured as the correlation between each '
  + 'month and the same month a year before (lag-12 autocorrelation), from the first sale; it counts '
  + 'as a yearly pattern above the 95% bound 1.96/√months, and needs 24 months.';

// The STL figures, each with its scale, for the "?" only.
const stlStrength = (stl) => (stl.available
  ? `seasonal strength ${stl.seasonal_strength.toFixed(2)} and trend strength ${stl.trend_strength.toFixed(2)}, each on a scale of 0 to 1 (STL decomposition)`
  : null);

// The tile's one line, in plain words: the peak and trough months for a
// product that repeats yearly, else what the test found. The figures sit
// behind the tile's "?" (the Technical Adviser, 2 Oct 2026: a score means
// nothing to the reader without its meaning).
const shortSeasonality = (stl) => {
  const yp = stl.yearly_pattern;
  if (!yp) return stl.available ? 'the yearly check could not run' : stl.reason;
  if (yp.repeats_yearly == null) return `needs 2 years of sales; it has ${yp.months} month${yp.months === 1 ? '' : 's'}`;
  if (!yp.repeats_yearly) return 'months don\u2019t repeat last year\u2019s ups and downs';
  return stl.available ? `busiest in ${stl.peak_month}, quietest in ${stl.trough_month}` : 'the same months sell well each year';
};

// The tile's value: the backend's verdict in plain words (its own label stays
// in the details list).
const seasonalityValue = (stl) => {
  const yp = stl?.yearly_pattern;
  if (!yp || yp.repeats_yearly == null) return 'Too early to tell';
  return yp.repeats_yearly ? 'Same busy months every year' : 'No regular busy season';
};

// The same finding with its figures, for the "?".
const yearlyDescription = (stl) => {
  const yp = stl.yearly_pattern;
  if (!yp) return stl.available ? stlStrength(stl) : stl.reason;
  if (yp.repeats_yearly == null) return `${yp.months} month${yp.months === 1 ? '' : 's'} from the first sale`;
  const verdict = yp.repeats_yearly
    ? `it does${stl.available ? `, peaking in ${stl.peak_month} and lowest in ${stl.trough_month}` : ''}`
    : 'it does not';
  const measured = yp.acf_lag12 == null
    ? 'sales never varied, so there is nothing to correlate'
    : `correlation with a year earlier ${yp.acf_lag12.toFixed(2)}, against a bound of ${yp.acf_bound.toFixed(2)}`;
  const strength = stlStrength(stl);
  return `${verdict} (${measured})${strength ? `; ${strength}` : ''}`;
};

// `variant` (2026-10-20): 'tiles' (the default) is the plain panel; 'details'
// is the technical list for the Sales forecast's "Show details" section (the
// measures, test names, the stability group and the bin with its reason).
const SkuDemandPatternPanel = ({ skuId, principal, compact = false, variant = 'tiles' }) => {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });

  useEffect(() => {
    if (!skuId) return undefined;
    let cancelled = false;
    setState({ status: 'loading', data: null, error: null });
    getSegment(skuId, { principal })
      .then((res) => {
        if (cancelled) return;
        setState({ status: 'loaded', data: res, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({ status: 'error', data: null, error: err.message || 'Failed to load the demand pattern' });
      });
    return () => { cancelled = true; };
  }, [skuId, principal]);

  // STL is Unilever SKU-level only (a Del Monte row is a category with no
  // SKU series), and a failure here must not blank the rest of the panel —
  // the tile just says it couldn't be computed.
  const [stl, setStl] = useState(null);
  useEffect(() => {
    if (!skuId || principal === 'delmonte') return undefined;
    let cancelled = false;
    setStl(null);
    getDecomposition(skuId, { principal })
      .then((res) => { if (!cancelled) setStl(res ?? { available: false, reason: 'No monthly sales series for this product.' }); })
      .catch(() => { if (!cancelled) setStl({ available: false, reason: 'Could not load the seasonality check.' }); });
    return () => { cancelled = true; };
  }, [skuId, principal]);

  const heading = (
    <div className="sku-pattern-header">
      <h4 className="sku-pattern-title">
        <Activity size={15} aria-hidden="true" />
        Sales pattern
      </h4>
      <SectionLede>How this product&apos;s sales behave</SectionLede>
      {/* The months the volatility, trend and history tiles measure:
          traits.py reads the monthly pieces from the SKU's first sale up to
          the cohort month (the ABC run the cohort was drawn from). */}
      {state.data?.traits?.cohort_period && (
        <span className="sku-pattern-cohort" title={`Monthly pcs sold, measured from the first sale to the ${formatMonth(state.data.traits.cohort_period)} cohort (the ABC run this pattern was measured for)`}>
          {state.data.traits.first_sale_period
            ? `Monthly sales in pcs, ${formatMonth(state.data.traits.first_sale_period)} – ${formatMonth(state.data.traits.cohort_period)}`
            : `Cohort ${formatMonth(state.data.traits.cohort_period)}`}
        </span>
      )}
    </div>
  );

  // The four tiles the loaded panel shows (volatility, trend, history,
  // seasonality), in the same tile class, so the panel keeps its height.
  if (variant === 'details' && state.status !== 'loaded') return null;
  if (state.status === 'loading') {
    return (
      <section className={`sku-pattern${compact ? ' sku-pattern-compact' : ''}`} aria-busy="true">
        {heading}
        <LoadingStatus>Loading demand pattern…</LoadingStatus>
        <div className="sku-pattern-tiles" aria-hidden="true">
          {[0, 1, 2, 3].map((k) => (
            <div className="sku-pattern-tile" key={k}>
              <SkeletonLine width="4.5rem" height="0.6rem" />
              <SkeletonLine width="8rem" height="1rem" />
              <SkeletonLine width="90%" height="0.65rem" />
            </div>
          ))}
        </div>
      </section>
    );
  }

  if (state.status === 'error') {
    return (
      <section className={`sku-pattern${compact ? ' sku-pattern-compact' : ''}`}>
        {heading}
        <p className="sku-pattern-note" role="alert">Could not load the demand pattern: {state.error}</p>
      </section>
    );
  }

  const data = state.data;
  if (variant === 'details' && (!data || !data.analyzed)) return null;
  // A 404 (getSegment -> null) or a product with no Phase-2 rows: say so
  // plainly. Never a placeholder band or trend.
  if (!data || !data.analyzed) {
    return (
      <section className={`sku-pattern sku-pattern-unanalyzed${compact ? ' sku-pattern-compact' : ''}`}>
        {heading}
        <p className="sku-pattern-empty-title">Not worked out yet</p>
        <p className="sku-pattern-note">
          {data?.not_analyzed_reason
            || `No sales pattern has been worked out for ${skuId} yet: it isn't in any segmentation cohort.`}
        </p>
      </section>
    );
  }

  const t = data.traits;
  const band = t?.cv_band ? CV_BAND_META[t.cv_band] : null;
  const trend = t?.trend ? TREND_META[t.trend] : null;
  const TrendIcon = trend?.Icon;
  const binSegment = data.segments?.find((s) => s.scheme === 'combined_v1')
    ?? data.segments?.find((s) => s.scheme === 'length_v2')
    ?? null;

  // Preview mode (GET /segment's data_mode): the traits and the STL were
  // measured over the placeholder months too; the stability group was not.
  const previewWindow = data.data_mode?.traits_window;

  // The technical list for "Show details": every measure behind the tiles.
  if (variant === 'details') {
    return (
      <dl className="forecast-howmade-list">
        {t && (
          <div className="forecast-howmade-item">
            <dt>How steady (volatility)</dt>
            <dd>
              {band ? `${band.technical}, ` : ''}coefficient of variation (CV) {t.cv != null ? t.cv.toFixed(2) : '—'} of monthly
              pieces. Under 0.5 reads low, under 1.0 medium, else high.
            </dd>
          </div>
        )}
        {t && (
          <div className="forecast-howmade-item">
            <dt>Direction (trend)</dt>
            <dd>Mann–Kendall test from the first sale, p &lt; 0.05{trend ? `: ${trend.gloss}` : ''}.</dd>
          </div>
        )}
        {t && (
          <div className="forecast-howmade-item">
            <dt>Sold for (history)</dt>
            <dd>
              {t.history_months} selling months, longest unbroken run {t.longest_run}. {stabilityGloss(t.stability_group)}
              {t.restart_flag ? '; sales restarted after a gap of 3 or more months' : ''}.
            </dd>
          </div>
        )}
        {principal !== 'delmonte' && stl && (
          <div className="forecast-howmade-item">
            <dt>Busy months (seasonality)</dt>
            <dd>{stl.yearly_pattern?.label ? `${stl.yearly_pattern.label}: ` : ''}{yearlyDescription(stl)}. {SEASONALITY_TOOLTIP}</dd>
          </div>
        )}
        {binSegment && (
          <div className="forecast-howmade-item">
            <dt>Bin</dt>
            <dd>
              {BIN_LABELS[binSegment.bin] || binSegment.bin}
              {binSegment.bin_reason ? `. ${binSegment.bin_reason}` : ''}
            </dd>
          </div>
        )}
      </dl>
    );
  }

  return (
    <section className={`sku-pattern${compact ? ' sku-pattern-compact' : ''}`}>
      {heading}

      {previewWindow && (
        <p className="chart-placeholder-note">
          Measured {formatMonth(previewWindow.start)} – {formatMonth(previewWindow.end)}, including the 2021–22
          sample-data months (not SSM&apos;s sales). The top-seller history comes from the real rankings and is unchanged.
        </p>
      )}

      {t && (
        <div className="sku-pattern-tiles">
          {/* Volatility: the band is the headline, the raw cv sits under
              it so the label never replaces the measurement. */}
          {/* Each tile: a label, a short value, one measured figure under it.
              The gloss and the method sit behind the label's "?" (UI pass). */}
          <div className="sku-pattern-tile" style={{ '--tile-accent': band?.color || SEMANTIC.noData }}>
            <span className="sku-pattern-tile-label">
              How steady are sales?
              <InfoTip label="About how steady sales are" size={12}>
                How far a month&apos;s sales swing above or below the average month.{' '}
                Coefficient of variation (CV) of monthly pieces: how far a month&apos;s sales swing around the
                average. Under 0.5 reads low, under 1.0 medium, else high
                {t.cv != null || band
                  ? ` — this product: ${[t.cv != null ? `CV ${t.cv.toFixed(2)}` : null, band?.gloss].filter(Boolean).join(', ')}`
                  : ''}.
                {' '}Low means a typical month stays within about 50% of the average; Medium 50–100%; High more
                than that.
              </InfoTip>
            </span>
            <span className="sku-pattern-tile-value" title={band?.technical}>{band ? band.label : 'Not measured'}</span>
            {/* The cv as a share of an average month: 0.43 reads "about 43%". */}
            <span className="sku-pattern-tile-desc">
              {t.cv != null
                ? `a typical month is about ${Math.round(t.cv * 100)}% above or below average`
                : 'the month-to-month swing was not measured'}
            </span>
          </div>

          <div className="sku-pattern-tile sku-pattern-tile-trend">
            <span className="sku-pattern-tile-label">
              Direction
              <InfoTip label="About the direction" size={12}>
                Whether sales are rising or falling over time, beyond normal ups and downs.{' '}
                Mann–Kendall test on the monthly series from the first sale; a direction counts only when
                p &lt; 0.05{trend ? ` — this product: ${trend.gloss}` : ''}.
              </InfoTip>
            </span>
            <span className="sku-pattern-tile-value">
              {TrendIcon && <TrendIcon size={18} aria-hidden="true" className="sku-pattern-trend-icon" />}
              {trend ? trend.label : '—'}
            </span>
            <span className="sku-pattern-tile-desc">{trend ? trend.plain : ''}</span>
          </div>

          <div className="sku-pattern-tile">
            <span className="sku-pattern-tile-label">
              <CalendarRange size={11} aria-hidden="true" /> Sold for
              <InfoTip label="About the sales history" size={12}>
                {`Months with sales, and the longest unbroken run (${t.longest_run} month${t.longest_run === 1 ? '' : 's'}). `}
                {stabilityGloss(t.stability_group)}
                {t.restart_flag ? '; sales restarted after a gap of 3 or more months' : ''}
                {'.'}
                {binSegment ? ` Bin: ${BIN_LABELS[binSegment.bin] || binSegment.bin}${binSegment.bin_reason ? ` (${binSegment.bin_reason})` : ''}.` : ''}
              </InfoTip>
            </span>
            <span className="sku-pattern-tile-value">
              {t.history_months} month{t.history_months === 1 ? '' : 's'}
            </span>
            <span className="sku-pattern-tile-desc">
              {t.first_sale_period ? `since ${formatMonth(t.first_sale_period)}` : 'months with sales'}
            </span>
          </div>

          {/* Seasonality: the yearly-pattern test on the SKU's monthly demand. */}
          {principal !== 'delmonte' && (
            <div className="sku-pattern-tile">
              <span className="sku-pattern-tile-label">
                <Waves size={11} aria-hidden="true" /> Busy months
                <InfoTip label="About busy months" size={12}>
                  Whether the same months sell well every year.{' '}
                  {SEASONALITY_TOOLTIP}
                  {stl ? ` This product${stl.periods?.length ? `, ${formatMonth(stl.periods[0])} – ${formatMonth(stl.periods[stl.periods.length - 1])}` : ''}: ${yearlyDescription(stl)}.` : ''}
                </InfoTip>
              </span>
              <span className="sku-pattern-tile-value">
                {!stl ? '…' : seasonalityValue(stl)}
              </span>
              <span className="sku-pattern-tile-desc">
                {!stl ? 'Checking…' : shortSeasonality(stl)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* The bin line that sat here moved to the History tile's "?" and the
          Sales forecast's "Show details" list (2026-10-20). */}
    </section>
  );
};

export default SkuDemandPatternPanel;
