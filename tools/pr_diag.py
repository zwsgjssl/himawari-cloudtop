# 診断(2026-11-24): ユーザー「昨夜の秋田沖、結構光ってたけど雷は予想できてた？」
#   答え合わせ(ltg-data)は全国の数だけで場所が無いので、秋田沖(北緯 39〜41°・東経 137.5〜140.2°)で
#   Map の雷予想の決まり(v349 の新: CAPE 100・対流性 0.3・925/850 収束 3e-5 / 前: CAPE 500・対流性 0.3)と冬季雷が塗った升の割合を、時刻ごとに出す。
#   答え合わせと同じ回(23日 06Z の +6・+9、12Z の +6・+9)。升の地図も文字で出す(# = 新の決まりで塗る、+ = 冬季雷だけ、. = なし)
import os, sys, tempfile, datetime as dt, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
P = np.array(ub.LEVELS_HPA, float); BOX = (39.0, 41.0, 137.5, 140.2)
def get(run, lead, nm, lv, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, nm), p); r = ub.cut(p, lv); os.remove(p); return r
with tempfile.TemporaryDirectory() as w:
    for run, lead in (("20261123T0600Z", 3), ("20261123T0600Z", 6), ("20261123T0600Z", 9), ("20261123T1200Z", 6), ("20261123T1200Z", 9)):
        v = dt.datetime.strptime(run, "%Y%m%dT%H%MZ") + dt.timedelta(hours=lead)
        try:
            lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], True, w); S, uS = get(run, lead, ub.FILES["S"], True, w)[2:4]; D = get(run, lead, ub.FILES["D"], True, w)[2]
            RH = get(run, lead, ub.FILES["RH"], True, w)[2]; CAPE = get(run, lead, ub.CAPE_FILE, False, w)[2]
            PR = []
            for nm in ub.PR_FILES:
                try: _, _, a7, u7, _ = get(run, lead, nm, False, w); PR.append(ub.pr_mmh(a7, u7))
                except Exception: PR.append(np.zeros_like(CAPE))
        except Exception as e: print(v, "読めない", e); continue
        Tc = T - 273.15 if np.nanmean(T) > 150 else T
        Sms = S*0.514444 if uS.strip().lower() in ("kt", "knots", "knot") else S
        rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
        conv = np.nan_to_num(PR[1]) + np.nan_to_num(PR[2])
        dy = 6371000*np.deg2rad(abs(lat[1] - lat[0])); dx = 6371000*np.deg2rad(abs(lon[1] - lon[0]))*np.cos(np.deg2rad(lat))[:, None]
        dv = 0; Ls = [list(P).index(p) for p in (925, 850) if p in P]
        for L in Ls: dv = dv + (np.gradient(U[L], axis=1)/dx + np.gradient(V[L], axis=0)*np.sign(lat[1] - lat[0])/dy)/len(Ls)
        new = (CAPE >= 100) & (conv >= 0.3) & (-dv >= 3e-5); old = (CAPE >= 500) & (conv >= 0.3)
        # 冬季雷(Map と同じ: 雲頂 -20℃ 以下・-10℃ の高さ 1.4〜3.5km)。湿度は 0〜1 なら % に
        R = RH*100 if np.nanmax(RH) <= 1.5 else RH
        nL = len(P); z = np.zeros_like(Tc); z[0] = 30.48*(1 - (P[0]/1013.25)**0.190284)*145366.45
        for L in range(1, nL): z[L] = z[L-1] + 29.2712*((Tc[L-1] + Tc[L])/2 + 273.15)*np.log(P[L-1]/P[L])
        ctT = np.full(CAPE.shape, np.nan); h10 = np.full(CAPE.shape, np.nan)
        for L in range(nL - 1, -1, -1):
            m = (R[L] >= np.where(Tc[L] < -20, 96.25, 95)) & np.isnan(ctT); ctT[m] = Tc[L][m]
        for L in range(nL - 1, 0, -1):
            m = (Tc[L-1] > -10) & (Tc[L] <= -10); h10 = np.where(m, z[L-1] + (z[L] - z[L-1])*(Tc[L-1] + 10)/(Tc[L-1] - Tc[L]), h10)
        wl = (ctT <= -20) & (h10 >= 1400) & (h10 <= 3500)
        yy = (lat >= BOX[0]) & (lat <= BOX[1]); xx = (lon >= BOX[2]) & (lon <= BOX[3]); s = np.ix_(yy, xx)
        print(f"\n{v:%d日 %HZ}({(v + dt.timedelta(hours=9)):%H}JST) {run} +{lead}h  秋田沖: 新の決まり {new[s].mean()*100:3.0f}%  前の決まり {old[s].mean()*100:3.0f}%  冬季雷 {wl[s].mean()*100:3.0f}%  "
              f"| CAPE 最大 {np.nanmax(CAPE[s]):4.0f} 中央 {np.nanmedian(CAPE[s]):4.0f}  対流性 0.3 以上 {(conv[s] >= .3).mean()*100:3.0f}%  収束 3e-5 以上 {(-dv[s] >= 3e-5).mean()*100:3.0f}%  "
              f"雲頂 最も冷たい {np.nanmin(ctT[s]):5.1f}℃  -10℃ の高さ {np.nanmedian(h10[s]):4.0f}m")
        ys = np.where(yy)[0]; xs = np.where(xx)[0]
        if lat[1] > lat[0]: ys = ys[::-1]
        for y in ys[::3]:
            print("   " + f"{lat[y]:5.2f} " + "".join("#" if new[y, x] else "+" if wl[y, x] else "." for x in xs[::2]))
        print("         西 " + f"{lon[xs[0]]:.1f}E" + " " * (len(xs[::2]) - 14) + f"{lon[xs[-1]]:.1f}E 東")
