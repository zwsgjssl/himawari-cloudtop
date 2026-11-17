# 診断: 2026-11-17 昼(日本時間)福岡→羽田の直近の便、降下中 FL210〜150 で雲の中 LP。断面図には雲が出ていない。
#   UKMET の湿度(水・氷に対する値)・気温・安定度・シアーを、羽田の西 190NM〜羽田の直線上で。00Z と 03Z
import os, sys, tempfile, datetime as dt, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
G = 9.81; P = np.array(ub.LEVELS_HPA, float)
A0, B0 = (33.586, 130.451), (35.553, 139.781)
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
def get(run, lead, name, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, True)
runs = [r for r in ub.list_runs(2) if ub.run_ready(r)]
print("回", runs[:3])
cases = []
for want in ("20261117T0000Z", "20261117T0300Z"):
    t = dt.datetime.strptime(want, "%Y%m%dT%H%MZ")
    for r in runs:
        t0 = dt.datetime.strptime(r, "%Y%m%dT%H%MZ"); L = int((t - t0).total_seconds()//3600)
        if L in ub.LEADS: cases.append((r, L, want)); break
with tempfile.TemporaryDirectory() as w:
  for run, lead, want in cases:
    lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
    RH = np.asarray(get(run, lead, ub.FILES["RH"], w)[2], "f8")
    TK = T if np.nanmean(T) > 150 else T + 273.15; Tc = TK - 273.15
    RHw = RH*100 if np.nanmax(RH) <= 1.5 else RH
    rhb, kind = ub.rh_bytes(RHw, Tc, lead); RHi = np.frombuffer(rhb, "u1").reshape(Tc.shape).astype(float)
    Skt = S if uS.strip().lower() in ("kt", "knots", "knot") else S*1.94384
    Sms = Skt/1.94384; rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
    TH = TK*(1000/P[:, None, None])**0.2857
    print(f"\n==== {want}  ({run} +{lead}h)  湿度の元は {kind}(表は 元の値 / 氷に直した値)")
    for f in np.linspace(0.6, 1.0, 9):
        la = A0[0] + (B0[0]-A0[0])*f; lo = A0[1] + (B0[1]-A0[1])*f
        y = int(np.argmin(abs(lat - la))); x = int(np.argmin(abs(lon - lo)))
        nm = (1 - f)*480
        row = [f"FL{fl_of(P[k]):03.0f} {Tc[k,y,x]:5.1f}℃ {RHw[k,y,x]:3.0f}/{RHi[k,y,x]:3.0f}%" for k in range(len(P)) if 400 <= P[k] <= 700]
        print(f"-- 羽田の西 {nm:3.0f}NM {la:.2f}N {lo:.2f}E")
        print("   " + " | ".join(row))
        for k in range(len(P) - 1):
            if not (450 <= P[k] <= 650): continue
            a, b = k, k+1; dz = 29.2712*(TK[a,y,x]+TK[b,y,x])/2*np.log(P[a]/P[b])
            S2 = ((U[b,y,x]-U[a,y,x])**2 + (V[b,y,x]-V[a,y,x])**2)/dz**2; N2 = G*(TH[b,y,x]-TH[a,y,x])/((TH[a,y,x]+TH[b,y,x])/2*dz)
            print(f"   FL{fl_of(P[a]):03.0f}-{fl_of(P[b]):03.0f} 減率 {-(TK[b,y,x]-TK[a,y,x])/dz*1000:4.1f}K/km VWS {np.sqrt(S2)*1.94384*304.8:4.1f} Ri {N2/max(S2,1e-10):6.2f} 風 {D[a,y,x]:3.0f}/{Skt[a,y,x]:3.0f}kt")
