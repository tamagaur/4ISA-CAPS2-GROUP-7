import sys, pickle, numpy as np, pandas as pd
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import scripts.calendar_selection as cs
pd.set_option("display.width", 200); pd.set_option("display.max_rows", 200)
W, comp, panel = cs.load(); cal = cs.Calendar(W, comp)
a = panel.actual.to_numpy(float); vbd = panel.value_before_dead.to_numpy(float); dead = panel.dead.to_numpy()
vals = pickle.load(open("local/cal_sel_values.pkl", "rb"))
live_k, none_k = cs.cfg_key(cs.LIVE), cs.cfg_key(cs.NONE)
# 1 reproduction of live vs the stored calendar run
raw = pd.read_csv("local/accuracy_as_served_rows.csv"); cr = raw[raw.run == "as_served_calendar"].reset_index(drop=True)
m = panel.merge(cr[["product_key","month","value"]].rename(columns={"value":"stored_cal"}), on=["product_key","month"])
lv = vals[live_k][0]
rel = np.abs(lv - m.stored_cal.to_numpy())/np.maximum(m.stored_cal.to_numpy(),1e-9)
print("1 reproduction: rows", len(m), "exact(<1e-6)", int((rel<1e-6).sum()), "treated rows", int(m.treatment.notna().sum()), "share of non-treated exact", float((rel[m.treatment.isna().to_numpy()]<1e-6).mean()))
print("  WAPE stored-cal", cs.wape(m.stored_cal.to_numpy(), m.actual.to_numpy()), "mine", cs.wape(lv, a), "none", cs.wape(vals[none_k][0], a))
# 2 month table
rows=[]
for t, idx in panel.groupby("t").indices.items():
    j=cal.midx[t]; A=a[idx].sum()
    f,n=cal.factors(t, panel.product_key.to_numpy()[idx], cs.LIVE)
    ff=vals[live_k][1][idx]
    rows.append(dict(month=t.strftime("%Y-%m"), n=len(idx), base_bias=vbd[idx].sum()/A-1, live_bias=vals[live_k][0][idx].sum()/A-1,
        comp_ratio=cal.comp[j], med_ratio=cal.med[j], live_med_factor=float(np.median(ff)), yrs=n))
mt=pd.DataFrame(rows); print("2 monthly"); print(mt.round(3).to_string(index=False))
ok=mt.comp_ratio.notna()
print("3 corr(base bias, comp ratio-1)", round(np.corrcoef(mt.base_bias[ok], mt.comp_ratio[ok]-1)[0,1],3), "corr(base_bias, med ratio-1)", round(np.corrcoef(mt.base_bias[ok], mt.med_ratio[ok]-1)[0,1],3), "n", int(ok.sum()))
ok2=mt.live_med_factor.ne(1)
print("   corr(base bias, causal live factor-1) on months with a factor", round(np.corrcoef(mt.base_bias[ok2], mt.live_med_factor[ok2]-1)[0,1],3), int(ok2.sum()))
print("   corr(live bias, comp ratio-1)", round(np.corrcoef(mt.live_bias[ok], mt.comp_ratio[ok]-1)[0,1],3))
# oracle: month-level scalar
orc=vbd.copy()
for t, idx in panel.groupby("t").indices.items():
    s=a[idx].sum()/max(vbd[idx].sum(),1e-9); orc[idx]=np.where(dead[idx],0,vbd[idx]*s)
ev=cs.window(panel,"2024-04","2026-02").to_numpy()
print("4 evidence-window WAPE: none", round(cs.wape(vals[none_k][0][ev],a[ev]),4), "live", round(cs.wape(vals[live_k][0][ev],a[ev]),4), "oracle month scalar (in-sample ceiling)", round(cs.wape(orc[ev],a[ev]),4))
# 5 shrink curve, live otherwise (own k2 geo dec gate none, log)
print("5 shrink curve (own2, geo, dec on, log-space): WAPE and signed bias on each window")
wins={"T1 test 25-03..25-08":("2025-03","2025-08"),"T2 test 25-09..26-02":("2025-09","2026-02"),"T3 test 24-04..24-12":("2024-04","2024-12"),"all 24-04..26-02":("2024-04","2026-02")}
for s in cs.SHRINKS:
    k=cs.cfg_key(dict(grain="own",k=2,avg="geo",s=s,dec=True,gate="none",linear=False)); out=[]
    for w,(lo,hi) in wins.items():
        mk=cs.window(panel,lo,hi).to_numpy(); v=vals[k][0][mk]; out.append(f"{cs.wape(v,a[mk]):.4f}/{v.sum()/a[mk].sum()-1:+.3f}")
    print(f"  s={s}:", "  ".join(out))
print("   (no-Dec-rule version)")
for s in cs.SHRINKS:
    k=cs.cfg_key(dict(grain="own",k=2,avg="geo",s=s,dec=False,gate="none",linear=False)); out=[]
    for w,(lo,hi) in wins.items():
        mk=cs.window(panel,lo,hi).to_numpy(); v=vals[k][0][mk]; out.append(f"{cs.wape(v,a[mk]):.4f}/{v.sum()/a[mk].sum()-1:+.3f}")
    print(f"  s={s}:", "  ".join(out))
# 6 grain at s=0.5,0.7,1.0 no dec rule
print("6 grain (no Dec rule, geo) held-out WAPE T1/T2/T3")
for g,k in cs.GRAINS:
  for s in (0.5,0.7,1.0):
    kk=cs.cfg_key(dict(grain=g,k=k,avg="geo",s=s,dec=False,gate="none",linear=False)); out=[]
    for w,(lo,hi) in list(wins.items())[:3]:
        mk=cs.window(panel,lo,hi).to_numpy(); out.append(f"{cs.wape(vals[kk][0][mk],a[mk]):.4f}")
    print(f"  {g}{k or ''} s={s}:", " ".join(out))
# grain per month (s=1, no dec, causal), pick the winner by month and relate to sign disagreement
print("   per-month WAPE s=1: company / median / own2 / none ; disagree(company vs median ratio sign)")
for t, idx in panel.groupby("t").indices.items():
    r=[]
    for g,k in (("company",0),("median",0),("own",2)):
        kk=cs.cfg_key(dict(grain=g,k=k,avg="geo",s=1.0,dec=False,gate="none",linear=False)); r.append(cs.wape(vals[kk][0][idx],a[idx]))
    r.append(cs.wape(vals[none_k][0][idx],a[idx]))
    j=cal.midx[t]; ec=cal.earlier(t,cal.comp); em=cal.earlier(t,cal.med)
    dis = (bool(ec) and bool(em) and np.sign(np.mean(np.log(cal.comp[ec])))!=np.sign(np.mean(np.log(cal.med[em]))))
    if ec and em: print(f"  {t:%Y-%m} {r[0]:.3f} {r[1]:.3f} {r[2]:.3f} {r[3]:.3f} {'DISAGREE' if dis else ''}  compF={np.exp(np.mean(np.log(cal.comp[ec]))):.3f} medF={np.exp(np.mean(np.log(cal.med[em]))):.3f}")
