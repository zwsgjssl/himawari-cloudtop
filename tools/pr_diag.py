# 診断(2026-11-24 5 回目): ユーザー「CAT の精度をあげたい」→「指標を足して答え合わせ」。
#   公開の PIREP 234 件で、いまの Map(Ri は VWS 4 以上・対流雲)に足す候補を比べる:
#   Ellrod TI2(VWS ×(変形 + 収束))・Dutton・鉛直流(山岳波・重力波の代わり: |w| の最大と、近くでのばらつき)・
#   慣性不安定(絶対渦度が小さい・負)・水平の気温の傾き。報告の場所 ±0.3°・±FL12 の最大(小さいほど効く物は最小)。
#   比べ方は順位の和(重みを合わせない): いまの Map = 順位(1/Ri) + 順位(対流雲)、それに候補を 1 つ足したとき
import os, sys, json, tempfile, datetime as dt, numpy as np, time
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
T0 = time.time(); P = np.array(ub.LEVELS_HPA, float); G = 9.80665
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
FL = np.array([fl_of(p) for p in P])
PIR = json.load(open(os.path.join(os.path.dirname(__file__), "diagdata/pireps.json")))
SEV = {"NEG": 0, "LGT": 2, "LGT-MOD": 3, "MOD": 4, "MOD-SEV": 4.5, "SEV": 4.5}
REP = [{"t": dt.datetime.utcfromtimestamp(x["obsTime"]), "fl": int(x["fltLvl"]), "sev": SEV.get(x["tbInt1"], 2), "lat": x["lat"], "lon": x["lon"]} for x in PIR]
def vtime(t):
    h = 3*round((t.hour + t.minute/60)/3); return dt.datetime(t.year, t.month, t.day) + dt.timedelta(hours=h)
cases = {}
for i, r in enumerate(REP): cases.setdefault(vtime(r["t"]), []).append(i)
def get(run, lead, nm, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, nm), p); r = ub.cut(p, True); os.remove(p); return r
esi = lambda Tc: 6.112*np.exp(22.46*Tc/(272.62 + Tc)); esw = lambda Tc: 6.112*np.exp(17.67*Tc/(Tc + 243.5))
def the(Tc, p):
    e = np.where(Tc < 0, esi(Tc), esw(Tc)); rs = 0.622*e/(p - e); TK = Tc + 273.15
    return TK*(1000/p)**0.2857*np.exp(np.where(Tc < 0, 2.834e6, 2.5e6)*rs/(1004*TK))
def lev(a):   # 層 → 面(上下の層の大きい方)
    o = np.full((len(P),) + a.shape[1:], -np.inf, a.dtype); o[:-1] = a; o[1:] = np.maximum(o[1:], a); return o
res = []
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
        try: W = get(run, lead, "wind_vertical_velocity_on_pressure_levels", w)[2]
        except Exception as e: W = None
        Tc = T - 273.15 if np.nanmean(T) > 150 else T
        Sms = S*0.514444 if uS.strip().lower() in ("kt", "knots", "knot") else S
        rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
        R = np.frombuffer(ub.rh_bytes(RH, Tc, lead)[0], dtype="u1").reshape(Tc.shape).astype("f4"); R[R == 255] = np.nan
        p = P[:, None, None]; TK = Tc + 273.15; th = TK*(1000/p)**0.2857
        dz = 29.2712*(TK[:-1] + TK[1:])/2*np.log(p[:-1]/p[1:])
        sh = np.hypot(U[1:] - U[:-1], V[1:] - V[:-1])/dz; vwk = sh*1.94384*304.8
        N2 = G*(th[1:] - th[:-1])/((th[1:] + th[:-1])/2*dz); q0 = np.where(vwk < 4, 0, np.where(N2 > 1e-7, sh*sh/N2, 99.0))
        thr = np.where(Tc < -20, 96.25, 95.0); cl = R >= thr; incl = cl[:-1] & cl[1:]
        ms = (the(Tc[1:], p[1:]) - the(Tc[:-1], p[:-1]))/(dz/1000); cvm = np.where(incl, -ms, -9.0)
        sg = np.sign(lat[1] - lat[0]); dy = 6371000*np.deg2rad(abs(lat[1] - lat[0])); dx = 6371000*np.deg2rad(abs(lon[1] - lon[0]))*np.cos(np.deg2rad(lat))[None, :, None]
        ddx = lambda a: np.gradient(a, axis=2)/dx; ddy = lambda a: sg*np.gradient(a, axis=1)/dy
        ux, uy, vx, vy = ddx(U), ddy(U), ddx(V), ddy(V)
        DEF = np.hypot(ux - vy, vx + uy); DIV = ux + vy; VOR = vx - uy; f = 2*7.292e-5*np.sin(np.deg2rad(lat))[None, :, None]
        mid = lambda a: (a[1:] + a[:-1])/2
        TI1 = sh*mid(DEF); TI2 = sh*(mid(DEF) - mid(DIV))
        spd = np.hypot(U, V); LWSk = np.hypot(ddx(spd), ddy(spd))*1.94384*185200   # kt/100NM
        DUT = 1.25*mid(LWSk) + 0.25*vwk**2 + 10.5
        HTG = np.hypot(ddx(TK), ddy(TK))*1e5                                       # K/100km
        AV = VOR + f
        F = {"q4": lev(q0), "cv": lev(cvm), "TI1": lev(TI1), "TI2": lev(TI2), "DUT": lev(DUT), "VWS": lev(vwk), "HTG": HTG, "nAV": -AV, "DIVa": np.abs(DIV)}
        if W is not None: F["Wabs"] = np.abs(W)
        for i in idx:
            r = REP[i]; Ls = [k for k in range(len(P)) if abs(FL[k] - r["fl"]) <= 12] or [int(np.argmin(abs(FL - r["fl"])))]
            yy = np.where(abs(lat - r["lat"]) <= 0.3)[0]; xx = np.where(abs(lon - r["lon"]) <= 0.3)[0]
            if not len(yy) or not len(xx): continue
            sl = np.ix_(Ls, yy, xx); o = {"sev": r["sev"], "t": str(v)}
            for k, a in F.items(): o[k] = float(np.nanmax(a[sl]))
            if W is not None: o["Wsd"] = float(np.nanmax([np.nanstd(W[L][np.ix_(yy, xx)]) for L in Ls]))
            res.append(o)
        print(v, "←", run, "+", lead, len(res), f"{time.time()-T0:.0f}s", flush=True)
os.makedirs("out", exist_ok=True); json.dump(res, open("out/feat5.json", "w"))
sev = np.array([o["sev"] for o in res])
def auc(s):
    o = []
    for pos, neg in ((sev >= 2, sev == 0), (sev >= 4, sev == 0), (sev >= 4, (sev >= 2) & (sev < 3))):
        a, b = s[pos], s[neg]; o.append(float(np.mean([(x > y) + 0.5*(x == y) for x in a for y in b])) if len(a) and len(b) else np.nan)
    return " ".join(f"{x:.2f}" for x in o)
def rk(a): a = np.nan_to_num(np.array(a, float), nan=-1e9, neginf=-1e9); return np.argsort(np.argsort(a))/len(a)
X = {k: np.array([o.get(k, np.nan) for o in res]) for k in res[0] if k not in ("sev", "t")}
print(f"\n報告 {len(res)} 件(NEG {int((sev==0).sum())}・LGT {int(((sev>=2)&(sev<3)).sum())}・MOD 以上 {int((sev>=4).sum())})")
print("AUC: LGT 以上 vs NEG・MOD 以上 vs NEG・MOD 以上 vs LGT")
for k, a in X.items(): print(f"  単独 {k:6} {auc(rk(a))}")
base = rk(X["q4"]) + rk(X["cv"]); print(f"  いまの Map(Ri+対流雲) {auc(base)}")
for k, a in X.items():
    if k in ("q4", "cv"): continue
    print(f"  いまの Map + {k:6} {auc(base + rk(a))}")
