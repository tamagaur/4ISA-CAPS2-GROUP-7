#!/usr/bin/env bash
# scripts/check.sh - the project's one check command.
#
#   scripts/check.sh --fast   (target < 90 s; run constantly)
#       backend lint, frontend lint, the pinned-figure verification, the Chapter 4 code figures
#       (docs/CHAPTER4_CODE_FIGURES.json: route count and sign-in split, @cached GET routes, opt-in list size), the cross-endpoint invariants
#   scripts/check.sh --full   everything above + the whole pytest suite + its pinned totals + the frontend production build
#
# Skipped is not passed, with ONE exception: the 21 opt-in tests named in scripts/known_opt_in_skips.txt (whole suite only;
# listed as NOT RUN, never as passed; any other skip, or a listed one skipping for a new reason, fails). If a check cannot run (a live database variable is unset, a test skips itself, node
# modules are missing) this script FAILS and says why. It never reports green over a skipped check.
#
# Read-only: the database is only ever read, inside a transaction that is SET TRANSACTION READ ONLY and rolled back.
# Lint scope: backend lint is ruff's correctness rules (syntax errors, undefined names); the 200+ style findings
# that predate this script are not gated, or the gate would be permanently red. Frontend lint is oxlint errors only
# (warnings exist and are not gated). The frontend is Vite + React Router, plain .jsx.
set -u

MODE="${1:-}"
case "$MODE" in --fast|--full) ;; *) echo "usage: scripts/check.sh --fast | --full"; exit 2 ;; esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
else PY="$(command -v python3 || command -v python)"; fi
export PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
NAMES=(); RESULTS=(); TIMES=()
START_ALL=$SECONDS

# step "name" command...   (runs the command, records PASS/FAIL, keeps going so every failure is reported)
step() {
  local name="$1"; shift
  echo; echo "=== $name"
  local t0=$SECONDS
  "$@"; local rc=$?
  NAMES+=("$name"); TIMES+=($((SECONDS - t0)))
  if [ $rc -eq 0 ]; then RESULTS+=("PASS"); else RESULTS+=("FAIL"); echo "--- $name: FAILED (exit $rc)"; fi
}

# pytest wrapper: any skip is a failure, even when pytest itself exits 0
pytest_strict() {
  local label="$1"; shift
  local xml="$TMP/$label.xml"
  "$PY" -m pytest -q -p no:cacheprovider -rs --junitxml="$xml" "$@"; local rc=$?
  [ -f "$xml" ] || { echo "FAIL: pytest wrote no result file"; return 1; }
  # only the whole suite may skip, and only the 21 named in scripts/known_opt_in_skips.txt; every other run allows none
  local allow=""; [ "$label" = "full" ] && allow="--allow-listed"
  "$PY" scripts/check_helpers.py junit "$xml" $allow || rc=1
  return $rc
}

lint_backend()  { "$PY" -m ruff check backend analytics scripts tests --select E9,F63,F7,F82; }
lint_frontend() {
  [ -d frontend/node_modules ] || { echo "FAIL: frontend/node_modules is missing (run: cd frontend && npm ci)"; return 1; }
  (cd frontend && npx --no-install oxlint --quiet)
}
pinned() {
  "$PY" -m scripts.snapshot_published_figures --verify | tee "$TMP/pinned.txt"; local rc=${PIPESTATUS[0]}
  grep -q "not read" "$TMP/pinned.txt" && { echo "FAIL: the live actuals version could not be read, so the check was only partly run"; rc=1; }
  return $rc
}
chapter_static() { "$PY" -m scripts.chapter_figures --verify; }
chapter_totals() { "$PY" -m scripts.chapter_figures --verify-junit "$TMP/invariants.xml" "$TMP/full.xml"; }
invariants()    { pytest_strict invariants tests/invariants; }
full_suite()    { pytest_strict full tests --ignore=tests/invariants; }
frontend_build(){
  [ -d frontend/node_modules ] || { echo "FAIL: frontend/node_modules is missing (run: cd frontend && npm ci)"; return 1; }
  (cd frontend && npm run build)
}

step "live database configured and reachable" "$PY" scripts/check_helpers.py env
step "backend lint (ruff, correctness rules)" lint_backend
step "frontend lint (oxlint, errors)" lint_frontend
step "pinned figures reproduce" pinned
step "Chapter 4 code figures (routes, sign-in split, cached GETs, opt-in list)" chapter_static
step "cross-endpoint invariants (tests/invariants)" invariants
if [ "$MODE" = "--full" ]; then
  step "whole pytest suite (skips fail)" full_suite
  step "Chapter 4 pytest totals (collected, skipped, failed)" chapter_totals
  step "frontend production build" frontend_build
fi

ELAPSED=$((SECONDS - START_ALL))
echo; echo "================ check.sh $MODE"
FAILS=0
for i in "${!NAMES[@]}"; do
  printf '  %-4s %4ss  %s\n' "${RESULTS[$i]}" "${TIMES[$i]}" "${NAMES[$i]}"
  [ "${RESULTS[$i]}" = "PASS" ] || FAILS=$((FAILS + 1))
done
echo "  total ${ELAPSED}s"
if [ "$MODE" = "--fast" ] && [ "$ELAPSED" -gt 90 ]; then echo "  NOTE: over the 90 s target for --fast"; fi
if [ "$FAILS" -gt 0 ]; then echo "RED: $FAILS check(s) failed"; exit 1; fi
echo "GREEN: all checks ran and passed (no unlisted skips; in --full, the 21 opt-in tests in scripts/known_opt_in_skips.txt are NOT RUN wherever their inputs are absent)"
