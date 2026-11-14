# 診断: 今日(最新の UKMET の回)の日本付近で、Ri≦0.75/0.5/0.25 と FGEN≧1/2/3 ℃/100km/3h がどれくらい塗られるか(面積 %)。
#   日本付近 = 30〜42N・128〜146E。Ri は隣の気圧面の間の層(アプリと同じ乾いた空気の式)、FGEN は気圧面ごと(アプリと同じ式)
import os, sys, tempfile, datetime as dt, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
G = 9.81; R = 6371e3; P = np.array(ub.LEVELS_HPA, float)
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
def get(run, lead, name, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, True)
run = next(r for r in ub.list_runs() if ub.run_ready(r)); t0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ")
print("回", run)
with tempfile.TemporaryDirectory() as w:
    for lead in ub.LEADS:
        vt = t0 + dt.timedelta(hours=lead)
        if not (dt.datetime(2026, 11, 14, 23) <= vt <= dt.datetime(2026, 11, 15, 9)): continue
        lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
        TK = T if np.nanmean(T) > 150 else T + 273.15
        Sms = S/ub.KT if uS.strip().lower() in ("kt", "knots", "knot") else S
        rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
        dlat = np.deg2rad(lat[1] - lat[0]); dlon = np.deg2rad(lon[1] - lon[0]); cl = np.cos(np.deg2rad(lat))[None, :, None]
        ddx = lambda F: np.gradient(F, axis=2)/(R*cl*dlon); ddy = lambda F: np.gradient(F, axis=1)/(R*dlat)
        TH = TK*(1000/P[:, None, None])**0.2857; tx, ty = ddx(TH), ddy(TH)
        FG = -(tx*tx*ddx(U) + tx*ty*(ddx(V) + ddy(U)) + ty*ty*ddy(V))/(np.hypot(tx, ty) + 1e-12)*1.08e9
        dom = np.ix_((lat >= 30) & (lat <= 42), (lon >= 128) & (lon <= 146))
        jst = (vt + dt.timedelta(hours=9)).strftime("%H時")
        print(f"== {vt:%d日%H}Z(日本 {jst})  面積 %   Ri≦0.75 / 0.5 / 0.25(参考 Ri≦1)    FGEN≧1 / 2 / 3")
        for k in range(len(P) - 1):
            a, b = k, k + 1
            if P[a] > 450 or P[b] < 175: continue
            dz = 29.2712*(TK[a] + TK[b])/2*np.log(P[a]/P[b])
            S2 = ((U[b] - U[a])**2 + (V[b] - V[a])**2)/dz**2; N2 = G*(TH[b] - TH[a])/((TH[a] + TH[b])/2*dz)
            Ri = np.where(N2 <= 0, 0, N2/np.maximum(S2, 1e-10))[dom]; F = FG[a][dom]
            print(f"  FL{fl_of(P[a]):03.0f}-{fl_of(P[b]):03.0f}   Ri {100*(Ri<=.75).mean():4.1f} {100*(Ri<=.5).mean():4.1f} {100*(Ri<=.25).mean():4.1f} ({100*(Ri<=1).mean():4.1f})"
                  f"    FGEN(FL{fl_of(P[a]):03.0f}) {100*(F>=1).mean():4.1f} {100*(F>=2).mean():4.1f} {100*(F>=3).mean():4.1f}")
