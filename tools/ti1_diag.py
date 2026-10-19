#!/usr/bin/env python3
# 一回きりの確かめ(2026-10-19): TI1 のシアーを「上下の面の差(今)」と「上・下の隣との差の大きい方(案)」で比べる。結果はブランチ diag
import datetime as dt, json, os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ukmo_build as ub
PTS = {"宇都宮 36.9N 140.0E": (36.9, 140.0), "郡山 37.5N 140.1E": (37.5, 140.1), "仙台の西 38.4N 140.4E": (38.4, 140.4), "花巻の手前 39.5N 140.7E": (39.5, 140.7)}
run = next(r for r in ub.list_runs(2) if ub.run_ready(r)); lead = 6
w = tempfile.mkdtemp(); g = {}
for k in ("T", "S", "D"):
    p = os.path.join(w, k + ".nc"); ub.download(ub.key_of(run, lead, ub.FILES[k]), p); g[k] = ub.cut(p, True)
lat, lon, T, uT, _ = g["T"]; S = g["S"][2]; D = g["D"][2]
Tc = T - 273.15 if np.nanmean(T) > 150 else T; Skt = S / 0.514444; rad = np.deg2rad(D)
U, V = -Skt * np.sin(rad), -Skt * np.cos(rad)
dl, dn = (lat[-1] - lat[0]) / (len(lat) - 1), (lon[-1] - lon[0]) / (len(lon) - 1)
u, v = U * 0.514444, V * 0.514444
p = np.array(ub.LEVELS_HPA, dtype="f8")[:, None, None]; TK = Tc + 273.15
dzl = 29.2712 * (TK[:-1] + TK[1:]) / 2 * np.log(p[:-1] / p[1:]); z = np.concatenate([np.zeros_like(TK[:1]), np.cumsum(dzl, axis=0)])
L = TK.shape[0]; lo = np.r_[0, np.arange(L - 1)]; hi = np.r_[np.arange(1, L), L - 1]
VC = np.hypot(u[hi] - u[lo], v[hi] - v[lo]) / (z[hi] - z[lo])
up = np.full_like(VC, np.nan); dn_ = np.full_like(VC, np.nan)
up[:-1] = np.hypot(u[1:] - u[:-1], v[1:] - v[:-1]) / dzl; dn_[1:] = np.hypot(u[1:] - u[:-1], v[1:] - v[:-1]) / dzl
VM = np.fmax(up, dn_)
R = ub.R_EARTH; dy = R * np.deg2rad(dl); dx = (R * np.cos(np.deg2rad(lat)) * np.deg2rad(dn))[None, :, None]
DEF = np.hypot(np.gradient(u, axis=2) / dx - np.gradient(v, axis=1) / dy, np.gradient(v, axis=2) / dx + np.gradient(u, axis=1) / dy)
A, B = VC * DEF * 1e7, VM * DEF * 1e7
FL = np.array([145366.45 * (1 - (P / 1013.25) ** 0.190284) / 100 for P in ub.LEVELS_HPA])
mid = (FL >= 250) & (FL <= 450)
out = {"run": run, "lead": lead, "levels": [], "pct_now": {}, "pct_new": {}, "pts": {}}
for q in (90, 95, 98, 99, 99.5): out["pct_now"][q] = round(float(np.nanpercentile(A[mid], q)), 1); out["pct_new"][q] = round(float(np.nanpercentile(B[mid], q)), 1)
for name, (la, lo_) in PTS.items():
    i, j = int(np.argmin(abs(lat - la))), int(np.argmin(abs(lon - lo_))); rows = []
    for k in range(L):
        if 250 <= FL[k] <= 450: rows.append([int(round(FL[k])), int(round(float(np.hypot(U[k, i, j], V[k, i, j])))), round(float(VC[k, i, j]) * 1000 / 3.28084 * 1.94384, 1), round(float(VM[k, i, j]) * 1000 / 3.28084 * 1.94384, 1), round(float(A[k, i, j]), 1), round(float(B[k, i, j]), 1)])
    out["pts"][name] = rows
os.makedirs("diag_out", exist_ok=True); json.dump(out, open("diag_out/ti1_diag.json", "w"), ensure_ascii=False, indent=1); print(json.dumps(out["pct_now"]), json.dumps(out["pct_new"]))
