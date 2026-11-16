# 診断: 2026-11-15 11Z(日本 20 時)ごろ、羽田の南(北緯 33.5〜35.5°・東経 139〜140.5°)の FL300〜340 で MOD の報告が複数(ユーザー)。
#   UKMET で、その箱の層ごとに VWS 最大・Ri 最小・FGEN 最大・雲(氷に対する湿度 95% 以上の割合)・湿った空気での安定度・風、と Ri≦0.75・FGEN≧2 の面積 %
import os, sys, tempfile, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
G = 9.81; R = 6371e3; P = np.array(ub.LEVELS_HPA, float)
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
    bx = np.ix_((lat >= 33.5) & (lat <= 35.5), (lon >= 139) & (lon <= 140.5))
    print(f"== {run} +{lead}h  羽田の南の箱。層: VWS 最大 kt/1000ft / Ri 最小 / Ri≦0.75 % / FGEN 最大・≧2 % / 雲の割合 % / 雲の中の安定度 K/km(中央値) / 風(平均)")
    for k in range(len(P) - 1):
        a, b = k, k + 1
        if P[a] > 400 or P[b] < 175: continue
        dz = 29.2712*(TK[a] + TK[b])/2*np.log(P[a]/P[b])
        S2 = ((U[b] - U[a])**2 + (V[b] - V[a])**2)/dz**2; N2 = G*(TH[b] - TH[a])/((TH[a] + TH[b])/2*dz)
        Ri = np.where(N2 <= 0, 0, N2/np.maximum(S2, 1e-10)); vws = np.sqrt(S2)*1.94384*304.8
        F = (FG[a] + FG[b])/2; sat = (RHi[a] >= .95) & (RHi[b] >= .95); ms = (THE[b] - THE[a])/(dz/1000)
        um, vm = np.mean(((U[a] + U[b])/2)[bx]), np.mean(((V[a] + V[b])/2)[bx]); sp = np.hypot(um, vm)*1.94384; dr = (np.degrees(np.arctan2(-um, -vm)) + 360) % 360
        msv = np.nanmedian(ms[bx][sat[bx]]) if sat[bx].any() else float("nan")
        print(f"  FL{fl_of(P[a]):03.0f}-{fl_of(P[b]):03.0f}  VWS {np.nanmax(vws[bx]):5.1f}  Ri {np.nanmin(Ri[bx]):5.2f} {100*(Ri[bx] <= .75).mean():5.1f}%  FGEN {np.nanmax(F[bx]):5.1f} {100*(F[bx] >= 2).mean():5.1f}%  雲 {100*sat[bx].mean():5.1f}%  安定度 {msv:5.2f}  風 {dr:03.0f}°{sp:4.0f}kt")
    tz = np.ix_((lat >= 33.5) & (lat <= 35.5), (lon >= 139) & (lon <= 140.5))
with tempfile.TemporaryDirectory() as w:
    for run, lead in (("20261115T0600Z", 3), ("20261115T0600Z", 6), ("20261115T1200Z", 0)):
        try: case(run, lead, w)
        except Exception as e: print("失敗", run, lead, repr(e))
