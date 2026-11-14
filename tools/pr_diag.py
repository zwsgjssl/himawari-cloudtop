# 診断(ユーザーの体験との照らし合わせ、2026-11-14 HND→FUK: GUSRO 付近 FL210〜260 で LGT、FL300 は雲の中で滑らか)
# GUSRO(35.6624N 139.1370E)の真上の UKMET の層ごとの Ri・VWS・TI1・湿度。09Z と 12Z、近くの回 2 つ
import os, sys, tempfile, datetime as dt, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
LA, LO = 35.6624, 139.1370
def fl_of(p): return (1 - (p / 1013.25) ** 0.190284) * 145366.45 / 100
runs = [r for r in ub.list_runs(2) if ub.exists(ub.key_of(r, 3, ub.FILES["RH"]))[0]][:3]; print("回", runs)
with tempfile.TemporaryDirectory() as w:
    for run in runs:
        r0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ")
        for vh in (9, 12):
            V = dt.datetime(2026, 11, 14, vh); lead = int((V - r0).total_seconds() // 3600)
            if lead < 0 or lead % 3 or lead > 21: continue
            A = {}
            for k in ("T", "S", "D", "RH"):
                p = os.path.join(w, k); ub.download(ub.key_of(run, lead, ub.FILES[k]), p); A[k] = ub.cut(p, True)
            lat, lon, T, uT, _ = A["T"]; S, uS = A["S"][2], A["S"][3]; D = A["D"][2]; RH = A["RH"][2]
            Tc = T - 273.15 if np.nanmean(T) > 150 else T; Skt = S * ub.KT if uS.strip().lower() not in ("kt", "knots", "knot") else S
            rad = np.deg2rad(D); U, V_ = -Skt * np.sin(rad), -Skt * np.cos(rad)
            TI1 = ub.cat_indices(Tc, U, V_, lat, lat[1] - lat[0], lon[1] - lon[0])
            j = int(np.argmin(abs(lat - LA))); i = int(np.argmin(abs(lon - LO)))
            P = np.array(ub.LEVELS_HPA, float); TK = Tc[:, j, i] + 273.15; u = U[:, j, i] * 0.514444; v = V_[:, j, i] * 0.514444
            print(f"== {run} +{lead}h → {vh:02d}Z  格子 {lat[j]:.2f}N {lon[i]:.2f}E")
            print("  層(hPa)      FL帯        気温℃(下/上)  風(下)        VWS kt/1000ft  Ri     TI1(上の面)  湿度%(下/上)")
            for k in range(len(P) - 1):
                if P[k] > 500 or P[k + 1] < 200: continue
                dz = 29.2712 * (TK[k] + TK[k + 1]) / 2 * np.log(P[k] / P[k + 1]); th = TK * (1000 / P) ** 0.2857
                N2 = 9.81 * (th[k + 1] - th[k]) / ((th[k] + th[k + 1]) / 2 * dz); S2 = ((u[k + 1] - u[k]) ** 2 + (v[k + 1] - v[k]) ** 2) / dz ** 2
                Ri = N2 / S2 if S2 > 0 else 99; vws = np.sqrt(S2) * 1.94384 * 304.8
                wd = (np.degrees(np.arctan2(-U[k, j, i], -V_[k, j, i])) + 360) % 360; ws = np.hypot(U[k, j, i], V_[k, j, i])
                print(f"  {P[k]:4.0f}-{P[k+1]:4.0f}  FL{fl_of(P[k]):03.0f}-{fl_of(P[k+1]):03.0f}  {Tc[k,j,i]:6.1f}/{Tc[k+1,j,i]:6.1f}  {wd:03.0f}/{ws:3.0f}kt  {vws:5.1f}  {min(Ri, 99):6.2f}  {TI1[k+1,j,i]:6.1f}  {RH[k,j,i]:3.0f}/{RH[k+1,j,i]:3.0f}")
            # 周り(±0.3°)で一番小さい Ri(FL200〜270 と FL280〜320)
            for lo_p, hi_p, nm in ((475, 350, "FL200-270"), (350, 275, "FL280-320")):
                best = 99
                for jj in range(max(0, j - 3), min(len(lat), j + 4)):
                    for ii in range(max(0, i - 3), min(len(lon), i + 4)):
                        TKc = Tc[:, jj, ii] + 273.15; th = TKc * (1000 / P) ** 0.2857; uu = U[:, jj, ii] * 0.514444; vv = V_[:, jj, ii] * 0.514444
                        for k in range(len(P) - 1):
                            if P[k] > lo_p or P[k + 1] < hi_p: continue
                            dz = 29.2712 * (TKc[k] + TKc[k + 1]) / 2 * np.log(P[k] / P[k + 1]); N2 = 9.81 * (th[k + 1] - th[k]) / ((th[k] + th[k + 1]) / 2 * dz)
                            S2 = ((uu[k + 1] - uu[k]) ** 2 + (vv[k + 1] - vv[k]) ** 2) / dz ** 2
                            if S2 > 0: best = min(best, N2 / S2)
                print(f"  周り30km で一番小さい Ri {nm}: {best:.2f}")
