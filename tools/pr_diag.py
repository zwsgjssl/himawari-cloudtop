# 診断: 2026-11-14 の羽田→福岡の直線の断面で、前線の強まり(水平、気圧面ごと)が強かった所。09Z・12Z(06Z の回)
import matplotlib as _m; _m.rcParams["font.family"] = ["Noto Sans CJK JP", "DejaVu Sans"]
#   色 = 同じ気圧面の日本付近(30〜42N・128〜146E)の中での順位(上位何 %)。参考に VWS 6 kt/1000ft の線
import os, sys, math, tempfile, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
A0, B0 = (35.5523, 139.7797), (33.5859, 130.4511); R = 6371e3; P = np.array(ub.LEVELS_HPA, float)
fl = (1 - (P/1013.25)**0.190284)*145366.45/100
def gc(a, b, n):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b)); d = 2*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2)); out = []
    for k in range(n):
        f = k/(n-1); A = math.sin((1-f)*d)/math.sin(d); B = math.sin(f*d)/math.sin(d)
        x = A*math.cos(la1)*math.cos(lo1) + B*math.cos(la2)*math.cos(lo2); y = A*math.cos(la1)*math.sin(lo1) + B*math.cos(la2)*math.sin(lo2); z = A*math.sin(la1) + B*math.sin(la2)
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return out, d*R/1852
pts, dist = gc(A0, B0, 160); X = np.linspace(0, dist, len(pts))
fig, axs = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
with tempfile.TemporaryDirectory() as w:
    for ax, lead in zip(axs, (3, 6)):
        A = {}
        for k in ("T", "S", "D"):
            p = os.path.join(w, k); ub.download(ub.key_of("20261114T0600Z", lead, ub.FILES[k]), p); A[k] = ub.cut(p, True)
        lat, lon, T = A["T"][0], A["T"][1], A["T"][2]; S, uS = A["S"][2], A["S"][3]; D = A["D"][2]
        TK = T if np.nanmean(T) > 150 else T + 273.15; Sms = S/ub.KT if uS.strip().lower() in ("kt", "knots", "knot") else S
        rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
        dlat = np.deg2rad(abs(lat[1]-lat[0])); dlon = np.deg2rad(abs(lon[1]-lon[0])); sgn = 1 if lat[1] > lat[0] else -1; cl = np.cos(np.deg2rad(lat))[None, :, None]
        ddx = lambda F: np.gradient(F, axis=2)/(R*cl*dlon); ddy = lambda F: sgn*np.gradient(F, axis=1)/(R*dlat)
        TH = TK*(1000/P[:, None, None])**0.2857; tx, ty = ddx(TH), ddy(TH); ux, uy, vx, vy = ddx(U), ddy(U), ddx(V), ddy(V)
        FG = -(tx*tx*ux + tx*ty*(vx + uy) + ty*ty*vy)/(np.hypot(tx, ty) + 1e-12)*1e10
        dom = (lat >= 30) & (lat <= 42); dlo = (lon >= 128) & (lon <= 146)
        PCT = np.zeros_like(FG)
        for k in range(len(P)):
            a = np.sort(FG[k][np.ix_(dom, dlo)].ravel()); PCT[k] = 100*(1 - np.searchsorted(a, FG[k])/len(a))   # 上位何 %
        js = [int(np.argmin(abs(lat - la))) for la, lo in pts]; is_ = [int(np.argmin(abs(lon - lo))) for la, lo in pts]
        sec = np.array([[PCT[k, j, i] for j, i in zip(js, is_)] for k in range(len(P))])
        vws = np.full((len(P)-1, len(pts)), np.nan)
        for n, (j, i) in enumerate(zip(js, is_)):
            dz = 29.2712*(TK[:-1, j, i] + TK[1:, j, i])/2*np.log(P[:-1]/P[1:])
            vws[:, n] = np.hypot(U[1:, j, i] - U[:-1, j, i], V[1:, j, i] - V[:-1, j, i])/dz*1.94384*304.8
        m = (fl >= 150) & (fl <= 450); flm = (fl[:-1] + fl[1:])/2; mm = (flm >= 150) & (flm <= 450)
        cf = ax.contourf(X, fl[m], sec[m], levels=[0, 2, 5, 10, 20, 100], colors=["#b00020", "#ff6d00", "#ffd54f", "#fff8e1", "#ffffff"])
        ax.contour(X, flm[mm], vws[mm], levels=[6], colors=["#1b5e20"], linewidths=1.2)
        for f_ in fl[m]: ax.axhline(f_, color="k", lw=.25, ls=":")
        ax.axvspan(0, 25, color="#1565c0", alpha=.08); ax.text(3, 440, "GUSRO 付近", fontsize=8)
        ax.set_title(f"{'09' if lead == 3 else '12'}Z: 前線の強まりの順位(赤 = 上位 2%、橙 = 5%、黄 = 10%)、緑線 = VWS 6", fontsize=10); ax.set_ylabel("FL")
        print(f"== {'09' if lead == 3 else '12'}Z  上位 5% 以内の所(距離 NM: FL)")
        for k in range(len(P)):
            if not (180 <= fl[k] <= 420): continue
            hit = X[sec[k] <= 5]
            if len(hit): 
                segs = []; s0 = hit[0]; pv = hit[0]
                for x in hit[1:]:
                    if x - pv > 8: segs.append((s0, pv)); s0 = x
                    pv = x
                segs.append((s0, pv)); print(f"  FL{fl[k]:03.0f}: " + ", ".join(f"{a:.0f}-{b:.0f}NM" for a, b in segs))
axs[-1].set_xlabel("羽田からの距離 NM(福岡まで直線)"); fig.tight_layout(); os.makedirs("out", exist_ok=True); fig.savefig("out/fg.png", dpi=80)
