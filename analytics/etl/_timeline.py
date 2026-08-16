"""Live/replay event timeline viewer (analytics/etl/events.py's companion).

Generates a self-contained static HTML page - same packaging spirit as
analytics/etl/_review.py (inline CSS/JS, no external calls, no build step)
but structurally different in one key way: _review.py bakes a FINISHED
manifest into the HTML at generation time (pure function of already-done
work); this page ships with NO embedded data at all and fetches
<stage>/_events.jsonl repeatedly at VIEW time instead. That's what makes
the exact same generated file valid whether opened before, during, or
after the run it's watching - live and replay are the same code path,
not two modes.

Not hardcoded to "staging" for the same reason _review.py isn't - a later
Transform stage can reuse this unchanged as long as it writes events via
analytics.etl.events.EventLog to <stage>/_events.jsonl.

Viewing note: opening this file directly (file://) will have its fetch()
of the sibling _events.jsonl blocked by Chrome/Edge's local-file CORS
policy. Serve it instead, e.g. from the stage directory:
    python -m http.server
then open http://localhost:8000/_timeline.html

Usage: python -m analytics.etl._timeline --stage staging
"""
from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def render_timeline(stage: str, repo_root: Path = REPO_ROOT) -> Path:
    stage_dir = repo_root / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    html = HTML_TEMPLATE.replace("__STAGE__", stage)
    out_path = stage_dir / "_timeline.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SSM ETL — __STAGE__ timeline</title>
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0; padding: 20px; background: #f7f7f8; color: #1a1a1a; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .subtitle { color: #666; font-size: 13px; margin-bottom: 16px; }
  .header-strip { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; align-items: center; }
  .stat { background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 8px 12px; font-size: 12px; }
  .stat b { display: block; font-size: 16px; }
  .status-pill { border-radius: 999px; padding: 6px 14px; font-size: 12px; font-weight: 600; }
  .status-waiting { background: #e6e6e6; color: #555; }
  .status-live { background: #d7f0d7; color: #1a6b1a; }
  .status-finished { background: #dbe7ff; color: #1a3f8b; }
  .status-error { background: #ffd7d7; color: #8b1a1a; }
  .warn { color: #a33; font-size: 12px; }
  .timeline { background: #fff; border: 1px solid #ddd; border-radius: 6px; max-height: 75vh; overflow: auto; }
  .row { display: grid; grid-template-columns: 90px 110px 90px 1fr 90px; gap: 8px; padding: 6px 10px; border-bottom: 1px solid #f0f0f0; font-size: 12px; align-items: center; }
  .row:last-child { border-bottom: none; }
  .badge { display: inline-block; border-radius: 4px; padding: 2px 6px; font-size: 11px; font-weight: 600; text-align: center; }
  .badge.run_start, .badge.run_end { background: #1F2937; color: #fff; }
  .badge.family_start, .badge.family_done { background: #ED7D31; color: #fff; }
  .badge.file_start, .badge.file_done { background: #4472C4; color: #fff; }
  .badge.sheet_done { background: #70AD47; color: #fff; }
  .ts { color: #888; }
  .detail { color: #444; }
  .detail .file { color: #1155CC; }
  .counts { text-align: right; color: #666; }
</style>
</head>
<body>
<h1>SSM ETL — __STAGE__ timeline</h1>
<div class="subtitle">Polls __STAGE__/_events.jsonl every 750ms. Same page for a live run or a replay after it's finished.</div>

<div class="header-strip" id="headerStrip"></div>

<div class="timeline" id="timeline"></div>

<script>
const STAGE = "__STAGE__";
const EVENTS_URL = "_events.jsonl";
const POLL_MS = 750;

let cursor = 0;
let pollHandle = null;
let finished = false;
let skippedLines = 0;
let autoScroll = true;

const counts = { family: 0, fileStart: 0, fileDone: 0, sheetDone: 0, rejects: 0 };
let runStartTs = null;
let currentFamily = null;

const timelineEl = document.getElementById("timeline");
const headerEl = document.getElementById("headerStrip");

timelineEl.addEventListener("scroll", () => {
  const atBottom = timelineEl.scrollHeight - timelineEl.scrollTop - timelineEl.clientHeight < 20;
  autoScroll = atBottom;
});

function renderHeader(statusClass, statusText) {
  const elapsed = runStartTs ? ((Date.now() / 1000) - runStartTs).toFixed(1) + "s" : "—";
  const stats = [
    ["Family", currentFamily || "—"],
    ["Files started", counts.fileStart],
    ["Files done", counts.fileDone],
    ["Sheets done", counts.sheetDone],
    ["Rejects", counts.rejects],
    ["Elapsed", elapsed],
  ];
  let html = `<span class="status-pill ${statusClass}">${statusText}</span>`;
  html += stats.map(([label, val]) => `<div class="stat"><b>${val}</b>${label}</div>`).join("");
  if (skippedLines > 0) {
    html += `<span class="warn">${skippedLines} unparsable line(s) skipped</span>`;
  }
  headerEl.innerHTML = html;
}

function appendRow(ev) {
  const row = document.createElement("div");
  row.className = "row";
  const ts = ev.ts ? new Date(ev.ts * 1000).toLocaleTimeString() : "";
  const target = ev.src_sheet ? `${ev.src_file || ""} :: ${ev.src_sheet}` : (ev.src_file || ev.doc_type || "");
  const rowCounts = (ev.rows_in != null || ev.rows_out != null)
    ? `${ev.rows_out ?? "—"}/${ev.rows_in ?? "—"}` : "";
  row.innerHTML =
    `<span class="ts">${ts}</span>` +
    `<span class="badge ${ev.event}">${ev.event}</span>` +
    `<span>${ev.status || ""}</span>` +
    `<span class="detail"><span class="file">${target}</span> ${ev.message ? "— " + ev.message : ""}</span>` +
    `<span class="counts">${rowCounts}</span>`;
  timelineEl.appendChild(row);
}

function applyEvent(ev) {
  if (ev.event === "run_start") { runStartTs = ev.ts; }
  if (ev.event === "family_start") { currentFamily = ev.message || ev.doc_type || "?"; counts.family += 1; }
  if (ev.event === "file_start") { counts.fileStart += 1; }
  if (ev.event === "file_done") { counts.fileDone += 1; counts.rejects += (ev.reject_count || 0); }
  if (ev.event === "sheet_done") { counts.sheetDone += 1; }
  if (ev.event === "run_end") { finished = true; }
  appendRow(ev);
}

async function poll() {
  let text;
  try {
    const resp = await fetch(EVENTS_URL + "?_=" + Date.now(), { cache: "no-store" });
    if (!resp.ok) { renderHeader("status-waiting", "Waiting for run to start…"); return; }
    text = await resp.text();
  } catch (e) {
    renderHeader("status-waiting", "Waiting for run to start…");
    return;
  }

  if (text.length < cursor) {
    // File was replaced/truncated - a fresh run started. Reset and redraw.
    cursor = 0;
    timelineEl.innerHTML = "";
    counts.family = 0; counts.fileStart = 0; counts.fileDone = 0; counts.sheetDone = 0; counts.rejects = 0;
    runStartTs = null; currentFamily = null; finished = false; skippedLines = 0;
  }
  if (text.length <= cursor) {
    renderHeader(finished ? "status-finished" : "status-live", finished ? "Finished — replay" : "Live — in progress");
    return;
  }

  const newText = text.slice(cursor);
  const lines = newText.split("\n");
  // Trailing element is either "" (newText ended with \n, every line
  // complete) or a partial line still being written - leave it unconsumed
  // either way and retry it whole next tick.
  const trailing = lines.pop();
  let consumed = newText.length - trailing.length;

  for (const line of lines) {
    if (!line) continue;
    try {
      const ev = JSON.parse(line);
      applyEvent(ev);
    } catch (e) {
      skippedLines += 1;
    }
  }
  cursor += consumed;

  if (finished && pollHandle !== null) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
  if (autoScroll) { timelineEl.scrollTop = timelineEl.scrollHeight; }

  const anyError = timelineEl.querySelector(".badge.run_end")?.closest(".row")?.textContent.includes("error");
  renderHeader(
    finished ? (anyError ? "status-error" : "status-finished") : "status-live",
    finished ? (anyError ? "Finished — error" : "Finished — replay") : "Live — in progress"
  );
}

renderHeader("status-waiting", "Waiting for run to start…");
pollHandle = setInterval(poll, POLL_MS);
poll();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="staging")
    args = parser.parse_args()
    out_path = render_timeline(args.stage)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
