# Case-pack audit, 2026-10-23

Scope: `lp_run` 6 (planning cycle 2026-03-01, written 2026-10-22 14:25 UTC, code 3bd3201), 109 `lp_recommendation` rows, all Unilever.
Read live on `public` inside `BEGIN; SET TRANSACTION READ ONLY; ... ROLLBACK`. Nothing was changed and the plan was not re-run.

**Verdict: no wrong pack size found among the 109.** Plan total 435,988 pieces (before rounding 431,443.01); the plan is unchanged by this audit.

## a. Where pack_size comes from

| Principal | Source | Parsed from the name? |
|---|---|---|
| Unilever | The `PACK SIZE` column of the SOH (stock-on-hand) count file (`analytics/etl/extract/ssis_soh.py:168`, `PACK SIZE` -> `pack_size`). `scripts/apply_real_recovery_to_public.py` (X1/D11) filled 291 SKUs that were NULL from that same SOH value | No. It is a source column |
| Del Monte | The price list's `CASE PACK` column, exact code match (`scripts/apply_dm_fixes_to_public.py` batch B5, 187 rows) | No |

`Product_Dimension.pack_size` is TEXT. The LP reads only values matching `^[0-9]+(\.[0-9]+)?$` and above 0 (`backend/stock_units.py:65`, used by `scripts/run_lp.py` `PACK_SIZE_QUERY`). Anything else is "no pack size" and the order is not rounded (`analytics/optimization/lp.py` `round_to_case_packs`: no pack, or pack <= 1, is left unchanged).

## b. Coverage

| Group | Products | With pack_size | Usable (positive number) |
|---|---|---|---|
| Unilever SKU | 2,098 | 2,098 | 2,098 |
| Del Monte SKU | 597 | 187 | 187 |
| Del Monte category | 88 | 0 | 0 |
| **Whole master** | **2,783** | **2,285** | **2,285** |
| **The 109 planned** | 109 | 109 | 109 |

No non-numeric pack_size text exists anywhere in the master. The pack stored on each `lp_recommendation` row equals the current `Product_Dimension.pack_size` for all 109.
Del Monte SKUs are not in the plan (all 109 rows are Unilever), so Del Monte's 410 SKUs without a pack size do not affect it.

## c. Before and after, per product

Check used: the pack size must equal a count written in the product name (`24X25ML` -> 24; `24(11+1)13ML` -> 24; nested `12X12X22G` -> 12x12 = 144).

| Check | Result |
|---|---|
| Plan rows whose pack matches the name | 109 of 109 |
| Pack of 1 or less | 0 |
| Pack over 100 | 40 (all 288, 360, 144; each is the sachet or stick count written in the name, e.g. `288X13ML`, `360X25ML`) |
| Rows rounded up | 73 |
| Rows with order 0 (nothing to round) | 36 |
| Rows rounded down at a ceiling | 0 |
| Total before rounding / after | 431,443.01 / 435,988 (+4,544.99) |

Across the whole Unilever master, 2,096 of 2,098 packs agree with a count in the name; the 2 that do not are outside the plan: `67982571` DOVE S-CONDITIONER `6X48X10ML` has pack 48 where the name implies 288 (one real discrepancy, not planned, not changed), and `20304739` `12X(12X22G)` is 144 = pack 144 (the check's pattern missed the bracket form, not a data error).

Two things to know, neither a wrong value:
- The over-100 flag is the audit threshold; in every one of the 40 cases the pack is what the product name says. Sachet cartons really are 288 or 360 pieces.
- Promo packs written `40(6+1)65G` carry the leading number (40) as the pack, excluding the bonus unit. The data cannot show whether the physical case is 40 or counts the bonus sachets. 7 planned rows are of this form (`62687208`, `62687212`, `65071335`, `65071340`, `69767334`, `69767335`, `69767336`). Worth one question to SSM.

| SKU | Product | Pack | Before | After | Change | Action | Flags |
|---|---|---|---|---|---|---|---|
| 21015692 | AXE RO APOLLO 24X25ML | 24 | 219.82 | 240 | 20.18 | rounded up |  |
| 21051980 | SURF HS STD PWDR BLOSSOMFRESH 12X1100G | 12 | 0.00 | 0 | 0.00 | order 0 |  |
| 21051988 | SURF HS STD PWDR BLOSSOMFRESH 6X2200G | 6 | 41.17 | 42 | 0.83 | rounded up |  |
| 62681003 | SUNSILK SH AD HEALTHY&STRONG 288X13.5ML | 288 | 8,043.19 | 8,064 | 20.81 | rounded up | pack>100 (matches name) |
| 62687200 | CREAM SILK RO ULTREBORN HFALL 288X13ML | 288 | 14,286.79 | 14,400 | 113.21 | rounded up | pack>100 (matches name) |
| 62687204 | CREAM SILK RO ULTREBORN STRT 288X13ML | 288 | 21,355.78 | 21,600 | 244.22 | rounded up | pack>100 (matches name) |
| 62687208 | CREAM SILK ULT REBORN HF 24(11+1)13ML | 24 | 9,390.25 | 9,408 | 17.75 | rounded up |  |
| 62687212 | CREAM SILK ULT REBORN STRT 24(11+1)13ML | 24 | 9,723.32 | 9,744 | 20.68 | rounded up |  |
| 62718193 | CREAM SILK RO ULTREBORN HFALL 288X22ML | 288 | 5,322.07 | 5,472 | 149.93 | rounded up | pack>100 (matches name) |
| 62718199 | CREAM SILK RO ULTREBORN STRT 288X22ML | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 64314343 | DOVE SH CERAMIDE INTENSE REP 288X13.5ML | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 64314344 | DOVE SH CRMD INTNS REP 24(11+1)X13.5ML | 24 | 1,274.71 | 1,296 | 21.29 | rounded up |  |
| 64315064 | DOVE SH RESTORATIVEOIL NOURCARE 288X12ML | 288 | 13,323.25 | 13,536 | 212.75 | rounded up | pack>100 (matches name) |
| 64351369 | KNORR SOUP CHICKEN NOODLE PH 57X63G | 57 | 0.00 | 0 | 0.00 | order 0 |  |
| 64373260 | SURF FABCON BLOSSOM FRESH SOL 360X28ML | 360 | 47,007.85 | 47,160 | 152.15 | rounded up | pack>100 (matches name) |
| 64824374 | REX WMN RO POWDER DRY BRIGHT 72H 24X45ML | 24 | 104.56 | 120 | 15.44 | rounded up |  |
| 64824378 | REX W MRO PWDR DRY + BRGHTENING 24X25ML | 24 | 206.12 | 216 | 9.88 | rounded up |  |
| 64824382 | REX WMN DLN POWDER DRY + BRGHT 360X3ML | 360 | 32,569.19 | 32,760 | 190.81 | rounded up | pack>100 (matches name) |
| 64830409 | KNORR SOUP CRAB & CORN 60X55G | 60 | 308.87 | 360 | 51.13 | rounded up |  |
| 64856504 | SURF FABCON ANTIBAC W MINT STR 360X25ML | 360 | 1,046.11 | 1,080 | 33.89 | rounded up | pack>100 (matches name) |
| 64856586 | SURF FABCON MAGIC BLOOM STR SAC 360X25ML | 360 | 9,207.52 | 9,360 | 152.48 | rounded up | pack>100 (matches name) |
| 64856620 | SURF FABCON BLOSSOM FRESH STR 360X28ML | 360 | 23,670.00 | 23,760 | 90.00 | rounded up | pack>100 (matches name) |
| 64856638 | SURF FABCON LUXE PERFUME STR 360X25ML | 360 | 2,049.19 | 2,160 | 110.81 | rounded up | pack>100 (matches name) |
| 64860720 | SURF FABCON CHARCOAL FRESH STR 360X25ML | 360 | 6,355.14 | 6,480 | 124.86 | rounded up | pack>100 (matches name) |
| 64900488 | CREAM SILK TMT REBOND STRT 288X18ML | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 64900492 | CREAM SILK TMT DAMAGE REP 288X18ML | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 64900598 | CREAM SILK TRI-KRTN SCD STRT 288X14ML | 288 | 10,961.97 | 11,232 | 270.03 | rounded up | pack>100 (matches name) |
| 64900602 | CREAM SILK TRI-KRTN SCD REP SHN 288X14ML | 288 | 3,172.85 | 3,456 | 283.15 | rounded up | pack>100 (matches name) |
| 64953872 | CLOSEUP RED HOT PROMO HL 36X2X173G | 36 | 0.00 | 0 | 0.00 | order 0 | nested A×B |
| 64953874 | CLOSEUP RED HOT PROMO HL 48X2X120G | 48 | 0.00 | 0 | 0.00 | order 0 | nested A×B |
| 64957373 | KNORR SINGLES CHKN + CHKN 48(12+2)X10G | 48 | 5,174.47 | 5,184 | 9.53 | rounded up |  |
| 64957375 | KNORR SINGLES PORK + PORK 48(12+2)X10G | 48 | 4,721.54 | 4,752 | 30.46 | rounded up |  |
| 64957377 | KNORR SINGLES BEEF + BEEF 48(12+2)X10G | 48 | 1,673.79 | 1,680 | 6.21 | rounded up |  |
| 64961947 | LADY'S CHOICE REAL MAYO DOY 24X130ML | 24 | 0.00 | 0 | 0.00 | order 0 |  |
| 64971076 | KNORR SIN GABI+SINGABI 48(6+1)X11G | 48 | 2,221.80 | 2,256 | 34.20 | rounded up |  |
| 64971078 | KNORR SIN ORIG+SINORIG 48(6+1)X11G | 48 | 7,181.42 | 7,200 | 18.58 | rounded up |  |
| 64985753 | KNORR LIQUID SSONING ORIG TPR 12X500ML | 12 | 0.00 | 0 | 0.00 | order 0 |  |
| 64985759 | KNORR LIQUID SSONING ORIG TPR 6X1L | 6 | 384.49 | 390 | 5.51 | rounded up |  |
| 65003211 | AXE DEO AP RLN DARKTEMP 24X25ML | 24 | 51.10 | 72 | 20.90 | rounded up |  |
| 65004666 | BESTFOODS RGLR MYNS MAYO MAGIC 4X3.5L | 4 | 0.00 | 0 | 0.00 | order 0 |  |
| 65004685 | BESTFOODS SNDWCH SPRDSLDMATEDOY24X220ML | 24 | 0.00 | 0 | 0.00 | order 0 |  |
| 65071335 | SURF FABCON BF STR 60(5+1)28ML | 60 | 3,620.35 | 3,660 | 39.65 | rounded up |  |
| 65071340 | SURF FABCON LP STR 60(5+1)25ML | 60 | 3,492.92 | 3,540 | 47.08 | rounded up |  |
| 65244853 | CLEAR SH COOL SPRT MNTHL MEN3C 288X12ML | 288 | 10,376.85 | 10,656 | 279.15 | rounded up | pack>100 (matches name) |
| 65244857 | CLEAR SH COMPLETE SOFT CARE 3C 288X13ML | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 67022557 | SUNSILK SH DAMAGE RCONSTRUCTION 288X13ML | 288 | 427.15 | 576 | 148.85 | rounded up | pack>100 (matches name) |
| 67022565 | SUNSILK SH PERFECT STRAIGHT 288X13ML | 288 | 371.02 | 576 | 204.98 | rounded up | pack>100 (matches name) |
| 67311414 | DOVE BS BAR REGLR FBX 48X135G | 48 | 0.00 | 0 | 0.00 | order 0 |  |
| 67321283 | REXONA MEN MRO MS QUANTUM 24X25ML | 24 | 112.77 | 120 | 7.23 | rounded up |  |
| 67404149 | REXONA MEN RO ICE COOL IN 24X25ML | 24 | 296.37 | 312 | 15.63 | rounded up |  |
| 67404155 | REXONA MEN DL ICE COOL IN 360X3ML | 360 | 8,146.90 | 8,280 | 133.10 | rounded up | pack>100 (matches name) |
| 67469129 | SUNSILK SH SMOOTH&MNGBLE 12X350ML | 12 | 248.12 | 252 | 3.88 | rounded up |  |
| 67633586 | REXONA DLN QUANTUM 360X3ML | 360 | 9,677.92 | 9,720 | 42.08 | rounded up | pack>100 (matches name) |
| 67633590 | REXONA DLN PASSION 360X3ML | 360 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 67633600 | REXONA DLN SHOWER CLEAN 360X3ML | 360 | 5,917.55 | 6,120 | 202.45 | rounded up | pack>100 (matches name) |
| 67655817 | SUNSILK SH STRONG&LONG 24X180ML | 24 | 556.59 | 576 | 19.41 | rounded up |  |
| 67749047 | KNORR SINIGANG NA GABI 12X12X22G | 144 | 10,012.91 | 10,080 | 67.09 | rounded up | pack>100 (matches name); nested A×B |
| 67762749 | SURF HS STD PWDR BLOSSOM FRESH 144X74G | 144 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 67834801 | CLEAR SH COOL SPRT MENTHOL MEN 24X170ML | 24 | 0.00 | 0 | 0.00 | order 0 |  |
| 67834803 | CLEAR SH COMPLETE SOFT CARE 288X13ML | 288 | 5,616.05 | 5,760 | 143.95 | rounded up | pack>100 (matches name) |
| 67940679 | CLOSEUP RED HOT ULP RL 144X(2X10G) | 144 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name); nested A×B |
| 67975949 | KNORR SOUP CHICKEN&CORN 60X60G | 60 | 0.00 | 0 | 0.00 | order 0 |  |
| 68178533 | SURF POWDER TAWAS S 288X57G | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 68178534 | SURF POWDER KALAMANSI S 288X57G | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 68178539 | SURF POWDER KALAMANSI S 12X1100G | 12 | 764.36 | 768 | 3.64 | rounded up |  |
| 68200184 | CLOSEUP RED HOT NEW 12(11+1)X(2X10G) | 12 | 903.10 | 912 | 8.90 | rounded up |  |
| 68212522 | KNORR SNGNG ORIG+ PATIS 24(6+1)X22G | 24 | 1,100.15 | 1,104 | 3.85 | rounded up |  |
| 68394708 | KNORR LIQUID SEASONING ORIGINAL 24X250ML | 24 | 0.00 | 0 | 0.00 | order 0 |  |
| 68395711 | KNORR LIQUID SEASONING ORIGINAL 6X1L | 6 | 202.45 | 204 | 1.55 | rounded up |  |
| 68438404 | KNORR BN CUBES BEEF PANTRY 72X60G | 72 | 1,008.59 | 1,080 | 71.41 | rounded up |  |
| 68438405 | KNORR BN CUBES BEEF SAVERS 36X120G | 36 | 173.54 | 180 | 6.46 | rounded up |  |
| 68438412 | KNORR BN CUBES CHICKEN SAVERS 36X120G | 36 | 271.37 | 288 | 16.63 | rounded up |  |
| 68438416 | KNORR BN CUBES PORK PANTRY 72X60G | 72 | 543.18 | 576 | 32.82 | rounded up |  |
| 68565204 | CREAM SILK HC ULTREBORN STRT 24X180ML | 24 | 0.00 | 0 | 0.00 | order 0 |  |
| 68565205 | CREAM SILK HC ULTREBORN HFALL 24X180ML | 24 | 233.17 | 240 | 6.83 | rounded up |  |
| 68690506 | SUNSILK SH SMTH&MNGBLE (11+1)24X15ML | 24 | 10,794.33 | 10,800 | 5.67 | rounded up |  |
| 68690509 | SUNSILK SH STRONG&LONG (11+1)24X15ML | 24 | 10,546.96 | 10,560 | 13.04 | rounded up |  |
| 68690510 | SUNSILK SH SMTH&MNGBLE 288X15ML | 288 | 5,290.99 | 5,472 | 181.01 | rounded up | pack>100 (matches name) |
| 68690511 | SUNSILK SH STRONG&LONG 288X15ML | 288 | 1,936.34 | 2,016 | 79.66 | rounded up | pack>100 (matches name) |
| 68736096 | AXE DEO RO RLN DARKTEMP 24X40ML | 24 | 180.40 | 192 | 11.60 | rounded up |  |
| 68736102 | AXE DEO RO APOLLO 24X40ML | 24 | 192.13 | 216 | 23.87 | rounded up |  |
| 68763996 | LADY'S CHOICE SS CHICKEN JAR 24X220ML | 24 | 141.73 | 144 | 2.27 | rounded up |  |
| 68764018 | LADY'S CHOICE SS PLAIN 72X80ML | 72 | 611.54 | 648 | 36.46 | rounded up |  |
| 68830455 | KNORR SOUP CRM OF MUSHROOM 60X62G | 60 | 2,612.05 | 2,640 | 27.95 | rounded up |  |
| 68864117 | DOVE BAR REGULAR 48X90G | 48 | 0.00 | 0 | 0.00 | order 0 |  |
| 68864120 | DOVE BAR WHITE TRIPLES MP 16X3X90G | 16 | 0.00 | 0 | 0.00 | order 0 | nested A×B |
| 68864121 | DOVE BAR PINK 48X90G | 48 | 396.67 | 432 | 35.33 | rounded up |  |
| 69642633 | REXONA MEN RO QUANTUM 72H 24X45ML | 24 | 0.00 | 0 | 0.00 | order 0 |  |
| 69668130 | SURF POWDER ANTIBAC L 288X60G | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 69668140 | SURF POWDER CHERRY BLOSSOM L 288X65G | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 69668143 | SURF POWDER CHERRY BLOSSOM L 6X2200G | 6 | 215.62 | 216 | 0.38 | rounded up |  |
| 69668144 | SURF POWDER PURPLE BLOOMS L 12X1100G | 12 | 647.99 | 648 | 0.01 | rounded up |  |
| 69668145 | SURF POWDER PURPLE BLOOMS L 288X65G | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 69668147 | SURF POWDER ROSE FRESH L 144X130G | 144 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 69668148 | SURF POWDER ROSE FRESH L 288X65G | 288 | 8,914.06 | 8,928 | 13.94 | rounded up | pack>100 (matches name) |
| 69668149 | SURF POWDER SUN FRESH L 288X65G | 288 | 0.00 | 0 | 0.00 | order 0 | pack>100 (matches name) |
| 69668150 | SURF POWDER SUN FRESH L 12X1100G | 12 | 507.73 | 516 | 8.27 | rounded up |  |
| 69668151 | SURF POWDER SUN FRESH L 6X2200G | 6 | 142.22 | 144 | 1.78 | rounded up |  |
| 69695559 | LADY'S CHOICE REAL MAYO 6X1KG | 6 | 0.00 | 0 | 0.00 | order 0 |  |
| 69695560 | LADY'S CHOICE RAL MAYO DOY 24X220ML | 24 | 8,491.35 | 8,496 | 4.65 | rounded up |  |
| 69725979 | SURF BAR CHERRY BLOSSOM SXFL 96X120G | 96 | 0.00 | 0 | 0.00 | order 0 |  |
| 69725987 | SURF BAR BLOSSOM FRESH SXFL 96X120G | 96 | 2,411.61 | 2,496 | 84.39 | rounded up |  |
| 69726539 | SURF BAR SUN FRESH SXFL 96X120G | 96 | 0.00 | 0 | 0.00 | order 0 |  |
| 69731876 | SURF BAR BLOSSOM FRESH SXFL 36X360G | 36 | 0.00 | 0 | 0.00 | order 0 |  |
| 69731878 | SURF BAR CHERRY BLOSSOM SXFL 36X360G | 36 | 1,036.77 | 1,044 | 7.23 | rounded up |  |
| 69731886 | SURF BAR SUN FRESH SXFL 36X360G | 36 | 0.00 | 0 | 0.00 | order 0 |  |
| 69767334 | SURF POWDER CHERRY BLOSSM L 40(6+1)65G | 40 | 33,897.91 | 33,920 | 22.09 | rounded up |  |
| 69767335 | SURF POWDER ROSE FRSH L 40(6+1)65G | 40 | 23,929.71 | 23,960 | 30.29 | rounded up |  |
| 69767336 | SURF POWDER SUNFRESH L 40(6+1)65G | 40 | 13,423.19 | 13,440 | 16.81 | rounded up |  |

## d. Do any piece-sold products have a pack size?

Pack 1 exists on 8 master products, none in the plan: 3 Unilever (`SURF POWDER ... 1X7.5KG`, `1X7KG`; correct, the case is one unit) and 5 Del Monte (`KIKKOMAN ... 1/18L`, and four Fit 'n Right items, two of them named `6 Pack` but with pack 1; Del Monte only, not planned). Pack 1 is never rounded (`pack <= 1`).
No planned product is a single-piece item given a case size: every planned product is named as a multi-unit case.

## Unit caveat on record

`quantity_sold` for Unilever is the source's own pieces column, not cases x pack_size (DEC-11); cases x pack_size matches pieces for only 84.1% of rows (ARCHITECTURE.md DEC-11). Rounding is applied in pieces, to the pack from the SOH column. That disagreement is in the sales source, not in the pack size, and is unchanged by this audit.
