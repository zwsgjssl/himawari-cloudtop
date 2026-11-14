# 診断: ユーザーの体験(2026-11-14 11Z ごろ GUSRO 付近 FL210〜260 で LGT(LP 寄り)、FL300 は雲の中で滑らか)を、どの指標が拾えていたか。
#   GUSRO(35.66N 139.14E)の真上と周り 30km の最大。値の「強さ」は、同じ層の日本付近(30〜42N・128〜146E)の中での順位(上位何 %)で比べる
import os, sys, math, tempfile, datetime as dt, numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
LA, LO = 35.6624, 139.1370; G = 9.81; R = 6371e3
P = np.array(ub.LEVELS_HPA, float)
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
def get(run, lead, name, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, True)
def esat(Tk): Tc = Tk - 273.15; return 6.112*np.exp(17.67*Tc/(Tc + 243.5))
def tez(Tk, p):
    rs = 0.622*esat(Tk)/(p - esat(Tk)); return Tk*(1000/p)**0.2857*np.exp(2.5e6*rs/(1004*Tk))
def run_case(run, lead, w):
    lat, lon, T, uT, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
    RH = get(run, lead, ub.FILES["RH"], w)[2]
    try: W = get(run, lead, "wind_vertical_velocity_on_pressure_levels", w)[2]
    except Exception as e: W = None; print("  上下の風なし", e)
    TK = T if np.nanmean(T) > 150 else T + 273.15
    Sms = S/ub.KT if uS.strip().lower() in ("kt", "knots", "knot") else S
    rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
    RHf = RH/100 if np.nanmax(RH) > 2 else RH
    dlat = np.deg2rad(abs(lat[1] - lat[0])); dlon = np.deg2rad(abs(lon[1] - lon[0])); sgn = 1 if lat[1] > lat[0] else -1
    coslat = np.cos(np.deg2rad(lat))[None, :, None]
    ddx = lambda F: np.gradient(F, axis=2)/(R*coslat*dlon); ddy = lambda F: sgn*np.gradient(F, axis=1)/(R*dlat)
    ux, uy, vx, vy = ddx(U), ddy(U), ddx(V), ddy(V)
    DEF = np.hypot(ux - vy, vx + uy); DIV = ux + vy; ZETA = vx - uy; f = 2*7.292e-5*np.sin(np.deg2rad(lat))[:, None]
    TH = TK*(1000/P[:, None, None])**0.2857; tx, ty = ddx(TH), ddy(TH); gth = np.hypot(tx, ty) + 1e-12
    FG = -(tx*tx*ux + tx*ty*(vx + uy) + ty*ty*vy)/gth*1e10
    THE = tez(TK, P[:, None, None])
    j = int(np.argmin(abs(lat - LA))); i = int(np.argmin(abs(lon - LO)))
    dom = (lat >= 30) & (lat <= 42); dlo = (lon >= 128) & (lon <= 146)
    print(f"== {run} +{lead}h(GUSRO の格子 {lat[j]:.2f}N {lon[i]:.2f}E)。値: 真上 / 周り30km の最大 (日本付近の同じ層で上位何 %)  湿度の単位 {np.nanmax(RH):.2f}")
    for k in range(len(P) - 1):
        a, b = k, k + 1
        if P[a] > 500 or P[b] < 225: continue
        Tm = (TK[a] + TK[b])/2; dz = 29.2712*Tm*np.log(P[a]/P[b])
        S2 = ((U[b] - U[a])**2 + (V[b] - V[a])**2)/dz**2; vws = np.sqrt(S2)
        N2 = G*(TH[b] - TH[a])/((TH[a] + TH[b])/2*dz); Ri = N2/np.maximum(S2, 1e-10)
        sat = (RHf[a] >= .9) & (RHf[b] >= .9); N2m = G*(np.log(THE[b]) - np.log(THE[a]))/dz; RiM = np.where(sat, N2m/np.maximum(S2, 1e-10), Ri)
        defm = (DEF[a] + DEF[b])/2; cvg = -(DIV[a] + DIV[b])/2; za = (ZETA[a] + ZETA[b])/2 + f
        I = {"VWS kt/1000ft": vws*1.94384*304.8, "1/Ri": 1/np.clip(Ri, 0.01, 1e4), "1/Ri 雲中は湿潤": 1/np.clip(RiM, 0.01, 1e4),
             "TI1 x1e7": vws*defm*1e7, "TI2 x1e7": vws*np.maximum(0, defm + cvg)*1e7, "Brown x1e6": np.sqrt(.3*za**2 + defm**2)/24*S2*1e6,
             "前線の強まり": (FG[a] + FG[b])/2, "変形DEF x1e5": defm*1e5}
        if W is not None:
            Wm = (W[a] + W[b])/2; I["上下風のばらつき cm/s"] = swv(np.pad(Wm, 2, mode="edge"), (5, 5)).std(axis=(-1, -2))*100
        flab, fhi = fl_of(P[a]), fl_of(P[b])
        tag = "← 揺れた(FL210-260)" if fhi > 210 and flab < 262 else ("← 滑らか(FL300)" if flab < 305 and fhi > 295 else "")
        print(f"  FL{flab:03.0f}-{fhi:03.0f}  湿度 {RHf[a,j,i]*100:3.0f}/{RHf[b,j,i]*100:3.0f}%  {tag}")
        for n, F in I.items():
            c = F[j, i]; m = np.nanmax(F[max(0, j-3):j+4, max(0, i-3):i+4]); A = F[np.ix_(dom, dlo)].ravel()
            print(f"     {n:<18} {c:9.2f} / {m:9.2f}   (上位 {100*(A > c).mean():5.1f}% / {100*(A > m).mean():5.1f}%)")
with tempfile.TemporaryDirectory() as w:
    for run, lead in (("20261114T0600Z", 3), ("20261114T0600Z", 6)):
        try: run_case(run, lead, w)
        except Exception as e: print("失敗", run, lead, repr(e))
