# 診断: 2026-11-14 の羽田→福岡で、雲が対流性(揺れる雲)か層状(揺れない雲)か。GUSRO と直線上の数点で
#   湿度・気温減率・飽和相当温位の上下の差(湿った空気での安定度)・CAPE・対流性の雨/全体の雨
import matplotlib as _m
import os, sys, math, tempfile, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
P = np.array(ub.LEVELS_HPA, float); fl = (1 - (P/1013.25)**0.190284)*145366.45/100
def esat(Tk): Tc = Tk - 273.15; return 6.112*np.exp(17.67*Tc/(Tc + 243.5))
def tez(Tk, p): rs = 0.622*esat(Tk)/(p - esat(Tk)); return Tk*(1000/p)**0.2857*np.exp(2.5e6*rs/(1004*Tk))
PTS = [("GUSRO", 35.66, 139.14), ("浜松沖", 34.9, 137.6), ("紀伊半島", 34.4, 135.9), ("岡山", 34.6, 133.9), ("広島", 34.3, 132.5), ("北九州", 33.9, 131.0)]
with tempfile.TemporaryDirectory() as w:
    for lead in (3, 6):
        run = "20261114T0600Z"; A = {}
        for k, n in (("T", ub.FILES["T"]), ("RH", ub.FILES["RH"]), ("CAPE", ub.CAPE_FILE), ("PR", "precipitation_rate"), ("CR", "rainfall_rate_from_convection")):
            p = os.path.join(w, k); ub.download(ub.key_of(run, lead, n), p); A[k] = ub.cut(p, k in ("T", "RH"))
        lat, lon = A["T"][0], A["T"][1]; T = A["T"][2]; TK = T if np.nanmean(T) > 150 else T + 273.15; RH = A["RH"][2]; RH = RH*100 if np.nanmax(RH) <= 2 else RH
        la2, lo2 = A["CAPE"][0], A["CAPE"][1]
        print(f"== {'09' if lead == 3 else '12'}Z")
        for nm, la, lo in PTS:
            j = int(np.argmin(abs(lat - la))); i = int(np.argmin(abs(lon - lo))); j2 = int(np.argmin(abs(la2 - la))); i2 = int(np.argmin(abs(lo2 - lo)))
            cape = A["CAPE"][2][j2, i2]; pr = ub.pr_mmh(A["PR"][2], A["PR"][3])[j2, i2]; cr = ub.pr_mmh(A["CR"][2], A["CR"][3])[j2, i2]
            the = tez(TK[:, j, i], P); rows = []
            for k in range(len(P) - 1):
                if P[k] > 850 or P[k + 1] < 250: continue
                dz = 29.2712*(TK[k, j, i] + TK[k + 1, j, i])/2*np.log(P[k]/P[k + 1]); lr = (TK[k, j, i] - TK[k + 1, j, i])/dz*1000
                rows.append(f"FL{fl[k]:03.0f}-{fl[k+1]:03.0f} 湿{RH[k,j,i]:3.0f}% 減率{lr:4.1f}℃/km θe*差{the[k+1]-the[k]:+5.1f}K")
            print(f"  {nm}: CAPE {cape:5.0f} J/kg  雨 {pr:4.1f} mm/h(うち対流性 {cr:4.1f})")
            for r in rows: print("     " + r)
