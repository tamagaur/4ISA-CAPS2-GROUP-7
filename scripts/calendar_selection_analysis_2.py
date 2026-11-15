import sys, pickle, numpy as np, pandas as pd
sys.path.insert(0, ".")
import scripts.calendar_selection as cs
W, comp, panel = cs.load(); cal = cs.Calendar(W, comp)
a = panel.actual.to_numpy(float); vbd = panel.value_before_dead.to_numpy(float); dead = panel.dead.to_numpy()
vals = pickle.load(open("local/cal_sel_values.pkl", "rb")); res = pickle.load(open("local/cal_sel_results.pkl","rb"))
live_k, none_k = cs.cfg_key(cs.LIVE), cs.cfg_key(cs.NONE)
win=lambda lo,hi: cs.window(panel,lo,hi).to_numpy()
W3={"T1":win("2025-03","2025-08"),"T2":win("2025-09","2026-02"),"T3":win("2024-04","2024-12"),"ALL":win("2024-04","2026-02")}
print("A. seasonal-naive blend (a): WAPE on T1 T2 T3 ALL (a=0 = no factor)")
for aa in cs.SHRINKS:
    v=vals[f"SN|a={aa}"][0]; print(f"  a={aa}", " ".join(f"{k}={cs.wape(v[m],a[m]):.4f}" for k,m in W3.items()))
sn=cal.seasonal_naive
print("   share of rows where SN defined:", np.mean([np.isfinite(sn(t, panel.product_key.to_numpy()[i])).mean() for t,i in panel.groupby('t').indices.items() if t>=pd.Timestamp('2024-04-01')]).round(3))
print("B. folds: pick by fold & held-out (pick vs live vs none)")
for n,r in res["folds"].items(): print("  ",n,r["pick"], {k:(round(v,4) if isinstance(v,float) else v) for k,v in r.items() if k in("pick_test","live_test","none_test","ci_vs_live","ci_vs_none")})
# C. history: factor from only the most recent year vs all earlier years, same targets with >=2 yrs (2025-04..2026-02), live otherwise
orig=cs.Calendar.earlier
def mk(maxy):
    def earlier(self,t,series):
        j=self.midx[t]; return [j-12*y for y in range(1,maxy+1) if j-12*y>=0 and np.isfinite(series[j-12*y])]
    return earlier
tg=win("2025-04","2026-02"); nodec=win("2025-04","2025-11")
print("C. history (targets 2025-04..2026-02 all have 2 earlier years): WAPE with 1 earlier year vs 2")
for s in (0.5,1.0):
  for g,k in (("median",0),("own",2)):
    out=[]
    for maxy in (1,2):
        cs.Calendar.earlier=mk(maxy)
        v,_,_=cs.build_values(cal,panel,dict(grain=g,k=k,avg="geo",s=s,dec=False,gate="none",linear=False))
        out.append(f"{maxy}yr={cs.wape(v[tg],a[tg]):.4f}")
    print(f"   {g}{k or ''} s={s} (no Dec rule), 2025-04..2026-02:", " ".join(out))
cs.Calendar.earlier=mk(1); v1,_,_=cs.build_values(cal,panel,dict(grain="median",k=0,avg="geo",s=1.0,dec=False,gate="none",linear=False))
cs.Calendar.earlier=mk(2); v2,_,_=cs.build_values(cal,panel,dict(grain="median",k=0,avg="geo",s=1.0,dec=False,gate="none",linear=False)); cs.Calendar.earlier=orig
nn=vals[none_k][0]
print("   gain over no factor (pts) at s=1 median grain, per window: 1yr", round(100*(cs.wape(nn[tg],a[tg])-cs.wape(v1[tg],a[tg])),2), " 2yr", round(100*(cs.wape(nn[tg],a[tg])-cs.wape(v2[tg],a[tg])),2))
# bias-reduction per month for 1yr vs 2yr at s=1
print("   per target month |bias| none / 1yr / 2yr:")
for t,i in panel.groupby('t').indices.items():
    if t<pd.Timestamp('2025-04-01'): continue
    A=a[i].sum(); print(f"   {t:%Y-%m} {abs(nn[i].sum()/A-1):.3f} {abs(v1[i].sum()/A-1):.3f} {abs(v2[i].sum()/A-1):.3f}")
print("   March usable years for the Mar-2026 factor:", cal.earlier(pd.Timestamp('2026-03-01'),cal.med), [cal.months[j].strftime('%Y-%m') for j in cal.earlier(pd.Timestamp('2026-03-01'),cal.med)], "Mar 2023 ratio defined?", np.isfinite(cal.med[cal.midx[pd.Timestamp('2023-03-01')]]))
# D. December rule
print("D. December rule (own2 geo s=0.5 log): per December target, WAPE and bias with rule off/on, and overall gain share")
for t in ("2024-12","2025-12"):
    mm=win(t,t)
    k_on=cs.cfg_key(dict(grain="own",k=2,avg="geo",s=0.5,dec=True,gate="none",linear=False)); k_off=cs.cfg_key(dict(grain="own",k=2,avg="geo",s=0.5,dec=False,gate="none",linear=False))
    print(f"  {t}: none {cs.wape(vals[none_k][0][mm],a[mm]):.4f}  off {cs.wape(vals[k_off][0][mm],a[mm]):.4f} bias {vals[k_off][0][mm].sum()/a[mm].sum()-1:+.3f}  on {cs.wape(vals[k_on][0][mm],a[mm]):.4f} bias {vals[k_on][0][mm].sum()/a[mm].sum()-1:+.3f}")
for lab,m in (("ALL",W3["ALL"]),("ALL excl both Decembers",W3["ALL"]&~win("2024-12","2024-12")&~win("2025-12","2025-12"))):
    print(f"  {lab}: none {cs.wape(vals[none_k][0][m],a[m]):.4f} off {cs.wape(vals[k_off][0][m],a[m]):.4f} on {cs.wape(vals[k_on][0][m],a[m]):.4f}")
print("   pieces-error removed by factor (off vs none) and by rule (on vs off), ALL: ")
m=W3["ALL"]; e=lambda v:np.abs(v[m]-a[m]).sum()
print("   none",round(e(vals[none_k][0])),"off",round(e(vals[k_off][0])),"on",round(e(vals[k_on][0])), "-> Dec rule share of total gain", round((e(vals[k_off][0])-e(vals[k_on][0]))/(e(vals[none_k][0])-e(vals[k_on][0])),3))
print("   Dec med ratios (product median): ", {cal.months[j].strftime('%Y-%m'):round(cal.med[j],3) for j in range(len(cal.months)) if cal.months[j].month==12 and np.isfinite(cal.med[j])}, " company:", {cal.months[j].strftime('%Y-%m'):round(cal.comp[j],3) for j in range(len(cal.months)) if cal.months[j].month==12 and np.isfinite(cal.comp[j])})
# E. March & July table
print("E. March/July: base bias, live bias, s=1 own2 dec bias, FINAL-pick bias")
fp=res["folds"]["FINAL"]["pick"]; k1=cs.cfg_key(dict(grain="own",k=2,avg="geo",s=1.0,dec=True,gate="none",linear=False)); k0=cs.cfg_key(dict(grain="median",k=0,avg="geo",s=1.0,dec=True,gate="none",linear=False))
for t in ("2024-03","2025-03","2024-07","2025-07"):
    mm=win(t,t);A=a[mm].sum(); f=lambda k:vals[k][0][mm].sum()/A-1
    print(f"  {t}: base {vals[none_k][0][mm].sum()/A-1:+.3f}  live {f(live_k):+.3f}  s1own2 {f(k1):+.3f}  s1median {f(k0):+.3f}  FINALpick({fp}) {f(fp):+.3f}  | WAPE none {cs.wape(vals[none_k][0][mm],a[mm]):.3f} live {cs.wape(vals[live_k][0][mm],a[mm]):.3f} pick {cs.wape(vals[fp][0][mm],a[mm]):.3f}")
# log corr
base_b=[];lr=[]
for t,i in panel.groupby('t').indices.items():
    j=cal.midx[t]
    if np.isfinite(cal.comp[j]): base_b.append(np.log(a[i].sum()/vbd[i].sum())); lr.append(np.log(cal.comp[j]))
print("corr(log actual/base total, log company ratio) =",round(np.corrcoef(base_b,lr)[0,1],3),"n",len(lr))
