"""SSM ETL discovery — coverage.html generation.

Reads ONLY profiling/file_inventory.csv (already written to disk) and
renders a single self-contained static HTML coverage matrix. No network,
no build step, no in-memory state from the profiling run — this is a
provable view of the written inventory.

Usage: python profiling/build_coverage.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILING_DIR = REPO_ROOT / "profiling"

DOC_TYPES = [
    "sales_register", "purchase_order", "sales_return", "sell_out",
    "inventory_sign_off", "rmr_gs_bo", "ssis_summary", "unilever_sku",
    "price_list", "unknown",
]

DOC_TYPE_LABELS = {
    "sales_register": "Sales Register", "purchase_order": "Purchases/PO",
    "sales_return": "Sales Return", "sell_out": "Sell Out",
    "inventory_sign_off": "Inventory Sign-Off", "rmr_gs_bo": "RMR GS/BO",
    "ssis_summary": "SSIS Summary", "unilever_sku": "Unilever SKU",
    "price_list": "Price List", "unknown": "Unknown",
}


def month_range(periods: list[str]) -> list[str]:
    valid = sorted(p for p in periods if p)
    if not valid:
        return []
    start_y, start_m = map(int, valid[0].split("-"))
    end_y, end_m = map(int, valid[-1].split("-"))
    months = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def main():
    with open(PROFILING_DIR / "file_inventory.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    periods = [r["period"] for r in rows if r.get("period")]
    months = month_range(periods)

    # cell key: (month, doc_type) -> list of file paths
    cells: dict[tuple, list[str]] = defaultdict(list)
    for r in rows:
        if r.get("real_format") in ("lock-file",):
            continue
        period = r.get("period") or ""
        doc_type = r.get("doc_type") or "unknown"
        if period:
            cells[(period, doc_type)].append(r["path"])

    dup_groups = set(r["duplicate_group"] for r in rows if r.get("duplicate_group"))

    totals_by_principal = defaultdict(int)
    totals_by_doc_type = defaultdict(int)
    totals_by_year = defaultdict(int)
    ambiguous_count = magnolia_count = dup_file_count = 0
    for r in rows:
        totals_by_principal[r.get("principal", "unknown")] += 1
        totals_by_doc_type[r.get("doc_type", "unknown")] += 1
        if r.get("period"):
            totals_by_year[r["period"][:4]] += 1
        if r.get("principal") == "ambiguous":
            ambiguous_count += 1
        if str(r.get("magnolia_flag")).lower() == "true":
            magnolia_count += 1
        if r.get("duplicate_group"):
            dup_file_count += 1

    data = {
        "months": months,
        "docTypes": [{"key": d, "label": DOC_TYPE_LABELS[d]} for d in DOC_TYPES],
        "cells": {f"{m}|{d}": paths for (m, d), paths in cells.items()},
        "rows": [
            {
                "path": r["path"], "principal": r.get("principal", ""),
                "regions": r.get("regions", ""), "period": r.get("period", ""),
                "docType": r.get("doc_type", ""), "duplicateGroup": r.get("duplicate_group", ""),
                "magnolia": str(r.get("magnolia_flag")).lower() == "true",
            }
            for r in rows
        ],
        "totals": {
            "byPrincipal": dict(totals_by_principal),
            "byDocType": dict(totals_by_doc_type),
            "byYear": dict(totals_by_year),
            "ambiguous": ambiguous_count,
            "magnolia": magnolia_count,
            "duplicateFiles": dup_file_count,
            "duplicateGroups": len(dup_groups),
            "totalFiles": len(rows),
        },
    }

    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    out_path = PROFILING_DIR / "coverage.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(months)} months x {len(DOC_TYPES)} doc types, "
          f"{len(rows)} files in inventory)")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SSM ETL Discovery — Data Coverage</title>
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0; padding: 20px; background: #f7f7f8; color: #1a1a1a; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .subtitle { color: #666; font-size: 13px; margin-bottom: 16px; }
  .header-strip { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
  .stat { background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 8px 12px; font-size: 12px; }
  .stat b { display: block; font-size: 16px; }
  .filters { display: flex; gap: 16px; margin-bottom: 12px; font-size: 13px; flex-wrap: wrap; }
  .filters label { margin-right: 8px; }
  table { border-collapse: collapse; font-size: 12px; background: #fff; }
  th, td { border: 1px solid #e0e0e0; padding: 4px 6px; text-align: center; white-space: nowrap; }
  th { background: #eee; position: sticky; top: 0; }
  td.month-label, th.month-label { position: sticky; left: 0; background: #eee; text-align: left; font-weight: 600; }
  .present { background: #d7f0d7; cursor: pointer; }
  .missing { background: #f4f4f4; color: #bbb; }
  .duplicate { background: #ffe3b0; cursor: pointer; }
  .table-wrap { max-height: 75vh; overflow: auto; border: 1px solid #ddd; }
  #detail { margin-top: 12px; font-size: 12px; background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 10px; display: none; }
  #detail.open { display: block; }
  #detail ul { margin: 6px 0 0; padding-left: 18px; }
</style>
</head>
<body>
<h1>SSM ETL Discovery — Data Coverage Matrix</h1>
<div class="subtitle">Generated purely from profiling/file_inventory.csv. Rendered offline, no external calls.</div>

<div class="header-strip" id="headerStrip"></div>

<div class="filters">
  <span>Principal:
    <label><input type="checkbox" class="f-principal" value="unilever" checked> Unilever</label>
    <label><input type="checkbox" class="f-principal" value="delmonte" checked> Del Monte</label>
    <label><input type="checkbox" class="f-principal" value="ambiguous" checked> Ambiguous</label>
  </span>
  <span>Region:
    <label><input type="checkbox" class="f-region" value="pangasinan" checked> Pangasinan</label>
    <label><input type="checkbox" class="f-region" value="ilocos" checked> Ilocos</label>
    <label><input type="checkbox" class="f-region" value="la_union" checked> La Union</label>
    <label><input type="checkbox" class="f-region" value="unknown" checked> Unknown</label>
  </span>
</div>

<div class="table-wrap"><table id="matrix"></table></div>
<div id="detail"></div>

<script>
const DATA = __DATA_JSON__;

function principalOf(row) { return row.principal; }
function regionsOf(row) { return (row.regions || "unknown").split(";"); }

function activeFilters() {
  const principals = Array.from(document.querySelectorAll(".f-principal:checked")).map(x => x.value);
  const regions = Array.from(document.querySelectorAll(".f-region:checked")).map(x => x.value);
  return { principals, regions };
}

function rowMatchesFilters(row, filters) {
  if (!filters.principals.includes(row.principal)) return false;
  const regs = regionsOf(row);
  return regs.some(r => filters.regions.includes(r));
}

function renderHeaderStrip() {
  const t = DATA.totals;
  const el = document.getElementById("headerStrip");
  const stats = [
    ["Total files", t.totalFiles],
    ["Unilever", t.byPrincipal.unilever || 0],
    ["Del Monte", t.byPrincipal.delmonte || 0],
    ["Ambiguous principal", t.ambiguous],
    ["Magnolia-flagged", t.magnolia],
    ["Duplicate-group files", t.duplicateFiles + " (" + t.duplicateGroups + " groups)"],
  ];
  el.innerHTML = stats.map(([label, val]) =>
    `<div class="stat"><b>${val}</b>${label}</div>`).join("");
}

function renderMatrix() {
  const filters = activeFilters();
  const byPathRow = {};
  DATA.rows.forEach(r => byPathRow[r.path] = r);

  const table = document.getElementById("matrix");
  let thead = "<tr><th class='month-label'>Month</th>" +
    DATA.docTypes.map(d => `<th>${d.label}</th>`).join("") + "</tr>";

  let tbody = "";
  DATA.months.forEach(month => {
    tbody += `<tr><td class="month-label">${month}</td>`;
    DATA.docTypes.forEach(dt => {
      const key = month + "|" + dt.key;
      const allPaths = DATA.cells[key] || [];
      const paths = allPaths.filter(p => {
        const row = byPathRow[p];
        return row && rowMatchesFilters(row, filters);
      });
      if (paths.length === 0) {
        tbody += `<td class="missing">–</td>`;
      } else {
        const isDup = paths.some(p => byPathRow[p] && byPathRow[p].duplicateGroup);
        const cls = isDup ? "duplicate" : "present";
        const encoded = encodeURIComponent(JSON.stringify(paths));
        tbody += `<td class="${cls}" onclick="showDetail('${month}','${dt.label}','${encoded}')">${paths.length}</td>`;
      }
    });
    tbody += "</tr>";
  });
  table.innerHTML = thead + tbody;
}

function showDetail(month, docLabel, encodedPaths) {
  const paths = JSON.parse(decodeURIComponent(encodedPaths));
  const el = document.getElementById("detail");
  el.classList.add("open");
  el.innerHTML = `<b>${docLabel} — ${month}</b> (${paths.length} file(s))<ul>` +
    paths.map(p => `<li>${p}</li>`).join("") + "</ul>";
}

document.querySelectorAll(".f-principal, .f-region").forEach(el =>
  el.addEventListener("change", renderMatrix));

renderHeaderStrip();
renderMatrix();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
