#!/usr/bin/env python3
# 診断: 11-08 10Z ごろの新千歳→伊丹(HIMMY〜KMC〜伊丹)の雲が 2 層に分かれていた理由を見るための UKMET の鉛直の分布
import json, os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main_tools"))
import ukmo_build as ub
PTS = {"HIMMY": (36.821, 136.902), "KMC": (36.396, 136.404), "MID": (35.6, 135.9), "ITM": (34.785, 135.438)}
out = {}
for run, lead in (("20261108T0600Z", 3), ("20261108T0600Z", 6)):
    w = tempfile.mkdtemp(); P = {}
    for k in ("T", "S", "D", "RH"):
        P[k] = os.path.join(w, k + ".nc"); ub.download(ub.key_of(run, lead, ub.FILES[k]), P[k])
    lat, lon, T, uT, _ = ub.cut(P["T"], True); _, _, S, _, _ = ub.cut(P["S"], True); _, _, D, _, _ = ub.cut(P["D"], True); _, _, RH, _, _ = ub.cut(P["RH"], True)
    Tc = T - 273.15 if np.nanmean(T) > 150 else T; S = S * ub.KT
    key = f"{run}+{lead}"; out[key] = {}
    for nm, (la, lo) in PTS.items():
        y = int(np.argmin(abs(lat - la))); x = int(np.argmin(abs(lon - lo)))
        rows = []
        for i, p in enumerate(ub.LEVELS_HPA):
            if p > 700 or p < 150: continue
            t = float(Tc[i, y, x]); rh = float(RH[i, y, x]); th = (t + 273.15) * (1000 / p) ** 0.2857
            es = 6.112 * np.exp(17.67 * t / (t + 243.5)); e = es * rh / 100; td = 243.5 * np.log(max(e, 1e-6) / 6.112) / (17.67 - np.log(max(e, 1e-6) / 6.112))
            rows.append({"p": p, "T": round(t, 1), "RH": round(rh), "Tdd": round(t - td, 1), "th": round(th, 1), "dir": round(float(D[i, y, x])), "kt": round(float(S[i, y, x]))})
        out[key][nm] = rows
    for p in P.values(): os.remove(p)
os.makedirs("out", exist_ok=True); json.dump(out, open("out/prof.json", "w"), indent=0)
print("ok")
