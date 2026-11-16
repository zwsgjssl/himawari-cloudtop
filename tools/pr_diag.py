# 診断: 2026-11-17 朝(日本時間)、羽田→福岡(直線)の FL250〜300 で Ri が強く(小さく)出ている理由。
#   各層の Ri・VWS・N²(安定度)・気温減率・湿度・風を、直線上の数か所で並べる。圏界面の高さも
import os, sys, tempfile, datetime as dt, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
G = 9.81; P = np.array(ub.LEVELS_HPA, float)
A0, B0 = (35.553, 139.781), (33.586, 130.451)
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
def get(run, lead, name, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, True)
def get2(run, lead, name, w):
    p = os.path.join(w, "y.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, False)
now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
runs = [r for r in ub.list_runs(2) if ub.run_ready(r)]
run = runs[0]; t0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ")
lead = min(ub.LEADS, key=lambda L: abs((t0 + dt.timedelta(hours=L) - now).total_seconds()))
print("今", now, "回", run, "+", lead, "h =", t0 + dt.timedelta(hours=lead))
with tempfile.TemporaryDirectory() as w:
    lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
    RH = get(run, lead, ub.FILES["RH"], w)[2]
    try: TP = get2(run, lead, ub.FILES["TP"], w)[2]
    except Exception as e: TP = None; print("圏界面 失敗", e)
TK = T if np.nanmean(T) > 150 else T + 273.15
Skt = S if uS.strip().lower() in ("kt", "knots", "knot") else S*1.94384
Sms = Skt/1.94384; rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
TH = TK*(1000/P[:, None, None])**0.2857
n = 9; f = np.linspace(0, 1, n); la = A0[0] + (B0[0] - A0[0])*f; lo = A0[1] + (B0[1] - A0[1])*f
for j in range(n):
    y = int(np.argmin(abs(lat - la[j]))); x = int(np.argmin(abs(lon - lo[j])))
    tp = TP[..., y, x].item() if TP is not None else float("nan"); tp = tp/100 if tp > 2000 else tp
    print(f"\n== 点 {j} {la[j]:.2f}N {lo[j]:.2f}E  圏界面 {tp:.0f}hPa (FL{fl_of(tp):.0f})")
    for k in range(len(P) - 1):
        a, b = k, k + 1
        if P[a] > 500 or P[b] < 175: continue
        dz = 29.2712*(TK[a, y, x] + TK[b, y, x])/2*np.log(P[a]/P[b])
        du, dv = U[b, y, x] - U[a, y, x], V[b, y, x] - V[a, y, x]
        S2 = (du*du + dv*dv)/dz**2; N2 = G*(TH[b, y, x] - TH[a, y, x])/((TH[a, y, x] + TH[b, y, x])/2*dz)
        Ri = N2/max(S2, 1e-10); lapse = -(TK[b, y, x] - TK[a, y, x])/dz*1000
        print(f"  FL{fl_of(P[a]):03.0f}-{fl_of(P[b]):03.0f} T {TK[a,y,x]-273.15:6.1f}→{TK[b,y,x]-273.15:6.1f}℃ 減率 {lapse:4.1f}K/km  N² {N2*1e4:5.2f}e-4  "
              f"VWS {np.sqrt(S2)*1.94384*304.8:5.1f}kt/1000ft  Ri {Ri:6.2f}  風 {D[a,y,x]:3.0f}/{Skt[a,y,x]:3.0f}→{D[b,y,x]:3.0f}/{Skt[b,y,x]:3.0f}kt  RH {RH[a,y,x]:3.0f}%")
