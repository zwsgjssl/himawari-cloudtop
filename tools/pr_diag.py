# 診断: 湿りRi(雲の中だけ安定度を θe* の上下差で計算)と今の Ri を、2026-11-14 の GUSRO 付近で並べる。
#   体験: 11Z ごろ FL210〜260 で LGT(LP 寄り)、FL300 は雲の中で滑らか。
#   雲の中の判定は上下の両方の面で湿度 ≥ 90% と ≥ 95% の 2 通り。日本付近で Ri<1 の面積がどれだけ増えるか(出すぎないか)も見る
import os, sys, tempfile, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
LA, LO = 35.6624, 139.1370; G = 9.81
P = np.array(ub.LEVELS_HPA, float)
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
def get(run, lead, name, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, True)
def esat(Tk): Tc = Tk - 273.15; return 6.112*np.exp(17.67*Tc/(Tc + 243.5))
def tez(Tk, p): rs = 0.622*esat(Tk)/(p - esat(Tk)); return Tk*(1000/p)**0.2857*np.exp(2.5e6*rs/(1004*Tk))
def run_case(run, lead, w):
    lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
    RH = get(run, lead, ub.FILES["RH"], w)[2]
    TK = T if np.nanmean(T) > 150 else T + 273.15
    Sms = S/ub.KT if uS.strip().lower() in ("kt", "knots", "knot") else S
    rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
    RHf = RH/100 if np.nanmax(RH) > 2 else RH
    TH = TK*(1000/P[:, None, None])**0.2857; THE = tez(TK, P[:, None, None])
    j = int(np.argmin(abs(lat - LA))); i = int(np.argmin(abs(lon - LO)))
    dom = np.ix_((lat >= 30) & (lat <= 42), (lon >= 128) & (lon <= 146))
    print(f"== {run} +{lead}h  GUSRO の格子 {lat[j]:.2f}N {lon[i]:.2f}E。真上 / 周り30km の最小 Ri")
    print("   層           湿度(下/上)  減率   VWS     乾N²     湿N²    Ri    湿りRi(90%) 湿りRi(95%)   ※N² は x1e-4 /s²、VWS kt/1000ft")
    area = []
    for k in range(len(P) - 1):
        a, b = k, k + 1
        if P[a] > 500 or P[b] < 200: continue
        Tm = (TK[a] + TK[b])/2; dz = 29.2712*Tm*np.log(P[a]/P[b])
        S2 = ((U[b] - U[a])**2 + (V[b] - V[a])**2)/dz**2; S2c = np.maximum(S2, 1e-10)
        N2 = G*(TH[b] - TH[a])/((TH[a] + TH[b])/2*dz); N2m = G*(np.log(THE[b]) - np.log(THE[a]))/dz
        Ri = N2/S2c; lr = (TK[a] - TK[b])/dz*1000
        R9 = np.where((RHf[a] >= .9) & (RHf[b] >= .9), N2m/S2c, Ri); R95 = np.where((RHf[a] >= .95) & (RHf[b] >= .95), N2m/S2c, Ri)
        fa, fb = fl_of(P[a]), fl_of(P[b])
        tag = "← 揺れた" if fb > 210 and fa < 262 else ("← 滑らか" if fa < 305 and fb > 295 else "")
        mn = lambda F: np.nanmin(F[max(0, j-3):j+4, max(0, i-3):i+4])
        c = lambda F: f"{F[j,i]:6.2f}/{mn(F):5.2f}"
        print(f"   FL{fa:03.0f}-{fb:03.0f}  {RHf[a,j,i]*100:3.0f}/{RHf[b,j,i]*100:3.0f}%  {lr[j,i]:4.1f}  {np.sqrt(S2[j,i])*1.94384*304.8:5.1f}  {N2[j,i]*1e4:6.2f}  {N2m[j,i]*1e4:6.2f}  "
              f"{c(Ri)}  {c(R9)}  {c(R95)}  {tag}")
        area.append((fa, fb, [100*(F[dom] < 1).mean() for F in (Ri, R9, R95)], [100*(F[dom] < .5).mean() for F in (Ri, R9, R95)]))
    print("   日本付近(30〜42N・128〜146E)で Ri<1 / Ri<0.5 の面積 % : 今の Ri, 湿りRi(90%), 湿りRi(95%)")
    for fa, fb, x, y in area:
        print(f"     FL{fa:03.0f}-{fb:03.0f}  <1: {x[0]:5.1f} {x[1]:5.1f} {x[2]:5.1f}   <0.5: {y[0]:5.1f} {y[1]:5.1f} {y[2]:5.1f}")
with tempfile.TemporaryDirectory() as w:
    for run, lead in (("20261114T0600Z", 3), ("20261114T0600Z", 6)):
        try: run_case(run, lead, w)
        except Exception as e: print("失敗", run, lead, repr(e))
