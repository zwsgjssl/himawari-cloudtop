#!/usr/bin/env python3
# 一回きりの確かめ(2026-10-20): 羽田〜千歳の 03Z(18Z の回の 9 時間予想)で、VWS の出し方の違いを比べる。結果はブランチ diag
import json, os, sys, tempfile
import numpy as np
from scipy import ndimage as nd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ukmo_build as ub
RUN, LEAD = "20261019T1800Z", 9
PTS = [(35.55, 139.78), (36.42, 139.94), (37.53, 140.13), (38.39, 140.36), (39.02, 140.56), (39.84, 140.83), (40.74, 140.97), (41.46, 141.06), (42.13, 141.53), (42.77, 141.69)]
w = tempfile.mkdtemp(); g = {}
for k in ("T", "S", "D"):
    p = os.path.join(w, k + ".nc"); ub.download(ub.key_of(RUN, LEAD, ub.FILES[k]), p); g[k] = ub.cut(p, True)
lat, lon, T, _, _ = g["T"]; S = g["S"][2] / 0.514444; D = g["D"][2]
rad = np.deg2rad(D); U, V = -S * np.sin(rad), -S * np.cos(rad)
P = np.array(ub.LEVELS_HPA, float); FL = 145366.45 * (1 - (P / 1013.25) ** 0.190284) / 100
# 経路の点を 10NM ごとに
route = []
for (a0, b0), (a1, b1) in zip(PTS, PTS[1:]):
    n = int(np.hypot(a1 - a0, (b1 - b0) * np.cos(np.radians(a0))) * 6) + 1
    route += [(a0 + (a1 - a0) * t / n, b0 + (b1 - b0) * t / n) for t in range(n)]
def sample(X):
    out = []
    for la, lo in route:
        i, j = int(round((la - lat[0]) / (lat[1] - lat[0]))), int(round((lo - lon[0]) / (lon[1] - lon[0])))
        out.append(X[:, i, j])
    return np.array(out)   # [点, 層]
def vws(Uu, Vv, step):
    o = np.full(Uu.shape, np.nan); o = o[:-step]
    return np.hypot(Uu[step:] - Uu[:-step], Vv[step:] - Vv[:-step]) / ((FL[step:] - FL[:-step]) / 10)[:, None, None]
res = {}
for name, sm, st in (("今(10km・隣の面)", 0, 1), ("10km・2 面おき", 0, 2), ("約 30km にならす・隣の面", 3, 1), ("約 30km・2 面おき", 3, 2), ("約 50km・2 面おき", 5, 2)):
    Uu, Vv = (nd.uniform_filter(U, (1, sm, sm)), nd.uniform_filter(V, (1, sm, sm))) if sm else (U, V)
    W = vws(Uu, Vv, st); mid = (FL[st:] + FL[:-st]) / 2; R = sample(W)
    rows = []
    for lo_, hi_ in ((0, 100), (100, 250), (250, 330), (330, 370), (370, 420)):
        sel = (mid >= lo_) & (mid < hi_)
        if not sel.any(): continue
        v = R[:, sel].ravel(); rows.append({"band": f"FL{lo_:03d}-{hi_:03d}", "max": round(float(np.nanmax(v)), 1), "p90": round(float(np.nanpercentile(v, 90)), 1), "ge6": round(float((v >= 6).mean() * 100)), "ge9": round(float((v >= 9).mean() * 100)), "ge12": round(float((v >= 12).mean() * 100))})
    res[name] = rows
os.makedirs("diag_out", exist_ok=True); json.dump(res, open("diag_out/vws_diag.json", "w"), ensure_ascii=False, indent=1); print(json.dumps(res, ensure_ascii=False)[:500])
