"""
Chart 6 - unfit SKUs (Tier A as of 2026-02). Series + served band + measured cause
for every SKU whose fit-review verdict is 'not fit'.

Everything comes from the DSD Dev Viewer's own code (tools/dsd_dev_viewer/build.py,
commit 9ba24be's month record), run here, not re-implemented:
  fetch()             one READ ONLY transaction (transaction-scoped, rolled back)
  assemble()          the per-SKU payload on the real series
  add_band_evidence() the served model's rolling one-step holdout and its band per month
                      (global XGBoost nthread=1, analytics/forecasting/global_model.py:38)
  load_fit_review()   the fit review CSV merged per SKU, plus the month record:
                      spike_months (3 x MAD rule; count must equal cause_n_spikes) and
                      lvl (mean(last 6) / mean(prior 12) with its two windows; must equal
                      cause_level_shift). cause_largest_step_month is NOT used.
MASE gate: 1.1 (fit review; reports/diagnostics/UNFIT_SKU_LIST.md). Not changed here.

Check (pre-registered) G5: the list reproduces - the 'not fit' set equals
{common-window SKUs with mase_common >= 1.1} + {fallback-source SKUs with
mase_pipeline >= 1.1}, sized 25 + 3 = 28 - and the month record agrees with the fit
review on every SKU it covers (spikes 132/132, level ratio 86/86).
"""
import _common as C
import os
import sys

import pandas as pd

GATE = C.MASE_GATE_FIT_REVIEW
FALLBACK = "pipeline (20% split)"


def main():
    C.export_env_to_process()
    sys.path.insert(0, os.path.join(C.REPO, "tools", "dsd_dev_viewer"))
    import build as V

    raw, timing, dsn = V.fetch()
    payload = V.assemble(raw)
    payload["band"] = V.add_band_evidence(payload)
    fit = V.load_fit_review(payload)
    skus = payload["skus"]
    periods = payload["periods"]

    unfit = [s for s in skus if s.get("verdict") == "not fit"]
    common = [s for s in unfit if s.get("verdict_source") == "common"]
    fallback = [s for s in unfit if s.get("verdict_source") == FALLBACK]
    rebuilt = {s["pk"] for s in skus if s.get("verdict_source") == "common" and (s.get("mase_common") or 0) >= GATE} | \
              {s["pk"] for s in skus if s.get("verdict_source") == FALLBACK and (s.get("mase_pipeline") or 0) >= GATE}
    same_set = rebuilt == {s["pk"] for s in unfit}
    sc, lc = fit["spike_check"], fit["level_check"]
    ok = (same_set and len(common) == 25 and len(fallback) == 3 and len(unfit) == 28
          and sc["ok"] == sc["n"] == 132 and lc["ok"] == lc["n"] == 86)
    checks = [dict(id="G5", **{"pass": ok},
                   detail=f"not fit = {len(unfit)} ({len(common)} common + {len(fallback)} fallback; expected 25 + 3 = 28); "
                          f"rebuilt from the {GATE:g} gate: {'same set' if same_set else 'DIFFERENT set'} ({len(rebuilt)}); "
                          f"month record: spikes {sc['ok']}/{sc['n']} (expected 132/132), level ratio {lc['ok']}/{lc['n']} (expected 86/86)")]
    if not ok:
        C.fail("G5", checks[0]["detail"])

    rows, months = [], []
    for s in sorted(unfit, key=lambda s: (s["router_bin"] or "", -(s.get("mase_common") or s.get("mase_pipeline") or 0))):
        used = s["mase_common"] if s["verdict_source"] == "common" else s["mase_pipeline"]
        lvl = s.get("lvl") or {}
        rows.append(dict(pk=s["pk"], sku_code=s["code"], product_name=s["name"], router_bin=s["router_bin"], served_model=s["method"],
                         verdict_source=s["verdict_source"], mase_used=used, mase_gate=GATE, ma3_mase_common=s.get("ma3_mase_common"),
                         ma3_also_fails=s.get("ma3_fails"), cause_group=s.get("cause"), causes_all="; ".join(s.get("causes_all") or []),
                         n_spikes=len(s["spike_months"]) if s.get("spike_months") is not None else None,
                         spike_months="; ".join(s.get("spike_months") or []),
                         level_ratio=lvl.get("r"), level_prior=" .. ".join(lvl.get("prior") or []),
                         level_recent=" .. ".join(lvl.get("recent") or []),
                         cv_last12=s.get("cause_cv"), median_units=s.get("cause_median_units"), mad=s.get("cause_mad"),
                         band_coverage=s.get("cov"), band_width_over_forecast=s.get("bw"),
                         holdout_months=s.get("holdout_months")))
        hp = {h["m"]: h for h in (s.get("hpath") or [])}
        spikes = set(s.get("spike_months") or [])
        for i in range(s["first_i"], s["last_i"] + 1):
            m = periods[i]; h = hp.get(m, {})
            months.append(dict(pk=s["pk"], sku_code=s["code"], month=m, actual=s["monthly"][i],
                               null_quantity=i in (s.get("null_months") or []),
                               holdout=m in hp, forecast=h.get("v"), band_lo=h.get("lo"), band_hi=h.get("hi"),
                               outside_band=h.get("out"), ma3=h.get("m3"), spike=m in spikes,
                               level_prior=bool(lvl) and lvl["prior"][0] <= m <= lvl["prior"][1],
                               level_recent=bool(lvl) and lvl["recent"][0] <= m <= lvl["recent"][1]))
    S, M = pd.DataFrame(rows), pd.DataFrame(months)

    by_cause = S.cause_group.value_counts()
    by_bin = S.router_bin.value_counts()
    outside = M[M.holdout & M.outside_band.notna()]
    ma3_fail = int(S.ma3_also_fails.fillna(False).astype(bool).sum())
    band_agree = payload["band"]["agree"]
    caption = (
        f"Unfit SKUs, Tier A as of 2026-02 (single): {len(S)} of {len(skus)} carry the fit review's 'not fit' verdict "
        f"(MASE >= {GATE:g}, the fit-review gate; the pipeline gate is {C.MASE_GATE_PIPELINE:g}): {len(common)} scored on the common "
        f"window and {len(fallback)} on the stored 20% split. By bin: "
        + ", ".join(f"{b} {n}" for b, n in by_bin.items())
        + ". Measured cause (the fit review's first matching rule): "
        + ", ".join(f"{c} {n}" for c, n in by_cause.items())
        + f". MA3 also fails on the common holdout for {ma3_fail} of them. Each panel shows the real monthly series, the served "
          f"model's rolling one-step holdout with its band (forecast +/- {V.CONFIDENCE_Z} x holdout RMSE), and the measured cause "
          f"months: spikes (more than 3 x MAD from the SKU's median; {int(S.n_spikes.fillna(0).sum())} months across the "
          f"{len(S)} SKUs) and, where the level-shift rule applies, the prior-12 and last-6 windows its ratio is measured on. "
          f"Holdout months outside the band: {int(outside.outside_band.sum())} of {len(outside)}. The recomputed holdout "
          f"matches the stored MASE on {band_agree['mase']} of {band_agree['n']} scored SKUs. The month record reproduces the "
          f"fit review's spike counts on {sc['ok']} of {sc['n']} SKUs and its level ratios on {lc['ok']} of {lc['n']}."
    )
    C.write_result(6, "unfit", "Unfit SKUs", {"skus": S, "months": M}, caption, "DESCRIPTIVE",
                   f"list reproduces from the {GATE:g} gate; month record agrees with the fit review", checks, "ch06_unfit.py",
                   extra=dict(data_notes=C.null_notes([s["pk"] for s in skus if s.get("first_i") is not None]),
                              read_via=dsn, band_agree=band_agree, fit_file=fit["file"]))


if __name__ == "__main__":
    main()
