"""cells_7.csv and cells_lgbm.csv: the cells_all.py harness pointed at preds_plus.csv.gz for the run7.py models and
for lgbm@A (run_lgbm.py). Run as: python score_7_and_lgbm.py 7 | lgbm"""
import sys
which = sys.argv[1]
models = '["adida","imapa","otm","comb_m4","comb_simple","med_3"]' if which == "7" else '["lgbm@A"]'
src = open("cells_all.py").read(); head, tail = src.split("rows = []")
head = head.replace(r'REPO + r"\reports\experiment_artifacts\candidate_search_tierA_preds.csv.gz"', '"preds_plus.csv.gz"')
head = head.replace('cand = [c for c in A.columns if c not in META and c != "ma3"]', f"cand = {models}")
tail = tail.replace('R.to_csv("cells_all.csv", index=False)', f'R.to_csv("cells_{which}.csv", index=False)')
exec(head + "rows = []" + tail)
