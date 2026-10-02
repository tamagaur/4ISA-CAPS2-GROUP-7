# Examples - SIMULATION — real + 2021–22 placeholder data; not served, not used in the LP or in accuracy claims

**Scope.** Del Monte has no product-level sales, so it is not forecast. Product-level simulation and fit diagnosis are Unilever-only; Del Monte gets the category-level and coverage view.

One line per product. MASE on the same months and scale in both runs; never an accuracy claim.

- **biggest improvement** - `69695566` LADY'S CHOICE REAL MAYO 72X27ML: REAL long bin / xgb_ma3_avg, MASE 0.94 (borderline), March forecast 27,951 -> SIM long bin / xgb_ma3_avg, MASE 0.78 (fit), March forecast 28,092 (no placeholder rows of its own - it moves only because the shared XGBoost model is trained on the bigger pool; scored on common, 6 months).
- **biggest worsening** - `62718199` CREAM SILK RO ULTREBORN STRT 288X22ML: REAL long bin / xgb_ma3_avg, MASE 0.33 (fit), March forecast 11,430 -> SIM long bin / xgb_ma3_avg, MASE 0.48 (fit), March forecast 11,523 (no placeholder rows of its own - it moves only because the shared XGBoost model is trained on the bigger pool; scored on common, 6 months).
- **verdict change, with placeholder months** - `65004477` BESTFOODS RGLR MYNS MAYO MAGIC 72X80ML: REAL long bin / xgb_ma3_avg, MASE 1.11 (not fit), March forecast 4,379 -> SIM long bin / xgb_ma3_avg, MASE 1.07 (borderline), March forecast 4,192 (24 placeholder months added; sales months 38 -> 62; scored on common, 6 months).
- **does not change** - `68200184` CLOSEUP RED HOT NEW 12(11+1)X(2X10G): REAL long bin / xgb_ma3_avg, MASE 0.64 (fit), March forecast 544 -> SIM long bin / xgb_ma3_avg, MASE 0.64 (fit), March forecast 547 (20 placeholder months added; sales months 38 -> 58; scored on common, 6 months).
- **bin change** - none: 0 of 132 products change bin. All 40 products that receive placeholder rows already have 37+ real sales months, so they are in the long bin with or without them.
