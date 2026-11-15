import sys, pickle, numpy as np, pandas as pd
sys.path.insert(0, ".")
import scripts.calendar_selection as cs
W, comp, panel = cs.load(); cal = cs.Calendar(W, comp)
a = panel.actual.to_numpy(float)
vals = pickle.load(open("local/cal_sel_values.pkl", "rb")); res = pickle.load(open("local/cal_sel_results.pkl","rb"))
live_k, none_k = cs.cfg_key(cs.LIVE), cs.cfg_key(cs.NONE)
win=lambda lo,hi: cs.window(panel,lo,hi).to_numpy()
t1=win("2025-03","2025-08"); t2=win("2025-09","2026-02"); m=t1|t2
p1,p2=res["folds"]["T1"]["pick"],res["folds"]["T2"]["pick"]
seq=np.where(t1,vals[p1][0],vals[p2][0])
print("1. sequential (choose on past, test on next) pooled T1+T2, n",int(m.sum()),": procedure",round(cs.wape(seq[m],a[m]),4),"live",round(cs.wape(vals[live_k][0][m],a[m]),4),"none",round(cs.wape(vals[none_k][0][m],a[m]),4))
fp=res["folds"]["FINAL"]["pick"]
for n,(lo,hi) in {"T1":("2025-03","2025-08"),"T2":("2025-09","2026-02"),"T3":("2024-04","2024-12")}.items():
    w=win(lo,hi); print(f"   FINAL pick on {n}: {cs.wape(vals[fp][0][w],a[w]):.4f} live {cs.wape(vals[live_k][0][w],a[w]):.4f} none {cs.wape(vals[none_k][0][w],a[w]):.4f}  (the pick was chosen with these months in the choosing window for FINAL: in-sample)")
# 2 year-to-year stability of the realized ratio
pairs=[]
for j,t in enumerate(cal.months):
    if j-12>=0 and np.isfinite(cal.med[j]) and np.isfinite(cal.med[j-12]) and t<pd.Timestamp("2026-03-01"):
        pairs.append((t.strftime("%Y-%m"),np.log(cal.med[j-12]),np.log(cal.med[j]),np.log(cal.comp[j-12]) if np.isfinite(cal.comp[j-12]) else np.nan,np.log(cal.comp[j]) if np.isfinite(cal.comp[j]) else np.nan))
P=pd.DataFrame(pairs,columns=["m","pm","m_","pc","c_"])
print("2. last year's ratio vs this year's (log), n pairs",len(P))
for lab,x,y in (("product median",P.pm,P.m_),("company",P.pc,P.c_)):
    ok=x.notna()&y.notna(); b=np.polyfit(x[ok],y[ok],1)
    print(f"   {lab}: corr {np.corrcoef(x[ok],y[ok])[0,1]:.3f} slope {b[0]:.3f} (the data-implied shrink toward 1 if the factor were last year's ratio) n={int(ok.sum())}")
Pd=P[~P.m.str.endswith("-12")]; ok=Pd.pm.notna()
b=np.polyfit(Pd.pm,Pd.m_,1); print(f"   product median excl December: corr {np.corrcoef(Pd.pm,Pd.m_)[0,1]:.3f} slope {b[0]:.3f} n={len(Pd)}")
print("   per month (last yr -> this yr, product median ratio):",{r.m:(round(np.exp(r.pm),2),round(np.exp(r.m_),2)) for r in P.itertuples()})
# 3 March 2026 factors
t=pd.Timestamp("2026-03-01"); keys=panel[panel.month=="2026-02"].product_key.to_numpy()
for lab,c in (("live",cs.LIVE),("FINAL pick",dict(grain="own",k=4,avg="geo",s=0.7,dec=True,gate="agree",linear=False)),("median s=1",dict(grain="median",k=0,avg="geo",s=1.0,dec=True,gate="none",linear=False)),("company s=.5",dict(grain="company",k=0,avg="geo",s=0.5,dec=True,gate="none",linear=True))):
    f,n=cal.factors(t,keys,c); print(f"3. March 2026 {lab}: years {n} median factor {np.median(f):.3f} range {f.min():.3f}-{f.max():.3f}")
print("   March ratios by year: product median", {cal.months[j].strftime('%Y-%m'):round(cal.med[j],3) for j in range(len(cal.months)) if cal.months[j].month==3 and np.isfinite(cal.med[j])}, "company", {cal.months[j].strftime('%Y-%m'):round(cal.comp[j],3) for j in range(len(cal.months)) if cal.months[j].month==3 and np.isfinite(cal.comp[j])})
