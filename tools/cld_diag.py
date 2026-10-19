#!/usr/bin/env python3
# 一回きりの確かめ(2026-10-19 ユーザー「羽田千歳の断面図、赤外では雲が多いのに断面図は下層しか雲が無い」):
#   UKMET の湿度(気圧面)と雲量のファイルを、羽田〜千歳の直線上の数点で書き出す。結果はブランチ diag の out/ に
import datetime as dt, json, os, re, sys, tempfile
import numpy as np, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ukmo_build as ub
A, B = (35.55, 139.78), (42.78, 141.69)
PTS = [(A[0] + (B[0]-A[0])*f, A[1] + (B[1]-A[1])*f) for f in np.linspace(0, 1, 8)]
out = {"pts": PTS}
runs = ub.list_runs(2); run = next(r for r in runs if ub.run_ready(r)); out["run"] = run
lead = 3
pre = f"{ub.PREFIX}/{run}/"
valid = (dt.datetime.strptime(run, "%Y%m%dT%H%MZ") + dt.timedelta(hours=lead)).strftime("%Y%m%dT%H%MZ")
r = requests.get(ub.S3 + "/", params={"list-type": "2", "prefix": f"{pre}{valid}-PT{lead:04d}H00M-"}, headers=ub.UA, timeout=60)
names = sorted(set(re.findall(r"PT\d{4}H00M-([^<]+)\.nc</Key>", r.text))); out["files"] = names
w = tempfile.mkdtemp(); got = {}
for k, n in (("T", "temperature_on_pressure_levels"), ("RH", "relative_humidity_on_pressure_levels")):
    p = os.path.join(w, k + ".nc"); ub.download(ub.key_of(run, lead, n), p); got[k] = ub.cut(p, True)
single = [n for n in names if n.startswith("cloud_amount") and "height_levels" not in n] + [n for n in names if "cloud_base" in n or "cloud_top" in n]
sg = {}
for n in single:
    try: p = os.path.join(w, n + ".nc"); ub.download(ub.key_of(run, lead, n), p); sg[n] = ub.cut(p, False)
    except Exception as e: sg[n] = str(e)
lat, lon, T, uT, _ = got["T"]; _, _, RH, uR, _ = got["RH"]
Tc = T - 273.15 if np.nanmean(T) > 150 else T
out["rh_units"] = uR; out["rh_max"] = float(np.nanmax(RH))
cold = Tc < -40; out["rh_p999_below_-40"] = float(np.nanpercentile(RH[cold] * (100 if np.nanmax(RH) <= 1.5 else 1), 99.9))
rhb, mode = ub.rh_bytes(RH.copy(), Tc, lead); out["mode"] = mode
R2 = np.frombuffer(rhb, dtype="u1").reshape(Tc.shape)
rows = []
for la, lo in PTS:
    i, j = int(np.argmin(np.abs(lat - la))), int(np.argmin(np.abs(lon - lo)))
    rr = {"lat": round(la, 2), "lon": round(lo, 2), "lv": []}
    for L, P in enumerate(ub.LEVELS_HPA):
        rr["lv"].append([P, round(float(Tc[L, i, j]), 1), round(float(RH[L, i, j] * (100 if np.nanmax(RH) <= 1.5 else 1)), 1), int(R2[L, i, j])])
    for n, v in sg.items(): rr[n] = v if isinstance(v, str) else round(float(v[2][i, j]), 3)
    rows.append(rr)
out["rows"] = rows
os.makedirs("diag_out", exist_ok=True); json.dump(out, open("diag_out/cld_diag.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ("run", "rh_units", "rh_max", "rh_p999_below_-40", "mode")}))
