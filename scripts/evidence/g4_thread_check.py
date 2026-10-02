"""
G4 diagnostic, run once (approved exception to the one-thread rule, 2026-09-30):
does the chart-2 harness reproduce the stored xgb_abs@A exactly when it uses the
bake-off's own nthread=8 (final_models.py:81)? Two forecast months only, the first
and last with a stored XGBoost value: two fits, one process.

Exact match here means the nthread=1 gap is thread-count divergence, not a
harness difference. Writes reports/evidence/g4_thread_check.json.
"""
import _common as C
import json
import os

os.environ["OMP_NUM_THREADS"] = "8"      # this one process only; set before xgboost loads

import numpy as np  # noqa: E402

import ch02_truncation as T2  # noqa: E402


def main():
    A = C.load_preds()
    mats, periods, ix = C.load_series()
    series = {pk: (mats[pk][int(np.nonzero(mats[pk] > 0)[0][0]):], int(np.nonzero(mats[pk] > 0)[0][0]))
              for pk in sorted(mats) if (mats[pk] > 0).any()}
    st = A[np.isfinite(A["xgb_abs@A"])]
    months = [int(st.ti.min()), int(st.ti.max())]
    st = st[st.ti.isin(months)]
    out = {}
    for nt in (8, 1):
        T2.XGB_A["nthread"] = nt
        _, got = T2.xgb_for((series, None, months, list(zip(st.pk.astype(int), st.ti.astype(int)))))
        v = np.array([got.get((int(p), int(t)), np.nan) for p, t in zip(st.pk, st.ti)])
        ref = st["xgb_abs@A"].to_numpy()
        out[f"nthread_{nt}"] = dict(rows=len(ref), exact=int((v == ref).sum()), max_abs_diff=float(np.nanmax(np.abs(v - ref))))
    T2.XGB_A["nthread"] = 1
    res = dict(months=[periods[m] for m in months], fits_per_setting=len(months), **out,
               confirmed=out["nthread_8"]["exact"] == out["nthread_8"]["rows"])
    with open(os.path.join(C.EVID, "g4_thread_check.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1); fh.write("\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
