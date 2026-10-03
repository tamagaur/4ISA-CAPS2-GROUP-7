"""
Chart 8 - add the boundary-result sentence to the STORED result, without an LP run
(Yuan, 2026-09-30: keep the FLAWED verdict as computed; no new LP runs).

Reads reports/evidence/ch08.json and ch08_totals.csv as written by lp_charts.py at
d3dc662. The exact 105% cover (2.999999993) is not in the CSV - it stores floats to
6 significant figures - so it is read from the result's own verdict_detail, which
lp_charts.py wrote from the same in-memory value at run time, and cross-checked: the
peso gap printed there (6 decimals) must match the CSV's cover_gap_php within 5e-7,
and the verdict re-derived from the stored totals with the pre-registered rule must
equal the stored one. Only caption and data_notes change; the CSVs, checks, verdict
and the LP run's code commit are kept, and the restamp is recorded beside them.
"""
import _common as C
import json
import os
import re

import pandas as pd

from lp_charts import RUN_LP_TOLERANCE_PHP, boundary_note


def main():
    path = os.path.join(C.EVID, "ch08.json")
    with open(path, encoding="utf-8") as fh:
        meta = json.load(fh)
    A = pd.read_csv(os.path.join(C.EVID, "ch08_totals.csv")).set_index("allocation_pct")
    m = re.search(r"105%: month-end cover ([0-9.]+) weeks vs target ([0-9.]+) .*?PHP ([-+0-9.]+) against", meta["verdict_detail"])
    if not m:
        C.fail("restamp", "ch08.json verdict_detail does not carry the 105% cover and gap")
    cover, target, gap = float(m.group(1)), float(m.group(2)), float(m.group(3))
    if abs(gap - A.loc[105, "cover_gap_php"]) > 5e-7:          # detail prints 6 decimals; CSV holds 6 s.f.
        C.fail("restamp", f"gap in verdict_detail {gap} != ch08_totals.csv {A.loc[105, 'cover_gap_php']}")
    low_cover = cover < target
    cleared = A.loc[105, "n_short"] > 0 and A.loc[108, "n_short"] == 0
    verdict = "FLAWED" if (low_cover or cleared) else "CONFIRMS"
    if verdict != meta["verdict"]:
        C.fail("restamp", f"re-derived verdict {verdict} != stored {meta['verdict']}")
    if not (low_cover and -gap < RUN_LP_TOLERANCE_PHP):
        C.fail("restamp", "105% is not a boundary result; nothing to add")
    bn = boundary_note(cover, gap)
    if bn not in meta["caption"]:
        meta["caption"] = meta["caption"] + " " + bn
    if bn not in meta["data_notes"]:
        meta["data_notes"] = meta["data_notes"] + [bn]
    meta["caption_restamped_by"] = f"scripts/evidence/ch08_restamp.py @ {C.git_sha(['scripts/evidence/ch08_restamp.py', 'scripts/evidence/lp_charts.py', 'scripts/evidence/_common.py'])}"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1, allow_nan=False)
        fh.write("\n")
    print(f"ch08 {meta['verdict']} (unchanged): {bn}")
    for pct in (103, 105, 108):
        r = A.loc[pct]
        print(f"  {pct}%: month-end cover {r.month_end_cover_weeks:g} wk (CSV, 6 s.f.), gap PHP {r.cover_gap_php:+g}, "
              f"shortfall {r.shortfall:,.2f} pieces on {int(r.n_short)} SKUs, run_lp says met: {r.run_lp_says_met}")


if __name__ == "__main__":
    main()
