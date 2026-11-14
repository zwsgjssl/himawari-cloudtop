# 診断: 断面図の VWS の出し方の違い(RJTT→RJFF の直線、UKMET 00Z の回の 12Z)。
#   A = 今の Map(隣り合う 2 面の間の層ごと、層の真ん中に置く)
#   B = 各気圧面で上下 2 層にまたがる差(面に置く、v222 より前の Map)
#   C = 各気圧面で上・下の層の大きい方(面に置く、TI1 と同じ)
import os, sys, math, tempfile, datetime as dt, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
A0, B0 = (35.5523, 139.7797), (33.5859, 130.4511)
def gc(a, b, n):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b)); d = 2*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2)); out = []
    for k in range(n):
        f = k/(n-1); A = math.sin((1-f)*d)/math.sin(d); B = math.sin(f*d)/math.sin(d)
        x = A*math.cos(la1)*math.cos(lo1) + B*math.cos(la2)*math.cos(lo2); y = A*math.cos(la1)*math.sin(lo1) + B*math.cos(la2)*math.sin(lo2); z = A*math.sin(la1) + B*math.sin(la2)
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return out
run = "20261114T0000Z"; lead = 12; P = np.array(ub.LEVELS_HPA, float)
with tempfile.TemporaryDirectory() as w:
    A = {}
    for k in ("T", "S", "D"):
        p = os.path.join(w, k); ub.download(ub.key_of(run, lead, ub.FILES[k]), p); A[k] = ub.cut(p, True)
lat, lon, T, uT, _ = A["T"]; S, uS = A["S"][2], A["S"][3]; D = A["D"][2]
Tc = T - 273.15 if np.nanmean(T) > 150 else T; Skt = S*ub.KT if uS.strip().lower() not in ("kt", "knots", "knot") else S
rad = np.deg2rad(D); U, V = -Skt*np.sin(rad), -Skt*np.cos(rad)
pts = gc(A0, B0, 120); X = np.arange(len(pts)); fl = (1 - (P/1013.25)**0.190284)*145366.45/100
def col(la, lo):
    j = int(np.argmin(abs(lat - la))); i = int(np.argmin(abs(lon - lo))); return Tc[:, j, i] + 273.15, U[:, j, i], V[:, j, i]
Lay = np.full((len(P)-1, len(pts)), np.nan); Bc = np.full((len(P), len(pts)), np.nan); Cm = np.full((len(P), len(pts)), np.nan)
for n, (la, lo) in enumerate(pts):
    TK, u, v = col(la, lo); dz = 29.2712*(TK[:-1] + TK[1:])/2*np.log(P[:-1]/P[1:])/0.3048/1000   # 1000ft
    sh = np.hypot(u[1:] - u[:-1], v[1:] - v[:-1])/dz; Lay[:, n] = sh
    for k in range(1, len(P)-1): Bc[k, n] = math.hypot(u[k+1] - u[k-1], v[k+1] - v[k-1])/(dz[k-1] + dz[k]); Cm[k, n] = max(sh[k-1], sh[k])
flm = (fl[:-1] + fl[1:])/2
fig, ax = plt.subplots(1, 3, figsize=(18, 6), sharey=True)
for a, (Z, Y, nm) in zip(ax, ((Lay, flm, "A 今の Map: 層ごと(層の真ん中)"), (Bc, fl, "B 面で上下 2 層の差(v222 より前)"), (Cm, fl, "C 面で上・下の層の大きい方"))):
    m = (Y >= 150) & (Y <= 460)
    a.contourf(X, Y[m], Z[m], levels=[6, 9, 12, 99], colors=["#2e7d32", "#c9a400", "#e65100"], alpha=.45)
    cs = a.contour(X, Y[m], Z[m], levels=[6, 9, 12], colors=["#7bed2a", "#ffd400", "#ff7a00"], linewidths=1.4); a.clabel(cs, fmt="%d", fontsize=7)
    a.set_title(nm, fontsize=10); a.set_xlabel("RJTT → RJFF(直線)"); a.grid(alpha=.3)
    for f in fl[(fl >= 150) & (fl <= 460)]: a.axhline(f, color="k", lw=.3, ls=":")
ax[0].set_ylabel("FL"); fig.suptitle("UKMET 00Z の回 12:00Z の VWS kt/1000ft(点線 = UKMET の気圧面)"); fig.tight_layout()
os.makedirs("out", exist_ok=True); fig.savefig("out/vws.png", dpi=80)
print("面の FL", [round(f) for f in fl])
