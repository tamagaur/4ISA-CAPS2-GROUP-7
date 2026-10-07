import React, { useEffect, useState } from 'react';
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
// backend's cv_band, with the raw cv always beside it), the plain-
// language gloss on each stability_group code, the plain name of the
// SKU's bin (both codes stay in the tooltip), and the seasonality band
// over STL's measured strength (GET /decomposition). bin_reason is printed
// verbatim — it is the pipeline's own explanation and must not be
// paraphrased into something it didn't say.

// Coefficient-of-variation bands are a display convention over the stored
// cv (thresholds live in backend/routers/segment.py: < 0.5 low, < 1.0
// medium, else high). Colours follow the app-wide rule: green = steady,
// amber = watch, red = erratic enough to act on.
const CV_BAND_META = {
  low: { label: 'Low volatility', gloss: 'steady month to month', color: SEMANTIC.healthy },
  medium: { label: 'Medium volatility', gloss: 'noticeable month-to-month swings', color: SEMANTIC.watch },
  high: { label: 'High volatility', gloss: 'erratic — spikes and gaps', color: SEMANTIC.act },
};

// Mann-Kendall trend (p < 0.05). Direction only — a rising or falling
// series isn't good or bad on its own, so these stay neutral ink, never
// green/red.
const TREND_META = {
  up: { label: 'Rising', Icon: ArrowUpRight, gloss: 'statistically significant upward trend' },
  down: { label: 'Falling', Icon: ArrowDownRight, gloss: 'statistically significant downward trend' },
  none: { label: 'No clear trend', Icon: Minus, gloss: 'no significant direction either way' },
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
const STABILITY_GLOSS = {
  all_38: 'Class A in all 38 periods observed',
  at_least_30: 'Class A in at least 30 of the 38 periods',
  churn: 'Moves in and out of Class A — fewer than 30 of the 38 periods',
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
  'Does a month sell like the same month a year earlier? Lag-12 autocorrelation of monthly '
  + 'demand from the first sale, against the 95% bound 1.96/√months; needs 24 months.';

// The tile's one line: the peak and trough months for a product that
// repeats yearly, else the test's own figures. The full description sits
// behind the tile's "?" (UI pass, 2026-10-08).
const shortSeasonality = (stl) => {
  const yp = stl.yearly_pattern;
  if (yp?.repeats_yearly && stl.available) return `peaks ${stl.peak_month}, lowest ${stl.trough_month}`;
  if (yp && yp.repeats_yearly != null) return `ACF(12) ${yp.acf_lag12 == null ? 'n/a' : yp.acf_lag12.toFixed(2)} vs bound ${yp.acf_bound.toFixed(2)}`;
  return yearlyDescription(stl);
};

const yearlyDescription = (stl) => {
  const yp = stl.yearly_pattern;
  if (!yp) return stl.available ? `STL seasonal strength ${stl.seasonal_strength.toFixed(2)}` : stl.reason;
  if (yp.repeats_yearly == null) return `${yp.months} month${yp.months === 1 ? '' : 's'} from the first sale`;
  const acf = `ACF(12) ${yp.acf_lag12 == null ? 'n/a' : yp.acf_lag12.toFixed(2)} vs bound ${yp.acf_bound.toFixed(2)}`;
  const peaks = yp.repeats_yearly && stl.available ? `peaks in ${stl.peak_month}, lowest in ${stl.trough_month} · ` : '';
  const strength = stl.available ? ` · STL seasonal strength ${stl.seasonal_strength.toFixed(2)}, trend ${stl.trend_strength.toFixed(2)}` : '';
  return `${peaks}${acf}${strength}`;
};

const SkuDemandPatternPanel = ({ skuId, principal, compact = false }) => {
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
      .then((res) => { if (!cancelled) setStl(res ?? { available: false, reason: 'No SKU-level series for this product.' }); })
      .catch(() => { if (!cancelled) setStl({ available: false, reason: 'Could not load the STL decomposition.' }); });
    return () => { cancelled = true; };
  }, [skuId, principal]);

  const heading = (
    <div className="sku-pattern-header">
      <h4 className="sku-pattern-title">
        <Activity size={15} aria-hidden="true" />
        Demand pattern
      </h4>
      {/* The months the volatility, trend and history tiles measure:
          traits.py reads the monthly pieces from the SKU's first sale up to
          the cohort month (the ABC run the cohort was drawn from). */}
      {state.data?.traits?.cohort_period && (
        <span className="sku-pattern-cohort" title={`Monthly pieces sold, measured from the first sale to the ${formatMonth(state.data.traits.cohort_period)} cohort (the ABC run this pattern was measured for)`}>
          {state.data.traits.first_sale_period
            ? `Monthly pieces, ${formatMonth(state.data.traits.first_sale_period)} – ${formatMonth(state.data.traits.cohort_period)}`
            : `Cohort ${formatMonth(state.data.traits.cohort_period)}`}
        </span>
      )}
    </div>
  );

  // The four tiles the loaded panel shows (volatility, trend, history,
  // seasonality), in the same tile class, so the panel keeps its height.
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
  // A 404 (getSegment -> null) or a product with no Phase-2 rows: say so
  // plainly. Never a placeholder band or trend.
  if (!data || !data.analyzed) {
    return (
      <section className={`sku-pattern sku-pattern-unanalyzed${compact ? ' sku-pattern-compact' : ''}`}>
        {heading}
        <p className="sku-pattern-empty-title">Not yet analyzed</p>
        <p className="sku-pattern-note">
          {data?.not_analyzed_reason
            || `No demand-pattern record exists for ${skuId} — it isn't in any segmentation cohort yet.`}
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

  return (
    <section className={`sku-pattern${compact ? ' sku-pattern-compact' : ''}`}>
      {heading}

      {previewWindow && (
        <p className="chart-placeholder-note">
          Measured {formatMonth(previewWindow.start)} – {formatMonth(previewWindow.end)}, including the 2021–22
          placeholder months (not SSM&apos;s sales). The stability group comes from the real ABC runs and is unchanged.
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
              Volatility
              <InfoTip label="About volatility" size={12}>
                Coefficient of variation (CV) of monthly pieces: how far a month&apos;s sales swing around the
                average. Under 0.5 reads low, under 1.0 medium, else high{band ? ` — this product: ${band.gloss}` : ''}.
              </InfoTip>
            </span>
            <span className="sku-pattern-tile-value">{band ? band.label : 'Not measured'}</span>
            <span className="sku-pattern-tile-desc">
              {t.cv != null ? `CV ${t.cv.toFixed(2)}` : 'no coefficient of variation stored'}
            </span>
          </div>

          <div className="sku-pattern-tile sku-pattern-tile-trend">
            <span className="sku-pattern-tile-label">
              Trend
              <InfoTip label="About the trend" size={12}>
                Mann–Kendall test on the monthly series from the first sale; a direction counts only when
                p &lt; 0.05{trend ? ` — this product: ${trend.gloss}` : ''}.
              </InfoTip>
            </span>
            <span className="sku-pattern-tile-value">
              {TrendIcon && <TrendIcon size={18} aria-hidden="true" className="sku-pattern-trend-icon" />}
              {trend ? trend.label : '—'}
            </span>
            <span className="sku-pattern-tile-desc">{trend ? 'Mann–Kendall, p < 0.05' : ''}</span>
          </div>

          <div className="sku-pattern-tile">
            <span className="sku-pattern-tile-label">
              <CalendarRange size={11} aria-hidden="true" /> History
              <InfoTip label="About the history" size={12}>
                {STABILITY_GLOSS[t.stability_group] || t.stability_group}
                {t.restart_flag ? '; sales restarted after a gap of 3 or more months' : ''}
                {` (stability group: ${t.stability_group}).`}
              </InfoTip>
            </span>
            <span className="sku-pattern-tile-value">
              {t.history_months} selling month{t.history_months === 1 ? '' : 's'}
            </span>
            <span className="sku-pattern-tile-desc">
              {t.first_sale_period ? `first sale ${formatMonth(t.first_sale_period)} · ` : ''}
              {`longest run ${t.longest_run} month${t.longest_run === 1 ? '' : 's'}`}
            </span>
          </div>

          {/* Seasonality: STL decomposition of the SKU's monthly demand. */}
          {principal !== 'delmonte' && (
            <div className="sku-pattern-tile">
              <span className="sku-pattern-tile-label">
                <Waves size={11} aria-hidden="true" /> Seasonality
                <InfoTip label="About seasonality" size={12}>
                  {SEASONALITY_TOOLTIP}
                  {stl ? ` This product: ${yearlyDescription(stl)}${stl.periods?.length ? `, ${formatMonth(stl.periods[0])} – ${formatMonth(stl.periods[stl.periods.length - 1])}` : ''}.` : ''}
                </InfoTip>
              </span>
              <span className="sku-pattern-tile-value">
                {!stl ? '…' : stl.yearly_pattern?.label || 'Not enough history'}
              </span>
              <span className="sku-pattern-tile-desc">
                {!stl ? 'Decomposing…' : shortSeasonality(stl)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* One line under the tiles: the SKU's bin from ONE scheme,
          combined_v1 (length_v2 when it's absent), with its bin_reason
          verbatim. The per-scheme bin_reason blockquotes and the Feb-2026
          revenue-share footer that used to sit here were removed
          (2026-09-21) for restating the tiles in the pipeline's vocabulary
          (LONG_UP, stability_v1, CHURN) — so this names the bin in plain
          words and keeps the scheme and code in the tooltip. GET /segment's
          revenue_share_2026_02 is still unread here. */}
      {binSegment && (
        <p className="sku-pattern-bin" title={`${binSegment.scheme}: ${binSegment.bin}`}>
          <span className="sku-pattern-bin-label">Bin</span>
          <span className="sku-pattern-bin-name">{BIN_LABELS[binSegment.bin] || binSegment.bin}</span>
          {/* bin_reason verbatim — the pipeline's own words — one tap away. */}
          {binSegment.bin_reason && <InfoTip label="Why this bin" size={12}>{binSegment.bin_reason}</InfoTip>}
        </p>
      )}
    </section>
  );
};

export default SkuDemandPatternPanel;
