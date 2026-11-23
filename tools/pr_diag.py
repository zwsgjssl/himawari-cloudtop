# 診断(2026-11-23 4 回目): ユーザー「実際どんな表示になるか画像で」「Ri は VWS 4 以上くらいで出そうかな」
#   A) 画面写真用: 最新の回の今日 03Z・06Z を、端末保存と同じ形(off)で out/ に書く(Map の試作を本物の場で写すため)
#   B) 公開の PIREP 234 件で、Ri を塗る VWS の下限 0・3・4・5・6 kt/1000ft と、「対流雲」(雲の中で湿った安定度 ≦ 0.5 K/km、断面図の開発者用と同じ)を足したときの
#      報告の場所が塗られる割合(揺れた所・揺れなかった所)と、日本付近で塗られる広さを比べる
import os, sys, json, tempfile, datetime as dt, numpy as np, time
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
T0 = time.time(); P = np.array(ub.LEVELS_HPA, float); G = 9.80665
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
FL = np.array([fl_of(p) for p in P])
os.makedirs("out/off", exist_ok=True)
# ---- A ----
try:
    runs = ub.list_runs(1); run = next(r for r in runs if ub.exists(ub.key_of(r, 9, ub.FILES["RH"]))[0])
    r0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ"); slices = []; grid = None
    with tempfile.TemporaryDirectory() as w:
        for vh in (3, 6):
            v = dt.datetime(2026, 11, 23, vh); lead = int((v - r0).total_seconds()//3600)
            if lead < 0 or lead > 21: continue
            buf, cat, info, rhb, ctb = ub.build_slice(run, lead, w); grid = grid or info
            k = f"{run}_{lead:02d}"; ob = ub.off_bytes(buf, rhb, info["nx"]); open(f"out/off/{k}", "wb").write(ob)
            slices.append({"lead": lead, "t": v.strftime("%Y-%m-%dT%H:%MZ"), "off": k, "offBytes": len(ob)})
    meta = {"ok": True, "model": "ukmo", "run_id": run, "run": r0.strftime("%Y-%m-%dT%H:%MZ"), "created": "diag", "lv": ub.LEVELS_HPA, "vars": ["T", "u", "v"],
            "scale": 10, "nodata": ub.NODATA, "trop": True, "off": {"fmt": "UKO1"}, "grid": grid, "slices": slices,
            "attribution": "Contains Met Office data © Crown copyright, Met Office (CC BY-SA 4.0)"}
    json.dump(meta, open("out/info.json", "w")); print("A: 画面写真用", run, [s["t"] for s in slices], f"{time.time()-T0:.0f}s")
except Exception as e: print("A: できなかった", repr(e))
# ---- B ----
PIR = json.load(open(os.path.join(os.path.dirname(__file__), "diagdata/pireps.json")))
SEV = {"NEG": 0, "LGT": 2, "LGT-MOD": 3, "MOD": 4, "MOD-SEV": 4.5, "SEV": 4.5}
REP = [{"t": dt.datetime.utcfromtimestamp(x["obsTime"]), "fl": int(x["fltLvl"]), "sev": SEV.get(x["tbInt1"], 2), "lat": x["lat"], "lon": x["lon"]} for x in PIR]
def vtime(t):
    h = 3*round((t.hour + t.minute/60)/3); return dt.datetime(t.year, t.month, t.day) + dt.timedelta(hours=h)
cases = {}
for i, r in enumerate(REP): cases.setdefault(vtime(r["t"]), []).append(i)
MASKS = [0, 3, 4, 5, 6]
def get(run, lead, nm, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, nm), p); r = ub.cut(p, True); os.remove(p); return r
esi = lambda Tc: 6.112*np.exp(22.46*Tc/(272.62 + Tc)); esw = lambda Tc: 6.112*np.exp(17.67*Tc/(Tc + 243.5))
def the(Tc, p):
    e = np.where(Tc < 0, esi(Tc), esw(Tc)); rs = 0.622*e/(p - e); TK = Tc + 273.15
    return TK*(1000/p)**0.2857*np.exp(np.where(Tc < 0, 2.834e6, 2.5e6)*rs/(1004*TK))
res = []; area = {}
with tempfile.TemporaryDirectory() as w:
    for v, idx in sorted(cases.items(), key=lambda kv: -len(kv[1])):
        if time.time() - T0 > 46*60: print("時間切れ"); break
        got = None
        for back in (0, 6, 12):
            r0 = v - dt.timedelta(hours=v.hour % 6 + back); run = r0.strftime("%Y%m%dT%H%MZ"); lead = int((v - r0).total_seconds()//3600)
            try:
                if lead <= 21 and ub.exists(ub.key_of(run, lead, ub.FILES["RH"]))[0]: got = (run, lead); break
            except Exception: pass
        if not got: continue
        run, lead = got
        try:
            lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]; RH = get(run, lead, ub.FILES["RH"], w)[2]
        except Exception as e: print(v, "読めない", e); continue
        Tc = T - 273.15 if np.nanmean(T) > 150 else T
        Skt = S if uS.strip().lower() in ("kt", "knots", "knot") else S*1.94384
        rad = np.deg2rad(D); U, V = -Skt*np.sin(rad), -Skt*np.cos(rad)
        R = np.frombuffer(ub.rh_bytes(RH, Tc, lead)[0], dtype="u1").reshape(Tc.shape).astype("f4"); R[R == 255] = np.nan
        p = P[:, None, None]; TK = Tc + 273.15; th = TK*(1000/p)**0.2857
        dz = 29.2712*(TK[:-1] + TK[1:])/2*np.log(p[:-1]/p[1:])                          # m
        sh = np.hypot(U[1:] - U[:-1], V[1:] - V[:-1])*0.514444/dz; vwk = sh*1.94384*304.8
        N2 = G*(th[1:] - th[:-1])/((th[1:] + th[:-1])/2*dz); q0 = np.where(N2 > 1e-7, sh*sh/N2, 99.0)   # 1/Ri(層)
        thr = np.where(Tc < -20, 96.25, 95.0); cl = R >= thr; incl = cl[:-1] & cl[1:]
        ms = (the(Tc[1:], p[1:]) - the(Tc[:-1], p[:-1]))/(dz/1000)                           # K/km
        cv = incl & (ms <= 0.5)
        def lev(a, how):   # 層 → 面(上下の層の大きい方 / どちらか)
            o = np.zeros((len(P),) + a.shape[1:], a.dtype); o[:-1] = a; o[1:] = np.maximum(o[1:], a) if how == "max" else (o[1:] | a); return o
        Q = {m: lev(np.where(vwk < m, 0, q0), "max") for m in MASKS}; CV = lev(cv, "or")
        up = [k for k in range(len(P)) if 150 <= FL[k] <= 450]
        for m in MASKS: area.setdefault(f"Ri{m}", []).append(float(np.mean(Q[m][up] >= 4/3)))
        area.setdefault("cv", []).append(float(np.mean(CV[up])))
        for m in MASKS: area.setdefault(f"Ri{m}+cv", []).append(float(np.mean((Q[m][up] >= 4/3) | CV[up])))
        for i in idx:
            r = REP[i]; Ls = [k for k in range(len(P)) if abs(FL[k] - r["fl"]) <= 12] or [int(np.argmin(abs(FL - r["fl"])))]
            yy = np.where(abs(lat - r["lat"]) <= 0.3)[0]; xx = np.where(abs(lon - r["lon"]) <= 0.3)[0]
            if not len(yy) or not len(xx): continue
            sl = np.ix_(Ls, yy, xx); o = {"sev": r["sev"], "cv": bool(CV[sl].any())}
            for m in MASKS: o[f"Ri{m}"] = bool((Q[m][sl] >= 4/3).any()); o[f"q{m}"] = float(np.nanmax(Q[m][sl]))
            res.append(o)
        print(v, "←", run, "+", lead, len(res), f"{time.time()-T0:.0f}s")
json.dump({"res": res, "area": area}, open("out/b.json", "w"))
sev = np.array([o["sev"] for o in res])
def auc(pos, neg): return float(np.mean([(a > b) + 0.5*(a == b) for a in pos for b in neg])) if len(pos) and len(neg) else np.nan
print(f"\n報告 {len(res)} 件(NEG {int((sev==0).sum())}・LGT {int(((sev>=2)&(sev<3)).sum())}・MOD 以上 {int((sev>=4).sum())})、時刻 {len(area.get('cv', []))}")
print("塗られた報告の割合(報告の場所 ±0.3°・±FL12 のどこかが塗られていれば「塗られた」)と、FL150〜450 の日本付近で塗られる広さ")
print(f"{'表示':12} {'LGT以上':>8} {'MOD以上':>8} {'NEG':>6} {'広さ':>6}   AUC(1/Ri の最大で LGT以上vsNEG・MOD以上vsNEG)")
for nm in [f"Ri{m}" for m in MASKS] + ["cv"] + [f"Ri{m}+cv" for m in MASKS]:
    if "+" in nm: f = np.array([o[nm.split("+")[0]] or o["cv"] for o in res])
    else: f = np.array([o[nm] for o in res])
    line = f"{nm:12} {f[sev>=2].mean()*100:7.0f}% {f[sev>=4].mean()*100:7.0f}% {f[sev==0].mean()*100:5.0f}% {np.mean(area[nm])*100:5.1f}%"
    if nm.startswith("Ri") and "+" not in nm:
        qq = np.array([o["q" + nm[2:]] for o in res]); line += f"   {auc(qq[sev>=2], qq[sev==0]):.2f} {auc(qq[sev>=4], qq[sev==0]):.2f}"
    print(line)
