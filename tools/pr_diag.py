# 診断(2026-11-23 3 回目: Ri を上回る組み合わせを探すため、報告ごとの値を out/feat.json に書き出す)
# 診断(2026-11-22): CCAT を戻すか決めるための答え合わせ。nwp_ai/pilot_reports.json の揺れの報告(揺れなかった NIL も)の時刻・場所・高さで、
#   UKMET から Ri(VWS 6kt/1000ft 未満は無し)・TI1・VWS・LWS・CCAT(v136 の作り方を作り直し)を計算し、
#   「報告の場所の値が、その時刻の日本付近の同じ高さの帯の中で何 % 目か(順位)」を並べる。揺れた所で高く・揺れなかった所で低いほど良い指標。
#   CCAT の気候値(各指標の ln の平均・標準偏差)は、この診断で読んだ全部の時刻の場から作る(本番は過去の回の移動平均だった)。
import os, sys, json, tempfile, datetime as dt, numpy as np, requests
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
P = np.array(ub.LEVELS_HPA, float); G = 9.80665; R = 6371000.0
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
FL = np.array([fl_of(p) for p in P])
# 2026-11-22 2 回目: 公開の PIREP(aviationweather.gov を集めた物。日本付近・FL150 以上・揺れの記載あり)で。強さは tbInt1(NEG = 揺れなし)
PIR = json.load(open(os.path.join(os.path.dirname(__file__), "diagdata/pireps.json")))
REP = [{"t": dt.datetime.utcfromtimestamp(x["obsTime"]).strftime("%Y-%m-%dT%H:%MZ"), "from": x.get("acType") or "?", "to": "", "fl": int(x["fltLvl"]),
        "tb": x["tbInt1"], "pts": [[x["lat"], x["lon"]], [x["lat"], x["lon"]]]} for x in PIR]
SEV = {"NEG": 0, "LGT": 2, "LGT-MOD": 3, "MOD": 4, "MOD-SEV": 4.5, "SEV": 4.5, "NIL": 0, "LM-L": 1, "L-": 1, "L": 2, "L-LP": 2.5, "LP": 3, "LGT+": 3, "LM": 3.5, "LP-MOD": 4, "MOD": 4}
def has(key):
    try: return ub.exists(key)[0]
    except Exception: return False
def runs_for(t):
    """t に一番近い 3 時間おきの時刻 v と、それを含む回(新しい方から、lead 0〜9)"""
    v = dt.datetime(t.year, t.month, t.day, 3*round((t.hour + t.minute/60)/3) % 24) + dt.timedelta(days=1 if 3*round((t.hour + t.minute/60)/3) >= 24 else 0)
    out = []
    for back in (0, 6, 12):
        r0 = v - dt.timedelta(hours=v.hour % 6) - dt.timedelta(hours=back)
        out.append((r0.strftime("%Y%m%dT%H%MZ"), int((v - r0).total_seconds()//3600), v))
    return out
def load(run, lead, w):
    def g(name, lv=True):
        p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); r = ub.cut(p, lv); os.remove(p); return r
    lat, lon, T, uT, _ = g(ub.FILES["T"]); S, uS = g(ub.FILES["S"])[2:4]; D = g(ub.FILES["D"])[2]
    TK = T if np.nanmean(T) > 150 else T + 273.15
    Sms = S/1.94384 if uS.strip().lower() in ("kt", "knots", "knot") else S
    rad = np.deg2rad(D); return lat, lon, TK, -Sms*np.sin(rad), -Sms*np.cos(rad)
def load_ex(run, lead, w):
    """3 回目: 湿度・圏界面・CAPE・対流性の雨(無ければ None)"""
    out = {}
    for k, nm, lv in (("RH", ub.FILES["RH"], True), ("TP", ub.FILES["TP"], False), ("CAPE", ub.CAPE_FILE, False), ("CR", "rainfall_rate_from_convection", False)):
        try:
            p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, nm), p); r = ub.cut(p, lv); os.remove(p); out[k] = (r[2], r[3])
        except Exception as e: out[k] = None
    return out
def fields(lat, lon, TK, u, v, u2=None, v2=None, dts=None):
    p = P[:, None, None]; th = TK*(1000/p)**0.2857
    dzl = 29.2712*(TK[:-1] + TK[1:])/2*np.log(p[:-1]/p[1:])
    sh = np.hypot(u[1:] - u[:-1], v[1:] - v[:-1])/dzl
    VWS = np.zeros_like(u); VWS[:-1] = sh; VWS[1:] = np.maximum(VWS[1:], sh)      # s⁻¹(上下の大きい方 = 本番の TI1 と同じ)
    # Ri(層ごと = Map と同じ。上下の層の小さい方を面に)
    N2l = G*(th[1:] - th[:-1])/((th[1:] + th[:-1])/2*dzl); Ril = N2l/np.maximum(sh*sh, 1e-12)
    vwsk = sh*1.94384*304.8; Ril = np.where(vwsk < 6, 99.0, Ril)                    # v331 VWS 6kt/1000ft 未満は塗らない
    Ri = np.full_like(u, 99.0); Ri[:-1] = Ril; Ri[1:] = np.minimum(Ri[1:], Ril)
    dlat = np.deg2rad(lat[1] - lat[0])*R; dlon = (np.deg2rad(lon[1] - lon[0])*R*np.cos(np.deg2rad(lat)))[None, :, None]
    gx = lambda a: np.gradient(a, axis=2)/dlon; gy = lambda a: np.gradient(a, axis=1)/dlat
    ux, uy, vx, vy = gx(u), gy(u), gx(v), gy(v)
    DEF = np.hypot(ux - vy, vx + uy); TI1 = VWS*DEF*1e7
    # 前線形成(Petterssen、気圧面の温位): F = -(θx²ux + θxθy(vx+uy) + θy²vy)/|∇θ|
    tx, ty = gx(th), gy(th); gm = np.maximum(np.hypot(tx, ty), 1e-12)
    FG = -(tx*tx*ux + tx*ty*(vx + uy) + ty*ty*vy)/gm
    # NCSU1 = max(u ux + v vy, 0)·|∇ζ| / max(Ri, 1e-5)
    zeta = vx - uy; NC = np.maximum(u*ux + v*vy, 0)*np.hypot(gx(zeta), gy(zeta))/np.maximum(np.where(Ri >= 99, 1e3, Ri), 1e-5)
    # ラグランジュのロスビー数 |∂V/∂t + V·∇V| / (|f|·max(|V|,5))
    ADu, ADv = u*ux + v*uy, u*vx + v*vy
    dudt = (u2 - u)/dts if u2 is not None else 0; dvdt = (v2 - v)/dts if v2 is not None else 0
    f = np.abs(2*7.292e-5*np.sin(np.deg2rad(lat)))[None, :, None]
    LRo = np.hypot(dudt + ADu, dvdt + ADv)/(f*np.maximum(np.hypot(u, v), 5.0))
    LWS = np.hypot(gx(np.hypot(u, v)), gy(np.hypot(u, v)))*1.94384*111120          # 水平シアーの大きさ kt/60NM(目安。本番の LWS は風に直角の向きだけ)
    LWS = np.where(np.hypot(u, v)*1.94384 < 50, 0, LWS)
    N2 = np.full_like(u, np.nan); N2[:-1] = N2l; N2[1:] = np.fmin(N2[1:], N2l)
    return {"iRi": np.minimum(1/np.maximum(Ri, 0.1), 10.0)*(Ri < 99), "TI1": TI1, "VWS": VWS*1.94384*304.8, "LWS": LWS,
            "_fg": np.maximum(FG, 0), "_nc": NC, "_lro": LRo, "SPD": np.hypot(u, v)*1.94384, "N2": N2*1e4, "DEF": DEF*1e5}
cases = {}
for i, r in enumerate(REP):
    t = dt.datetime.strptime(r["t"], "%Y-%m-%dT%H:%MZ"); cases.setdefault(runs_for(t)[0][2], []).append(i)
print("報告", len(REP), "件、時刻", len(cases), "個")
F = {}
import time as _t; T0 = _t.time()
with tempfile.TemporaryDirectory() as w:
    for v, idx in sorted(cases.items(), key=lambda kv: -len(kv[1])):   # 報告の多い時刻から
        if _t.time() - T0 > 44*60: print("時間切れ。ここまで", len(F), "時刻"); break
        t = dt.datetime.strptime(REP[idx[0]]["t"], "%Y-%m-%dT%H:%MZ"); got = None
        for run, lead, _ in runs_for(t):
            if lead + 3 > 21: continue
            if has(ub.key_of(run, lead, ub.FILES["T"])) and has(ub.key_of(run, lead + 3, ub.FILES["T"])): got = (run, lead); break
        if not got: print(v, "UKMET が残っていない(回", [x[0] for x in runs_for(t)], ")"); continue
        run, lead = got
        try:
            lat, lon, TK, u, v_ = load(run, lead, w); _, _, _, u2, v2 = load(run, lead + 3, w)
        except Exception as e: print(v, "読めない", e); continue
        ff = fields(lat, lon, TK, u, v_, u2, v2, 3*3600.0); ex = load_ex(run, lead, w)
        if ex["RH"] is not None: ff["RH"] = ex["RH"][0]
        if ex["TP"] is not None:
            tp = ex["TP"][0]; tp = tp/100 if np.nanmean(tp) > 2000 else tp                       # Pa → hPa
            ff["dTP"] = np.abs(FL[:, None, None] - fl_of(tp)[None])                              # 圏界面からの離れ(FL)
        for k in ("CAPE", "CR"):
            if ex[k] is not None: ff[k] = np.repeat(np.asarray(ex[k][0], float)[None], len(P), 0)
        F[v] = (lat, lon, ff, run, lead)
        print(v, "←", run, "+", lead, "h")
if not F: sys.exit()
# CCAT の気候値(全部の時刻・FL150〜450 の面で)
up = [k for k in range(len(P)) if 150 <= FL[k] <= 450]
W = {"iRi": 1.0, "TI1": 1.5, "_fg": 1.0, "_lro": 1.0, "_nc": 1.0}
clim = {}
for k in W:
    mu, sd = np.full(len(P), np.nan), np.full(len(P), np.nan)
    for L in up:
        x = np.concatenate([f[2][k][L].ravel() for f in F.values()]); x = x[np.isfinite(x) & (x > 0)]
        if x.size > 100: lx = np.log(x); mu[L], sd[L] = lx.mean(), max(lx.std(), 1e-3)
    clim[k] = (mu[:, None, None], sd[:, None, None])
for key, (lat, lon, f, run, lead) in F.items():
    num = 0; den = 0
    for k, wgt in W.items():
        mu, sd = clim[k]; D = f[k]
        with np.errstate(all="ignore"): z = np.where(D > 0, (np.log(np.maximum(D, 1e-30)) - mu)/sd, -2.0)
        z = np.clip(z, -4, 6); ok = np.isfinite(z); num = num + np.where(ok, wgt*np.exp(2*z), 0); den = den + np.where(ok, wgt, 0)
    with np.errstate(all="ignore"): f["CCAT"] = np.where(den > 0, np.log(np.maximum(num, 1e-30)/np.where(den > 0, den, 1))/2, np.nan)
NAMES = ["iRi", "TI1", "VWS", "LWS", "CCAT"]
def pct(f, k, Ls, ys, xs):
    """報告の場所(線の上の点 × 高さの面)の一番大きい値が、その時刻のその面たちの日本付近全体で何 % 目か"""
    vals = [f[k][L, y, x] for L in Ls for y, x in zip(ys, xs)]; v = np.nanmax(vals)
    pool = np.concatenate([f[k][L].ravel() for L in Ls]); pool = pool[np.isfinite(pool)]
    return 100.0*np.mean(pool < v), v
rows = []; FEAT = []
print("\n報告ごと: 報告の場所の値が、同じ時刻・同じ高さの帯の日本付近全体で何 % 目か(100 に近いほど「いつもより強い」)")
print(f"{'時刻':16} {'区間':12} {'FL':>9} {'報告':6} " + " ".join(f"{n:>11}" for n in NAMES))
for i, r in enumerate(REP):
    t = dt.datetime.strptime(r["t"], "%Y-%m-%dT%H:%MZ"); key = runs_for(t)[0][2]
    if key not in F: continue
    lat, lon, f, run, lead = F[key]
    fl = r.get("fl"); fl = [fl, fl] if isinstance(fl, (int, float)) else (fl or [250, 400])
    Ls = sorted(set([int(np.argmin(abs(FL - fl[0])))] + [k for k in range(len(P)) if abs(FL[k] - fl[0]) <= 12]))
    pts = r.get("pts") or []; a = pts[0]
    yy = [k for k in range(len(lat)) if abs(lat[k] - a[0]) <= 0.3]; xx = [k for k in range(len(lon)) if abs(lon[k] - a[1]) <= 0.3]
    ys = [y for y in yy for x in xx]; xs = [x for y in yy for x in xx]
    res = [pct(f, k, Ls, ys, xs) for k in NAMES]
    tb = str(r.get("tb")); rows.append((SEV.get(tb, 2), res))
    ft = {"i": i, "t": r["t"], "tb": tb, "sev": SEV.get(tb, 2), "fl": fl[0], "lat": a[0], "lon": a[1]}
    for k in ("iRi", "TI1", "VWS", "LWS", "CCAT", "_fg", "_nc", "_lro", "SPD", "N2", "DEF", "RH", "dTP", "CAPE", "CR"):
        if k not in f: continue
        try:
            pv, vv = pct(f, k, Ls, ys, xs)
            if k in ("N2", "dTP"):   # 小さいほど効く物は一番小さい値も
                vals = [f[k][L, y, x] for L in Ls for y, x in zip(ys, xs)]; ft[k + "_min"] = float(np.nanmin(vals))
            ft[k] = float(vv); ft[k + "_p"] = float(pv)
        except Exception: pass
    FEAT.append(ft)

print("\nまとめ(揺れの強さ 0=NIL〜4=MOD と、順位 % の順位相関。+1 に近いほど揺れの強さどおり。揺れた報告(L 以上)の順位の平均と、NIL の平均)")
sev = np.array([s for s, _ in rows])
for j, n in enumerate(NAMES):
    pc = np.array([res[j][0] for _, res in rows])
    rk = lambda a: np.argsort(np.argsort(a)).astype(float)
    rho = np.corrcoef(rk(sev), rk(pc))[0, 1] if len(set(sev)) > 1 else np.nan
    print(f"  {n:5}: 順位相関 {rho:+.2f}  揺れた所の平均 {pc[sev >= 2].mean():4.0f}%  MOD・LM 以上の平均 {pc[sev >= 3.5].mean() if (sev >= 3.5).any() else np.nan:4.0f}%  NIL の平均 {pc[sev == 0].mean() if (sev == 0).any() else np.nan:4.0f}%  (件数 {len(pc)})")

def auc(pos, neg):
    if not len(pos) or not len(neg): return np.nan
    return float(np.mean([(p > n) + 0.5*(p == n) for p in pos for n in neg]))
print("\nAUC(揺れた報告と NEG を、順位 % で見分けられる割合。0.5 = 当てずっぽう、1 = 完全)")
for j, n in enumerate(NAMES):
    pc = np.array([res[j][0] for _, res in rows])
    print(f"  {n:5}: LGT 以上 vs NEG {auc(pc[sev >= 2], pc[sev == 0]):.2f}   MOD 以上 vs NEG {auc(pc[sev >= 4], pc[sev == 0]):.2f}   MOD 以上 vs LGT {auc(pc[sev >= 4], pc[(sev >= 2) & (sev < 3)]):.2f}")
print("件数: NEG", int((sev == 0).sum()), " LGT", int(((sev >= 2) & (sev < 3)).sum()), " LGT-MOD", int((sev == 3).sum()), " MOD 以上", int((sev >= 4).sum()))

os.makedirs("out", exist_ok=True); json.dump(FEAT, open("out/feat.json", "w"), ensure_ascii=False)
print("feat.json", len(FEAT), "件")
