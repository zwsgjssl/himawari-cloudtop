# 診断: Ri の塗りのしきい値を 1/0.5/0.25 から 0.75/0.5/0.25 にしたら、2026-11-14 の羽田→福岡(直線)と日本付近でどう変わるか。
#   体験: FL210〜260(GUSRO 付近)で LGT(LP 寄り)、FL300 に上がってからは福岡までほぼ揺れなし
import os, sys, tempfile, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
G = 9.81; P = np.array(ub.LEVELS_HPA, float)
A0, B0 = (35.553, 139.781), (33.586, 130.451)   # 羽田・福岡
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
def get(run, lead, name, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, True)
TH_ = (1, .75, .5, .25)
def run_case(run, lead, w):
    lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
    TK = T if np.nanmean(T) > 150 else T + 273.15
    Sms = S/ub.KT if uS.strip().lower() in ("kt", "knots", "knot") else S
    rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
    TH = TK*(1000/P[:, None, None])**0.2857
    dom = np.ix_((lat >= 30) & (lat <= 42), (lon >= 128) & (lon <= 146))
    n = 121; f = np.linspace(0, 1, n); la = A0[0] + (B0[0] - A0[0])*f; lo = A0[1] + (B0[1] - A0[1])*f
    dist = 2*6371*np.arcsin(np.sqrt(np.sin(np.deg2rad(B0[0]-A0[0])/2)**2 + np.cos(np.deg2rad(A0[0]))*np.cos(np.deg2rad(B0[0]))*np.sin(np.deg2rad(B0[1]-A0[1])/2)**2))/1.852
    jj = np.array([int(np.argmin(abs(lat - x))) for x in la]); ii = np.array([int(np.argmin(abs(lon - x))) for x in lo])
    print(f"== {run} +{lead}h  直線 {dist:.0f}NM。塗られる長さ NM(Ri≦1 / ≦0.75 / ≦0.5 / ≦0.25)と、日本付近の面積 %、直線上の VWS 平均(塗られた所)")
    for k in range(len(P) - 1):
        a, b = k, k + 1
        if P[a] > 500 or P[b] < 200: continue
        dz = 29.2712*(TK[a] + TK[b])/2*np.log(P[a]/P[b])
        S2 = ((U[b] - U[a])**2 + (V[b] - V[a])**2)/dz**2; N2 = G*(TH[b] - TH[a])/((TH[a] + TH[b])/2*dz)
        Ri = np.where(N2 <= 0, 0, N2/np.maximum(S2, 1e-10)); vws = np.sqrt(S2)*1.94384*304.8
        r = Ri[jj, ii]; v = vws[jj, ii]
        L = [dist*(r <= t).mean() for t in TH_]; Ar = [100*(Ri[dom] <= t).mean() for t in TH_]
        vm = [np.mean(v[r <= t]) if (r <= t).any() else float("nan") for t in TH_]
        seg = lambda t: ",".join(f"{dist*f[s]:.0f}-{dist*f[e]:.0f}" for s, e in runs(r <= t))
        print(f"  FL{fl_of(P[a]):03.0f}-{fl_of(P[b]):03.0f}  直線 {L[0]:4.0f}/{L[1]:4.0f}/{L[2]:4.0f}/{L[3]:4.0f}NM  面積 {Ar[0]:4.1f}/{Ar[1]:4.1f}/{Ar[2]:4.1f}/{Ar[3]:4.1f}%  VWS {vm[0]:4.1f}/{vm[1]:4.1f}/{vm[2]:4.1f}  ≦0.75 の所 NM: {seg(.75)}")
def runs(m):
    out = []; s = None
    for x, y in enumerate(m):
        if y and s is None: s = x
        if not y and s is not None: out.append((s, x - 1)); s = None
    if s is not None: out.append((s, len(m) - 1))
    return out
with tempfile.TemporaryDirectory() as w:
    for run, lead in (("20261114T0600Z", 3), ("20261114T0600Z", 6)):
        try: run_case(run, lead, w)
        except Exception as e: print("失敗", run, lead, repr(e))
