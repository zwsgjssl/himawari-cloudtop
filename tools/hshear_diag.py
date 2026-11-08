#!/usr/bin/env python3
# 診断: UKMET の横シアー(流れを横切る向きの風速の変わり方、kt/60NM)が 20kt/60NM 以上の所がどれくらいあるか(2026-11-08 ユーザーの問い)
import datetime as dt, json, os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main_tools"))
import ukmo_build as ub
from PIL import Image, ImageDraw
LV = {"FL300": 300, "FL340": 250, "FL390": 200}
now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
run = next(r for r in ub.list_runs(2) if ub.run_ready(r))
r0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ")
lead = min(ub.LEADS, key=lambda h: abs((r0 + dt.timedelta(hours=h) - now).total_seconds()))
ub.log("回", run, "予報", lead)
w = tempfile.mkdtemp(); P = {}
for k in ("S", "D"):
    P[k] = os.path.join(w, k + ".nc"); ub.download(ub.key_of(run, lead, ub.FILES[k]), P[k])
lat, lon, S, uS, _ = ub.cut(P["S"], True); _, _, D, _, _ = ub.cut(P["D"], True)
S = S * ub.KT; rad = np.deg2rad(D); U, V = -S*np.sin(rad), -S*np.cos(rad)
dlat = lat[1] - lat[0]; dlon = lon[1] - lon[0]
dy = dlat * 60.0; dx = dlon * 60.0 * np.cos(np.deg2rad(lat))[:, None]
out = {"run": run, "lead": lead, "valid": (r0 + dt.timedelta(hours=lead)).strftime("%Y-%m-%dT%H:%MZ"), "grid_nm": [float(dy), float(dx.mean())], "levels": {}}
coast = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main_tools", "coast_sat.json")))["rings"]
dom = (lat[:, None] >= 24) & (lat[:, None] <= 46) & (lon[None, :] >= 122) & (lon[None, :] <= 148)
for name, hp in LV.items():
    k = ub.LEVELS_HPA.index(hp); u, v, s = U[k], V[k], S[k]
    # 60NM あたり: 勾配(kt/NM)× 60
    dsdy, dsdx = np.gradient(s, axis=0) / dy, np.gradient(s, axis=1) / dx
    nx_, ny_ = -v / np.maximum(s, 1), u / np.maximum(s, 1)          # 流れの左向きの単位ベクトル
    hs = np.abs(dsdx * nx_ + dsdy * ny_) * 60                          # 横シアー kt/60NM
    dudx, dudy = np.gradient(u, axis=1) / dx, np.gradient(u, axis=0) / dy
    dvdx, dvdy = np.gradient(v, axis=1) / dx, np.gradient(v, axis=0) / dy
    DEF = np.hypot(dudx - dvdy, dvdx + dudy) * 60                      # 変形(TI1 の横の部分)kt/60NM
    # 約 30NM でならす(10km の格子の細かいばらつきを除く)
    def sm(a, n=2):
        b = a.copy()
        for _ in range(n): b = (b + np.roll(b, 1, 0) + np.roll(b, -1, 0) + np.roll(b, 1, 1) + np.roll(b, -1, 1)) / 5
        return b
    hs_s, def_s = sm(hs), sm(DEF)
    st = {}
    for nm, a in (("hs", hs), ("hs_smooth", hs_s), ("def_smooth", def_s)):
        q = a[dom]
        st[nm] = {"p50": round(float(np.percentile(q, 50)), 1), "p90": round(float(np.percentile(q, 90)), 1), "p99": round(float(np.percentile(q, 99)), 1),
                  "ge20": round(float((q >= 20).mean() * 100), 1), "ge30": round(float((q >= 30).mean() * 100), 1), "ge40": round(float((q >= 40).mean() * 100), 1)}
    st["maxwind"] = round(float(s[dom].max()))
    out["levels"][name] = st
    # 0.25° に間引いた値(経路の上の割合を手元で数える用)
    step = max(1, int(round(0.25 / dlat)))
    out["levels"][name]["grid"] = {"lat0": float(lat[0]), "lon0": float(lon[0]), "d": float(dlat * step),
        "hs": np.round(hs_s[::step, ::step]).astype(int).tolist(), "spd": np.round(s[::step, ::step]).astype(int).tolist()}
    # 絵: 風速(灰色)+ 横シアー 20/30/40 を緑・黄・橙
    H, W = s.shape; img = np.zeros((H, W, 3), "u1")
    g = np.clip(s / 180 * 200, 0, 200).astype("u1"); img[...] = g[..., None]
    for th, col in ((20, (60, 200, 60)), (30, (240, 220, 0)), (40, (255, 120, 0))): img[hs_s >= th] = col
    im = Image.fromarray(img[::-1]); dr = ImageDraw.Draw(im)
    xy = lambda lo, la: ((lo - lon[0]) / dlon, (lat[-1] - la) / dlat)
    for rg in coast: dr.line([xy(a, b) for a, b in rg], fill=(80, 160, 255), width=1)
    dr.text((5, 5), f"UKMET {run} +{lead}h {name}  lateral shear kt/60NM (smoothed ~30NM): green>=20 yellow>=30 orange>=40, gray=wind speed", fill=(255, 255, 255))
    os.makedirs("out", exist_ok=True); im.save(f"out/hs_{name}.png")
    ub.log(name, json.dumps({k: v for k, v in st.items() if k != "grid"}))
json.dump(out, open("out/hs.json", "w"))
