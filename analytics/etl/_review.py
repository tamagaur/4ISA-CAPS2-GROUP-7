"""Stage-parameterized review viewer (SSM_EXTRACT_FIX_AND_REVIEW_PROMPT.md
Part B).

Reads ONLY <repo_root>/<stage>/_manifest.json (already written to disk) and
renders a single self-contained static HTML page — same spirit as
profiling/coverage.html: offline, inline CSS/JS, no external calls,
generated purely from real output. Not hardcoded to "staging" so a later
transform/ (or other) stage can reuse this unchanged, as long as it writes
the same manifest shape: {"staged": [...], "reject": [...]}.

Usage: python -m analytics.etl._review --stage staging
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def render_review(stage: str, repo_root: Path = REPO_ROOT) -> Path:
    stage_dir = repo_root / stage
    manifest_path = stage_dir / "_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    staged = manifest.get("staged", [])
    rejects = manifest.get("reject", [])

    checksum_counts = {"pass": 0, "mismatch": 0, "unverified": 0}
    for r in staged:
        checksum_counts[r.get("checksum_status") or "unverified"] += 1

    data = {
        "stage": stage,
        "staged": staged,
        "reject": rejects,
        "summary": {
            "files": len(set(r["src_file"] for r in staged)),
            "sheetsStaged": len(staged),
            "totalRows": sum(r.get("row_count", 0) for r in staged),
            "checksum": checksum_counts,
            "rejects": len(rejects),
        },
    }

    html = HTML_TEMPLATE.replace("__STAGE__", stage).replace(
        "__DATA_JSON__", json.dumps(data, ensure_ascii=False)
    )
    out_path = stage_dir / "_review.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SSM ETL — __STAGE__ review</title>
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0; padding: 20px; background: #f7f7f8; color: #1a1a1a; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .subtitle { color: #666; font-size: 13px; margin-bottom: 16px; }
  .header-strip { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
  .stat { background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 8px 12px; font-size: 12px; }
  .stat b { display: block; font-size: 16px; }
  .filters { display: flex; gap: 16px; margin-bottom: 12px; font-size: 12px; flex-wrap: wrap; }
  .filter-group { background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 6px 10px; }
  .filter-group b { display: block; font-size: 11px; text-transform: uppercase; color: #888; margin-bottom: 4px; }
  .filter-group label { margin-right: 8px; white-space: nowrap; }
  table { border-collapse: collapse; font-size: 12px; background: #fff; width: 100%; }
  th, td { border: 1px solid #e0e0e0; padding: 4px 6px; text-align: left; }
  th { background: #eee; position: sticky; top: 0; cursor: default; }
  tr.data-row { cursor: pointer; }
  tr.data-row:hover { background: #f0f6ff; }
  .checksum { font-weight: 600; text-align: center; }
  .checksum.pass { background: #d7f0d7; }
  .checksum.mismatch { background: #ffe3b0; }
  .checksum.unverified { background: #e6e6e6; color: #777; }
  .table-wrap { max-height: 65vh; overflow: auto; border: 1px solid #ddd; margin-bottom: 20px; }
  tr.detail-row td { background: #fafafa; font-size: 11px; color: #444; }
  .reject-reason { color: #a33; }
</style>
</head>
<body>
<h1>SSM ETL — __STAGE__ review</h1>
<div class="subtitle">Generated purely from __STAGE__/_manifest.json. Rendered offline, no external calls.</div>

<div class="header-strip" id="headerStrip"></div>
<div class="filters" id="filters"></div>

<div class="table-wrap"><table id="stagedTable"></table></div>

<h2 style="font-size:15px;">Rejects</h2>
<div class="table-wrap"><table id="rejectTable"></table></div>

<script>
const DATA = __DATA_JSON__;

function uniqueSorted(arr) { return Array.from(new Set(arr)).sort(); }

function renderHeaderStrip() {
  const s = DATA.summary;
  const el = document.getElementById("headerStrip");
  const stats = [
    ["Files", s.files],
    ["Sheets staged", s.sheetsStaged],
    ["Total rows", s.totalRows],
    ["Checksum pass", s.checksum.pass],
    ["Checksum mismatch", s.checksum.mismatch],
    ["Checksum unverified", s.checksum.unverified],
    ["Rejects", s.rejects],
  ];
  el.innerHTML = stats.map(([label, val]) => `<div class="stat"><b>${val}</b>${label}</div>`).join("");
}

const FILTER_FIELDS = [
  ["principal", "Principal"],
  ["region", "Region"],
  ["doc_type", "Doc type"],
];

function renderFilters() {
  const el = document.getElementById("filters");
  let html = "";
  FILTER_FIELDS.forEach(([field, label]) => {
    const values = uniqueSorted(DATA.staged.map(r => r[field]));
    html += `<div class="filter-group"><b>${label}</b>` +
      values.map(v => `<label><input type="checkbox" class="f-${field}" value="${v}" checked> ${v}</label>`).join("") +
      "</div>";
  });
  html += `<div class="filter-group"><b>Checksum</b>` +
    ["pass", "mismatch", "unverified"].map(v =>
      `<label><input type="checkbox" class="f-checksum" value="${v}" checked> ${v}</label>`).join("") +
    "</div>";
  el.innerHTML = html;
  el.querySelectorAll("input").forEach(cb => cb.addEventListener("change", renderStagedTable));
}

function activeValues(cls) {
  return Array.from(document.querySelectorAll("." + cls + ":checked")).map(x => x.value);
}

function rowMatches(r, filters) {
  if (!filters.principal.includes(String(r.principal))) return false;
  if (!filters.region.includes(String(r.region))) return false;
  if (!filters.doc_type.includes(String(r.doc_type))) return false;
  if (!filters.checksum.includes(String(r.checksum_status || "unverified"))) return false;
  return true;
}

let expandedRow = null;

function renderStagedTable() {
  const filters = {
    principal: activeValues("f-principal"),
    region: activeValues("f-region"),
    doc_type: activeValues("f-doc_type"),
    checksum: activeValues("f-checksum"),
  };
  const rows = DATA.staged.filter(r => rowMatches(r, filters));

  const table = document.getElementById("stagedTable");
  let html = "<tr><th>src_file</th><th>src_sheet</th><th>principal</th><th>region</th>" +
    "<th>period</th><th>doc_type</th><th>sheet_role</th><th>grain</th><th>rows</th><th>checksum</th></tr>";

  rows.forEach((r, i) => {
    const status = r.checksum_status || "unverified";
    let checksumCell = status;
    if (status === "mismatch" || status === "pass") {
      checksumCell = `${status} (${r.checksum_column}: expected ${r.checksum_expected}, got ${r.checksum_got}, diff ${r.checksum_diff})`;
    } else if (r.checksum_column) {
      checksumCell = `unverified (no comparable totals row for ${r.checksum_column})`;
    }
    html += `<tr class="data-row" data-idx="${i}"><td>${r.src_file}</td><td>${r.src_sheet}</td>` +
      `<td>${r.principal}</td><td>${r.region}</td><td>${r.period}</td><td>${r.doc_type}</td>` +
      `<td>${r.sheet_role}</td><td>${r.grain}</td><td>${r.row_count}</td>` +
      `<td class="checksum ${status}">${checksumCell}</td></tr>`;
  });
  table.innerHTML = html;

  table.querySelectorAll("tr.data-row").forEach(tr => {
    tr.addEventListener("click", () => {
      const idx = Number(tr.getAttribute("data-idx"));
      const existing = tr.nextElementSibling;
      if (existing && existing.classList.contains("detail-row")) {
        existing.remove();
        return;
      }
      table.querySelectorAll("tr.detail-row").forEach(d => d.remove());
      const r = rows[idx];
      const detail = document.createElement("tr");
      detail.className = "detail-row";
      detail.innerHTML = `<td colspan="10">Raw columns: ${r.columns.join(", ")}</td>`;
      tr.after(detail);
    });
  });
}

function renderRejectTable() {
  const table = document.getElementById("rejectTable");
  let html = "<tr><th>src_file</th><th>src_sheet</th><th>reason</th></tr>";
  DATA.reject.forEach(r => {
    html += `<tr><td>${r.src_file}</td><td>${r.src_sheet || "(whole file)"}</td>` +
      `<td class="reject-reason">${r.reason}</td></tr>`;
  });
  table.innerHTML = html;
}

renderHeaderStrip();
renderFilters();
renderStagedTable();
renderRejectTable();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="staging")
    args = parser.parse_args()
    out_path = render_review(args.stage)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
