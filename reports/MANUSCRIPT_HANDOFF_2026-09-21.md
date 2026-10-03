# Forecasting methodology changes: briefing for Chapters 1-3

As of 2026-09-21. For teammates revising Chapters 1-3. Information only: no chapter text is proposed here.

## 1. What changed and why

The paper can no longer say "every Tier A product is forecast with MA3 and judged by MAPE with a 20% threshold." Each product now gets a model matched to how much sales history it has, and the models were tested much more strictly. The honest result: the new models are **equal** in accuracy to MA3 within the margin of error. They are not more accurate, and the paper must never say they are.

Terms used below: SKU (stock-keeping unit, one distinct product), MA3 (3-month moving average), TSB (Teunter-Syntetos-Babai method), XGBoost (Extreme Gradient Boosting, a machine-learning model), MAPE (mean absolute percentage error), WAPE (weighted absolute percentage error), MASE (mean absolute scaled error).

**Who is forecast.** ABC classification (ranking products by revenue) on February 2026 revenue gives 132 Unilever Tier A SKUs. Forecasting covers these only. Del Monte is excluded from forecasting because no SKU-level sales data exists for it, only category-level sell-out. Del Monte is classified by product category instead.

**How each SKU is forecast.** Each SKU is placed in a group ("bin") by how many months it has sales. Real data covers January 2023 to February 2026 (38 months).

| Bin | Months with sales | Method served | SKUs on February 2026 |
| --- | --- | --- | --- |
| Insufficient | Under 3 | No real forecast. A provisional trailing average is stored and labelled "insufficient data" | 13 |
| Short | 3-11 | MA3 | 30 |
| Medium | 12-23 | TSB, fixed smoothing weights 0.3 and 0.1 | 17 |
| Long | 24 or more | The average of XGBoost and MA3 | 72 |

**The XGBoost model.** It is one "global" model trained across all Tier A SKUs at once, not one model per SKU. It uses 14 features: recent monthly lags, a 12-month lag, short and long averages, recent variability, count of zero months, months of history, share of months with a sale, and calendar month. Each SKU's values are scaled by its own recent average, so large and small products can be learned together.

**The safety net.** MA3 is still calculated for every SKU, as a benchmark and as an automatic fallback. The fallback fires if XGBoost cannot produce a number, or if a forecast is above the SKU's historical maximum or below zero.

**How the models were tested.** This replaces the single train/test split.

- Real data only.
- Rolling one-step-ahead holdout: each month is forecast using only the months before it.
- Results are checked separately across five half-year blocks (October 2023-February 2024, March-August 2024, September 2024-February 2025, March-August 2025, September 2025-February 2026), so one lucky stretch cannot carry a conclusion.
- Bootstrap 95% confidence intervals: the set of SKUs is re-drawn at random 1,000 times (fixed seed) to show how far a result could move by chance.
- Decision rule: a model replaces MA3 only if the 95% interval on the difference excludes zero **and** more SKUs improve than worsen.

**How accuracy is measured.** WAPE ranks the models. MASE below 1 is the pass gate. MAPE is no longer the primary metric because it becomes unstable when actual sales are near zero. Some SKUs showed MAPE above 1,000% for this reason alone.

**What the tests found.** 35 candidate models were tested. None beat MA3 consistently across the five blocks. The XGBoost+MA3 average scored 0 wins, 4 ties and 1 loss across blocks. TSB tied with MA3 in all 4 blocks where it could be tested. The bias check found no model that systematically over- or under-forecasts, and the new models cannot be distinguished from MA3. The new models are served because they are trained models that learn from data, with MA3 retained as benchmark and fallback.

**Going forward.** Each month, over a rolling 6-month window, a served model reverts to MA3 only if MA3 clearly beats it under the same two-condition rule. A tie changes nothing.

**Tested and rejected.** Choosing among six simple models per bin (six bins by length and trend) was rejected. No bin winner cleared the margin of error, and 52 of 132 SKUs changed bin within six months, too unstable to route on. Seasonal models were rejected because seasonality is not detectable in 38 months: 10 SKUs tested significant against about 26 expected by chance.

**Synthetic data.** San San Marketing (SSM) has not yet delivered 2021-2022 data, and the adviser asked the team to fill it. Placeholder rows are generated from each product's own 2023-2026 behaviour, only for products shown to exist in 2021-2022 stock records. They are flagged as synthetic and are never used by any forecast, classification or bin. They will be replaced when real files arrive.

## 2. Before and after

Three "before" facts are on record: MA3 for every Tier A SKU, MAPE with a 20% threshold, and a single train/test split. Where a "before" cell says "check the paper", the old position was not recorded, so compare against what the chapters currently say. The chapter column is a best guess: 1 = scope, limitations, significance; 2 = related literature; 3 = methodology.

| Item | Before | Now | Why it changed | Chapter likely affected |
| --- | --- | --- | --- | --- |
| Forecast cohort | Every Tier A SKU. Count and period: check the paper | 132 Unilever Tier A SKUs, from ABC classification on February 2026 revenue. Forecasting covers these only | The cohort is now tied to a named month and to the one principal with SKU-level sales data | 1, 3 |
| Forecast method | MA3 for every Tier A SKU | One method per history-length bin: short = MA3, medium = TSB, long = average of XGBoost and MA3 (bin table in section 1) | Trained models that learn from data are served where enough history exists. MA3 stays as benchmark and fallback | 3 |
| SKUs with under 3 months of sales | Check the paper | No real forecast. A provisional trailing average is stored and labelled "insufficient data" (13 SKUs on February 2026) | A 3-month average cannot be computed from fewer than 3 months. Project rule: show a flagged status, never a number pretending to be measured | 1, 3 |
| Machine-learning model | None | One global XGBoost model across all Tier A SKUs, 14 features, each SKU scaled by its own recent average. Used only in the long bin, averaged with MA3 | One model can learn from all products at once. Scaling lets large and small products be learned together | 2, 3 |
| Role of MA3 | The only forecasting method | Served for the short bin, calculated for every SKU as benchmark, and automatic fallback (XGBoost gives no number, or forecast above historical maximum or below zero) | None of the 35 candidates beat it consistently. The fallback guards against implausible forecasts | 3 |
| Evaluation design | Single train/test split | Real data only. Rolling one-step-ahead holdout. Five half-year blocks checked separately. Bootstrap 95% confidence intervals, 1,000 resamples over SKUs, fixed seed | One lucky stretch cannot carry a conclusion. Intervals show the margin of error | 2, 3 |
| Ranking metric | MAPE | WAPE ranks models. MAPE is no longer primary | MAPE becomes unstable when actual sales are near zero. Some SKUs showed MAPE above 1,000% for this reason alone | 2, 3 |
| Pass threshold | MAPE of 20% | MASE below 1 | MASE compares a model's error with the error of simply repeating last month's sales. Below 1 means the model's error is smaller (code: `analytics/forecasting/diagnostic_metrics.py`, lines 75-80) | 2, 3 |
| Rule for adopting a model | Check the paper | A model replaces MA3 only if the 95% interval on the difference excludes zero and more SKUs improve than worsen | A difference inside the margin of error is not evidence of improvement | 3 |
| Accuracy claim | Check the paper | New models are equal in accuracy to MA3 within the margin of error. 35 candidates tested, none beat MA3 consistently. XGBoost+MA3 average: 0 wins, 4 ties, 1 loss. TSB: tied in all 4 blocks where it could be tested | This is what the tests found. The paper must not claim the new models are more accurate than MA3 | 1, 3 |
| Bias | Check the paper | No model systematically over- or under-forecasts. The new models cannot be distinguished from MA3 | Bias check added to the evaluation | 3 |
| Monthly switching rule | None | Each month, over a rolling 6-month window, a served model reverts to MA3 only if MA3 clearly beats it under the same two-condition rule. A tie changes nothing | Keeps the served model under review without switching on noise | 3 |
| Per-bin model selection | Not applicable | Tested and rejected: six simple models across six bins by length and trend | No bin winner cleared the margin of error. 52 of 132 SKUs changed bin within six months, too unstable to route on | 3 |
| Seasonality | Check the paper | No seasonal model is used | Not detectable in 38 months: 10 SKUs significant against about 26 expected by chance | 1, 2, 3 |
| 2021-2022 data | Check the paper | Not yet delivered by SSM. Synthetic placeholder rows fill the gap, flagged as synthetic, never used by any forecast, classification or bin | The adviser asked the team to fill the gap. Rows will be replaced when real files arrive | 1, 3 |
| Del Monte | Check the paper | Classified by product category. Excluded from forecasting. Its sell-out data has 94 distinct `category_path` values before January 2025 and 57 after | No SKU-level sales data exists, only category-level sell-out. The category vocabulary changed in January 2025 | 1, 3 |

Note on Del Monte counts: the 94 and 57 are distinct `category_path` values in the live database. A separate, smaller figure exists for ABC-ranked categories (about 63 before, 4-5 after). Do not mix the two levels.

## 3. Verified literature

All 23 citations with a DOI below were checked one by one against the Crossref citation database on 2026-09-21, and each DOI resolves at doi.org. One WAPE source has no DOI and is marked. "What it supports" is taken from each paper's abstract or title only. Nobody has read the full papers yet, so read a paper before citing it for a specific claim.

Status key: **Verified** = citation details confirmed and abstract read. **Verified, title only** = citation details confirmed, but no abstract could be retrieved. **Unverified** = a stated part could not be confirmed.

### TSB and intermittent demand

| Citation (APA 7) | What it supports | Status |
| --- | --- | --- |
| Teunter, R. H., Syntetos, A. A., & Babai, M. Z. (2011). Intermittent demand: Linking forecasting to inventory obsolescence. *European Journal of Operational Research, 214*(3), 606-615. https://doi.org/10.1016/j.ejor.2011.05.018 | The source of the TSB method: an intermittent-demand method that updates the demand probability every period | Verified |
| Croston, J. D. (1972). Forecasting and stock control for intermittent demands. *Journal of the Operational Research Society, 23*(3), 289-303. https://doi.org/10.1057/jors.1972.50 | The original intermittent-demand method that TSB builds on: separate estimates of demand size and demand frequency | Verified. Crossref lists the journal under this name. The historical title "Operational Research Quarterly" is unverified |
| Syntetos, A. A., & Boylan, J. E. (2005). The accuracy of intermittent demand estimates. *International Journal of Forecasting, 21*(2), 303-314. https://doi.org/10.1016/j.ijforecast.2004.10.001 | Comparison of intermittent-demand methods on 3,000 real series | Verified |

### Global models and XGBoost for demand

| Citation (APA 7) | What it supports | Status |
| --- | --- | --- |
| Chen, T., & Guestrin, C. (2016). XGBoost: A scalable tree boosting system. In *Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining* (pp. 785-794). ACM. https://doi.org/10.1145/2939672.2939785 | The source of the XGBoost algorithm. Peer-reviewed conference paper, not a journal article | Verified |
| Montero-Manso, P., & Hyndman, R. J. (2021). Principles and algorithms for forecasting groups of time series: Locality and globality. *International Journal of Forecasting, 37*(4), 1632-1653. https://doi.org/10.1016/j.ijforecast.2021.03.004 | The idea of a "global" model: one model for all series against one model per series | Verified |
| Januschowski, T., Gasthaus, J., Wang, Y., Salinas, D., Flunkert, V., Bohlke-Schneider, M., & Callot, L. (2020). Criteria for classifying forecasting methods. *International Journal of Forecasting, 36*(1), 167-177. https://doi.org/10.1016/j.ijforecast.2019.05.008 | How to classify forecasting methods. Argues the machine-learning versus statistical split is not the fundamental one | Verified |
| Makridakis, S., Spiliotis, E., & Assimakopoulos, V. (2022). M5 accuracy competition: Results, findings, and conclusions. *International Journal of Forecasting, 38*(4), 1346-1364. https://doi.org/10.1016/j.ijforecast.2021.11.013 | Results of a large retail forecasting competition on 42,840 Walmart unit-sales series | Verified |
| Fildes, R., Ma, S., & Kolassa, S. (2022). Retail forecasting: Research and practice. *International Journal of Forecasting, 38*(4), 1283-1318. https://doi.org/10.1016/j.ijforecast.2019.06.004 | Review of retail demand forecasting down to product level, and the evidence on which methods are more accurate | Verified |

### Metrics: MASE, WAPE and the problem with MAPE

| Citation (APA 7) | What it supports | Status |
| --- | --- | --- |
| Hyndman, R. J., & Koehler, A. B. (2006). Another look at measures of forecast accuracy. *International Journal of Forecasting, 22*(4), 679-688. https://doi.org/10.1016/j.ijforecast.2006.03.001 | The source of MASE. Finds many common accuracy measures inadequate. Do not cite it for WAPE: its abstract does not mention WAPE | Verified |
| Kim, S., & Kim, H. (2016). A new metric of absolute percentage error for intermittent demand forecasts. *International Journal of Forecasting, 32*(3), 669-679. https://doi.org/10.1016/j.ijforecast.2015.12.003 | MAPE is infinite or undefined when actual values are zero or near zero | Verified |
| Kolassa, S., & Schütz, W. (2007). Advantages of the MAD/Mean ratio over the MAPE. *Foresight: The International Journal of Applied Forecasting*, (6), 40-43. | The clearest WAPE source. Describes the MAD/Mean ratio (the same calculation as WAPE) as a weighted alternative to MAPE, suited to intermittent and near-zero demand | Real paper, **no DOI**. Peer-review status of *Foresight* is unverified |
| Hewamalage, H., Ackermann, K., & Bergmeir, C. (2023). Forecast evaluation for data scientists: Common pitfalls and best practices. *Data Mining and Knowledge Discovery, 37*(2), 788-832. https://doi.org/10.1007/s10618-022-00894-5 | A WAPE definition with a DOI: sum of absolute errors over sum of absolute actuals | Citation verified. The definition was read in the arXiv preprint (Section 6.1.2), **unverified** in the published version. Check the published PDF before citing |
| Kolassa, S. (2016). Evaluating predictive count data distributions in retail sales forecasting. *International Journal of Forecasting, 32*(3), 788-803. https://doi.org/10.1016/j.ijforecast.2015.12.004 | A limitation only. Its abstract says measures such as MASE and weighted MAPE are unsuitable for count data. Never cite it as support for WAPE | Verified |

### Evaluation design: rolling holdout and bootstrap

| Citation (APA 7) | What it supports | Status |
| --- | --- | --- |
| Tashman, L. J. (2000). Out-of-sample tests of forecasting accuracy: An analysis and review. *International Journal of Forecasting, 16*(4), 437-450. https://doi.org/10.1016/S0169-2070(00)00065-0 | Testing forecasts on data the model has not seen. Whether it covers rolling holdouts specifically is unverified | Verified, title only |
| Bergmeir, C., & Benítez, J. M. (2012). On the use of cross-validation for time series predictor evaluation. *Information Sciences, 191*, 192-213. https://doi.org/10.1016/j.ins.2011.12.028 | Evaluating time series forecasters with repeated train and test splits | Verified, title only |
| Efron, B. (1979). Bootstrap methods: Another look at the jackknife. *The Annals of Statistics, 7*(1), 1-26. https://doi.org/10.1214/aos/1176344552 | The source of the bootstrap: estimating how much a result varies by resampling | Verified |
| DiCiccio, T. J., & Efron, B. (1996). Bootstrap confidence intervals. *Statistical Science, 11*(3), 189-228. https://doi.org/10.1214/ss/1032280214 | Survey of bootstrap methods for confidence intervals | Verified |

### Forecast combination, and simple against complex models

| Citation (APA 7) | What it supports | Status |
| --- | --- | --- |
| Bates, J. M., & Granger, C. W. J. (1969). The combination of forecasts. *Journal of the Operational Research Society, 20*(4), 451-468. https://doi.org/10.1057/jors.1969.103 | The founding paper on averaging two forecasts. Supports the XGBoost+MA3 average as a technique | Verified. Same journal-title note as Croston (1972) |
| Clemen, R. T. (1989). Combining forecasts: A review and annotated bibliography. *International Journal of Forecasting, 5*(4), 559-583. https://doi.org/10.1016/0169-2070(89)90012-5 | Review of the forecast-combination literature | Verified, title only |
| Wang, X., Hyndman, R. J., Li, F., & Kang, Y. (2023). Forecast combinations: An over 50-year review. *International Journal of Forecasting, 39*(4), 1518-1547. https://doi.org/10.1016/j.ijforecast.2022.11.005 | Recent review of forecast combination, from simple averages onward | Verified |
| Green, K. C., & Armstrong, J. S. (2015). Simple versus complex forecasting: The evidence. *Journal of Business Research, 68*(8), 1678-1685. https://doi.org/10.1016/j.jbusres.2015.03.026 | Context for our result. Reviews 97 comparisons in 32 papers and finds no balance of evidence that complexity improves accuracy | Verified |
| Makridakis, S., Spiliotis, E., & Assimakopoulos, V. (2018). Statistical and Machine Learning forecasting methods: Concerns and ways forward. *PLOS ONE, 13*(3), Article e0194889. https://doi.org/10.1371/journal.pone.0194889 | Context for our result. On 1,045 monthly series, machine-learning methods did not beat statistical methods | Verified |
| Petropoulos, F., Apiletti, D., Assimakopoulos, V., Babai, M. Z., Barrow, D. K., Ben Taieb, S., Bergmeir, C., Bessa, R. J., Bijak, J., Boylan, J. E., Browell, J., Carnevale, C., Castle, J. L., Cirillo, P., Clements, M. P., Cordeiro, C., Cyrino Oliveira, F. L., De Baets, S., Dokumentov, A., . . . Ziel, F. (2022). Forecasting: Theory and practice. *International Journal of Forecasting, 38*(3), 705-871. https://doi.org/10.1016/j.ijforecast.2021.11.001 | Encyclopedic review of forecasting theory and practice. General background reference | Verified |
| Davydenko, A., & Fildes, R. (2013). Measuring forecasting accuracy: The case of judgmental adjustments to SKU-level demand forecasts. *International Journal of Forecasting, 29*(3), 510-522. https://doi.org/10.1016/j.ijforecast.2012.09.002 | Accuracy measurement for SKU-level demand forecasts. Not a WAPE source: it recommends a different metric | Verified |

Open choice for the team: WAPE needs one defining citation. Either cite Kolassa and Schütz (2007) without a DOI, or cite Hewamalage et al. (2023) after checking the published PDF.

## 4. Limitations

These are plain facts to carry into the paper, not paper wording.

**Accuracy**

- The new models are not shown to be more accurate than MA3. 35 candidates were tested and none beat MA3 consistently across the five blocks.
- The XGBoost+MA3 average scored 0 wins, 4 ties and 1 loss. TSB tied in all 4 blocks where it could be tested, so one block has no TSB result.
- The evaluation measures one-month-ahead accuracy only. No longer-horizon result is on record.
- A forecast above the SKU's historical maximum is replaced by MA3, so a served forecast cannot predict a new record month.
- TSB uses fixed smoothing weights of 0.3 and 0.1. They are not tuned per SKU.
- One paper in the literature list (Kolassa, 2016) cautions that MASE and weighted MAPE are unsuitable for count data.

**Data span**

- Real data covers 38 months, January 2023 to February 2026.
- Seasonality is not detectable in 38 months: 10 SKUs tested significant against about 26 expected by chance. No seasonal model is used, so any real seasonal pattern is not captured.
- Unilever SKU-level demand exists at monthly grain only. The daily files carry no SKU (project record: all 106 raw files were opened).

**Coverage**

- Forecasting covers the 132 Unilever Tier A SKUs as of February 2026 only. Other tiers are not forecast.
- 13 of the 132 have under 3 months of sales and get no real forecast. They carry a provisional trailing average labelled "insufficient data".
- The bin counts (13 insufficient, 30 short, 17 medium, 72 long) are a February 2026 snapshot. A SKU moves up a bin as it gains months of sales.
- Del Monte is excluded from forecasting. No SKU-level sales data exists for it, only category-level sell-out.
- Del Monte's category vocabulary changed in January 2025: 94 distinct `category_path` values before, 57 after. Category figures across that date are not like-for-like. Whether the two sets overlap has not been checked.

**Synthetic data**

- 2021-2022 data has not yet been delivered by SSM. The gap is filled with synthetic placeholder rows at the adviser's request.
- The rows are generated from each product's own 2023-2026 behaviour, only for products shown to exist in 2021-2022 stock records.
- They are smoother than real data. This is a known limitation.
- They are flagged as synthetic and never used by any forecast, classification or bin. No reported result depends on them.
- They will be replaced when real files arrive.

**Rejected approach, for the record**

- Per-bin model selection (six simple models, six bins by length and trend) was rejected. No bin winner cleared the margin of error, and 52 of 132 SKUs changed bin within six months.
