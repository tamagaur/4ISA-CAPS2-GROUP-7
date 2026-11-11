"""
scripts/evidence/_common.py - shared by every Evidence chart script.

Import this FIRST in each script: it pins the maths libraries to one thread
before numpy loads (at most 4 worker processes run at once, each single-threaded).

What lives here, and where it came from:
  - BLOCKS, cells(), compare(): verbatim from
    reports/experiment_artifacts/scripts/candidate_followup_2026-09-22/cells_all.py:9-31
    (the WAPE two-condition test: 95% bootstrap interval on the median difference
    excludes 0 AND more SKUs improve than worsen; 1,000 resamples, seed 20260921).
  - read_only(): BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK. Never
    set_session(readonly=True) - that leaks through the :6543 pooler.
  - write_result(): the chart's CSV plus reports/evidence/chNN.json (caption, verdict,
    criterion). Captions are f-strings over computed values; no number is typed in.

The database URL is read from the shared checkout's .env into this process only
(dotenv_values; never copied, never printed). Override with DSD_ENV_FILE.
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"

import contextlib
import datetime
import json
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
EVID = os.path.join(REPO, "reports", "evidence")
INPUTS = os.path.join(EVID, "inputs")
SHARED_ENV = os.environ.get("DSD_ENV_FILE", r"C:\Users\kyuan\Capstone-Project\.env")
MAX_WORKERS = 4
sys.path.insert(0, REPO)

# ---- verbatim: cells_all.py:2,9-31 ------------------------------------------
SEED, NBOOT, MIN_ORIG, MIN_N = 20260921, 1000, 3, 5
BLOCKS = [("2023-10", "2024-02"), ("2024-03", "2024-08"), ("2024-09", "2025-02"), ("2025-03", "2025-08"), ("2025-09", "2026-02")]
FULL = ("2023-10", "2026-02")


def cells(df, models):  # verbatim logic of build_experiment_log.cells, plus scaled signed error
    out = []
    for pk, grp in df.groupby("pk"):
        a = grp.actual.to_numpy(); den = np.abs(a).sum()
        if len(grp) < MIN_ORIG or den <= 0: continue
        r = dict(pk=pk); sc = grp.scale.to_numpy(); ok = sc > 0
        for m in models:
            p = grp[m].to_numpy(); fin = np.isfinite(p).all()
            r[m] = np.abs(a - p).sum() / den if fin else np.nan
            r["mase_" + m] = float(np.mean(np.abs(a - p)[ok] / sc[ok])) if fin and ok.any() else np.nan
            r["bias_" + m] = float(np.mean((p - a)[ok] / sc[ok])) if fin and ok.any() else np.nan
        out.append(r)
    return pd.DataFrame(out)


def compare(m, b):  # build_experiment_log.compare + two-condition verdict
    m, b = np.asarray(m, float), np.asarray(b, float); ok = np.isfinite(m) & np.isfinite(b); m, b = m[ok], b[ok]
    if len(m) < MIN_N: return dict(n=len(m), v="NT")
    i = np.random.default_rng(SEED).integers(0, len(m), (NBOOT, len(m)))
    d = np.median(m[i], axis=1) - np.median(b[i], axis=1); lo, hi = np.percentile(d, [2.5, 97.5])
    nb, nw = int((m < b - 1e-12).sum()), int((m > b + 1e-12).sum())
    v = "W" if (hi < 0 and nb > nw) else "L" if (lo > 0 and nw > nb) else "T"
    return dict(n=len(m), lo=lo, hi=hi, nb=nb, nw=nw, v=v, mv=np.median(m), bv=np.median(b))
# ---- end verbatim -----------------------------------------------------------

# The one NULL quantity in the Tier A 2026-02 series, accepted by Yuan 2026-09-30.
# Counted as 0, as the bake-off did (final_fit.py skips a non-finite quantity; the
# stored artifact has actual = 0.0 for this SKU-month). Any OTHER NULL stops the run.
KNOWN_NULLS = {(150, "2025-12")}
KNOWN_NULL_NOTE = ("Data note: product_key 150 / SKU 64861486, 2025-12 has a NULL quantity in "
                   "Unilever_SKU_Demand_Fact_Real (net PHP 2.89, La Union source); it is counted as 0, "
                   "the same treatment as the bake-off.")


# For session 5f (logged, not acted on here): the served global model fits with
# nthread=1 (analytics/forecasting/global_model.py:38); the stored bake-off
# forecasts (xgb_abs@A, ens_xgb_ma3@A) were fitted with nthread=8
# (reports/experiment_artifacts/scripts/final_models.py:81).
THREAD_NOTE = ("Note for session 5f: the served XGBoost model fits with nthread=1 (analytics/forecasting/global_model.py:38); "
               "the stored bake-off XGBoost forecasts shown here were fitted with nthread=8 "
               "(reports/experiment_artifacts/scripts/final_models.py:81).")


def null_notes(pks_used) -> list:
    """The data note, if this chart used SKU 150's series."""
    return [KNOWN_NULL_NOTE] if any(pk in {k for k, _ in KNOWN_NULLS} for pk in set(int(p) for p in pks_used)) else []


MASE_GATE_PIPELINE = 1.0   # analytics/forecasting/baseline.py:55, scripts/run_lp.py:113
MASE_GATE_FIT_REVIEW = 1.1  # reports/diagnostics/UNFIT_SKU_LIST.md (fit review); NOT changed here - logged for 5f


def in_window(df, lo, hi):
    return df[(df.month >= lo) & (df.month <= hi)]


def block_table(df, model, base, label_cols=None):
    """Two-condition test of `model` vs `base` in each block and over the full window.
    One row per window: n, median WAPE of each, interval, n_better, n_worse, verdict,
    and the model's MASE < 1 share (pipeline gate) on the same SKUs."""
    rows = []
    for lo, hi in [FULL] + BLOCKS:
        c = cells(in_window(df, lo, hi), [model, base])
        r = compare(c[model], c[base]) if len(c) else dict(n=0, v="NT")
        mm = c["mase_" + model] if len(c) else pd.Series(dtype=float)
        mm = mm[np.isfinite(mm)]
        rows.append(dict(window="full" if (lo, hi) == FULL else f"{lo}..{hi}", start=lo, end=hi, model=model, baseline=base,
                         n=r["n"], model_wape=r.get("mv"), base_wape=r.get("bv"), ci_lo=r.get("lo"), ci_hi=r.get("hi"),
                         n_better=r.get("nb"), n_worse=r.get("nw"), verdict=r["v"],
                         mase_pass_pct=100 * float((mm < MASE_GATE_PIPELINE).mean()) if len(mm) else np.nan,
                         **(label_cols or {})))
    return pd.DataFrame(rows)


def majority(verdicts, letter):
    """True if `letter` holds in a strict majority of the TESTABLE blocks (NT excluded)."""
    t = [v for v in verdicts if v != "NT"]
    return len(t) > 0 and sum(v == letter for v in t) * 2 > len(t), f"{sum(v == letter for v in t)} of {len(t)} testable"


# ---- database: read-only transaction ----------------------------------------
def _env():
    from dotenv import dotenv_values
    return dotenv_values(SHARED_ENV) if os.path.isfile(SHARED_ENV) else {}


def export_env_to_process():
    """For subprocesses that call load_dotenv() themselves (run_lp.py, build.py):
    put the URLs in os.environ (never printed)."""
    for k, v in _env().items():
        if k.startswith("SUPABASE") and v and k not in os.environ:
            os.environ[k] = v


@contextlib.contextmanager
def read_only():
    import psycopg2
    from analytics.config import long_read_db_url
    _env()
    # One URL, no fall-through: until 2026-11-11 this tried SUPABASE_DIRECT_URL first and the other on failure, so a
    # process told SUPABASE_DB_URL=<a local copy> read live (.env's direct URL).
    url = long_read_db_url()
    var = "SUPABASE_DIRECT_URL" if url != os.environ.get("SUPABASE_DB_URL") else "SUPABASE_DB_URL"   # yielded: which route
    try:
        conn = psycopg2.connect(url, connect_timeout=20)
    except Exception as exc:  # message class only, never the DSN
        raise SystemExit(f"no database connection: {type(exc).__name__}")
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")      # first statement of the implicit BEGIN
        cur.execute("SHOW transaction_read_only")
        assert cur.fetchone()[0] == "on", "transaction is not read-only"
        yield cur, var
    finally:
        conn.rollback()
        conn.close()


# ---- outputs ----------------------------------------------------------------
def git_sha(paths=()):
    """HEAD, plus ' +uncommitted' if any of `paths` differs from HEAD (so the record
    never claims code that was not in that commit)."""
    try:
        sha = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", REPO, "status", "--porcelain", "--", *paths], capture_output=True, text=True).stdout.strip()
        return sha + (" +uncommitted" if dirty else "")
    except Exception:
        return "unknown"


def prereg(chart: int) -> dict:
    p = pd.read_csv(os.path.join(EVID, "PREREGISTERED.csv"))
    return p[p.chart == chart].iloc[0].to_dict()


def write_result(chart: int, slug: str, title: str, frames: dict, caption: str, verdict: str, verdict_detail: str,
                 checks: list, script: str, extra: dict | None = None):
    """frames: {suffix: DataFrame} -> reports/evidence/chNN_<suffix>.csv. Writes chNN.json."""
    os.makedirs(EVID, exist_ok=True)
    files = {}
    for suffix, df in frames.items():
        name = f"ch{chart:02d}_{suffix}.csv"
        df.to_csv(os.path.join(EVID, name), index=False, float_format="%.6g", lineterminator="\n")
        files[suffix] = f"reports/evidence/{name}"
    pr = prereg(chart)
    meta = dict(chart=chart, slug=slug, title=title, files=files, caption=caption, verdict=verdict,
                verdict_detail=verdict_detail, criterion=pr["flawed_if"], otherwise=pr["otherwise"],
                mase_gate_used=pr["mase_gate_used"], rerun_after_5f=pr["rerun_after_5f"], checks=checks,
                script=f"scripts/evidence/{script}",
                code_commit=git_sha([f"scripts/evidence/{script}", "scripts/evidence/_common.py"]),
                computed_at=datetime.datetime.now().isoformat(timespec="seconds"), **(extra or {}))
    with open(os.path.join(EVID, f"ch{chart:02d}.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1, allow_nan=False, default=_json_default)
        fh.write("\n")
    print(f"ch{chart:02d} {verdict}: {verdict_detail}")
    for c in checks:
        print(f"  check {c['id']}: {'PASS' if c['pass'] else 'FAIL'} - {c['detail']}")


def _json_default(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)): return bool(o)
    return str(o)


def fail(check_id: str, detail: str):
    """A pre-registered check failed: stop the build (the caller reports only this)."""
    raise SystemExit(f"CHECK {check_id} FAILED: {detail}")


def load_preds():
    """The cited bake-off artifact, parsed exactly (round_trip) as the transforms
    experiment's identity control read it."""
    A = pd.read_csv(os.path.join(REPO, "reports", "experiment_artifacts", "candidate_search_tierA_preds.csv.gz"),
                    float_precision="round_trip")
    A["month"] = A.month.astype(str).str[:7]
    return A


def load_series():
    """reports/evidence/inputs/unilever_tierA_2026-02_series.csv -> {pk: (x_from_first_sale, fs)} on 2023-01..2026-02,
    exactly as final_fit.py builds it (missing months = 0)."""
    d = pd.read_csv(os.path.join(INPUTS, "unilever_tierA_2026-02_series.csv"), float_precision="round_trip")
    periods = [str(p) for p in pd.period_range("2023-01", "2026-02", freq="M")]
    ix = {p: i for i, p in enumerate(periods)}
    mats = {int(pk): np.zeros(len(periods)) for pk in d.pk.unique()}
    for r in d.itertuples(index=False):
        i = ix.get(r.month)
        if i is not None and np.isfinite(r.q):
            mats[int(r.pk)][i] += r.q
    return mats, periods, ix
