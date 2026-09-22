"""preview_summary.csv (testable blocks per bin per arm + test-month bin moves REAL -> SYNTH) and the chronos_bolt
'not run' rows appended to cells_arms.csv."""
import pandas as pd
C2 = pd.read_csv("cells_arms.csv"); A = pd.read_csv("preds_synth.csv.gz")
tb = C2[C2.model == "MA3"][["arm", "bin", "testable"]].assign(table="testable_blocks").rename(columns={"testable": "value"})
mv = pd.crosstab(A.bin_real, A.bin).stack().reset_index(); mv.columns = ["real_bin", "synth_bin", "value"]; mv["table"] = "test_month_bin_moves"
pd.concat([tb, mv], ignore_index=True)[["table", "arm", "bin", "real_bin", "synth_bin", "value"]].to_csv("preview_summary.csv", index=False)
NR = "not run (environment: Windows Application Control blocks torch)"
cr = pd.DataFrame([dict(arm=a, bin=b, model="chronos_bolt", tag=NR) for a in ("REAL", "SYNTH") for b in ("short", "medium", "long")])
pd.concat([C2[C2.model != "chronos_bolt"], cr], ignore_index=True).to_csv("cells_arms.csv", index=False)
