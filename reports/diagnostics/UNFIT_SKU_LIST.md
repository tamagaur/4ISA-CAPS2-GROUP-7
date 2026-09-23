# Unfit SKU list -- Tier A as of 2026-02 (28 not-fit SKUs)

Source: `reports/diagnostics/fit_review_common_2026-09-23.csv` (132 rows). Report only --
no recomputation, no DB reads. Every number below is copied from that file.

> Verdicts come from the common window **2025-09 to 2026-02**; 12 short-bin SKUs fall back
> to the stored 20% split scoring and are marked; thresholds were fixed before computing and
> are recorded in `reports/diagnostics/README.md`; the two measured gates (CV p75 **0.4365**,
> units Q1 **812.5**) are cohort-relative to the 119 scored Tier A SKUs as of 2026-02.

Of the 28 listed here, **3** carry the `pipeline (20% split)` fallback source; the other 9 of
the 12 fallback SKUs scored clean or borderline and so are not in this list.

**Columns this report asks for that the CSV does not carry** -- flagged, not estimated:

| requested | status |
|---|---|
| router bin and combined_v1 bin as separate columns | **absent.** The file carries one `bin` column only; it does not record whether the router bin and the combined_v1 bin agree. `bin` is reported once in each table below. |
| largest spike deviation | **absent.** The file carries `cause_n_spikes` and `cause_mad` but no per-spike magnitude. Per-month spike detail lives in `incident_check_2026-09-23.csv`, which this report was told not to read. |

## Short bin -- 8 SKUs (ascending MASE)

| # | SKU | Product | Bin | Served model | MASE used | Verdict source | Thresholds crossed | Cause group | Other rules fired | Cause numbers | MA3 MASE (common holdout) | Band width / forecast |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `65086431` | BREEZE PWD ROSEGOLD ATL 24(6+1)(64G+64G) | short | `ma3` | 1.135 | `pipeline (20% split)` **[fallback]** | MASE 1.135 vs gate 1.1; median units 322 vs Q1 812.5 | tiny scale | none | level shift -- (needs >=18 mo; has 5); spikes 0 (MAD 170; largest deviation not in file); CV -- (needs 12 mo; has 5); median units 322; zero/missing share 0, longest zero run 0, months 5 | -- not comparable (pipeline (20% split); no common-window MASE) | stored 2.2x; common -- |
| 2 | `64900613` | CREAMSILK TR-KRTN SCD STRT 24(11+1)X14ML | short | `ma3` | 1.4376 | `common` | MASE 1.4376 vs gate 1.1 | none of the above | none | level shift -- (needs >=18 mo; has 9); spikes 0 (MAD 352; largest deviation not in file); CV -- (needs 12 mo; has 9); median units 952; zero/missing share 0, longest zero run 0, months 9 | 1.4376 (fails) | stored 2.16x; common 1.96x |
| 3 | `64900508` | CREAM SILK TMT DAMAGE REP24(11+1)X18ML | short | `ma3` | 1.503 | `pipeline (20% split)` **[fallback]** | MASE 1.503 vs gate 1.1 | none of the above | none | level shift -- (needs >=18 mo; has 7); spikes 0 (MAD 331; largest deviation not in file); CV -- (needs 12 mo; has 7); median units 1025; zero/missing share 0, longest zero run 0, months 7 | -- not comparable (pipeline (20% split); no common-window MASE) | stored 1.71x; common 1.4x |
| 4 | `64401259` | BESTFOODS ALL PURPOSE DRSG 4X3.5L | short | `ma3` | 1.8333 | `common` | MASE 1.8333 vs gate 1.1; spikes 2 vs gate >=1 month beyond 3xMAD (MAD 49); median units 337.5 vs Q1 812.5 | spiky | tiny scale | level shift -- (needs >=18 mo; has 10); spikes 2 (MAD 49; largest deviation not in file); CV -- (needs 12 mo; has 10); median units 337.5; zero/missing share 0, longest zero run 0, months 10 | 1.8333 (fails) | stored 1.53x; common 1.26x |
| 5 | `64861488` | SURF PWDR PURPLE BLOOMS L 40(6+1)65G | short | `ma3` | 1.8776 | `common` | MASE 1.8776 vs gate 1.1; recent level 0.4068 vs band 0.7-1.3; CV 0.573 vs p75 0.4365; spikes 2 vs gate >=1 month beyond 3xMAD (MAD 567.5) | high volatility | spiky | level shift -- (needs >=18 mo; has 12); spikes 2 (MAD 567.5; largest deviation not in file); CV 0.573; median units 1937.5; zero/missing share 0.083, longest zero run 1, months 12 | 1.8776 (fails) | stored 4.2x; common 5.18x |
| 6 | `64900506` | CREAM SILK TMT RBOND STRT 24(11+1)X18ML | short | `ma3` | 2.181 | `pipeline (20% split)` **[fallback]** | MASE 2.181 vs gate 1.1; spikes 2 vs gate >=1 month beyond 3xMAD (MAD 276) | spiky | none | level shift -- (needs >=18 mo; has 7); spikes 2 (MAD 276; largest deviation not in file); CV -- (needs 12 mo; has 7); median units 882; zero/missing share 0, longest zero run 0, months 7 | -- not comparable (pipeline (20% split); no common-window MASE) | stored 2.1x; common 1.47x |
| 7 | `64967994` | LADY'S CHOICE SS BACON DOY 24X220ML | short | `ma3` | 5.2646 | `common` | MASE 5.2646 vs gate 1.1; median units 322 vs Q1 812.5 | tiny scale | none | level shift -- (needs >=18 mo; has 8); spikes 0 (MAD 192; largest deviation not in file); CV -- (needs 12 mo; has 8); median units 322; zero/missing share 0, longest zero run 0, months 8 | 5.2646 (fails) | stored 1.51x; common 1.44x |
| 8 | `64900614` | CREAMSILK TRI-KRTN SCD R&S 24(11+1)X14ML | short | `ma3` | 5.9791 | `common` | MASE 5.9791 vs gate 1.1; median units 597 vs Q1 812.5 | tiny scale | none | level shift -- (needs >=18 mo; has 9); spikes 0 (MAD 283; largest deviation not in file); CV -- (needs 12 mo; has 9); median units 597; zero/missing share 0, longest zero run 0, months 9 | 5.9791 (fails) | stored 2.39x; common 2.01x |

## Medium bin -- 9 SKUs (ascending MASE)

| # | SKU | Product | Bin | Served model | MASE used | Verdict source | Thresholds crossed | Cause group | Other rules fired | Cause numbers | MA3 MASE (common holdout) | Band width / forecast |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `68764000` | LADY'S CHOICE SS CHICKEN 72X80ML | medium | `tsb` | 1.1087 | `common` | MASE 1.1087 vs gate 1.1; recent level 0.695 vs band 0.7-1.3; spikes 2 vs gate >=1 month beyond 3xMAD (MAD 388); trend reversal: sign(Theil-Sen last 12) != sign(full history) | spiky | trend reversal | level shift 0.933 @ 2025-12; spikes 2 (MAD 388; largest deviation not in file); CV 0.261; median units 2773.5; zero/missing share 0, longest zero run 0, months 20 | 1.2822 (fails) | stored 1.64x; common 1.35x |
| 2 | `64830409` | KNORR SOUP CRAB & CORN 60X55G | medium | `tsb` | 1.1624 | `common` | MASE 1.1624 vs gate 1.1; spikes 2 vs gate >=1 month beyond 3xMAD (MAD 174.5) | spiky | none | level shift -- (needs >=18 mo; has 16); spikes 2 (MAD 174.5; largest deviation not in file); CV 0.185; median units 1584.5; zero/missing share 0, longest zero run 0, months 16 | 1.4209 (fails) | stored 0.67x; common 0.67x |
| 3 | `64314343` | DOVE SH CERAMIDE INTENSE REP 288X13.5ML | medium | `tsb` | 1.1808 | `common` | MASE 1.1808 vs gate 1.1; CV 0.446 vs p75 0.4365 | high volatility | none | level shift 0.809 @ 2024-08; spikes 0 (MAD 5731; largest deviation not in file); CV 0.446; median units 19217; zero/missing share 0, longest zero run 0, months 23 | 1.2361 (fails) | stored 2.03x; common 2.13x |
| 4 | `64314335` | DOVE SH KERATIN STRT&SILKY 288X13.5ML | medium | `tsb` | 1.5761 | `common` | MASE 1.5761 vs gate 1.1; recent level 0.1836 vs band 0.7-1.3; diverges +261% vs gate 50%; level shift 0.431 vs band 0.7-1.3 (step month 2025-12); CV 0.601 vs p75 0.4365; spikes 3 vs gate >=1 month beyond 3xMAD (MAD 6904) | level shift | high volatility, spiky | level shift 0.431 @ 2025-12; spikes 3 (MAD 6904; largest deviation not in file); CV 0.601; median units 35104; zero/missing share 0, longest zero run 0, months 23 | 1.2798 (fails) | stored 2.76x; common 3.43x |
| 5 | `64788598` | CREAM SILK RO ULTREBORN ST 24(11+1)X22ML | medium | `tsb` | 1.5767 | `common` | MASE 1.5767 vs gate 1.1; recent level 1.3781 vs band 0.7-1.3; level shift 2.217 vs band 0.7-1.3 (step month 2025-11); CV 0.574 vs p75 0.4365; spikes 1 vs gate >=1 month beyond 3xMAD (MAD 342); median units 540.5 vs Q1 812.5 | level shift | high volatility, spiky, tiny scale | level shift 2.217 @ 2025-11; spikes 1 (MAD 342; largest deviation not in file); CV 0.574; median units 540.5; zero/missing share 0, longest zero run 0, months 20 | 1.5868 (fails) | stored 1.95x; common 1.66x |
| 6 | `64784425` | KNORR CUBES PORK DUO 48X6X20G | medium | `tsb` | 1.6941 | `common` | MASE 1.6941 vs gate 1.1; recent level 0.599 vs band 0.7-1.3; diverges +51% vs gate 50%; CV 0.485 vs p75 0.4365; spikes 4 vs gate >=1 month beyond 3xMAD (MAD 3532) | high volatility | spiky | level shift 0.809 @ 2024-09; spikes 4 (MAD 3532; largest deviation not in file); CV 0.485; median units 19366; zero/missing share 0, longest zero run 0, months 21 | 1.8166 (fails) | stored 2.48x; common 2.49x |
| 7 | `64784421` | KNORR CUBES CHICKEN DUO 48X6X20G | medium | `tsb` | 2.0487 | `common` | MASE 2.0487 vs gate 1.1; recent level 0.4964 vs band 0.7-1.3; diverges +63% vs gate 50%; CV 0.569 vs p75 0.4365; spikes 5 vs gate >=1 month beyond 3xMAD (MAD 3422.5) | high volatility | spiky | level shift 0.764 @ 2025-12; spikes 5 (MAD 3422.5; largest deviation not in file); CV 0.569; median units 17038.5; zero/missing share 0, longest zero run 0, months 20 | 2.1326 (fails) | stored 2.49x; common 3.3x |
| 8 | `64788596` | CREAM SILK RO ULTREBORN HF 24(11+1)X22ML | medium | `tsb` | 2.6819 | `common` | MASE 2.6819 vs gate 1.1; level shift 3.254 vs band 0.7-1.3 (step month 2025-11); CV 0.699 vs p75 0.4365; spikes 3 vs gate >=1 month beyond 3xMAD (MAD 310); median units 591.5 vs Q1 812.5 | level shift | high volatility, spiky, tiny scale | level shift 3.254 @ 2025-11; spikes 3 (MAD 310; largest deviation not in file); CV 0.699; median units 591.5; zero/missing share 0, longest zero run 0, months 20 | 2.4392 (fails) | stored 2.2x; common 2.14x |
| 9 | `68764004` | LADY'S CHOICE SS HAM DOY 24X220ML | medium | `tsb` | 3.0052 | `common` | MASE 3.0052 vs gate 1.1; recent level 1.4643 vs band 0.7-1.3; level shift 1.454 vs band 0.7-1.3 (step month 2025-12); CV 0.664 vs p75 0.4365; spikes 2 vs gate >=1 month beyond 3xMAD (MAD 213) | level shift | high volatility, spiky | level shift 1.454 @ 2025-12; spikes 2 (MAD 213; largest deviation not in file); CV 0.664; median units 838; zero/missing share 0, longest zero run 0, months 21 | 3.1456 (fails) | stored 2.73x; common 2.88x |

## Long bin -- 11 SKUs (ascending MASE)

| # | SKU | Product | Bin | Served model | MASE used | Verdict source | Thresholds crossed | Cause group | Other rules fired | Cause numbers | MA3 MASE (common holdout) | Band width / forecast |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `65004477` | BESTFOODS RGLR MYNS MAYO MAGIC 72X80ML | long | `xgb_ma3_avg` | 1.1107 | `common` | MASE 1.1107 vs gate 1.1; spikes 5 vs gate >=1 month beyond 3xMAD (MAD 553.5) | spiky | none | level shift 0.965 @ 2024-09; spikes 5 (MAD 553.5; largest deviation not in file); CV 0.218; median units 4611.5; zero/missing share 0, longest zero run 0, months 38 | 1.2407 (fails) | stored 0.93x; common 0.97x |
| 2 | `67749046` | KNORR SINIGANG ISDA 24X12X11G | long | `xgb_ma3_avg` | 1.2835 | `common` | MASE 1.2835 vs gate 1.1; spikes 2 vs gate >=1 month beyond 3xMAD (MAD 2806.5); trend reversal: sign(Theil-Sen last 12) != sign(full history) | spiky | trend reversal | level shift 1.069 @ 2025-12; spikes 2 (MAD 2806.5; largest deviation not in file); CV 0.371; median units 16287.5; zero/missing share 0, longest zero run 0, months 38 | 1.2962 (fails) | stored 1.81x; common 1.96x |
| 3 | `68438417` | KNORR BN CUBES PORK SAVERS 36X120G | long | `xgb_ma3_avg` | 1.3347 | `common` | MASE 1.3347 vs gate 1.1; recent level 1.3839 vs band 0.7-1.3; level shift 1.385 vs band 0.7-1.3 (step month 2025-12); spikes 5 vs gate >=1 month beyond 3xMAD (MAD 125); median units 725 vs Q1 812.5; trend reversal: sign(Theil-Sen last 12) != sign(full history) | level shift | spiky, tiny scale, trend reversal | level shift 1.385 @ 2025-12; spikes 5 (MAD 125; largest deviation not in file); CV 0.43; median units 725; zero/missing share 0, longest zero run 0, months 38 | 1.5581 (fails) | stored 1.15x; common 1.06x |
| 4 | `68394707` | KNORR LIQUID SEASONING ORIGINAL 24X130ML | long | `xgb_ma3_avg` | 1.3435 | `common` | MASE 1.3435 vs gate 1.1; spikes 2 vs gate >=1 month beyond 3xMAD (MAD 203); trend reversal: sign(Theil-Sen last 12) != sign(full history) | spiky | trend reversal | level shift 1 @ 2025-01; spikes 2 (MAD 203; largest deviation not in file); CV 0.162; median units 2015; zero/missing share 0, longest zero run 0, months 38 | 1.6002 (fails) | stored 0.68x; common 0.67x |
| 5 | `68438413` | KNORR BN CUBES PORK SINGLES 48X12X10G | long | `xgb_ma3_avg` | 1.576 | `common` | MASE 1.576 vs gate 1.1; recent level 0.5126 vs band 0.7-1.3; level shift 0.608 vs band 0.7-1.3 (step month 2025-12); spikes 2 vs gate >=1 month beyond 3xMAD (MAD 20488) | level shift | spiky | level shift 0.608 @ 2025-12; spikes 2 (MAD 20488; largest deviation not in file); CV 0.401; median units 140386.5; zero/missing share 0, longest zero run 0, months 38 | 1.5091 (fails) | stored 2.23x; common 2.76x |
| 6 | `67749045` | KNORR SINIGANG NA GABI 24X12X11G | long | `xgb_ma3_avg` | 1.6279 | `common` | MASE 1.6279 vs gate 1.1; spikes 1 vs gate >=1 month beyond 3xMAD (MAD 5840); trend reversal: sign(Theil-Sen last 12) != sign(full history) | spiky | trend reversal | level shift 1.042 @ 2025-11; spikes 1 (MAD 5840; largest deviation not in file); CV 0.287; median units 41654.5; zero/missing share 0, longest zero run 0, months 38 | 1.8971 (fails) | stored 1.36x; common 1.46x |
| 7 | `69695556` | LADY'S CHOICE REAL MAYO DOY 12X470ML | long | `xgb_ma3_avg` | 1.629 | `common` | MASE 1.629 vs gate 1.1; CV 0.56 vs p75 0.4365; spikes 2 vs gate >=1 month beyond 3xMAD (MAD 861) | high volatility | spiky | level shift 1.149 @ 2024-06; spikes 2 (MAD 861; largest deviation not in file); CV 0.56; median units 2052.5; zero/missing share 0, longest zero run 0, months 24 | 1.7889 (fails) | stored 2.56x; common 3.35x |
| 8 | `68438409` | KNORR BN CUBES CHICKEN SINGLES 48X12X10G | long | `xgb_ma3_avg` | 1.9784 | `common` | MASE 1.9784 vs gate 1.1; spikes 1 vs gate >=1 month beyond 3xMAD (MAD 30546); trend reversal: sign(Theil-Sen last 12) != sign(full history) | spiky | trend reversal | level shift 0.927 @ 2024-04; spikes 1 (MAD 30546; largest deviation not in file); CV 0.378; median units 146758; zero/missing share 0, longest zero run 0, months 38 | 2.2076 (fails) | stored 1.5x; common 1.63x |
| 9 | `65004662` | BESTFOODS RGLR MYNS MAYOMAGICDOY24X220ML | long | `xgb_ma3_avg` | 2.1185 | `common` | MASE 2.1185 vs gate 1.1; level shift 1.587 vs band 0.7-1.3 (step month 2023-04); CV 0.597 vs p75 0.4365; spikes 9 vs gate >=1 month beyond 3xMAD (MAD 1181) | level shift | high volatility, spiky | level shift 1.587 @ 2023-04; spikes 9 (MAD 1181; largest deviation not in file); CV 0.597; median units 4025; zero/missing share 0, longest zero run 0, months 38 | 2.1313 (fails) | stored 2.26x; common 2.89x |
| 10 | `69695564` | LADY'S CHOICE REAL MAYO 4X3.5L | long | `xgb_ma3_avg` | 2.2458 | `common` | MASE 2.2458 vs gate 1.1; level shift 1.365 vs band 0.7-1.3 (step month 2025-10); CV 0.566 vs p75 0.4365; spikes 1 vs gate >=1 month beyond 3xMAD (MAD 31); median units 71 vs Q1 812.5; trend reversal: sign(Theil-Sen last 12) != sign(full history) | level shift | high volatility, spiky, tiny scale, trend reversal | level shift 1.365 @ 2025-10; spikes 1 (MAD 31; largest deviation not in file); CV 0.566; median units 71; zero/missing share 0, longest zero run 0, months 24 | 2.3672 (fails) | stored 2.36x; common 2.55x |
| 11 | `67749043` | KNORR SINIGANG SAM ORIG 24X12X11G | long | `xgb_ma3_avg` | 2.6246 | `common` | MASE 2.6246 vs gate 1.1; level shift 1.382 vs band 0.7-1.3 (step month 2025-10); spikes 1 vs gate >=1 month beyond 3xMAD (MAD 25092) | level shift | spiky | level shift 1.382 @ 2025-10; spikes 1 (MAD 25092; largest deviation not in file); CV 0.402; median units 129700.5; zero/missing share 0, longest zero run 0, months 38 | 2.6968 (fails) | stored 1.81x; common 2.01x |

All 28 are `verdict = not fit`, so every row crosses the MASE gate by construction.

## Summary 1 -- thresholds crossed, by bin

| threshold | short (8) | medium (9) | long (11) | all 28 |
|---|---|---|---|---|
| MASE >= 1.1 | 8 | 9 | 11 | 28 |
| recent level outside 0.7-1.3 | 1 | 6 | 2 | 9 |
| diverges from MA3 > 50% | 0 | 3 | 0 | 3 |
| level shift outside 0.7-1.3 | 0 | 4 | 5 | 9 |
| CV > p75 0.4365 | 1 | 7 | 3 | 11 |
| spiky (>=1 month beyond 3xMAD) | 3 | 8 | 11 | 22 |
| tiny scale (median units <= Q1 812.5) | 4 | 2 | 2 | 8 |
| intermittent (share >= 0.30 or run >= 3) | 0 | 0 | 0 | 0 |
| trend reversal (Theil-Sen sign flip) | 0 | 1 | 6 | 7 |

The `recent level`, `level shift` and `CV` rows are suppressed to 0 wherever the underlying
column is null (see **Nulls** below) -- a null is not a non-crossing.

## Summary 2 -- cause group vs verdict (all 132 scored rows; a cause is not a diagnosis)

| cause group | not fit | clean | borderline | no verdict | not-fit share of group |
|---|---|---|---|---|---|
| level shift | 9 | 9 | 6 | 0 | 9/24 |
| spiky | 9 | 43 | 7 | 0 | 9/59 |
| high volatility | 5 | 4 | 1 | 0 | 5/10 |
| tiny scale | 3 | 3 | 0 | 1 | 3/7 |
| none of the above | 2 | 14 | 3 | 12 | 2/31 |
| intermittent | 0 | 1 | 0 | 0 | 0/1 |
| **total** | **28** | **74** | **17** | **13** | **28/132** |

Every cause group holding not-fit SKUs also holds clean ones. The cause names what the
series looks like, never why this SKU is unfit, and is not a candidate bin.

## Summary 3 -- does MA3 also fail on the same holdout?

| outcome | count of 28 | note |
|---|---|---|
| MA3 also fails (MA3 MASE >= 1.1) | 25 | on these, the served model is not what makes the score bad -- the naive baseline misses too |
| MA3 passes (MA3 MASE < 1.1) | 0 | -- |
| not comparable | 3 | `64900508` (7.0 mo), `64900506` (7.0 mo), `65086431` (5.0 mo). All three are scored from `pipeline (20% split)`: `mase_common` and `ma3_mase_common` are both null, so there is no MA3 figure on the same holdout to compare against. |

## Nulls found in the 28 rows

| column | nulls | SKUs (months of history) | why |
|---|---|---|---|
| `mase_common` | 3 | `64900508` (7), `64900506` (7), `65086431` (5) | not scored on the common window; verdict falls back to the stored 20% split |
| `ma3_mase_common` | 3 | `64900508` (7), `64900506` (7), `65086431` (5) | no common-window scoring, so no MA3 figure on that holdout |
| `mape_common` | 1 | `65086431` (5) | not scored on the common window (`verdict_source` = pipeline 20% split) |
| `wape_common` | 1 | `65086431` (5) | not scored on the common window (`verdict_source` = pipeline 20% split) |
| `rmse_common` | 1 | `65086431` (5) | not scored on the common window (`verdict_source` = pipeline 20% split) |
| `ma3_rmse_common` | 1 | `65086431` (5) | not scored on the common window (`verdict_source` = pipeline 20% split) |
| `coverage_common_in_sample` | 1 | `65086431` (5) | not scored on the common window (`verdict_source` = pipeline 20% split) |
| `ma3_coverage_common_in_sample` | 1 | `65086431` (5) | not scored on the common window (`verdict_source` = pipeline 20% split) |
| `band_width_common` | 1 | `65086431` (5) | not scored on the common window (`verdict_source` = pipeline 20% split) |
| `band_width_over_forecast_common` | 1 | `65086431` (5) | not scored on the common window (`verdict_source` = pipeline 20% split) |
| `recent_level_ratio` | 7 | `64401259` (10), `64900508` (7), `64900614` (9), `64900506` (7), `65086431` (5), `64900613` (9), `64967994` (8) | mean(last 3)/mean(last 12) needs 12 months |
| `ma3_also_fails_common` | 3 | `64900508` (7), `64900506` (7), `65086431` (5) | derived from `ma3_mase_common`, which is null |
| `cause_level_shift` | 9 | `64830409` (16), `64401259` (10), `64900508` (7), `64900614` (9), `64900506` (7), `64861488` (12), `65086431` (5), `64900613` (9), `64967994` (8) | level shift needs >= 18 months |
| `cause_largest_step_month` | 1 | `65086431` (5) | shortest series in the cohort (5 months); the other 8 SKUs with a null `cause_level_shift` still carry a step month |
| `cause_cv_last12` | 7 | `64401259` (10), `64900508` (7), `64900614` (9), `64900506` (7), `65086431` (5), `64900613` (9), `64967994` (8) | CV(last 12) needs 12 months |

No other column is null in any of the 28 rows.

