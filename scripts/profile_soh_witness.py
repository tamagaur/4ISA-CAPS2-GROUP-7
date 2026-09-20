"""Read-only profile of the unloaded 2021-22 SSIS SOH sheets (existence witness).

Reuses the ssis_soh extractor's helpers; does NOT call parse_ssis_soh()
(MIN_PERIOD="2023-01" skips these files and R7 raises on the pre-2023
"MOVING AVERAGE PRICE(CS)" column). Period = file period (D1). No DB access.

    python scripts/profile_soh_witness.py [--out data/processed/soh_witness_2021_2022.parquet]
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from profiling.detect import detect_header, is_blank, trim_grid  # noqa: E402
from profiling.profile_files import infer_period  # noqa: E402
from profiling.reader import read_workbook  # noqa: E402
from analytics.etl._coerce import to_number  # noqa: E402
from analytics.etl.extract._shared import _force_text  # noqa: E402
from analytics.etl.extract.ssis_soh import SOH_SHEET_RE, combine_total_units, parse_cs_pc  # noqa: E402

YEARS = ("2021", "2022")


def profile(raw_dir: Path) -> tuple[pd.DataFrame, list[dict]]:
    rows, log = [], []
    for year in YEARS:
        for f in sorted((raw_dir / "SSIS" / year).glob("*.xlsx")):
            period = infer_period(f)
            wb = read_workbook(f, full_read=True)
            matches = [s for s in wb.sheets if SOH_SHEET_RE.search(s.name)]
            entry = {"file": f.name, "period": period, "soh_sheets": len(matches), "rows": 0, "unparseable_qty": 0}
            log.append(entry)
            if period is None or not matches:
                continue
            sheet = matches[0]
            entry["sheet"] = sheet.name
            trimmed = trim_grid(sheet.rows)
            hd = detect_header(trimmed)
            if hd.header_row_index < 0:
                entry["error"] = "no detectable header"
                continue
            labels = [str(h).strip() if not is_blank(h) else f"__col{i}__"
                      for i, h in enumerate(trimmed[hd.header_row_index])]
            idx = {h: i for i, h in enumerate(labels)}
            i_sku, i_qty, i_ps = idx.get("Article No"), idx.get("Stock Quantity (CS/PC)"), idx.get("PACK SIZE")
            if i_sku is None or i_qty is None:
                entry["error"] = f"missing column(s); labels={labels[:8]}"
                continue
            for r in trimmed[hd.header_row_index + 1:]:
                v = r[i_sku] if i_sku < len(r) else None
                if is_blank(v):
                    continue
                q = r[i_qty] if i_qty < len(r) else None
                ps = to_number(r[i_ps]) if i_ps is not None and i_ps < len(r) and not is_blank(r[i_ps]) else None
                try:
                    c, p = parse_cs_pc(q)
                    stock = combine_total_units(c, p, ps)
                    cases, pieces = c, p
                except ValueError:
                    entry["unparseable_qty"] += 1
                    stock = cases = pieces = None
                rows.append({"sku": _force_text(v), "period": period, "stock": stock,
                             "stock_cases": cases, "stock_pieces": pieces, "src_file": f.name})
                entry["rows"] += 1
    return pd.DataFrame(rows), log


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "processed" / "soh_witness_2021_2022.parquet"))
    args = ap.parse_args()
    df, log = profile(REPO_ROOT / "data" / "raw")
    for e in log:
        print(e)
    # one row per (sku, period): duplicate files for a period collapse to max stock
    out = (df.groupby(["sku", "period"], as_index=False)
             .agg(stock=("stock", "max"), stock_cases=("stock_cases", "max"), stock_pieces=("stock_pieces", "max")))
    print(f"files={len(log)} periods={df['period'].nunique()} articles={df['sku'].nunique()} "
          f"raw_rows={len(df)} out_rows={len(out)} null_stock={int(out['stock'].isna().sum())} "
          f"zero_stock={int((out['stock'] == 0).sum())}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
