# Pre-Load Coverage Checklist

One row per (principal, doc_type, month), all 68 months (2021-01 to 2026-08), no ranges collapsed.

**Note on unilever_sku**: derived directly from transform_fact()'s row-level output (grouped by calendar_month), not from transform/_manifest.json. transform_driver.py's _sheet_record() groups by (src_file, src_sheet), which collapses all 38 real months into one manifest record since the real unilever_sku corpus is one combined file/sheet - confirmed this is a manifest-reporting bug only (transform_fact() itself correctly processes all 44,583 rows / 68 months, 0 conflicts, rows_in==rows_out). Not fixed in transform_driver.py itself this session (would need care to not affect every other doc_type's classification); worked around here for accurate reporting.

| Principal | Doc Type | Month | Source | Transform Outcome | Row Count | Reach Fact | If NO, Why |
|---|---|---|---|---|---|---|---|
| delmonte | sales_register | 2021-01 | SYNTHETIC | 540 promoted | 540 | YES |  |
| delmonte | sales_register | 2021-02 | SYNTHETIC | 610 promoted | 610 | YES |  |
| delmonte | sales_register | 2021-03 | SYNTHETIC | 891 promoted | 891 | YES |  |
| delmonte | sales_register | 2021-04 | SYNTHETIC | 759 promoted | 759 | YES |  |
| delmonte | sales_register | 2021-05 | SYNTHETIC | 584 promoted | 584 | YES |  |
| delmonte | sales_register | 2021-06 | SYNTHETIC | 604 promoted | 604 | YES |  |
| delmonte | sales_register | 2021-07 | SYNTHETIC | 664 promoted | 664 | YES |  |
| delmonte | sales_register | 2021-08 | SYNTHETIC | 532 promoted | 532 | YES |  |
| delmonte | sales_register | 2021-09 | SYNTHETIC | 513 promoted | 513 | YES |  |
| delmonte | sales_register | 2021-10 | SYNTHETIC | 740 promoted | 740 | YES |  |
| delmonte | sales_register | 2021-11 | SYNTHETIC | 407 promoted | 407 | YES |  |
| delmonte | sales_register | 2021-12 | SYNTHETIC | 462 promoted | 462 | YES |  |
| delmonte | sales_register | 2022-01 | SYNTHETIC | 726 promoted | 726 | YES |  |
| delmonte | sales_register | 2022-02 | SYNTHETIC | 821 promoted | 821 | YES |  |
| delmonte | sales_register | 2022-03 | SYNTHETIC | 1029 promoted | 1029 | YES |  |
| delmonte | sales_register | 2022-04 | SYNTHETIC | 683 promoted | 683 | YES |  |
| delmonte | sales_register | 2022-05 | SYNTHETIC | 974 promoted | 974 | YES |  |
| delmonte | sales_register | 2022-06 | SYNTHETIC | 748 promoted | 748 | YES |  |
| delmonte | sales_register | 2022-07 | SYNTHETIC | 806 promoted | 806 | YES |  |
| delmonte | sales_register | 2022-08 | SYNTHETIC | 485 promoted | 485 | YES |  |
| delmonte | sales_register | 2022-09 | SYNTHETIC | 788 promoted | 788 | YES |  |
| delmonte | sales_register | 2022-10 | SYNTHETIC | 1004 promoted | 1004 | YES |  |
| delmonte | sales_register | 2022-11 | SYNTHETIC | 791 promoted | 791 | YES |  |
| delmonte | sales_register | 2022-12 | SYNTHETIC | 823 promoted | 823 | YES |  |
| delmonte | sales_register | 2023-01 | REAL | 781 promoted | 781 | YES |  |
| delmonte | sales_register | 2023-02 | REAL | 781 promoted | 781 | YES |  |
| delmonte | sales_register | 2023-03 | REAL | 872 promoted | 872 | YES |  |
| delmonte | sales_register | 2023-04 | REAL | 675 promoted | 675 | YES |  |
| delmonte | sales_register | 2023-05 | REAL | 862 promoted | 862 | YES |  |
| delmonte | sales_register | 2023-06 | REAL | 722 promoted | 722 | YES |  |
| delmonte | sales_register | 2023-07 | SYNTHETIC | 980 promoted | 980 | YES |  |
| delmonte | sales_register | 2023-08 | REAL | 703 promoted | 703 | YES |  |
| delmonte | sales_register | 2023-09 | REAL | 793 promoted | 793 | YES |  |
| delmonte | sales_register | 2023-10 | SYNTHETIC | 625 promoted | 625 | YES |  |
| delmonte | sales_register | 2023-11 | REAL | 719 promoted | 719 | YES |  |
| delmonte | sales_register | 2023-12 | REAL | 285 conflict+426 promoted | 711 | YES | partial: 285 rows did not promote |
| delmonte | sales_register | 2024-01 | REAL | 524 conflict+163 promoted | 687 | YES | partial: 524 rows did not promote |
| delmonte | sales_register | 2024-02 | REAL | 222 conflict+607 promoted | 829 | YES | partial: 222 rows did not promote |
| delmonte | sales_register | 2024-03 | SYNTHETIC | 993 promoted | 993 | YES |  |
| delmonte | sales_register | 2024-04 | SYNTHETIC | 898 promoted | 898 | YES |  |
| delmonte | sales_register | 2024-05 | SYNTHETIC | 786 promoted | 786 | YES |  |
| delmonte | sales_register | 2024-06 | SYNTHETIC | 939 promoted | 939 | YES |  |
| delmonte | sales_register | 2024-07 | SYNTHETIC | 919 promoted | 919 | YES |  |
| delmonte | sales_register | 2024-08 | SYNTHETIC | 1113 promoted | 1113 | YES |  |
| delmonte | sales_register | 2024-09 | SYNTHETIC | 710 promoted | 710 | YES |  |
| delmonte | sales_register | 2024-10 | SYNTHETIC | 973 promoted | 973 | YES |  |
| delmonte | sales_register | 2024-11 | SYNTHETIC | 780 promoted | 780 | YES |  |
| delmonte | sales_register | 2024-12 | SYNTHETIC | 639 promoted | 639 | YES |  |
| delmonte | sales_register | 2025-01 | SYNTHETIC | 832 promoted | 832 | YES |  |
| delmonte | sales_register | 2025-02 | SYNTHETIC | 1002 promoted | 1002 | YES |  |
| delmonte | sales_register | 2025-03 | REAL | 1701 promoted | 1701 | YES |  |
| delmonte | sales_register | 2025-04 | REAL | 1540 promoted | 1540 | YES |  |
| delmonte | sales_register | 2025-05 | SYNTHETIC | 774 promoted | 774 | YES |  |
| delmonte | sales_register | 2025-06 | REAL | 1808 promoted | 1808 | YES |  |
| delmonte | sales_register | 2025-07 | SYNTHETIC | 954 promoted | 954 | YES |  |
| delmonte | sales_register | 2025-08 | REAL | 1582 promoted | 1582 | YES |  |
| delmonte | sales_register | 2025-09 | REAL | 1532 promoted | 1532 | YES |  |
| delmonte | sales_register | 2025-10 | REAL | 1130 demoted+1386 promoted | 2516 | YES | partial: 1130 rows did not promote |
| delmonte | sales_register | 2025-11 | REAL | 1094 demoted+1397 promoted | 2491 | YES | partial: 1094 rows did not promote |
| delmonte | sales_register | 2025-12 | REAL | 1512 promoted | 1512 | YES |  |
| delmonte | sales_register | 2026-01 | SYNTHETIC | 662 promoted | 662 | YES |  |
| delmonte | sales_register | 2026-02 | SYNTHETIC | 1089 promoted | 1089 | YES |  |
| delmonte | sales_register | 2026-03 | SYNTHETIC | 786 promoted | 786 | YES |  |
| delmonte | sales_register | 2026-04 | SYNTHETIC | 79 promoted | 79 | YES |  |
| delmonte | sales_register | 2026-05 | SYNTHETIC | 67 promoted | 67 | YES |  |
| delmonte | sales_register | 2026-06 | SYNTHETIC | 633 promoted | 633 | YES |  |
| delmonte | sales_register | 2026-07 | SYNTHETIC | 1072 conflict | 1072 | NO | dedup conflict on natural key |
| delmonte | sales_register | 2026-08 | SYNTHETIC | 86 promoted | 86 | YES |  |
| delmonte | sell_out | 2021-01 | SYNTHETIC | 132 promoted | 132 | YES |  |
| delmonte | sell_out | 2021-02 | SYNTHETIC | 149 promoted | 149 | YES |  |
| delmonte | sell_out | 2021-03 | SYNTHETIC | 133 promoted | 133 | YES |  |
| delmonte | sell_out | 2021-04 | SYNTHETIC | 144 promoted | 144 | YES |  |
| delmonte | sell_out | 2021-05 | SYNTHETIC | 153 promoted | 153 | YES |  |
| delmonte | sell_out | 2021-06 | SYNTHETIC | 145 promoted | 145 | YES |  |
| delmonte | sell_out | 2021-07 | SYNTHETIC | 133 promoted | 133 | YES |  |
| delmonte | sell_out | 2021-08 | SYNTHETIC | 129 promoted | 129 | YES |  |
| delmonte | sell_out | 2021-09 | SYNTHETIC | 135 promoted | 135 | YES |  |
| delmonte | sell_out | 2021-10 | SYNTHETIC | 141 promoted | 141 | YES |  |
| delmonte | sell_out | 2021-11 | SYNTHETIC | 137 promoted | 137 | YES |  |
| delmonte | sell_out | 2021-12 | SYNTHETIC | 136 promoted | 136 | YES |  |
| delmonte | sell_out | 2022-01 | SYNTHETIC | 139 promoted | 139 | YES |  |
| delmonte | sell_out | 2022-02 | SYNTHETIC | 134 promoted | 134 | YES |  |
| delmonte | sell_out | 2022-03 | SYNTHETIC | 143 promoted | 143 | YES |  |
| delmonte | sell_out | 2022-04 | SYNTHETIC | 127 promoted | 127 | YES |  |
| delmonte | sell_out | 2022-05 | SYNTHETIC | 146 promoted | 146 | YES |  |
| delmonte | sell_out | 2022-06 | SYNTHETIC | 146 promoted | 146 | YES |  |
| delmonte | sell_out | 2022-07 | SYNTHETIC | 138 promoted | 138 | YES |  |
| delmonte | sell_out | 2022-08 | SYNTHETIC | 146 promoted | 146 | YES |  |
| delmonte | sell_out | 2022-09 | SYNTHETIC | 143 promoted | 143 | YES |  |
| delmonte | sell_out | 2022-10 | SYNTHETIC | 142 promoted | 142 | YES |  |
| delmonte | sell_out | 2022-11 | SYNTHETIC | 134 promoted | 134 | YES |  |
| delmonte | sell_out | 2022-12 | SYNTHETIC | 142 promoted | 142 | YES |  |
| delmonte | sell_out | 2023-01 | REAL | 135 promoted | 135 | YES |  |
| delmonte | sell_out | 2023-02 | REAL | 130 promoted | 130 | YES |  |
| delmonte | sell_out | 2023-03 | REAL | 139 promoted | 139 | YES |  |
| delmonte | sell_out | 2023-04 | REAL | 137 promoted | 137 | YES |  |
| delmonte | sell_out | 2023-05 | REAL | 131 promoted | 131 | YES |  |
| delmonte | sell_out | 2023-06 | REAL | 135 promoted | 135 | YES |  |
| delmonte | sell_out | 2023-07 | SYNTHETIC | 141 promoted | 141 | YES |  |
| delmonte | sell_out | 2023-08 | REAL | 139 promoted | 139 | YES |  |
| delmonte | sell_out | 2023-09 | REAL | 141 promoted | 141 | YES |  |
| delmonte | sell_out | 2023-10 | SYNTHETIC | 140 promoted | 140 | YES |  |
| delmonte | sell_out | 2023-11 | REAL | 140 promoted | 140 | YES |  |
| delmonte | sell_out | 2023-12 | SYNTHETIC | 136 promoted | 136 | YES |  |
| delmonte | sell_out | 2024-01 | REAL | 146 promoted | 146 | YES |  |
| delmonte | sell_out | 2024-02 | REAL | 136 promoted | 136 | YES |  |
| delmonte | sell_out | 2024-03 | SYNTHETIC | 134 promoted | 134 | YES |  |
| delmonte | sell_out | 2024-04 | SYNTHETIC | 128 promoted | 128 | YES |  |
| delmonte | sell_out | 2024-05 | SYNTHETIC | 137 promoted | 137 | YES |  |
| delmonte | sell_out | 2024-06 | SYNTHETIC | 144 promoted | 144 | YES |  |
| delmonte | sell_out | 2024-07 | SYNTHETIC | 144 promoted | 144 | YES |  |
| delmonte | sell_out | 2024-08 | SYNTHETIC | 138 promoted | 138 | YES |  |
| delmonte | sell_out | 2024-09 | SYNTHETIC | 142 promoted | 142 | YES |  |
| delmonte | sell_out | 2024-10 | SYNTHETIC | 133 promoted | 133 | YES |  |
| delmonte | sell_out | 2024-11 | SYNTHETIC | 135 promoted | 135 | YES |  |
| delmonte | sell_out | 2024-12 | SYNTHETIC | 144 promoted | 144 | YES |  |
| delmonte | sell_out | 2025-01 | SYNTHETIC | 26 promoted | 26 | YES |  |
| delmonte | sell_out | 2025-02 | SYNTHETIC | 25 promoted | 25 | YES |  |
| delmonte | sell_out | 2025-03 | REAL | 12 promoted | 12 | YES |  |
| delmonte | sell_out | 2025-04 | REAL | 11 promoted | 11 | YES |  |
| delmonte | sell_out | 2025-05 | SYNTHETIC | 28 promoted | 28 | YES |  |
| delmonte | sell_out | 2025-06 | REAL | 11 promoted | 11 | YES |  |
| delmonte | sell_out | 2025-07 | SYNTHETIC | 26 promoted | 26 | YES |  |
| delmonte | sell_out | 2025-08 | REAL | 10 promoted | 10 | YES |  |
| delmonte | sell_out | 2025-09 | REAL | 10 promoted | 10 | YES |  |
| delmonte | sell_out | 2025-10 | SYNTHETIC | 29 promoted | 29 | YES |  |
| delmonte | sell_out | 2025-11 | SYNTHETIC | 28 promoted | 28 | YES |  |
| delmonte | sell_out | 2025-12 | REAL | 10 promoted | 10 | YES |  |
| delmonte | sell_out | 2026-01 | SYNTHETIC | 26 promoted | 26 | YES |  |
| delmonte | sell_out | 2026-02 | SYNTHETIC | 29 promoted | 29 | YES |  |
| delmonte | sell_out | 2026-03 | SYNTHETIC | 26 promoted | 26 | YES |  |
| delmonte | sell_out | 2026-04 | SYNTHETIC | 6 conflict+5 promoted | 11 | YES | partial: 6 rows did not promote |
| delmonte | sell_out | 2026-05 | SYNTHETIC | 14 conflict+5 promoted | 19 | YES | partial: 14 rows did not promote |
| delmonte | sell_out | 2026-06 | SYNTHETIC | 20 conflict | 20 | NO | dedup conflict on natural key |
| delmonte | sell_out | 2026-07 | SYNTHETIC | 11 conflict | 11 | NO | dedup conflict on natural key |
| delmonte | sell_out | 2026-08 | SYNTHETIC | 14 conflict+5 promoted | 19 | YES | partial: 14 rows did not promote |
| delmonte | inventory_sign_off | 2021-01 | SYNTHETIC | 362 promoted | 362 | YES |  |
| delmonte | inventory_sign_off | 2021-02 | SYNTHETIC | 361 promoted | 361 | YES |  |
| delmonte | inventory_sign_off | 2021-03 | SYNTHETIC | 311 promoted | 311 | YES |  |
| delmonte | inventory_sign_off | 2021-04 | SYNTHETIC | 306 promoted | 306 | YES |  |
| delmonte | inventory_sign_off | 2021-05 | SYNTHETIC | 301 promoted | 301 | YES |  |
| delmonte | inventory_sign_off | 2021-06 | SYNTHETIC | 343 promoted | 343 | YES |  |
| delmonte | inventory_sign_off | 2021-07 | SYNTHETIC | 341 promoted | 341 | YES |  |
| delmonte | inventory_sign_off | 2021-08 | SYNTHETIC | 344 promoted | 344 | YES |  |
| delmonte | inventory_sign_off | 2021-09 | SYNTHETIC | 121 conflict+223 promoted | 344 | YES | partial: 121 rows did not promote |
| delmonte | inventory_sign_off | 2021-10 | SYNTHETIC | 326 promoted | 326 | YES |  |
| delmonte | inventory_sign_off | 2021-11 | SYNTHETIC | 362 promoted | 362 | YES |  |
| delmonte | inventory_sign_off | 2021-12 | SYNTHETIC | 297 promoted | 297 | YES |  |
| delmonte | inventory_sign_off | 2022-01 | SYNTHETIC | 271 promoted | 271 | YES |  |
| delmonte | inventory_sign_off | 2022-02 | SYNTHETIC | 329 promoted | 329 | YES |  |
| delmonte | inventory_sign_off | 2022-03 | SYNTHETIC | 309 promoted | 309 | YES |  |
| delmonte | inventory_sign_off | 2022-04 | SYNTHETIC | 322 promoted | 322 | YES |  |
| delmonte | inventory_sign_off | 2022-05 | SYNTHETIC | 306 promoted | 306 | YES |  |
| delmonte | inventory_sign_off | 2022-06 | SYNTHETIC | 327 promoted | 327 | YES |  |
| delmonte | inventory_sign_off | 2022-07 | SYNTHETIC | 333 promoted | 333 | YES |  |
| delmonte | inventory_sign_off | 2022-08 | SYNTHETIC | 332 promoted | 332 | YES |  |
| delmonte | inventory_sign_off | 2022-09 | SYNTHETIC | 288 promoted | 288 | YES |  |
| delmonte | inventory_sign_off | 2022-10 | SYNTHETIC | 277 promoted | 277 | YES |  |
| delmonte | inventory_sign_off | 2022-11 | SYNTHETIC | 362 promoted | 362 | YES |  |
| delmonte | inventory_sign_off | 2022-12 | SYNTHETIC | 290 promoted | 290 | YES |  |
| delmonte | inventory_sign_off | 2023-01 | REAL | 309 promoted | 309 | YES |  |
| delmonte | inventory_sign_off | 2023-02 | REAL | 201 promoted | 201 | YES |  |
| delmonte | inventory_sign_off | 2023-03 | REAL | 294 promoted | 294 | YES |  |
| delmonte | inventory_sign_off | 2023-04 | REAL | 298 promoted | 298 | YES |  |
| delmonte | inventory_sign_off | 2023-05 | REAL | 311 promoted | 311 | YES |  |
| delmonte | inventory_sign_off | 2023-06 | REAL | 295 promoted | 295 | YES |  |
| delmonte | inventory_sign_off | 2023-07 | SYNTHETIC | 287 promoted | 287 | YES |  |
| delmonte | inventory_sign_off | 2023-08 | REAL | 739 promoted | 739 | YES |  |
| delmonte | inventory_sign_off | 2023-09 | REAL | 313 promoted | 313 | YES |  |
| delmonte | inventory_sign_off | 2023-10 | SYNTHETIC | 324 promoted | 324 | YES |  |
| delmonte | inventory_sign_off | 2023-11 | SYNTHETIC | 291 promoted | 291 | YES |  |
| delmonte | inventory_sign_off | 2023-12 | REAL | 293 promoted | 293 | YES |  |
| delmonte | inventory_sign_off | 2024-01 | REAL | 286 promoted | 286 | YES |  |
| delmonte | inventory_sign_off | 2024-02 | REAL | 310 promoted | 310 | YES |  |
| delmonte | inventory_sign_off | 2024-03 | SYNTHETIC | 283 promoted | 283 | YES |  |
| delmonte | inventory_sign_off | 2024-04 | SYNTHETIC | 359 promoted | 359 | YES |  |
| delmonte | inventory_sign_off | 2024-05 | SYNTHETIC | 280 promoted | 280 | YES |  |
| delmonte | inventory_sign_off | 2024-06 | SYNTHETIC | 253 promoted | 253 | YES |  |
| delmonte | inventory_sign_off | 2024-07 | SYNTHETIC | 307 promoted | 307 | YES |  |
| delmonte | inventory_sign_off | 2024-08 | SYNTHETIC | 325 promoted | 325 | YES |  |
| delmonte | inventory_sign_off | 2024-09 | SYNTHETIC | 368 promoted | 368 | YES |  |
| delmonte | inventory_sign_off | 2024-10 | SYNTHETIC | 310 promoted | 310 | YES |  |
| delmonte | inventory_sign_off | 2024-11 | SYNTHETIC | 304 promoted | 304 | YES |  |
| delmonte | inventory_sign_off | 2024-12 | SYNTHETIC | 347 promoted | 347 | YES |  |
| delmonte | inventory_sign_off | 2025-01 | SYNTHETIC | 315 promoted | 315 | YES |  |
| delmonte | inventory_sign_off | 2025-02 | SYNTHETIC | 311 promoted | 311 | YES |  |
| delmonte | inventory_sign_off | 2025-03 | REAL | 238 demoted+294 promoted | 532 | YES | partial: 238 rows did not promote |
| delmonte | inventory_sign_off | 2025-04 | REAL | 238 demoted+294 promoted | 532 | YES | partial: 238 rows did not promote |
| delmonte | inventory_sign_off | 2025-05 | SYNTHETIC | 359 promoted | 359 | YES |  |
| delmonte | inventory_sign_off | 2025-06 | REAL | 238 demoted+306 promoted | 544 | YES | partial: 238 rows did not promote |
| delmonte | inventory_sign_off | 2025-07 | SYNTHETIC | 304 promoted | 304 | YES |  |
| delmonte | inventory_sign_off | 2025-08 | REAL | 238 demoted+326 promoted | 564 | YES | partial: 238 rows did not promote |
| delmonte | inventory_sign_off | 2025-09 | REAL | 238 demoted+305 promoted | 543 | YES | partial: 238 rows did not promote |
| delmonte | inventory_sign_off | 2025-10 | SYNTHETIC | 352 promoted | 352 | YES |  |
| delmonte | inventory_sign_off | 2025-11 | SYNTHETIC | 338 promoted | 338 | YES |  |
| delmonte | inventory_sign_off | 2025-12 | REAL | 238 demoted+417 promoted | 655 | YES | partial: 238 rows did not promote |
| delmonte | inventory_sign_off | 2026-01 | SYNTHETIC | 299 promoted | 299 | YES |  |
| delmonte | inventory_sign_off | 2026-02 | SYNTHETIC | 296 promoted | 296 | YES |  |
| delmonte | inventory_sign_off | 2026-03 | SYNTHETIC | 306 promoted | 306 | YES |  |
| delmonte | inventory_sign_off | 2026-04 | SYNTHETIC | 333 conflict | 333 | NO | dedup conflict on natural key |
| delmonte | inventory_sign_off | 2026-05 | SYNTHETIC | 309 conflict | 309 | NO | dedup conflict on natural key |
| delmonte | inventory_sign_off | 2026-06 | SYNTHETIC | 400 conflict | 400 | NO | dedup conflict on natural key |
| delmonte | inventory_sign_off | 2026-07 | SYNTHETIC | 294 conflict | 294 | NO | dedup conflict on natural key |
| delmonte | inventory_sign_off | 2026-08 | SYNTHETIC | 333 conflict | 333 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2021-01 | SYNTHETIC | 48 promoted | 48 | YES |  |
| delmonte | purchase_order | 2021-02 | SYNTHETIC | 26 promoted | 26 | YES |  |
| delmonte | purchase_order | 2021-03 | SYNTHETIC | 25 promoted | 25 | YES |  |
| delmonte | purchase_order | 2021-04 | SYNTHETIC | 36 promoted | 36 | YES |  |
| delmonte | purchase_order | 2021-05 | SYNTHETIC | 23 promoted | 23 | YES |  |
| delmonte | purchase_order | 2021-06 | SYNTHETIC | 47 promoted | 47 | YES |  |
| delmonte | purchase_order | 2021-07 | SYNTHETIC | 42 promoted | 42 | YES |  |
| delmonte | purchase_order | 2021-08 | SYNTHETIC | 32 promoted | 32 | YES |  |
| delmonte | purchase_order | 2021-09 | SYNTHETIC | 27 promoted | 27 | YES |  |
| delmonte | purchase_order | 2021-10 | SYNTHETIC | 39 promoted | 39 | YES |  |
| delmonte | purchase_order | 2021-11 | SYNTHETIC | 30 promoted | 30 | YES |  |
| delmonte | purchase_order | 2021-12 | SYNTHETIC | 35 promoted | 35 | YES |  |
| delmonte | purchase_order | 2022-01 | SYNTHETIC | 29 promoted | 29 | YES |  |
| delmonte | purchase_order | 2022-02 | SYNTHETIC | 33 promoted | 33 | YES |  |
| delmonte | purchase_order | 2022-03 | SYNTHETIC | 34 promoted | 34 | YES |  |
| delmonte | purchase_order | 2022-04 | SYNTHETIC | 27 promoted | 27 | YES |  |
| delmonte | purchase_order | 2022-05 | SYNTHETIC | 33 promoted | 33 | YES |  |
| delmonte | purchase_order | 2022-06 | SYNTHETIC | 30 promoted | 30 | YES |  |
| delmonte | purchase_order | 2022-07 | SYNTHETIC | 43 promoted | 43 | YES |  |
| delmonte | purchase_order | 2022-08 | SYNTHETIC | 33 promoted | 33 | YES |  |
| delmonte | purchase_order | 2022-09 | SYNTHETIC | 41 promoted | 41 | YES |  |
| delmonte | purchase_order | 2022-10 | SYNTHETIC | 45 promoted | 45 | YES |  |
| delmonte | purchase_order | 2022-11 | SYNTHETIC | 43 promoted | 43 | YES |  |
| delmonte | purchase_order | 2022-12 | SYNTHETIC | 38 promoted | 38 | YES |  |
| delmonte | purchase_order | 2023-01 | SYNTHETIC | 58 promoted | 58 | YES |  |
| delmonte | purchase_order | 2023-02 | SYNTHETIC | 38 promoted | 38 | YES |  |
| delmonte | purchase_order | 2023-03 | SYNTHETIC | 38 promoted | 38 | YES |  |
| delmonte | purchase_order | 2023-04 | SYNTHETIC | 33 promoted | 33 | YES |  |
| delmonte | purchase_order | 2023-05 | SYNTHETIC | 51 promoted | 51 | YES |  |
| delmonte | purchase_order | 2023-06 | SYNTHETIC | 32 promoted | 32 | YES |  |
| delmonte | purchase_order | 2023-07 | SYNTHETIC | 25 promoted | 25 | YES |  |
| delmonte | purchase_order | 2023-08 | SYNTHETIC | 45 promoted | 45 | YES |  |
| delmonte | purchase_order | 2023-09 | REAL | 34 promoted | 34 | YES |  |
| delmonte | purchase_order | 2023-10 | SYNTHETIC | 31 promoted | 31 | YES |  |
| delmonte | purchase_order | 2023-11 | REAL | 39 promoted | 39 | YES |  |
| delmonte | purchase_order | 2023-12 | REAL | 57 promoted | 57 | YES |  |
| delmonte | purchase_order | 2024-01 | REAL | 37 conflict | 37 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-02 | REAL | 8 conflict+21 promoted | 29 | YES | partial: 8 rows did not promote |
| delmonte | purchase_order | 2024-03 | SYNTHETIC | 36 conflict | 36 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-04 | SYNTHETIC | 41 conflict | 41 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-05 | SYNTHETIC | 26 conflict | 26 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-06 | SYNTHETIC | 29 conflict | 29 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-07 | SYNTHETIC | 33 conflict | 33 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-08 | SYNTHETIC | 46 conflict | 46 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-09 | SYNTHETIC | 49 conflict | 49 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-10 | SYNTHETIC | 46 conflict | 46 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-11 | SYNTHETIC | 37 conflict | 37 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2024-12 | SYNTHETIC | 54 conflict | 54 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-01 | SYNTHETIC | 26 conflict | 26 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-02 | SYNTHETIC | 49 conflict | 49 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-03 | REAL | 22 conflict+16 promoted | 38 | YES | partial: 22 rows did not promote |
| delmonte | purchase_order | 2025-04 | REAL | 64 conflict | 64 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-05 | SYNTHETIC | 54 conflict | 54 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-06 | REAL | 58 conflict | 58 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-07 | SYNTHETIC | 27 conflict | 27 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-08 | REAL | 74 conflict | 74 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-09 | REAL | 45 promoted | 45 | YES |  |
| delmonte | purchase_order | 2025-10 | SYNTHETIC | 30 conflict | 30 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-11 | SYNTHETIC | 39 conflict | 39 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2025-12 | REAL | 24 conflict+45 promoted | 69 | YES | partial: 24 rows did not promote |
| delmonte | purchase_order | 2026-01 | SYNTHETIC | 30 conflict | 30 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2026-02 | SYNTHETIC | 41 conflict | 41 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2026-03 | SYNTHETIC | 26 conflict | 26 | NO | dedup conflict on natural key |
| delmonte | purchase_order | 2026-04 | SYNTHETIC | 32 promoted | 32 | YES |  |
| delmonte | purchase_order | 2026-05 | SYNTHETIC | 62 promoted | 62 | YES |  |
| delmonte | purchase_order | 2026-06 | SYNTHETIC | 77 promoted | 77 | YES |  |
| delmonte | purchase_order | 2026-07 | SYNTHETIC | 37 promoted | 37 | YES |  |
| delmonte | purchase_order | 2026-08 | SYNTHETIC | 42 promoted | 42 | YES |  |
| delmonte | sales_return | 2021-01 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-02 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-03 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-04 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-05 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-06 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-08 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-09 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-10 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-11 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2021-12 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-01 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-02 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-03 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-04 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-05 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-06 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-08 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-09 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-10 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-11 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2022-12 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2023-01 | REAL | 70 demoted | 70 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2023-02 | REAL | 47 demoted | 47 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2023-03 | REAL | 42 demoted | 42 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2023-04 | REAL | 37 demoted | 37 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2023-05 | REAL | 69 demoted | 69 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2023-06 | REAL | 71 demoted | 71 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2023-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2023-08 | REAL | 66 demoted | 66 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2023-09 | REAL | 84 demoted | 84 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2023-10 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2023-11 | REAL | 35 demoted | 35 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2023-12 | REAL | 92 demoted | 92 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2024-01 | REAL | 95 demoted | 95 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2024-02 | REAL | 63 demoted | 63 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2024-03 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2024-04 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2024-05 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2024-06 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2024-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2024-08 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2024-09 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2024-10 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2024-11 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2024-12 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2025-01 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2025-02 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2025-03 | REAL | 85 demoted | 85 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2025-04 | REAL | 65 demoted | 65 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2025-05 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2025-06 | REAL | 128 demoted | 128 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2025-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2025-08 | REAL | 130 demoted | 130 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2025-09 | REAL | 124 demoted | 124 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2025-10 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2025-11 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2025-12 | REAL | 103 demoted | 103 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2026-01 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2026-02 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2026-03 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | sales_return | 2026-04 | SYNTHETIC | 121 demoted | 121 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2026-05 | SYNTHETIC | 88 demoted | 88 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2026-06 | SYNTHETIC | 101 demoted | 101 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2026-07 | SYNTHETIC | 123 demoted | 123 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | sales_return | 2026-08 | SYNTHETIC | 92 demoted | 92 | NO | demoted (no source_of_truth.yaml fact entry for this doc_type) |
| delmonte | rmr_gs_bo | 2021-01 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-02 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-03 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-04 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-05 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-06 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-08 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-09 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-10 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-11 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2021-12 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-01 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-02 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-03 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-04 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-05 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-06 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-08 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-09 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-10 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-11 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2022-12 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-01 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-02 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-03 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-04 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-05 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-06 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-08 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-09 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-10 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-11 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2023-12 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-01 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-02 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-03 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-04 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-05 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-06 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-08 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-09 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-10 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-11 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2024-12 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-01 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-02 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-03 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-04 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-05 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-06 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-07 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-08 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-09 | NONE | N/A | 0 | NO | no staged data for this month |
| delmonte | rmr_gs_bo | 2025-10 | REAL | 164 conflict+151 demoted | 315 | NO | dedup conflict on natural key; demoted (wrong sheet_role) |
| delmonte | rmr_gs_bo | 2025-11 | REAL | 119 conflict+104 demoted | 223 | NO | dedup conflict on natural key; demoted (wrong sheet_role) |
| delmonte | rmr_gs_bo | 2025-12 | SYNTHETIC | 149 conflict | 149 | NO | dedup conflict on natural key |
| delmonte | rmr_gs_bo | 2026-01 | SYNTHETIC | 123 conflict | 123 | NO | dedup conflict on natural key |
| delmonte | rmr_gs_bo | 2026-02 | SYNTHETIC | 119 conflict | 119 | NO | dedup conflict on natural key |
| delmonte | rmr_gs_bo | 2026-03 | SYNTHETIC | 114 conflict | 114 | NO | dedup conflict on natural key |
| delmonte | rmr_gs_bo | 2026-04 | SYNTHETIC | 154 conflict | 154 | NO | dedup conflict on natural key |
| delmonte | rmr_gs_bo | 2026-05 | SYNTHETIC | 158 conflict | 158 | NO | dedup conflict on natural key |
| delmonte | rmr_gs_bo | 2026-06 | SYNTHETIC | 125 conflict | 125 | NO | dedup conflict on natural key |
| delmonte | rmr_gs_bo | 2026-07 | SYNTHETIC | 119 conflict | 119 | NO | dedup conflict on natural key |
| delmonte | rmr_gs_bo | 2026-08 | SYNTHETIC | 114 conflict | 114 | NO | dedup conflict on natural key |
| unilever | unilever_sku | 2021-01 | SYNTHETIC | 660 promoted | 660 | YES |  |
| unilever | unilever_sku | 2021-02 | SYNTHETIC | 642 promoted | 642 | YES |  |
| unilever | unilever_sku | 2021-03 | SYNTHETIC | 671 promoted | 671 | YES |  |
| unilever | unilever_sku | 2021-04 | SYNTHETIC | 650 promoted | 650 | YES |  |
| unilever | unilever_sku | 2021-05 | SYNTHETIC | 626 promoted | 626 | YES |  |
| unilever | unilever_sku | 2021-06 | SYNTHETIC | 667 promoted | 667 | YES |  |
| unilever | unilever_sku | 2021-07 | SYNTHETIC | 653 promoted | 653 | YES |  |
| unilever | unilever_sku | 2021-08 | SYNTHETIC | 661 promoted | 661 | YES |  |
| unilever | unilever_sku | 2021-09 | SYNTHETIC | 667 promoted | 667 | YES |  |
| unilever | unilever_sku | 2021-10 | SYNTHETIC | 660 promoted | 660 | YES |  |
| unilever | unilever_sku | 2021-11 | SYNTHETIC | 641 promoted | 641 | YES |  |
| unilever | unilever_sku | 2021-12 | SYNTHETIC | 675 promoted | 675 | YES |  |
| unilever | unilever_sku | 2022-01 | SYNTHETIC | 665 promoted | 665 | YES |  |
| unilever | unilever_sku | 2022-02 | SYNTHETIC | 655 promoted | 655 | YES |  |
| unilever | unilever_sku | 2022-03 | SYNTHETIC | 683 promoted | 683 | YES |  |
| unilever | unilever_sku | 2022-04 | SYNTHETIC | 647 promoted | 647 | YES |  |
| unilever | unilever_sku | 2022-05 | SYNTHETIC | 661 promoted | 661 | YES |  |
| unilever | unilever_sku | 2022-06 | SYNTHETIC | 668 promoted | 668 | YES |  |
| unilever | unilever_sku | 2022-07 | SYNTHETIC | 639 promoted | 639 | YES |  |
| unilever | unilever_sku | 2022-08 | SYNTHETIC | 660 promoted | 660 | YES |  |
| unilever | unilever_sku | 2022-09 | SYNTHETIC | 672 promoted | 672 | YES |  |
| unilever | unilever_sku | 2022-10 | SYNTHETIC | 641 promoted | 641 | YES |  |
| unilever | unilever_sku | 2022-11 | SYNTHETIC | 646 promoted | 646 | YES |  |
| unilever | unilever_sku | 2022-12 | SYNTHETIC | 643 promoted | 643 | YES |  |
| unilever | unilever_sku | 2023-01 | REAL | 593 promoted | 593 | YES |  |
| unilever | unilever_sku | 2023-02 | REAL | 589 promoted | 589 | YES |  |
| unilever | unilever_sku | 2023-03 | REAL | 587 promoted | 587 | YES |  |
| unilever | unilever_sku | 2023-04 | REAL | 576 promoted | 576 | YES |  |
| unilever | unilever_sku | 2023-05 | REAL | 619 promoted | 619 | YES |  |
| unilever | unilever_sku | 2023-06 | REAL | 608 promoted | 608 | YES |  |
| unilever | unilever_sku | 2023-07 | REAL | 610 promoted | 610 | YES |  |
| unilever | unilever_sku | 2023-08 | REAL | 627 promoted | 627 | YES |  |
| unilever | unilever_sku | 2023-09 | REAL | 589 promoted | 589 | YES |  |
| unilever | unilever_sku | 2023-10 | REAL | 596 promoted | 596 | YES |  |
| unilever | unilever_sku | 2023-11 | REAL | 597 promoted | 597 | YES |  |
| unilever | unilever_sku | 2023-12 | REAL | 563 promoted | 563 | YES |  |
| unilever | unilever_sku | 2024-01 | REAL | 582 promoted | 582 | YES |  |
| unilever | unilever_sku | 2024-02 | REAL | 659 promoted | 659 | YES |  |
| unilever | unilever_sku | 2024-03 | REAL | 560 promoted | 560 | YES |  |
| unilever | unilever_sku | 2024-04 | REAL | 597 promoted | 597 | YES |  |
| unilever | unilever_sku | 2024-05 | REAL | 627 promoted | 627 | YES |  |
| unilever | unilever_sku | 2024-06 | REAL | 644 promoted | 644 | YES |  |
| unilever | unilever_sku | 2024-07 | REAL | 680 promoted | 680 | YES |  |
| unilever | unilever_sku | 2024-08 | REAL | 637 promoted | 637 | YES |  |
| unilever | unilever_sku | 2024-09 | REAL | 649 promoted | 649 | YES |  |
| unilever | unilever_sku | 2024-10 | REAL | 666 promoted | 666 | YES |  |
| unilever | unilever_sku | 2024-11 | REAL | 691 promoted | 691 | YES |  |
| unilever | unilever_sku | 2024-12 | REAL | 660 promoted | 660 | YES |  |
| unilever | unilever_sku | 2025-01 | REAL | 699 promoted | 699 | YES |  |
| unilever | unilever_sku | 2025-02 | REAL | 666 promoted | 666 | YES |  |
| unilever | unilever_sku | 2025-03 | REAL | 674 promoted | 674 | YES |  |
| unilever | unilever_sku | 2025-04 | REAL | 665 promoted | 665 | YES |  |
| unilever | unilever_sku | 2025-05 | REAL | 732 promoted | 732 | YES |  |
| unilever | unilever_sku | 2025-06 | REAL | 708 promoted | 708 | YES |  |
| unilever | unilever_sku | 2025-07 | REAL | 708 promoted | 708 | YES |  |
| unilever | unilever_sku | 2025-08 | REAL | 716 promoted | 716 | YES |  |
| unilever | unilever_sku | 2025-09 | REAL | 774 promoted | 774 | YES |  |
| unilever | unilever_sku | 2025-10 | REAL | 768 promoted | 768 | YES |  |
| unilever | unilever_sku | 2025-11 | REAL | 754 promoted | 754 | YES |  |
| unilever | unilever_sku | 2025-12 | REAL | 687 promoted | 687 | YES |  |
| unilever | unilever_sku | 2026-01 | REAL | 770 promoted | 770 | YES |  |
| unilever | unilever_sku | 2026-02 | REAL | 779 promoted | 779 | YES |  |
| unilever | unilever_sku | 2026-03 | SYNTHETIC | 670 promoted | 670 | YES |  |
| unilever | unilever_sku | 2026-04 | SYNTHETIC | 643 promoted | 643 | YES |  |
| unilever | unilever_sku | 2026-05 | SYNTHETIC | 652 promoted | 652 | YES |  |
| unilever | unilever_sku | 2026-06 | SYNTHETIC | 654 promoted | 654 | YES |  |
| unilever | unilever_sku | 2026-07 | SYNTHETIC | 640 promoted | 640 | YES |  |
| unilever | unilever_sku | 2026-08 | SYNTHETIC | 657 promoted | 657 | YES |  |
| unilever | ssis_summary | 2021-01 | REAL | 99073 blocked | 99073 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-02 | REAL | 11113 blocked | 11113 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-03 | REAL | 12936 blocked | 12936 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-04 | REAL | 13185 blocked | 13185 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-05 | REAL | 34883 blocked | 34883 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-06 | REAL | 40143 blocked | 40143 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-07 | REAL | 39635 blocked | 39635 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-08 | REAL | 34528 blocked | 34528 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-09 | REAL | 19622 blocked | 19622 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-10 | REAL | 31724 blocked | 31724 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-11 | REAL | 33466 blocked | 33466 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2021-12 | REAL | 23096 blocked | 23096 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-01 | REAL | 32628 blocked | 32628 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-02 | REAL | 29264 blocked | 29264 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-03 | REAL | 34725 blocked | 34725 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-04 | REAL | 27479 blocked | 27479 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-05 | REAL | 28267 blocked | 28267 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-06 | REAL | 31209 blocked | 31209 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-07 | REAL | 28641 blocked | 28641 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-08 | REAL | 27968 blocked | 27968 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-09 | REAL | 38278 blocked | 38278 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-10 | REAL | 33458 blocked | 33458 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-11 | REAL | 15510 blocked | 15510 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2022-12 | REAL | 22870 blocked | 22870 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-01 | REAL | 14226 blocked | 14226 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-02 | REAL | 16251 blocked | 16251 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-03 | REAL | 21179 blocked | 21179 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-04 | REAL | 14364 blocked | 14364 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-05 | REAL | 20882 blocked | 20882 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-06 | REAL | 17155 blocked | 17155 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-07 | REAL | 14946 blocked | 14946 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-08 | REAL | 18429 blocked | 18429 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-09 | REAL | 18257 blocked | 18257 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-10 | REAL | 17930 blocked | 17930 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-11 | REAL | 15499 blocked | 15499 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2023-12 | REAL | 9839 blocked | 9839 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-01 | REAL | 16108 blocked | 16108 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-02 | REAL | 16186 blocked | 16186 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-03 | REAL | 16787 blocked | 16787 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-04 | REAL | 33962 blocked | 33962 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-05 | REAL | 39498 blocked | 39498 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-06 | REAL | 34955 blocked | 34955 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-07 | REAL | 43131 blocked | 43131 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-08 | REAL | 46785 blocked | 46785 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-09 | REAL | 43843 blocked | 43843 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-10 | REAL | 35090 blocked | 35090 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-11 | REAL | 37158 blocked | 37158 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2024-12 | REAL | 18498 blocked | 18498 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-01 | REAL | 44621 blocked | 44621 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-02 | REAL | 38744 blocked | 38744 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-03 | REAL | 48650 blocked | 48650 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-04 | REAL | 41585 blocked | 41585 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-05 | REAL | 53310 blocked | 53310 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-06 | REAL | 46503 blocked | 46503 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-07 | REAL | 47723 blocked | 47723 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-08 | REAL | 42891 blocked | 42891 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-09 | REAL | 44532 blocked | 44532 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-10 | REAL | 43499 blocked | 43499 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-11 | REAL | 44326 blocked | 44326 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2025-12 | REAL | 32530 blocked | 32530 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2026-01 | REAL | 26672 blocked | 26672 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2026-02 | REAL | 24571 blocked | 24571 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2026-03 | REAL | 26494 blocked | 26494 | NO | blocked (natural_key unconfirmed) |
| unilever | ssis_summary | 2026-04 | NONE | N/A | 0 | NO | no staged data for this month |
| unilever | ssis_summary | 2026-05 | NONE | N/A | 0 | NO | no staged data for this month |
| unilever | ssis_summary | 2026-06 | NONE | N/A | 0 | NO | no staged data for this month |
| unilever | ssis_summary | 2026-07 | NONE | N/A | 0 | NO | no staged data for this month |
| unilever | ssis_summary | 2026-08 | NONE | N/A | 0 | NO | no staged data for this month |

## Summary per (principal, doc_type)

| Principal | Doc Type | YES months | NO months | NO month list |
|---|---|---|---|---|
| delmonte | sales_register | 67/68 | 1/68 | 2026-07 |
| delmonte | sell_out | 66/68 | 2/68 | 2026-06, 2026-07 |
| delmonte | inventory_sign_off | 63/68 | 5/68 | 2026-04, 2026-05, 2026-06, 2026-07, 2026-08 |
| delmonte | purchase_order | 45/68 | 23/68 | 2024-01, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-04, 2025-05, 2025-06, 2025-07, 2025-08, 2025-10, 2025-11, 2026-01, 2026-02, 2026-03 |
| delmonte | sales_return | 0/68 | 68/68 | 2021-01, 2021-02, 2021-03, 2021-04, 2021-05, 2021-06, 2021-07, 2021-08, 2021-09, 2021-10, 2021-11, 2021-12, 2022-01, 2022-02, 2022-03, 2022-04, 2022-05, 2022-06, 2022-07, 2022-08, 2022-09, 2022-10, 2022-11, 2022-12, 2023-01, 2023-02, 2023-03, 2023-04, 2023-05, 2023-06, 2023-07, 2023-08, 2023-09, 2023-10, 2023-11, 2023-12, 2024-01, 2024-02, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-03, 2025-04, 2025-05, 2025-06, 2025-07, 2025-08, 2025-09, 2025-10, 2025-11, 2025-12, 2026-01, 2026-02, 2026-03, 2026-04, 2026-05, 2026-06, 2026-07, 2026-08 |
| delmonte | rmr_gs_bo | 0/68 | 68/68 | 2021-01, 2021-02, 2021-03, 2021-04, 2021-05, 2021-06, 2021-07, 2021-08, 2021-09, 2021-10, 2021-11, 2021-12, 2022-01, 2022-02, 2022-03, 2022-04, 2022-05, 2022-06, 2022-07, 2022-08, 2022-09, 2022-10, 2022-11, 2022-12, 2023-01, 2023-02, 2023-03, 2023-04, 2023-05, 2023-06, 2023-07, 2023-08, 2023-09, 2023-10, 2023-11, 2023-12, 2024-01, 2024-02, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-03, 2025-04, 2025-05, 2025-06, 2025-07, 2025-08, 2025-09, 2025-10, 2025-11, 2025-12, 2026-01, 2026-02, 2026-03, 2026-04, 2026-05, 2026-06, 2026-07, 2026-08 |
| unilever | unilever_sku | 68/68 | 0/68 |  |
| unilever | ssis_summary | 0/68 | 68/68 | 2021-01, 2021-02, 2021-03, 2021-04, 2021-05, 2021-06, 2021-07, 2021-08, 2021-09, 2021-10, 2021-11, 2021-12, 2022-01, 2022-02, 2022-03, 2022-04, 2022-05, 2022-06, 2022-07, 2022-08, 2022-09, 2022-10, 2022-11, 2022-12, 2023-01, 2023-02, 2023-03, 2023-04, 2023-05, 2023-06, 2023-07, 2023-08, 2023-09, 2023-10, 2023-11, 2023-12, 2024-01, 2024-02, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-03, 2025-04, 2025-05, 2025-06, 2025-07, 2025-08, 2025-09, 2025-10, 2025-11, 2025-12, 2026-01, 2026-02, 2026-03, 2026-04, 2026-05, 2026-06, 2026-07, 2026-08 |