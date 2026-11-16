# 診断: 2026-11-15 新千歳→羽田(到着 11:20Z ごろ、北から進入)。ユーザー本人: FL300〜350 で L、ほかはほぼ揺れなし、10000ft 以下はレーダーのエコーが多いのにほぼ揺れなし。
#   新千歳〜羽田の直線(会社経路は使わない)の羽田から 0〜250NM を 25NM ごとに、FL280〜360 の層の Ri 最小・VWS 最大・FGEN 最大・雲、FL100 以下の雲・雲の中の安定度
import os, sys, tempfile, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
G = 9.81; R = 6371e3; P = np.array(ub.LEVELS_HPA, float)
A0, B0 = (35.553, 139.781), (42.775, 141.692)
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
def get(run, lead, name, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, True)
def esat(T): Tc = T - 273.15; return 6.112*np.exp(17.67*Tc/(Tc + 243.5))
def esati(T): Tc = T - 273.15; return np.where(Tc < 0, 6.112*np.exp(22.46*Tc/(272.62 + Tc)), esat(T))
def case(run, lead, w):
    lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]; RH = get(run, lead, ub.FILES["RH"], w)[2]
    TK = T if np.nanmean(T) > 150 else T + 273.15; RHf = RH/100 if np.nanmax(RH) > 2 else RH
    cold = TK < 233; p999 = np.nanpercentile(RHf[cold], 99.9) if cold.any() else 1
    RHi = RHf*esat(TK)/esati(TK) if p999 < .95 else RHf
    Sms = S/ub.KT if uS.strip().lower() in ("kt", "knots", "knot") else S; rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
    dlat = np.deg2rad(lat[1] - lat[0]); dlon = np.deg2rad(lon[1] - lon[0]); cl = np.cos(np.deg2rad(lat))[None, :, None]
    ddx = lambda F: np.gradient(F, axis=2)/(R*cl*dlon); ddy = lambda F: np.gradient(F, axis=1)/(R*dlat)
    TH = TK*(1000/P[:, None, None])**0.2857; tx, ty = ddx(TH), ddy(TH)
    FG = -(tx*tx*ddx(U) + tx*ty*(ddx(V) + ddy(U)) + ty*ty*ddy(V))/(np.hypot(tx, ty) + 1e-12)*1.08e9
    e = esati(TK); rs = 0.622*e/(P[:, None, None] - e); Lh = np.where(TK < 273.15, 2.834e6, 2.5e6); THE = TH*np.exp(Lh*rs/(1004*TK))
    tot = 2*6371*np.arcsin(np.sqrt(np.sin(np.deg2rad(B0[0]-A0[0])/2)**2 + np.cos(np.deg2rad(A0[0]))*np.cos(np.deg2rad(B0[0]))*np.sin(np.deg2rad(B0[1]-A0[1])/2)**2))/1.852
    print(f"== {run} +{lead}h  羽田からの距離ごと(直線 {tot:.0f}NM のうち 0〜250NM、前後 12NM の幅の最小・最大)")
    lays = [k for k in range(len(P) - 1) if P[k] <= 400 and P[k + 1] >= 200]
    for d in range(0, 251, 25):
        f = d/tot; la = A0[0] + (B0[0] - A0[0])*f; lo = A0[1] + (B0[1] - A0[1])*f
        j = int(np.argmin(abs(lat - la))); i = int(np.argmin(abs(lon - lo))); s = (slice(max(0, j-2), j+3), slice(max(0, i-2), i+3))
        hi = []
        for k in lays:
            a, b = k, k + 1; dz = 29.2712*(TK[a] + TK[b])/2*np.log(P[a]/P[b])
            S2 = ((U[b] - U[a])**2 + (V[b] - V[a])**2)/dz**2; N2 = G*(TH[b] - TH[a])/((TH[a] + TH[b])/2*dz)
            Ri = np.where(N2 <= 0, 0, N2/np.maximum(S2, 1e-10))[s]; vw = (np.sqrt(S2)*1.94384*304.8)[s]; F = ((FG[a] + FG[b])/2)[s]; c = ((RHi[a] >= .95) & (RHi[b] >= .95))[s]
            if fl_of(P[b]) < 280 or fl_of(P[a]) > 365: continue
            hi.append(f"FL{fl_of(P[a]):03.0f}-{fl_of(P[b]):03.0f} Ri{np.nanmin(Ri):4.2f} V{np.nanmax(vw):4.1f} F{np.nanmax(F):4.1f}{'雲' if c.mean() >= .5 else ''}")
        lo_ = []
        for k in range(len(P) - 1):
            a, b = k, k + 1
            if fl_of(P[b]) > 105 or fl_of(P[a]) < 10: continue
            dz = 29.2712*(TK[a] + TK[b])/2*np.log(P[a]/P[b]); c = ((RHi[a] >= .95) & (RHi[b] >= .95))[s]; ms = ((THE[b] - THE[a])/(dz/1000))[s]
            lo_.append(f"{fl_of(P[a]):03.0f}-{fl_of(P[b]):03.0f}:{'雲' if c.mean() >= .5 else '--'}{np.nanmedian(ms):+.1f}")
        print(f"  {d:3d}NM ({la:.2f}N {lo:.2f}E)  " + " | ".join(hi) + "   低い所 " + " ".join(lo_))
with tempfile.TemporaryDirectory() as w:
    for run, lead in (("20261115T0600Z", 4), ("20261115T0600Z", 5), ("20261115T1200Z", 0)):
        try: case(run, lead, w)
        except Exception as e: print("失敗", run, lead, repr(e))
