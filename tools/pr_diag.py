# 診断(2026-11-23): 函館の TAF に TEMPO TSRA(05〜21Z)が出ているのに、Map の雷予想が塗らない理由を見る。
#   UKMET の各時刻で、函館の周り(±0.5°)と上流の日本海側(北緯 40.5〜43.5°・東経 138〜142°)の
#   CAPE・対流性の雨と雪・雲頂(Map の upCtGrid と同じ RH の決め方)・-10℃ の高さを出して、Map の 2 つの決まり
#   (夏: 対流性 0.3mm/h 以上 かつ CAPE 500 以上 / 冬季雷: 雲頂 -20℃ 以下 かつ -10℃ の高さ 1.4km 以上 3.5km 以下)のどこで落ちるかを見る
import os, sys, tempfile, datetime as dt, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
P = np.array(ub.LEVELS_HPA, float)
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
HK = (41.77, 140.82)
def get(run, lead, nm, lv, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, nm), p); r = ub.cut(p, lv); os.remove(p); return r
def has(run, lead):
    try: return ub.exists(ub.key_of(run, lead, ub.FILES["T"]))[0]
    except Exception: return False
runs = [r for r in ("20261123T0000Z", "20261122T1800Z", "20261122T1200Z") if has(r, 6)]
print("使える回", runs)
with tempfile.TemporaryDirectory() as w:
  for run in runs[:2]:
    r0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ"); print("\n==== 回", run)
    for vh in range(3, 24, 3):
        v = dt.datetime(2026, 11, 23, vh); lead = int((v - r0).total_seconds()//3600)
        if lead < 0 or lead > 21: continue
        try:
            lat, lon, T, uT, _ = get(run, lead, ub.FILES["T"], True, w); RH = get(run, lead, ub.FILES["RH"], True, w)[2]
            CAPE = get(run, lead, ub.CAPE_FILE, False, w)[2]
            PR = []
            for nm in ub.PR_FILES:
                try: la7, _, a7, u7, _ = get(run, lead, nm, False, w); PR.append(ub.pr_mmh(a7, u7))
                except Exception as e: PR.append(np.zeros_like(CAPE))
        except Exception as e: print(v, "読めない", e); continue
        Tc = T - 273.15 if np.nanmean(T) > 150 else T
        conv = np.nan_to_num(PR[1]) + np.nan_to_num(PR[2])
        nL, ny, nx = Tc.shape; ct = np.zeros((ny, nx)); ctT = np.full((ny, nx), np.nan); h10 = np.full((ny, nx), np.nan)
        thr = np.where(Tc < -20, 96.25, 95.0); cl = RH >= thr
        z = np.zeros_like(Tc); z[0] = fl_of(P[0])*30.48
        for L in range(1, nL): z[L] = z[L-1] + 29.2712*((Tc[L-1] + Tc[L])/2 + 273.15)*np.log(P[L-1]/P[L])
        for L in range(nL - 1, -1, -1):
            m = cl[L] & (ct == 0); ct[m] = fl_of(P[L]); ctT[m] = Tc[L][m]
        for L in range(nL - 1, 0, -1):
            m = (Tc[L-1] > -10) & (Tc[L] <= -10)
            h10 = np.where(m, z[L-1] + (z[L] - z[L-1])*(Tc[L-1] + 10)/(Tc[L-1] - Tc[L]), h10)
        h10 = np.where(Tc[0] <= -10, 0, h10)
        summer = (conv >= 0.3) & (CAPE >= 500)
        wl = (ctT <= -20) & (h10 >= 1400) & (h10 <= 3500)
        for name, (a0, a1, b0, b1) in (("函館 ±0.5°", (HK[0]-.5, HK[0]+.5, HK[1]-.5, HK[1]+.5)), ("日本海側 40.5-43.5N 138-142E", (40.5, 43.5, 138, 142))):
            yy = (lat >= a0) & (lat <= a1); xx = (lon >= b0) & (lon <= b1); s = np.ix_(yy, xx)
            c, cv, ctt, hh, ctf = CAPE[s], conv[s], ctT[s], h10[s], ct[s]
            print(f"{v:%d %HZ} +{lead:2d}h {name:24} CAPE 最大 {np.nanmax(c):5.0f} 90% {np.nanpercentile(c,90):4.0f} | 対流性 最大 {np.nanmax(cv):4.1f}mm/h 0.3以上 {np.mean(cv>=.3)*100:3.0f}% | "
                  f"雲頂 最高 FL{np.nanmax(ctf):3.0f} 最も冷たい {np.nanmin(ctt):5.1f}℃ | -10℃ 高さ {np.nanmin(hh):4.0f}〜{np.nanmax(hh):4.0f}m | "
                  f"夏の決まり {np.mean(summer[s])*100:3.0f}%  冬季雷 {np.mean(wl[s])*100:3.0f}% | "
                  f"CAPE≥100&対流0.3 {np.mean((c>=100)&(cv>=.3))*100:3.0f}%  雲頂≤-20 {np.mean(ctt<=-20)*100:3.0f}%  雲頂≤-10 {np.mean(ctt<=-10)*100:3.0f}%")
        yi = int(np.argmin(abs(lat - HK[0]))); xi = int(np.argmin(abs(lon - HK[1])))
        print("   函館の点 FL:気温/RH", " ".join(f"{fl_of(P[L]):.0f}:{Tc[L,yi,xi]:.0f}/{RH[L,yi,xi]:.0f}%" for L in range(0, nL, 2)))
